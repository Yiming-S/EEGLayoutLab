import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, rm, symlink, realpath, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { ProjectStore, PROJECT_LIMITS } from '../server/projects/store.mjs';

const key = 'a'.repeat(64), hash = value => createHash('sha256').update(value).digest('hex');
const scientific = () => ({ request: { seed: 2026, xyz_mm: [[-112.31415926535898, 1e-14, 0]] }, waveforms: { data: [1.25e-12, -9.125e-10] }, provenance: { code_sha256: 'b'.repeat(64), thread_count: 1 }, qa: { residual: 4.16e-13 } });
const snapshot = () => ({ schema: 'research-project-snapshot/1', kind: 'source', record_id: key, payload: scientific() });
async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'eeg-project-')); t.after(() => rm(root, { recursive: true, force: true }));
  const store = new ProjectStore(join(root, 'projects'));
  const created = await store.create({ title: 'Study A', owner_name: 'Researcher', notes: 'Original study' });
  return { root, store, ...created };
}

void test('project comparison settings retain exact requirements without changing archived calculations', async t => {
  const { store, project, access_key } = await fixture(t);
  const saveLayout = (revision, record_id) => store.attach(project.id, access_key, { revision, kind: 'layout' },
    { schema: 'research-project-snapshot/1', kind: 'layout', record_id, payload: scientific() }, { protocol: 'cache', electrode_count: 64 });
  const first = await saveLayout(1, '1'.repeat(64)), second = await saveLayout(2, '2'.repeat(64));
  const before = await store.readSnapshots(project.id, access_key);
  const workflow = { reference_entry_id: first.entry.id, candidate_entry_id: second.entry.id,
    comparison_href: `/decision?a=${'1'.repeat(64)}&b=${'2'.repeat(64)}&ar=87&thresholdMode=custom&sensitivity=63&localization=52&p90=28.5` };
  const saved = await store.patch(project.id, access_key, { revision: 3, workflow });
  assert.deepEqual(saved.project.workflow, workflow);
  assert.deepEqual((await store.readSnapshots(project.id, access_key)).entries, before.entries);
  await store.detach(project.id, access_key, first.entry.id, 4);
  const remaining = (await store.get(project.id, access_key)).project;
  assert.equal(remaining.workflow.reference_entry_id, null);
  assert.equal(remaining.workflow.candidate_entry_id, second.entry.id);
  assert.equal(remaining.workflow.comparison_href, null);
});

void test('comparison settings reject external links, foreign layouts, unsupported parameters and fake scores', async t => {
  const { store, project, access_key } = await fixture(t);
  const first = await store.attach(project.id, access_key, { revision: 1, kind: 'layout' },
    { schema: 'research-project-snapshot/1', kind: 'layout', record_id: key, payload: scientific() }, { protocol: 'cache' });
  const second = await store.attach(project.id, access_key, { revision: 2, kind: 'layout' },
    { schema: 'research-project-snapshot/1', kind: 'layout', record_id: 'b'.repeat(64), payload: scientific() }, { protocol: 'cache' });
  const valid = { reference_entry_id: first.entry.id, candidate_entry_id: second.entry.id, comparison_href: `/decision?a=${key}&b=${'b'.repeat(64)}&ar=90` };
  for (const value of [
    { ...valid, reference_entry_id: '00000000-0000-4000-8000-000000000001' },
    { ...valid, candidate_entry_id: first.entry.id },
    { ...valid, comparison_href: 'https://example.org/decision' },
    { ...valid, comparison_href: valid.comparison_href + '&score=1' },
    { ...valid, comparison_href: valid.comparison_href + '&ar=80' },
    { ...valid, comparison_href: valid.comparison_href.replace('ar=90', 'ar=101') },
    { ...valid, comparison_href: valid.comparison_href + '&p90=-1' },
    { ...valid, comparison_href: valid.comparison_href.replace('ar=90', 'ar=5') },
    { ...valid, comparison_href: valid.comparison_href + '&thresholdMode=joint&sensitivity=42' },
    { ...valid, comparison_href: valid.comparison_href + '&thresholdMode=joint&p90=20' },
    { ...valid, comparison_href: 0 },
    { ...valid, scientific_result: { score: 1 } },
  ]) await assert.rejects(store.patch(project.id, access_key, { revision: 3, workflow: value }), { status: 400 });
  assert.equal((await store.get(project.id, access_key)).project.revision, 3);
});

