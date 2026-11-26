"""Head-frame registration and balanced spatial region assignment (``webapp/lib/head-registration.ts`` &
``head-frame-import.ts``, U12).
"""
from __future__ import annotations

import math
from typing import Any, Optional

from ..jobs import jssort
from ..schemas import jsjson
from . import jsmath
from .coordinate_source import HEAD_REGISTRATION_LIMIT_MM, HEAD_REGISTRATION_METHOD
from .ernie_mni import ErnieMniSurface, load_mapping, project_onto_scalp

__all__ = [
    'LANDMARK_WEIGHT', 'REGION_ASSIGNMENT_METHOD', 'UNIT_MM', 'BALANCED_REGION_DESCRIPTION',
    'ernie_landmarks', 'region_sizes', 'assign_balanced_regions',
    'similarity_fit', 'landmark_similarity', 'register_head_points',
    'place_on_ernie', 'imported_regions',
]

LANDMARK_WEIGHT = 8
MAX_ITERATIONS = 500
TOLERANCE_MM = 1e-4
REGION_ASSIGNMENT_METHOD = 'balanced-spatial/1'
UNIT_MM = {'mm': 1.0, 'cm': 10.0, 'm': 1000.0}


def BALANCED_REGION_DESCRIPTION(count: int) -> str:
    return (
        f"EEGLayoutLab balanced region index assigned on import: {count} spatial region{'' if count == 1 else 's'} "
        'of balanced size (size-constrained k-means on the Ernie coordinates, solved exactly as an assignment '
        'problem), numbered from anterior to posterior.'
    )


def ernie_landmarks(root: Optional[str] = None) -> dict[str, list[float]]:
    native = load_mapping(root)['landmarks']['native_mm']
    return {'NAS': list(native['Nz']), 'LPA': list(native['LPA']), 'RPA': list(native['RPA'])}


def _sub(a: list[float], b: list[float]) -> list[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _dot(a: list[float], b: list[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a: list[float]) -> float:
    return math.sqrt(_dot(a, a))


def _scaled(a: list[float], s: float) -> list[float]:
    return [a[0] * s, a[1] * s, a[2] * s]


def _cross(a: list[float], b: list[float]) -> list[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _unit(a: list[float]) -> list[float]:
    return _scaled(a, 1.0 / _norm(a))


def _apply(rot: list[list[float]], pt: list[float]) -> list[float]:
    return [rot[row][0] * pt[0] + rot[row][1] * pt[1] + rot[row][2] * pt[2] for row in range(3)]


def _fiducial_frame(landmarks: dict[str, list[float]]) -> dict[str, Any]:
    nas, lpa, rpa = landmarks['NAS'], landmarks['LPA'], landmarks['RPA']
    across = _sub(rpa, lpa)
    width = _norm(across)
    if not (width > 1.0):
        raise ValueError('左右耳前点重合或距离过近，无法建立基准坐标系。')
    x = _scaled(across, 1.0 / width)
    t = _dot(_sub(nas, lpa), x)
    origin = [lpa[0] + t * x[0], lpa[1] + t * x[1], lpa[2] + t * x[2]]
    forward = _sub(nas, origin)
    depth = _norm(forward)
    if not (depth > 1.0):
        raise ValueError('鼻根点位于左右耳前点连线上，无法建立基准坐标系。')
    y = _scaled(forward, 1.0 / depth)
    z = _unit(_cross(x, y))
    return {'origin': origin, 'axes': [x, y, z], 'width': width, 'depth': depth}


def _js_sign(val: float) -> float:
    if val > 0.0:
        return 1.0
    if val < 0.0:
        return -1.0
    return 0.0


def _largest_eigenvector(inp: list[list[float]]) -> list[float]:
    a = [list(row) for row in inp]
    v = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    for _ in range(100):
        off = 0.0
        for p in range(4):
            for q in range(p + 1, 4):
                off += a[p][q] * a[p][q]
        if off < 1e-30:
            break
        for p in range(4):
            for q in range(p + 1, 4):
                if abs(a[p][q]) < 1e-300:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
                sign = _js_sign(theta if theta != 0.0 else 1.0)
                t = sign / (abs(theta) + math.sqrt(theta * theta + 1.0))
                c = 1.0 / math.sqrt(t * t + 1.0)
                s = t * c
                for k in range(4):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p] = c * akp - s * akq
                    a[k][q] = s * akp + c * akq
                for k in range(4):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k] = c * apk - s * aqk
                    a[q][k] = s * apk + c * aqk
                for k in range(4):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p] = c * vkp - s * vkq
                    v[k][q] = s * vkp + c * vkq
    best = 0
    for i in range(1, 4):
        if a[i][i] > a[best][best]:
            best = i
    return [row[best] for row in v]


