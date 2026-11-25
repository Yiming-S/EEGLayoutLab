import test from 'node:test';
import { NOISE_MODEL_PRESETS, noiseModelId } from '../contracts/scientific-options.mjs';
import assert from 'node:assert/strict';
import { createHookHarness } from './helpers/hook-harness.mjs';
import { apiJson } from '../client/task-client.ts';
import * as workflow from '../lib/lab-workflow.ts';
import * as placements from '../lib/placement-options.ts';
import * as catalog from '../lib/records-catalog.ts';
import * as layoutPages from '../lib/layout-page.ts';
import * as recordLabels from '../lib/i18n/records.ts';
import * as librarySearch from '../lib/library-search.ts';
import { preserveResultsContext } from '../lib/results-library.ts';
import { requestKey } from '../lib/local-compute.ts';
import { MASK_NAMES, protocolName } from '../lib/ui-language.ts';
import { SOURCE_REGIONS } from '../lib/source-regions.ts';

const json = (value, status = 200) => ({ ok: status < 400, status, json: async () => value });
const protocol = { anatomical_preset_matrix: { 2: [{ masks: ['PL', 'PR'] }] } };
const tx = value => value;
const saved = (letter, extra = {}) => ({
  id: letter.repeat(64), dataset_id: 'strict_area', status: 'completed', label: 'fixture', compatible: false,
  mode: 'whole_scalp_free', region_count: 2, area_cap_cm2: 120, request: null,
  metrics: { field_relative: -.25, sensitivity_tail: .4, localization_relative: .5, conditional_global: -.25 },
  layout: { xyzMm: [[1, 2, 3]], regionIndices: [0], referenceXyzMm: [[4, 5, 6]] },
  ...extra,
});
const library = records => ({ schema: 'local-data-library/1', records, warnings: [] });
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };

async function controller(t, feature, search, fetchSource) {
  const callbacks = new Map(), writes = [], calls = [];
  const window = { location: { search, replace: href => writes.push(href) }, matchMedia: () => ({ matches: true }),
    history: { replaceState: (_state, _title, href) => { writes.push(href); window.location.search = new URL(href, 'http://localhost').search; } },
    addEventListener: (name, callback) => callbacks.set(name, callback), removeEventListener: name => callbacks.delete(name) };
  const harness = await createHookHarness({
    filename: new URL(`../features/${feature}/use-${feature}-controller.ts`, import.meta.url),
    exportName: `use${feature[0].toUpperCase() + feature.slice(1)}Controller`, maxTimerMs: Infinity,
    imports: { apiJson, NOISE_MODEL_PRESETS, presetIdFor: noiseModelId, ...workflow, ...placements, ...catalog, ...layoutPages, ...recordLabels, ...librarySearch, preserveResultsContext, requestKey,
      MASK_NAMES, protocolName, SOURCE_REGIONS, useLanguage: () => ({ tx, locale: 'en' }) },
    globals: { window, document: { getElementById: () => null }, fetch: (url, options) => {
      calls.push({ url, options }); return fetchSource(url, options, calls.length);
    } },
  });
  t.after(() => harness.dispose());
  return { harness, calls, writes, window, navigate: async search => {
    window.location.search = search; callbacks.get('popstate')?.(); await harness.flush();
  } };
}

void test('design restores ordered draft masks and AR, then hides results when regional choices change', async t => {
  const f = await controller(t, 'design', '?draft=1&r=3&radius=40&mode=preset&masks=PL,PR,PL&ar=34', () => json(protocol));
  await f.harness.waitFor(s => s.ready);
  const expected = { region_count: 3, radius_mm: 40, mode: 'preset', mask_codes: ['PL', 'PR', 'PL'] };
  assert.deepEqual(f.harness.current.request, expected);
  const layout = { xyzMm: [[5, 6, 7]] };
  await f.harness.act(s => s.setComputed({ request: expected, status: 'completed', layout, metrics: { field_relative: -.2 } }));
  assert.equal(f.harness.current.layout, layout);
  await f.harness.act(s => s.setAR(62));
  assert.equal(f.harness.current.layout, layout);
  assert.equal(f.calls.length, 1);
  assert.equal(new URL(f.harness.current.here, 'http://localhost').searchParams.get('masks'), 'PL,PR,PL');
  await f.harness.act(s => s.changeRegions(4));
  assert.equal(f.harness.current.request, null);
  assert.equal(f.harness.current.layout, undefined);
  assert.equal(f.harness.current.metrics, undefined);
});

