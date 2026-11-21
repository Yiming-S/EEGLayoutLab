import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { mkdtemp, readFile, rm, writeFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { RecordVisibility, libraryConfig, moderationPath } from '../server/library/record-visibility.mjs';
import { CommunityQueue, communityMiddleware } from '../server/community-queue.mjs';
import { computeMiddleware } from '../server/local-compute-server.mjs';
import { createAccessPolicy } from '../server/http/access-policy.mjs';
import { sendJson } from '../server/http/responses.mjs';
import { parse, run } from './library-moderation.mjs';

const hex = value => createHash('sha256').update(String(value)).digest('hex');
const A = hex('browser A'), B = hex('browser B'), RECORD = hex('record'), OTHER = hex('other');
const stacks = new WeakMap();
// Cleanups run last-registered first, so servers and queues stop before their directory is removed.
const later = (t, fn) => {
  if (!stacks.has(t)) { const fns = []; stacks.set(t, fns); t.after(async () => { for (const f of fns.reverse()) await f(); }); }
  stacks.get(t).push(fn);
};
const directory = async t => {
  const path = await mkdtemp(join(tmpdir(), 'eeg-visibility-'));
  later(t, () => rm(path, { recursive: true, force: true }));
  return path;
};
const moderate = (queueDirectory, ...args) => run(parse([...args], { EEG_QUEUE_DIRECTORY: queueDirectory }));

void test('library scope defaults to shared on every host; owner scope is opt-in with review', async t => {
  assert.deepEqual(libraryConfig({}), { scope: 'shared', review: false });
  assert.deepEqual(libraryConfig({ EEG_LIBRARY_SCOPE: 'owner' }), { scope: 'owner', review: true });
  assert.deepEqual(libraryConfig({ EEG_LIBRARY_SCOPE: 'owner', EEG_LIBRARY_REVIEW: '0' }), { scope: 'owner', review: false });
  assert.throws(() => libraryConfig({ EEG_LIBRARY_SCOPE: 'public' }), /shared or owner/);
  assert.throws(() => libraryConfig({ EEG_LIBRARY_REVIEW: 'yes' }), /0 or 1/);
  const { hostConfig } = await import('../server/host/config.mjs');
  const root = await directory(t);
  const hosted = hostConfig({ webappRoot: root, repositoryRoot: root, env: { EEG_PUBLIC_ORIGIN: 'https://eeg.example.org', EEG_TRUSTED_PROXIES: '127.0.0.1' } });
  assert.deepEqual(hosted.library, { scope: 'shared', review: false }, 'a public host lists every record unless configured otherwise');
});

void test('owners list their records; publishing needs ownership, review gates listing, removal hides links', async t => {
  const queue = await directory(t), v = new RecordVisibility({ directory: queue, scope: 'owner', review: true });
  await v.claim('design-evaluation', RECORD, A); await v.claim('design-evaluation', RECORD, A);
  await v.claim('source-reception', OTHER, A); await v.claim('design-evaluation', 'not-a-key', A);
  assert.deepEqual(v.entries.get(RECORD).owners, [A]);
  assert.equal(v.entries.has(OTHER), false, 'signal records stay with the browser receipts');
  assert.equal(v.listable(RECORD, A), true); assert.equal(v.listable(RECORD, B), false);
  assert.equal(v.readable(RECORD, B), true, 'an unlisted record opens from its link');
  await assert.rejects(v.publish(RECORD, B, true), { status: 403 });
  await assert.rejects(v.publish(RECORD, A, 'yes'), { status: 400 });
  assert.equal((await v.publish(RECORD, A, true, 'Layout')).state, 'pending');
  assert.equal(v.listable(RECORD, B), false);
  await moderate(queue, 'approve', RECORD);
  assert.deepEqual(v.view(RECORD, B), { scope: 'owner', review: true, owned: false, state: 'public', published_by_me: false });
  assert.equal(v.listable(RECORD, B), true);
  await moderate(queue, 'remove', RECORD, '--reason', 'Offensive name');
  assert.equal(v.listable(RECORD, B), false); assert.equal(v.readable(RECORD, B), false);
  assert.equal(v.readable(RECORD, A), true);
  assert.equal(v.view(RECORD, A).state, 'removed'); assert.equal(v.view(RECORD, A).reason, 'Offensive name');
  assert.equal(v.view(RECORD, B).reason, undefined, 'only owners see the removal reason');
  await assert.rejects(v.publish(RECORD, A, true), { status: 409 });
  assert.equal((await v.publish(RECORD, A, false)).state, 'removed', 'withdrawing stays possible');
  await moderate(queue, 'restore', RECORD);
  assert.equal(v.state(RECORD), 'private');
  // Restart: owners and publishers persist; review off lists a published record at once.
  await v.publish(RECORD, A, true); await v.flush();
  const restarted = new RecordVisibility({ directory: queue, scope: 'owner', review: false });
  assert.equal(restarted.state(RECORD), 'public'); assert.equal(restarted.listable(RECORD, B), true);
  assert.equal((await restarted.publish(RECORD, A, false)).state, 'private');
});

void test('a second owner publishes independently; shared scope lists all but removed records', async t => {
  const queue = await directory(t), v = new RecordVisibility({ directory: queue, scope: 'owner', review: false });
  await v.claim('local-compute', RECORD, A); await v.claim('local-compute', RECORD, B);
  await v.publish(RECORD, A, true);
  assert.equal((await v.publish(RECORD, B, false)).state, 'public', 'B withdrawing its own publication leaves A\'s');
  assert.equal(v.view(RECORD, B).published_by_me, false);
  const shared = new RecordVisibility({ directory: queue, scope: 'shared' });
  await shared.claim('local-compute', OTHER, A);
  assert.equal(shared.listable(OTHER, B), true);
  await moderate(queue, 'remove', OTHER);
  assert.equal(shared.listable(OTHER, B), false); assert.equal(shared.listable(OTHER, A), true);
  const rows = [{ id: OTHER, dataset_id: 'cache' }, { id: hex('official'), dataset_id: 'strict_area' }];
  assert.deepEqual(shared.present(rows, B, r => r.id, r => r.dataset_id === 'cache'), [rows[1]]);
});

void test('a broken moderation file keeps the last valid removals; invalid record files stop startup', async t => {
  const queue = await directory(t), v = new RecordVisibility({ directory: queue, scope: 'owner', review: false });
  await v.claim('design-evaluation', RECORD, A); await v.publish(RECORD, A, true);
  await moderate(queue, 'remove', RECORD);
  assert.equal(v.state(RECORD), 'removed');
  await writeFile(moderationPath(queue), '{"version": 1, "records": {"bad": {}}}');
  assert.equal(v.state(RECORD), 'removed'); assert.match(v.moderationError, /Invalid moderation entry/);
  await assert.rejects(moderate(queue, 'restore', RECORD), /Invalid moderation entry/);
  await writeFile(join(queue, 'library/records', `${RECORD}.json`), '{"version": 1}');
  assert.throws(() => new RecordVisibility({ directory: queue }), /preserve it for recovery/);
});

void test('moderation tool arguments and the pending list', async t => {
  const queue = await directory(t), v = new RecordVisibility({ directory: queue, scope: 'owner', review: true });
  assert.throws(() => parse(['publish', RECORD], { EEG_QUEUE_DIRECTORY: queue }), /Commands/);
  assert.throws(() => parse(['approve', 'abc'], { EEG_QUEUE_DIRECTORY: queue }), /64-hex/);
  assert.throws(() => parse(['remove', RECORD, '--reason'], { EEG_QUEUE_DIRECTORY: queue }), /Usage/);
  assert.throws(() => parse(['list', '--all'], { EEG_QUEUE_DIRECTORY: queue }), /Usage/);
  assert.equal(parse(['--queue-directory', queue, 'list'], {}).queueDirectory, queue);
  await assert.rejects(moderate(queue, 'approve', RECORD), /No visitor record/);
  await v.claim('electrode-editor', RECORD, A); await v.claim('electrode-editor', OTHER, A);
  await v.publish(RECORD, A, true, 'Parent · 电极编辑 · 40电极');
  assert.deepEqual((await moderate(queue, 'list', '--pending')).records.map(r => [r.id, r.label, r.moderation]), [[RECORD, 'Parent · 电极编辑 · 40电极', null]]);
  await moderate(queue, 'approve', RECORD);
  assert.deepEqual((await moderate(queue, 'list', '--pending')).records, []);
  assert.equal((await moderate(queue, 'list')).records[0].moderation, 'approved');
});

function scientificFixture(root, records) {
  const token = 'c'.repeat(64);
  return {
    root, token, runtime: { queueDirectory: join(root, 'queue') }, health: () => ({ token, available: true }),
    library: {
      get: async id => structuredClone(records.find(r => r.id === id) ?? null),
      list: async () => ({ schema: 'local-data-library/1', records: structuredClone(records).map(({ layout: _l, ...r }) => r), warnings: [],
        datasets: ['design_evaluation', 'strict_area'].map(id => ({ id, label: id, count: 0 })) }),
    },
    editor: {
      records: async () => [{ key: OTHER, parent_label: 'Parent', electrode_count: 40, finished_at: '2026-11-20T00:00:00Z' }],
      parents: async visible => visible(structuredClone(records)).filter(r => r.dataset_id !== 'design_evaluation'),
    },
  };
}

void test('HTTP: lists show one browser\'s records plus public and official ones; publishing is owner-only', async t => {
  const root = await directory(t), official = hex('official');
  const records = [
    { id: RECORD, dataset_id: 'design_evaluation', status: 'completed', label: 'My unpublished layout', layout: { xyzMm: [] } },
    { id: official, dataset_id: 'strict_area', status: 'completed', label: 'Official', layout: { xyzMm: [] } },
  ];
  const queue = scientificFixture(root, records), done = { id: randomUUID(), key: RECORD, status: 'completed', result: { ok: true } };
  const adapter = { prepare: async r => ({ request: r, key: r.key }), lookup: async () => ({ hit: true, job: done }), start: async () => ({}),
    get: () => null, busy: () => false, pid: () => undefined, cancel: () => {} };
  const visibility = new RecordVisibility({ directory: queue.runtime.queueDirectory, scope: 'owner', review: true });
  const scheduler = new CommunityQueue({ directory: queue.runtime.queueDirectory, pollMs: 3600000, visibility,
    adapters: { 'local-compute': adapter, 'design-evaluation': adapter, 'electrode-editor': adapter, 'source-reception': adapter } });
  later(t, () => scheduler.dispose());
  const guard = createAccessPolicy().guard, tokenMatches = (value, expected) => value === expected;
  const middleware = communityMiddleware({ scheduler, queue, guard, send: sendJson, tokenMatches, legacy: computeMiddleware(queue, guard, scheduler) });
  const server = createServer((req, res) => middleware(req, res, () => res.writeHead(404).end()));
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  later(t, async () => { const stopped = once(server, 'close'); server.close(); server.closeAllConnections(); await stopped; });
  const origin = `http://127.0.0.1:${server.address().port}`, cookies = new Map();
  const call = async (path, { browser = 'A', method = 'GET', body, token = queue.token, raw } = {}) => {
    const response = await fetch(origin + path, { method, headers: { Origin: origin, Cookie: cookies.get(browser) ?? '',
      ...(method === 'GET' ? {} : { 'Content-Type': 'application/json', ...(token ? { 'X-EEG-Compute-Token': token } : {}) }) },
    ...(raw !== undefined ? { body: raw } : body ? { body: JSON.stringify(body) } : {}) });
    if (response.headers.get('set-cookie')) cookies.set(browser, response.headers.get('set-cookie').split(';')[0]);
    return { status: response.status, data: await response.json() };
  };
  const ids = async browser => (await call('/api/local-compute/library', { browser })).data.records.map(r => [r.id, r.visibility?.state ?? 'official', r.visibility?.owned ?? null]);
  await call('/api/local-compute/health'); await call('/api/local-compute/health', { browser: 'B' });
  // Browser A obtains both records (a cache hit makes it an owner); B never submitted them.
  assert.equal((await call('/api/design-evaluation/lookup', { method: 'POST', body: { key: RECORD } })).status, 200);
  assert.equal((await call('/api/electrode-editor/lookup', { method: 'POST', body: { key: OTHER } })).status, 200);
  assert.deepEqual(await ids('A'), [[RECORD, 'private', true], [official, 'official', null]]);
  assert.deepEqual(await ids('B'), [[official, 'official', null]]);
  const listB = (await call('/api/local-compute/library', { browser: 'B' })).data;
  assert.deepEqual(listB.library_scope, { scope: 'owner', review: true });
  assert.equal(listB.datasets.find(d => d.id === 'design_evaluation').count, 0);
  assert.deepEqual((await call('/api/electrode-editor/records', { browser: 'B' })).data.records, []);
  assert.equal((await call('/api/electrode-editor/records')).data.records[0].visibility.state, 'private');
  assert.deepEqual((await call('/api/electrode-editor/parents', { browser: 'B' })).data.records.map(r => r.id), [official]);
  // A link still opens an unlisted record; the owner's copy carries its visibility.
  assert.equal((await call(`/api/local-compute/library/${RECORD}`, { browser: 'B' })).data.record.visibility.owned, false);
  assert.equal((await call(`/api/local-compute/library/${RECORD}`)).data.record.visibility.state, 'private');
  // Publishing: token, owner, body shape, existence.
  const publish = (browser, value, extra = {}) => call(`/api/local-compute/library/${RECORD}/visibility`, { browser, method: 'POST', body: { public: value }, ...extra });
  assert.equal((await publish('A', true, { token: '' })).status, 403);
  assert.equal((await publish('B', true)).status, 403);
  const extra = await call(`/api/local-compute/library/${RECORD}/visibility`, { method: 'POST', raw: '{"public": true, "x": 1}' });
  assert.equal(extra.status, 400, JSON.stringify(extra.data));
  assert.equal((await call(`/api/local-compute/library/${RECORD}/visibility`, { method: 'POST', raw: 'x'.repeat(300) })).status, 413);
  assert.equal((await call(`/api/local-compute/library/${hex('missing')}/visibility`, { method: 'POST', body: { public: true } })).status, 404);
  assert.equal((await call(`/api/local-compute/library/${RECORD}/visibility`)).status, 405);
  const pending = await publish('A', true);
  assert.equal(pending.status, 200); assert.equal(pending.data.visibility.state, 'pending');
  assert.deepEqual(await ids('B'), [[official, 'official', null]]);
  await moderate(queue.runtime.queueDirectory, 'approve', RECORD);
  assert.deepEqual(await ids('B'), [[RECORD, 'public', false], [official, 'official', null]]);
  assert.equal(JSON.parse(await readFile(join(queue.runtime.queueDirectory, 'library/records', `${RECORD}.json`), 'utf8')).label, 'My unpublished layout');
  // Removal hides the record and its links from everyone but its owners.
  await moderate(queue.runtime.queueDirectory, 'remove', RECORD, '--reason', 'Name');
  assert.deepEqual(await ids('B'), [[official, 'official', null]]);
  assert.equal((await call(`/api/local-compute/library/${RECORD}`, { browser: 'B' })).status, 404);
  assert.equal((await call(`/api/local-compute/library/${RECORD}/bundle`, { browser: 'B' })).status, 404);
  assert.equal((await publish('A', true)).status, 409);
  assert.deepEqual(await ids('A'), [[RECORD, 'removed', true], [official, 'official', null]]);
  // The editor record publishes through the same endpoint with a generated label.
  const edit = await call(`/api/local-compute/library/${OTHER}/visibility`, { method: 'POST', body: { public: true } });
  assert.equal(edit.data.visibility.state, 'pending');
  assert.equal(JSON.parse(await readFile(join(queue.runtime.queueDirectory, 'library/records', `${OTHER}.json`), 'utf8')).label, 'Parent · 电极编辑 · 40电极');
  // A page visit renews the same visitor cookie; API calls do not rewrite it.
  const page = await fetch(origin + '/library', { headers: { Origin: origin, Accept: 'text/html', Cookie: cookies.get('A') } });
  assert.equal(page.headers.get('set-cookie').split(';')[0], cookies.get('A'));
  assert.match(page.headers.get('set-cookie'), /Max-Age=2592000/);
  assert.equal((await fetch(origin + '/api/local-compute/library', { headers: { Origin: origin, Cookie: cookies.get('A') } })).headers.get('set-cookie'), null);
  // Rate limit is shared with submissions.
  for (let i = 0; i < 20; i++) await publish('A', false);
  assert.equal((await publish('A', false)).status, 429);
});

void test('owners are recorded when a queued task completes, except browsers that left it', async t => {
  const root = await directory(t); await mkdir(join(root, 'queue'), { recursive: true });
  const visibility = new RecordVisibility({ directory: join(root, 'queue'), scope: 'owner' });
  const jobs = new Map(); let running = null;
  const adapter = { prepare: async r => ({ request: r, key: r.key }), lookup: async () => ({ hit: false }),
    start: async r => { running = { id: randomUUID(), key: r.key, status: 'running' }; jobs.set(running.id, running); return { job: running }; },
    get: id => jobs.get(id), busy: () => running?.status === 'running', pid: () => undefined, cancel: () => {} };
  const scheduler = new CommunityQueue({ directory: join(root, 'queue'), pollMs: 3600000, visibility, adapters: { 'design-evaluation': adapter } });
  later(t, () => scheduler.dispose());
  const a = { id: A, ip: 'x' }, b = { id: B, ip: 'x' }, c = { id: hex('C'), ip: 'x' };
  const first = await scheduler.submit('design-evaluation', { key: RECORD }, a);
  await scheduler.submit('design-evaluation', { key: RECORD }, b);
  await scheduler.submit('design-evaluation', { key: RECORD }, c);
  await scheduler.cancel(first.job.id, c, 'design-evaluation');
  await scheduler.tick();
  assert.equal(visibility.entries.has(RECORD), false, 'nothing is owned before the record exists');
  running.status = 'completed'; await scheduler.tick();
  assert.deepEqual(visibility.entries.get(RECORD).owners, [A, B]);
  const failed = await scheduler.submit('design-evaluation', { key: OTHER }, a);
  await scheduler.tick(); running.status = 'failed'; await scheduler.tick();
  assert.equal(scheduler.own(failed.job.id, a).status, 'failed'); assert.equal(visibility.entries.has(OTHER), false);
});