def similarity_fit(source: list[list[float]], target: list[list[float]], weights: list[float]) -> dict[str, Any]:
    total = 0.0
    for w in weights:
        total += w

    def mean(pts: list[list[float]]) -> list[float]:
        out = []
        for axis in range(3):
            acc = 0.0
            for i, p in enumerate(pts):
                acc += weights[i] * p[axis]
            out.append(acc / total)
        return out

    ms, mt = mean(source), mean(target)
    m = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    spread = 0.0
    for i, p in enumerate(source):
        a = _sub(p, ms)
        b = _sub(target[i], mt)
        spread += weights[i] * _dot(a, a)
        for r in range(3):
            for c in range(3):
                m[r][c] += weights[i] * a[r] * b[c]
    (sxx, sxy, sxz), (syx, syy, syz), (szx, szy, szz) = m
    w, x, y, z = _largest_eigenvector([
        [sxx + syy + szz, syz - szy, szx - sxz, sxy - syx],
        [syz - szy, sxx - syy - szz, sxy + syx, szx + sxz],
        [szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy],
        [sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz],
    ])
    rotation = [
        [w * w + x * x - y * y - z * z, 2.0 * (x * y - w * z), 2.0 * (x * z + w * y)],
        [2.0 * (x * y + w * z), w * w - x * x + y * y - z * z, 2.0 * (y * z - w * x)],
        [2.0 * (x * z - w * y), 2.0 * (y * z + w * x), w * w - x * x - y * y + z * z],
    ]
    aligned = 0.0
    for i, p in enumerate(source):
        aligned += weights[i] * _dot(_sub(target[i], mt), _apply(rotation, _sub(p, ms)))
    scale = aligned / spread
    rotated = _apply(rotation, ms)
    translation = [mt[0] - scale * rotated[0], mt[1] - scale * rotated[1], mt[2] - scale * rotated[2]]
    return {'scale': scale, 'rotation': rotation, 'translation': translation}


def _transform(sim: dict[str, Any], p: list[float]) -> list[float]:
    r = _apply(sim['rotation'], p)
    s, t = sim['scale'], sim['translation']
    return [s * r[0] + t[0], s * r[1] + t[1], s * r[2] + t[2]]


def landmark_similarity(
    from_lm: dict[str, list[float]],
    to_lm: Optional[dict[str, list[float]]] = None,
    *,
    root: Optional[str] = None,
) -> dict[str, Any]:
    if to_lm is None:
        to_lm = ernie_landmarks(root)
    a = _fiducial_frame(from_lm)
    b = _fiducial_frame(to_lm)
    scale = math.sqrt((b['width'] / a['width']) * (b['depth'] / a['depth']))
    ax, bx = a['axes'], b['axes']
    rotation = [
        [bx[0][r] * ax[0][c] + bx[1][r] * ax[1][c] + bx[2][r] * ax[2][c] for c in range(3)]
        for r in range(3)
    ]
    moved = _apply(rotation, a['origin'])
    bo = b['origin']
    return {
        'scale': scale,
        'rotation': rotation,
        'translation': [bo[0] - scale * moved[0], bo[1] - scale * moved[1], bo[2] - scale * moved[2]],
    }


