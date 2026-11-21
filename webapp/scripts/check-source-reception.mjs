import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { mkdtemp, readFile, writeFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import {
  LocalComputeQueue,
  computeMiddleware,
} from './local-compute-server.mjs';
import {
  SourceReceptionService,
  normalizeSourceRequest,
  validateSourceResult,
} from './source-reception-server.mjs';
import { normalizeReceptionRequest } from '../server/reception-v2-support.mjs';
import {
  combinedTrace,
  sourceKey,
  sourcePass,
  sourceExperimentLink,
  sourceBackLink,
} from '../lib/source-reception.ts';

const req = {
  record_id: 'a'.repeat(64),
  brain_region: 'frontal',
  waveform: 'burst',
  artifact_scale: 1,
  seed: 2026,
};
const layout = {
  xyzMm: Array.from({ length: 64 }, (_, i) => [i * 5, 0, 0]),
  referenceXyzMm: Array.from({ length: 64 }, (_, i) => [i * 5, 1, 0]),
  regionIndices: Array.from({ length: 64 }, (_, i) => i % 2),
};
const record = { id: req.record_id, layout };
function result() {
  const a = Array.from({ length: 64 }, () => Array(400).fill(1));
  const traces = Object.fromEntries(
    [
      'brain_uv',
      'ecg_uv',
      'eog_uv',
      'noise_uv',
      'reconstructed_brain_uv',
      'reconstructed_ecg_uv',
      'reconstructed_eog_uv',
      'reconstructed_noise_uv',
    ].map((k) => [k, a]),
  );
  const score = (condition, artifact_scale) => ({
    condition,
    artifact_scale,
    baseline: { nmse: 0.1, explained_energy: 0.9, brain_artifact_ratio_db: 10 },
    candidate: { nmse: 0.2, explained_energy: 0.8, brain_artifact_ratio_db: 5 },
    field_retention: 0.8 / 0.9,
  });
  return {
    schema_version: 'source-reception/1',
    status: 'completed',
    request: req,
    layout,
    source: { xyz_mm: [[1, 2, 3]] },
    waveforms: {
      time_s: Array.from({ length: 400 }, (_, i) => i / 50),
      baseline: traces,
      candidate: traces,
    },
    conditions: ['clean', 'ecg', 'eog', 'mixed'].map((c) =>
      score(c, c === 'clean' ? 0 : 1),
    ),
    strength_curve: [
      score('clean', 0),
      ...['ecg', 'eog', 'mixed'].flatMap((c) =>
        [0, 0.5, 1, 2, 4].map((s) => score(c, s)),
      ),
    ],
  };
}
async function fixture(options = {}) {
  const root = await mkdtemp(join(tmpdir(), 'eeg-source-test-')),
    children = [];
  const queue = new LocalComputeQueue({
    repositoryRoot: root,
    getIdentity: () => ({}),
    spawnProcess: () => assert.fail('unexpected radius worker'),
  });
  let version = 1;
  const getContext = async (r) => ({
    record,
    identity: { version },
    key: createHash('sha256')
      .update(JSON.stringify({ r, version }))
      .digest('hex'),
  });
  const source = new SourceReceptionService(queue, {
    timeoutMs: 3000,
    getContext,
    spawnProcess: (...args) => {
      const child = new EventEmitter();
      child.stdout = new PassThrough();
      child.stderr = new PassThrough();
      child.kills = [];
      child.kill = (s) => child.kills.push(s);
      child.args = args;
      children.push(child);
      return child;
    },
    ...options,
  });
  queue.sources = source;
  return {
    source,
    queue,
    root,
    children,
    bump: () => {
      version++;
    },
  };
}
async function until(p) {
  for (let i = 0; i < 200; i++) {
    if (p()) return;
    await new Promise((r) => setTimeout(r, 5));
  }
  throw new Error('timeout');
}
async function complete(f, r = result()) {
  const job = f.source.active;
  await writeFile(join(job.batch, 'result.json'), JSON.stringify(r));
  f.children.at(-1).emit('close', 0);
  await until(() => !f.source.active);
  return job;
}

void test('source request is bounded and excludes AR, shell commands, paths and arbitrary coordinates', () => {
  assert.deepEqual(normalizeSourceRequest(req), req);
  for (const change of [
    { record_id: '../../x' },
    { record_id: [req.record_id] },
    { seed: 1.5 },
    { artifact_scale: -1 },
    { brain_region: 'heart' },
    { waveform: 'unknown' },
    { ar: 90 },
    { path: '/tmp/a' },
    { xyzMm: [] },
  ])
    assert.throws(() => normalizeSourceRequest({ ...req, ...change }));
});
void test('source result rejects stale coordinates, missing/duplicate conditions and clipped negative scores', () => {
  validateSourceResult(result(), req, record);
  const moved = structuredClone(result());
  moved.layout.xyzMm[0][0] += 0.001;
  assert.throws(() => validateSourceResult(moved, req, record));
  const duplicate = result();
  duplicate.strength_curve[1] = duplicate.strength_curve[0];
  assert.throws(() => validateSourceResult(duplicate, req, record));
  const bad = result();
  bad.conditions[0].candidate.nmse = 2;
  bad.conditions[0].candidate.explained_energy = 0;
  assert.throws(() => validateSourceResult(bad, req, record));
  const negative = result();
  negative.conditions[0].candidate.nmse = 2;
  negative.conditions[0].candidate.explained_energy = -1;
  negative.conditions[0].field_retention = -1 / 0.9;
  validateSourceResult(negative, req, record);
  const low = result();
  low.conditions[0].baseline = {
    nmse: 1 - 1e-9,
    explained_energy: 1e-9,
    brain_artifact_ratio_db: null,
  };
  low.conditions[0].field_retention = null;
  validateSourceResult(low, req, record);
});
void test('waveform composition keeps brain, artifacts and electronic noise separate; AR is display-only', () => {
  const c = result().waveforms.baseline;
  assert.deepEqual(combinedTrace(c, 0, 'clean')[0], {
    brain: 1,
    artifact: 0,
    mixed: 2,
  });
  assert.deepEqual(combinedTrace(c, 0, 'mixed')[0], {
    brain: 1,
    artifact: 2,
    mixed: 4,
  });
  assert.deepEqual(combinedTrace(c, 0, 'ecg', true)[0], {
    brain: 1,
    artifact: 1,
    mixed: 3,
  });
  assert.equal(sourcePass(-0.1, 90), 'fail');
  assert.equal(sourcePass(null, 90), 'undefined');
  assert.equal(sourcePass(0.9, 90), 'pass');
  assert.equal(sourceKey({ ...req, ar: 20 }), sourceKey(req));
  const back = '/design?draft=1&r=2&radius=35&mode=preset&masks=AL,AR&ar=50';
  const u = new URL(
    sourceExperimentLink(req.record_id, 50, back),
    'http://localhost',
  );
  assert.equal(u.searchParams.get('returnTo'), back);
  assert.equal(u.searchParams.get('ar'), '50');
  const returned = new URL(sourceBackLink(back, 30), 'http://localhost');
  assert.equal(returned.searchParams.get('ar'), '30'); assert.equal(returned.searchParams.get('masks'), 'AL,AR');
});
void test('cache miss is read-only; source and radius computations share capacity in both directions', async () => {
  const f = await fixture();
  assert.equal((await f.source.lookup(req)).hit, false);
  assert.equal(f.children.length, 0);
  const releaseRadius = f.queue.executionSlot.acquire('radius');
  assert.equal((await f.source.submit(req)).busy, true);
  releaseRadius();
  const j = await f.source.submit(req);
  assert.equal(f.children.length, 1);
  assert.equal((await f.source.submit(req)).job.id, j.job.id);
  assert.equal((await f.source.submit({ ...req, seed: 5 })).busy, true);
  assert.equal(
    (
      await f.queue.submit({
        region_count: 2,
        radius_mm: 35,
        mode: 'whole_surface',
      })
    ).busy,
    true,
  );
  assert.equal(f.children[0].args[2].shell, false);
  assert.equal(f.children[0].args[2].env.OMP_NUM_THREADS, '2');
  f.source.cancel(j.job.id);
  assert.equal((await f.source.submit({ ...req, seed: 5 })).busy, true);
  f.children[0].emit('close', null);
  await until(() => !f.source.active);
  f.source.dispose();
  f.queue.dispose();
});
void test('completed result survives service restart; cache corruption and scientific identity changes miss', async () => {
  const f = await fixture();
  await f.source.submit(req);
  const job = await complete(f);
  assert.equal(job.status, 'completed');
  assert.equal((await f.source.lookup(req)).job.cached, true);
  const second = new SourceReceptionService(f.queue, {
    getContext: f.source.customContext,
    spawnProcess: () => assert.fail('cached result must not compute'),
  });
  assert.equal((await second.lookup(req)).hit, true);
  const cachePath = join(job.directory, 'cache.json'),
    cache = JSON.parse(await readFile(cachePath, 'utf8'));
  cache.result.conditions[0].field_retention = 100;
  await writeFile(cachePath, JSON.stringify(cache));
  assert.equal((await f.source.lookup(req)).hit, false);
  f.bump();
  assert.equal((await second.lookup(req)).hit, false);
  second.dispose();
  f.source.dispose();
  f.queue.dispose();
});
void test('timeout/cancellation do not free capacity before process close and never cache a score', async () => {
  const f = await fixture({ timeoutMs: 15 }),
    j = await f.source.submit(req);
  await until(() => f.children[0].kills.length);
  assert.equal(f.source.active.id, j.job.id);
  assert.equal((await f.source.submit({ ...req, seed: 4 })).busy, true);
  f.children[0].emit('close', null);
  await until(() => !f.source.active);
  assert.equal(f.source.jobs.get(j.job.id).status, 'timeout');
  assert.equal((await f.source.lookup(req)).hit, false);
  f.source.dispose();
  f.queue.dispose();
});
void test('model changes during computation and mismatched worker results cannot become cache hits', async () => {
  const f = await fixture();
  await f.source.submit(req);
  f.bump();
  const job = await complete(f);
  assert.equal(job.status, 'failed');
  assert.equal(job.result, null);
  f.source.dispose();
  f.queue.dispose();
});
void test('source API shares existing local-origin and session-token protections', async () => {
  const f = await fixture(),
    handle = computeMiddleware(f.queue);
  for (const [remote, token] of [
    ['127.0.0.1', undefined],
    ['127.0.0.1', 'bad'],
    ['192.168.1.4', f.queue.token],
  ]) {
    let code;
    await handle(
      {
        url: '/api/source-reception/jobs',
        method: 'POST',
        socket: { remoteAddress: remote },
        headers: { host: 'localhost:3000', 'x-eeg-compute-token': token },
      },
      {
        writeHead(s) {
          code = s;
        },
        end() {},
      },
      () => assert.fail(),
    );
    assert.equal(code, 403);
  }
  assert.equal(f.children.length, 0);
  f.source.dispose();
  f.queue.dispose();
});

void test('original signal download survives changed identity and rejects corrupt or mismatched saved results', async () => {
  const f = await fixture();
  await f.source.submit(req);
  const job = await complete(f), original = job.result;
  f.bump();
  assert.equal((await f.source.lookup(req)).hit, false);
  assert.deepEqual(await f.source.savedResult(job.key, req), original);
  assert.equal(f.children.length, 1);
  await assert.rejects(f.source.savedResult(job.key, { ...req, seed: 43 }), /校验失败/);
  await assert.rejects(f.source.savedResult('../../cache', req), /Invalid saved/);
  const path = join(job.directory, 'cache.json'), cache = JSON.parse(await readFile(path, 'utf8'));
  cache.result.conditions[0].field_retention = 100;
  await writeFile(path, JSON.stringify(cache));
  await assert.rejects(f.source.savedResult(job.key, req), /校验失败/);
  f.source.dispose(); f.queue.dispose();
});

void test('v2 original download requires its frozen identity layout even when the result checksum is recomputed', async () => {
  const f = await fixture();
  const request = normalizeReceptionRequest({ record_id: req.record_id, mode: 'single_source', source_index: 2,
    waveform: 'burst', artifact_scale: 1, seed: 2026 });
  const r = structuredClone(result());
  r.schema_version = 'source-reception/2'; r.request = request;
  r.source = { xyz_mm: [[1, 2, 3]], mode: 'single_source', normals_mri: [[1, 0, 0]], generation_source_indices: [2] };
  r.waveforms.source_nam = [Array(400).fill(1)];
  const identity = { layout: structuredClone(layout), version: 'old-model' };
  const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
  const key = hash({ request, identity }), directory = join(f.root, 'results/v2/source_reception_v2_jobs', key), path = join(directory, 'cache.json');
  await mkdir(directory, { recursive: true });
  const cache = { key, identity, result: r, result_sha256: hash(r) };
  await writeFile(path, JSON.stringify(cache));
  f.source.customContext = async () => assert.fail('historical download must not inspect the current model');
  assert.deepEqual(await f.source.savedResult(key, request), r);
  cache.result.layout.xyzMm[0][0] += 1.25; cache.result_sha256 = hash(cache.result);
  await writeFile(path, JSON.stringify(cache));
  await assert.rejects(f.source.savedResult(key, request), /冻结点位/);
  delete cache.identity; cache.result.layout = {}; cache.result_sha256 = hash(cache.result);
  await writeFile(path, JSON.stringify(cache));
  await assert.rejects(f.source.savedResult(key, request), /校验失败/);
  // V1 has no frozen identity in its cache format, but still requires real 64-point geometry.
  const old = result(), oldKey = 'f'.repeat(64), oldDirectory = join(f.root, 'results/v2/source_reception_jobs', oldKey);
  old.layout = {};
  await mkdir(oldDirectory, { recursive: true });
  await writeFile(join(oldDirectory, 'cache.json'), JSON.stringify({ key: oldKey, result: old, result_sha256: hash(old) }));
  await assert.rejects(f.source.savedResult(oldKey, req), /坐标或区域标签无效/);
  f.source.dispose(); f.queue.dispose();
});

void test('v1 and v2 signal simulation both refuse a layout searched under correlated noise', async () => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-source-noise-'));
  const parent = { id: req.record_id, dataset_id: 'cache', status: 'completed', layout, request: { region_count: 2 } };
  const source = new SourceReceptionService({ root, python: 'python3', library: { get: async () => parent } });
  const v2 = normalizeReceptionRequest({ record_id: req.record_id, mode: 'single_source', source_index: 2,
    waveform: 'burst', artifact_scale: 1, seed: 2026 });
  // An independent-noise parent passes the guard and only then needs the model files.
  for (const request of [normalizeReceptionRequest(req), v2])
    await assert.rejects(source.context(request), (error) => !/独立噪声/.test(error.message));
  parent.request.noise_model = { kind: 'spatial', rho: 0.5, length_mm: 20 };
  for (const request of [normalizeReceptionRequest(req), v2])
    await assert.rejects(source.context(request), /独立噪声/);
  source.dispose();
});
