import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { curateLibrary, redactHomePaths, showcaseHealth, showcaseDisplayCopy, SHOWCASE_DATA_SCHEMA as WRITTEN_SCHEMA } from './build-showcase-data.mjs';
import { installShowcaseApi, showcaseFile, showcaseRefusal, SHOWCASE_DATA_SCHEMA, SHOWCASE_READ_ONLY_CODE } from '../lib/showcase-api.ts';
import { guideStepHref } from '../lib/usage-guide.ts';
import { DISPLAY_COPY_REFERENCE_SCOPE, verifyShowcaseDisplayCopy } from '../lib/showcase-display-copy.ts';
import { fetchReproducibilityBundle } from '../lib/layout-exports.ts';
import { parseDesign, restoreDesignEvaluation } from '../lib/design-decision.ts';
import * as decision from '../lib/design-decision.ts';
import * as taskClient from '../client/task-client.ts';
import * as displayCopies from '../lib/showcase-display-copy.ts';
import { NOISE_MODEL_PRESETS, normalizeDataPrior } from '../contracts/scientific-options.mjs';
import { safeReturnHref } from '../lib/ui-language.ts';
import { canCompareRecord } from '../lib/workspace-navigation.ts';
import { createHookHarness } from './helpers/hook-harness.mjs';

const sha = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
function originalBundle() {
  const request = { action: 'evaluate', radius_mm: 6, seed: 42 };
  const identity = { python: '/Users/researcher/.runtime/bin/python', digests: { model: 'a'.repeat(64) } };
  const key = sha({ request, identity });
  const result = { request, nominal: { field_relative: -0.123456789012345, field_absolute: 1.0000000000000002 },
    coordinates: [[1e-18, -99.123456789, 24]], provenance: { source: '/home/researcher/model/data.npz' } };
  const raw = { key, identity, result, result_sha256: sha(result), finished_at: '2026-11-23T12:00:00Z' };
  return { schema: 'eeg-reproducibility-bundle/1', record_id: key,
    record: { id: key, dataset_id: 'design_evaluation', metrics: result.nominal, provenance: { file: '/Users/researcher/results/cache.json' } },
    source: { path: `results/v2/design_evaluation_jobs/${key}/cache.json`, sha256: sha(raw) },
    search: { configuration: request, curve: [], trace: [], history_status: 'not_applicable_coordinate_evaluation' }, snapshots: [null, null],
    coordinate_note: 'Input: original_record.result.request', original_record: raw,
    reproduction: { request, identity, scope: 'Original archive', metrics_recomputed: false, entrypoint: 'scripts/design_evaluation.py' } };
}

void test('showcase copies separate opaque original references from independently verifiable redacted content', async () => {
  const original = originalBundle(), before = JSON.stringify(original);
  const copy = await showcaseDisplayCopy(original);
  assert.equal(JSON.stringify(original), before, 'publishing never mutates the original');
  assert.equal(JSON.stringify(await showcaseDisplayCopy(original)), JSON.stringify(copy), 'no time or random build identity');
  assert.equal(copy.schema, 'eeg-showcase-display-copy/1');
  assert.equal(copy.source_reference.verification, DISPLAY_COPY_REFERENCE_SCOPE);
  assert.equal(copy.source_reference.scientific_key, original.original_record.key);
  assert.deepEqual(copy.source_reference.source_file, original.source);
  assert.equal(copy.source_reference.result_sha256, original.original_record.result_sha256);
  assert.equal(copy.display_record.redacted_identity.python, '~/.runtime/bin/python');
  assert.equal(copy.display_record.result.provenance.source, '~/model/data.npz');
  assert.deepEqual(copy.display_record.result.nominal, original.original_record.result.nominal);
  assert.deepEqual(copy.display_record.result.coordinates, original.original_record.result.coordinates);
  assert.equal('original_record' in copy || 'reproduction' in copy || 'source' in copy, false);
  assert.equal('key' in copy.display_record || 'result_sha256' in copy.display_record || 'identity' in copy.display_record, false);
  assert.notEqual(copy.integrity.result_sha256, copy.source_reference.result_sha256, 'redacting result provenance changes only the display digest');
  const { integrity, ...payload } = copy;
  assert.equal(integrity.payload_sha256, sha(payload));
  assert.equal(integrity.display_record_sha256, sha(copy.display_record));
  assert.equal(integrity.result_sha256, sha(copy.display_record.result));
  assert.notEqual(sha({ request: copy.display_context.request, identity: copy.display_context.redacted_identity }), copy.record_id, 'never fabricate a new scientific key');
  await verifyShowcaseDisplayCopy(JSON.parse(JSON.stringify(copy, null, 2)), original.record);
});

