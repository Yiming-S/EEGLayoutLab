import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { createServer } from 'node:http';
import { once } from 'node:events';
import {
  mkdtemp,
  mkdir,
  readFile,
  realpath,
  rm,
  symlink,
  writeFile,
} from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { CommunityQueue } from '../server/community-queue.mjs';
import { RobustnessStudyService } from '../server/studies/service.mjs';
import { StudyStore } from '../server/studies/store.mjs';
import {
  STUDY_LIMITS,
  aggregateStudy,
  empiricalSummary,
  normalizeStudyInput,
  summarizeStudyCase,
} from '../server/studies/protocol.mjs';
import {
  normalizeDesignRequest,
  validateDesignResult,
} from '../server/design-evaluation-server.mjs';
import { createAccessPolicy } from '../server/http/access-policy.mjs';
import { sendJson } from '../server/http/responses.mjs';

const hash = (value) =>
  createHash('sha256')
    .update(
      typeof value === 'string' || Buffer.isBuffer(value)
        ? value
        : JSON.stringify(value),
    )
    .digest('hex');
const owner = { id: 'a'.repeat(64), ip: 'local-a' },
  stranger = { id: 'b'.repeat(64), ip: 'local-b' };
const design = {
  schema: 'eeg-electrode-design/1',
  coordinate_system: 'ernie_native_mm',
  unit: 'mm',
  name: 'Original scientific name',
  xyz_mm: Array.from({ length: 64 }, (_, i) => [
    (i % 8) * 6,
    Math.floor(i / 8) * 6,
    0,
  ]),
  region_indices: Array.from({ length: 64 }, (_, i) => i % 2),
};
const input = (seeds = [42, 43], extra = {}) => ({
  protocol: 'noise_seeds',
  design,
  cases: seeds.map((seed) => ({ seed, radius_mm: 6 })),
  ...extra,
});
const resultFor = (request) => ({
  schema: 'design-evaluation/1',
  status: 'completed',
  request,
  forward_mode: request.head_id ? 'head_scalp_node_table' : 'cached_fem',
  nominal: {
    field_relative: 0.9,
    field_absolute: 0.81,
    reference_field_absolute: 0.9,
    sensitivity_tail: 0.8,
    localization_relative: 0.7,
    median_mm: 10,
    p90_mm: 20,
    reference_median_mm: 9,
    reference_p90_mm: 18,
  },
  evaluated_xyz_mm: request.design.xyz_mm,
  projection_max_mm: 0,
  trials: [],
  provenance: {
    candidate_count: 64,
    original_values: [1 / 3, -1e-18, 1.0000000000000002],
  },
});
const deferred = () => {
  let resolve;
  const promise = new Promise((r) => {
    resolve = r;
  });
  return { promise, resolve };
};
async function fixture(
  t,
  {
    cached = true,
    studyLimits,
    beforeWrite = async () => {},
    beforeNewWork = async () => {},
  } = {},
) {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'eeg-studies-'))),
    directory = join(root, 'queue'),
    token = 'c'.repeat(64);
  let version = 1,
    holdPrepare = null,
    preparations = 0,
    starts = 0;
  // Like scientificContext, a head request adds its own package to the identity.
  const identity = (request) => ({
    protocol: 'unchanged-design-evaluation/1',
    version,
    ...(request?.head_id ? { head_id: request.head_id } : {}),
  });
  const cachePath = (key) =>
    join(root, 'results/v2/design_evaluation_jobs', key, 'cache.json');
  const adapter = {
    async prepare(raw) {
      preparations++;
      if (holdPrepare) await holdPrepare.promise;
      const request = normalizeDesignRequest(
          raw?.schema === 'design-submission/1' ? raw.request : raw,
        ),
        ctx = { identity: identity(request) };
      return { request, key: hash({ request, identity: ctx.identity }), ctx };
    },
    async lookup(prepared) {
      try {
        const cache = JSON.parse(
          await readFile(cachePath(prepared.key), 'utf8'),
        );
        validateDesignResult(cache.result, prepared.request);
        return {
          hit: true,
          job: {
            id: randomUUID(),
            key: prepared.key,
            request: prepared.request,
            status: 'completed',
            cached: true,
            result: cache.result,
          },
        };
      } catch {
        return { hit: false };
      }
    },
    start() {
      starts++;
      assert.fail('Studies unit tests must not launch a scientific worker');
    },
    busy: () => false,
    get: () => null,
    cancel() {},
  };
  const queue = { root, runtime: { queueDirectory: directory }, token };
  const scheduler = new CommunityQueue({
    directory,
    adapters: { 'design-evaluation': adapter },
    pollMs: 3600000,
    beforeNewWork,
  });
  const store = new StudyStore(join(directory, 'studies'), {
    beforeWrite,
    ...(studyLimits ? { limits: studyLimits } : {}),
  });
  let service = new RobustnessStudyService({
    queue,
    scheduler,
    store,
    guard: createAccessPolicy().guard,
    tokenMatches: (a, b) => a === b,
    send: sendJson,
    pollMs: 3600000,
  });
  const seedCache = async (request) => {
    const ctx = { identity: identity(request) },
      key = hash({ request, identity: ctx.identity }),
      result = resultFor(request),
      cache = {
        key,
        identity: ctx.identity,
        result,
        result_sha256: hash(result),
        finished_at: '2026-11-14T12:00:00.000Z',
      };
    const path = cachePath(key);
    await mkdir(dirname(path), { recursive: true });
    const bytes = JSON.stringify(cache, null, 2) + '\n';
    await writeFile(path, bytes);
    return { key, cache, bytes, path };
  };
  if (cached)
    for (const request of normalizeStudyInput(input()).requests)
      await seedCache(request);
  await service.ready();
  t.after(async () => {
    service.stop();
    await service.flush();
    service.close();
    scheduler.dispose();
    await rm(root, { recursive: true, force: true });
  });
  return {
    root,
    queue,
    scheduler,
    store,
    adapter,
    cachePath,
    seedCache,
    get service() {
      return service;
    },
    async restart() {
      service.stop();
      await service.flush();
      service.close();
      service = new RobustnessStudyService({
        queue,
        scheduler,
        store: new StudyStore(store.directory, { beforeWrite }),
        guard: createAccessPolicy().guard,
        tokenMatches: (a, b) => a === b,
        send: sendJson,
        pollMs: 3600000,
      });
      await service.ready();
      return service;
    },
    setVersion(value) {
      version = value;
    },
    setPrepareHold(value) {
      holdPrepare = value;
    },
    counts: () => ({ preparations, starts }),
  };
}

