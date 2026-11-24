import type { channelSubsets } from './channel-subset.ts';
import { FIGURE_REGION_COLORS, advance, escape, wrap } from './layout-figure.ts';

/**
 * Error against subset size for a channel-subset report (eeg-channel-subset/1), as a static SVG.
 *
 * With held-out summaries the curves are the mean held-out error; without them, the training error,
 * which is optimistic for the data-greedy subsets. Random subsets show their median and P10–P90 band
 * over draws, and the 10-20 subset is one point; the data-greedy curve includes the 10-20 size.
 */

export type SubsetReport = ReturnType<typeof channelSubsets>;
type ErrorRow = { count: number; train_error: number; test_error: { mean: number } | null };

// Colour and shape follow the method, never its position, so a report without a prior keeps the data colour.
export const SUBSET_METHODS = [
  { id: 'data', color: FIGURE_REGION_COLORS[0], shape: 'circle' },
  { id: 'data_prior', color: FIGURE_REGION_COLORS[1], shape: 'square' },
  { id: 'area_prior', color: FIGURE_REGION_COLORS[2], shape: 'triangle' },
] as const;
const STANDARD = { color: FIGURE_REGION_COLORS[3], shape: 'diamond' } as const;
type Shape = (typeof SUBSET_METHODS)[number]['shape'] | typeof STANDARD.shape;
const INK = { primary: '#0b0b0b', secondary: '#52514e', muted: '#6f6e69', axis: '#8a8984', grid: '#e6e5e0', random: '#8a8984', surface: '#ffffff' };
const WIDTH = 640, LEFT = 64, RIGHT = 612, PLOT_HEIGHT = 260;

export type SubsetFigureText = {
  title: string;
  subtitle: string;
  xLabel: string;
  yLabel: string;
  names: Record<(typeof SUBSET_METHODS)[number]['id'] | 'random' | 'standard', string>;
  /** "16 channels" in the page language. */
  channels: (count: number) => string;
  caption: string[];
};

/** The plotted values: held-out means when the report has held-out summaries, else training errors. */
export function subsetCurves(report: SubsetReport) {
  const heldOut = report.test.length > 0, value = (row: ErrorRow) => heldOut ? row.test_error!.mean : row.train_error;
  const methods = report.methods as Record<string, { counts: ErrorRow[] } | undefined>, standard = report.standard_10_20;
  const series = SUBSET_METHODS.flatMap(method => {
    const rows = methods[method.id]?.counts;
    if (!rows) return [];
    const points = rows.map(row => ({ count: row.count, value: value(row) }));
    if (method.id === 'data' && standard?.data_same_count && !points.some(point => point.count === standard.count))
      points.push({ count: standard.count, value: value({ count: standard.count, ...standard.data_same_count }) });
    return [{ ...method, points: points.sort((a, b) => a.count - b.count) }];
  });
  const random = report.random.counts.map(row => ({ count: row.count, ...(heldOut ? row.test_error_mean! : row.train_error) }));
  return { heldOut, series, random, standard: standard ? { count: standard.count, value: value(standard) } : null };
}

const fixed = (value: number) => Number(value.toFixed(2));
const percent = (value: number, digits = 1) => `${(100 * value).toFixed(digits)}%`;

/**
 * Upper end and step of the error axis: zero to a round value above every plotted value, in at most five steps.
 * A held-out error can exceed 100% when a subset predicts the held-out data worse than predicting zero.
 */
export function errorAxis(max: number) {
  for (let exponent = -2; ; exponent++) {
    for (const mantissa of [1, 2, 2.5, 5]) {
      const step = mantissa * 10 ** exponent, top = Math.max(step, Math.ceil((max * 1.05) / step - 1e-9) * step);
      if (top / step <= 5) return { top, step };
    }
  }
}

function marker(shape: Shape, x: number, y: number, fill: string) {
  // Markers are at least 8 px across with a 2 px surface ring, so they stay legible where they cross a line.
  const s = 4.5, ring = `class="mark" fill="${fill}" stroke="${INK.surface}" stroke-width="2"`;
  const polygon = (points: number[][]) => `<polygon points="${points.map(([px, py]) => `${fixed(x + px)},${fixed(y + py)}`).join(' ')}" ${ring}/>`;
  if (shape === 'circle') return `<circle cx="${fixed(x)}" cy="${fixed(y)}" r="${s}" ${ring}/>`;
  if (shape === 'square') return `<rect x="${fixed(x - s)}" y="${fixed(y - s)}" width="${2 * s}" height="${2 * s}" rx="1.5" ${ring}/>`;
  if (shape === 'triangle') return polygon([[0, -s * 1.25], [s * 1.15, s * 0.85], [-s * 1.15, s * 0.85]]);
  return polygon([[0, -s * 1.4], [s * 1.4, 0], [0, s * 1.4], [-s * 1.4, 0]]);
}

