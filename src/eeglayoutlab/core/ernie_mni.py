"""Ernie native <-> MNI mapping and scalp surface projection (``webapp/lib/ernie-mni.ts``, U13).

Reads ``ernie-mni-mapping.json``, ``models/ernie/scalp.bin`` and ``data/ernie-scalp-mni.bin`` from
``R/webapp/public`` (resolved via ``jobs.runtime.repository_root``), using pure Python floats (no ``numpy``, no
``json``).
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import struct
from typing import Any, Optional

from ..jobs import nodepath
from ..jobs.runtime import repository_root
from ..schemas import jsjson

__all__ = [
    'ErnieMniSurface', 'load_mapping', 'verified_surface', 'surface_from_buffers',
    'ernie_to_mni', 'mni_to_ernie', 'project_onto_scalp',
]

MAPPING_REL = 'webapp/public/data/ernie-mni-mapping.json'
_MAPPING_MEMO: dict[str, dict[str, Any]] = {}


def _public_dir(root: Optional[str] = None) -> str:
    resolved = repository_root(nodepath.resolve(root) if root else None)
    return nodepath.join(resolved, 'webapp/public')


def load_mapping(root: Optional[str] = None) -> dict[str, Any]:
    """Loads and caches ``R/webapp/public/data/ernie-mni-mapping.json``."""
    pub = _public_dir(root)
    path = nodepath.join(pub, 'data/ernie-mni-mapping.json')
    cached = _MAPPING_MEMO.get(path)
    if cached is not None:
        return cached
    data = jsjson.parse(Path(path).read_text(encoding='utf-8'))
    _MAPPING_MEMO[path] = data
    return data


@dataclass
class ErnieMniSurface:
    mapping: dict[str, Any]
    native: list[float]
    mni: list[float]
    faces: list[int]
    usable: list[int]
    on_usable: list[int]
    native_edge: float
    mni_edge: float
    _projector: Optional[dict[str, Any]] = None


def _longest_edge(vertices: list[float], faces: list[int], usable: list[int]) -> float:
    longest = 0.0
    for f in range(0, len(faces), 3):
        if usable[f // 3]:
            f0, f1, f2 = faces[f], faces[f + 1], faces[f + 2]
            for a, b in ((f0, f1), (f1, f2), (f2, f0)):
                dx = vertices[3 * a] - vertices[3 * b]
                dy = vertices[3 * a + 1] - vertices[3 * b + 1]
                dz = vertices[3 * a + 2] - vertices[3 * b + 2]
                d2 = dx * dx + dy * dy + dz * dz
                if d2 > longest:
                    longest = d2
    return math.sqrt(longest)


def surface_from_buffers(scalp: bytes, mni_buffer: bytes, mapping: Optional[dict[str, Any]] = None) -> ErnieMniSurface:
    """``surfaceFromBuffers``: unpacks little-endian float32 scalp (* 1000) and MNI coordinates and uint16 faces."""
    if mapping is None:
        mapping = load_mapping()
    sb = mapping['scalp_buffer']
    mb = mapping['mni_buffer']
    n_verts = int(sb['vertices'])
    n_tris = int(sb['triangles'])
    pos_offset = int(sb['position_byte_offset'])
    idx_offset = int(sb['index_byte_offset'])
    if len(scalp) < idx_offset + n_tris * 6 or len(mni_buffer) != int(mb['byte_length']):
        raise ValueError('Ernie–MNI映射数据长度不符。')
    raw_pos = struct.unpack_from(f'<{n_verts * 3}f', scalp, pos_offset)
    raw_mni = struct.unpack_from(f'<{n_verts * 3}f', mni_buffer, 0)
    native = [v * 1000.0 for v in raw_pos]
    mni = list(raw_mni)
    faces = list(struct.unpack_from(f'<{n_tris * 3}H', scalp, idx_offset))
    usable = list(mni_buffer[n_verts * 12:])
    if len(usable) != n_tris or any(flag > 1 for flag in usable):
        raise ValueError('Ernie–MNI映射数据格式不符。')
    on_usable = [0] * n_verts
    for face in range(n_tris):
        if usable[face]:
            on_usable[faces[3 * face]] = 1
            on_usable[faces[3 * face + 1]] = 1
            on_usable[faces[3 * face + 2]] = 1
    return ErnieMniSurface(
        mapping=mapping,
        native=native,
        mni=mni,
        faces=faces,
        usable=usable,
        on_usable=on_usable,
        native_edge=_longest_edge(native, faces, usable),
        mni_edge=_longest_edge(mni, faces, usable),
    )


def verified_surface(
    scalp: Optional[bytes] = None,
    mni_buffer: Optional[bytes] = None,
    *,
    root: Optional[str] = None,
) -> ErnieMniSurface:
    """``verifiedSurface``: checks SHA-256 of both binary buffers against ``ernie-mni-mapping.json``."""
    mapping = load_mapping(root)
    if scalp is None or mni_buffer is None:
        pub = _public_dir(root)
        scalp_file = str(mapping['scalp_buffer']['file']).lstrip('/')
        mni_file = str(mapping['mni_buffer']['file']).lstrip('/')
        try:
            if scalp is None:
                scalp = Path(nodepath.join(pub, scalp_file)).read_bytes()
            if mni_buffer is None:
                mni_buffer = Path(nodepath.join(pub, mni_file)).read_bytes()
        except OSError as error:
            raise ValueError('无法读取Ernie–MNI映射数据。') from error
    scalp_hash = hashlib.sha256(scalp).hexdigest()
    mni_hash = hashlib.sha256(mni_buffer).hexdigest()
    if scalp_hash != mapping['scalp_buffer']['sha256'] or mni_hash != mapping['mni_buffer']['sha256']:
        raise ValueError('Ernie–MNI映射数据校验失败。')
    return surface_from_buffers(scalp, mni_buffer, mapping)


def _closest(p: list[float], v: list[float], a: int, b: int, c: int) -> tuple[float, float, float]:
    """Closest point of triangle abc to p (Ericson 5.1.5) as barycentric weights, matching ``ernie-mni.ts``."""
    ax, ay, az = v[3 * a], v[3 * a + 1], v[3 * a + 2]
    abx, aby, abz = v[3 * b] - ax, v[3 * b + 1] - ay, v[3 * b + 2] - az
    acx, acy, acz = v[3 * c] - ax, v[3 * c + 1] - ay, v[3 * c + 2] - az
    apx, apy, apz = p[0] - ax, p[1] - ay, p[2] - az
    d1 = abx * apx + aby * apy + abz * apz
    d2 = acx * apx + acy * apy + acz * apz
    if d1 <= 0.0 and d2 <= 0.0:
        return 1.0, 0.0, 0.0
    bpx, bpy, bpz = p[0] - v[3 * b], p[1] - v[3 * b + 1], p[2] - v[3 * b + 2]
    d3 = abx * bpx + aby * bpy + abz * bpz
    d4 = acx * bpx + acy * bpy + acz * bpz
    if d3 >= 0.0 and d4 <= d3:
        return 0.0, 1.0, 0.0
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        t = d1 / (d1 - d3)
        return 1.0 - t, t, 0.0
    cpx, cpy, cpz = p[0] - v[3 * c], p[1] - v[3 * c + 1], p[2] - v[3 * c + 2]
    d5 = abx * cpx + aby * cpy + abz * cpz
    d6 = acx * cpx + acy * cpy + acz * cpz
    if d6 >= 0.0 and d5 <= d6:
        return 0.0, 0.0, 1.0
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        t = d2 / (d2 - d6)
        return 1.0 - t, 0.0, t
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return 0.0, 1.0 - t, t
    denom = 1.0 / (va + vb + vc)
    t = vb * denom
    s = vc * denom
    return 1.0 - t - s, t, s


def _at(v: list[float], f: list[int], face: int, w: tuple[float, float, float]) -> list[float]:
    f0, f1, f2 = 3 * f[3 * face], 3 * f[3 * face + 1], 3 * f[3 * face + 2]
    return [
        w[0] * v[f0] + w[1] * v[f1] + w[2] * v[f2],
        w[0] * v[f0 + 1] + w[1] * v[f1 + 1] + w[2] * v[f2 + 1],
        w[0] * v[f0 + 2] + w[1] * v[f1 + 2] + w[2] * v[f2 + 2],
    ]


def _valid_point(point: Any) -> list[float]:
    if (not isinstance(point, (list, tuple)) or len(point) != 3
            or not all(jsjson.is_number(v) and math.isfinite(float(v)) for v in point)):
        raise ValueError('坐标必须是有限的三维数值。')
    return [float(point[0]), float(point[1]), float(point[2])]


def _transfer(
    points: list[list[float]],
    src: list[float],
    dst: list[float],
    surface: ErnieMniSurface,
    edge: float,
) -> dict[str, list[Any]]:
    n_verts = len(src) // 3
    n_tris = len(surface.usable)
    faces = surface.faces
    usable = surface.usable
    on_usable = surface.on_usable
    out_points: list[list[float]] = []
    out_dists: list[float] = []
    squared = [math.inf] * n_verts
    for raw_pt in points:
        pt = _valid_point(raw_pt)
        px, py, pz = pt
        nearest = math.inf
        for i in range(n_verts):
            if not on_usable[i]:
                squared[i] = math.inf
                continue
            dx = src[3 * i] - px
            dy = src[3 * i + 1] - py
            dz = src[3 * i + 2] - pz
            d2 = dx * dx + dy * dy + dz * dz
            squared[i] = d2
            if d2 < nearest:
                nearest = d2
        radius_sq = (math.sqrt(nearest) + edge) ** 2
        near = [1 if squared[i] <= radius_sq else 0 for i in range(n_verts)]
        best = math.inf
        best_face = -1
        best_w = (1.0, 0.0, 0.0)
        for face in range(n_tris):
            if not usable[face]:
                continue
            a, b, c = faces[3 * face], faces[3 * face + 1], faces[3 * face + 2]
            if not near[a] and not near[b] and not near[c]:
                continue
            w = _closest(pt, src, a, b, c)
            q = _at(src, faces, face, w)
            dist = (q[0] - px) ** 2 + (q[1] - py) ** 2 + (q[2] - pz) ** 2
            if dist < best:
                best = dist
                best_face = face
                best_w = w
        out_points.append(_at(dst, faces, best_face, best_w))
        out_dists.append(math.sqrt(best))
    return {'points': out_points, 'distances_mm': out_dists}


def ernie_to_mni(points: list[list[float]], surface: ErnieMniSurface) -> dict[str, list[Any]]:
    return _transfer(points, surface.native, surface.mni, surface, surface.native_edge)


def mni_to_ernie(points: list[list[float]], surface: ErnieMniSurface) -> dict[str, list[Any]]:
    return _transfer(points, surface.mni, surface.native, surface, surface.mni_edge)


def _projector(surface: ErnieMniSurface) -> dict[str, Any]:
    if surface._projector is not None:
        return surface._projector
    v = surface.native
    faces = surface.faces
    n_verts = len(v) // 3
    n_tris = len(faces) // 3
    every = [1] * n_tris
    edge = _longest_edge(v, faces, every)
    mn = [math.inf, math.inf, math.inf]
    mx = [-math.inf, -math.inf, -math.inf]
    for i in range(n_verts):
        for a in range(3):
            val = v[3 * i + a]
            if val < mn[a]:
                mn[a] = val
            if val > mx[a]:
                mx[a] = val
    cell = max(edge, 1.0)
    dims = [math.floor((mx[a] - mn[a]) / cell) + 1 for a in range(3)]
    cells: dict[int, list[int]] = {}
    incident: list[list[int]] = [[] for _ in range(n_verts)]
    for i in range(n_verts):
        cx = math.floor((v[3 * i] - mn[0]) / cell)
        cy = math.floor((v[3 * i + 1] - mn[1]) / cell)
        cz = math.floor((v[3 * i + 2] - mn[2]) / cell)
        key = (cx * dims[1] + cy) * dims[2] + cz
        cells.setdefault(key, []).append(i)
    for face in range(n_tris):
        incident[faces[3 * face]].append(face)
        incident[faces[3 * face + 1]].append(face)
        incident[faces[3 * face + 2]].append(face)
    built = {'cell': cell, 'edge': edge, 'min': mn, 'dims': dims, 'cells': cells, 'incident': incident}
    surface._projector = built
    return built


def project_onto_scalp(points: list[list[float]], surface: ErnieMniSurface) -> dict[str, list[Any]]:
    """``projectOntoScalp``: exact closest points on Ernie's whole native scalp via uniform grid."""
    proj = _projector(surface)
    cell: float = proj['cell']
    edge: float = proj['edge']
    mn: list[float] = proj['min']
    dims: list[int] = proj['dims']
    cells: dict[int, list[int]] = proj['cells']
    incident: list[list[int]] = proj['incident']
    v = surface.native
    faces = surface.faces
    out_points: list[list[float]] = []
    out_dists: list[float] = []

    def visit(pt: list[float], radius: float):
        lo0 = max(0, math.floor((pt[0] - radius - mn[0]) / cell))
        lo1 = max(0, math.floor((pt[1] - radius - mn[1]) / cell))
        lo2 = max(0, math.floor((pt[2] - radius - mn[2]) / cell))
        hi0 = min(dims[0] - 1, math.floor((pt[0] + radius - mn[0]) / cell))
        hi1 = min(dims[1] - 1, math.floor((pt[1] + radius - mn[1]) / cell))
        hi2 = min(dims[2] - 1, math.floor((pt[2] + radius - mn[2]) / cell))
        d1, d2 = dims[1], dims[2]
        for x in range(lo0, hi0 + 1):
            for y in range(lo1, hi1 + 1):
                base = (x * d1 + y) * d2
                for z in range(lo2, hi2 + 1):
                    bucket = cells.get(base + z)
                    if bucket:
                        yield from bucket

    for raw_pt in points:
        pt = _valid_point(raw_pt)
        px, py, pz = pt

        def sq(idx: int) -> float:
            return (v[3 * idx] - px) ** 2 + (v[3 * idx + 1] - py) ** 2 + (v[3 * idx + 2] - pz) ** 2

        nearest = math.inf
        radius = cell
        while math.isinf(nearest):
            for idx in visit(pt, radius):
                d2 = sq(idx)
                if d2 < nearest:
                    nearest = d2
            radius *= 2.0
        for idx in visit(pt, math.sqrt(nearest)):
            d2 = sq(idx)
            if d2 < nearest:
                nearest = d2
        reach = math.sqrt(nearest) + edge
        reach_sq = reach * reach
        seen: set[int] = set()
        best = math.inf
        best_face = -1
        best_w = (1.0, 0.0, 0.0)
        for idx in visit(pt, reach):
            if sq(idx) > reach_sq:
                continue
            for face in incident[idx]:
                if face in seen:
                    continue
                seen.add(face)
                w = _closest(pt, v, faces[3 * face], faces[3 * face + 1], faces[3 * face + 2])
                q = _at(v, faces, face, w)
                dist = (q[0] - px) ** 2 + (q[1] - py) ** 2 + (q[2] - pz) ** 2
                if dist < best:
                    best = dist
                    best_face = face
                    best_w = w
        out_points.append(_at(v, faces, best_face, best_w))
        out_dists.append(math.sqrt(best))
    return {'points': out_points, 'distances_mm': out_dists}
