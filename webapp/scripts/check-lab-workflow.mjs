import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { LocalComputeQueue, MASK_CODES, normalizeRequest } from './local-compute-server.mjs';
import { parseAR, areaRows, areaConclusion, minimumTestedArea, assessment, comparisonLink, radiusDesignLink, recordLink, methodLink, AREA_CAPS, REGION_COUNTS, MANUAL_COMPUTE_DEFAULT } from '../lib/lab-workflow.ts';
import { designLink } from '../lib/local-library.ts';
import { displayJob, matchingResult } from '../lib/local-compute.ts';
import { RETENTION_EXAMPLE, RETENTION_SECTIONS, isRetentionGuideHash, guidePercent } from '../lib/retention-guide.ts';
import { PAGES, MASK_NAMES, recordTitle, protocolName, metricPercent, metricDistance, safeReturnHref, parseLibraryView, libraryViewLink } from '../lib/ui-language.ts';
import { WORKSPACES, WORKSPACE_TABS } from '../lib/workspace-navigation.ts';
import { METRICS } from '../lib/lab-workflow.ts';
import { CRITERIA } from '../lib/single-head-results.ts';
import { placementChoices, choiceFromSlots, placementDesignLink } from '../lib/placement-options.ts';

void test('AR query parsing is bounded, includes equality, and does not turn missing metrics into zero', () => {
  assert.equal(parseAR('50'), 50); assert.equal(parseAR('90'), 90);
  for (const value of [null, '', '0', '101', '50.5', 'NaN', 'text']) assert.equal(parseAR(value), 90);
  const m = { field_relative: .9, sensitivity_tail: .5, localization_relative: .6 };
  assert.equal(assessment(m, 50).state, 'pass');
  assert.deepEqual(assessment(m, 90).limiting, ['幅度保留率（最差10%）', '相对定位评分']);
  assert.equal(assessment({ ...m, sensitivity_tail: null }, 50).state, 'undefined');
});

void test('all 30 actual strict-area records have exactly one entry per domain-area-R and preserved metrics', async () => {
  const queue = new LocalComputeQueue({ repositoryRoot: '..', spawnProcess: () => assert.fail('comparison cannot compute') });
  const data = await queue.library.list();
  const ids = new Set();
  for (const domain of ['whole_scalp_free', 'low_hair_free']) for (const area of AREA_CAPS) {
    const rows = areaRows(data.records, domain, area);
    assert.deepEqual(rows.map((r) => r.region_count), REGION_COUNTS);
    for (const row of rows) {
      ids.add(row.id); assert.equal(row.dataset_id, 'strict_area'); assert.equal(row.area_cap_cm2, area);
      assert.equal(row.geometry.union_connected_component_count, row.region_count);
      assert.equal(row.metrics.conditional_global, Math.min(row.metrics.field_relative, row.metrics.sensitivity_tail, row.metrics.localization_relative));
      const href = comparisonLink(row, 50), url = new URL(href, 'http://localhost');
      assert.equal(Number(url.searchParams.get('ar')), 50);
      assert.equal(Number(url.searchParams.get('r')), row.region_count);
      assert.equal(Number(url.searchParams.get('area')), row.area_cap_cm2);
      assert.equal(radiusDesignLink(row, 50), `/design?from=${row.id}&ar=50`);
      assert.equal(row.request, null); // Never silently translate area into a radius request.
    }
  }
  assert.equal(ids.size, 30); assert.equal(queue.jobs.size, 0); queue.dispose();
});

void test('other protocols, missing rows and unmeasured sizes cannot fill strict-area gaps', () => {
  const historical = { dataset_id: 'offline_radius', region_count: 2, area_cap_cm2: 120, mode: 'whole_scalp_free', metrics: { field_relative: 1 } };
  assert.ok(areaRows([historical], 'whole_scalp_free', 120).every((r) => r === undefined));
  assert.ok(areaRows([], 'whole_scalp_free', 90).every((r) => r === undefined));
});

void test('minimum area is only the first tested passing cap, never an interpolated area', () => {
  const rows = [60, 120, 180].map((a) => ({ dataset_id: 'strict_area', mode: 'whole_scalp_free', region_count: 2, area_cap_cm2: a,
    metrics: { field_relative: a / 200, sensitivity_tail: a / 200, localization_relative: a / 200 } }));
  assert.equal(minimumTestedArea(rows, 'whole_scalp_free', 2, 50).area_cap_cm2, 120);
  assert.equal(minimumTestedArea(rows, 'whole_scalp_free', 2, 95), undefined);
});

