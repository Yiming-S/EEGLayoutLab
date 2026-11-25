import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { curateLibrary, redactHomePaths, showcaseHealth, SHOWCASE_DATA_SCHEMA as WRITTEN_SCHEMA } from './build-showcase-data.mjs';
import { installShowcaseApi, showcaseFile, showcaseRefusal, SHOWCASE_DATA_SCHEMA, SHOWCASE_READ_ONLY_CODE } from '../lib/showcase-api.ts';
import { guideStepHref } from '../lib/usage-guide.ts';

const library = {
  schema: 'local-data-library/1',
  local_only: true,
  records: [
    { id: 'a', dataset_id: 'strict_area', label: 'A', visibility: { scope: 'shared' } },
    { id: 'b', dataset_id: 'offline_radius', label: 'B' },
    { id: 'c', dataset_id: 'design_evaluation', label: 'C', visibility: { scope: 'shared' } },
    { id: 'd', dataset_id: 'design_evaluation', label: 'D' },
  ],
  warnings: ['/Users/someone/results missing'],
  datasets: [{ id: 'strict_area', count: 1 }, { id: 'offline_radius', count: 1 }, { id: 'design_evaluation', count: 2 }],
  electrode_annotations: [{ id: 'x' }],
  library_scope: { scope: 'owner' },
};
const curation = { library: { datasets: ['strict_area'], records: [{ id: 'c', label: 'C', bundle: true }] } };