def register_head_points(
    points: list[list[float]],
    landmarks: dict[str, list[float]],
    surface: ErnieMniSurface,
) -> dict[str, Any]:
    if any(not isinstance(p, (list, tuple)) or len(p) != 3
           or not all(jsjson.is_number(v) and math.isfinite(float(v)) for v in p) for p in points):
        raise ValueError('坐标必须是有限的三维数值。')
    pts = [[float(p[0]), float(p[1]), float(p[2])] for p in points]
    target_map = {
        'NAS': list(surface.mapping['landmarks']['native_mm']['Nz']),
        'LPA': list(surface.mapping['landmarks']['native_mm']['LPA']),
        'RPA': list(surface.mapping['landmarks']['native_mm']['RPA']),
    }
    names = ('NAS', 'LPA', 'RPA')
    src_lm = [list(landmarks[n]) for n in names]
    dst_lm = [target_map[n] for n in names]
    weights = [1.0] * len(pts) + [float(LANDMARK_WEIGHT)] * 3
    current = landmark_similarity(landmarks, target_map)
    iterations = 0
    previous: Optional[list[list[float]]] = None
    while iterations < MAX_ITERATIONS:
        moved = [_transform(current, p) for p in pts]
        if previous is not None and max(_norm(_sub(p, previous[i])) for i, p in enumerate(moved)) < TOLERANCE_MM:
            break
        previous = moved
        closest = project_onto_scalp(moved, surface)['points']
        current = similarity_fit([*pts, *src_lm], [*closest, *dst_lm], weights)
        iterations += 1
    moved = [_transform(current, p) for p in pts]
    projected = project_onto_scalp(moved, surface)
    residuals = {n: _norm(_sub(_transform(current, landmarks[n]), target_map[n])) for n in names}
    rot = current['rotation']
    trace = rot[0][0] + rot[1][1] + rot[2][2]
    clamped = max(-1.0, min(1.0, (trace - 1.0) / 2.0))
    rotation_deg = jsmath.acos(clamped) * 180.0 / math.pi
    return {
        'points': projected['points'],
        'distances_mm': projected['distances_mm'],
        'scale': current['scale'],
        'rotation_deg': rotation_deg,
        'translation_mm': current['translation'],
        'landmark_residuals_mm': residuals,
        'iterations': iterations,
    }


def _same_landmarks(lm: dict[str, list[float]], target: dict[str, list[float]]) -> bool:
    return all(
        abs(lm[name][axis] - target[name][axis]) <= 1e-6
        for name in ('NAS', 'LPA', 'RPA')
        for axis in range(3)
    )


def place_on_ernie(
    points: list[list[float]],
    landmarks: dict[str, list[float]],
    surface: Optional[ErnieMniSurface],
    inp: dict[str, Any],
    *,
    root: Optional[str] = None,
) -> dict[str, Any]:
    mapping = surface.mapping if surface is not None else load_mapping(root)
    target_lm = {
        'NAS': list(mapping['landmarks']['native_mm']['Nz']),
        'LPA': list(mapping['landmarks']['native_mm']['LPA']),
        'RPA': list(mapping['landmarks']['native_mm']['RPA']),
    }
    if inp['unit'] == 'mm' and _same_landmarks(landmarks, target_lm):
        return {
            'xyz': points,
            'conversion': None,
            'description': "Ernie native coordinate frame used by EEGLayoutLab, in millimetres "
                           "(the file carries Ernie's template landmarks).",
        }
    if surface is None:
        raise ValueError('头坐标配准需要先读取Ernie头皮数据。')
    reg = register_head_points(points, landmarks, surface)
    dists = reg['distances_mm']
    max_dist = max(dists)
    worst = dists.index(max_dist)
    if max_dist > HEAD_REGISTRATION_LIMIT_MM:
        raise ValueError(
            f"配准后电极{inp['names'][worst]}距Ernie头皮{jsmath.to_fixed(max_dist, 1)} mm，"
            f"超过{HEAD_REGISTRATION_LIMIT_MM} mm。请检查坐标系、单位和基准点。"
            "球面模板（非实测坐标）请改用电极名称列表导入。"
        )
    scale = reg['scale']
    if not (0.5 <= scale <= 2.0):
        raise ValueError(f"配准缩放系数{jsmath.to_fixed(scale, 2)}超出0.5–2，请检查单位。")
    residual = max(reg['landmark_residuals_mm'].values())
    conversion = {
        'method': HEAD_REGISTRATION_METHOD,
        'mapping_id': mapping['mapping_id'],
        'input_coordinate_system': inp['coordinate_system'],
        'input_unit': inp['unit'],
        'landmark_source': inp['landmark_source'],
        'scale': scale,
        'rotation_deg': reg['rotation_deg'],
        'max_landmark_residual_mm': residual,
        'max_surface_distance_mm': max_dist,
        'iterations': reg['iterations'],
    }
    description = (
        f"{inp['coordinate_system']} head-frame coordinates registered onto the Ernie template scalp: "
        'NAS/LPA/RPA landmark alignment refined by an isotropic similarity fit to the scalp surface '
        f"(scale {jsmath.to_fixed(scale, 3)}, rotation {jsmath.to_fixed(reg['rotation_deg'], 1)}°), "
        f'then projected onto the scalp. Largest distance from the scalp before projection: '
        f'{jsmath.to_fixed(max_dist, 2)} mm; largest landmark residual against SimNIBS template landmarks: '
        f'{jsmath.to_fixed(residual, 1)} mm. Template-head placement, not an individual anatomical registration.'
    )
    return {'xyz': reg['points'], 'conversion': conversion, 'description': description}