void test('projects survive restart and cross-browser credentials without storing raw keys', async t => {
  const { store, project, access_key, root } = await fixture(t);
  assert.equal(access_key.length, 64);
  const metadata = await readFile(join(root, 'projects', project.id, 'project.json'), 'utf8');
  assert.ok(!metadata.includes(access_key)); assert.ok(metadata.includes(hash(access_key)));
  const restarted = new ProjectStore(join(root, 'projects'));
  assert.deepEqual(await restarted.get(project.id, access_key), { project, role: 'owner' });
  await assert.rejects(restarted.get(project.id, '0'.repeat(64)), { status: 403 });
  assert.equal(store.directory, join(await realpath(root), 'projects'));
});

void test('an interrupted atomic snapshot write does not prevent recovery or become a scientific result', async t => {
  const { store, project, access_key } = await fixture(t);
  const directory = join(store.directory, project.id, 'snapshots');
  const orphan = join(directory, `${'d'.repeat(64)}.json.${randomUUID()}.tmp`);
  await writeFile(orphan, '{"incomplete":', { mode: 0o600 });
  const restarted = new ProjectStore(store.directory);
  const attached = await restarted.attach(project.id, access_key, { revision: 1, kind: 'source' }, snapshot(), { protocol: 'source-reception/2' });
  assert.deepEqual((await restarted.getEntry(project.id, access_key, attached.entry.id)).snapshot, snapshot());
  assert.equal(await readFile(orphan, 'utf8'), '{"incomplete":');
  await writeFile(join(directory, 'unexpected-file'), 'unrelated');
  const next = snapshot(); next.record_id = 'e'.repeat(64);
  await assert.rejects(restarted.attach(project.id, access_key, { revision: 2, kind: 'source' }, next, {}), { status: 409 });
  assert.equal((await restarted.get(project.id, access_key)).project.revision, 2);
});

void test('read-only sharing can be rotated and revoked without changing scientific copies', async t => {
  const { store, project, access_key } = await fixture(t);
  const shared = await store.share(project.id, access_key, { revision: 1 });
  assert.equal((await store.get(project.id, shared.access_key)).role, 'viewer');
  await assert.rejects(store.patch(project.id, shared.access_key, { revision: 2, title: 'Write blocked' }), { status: 403 });
  const rotated = await store.share(project.id, access_key, { revision: 2 });
  await assert.rejects(store.get(project.id, shared.access_key), { status: 403 });
  await store.revokeShare(project.id, access_key, { revision: 3 });
  await assert.rejects(store.get(project.id, rotated.access_key), { status: 403 });
  assert.equal((await store.get(project.id, access_key)).project.revision, 4);
});

void test('rename and entry notes preserve exact archived scientific JSON and checksums', async t => {
  const { store, project, access_key, root } = await fixture(t), original = snapshot();
  const attached = await store.attach(project.id, access_key, { revision: 1, kind: 'source', receipt_id: 'unused-by-store', title: 'Signal A' }, original, { protocol: 'source-reception/2', electrode_count: 64 });
  original.payload.waveforms.data[0] = 999;
  const saved = await store.getEntry(project.id, access_key, attached.entry.id);
  assert.deepEqual(saved.snapshot.payload, scientific());
  await store.patch(project.id, access_key, { revision: 2, title: 'Renamed study', notes: 'Keep original signal' });
  await store.patchEntry(project.id, access_key, attached.entry.id, { revision: 3, title: 'Renamed signal', notes: 'Selected for comparison' });
  const archived = await store.readSnapshots(project.id, access_key);
  assert.equal(archived.entries[0].snapshot_json, JSON.stringify(snapshot()));
  assert.equal(hash(archived.entries[0].snapshot_json), attached.entry.snapshot_sha256);
  assert.deepEqual(archived.entries[0].snapshot.payload, scientific());
  const persisted = await readFile(join(root, 'projects', project.id, 'snapshots', attached.entry.snapshot_sha256 + '.json'), 'utf8');
  assert.equal(persisted, archived.entries[0].snapshot_json);
  assert.ok(!JSON.stringify(archived.project).includes('owner_key_hash'));
});

