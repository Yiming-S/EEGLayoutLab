import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, symlink, link, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { Readable } from 'node:stream';
import { buildReconciliation, eligibleReceipt, INTERRUPTED_MESSAGE, jsonHash } from '../server/operations/reconciliation.mjs';
import { inspectReceipt, readStrictCache, readInspectionInput, sourceFingerprint } from '../../scripts/inspect_service_reconciliation.mjs';

const request = { region_count: 2, radius_mm: 35, mode: 'preset', mask_codes: ['AL', 'AR'] };
const identity = { version: 'boundary-fixture-only', threads: 2 };
const key = jsonHash({ request, identity });
const task = (status = 'running') => ({ id: 'receipt-one', sequence: 1, kind: 'local-compute', key, request,
  owners: ['owner-a', 'owner-b'], status, annotation_refs: { 'owner-a': ['a'.repeat(64)], 'owner-b': ['b'.repeat(64)] },
  workerPid: 99999999, backendId: 'old-backend', starting: true });
const observation = () => ({ id: 'receipt-one', kind: 'local-compute', key, verdict: 'verified', status: 'completed',
  request_sha256: jsonHash(request), identity_sha256: jsonHash(identity), cache_sha256: 'f'.repeat(64),
  cache_path: 'results/v2/local_app_jobs/cache.json', finished_at: '2026-11-14T12:00:00Z', catalog: { electrode_count: 64 } });
const queue = (...tasks) => ({ version: 1, sequence: tasks.length, tasks });

void test('only running and exact restart-interrupted failed receipts are recoverable', () => {
  assert.equal(eligibleReceipt(task()), true);
  assert.equal(eligibleReceipt({ ...task('failed'), message: INTERRUPTED_MESSAGE }), true);
  for (const status of ['queued', 'cancelling', 'cancelled', 'completed', 'no_layout', 'failed']) assert.equal(eligibleReceipt(task(status)), false);
});
void test('pure repair retains owners, annotation variants, order and unknown legacy fields', () => {
  const first = { ...task('queued'), id: 'queued-first', legacy_metadata: { retained: true } };
  const source = { ...queue(first, task()), legacy_format: true };
  const before = JSON.stringify(source), result = buildReconciliation(source, [observation()]);
  assert.equal(JSON.stringify(source), before);
  assert.deepEqual(result.proposed_queue.tasks[0], first);
  const restored = result.proposed_queue.tasks[1];
  assert.equal(restored.status, 'completed'); assert.equal(restored.cached, true);
  assert.deepEqual(restored.owners, task().owners); assert.deepEqual(restored.annotation_refs, task().annotation_refs);
  for (const field of ['starting', 'workerPid', 'backendId', 'result']) assert.equal(field in restored, false);
  assert.equal(result.proposed_queue.legacy_format, true);
  assert.equal(result.proposed_queue.sequence, source.sequence);
});
void test('no_layout is valid only for the radius cache; cancellations never revive', () => {
  const noLayout = { ...observation(), status: 'no_layout' };
  assert.equal(buildReconciliation(queue(task()), [noLayout]).changes[0].to, 'no_layout');
  for (const status of ['cancelling', 'cancelled']) assert.equal(buildReconciliation(queue(task(status)), [observation()]).changes.length, 0);
  const source = { ...task(), kind: 'source-reception' };
  assert.equal(buildReconciliation(queue(source), [{ ...noLayout, kind: source.kind }]).changes.length, 0);
});
void test('missing, invalid, stale and duplicate observations cannot change receipts', () => {
  for (const value of [[], [{ ...observation(), key: '0'.repeat(64) }], [{ ...observation(), request_sha256: '0'.repeat(64) }],
    [{ ...observation(), verdict: 'retained', reason: 'bad-cache' }], [{ ...observation(), identity_sha256: 'invalid' }]]) {
    assert.equal(buildReconciliation(queue(task()), value).changes.length, 0);
  }
  assert.throws(() => buildReconciliation(queue(task()), [observation(), observation()]), /Duplicate/);
  assert.throws(() => buildReconciliation(queue(task(), task()), []), /Invalid/);
});

