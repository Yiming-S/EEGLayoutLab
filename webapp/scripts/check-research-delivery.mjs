import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { buildResearchDelivery, validateResearchDelivery } from '../server/delivery/research-bundle.mjs';

const hash = value => createHash('sha256').update(value).digest('hex');
const clone = value => JSON.parse(JSON.stringify(value));
function fixture() {
  const entries = ['layout', 'editor', 'source'].map((kind, i) => {
    const payload = { request: { seed: 2026, source_index: 2 }, coordinates: [[-112.31415926535898, 1.42e-14, 0]],
      values: [1 / 3, -1e-18, 1.0000000000000002], schema: `original-${kind}/1` };
    const snapshot = { schema: 'research-project-snapshot/1', kind, record_id: String(i + 1).repeat(64), payload };
    const snapshot_json = JSON.stringify(snapshot);
    const entry = { id: randomUUID(), kind, record_id: snapshot.record_id, title: `${kind} result`, notes: 'Saved reason',
      created_at: '2026-11-13T12:00:00Z', snapshot_sha256: hash(snapshot_json), snapshot_bytes: Buffer.byteLength(snapshot_json), summary: { protocol: payload.schema } };
    return { entry, snapshot, snapshot_json };
  });
  return { project: { schema: 'research-project/1', id: randomUUID(), title: 'Research study', owner_name: 'Researcher', notes: 'Study notes', revision: 3,
    created_at: '2026-11-13T12:00:00Z', updated_at: '2026-11-13T12:01:00Z', entries: entries.map(value => value.entry), owner_key_hash: 'private credential', viewer_key_hash: 'private share' }, entries };
}

void test('one research delivery retains exact snapshot bytes and every scientific number', () => {
  const input = fixture(), original = clone(input);
  const bundle = buildResearchDelivery(input, { application_version: '0.1.2', data_manifest_sha256: 'a'.repeat(64), env: 'private environment' });
  assert.equal(validateResearchDelivery(bundle), true);
  assert.deepEqual(input, original, 'Export mutated a scientific input or project.');
  assert.equal(bundle.records.length, 3); assert.equal(bundle.files.length, 4);
  for (const source of input.entries) {
    const file = bundle.files.find(value => value.path === `records/${source.entry.id}.json`);
    assert.equal(file.content, source.snapshot_json);
    assert.equal(hash(file.content), source.entry.snapshot_sha256);
    assert.deepEqual(JSON.parse(file.content).payload, source.snapshot.payload);
  }
  const text = JSON.stringify(bundle);
  for (const secret of ['owner_key_hash', 'viewer_key_hash', 'private credential', 'private share', 'private environment']) assert.ok(!text.includes(secret));
  assert.equal(bundle.scientific_results_recomputed, false);
  assert.match(bundle.files[0].content, /saved snapshots describe the original calculation/);
});

void test('export refuses changed scientific text, missing entries and oversized delivery', () => {
  const input = fixture(); input.entries[0].snapshot_json += ' ';
  assert.throws(() => buildResearchDelivery(input), /checksum/);
  const missing = fixture(); missing.entries.pop(); assert.throws(() => buildResearchDelivery(missing), /incomplete/);
  assert.throws(() => buildResearchDelivery(fixture(), {}, { maxBytes: 100 }), error => error.status === 413);
});

void test('identity substitution and duplicate project entries cannot pass delivery', () => {
  const input = fixture(); input.entries[0].entry.record_id = 'f'.repeat(64);
  assert.throws(() => buildResearchDelivery(input), /identity/);
  const duplicate = fixture(); duplicate.entries[1] = duplicate.entries[0];
  assert.throws(() => buildResearchDelivery(duplicate), /identity/);
});

void test('verification detects edits to payload, project annotations, host version and manifest', () => {
  const original = buildResearchDelivery(fixture());
  for (const change of [
    bundle => { bundle.files[1].content += ' '; },
    bundle => { bundle.project.title = 'Changed after export'; },
    bundle => { bundle.records[0].notes = 'Changed after export'; },
    bundle => { bundle.host.application_version = 'different'; },
    bundle => { bundle.files[1].path = '../outside.json'; },
  ]) {
    const bundle = clone(original); change(bundle);
    assert.throws(() => validateResearchDelivery(bundle), /integrity/);
  }
});

void test('empty projects yield a valid readable handoff and retain saved workflow metadata', () => {
  const input = fixture(); input.entries = []; input.project.entries = [];
  input.project.workflow = { comparison_href: '/decision?ar=90' };
  const bundle = buildResearchDelivery(input);
  assert.equal(validateResearchDelivery(bundle), true);
  assert.equal(bundle.files.length, 1);
  assert.deepEqual(bundle.project.workflow, input.project.workflow);
});

void test('a recomputed checksum does not make contradictory record paths or headers valid', () => {
  const original = buildResearchDelivery(fixture());
  for (const change of [
    bundle => { bundle.records[0].id = randomUUID(); },
    bundle => { bundle.records[0].kind = 'invented'; },
    bundle => { bundle.project.id = '../outside'; },
    bundle => { bundle.host.data_manifest_sha256 = 'missing'; },
    bundle => { bundle.exported_at = 'not a timestamp'; },
  ]) {
    const bundle = clone(original); change(bundle);
    const { manifest_sha256: _checksum, files, ...metadata } = bundle;
    bundle.manifest_sha256 = hash(JSON.stringify({ ...metadata, files: files.map(({ content: _content, ...file }) => file) }));
    assert.throws(() => validateResearchDelivery(bundle));
  }
});
