import * as taskClient from '../client/task-client.ts';
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { CommunityQueue } from '../server/community-queue.mjs';
import { BRAIN_REGIONS, sourceKey, sourceBackLink } from '../lib/source-reception.ts';
import { canonicalSourceRegions } from '../lib/source-regions.ts';
import { parseAR } from '../lib/lab-workflow.ts';
import { safeReturnHref } from '../lib/ui-language.ts';
import { createHookHarness } from './helpers/hook-harness.mjs';

const request = letter => ({
  record_id: letter.repeat(64), mode: 'multi_source', region_definition: 'dk40-six-roi-v1',
  brain_region: 'frontal', waveform: 'burst', artifact_scale: 1, seed: 2026,
});
const a = request('a'), b = request('b'), c = request('c');
const sourceJob = (request, status = 'queued', id = request.record_id.slice(0, 1)) => ({
  id, key: sourceKey(request), request, status, progress: 0, cached: false,
  message: status, result: status === 'completed' ? { request } : null,
});
const json = value => ({ ok: true, json: async () => value });
const deferred = () => {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return { promise, resolve };
};
async function controller(t, fetchSource, { active = null, initial = b } = {}) {
  const calls = [];
  const harness = await createHookHarness({
    filename: new URL('../features/reception/use-reception-controller.ts', import.meta.url),
    exportName: 'useReceptionController', maxTimerMs: 10,
    imports: {
      ...taskClient,
      useLanguage: () => ({ tx: value => value, locale: 'en' }),
      safeReturnHref, parseAR, canonicalSourceRegions, BRAIN_REGIONS, sourceKey, sourceBackLink,
    },
    globals: {
      window: {
        location: { search: `?record=${initial.record_id}` },
        history: { replaceState() {} }, addEventListener() {}, removeEventListener() {},
      },
      fetch: async (url, options) => {
        calls.push(url);
        if (url.endsWith('/layouts')) return json({ records: [a, b, c].map(r => ({
          id: r.record_id, status: 'completed', dataset_id: 'strict_area',
        })) });
        if (url.endsWith('/health')) return json({ token: 'token', active_job: active });
        return fetchSource(url, options);
      },
    },
  });
  t.after(() => harness.dispose());
  return { harness, calls };
}

void test('refresh restores the selected queued task instead of the earlier health task, then displays its result', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'eeg-reception-controller-'));
  const workers = new Map(), cache = new Map(), visitor = { id: 'same-browser', ip: '127.0.0.1' };
  const scheduler = new CommunityQueue({ directory, pollMs: 3600000, adapters: {
    'source-reception': {
      prepare: async request => ({ request, key: sourceKey(request) }),
      lookup: async p => cache.has(p.key) ? { hit: true, job: cache.get(p.key) } : { hit: false },
      start: async request => {
        const job = sourceJob(request, 'running'); workers.set(job.id, job); return { job };
      },
      get: id => workers.get(id), pid: () => undefined,
      busy: () => [...workers.values()].some(j => j.status === 'running'), cancel() {},
    },
  } });
  t.after(async () => { scheduler.dispose(); await rm(directory, { recursive: true, force: true }); });
  await scheduler.submit('source-reception', a, visitor);
  const receiptB = (await scheduler.submit('source-reception', b, visitor)).job;
  await scheduler.tick();
  const { harness, calls } = await controller(t, async (url, options) => {
    if (url.endsWith('/lookup')) return json(await scheduler.submit('source-reception', JSON.parse(options.body), visitor, true));
    const id = url.split('/').at(-1);
    return json({ job: await scheduler.view(scheduler.own(id, visitor)) });
  }, { active: await scheduler.active('source-reception', visitor) });
  await harness.waitFor(s => s.active?.id === receiptB.id && s.job?.status === 'queued');
  assert.equal(harness.current.busy, true);
  assert.equal(harness.current.lookup.message, '已加入计算队列');
  assert.equal(harness.current.result, null);
  await harness.waitFor(() => calls.some(url => url.endsWith('/' + receiptB.id)));
  const complete = async req => {
    const job = workers.get(req.record_id[0]);
    Object.assign(job, { status: 'completed', progress: 1, result: { request: req } });
    cache.set(sourceKey(req), { ...job, cached: true });
    await scheduler.tick();
  };
  await complete(a);
  await harness.waitFor(s => s.job?.status === 'running');
  await complete(b);
  await harness.waitFor(s => s.result?.request.record_id === b.record_id);
  assert.equal(harness.current.job.id, receiptB.id);
  assert.equal(harness.current.busy, false);
  assert.equal(harness.current.lookup.message, '源—接收对照已计算并保存');
  const lookupCount = calls.filter(url => url.endsWith('/lookup')).length;
  await harness.act(s => s.setAR(70));
  assert.equal(calls.filter(url => url.endsWith('/lookup')).length, lookupCount);
  harness.dispose();
});

void test('a late lookup reply cannot replace a newly selected cached scene', async t => {
  const late = deferred(); let queriedB = false;
  const cachedC = { ...sourceJob(c, 'completed'), cached: true };
  const { harness, calls } = await controller(t, async (url, options) => {
    assert.ok(url.endsWith('/lookup'));
    if (JSON.parse(options.body).record_id === b.record_id) { queriedB = true; return late.promise; }
    return json({ hit: true, job: cachedC });
  });
  await harness.waitFor(() => queriedB);
  await harness.act(s => s.setId(c.record_id));
  await harness.waitFor(s => s.result?.request.record_id === c.record_id);
  late.resolve(json({ hit: true, job: sourceJob(b) }));
  await harness.flush();
  assert.equal(harness.current.result.request.record_id, c.record_id);
  assert.equal(harness.current.lookup.key, sourceKey(c));
  assert.equal(harness.current.lookup.message, '已读取已有结果，不重新计算。');
  assert.equal(calls.some(url => url.endsWith('/jobs/b')), false);
});

