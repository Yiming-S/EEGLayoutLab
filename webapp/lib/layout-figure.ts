import { validateDesign, type ElectrodeDesign } from './design-decision.ts';
import { ERNIE_MNI_MAPPING, type Point } from './ernie-mni.ts';

/**
 * A static 2D layout figure (SVG) for papers and reports.
 *
 * Electrodes are drawn in the head frame of the Ernie template landmarks (x toward RPA, y toward NAS,
 * z up, origin on the LPA–RPA line) with an azimuthal equidistant projection: the distance from the
 * centre is proportional to the angle from the vertical axis, and the circle is the NAS–LPA–RPA plane.
 */

// Reference categorical slots 1–6. Beyond three regions colour alone is not separable for every pair,
// so each region also has its own marker shape and the legend names it.
export const FIGURE_REGION_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300'];
const SHAPES = ['circle', 'square', 'triangle', 'diamond', 'triangle-down', 'hexagon'] as const;
const INK = { primary: '#0b0b0b', secondary: '#52514e', muted: '#6f6e69', line: '#8a8984', surface: '#ffffff' };
const WIDTH = 640, CENTRE = { x: 320, y: 352 }, MAX_RADIUS = 236, FIT_RADIUS = 290;

export type FigureText = {
  title: string;
  subtitle: string;
  region: (index: number, count: number) => string;
  caption: string[];
};

const sub = (a: Point, b: Point): Point => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a: Point, b: Point) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const unit = (a: Point): Point => { const n = Math.hypot(...a); return [a[0] / n, a[1] / n, a[2] / n]; };
const escape = (text: string) => text.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
const fixed = (value: number) => Number(value.toFixed(2));
// SVG text does not wrap. Approximate advance widths (em): CJK and full-width 1, Latin about 0.56.
const graphemes = (text: string) => Array.from(new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(text), part => part.segment);
const advance = (text: string) => graphemes(text).reduce((sum, c) => sum + (/[\u2e80-\uffef]/.test(c) ? 1 : /[A-Z]/.test(c) ? 0.66 : 0.54), 0);
function wrap(text: string, size: number, width: number) {
  const lines: string[] = [];
  let line = '';
  for (const token of text.match(/[\u2e80-\uffef]|[^\s\u2e80-\uffef]+\s*|\s+/g) ?? []) {
    if (line && advance((line + token).trimEnd()) * size > width) { lines.push(line.trimEnd()); line = token.trimStart(); }
    else line += token;
  }
  if (line.trim()) lines.push(line.trimEnd());
  return lines;
}
function clip(text: string, size: number, width: number) {
  if (advance(text) * size <= width) return text;
  let kept = graphemes(text);
  while (kept.length && advance(kept.join('') + '…') * size > width) kept = kept.slice(0, -1);
  return kept.join('') + '…';
}

/** Unit-disc coordinates of each electrode: radius 1 is the landmark plane, anterior is +y. */
export function projectLayout(xyz: readonly Point[]) {
  const marks = ERNIE_MNI_MAPPING.landmarks.native_mm, nas = marks.Nz as Point, lpa = marks.LPA as Point, rpa = marks.RPA as Point;
  const ex = unit(sub(rpa, lpa)), origin = lpa.map((value, axis) => value + dot(sub(nas, lpa), ex) * ex[axis]) as Point;
  const ey = unit(sub(nas, origin)), ez: Point = [ex[1] * ey[2] - ex[2] * ey[1], ex[2] * ey[0] - ex[0] * ey[2], ex[0] * ey[1] - ex[1] * ey[0]];
  return xyz.map(point => {
    const v = sub(point, origin), x = dot(v, ex), y = dot(v, ey), z = dot(v, ez);
    const r = Math.atan2(Math.hypot(x, y), z) / (Math.PI / 2), azimuth = Math.atan2(y, x);
    return { x: r * Math.cos(azimuth), y: r * Math.sin(azimuth), r };
  });
}

function marker(shape: (typeof SHAPES)[number], x: number, y: number, size: number, fill: string) {
  const s = size / 2, ring = `fill="${fill}" stroke="${INK.surface}" stroke-width="1.5"`;
  const polygon = (points: number[][]) => `<polygon points="${points.map(([px, py]) => `${fixed(x + px)},${fixed(y + py)}`).join(' ')}" ${ring}/>`;
  if (shape === 'circle') return `<circle cx="${fixed(x)}" cy="${fixed(y)}" r="${s}" ${ring}/>`;
  if (shape === 'square') return `<rect x="${fixed(x - s * 0.9)}" y="${fixed(y - s * 0.9)}" width="${fixed(s * 1.8)}" height="${fixed(s * 1.8)}" rx="1.5" ${ring}/>`;
  if (shape === 'triangle') return polygon([[0, -s * 1.15], [s * 1.05, s * 0.75], [-s * 1.05, s * 0.75]]);
  if (shape === 'triangle-down') return polygon([[0, s * 1.15], [s * 1.05, -s * 0.75], [-s * 1.05, -s * 0.75]]);
  if (shape === 'diamond') return polygon([[0, -s * 1.25], [s * 1.25, 0], [0, s * 1.25], [-s * 1.25, 0]]);
  return polygon(Array.from({ length: 6 }, (_, k) => [s * 1.1 * Math.cos(Math.PI / 6 + k * Math.PI / 3), s * 1.1 * Math.sin(Math.PI / 6 + k * Math.PI / 3)]));
}

