import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import Module, { createRequire } from 'node:module';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { resolveLocale, translateText, retentionTerminology, localize, formatDate } from '../lib/i18n/core.ts';
import { localizedRecordTitle, localizedEditorParentTitle, recordSearchText } from '../lib/i18n/records.ts';
import { decisionMarkdown, designCSV, qualification, jointDecisionThresholds, restoreDesignEvaluation } from '../lib/design-decision.ts';
import { requestKey } from '../lib/local-compute.ts';
import { sourceKey } from '../lib/source-reception.ts';
import catalog from '../lib/i18n/catalog.json' with { type: 'json' };
import simulationCatalog from '../lib/i18n/simulation-catalog.json' with { type: 'json' };
import researchWorkflowCatalog from '../lib/i18n/research-workflow-catalog.json' with { type: 'json' };
import { METHOD_ENTRIES, METHOD_GROUPS, docsHref, movedSection } from '../lib/method-index.ts';
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
    for (const id of METHOD_ENTRIES.flatMap(entry => entry.ids)) assert.equal((method.match(new RegExp('id="' + id + '"', 'g')) ?? []).length, 1, id);
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
  assert.equal(retentionTerminology('2区 · AL + AR · 半径≤35 mm'), '2区 · AL + AR · 半径≤35 mm');
  assert.equal(retentionTerminology('AL + AR · AR阈值90%'), 'AL + AR · 最低保留要求90%');
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
  const search = '?ar=32&domain=low_hair_free&area=60&r=4&metric=sensitivity_tail&filter=cache&regions=2&kind=editor&electrodes=56&location=AR&q=%E8%80%B3&page=3&sort=oldest&record=' + record.id;
  const overview = new URL(resultsViewHref('overview', search, record), 'http://localhost');
  const adjusted = new URL(preserveResultsContext('/?ar=46&domain=whole_scalp_free&area=180&r=6&metric=field_relative', overview.search), overview);
  const listing = new URL(resultsViewHref('records', adjusted.search), adjusted);
  assert.equal(listing.pathname, '/library');
  for (const [key, expected] of Object.entries({ ar: '46', domain: 'whole_scalp_free', area: '180', r: '6', metric: 'field_relative', filter: 'cache', regions: '2', kind: 'editor', electrodes: '56', location: 'AR', q: '耳', page: '3', sort: 'oldest', record: record.id })) assert.equal(listing.searchParams.get(key), expected, key);
  const cleared = new URL(preserveResultsContext('/library?ar=46&sort=newest', listing.search), listing);
  for (const key of ['filter', 'record', 'q', 'page', 'regions', 'kind', 'electrodes', 'location']) assert.equal(cleared.searchParams.has(key), false, key);
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
    assert.ok(menu.includes(locale === 'en' ? 'Layout List' : '布局列表'));
    assert.ok(views.includes(locale === 'en' ? 'Experiment Overview' : '实验总览'));
    assert.ok(views.includes(locale === 'en' ? 'All Records' : '全部记录'));
    for (const dataset_id of ['historical_area', 'offline_radius']) {
      const historical = render(SavedLayoutContent, { record: { ...fixture, dataset_id, label: 'Historical layout fixture' }, ar: 32, returnHref: '/library?ar=32' }, locale);
      assert.doesNotMatch(historical, /href="\/reception\?/);
      assert.ok(historical.includes(locale === 'en' ? 'historical protocol' : '历史协议'));
      if (locale === 'en') assert.doesNotMatch(visibleText(historical), /[\u3400-\u9fff]/);
    }
  }
  assert.equal(JSON.stringify(fixture), before);
  assert.equal(savedLayoutActions({ ...fixture, dataset_id: 'offline_radius' }, 32, '/').reception, null);
  assert.equal(savedLayoutActions({ ...fixture, dataset_id: 'historical_area' }, 32, '/').edit, null);
  assert.equal(savedLayoutActions({ ...fixture, layout: { ...fixture.layout, regionPatchVertexIndices: undefined } }, 32, '/').edit, null);
  // The findings page shows a record's details in place; the layout list opens the layout's page, which shows them.
  for (const [file, details] of [['features/overview/overview-workspace.tsx', /<SavedLayoutDetails/], ['features/layout/layout-workspace.tsx', /<SavedLayoutContent[^>]*returnHref=\{here\}/]]) {
    const source = fs.readFileSync(path.join(root, file), 'utf8');
    assert.match(source, details, file);
    assert.doesNotMatch(source, /<Head\b|<PerformanceSummary\b|createObjectURL/, file);
  }
  const library = fs.readFileSync(path.join(root, 'features/library/library-workspace.tsx'), 'utf8');
  assert.doesNotMatch(library, /<SavedLayoutDetails|<SavedLayoutContent/);
  assert.match(library, /layoutHref\(\{ id: row\.id \}, ar\)/);
});
void test('historical names are localized while custom names and search results remain stable', () => {
  assert.doesNotMatch(localizedRecordTitle(record, 'en'), /[\u3400-\u9fff]/);
  assert.match(recordSearchText(record), /ear/);
  assert.match(recordSearchText(record), /耳周/);
  const custom = { ...record, dataset_id: 'design_evaluation', label: '标准64导布局' };
  assert.match(localizedRecordTitle(custom, 'en'), /标准64导布局/);
  assert.equal(record.label, '原始中文标题');
});

