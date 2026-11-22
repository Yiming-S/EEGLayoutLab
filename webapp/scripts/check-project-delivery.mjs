import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ProjectStore } from '../server/projects/store.mjs';
import { ProjectDelivery, deliveryVersions, runtimeLockPath } from '../server/delivery/project-delivery.mjs';
import { validateResearchDelivery } from '../server/delivery/research-bundle.mjs';

void test('project delivery serves complete archives to an owner or viewer and rejects revoked access', async t => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-project-delivery-')); t.after(() => rm(root, { recursive: true, force: true }));
  const store = new ProjectStore(join(root, 'projects'));
  const created = await store.create({ title: 'Delivery study', owner_name: 'Researcher' });
  const snapshot = { schema: 'research-project-snapshot/1', kind: 'source', record_id: 'a'.repeat(64), payload: { request: { seed: 2026 }, values: [1.42e-14, -1e-20] } };
  const attached = await store.attach(created.project.id, created.access_key, { revision: 1, kind: 'source' }, snapshot, { protocol: 'source-reception/2' });
  const delivery = new ProjectDelivery({ store, versions: async () => ({ application_version: '0.1.2' }) });
  const owner = await delivery.export(created.project.id, created.access_key);
  assert.equal(validateResearchDelivery(owner), true);
  assert.deepEqual(JSON.parse(owner.files[1].content).payload, snapshot.payload);
  const share = await store.share(created.project.id, created.access_key, { revision: attached.project.revision });
  const viewer = await delivery.export(created.project.id, share.access_key);
  assert.deepEqual(viewer.files[1], owner.files[1]);
  await store.revokeShare(created.project.id, created.access_key, { revision: share.project.revision });
  await assert.rejects(delivery.export(created.project.id, share.access_key), { status: 403 });
});

void test('delivery limits memory and concurrent exports, then recovers from a failed attempt', async () => {
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  const delivery = new ProjectDelivery({ store: { async readSnapshots() { await pending; throw new Error('Archive unavailable'); } } });
  const first = delivery.export('id', 'key');
  await assert.rejects(delivery.export('id', 'key'), { status: 429 });
  release(); await assert.rejects(first, /Archive unavailable/);
  assert.equal(delivery.active, false);
  const limited = new ProjectDelivery({ maximumBytes: 100, store: { async readSnapshots(_id, _key, { maxBytes }) { assert.equal(maxBytes, 100); throw Object.assign(new Error('Size limit'), { status: 413 }); } } });
  await assert.rejects(limited.export('id', 'key'), { status: 413 });
});

void test('delivery distinguishes current host bytes from the scientific data/runtime lock and fails on missing identities', async t => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-delivery-versions-')); t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(join(root, 'data')); await mkdir(join(root, 'configs/runtime'), { recursive: true });
  await writeFile(join(root, 'data/manifest.json'), JSON.stringify({ schema_version: 'eeglayoutlab-data-bundle/1', bundle_id: 'test-model-v1' }));
  await writeFile(join(root, 'configs/runtime/manifest.json'), JSON.stringify({ schema: 'eeglayoutlab-runtime-lock/1' }));
  const value = await deliveryVersions(root);
  assert.equal(value.data_bundle_id, 'test-model-v1'); assert.match(value.data_manifest_sha256, /^[a-f0-9]{64}$/);
  assert.ok(value.source_files.every(row => !row.path.startsWith('/') && /^[a-f0-9]{64}$/.test(row.sha256)));
  await rm(join(root, 'data/manifest.json'));
  await assert.rejects(deliveryVersions(root), error => error.status === 503 && !error.message.includes(root));
});

void test('delivery names the lock of the managed runtime in use', async t => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-delivery-lock-')); t.after(() => rm(root, { recursive: true, force: true }));
  assert.equal(runtimeLockPath(root), 'configs/runtime/manifest.json');
  await mkdir(join(root, '.runtime/compute-linux-64/bin'), { recursive: true }); await writeFile(join(root, '.runtime/compute-linux-64/bin/python'), 'fixture');
  assert.equal(runtimeLockPath(root), 'configs/runtime/manifest-linux-64.json');
  await mkdir(join(root, '.runtime/simnibs-4.6.0/bin'), { recursive: true }); await writeFile(join(root, '.runtime/simnibs-4.6.0/bin/python'), 'fixture');
  assert.equal(runtimeLockPath(root), 'configs/runtime/manifest.json');
});