void test('an area record remains read-only until explicit radius drafting and never starts computation', async t => {
  const record = saved('a');
  const f = await controller(t, 'design', `?from=${record.id}&ar=48`, url => json(url.startsWith('/data/') ? protocol : { record }));
  await f.harness.waitFor(s => s.ready);
  assert.equal(f.harness.current.editing, false);
  assert.deepEqual(f.harness.current.layout, record.layout);
  assert.deepEqual(f.harness.current.metrics, record.metrics);
  await f.harness.act(s => s.startRadius());
  assert.equal(f.harness.current.editing, true);
  assert.equal(f.harness.current.layout, undefined);
  assert.equal(f.harness.current.metrics, undefined);
  assert.deepEqual(f.harness.current.request, { region_count: 2, radius_mm: 35, mode: 'whole_surface' });
  assert.equal(f.calls.length, 2);
  assert.ok(f.calls.every(call => !call.options.method || call.options.method === 'GET'));
});

void test('design rejects an invalid draft without promoting it to a ready request', async t => {
  const f = await controller(t, 'design', '?draft=1&r=5&radius=35&mode=preset&masks=PL', () => json(protocol));
  await f.harness.waitFor(s => Boolean(s.error));
  assert.equal(f.harness.current.ready, false);
  assert.equal(f.harness.current.error, '草稿参数无效');
  assert.equal(f.writes.length, 0);
});

void test('library keeps an explicit record outside filters, retains overview URL context and opens a layout on its page', async t => {
  const a = saved('a'), b = saved('b', { region_count: 3 });
  const f = await controller(t, 'library', `?record=${a.id}&regions=3&ar=32&area=180&domain=low_hair_free`, url => {
    if (url.endsWith('/library')) return json(library([a, b]));
    if (url.includes('electrode-editor')) return json({ error: 'editor offline' }, 503);
    return json({ schema: 'browser-experiment-records/1', records: [] });
  });
  await f.harness.waitFor(s => !s.loading);
  assert.equal(f.harness.current.selected.id, a.id);
  assert.deepEqual(f.harness.current.choices.map(row => row.id), [b.id]);
  assert.deepEqual(f.harness.current.catalogWarnings, ['editor offline']);
  assert.equal(f.harness.current.error, '');
  assert.equal(new URL(f.harness.current.here, 'http://localhost').searchParams.get('area'), '180');
  assert.ok(f.writes.includes(`/layout?id=${a.id}&ar=32`));
  await f.navigate(`?record=${b.id}&regions=2&ar=58&sort=oldest`);
  assert.equal(f.harness.current.selected.id, b.id);
  assert.equal(f.harness.current.ar, 58);
  assert.ok(f.writes.includes(`/layout?id=${b.id}&ar=58`));
  assert.equal(f.calls.length, 3);
});

void test('library refresh aborts stale requests and does not replace newer records with late responses', async t => {
  const old = deferred();
  const f = await controller(t, 'library', '?ar=42', (url, _options, index) => {
    if (index <= 3) return old.promise;
    if (url.endsWith('/library')) return json(library([saved('b')]));
    return json({ schema: 'browser-experiment-records/1', records: [] });
  });
  await f.harness.act(s => s.setRetry(value => value + 1));
  await f.harness.waitFor(s => !s.loading);
  assert.equal(f.calls[0].options.signal.aborted, true);
  old.resolve(json(library([saved('a')])));
  await f.harness.flush();
  assert.deepEqual(f.harness.current.catalog.map(row => row.id), [saved('b').id]);
  assert.equal(f.harness.current.ar, 42);
});

void test('overview restores controls and updates URL/AR without fetching or changing saved coordinates', async t => {
  const record = saved('a', { mode: 'low_hair_free', region_count: 4, area_cap_cm2: 180 });
  const f = await controller(t, 'overview', '?domain=low_hair_free&area=180&r=4&ar=31&metric=field_relative&kind=editor', () => json(library([record])));
  await f.harness.waitFor(s => Boolean(s.data));
  assert.equal(f.harness.current.selected.id, record.id);
  assert.equal(f.harness.current.curve[2].r4, -25);
  const coordinates = f.harness.current.selected.layout;
  await f.harness.act(s => s.setAR(72));
  assert.equal(f.harness.current.selected.layout, coordinates);
  assert.equal(new URL(f.harness.current.here, 'http://localhost').searchParams.get('kind'), 'editor');
  await f.navigate('?domain=whole_scalp_free&area=60&r=2&ar=43&metric=sensitivity_tail');
  assert.equal(f.harness.current.area, 60);
  assert.equal(f.harness.current.metric, 'sensitivity_tail');
  assert.equal(f.harness.current.ar, 43);
  assert.equal(f.calls.length, 1);
});

void test('unmount aborts overview and design loads before their late replies can update state', async t => {
  for (const feature of ['overview', 'design']) {
    const late = deferred();
    const f = await controller(t, feature, '', () => late.promise);
    f.harness.dispose();
    assert.equal(f.calls[0].options.signal.aborted, true);
    late.resolve(json(feature === 'design' ? protocol : library([saved('a')])));
    await f.harness.flush();
    if (feature === 'design') assert.equal(f.harness.current.ready, false);
    else assert.equal(f.harness.current.data, null);
  }
});