void test('area conclusions distinguish missing, incomplete, undefined and tested failure', () => {
  const row = { dataset_id: 'strict_area', mode: 'whole_scalp_free', region_count: 2, area_cap_cm2: 60,
    metrics: { field_relative: .8, sensitivity_tail: .6, localization_relative: .6 } };
  const full = AREA_CAPS.map((area) => ({ ...row, area_cap_cm2: area }));
  assert.equal(areaConclusion([], row.mode, 2, 90), '暂无同协议可判断数据');
  assert.equal(areaConclusion([row], row.mode, 2, 90), '数据不完整，不能判定整个已测范围');
  assert.equal(areaConclusion([row], row.mode, 2, 50), '数据不完整；已知60 cm²上限达标');
  assert.equal(areaConclusion(full, row.mode, 2, 90), '已测范围内未达标');
  assert.equal(areaConclusion(full, row.mode, 2, 50), '首个达标面积上限：60 cm²');
  full[0] = { ...row, metrics: { ...row.metrics, localization_relative: null } };
  assert.equal(areaConclusion(full, row.mode, 2, 90), '数据不完整，不能判定整个已测范围');
});

void test('method links preserve the exact draft and AR without interpreting or replacing parameters', () => {
  const draft = '/design?from=' + 'a'.repeat(64) + '&draft=1&r=3&radius=40&mode=choose&ar=50';
  const url = new URL(methodLink(draft, 50, '#local-compute'), 'http://localhost');
  assert.equal(url.pathname, '/method'); assert.equal(url.hash, '#local-compute');
  assert.equal(url.searchParams.get('ar'), '50'); assert.equal(url.searchParams.get('returnTo'), draft);
});

void test('record links preserve exact IDs and AR; historical radius constraints can be restored without translating area protocols', () => {
  const row = { id: 'a'.repeat(64), dataset_id: 'cache', compatible: true, request: { region_count: 2, mode: 'whole_surface', radius_mm: 35 } };
  assert.equal(designLink(row, 50), `/design?saved=${row.id}&ar=50`);
  assert.equal(radiusDesignLink(row, 50), designLink(row, 50));
  assert.equal(recordLink(row, 50), `/library?record=${row.id}&ar=50`);
  assert.equal(radiusDesignLink({ ...row, compatible: false }, 50), `/design?saved=${row.id}&ar=50`);
  assert.equal(designLink({ ...row, compatible: false }, 50), `/design?saved=${row.id}&ar=50`);
  assert.equal(designLink({ ...row, compatible: false, request: null }, 50), null);
  assert.equal(radiusDesignLink({ ...row, dataset_id: 'offline_radius' }, 50), null);
});

void test('manual is default; exact cached B can display while old A runs, never vice versa', () => {
  assert.equal(MANUAL_COMPUTE_DEFAULT, false);
  const a = { region_count: 2, radius_mm: 35, mode: 'whole_surface' }, b = { ...a, region_count: 3 };
  const active = { request: a, status: 'running', result: null };
  const stored = { request: b, status: 'completed', result: { request: b, status: 'completed' } };
  assert.equal(matchingResult(displayJob(active, stored, b), b), stored.result);
  assert.equal(matchingResult(displayJob(active, stored, a), a), null);
});

void test('editor rejects incompatible region presets and area entry stays read-only by construction', async () => {
  const source = await readFile('app/design/page.tsx', 'utf8');
  assert.ok(source.includes("setChoiceId('')"));
  assert.ok(source.includes("setEditing(false)"));
  assert.ok(source.includes('editing && request && <LocalComputePanel'));
  assert.ok(source.includes("q.has('saved') && !record.compatible"));
  assert.ok(source.includes('const layout = editing ? result?.layout : source?.layout'));
  assert.ok(source.includes('const metrics = editing ? result?.metrics : source?.metrics'));
  assert.ok(!source.includes('?? domainChoices[1]'));
  const panel = await readFile('components/local-compute-panel.tsx', 'utf8');
  assert.ok(panel.includes('useState(MANUAL_COMPUTE_DEFAULT)'));
  assert.ok(panel.includes("fetch('/api/local-compute/lookup'"));
  const home = await readFile('app/page.tsx', 'utf8');
  assert.ok(!home.includes('/api/local-compute/jobs'));
});