/** The 10-20 subset is a hollow diamond, drawn under the data curve: the data-greedy point at the same size stays visible inside it. */
function reference(x: number, y: number) {
  const s = 8.5;
  return `<polygon points="${[[0, -s], [s, 0], [0, s], [-s, 0]].map(([px, py]) => `${fixed(x + px)},${fixed(y + py)}`).join(' ')}" class="mark" fill="${INK.surface}" stroke="${STANDARD.color}" stroke-width="2" stroke-linejoin="round"/>`;
}

type Pixel = { x: number; y: number };
/** Height of a polyline at a pixel column, or null outside it. */
function heightAt(line: Pixel[], px: number) {
  for (let i = 1; i < line.length; i++) {
    const a = line[i - 1], b = line[i];
    if (px >= a.x && px <= b.x) return b.x === a.x ? a.y : a.y + ((px - a.x) / (b.x - a.x)) * (b.y - a.y);
  }
  return null;
}

export function channelSubsetFigureSvg(report: SubsetReport, text: SubsetFigureText) {
  const { series, random, standard } = subsetCurves(report);

  // Legend first: its rows set where the plot starts. Line keys mirror the marks; random is a band with its median.
  type Item = { label: string; key: string };
  const lineKey = (color: string, shape: Shape) => (x: number, y: number) =>
    `<line x1="${x}" y1="${y}" x2="${x + 22}" y2="${y}" stroke="${color}" stroke-width="2" stroke-linecap="round"/>${marker(shape, x + 11, y, color)}`;
  const items: (Item & { draw: (x: number, y: number) => string })[] = [
    ...series.map(s => ({ label: text.names[s.id], key: s.id, draw: lineKey(s.color, s.shape) })),
    ...(standard ? [{ label: text.names.standard, key: 'standard', draw: (x: number, y: number) => reference(x + 11, y) }] : []),
    { label: text.names.random, key: 'random', draw: (x: number, y: number) =>
      `<rect x="${x}" y="${y - 6}" width="22" height="12" rx="2" fill="${INK.random}" fill-opacity="0.16"/><line x1="${x}" y1="${y}" x2="${x + 22}" y2="${y}" stroke="${INK.random}" stroke-width="2" stroke-linecap="round"/>` },
  ];
  const legend: string[] = [];
  let lx = LEFT - 32, ly = 80;
  for (const item of items) {
    const width = 30 + advance(item.label) * 11 + 18;
    if (lx > LEFT - 32 && lx + width > WIDTH - 24) { lx = LEFT - 32; ly += 20; }
    legend.push(`<g>${item.draw(lx, ly)}<text x="${lx + 30}" y="${ly + 4}" font-size="11" fill="${INK.primary}">${escape(item.label)}</text></g>`);
    lx += width;
  }
  const top = ly + 30, bottom = top + PLOT_HEIGHT;

  const counts = [...new Set([...report.counts, ...(standard ? [standard.count] : [])])].sort((a, b) => a - b);
  const lo = counts[0], hi = counts.at(-1)!, pad = hi > lo ? (hi - lo) * 0.05 : 1;
  const x = (count: number) => LEFT + ((count - lo + pad) / (hi - lo + 2 * pad)) * (RIGHT - LEFT);
  const values = [...series.flatMap(s => s.points.map(p => p.value)), ...random.map(r => r.p90), ...(standard ? [standard.value] : [])];
  const axis = errorAxis(Math.max(...values));
  const y = (value: number) => bottom - (value / axis.top) * PLOT_HEIGHT;
  const digits = axis.step < 0.05 && Math.round(axis.step * 1000) % 10 ? 1 : 0;

  const grid: string[] = [];
  for (let k = 0; k * axis.step <= axis.top + 1e-9; k++) {
    const value = k * axis.step, gy = fixed(y(value));
    grid.push(`<line x1="${LEFT}" y1="${gy}" x2="${RIGHT}" y2="${gy}" stroke="${k ? INK.grid : INK.axis}" stroke-width="1"/>`,
      `<text x="${LEFT - 8}" y="${fixed(gy + 4)}" text-anchor="end" font-size="11" fill="${INK.secondary}">${percent(value, digits)}</text>`);
  }
  // Integer ticks at the plotted sizes; a label too close to the previous one is left to the tooltip.
  let lastTick = -Infinity;
  for (const count of counts) {
    const tx = x(count);
    grid.push(`<line x1="${fixed(tx)}" y1="${bottom}" x2="${fixed(tx)}" y2="${bottom + 4}" stroke="${INK.axis}" stroke-width="1"/>`);
    if (tx - lastTick >= 22) { grid.push(`<text x="${fixed(tx)}" y="${bottom + 18}" text-anchor="middle" font-size="11" fill="${INK.secondary}">${count}</text>`); lastTick = tx; }
  }

  const path = (points: { count: number; value: number }[]) => points.map((p, i) => `${i ? 'L' : 'M'} ${fixed(x(p.count))} ${fixed(y(p.value))}`).join(' ');
  const band = random.length > 1
    ? `<path d="${path(random.map(r => ({ count: r.count, value: r.p90 })))} ${[...random].reverse().map(r => `L ${fixed(x(r.count))} ${fixed(y(r.p10))}`).join(' ')} Z" fill="${INK.random}" fill-opacity="0.16"/>`
    : `<line x1="${fixed(x(random[0].count))}" y1="${fixed(y(random[0].p10))}" x2="${fixed(x(random[0].count))}" y2="${fixed(y(random[0].p90))}" stroke="${INK.random}" stroke-opacity="0.4" stroke-width="8"/>`;
  const line = (points: { count: number; value: number }[], color: string) =>
    `<path d="${path(points)}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
  // Every point carries a hit area larger than its mark and a tooltip with the method, size and value.
  const point = (title: string, count: number, value: number, mark: string) =>
    `<g class="point"><title>${escape(title)}</title><circle cx="${fixed(x(count))}" cy="${fixed(y(value))}" r="12" fill="${INK.surface}" fill-opacity="0"/>${mark}</g>`;
  const drawSeries = (s: (typeof series)[number]) => [line(s.points, s.color),
    ...s.points.map(p => point(`${text.names[s.id]} · ${text.channels(p.count)} · ${percent(p.value)}`, p.count, p.value, marker(s.shape, x(p.count), y(p.value), s.color)))];
  const marks = [
    band,
    line(random.map(r => ({ count: r.count, value: r.median })), INK.random),
    ...random.map(r => point(`${text.names.random} · ${text.channels(r.count)} · ${percent(r.median)} (P10–P90 ${percent(r.p10)}–${percent(r.p90)})`, r.count, r.median, '')),
    // Model curves first, then the 10-20 point, then the data curve on top.
    ...series.filter(s => s.id !== 'data').reverse().flatMap(drawSeries),
    ...(standard ? [point(`${text.names.standard} · ${percent(standard.value)}`, standard.count, standard.value, reference(x(standard.count), y(standard.value)))] : []),
    ...series.filter(s => s.id === 'data').flatMap(drawSeries),
  ];
  if (standard) {
    // The 10-20 label goes beside its point, on the first side where it crosses no curve and stays in the plot.
    const sx = x(standard.count), sy = y(standard.value), label = text.names.standard, width = advance(label) * 11;
    const lines = [random.map(r => ({ x: x(r.count), y: y(r.median) })), ...series.map(s => s.points.map(p => ({ x: x(p.count), y: y(p.value) })))];
    const places = [[12, -12], [12, 18], [-12, -12], [-12, 18]].map(([dx, dy]) => ({ left: dx > 0 ? sx + dx : sx + dx - width, baseline: sy + dy, end: dx < 0 }));
    const inside = (p: (typeof places)[number]) => p.left >= LEFT && p.left + width <= WIDTH - 8 && p.baseline - 10 >= top && p.baseline + 3 <= bottom;
    const clear = (p: (typeof places)[number]) => lines.every(poly => Array.from({ length: 7 }, (_, k) => heightAt(poly, p.left + (k / 6) * width))
      .every(h => h === null || h < p.baseline - 14 || h > p.baseline + 6));
    const place = places.find(p => inside(p) && clear(p)) ?? places.find(inside) ?? places[0];
    marks.push(`<text x="${fixed(place.end ? place.left + width : place.left)}" y="${fixed(place.baseline)}" text-anchor="${place.end ? 'end' : 'start'}" font-size="11" fill="${INK.secondary}">${escape(label)}</text>`);
  }

  const caption = text.caption.flatMap(item => wrap(item, 10, WIDTH - 64)), captionY = bottom + 64, height = captionY + caption.length * 14 + 12;
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${WIDTH}" height="${height}" viewBox="0 0 ${WIDTH} ${height}" font-family="Helvetica, Arial, 'PingFang SC', 'Noto Sans CJK SC', sans-serif">`,
    `<title>${escape(text.title)}</title>`,
    `<style>.point:hover .mark{stroke:${INK.primary}}</style>`,
    `<rect width="${WIDTH}" height="${height}" fill="${INK.surface}"/>`,
    `<text x="32" y="36" font-size="16" font-weight="600" fill="${INK.primary}">${escape(text.title)}</text>`,
    `<text x="32" y="56" font-size="12" fill="${INK.secondary}">${escape(text.subtitle)}</text>`,
    ...legend, ...grid, ...marks,
    `<text x="${fixed((LEFT + RIGHT) / 2)}" y="${bottom + 40}" text-anchor="middle" font-size="12" fill="${INK.secondary}">${escape(text.xLabel)}</text>`,
    `<text transform="translate(18 ${fixed((top + bottom) / 2)}) rotate(-90)" text-anchor="middle" font-size="12" fill="${INK.secondary}">${escape(text.yLabel)}</text>`,
    ...caption.map((item, index) => `<text x="32" y="${captionY + index * 14}" font-size="10" fill="${INK.muted}">${escape(item)}</text>`),
    '</svg>',
  ].join('\n') + '\n';
}
