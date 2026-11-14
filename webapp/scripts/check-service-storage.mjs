import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createLocalComputeService, LocalComputeQueue } from '../server/local-compute-server.mjs';
import { DesignEvaluationService } from '../server/design-evaluation-server.mjs';
import { SourceReceptionService } from '../server/source-reception-server.mjs';
import { ElectrodeEditorService } from '../server/electrode-editor-server.mjs';

void test('service factory shares one record store and honors a paused custom queue directory', async () => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-service-config-'));
  const queueDirectory = join(root, 'isolated-queue');
  let service;
  try {
    service = createLocalComputeService(root, { queueDirectory, initialMaintenance: true, getIdentity: () => ({}) });
    const { queue, scheduler } = service;
    assert.equal(queue.runtime.queueDirectory, queueDirectory);
    assert.equal(scheduler.directory, queueDirectory);
    assert.equal(scheduler.executionSlot, queue.executionSlot);
    for (const workflow of [queue.designTests, queue.sources, queue.editor]) assert.equal(workflow.store, queue.store);
    assert.equal(queue.designTests.recordKind, 'design');
    assert.equal(queue.editor.recordKind, 'editor');
    assert.equal(scheduler.maintenance, true);
    assert.equal(queue.executionSlot.paused, true);
    const result = await queue.submit({ region_count: 2, radius_mm: 35, mode: 'whole_surface' });
    assert.deepEqual(result, { busy: true, maintenance: true });
    assert.equal(JSON.parse(await readFile(join(queueDirectory, 'queue.json'), 'utf8')).maintenance, true);
  } finally { await service?.dispose(); await rm(root, { recursive: true, force: true }); }
});

void test('native services preserve managed interpreter precedence over radius overrides', async () => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-service-python-'));
  const native = join(root, '.runtime/simnibs-4.6.0/bin/python');
  const services = [];
  try {
    await mkdir(join(native, '..'), { recursive: true }); await writeFile(native, 'fixture');
    const queue = new LocalComputeQueue({ repositoryRoot: root, python: '/explicit/python', getIdentity: () => ({}) });
    services.push(queue);
    assert.equal(queue.python, '/explicit/python');
    for (const Constructor of [DesignEvaluationService, SourceReceptionService, ElectrodeEditorService]) {
      const service = new Constructor(queue); services.push(service);
      assert.equal(service.python, native);
    }
    assert.equal(new SourceReceptionService({ root, python: '/fallback/python' }).python, native);
  } finally { for (const service of services) service.dispose(); await rm(root, { recursive: true, force: true }); }
});

void test('source identity uses its injected native context without a design service', async () => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-source-native-context-'));
  const record = { id: 'a'.repeat(64), dataset_id: 'strict_area', status: 'completed', layout: { id: 'layout' }, provenance: { file: 'frozen.json' } };
  const runtimeHash = 'b'.repeat(64), forward = { schema: 'design-evaluation-cache/1', digests: { fixture: 'c'.repeat(64) }, python: process.execPath, threads: 1 };
  const queue = { root, python: process.execPath, library: { get: async () => record } };
  Object.defineProperty(queue, 'designTests', { get() { throw new Error('Source workflow accessed the design service'); } });
  let nativeCalls = 0;
  const source = new SourceReceptionService(queue, { nativeContext: request => {
    assert.deepEqual(request, {}); nativeCalls++; return { identity: forward };
  } });
  source.inputs.digest = async () => 'd'.repeat(64);
  try {
    await mkdir(join(root, 'scripts'));
    await writeFile(join(root, 'scripts/inspect_reception_runtime.py'), `process.stdout.write(JSON.stringify({ schema: 'reception-runtime-digest/1', sha256: '${runtimeHash}' }));`);
    const request = { record_id: record.id, mode: 'single_source' };
    const context = await source.context(request);
    assert.equal(nativeCalls, 1);
    assert.deepEqual(context.identity.forward, forward);
    assert.equal(context.identity.numerical_runtime_sha256, runtimeHash);
    assert.equal(context.key, createHash('sha256').update(JSON.stringify({ request, identity: context.identity })).digest('hex'));
  } finally { source.dispose(); await rm(root, { recursive: true, force: true }); }
});