void test('retention teaching example matches its frozen metric excerpt, including absolute and relative values', async () => {
  const e = RETENTION_EXAMPLE;
  const fixture = JSON.parse(await readFile(new URL('../public/data/retention-example.json', import.meta.url), 'utf8'));
  assert.equal(fixture.source_record_id, e.recordId);
  const m = fixture.metrics;
  const mapping = {
    fieldAbsolute: 'field_absolute', referenceFieldAbsolute: 'reference_field_absolute',
    fieldRelative: 'field_relative', sensitivity: 'sensitivity_tail', localizationRelative: 'localization_relative',
    utility: 'localization_utility', referenceUtility: 'reference_localization_utility',
    medianMm: 'median_mm', referenceMedianMm: 'reference_median_mm',
    p90Mm: 'p90_mm', referenceP90Mm: 'reference_p90_mm', global: 'conditional_global',
  };
  for (const [key, stored] of Object.entries(mapping)) assert.equal(e[key], m[stored], key);
  assert.ok(Math.abs(e.fieldRelative - e.fieldAbsolute / e.referenceFieldAbsolute) < 1e-12);
  assert.ok(Math.abs(e.localizationRelative - e.utility / e.referenceUtility) < 1e-12);
  assert.equal(e.global, Math.min(e.fieldRelative, e.sensitivity, e.localizationRelative));
  assert.deepEqual([e.fieldRelative, e.sensitivity, e.localizationRelative, e.global].map(guidePercent), ['57.15%', '12.50%', '18.54%', '12.50%']);
  assert.equal(assessment(m, 90).state, 'fail');
  assert.equal(assessment(m, 50).state, 'fail');
  assert.equal(assessment(m, 10).state, 'pass');
});

void test('complete retention guide is visible outside historical details and its directory anchors resolve', async () => {
  const page = await readFile('app/method/page.tsx', 'utf8');
  const guide = await readFile('components/retention-explainer.tsx', 'utf8');
  const context = await readFile('components/method-context.tsx', 'utf8');
  assert.ok(page.indexOf('<RetentionExplainer />') > 0);
  assert.ok(page.indexOf('<RetentionExplainer />') < page.indexOf('<TechnicalDetails>'));
  assert.ok(guide.includes('id="retention-guide"'));
  assert.equal(RETENTION_SECTIONS.length, 8);
  assert.equal(new Set(RETENTION_SECTIONS.map(([id]) => id)).size, 8);
  for (const [id] of RETENTION_SECTIONS) {
    assert.equal(guide.split(`id="${id}"`).length - 1, 1);
    assert.equal(isRetentionGuideHash('#' + id), true);
  }
  assert.equal(isRetentionGuideHash('#retention-guide'), true);
  for (const hash of ['', '#local-compute', '#source-reception', '#retention-guide-unknown']) assert.equal(isRetentionGuideHash(hash), false);
  assert.ok(context.includes('!isRetentionGuideHash(window.location.hash)'));
});

void test('retention guide separates model scores, fixed examples, protocols, and live computation', async () => {
  const guide = await readFile('components/retention-explainer.tsx', 'utf8');
  for (const text of [
    '固定示例 · 独立于当前配置', '自身的噪声、重建误差和定位误差仍按绝对数值报告', '三项相对指标分别衡量',
    '256个', '16次噪声重复', '4,096点', '通过离散源定位仿真计算误差', 'd / (50 mm)', '10%皮层面积权重',
    '两套布局的最差10%不一定包含同一组脑源', '定位在冻结布局后评价', 'ECG/EOG干扰另在信号仿真页设置',
    'AR只改变通过判断', 'MI、P300任务分类和人体表现尚待验证',
  ]) assert.ok(guide.includes(text), text);
  for (const text of ['fetch(', '/api/local-compute/jobs', '/Users/', String.raw`\[`, String.raw`\(`]) assert.ok(!guide.includes(text), text);
});