void test('study protocols preserve original normalized requests and keep labels outside scientific identity', () => {
  const names = Array.from({ length: 64 }, (_, i) => `Channel ${i + 1}`),
    normalized = normalizeStudyInput(
      input([42], { design: { ...design, electrode_names: names } }),
    );
  assert.deepEqual(normalized.requests, [
    normalizeDesignRequest({
      action: 'evaluate',
      design,
      radius_mm: 6,
      seed: 42,
    }),
  ]);
  assert.deepEqual(normalized.annotation.electrode_names, names);
  assert.equal(normalized.design.electrode_names, undefined);
  const grid = normalizeStudyInput(
    input([42], {
      protocol: 'grid_displacements',
      cases: [
        { seed: 42, radius_mm: 3 },
        { seed: 42, radius_mm: 10 },
      ],
    }),
  );
  assert.deepEqual(
    grid.requests.map((r) => [r.action, r.seed, r.radius_mm]),
    [
      ['perturb', 42, 3],
      ['perturb', 42, 10],
    ],
  );
  for (const invalid of [
    input([42, 42]),
    input(Array.from({ length: 13 }, (_, i) => i)),
    input([42], {
      cases: [
        { seed: 42, radius_mm: 3 },
        { seed: 43, radius_mm: 6 },
      ],
    }),
    input([42], { cases: [{ seed: -1, radius_mm: 6 }] }),
  ])
    assert.throws(() => normalizeStudyInput(invalid));
});

void test('cross-head studies evaluate one head per case at one radius without conductivity scenarios', () => {
  const heads = (cases, extra = {}) => input([], { protocol: 'heads', cases, ...extra });
  const study = normalizeStudyInput(
    heads([
      { head_id: 'ernie_xh', seed: 42, radius_mm: 6 },
      { head_id: 'ixi002', seed: 42, radius_mm: 6 },
    ]),
  );
  assert.deepEqual(
    study.requests.map((r) => [r.action, r.head_id, r.seed, r.radius_mm]),
    [
      ['evaluate', 'ernie_xh', 42, 6],
      ['evaluate', 'ixi002', 42, 6],
    ],
  );
  assert.deepEqual(
    study.requests[1],
    normalizeDesignRequest({ action: 'evaluate', design, radius_mm: 6, seed: 42, head_id: 'ixi002' }),
  );
  assert.equal(aggregateStudy('heads', []).interpretation, 'cross_head_empirical_cases');
  assert.equal(aggregateStudy('noise_seeds', []).interpretation, 'Ernie_within_model_empirical_cases');
  for (const invalid of [
    heads([{ head_id: 'ixi002', seed: 42, radius_mm: 6 }, { head_id: 'ixi002', seed: 43, radius_mm: 6 }]),
    heads([{ head_id: 'ixi002', seed: 42, radius_mm: 6 }, { head_id: 'ixi012', seed: 42, radius_mm: 3 }]),
    heads([{ head_id: 'ernie_xh', seed: 42, radius_mm: 6 }, { head_id: 'ixi002', seed: 7, radius_mm: 6 }]),
    heads([{ seed: 42, radius_mm: 6 }]),
    heads([{ head_id: '', seed: 42, radius_mm: 6 }]),
    heads([{ head_id: 'IXI/002', seed: 42, radius_mm: 6 }]),
    heads([{ head_id: 'ixi002', seed: 42, radius_mm: 6 }], { conductivity_scenario: 'skull_x2' }),
    input([42], { cases: [{ head_id: 'ixi002', seed: 42, radius_mm: 6 }] }),
  ])
    assert.throws(() => normalizeStudyInput(invalid));
});

