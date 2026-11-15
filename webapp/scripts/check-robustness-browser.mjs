/** Real Chrome robustness acceptance. Every admitted case must first be an exact, completed cache hit. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { access, mkdir, readFile, writeFile } from 'node:fs/promises';
import { isAbsolute, join, relative, resolve } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { chromium } from 'playwright';
import { translateText } from '../lib/i18n/core.ts';
import { normalizeDesignRequest } from '../server/design-evaluation-server.mjs';

const root = resolve(import.meta.dirname, '../..'), artifactRoot = join(root, 'artifacts/research-workflow/2026-11-14');
assert.ok(process.env.EEG_TEST_URL, 'Set the isolated verification URL.');
const origin = new URL(process.env.EEG_TEST_URL);
assert.ok(origin.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(origin.hostname) && origin.port && origin.port !== '3000' && origin.pathname === '/' && !origin.search && !origin.hash);
const output = process.env.EEG_QA_OUTPUT || join(artifactRoot, 'stage5-browser'), suffix = relative(artifactRoot, output);
assert.ok(isAbsolute(output) && suffix && !suffix.startsWith('..') && !isAbsolute(suffix));
const executablePath = process.env.EEG_BROWSER_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
await access(executablePath); await mkdir(output, { recursive: true, mode: 0o700 });
const noiseInput = JSON.parse(await readFile(join(artifactRoot, 'stage5-science/noise_seeds-input.json'), 'utf8'));
const gridInput = JSON.parse(await readFile(join(artifactRoot, 'stage5-science/grid_displacements-input.json'), 'utf8'));
assert.equal(noiseInput.cases.length, 2); assert.equal(gridInput.cases.length, 6); assert.deepEqual(noiseInput.design, gridInput.design);
const names = Array.from({ length: 64 }, (_, index) => index === 0 ? 'Study-Fp1, left' : index === 1 ? 'Study-Cz "midline"' : index === 2 ? 'Study-电极03' : `Study-Channel-${index + 1}`);
const source = { schema: 'electrode-coordinate-source/1', format: 'bids-electrodes/1', electrodes_file: 'study-electrodes.tsv', coordsystem_file: 'study-coordsystem.json', coordinate_system: 'ernie_native_mm', unit: 'mm', coordinate_system_description: 'Ernie native frame in millimetres.', region_index_base: 0, region_description: 'Explicit zero-based EEGLayoutLab regions.' };
const imported = { ...noiseInput.design, electrode_names: names, source_metadata: source }, cached = new Map(), observations = [], requests = [], artifacts = [], secrets = [];
const diagnostics = { pageErrors: [], consoleErrors: [], httpFailures: [], requestFailures: [], blockedWrites: [], routeErrors: [] };
const hash = value => createHash('sha256').update(typeof value === 'string' ? value : JSON.stringify(value)).digest('hex');
const scrub = value => typeof value === 'string' ? secrets.reduce((text, secret) => text.replaceAll(secret, '[credential]'), value) : Array.isArray(value) ? value.map(scrub) : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, scrub(item)])) : value;
const t = (source, locale = 'en') => translateText(source, locale);
const button = (page, source, locale = 'en') => page.getByRole('button', { name: t(source, locale), exact: true });
const label = (page, source, locale = 'en') => page.getByLabel(t(source, locale), { exact: true });
let browser, context, page, armed, failure, noiseStudy, gridStudy, cancelledStudy, phase = 'initialization';
const contexts = [];
async function check(name, work) {
  phase = name; const started = Date.now();
  try { const details = await work(); observations.push({ name, pass: true, seconds: (Date.now() - started) / 1000, ...details }); console.log(JSON.stringify(scrub(observations.at(-1)))); }
  catch (error) { observations.push({ name, pass: false, error: scrub(error.message) }); throw error; }
}
async function api(path, options = {}, expected = 200) {
  requests.push({ phase, transport: 'api', method: options.method || 'GET', path });
  const response = await context.request.fetch(origin.origin + path, options); assert.equal(response.status(), expected, `${options.method || 'GET'} ${path}: ${response.status()}`); return response.json();
}
async function paused() {
  const health = await api('/api/local-compute/health'); if (health.token && !secrets.includes(health.token)) secrets.push(health.token);
  assert.equal(health.maintenance, true); assert.equal(health.drained, true); return health;
}
async function setup(locale, storageState) {
  const target = await browser.newContext({ viewport: { width: 1280, height: 1050 }, serviceWorkers: 'block', acceptDownloads: true, ...(storageState ? { storageState } : {}) }); contexts.push(target);
  await target.addCookies([{ name: 'eeg-layout-language', value: locale, url: origin.origin }]);
  await target.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method();
    try {
      if (['GET', 'HEAD'].includes(method) || method === 'POST' && path === '/api/community/heartbeat') return route.continue();
      // Coordinates may inspect the exact imported design; this route never admits a new task.
      if (method === 'POST' && path === '/api/design-evaluation/lookup') { const raw = request.postDataJSON(), scientific = raw.schema === 'design-submission/1' ? raw.request : raw; assert.deepEqual(scientific.design, noiseInput.design); return route.continue(); }
      if (armed && method === 'POST' && path === armed.path && isDeepStrictEqual(request.postDataJSON(), armed.body)) { armed = null; return route.continue(); }
      diagnostics.blockedWrites.push({ phase, path, method }); await route.abort('blockedbyclient');
    } catch (error) { diagnostics.routeErrors.push({ phase, path, message: error.message }); await route.abort('blockedbyclient'); }
  });
  target.on('request', request => { const url = new URL(request.url()); requests.push({ phase, transport: 'browser', method: request.method(), path: url.pathname, query: url.search }); });
  target.on('response', response => { if (response.status() >= 400) diagnostics.httpFailures.push({ phase, path: new URL(response.url()).pathname, status: response.status() }); });
  target.on('requestfailed', request => diagnostics.requestFailures.push({ phase, path: new URL(request.url()).pathname, message: request.failure()?.errorText }));
  target.on('page', targetPage => { targetPage.setDefaultTimeout(45000); targetPage.setDefaultNavigationTimeout(60000); targetPage.on('pageerror', error => diagnostics.pageErrors.push({ phase, message: error.message })); targetPage.on('console', message => { if (message.type() === 'error') diagnostics.consoleErrors.push({ phase, message: message.text() }); }); });
  return target;
}
async function navigate(path) { await page.goto(new URL(path, origin).href, { waitUntil: 'networkidle' }); }
async function shot(filename) { await page.screenshot({ path: join(output, filename), fullPage: true }); artifacts.push(filename); }
async function waitStudy(studyId, terminal = true) {
  const deadline = Date.now() + 45000;
  while (Date.now() < deadline) { const value = (await api('/api/robustness-studies/' + studyId)).study; if (!terminal || ['completed', 'completed_with_failures', 'cancelled'].includes(value.status)) return value; await new Promise(done => setTimeout(done, 100)); }
  throw new Error('Study did not reach a terminal state.');
}
async function draft(protocol, cases, title) {
  if (!await page.locator('[data-study-design]').count()) { await label(page, '导入64电极CSV或JSON').setInputFiles({ name: 'study-original.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(imported)) }); await page.locator('[data-study-design]').waitFor(); }
  await label(page, '研究名称').fill(title); await label(page, '研究备注').fill('Browser acceptance: <b>plain text</b>');
  await label(page, '重复评估协议').selectOption(protocol);
  const countCases = () => page.getByLabel(new RegExp('^' + t('案例') + ' [0-9]+ ' + t('随机种子') + '$')).count();
  while (await countCases() > cases.length) await page.getByRole('button', { name: `${t('删除案例')} ${await countCases()}`, exact: true }).click();
  while (await countCases() < cases.length) await button(page, '添加明确案例').click();
  for (const [index, entry] of cases.entries()) { await page.getByLabel(`${t('案例')} ${index + 1} ${t('随机种子')}`, { exact: true }).fill(String(entry.seed)); if (protocol === 'grid_displacements') await page.getByLabel(`${t('案例')} ${index + 1} ${t('半径参数')} (mm)`, { exact: true }).selectOption(String(entry.radius_mm)); }
  if (protocol === 'noise_seeds') await label(page, '固定半径参数（mm）').selectOption(String(cases[0].radius_mm));
  const expected = { protocol, design: imported, cases, title, notes: 'Browser acceptance: <b>plain text</b>' };
  armed = { path: '/api/robustness-studies', body: expected };
  const [saved] = await Promise.all([page.waitForResponse(response => new URL(response.url()).pathname === '/api/robustness-studies' && response.request().method() === 'POST'), button(page, '保存研究草稿').click()]); assert.equal(saved.status(), 201); const study = (await saved.json()).study;
  assert.equal(armed, null); assert.equal(study.status, 'draft'); assert.equal(study.cases.length, cases.length); assert.ok(study.cases.every(entry => entry.status === 'pending' && entry.receipt_id === null));
  assert.deepEqual(study.design, noiseInput.design); assert.deepEqual(study.annotation.electrode_names, names); assert.deepEqual(study.annotation.source_metadata, source); await page.getByRole('heading', { name: title, exact: true }).waitFor(); return study;
}
async function start(study) {
  armed = { path: '/api/robustness-studies/' + study.id + '/start', body: {} };
  const path = armed.path, [complete] = await Promise.all([page.waitForResponse(value => new URL(value.url()).pathname === path && value.request().method() === 'POST'), button(page, '开始此研究').click()]); assert.equal(complete.status(), 200); assert.equal(armed, null);
  const done = await waitStudy(study.id); assert.equal(done.status, 'completed'); await page.getByText(t('研究已完成'), { exact: true }).waitFor(); return done;
}
async function exportStudy(study, filename, locale = 'en') {
  const [download] = await Promise.all([page.waitForEvent('download'), button(page, '下载完整研究JSON', locale).click()]); await download.saveAs(join(output, filename)); artifacts.push(filename);
  const raw = await readFile(join(output, filename), 'utf8'), value = JSON.parse(raw); assert.equal(value.schema, 'eeg-robustness-study-export/1'); assert.equal(value.study.id, study.id);
  for (const entry of value.cases) {
    if (!entry.cache) { assert.equal(entry.cache_json, null); continue; }
    assert.equal(hash(entry.cache_json), entry.source_sha256); assert.deepEqual(JSON.parse(entry.cache_json), entry.cache);
    const current = value.study.cases[entry.index], previous = cached.get(JSON.stringify(current.request)); assert.ok(previous, 'Every archived case was proven cached before the browser action.');
    assert.equal(entry.key, previous.key); assert.deepEqual(entry.cache.result, previous.result);
    const receipt = (await api('/api/design-evaluation/jobs/' + current.receipt_id)).job; assert.equal(receipt.cached, true); assert.equal(receipt.key, previous.key);
  }
  return value;
}
try {
  browser = await chromium.launch({ executablePath, headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  context = await setup('en'); page = await context.newPage();
  await check('Require maintenance and exact cached results for all two noise and six grid cases', async () => {
    const health = await paused();
    for (const input of [noiseInput, gridInput]) for (const entry of input.cases) {
      const request = normalizeDesignRequest({ action: input.protocol === 'noise_seeds' ? 'evaluate' : 'perturb', design: input.design, ...entry });
      const value = await api('/api/design-evaluation/lookup', { method: 'POST', headers: { Origin: origin.origin, 'X-EEG-Compute-Token': health.token }, data: request });
      assert.equal(value.hit, true); assert.equal(value.job.cached, true); assert.equal(value.job.status, 'completed'); assert.deepEqual(value.job.request, request); cached.set(JSON.stringify(request), value.job);
    }
    return { cached_cases: cached.size, maintenance: true, drained: true };
  });
  // Proof lookups use their own visitor so the original per-browser submission limit remains available to the explicit study cases.
  await page.close(); context = await setup('en'); page = await context.newPage();
  await check('The coordinate handoff retains original coordinates, names and file declarations without starting a study', async () => {
    await navigate('/coordinates'); await label(page, '导入CSV或JSON').setInputFiles({ name: 'study-original.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(imported)) });
    await button(page, '用此坐标创建稳健性研究').waitFor(); await page.waitForLoadState('networkidle'); await button(page, '用此坐标创建稳健性研究').click(); await page.waitForURL('**/robustness?draft=1'); await page.waitForLoadState('networkidle');
    await page.locator('[data-study-design]').waitFor(); assert.equal(await label(page, '研究名称').inputValue(), noiseInput.design.name);
    const handoff = await page.evaluate(() => JSON.parse(sessionStorage.getItem('eeg-robustness-coordinate-draft/1'))); assert.deepEqual(handoff.design, imported);
    assert.equal(requests.filter(entry => entry.transport === 'browser' && entry.method === 'POST' && entry.path === '/api/robustness-studies').length, 0); return { names: 64, original_points: 64, scientific_jobs: 0 };
  });
  await check('Invalid replacement files clear the prior valid design and duplicate cases are rejected before any POST', async () => {
    await label(page, '导入64电极CSV或JSON').setInputFiles({ name: 'invalid.json', mimeType: 'application/json', buffer: Buffer.from('not JSON') }); await page.getByRole('alert').waitFor(); assert.equal(await page.locator('[data-study-design]').count(), 0); assert.equal(await button(page, '保存研究草稿').isDisabled(), true);
    await label(page, '导入64电极CSV或JSON').setInputFiles({ name: 'study-original.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(imported)) }); await page.locator('[data-study-design]').waitFor();
    await button(page, '添加明确案例').click(); await page.getByLabel(`${t('案例')} 2 ${t('随机种子')}`, { exact: true }).fill('42'); await button(page, '保存研究草稿').click(); await page.getByText(t('案例的种子与半径组合不能重复'), { exact: true }).waitFor();
    await page.getByRole('button', { name: `${t('删除案例')} 2`, exact: true }).click(); return { invalid_file_cleared: true, duplicate_rejected: true, study_posts: 0 };
  });
  await check('Saving and reloading a two-case noise draft does not submit computation', async () => {
    noiseStudy = await draft('noise_seeds', noiseInput.cases, 'Browser noise study'); const before = requests.filter(entry => entry.transport === 'browser' && entry.method === 'POST').length;
    await page.reload({ waitUntil: 'networkidle' }); await button(page, '开始此研究').waitFor(); assert.equal(requests.filter(entry => entry.transport === 'browser' && entry.method === 'POST').length, before);
    const state = await waitStudy(noiseStudy.id, false); assert.equal(state.status, 'draft'); assert.ok(state.cases.every(entry => !entry.receipt_id)); return { cases: 2, reload_posts: 0 };
  });
  await check('Explicit start completes the two exact cached noise cases and downloads the complete original caches', async () => {
    noiseStudy = await start(noiseStudy); const value = await exportStudy(noiseStudy, 'noise-study-export.json'); assert.equal(value.study.aggregation.completed_cases, 2); assert.equal(value.study.aggregation.groups[0].nominal.field_relative.n, 2);
    await shot('01-noise-completed-en.png'); return { completed_cases: 2, result_caches_equal: true, exact_cache_json_sha: true };
  });
  await check('Grid protocol runs six pre-cached cases with four original trials and case-level groups for each radius', async () => {
    await button(page, '编辑新的研究草稿').click(); gridStudy = await draft('grid_displacements', gridInput.cases, 'Browser grid study'); gridStudy = await start(gridStudy);
    const value = await exportStudy(gridStudy, 'grid-study-export.json'); assert.equal(value.study.aggregation.completed_cases, 6); assert.deepEqual(value.study.aggregation.groups.map(group => [group.radius_mm, group.case_count]), [[3, 2], [6, 2], [10, 2]]);
    assert.ok(value.study.cases.every(entry => entry.summary.trials.length === 4 && entry.summary.valid_trials + entry.summary.rejected_trials === 4));
    const rejected = value.study.cases.reduce((sum, entry) => sum + entry.summary.rejected_trials, 0), zeroCases = value.study.cases.filter(entry => entry.summary.valid_trials === 0);
    assert.equal(rejected, 19); assert.equal(zeroCases.length, 2);
    const zero = page.locator(`[data-study-case="${zeroCases[0].index}"]`); await zero.locator(':scope > summary').click();
    const summary = zero.locator('section').filter({ has: page.getByRole('heading', { name: t('本案例有效偏移摘要'), exact: true }) });
    const readings = await summary.locator('tbody tr').evaluateAll(rows => rows.map(row => [...row.querySelectorAll('td')].map(cell => cell.textContent)));
    assert.equal(readings.length, 3); for (const row of readings) assert.deepEqual(row, ['0', t('无有效读数'), t('无有效读数'), t('无有效读数')]);
    await shot('02-grid-completed-en.png'); return { completed_cases: 6, original_trials: 24, geometry_rejected_trials: rejected, cases_with_no_valid_trials: zeroCases.length, zero_case_readings_are_missing: true, radius_groups: 3 };
  });
  await check('A restored Chinese browser reads names and results with zero mutation requests', async () => {
    const state = await context.storageState(), chinese = await setup('zh-CN', state); page = await chinese.newPage(); const before = requests.length;
    await navigate('/robustness?study=' + gridStudy.id); await page.getByText('研究已完成', { exact: true }).waitFor(); const detail = page.locator('details').filter({ has: page.locator('summary', { hasText: t('查看研究输入坐标与名称', 'zh-CN') }) }).first(); await detail.locator('summary').click();
    const rows = await detail.locator('tbody tr').evaluateAll(values => values.map(row => [...row.querySelectorAll('td')].map(cell => cell.textContent)));
    assert.equal(rows.length, 64); for (const [index, row] of rows.entries()) { assert.equal(row[0], names[index]); assert.deepEqual(row.slice(2).map(Number), noiseInput.design.xyz_mm[index]); }
    assert.equal(requests.slice(before).filter(entry => entry.transport === 'browser' && entry.method === 'POST').length, 0); await shot('03-grid-restored-zh.png');
    await page.close(); page = await context.newPage(); await navigate('/robustness?study=' + gridStudy.id); await button(page, '编辑新的研究草稿').waitFor(); return { restored_names: 64, restored_points: 64, mutation_posts: 0 };
  });
  await check('Cancelling a saved draft retains both cancelled cases and never creates child receipts', async () => {
    await button(page, '编辑新的研究草稿').click(); await label(page, '导入64电极CSV或JSON').setInputFiles({ name: 'study-original.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(imported)) }); await page.locator('[data-study-design]').waitFor(); cancelledStudy = await draft('noise_seeds', noiseInput.cases, 'Browser cancelled draft');
    const path = '/api/robustness-studies/' + cancelledStudy.id + '/cancel'; armed = { path, body: {} }; const [response] = await Promise.all([page.waitForResponse(value => new URL(value.url()).pathname === path && value.request().method() === 'POST'), button(page, '取消此研究').click()]); assert.equal(response.status(), 200);
    cancelledStudy = await waitStudy(cancelledStudy.id); assert.equal(cancelledStudy.status, 'cancelled'); assert.ok(cancelledStudy.cases.every(entry => entry.status === 'cancelled' && entry.receipt_id === null)); const value = await exportStudy(cancelledStudy, 'cancelled-study-export.json'); assert.ok(value.cases.every(entry => entry.cache === null && entry.cache_json === null)); await shot('04-draft-cancelled-en.png'); return { retained_cancelled_cases: 2, child_receipts: 0 };
  });
  await check('The form bounds explicit cases at twelve without submitting them', async () => {
    await button(page, '编辑新的研究草稿').click(); const before = requests.filter(entry => entry.transport === 'browser' && entry.method === 'POST').length;
    while (await page.getByLabel(new RegExp('^' + t('案例') + ' [0-9]+ ' + t('随机种子') + '$')).count() < 12) await button(page, '添加明确案例').click(); assert.equal(await button(page, '添加明确案例').isDisabled(), true);
    assert.equal(await page.getByLabel(new RegExp('^' + t('案例') + ' [0-9]+ ' + t('随机种子') + '$')).count(), 12); assert.equal(requests.filter(entry => entry.transport === 'browser' && entry.method === 'POST').length, before); return { case_limit: 12, new_posts: 0 };
  });
  await check('Original cached science is unchanged and browser diagnostics contain no unexpected errors', async () => {
    const primaryContext = context; context = await setup('en'); const health = await paused();
    // Read ready cache results again through the same validated endpoint. This does not submit scientific work.
    for (const [raw, previous] of cached) { const value = await api('/api/design-evaluation/lookup', { method: 'POST', headers: { Origin: origin.origin, 'X-EEG-Compute-Token': health.token }, data: JSON.parse(raw) }); assert.equal(value.hit, true); assert.equal(value.job.key, previous.key); assert.deepEqual(value.job.result, previous.result); }
    context = primaryContext;
    for (const [name, entries] of Object.entries(diagnostics)) assert.deepEqual(entries, [], name);
    assert.equal(requests.filter(entry => entry.transport === 'browser' && entry.method === 'POST' && /\/jobs(?:\/|$)/.test(entry.path)).length, 0);
    return { unchanged_cached_results: 8, browser_job_posts: 0, unexpected_diagnostics: 0 };
  });
} catch (error) { failure = error; if (page) { await page.screenshot({ path: join(output, 'failure.png'), fullPage: true }).catch(() => {}); await writeFile(join(output, 'failure-page.txt'), await page.locator('body').innerText().catch(() => 'unavailable'), { mode: 0o600 }); } }
finally {
  await writeFile(join(output, 'report.json'), JSON.stringify(scrub({ stage: 5, base: origin.origin, output, finished_at: new Date().toISOString(), totals: { passed: observations.filter(value => value.pass).length, failed: observations.filter(value => !value.pass).length }, observations, diagnostics, requests, artifacts, scientific_cases_proven_cached: cached.size, failure: failure?.message ?? null, scope: 'Actual Chrome and original API responses. All eight submitted study cases are exact cache hits before admission; no public jobs POST or new FEM is permitted. Unknown mutation outcomes, file/export races and restart behavior have separate focused tests.' }), null, 2) + '\n', { mode: 0o600 });
  for (const target of contexts) await target.close().catch(() => {}); await browser?.close();
}
console.log(JSON.stringify({ output, passed: observations.filter(value => value.pass).length, failed: observations.filter(value => !value.pass).length, failure: failure?.message ?? null }));
if (failure) process.exitCode = 1;