void test('performance cards link to the guide with the current draft, record, and AR preserved', async () => {
  const card = await readFile('components/performance-summary.tsx', 'utf8');
  assert.ok(card.includes("methodLink(returnHref ?? '/?ar=' + ar, ar, '#retention-guide')"));
  for (const file of ['app/page.tsx', 'app/design/page.tsx', 'app/library/page.tsx']) {
    const source = await readFile(file, 'utf8');
    assert.match(source, file === 'app/design/page.tsx' ? /<PerformanceSummary[^>]*returnHref=\{here\}/ : /<SavedLayoutDetails[^>]*returnHref=\{here\}/, file);
  }
  assert.match(await readFile('components/saved-layout-details.tsx', 'utf8'), /<PerformanceSummary[^>]*returnHref=\{returnHref\}/);
  for (const back of [
    '/design?draft=1&r=2&radius=25&mode=preset&masks=PL%2CPR&ar=50',
    '/library?record=' + RETENTION_EXAMPLE.recordId + '&ar=50',
  ]) {
    const url = new URL(methodLink(back, 50, '#retention-guide'), 'http://localhost');
    assert.equal(url.hash, '#retention-guide');
    assert.equal(url.searchParams.get('returnTo'), back);
    assert.equal(url.searchParams.get('ar'), '50');
  }
});

void test('navigation groups existing destinations into four workspaces with visible tool tabs', async () => {
  assert.deepEqual(PAGES.map((p) => [p.path, p.label]), [
    ['/', '结果库'], ['/design', '布局设计'], ['/electrodes', '电极编辑'], ['/decision', '方案对比'], ['/reception', '信号仿真'], ['/guide', '使用指南'], ['/method', '建模与原理'],
  ]);
  const header = await readFile('components/site-header.tsx', 'utf8');
  assert.deepEqual(WORKSPACES.map(p => p.label), ['结果库', '布局设计', '信号仿真', '文档']);
  assert.deepEqual(WORKSPACE_TABS.design.map(p => p[0]), ['design', 'electrodes', 'coordinates']);
  assert.deepEqual(WORKSPACE_TABS.results.map(p => p[0]), ['compare', 'library', 'decision']);
  assert.ok(header.includes('WORKSPACES.map'));
  assert.ok(header.includes('WORKSPACE_TABS[group].map'));
  for (const [file, current] of [['app/page.tsx', 'compare'], ['app/design/page.tsx', 'design'], ['features/reception/reception-workspace.tsx', 'reception']]) {
    const source = await readFile(file, 'utf8');
    assert.ok(source.includes(`current="${current}"`));
    assert.ok(!source.includes('<LabNavigation'));
  }
});

void test('library URLs preserve filters, Unicode search, page, record and AR with legacy history compatibility', () => {
  const state = { filter: 'cache', region: 2, search: '左耳后 & 前额', page: 2 };
  const url = new URL(libraryViewLink(50, RETENTION_EXAMPLE.recordId, state), 'http://localhost');
  assert.deepEqual(parseLibraryView(url.searchParams), state);
  assert.equal(url.searchParams.get('record'), RETENTION_EXAMPLE.recordId);
  assert.equal(url.searchParams.get('ar'), '50');
  assert.equal(parseLibraryView(new URLSearchParams('history=1')).filter, 'offline_radius');
  assert.deepEqual(parseLibraryView(new URLSearchParams('filter=unknown&regions=5&page=-9')), { filter: 'all', region: 0, search: '', page: 0 });
});

void test('safe method returns preserve historical page state and reject external or unsupported destinations', () => {
  for (const back of ['/results?ar=50&snr=10&metric=localization_relative', '/pilot-results?family=bilateral_ear&radius=30', '/library?filter=cache&q=%E8%80%B3&page=3', '/design?draft=1&r=2#layout']) {
    assert.equal(safeReturnHref(back, '/'), back);
    const url = new URL(methodLink(back, 50), 'http://localhost');
    assert.equal(safeReturnHref(url.searchParams.get('returnTo'), '/'), back);
  }
  for (const bad of [null, '//example.org', 'https://example.org', '/\\example.org', '/api/local-compute/jobs', '/unrecognized', '/design/../../outside']) assert.equal(safeReturnHref(bad, '/'), '/');
});

void test('record titles translate mask codes without mutating IDs, requests or raw names', () => {
  const record = { id: 'a'.repeat(64), label: 'PL + PR', dataset_id: 'cache', region_count: 2, mode: 'preset', request: { mask_codes: ['PL', 'PR'], radius_mm: 25 }, radius_cap_mm: 25 };
  const before = JSON.stringify(record);
  assert.equal(recordTitle(record), '2个区域 · 左耳后邻近区 + 右耳后邻近区 · 每区半径 ≤ 25 mm');
  assert.equal(JSON.stringify(record), before);
  assert.equal(recordTitle({ ...record, dataset_id: 'offline_radius' }), record.label);
  assert.equal(protocolName('strict_area'), '总面积上限约束实验');
  assert.equal(protocolName('cache'), '每区半径约束计算');
});