void test('empirical summaries use case weights and retain rejected trials and failure counts', () => {
  const simple = empiricalSummary([0, 10, 20, 30]);
  assert.equal(simple.n, 4);
  assert.equal(simple.median, 15);
  assert.ok(Math.abs(simple.p10 - 3) <= 4 * Number.EPSILON);
  assert.equal(simple.p90, 27);
  assert.deepEqual(empiricalSummary([null, NaN]), {
    n: 0,
    median: null,
    p10: null,
    p90: null,
  });
  const trial = (value, status = 'completed') => ({
    status,
    field_relative: value,
    fixed_estimator_field_relative: value,
    sensitivity_tail: value,
  });
  const a = summarizeStudyCase({
    nominal: { field_relative: 0.5 },
    trials: [trial(0), trial(0), trial(0), trial(0)],
  });
  const b = summarizeStudyCase({
    nominal: { field_relative: 1 },
    trials: [
      trial(100),
      trial(null, 'geometry_rejected'),
      trial(null, 'geometry_rejected'),
      trial(null, 'geometry_rejected'),
    ],
  });
  const cases = [
      { status: 'completed', request: { radius_mm: 3 }, summary: a },
      { status: 'completed', request: { radius_mm: 3 }, summary: b },
      { status: 'failed', request: { radius_mm: 3 } },
      { status: 'cancelled', request: { radius_mm: 3 } },
    ],
    before = JSON.stringify(cases);
  const summary = aggregateStudy('grid_displacements', cases);
  assert.equal(
    summary.groups[0].trial_case_medians.field_relative.median,
    50,
    'Do not pool five trials and weight the first case four times.',
  );
  assert.equal(summary.completed_cases, 2);
  assert.equal(summary.failed_cases, 1);
  assert.equal(summary.cancelled_cases, 1);
  assert.equal(b.rejected_trials, 3);
  assert.equal(b.trials.length, 4);
  assert.equal(JSON.stringify(cases), before);
});

void test('create and reads launch no jobs, completed cases archive exact original caches and survive receipt cleanup', async (t) => {
  const f = await fixture(t),
    created = await f.service.create(input(), owner),
    id = created.study.id;
  assert.equal(created.study.status, 'draft');
  assert.equal(f.scheduler.tasks.length, 0);
  await f.service.get(id, owner);
  await f.service.list(owner);
  assert.equal(f.scheduler.tasks.length, 0);
  const originals = await Promise.all(
    created.study.cases.map(async (entry) => ({
      key: entry.key,
      bytes: await readFile(f.cachePath(entry.key), 'utf8'),
    })),
  );
  await f.service.start(id, owner);
  await f.service.flush();
  const done = (await f.service.get(id, owner)).study;
  assert.equal(done.status, 'completed');
  assert.equal(done.cases.length, 2);
  assert.equal(done.aggregation.completed_cases, 2);
  assert.equal(done.owner, undefined);
  f.scheduler.tasks = [];
  const exported = await f.store.present(id, owner.id, true);
  for (const entry of exported.cases) {
    assert.equal(entry.cache_json, originals[entry.index].bytes);
    assert.equal(entry.source_sha256, hash(entry.cache_json));
    assert.equal(
      await readFile(f.cachePath(entry.key), 'utf8'),
      originals[entry.index].bytes,
    );
  }
  assert.equal(f.counts().starts, 0);
});

void test('a cross-head study binds one identity per head, then creates and runs every head', async (t) => {
  const f = await fixture(t),
    study = input([], {
      protocol: 'heads',
      cases: [
        { head_id: 'ernie_xh', seed: 42, radius_mm: 6 },
        { head_id: 'ixi002', seed: 42, radius_mm: 6 },
      ],
    });
  for (const request of normalizeStudyInput(study).requests) await f.seedCache(request);
  const created = await f.service.create(study, owner),
    id = created.study.id;
  assert.equal(created.study.status, 'draft');
  const record = await f.store.load(id, owner.id),
    identities = record.cases.map((entry) => entry.identity_sha256);
  assert.deepEqual(
    identities,
    ['ernie_xh', 'ixi002'].map((head_id) =>
      hash({ protocol: 'unchanged-design-evaluation/1', version: 1, head_id }),
    ),
  );
  assert.equal(record.identity_sha256, hash(identities));
  assert.ok(created.study.cases.every((entry) => !('identity_sha256' in entry)));
  await f.service.start(id, owner);
  await f.service.flush();
  const done = (await f.service.get(id, owner)).study;
  assert.equal(done.status, 'completed');
  assert.deepEqual(
    done.cases.map((entry) => [entry.request.head_id, entry.status]),
    [
      ['ernie_xh', 'completed'],
      ['ixi002', 'completed'],
    ],
  );
  assert.equal(done.aggregation.interpretation, 'cross_head_empirical_cases');
  const exported = await f.store.present(id, owner.id, true);
  assert.ok(exported.study.cases.every((entry) => !('identity_sha256' in entry)));
  assert.equal(f.counts().starts, 0);
  for (const change of [
    (value) => {
      value.cases[1].request.seed = 43;
    },
    (value) => {
      value.cases[1].identity_sha256 = identities[0];
    },
    (value) => {
      delete value.cases[1].identity_sha256;
    },
  ])
    await assert.rejects(f.store.update(id, owner.id, change), { status: 409 });
});