void test('a late submit reply cannot replace a newer selected scene', async t => {
  const late = deferred(); let submitted = false;
  const cachedC = { ...sourceJob(c, 'completed'), cached: true };
  const { harness } = await controller(t, async (url, options) => {
    if (url.endsWith('/jobs')) { submitted = true; return late.promise; }
    if (url.endsWith('/lookup')) return json(JSON.parse(options.body).record_id === c.record_id
      ? { hit: true, job: cachedC } : { hit: false });
    throw new Error(url);
  });
  await harness.waitFor(s => s.lookup.key === sourceKey(b));
  const submission = harness.current.submit();
  await harness.waitFor(() => submitted);
  await harness.act(s => s.setId(c.record_id));
  await harness.waitFor(s => s.result?.request.record_id === c.record_id);
  late.resolve(json({ job: sourceJob(b) }));
  await submission;
  await harness.flush();
  assert.equal(harness.current.active, null);
  assert.equal(harness.current.result.request.record_id, c.record_id);
  assert.equal(harness.current.lookup.key, sourceKey(c));
});

void test('late poll and cancellation replies cannot overwrite the newly restored task', async t => {
  const oldPoll = deferred(), oldCancel = deferred(); let pollingB = false;
  const jobB = sourceJob(b), jobC = sourceJob(c);
  const { harness } = await controller(t, async (url, options) => {
    if (url.endsWith('/lookup')) return json({ hit: true, job: JSON.parse(options.body).record_id === b.record_id ? jobB : jobC });
    if (url.endsWith('/b/cancel')) return oldCancel.promise;
    if (url.endsWith('/jobs/b')) { pollingB = true; return oldPoll.promise; }
    if (url.endsWith('/jobs/c')) return json({ job: jobC });
    throw new Error(url);
  });
  await harness.waitFor(() => pollingB);
  const cancellation = harness.current.cancel();
  await harness.act(s => s.setId(c.record_id));
  await harness.waitFor(s => s.active?.id === 'c');
  oldCancel.resolve(json({ job: sourceJob(b, 'cancelled') }));
  oldPoll.resolve(json({ job: sourceJob(b, 'completed') }));
  await cancellation;
  await harness.flush();
  assert.equal(harness.current.active.id, 'c');
  assert.equal(harness.current.job.status, 'queued');
  assert.equal(harness.current.lookup.key, sourceKey(c));
  assert.equal(harness.current.result, null);
});

for (const status of ['failed', 'cancelled', 'timeout']) {
  void test(`a recovered task reaching ${status} stops polling and never becomes a cached result`, async t => {
    const { harness } = await controller(t, async url => {
      if (url.endsWith('/lookup')) return json({ hit: true, job: sourceJob(b) });
      return json({ job: sourceJob(b, status) });
    });
    await harness.waitFor(s => s.job?.status === status);
    assert.equal(harness.current.busy, false);
    assert.equal(harness.current.result, null);
    assert.equal(harness.current.lookup.message, status);
  });
}

void test('leaving a shared queued task through cancellation immediately restores idle state', async t => {
  const { harness } = await controller(t, async url => {
    if (url.endsWith('/cancel')) return json({ job: {
      ...sourceJob(b, 'cancelled'), message: '已退出共享任务，其他访客的计算继续',
    } });
    return json({ hit: true, job: sourceJob(b) });
  });
  await harness.waitFor(s => s.active?.status === 'queued');
  await harness.act(s => s.cancel());
  assert.equal(harness.current.busy, false);
  assert.equal(harness.current.job.status, 'cancelled');
  assert.equal(harness.current.lookup.message, '已退出共享任务，其他访客的计算继续');
  assert.equal(harness.current.result, null);
});

void test('a transient connection error keeps the known task running and later recovers its result', async t => {
  const recovered = deferred(); let polls = 0;
  const { harness } = await controller(t, async url => {
    if (url.endsWith('/lookup')) return json({ hit: true, job: sourceJob(b, 'running') });
    polls++;
    if (polls === 1) throw new TypeError('Offline');
    return recovered.promise;
  });
  await harness.waitFor(s => s.connection === 'reconnecting');
  assert.equal(harness.current.job.status, 'running');
  assert.equal(harness.current.busy, true);
  recovered.resolve(json({ job: sourceJob(b, 'completed') }));
  await harness.waitFor(s => s.result?.request.record_id === b.record_id);
  assert.equal(harness.current.connection, 'connected');
  assert.equal(harness.current.error.message, '');
});

for (const status of [401, 403, 404]) {
  void test(`a blocked HTTP ${status} task can reconnect without changing server state or resubmitting`, async t => {
    let restored = false, submissions = 0;
    const { harness } = await controller(t, async url => {
      if (url.endsWith('/lookup')) return json({ hit: true, job: sourceJob(b, 'running') });
      if (url.endsWith('/jobs')) submissions++;
      return restored ? json({ job: sourceJob(b, 'completed') })
        : { ok: false, status, json: async () => ({ error: 'Unavailable' }) };
    });
    await harness.waitFor(s => s.connection === 'blocked');
    assert.equal(harness.current.job.status, 'running');
    assert.equal(harness.current.busy, false);
    assert.ok(harness.current.fatal);
    restored = true;
    await harness.act(s => s.setRetry(n => n + 1));
    await harness.waitFor(s => s.result?.request.record_id === b.record_id);
    assert.equal(harness.current.connection, 'connected');
    assert.equal(submissions, 0);
  });
}
