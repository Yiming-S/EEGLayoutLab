import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import Module, { createRequire } from 'node:module';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { parseDesign, exportDesign, designCSV } from '../lib/design-decision.ts';
import { layoutExportAvailability, layoutExportFile, layoutSummaryMarkdown, fetchReproducibilityBundle } from '../lib/layout-exports.ts';
import catalog from '../lib/i18n/export-refresh-catalog.json' with { type: 'json' };

const fixture = () => ({
  id: 'a'.repeat(64), dataset_id: 'cache', label: 'Saved test layout', region_count: 2,
  mode: 'preset', status: 'completed', compatible: true,
  request: { region_count: 2, radius_mm: 35, mode: 'preset', mask_codes: ['AL', 'AR'] },
  radius_cap_mm: 35, spacing_mm: 4, finished_at: '2026-09-10T12:00:00Z',
  metrics: { field_relative: .82, field_absolute: .813, reference_field_absolute: .99,
    sensitivity_tail: .31, localization_relative: .42, conditional_global: .31,
    median_mm: 14.9, p90_mm: 32.1, reference_median_mm: 10.9 },
  geometry: { common_graph_radius_mm: 34.9, union_area_cm2: 119.97, minimum_chord_distance_mm: 4.8, union_connected_component_count: 2 },
  layout: { id: 'saved', xyzMm: Array.from({ length: 64 }, (_, i) => [(i % 8) * 6, Math.floor(i / 8) * 6, i ? -i / 10 : 0]),
    regionIndices: Array.from({ length: 64 }, (_, i) => Number(i >= 32)),
    referenceXyzMm: Array.from({ length: 64 }, (_, i) => [i, 1, 2]) },
  provenance: { bank_sha256: 'b'.repeat(64), source: 'original', objective: 'min_field_sensitivity20', seed: 2026 },
});

void test('coordinate and layout exports reuse the import schema and preserve order exactly', () => {
  const record = fixture(), original = JSON.stringify(record);
  const csv = layoutExportFile(record, 'coordinates_csv', 32);
  const design = layoutExportFile(record, 'design_json', 32);
  assert.equal(csv.content, designCSV(exportDesign(record)) + '\n');
  assert.deepEqual(parseDesign(csv.content, record.label), { ...exportDesign(record), electrode_names: Array.from({ length: 64 }, (_, i) => `E${i + 1}`) });
  assert.deepEqual(parseDesign(design.content), exportDesign(record));
  assert.equal(parseDesign(design.content).xyz_mm[63][2], -6.3);
  assert.match(csv.content, /^# coordinate_system=ernie_native_mm; unit=mm; region=zero_based/);
  assert.match(csv.filename, /-coordinates\.csv$/); assert.match(design.filename, /-layout\.json$/);
  assert.equal(JSON.stringify(record), original);
});

void test('invalid and partial layouts disable importable exports without fabricating coordinates', () => {
  const bad = [
    { ...fixture(), status: 'no_layout', layout: null },
    { ...fixture(), layout: { ...fixture().layout, xyzMm: fixture().layout.xyzMm.slice(0, 63) } },
    { ...fixture(), layout: { ...fixture().layout, xyzMm: Array(64).fill([1, 2, 3]) } },
    { ...fixture(), layout: { ...fixture().layout, regionIndices: Array.from({ length: 64 }, (_, i) => Number(i > 32)) } },
  ];
  for (const record of bad) {
    assert.equal(layoutExportAvailability(record).design, null);
    for (const kind of ['coordinates_csv', 'design_json']) assert.throws(() => layoutExportFile(record, kind, 32));
    assert.deepEqual(JSON.parse(layoutExportFile(record, 'result_json', 32).content), record);
    assert.match(layoutExportFile(record, 'report_md', 32, 'en').content, /Saved metrics and current criterion/);
  }
});

void test('full-result JSON remains the original record and is distinct from importable design JSON', () => {
  const record = fixture(); record.provenance.original_name = '保留原数据';
  const raw = layoutExportFile(record, 'result_json', 10, 'en');
  assert.deepEqual(JSON.parse(raw.content), record);
  assert.throws(() => parseDesign(raw.content));
  assert.match(raw.filename, /-result\.json$/);
  assert.equal(JSON.parse(layoutExportFile(record, 'design_json', 10).content).schema, 'eeg-electrode-design/1');
});

void test('summary uses the current common threshold, preserves real scores and does not invent metadata', () => {
  const record = fixture(), before = JSON.stringify(record);
  let text = layoutSummaryMarkdown(record, 32, 'en', '2026-09-15T00:00:00Z');
  assert.match(text, /At least one metric is below the requirement/);
  assert.match(text, /82\.00%/); assert.match(text, /31\.00%/); assert.match(text, /32\.10 mm/);
  assert.match(text, /32%/); assert.match(text, /2026-09-15T00:00:00Z/);
  assert.doesNotMatch(text, /[\u3400-\u9fff]|4096|20 dB/);
  assert.match(layoutSummaryMarkdown(record, 30, 'en'), /All three metrics meet the requirement/);
  assert.match(layoutSummaryMarkdown(record, 30, 'zh-CN'), /三项均达到要求/);
  assert.equal(JSON.stringify(record), before);
  record.metrics.field_relative = -0.2; record.metrics.field_absolute = 1.1;
  text = layoutSummaryMarkdown(record, 30, 'en');
  assert.match(text, /-20\.00%/); assert.match(text, /110\.00%/);
  record.metrics.localization_relative = null;
  assert.match(layoutSummaryMarkdown(record, 30, 'en'), /Joint three-metric assessment: Not recorded or not assessable/);
  const empty = { ...record, status: 'no_layout', layout: null, metrics: null };
  assert.match(layoutSummaryMarkdown(empty, 30, 'en'), /Not recorded or not assessable/);
  assert.doesNotMatch(layoutSummaryMarkdown(empty, 30, 'en'), /\| 0\.00%/);
});

void test('experiment export issues exactly one read-only GET and validates schema plus record identity', async () => {
  const record = fixture(), calls = [];
  const bundle = { schema: 'eeg-reproducibility-bundle/1', record_id: record.id, record,
    source: { sha256: 'c'.repeat(64) }, search: { trace: [] }, original_record: { keep: true },
    reproduction: { metrics_recomputed: false } };
  const signal = new AbortController().signal;
  const result = await fetchReproducibilityBundle(record, async (url, options) => {
    calls.push({ url, options }); return new Response(JSON.stringify(bundle));
  }, signal);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, `/api/local-compute/library/${record.id}/bundle`);
  assert.equal(calls[0].options.method, 'GET'); assert.equal(calls[0].options.cache, 'no-store');
  assert.strictEqual(calls[0].options.signal, signal);
  assert.deepEqual(JSON.parse(result.content), bundle);
  assert.match(result.filename, /-reproducibility\.json$/);
  for (const invalid of [null, { ...bundle, schema: 'wrong/1' }, { ...bundle, record_id: 'd'.repeat(64) },
    { ...bundle, record: { ...record, dataset_id: 'historical_area' } }]) {
    await assert.rejects(fetchReproducibilityBundle(record, async () => new Response(JSON.stringify(invalid))), /不匹配/);
  }
});

