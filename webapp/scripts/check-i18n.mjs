import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import Module, { createRequire } from 'node:module';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { resolveLocale, translateText, retentionTerminology, localize, formatDate } from '../lib/i18n/core.ts';
import { localizedRecordTitle, recordSearchText } from '../lib/i18n/records.ts';
import { decisionMarkdown, designCSV, qualification } from '../lib/design-decision.ts';
import { requestKey } from '../lib/local-compute.ts';
import { sourceKey } from '../lib/source-reception.ts';
import catalog from '../lib/i18n/catalog.json' with { type: 'json' };
import simulationCatalog from '../lib/i18n/simulation-catalog.json' with { type: 'json' };
import { SIMULATION_SECTIONS, SIMULATION_DETAIL_IDS, isSimulationGuideHash } from '../lib/simulation-guide.ts';
import { COPYRIGHT_NOTICE, copyrightHref, isCopyrightHash } from '../lib/copyright.ts';
import { documentationHref, METHOD_CONTENTS } from '../lib/documentation.ts';
import { USAGE_EXPLANATIONS } from '../lib/usage-guide.ts';
import { preserveResultsContext, resultsViewHref, resultQualification, savedLayoutActions } from '../lib/results-library.ts';

const root = path.resolve(import.meta.dirname, '..');
// Compile UI fixtures in memory for server-render unit tests; this is not a
// browser or a DOM text-replacement system. No app/data files are generated.
const modules = new Map();
function loadUI(file) {
  let target = path.resolve(root, file);
  if (!fs.existsSync(target)) target = ['.tsx', '.ts', '.json'].map(e => target + e).find(p => fs.existsSync(p));
  if (!target) throw new Error('Fixture module not found: ' + file);
  if (target.endsWith('.json')) return JSON.parse(fs.readFileSync(target, 'utf8'));
  if (modules.has(target)) return modules.get(target).exports;
  const unit = new Module(target); modules.set(target, unit);
  unit.filename = target; unit.paths = Module._nodeModulePaths(path.dirname(target));
  const require = createRequire(target);
  unit.require = (specifier) => {
    if (specifier.startsWith('@/')) return loadUI(specifier.slice(2));
    if (specifier.startsWith('.')) return loadUI(path.relative(root, path.resolve(path.dirname(target), specifier)));
    return require(specifier);
  };
  unit._compile(ts.transpileModule(fs.readFileSync(target, 'utf8'), { compilerOptions: {
    jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true,
  }, fileName: target }).outputText, target);
  return unit.exports;
}
const { LanguageProvider } = loadUI('components/language-provider.tsx');
const render = (component, props, locale) => renderToStaticMarkup(React.createElement(LanguageProvider, { initialLocale: locale }, React.createElement(component, props)));
const visibleText = html => html.replace(/<(script|style|pre|code)\b[^>]*>[\s\S]*?<\/\1>/g, '').replace(/<[^>]+>/g, '').replaceAll('简体中文', '');

void test('usage and methods are separate bilingual pages with preserved content and working section links', () => {
  const Guide = loadUI('app/guide/page.tsx').default;
  const Method = loadUI('app/method/page.tsx').default;
  for (const locale of ['zh-CN', 'en']) {
    const guide = render(Guide, {}, locale), method = render(Method, {}, locale);
    if (locale === 'en') assert.doesNotMatch(visibleText(guide), /[\u3400-\u9fff]/);
    assert.match(guide, /aria-current="page"[^>]*>User Guide|使用指南|User Guide/);
    assert.equal(USAGE_EXPLANATIONS.length, 7);
    for (const [, body] of USAGE_EXPLANATIONS) assert.ok(guide.includes(renderToStaticMarkup(React.createElement(React.Fragment, null, translateText(body, locale)))), body);
    for (const id of ['purpose', 'compare', 'design', 'electrodes', 'reception', 'reading', 'records']) {
      assert.equal((guide.match(new RegExp('id="usage-' + id + '"', 'g')) ?? []).length, 1);
      assert.ok(guide.includes('href="#usage-' + id + '"'));
    }
    assert.ok(!guide.includes('id="retention-guide"'));
    assert.ok(!method.includes('id="usage-purpose"'));
    assert.ok(method.indexOf('id="simulation-model"') < method.indexOf('id="model-terms"'));
    for (const [id] of METHOD_CONTENTS) assert.equal((method.match(new RegExp('id="' + id + '"', 'g')) ?? []).length, 1, id);
    for (const match of guide.matchAll(/href="\/method#([^"&]+)"/g)) assert.ok(method.includes('id="' + match[1] + '"'), match[1]);
  }
});

