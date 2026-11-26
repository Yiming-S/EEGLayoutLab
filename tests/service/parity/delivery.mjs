// Node reference for tests/service/test_delivery.py: webapp/server/delivery/research-bundle.mjs and
// project-delivery.mjs. Writes only <out.json>; reads the synthetic roots the spec names.
// Usage: node tests/service/parity/delivery.mjs <spec.json> <out.json>
//
// spec: {mode, cases}; the output is {node: process.version, cases: [...]}, one entry per case with its `id`.
// A failure is recorded as {ok: false, name, message, status, safe}: `safe` when Node's project middleware would
// show the message (projectSafe).
//
// Mode 'build': cases [{id, input, versions?, now?, max_bytes?}], each a JSON text: buildResearchDelivery(input,
// versions, {now: () => now, maxBytes: max_bytes}), an absent member passed as undefined (Node's default; `now`
// absent is the real clock). Recorded {ok: true, json: JSON.stringify(bundle), after: JSON.stringify(input)}.
// Mode 'validate': cases [{id, text}]: validateResearchDelivery(JSON.parse(text)), recorded {ok: true, value}.
// Mode 'search': cases [{id, href}] (a JSON text): [...new URL(href, 'http://localhost').searchParams], recorded
// {ok: true, pairs}.
// Mode 'versions': cases [{id, root, source}]: runtimeLockPath(root) as `lock`, then deliveryVersions(root, source)
// recorded {ok: true, value} or the failure (with `includes_root`: whether the message names the root).
// Mode 'fixtures': no cases. The delivery fixtures of check-research-delivery-reader.mjs ({}, {named: true},
// {legacy: true}) and check-delivery-upload-contract.mjs (source-reception/1 and /2), built by Node's builder with
// the checks' own fixture code (kept here verbatim, as they were before they read tests/service/fixtures/delivery),
// as `JSON.stringify(bundle, null, 2) + '\n'` texts by fixture name. For the upload check's hash-valid mutations,
// `mutations` records whether the delivery Node builds from the mutated result equals the base delivery mutated by
// the check's `delivery(schema, mutate)` (the snapshot changed in place, then the file, record and manifest
// checksums recomputed), compared as JSON text.
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { buildResearchDelivery, validateResearchDelivery } from '../../../webapp/server/delivery/research-bundle.mjs';
import { deliveryVersions, runtimeLockPath } from '../../../webapp/server/delivery/project-delivery.mjs';

const [specPath, outPath] = process.argv.slice(2);
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
const failure = error => ({ ok: false, name: error?.name, message: String(error?.message), status: error?.status,
  safe: Boolean(error?.projectSafe) });
const parsed = text => text === undefined ? undefined : JSON.parse(text);

function build(item) {
  const input = parsed(item.input), now = parsed(item.now), maxBytes = parsed(item.max_bytes);
  try {
    const options = { ...(item.now === undefined ? {} : { now: () => now }), maxBytes };
    const bundle = buildResearchDelivery(input, parsed(item.versions), options);
    return { ok: true, json: JSON.stringify(bundle), after: JSON.stringify(input) };
  } catch (error) { return failure(error); }
}

function validate(item) {
  let value;
  try { value = JSON.parse(item.text); } catch (error) { return { ok: false, name: 'input', message: String(error) }; }
  try { return { ok: true, value: validateResearchDelivery(value) }; } catch (error) { return failure(error); }
}

function search(item) {
  try { return { ok: true, pairs: [...new URL(parsed(item.href), 'http://localhost').searchParams] }; }
  catch (error) { return failure(error); }
}

async function versions(item) {
  const lock = runtimeLockPath(item.root);
  try { return { lock, ok: true, value: await deliveryVersions(item.root, item.source) }; }
  catch (error) { return { lock, ...failure(error), includes_root: String(error.message).includes(item.root) }; }
}

// --- The checks' fixture code, verbatim ---------------------------------------------------------------------------

const sha = value => createHash('sha256').update(value).digest('hex');

