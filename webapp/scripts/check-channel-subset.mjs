import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { TEN_TWENTY, channelSubsets, covarianceMatrix, generator, greedyOrder, reconstructionError } from '../lib/channel-subset.ts';

const NAMES = ['Fp1', 'Fp2', 'F3', 'F4', 'FC1', 'FC2', 'C3', 'Cz', 'C4', 'CP1', 'P3', 'Pz'];

/** Covariance of a few spatial factors plus channel noise, as plain arrays. */
function covariance(seed, n = NAMES.length, factors = 3) {
  const random = generator(seed), normal = () => Math.sqrt(-2 * Math.log(1 - random())) * Math.cos(2 * Math.PI * random());
  const F = Array.from({ length: n }, () => Array.from({ length: factors }, normal));
  return Array.from({ length: n }, (_, i) => Array.from({ length: n }, (_, j) =>
    F[i].reduce((s, f, k) => s + f * F[j][k], 0) + (i === j ? 0.05 + 0.1 * random() : 0)));
}

/** Unexplained variance with the reconstructor fitted on the same covariance, by explicit projection on the differences. */
function bruteError(c, subset) {
  const n = c.length, s0 = subset[0], rows = subset.slice(1).map((ch) => Array.from({ length: n }, (_, j) => (j === ch) - (j === s0)));
  const centred = c.map((row) => row.map((v, j) => v - row.reduce((a, b) => a + b) / n - c.reduce((a, r) => a + r[j], 0) / n + c.flat().reduce((a, b) => a + b) / n / n));
  const DC = rows.map((d) => centred[0].map((_, j) => d.reduce((s, v, p) => s + v * centred[p][j], 0)));
  const A = DC.map((row) => rows.map((d) => d.reduce((s, v, p) => s + v * row[p], 0)));
  // Gauss–Jordan inverse of A.
  const k = A.length, inv = A.map((row, i) => [...row, ...Array.from({ length: k }, (_, j) => Number(i === j))]);
  for (let col = 0; col < k; col++) {
    const pivot = inv[col][col];
    for (let j = 0; j < 2 * k; j++) inv[col][j] /= pivot;
    for (let r = 0; r < k; r++) if (r !== col) { const f = inv[r][col]; for (let j = 0; j < 2 * k; j++) inv[r][j] -= f * inv[col][j]; }
  }
  let explained = 0;
  for (let a = 0; a < k; a++) for (let b = 0; b < k; b++) explained += inv[a][k + b] * DC[a].reduce((s, v, j) => s + v * DC[b][j], 0);
  const trace = centred.reduce((s, row, i) => s + row[i], 0);
  return 1 - explained / trace;
}

const close = (a, b, tolerance = 1e-9) => assert.ok(Math.abs(a - b) < tolerance, `${a} vs ${b}`);

void test('the error is the projection on the subset differences, whichever subset channel is the reference', () => {
  const c = covariance(1), m = covarianceMatrix(c, NAMES);
  for (const subset of [[0, 5], [2, 7, 9], [11, 0, 4, 8, 6]]) {
    const error = reconstructionError(m, m, subset);
    close(error, bruteError(c, subset));
    close(reconstructionError(m, m, [...subset].reverse()), error);
  }
  close(reconstructionError(m, m, NAMES.map((_, i) => i)), 0);
  assert.equal(reconstructionError(m, m, [3]), 1);
  // Errors are linear in a trace-normalized held-out covariance.
  const t1 = covarianceMatrix(covariance(2), NAMES), t2 = covarianceMatrix(covariance(3), NAMES);
  const both = { n: t1.n, a: t1.a.map((v, k) => (v + t2.a[k]) / 2) };
  close(reconstructionError(m, both, [1, 4, 9]), (reconstructionError(m, t1, [1, 4, 9]) + reconstructionError(m, t2, [1, 4, 9])) / 2);
});

void test('greedy selection takes the best pair, then the best next channel at each step', () => {
  const c = covariance(4), m = covarianceMatrix(c, NAMES), n = NAMES.length;
  const order = greedyOrder(m, 6);
  let best = Infinity, pair = null;
  for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) { const e = bruteError(c, [i, j]); if (e < best - 1e-12) { best = e; pair = [i, j]; } }
  assert.deepEqual(order.slice(0, 2).sort((a, b) => a - b), pair);
  for (let k = 2; k < 6; k++) {
    const errors = NAMES.map((_, ch) => order.slice(0, k).includes(ch) ? Infinity : bruteError(c, [...order.slice(0, k), ch]));
    close(errors[order[k]], Math.min(...errors), 1e-9);
  }
});

const summary = (label, c, names = NAMES, band = [1, 40]) => ({ schema: 'eeg-covariance-summary/1', label, channels: names, covariance: c,
  processing: { band_hz: band }, source: { file: `${label}.edf`, sha256: label.padEnd(64, '0') } });

