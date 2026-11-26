"""Static SVG figure for channel-subset error curves (``webapp/lib/channel-subset-figure.ts``, phase 3 slice 12)."""
from __future__ import annotations

import math
from typing import Any, Callable, Optional, Sequence

from ..core import jsmath
from ..schemas import jsjson
from .layout import FIGURE_REGION_COLORS, advance, escape, wrap

__all__ = ['SUBSET_METHODS', 'subset_curves', 'error_axis', 'channel_subset_figure_svg']

SUBSET_METHODS: tuple[dict[str, str], ...] = (
    {'id': 'data', 'color': FIGURE_REGION_COLORS[0], 'shape': 'circle'},
    {'id': 'data_prior', 'color': FIGURE_REGION_COLORS[1], 'shape': 'square'},
    {'id': 'area_prior', 'color': FIGURE_REGION_COLORS[2], 'shape': 'triangle'},
)
_STANDARD = {'color': FIGURE_REGION_COLORS[3], 'shape': 'diamond'}
_INK = {
    'primary': '#0b0b0b',
    'secondary': '#52514e',
    'muted': '#6f6e69',
    'axis': '#8a8984',
    'grid': '#e6e5e0',
    'random': '#8a8984',
    'surface': '#ffffff',
}
_WIDTH = 640
_LEFT = 64
_RIGHT = 612
_PLOT_HEIGHT = 260


def _num(val: float | int) -> str:
    return jsjson.number_to_string(float(val))


def _fixed(val: float) -> str:
    return jsjson.number_to_string(jsmath.fixed_2(val))


def _percent(val: float, digits: int = 1) -> str:
    return f'{jsmath.to_fixed(100.0 * val, digits)}%'


def _js_round(val: float) -> int:
    return math.floor(val + 0.5) if val >= 0.0 else -math.floor(-val + 0.5 + 1e-18)


def subset_curves(report: dict[str, Any]) -> dict[str, Any]:
    """``subsetCurves(report)``: held-out means when held-out summaries exist, else training errors."""
    held_out = len(report['test']) > 0

    def row_value(row: dict[str, Any]) -> float:
        return float(row['test_error']['mean']) if held_out else float(row['train_error'])

    methods = report.get('methods') or {}
    standard = report.get('standard_10_20')
    series: list[dict[str, Any]] = []
    for method in SUBSET_METHODS:
        m_block = methods.get(method['id'])
        if not m_block:
            continue
        rows = m_block['counts']
        points = [{'count': int(row['count']), 'value': row_value(row)} for row in rows]
        if method['id'] == 'data' and standard and standard.get('data_same_count'):
            std_count = int(standard['count'])
            if not any(pt['count'] == std_count for pt in points):
                points.append({
                    'count': std_count,
                    'value': row_value({'count': std_count, **standard['data_same_count']}),
                })
        points.sort(key=lambda pt: pt['count'])
        series.append({**method, 'points': points})

    random_pts = [
        {
            'count': int(row['count']),
            **(row['test_error_mean'] if held_out else row['train_error']),
        }
        for row in report['random']['counts']
    ]
    std_pt = {'count': int(standard['count']), 'value': row_value(standard)} if standard else None
    return {'heldOut': held_out, 'series': series, 'random': random_pts, 'standard': std_pt}


def error_axis(max_val: float) -> dict[str, float]:
    """``errorAxis(max)``: round upper bound and step in at most five steps."""
    exponent = -2
    while True:
        for mantissa in (1.0, 2.0, 2.5, 5.0):
            step = mantissa * (10.0 ** exponent)
            top = max(step, math.ceil((max_val * 1.05) / step - 1e-9) * step)
            if top / step <= 5.0:
                return {'top': top, 'step': step}
        exponent += 1


