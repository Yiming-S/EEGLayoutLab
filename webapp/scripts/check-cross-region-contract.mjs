// Contract tests: no native solver or existing result files are used.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { createHash } from 'node:crypto';

const load = (file) => import(new URL('../' + file, import.meta.url).href);
const { normalizeReceptionRequest, validateReceptionResult } = await load('server/reception-v2-support.mjs');
const { SOURCE_REGIONS } = await load('server/source-reception-server.mjs');
const { sourceKey, BRAIN_REGIONS } = await load('lib/source-reception.ts');
const { communityAdapters } = await load('server/community-adapters.mjs');
const { CommunityQueue } = await load('server/community-queue.mjs');

const common = { record_id: 'a'.repeat(64), waveform: 'burst', artifact_scale: 1, seed: 2026 };
const cross = (brain_regions) => ({ ...common, mode: 'cross_region', brain_regions });
const layout = {
  xyzMm: Array.from({ length: 64 }, (_, i) => [i * 5, 0, 0]),
  referenceXyzMm: Array.from({ length: 64 }, (_, i) => [i * 5, 1, 0]),
  regionIndices: Array.from({ length: 64 }, (_, i) => Number(i >= 32)),
};
const record = { id: common.record_id, layout };

function fixtureResult(regions) {
  const request = normalizeReceptionRequest(cross(regions));
  const k = request.brain_regions.length;
  const matrix = Array.from({ length: 64 }, () => Array(400).fill(1));
  const traces = Object.fromEntries(['brain_uv', 'ecg_uv', 'eog_uv', 'noise_uv',
    'reconstructed_brain_uv', 'reconstructed_ecg_uv', 'reconstructed_eog_uv',
    'reconstructed_noise_uv'].map((key) => [key, matrix]));
  const score = (condition, artifact_scale) => ({ condition, artifact_scale,
    baseline: { nmse: 0.1, explained_energy: 0.9, brain_artifact_ratio_db: 10 },
    candidate: { nmse: 0.2, explained_energy: 0.8, brain_artifact_ratio_db: 5 },
    field_retention: 0.8 / 0.9 });
  return {
    schema_version: 'source-reception/2', status: 'completed', request, layout,
    source: {
      mode: 'cross_region', region: 'cross_region', source_regions: [...request.brain_regions],
      patch_count: k, xyz_mm: Array.from({ length: k }, (_, i) => [i, 2, 3]),
      normals_mri: Array.from({ length: k }, () => [0, 0, 1]),
      generation_source_indices: Array.from({ length: k }, (_, i) => i),
      bank_source_indices: Array.from({ length: k }, (_, i) => 4096 + i),
    },
    waveforms: { time_s: Array.from({ length: 400 }, (_, i) => i / 50),
      source_nam: Array.from({ length: k }, () => Array(400).fill(1)),
      baseline: traces, candidate: traces },
    conditions: ['clean', 'ecg', 'eog', 'mixed'].map((c) => score(c, c === 'clean' ? 0 : 1)),
    strength_curve: [score('clean', 0), ...['ecg', 'eog', 'mixed'].flatMap((c) => [0, 0.5, 1, 2, 4].map((s) => score(c, s)))],
  };
}

await test('all 63 nonempty subsets canonicalize identically in UI and server', () => {
  assert.deepEqual(BRAIN_REGIONS.map(([id]) => id), SOURCE_REGIONS);
  for (let mask = 1; mask < 64; mask++) {
    const canonical = SOURCE_REGIONS.filter((_, i) => mask & (1 << i));
    const reverse = [...canonical].reverse();
    const request = normalizeReceptionRequest(cross(reverse));
    assert.deepEqual(request.brain_regions, canonical);
    assert.deepEqual(reverse, [...canonical].reverse(), 'normalization must not mutate input');
    assert.equal(sourceKey(cross(reverse)), sourceKey(cross(canonical)));
    assert.equal(sourceKey(request), JSON.stringify(request));
    assert.ok(!Object.hasOwn(request, 'brain_region'));
    assert.ok(!Object.hasOwn(request, 'source_index'));
  }
});