void test('the showcase library keeps the curated records and their dataset counts, without visitor fields', () => {
  const curated = curateLibrary(library, curation);
  assert.deepEqual(curated.records.map((record) => record.id), ['a', 'c']);
  assert.ok(curated.records.every((record) => !('visibility' in record)));
  assert.deepEqual(curated.datasets, [{ id: 'strict_area', count: 1 }, { id: 'design_evaluation', count: 1 }]);
  assert.deepEqual([curated.warnings, curated.electrode_annotations, 'library_scope' in curated], [[], [], false]);
  assert.throws(() => curateLibrary(library, { library: { datasets: [], records: [{ id: 'zz' }] } }), /not in the host's library/);
  assert.throws(() => curateLibrary(library, { library: { datasets: [], records: [{ id: 'c', label: 'renamed' }] } }), /labelled "C"/);
});

void test('home-directory prefixes are written as ~ in every string of the published data', () => {
  const { value, count } = redactHomePaths({ identity: { python: '/Users/someone/EEG/.runtime/bin/python' }, list: ['/home/other/x/y', 'plain'] });
  assert.deepEqual(value, { identity: { python: '~/EEG/.runtime/bin/python' }, list: ['~/x/y', 'plain'] });
  assert.equal(count, 2);
});

void test('published health reports no computation and carries no session token', () => {
  const health = showcaseHealth({ available: true, token: 'secret', active_job: { id: 'j' }, max_concurrent_jobs: 1, supported_masks: ['PL'] });
  assert.deepEqual(health, { available: false, showcase: true, token: 'showcase-read-only', active_job: null, max_concurrent_jobs: 0, maintenance: false, drained: false, supported_masks: ['PL'] });
});

void test('only listed GET paths without a query map to showcase files', () => {
  const paths = new Set(['/api/local-compute/library', '/api/local-compute/library/a/bundle']);
  assert.equal(WRITTEN_SCHEMA, SHOWCASE_DATA_SCHEMA);
  assert.equal(showcaseFile('/api/local-compute/library', '', paths), '/showcase-api/local-compute/library.json');
  assert.equal(showcaseFile('/api/local-compute/library/a/bundle', '', paths), '/showcase-api/local-compute/library/a/bundle.json');
  assert.equal(showcaseFile('/api/local-compute/library/a/bundle', '?annotation_id=1', paths), null);
  assert.equal(showcaseFile('/api/local-compute/jobs', '', paths), null);
  assert.match(showcaseRefusal('zh-CN'), /只读展示版/);
  assert.match(showcaseRefusal('en'), /read-only showcase/);
});

void test('the installed fetch answers /api from showcase files and refuses everything else', async (t) => {
  const origin = 'https://showcase.example';
  const sent = [];
  const network = async (input) => {
    const url = String(input);
    sent.push(url);
    if (url === '/showcase-api/index.json') return Response.json({ schema: SHOWCASE_DATA_SCHEMA, paths: ['/api/robustness-studies'] });
    if (url === '/showcase-api/robustness-studies.json') return Response.json({ studies: [] });
    if (url === 'https://elsewhere.example/api/x') return new Response('passed through');
    return new Response('missing', { status: 404 });
  };
  const saved = { window: globalThis.window, document: globalThis.document };
  globalThis.window = { fetch: network, location: { href: `${origin}/design`, origin } };
  globalThis.document = { documentElement: { lang: 'en' } };
  t.after(() => { globalThis.window = saved.window; globalThis.document = saved.document; });
  installShowcaseApi();
  installShowcaseApi(); // a second call keeps the first wrapper

  const listed = await window.fetch('/api/robustness-studies');
  assert.deepEqual([listed.status, await listed.json(), listed.headers.get('X-EEG-API-Version')], [200, { studies: [] }, '1']);
  for (const [path, init] of [['/api/local-compute/jobs', { method: 'POST', body: '{}' }], ['/api/projects', undefined], ['/open?token=x', undefined]]) {
    const refused = await window.fetch(path, init);
    assert.equal(refused.status, 403, path);
    assert.deepEqual(await refused.json(), { error: showcaseRefusal('en'), code: SHOWCASE_READ_ONLY_CODE });
  }
  assert.equal(await (await window.fetch('https://elsewhere.example/api/x')).text(), 'passed through');
  await assert.rejects(window.fetch('/api/robustness-studies', { signal: AbortSignal.abort() }), { name: 'AbortError' });
  assert.deepEqual(sent.filter((url) => url.startsWith('/showcase-api/index')), ['/showcase-api/index.json']);
  assert.ok(!sent.some((url) => url.startsWith('/api/')), 'no /api request reaches the network');
});

void test('the committed curation names records the committed data includes', async () => {
  const committed = JSON.parse(await readFile(new URL('../showcase/curation.json', import.meta.url), 'utf8'));
  const index = JSON.parse(await readFile(new URL('../showcase/api/index.json', import.meta.url), 'utf8'));
  assert.equal(index.schema, SHOWCASE_DATA_SCHEMA);
  for (const entry of committed.library.records) {
    assert.ok(index.paths.includes(`/api/local-compute/library/${entry.id}`), entry.label);
    if (entry.bundle) assert.ok(index.paths.includes(`/api/local-compute/library/${entry.id}/bundle`), entry.label);
  }
  const published = JSON.parse(await readFile(new URL('../showcase/api/local-compute/library.json', import.meta.url), 'utf8'));
  for (const record of published.records) assert.ok(index.paths.includes(`/api/local-compute/library/${record.id}`), record.id);
  const text = await Promise.all(index.paths.map((path) => readFile(new URL(`../showcase/api/${path.slice('/api/'.length)}.json`, import.meta.url), 'utf8')));
  assert.ok(!text.some((body) => /\/Users\/|\/home\/|\/private\/var\//.test(body)), 'no local path is published');
});

void test('in the showcase the guide opens the page of each step, except the workspace home it leaves out', async () => {
  const source = await readFile(new URL('../app/guide/page.tsx', import.meta.url), 'utf8');
  const paths = [...source.matchAll(/\bpath: '([^']+)'/g)].map((match) => match[1]);
  assert.ok(paths.includes('/') && paths.includes('/design') && paths.includes('/reception'), paths.join(' '));
  for (const path of paths) {
    assert.equal(guideStepHref(path, 75, false), path + '?ar=75');
    assert.equal(guideStepHref(path, 75, true), path === '/' ? null : path + '?ar=75');
  }
});
