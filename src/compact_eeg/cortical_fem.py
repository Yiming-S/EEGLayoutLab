"""Fixed-mesh SimNIBS FEM evaluation of arbitrary external point electrodes.

This module reuses the official assembler, MUMPS solver, GM patch-recovery
interpolation and tetrahedron gradient operator. It does not implement another
FEM solver. Source/interpolation QA is descriptive and is never an automatic
claim of anatomical qualification, performance, or AR.

All mesh/electrode/source coordinates are millimetres. Returned normal EEG
leadfields are gauge-referenced and have units V/(A*m). Apply each layout's
own reference contrast outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import time
from typing import Callable

import numpy as np
from scipy import sparse
from scipy.spatial import cKDTree


@contextmanager
def preserved_numpy_search_seed(seed):
    """Make an official stochastic tetrahedron search repeatable and restore RNG.

    SimNIBS 4.6's Cython walk uses np.random.shuffle. Callers must not run
    different constructors concurrently in threads sharing this global RNG;
    isolated worker processes are appropriate for independent head models.
    """
    state = np.random.get_state()
    np.random.seed(seed)
    try:
        yield
    finally:
        np.random.set_state(state)


def _finite_array(value, name, ndim=None):
    array = np.asarray(value, dtype=np.float64)
    if ndim is not None and array.ndim != ndim:
        raise ValueError(f"{name} must have {ndim} dimensions")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} contains non-finite values")
    return array


def point_sampling_matrix(node_count, node_rows, barycentric_weights):
    """K x N continuous point-potential interpolation, with zero-based rows."""
    rows = np.asarray(node_rows, dtype=np.int64)
    weights = _finite_array(barycentric_weights, "barycentric weights", 2)
    if rows.ndim != 2 or rows.shape != weights.shape or rows.shape[1] != 3:
        raise ValueError("node rows and weights must both have shape (K,3)")
    if rows.size == 0 or rows.min() < 0 or rows.max() >= node_count:
        raise ValueError("point references outside volume mesh, or empty points")
    if np.any(weights < -1e-10) or np.any(weights > 1 + 1e-10):
        raise ValueError("point barycentric weights must lie within their triangle")
    if not np.allclose(weights.sum(axis=1), 1, rtol=0, atol=1e-10):
        raise ValueError("point barycentric weights must sum to one")
    matrix = sparse.csr_matrix(
        (weights.reshape(-1), (np.repeat(np.arange(len(rows)), 3), rows.reshape(-1))),
        shape=(len(rows), node_count),
    )
    matrix.sum_duplicates()
    matrix.eliminate_zeros()
    return matrix


def balanced_sampling_rhs(sampling, gauge_row, current_amperes=1.0):
    """N x K loads for weighted point electrodes against one pure gauge node."""
    sampling = sparse.csr_matrix(sampling)
    if not 0 <= gauge_row < sampling.shape[1]:
        raise ValueError("gauge row outside matrix")
    if not np.isfinite(current_amperes) or current_amperes <= 0:
        raise ValueError("normalization current must be positive and finite")
    if not np.allclose(np.asarray(sampling.sum(axis=1)).ravel(), 1, atol=1e-10, rtol=0):
        raise ValueError("sampling rows must conserve total point current")
    rhs = sampling.T.toarray() * current_amperes
    rhs[gauge_row] -= current_amperes
    return rhs


def compose_normal_operator(interpolation, gradients_per_mm, tetrahedron_node_rows, normals, node_count):
    """Build +1000 sum_c diag(n_c) M D_c, the negative of E/I by reciprocity.

    M's columns and G's elements must be in exactly the same order. Unlike
    point-electrode weights, official patch-recovery interpolation weights
    may be negative and are not clipped or renormalized here.
    """
    m = sparse.csr_matrix(interpolation)
    g = _finite_array(gradients_per_mm, "gradients", 3)
    rows = np.asarray(tetrahedron_node_rows, dtype=np.int64)
    n = _finite_array(normals, "normals", 2)
    if g.shape != (m.shape[1], 4, 3) or rows.shape != (m.shape[1], 4):
        raise ValueError("GM interpolation columns and tetrahedron gradients are misaligned")
    if n.shape != (m.shape[0], 3) or not np.allclose(np.linalg.norm(n, axis=1), 1, rtol=0, atol=1e-6):
        raise ValueError("one unit normal per interpolation row is required")
    if not np.all(np.isfinite(m.data)) or rows.min() < 0 or rows.max() >= node_count:
        raise ValueError("non-finite interpolation or invalid node rows")
    operator = sparse.csr_matrix((m.shape[0], node_count))
    row_ids = np.repeat(np.arange(m.shape[1]), 4)
    for component in range(3):
        derivative = sparse.csr_matrix(
            (g[:, :, component].reshape(-1), (row_ids, rows.reshape(-1))),
            shape=(m.shape[1], node_count),
        )
        operator += m.multiply(n[:, component, None]) @ derivative
    operator *= 1000.0
    operator.sum_duplicates()
    operator.eliminate_zeros()
    return operator.tocsr()


@dataclass(frozen=True)
class ElectrodeProjection:
    requested_mm: np.ndarray
    projected_mm: np.ndarray
    triangle_ids: np.ndarray
    barycentric_weights: np.ndarray
    node_rows: np.ndarray
    distances_mm: np.ndarray
    matrix: sparse.csr_matrix


class FixedMeshLeadfield:
    """One source operator and at most one factorization for many layouts.

    Parameters follow original SimNIBS node numbering: ``gauge_node`` is
    one-based; external-to-volume mapping and triangle indices are zero-based.
    The constructor qualifies source interpolation and builds the sparse
    source operator. ``prepare_solver``/the first ``evaluate`` assembles and
    factorizes the system lazily, allowing callers to inspect source QA first.
    The caller must enforce thread limits before importing native libraries.
    """

    def __init__(
        self, mesh, conductivity, external_vertices_mm, external_triangles,
        external_to_volume_node_rows, source_xyz_mm, source_normals,
        *, gauge_node=122743, solver="mumps", source_search_seed=20260908, progress: Callable | None = None,
    ):
        import simnibs
        from simnibs.mesh_tools import mesh_io
        from simnibs.simulation import fem

        self.mesh, self._mesh_io, self._fem = mesh, mesh_io, fem
        self.conductivity = _finite_array(conductivity, "conductivity", 1)
        self.external_vertices_mm = _finite_array(external_vertices_mm, "external vertices", 2)
        self.external_triangles = np.asarray(external_triangles, dtype=np.int64)
        self.external_node_rows = np.asarray(external_to_volume_node_rows, dtype=np.int64)
        self.source_xyz_mm = _finite_array(source_xyz_mm, "source coordinates", 2)
        self.source_normals = _finite_array(source_normals, "source normals", 2)
        self.gauge_node = int(gauge_node)
        self.gauge_row = self.gauge_node - 1
        self.solver = solver
        self.source_search_seed = int(source_search_seed)
        self.simnibs_version = simnibs.__version__
        self.system = None
        self.timings = {}
        self.progress = progress or (lambda *_args, **_kwargs: None)
        if solver != "mumps":
            raise ValueError("initial qualified implementation is frozen to MUMPS")
        if self.conductivity.shape != (mesh.elm.nr,) or np.any(self.conductivity[mesh.elm.get_tetrahedra()] <= 0):
            raise ValueError("positive conductivity is required for every volume element")
        if not np.array_equal(mesh.nodes.node_number, np.arange(1, mesh.nodes.nr + 1)):
            raise ValueError("requires original consecutive SimNIBS node numbering")
        if not 0 <= self.gauge_row < mesh.nodes.nr:
            raise ValueError("gauge node outside mesh")
        if self.external_vertices_mm.shape != (len(self.external_node_rows), 3):
            raise ValueError("external coordinates and node mapping dimensions differ")
        if len(np.unique(self.external_node_rows)) != len(self.external_node_rows):
            raise ValueError("external-to-volume node mapping is not injective")
        if self.external_node_rows.min() < 0 or self.external_node_rows.max() >= mesh.nodes.nr:
            raise ValueError("external surface node mapping outside volume mesh")
        if not np.allclose(self.external_vertices_mm, mesh.nodes.node_coord[self.external_node_rows], rtol=0, atol=1e-7):
            raise ValueError("external surface and volume mesh coordinates disagree")
        if self.external_triangles.ndim != 2 or self.external_triangles.shape[1] != 3 or self.external_triangles.min() < 0 or self.external_triangles.max() >= len(self.external_node_rows):
            raise ValueError("invalid external surface triangles")
        if self.source_xyz_mm.shape != self.source_normals.shape or self.source_xyz_mm.shape[1] != 3 or len(self.source_xyz_mm) == 0:
            raise ValueError("source coordinates/normals must both have nonempty shape (Ns,3)")
        if not np.allclose(np.linalg.norm(self.source_normals, axis=1), 1, rtol=0, atol=1e-6):
            raise ValueError("source normals must already be normalized")
        self._build_source_operator()

    def _build_source_operator(self):
        timer = time.perf_counter()
        self.progress("cortical_interpolation_qa_start")
        # Exactly the official TDCSLEADFIELD GM + WM/CSF convex-fill approach.
        roi = self.mesh.crop_mesh(tags=[1, 2, 3])
        gm_roi_ids = roi.elm.elm_number[roi.elm.get_tetrahedra(2)]
        gm_global_rows = np.flatnonzero(self.mesh.elm.get_tetrahedra(2))
        if len(gm_roi_ids) != len(gm_global_rows):
            raise ValueError("ROI and original GM element counts disagree")
        # crop_mesh preserves original element order; verify the map geometrically.
        for start in range(0, len(gm_global_rows), 100_000):
            ids = gm_roi_ids[start:start + 100_000]
            original = gm_global_rows[start:start + 100_000]
            roi_xyz = roi.nodes[roi.elm[ids]]
            global_xyz = self.mesh.nodes[self.mesh.elm.node_number_list[original]]
            if not np.array_equal(roi_xyz, global_xyz):
                raise ValueError("GM crop column order differs from original tetrahedron order")
        with preserved_numpy_search_seed(self.source_search_seed):
            th_ids, bary = roi.find_tetrahedron_with_points(self.source_xyz_mm, compute_baricentric=True)
        tissue = np.full(len(th_ids), -1, dtype=np.int32)
        inside = th_ids >= 1
        tissue[inside] = roi.elm.tag1[th_ids[inside] - 1]
        in_gm = tissue == 2
        fallback = ~in_gm
        gm_global_nodes = self.mesh.elm.node_number_list[gm_global_rows] - 1
        unique_gm_nodes = np.unique(gm_global_nodes)
        nearest_distance = np.zeros(len(th_ids), dtype=float)
        nearest_global_node = np.full(len(th_ids), -1, dtype=np.int64)
        if np.any(fallback):
            distance, idx = cKDTree(self.mesh.nodes.node_coord[unique_gm_nodes]).query(self.source_xyz_mm[fallback])
            nearest_distance[fallback] = distance
            nearest_global_node[fallback] = unique_gm_nodes[idx]
        self.source_qa_arrays = {
            "containing_brain_roi_element_number_one_based": th_ids,
            "containing_tissue_tag_or_minus_one": tissue,
            "containing_tetrahedron_barycentric": bary,
            "gm_nearest_node_fallback_mask": fallback,
            "gm_fallback_distance_mm": nearest_distance,
            "gm_fallback_original_node_row_or_minus_one": nearest_global_node,
        }
        self.progress("cortical_interpolation_matrix_start", source_count=len(th_ids), fallback_count=int(fallback.sum()))
        with preserved_numpy_search_seed(self.source_search_seed):
            interpolation = roi.interp_matrix(
                self.source_xyz_mm, out_fill="nearest", th_indices=gm_roi_ids, element_wise=True,
            ).tocsr()
        interpolation.sum_duplicates()
        interpolation.eliminate_zeros()
        if interpolation.shape != (len(th_ids), len(gm_global_rows)):
            raise ValueError("official interpolation columns must match GM-only tetrahedra")
        if not np.all(np.isfinite(interpolation.data)):
            raise ValueError("official interpolation produced non-finite coefficients")
        # All three official searches receive the same frozen random sequence,
        # and preserve the caller's RNG. Check every resulting node-wise row
        # against the recorded containment/barycentric/fallback evidence.
        with preserved_numpy_search_seed(self.source_search_seed):
            nodal_interpolation = roi.interp_matrix(
                self.source_xyz_mm, out_fill="nearest", th_indices=gm_roi_ids, element_wise=False,
            ).tocsr()
        nodal_interpolation.sum_duplicates()
        nodal_interpolation.eliminate_zeros()
        if nodal_interpolation.shape[1] != len(unique_gm_nodes):
            raise ValueError("official GM node interpolation and original node map differ")
        gm_source_rows = np.flatnonzero(in_gm)
        gm_local_containing = np.searchsorted(gm_roi_ids, th_ids[in_gm])
        gm_compact_node_rows = np.searchsorted(unique_gm_nodes, gm_global_nodes[gm_local_containing])
        fallback_compact_node_rows = np.searchsorted(unique_gm_nodes, nearest_global_node[fallback])
        expected_nodal = sparse.csr_matrix((
            np.concatenate((bary[in_gm].reshape(-1), np.ones(int(fallback.sum())))),
            (np.concatenate((np.repeat(gm_source_rows, 4), np.flatnonzero(fallback))),
             np.concatenate((gm_compact_node_rows.reshape(-1), fallback_compact_node_rows))),
        ), shape=nodal_interpolation.shape)
        node_diff = nodal_interpolation - expected_nodal
        node_diff_max = float(np.max(np.abs(node_diff.data))) if node_diff.nnz else 0.
        if node_diff_max > 1e-10:
            raise ValueError("official node interpolation partition/weights differ from recorded source QA")
        used_gm = np.unique(interpolation.indices)
        compact_interpolation = interpolation[:, used_gm].tocsr()
        selected_global_rows = gm_global_rows[used_gm]
        selected_global_nodes = gm_global_nodes[used_gm]
        gradient_mesh = self.mesh.crop_mesh(elements=self.mesh.elm.elm_number[selected_global_rows])
        if gradient_mesh.elm.nr != len(used_gm) or not np.all(gradient_mesh.elm.get_tetrahedra(2)):
            raise ValueError("gradient submesh does not match selected GM columns")
        if not np.array_equal(gradient_mesh.nodes[gradient_mesh.elm.node_number_list], self.mesh.nodes.node_coord[selected_global_nodes]):
            raise ValueError("gradient submesh reordered the interpolation columns")
        gradients = self._fem._gradient_operator(gradient_mesh)
        self.source_operator = compose_normal_operator(
            compact_interpolation, gradients, selected_global_nodes,
            self.source_normals, self.mesh.nodes.nr,
        )
        # Independent application order using the actual official local G,
        # E=-1000*G*U, official M and then -E dot normal. Compare sampled sources
        # to T@U for two deterministic voltage probes, without a global solve.
        xyz = self.mesh.nodes.node_coord
        probes = np.column_stack((.03 * xyz[:, 0] + .01 * xyz[:, 1] - .02 * xyz[:, 2],
                                  np.sin(.017 * xyz[:, 0]) + np.cos(.013 * xyz[:, 1]) + .0003 * xyz[:, 2] ** 2))
        local_values = probes[selected_global_nodes]
        official_e = -1000. * np.einsum("eic,eip->ecp", gradients, local_values)
        sample = np.unique(np.linspace(0, len(th_ids) - 1, min(32, len(th_ids)), dtype=int))
        source_e = (compact_interpolation[sample] @ official_e.reshape(len(used_gm), 6)).reshape(len(sample), 3, 2)
        expected = -np.einsum("sc,scp->sp", self.source_normals[sample], source_e)
        obtained = self.source_operator[sample] @ probes
        delta = obtained - expected
        official_check = {
            "sample_source_count": len(sample), "probe_count": 2,
            "relative_frobenius_difference": float(np.linalg.norm(delta) / np.linalg.norm(expected)),
            "max_absolute_difference_V_per_m": float(np.max(np.abs(delta))),
            "interpretation": "T application versus official gradient, negative electric field, interpolation and normal projection; not independent FEM validation.",
        }
        row_sums = np.asarray(interpolation.sum(axis=1)).ravel()
        fallback_dist = nearest_distance[fallback]
        self.source_qa = {
            "source_count": len(th_ids), "source_coordinate_unit": "mm",
            "sources_in_gm_count": int(in_gm.sum()), "sources_outside_gm_count": int(fallback.sum()),
            "sources_outside_brain_roi_count": int((~inside).sum()),
            "containing_tissue_counts": {str(tag): int(np.sum(tissue == tag)) for tag in np.unique(tissue)},
            "fallback_fraction": float(fallback.mean()),
            "fallback_distance_definition": "Euclidean mm from source to nearest node of GM-only cropped mesh, exactly the official interp_matrix nearest-node fallback before patch recovery.",
            "fallback_distance_mm": {"maximum": float(fallback_dist.max()) if len(fallback_dist) else 0.,
                                     "median": float(np.median(fallback_dist)) if len(fallback_dist) else 0.,
                                     "p95": float(np.quantile(fallback_dist, .95)) if len(fallback_dist) else 0.},
            "gm_element_count": len(gm_global_rows), "gm_elements_used_by_source_operator": len(used_gm),
            "gm_original_column_order_verified": True,
            "source_search_randomness": {"numpy_legacy_seed": self.source_search_seed,
                                         "numpy_version": np.__version__, "simnibs_version": self.simnibs_version,
                                         "same_seed_for_each_of_three_official_calls": True,
                                         "caller_rng_state_restored": True},
            "all_source_nodal_interpolation_qa_max_abs_difference": node_diff_max,
            "interpolation_shape": list(interpolation.shape), "interpolation_nnz": int(interpolation.nnz),
            "interpolation_row_sum_max_error": float(np.max(np.abs(row_sums - 1))),
            "normal_operator_shape": list(self.source_operator.shape), "normal_operator_nnz": int(self.source_operator.nnz),
            "normal_operator_constant_field_max_abs": float(np.max(np.abs(self.source_operator @ np.ones(self.mesh.nodes.nr)))),
            "official_operator_sample_check": official_check,
            "anatomical_qualification_determined": False, "formal_v2_performance_eligible": False,
            "interpretation": "Descriptive source-location and interpolation QA only. No sources have been discarded or moved. The caller must decide eligibility before performance evaluation.",
        }
        self.timings["source_operator_seconds"] = time.perf_counter() - timer
        self.progress("cortical_source_operator_complete", **self.timings)

    def project(self, points_mm, *, triangle_ids=None, barycentric_weights=None, nearest_vertex_count=20):
        points = _finite_array(points_mm, "electrode points", 2)
        if points.shape[1] != 3 or len(points) == 0:
            raise ValueError("electrode points must have nonempty shape (K,3)")
        if (triangle_ids is None) != (barycentric_weights is None):
            raise ValueError("known triangles and weights must be supplied together")
        if triangle_ids is None:
            import cortech
            surface = cortech.Surface(self.external_vertices_mm, self.external_triangles)
            triangles, weights, projected, _ = surface.project_points(points, pttris=nearest_vertex_count)
        else:
            triangles = np.asarray(triangle_ids, dtype=np.int64)
            weights = _finite_array(barycentric_weights, "known barycentric weights", 2)
            if triangles.shape != (len(points),) or triangles.min() < 0 or triangles.max() >= len(self.external_triangles):
                raise ValueError("known triangle IDs outside qualified exterior component")
            if weights.shape != (len(points), 3):
                raise ValueError("known weights must have shape (K,3)")
            projected = np.einsum("ki,kij->kj", weights, self.external_vertices_mm[self.external_triangles[triangles]])
            if not np.allclose(projected, points, atol=1e-7, rtol=0):
                raise ValueError("known weights do not reproduce requested surface coordinates")
        triangles = np.asarray(triangles, dtype=np.int64)
        weights = np.asarray(weights, dtype=np.float64)
        node_rows = self.external_node_rows[self.external_triangles[triangles]]
        matrix = point_sampling_matrix(self.mesh.nodes.nr, node_rows, weights)
        if not np.allclose(matrix @ self.mesh.nodes.node_coord, projected, atol=1e-7, rtol=0):
            raise ValueError("volume-node weights do not reproduce projected coordinates")
        return ElectrodeProjection(points, np.asarray(projected), triangles, weights, node_rows,
                                   np.linalg.norm(points - projected, axis=1), matrix)

    def prepare_solver(self):
        if self.system is not None:
            return
        self.progress("cortical_fem_matrix_assembly_start")
        timer = time.perf_counter()
        self.system = self._fem.FEMSystem(
            self.mesh, self.conductivity,
            dirichlet=self._fem.DirichletBC([self.gauge_node], [0.]),
            units="mm", solver_options=self.solver,
        )
        self.timings["matrix_assembly_seconds"] = time.perf_counter() - timer
        if not np.array_equal(self.system.dof_map.inverse, self.mesh.nodes.node_number):
            raise ValueError("solver DOF order differs from source operator original node order")
        self.progress("cortical_fem_factorization_start")
        timer = time.perf_counter()
        self.system.prepare_solver()
        self.timings["factorization_seconds"] = time.perf_counter() - timer
        self.progress("cortical_fem_factorization_complete", **self.timings)

    def evaluate(self, points_or_projection, *, block_size=8, current_amperes=1.0):
        """Return (gauge-referenced K x Ns normal leadfield, serializable QA).

        A newly supplied coordinate is projected and directly solved on this
        unchanged FEM mesh. This is not interpolation of an earlier montage's
        leadfield. Point-current weights and source recovery are FE operators.
        """
        if not isinstance(block_size, int) or not 1 <= block_size <= 8:
            raise ValueError("block_size must be an integer from 1 through 8")
        projection = points_or_projection if isinstance(points_or_projection, ElectrodeProjection) else self.project(points_or_projection)
        if projection.matrix.shape[1] != self.mesh.nodes.nr:
            raise ValueError("projection belongs to a different volume mesh")
        self.prepare_solver()
        sampling = projection.matrix
        count = sampling.shape[0]
        result = np.empty((count, len(self.source_xyz_mm)))
        transfer = np.empty((count, count))
        residuals = np.zeros(count)
        free_residuals = np.zeros(count)
        net_rhs = np.zeros(count)
        net_computed = np.zeros(count)
        reaction_error = np.zeros(count)
        free = np.arange(self.mesh.nodes.nr) != self.gauge_row
        timer = time.perf_counter()
        for start in range(0, count, block_size):
            stop = min(start + block_size, count)
            rhs = balanced_sampling_rhs(sampling[start:stop], self.gauge_row, current_amperes)
            potentials = self.system.solve(rhs)
            if potentials.ndim == 1:
                potentials = potentials[:, None]
            if not np.all(np.isfinite(potentials)):
                raise RuntimeError("native FEM returned non-finite potentials")
            result[start:stop] = (self.source_operator @ potentials).T / current_amperes
            transfer[:, start:stop] = (sampling @ potentials - potentials[self.gauge_row]) / current_amperes
            current_computed = self.system.A @ potentials
            residual = current_computed - rhs
            denom = np.linalg.norm(rhs, axis=0)
            free_denom = np.linalg.norm(rhs[free], axis=0)
            absolute = np.linalg.norm(residual, axis=0)
            if np.any((denom == 0) & (absolute != 0)):
                raise RuntimeError("nonzero residual for an exactly zero point-gauge load")
            np.divide(absolute, denom, out=residuals[start:stop], where=denom > 0)
            np.divide(np.linalg.norm(residual[free], axis=0), free_denom, out=free_residuals[start:stop], where=free_denom > 0)
            net_rhs[start:stop] = rhs.sum(axis=0)
            net_computed[start:stop] = current_computed.sum(axis=0)
            reaction_error[start:stop] = np.abs(residual[self.gauge_row]) / current_amperes
            self.progress("cortical_fem_electrode_block_complete", completed_electrodes=stop, total_electrodes=count)
        elapsed = time.perf_counter() - timer
        scale = float(np.linalg.norm(transfer))
        difference = float(np.linalg.norm(transfer - transfer.T))
        qa = {
            "electrode_count": count, "source_count": len(self.source_xyz_mm), "rhs_block_size": block_size,
            "leadfield_shape": list(result.shape), "leadfield_unit": "V/(A*m)",
            "reference": "fixed single-node numerical voltage gauge; caller applies layout-specific reference contrast",
            "gauge_node_number_one_based": self.gauge_node, "normalization_current_A": float(current_amperes),
            "relative_full_system_residual_per_electrode": residuals.tolist(),
            "relative_free_dof_residual_per_electrode": free_residuals.tolist(),
            "max_relative_full_system_residual": float(residuals.max()),
            "max_relative_free_dof_residual": float(free_residuals.max()),
            "net_prescribed_current_A_per_electrode": net_rhs.tolist(),
            "net_assembled_current_A_per_electrode": net_computed.tolist(),
            "reaction_current_relative_error_per_electrode": reaction_error.tolist(),
            "point_transfer_reciprocity_relative_frobenius": difference / scale if scale else 0.,
            "projection_distance_mm": {"maximum": float(projection.distances_mm.max()), "median": float(np.median(projection.distances_mm))},
            "solve_and_residual_seconds": elapsed, "cached_preparation_timings": dict(self.timings),
            "source_qa": self.source_qa,
            "formal_v2_performance_eligible": False, "performance_or_AR_computed": False,
        }
        return result, qa

    def close(self):
        """Release the native factorization when no more layouts are evaluated."""
        self.system = None