void test('non-head studies still refuse case identities that differ while preparing', async (t) => {
  const f = await fixture(t),
    prepare = f.adapter.prepare.bind(f.adapter);
  f.adapter.prepare = async (raw) => {
    const prepared = await prepare(raw);
    f.setVersion(2);
    return prepared;
  };
  await assert.rejects(f.service.create(input(), owner), { status: 409 });
  assert.deepEqual((await f.service.list(owner)).studies, []);
});

void test('non-head study records keep the single shared identity older servers verify', async (t) => {
  const f = await fixture(t),
    id = (await f.service.create(input(), owner)).study.id,
    record = await f.store.load(id, owner.id);
  assert.equal(
    record.identity_sha256,
    hash({ protocol: 'unchanged-design-evaluation/1', version: 1 }),
  );
  assert.ok(record.cases.every((entry) => !('identity_sha256' in entry)));
  await assert.rejects(
    f.store.update(id, owner.id, (value) => {
      for (const entry of value.cases) entry.identity_sha256 = value.identity_sha256;
    }),
    { status: 409 },
  );
});

void test('legacy records written without per-case identities still load and run', async (t) => {
  const f = await fixture(t),
    id = (await f.service.create(input(), owner)).study.id,
    current = await f.store.load(id, owner.id),
    // Exactly the case fields an older server writes.
    legacy = {
      ...current,
      cases: current.cases.map(({ index, request, key }) => ({
        index,
        request,
        key,
        status: 'pending',
        receipt_id: null,
        error: null,
      })),
    };
  await writeFile(join(f.store.directory, id, 'study.json'), JSON.stringify(legacy));
  assert.deepEqual(await f.store.load(id, owner.id), legacy);
  await f.service.start(id, owner);
  await f.service.flush();
  assert.equal((await f.service.get(id, owner)).study.status, 'completed');
});

void test('private study directory and all record operations enforce original browser ownership', async (t) => {
  const f = await fixture(t),
    id = (await f.service.create(input([42]), owner)).study.id;
  assert.deepEqual((await f.service.list(stranger)).studies, []);
  for (const action of [
    () => f.service.get(id, stranger),
    () => f.service.start(id, stranger),
    () => f.service.cancel(id, stranger),
    () => f.store.present(id, stranger.id, true),
  ])
    await assert.rejects(action(), { status: 404 });
  assert.equal(f.scheduler.tasks.length, 0);
});

void test('concurrent starts from one browser admit at most one parent study', async (t) => {
  const f = await fixture(t, { cached: false }),
    a = (await f.service.create(input([42]), owner)).study.id,
    b = (await f.service.create(input([43]), owner)).study.id;
  const outcomes = await Promise.allSettled([
    f.service.start(a, owner),
    f.service.start(b, owner),
  ]);
  await f.service.flush();
  assert.equal(outcomes.filter((o) => o.status === 'fulfilled').length, 1);
  assert.equal(
    outcomes.find((o) => o.status === 'rejected').reason.status,
    429,
  );
  assert.equal(f.service.active.size, 1);
  assert.equal(f.scheduler.tasks.length, 1);
});

void test('cancel during case preparation prevents a later child admission', async (t) => {
  const f = await fixture(t, { cached: false }),
    id = (await f.service.create(input([42]), owner)).study.id,
    gate = deferred();
  f.setPrepareHold(gate);
  await f.service.start(id, owner);
  const cancelled = f.service.cancel(id, owner);
  await cancelled;
  gate.resolve();
  f.setPrepareHold(null);
  await f.service.flush();
  assert.equal((await f.service.get(id, owner)).study.status, 'cancelled');
  assert.equal(f.scheduler.tasks.length, 0);
});

void test('cancel inside original queue write admission prevents receipt creation', async (t) => {
  const entered = deferred(),
    gate = deferred();
  let block = false;
  const f = await fixture(t, {
    cached: false,
    beforeNewWork: async () => {
      if (block) {
        entered.resolve();
        await gate.promise;
      }
    },
  });
  const id = (await f.service.create(input([42]), owner)).study.id;
  block = true;
  await f.service.start(id, owner);
  await entered.promise;
  const cancellation = f.service.cancel(id, owner);
  await cancellation;
  gate.resolve();
  await f.service.flush();
  assert.equal((await f.service.get(id, owner)).study.status, 'cancelled');
  assert.equal(f.scheduler.tasks.length, 0);
});