void test('the report compares data, model, 10-20 and random subsets on training and held-out summaries', () => {
  const training = [summary('a', covariance(5)), summary('b', covariance(6))];
  const test = [summary('c', covariance(7)), summary('d', covariance(8).slice(1).map((row) => row.slice(1)), NAMES.slice(1))];
  const model = covariance(9);
  const prior = { schema: 'eeg-data-prior/1', id: 'p'.repeat(16), channels: NAMES.slice(0, 11), band_hz: [1, 40],
    channel_model: { data_prior: model.slice(0, 11).map((row) => row.slice(0, 11)), area_prior: covariance(10).slice(0, 11).map((row) => row.slice(0, 11)) } };
  const report = channelSubsets({ training, test, prior, counts: [4, 2], draws: 50 });
  assert.equal(report.schema, 'eeg-channel-subset/1');
  assert.deepEqual(report.counts, [2, 4]);
  assert.deepEqual(report.channels_outside_prior, ['Pz']);
  assert.deepEqual(report.universe, NAMES.slice(0, 11));
  assert.deepEqual(report.test.map((s) => s.label), ['c']);
  assert.deepEqual(report.test_skipped.map((s) => [s.label, s.missing]), [['d', ['Fp1']]]);
  assert.deepEqual(Object.keys(report.methods), ['data', 'data_prior', 'area_prior']);
  const data = report.methods.data;
  assert.deepEqual(data.counts[1].channels.slice(0, 2), data.counts[0].channels);
  assert.ok(data.counts[1].train_error < data.counts[0].train_error);
  // Data-greedy subsets are at least as good on the training data as the median random subset.
  for (const [k, row] of data.counts.entries()) assert.ok(row.train_error <= report.random.counts[k].train_error.median + 1e-12);
  assert.deepEqual(report.standard_10_20.channels, TEN_TWENTY.filter((name) => NAMES.slice(0, 11).includes(name)));
  // At the 10-20 size the data-greedy subset is the first channels of the data order, and fits the training data at least as well.
  assert.equal(report.standard_10_20.count, 8);
  assert.deepEqual(report.standard_10_20.data_same_count.channels, data.order.slice(0, 8));
  assert.ok(report.standard_10_20.data_same_count.train_error <= report.standard_10_20.train_error + 1e-12);
  assert.deepEqual(channelSubsets({ training, test, prior, counts: [4, 2], draws: 50 }).random, report.random, 'seeded');
  assert.throws(() => channelSubsets({ training, test: [summary('e', covariance(7), NAMES, [8, 30])] }), /频带/);
  assert.throws(() => channelSubsets({ training, counts: [12] }), /通道数/);
  assert.throws(() => channelSubsets({ training: [{ ...training[0], schema: 'x' }] }), /协方差摘要/);
});

void test('channels in 90% of the training summaries form the universe, and default sizes that do not fit are dropped', () => {
  const full = Array.from({ length: 9 }, (_, i) => summary(`s${i}`, covariance(20 + i)));
  const partial = summary('partial', covariance(30).slice(1).map((row) => row.slice(1)), NAMES.slice(1));
  const report = channelSubsets({ training: [...full, partial], draws: 20 });
  assert.deepEqual(report.universe, NAMES);
  assert.deepEqual(report.training_skipped.map((s) => [s.label, s.missing]), [['partial', ['Fp1']]]);
  assert.equal(report.training.length, 9);
  assert.deepEqual(report.counts, [8], 'defaults 16, 24 and 32 exceed the 12 channels');
  // With one more summary missing Fp1, it falls below 90% and leaves the universe instead.
  assert.deepEqual(channelSubsets({ training: [...full.slice(1), partial, partial], draws: 20 }).universe, NAMES.slice(1));
});

void test('the channels command writes the report from summary files and directories', () => {
  const directory = mkdtempSync(join(tmpdir(), 'eeg-channels-'));
  try {
    const cli = fileURLToPath(new URL('./eeglayoutlab.mjs', import.meta.url));
    mkdirSync(join(directory, 'held'));
    writeFileSync(join(directory, 'a.json'), JSON.stringify(summary('a', covariance(11))));
    writeFileSync(join(directory, 'held', 'b.json'), JSON.stringify(summary('b', covariance(12))));
    writeFileSync(join(directory, 'held', 'notes.json'), JSON.stringify({ schema: 'other' }));
    const out = join(directory, 'subset.json');
    const run = spawnSync(process.execPath, [cli, 'channels', join(directory, 'a.json'), '--test', join(directory, 'held'), '--counts', '3,5', '--draws', '20', '--out', out], { encoding: 'utf8' });
    assert.equal(run.status, 0, run.stderr);
    const report = JSON.parse(readFileSync(out, 'utf8'));
    assert.deepEqual([report.counts, report.test.map((s) => s.label), report.random.draws], [[3, 5], ['b'], 20]);
    assert.match(run.stdout, /^count\tdata\trandom median/);
    assert.match(spawnSync(process.execPath, [cli, 'channels', join(directory, 'a.json'), '--counts', '40', '--out', out], { encoding: 'utf8' }).stderr, /通道数/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