void test('saved editor scores use a complete translated metric label with an unchanged number', () => {
  const source = fs.readFileSync(path.join(root, 'features/electrodes/electrodes-workspace.tsx'), 'utf8');
  assert.ok(source.includes("{date(r.finished_at, true)} · {tx('信号重建保留率')}{' '}"));
  assert.ok(!source.includes("tx('场重建保留率')"));
  const score = (.7039 * 100).toFixed(2) + '%';
  assert.equal(`${translateText('信号重建保留率', 'zh-CN')} ${score}`, '场重建保留率 70.39%');
  assert.equal(`${translateText('信号重建保留率', 'en')} ${score}`, 'Field Reconstruction Retention 70.39%');
});

void test('edited records use structured parent locations while unavailable custom names remain untouched', () => {
  const edited = { parent_id: record.id, parent_label: '2区 · AL + AR · 半径≤35 mm' };
  const before = JSON.stringify(edited);
  const zh = localizedEditorParentTitle(edited, [record], 'zh-CN');
  const en = localizedEditorParentTitle(edited, [record], 'en');
  assert.match(zh, /左耳周扩展区 \+ 右耳周扩展区/);
  assert.doesNotMatch(zh, /最低保留要求/);
  assert.doesNotMatch(en, /[\u3400-\u9fff]/);
  assert.equal(localizedEditorParentTitle({ ...edited, parent_label: '我的 AR 研究方案' }, [], 'zh-CN'), '我的 AR 研究方案');
  assert.equal(localizedEditorParentTitle({ ...edited, parent_label: '我的 AR 研究方案' }, [], 'en'), '我的 AR 研究方案');
  assert.equal(JSON.stringify(edited), before);
});

void test('decision controls disclose all active requirements in both languages', () => {
  const { DecisionRequirements } = loadUI('features/decision/decision-requirements.tsx');
  for (const locale of ['en', 'zh-CN']) {
    const joint = render(DecisionRequirements, { thresholds: jointDecisionThresholds(90), onChange() {} }, locale);
    const custom = render(DecisionRequirements, { thresholds: { mode: 'custom', field: 90, sensitivity: null, localization: null, p90_mm: null }, onChange() {} }, locale);
    const mixed = render(DecisionRequirements, { thresholds: { mode: 'custom', field: 68, sensitivity: 30, localization: null, p90_mm: 20 }, onChange() {} }, locale);
    assert.match(joint, /90%/);
    assert.match(custom, locale === 'en' ? /Checks only field reconstruction/ : /仅检查场重建/);
    assert.match(mixed, /68%/); assert.match(mixed, /30%/); assert.match(mixed, /20 mm/);
    if (locale === 'en') for (const html of [joint, custom, mixed]) assert.doesNotMatch(visibleText(html), /[\u3400-\u9fff]/);
  }
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
  assert.match(en, /English/); assert.match(en, /简体中文/); assert.match(en, /Region Design/);
  assert.doesNotMatch(visibleText(en), /[\u3400-\u9fff]/);
  assert.match(render(SiteHeader, { current: 'design' }, 'zh-CN'), /区域设计/);
});