void test('cancelling a shared queued case removes only the study browser and retains other owners', async (t) => {
  const f = await fixture(t, { cached: false }),
    id = (await f.service.create(input([42]), owner)).study.id;
  await f.service.start(id, owner);
  await f.service.flush();
  const task = f.scheduler.tasks[0];
  task.owners.push(stranger.id);
  f.scheduler.persist();
  await f.service.cancel(id, owner);
  await f.service.flush();
  assert.equal((await f.service.get(id, owner)).study.status, 'cancelled');
  assert.deepEqual(task.owners, [stranger.id]);
  assert.equal(task.status, 'queued');
});

void test('restart pauses the parent and a GET never accepts more cases; explicit resume reconciles owned receipts', async (t) => {
  const f = await fixture(t, { cached: false }),
    id = (await f.service.create(input(), owner)).study.id;
  await f.service.start(id, owner);
  await f.service.flush();
  assert.equal(f.scheduler.tasks.length, 1);
  await f.restart();
  assert.equal(
    (await f.service.get(id, owner)).study.status,
    'paused_recovery',
  );
  await f.service.list(owner);
  await f.service.flush();
  assert.equal(f.scheduler.tasks.length, 1);
  await f.service.start(id, owner, true);
  await f.service.flush();
  assert.equal(f.scheduler.tasks.length, 1);
  assert.equal(
    (await f.service.get(id, owner)).study.cases[0].receipt_id,
    f.scheduler.tasks[0].id,
  );
});

void test('an uncertain interrupted submission is retained without blindly resubmitting it', async (t) => {
  const f = await fixture(t, { cached: false }),
    id = (await f.service.create(input([42]), owner)).study.id;
  await f.store.update(id, owner.id, (record) => {
    record.status = 'running';
    Object.assign(record.cases[0], {
      status: 'submitting',
      operation_id: randomUUID(),
    });
  });
  await f.restart();
  await f.service.start(id, owner, true);
  await f.service.flush();
  const study = (await f.service.get(id, owner)).study;
  assert.equal(study.status, 'completed_with_failures');
  assert.equal(study.cases[0].status, 'failed_uncertain');
  assert.equal(f.scheduler.tasks.length, 0);
});

void test('changed scientific identity fails pending cases without new receipts', async (t) => {
  const f = await fixture(t, { cached: false }),
    id = (await f.service.create(input(), owner)).study.id;
  f.setVersion(2);
  await f.service.start(id, owner);
  await f.service.flush();
  const study = (await f.service.get(id, owner)).study;
  assert.equal(study.status, 'completed_with_failures');
  assert.ok(
    study.cases.every(
      (entry) => entry.error.code === 'scientific_identity_changed',
    ),
  );
  assert.equal(f.scheduler.tasks.length, 0);
});

void test('archive checks exact cache binding and rejects corrupted or symlinked snapshots', async (t) => {
  const f = await fixture(t),
    id = (await f.service.create(input([42]), owner)).study.id;
  await f.service.start(id, owner);
  await f.service.flush();
  const study = (await f.service.get(id, owner)).study,
    entry = study.cases[0];
  const path = join(
      f.store.directory,
      id,
      'snapshots',
      entry.source_sha256 + '.json',
    ),
    original = await readFile(path);
  await writeFile(path, Buffer.concat([original, Buffer.from(' ')]));
  await assert.rejects(f.service.get(id, owner), /checksum/);
  await rm(path);
  await symlink(f.cachePath(entry.key), path);
  await assert.rejects(f.service.get(id, owner));
});

void test('studies are capped per client network and stale unstarted drafts free their slots', async (t) => {
  const network = 'b'.repeat(64);
  const f = await fixture(t, { studyLimits: { ...STUDY_LIMITS, perOwner: 1, perNetwork: 1 } });
  const first = (await f.service.create(input([42]), { ...owner, network })).study;
  // A fresh cookie on the same network does not get a new share.
  await assert.rejects(f.service.create(input([43]), { id: 'c'.repeat(64), ip: 'local-c', network }), { status: 429 });
  await assert.rejects(f.service.create(input([43]), owner), { status: 429 });
  const path = join(f.store.directory, first.id, 'study.json'),
    record = JSON.parse(await readFile(path, 'utf8'));
  assert.equal(record.network, network);
  assert.equal(JSON.stringify(await f.service.get(first.id, owner)).includes(network), false);
  record.updated_at = '2020-01-01T00:00:00.000Z';
  await writeFile(path, JSON.stringify(record));
  const second = (await f.service.create(input([43]), { ...owner, network })).study;
  assert.notEqual(second.id, first.id);
  await assert.rejects(f.service.get(first.id, owner), { status: 404 });
});

void test('study count, metadata, total-byte and unsafe-root limits fail before scientific submission', async (t) => {
  const f = await fixture(t, { studyLimits: { ...STUDY_LIMITS, perOwner: 1 } });
  await f.service.create(input([42]), owner);
  await assert.rejects(f.service.create(input([43]), owner), { status: 429 });
  assert.equal(f.scheduler.tasks.length, 0);
  const second = await fixture(t, {
    studyLimits: { ...STUDY_LIMITS, metadataBytes: 10 },
  });
  await assert.rejects(second.service.create(input([42]), owner), {
    status: 413,
  });
  assert.equal(second.scheduler.tasks.length, 0);
  const third = await fixture(t, {
    studyLimits: { ...STUDY_LIMITS, totalBytes: 10 },
  });
  await assert.rejects(third.service.create(input([42]), owner), {
    status: 507,
  });
  assert.equal(third.scheduler.tasks.length, 0);
  const fourth = await fixture(t);
  await symlink(f.root, fourth.store.directory);
  await assert.rejects(fourth.service.create(input([42]), owner));
});