void test('documentation navigation retains the original working query across both pages and rejects external returns', () => {
  const search = '?ar=32&record=abc&sourceMode=multi_source&region=frontal&seed=2026';
  const guide = new URL(documentationHref('/reception', search, 'guide', 'usage-reception'), 'http://localhost');
  const method = new URL(documentationHref(guide.pathname, guide.search, 'method', 'simulation-sources'), guide);
  const back = new URL(documentationHref(method.pathname, method.search, 'guide'), method);
  for (const url of [guide, method, back]) {
    assert.equal(url.searchParams.get('ar'), '32');
    assert.equal(url.searchParams.get('returnTo'), '/reception' + search);
  }
  assert.equal(method.hash, '#simulation-sources');
  assert.equal(new URL(copyrightHref('/guide', guide.search, 'about-copyright'), guide).searchParams.get('returnTo'), '/reception' + search);
  for (const bad of ['https://example.com', '//example.com', '/unsupported']) {
    const url = new URL(documentationHref('/guide', '?ar=32&returnTo=' + encodeURIComponent(bad), 'method'), guide);
    assert.equal(url.searchParams.get('returnTo'), '/?ar=32');
  }
});

void test('locale resolution honors explicit choice and browser language quality', () => {
  assert.equal(resolveLocale('en', 'zh-CN'), 'en');
  assert.equal(resolveLocale('zh-CN', 'en-US'), 'zh-CN');
  assert.equal(resolveLocale(null, 'zh-TW, en;q=0.8'), 'zh-CN');
  assert.equal(resolveLocale(null, 'en;q=0.9, zh;q=0.5'), 'en');
  assert.equal(resolveLocale(null, 'zh;q=0, en;q=0.3'), 'en');
  assert.equal(resolveLocale('invalid', 'de-DE'), 'en');
});

void test('catalog has unique sources, both languages, and matching typed placeholder indices', () => {
  const sources = new Set();
  for (const [id, entry] of Object.entries(catalog)) {
    assert.ok(entry.source && entry.en, id);
    assert.ok(!sources.has(entry.source), id); sources.add(entry.source);
    assert.doesNotMatch(entry.en, /[\u3400-\u9fff]/, id);
    const tokens = s => [...s.matchAll(/\{\{(\d+)\}\}/g)].map(m=>m[1]).sort((a,b)=>Number(a)-Number(b));
    assert.deepEqual(tokens(entry.source), tokens(entry.en), id);
  }
});

void test('translation preserves numbers, absent metrics, raw objects, and schema values', () => {
  const data = Object.freeze({ name: '用户布局', mode: 'preset', mask_codes: ['AL', 'AR'], values: [null, undefined, -0.2, 1.1] });
  assert.strictEqual(localize(data, 'en'), data);
  assert.equal(translateText('-20.00%', 'en'), '-20.00%');
  assert.equal(translateText('110.00%', 'en'), '110.00%');
  assert.equal(translateText('尚未计算', 'en'), 'Not yet calculated');
  assert.notEqual(translateText('指标无法计算', 'en'), '0');
  assert.equal(retentionTerminology('AR'), 'AR');
  assert.equal(translateText('AR', 'en'), 'AR');
  assert.equal(translateText('FM + AL + AR', 'en'), 'FM + AL + AR');
});