void test('failed bundle reads are retryable, and unsafe record IDs never issue requests', async () => {
  const record = fixture(); let calls = 0;
  const fetcher = async () => {
    calls += 1;
    return calls === 1 ? new Response('{}', { status: 500 }) : new Response(JSON.stringify({
      schema: 'eeg-reproducibility-bundle/1', record_id: record.id, record,
    }));
  };
  await assert.rejects(fetchReproducibilityBundle(record, fetcher), /读取失败/);
  const result = await fetchReproducibilityBundle(record, fetcher);
  assert.equal(calls, 2); assert.equal(JSON.parse(result.content).record_id, record.id);
  await assert.rejects(fetchReproducibilityBundle({ ...record, id: '../wrong' }, fetcher), /编号格式/);
  assert.equal(calls, 2);
});

void test('new export translations are bilingual and do not duplicate existing catalog sources', () => {
  const directory = path.resolve(import.meta.dirname, '../lib/i18n');
  const sources = new Set();
  for (const filename of fs.readdirSync(directory).filter((n) => n.endsWith('catalog.json') && n !== 'export-refresh-catalog.json')) {
    for (const entry of Object.values(JSON.parse(fs.readFileSync(path.join(directory, filename), 'utf8')))) sources.add(entry.source);
  }
  for (const [key, value] of Object.entries(catalog)) {
    assert.ok(value.source && value.en, key); assert.doesNotMatch(value.en, /[\u3400-\u9fff]/, key);
    assert.ok(!sources.has(value.source), `Duplicate source: ${value.source}`); sources.add(value.source);
    const tokens = text => [...text.matchAll(/\{\{(\d+)\}\}/g)].map((m) => m[1]);
    assert.deepEqual(tokens(value.source), tokens(value.en), key);
  }
});

// Render without a browser. Loading or opening the menu must not fetch a bundle.
const root = path.resolve(import.meta.dirname, '..'), loaded = new Map();
function loadUI(file) {
  let target = path.resolve(root, file);
  if (!fs.existsSync(target)) target = ['.tsx', '.ts', '.json'].map((extension) => target + extension).find((p) => fs.existsSync(p));
  if (!target) throw new Error('Fixture module not found: ' + file);
  if (target.endsWith('.json')) return JSON.parse(fs.readFileSync(target, 'utf8'));
  if (loaded.has(target)) return loaded.get(target).exports;
  const unit = new Module(target); loaded.set(target, unit); unit.filename = target;
  unit.paths = Module._nodeModulePaths(path.dirname(target)); const require = createRequire(target);
  unit.require = (specifier) => specifier.startsWith('@/') ? loadUI(specifier.slice(2)) : specifier.startsWith('.')
    ? loadUI(path.relative(root, path.resolve(path.dirname(target), specifier))) : require(specifier);
  unit._compile(ts.transpileModule(fs.readFileSync(target, 'utf8'), { compilerOptions: {
    jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true,
  }, fileName: target }).outputText, target);
  return unit.exports;
}

void test('export menu renders five distinct formats in both languages without automatic fetch', () => {
  const { LayoutExportMenu } = loadUI('components/layout-export-menu.tsx');
  const { LanguageProvider } = loadUI('components/language-provider.tsx');
  const original = globalThis.fetch; let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw new Error('Unexpected fetch'); };
  try {
    for (const locale of ['en', 'zh-CN']) {
      const html = renderToStaticMarkup(React.createElement(LanguageProvider, { initialLocale: locale },
        React.createElement(LayoutExportMenu, { record: fixture(), ar: 32 })));
      assert.match(html, /<details/); assert.equal((html.match(/<button/g) ?? []).length, 5);
      if (locale === 'en') assert.doesNotMatch(html.replace(/<[^>]+>/g, ''), /[\u3400-\u9fff]/);
      const invalid = renderToStaticMarkup(React.createElement(LanguageProvider, { initialLocale: locale },
        React.createElement(LayoutExportMenu, { record: { ...fixture(), layout: null }, ar: 32 })));
      assert.equal((invalid.match(/disabled=""/g) ?? []).length, 2);
    }
  } finally { globalThis.fetch = original; }
  assert.equal(calls, 0);
});