void test('snapshot persistence precedes metadata and queued mutations enforce revisions', async t => {
  const { store, project, access_key } = await fixture(t);
  const results = await Promise.allSettled([
    store.patch(project.id, access_key, { revision: 1, title: 'First writer' }),
    store.patch(project.id, access_key, { revision: 1, title: 'Second writer' }),
  ]);
  assert.equal(results.filter(result => result.status === 'fulfilled').length, 1);
  assert.equal(results.find(result => result.status === 'rejected').reason.status, 409);
  await store.flush(); assert.equal(store.pendingWrites, 0);
  const current = await store.get(project.id, access_key);
  assert.equal(current.project.title, 'First writer'); assert.equal(current.project.revision, 2);
});

void test('detaching entries never deletes original snapshots or scientific files', async t => {
  const { store, project, access_key, root } = await fixture(t);
  const attached = await store.attach(project.id, access_key, { revision: 1, kind: 'source' }, snapshot(), { protocol: 'source-reception/2' });
  await store.detach(project.id, access_key, attached.entry.id, 2);
  assert.deepEqual((await store.get(project.id, access_key)).project.entries, []);
  assert.equal((await readdir(join(root, 'projects', project.id, 'snapshots'))).length, 1);
  await assert.rejects(store.getEntry(project.id, access_key, attached.entry.id), { status: 404 });
});

void test('corrupt metadata, snapshots, symlinks and traversal fail closed', async t => {
  const { store, project, access_key, root } = await fixture(t);
  const attached = await store.attach(project.id, access_key, { revision: 1, kind: 'source' }, snapshot(), { protocol: 'source-reception/2' });
  const path = join(root, 'projects', project.id, 'snapshots', attached.entry.snapshot_sha256 + '.json');
  await writeFile(path, JSON.stringify({ ...snapshot(), payload: { altered: true } }));
  await assert.rejects(store.getEntry(project.id, access_key, attached.entry.id), { status: 409 });
  await rm(path); await symlink(join(root, 'projects', project.id, 'project.json'), path);
  await assert.rejects(store.getEntry(project.id, access_key, attached.entry.id), { status: 409 });
  await assert.rejects(store.get('../project.json', access_key), { status: 400 });
  const metadata = join(root, 'projects', project.id, 'project.json'); await writeFile(metadata, '{"broken":true}');
  await assert.rejects(store.get(project.id, access_key), { status: 409 });
});

void test('project root symlinks are rejected rather than followed', async t => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-project-link-')); t.after(() => rm(root, { recursive: true, force: true }));
  await symlink(root, join(root, 'projects'));
  const store = new ProjectStore(join(root, 'projects'));
  await assert.rejects(store.create({ title: 'Blocked', owner_name: 'Researcher' }), { status: 409 });
});

void test('bounded snapshots and export preflight reject large data before loading payloads', async t => {
  const { store, project, access_key } = await fixture(t);
  const huge = snapshot(); huge.payload.large = 'x'.repeat(PROJECT_LIMITS.snapshotBytes);
  assert.throws(() => store.attach(project.id, access_key, { revision: 1, kind: 'source' }, huge, {}), { status: 413 });
  await store.attach(project.id, access_key, { revision: 1, kind: 'source' }, snapshot(), { protocol: 'source-reception/2' });
  await assert.rejects(store.readSnapshots(project.id, access_key, { maxBytes: 10 }), { status: 413 });
  assert.equal((await store.get(project.id, access_key)).project.entries.length, 1);
});

void test('shutdown rejects new writes while flushing already accepted metadata writes', async t => {
  const { store, project, access_key } = await fixture(t);
  const accepted = store.patch(project.id, access_key, { revision: 1, notes: 'Final accepted note' });
  store.close();
  await assert.rejects(store.patch(project.id, access_key, { revision: 1, title: 'Too late' }), { status: 503 });
  await accepted; await store.flush();
  assert.equal(store.pendingWrites, 0);
  assert.equal((await store.get(project.id, access_key)).project.notes, 'Final accepted note');
});
