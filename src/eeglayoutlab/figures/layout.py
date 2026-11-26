"""Static 2D layout figure SVG generator (``webapp/lib/layout-figure.ts``, phase 3 slice 5)."""
from __future__ import annotations

import math
import re
from typing import Any, Callable, Optional

from ..core import jsmath
from ..core.design_file import validate_design
from ..core.ernie_mni import load_mapping
from ..schemas import jsjson

__all__ = [
    'FIGURE_REGION_COLORS', 'escape', 'advance', 'wrap', 'clip',
    'project_layout', 'fitted_radius', 'validate_layout_plot',
    'plot_figure_spacing', 'figure_spacing', 'plot_figure_svg', 'layout_figure_svg',
]

FIGURE_REGION_COLORS = ('#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300')
_SHAPES = ('circle', 'square', 'triangle', 'diamond', 'triangle-down', 'hexagon')
_INK = {'primary': '#0b0b0b', 'secondary': '#52514e', 'muted': '#6f6e69', 'line': '#8a8984', 'surface': '#ffffff'}
_WIDTH = 640
_CENTRE_X = 320.0
_CENTRE_Y = 352.0
_MAX_RADIUS = 236.0
_FIT_RADIUS = 290.0

_ESCAPE_MAP = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}
_ESCAPE_RE = re.compile(r'[&<>"\']')
_UPPER_RE = re.compile(r'[A-Z]')


def _has_utf16_cjk_unit(text: str) -> bool:
    """``/[\\u2e80-\\uffef]/.test(text)`` in V8 (without ``/u``, supplementary surrogates 0xD800-0xDFFF also match)."""
    return any(0x2E80 <= ord(ch) <= 0xFFEF or ord(ch) > 0xFFFF for ch in text)


def _utf16_tokens(text: str) -> list[str]:
    """``text.match(/[\\u2e80-\\uffef]|[^\\s\\u2e80-\\uffef]+\\s*|\\s+/g) ?? []`` over UTF-16 code units."""
    raw = text.encode('utf-16-le', errors='surrogatepass')
    units = [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2)]
    ws_codes = {ord(ch) for ch in jsjson.JS_TRIM}
    n = len(units)
    tokens: list[str] = []
    i = 0

    def decode_slice(start: int, end: int) -> str:
        buf = bytearray()
        for u in units[start:end]:
            buf.append(u & 0xFF)
            buf.append((u >> 8) & 0xFF)
        return bytes(buf).decode('utf-16-le', errors='surrogatepass')

    while i < n:
        u = units[i]
        if 0x2E80 <= u <= 0xFFEF:
            tokens.append(decode_slice(i, i + 1))
            i += 1
        elif u in ws_codes:
            start = i
            while i < n and units[i] in ws_codes:
                i += 1
            tokens.append(decode_slice(start, i))
        else:
            start = i
            while i < n and units[i] not in ws_codes and not (0x2E80 <= units[i] <= 0xFFEF):
                i += 1
            while i < n and units[i] in ws_codes:
                i += 1
            tokens.append(decode_slice(start, i))
    return tokens


def escape(text: str) -> str:
    return _ESCAPE_RE.sub(lambda m: _ESCAPE_MAP[m.group(0)], text)


def _fmt(val: float) -> str:
    return jsjson.number_to_string(jsmath.fixed_2(val))


def _fmt_raw(val: float) -> str:
    return jsjson.number_to_string(val)


def _trim_start(text: str) -> str:
    i = 0
    while i < len(text) and text[i] in jsjson.JS_TRIM:
        i += 1
    return text[i:]


def _trim_end(text: str) -> str:
    end = len(text)
    while end > 0 and text[end - 1] in jsjson.JS_TRIM:
        end -= 1
    return text[:end]


def advance(text: str) -> float:
    total = 0.0
    for c in jsmath.graphemes(text):
        total += 1.0 if _has_utf16_cjk_unit(c) else (0.66 if _UPPER_RE.search(c) else 0.54)
    return total


def wrap(text: str, size: float, width: float) -> list[str]:
    lines: list[str] = []
    line = ''
    for token in _utf16_tokens(text):
        if line and advance(_trim_end(line + token)) * size > width:
            lines.append(_trim_end(line))
            line = _trim_start(token)
        else:
            line += token
    if jsjson.js_trim(line):
        lines.append(_trim_end(line))
    return lines


def clip(text: str, size: float, width: float) -> str:
    if advance(text) * size <= width:
        return text
    kept = jsmath.graphemes(text)
    while kept and advance(''.join(kept) + '…') * size > width:
        kept.pop()
    return ''.join(kept) + '…'