function readerFixture({ named = false, legacy = false } = {}) {
  const id = '18358bf4-143e-4431-8456-b99328462b37';
  const entryId = '18358bf4-143e-4431-8456-b99328462b38';
  const recordId = 'a'.repeat(64),
    annotationId = 'b'.repeat(64),
    date = '2026-11-14T12:00:00.000Z';
  const snapshot = {
    schema: 'research-project-snapshot/1',
    kind: 'layout',
    record_id: recordId,
    payload: {
      record: {
        id: recordId,
        layout: {
          xyzMm: Array.from({ length: 64 }, (_, i) => [i, i / 3, -i]),
          regionIndices: Array.from({ length: 64 }, (_, i) => i % 2),
        },
        metrics: {
          field_relative: 0.975,
          sensitivity_tail: null,
          localization_relative: 1.001,
          ...(legacy ? {} : { median_mm: 1.234, p90_mm: 3.456 }),
        },
      },
    },
    ...(named
      ? {
          electrode_annotation: {
            schema: 'eeg-electrode-annotation/1',
            id: annotationId,
            record_id: recordId,
            request_sha256: 'c'.repeat(64),
            electrode_names: Array.from(
              { length: 64 },
              (_, i) => `名称, "${i}"`,
            ),
          },
        }
      : {}),
  };
  const snapshot_json = JSON.stringify(snapshot, null, 2) + '\n';
  const entry = {
    id: entryId,
    kind: 'layout',
    title: 'Original layout',
    notes: '<script>never executed</script>',
    record_id: recordId,
    ...(named ? { annotation_id: annotationId } : {}),
    created_at: date,
    snapshot_bytes: Buffer.byteLength(snapshot_json),
    snapshot_sha256: sha(snapshot_json),
    summary: { protocol: 'design_evaluation' },
  };
  const project = {
    schema: 'research-project/1',
    id,
    title: 'Delivery',
    owner_name: 'Researcher',
    notes: 'Saved evidence',
    revision: 1,
    created_at: date,
    updated_at: date,
    entries: [entry],
  };
  return buildResearchDelivery(
    { project, entries: [{ entry, snapshot_json }] },
    { application_version: '0.1.2' },
    { now: () => date },
  );
}

const uploadDate = '2026-11-14T12:00:00.000Z';
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
function uploadDelivery(result) {
  const snapshot = { schema: 'research-project-snapshot/1', kind: 'source', record_id: record, payload: result };
  const snapshot_json = JSON.stringify(snapshot);
  const entry = { id: entryId, kind: 'source', record_id: record, title: 'Source wire fixture', notes: '', created_at: uploadDate,
    snapshot_sha256: sha(snapshot_json), snapshot_bytes: Buffer.byteLength(snapshot_json), summary: { protocol: result.schema_version, parent_id: parent } };
  return buildResearchDelivery({ project: { schema: 'research-project/1', id: projectId, title: 'Upload contract', owner_name: 'Fixture', notes: '',
    revision: 1, created_at: uploadDate, updated_at: uploadDate, entries: [entry] }, entries: [{ entry, snapshot_json }] }, {}, { now: () => uploadDate });
}
const MUTATIONS = [
  ['missing provenance', result => { delete result.provenance; }],
  ['missing metrics', result => { delete result.metrics; }],
  ['object patch count', result => { result.source.patch_count = { poison: 'React child' }; }],
  ['missing source waveform', result => { delete result.waveforms.source_nam; }],
  ['short source waveform', result => { result.waveforms.source_nam[0].pop(); }],
  ['object amplitude ratio', result => { result.metrics.pure_brain_amplitude_ratio = { valueOf: 0, toString: 0 }; }],
];
// check-delivery-upload-contract.mjs's delivery(schema, mutate) over the committed base fixture (its `base`).
function rehashed(base, mutate) {
  const bundle = JSON.parse(base), file = bundle.files[1], snapshot = JSON.parse(file.content);
  mutate(snapshot.payload);
  file.content = JSON.stringify(snapshot);
  file.size_bytes = Buffer.byteLength(file.content);
  file.sha256 = sha(file.content);
  bundle.records[0].snapshot_sha256 = file.sha256;
  const { manifest_sha256: _checksum, files, ...metadata } = bundle;
  bundle.manifest_sha256 = sha(JSON.stringify({ ...metadata,
    files: files.map(({ content: _content, ...rest }) => rest) }));
  return bundle;
}

function fixtures() {
  const pretty = bundle => JSON.stringify(bundle, null, 2) + '\n';
  const texts = { reader: pretty(readerFixture()), 'reader-named': pretty(readerFixture({ named: true })),
    'reader-legacy': pretty(readerFixture({ legacy: true })) };
  const mutations = [];
  for (const schema of ['source-reception/1', 'source-reception/2']) {
    const name = `upload-${schema.replace('/', '-')}`;
    texts[name] = pretty(uploadDelivery(sourceFixture(schema)));
    for (const [label, mutate] of MUTATIONS) {
      const result = sourceFixture(schema); mutate(result);
      const equal = JSON.stringify(uploadDelivery(result)) === JSON.stringify(rehashed(texts[name], mutate));
      mutations.push({ schema, label, equal });
    }
  }
  return { texts, mutations };
}

const out = { node: process.version, cases: [] };
if (spec.mode === 'fixtures') Object.assign(out, fixtures());
for (const item of spec.cases ?? []) {
  const modes = { build, validate, search, versions };
  if (!Object.hasOwn(modes, spec.mode)) throw new Error(`Unknown mode ${spec.mode}`);
  const value = await modes[spec.mode](item);
  out.cases.push({ id: item.id, ...value });
}
writeFileSync(outPath, JSON.stringify(out));