void test('metric names stay consistent across current and historical scores; undefined is never fail', async () => {
  for (const metric of METRICS) assert.equal(CRITERIA.find((c) => c.id === metric.key)?.label, metric.label);
  const base = { field_relative: 1, sensitivity_tail: 1, localization_relative: 1 };
  for (const value of [null, NaN, Infinity, undefined]) for (const m of METRICS) assert.equal(assessment({ ...base, [m.key]: value }, 90).state, 'undefined');
  for (const v of ['1', '9']) assert.equal(parseAR(v), 90);
  assert.equal(parseAR('10'), 10); assert.equal(parseAR('100'), 100);
  const card = await readFile('components/performance-summary.tsx', 'utf8');
  assert.ok(card.includes('Number.isFinite(value)'));
  assert.ok(card.includes("!valid ? '无法判断'"));
});

void test('historical pages disclose their scope and preserve settings in method links', async () => {
  const history = await readFile('app/results/page.tsx', 'utf8');
  const pilot = await readFile('app/pilot-results/page.tsx', 'utf8');
  assert.ok(history.includes('历史半径实验'));
  assert.ok(history.includes('min="10"')); assert.ok(!history.includes('min="1"'));
  assert.ok(history.includes('已找到最高 G')); assert.ok(!history.includes('已找到最高AR'));
  assert.ok(history.includes("q.get('objective') === 'min_field_sensitivity_20db'"));
  assert.ok(pilot.includes('历史原型：双区域初始布局'));
  assert.ok(!pilot.includes('1、3、4、6区域的结果尚未计算'));
  for (const source of [history, pilot]) {
    assert.ok(source.includes('methodLink(here, ar,'));
    assert.ok(source.includes('returnHref={here}'));
    assert.ok(source.includes("window.history.replaceState(null, '', here)"));
  }
});

void test('method page separates current calculation, historical experiments and unimplemented plans', async () => {
  const source = await readFile('app/method/page.tsx', 'utf8');
  assert.ok(source.indexOf('id="local-compute"') < source.indexOf('id="single-head-optimization"'));
  assert.ok(source.includes('后续验证计划 · 尚未全部实施'));
  assert.ok(source.includes('样本量与具体执行方案尚待确定'));
  assert.ok(source.includes('G取三者最低值，用于与接受阈值AR比较'));
  assert.ok(source.includes('得到下尾评分U；相对定位评分Rloc为候选布局U除以标准64导U'));
  const historical = await readFile('app/results/page.tsx', 'utf8');
  assert.ok(historical.includes('下尾定位评分 U（0—1）'));
  assert.ok(!historical.includes('尾部相对定位评分 U'));
});

void test('all supported preset shortcuts are exposed without inventing subdivided masks or scores', async () => {
  const protocol = JSON.parse(await readFile('public/data/experiment_protocol_v2.json', 'utf8'));
  const counts = REGION_COUNTS.map((r) => placementChoices(protocol, r, MASK_NAMES).filter((c) => c.mode === 'preset').length);
  assert.deepEqual(counts, [5, 6, 3, 3, 2]);
  for (const r of REGION_COUNTS) for (const c of placementChoices(protocol, r, MASK_NAMES).filter((x) => x.mode === 'preset')) {
    assert.equal(c.maskCodes.length, r);
    assert.ok(c.maskCodes.every((code) => MASK_CODES.includes(code)));
    const url = new URL(placementDesignLink(c, r, 46), 'http://localhost');
    assert.equal(url.pathname, '/design'); assert.equal(url.searchParams.get('ar'), '46');
    assert.equal(url.searchParams.get('draft'), '1'); assert.equal(url.searchParams.get('radius'), '35');
    assert.equal(url.searchParams.get('area'), null); assert.equal(url.searchParams.get('saved'), null);
    assert.deepEqual(url.searchParams.get('masks').split(','), c.maskCodes);
    assert.ok(!('metrics' in c));
  }
});

