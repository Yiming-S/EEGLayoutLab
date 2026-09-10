"""Fresh cortical sampling and independently known spherical FEM controls.

No native FEM import occurs at module import time. Fresh samples are not drawn
from an inverse dictionary, and nested quadrature weights are recomputed from
the entire declared native cortical domain at each dictionary level.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree, ConvexHull, Delaunay


def extend_farthest_points(xyz, initial_indices, count):
    xyz = np.asarray(xyz, float)
    initial = np.asarray(initial_indices, dtype=np.int64)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.all(np.isfinite(xyz)):
        raise ValueError("finite (N,3) coordinates required")
    if initial.ndim != 1 or not len(initial) or len(np.unique(initial)) != len(initial):
        raise ValueError("initial indices must be distinct and nonempty")
    if initial.min() < 0 or initial.max() >= len(xyz) or not len(initial) <= count <= len(xyz):
        raise ValueError("invalid farthest point extent")
    out = np.empty(count, dtype=np.int64)
    out[:len(initial)] = initial
    minimum = cKDTree(xyz[initial]).query(xyz)[0] ** 2
    minimum[initial] = -np.inf
    for k in range(len(initial), count):
        chosen = int(np.argmax(minimum))
        out[k] = chosen
        delta = xyz - xyz[chosen]
        minimum = np.minimum(minimum, np.einsum("ij,ij->i", delta, delta))
        minimum[out[:k+1]] = -np.inf
    return out


def sample_cortical_faces(xyz, triangles, normals, retained, count, seed):
    xyz, normals = np.asarray(xyz, float), np.asarray(normals, float)
    tri, retained = np.asarray(triangles, np.int64), np.asarray(retained, bool)
    if xyz.shape != normals.shape or xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError("native positions and normals must match")
    if retained.shape != (len(tri),) or count < 1:
        raise ValueError("invalid retained domain or sample count")
    area = np.linalg.norm(np.cross(xyz[tri[:,1]]-xyz[tri[:,0]], xyz[tri[:,2]]-xyz[tri[:,0]]), axis=1)/2
    mass = area*retained
    if not np.all(np.isfinite(mass)) or mass.sum() <= 0:
        raise ValueError("positive finite cortical area required")
    rng = np.random.default_rng(seed)
    faces = rng.choice(len(tri), size=count, p=mass/mass.sum())
    uv = rng.uniform(1e-10, 1-1e-10, (count,2))
    root = np.sqrt(uv[:,0])
    bary = np.column_stack((1-root, root*(1-uv[:,1]), root*uv[:,1]))
    positions = np.einsum("ij,ijk->ik", bary, xyz[tri[faces]])
    ns = np.einsum("ij,ijk->ik", bary, normals[tri[faces]])
    ns /= np.linalg.norm(ns, axis=1)[:,None]
    return {"xyz_mm":positions, "normals":ns, "triangle_indices":faces,
            "barycentric_weights":bary, "total_retained_area_mm2":float(mass.sum())}


def sphere_surface_potential(electrode_xyz_mm, moment_direction, radius_mm=90., conductivity=.33):
    """Insulating homogeneous sphere, central unit Am dipole, V/(Am).

    Phi(R n)=3 p.n/(4*pi*sigma*R**2); gauge-free after centering.
    The expression solves the central dipole primary field plus its regular
    harmonic correction whose outer normal derivative cancels at R.
    """
    points = np.asarray(electrode_xyz_mm, float)
    p = np.asarray(moment_direction, float)
    if points.ndim != 2 or points.shape[1] != 3 or p.shape != (3,) or conductivity <= 0 or radius_mm <= 0:
        raise ValueError("invalid sphere parameters")
    if not np.allclose(np.linalg.norm(points, axis=1), radius_mm, atol=1e-7):
        raise ValueError("analytic electrodes must be exactly on sphere")
    return 3 * (points @ p) / (4*np.pi*conductivity*(radius_mm/1000)**3) / 1000


def sphere_tetrahedral_mesh(level, radius_mm=90.):
    """Deterministic Delaunay volume with exactly spherical boundary vertices.

    A slightly perturbed Cartesian interior avoids coplanar tetrahedra. The
    polyhedral surface converges to a sphere as boundary density increases.
    """
    if level not in (3,5,8,12,18,24):
        raise ValueError("bounded supported sphere resolutions are 3,5,8,12,18,24")
    surface_count = 24*level**2
    j = np.arange(surface_count)
    z = 1-2*(j+.5)/surface_count
    phi = j*np.pi*(3-np.sqrt(5))
    skin = radius_mm*np.column_stack((np.sqrt(1-z*z)*np.cos(phi), np.sqrt(1-z*z)*np.sin(phi), z))
    axis = np.linspace(-radius_mm, radius_mm, 2*level+1)
    inner = np.stack(np.meshgrid(axis,axis,axis,indexing="ij"),axis=-1).reshape(-1,3)
    inner = inner[np.linalg.norm(inner,axis=1) < radius_mm*(1-.5/level)]
    rng = np.random.default_rng(89200+level)
    inner += rng.normal(size=inner.shape) * radius_mm/level * .03
    # Origin deliberately not a mesh node; all three test dipoles share it.
    xyz = np.vstack((skin, inner))
    tess = Delaunay(xyz)
    tet = tess.simplices.copy()
    volume6 = np.linalg.det(xyz[tet[:,1:]]-xyz[tet[:,:1]])
    if np.any(np.abs(volume6) < 1e-10):
        raise ValueError("degenerate sphere tetrahedron")
    negative = volume6 < 0
    tet[negative, :2] = tet[negative, :2][:, ::-1]
    boundary = ConvexHull(skin).simplices.copy()
    center = skin[boundary].mean(axis=1)
    normal = np.cross(skin[boundary[:,1]]-skin[boundary[:,0]],skin[boundary[:,2]]-skin[boundary[:,0]])
    reverse = np.einsum("ij,ij->i", center, normal) < 0
    boundary[reverse,:2] = boundary[reverse,:2][:,::-1]
    return xyz, tet, boundary, surface_count


def run_native_sphere_control(levels=(3,5,8,12,18,24), progress=None):
    """Same FixedMeshLeadfield point-current/recovery chain versus exact sphere.

    This is a homogeneous analytical anchor, NOT Ernie mesh convergence,
    multishell/anatomical validation, or a proof of source-localization accuracy.
    """
    from simnibs.mesh_tools import mesh_io
    from .cortical_fem import FixedMeshLeadfield
    from .metrics import helmert_contrast
    records, raw = [], {}
    for level in levels:
        xyz,tet,tri,ns = sphere_tetrahedral_mesh(level)
        mesh = mesh_io.Msh()
        mesh.nodes = mesh_io.Nodes(xyz)
        mesh.elm = mesh_io.Elements(tetrahedra=tet+1)
        mesh.elm.tag1[:] = 2
        mesh.elm.tag2[:] = 2
        # Select 64 surface nodes with angular FPS independently at each level;
        # exact solution is evaluated at these same nodes, not remapped nodes.
        selected = extend_farthest_points(xyz[:ns], [0],64)
        model = FixedMeshLeadfield(mesh, np.full(mesh.elm.nr,.33), xyz[:ns], tri,
            np.arange(ns), np.zeros((3,3)), np.eye(3), gauge_node=ns+1,
            source_search_seed=9871, progress=progress)
        try:
            obtained, qa = model.evaluate(xyz[selected], block_size=8)
            exact = np.column_stack([sphere_surface_potential(xyz[selected],p) for p in np.eye(3)])
            c = helmert_contrast(64)
            delta = c@(obtained-exact)
            relative = float(np.linalg.norm(delta)/np.linalg.norm(c@exact))
            records.append({"level":level,"nodes":len(xyz),"tetrahedra":len(tet),
                "surface_vertices":ns,"relative_reference_free_leadfield_error":relative,
                "max_relative_system_residual":qa["max_relative_full_system_residual"],
                "reference_free_correlation":float(np.corrcoef((c@obtained).ravel(),(c@exact).ravel())[0,1]),
                "source_qa":model.source_qa,"qa":qa})
            for key,value in (("fem",obtained),("analytic",exact),("electrodes_mm",xyz[selected])):
                raw[f"sphere_level_{level}_{key}"]=value
        finally:
            model.close()
        if progress:
            progress("sphere_level_completed",level=level,relative_error=relative)
    errors=[r["relative_reference_free_leadfield_error"] for r in records]
    return {"status":"completed_analytical_homogeneous_sphere_control",
        "same_point_current_source_recovery_chain":True,"central_dipole_directions":3,
        "decreases_at_every_level":all(b<a for a,b in zip(errors,errors[1:])),
        "records":records,"ernie_mesh_convergence_proven":False,
        "interpretation":"Reference-free field error against exact central-dipole homogeneous sphere; not Ernie mesh convergence or human validation."},raw