async function fixture(t, { storedIdentity = true } = {}) {
  const root = await mkdtemp(join(tmpdir(), 'eeg-reconcile-cache-')); t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, 'results/v2/local_app_jobs', key, 'cache.json');
  const result = { status: 'completed', request, exact: [1 / 3, -1e-18, 1.0000000000000002] };
  const cache = { key, request, result, result_sha256: jsonHash(result), finished_at: observation().finished_at,
    ...(storedIdentity ? { identity } : {}) };
  await mkdir(dirname(path), { recursive: true }); await writeFile(path, JSON.stringify(cache));
  let preparations = 0, validations = 0;
  const adapter = { prepare: async value => { preparations++; return { request: value, key, ctx: { identity } }; },
    lookup: async () => { validations++; return { hit: true, job: { key, status: 'completed', result } }; } };
  return { root, path, result, cache, adapter, options: { root, adapters: { 'local-compute': adapter }, cacheFile: () => path },
    counts: () => ({ preparations, validations }) };
}
void test('inspector validates the raw result and full current identity twice without modifying cache', async t => {
  const f = await fixture(t), before = await readFile(f.path);
  const found = await inspectReceipt(task(), f.options);
  assert.equal(found.verdict, 'verified'); assert.equal(found.identity_evidence, 'stored_identity_and_original_key_definition');
  assert.deepEqual(f.counts(), { preparations: 2, validations: 1 }); assert.deepEqual(await readFile(f.path), before);
});
void test('legacy cache without identity uses the original key definition and production validator', async t => {
  const f = await fixture(t, { storedIdentity: false });
  const found = await inspectReceipt(task(), f.options);
  assert.equal(found.verdict, 'verified'); assert.equal(found.identity_evidence, 'original_key_definition_and_production_validation');
  assert.equal('identity' in JSON.parse(await readFile(f.path, 'utf8')), false);
});
void test('rehashed but wrong stored identity and invalid result checksum are retained', async t => {
  const f = await fixture(t);
  for (const changed of [{ ...f.cache, identity: { version: 'other' } }, { ...f.cache, result_sha256: '0'.repeat(64) }]) {
    await writeFile(f.path, JSON.stringify(changed)); assert.equal((await inspectReceipt(task(), f.options)).verdict, 'retained');
  }
});
void test('a changed current key or cache between reads is never accepted', async t => {
  const f = await fixture(t); let count = 0;
  f.adapter.prepare = async value => ({ request: value, key: ++count === 1 ? key : '0'.repeat(64), ctx: { identity } });
  assert.equal((await inspectReceipt(task(), f.options)).verdict, 'retained');
  f.adapter.prepare = async value => ({ request: value, key, ctx: { identity } });
  f.adapter.lookup = async () => { await writeFile(f.path, JSON.stringify({ ...f.cache, ignored: 'concurrent change' })); return { hit: true, job: { key, status: 'completed', result: f.result } }; };
  assert.equal((await inspectReceipt(task(), f.options)).verdict, 'retained');
});
void test('cache symlinks and hardlinks are rejected even within the scientific root', async t => {
  const f = await fixture(t), other = join(f.root, 'other.json');
  await writeFile(other, JSON.stringify(f.cache)); await rm(f.path); await symlink(other, f.path);
  await assert.rejects(readStrictCache(f.root, f.path), /link/);
  await rm(f.path); await link(other, f.path);
  await assert.rejects(readStrictCache(f.root, f.path), /Invalid cache/);
});

void test('queue JSON streamed one UTF-8 byte at a time preserves scientific request names', async () => {
  const value = { queue_json: JSON.stringify({ request: { design: { name: '王祎与沈一鸣的电极布局' } } }) };
  const bytes = Buffer.from(JSON.stringify(value));
  assert.deepEqual(await readInspectionInput(Readable.from([...bytes].map(byte => Buffer.from([byte])))), value);
  await assert.rejects(readInspectionInput(Readable.from([bytes]), bytes.length - 1), /too large/);
  await assert.rejects(readInspectionInput(Readable.from([Buffer.from([0xff])])), /encoded|encoding/i);
});

void test('inspection fingerprint includes the shared source and coordinate validators', async t => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-reconcile-source-')); t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(join(root, 'webapp/server'), { recursive: true }); await mkdir(join(root, 'webapp/contracts'));
  await writeFile(join(root, 'webapp/server/example.mjs'), 'export const server = 1;');
  const source = join(root, 'webapp/contracts/source-reception.mjs'), coordinate = join(root, 'webapp/contracts/coordinate-source.mjs');
  await writeFile(source, 'export const source = 1;'); await writeFile(coordinate, 'export const coordinate = 1;');
  const before = await sourceFingerprint(root);
  await writeFile(source, 'export const source = 2;'); const afterSource = await sourceFingerprint(root);
  assert.notEqual(afterSource, before);
  await writeFile(coordinate, 'export const coordinate = 2;');
  assert.notEqual(await sourceFingerprint(root), afterSource);
});