await test('cross-region mode rejects invalid selection shape and mixed-mode fields', () => {
  for (const regions of [undefined, null, '', 'frontal', [], ['frontal', 'frontal'],
    ['unknown'], [0], [true], [{ id: 'frontal' }], [...SOURCE_REGIONS, 'frontal']]) {
    assert.throws(() => normalizeReceptionRequest(cross(regions)));
  }
  for (const extra of [{ brain_region: 'frontal' }, { source_index: 0 }, { ar: 90 },
    { xyz_mm: [] }, { path: '/tmp/input' }]) {
    assert.throws(() => normalizeReceptionRequest({ ...cross(['frontal']), ...extra }));
  }
});

await test('legacy request keys survive and new mode, selected set, and physical conditions remain distinct', () => {
  const v1 = { record_id: common.record_id, brain_region: 'frontal', waveform: 'burst', artifact_scale: 1, seed: 2026 };
  assert.equal(sourceKey(v1), JSON.stringify(v1));
  const single = normalizeReceptionRequest({ ...common, mode: 'single_source', source_index: 0 });
  const multi = normalizeReceptionRequest({ ...common, mode: 'multi_source', brain_region: 'frontal' });
  assert.equal(sourceKey(single), JSON.stringify(single));
  assert.equal(sourceKey(multi), JSON.stringify(multi));
  const base = cross(['frontal']);
  for (const other of [v1, single, multi, cross(['central']), cross(['frontal', 'central']),
    { ...base, seed: 2027 }, { ...base, waveform: 'rhythm' }, { ...base, artifact_scale: 2 }]) {
    assert.notEqual(sourceKey(base), sourceKey(other));
  }
});

await test('K=1, 3, 6 results are accepted, while source mapping and shape corruption is rejected', () => {
  for (const regions of [SOURCE_REGIONS.slice(0, 1), SOURCE_REGIONS.slice(0, 3), SOURCE_REGIONS]) {
    const result = fixtureResult(regions);
    validateReceptionResult(result, result.request, record);
  }
  const mutations = [
    r => { r.source.patch_count = 6; },
    r => { r.source.source_regions.reverse(); },
    r => { r.source.source_regions[0] = 'unknown'; },
    r => { r.source.source_regions.pop(); },
    r => { r.source.generation_source_indices[1] = r.source.generation_source_indices[0]; },
    r => { r.source.generation_source_indices[0] = -1; },
    r => { r.source.generation_source_indices[0] = 256; },
    r => { r.source.generation_source_indices[0] = 0.5; },
    r => { r.source.generation_source_indices.pop(); },
    r => { r.source.bank_source_indices[0] += 1; },
    r => { r.source.normals_mri[0] = [0, 0, 2]; },
    r => { r.source.normals_mri.pop(); },
    r => { r.source.xyz_mm.pop(); },
    r => { r.waveforms.source_nam.pop(); },
    r => { r.waveforms.source_nam[0].pop(); },
    r => { r.waveforms.source_nam[0][0] = NaN; },
  ];
  for (const mutate of mutations) {
    const result = fixtureResult(SOURCE_REGIONS.slice(0, 3));
    mutate(result);
    assert.throws(() => validateReceptionResult(result, result.request, record), String(mutate));
  }
});

await test('real source adapter deduplicates permuted selections and restores a pending canonical request', async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'eeg-cross-fifo-'));
  const service = {
    jobs: new Map(), active: null, submitting: false,
    context: async request => ({ key: createHash('sha256').update(JSON.stringify(request)).digest('hex') }),
    lookup: async () => ({ hit: false }),
    submit: async () => assert.fail('this test must not launch a worker'),
    view: j => j,
    cancel: () => {},
  };
  const adapters = { 'source-reception': communityAdapters({ sources: service }, () => {})['source-reception'] };
  let q = new CommunityQueue({ directory, adapters, pollMs: 3600000 });
  t.after(async () => { q.dispose(); await rm(directory, { recursive: true, force: true }); });
  const a = { id: 'one', ip: '127.0.0.1' }, b = { id: 'two', ip: '127.0.0.1' };
  const first = await q.submit('source-reception', cross(['occipital', 'frontal']), a);
  const duplicate = await q.submit('source-reception', cross(['frontal', 'occipital']), b);
  assert.equal(first.job.id, duplicate.job.id);
  assert.deepEqual(q.tasks[0].request.brain_regions, ['frontal', 'occipital']);
  q.dispose();
  q = new CommunityQueue({ directory, adapters, pollMs: 3600000 });
  const restored = await q.submit('source-reception', cross(['occipital', 'frontal']), a, true);
  assert.equal(restored.job.id, first.job.id);
  assert.equal(restored.job.status, 'queued');
});