void test('a resource refusal pauses the pending case and GET does not retry it', async (t) => {
  let blocked = true;
  const f = await fixture(t, {
    cached: false,
    beforeNewWork: async () => {
      if (blocked)
        throw Object.assign(new Error('Resource blocked'), {
          status: 503,
          resourceSafe: true,
        });
    },
  });
  const id = (await f.service.create(input([42]), owner)).study.id;
  await f.service.start(id, owner);
  await f.service.flush();
  assert.equal(
    (await f.service.get(id, owner)).study.status,
    'paused_resource',
  );
  assert.equal(f.scheduler.tasks.length, 0);
  blocked = false;
  await f.service.get(id, owner);
  await f.service.flush();
  assert.equal(f.scheduler.tasks.length, 0);
  await f.service.start(id, owner, true);
  await f.service.flush();
  assert.equal(f.scheduler.tasks.length, 1);
});

void test('default queue admission remains unchanged while internal expected-key and cancellation guards act before receipts', async (t) => {
  const f = await fixture(t, { cached: false }),
    prepared = await f.adapter.prepare(
      normalizeStudyInput(input([42])).requests[0],
    );
  await assert.rejects(
    f.scheduler.submit(
      'design-evaluation',
      prepared.request,
      owner,
      false,
      'd'.repeat(64),
    ),
    { status: 409 },
  );
  await assert.rejects(
    f.scheduler.submit(
      'design-evaluation',
      prepared.request,
      owner,
      false,
      prepared.key,
      () => false,
    ),
    (error) => error.studyAdmissionCancelled === true,
  );
  assert.equal(f.scheduler.tasks.length, 0);
  const legacy = await f.scheduler.submit(
    'design-evaluation',
    prepared.request,
    owner,
  );
  assert.equal(legacy.job.key, prepared.key);
  assert.equal(legacy.job.status, 'queued');
  assert.deepEqual(f.scheduler.tasks[0].request, prepared.request);
});