def _marker(shape: str, x: float, y: float, fill: str) -> str:
    s = 4.5
    ring = f'class="mark" fill="{fill}" stroke="{_INK["surface"]}" stroke-width="2"'

    def polygon(pts: Sequence[tuple[float, float]]) -> str:
        coords = ' '.join(f'{_fixed(x + px)},{_fixed(y + py)}' for px, py in pts)
        return f'<polygon points="{coords}" {ring}/>'

    if shape == 'circle':
        return f'<circle cx="{_fixed(x)}" cy="{_fixed(y)}" r="{_num(s)}" {ring}/>'
    if shape == 'square':
        return (
            f'<rect x="{_fixed(x - s)}" y="{_fixed(y - s)}" '
            f'width="{_num(2.0 * s)}" height="{_num(2.0 * s)}" rx="1.5" {ring}/>'
        )
    if shape == 'triangle':
        return polygon([(0.0, -s * 1.25), (s * 1.15, s * 0.85), (-s * 1.15, s * 0.85)])
    return polygon([(0.0, -s * 1.4), (s * 1.4, 0.0), (0.0, s * 1.4), (-s * 1.4, 0.0)])


def _reference(x: float, y: float) -> str:
    s = 8.5
    coords = ' '.join(f'{_fixed(x + px)},{_fixed(y + py)}' for px, py in ((0.0, -s), (s, 0.0), (0.0, s), (-s, 0.0)))
    return (
        f'<polygon points="{coords}" class="mark" fill="{_INK["surface"]}" '
        f'stroke="{_STANDARD["color"]}" stroke-width="2" stroke-linejoin="round"/>'
    )


def _height_at(line: Sequence[tuple[float, float]], px: float) -> Optional[float]:
    for i in range(1, len(line)):
        ax, ay = line[i - 1]
        bx, by = line[i]
        if ax <= px <= bx:
            return ay if bx == ax else ay + ((px - ax) / (bx - ax)) * (by - ay)
    return None


