import test from 'node:test';
import assert from 'node:assert/strict';
import { parseElectrodeLabels } from '../lib/bids-electrodes.ts';
import { ERNIE_MNI_MAPPING } from '../lib/ernie-mni.ts';
import { FIGURE_REGION_COLORS, figureSpacing, layoutFigureSvg, plotFigureSpacing, plotFigureSvg, projectLayout, sharedFigureRadius, sharedPlotFigureRadius } from '../lib/layout-figure.ts';

const names = ERNIE_MNI_MAPPING.golden.standard64.names;
const labels = regions => parseElectrodeLabels({ name: 'labels.tsv', text: 'name\tregion\n' + names.map((name, index) => name + '\t' + regions(index)).join('\n') + '\n' });
const text = { title: 'standard64 & <test>', subtitle: '64 electrodes', region: index => `Region ${index + 1}`,
  caption: ['A long caption line that is certainly wider than the figure and therefore has to be wrapped onto more than one line of text.', '圆为NAS–LPA–RPA平面，低于该平面的电极画在圆外。位置为模板头上的设计位置，不是实测位置。'] };

void test('the projection puts the vertex at the centre, the landmark plane on the circle and the nose up', () => {
  const marks = ERNIE_MNI_MAPPING.landmarks.native_mm;
  const [nas, lpa, rpa] = projectLayout([marks.Nz, marks.LPA, marks.RPA]);
  for (const point of [nas, lpa, rpa]) assert.ok(Math.abs(point.r - 1) < 1e-9, 'landmarks lie on the circle');
  assert.ok(nas.y > 0.999 && lpa.x < -0.999 && rpa.x > 0.999);
  const design = labels(index => index % 2), at = name => projectLayout(design.xyz_mm)[names.indexOf(name)];
  assert.ok(at('Cz').r < 0.15, 'Cz is near the centre');
  assert.ok(at('C3').x < -0.3 && at('C4').x > 0.3 && at('Fpz').y > 0.6 && at('Oz').y < -0.6);
  assert.ok(at('Iz').r > 1 && at('P9').r > 1, 'electrodes below the landmark plane are outside the circle');
});

void test('the SVG draws every electrode once with its region colour, shape and legend, and escapes text', () => {
  const design = labels(index => index % 4), svg = layoutFigureSvg(design, text);
  assert.match(svg, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg" width="640" height="\d+"/);
  assert.equal((svg.match(/<title>/g) ?? []).length, 64);
  assert.ok(svg.includes('standard64 &amp; &lt;test&gt;') && !svg.includes('<test>'));
  for (let region = 0; region < 4; region++) assert.ok(svg.includes(`>Region ${region + 1} (16)</text>`));
  assert.equal((svg.match(new RegExp(`fill="${FIGURE_REGION_COLORS[3]}"`, 'g')) ?? []).length, 16 + 1);
  assert.ok(svg.includes('>Fp1</text>') && !layoutFigureSvg(design, text, { labels: false }).includes('>Fp1</text>'));
  // Each caption line fits the 640-pixel figure.
  const captions = [...svg.matchAll(/font-size="10" fill="#6f6e69">([^<]*)</g)].map(match => match[1]);
  assert.equal(captions.length, 3); assert.ok(captions.every(line => line.length < 115));
  assert.ok(!layoutFigureSvg(labels(() => 0), text).includes('Region 1 (64)'), 'one region needs no legend');
});

void test('the electrode positions fit inside the figure above the legend', () => {
  const svg = layoutFigureSvg(labels(index => index % 2), text);
  const ys = [...svg.matchAll(/<g><title>[^<]*<\/title><(?:circle cx="[^"]+" cy="([^"]+)"|rect x="[^"]+" y="([^"]+)")/g)].map(match => Number(match[1] ?? match[2]));
  assert.equal(ys.length, 64);
  assert.ok(Math.max(...ys) < 665 && Math.min(...ys) > 70);
  assert.ok(figureSpacing(labels(index => index % 2)) > 16, 'standard64 names do not collide');
});

void test('side-by-side figures share a scale that fits both sets of electrodes', () => {
  const standard = labels(index => index % 2);
  const lower = { ...standard, xyz_mm: [[0, -35, -200], ...standard.xyz_mm.slice(1)] };
  const headRadius = svg => Number(svg.match(/<circle cx="320" cy="352" r="([\d.]+)"/)?.[1]);
  const [standardRadius, lowerRadius] = [standard, lower].map(design => headRadius(layoutFigureSvg(design, text)));
  assert.ok(standardRadius > lowerRadius);
  const radius = sharedFigureRadius([standard, lower]);
  assert.equal(sharedFigureRadius([lower, standard]), radius);
  for (const design of [standard, lower]) {
    assert.equal(headRadius(layoutFigureSvg(design, text, { radius })), Math.round(radius * 100) / 100);
    assert.ok(projectLayout(design.xyz_mm).every(point => point.r * radius <= 290 + 1e-9));
  }
  assert.ok(figureSpacing(standard, radius) < figureSpacing(standard));
  const adaptive16 = {
    name: 'adaptive16',
    xyz_mm: standard.xyz_mm.slice(0, 16),
    region_indices: [...Array(4).fill(0), ...Array(12).fill(1)],
  };
  const sharedAdaptiveRadius = sharedPlotFigureRadius([adaptive16, standard]);
  const adaptiveSvg = plotFigureSvg(adaptive16, { ...text, subtitle: '16 electrodes' }, { radius: sharedAdaptiveRadius });
  assert.equal((adaptiveSvg.match(/<title>/g) ?? []).length, 16);
  assert.ok(adaptiveSvg.includes('>Region 1 (4)</text>') && adaptiveSvg.includes('>Region 2 (12)</text>'));
  assert.ok(plotFigureSpacing(adaptive16, sharedAdaptiveRadius) > 0);
});
