import { readFileSync, writeFileSync } from 'node:fs';
import { figureSpacing, layoutFigureSvg } from '../../../webapp/lib/layout-figure.ts';

const spec = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' });

const results = [];
for (const c of spec.cases) {
  try {
    if (c.op === 'svg') {
      const design = c.design;
      const count = Math.max(...design.region_indices) + 1;
      const showNames = c.labels === undefined ? figureSpacing(design) >= 16 : c.labels === 'yes';
      const svg = layoutFigureSvg(
        design,
        {
          title: c.title ?? design.name,
          subtitle: c.subtitle ?? `64 electrodes · ${count} region${count > 1 ? 's' : ''} · Ernie template head`,
          region: index => `${c.regionPrefix ?? 'Region'} ${index + 1}`,
          caption: c.caption ?? [
            'Head frame from the Ernie template landmarks NAS, LPA and RPA (x toward RPA, y toward NAS); azimuthal equidistant projection by angle from the vertical axis.',
            'The circle is the NAS–LPA–RPA plane; electrodes below it lie outside. Positions are design positions on the template head, not measured positions.',
          ],
        },
        { labels: showNames, radius: c.radius },
      );
      results.push({ id: c.id, ok: true, spacing: figureSpacing(design), svg });
    } else if (c.op === 'math') {
      const out = c.inputs.map(([a, b]) => [
        Math.atan2(a, b),
        Math.sin(a),
        Math.cos(a),
        Math.acos(Math.max(-1, Math.min(1, a))),
      ]);
      results.push({ id: c.id, ok: true, out });
    } else if (c.op === 'format') {
      const out = c.inputs.map(([x, digits]) => [x.toFixed(digits), x.toPrecision(digits)]);
      results.push({ id: c.id, ok: true, out });
    } else if (c.op === 'graphemes') {
      const out = c.inputs.map(s => Array.from(segmenter.segment(s), item => item.segment));
      results.push({ id: c.id, ok: true, out });
    } else {
      throw new Error(`unknown op ${c.op}`);
    }
  } catch (error) {
    results.push({ id: c.id, ok: false, message: error.message });
  }
}
writeFileSync(process.argv[3], JSON.stringify({ results }));