void test('free placement offers all nine backend-supported sites, including non-preset and repeated choices', () => {
  assert.deepEqual(Object.keys(MASK_NAMES).sort(), [...MASK_CODES].sort());
  for (const mask of MASK_CODES) {
    const c = choiceFromSlots([mask], 1, MASK_NAMES);
    assert.ok(c);
    assert.deepEqual(normalizeRequest({ region_count: 1, radius_mm: 35, mode: c.mode, mask_codes: c.maskCodes }).mask_codes, [mask]);
  }
  for (const masks of [['FR', 'OL'], ['PL', 'PL'], ['FR', 'PL', 'FM'], ['OR', 'PL', 'FR', 'AL', 'FM', 'PR']]) {
    const c = choiceFromSlots(masks, masks.length, MASK_NAMES);
    assert.deepEqual(c.maskCodes, masks);
    assert.deepEqual(normalizeRequest({ region_count: masks.length, radius_mm: 35, mode: c.mode, mask_codes: c.maskCodes }).mask_codes, masks);
    assert.deepEqual(new URL(placementDesignLink(c, masks.length, 50), 'http://localhost').searchParams.get('masks').split(','), masks);
  }
  for (const [masks, r] of [[['PL', ''], 2], [['PL'], 2], [['PL_superior'], 1], [[], 0], [Array(5).fill('PL'), 5]]) assert.equal(choiceFromSlots(masks, r, MASK_NAMES), null);
});

void test('placement choices are flat controls; incomplete regional choices cannot display another result', async () => {
  const home = await readFile('app/page.tsx', 'utf8');
  const design = await readFile('app/design/page.tsx', 'utf8');
  const controls = await readFile('components/placement-options.tsx', 'utf8');
  assert.ok(home.includes('<HomePlacementOptions'));
  assert.ok(design.includes('<DesignPlacementOptions'));
  assert.ok(!/<(?:select|details)\b/.test(controls));
  assert.ok(controls.includes('Object.entries(MASK_NAMES)'));
  assert.ok(controls.includes('REGION_COUNTS.map'));
  assert.ok(controls.includes('不沿用上方总面积约束、不自动计算'));
  assert.ok(controls.includes('眼电干扰在信号仿真页单独评价'));
  assert.ok(design.includes("setChoiceId(selected?.id ?? '')"));
  assert.ok(design.includes('requestKey(computed.request) === requestKey(request)'));
  assert.ok(design.includes("customSlots.join(',')"));
  assert.ok(!design.includes('允许布置范围或位置组合<select'));
  assert.ok(!home.includes('允许布置范围<select'));
});

void test('display states distinguish pending values from invalid metrics and preserve numeric ranges', () => {
  assert.equal(metricPercent(undefined), '尚未计算');
  assert.equal(metricPercent(undefined, '正在读取'), '正在读取');
  for (const value of [null, NaN, Infinity, -Infinity]) {
    assert.equal(metricPercent(value), '指标无法计算');
    assert.equal(metricDistance(value), '指标无法计算');
  }
  assert.equal(metricPercent(0), '0.00%');
  assert.equal(metricPercent(-.5), '-50.00%');
  assert.equal(metricPercent(1.2), '120.00%');
  assert.equal(metricDistance(undefined), '尚未计算');
  assert.equal(metricDistance(10.925), '10.93 mm');
});

void test('public copy uses factual scope and correct AR, metric and reference terminology', async () => {
  const files = ['app/page.tsx', 'app/design/page.tsx', 'app/library/page.tsx', 'app/method/page.tsx',
    'app/results/page.tsx', 'app/pilot-results/page.tsx', 'features/reception/reception-workspace.tsx', 'features/reception/experiment-result.tsx',
    'components/retention-explainer.tsx', 'components/performance-summary.tsx', 'components/local-compute-panel.tsx'];
  for (const file of files) {
    const text = await readFile(file, 'utf8');
    assert.doesNotMatch(text, /不得声称|不得把|不得用|禁止外推|不显示虚构|不伪造|尚未声称|背书|解释能量|严格固定面积|20 dB独立噪声|AR未定义|三指标通过率/, file);
  }
  const method = await readFile('app/method/page.tsx', 'utf8');
  assert.ok(method.includes('在AR＝10%时通过模型内判据'));
  assert.ok(method.includes('根据源先验、前向模型和噪声协方差构造LMMSE估计器'));
  const reception = (await Promise.all(['features/reception/experiment-result.tsx', 'features/reception/reception-workspace.tsx'].map(p => readFile(p, 'utf8')))).join('\n');
  assert.ok(reception.includes('相对指标无法计算，无法判断是否达到AR'));
  assert.ok(reception.includes('方法背景参考：'));
  assert.ok(reception.includes('假设性空间场'));
  assert.equal(MASK_NAMES.OL, '左眶周上外侧');
  assert.equal(MASK_NAMES.AL, '左耳周扩展区');
});
