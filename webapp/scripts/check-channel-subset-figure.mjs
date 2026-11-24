import test from 'node:test';
import assert from 'node:assert/strict';
import { channelSubsets, generator } from '../lib/channel-subset.ts';
import { SUBSET_METHODS, channelSubsetFigureSvg, errorAxis, subsetCurves } from '../lib/channel-subset-figure.ts';

// Nine of these are 10-20 channels, so the 10-20 subset is smaller than the universe.
const NAMES = ['Fp1', 'Fp2', 'F3', 'F4', 'FC1', 'FC2', 'C3', 'Cz', 'C4', 'CP1', 'P3', 'Pz'];

function covariance(seed, n = NAMES.length, factors = 3) {
  const random = generator(seed), normal = () => Math.sqrt(-2 * Math.log(1 - random())) * Math.cos(2 * Math.PI * random());
  const F = Array.from({ length: n }, () => Array.from({ length: factors }, normal));
  return Array.from({ length: n }, (_, i) => Array.from({ length: n }, (_, j) =>
    F[i].reduce((s, f, k) => s + f * F[j][k], 0) + (i === j ? 0.05 + 0.1 * random() : 0)));
}
const summary = (label, c) => ({ schema: 'eeg-covariance-summary/1', label, channels: NAMES, covariance: c,
  processing: { band_hz: [1, 40] }, source: { file: `${label}.edf`, sha256: label.padEnd(64, '0') } });
const prior = { schema: 'eeg-data-prior/1', id: 'p'.repeat(16), channels: NAMES, band_hz: [1, 40],
  channel_model: { data_prior: covariance(9), area_prior: covariance(10) } };
const training = [summary('a', covariance(5)), summary('b', covariance(6))], held = [summary('c', covariance(7))];

const text = names => ({ title: 'Errors', subtitle: 'Mean held-out error', xLabel: 'Channels', yLabel: 'Unexplained variance', caption: ['A caption line.'],
  names: { data: 'Data', data_prior: 'Data prior', area_prior: 'Area prior', random: 'Random', standard: '10-20 (9)', ...names }, channels: count => `${count} channels` });

void test('the curves take held-out means when there are held-out summaries, and training errors otherwise', () => {
  const report = channelSubsets({ training, test: held, prior, counts: [6, 3], draws: 30 });
  const curves = subsetCurves(report), standard = report.standard_10_20;
  assert.equal(curves.heldOut, true);
  assert.deepEqual(curves.series.map(s => s.id), ['data', 'data_prior', 'area_prior']);
  // The data curve adds the 10-20 size, so the two subsets can be compared at the same channel count.
  assert.equal(standard.count, 9);
  assert.deepEqual(curves.series[0].points, [
    ...report.methods.data.counts.map(row => ({ count: row.count, value: row.test_error.mean })),
    { count: 9, value: standard.data_same_count.test_error.mean }]);
  assert.deepEqual(curves.series[1].points.map(p => p.count), [3, 6]);
  assert.deepEqual(curves.random, report.random.counts.map(row => ({ count: row.count, ...row.test_error_mean })));
  assert.deepEqual(curves.standard, { count: 9, value: standard.test_error.mean });

  const trained = subsetCurves(channelSubsets({ training, counts: [3, 6], draws: 30 }));
  assert.equal(trained.heldOut, false);
  assert.deepEqual(trained.series.map(s => [s.id, s.color]), [['data', SUBSET_METHODS[0].color]], 'without a prior the data curve keeps its colour');
  const plain = channelSubsets({ training, counts: [3, 6], draws: 30 });
  assert.deepEqual(trained.series[0].points.slice(0, 2), plain.methods.data.counts.map(row => ({ count: row.count, value: row.train_error })));
  assert.deepEqual(trained.random.map(r => r.median), plain.random.counts.map(row => row.train_error.median));
});

void test('the figure draws every method, the random band and the 10-20 point, each with a tooltip', () => {
  const report = channelSubsets({ training, test: held, prior, counts: [3, 6], draws: 30 });
  const svg = channelSubsetFigureSvg(report, text({ data: 'Data <b>&</b>' }));
  assert.doesNotMatch(svg, /NaN|undefined|Infinity/);
  assert.match(svg, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg"/);
  for (const method of SUBSET_METHODS) assert.match(svg, new RegExp(`stroke="${method.color}" stroke-width="2" stroke-linejoin`), method.id);
  assert.match(svg, /fill="#8a8984" fill-opacity="0\.16"\/>/, 'random P10–P90 band');
  // Points: random 2, data 3 (with the 10-20 size), each model 2, 10-20 1; plus the figure title.
  assert.equal(svg.match(/<title>/g).length, 1 + 2 + 3 + 2 + 2 + 1);
  assert.match(svg, /<title>Data &lt;b&gt;&amp;&lt;\/b&gt; · 9 channels · \d+\.\d%<\/title>/);
  assert.doesNotMatch(svg, /<b>/);
  assert.match(svg, />10-20 \(9\)<\/text>/, 'the 10-20 point is labelled directly');
  // The error axis starts at zero and reaches above every plotted value.
  const curves = subsetCurves(report), max = Math.max(...curves.random.map(r => r.p90), ...curves.series.flatMap(s => s.points.map(p => p.value)));
  const ticks = [...svg.matchAll(/text-anchor="end" font-size="11" fill="#52514e">([\d.]+)%</g)].map(m => Number(m[1]) / 100);
  assert.equal(ticks[0], 0);
  assert.ok(ticks.at(-1) >= max && ticks.length <= 6, ticks.join(','));
});

void test('one subset size draws the random spread as a range, and the axis steps stay round', () => {
  const svg = channelSubsetFigureSvg(channelSubsets({ training, counts: [4], draws: 30 }), text({}));
  assert.doesNotMatch(svg, /NaN|undefined|Infinity/);
  assert.match(svg, /stroke="#8a8984" stroke-opacity="0\.4" stroke-width="8"/);
  assert.deepEqual(errorAxis(0.44), { top: 0.5, step: 0.1 });
  assert.deepEqual(errorAxis(0.13), { top: 0.15000000000000002, step: 0.05 });
  assert.deepEqual(errorAxis(0.9), { top: 1, step: 0.2 });
  assert.deepEqual(errorAxis(0.003), { top: 0.01, step: 0.01 });
});