void test('showcase integrity rejects changed results, payload metadata, unsafe paths and false original claims', async () => {
  const copy = await showcaseDisplayCopy(originalBundle());
  for (const tamper of [
    value => { value.display_record.result.nominal.field_relative = .99; },
    value => { value.search.configuration.seed = 43; },
    value => { value.source_reference.scientific_key = '0'.repeat(64); },
    value => { value.display_context.redacted_identity.python = '/Users/private/bin/python'; },
    value => { value.redaction.original_included = true; },
    value => { value.original_record = value.display_record; },
    value => { value.integrity.result_sha256 = '0'.repeat(64); },
    value => { delete value.integrity.payload_sha256; },
  ]) {
    const changed = structuredClone(copy); tamper(changed);
    await assert.rejects(verifyShowcaseDisplayCopy(changed), /校验失败/);
  }
  await assert.rejects(verifyShowcaseDisplayCopy(copy, { ...copy.record, id: 'f'.repeat(64) }), /校验失败/);
});

void test('showcase publication refuses damaged originals and paths it cannot redact', async () => {
  const damaged = originalBundle(); damaged.original_record.result.nominal.field_relative = .99;
  await assert.rejects(showcaseDisplayCopy(damaged), /Original result checksum mismatch/);
  const unsupported = originalBundle(); unsupported.record.provenance.file = '/private/var/session/private.json';
  await assert.rejects(showcaseDisplayCopy(unsupported), /local path/);
  await assert.rejects(showcaseDisplayCopy(await showcaseDisplayCopy(originalBundle())), /Expected an original/);
});

void test('showcase downloads verify the display schema and cannot be restored as original calculations', async () => {
  const original = originalBundle(), copy = await showcaseDisplayCopy(original);
  let calls = 0;
  const file = await fetchReproducibilityBundle(original.record, async (_url, options) => {
    calls++; assert.equal(options.method, 'GET'); return Response.json(copy);
  });
  assert.equal(calls, 1);
  assert.match(file.filename, /-display-copy\.json$/);
  assert.deepEqual(JSON.parse(file.content), copy);
  assert.throws(() => restoreDesignEvaluation(copy, original.record));
  assert.throws(() => parseDesign(file.content));
  copy.display_record.result.nominal.field_relative = .5;
  await assert.rejects(fetchReproducibilityBundle(original.record, async () => Response.json(copy)), /校验失败/);
});

void test('coordinate restoration verifies showcase copies and opens only an unevaluated coordinate draft', async () => {
  const file = new URL('../showcase/api/local-compute/library/9e4c787ffe1603f136f888fdf59b40b9ad46339b97a97cb3452bc3132e0c18b6/bundle.json', import.meta.url);
  const valid = JSON.parse(await readFile(file, 'utf8'));
  for (const tampered of [false, true]) {
    const copy = structuredClone(valid), calls = [], stored = new Map();
    if (tampered) copy.display_record.result.nominal.field_relative = .123;
    const window = { location: { search: `?a=${copy.record_id}` }, history: { replaceState() {} } };
    const harness = await createHookHarness({
      filename: new URL('../features/decision/use-decision-controller.ts', import.meta.url),
      exportName: 'useDecisionController', args: ['coordinates'], maxTimerMs: Infinity,
      imports: { ...decision, ...taskClient, ...displayCopies, NOISE_MODEL_PRESETS, normalizeDataPrior, safeReturnHref, canCompareRecord,
        useLanguage: () => ({ tx: value => value, locale: 'en' }) },
      globals: { window, sessionStorage: { getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, value) },
        fetch: async (url, options) => {
          calls.push({ url, options });
          if (url.endsWith('/health')) return Response.json({ available: false, active_job: null });
          if (url.endsWith('/library')) return Response.json({ schema: 'local-data-library/1', records: [copy.record] });
          if (url.endsWith('/bundle')) return Response.json(copy);
          return Response.json({ record: copy.record });
        } },
    });
    try {
      await harness.waitFor(state => tampered ? Boolean(state.error) : Boolean(state.imported));
      assert.equal(harness.current.job, null);
      assert.equal(harness.current.result, null);
      assert.equal(harness.current.jobIdentity, '');
      assert.ok(calls.every(({ options }) => !options?.method || options.method === 'GET'));
      if (tampered) {
        assert.match(harness.current.error, /校验失败/);
        assert.equal(harness.current.imported, null);
      } else {
        assert.equal(harness.current.error, '');
        assert.deepEqual(harness.current.imported.xyz_mm, copy.record.layout.xyzMm);
        assert.equal(harness.current.testTarget, 'import');
        assert.match(harness.current.draftNotice, /坐标草稿/);
      }
    } finally { harness.dispose(); }
  }
});

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
    if (entry.bundle) {
      const copy = JSON.parse(await readFile(new URL(`../showcase/api/local-compute/library/${entry.id}/bundle.json`, import.meta.url), 'utf8'));
      await verifyShowcaseDisplayCopy(copy);
      assert.equal(copy.record_id, entry.id);
      const { integrity, ...payload } = copy;
      assert.equal(integrity.payload_sha256, sha(payload));
      assert.equal(integrity.result_sha256, sha(copy.display_record.result));
    }
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