def region_sizes(count: int) -> list[int]:
    return [64 // count + (1 if i < 64 % count else 0) for i in range(count)]


def _assignment(cost: list[list[float]]) -> list[int]:
    """Minimum-cost assignment of rows to columns for a square matrix (Kuhn-Munkres with potentials)."""
    n = len(cost)
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [math.inf] * (n + 1)
        used = [0] * (n + 1)
        while True:
            used[j0] = 1
            i0 = p[j0]
            delta = math.inf
            j1 = 0
            row = cost[i0 - 1]
            ui0 = u[i0]
            for j in range(1, n + 1):
                if not used[j]:
                    cur = row[j - 1] - ui0 - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    rows = [0] * n
    for j in range(1, n + 1):
        rows[p[j] - 1] = j - 1
    return rows


def assign_balanced_regions(points: list[list[float]], count: int) -> list[int]:
    """``assignBalancedRegions(points, count)``: deterministic balanced k-means with V8 sort ordering."""
    if len(points) != 64:
        raise ValueError('需要64个电极。')
    if count not in (1, 2, 3, 4, 6):
        raise ValueError('区域数须为1、2、3、4或6。')
    if count == 1:
        return [0] * 64
    sizes = region_sizes(count)
    slots = [region for region, size in enumerate(sizes) for _ in range(size)]

    def squared(a: list[float], b: list[float]) -> float:
        return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2

    centroid = []
    for axis in range(3):
        acc = 0.0
        for p in points:
            acc += p[axis]
        centroid.append(acc / 64.0)

    def farthest(fn) -> int:
        best = 0
        for i, p in enumerate(points):
            if fn(p) > fn(points[best]):
                best = i
        return best

    centers = [points[farthest(lambda p: squared(p, centroid))]]
    while len(centers) < count:
        centers.append(points[farthest(lambda p: min(squared(p, c) for c in centers))])

    labels: list[int] = []
    for _ in range(100):
        rows = _assignment([[squared(p, centers[region]) for region in slots] for p in points])
        nxt = [slots[slot] for slot in rows]
        if len(labels) == 64 and all(nxt[i] == labels[i] for i in range(64)):
            break
        labels = nxt
        for region in range(count):
            members = [points[i] for i in range(64) if labels[i] == region]
            new_c = []
            for axis in range(3):
                acc = 0.0
                for m in members:
                    acc += m[axis]
                new_c.append(acc / len(members))
            centers[region] = new_c

    def cmp_centers(a: dict[str, Any], b: dict[str, Any]) -> float:
        dy = b['c'][1] - a['c'][1]
        if dy != 0.0:
            return dy
        dx = a['c'][0] - b['c'][0]
        if dx != 0.0:
            return dx
        return float(a['region'] - b['region'])

    order = jssort.array_sort([{'c': c, 'region': region} for region, c in enumerate(centers)], cmp_centers)
    renamed = {item['region']: index for index, item in enumerate(order)}
    return [renamed[label] for label in labels]


def imported_regions(
    xyz: list[list[float]],
    from_file: Optional[list[int]],
    region_count: Optional[int],
    file_description: Optional[str] = None,
) -> dict[str, Any]:
    if from_file is not None:
        return {
            'region_indices': from_file,
            'region_assignment': {'method': 'file'},
            'region_description': file_description,
        }
    if not region_count:
        raise ValueError('文件没有region列，请选择区域数（1、2、3、4或6），由软件按空间位置均衡分区。')
    return {
        'region_indices': assign_balanced_regions(xyz, region_count),
        'region_assignment': {'method': REGION_ASSIGNMENT_METHOD, 'region_count': region_count},
        'region_description': BALANCED_REGION_DESCRIPTION(region_count),
    }