def channel_subset_figure_svg(report: dict[str, Any], text: dict[str, Any]) -> str:
    """``channelSubsetFigureSvg(report, text)`` from ``webapp/lib/channel-subset-figure.ts``."""
    curves = subset_curves(report)
    series = curves['series']
    random_pts = curves['random']
    standard = curves['standard']
    names = text['names']
    channels_fn: Callable[[int], str] = text['channels']

    def make_line_key(color: str, shape: str) -> Callable[[float, float], str]:
        return lambda lx, ly: (
            f'<line x1="{_num(lx)}" y1="{_num(ly)}" x2="{_num(lx + 22.0)}" y2="{_num(ly)}" '
            f'stroke="{color}" stroke-width="2" stroke-linecap="round"/>'
            f'{_marker(shape, lx + 11.0, ly, color)}'
        )

    items: list[tuple[str, Callable[[float, float], str]]] = [
        *((names[s['id']], make_line_key(s['color'], s['shape'])) for s in series),
        *([(names['standard'], lambda lx, ly: _reference(lx + 11.0, ly))] if standard else []),
        (
            names['random'],
            lambda lx, ly: (
                f'<rect x="{_num(lx)}" y="{_num(ly - 6.0)}" width="22" height="12" rx="2" '
                f'fill="{_INK["random"]}" fill-opacity="0.16"/>'
                f'<line x1="{_num(lx)}" y1="{_num(ly)}" x2="{_num(lx + 22.0)}" y2="{_num(ly)}" '
                f'stroke="{_INK["random"]}" stroke-width="2" stroke-linecap="round"/>'
            ),
        ),
    ]

    legend: list[str] = []
    lx = float(_LEFT - 32)
    ly = 80.0
    for label, draw_fn in items:
        width = 30.0 + advance(label) * 11.0 + 18.0
        if lx > _LEFT - 32 and lx + width > _WIDTH - 24:
            lx = float(_LEFT - 32)
            ly += 20.0
        legend.append(
            f'<g>{draw_fn(lx, ly)}<text x="{_num(lx + 30.0)}" y="{_num(ly + 4.0)}" '
            f'font-size="11" fill="{_INK["primary"]}">{escape(label)}</text></g>'
        )
        lx += width

    top = ly + 30.0
    bottom = top + _PLOT_HEIGHT

    counts = sorted({*(int(c) for c in report['counts']), *([int(standard['count'])] if standard else [])})
    lo, hi = counts[0], counts[-1]
    pad = (hi - lo) * 0.05 if hi > lo else 1.0

    def x_coord(count: int) -> float:
        return _LEFT + ((count - lo + pad) / (hi - lo + 2.0 * pad)) * (_RIGHT - _LEFT)

    values = [
        *(pt['value'] for s in series for pt in s['points']),
        *(float(r['p90']) for r in random_pts),
        *([float(standard['value'])] if standard else []),
    ]
    axis = error_axis(max(values))

    def y_coord(val: float) -> float:
        return bottom - (val / axis['top']) * _PLOT_HEIGHT

    digits = 1 if (axis['step'] < 0.05 and (_js_round(axis['step'] * 1000.0) % 10 != 0)) else 0

    grid: list[str] = []
    k = 0
    while k * axis['step'] <= axis['top'] + 1e-9:
        val = k * axis['step']
        gy = jsmath.fixed_2(y_coord(val))
        gy_s = jsjson.number_to_string(gy)
        grid.append(
            f'<line x1="{_LEFT}" y1="{gy_s}" x2="{_RIGHT}" y2="{gy_s}" '
            f'stroke="{_INK["grid"] if k else _INK["axis"]}" stroke-width="1"/>'
        )
        grid.append(
            f'<text x="{_LEFT - 8}" y="{_fixed(gy + 4.0)}" text-anchor="end" font-size="11" '
            f'fill="{_INK["secondary"]}">{_percent(val, digits)}</text>'
        )
        k += 1

    last_tick = -math.inf
    for count in counts:
        tx = x_coord(count)
        grid.append(
            f'<line x1="{_fixed(tx)}" y1="{_num(bottom)}" x2="{_fixed(tx)}" y2="{_num(bottom + 4.0)}" '
            f'stroke="{_INK["axis"]}" stroke-width="1"/>'
        )
        if tx - last_tick >= 22.0:
            grid.append(
                f'<text x="{_fixed(tx)}" y="{_num(bottom + 18.0)}" text-anchor="middle" font-size="11" '
                f'fill="{_INK["secondary"]}">{count}</text>'
            )
            last_tick = tx

    def svg_path(pts: Sequence[dict[str, Any]]) -> str:
        return ' '.join(
            f"{'L' if idx else 'M'} {_fixed(x_coord(pt['count']))} {_fixed(y_coord(pt['value']))}"
            for idx, pt in enumerate(pts)
        )

    if len(random_pts) > 1:
        upper = svg_path([{'count': r['count'], 'value': float(r['p90'])} for r in random_pts])
        lower = ' '.join(
            f"L {_fixed(x_coord(r['count']))} {_fixed(y_coord(float(r['p10'])))}"
            for r in reversed(random_pts)
        )
        band_svg = f'<path d="{upper} {lower} Z" fill="{_INK["random"]}" fill-opacity="0.16"/>'
    else:
        r0 = random_pts[0]
        band_svg = (
            f'<line x1="{_fixed(x_coord(r0["count"]))}" y1="{_fixed(y_coord(float(r0["p10"])))}" '
            f'x2="{_fixed(x_coord(r0["count"]))}" y2="{_fixed(y_coord(float(r0["p90"])))}" '
            f'stroke="{_INK["random"]}" stroke-opacity="0.4" stroke-width="8"/>'
        )

    def svg_line(pts: Sequence[dict[str, Any]], color: str) -> str:
        return (
            f'<path d="{svg_path(pts)}" fill="none" stroke="{color}" '
            'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        )

    def svg_point(title: str, count: int, val: float, mark: str) -> str:
        return (
            f'<g class="point"><title>{escape(title)}</title>'
            f'<circle cx="{_fixed(x_coord(count))}" cy="{_fixed(y_coord(val))}" r="12" '
            f'fill="{_INK["surface"]}" fill-opacity="0"/>{mark}</g>'
        )

    def draw_series(s: dict[str, Any]) -> list[str]:
        return [
            svg_line(s['points'], s['color']),
            *(
                svg_point(
                    f"{names[s['id']]} · {channels_fn(pt['count'])} · {_percent(pt['value'])}",
                    pt['count'],
                    pt['value'],
                    _marker(s['shape'], x_coord(pt['count']), y_coord(pt['value']), s['color']),
                )
                for pt in s['points']
            ),
        ]

    marks: list[str] = [
        band_svg,
        svg_line([{'count': r['count'], 'value': float(r['median'])} for r in random_pts], _INK['random']),
        *(
            svg_point(
                f"{names['random']} · {channels_fn(r['count'])} · {_percent(float(r['median']))} "
                f"(P10–P90 {_percent(float(r['p10']))}–{_percent(float(r['p90']))})",
                r['count'],
                float(r['median']),
                '',
            )
            for r in random_pts
        ),
        *(elem for s in reversed([s for s in series if s['id'] != 'data']) for elem in draw_series(s)),
        *(
            [
                svg_point(
                    f"{names['standard']} · {_percent(standard['value'])}",
                    standard['count'],
                    standard['value'],
                    _reference(x_coord(standard['count']), y_coord(standard['value'])),
                )
            ]
            if standard
            else []
        ),
        *(elem for s in series if s['id'] == 'data' for elem in draw_series(s)),
    ]

    if standard:
        sx = x_coord(standard['count'])
        sy = y_coord(standard['value'])
        std_label = names['standard']
        lbl_width = advance(std_label) * 11.0
        polylines: list[list[tuple[float, float]]] = [
            [(x_coord(r['count']), y_coord(float(r['median']))) for r in random_pts],
            *[[(x_coord(pt['count']), y_coord(pt['value'])) for pt in s['points']] for s in series],
        ]
        places = [
            {
                'left': sx + dx if dx > 0 else sx + dx - lbl_width,
                'baseline': sy + dy,
                'end': dx < 0,
            }
            for dx, dy in ((12.0, -12.0), (12.0, 18.0), (-12.0, -12.0), (-12.0, 18.0))
        ]

        def inside(p: dict[str, Any]) -> bool:
            return (
                p['left'] >= _LEFT
                and p['left'] + lbl_width <= _WIDTH - 8
                and p['baseline'] - 10.0 >= top
                and p['baseline'] + 3.0 <= bottom
            )

        def clear(p: dict[str, Any]) -> bool:
            for poly in polylines:
                for k_sample in range(7):
                    h = _height_at(poly, p['left'] + (k_sample / 6.0) * lbl_width)
                    if h is not None and not (h < p['baseline'] - 14.0 or h > p['baseline'] + 6.0):
                        return False
            return True

        chosen_place = (
            next((p for p in places if inside(p) and clear(p)), None)
            or next((p for p in places if inside(p)), None)
            or places[0]
        )
        anchor_x = chosen_place['left'] + lbl_width if chosen_place['end'] else chosen_place['left']
        anchor = 'end' if chosen_place['end'] else 'start'
        marks.append(
            f'<text x="{_fixed(anchor_x)}" y="{_fixed(chosen_place["baseline"])}" '
            f'text-anchor="{anchor}" font-size="11" fill="{_INK["secondary"]}">{escape(std_label)}</text>'
        )

    caption = [line for item in text['caption'] for line in wrap(item, 10.0, float(_WIDTH - 64))]
    caption_y = bottom + 64.0
    height = caption_y + len(caption) * 14.0 + 12.0
    h_str = _num(height)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_WIDTH}" height="{h_str}" viewBox="0 0 {_WIDTH} {h_str}" '
        f'font-family="Helvetica, Arial, \'PingFang SC\', \'Noto Sans CJK SC\', sans-serif">',
        f'<title>{escape(text["title"])}</title>',
        f'<style>.point:hover .mark{{stroke:{_INK["primary"]}}}</style>',
        f'<rect width="{_WIDTH}" height="{h_str}" fill="{_INK["surface"]}"/>',
        f'<text x="32" y="36" font-size="16" font-weight="600" fill="{_INK["primary"]}">{escape(text["title"])}</text>',
        f'<text x="32" y="56" font-size="12" fill="{_INK["secondary"]}">{escape(text["subtitle"])}</text>',
        *legend,
        *grid,
        *marks,
        f'<text x="{_fixed((_LEFT + _RIGHT) / 2.0)}" y="{_num(bottom + 40.0)}" text-anchor="middle" '
        f'font-size="12" fill="{_INK["secondary"]}">{escape(text["xLabel"])}</text>',
        f'<text transform="translate(18 {_fixed((top + bottom) / 2.0)}) rotate(-90)" text-anchor="middle" '
        f'font-size="12" fill="{_INK["secondary"]}">{escape(text["yLabel"])}</text>',
        *(
            f'<text x="32" y="{_num(caption_y + idx * 14.0)}" font-size="10" '
            f'fill="{_INK["muted"]}">{escape(item)}</text>'
            for idx, item in enumerate(caption)
        ),
        '</svg>',
    ]
    return '\n'.join(out) + '\n'