void test('the method index server-renders in English and links every chapter of the documentation', () => {
  const Method = loadUI('app/method/page.tsx').default;
  const html = render(Method, {}, 'en');
  const leaked = visibleText(html).match(/.{0,60}[\u3400-\u9fff].{0,100}/g);
  assert.deepEqual(leaked, null);
  // Before the local service answers, chapters open on GitHub with the same anchors.
  for (const entry of METHOD_ENTRIES) assert.ok(html.includes('href="' + docsHref(entry.doc, 'github') + '"'), entry.doc);
  for (const group of METHOD_GROUPS) assert.ok(html.includes('href="' + docsHref(group.page + '/', 'github') + '"'), group.page);
});

void test('copyright footer and concise notice render the author, acknowledgments and third-party attribution', () => {
  const { SiteFooter } = loadUI('components/site-footer.tsx');
  const { CopyrightNotice } = loadUI('components/copyright-notice.tsx');
  const Method = loadUI('app/method/page.tsx').default;
  for (const locale of ['zh-CN', 'en']) {
    const footer = render(SiteFooter, {}, locale);
    const method = render(Method, {}, locale);
    const notice = render(CopyrightNotice, {}, locale);
    assert.match(footer, /© 2026 Yiming Shen(?! &amp;)/);
    assert.doesNotMatch(footer, /Yi Wang/);
    assert.match(footer, /#about-copyright/);
    assert.match(footer, /#third-party-licenses/);
    assert.match(footer, locale === 'en' ? /About &amp; Copyright/ : /关于与版权/);
    assert.match(footer, locale === 'en' ? /Third-Party Licenses/ : /第三方许可/);
    if (locale === 'en') assert.doesNotMatch(visibleText(footer), /[\u3400-\u9fff]/);
    assert.equal((method.match(/id="about-copyright"/g) ?? []).length, 1);
    assert.equal((method.match(/id="third-party-licenses"/g) ?? []).length, 1);
    assert.match(notice, /© 2026 Yiming Shen(?! &amp;)/);
    assert.equal((notice.match(/Yiming Shen, PhD/g) ?? []).length, 1);
    assert.equal((notice.match(/Yi Wang, PhD/g) ?? []).length, 1);
    assert.match(notice, locale === 'en' ? />Author<\/h3><p[^>]*>Yiming Shen, PhD<\/p>/ : />作者<\/h3><p[^>]*>Yiming Shen, PhD<\/p>/);
    assert.match(notice, locale === 'en' ? />Acknowledgments<\/h3><p[^>]*>Yi Wang, PhD<\/p>/ : />致谢<\/h3><p[^>]*>Yi Wang, PhD<\/p>/);
    assert.match(notice, locale === 'en'
      ? /EEG Layout Lab is a tool for designing EEG electrode layouts, simulating EEG signals, and comparing layout performance\./
      : /EEG Layout Lab 用于设计脑电电极布局、模拟脑电信号和比较布局性能。/);
    assert.match(notice, locale === 'en'
      ? /The original project code and documentation are licensed under GNU GPL version 3 only \(GPL-3\.0-only\)\. You may modify and redistribute them under that license\. The software is provided without warranty\./
      : /本项目的原创代码与文档采用 GNU 通用公共许可证第3版（仅此版本，GPL-3\.0-only）。可按该许可修改和再分发，软件不提供担保。/);
    assert.match(notice, locale === 'en'
      ? /href="\/LICENSE\.txt">Full license text<\/a>/
      : /href="\/LICENSE\.txt">许可证全文<\/a>/);
    assert.match(notice, locale === 'en'
      ? /The Ernie head model and 3D display assets come from the SimNIBS example dataset v4\.1\./
      : /本项目的 Ernie 头部模型和三维显示资产源自 SimNIBS 示例数据集 v4\.1。/);
    assert.doesNotMatch(notice, /Original Content|原创内容|does not replace|不代替|underlying ownership|原有权利归属|Licensing and References|许可与引用/);
    if (locale === 'en') assert.doesNotMatch(visibleText(notice), /[\u3400-\u9fff]/);
    assert.match(method, /© SimNIBS developers 2024/);
    assert.match(method, /CC BY-NC 4\.0/);
    assert.match(method, /https:\/\/github\.com\/simnibs\/example-dataset\/releases\/tag\/v4\.1/);
    assert.match(method, /https:\/\/creativecommons\.org\/licenses\/by-nc\/4\.0\//);
    assert.match(method, /\/models\/ernie\/README\.md/);
    assert.match(method, /\/models\/ernie\/manifest\.json/);
    assert.match(notice, /href="#anatomical-display"/);
  }
  assert.equal(COPYRIGHT_NOTICE, '© 2026 Yiming Shen');
  assert.deepEqual(fs.readFileSync(path.join(root, 'public/LICENSE.txt')), fs.readFileSync(path.join(root, '..', 'LICENSE')));
  const layout = fs.readFileSync(path.join(root, 'app/layout.tsx'), 'utf8');
  assert.match(layout, /<LanguageProvider[^>]*>[\s\S]*\{children\}[\s\S]*<SiteFooter\s*\/>[\s\S]*<\/LanguageProvider>/);
  for (const file of ['README.md', 'manifest.json']) assert.ok(fs.existsSync(path.join(root, 'public/models/ernie', file)));
});

void test('copyright links preserve design queries and method return context', () => {
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

void test('old method anchors point to the documentation chapter that replaced them, and the chapters exist', () => {
  const old = ['simulation-model', 'simulation-overview', 'simulation-forward', 'simulation-fem-details', 'simulation-sources', 'simulation-source-regions',
    'simulation-prior-details', 'simulation-waveform-details', 'simulation-comparison', 'simulation-artifacts', 'simulation-parameters', 'retention-guide',
    'retention-comparison', 'retention-field', 'retention-sensitivity', 'retention-localization', 'retention-ar', 'retention-geometry', 'retention-scope',
    'retention-reading', 'model-terms', 'electrode-editor', 'design-decision', 'source-field-interaction', 'local-compute', 'single-head-optimization',
    'first-batch', 'planned-validation', 'anatomical-display', 'method-references'];
  for (const id of old) assert.ok(movedSection('#' + id), id);
  assert.equal(movedSection('#about-copyright'), undefined);
  assert.equal(docsHref('method-details/#signal-model', 'local'), '/docs/method-details/#signal-model');
  assert.equal(docsHref('validation/', 'local'), '/docs/validation/');
  assert.equal(docsHref('method-details/#signal-model', 'github'), 'https://github.com/Yiming-S/EEGLayoutLab/blob/main/docs/method-details.md#signal-model');
  // GitHub-style heading slugs, which the documentation site's slugify produces too.
  const slug = heading => heading.trim().toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, '').replace(/\s/g, '-');
  for (const entry of METHOD_ENTRIES) {
    const [page, anchor] = entry.doc.split('/#');
    const markdown = fs.readFileSync(path.join(root, '..', 'docs', page.replace(/\/$/, '') + '.md'), 'utf8');
    if (anchor) assert.ok(markdown.split('\n').some(line => /^#{1,4} /.test(line) && slug(line.replace(/^#+ /, '')) === anchor), entry.doc);
  }
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
});

void test('unknown diagnostic is summarized with raw detail access, not mislabeled as a result', () => {
  const { RuntimeMessage } = loadUI('components/runtime-message.tsx');
  const html = render(RuntimeMessage, { message: '测试用未知诊断', status: 'running' }, 'en');
  assert.match(html, /Computation in progress/); assert.match(html, /Raw Details/);
  assert.doesNotMatch(visibleText(html), /[\u3400-\u9fff]/);
});

void test('every route entry point renders English system text', () => {
  for (const route of ['', 'findings', 'library', 'layout', 'design', 'electrodes', 'coordinates', 'decision', 'robustness', 'reception', 'channels', 'projects', 'deliveries', 'guide', 'method', 'results', 'pilot-results']) {
    const Page = loadUI('app/' + (route ? route + '/' : '') + 'page.tsx').default;
    const html = render(Page, {}, 'en');
    assert.doesNotMatch(visibleText(html), /[\u3400-\u9fff]/, route || '/');
  }
});

void test('project snapshot layout and edited metrics render bilingual values directly from saved data', () => {
  const { ProjectSnapshotViewer } = loadUI('features/projects/project-snapshot-viewer.tsx');
  const metrics = { field_relative: -.123456789, sensitivity_tail: .4, localization_relative: .5,
    conditional_global: -.123456789, median_mm: 12, reference_median_mm: 10, p90_mm: 30 };
  const result = { schema: 'electrode-editor/1', electrode_count: 63, edited_metrics: metrics, evaluated_xyz_mm: [[1.25, -2.5, 3.75]] };
  const editorEntry = { id: 'editor', kind: 'editor', record_id: 'e'.repeat(64) };
  const layoutEntry = { id: 'layout', kind: 'layout', record_id: 'a'.repeat(64) };
  const record = { id: layoutEntry.record_id, metrics, layout: { xyzMm: result.evaluated_xyz_mm, regionIndices: [0] } };
  const snapshots = [
    { entry: editorEntry, snapshot: { schema: 'research-project-snapshot/1', kind: 'editor', record_id: editorEntry.record_id, payload: { cache: { result } } } },
    { entry: layoutEntry, snapshot: { schema: 'research-project-snapshot/1', kind: 'layout', record_id: layoutEntry.record_id, payload: { record } } },
  ];
  const original = JSON.stringify(snapshots);
  for (const fixture of snapshots) {
    const english = render(ProjectSnapshotViewer, fixture, 'en');
    const chinese = render(ProjectSnapshotViewer, fixture, 'zh-CN');
    assert.doesNotMatch(visibleText(english), /[\u3400-\u9fff]/);
    assert.match(english, /-12\.35%/); assert.match(chinese, /-12\.35%/);
    assert.match(english, /1\.250000/); assert.match(english, /-2\.500000/);
  }
  assert.equal(JSON.stringify(snapshots), original);
});

void test('project delivery controls are bilingual and never render access credentials', () => {
  const { ProjectDeliveryPanel } = loadUI('features/projects/project-delivery-panel.tsx');
  const project = { id: '00000000-0000-4000-8000-000000000001', revision: 3, entries: [{ id: 'entry' }] };
  for (const locale of ['en', 'zh-CN']) {
    // The workspace owns its projects: the panel takes the project alone and names no credential.
    const html = render(ProjectDeliveryPanel, { project }, locale);
    assert.doesNotMatch(visibleText(html), /凭据|credential|access key|访问密钥/i);
    assert.match(html, /type="button"/);
    if (locale === 'en') { assert.doesNotMatch(visibleText(html), /[\u3400-\u9fff]/); assert.match(html, /Download project delivery package/); }
    else assert.match(html, /下载项目交付包/);
  }
});

void test('coordinate import is separate from comparison and the five areas remain bilingual', () => {
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
    assert.equal((main?.match(/<a /g) ?? []).length, 5);
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

void test('research workflow catalog has unique sources, English text and matching placeholders', () => {
  const sources = new Set(), tokens = s => [...s.matchAll(/\{\{(\d+)\}\}/g)].map(m => Number(m[1])).sort((a, b) => a - b);
  for (const [id, entry] of Object.entries(researchWorkflowCatalog)) {
    assert.ok(entry.source && entry.en, id);
    assert.ok(!sources.has(entry.source), id); sources.add(entry.source);
    assert.doesNotMatch(entry.en, /[㐀-鿿]/, id);
    assert.deepEqual(tokens(entry.source), tokens(entry.en), id);
  }
});

void test('worker diagnostics and progress messages from evaluation sources render in English', () => {
  const messages = [];
  for (const file of ['src/compact_eeg/workflows/design_evaluation.py', 'src/compact_eeg/workflows/head_package.py', 'src/compact_eeg/workflows/scalp_node_table.py', 'src/compact_eeg/noise_models.py']) {
    for (const line of fs.readFileSync(path.join(root, '..', file), 'utf8').split('\n')) {
      if (!/raise \w+\(|progress\(|message=/.test(line)) continue;
      // Scan literals in order so f-string fields quoted with the other quote stay inside their literal.
      for (let i = 0; i < line.length; i++) {
        if (line[i] === '#') break;
        if (line[i] !== '"' && line[i] !== "'") continue;
        const end = line.indexOf(line[i], i + 1);
        if (end < 0) break;
        const literal = line.slice(i + 1, end);
        if (/[㐀-鿿]/.test(literal)) messages.push(line[i - 1] === 'f' ? literal.replace(/\{[^{}]*\}/g, '12') : literal);
        i = end;
      }
    }
  }
  assert.ok(messages.length > 20);
  for (const message of messages) assert.doesNotMatch(translateText(message, 'en'), /[㐀-鿿]|\{\{\d/, message);
  assert.equal(translateText('布局映射到头模 ixi012 后最小电极间距为 2.50 mm，低于3 mm；该布局在此头模上不评价。', 'en'),
    'After mapping to head model ixi012, the minimum electrode spacing is 2.50 mm, below 3 mm; the layout is not evaluated on this head model.');
  assert.equal(translateText('布局映射到头模 ixi012 后，有电极距该头模头皮 51.3 mm，超过10 mm；该布局在此头模上不评价。', 'en'),
    "After mapping to head model ixi012, an electrode lies 51.3 mm from that head model's scalp, more than 10 mm; the layout is not evaluated on this head model.");
  // The scenario vertex diagnostic is assembled from a separately chosen subject phrase.
  for (const who of ['标准64参照第3点', '第3个电极', '第3个电极（候选库编号 1234）'])
    assert.doesNotMatch(translateText(who + '所在面片的顶点 812 不在电导率情景所用的预计算头皮节点表中；需按当前顶点规则重新预计算头皮节点表。', 'en'), /[\u3400-\u9fff]|\{\{\d/, who);
});

void test('noise-model record titles translate the base title and the noise suffix separately', () => {
  const noise_model = { kind: 'spatial', rho: 0.5, length_mm: 20 };
  for (const base of [record, ...['whole_surface', 'low_hair'].map(mode => ({ ...record, mode, request: { region_count: 2, radius_mm: 35, mode } }))]) {
    const noisy = { ...base, request: { ...base.request, noise_model } };
    assert.doesNotMatch(localizedRecordTitle(noisy, 'en'), /[㐀-鿿]/);
    assert.equal(localizedRecordTitle(noisy, 'en'), localizedRecordTitle(base, 'en') + ' · Spatially correlated noise ρ=0.5, L=20 mm');
    assert.equal(localizedRecordTitle(noisy, 'zh-CN'), localizedRecordTitle(base, 'zh-CN') + ' · 空间相关噪声 ρ=0.5，L=20 mm');
  }
});

void test('non-default coordinate evaluations offer no saved-record, project or simulation hand-off', () => {
  const key = 'c'.repeat(64), xyz = Array.from({ length: 64 }, (_, i) => [i * 5, 0, 0]);
  const design = { schema: 'eeg-electrode-design/1', coordinate_system: 'ernie_native_mm', unit: 'mm', name: 'Fixture', xyz_mm: xyz, region_indices: xyz.map((_, i) => Number(i >= 32)) };
  const metrics = { field_relative: .9, field_absolute: .8, reference_field_absolute: .9, sensitivity_tail: .9, median_mm: 10, p90_mm: 20, localization_relative: .9, reference_median_mm: 9, reference_p90_mm: 18 };
  const result = { forward_mode: 'scalp_node_table', evaluated_xyz_mm: xyz, nominal: metrics, projection_max_mm: 0, trials: [] };
  const prior = { region_gain: [1.066, 2.606, 0.0985, 1.309, 0.6004, 1.161, 0.0985], rho: 0, length_mm: null };
  const state = (locale, noiseModelId, scenarioId, dataPrior = null) => ({ tx: value => localize(value, locale), locale, dataPrior, dataPriorSource: '', setDataPrior() {}, ids: ['', ''], setIds() {}, error: '', thresholds: jointDecisionThresholds(90), setThresholds() {},
    setImported() {}, importError: '', draftNotice: '', setImportError() {}, job: { id: 'job', key, status: 'completed', message: '设计评价已完成并保存', progress: 1, result }, computeError: '',
    testTarget: 'import', setTestTarget() {}, radius: 6, setRadius() {}, seed: 42, setSeed() {}, noiseModelId, setNoiseModelId() {}, scenarioId, setScenarioId() {}, action: 'evaluate',
    showEvaluated: true, setShowEvaluated() {}, here: '/coordinates?ar=90&resume=1', shown: [], loaded: true, choices: [], notes: [], design, requestIdentity: 'same', jobIdentity: 'same',
    result, resultQualification: { state: 'pass', missing: [], failed: [] }, computing: false, runEvaluation() {}, cancel() {}, preview: undefined });
  const workspace = path.join(root, 'features/decision/decision-workspace.tsx'), controller = path.join(root, 'features/decision/use-decision-controller.ts');
  const previous = [workspace, controller].map(file => [file, modules.get(file)]);
  let current;
  modules.delete(workspace); modules.set(controller, { exports: { useDecisionController: () => current } });
  try {
    const Page = loadUI('features/decision/decision-workspace.tsx').default;
    for (const locale of ['zh-CN', 'en']) {
      current = state(locale, 'iid', '');
      const saved = render(Page, { mode: 'coordinates' }, locale);
      assert.ok(saved.includes('/layout?id=' + key)); assert.ok(saved.includes('/reception?record=' + key)); assert.ok(saved.includes('/projects?record=' + key));
      for (const [noise, scenario, dataPrior] of [['spatial_20', ''], ['iid', 'skull_x2'], ['iid', '', prior]]) {
        current = state(locale, noise, scenario, dataPrior);
        const html = render(Page, { mode: 'coordinates' }, locale);
        assert.ok(html.includes('/layout?id=' + key) && html.includes('/projects?record=' + key), noise + scenario);
        assert.ok(!html.includes('/reception?record=' + key), noise + scenario);
        assert.match(html, locale === 'en' ? /Signal simulation accepts only layouts under the default protocol/ : /信号仿真只接受默认协议下的布局/);
        if (locale === 'en') assert.doesNotMatch(visibleText(html), /[㐀-鿿]/);
      }
    }
  } finally {
    for (const [file, unit] of previous) if (unit) modules.set(file, unit); else modules.delete(file);
  }
  const record = { id: key, layout: { xyzMm: xyz } };
  // Saved evaluations come back with their conditions; cross-head ones stay out of this page.
  for (const [extra, noise, scenario] of [[{ noise_model: { kind: 'spatial', rho: 0.5, length_mm: 20 } }, 'spatial_20', ''], [{ conductivity_scenario: 'skull_x2' }, 'iid', 'skull_x2']]) {
    const request = { action: 'evaluate', design, radius_mm: 6, seed: 42, ...extra };
    const bundle = { schema: 'eeg-reproducibility-bundle/1', record_id: key, reproduction: { request }, original_record: { result: { ...result, request } } };
    const restored = restoreDesignEvaluation(bundle, record);
    assert.equal(restored.noise_model_id, noise); assert.equal(restored.conductivity_scenario, scenario);
  }
  const headRequest = { action: 'evaluate', design, radius_mm: 6, seed: 42, head_id: 'ixi002' };
  assert.throws(() => restoreDesignEvaluation({ schema: 'eeg-reproducibility-bundle/1', record_id: key, reproduction: { request: headRequest }, original_record: { result: { ...result, request: headRequest } } }, record), /跨头模评价/);
});

void test('correlated-noise layouts explain the missing simulation hand-off and head results name their origin', () => {
  const { SavedLayoutContent } = loadUI('components/saved-layout-details.tsx');
  const { ProjectWorkflowEditor } = loadUI('features/projects/project-workflow-editor.tsx');
  const { evaluationPresentation } = loadUI('features/decision/evaluation-presentation.ts');
  const layout = { xyzMm: Array.from({ length: 64 }, () => [0, 0, 0]), referenceXyzMm: Array.from({ length: 64 }, () => [0, 0, 0]),
    regionIndices: Array.from({ length: 64 }, (_, i) => i < 32 ? 0 : 1), regionPatchVertexIndices: [[0], [1]] };
  const noisy = { ...record, layout, request: { ...record.request, noise_model: { kind: 'spatial', rho: 0.5, length_mm: 20 } } };
  const entry = (simulation) => ({ id: 'layout', kind: 'layout', title: 'Layout', record_id: 'a'.repeat(64), summary: { protocol: 'cache', electrode_count: 64, ...simulation } });
  const project = (summary) => ({ id: 'p', entries: [entry(summary)], workflow: { reference_entry_id: null, candidate_entry_id: 'layout', comparison_href: null } });
  for (const locale of ['zh-CN', 'en']) {
    const sentence = locale === 'en' ? /Signal simulation uses independent noise/ : /空间相关噪声下搜索的布局不进入信号仿真/;
    const html = render(SavedLayoutContent, { record: noisy, ar: 32, returnHref: '/library?ar=32' }, locale);
    assert.doesNotMatch(html, /href="\/reception\?/); assert.doesNotMatch(html, /href="\/electrodes\?/); assert.match(html, sentence);
    assert.doesNotMatch(render(SavedLayoutContent, { record: { ...noisy, request: record.request }, ar: 32, returnHref: '/library?ar=32' }, locale), sentence);
    const blocked = render(ProjectWorkflowEditor, { project: project({ simulation: false }), owner: false, busy: false, save() {} }, locale);
    assert.doesNotMatch(blocked, /href="\/reception\?/);
    assert.match(blocked, locale === 'en' ? /not available for signal simulation/ : /该布局不进入信号仿真/);
    const short = render(ProjectWorkflowEditor, { project: { ...project({ simulation: false }), entries: [{ ...entry({ simulation: false }), summary: { protocol: 'cache', electrode_count: 32, simulation: false } }] }, owner: false, busy: false, save() {} }, locale);
    assert.match(short, locale === 'en' ? /64-electrode/ : /选择已评价的64电极候选布局/); assert.doesNotMatch(short, /该布局不进入信号仿真/);
    for (const summary of [{}, { simulation: true }]) assert.match(render(ProjectWorkflowEditor, { project: project(summary), owner: false, busy: false, save() {} }, locale), /href="\/reception\?record=a{64}"/);
    if (locale === 'en') for (const content of [html, blocked]) assert.doesNotMatch(visibleText(content), /[㐀-鿿]/);
  }
  const origin = evaluationPresentation(null, { forward_mode: 'head_scalp_node_table' }).origin;
  assert.equal(origin, '其他头模的预计算头皮节点表'); assert.doesNotMatch(translateText(origin, 'en'), /[㐀-鿿]/);
});

void test('the library names the workspace scope of its signal records in both languages', () => {
  const library = fs.readFileSync(path.join(root, 'features/library/library-workspace.tsx'), 'utf8');
  assert.doesNotMatch(library, /RecordVisibilityControl|visibility|本浏览器|当前浏览器|共享库/);
  const notes = library.match(/'[^']*此工作区[^']*'|'其他工作区[^']*'/g) ?? [];
  assert.ok(notes.length >= 2, 'workspace-scoped notes');
  for (const note of notes) assert.doesNotMatch(translateText(note.slice(1, -1), 'en'), /[㐀-鿿]/, note);
  assert.equal(fs.existsSync(path.join(root, 'components/record-visibility-control.tsx')), false);
});