void test('template messages interpolate values and legacy titles without unresolved Han text', () => {
  for (const value of ['已选2/4个区域的部位。请补全每个区域后开始计算。', '3区 · 双耳后＋前额 · 半径≤35 mm · 点距4 mm · 场与敏感度优化', '计算结果校验失败：区域几何无效']) {
    assert.doesNotMatch(translateText(value, 'en'), /[\u3400-\u9fff]|\{\{\d/);
  }
});

const record = {
  id: 'a'.repeat(64), dataset_id: 'cache', label: '原始中文标题', region_count: 2, mode: 'preset', status: 'completed', compatible: true,
  request: { region_count: 2, radius_mm: 35, mode: 'preset', mask_codes: ['AL','AR'] }, radius_cap_mm: 35, spacing_mm: 4,
  metrics: { field_relative: -0.125, sensitivity_tail: .2, localization_relative: .3, median_mm: 20, p90_mm: 45, reference_field_absolute: .99, reference_median_mm: 10 },
  geometry: { union_area_cm2: 44 }, provenance: { original_label: '原始中文', sha256: 'b'.repeat(64) },
};

void test('results views retain each other’s controls, selected record, sorting, and threshold', () => {
  const search = '?ar=32&domain=low_hair_free&area=60&r=4&metric=sensitivity_tail&filter=cache&regions=2&q=%E8%80%B3&page=3&sort=oldest&record=' + record.id;
  const overview = new URL(resultsViewHref('overview', search, record), 'http://localhost');
  const adjusted = new URL(preserveResultsContext('/?ar=46&domain=whole_scalp_free&area=180&r=6&metric=field_relative', overview.search), overview);
  const listing = new URL(resultsViewHref('records', adjusted.search), adjusted);
  assert.equal(listing.pathname, '/library');
  for (const [key, expected] of Object.entries({ ar: '46', domain: 'whole_scalp_free', area: '180', r: '6', metric: 'field_relative', filter: 'cache', regions: '2', q: '耳', page: '3', sort: 'oldest', record: record.id })) assert.equal(listing.searchParams.get(key), expected, key);
  const cleared = new URL(preserveResultsContext('/library?ar=46&sort=newest', listing.search), listing);
  for (const key of ['filter', 'record', 'q', 'page', 'regions']) assert.equal(cleared.searchParams.has(key), false, key);
  assert.equal(cleared.searchParams.get('area'), '180');
  assert.equal(new URL(resultsViewHref('records', '?ar=32', record), listing).searchParams.get('record'), record.id);
});

void test('shared saved-layout details separate evaluation from qualification and gate downstream actions', () => {
  const { SavedLayoutContent } = loadUI('components/saved-layout-details.tsx');
  const { SiteHeader } = loadUI('components/site-header.tsx');
  const { ResultsNavigation } = loadUI('components/results-navigation.tsx');
  const fixture = { ...record, layout: {
    xyzMm: Array.from({ length: 64 }, () => [0, 0, 0]), referenceXyzMm: Array.from({ length: 64 }, () => [0, 0, 0]),
    regionIndices: Array.from({ length: 64 }, (_, i) => i < 32 ? 0 : 1), regionPatchVertexIndices: [[0], [1]],
  }, geometry: { ...record.geometry, common_graph_radius_mm: 35 } };
  const noLayout = { ...fixture, status: 'no_layout', layout: null, metrics: null };
  assert.equal(resultQualification(noLayout, 32), '无法判断');
  assert.equal(resultQualification(fixture, 32), '未达到要求');
  const before = JSON.stringify(fixture);
  for (const locale of ['zh-CN', 'en']) {
    const html = render(SavedLayoutContent, { record: fixture, ar: 32, returnHref: '/library?ar=32' }, locale);
    const empty = render(SavedLayoutContent, { record: noLayout, ar: 32, returnHref: '/library?ar=32' }, locale);
    const menu = render(SiteHeader, { current: 'library', arPercent: 32, returnHref: '/library?ar=32' }, locale);
    const views = render(ResultsNavigation, { view: 'records', here: '/library?ar=32', selected: fixture }, locale);
    if (locale === 'en') for (const content of [html, empty, menu, views]) assert.doesNotMatch(visibleText(content), /[\u3400-\u9fff]/);
    assert.match(html, /32 \+ 32/); assert.match(html, /-12.50%/);
    assert.match(html, /\/electrodes\?parent=/); assert.match(html, /\/reception\?record=/);
    assert.doesNotMatch(empty, /href="\/reception\?/); assert.doesNotMatch(empty, /href="\/electrodes\?/);
    assert.match(empty, /href="\/design\?saved=/);
    assert.equal((menu.match(/aria-current="page"/g) ?? []).length, 2); // primary group and its visible tool tab
    assert.ok(menu.includes(locale === 'en' ? 'Results Library' : '结果库'));
    assert.ok(views.includes(locale === 'en' ? 'Experiment Overview' : '实验总览'));
    assert.ok(views.includes(locale === 'en' ? 'All Records' : '全部记录'));
  }
  assert.equal(JSON.stringify(fixture), before);
  assert.equal(savedLayoutActions({ ...fixture, dataset_id: 'offline_radius' }, 32, '/').reception, null);
  assert.equal(savedLayoutActions({ ...fixture, dataset_id: 'historical_area' }, 32, '/').edit, null);
  assert.equal(savedLayoutActions({ ...fixture, layout: { ...fixture.layout, regionPatchVertexIndices: undefined } }, 32, '/').edit, null);
  for (const file of ['app/page.tsx', 'app/library/page.tsx']) {
    const source = fs.readFileSync(path.join(root, file), 'utf8');
    assert.match(source, /<SavedLayoutDetails/);
    assert.doesNotMatch(source, /<Head\b|<PerformanceSummary\b|createObjectURL/);
  }
});
void test('historical names are localized while custom names and search results remain stable', () => {
  assert.doesNotMatch(localizedRecordTitle(record, 'en'), /[\u3400-\u9fff]/);
  assert.match(recordSearchText(record), /ear/);
  assert.match(recordSearchText(record), /耳周/);
  const custom = { ...record, dataset_id: 'design_evaluation', label: '标准64导布局' };
  assert.match(localizedRecordTitle(custom, 'en'), /标准64导布局/);
  assert.equal(record.label, '原始中文标题');
});

void test('locale is absent from request/cache identity and threshold assessment', () => {
  const request = Object.freeze(record.request), before = requestKey(request);
  const source = Object.freeze({ record_id: record.id, waveform: 'burst', artifact_scale: 1, seed: 2026, brain_region: 'frontal' });
  const sourceBefore = sourceKey(source);
  const threshold = { field: 32, sensitivity: null, localization: null, p90_mm: null };
  const assessment = qualification(record, threshold);
  for (const locale of ['zh-CN','en','zh-CN']) {
    localizedRecordTitle(record, locale);
    assert.equal(requestKey(request), before); assert.equal(sourceKey(source), sourceBefore);
    assert.deepEqual(qualification(record, threshold), assessment);
  }
});

void test('localized reports preserve negative values and byte-identical raw JSON blocks', () => {
  const supplement = { label: '原始输入', values: [null, -1, 1.2] };
  const threshold = { field: 32, sensitivity: null, localization: null, p90_mm: null };
  const en = decisionMarkdown([record], threshold, supplement, 'en');
  const zh = decisionMarkdown([record], threshold, supplement, 'zh-CN');
  const blocks = s => [...s.matchAll(/```json\n([\s\S]*?)\n```/g)].map(m=>m[1]);
  assert.deepEqual(blocks(en), blocks(zh));
  assert.match(en, /-12.50%/); assert.match(zh, /-12.50%/);
  assert.doesNotMatch(en.replace(/```json[\s\S]*?```/g, ''), /[\u3400-\u9fff]/);
  const design = { name: '原始布局', xyz_mm: [[1.1,2,3]], region_indices: [0] };
  assert.equal(designCSV(design), '# coordinate_system=ernie_native_mm; unit=mm; region=zero_based\nelectrode,region,x_mm,y_mm,z_mm\nE1,0,1.1,2,3');
});

void test('header renders both language choices and all navigation in the selected language', () => {
  const { SiteHeader } = loadUI('components/site-header.tsx');
  const en = render(SiteHeader, { current: 'design', arPercent: 32 }, 'en');
  assert.match(en, /English/); assert.match(en, /简体中文/); assert.match(en, /Layout Design/);
  assert.doesNotMatch(visibleText(en), /[\u3400-\u9fff]/);
  assert.match(render(SiteHeader, { current: 'design' }, 'zh-CN'), /布局设计/);
});

void test('full method and retention guide server-render in English without untranslated system text', () => {
  const Method = loadUI('app/method/page.tsx').default;
  const html = render(Method, {}, 'en');
  const leaked = visibleText(html).match(/.{0,60}[\u3400-\u9fff].{0,100}/g);
  assert.deepEqual(leaked, null);
  assert.match(html, /Minimum Required Retention/i);
  assert.match(html, /τ/);
  assert.doesNotMatch(visibleText(html), /\bAR\b/);
});

void test('copyright footer and notice render in both languages with separate third-party attribution', () => {
  const { SiteFooter } = loadUI('components/site-footer.tsx');
  const Method = loadUI('app/method/page.tsx').default;
  for (const locale of ['zh-CN', 'en']) {
    const footer = render(SiteFooter, {}, locale);
    const method = render(Method, {}, locale);
    assert.match(footer, /© 2026 Yiming Shen/);
    assert.match(footer, /#about-copyright/);
    assert.match(footer, /#third-party-licenses/);
    assert.match(footer, locale === 'en' ? /About &amp; Copyright/ : /关于与版权/);
    assert.match(footer, locale === 'en' ? /Third-Party Licenses/ : /第三方许可/);
    if (locale === 'en') assert.doesNotMatch(visibleText(footer), /[\u3400-\u9fff]/);
    assert.equal((method.match(/id="about-copyright"/g) ?? []).length, 1);
    assert.equal((method.match(/id="third-party-licenses"/g) ?? []).length, 1);
    assert.ok(method.indexOf('id="about-copyright"') > method.indexOf('</details>'));
    assert.match(method, /© SimNIBS developers 2024/);
    assert.match(method, /CC BY-NC 4\.0/);
    assert.match(method, /\/models\/ernie\/README\.md/);
    assert.match(method, /\/models\/ernie\/manifest\.json/);
  }
  assert.equal(COPYRIGHT_NOTICE, '© 2026 Yiming Shen');
  const layout = fs.readFileSync(path.join(root, 'app/layout.tsx'), 'utf8');
  assert.match(layout, /<LanguageProvider[^>]*>[\s\S]*\{children\}[\s\S]*<SiteFooter\s*\/>[\s\S]*<\/LanguageProvider>/);
  for (const file of ['README.md', 'manifest.json']) assert.ok(fs.existsSync(path.join(root, 'public/models/ernie', file)));
});

void test('copyright links preserve design queries and method return context without triggering technical details', () => {
  const search = '?ar=32&draft=1&r=4&radius=35&mode=low_hair';
  const link = new URL(copyrightHref('/design', search, 'about-copyright'), 'http://localhost');
  assert.equal(link.pathname, '/method');
  assert.equal(link.searchParams.get('ar'), '32');
  assert.equal(link.searchParams.get('returnTo'), '/design' + search);
  assert.equal(link.hash, '#about-copyright');
  const currentMethod = 'http://localhost/method?ar=32&returnTo=%2Fdesign%3Far%3D32';
  const withinMethod = new URL(copyrightHref('/method', '?ar=32', 'third-party-licenses'), currentMethod);
  assert.equal(withinMethod.search, new URL(currentMethod).search);
  assert.equal(withinMethod.hash, '#third-party-licenses');
  assert.ok(isCopyrightHash('#about-copyright'));
  assert.ok(isCopyrightHash('#third-party-licenses'));
  assert.equal(isCopyrightHash('#anatomical-display'), false);
  const details = fs.readFileSync(path.join(root, 'components/method-context.tsx'), 'utf8');
  assert.match(details, /!isCopyrightHash\(window\.location\.hash\)/);
});

void test('performance cards preserve numeric scores and their meaning in both languages', () => {
  const { PerformanceSummary } = loadUI('components/performance-summary.tsx');
  const props = { metrics: record.metrics, ar: 32, basis: '每区半径上限约束搜索；新结果自动保存为计算记录', returnHref: '/design?ar=32' };
  for (const locale of ['zh-CN','en']) {
    const html = render(PerformanceSummary, props, locale);
    assert.match(html, /-12.50%/); assert.match(html, /20.00%/); assert.match(html, /30.00%/);
    if (locale === 'en') assert.doesNotMatch(visibleText(html), /[\u3400-\u9fff]/);
  }
});

void test('signal-generation guide renders bilingual content before metrics, with technical details locally collapsed', () => {
  const { SimulationExplainer } = loadUI('components/simulation-explainer.tsx');
  const Method = loadUI('app/method/page.tsx').default;
  const anchors = ['simulation-model', ...SIMULATION_SECTIONS.map(([id]) => id), ...SIMULATION_DETAIL_IDS];
  for (const locale of ['zh-CN', 'en']) {
    const html = render(SimulationExplainer, {}, locale);
    const page = render(Method, {}, locale);
    for (const id of anchors) {
      assert.equal((html.match(new RegExp('id="' + id + '"', 'g')) ?? []).length, 1, id);
      assert.ok(isSimulationGuideHash('#' + id));
    }
    for (const [id] of SIMULATION_SECTIONS) assert.ok(html.includes('href="#' + id + '"'));
    const details = html.match(/<details\b[^>]*>/g) ?? [];
    assert.equal(details.length, 4); // three existing explanations plus the DK label mapping
    for (const tag of details) assert.doesNotMatch(tag, /\bopen(?:=|\s|>)/);
    assert.ok(page.indexOf('id="simulation-model"') < page.indexOf('id="retention-guide"'));
    assert.ok(page.indexOf('id="retention-guide"') < page.indexOf('id="electrode-editor"'));
    assert.match(html, /4096/); assert.match(html, /256/); assert.match(html, /5387×4352/);
    assert.match(html, /4000/); assert.match(html, /10 nA·m/); assert.match(html, /0\.65/);
    assert.match(html, /href="#source-field-interaction"/);
    assert.doesNotMatch(html, /\/Users\/|localhost|\[object Object\]|\{\{\d/);
    if (locale === 'en') {
      assert.doesNotMatch(visibleText(html), /[\u3400-\u9fff]/);
      assert.match(html, /How Simulated EEG Is Generated/);
      assert.match(html, /not calculated from the waveform/);
      assert.match(html, /not an independent head model/);
    } else assert.match(html, /模拟脑电信号如何生成/);
  }
  for (const hash of ['', '#simulation-unknown', '#single-head-optimization', '#anatomical-display']) assert.equal(isSimulationGuideHash(hash), false);
  const context = fs.readFileSync(path.join(root, 'components/method-context.tsx'), 'utf8');
  assert.match(context, /!isSimulationGuideHash\(window\.location\.hash\)/);
  assert.match(context, /'#source-field-interaction'/);
});

void test('signal-generation translations have complete unique sources and no shadowed main-catalog entries', () => {
  const sources = new Set(Object.values(catalog).map((entry) => entry.source));
  for (const [key, entry] of Object.entries(simulationCatalog)) {
    assert.ok(entry.source && entry.en, key);
    assert.ok(!sources.has(entry.source), key); sources.add(entry.source);
    assert.equal(translateText(entry.source, 'en'), entry.en, key);
    assert.equal(translateText(entry.source, 'zh-CN'), entry.source, key);
    assert.doesNotMatch(entry.en, /[\u3400-\u9fff]/, key);
  }
  const guide = fs.readFileSync(path.join(root, 'components/simulation-explainer.tsx'), 'utf8');
  assert.doesNotMatch(guide, /fetch\(|\/api\/|localStorage|replaceState|\/Users\//);
});

void test('unknown diagnostic is summarized with raw detail access, not mislabeled as a result', () => {
  const { RuntimeMessage } = loadUI('components/runtime-message.tsx');
  const html = render(RuntimeMessage, { message: '测试用未知诊断', status: 'running' }, 'en');
  assert.match(html, /Computation in progress/); assert.match(html, /Raw Details/);
  assert.doesNotMatch(visibleText(html), /[\u3400-\u9fff]/);
});

void test('all eleven route entry points render English system text', () => {
  for (const route of ['', 'design', 'electrodes', 'coordinates', 'decision', 'reception', 'library', 'guide', 'method', 'results', 'pilot-results']) {
    const Page = loadUI('app/' + (route ? route + '/' : '') + 'page.tsx').default;
    const html = render(Page, {}, 'en');
    assert.doesNotMatch(visibleText(html), /[\u3400-\u9fff]/, route || '/');
  }
});

void test('coordinate import is separate from comparison and the four workspaces remain bilingual', () => {
  const Coordinates = loadUI('app/coordinates/page.tsx').default;
  const Decision = loadUI('app/decision/page.tsx').default;
  const { SiteHeader } = loadUI('components/site-header.tsx');
  for (const locale of ['en', 'zh-CN']) {
    const coordinates = render(Coordinates, {}, locale), decision = render(Decision, {}, locale);
    assert.match(coordinates, /type="file"/); assert.doesNotMatch(decision, /type="file"/);
    assert.doesNotMatch(coordinates, /运行4次网格偏移|Run 4 Grid Displacements/);
    assert.match(decision, /href="\/coordinates\?/);
    const header = render(SiteHeader, { current: 'electrodes', arPercent: 32, returnHref: '/electrodes?ar=32', selection: { id: null, phase: 'edited', channels: 56, regions: 2 } }, locale);
    assert.match(header, /56/); assert.match(header, /aria-current="page"/);
    if (locale === 'en') assert.doesNotMatch(visibleText(header), /[\u3400-\u9fff]/);
    const main = header.match(/<nav aria-label="(?:Main navigation|主导航)"[^>]*>([\s\S]*?)<\/nav>/)?.[1];
    assert.equal((main?.match(/<a /g) ?? []).length, 4);
  }
});

void test('all nine placement choices and 3D controls render without Chinese system text in English', () => {
  const { DesignPlacementOptions } = loadUI('components/placement-options.tsx');
  const html = render(DesignPlacementOptions, { count: 4, choices: [], selected: '', slots: [], onSelect() {}, onSlot() {}, onCount() {} }, 'en');
  assert.doesNotMatch(visibleText(html), /[\u3400-\u9fff]/);
  const { ClusterHeadViewer } = loadUI('components/cluster-head-viewer.tsx');
  const head = render(ClusterHeadViewer, { regionCount: 4, allocation: [16,16,16,16], domainMode: 'low_hair', radiusCm: 3.5 }, 'en');
  assert.doesNotMatch(visibleText(head), /[\u3400-\u9fff]/);
  assert.match(head, /Standard 64-electrode layout/);
});

void test('legacy failure codes are display messages and scientific formula uses tau', () => {
  assert.equal(translateText('no_complete_layout_constructed', 'zh-CN'), '本次预算内未构造出完整布局');
  assert.match(translateText('no_complete_layout_constructed', 'en'), /search budget/);
  assert.match(translateText('Pass(X; AR) = 1[R', 'zh-CN'), /τ/);
});

void test('date formatting follows selected locale without changing stored timestamp', () => {
  const iso='2026-09-09T14:30:15.075Z';
  assert.notEqual(formatDate(iso,'en'), formatDate(iso,'zh-CN'));
  assert.equal(iso,'2026-09-09T14:30:15.075Z');
});
