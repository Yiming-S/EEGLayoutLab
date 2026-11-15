/** UI-boundary regressions for local files with valid checksums; no external scientific data. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { buildResearchDelivery } from '../server/delivery/research-bundle.mjs';
import { openResearchDelivery } from '../features/projects/research-delivery-format.mjs';

const sha = value => createHash('sha256').update(value).digest('hex');
const date = '2026-11-14T12:00:00.000Z';
const parent = 'a'.repeat(64), record = 'b'.repeat(64);
const projectId = '19d70d92-60a7-4271-9d42-ff38c8cb8881', entryId = '19d70d92-60a7-4271-9d42-ff38c8cb8882';
function sourceFixture(schema) {
  const single = schema === 'source-reception/2';
  const request = { record_id: parent, ...(single ? { mode: 'single_source', source_index: 2 } : { brain_region: 'frontal' }), waveform: 'burst', artifact_scale: 1, seed: 2026 };
  const xyz = Array.from({ length: 64 }, (_, i) => [i, i / 3, 80]);
  const metric = { nmse: 0.2, explained_energy: 0.8, brain_artifact_ratio_db: null };
  const score = (condition, artifact_scale) => ({ condition, artifact_scale, baseline: { ...metric }, candidate: { ...metric }, field_retention: 1 });
  const components = () => Object.fromEntries(['brain_uv', 'ecg_uv', 'eog_uv', 'noise_uv', 'reconstructed_brain_uv', 'reconstructed_ecg_uv', 'reconstructed_eog_uv', 'reconstructed_noise_uv']
    .map(name => [name, Array.from({ length: 64 }, () => Array(400).fill(0))]));
  return { schema_version: schema, status: 'completed', request,
    source: { ...(single ? { mode: 'single_source', generation_source_indices: [2] } : {}),
      region: 'frontal', selection_method: 'synthetic wire fixture', xyz_mm: [[0, 0, 60]], normals_mri: [[0, 0, 1]], bank_source_indices: [4098], patch_count: 1 },
    layout: { xyzMm: xyz, referenceXyzMm: xyz, regionIndices: Array(64).fill(0) },
    conditions: ['clean', 'ecg', 'eog', 'mixed'].map(condition => score(condition, condition === 'clean' ? 0 : 1)),
    strength_curve: [score('clean', 0), ...['ecg', 'eog', 'mixed'].flatMap(condition => [0, 0.5, 1, 2, 4].map(scale => score(condition, scale)))],
    waveforms: { time_s: Array.from({ length: 400 }, (_, i) => i / 100), source_nam: [Array(400).fill(0)],
      ecg_latent: Array(400).fill(0), eog_latent: Array(400).fill(0), baseline: components(), candidate: components() },
    metrics: { pure_brain_amplitude_ratio: 1 }, protocol: {}, provenance: { forward_mode: 'exact_bank' } };
}
function delivery(result) {
  const snapshot = { schema: 'research-project-snapshot/1', kind: 'source', record_id: record, payload: result };
  const snapshot_json = JSON.stringify(snapshot);
  const entry = { id: entryId, kind: 'source', record_id: record, title: 'Source wire fixture', notes: '', created_at: date,
    snapshot_sha256: sha(snapshot_json), snapshot_bytes: Buffer.byteLength(snapshot_json), summary: { protocol: result.schema_version, parent_id: parent } };
  return buildResearchDelivery({ project: { schema: 'research-project/1', id: projectId, title: 'Upload contract', owner_name: 'Fixture', notes: '',
    revision: 1, created_at: date, updated_at: date, entries: [entry] }, entries: [{ entry, snapshot_json }] }, {}, { now: () => date });
}
for (const schema of ['source-reception/1', 'source-reception/2']) {
  void test(`local upload keeps a complete ${schema} snapshot byte-identical`, async () => {
    const bundle = delivery(sourceFixture(schema)), raw = JSON.stringify(bundle, null, 2) + '\n';
    const opened = await openResearchDelivery(raw);
    assert.equal(opened.original_text, raw);
    assert.equal(opened.entries[0].snapshot_json, bundle.files.find(file => file.path.startsWith('records/')).content);
  });
  for (const [name, mutate] of [
    ['missing provenance', result => { delete result.provenance; }],
    ['missing metrics', result => { delete result.metrics; }],
    ['object patch count', result => { result.source.patch_count = { poison: 'React child' }; }],
    ['missing source waveform', result => { delete result.waveforms.source_nam; }],
    ['short source waveform', result => { result.waveforms.source_nam[0].pop(); }],
    ['object amplitude ratio', result => { result.metrics.pure_brain_amplitude_ratio = { valueOf: 0, toString: 0 }; }],
  ]) void test(`local upload rejects hash-valid ${schema} ${String(name)}`, async () => {
    const result = sourceFixture(schema); mutate(result);
    // Producer recomputes every file/record/manifest checksum for the malformed result.
    await assert.rejects(openResearchDelivery(JSON.stringify(delivery(result))));
  });
}