void test('HTTP study writes require origin/token and reads isolate signed browser sessions', async (t) => {
  const f = await fixture(t),
    middleware = f.service.middleware((_req, res) => res.writeHead(404).end());
  const server = createServer((req, res) =>
    middleware(req, res, () => res.writeHead(404).end()),
  );
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(async () => {
    const closed = once(server, 'close');
    server.close();
    server.closeAllConnections();
    await closed;
  });
  const origin = `http://127.0.0.1:${server.address().port}`,
    cookies = new Map();
  const call = async (
    path,
    {
      browser = 'A',
      method = 'GET',
      body,
      token = f.queue.token,
      originHeader = origin,
    } = {},
  ) => {
    const response = await fetch(origin + path, {
      method,
      headers: {
        Origin: originHeader,
        Cookie: cookies.get(browser) ?? '',
        ...(method === 'POST'
          ? { 'Content-Type': 'application/json', 'X-EEG-Compute-Token': token }
          : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (response.headers.get('set-cookie'))
      cookies.set(browser, response.headers.get('set-cookie').split(';')[0]);
    return { status: response.status, data: await response.json() };
  };
  await call('/api/robustness-studies');
  await call('/api/robustness-studies', { browser: 'B' });
  assert.equal(
    (
      await call('/api/robustness-studies', {
        method: 'POST',
        body: input([42]),
        token: '',
      })
    ).status,
    403,
  );
  assert.equal(
    (
      await call('/api/robustness-studies', {
        method: 'POST',
        body: input([42]),
        originHeader: 'https://foreign.test',
      })
    ).status,
    403,
  );
  assert.equal(
    (
      await call('/api/robustness-studies', {
        method: 'POST',
        body: input([42], { design: { ...design, unit: 'm' } }),
      })
    ).status,
    400,
  );
  const created = await call('/api/robustness-studies', {
    method: 'POST',
    body: input([42]),
  });
  assert.equal(created.status, 201);
  const id = created.data.study.id;
  assert.equal(
    (await call(`/api/robustness-studies/${id}`, { browser: 'B' })).status,
    404,
  );
  assert.deepEqual(
    (await call('/api/robustness-studies', { browser: 'B' })).data.studies,
    [],
  );
  assert.equal(
    (
      await call(`/api/robustness-studies/${id}/start`, {
        method: 'POST',
        body: { extra: true },
      })
    ).status,
    400,
  );
  assert.equal(f.scheduler.tasks.length, 0);
});

void test('maintenance rejection retains a pending case until an explicit resume', async (t) => {
  const f = await fixture(t, { cached: false }),
    id = (await f.service.create(input([42]), owner)).study.id;
  f.scheduler.maintenance = true;
  await f.service.start(id, owner);
  await f.service.flush();
  let study = (await f.service.get(id, owner)).study;
  assert.equal(study.status, 'paused_resource');
  assert.equal(study.cases[0].status, 'pending');
  assert.equal(f.scheduler.tasks.length, 0);
  f.scheduler.maintenance = false;
  await f.service.get(id, owner);
  await f.service.flush();
  assert.equal(f.scheduler.tasks.length, 0);
  await f.service.start(id, owner, true);
  await f.service.flush();
  study = (await f.service.get(id, owner)).study;
  assert.equal(study.cases[0].status, 'queued');
  assert.equal(f.scheduler.tasks.length, 1);
});
void test('stopping during preparation does not label the unsubmitted case as cancelled', async (t) => {
  const f = await fixture(t, { cached: false }),
    id = (await f.service.create(input([42]), owner)).study.id,
    gate = deferred();
  f.setPrepareHold(gate);
  await f.service.start(id, owner);
  f.service.stop();
  gate.resolve();
  f.setPrepareHold(null);
  await f.service.flush();
  assert.equal(
    (await f.service.get(id, owner)).study.cases[0].status,
    'pending',
  );
  assert.equal(f.scheduler.tasks.length, 0);
  await f.restart();
  assert.equal(
    (await f.service.get(id, owner)).study.status,
    'paused_recovery',
  );
  await f.service.start(id, owner, true);
  await f.service.flush();
  assert.equal(f.scheduler.tasks.length, 1);
});
void test('stopping inside queue admission preserves a confirmed unaccepted case for recovery', async (t) => {
  const entered = deferred(),
    gate = deferred();
  let block = false;
  const f = await fixture(t, {
    cached: false,
    beforeNewWork: async () => {
      if (block) {
        entered.resolve();
        await gate.promise;
      }
    },
  });
  const id = (await f.service.create(input([42]), owner)).study.id;
  block = true;
  await f.service.start(id, owner);
  await entered.promise;
  f.service.stop();
  gate.resolve();
  await f.service.flush();
  const study = (await f.service.get(id, owner)).study;
  assert.equal(study.status, 'paused_recovery');
  assert.equal(study.cases[0].status, 'pending');
  assert.equal(f.scheduler.tasks.length, 0);
});

void test('cancel remains usable after an original receipt was removed', async (t) => {
  const f = await fixture(t, { cached: false }),
    id = (await f.service.create(input([42]), owner)).study.id;
  await f.service.start(id, owner);
  await f.service.flush();
  f.scheduler.tasks = [];
  await f.service.cancel(id, owner);
  await f.service.flush();
  const study = (await f.service.get(id, owner)).study;
  assert.equal(study.status, 'cancelled');
  assert.equal(study.cases[0].status, 'cancelled');
});
void test('cancelling remaining work preserves an already failed child and its reason', async (t) => {
  const f = await fixture(t, { cached: false }),
    id = (await f.service.create(input(), owner)).study.id;
  await f.service.start(id, owner);
  await f.service.flush();
  const task = f.scheduler.tasks[0];
  task.status = 'failed';
  task.message = 'Original failed solver case';
  await f.service.cancel(id, owner);
  await f.service.flush();
  const study = (await f.service.get(id, owner)).study;
  assert.equal(study.status, 'cancelled');
  assert.equal(study.cases[0].status, 'failed');
  assert.equal(study.cases[0].error.message, 'Original failed solver case');
  assert.equal(study.cases[1].status, 'cancelled');
});

void test('quota-blocked startup keeps existing research readable and waits for explicit recovery', async (t) => {
  let blocked = false;
  const f = await fixture(t, {
    cached: false,
    beforeWrite: async () => {
      if (blocked)
        throw Object.assign(new Error('Study quota'), {
          status: 507,
          studySafe: true,
        });
    },
  });
  const id = (await f.service.create(input([42]), owner)).study.id;
  await f.service.start(id, owner);
  await f.service.flush();
  blocked = true;
  await f.restart();
  assert.equal(
    (await f.service.get(id, owner)).study.status,
    'paused_recovery',
  );
  assert.equal((await f.service.list(owner)).studies.length, 1);
  assert.equal(f.scheduler.tasks.length, 1);
  blocked = false;
  await f.service.start(id, owner, true);
  await f.service.flush();
  assert.equal(f.scheduler.tasks.length, 1);
});

void test('cancel clears a transient resource pause and terminal studies cannot resume', async (t) => {
  let blocked = false;
  const f = await fixture(t, {
    cached: false,
    beforeWrite: async () => {
      if (blocked)
        throw Object.assign(new Error('Resource blocked'), {
          status: 503,
          resourceSafe: true,
        });
    },
  });
  const id = (await f.service.create(input([42]), owner)).study.id,
    gate = deferred();
  f.setPrepareHold(gate);
  await f.service.start(id, owner);
  blocked = true;
  gate.resolve();
  f.setPrepareHold(null);
  await f.service.flush();
  assert.equal(
    (await f.service.get(id, owner)).study.status,
    'paused_resource',
  );
  blocked = false;
  await f.service.cancel(id, owner);
  await f.service.flush();
  assert.equal((await f.service.get(id, owner)).study.status, 'cancelled');
  assert.equal((await f.service.list(owner)).studies[0].status, 'cancelled');
  await assert.rejects(f.service.start(id, owner, true), { status: 409 });
  assert.equal(f.scheduler.tasks.length, 0);
});
void test('cancelling recovery pauses clears the directory overlay and never revives a cancelled parent', async (t) => {
  const f = await fixture(t, { cached: false }),
    id = (await f.service.create(input([42]), owner)).study.id;
  await f.service.start(id, owner);
  await f.service.flush();
  await f.restart();
  await f.service.cancel(id, owner);
  await f.service.flush();
  assert.equal((await f.service.list(owner)).studies[0].status, 'cancelled');
  await assert.rejects(f.service.start(id, owner, true), { status: 409 });
});

void test('resource admission blocks new work but cannot block cancellation of owned queued work', async (t) => {
  let blocked = false;
  const f = await fixture(t, {
    cached: false,
    beforeWrite: async () => {
      if (blocked)
        throw Object.assign(new Error('Resource blocked'), {
          status: 503,
          resourceSafe: true,
        });
    },
  });
  const id = (await f.service.create(input(), owner)).study.id;
  await f.service.start(id, owner);
  await f.service.flush();
  blocked = true;
  await f.service.cancel(id, owner);
  await f.service.flush();
  const study = (await f.service.get(id, owner)).study;
  assert.equal(study.status, 'cancelled');
  assert.equal(study.cancel_requested, true);
  assert.ok(study.cases.every((entry) => entry.status === 'cancelled'));
  assert.equal(f.scheduler.tasks.length, 1);
  assert.equal(f.scheduler.tasks[0].status, 'cancelled');
  await assert.rejects(f.service.create(input([44]), owner), {
    resourceSafe: true,
  });
});
void test('cancelled completion waits for original-result archive without authorizing later cases', async (t) => {
  let blocked = false;
  const f = await fixture(t, {
    cached: false,
    beforeWrite: async () => {
      if (blocked)
        throw Object.assign(new Error('Resource blocked'), {
          status: 503,
          resourceSafe: true,
        });
    },
  });
  const id = (await f.service.create(input(), owner)).study.id;
  await f.service.start(id, owner);
  await f.service.flush();
  const task = f.scheduler.tasks[0];
  await f.seedCache(task.request);
  task.status = 'completed';
  blocked = true;
  await f.service.cancel(id, owner);
  await f.service.flush();
  let study = (await f.service.get(id, owner)).study;
  assert.equal(study.status, 'paused_resource');
  assert.equal(study.cancel_requested, true);
  assert.equal(study.cases[1].status, 'cancelled');
  assert.equal(f.scheduler.tasks.length, 1);
  await f.restart();
  study = (await f.service.get(id, owner)).study;
  assert.equal(study.cancel_requested, true);
  assert.equal(study.status, 'paused_recovery');
  blocked = false;
  await f.service.start(id, owner, true);
  await f.service.flush();
  study = (await f.service.get(id, owner)).study;
  assert.equal(study.status, 'cancelled');
  assert.equal(study.cases[0].status, 'completed');
  assert.equal(study.cases[1].status, 'cancelled');
  assert.equal(f.scheduler.tasks.length, 1);
  assert.equal(study.aggregation.completed_cases, 1);
});

void test('explicit parent recovery checks a complete interrupted cache before marking its existing receipt failed', async (t) => {
  for (const scenario of [
    'valid',
    'missing',
    'corrupt',
    'ordinary_solver_failure',
  ]) {
    const f = await fixture(t, { cached: false }),
      id = (await f.service.create(input([42]), owner)).study.id;
    await f.service.start(id, owner);
    await f.service.flush();
    const task = f.scheduler.tasks[0];
    let original;
    if (scenario !== 'missing') {
      original = await f.seedCache(task.request);
      if (scenario === 'corrupt')
        await writeFile(original.path, original.bytes.replace('0.81', '0.82'));
    }
    task.status = 'failed';
    task.message =
      scenario === 'ordinary_solver_failure'
        ? 'Actual solver failed'
        : '服务重启中断了计算，可重新提交';
    await f.store.update(id, owner.id, (record) => {
      record.cases[0].status = 'running';
    });
    await f.restart();
    await f.service.start(id, owner, true);
    await f.service.flush();
    const study = (await f.service.get(id, owner)).study;
    assert.equal(f.scheduler.tasks.length, 1);
    assert.equal(f.counts().starts, 0);
    if (scenario === 'valid') {
      assert.equal(study.status, 'completed');
      assert.equal(study.cases[0].status, 'completed');
      const exported = await f.store.present(id, owner.id, true);
      assert.equal(exported.cases[0].cache_json, original.bytes);
    } else {
      assert.equal(study.status, 'completed_with_failures');
      assert.equal(study.cases[0].status, 'failed');
    }
  }
});