def _sub(a: list[float], b: list[float]) -> list[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _dot(a: list[float], b: list[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _unit(a: list[float]) -> list[float]:
    n = jsjson.hypot(*a)
    return [a[0] / n, a[1] / n, a[2] / n]


def project_layout(xyz: list[list[float]], *, root: Optional[str] = None) -> list[dict[str, float]]:
    """``projectLayout``: unit-disc azimuthal equidistant coordinates."""
    marks = load_mapping(root)['landmarks']['native_mm']
    nas, lpa, rpa = list(marks['Nz']), list(marks['LPA']), list(marks['RPA'])
    ex = _unit(_sub(rpa, lpa))
    t = _dot(_sub(nas, lpa), ex)
    origin = [lpa[axis] + t * ex[axis] for axis in range(3)]
    ey = _unit(_sub(nas, origin))
    ez = [ex[1] * ey[2] - ex[2] * ey[1], ex[2] * ey[0] - ex[0] * ey[2], ex[0] * ey[1] - ex[1] * ey[0]]
    out = []
    half_pi = math.pi / 2.0
    for point in xyz:
        v = _sub(point, origin)
        x, y, z = _dot(v, ex), _dot(v, ey), _dot(v, ez)
        r = jsmath.atan2(jsjson.hypot(x, y), z) / half_pi
        azimuth = jsmath.atan2(y, x)
        out.append({'x': r * jsmath.cos(azimuth), 'y': r * jsmath.sin(azimuth), 'r': r})
    return out


def fitted_radius(points: list[dict[str, float]]) -> float:
    max_r = max([1.0, *(p['r'] for p in points)])
    return min(_MAX_RADIUS, _FIT_RADIUS / max_r)


def _finite_coord(v: Any) -> bool:
    return jsjson.is_number(v) and math.isfinite(float(v)) and abs(float(v)) <= 500.0


def validate_layout_plot(inp: Any) -> dict[str, Any]:
    if (
        not isinstance(inp, dict)
        or not isinstance(inp.get('xyz_mm'), list)
        or not (2 <= len(inp['xyz_mm']) <= 64)
        or any(not isinstance(p, list) or len(p) != 3 or not all(_finite_coord(v) for v in p) for p in inp['xyz_mm'])
    ):
        raise ValueError('布局图需要2–64个有效三维坐标。')
    total = len(inp['xyz_mm'])
    if len({','.join(jsjson.number_to_string(float(v)) for v in p) for p in inp['xyz_mm']}) != total:
        raise ValueError('布局图坐标不能重复。')
    regions = inp.get('region_indices')
    if not isinstance(regions, list) or len(regions) != total:
        raise ValueError('布局图需要匹配的区域标签。')
    distinct = {int(float(v)) if jsjson.is_integer(v) else repr(v) for v in regions}
    r = len(distinct)
    if r not in (1, 2, 3, 4, 6) or any(not jsjson.is_integer(v) or float(v) < 0 or float(v) >= r for v in regions):
        raise ValueError('区域标签须从0连续编号，区域数量为1、2、3、4或6。')
    if 'electrode_names' in inp and inp['electrode_names'] is not None:
        if not isinstance(inp['electrode_names'], list) or len(inp['electrode_names']) != total:
            raise ValueError('电极名称数量须与坐标一致。')
    return inp


def _marker(shape: str, x: float, y: float, size: float, fill: str) -> str:
    s = size / 2.0
    ring = f'fill="{fill}" stroke="{_INK["surface"]}" stroke-width="1.5"'

    def polygon(pts: list[tuple[float, float]]) -> str:
        coords = ' '.join(f'{_fmt(x + px)},{_fmt(y + py)}' for px, py in pts)
        return f'<polygon points="{coords}" {ring}/>'

    if shape == 'circle':
        return f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="{_fmt_raw(s)}" {ring}/>'
    if shape == 'square':
        return (
            f'<rect x="{_fmt(x - s * 0.9)}" y="{_fmt(y - s * 0.9)}" '
            f'width="{_fmt(s * 1.8)}" height="{_fmt(s * 1.8)}" rx="1.5" {ring}/>'
        )
    if shape == 'triangle':
        return polygon([(0.0, -s * 1.15), (s * 1.05, s * 0.75), (-s * 1.05, s * 0.75)])
    if shape == 'triangle-down':
        return polygon([(0.0, s * 1.15), (s * 1.05, -s * 0.75), (-s * 1.05, -s * 0.75)])
    if shape == 'diamond':
        return polygon([(0.0, -s * 1.25), (s * 1.25, 0.0), (0.0, s * 1.25), (-s * 1.25, 0.0)])
    return polygon([
        (
            s * 1.1 * jsmath.cos(math.pi / 6.0 + k * math.pi / 3.0),
            s * 1.1 * jsmath.sin(math.pi / 6.0 + k * math.pi / 3.0),
        )
        for k in range(6)
    ])


def plot_figure_spacing(plot: dict[str, Any], radius: Optional[float] = None, *, root: Optional[str] = None) -> float:
    validated = validate_layout_plot(plot)
    disc = project_layout(validated['xyz_mm'], root=root)
    scale = radius if radius is not None else fitted_radius(disc)
    closest = math.inf
    for i, a in enumerate(disc):
        for b in disc[i + 1:]:
            d = jsjson.hypot(a['x'] - b['x'], a['y'] - b['y']) * scale
            if d < closest:
                closest = d
    return closest


def figure_spacing(design: dict[str, Any], radius: Optional[float] = None, *, root: Optional[str] = None) -> float:
    return plot_figure_spacing(validate_design(design), radius, root=root)


def plot_figure_svg(
    inp: dict[str, Any],
    text: dict[str, Any],
    *,
    labels: bool = True,
    radius: Optional[float] = None,
    root: Optional[str] = None,
) -> str:
    design = validate_layout_plot(inp)
    raw_names = design.get('electrode_names')
    names = list(raw_names) if raw_names else [f'E{i + 1}' for i in range(len(design['xyz_mm']))]
    disc = project_layout(design['xyz_mm'], root=root)
    reg_indices = [int(float(v)) for v in design['region_indices']]
    count = max(reg_indices) + 1
    r = radius if radius is not None else fitted_radius(disc)
    cx, cy = _CENTRE_X, _CENTRE_Y
    cx_s, cy_s = _fmt_raw(cx), _fmt_raw(cy)

    head = [
        f'<circle cx="{cx_s}" cy="{cy_s}" r="{_fmt(r)}" fill="none" stroke="{_INK["line"]}" stroke-width="1.5"/>',
        f'<path d="M {_fmt(cx - r * 0.09)} {_fmt(cy - r * 0.996)} L {cx_s} {_fmt(cy - r * 1.09)} '
        f'L {_fmt(cx + r * 0.09)} {_fmt(cy - r * 0.996)}" fill="none" stroke="{_INK["line"]}" '
        f'stroke-width="1.5" stroke-linejoin="round"/>',
        *(
            f'<path d="M {_fmt(cx + side * r)} {_fmt(cy - r * 0.12)} '
            f'q {_fmt(side * r * 0.07)} {_fmt(r * 0.02)} {_fmt(side * r * 0.07)} {_fmt(r * 0.12)} '
            f't {_fmt(-side * r * 0.07)} {_fmt(r * 0.12)}" fill="none" stroke="{_INK["line"]}" stroke-width="1.5"/>'
            for side in (-1, 1)
        ),
    ]
    raw_region_fn = text['region']

    def region_fn(reg: int, total_regions: int) -> str:
        try:
            return raw_region_fn(reg, total_regions)
        except TypeError:
            return raw_region_fn(reg)

    electrodes = []
    for idx, p in enumerate(disc):
        x = cx + p['x'] * r
        y = cy - p['y'] * r
        reg = reg_indices[idx]
        lbl = (
            f'<text x="{_fmt(x)}" y="{_fmt(y + 15.0)}" text-anchor="middle" font-size="9" '
            f'fill="{_INK["secondary"]}">{escape(names[idx])}</text>'
            if labels
            else ''
        )
        electrodes.append(
            f'<g><title>{escape(names[idx])} · {escape(region_fn(reg, count))}</title>'
            f'{_marker(_SHAPES[reg], x, y, 10.0, FIGURE_REGION_COLORS[reg])}{lbl}</g>'
        )

    legend_y = 680
    per_region = [0] * count
    for reg in reg_indices:
        per_region[reg] += 1
    legend = (
        []
        if count < 2
        else [
            f'{_marker(_SHAPES[reg], 32 + reg * ((_WIDTH - 64) // count) + 6, float(legend_y), 10.0, FIGURE_REGION_COLORS[reg])}'
            f'<text x="{32 + reg * ((_WIDTH - 64) // count) + 18}" y="{legend_y + 4}" font-size="11" '
            f'fill="{_INK["primary"]}">{escape(region_fn(reg, count))} ({per_region[reg]})</text>'
            for reg in range(count)
        ]
    )
    caption_lines = [wrapped for line in text['caption'] for wrapped in wrap(line, 10.0, float(_WIDTH - 64))]
    caption_y = 690 if count < 2 else 712
    height = caption_y + len(caption_lines) * 14 + 14
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_WIDTH}" height="{height}" viewBox="0 0 {_WIDTH} {height}" '
        f'font-family="Helvetica, Arial, \'PingFang SC\', \'Noto Sans CJK SC\', sans-serif">',
        f'<rect width="{_WIDTH}" height="{height}" fill="{_INK["surface"]}"/>',
        f'<text x="32" y="40" font-size="16" font-weight="600" fill="{_INK["primary"]}">'
        f'{escape(clip(text["title"], 16.0, float(_WIDTH - 64)))}</text>',
        f'<text x="32" y="60" font-size="12" fill="{_INK["secondary"]}">{escape(text["subtitle"])}</text>',
        *head,
        *electrodes,
        *legend,
        *(
            f'<text x="32" y="{caption_y + idx * 14}" font-size="10" fill="{_INK["muted"]}">{escape(line)}</text>'
            for idx, line in enumerate(caption_lines)
        ),
        '</svg>',
    ]
    return '\n'.join(out) + '\n'


def layout_figure_svg(
    inp: dict[str, Any],
    text: dict[str, Any],
    *,
    labels: bool = True,
    radius: Optional[float] = None,
    root: Optional[str] = None,
) -> str:
    return plot_figure_svg(validate_design(inp), text, labels=labels, radius=radius, root=root)
