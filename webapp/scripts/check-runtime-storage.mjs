import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runtimeConfig } from '../server/runtime/config.mjs';
import { RecordStore } from '../server/storage/records.mjs';

void test('explicit runtime roots preserve interpreter precedence and reject ambiguous queue paths', async () => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-runtime-'));
  try {
    assert.equal(runtimeConfig({ repositoryRoot: root, env: {} }).python, 'python3');
    const native = join(root, '.runtime/simnibs-4.6.0/bin/python');
    await mkdir(join(native, '..'), { recursive: true }); await writeFile(native, 'fixture');
    const config = runtimeConfig({ repositoryRoot: root, python: '/explicit/python', env: {} });
    assert.equal(config.python, '/explicit/python'); assert.equal(config.nativePython, native);
    assert.equal(config.queueDirectory, join(root, 'results/web-service'));
    assert.throws(() => runtimeConfig({ repositoryRoot: root, queueDirectory: 'relative/path', env: {} }));
  } finally { await rm(root, { recursive: true, force: true }); }
});

void test('the Linux table runtime is selected only when the SimNIBS runtime is absent', async () => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-runtime-'));
  try {
    const table = join(root, '.runtime/compute-linux-64/bin/python'), native = join(root, '.runtime/simnibs-4.6.0/bin/python');
    await mkdir(join(table, '..'), { recursive: true }); await writeFile(table, 'fixture');
    assert.equal(runtimeConfig({ repositoryRoot: root, env: {} }).python, table);
    assert.equal(runtimeConfig({ repositoryRoot: root, env: { EEG_COMPUTE_PYTHON: '/env/python' } }).python, '/env/python');
    assert.equal(runtimeConfig({ repositoryRoot: root, env: { EEG_COMPUTE_PYTHON: '/env/python' } }).nativePython, table);
    await mkdir(join(native, '..'), { recursive: true }); await writeFile(native, 'fixture');
    assert.equal(runtimeConfig({ repositoryRoot: root, env: {} }).nativePython, native);
  } finally { await rm(root, { recursive: true, force: true }); }
});

void test('record storage isolates checkouts and preserves the previous JSON when replacement fails', async () => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-records-'));
  const other = await mkdtemp(join(tmpdir(), 'eeg-records-other-'));
  const key = 'a'.repeat(64), id = 'b'.repeat(36);
  try {
    const store = new RecordStore(root), outside = new RecordStore(other);
    const batch = await store.createBatch('radius', key, id);
    await store.write(join(batch, 'job.json'), { status: 'running' });
    const path = store.path('radius', key, 'cache.json');
    await store.write(path, { schema: 'old/1', value: 2 });
    assert.deepEqual(await store.read(path), { schema: 'old/1', value: 2 });
    const circular = {}; circular.self = circular;
    await assert.rejects(store.write(path, circular));
    assert.equal(JSON.parse(await readFile(path, 'utf8')).value, 2);
    assert.deepEqual(await outside.keys('radius'), []);
    assert.deepEqual(await store.keys('radius'), [key]);
    assert.throws(() => store.path('radius', key, '..', '..', 'outside'));
    assert.throws(() => store.path('radius', 'invalid'));
  } finally { await rm(root, { recursive: true, force: true }); await rm(other, { recursive: true, force: true }); }
});

void test('record reads and batch creation reject symlinks to external data', async () => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-record-links-'));
  const other = await mkdtemp(join(tmpdir(), 'eeg-record-external-'));
  const key = 'a'.repeat(64);
  try {
    await writeFile(join(other, 'secret.json'), '{}');
    const store = new RecordStore(root);
    await mkdir(store.directory('radius'), { recursive: true });
    await symlink(other, store.path('radius', key));
    await assert.rejects(store.read(store.path('radius', key, 'secret.json')), /leaves/);
    await assert.rejects(store.createBatch('radius', key, 'b'.repeat(36)), /leaves/);
  } finally { await rm(root, { recursive: true, force: true }); await rm(other, { recursive: true, force: true }); }
});