/** Closest pair of projected electrodes in figure pixels; names collide below about 16 px. */
export function figureSpacing(design: ElectrodeDesign) {
  const disc = projectLayout(validateDesign(design).xyz_mm), scale = Math.min(MAX_RADIUS, FIT_RADIUS / Math.max(1, ...disc.map(p => p.r)));
  let closest = Infinity;
  disc.forEach((a, i) => disc.slice(i + 1).forEach(b => { closest = Math.min(closest, Math.hypot(a.x - b.x, a.y - b.y) * scale); }));
  return closest;
}

export function layoutFigureSvg(input: ElectrodeDesign, text: FigureText, { labels = true } = {}) {
  const design = validateDesign(input), names = design.electrode_names ?? design.xyz_mm.map((_, index) => `E${index + 1}`);
  const disc = projectLayout(design.xyz_mm), count = Math.max(...design.region_indices) + 1;
  // Electrodes below the landmark plane lie outside the circle; shrink the head so every one fits.
  const radius = Math.min(MAX_RADIUS, FIT_RADIUS / Math.max(1, ...disc.map(p => p.r)));
  const at = (p: { x: number; y: number }) => ({ x: CENTRE.x + p.x * radius, y: CENTRE.y - p.y * radius });
  const { x: cx, y: cy } = CENTRE, r = radius;
  const head = [
    `<circle cx="${cx}" cy="${cy}" r="${fixed(r)}" fill="none" stroke="${INK.line}" stroke-width="1.5"/>`,
    `<path d="M ${fixed(cx - r * 0.09)} ${fixed(cy - r * 0.996)} L ${cx} ${fixed(cy - r * 1.09)} L ${fixed(cx + r * 0.09)} ${fixed(cy - r * 0.996)}" fill="none" stroke="${INK.line}" stroke-width="1.5" stroke-linejoin="round"/>`,
    ...[-1, 1].map(side => `<path d="M ${fixed(cx + side * r)} ${fixed(cy - r * 0.12)} q ${fixed(side * r * 0.07)} ${fixed(r * 0.02)} ${fixed(side * r * 0.07)} ${fixed(r * 0.12)} t ${fixed(-side * r * 0.07)} ${fixed(r * 0.12)}" fill="none" stroke="${INK.line}" stroke-width="1.5"/>`),
  ];
  const electrodes = disc.map((p, index) => {
    const { x, y } = at(p), region = design.region_indices[index];
    const label = labels ? `<text x="${fixed(x)}" y="${fixed(y + 15)}" text-anchor="middle" font-size="9" fill="${INK.secondary}">${escape(names[index])}</text>` : '';
    return `<g><title>${escape(names[index])} · ${escape(text.region(region, count))}</title>${marker(SHAPES[region], x, y, 10, FIGURE_REGION_COLORS[region])}${label}</g>`;
  });
  const legendY = 680, perRegion = design.region_indices.reduce((totals, region) => { totals[region]++; return totals; }, Array(count).fill(0) as number[]);
  const legend = count < 2 ? [] : Array.from({ length: count }, (_, region) => {
    const x = 32 + region * Math.floor((WIDTH - 64) / count);
    return `${marker(SHAPES[region], x + 6, legendY, 10, FIGURE_REGION_COLORS[region])}<text x="${x + 18}" y="${legendY + 4}" font-size="11" fill="${INK.primary}">${escape(text.region(region, count))} (${perRegion[region]})</text>`;
  });
  const caption = text.caption.flatMap(line => wrap(line, 10, WIDTH - 64));
  const captionY = count < 2 ? 690 : 712, height = captionY + caption.length * 14 + 14;
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${WIDTH}" height="${height}" viewBox="0 0 ${WIDTH} ${height}" font-family="Helvetica, Arial, 'PingFang SC', 'Noto Sans CJK SC', sans-serif">`,
    `<rect width="${WIDTH}" height="${height}" fill="${INK.surface}"/>`,
    `<text x="32" y="40" font-size="16" font-weight="600" fill="${INK.primary}">${escape(clip(text.title, 16, WIDTH - 64))}</text>`,
    `<text x="32" y="60" font-size="12" fill="${INK.secondary}">${escape(text.subtitle)}</text>`,
    ...head, ...electrodes, ...legend,
    ...caption.map((line, index) => `<text x="32" y="${captionY + index * 14}" font-size="10" fill="${INK.muted}">${escape(line)}</text>`),
    '</svg>',
  ].join('\n') + '\n';
}

/** PNG at a fixed pixel scale from the same SVG (browser only). */
export async function svgToPng(svg: string, scale = 3): Promise<Blob> {
  const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }));
  try {
    const image = new Image();
    await new Promise<void>((resolve, reject) => { image.onload = () => resolve(); image.onerror = () => reject(new Error('布局图渲染失败。')); image.src = url; });
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(image.width * scale); canvas.height = Math.round(image.height * scale);
    const context = canvas.getContext('2d');
    if (!context) throw new Error('布局图渲染失败。');
    context.scale(scale, scale); context.drawImage(image, 0, 0);
    return await new Promise<Blob>((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('布局图渲染失败。')), 'image/png'));
  } finally { URL.revokeObjectURL(url); }
}
