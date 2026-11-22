/** Actual Chrome coordinate/BIDS acceptance. Only a proven, paused golden-cache request is admitted. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { access, mkdir, readFile, writeFile } from 'node:fs/promises';
import { isAbsolute, join, relative, resolve } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { chromium } from 'playwright';
import { translateText } from '../lib/i18n/core.ts';
import { parseBIDSElectrodes } from '../lib/bids-electrodes.ts';
import { designSubmission } from '../lib/design-decision.ts';

const root = resolve(import.meta.dirname, '../..'), artifactRoot = join(root, 'artifacts/research-workflow/2026-11-14');
assert.ok(process.env.EEG_TEST_URL, 'Set EEG_TEST_URL to the isolated paused verification server.');
const base = new URL(process.env.EEG_TEST_URL);
assert.ok(base.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(base.hostname) && base.port && base.port !== '3000');
assert.ok(base.pathname === '/' && !base.search && !base.hash && !base.username && !base.password);
assert.equal(process.argv.length, 2);
const output = process.env.EEG_QA_OUTPUT || join(artifactRoot, 'stage2-coordinate-review-browser'), child = relative(artifactRoot, output);
assert.ok(isAbsolute(output) && child && child !== '..' && !child.startsWith('../') && !isAbsolute(child));
const executablePath = process.env.EEG_BROWSER_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
assert.ok(isAbsolute(executablePath)); await access(executablePath);
const baseline = JSON.parse(await readFile(join(root, 'artifacts/productization/2026-11-13/scientific-baseline/design-request.json'), 'utf8'));
assert.equal(baseline.action, 'evaluate'); assert.equal(baseline.radius_mm, 6); assert.equal(baseline.seed, 42);
assert.equal(baseline.design.name, 'Native FEM integration fixture'); assert.equal(baseline.design.xyz_mm.length, 64);
await mkdir(output, { recursive: true, mode: 0o700 });

const names = Array.from({ length: 64 }, (_, index) => index === 0 ? 'Review-Fp1, left' : index === 1 ? 'Review-Cz "midline"' : index === 2 ? 'Review-电极03' : `Review-Channel${index + 1}`);
const imported = { ...baseline.design, electrode_names: names }, observations = [], requests = [], artifacts = [], secrets = [];
const diagnostics = { pageErrors: [], consoleErrors: [], httpFailures: [], requestFailures: [], blockedWrites: [] };
const requestOrder = new Map(), successfulReads = [], controlledAborts = [], consoleMessages = [];
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const scrub = value => typeof value === 'string' ? secrets.reduce((text, secret) => text.replaceAll(secret, '[credential]'), value)
  : Array.isArray(value) ? value.map(scrub) : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, scrub(item)])) : value;
let browser, context, page, cached, originalRecord, jsonJob, bidsJob, bidsFiles, bidsDesign, failure, locale = 'en', phase = 'initialization', armedSubmission, admittedCachedJobs = 0, navigation;
const t = source => translateText(source, locale);
const button = (target, source) => target.getByRole('button', { name: t(source), exact: true });
const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const keyOf = url => { const value = new URL(url, base); return value.pathname + value.search; };
async function check(name, work) {
  phase = name; const started = Date.now();
  try { const details = await work(); observations.push({ name, pass: true, seconds: (Date.now() - started) / 1000, ...details }); console.log(JSON.stringify(scrub(observations.at(-1)))); }
  catch (error) { observations.push({ name, pass: false, error: scrub(error.message) }); throw error; }
}
async function api(path, options = {}) {
  requests.push({ transport: 'api', phase, method: options.method || 'GET', path: path.split('?')[0], query: path.includes('?') ? '?' + path.split('?')[1] : '' });
  const response = await context.request.fetch(base.origin + path, options);
  assert.ok(response.ok(), `${options.method || 'GET'} ${path}: ${response.status()}`);
  return response.json();
}
async function paused() {
  const health = await api('/api/local-compute/health');
  if (health.token && !secrets.includes(health.token)) secrets.push(health.token);
  assert.equal(health.maintenance, true); assert.equal(health.drained, true);
  return health;
}
async function navigate(path) {
  navigation = { phase, start_request_index: requests.length };
  try { await page.goto(new URL(path, base).href, { waitUntil: 'networkidle' }); }
  finally { navigation = null; }
}
async function details(source) {
  const summary = page.locator('summary').filter({ hasText: new RegExp('^' + escape(t(source)) + '$') });
  await summary.waitFor(); assert.equal(await summary.count(), 1);
  const section = summary.locator('..'); if (!await section.evaluate(element => element.open)) await summary.click(); return section;
}
async function reviewRows() {
  const section = await details('逐电极坐标检查');
  await section.locator('tbody tr').last().waitFor();
  return section.locator('tbody tr').evaluateAll(rows => rows.map(row => ({ cells: [...row.querySelectorAll('td')].map(cell => cell.textContent), movement: row.querySelectorAll('td')[4]?.getAttribute('title') })));
}
async function assertReview(evaluated) {
  const rows = await reviewRows(); assert.equal(rows.length, 64);
  for (const [index, row] of rows.entries()) {
    assert.equal(row.cells[0], names[index]); assert.equal(Number(row.cells[1]), baseline.design.region_indices[index]);
    assert.deepEqual(row.cells[2].split(',').map(Number), baseline.design.xyz_mm[index]);
    if (!evaluated) { assert.equal(row.cells[3], '—'); assert.equal(row.cells[4], '—'); assert.equal(row.movement, null); assert.equal(row.cells[5], t('未评价')); }
    else {
      const actual = cached.result.evaluated_xyz_mm[index], movement = Math.hypot(...actual.map((value, axis) => value - baseline.design.xyz_mm[index][axis]));
      assert.deepEqual(row.cells[3].split(',').map(Number), actual);
      assert.ok(Math.abs(Number(row.cells[4]) - movement) <= 5.1e-7); assert.ok(Math.abs(Number(row.movement) - movement) <= 1e-12);
      assert.equal(row.cells[5], t(movement <= 2 + 1e-7 ? '合格' : '超出投影限制'));
    }
  }
  return rows;
}
async function saveDownload(target, name, filename) {
  const waiting = page.waitForEvent('download'); await target.getByRole('button', { name, exact: true }).click();
  const download = await waiting; await download.saveAs(join(output, filename)); artifacts.push(filename);
  return readFile(join(output, filename), 'utf8');
}
async function shot(filename) { await page.screenshot({ path: join(output, filename), fullPage: true }); artifacts.push(filename); }
async function switchLanguage(next) {
  const settings = page.getByLabel(t('界面设置'), { exact: true }), menu = settings.locator('..');
  if (!await menu.evaluate(element => element.open)) await settings.click();
  await page.getByText(next === 'zh-CN' ? '简体中文' : 'English', { exact: true }).click();
  locale = next; await page.locator(`html[lang="${next}"]`).waitFor();
  const current = page.getByLabel(t('界面设置'), { exact: true });
  if (await current.locator('..').evaluate(element => element.open)) await current.click();
}
async function evaluate(design) {
  await paused(); armedSubmission = designSubmission(design, 'evaluate', 6, 42);
  assert.deepEqual(armedSubmission.request, baseline);
  const waiting = page.waitForResponse(response => new URL(response.url()).pathname === '/api/design-evaluation/jobs' && response.request().method() === 'POST');
  await button(page, '评价当前坐标').click(); const response = await waiting; assert.equal(response.status(), 202);
  const job = (await response.json()).job; assert.equal(job.cached, true); assert.equal(job.status, 'completed'); assert.equal(job.key, cached.key);
  assert.deepEqual(job.request, baseline); assert.deepEqual(job.result, cached.result); assert.match(job.annotation_id, /^[a-f0-9]{64}$/);
  await page.getByRole('heading', { name: t('已读取保存的坐标评价'), exact: true }).waitFor();
  await page.getByText(`${t('原结果来源')} · ${t({ direct_fem: '新位置FEM', scalp_node_table: '头皮节点预计算FEM' }[job.result.forward_mode] ?? '已有前向库FEM')}`, { exact: true }).waitFor();
  await button(page, '导出实际评价坐标').waitFor(); await page.waitForLoadState('networkidle'); return job;
}
const filePayloads = files => files.map(file => ({ name: file.name, mimeType: file.name.endsWith('.tsv') ? 'text/tab-separated-values' : 'application/json', buffer: Buffer.from(file.text) }));

try {
  browser = await chromium.launch({ executablePath, headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  context = await browser.newContext({ viewport: { width: 1512, height: 1100 }, serviceWorkers: 'block', acceptDownloads: true });
  await context.addCookies([{ name: 'eeg-layout-language', value: 'en', url: base.origin }]);
  await context.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method();
    if (['GET', 'HEAD'].includes(method) || method === 'POST' && path === '/api/community/heartbeat') return route.continue();
    if (method === 'POST' && path === '/api/design-evaluation/jobs' && cached && armedSubmission && isDeepStrictEqual(request.postDataJSON(), armedSubmission)) {
      admittedCachedJobs++; armedSubmission = null; return route.continue();
    }
    diagnostics.blockedWrites.push({ phase, method, path }); await route.abort('blockedbyclient');
  });
  context.on('request', request => { const url = new URL(request.url()); requestOrder.set(request, requests.length); requests.push({ transport: 'browser', phase, method: request.method(), path: url.pathname, query: url.search }); });
  context.on('response', response => {
    const url = new URL(response.url());
    if (response.status() >= 400) diagnostics.httpFailures.push({ phase, path: url.pathname, status: response.status() });
    if (response.status() === 200 && response.request().method() === 'GET') successfulReads.push({ key: keyOf(response.url()), request_index: requestOrder.get(response.request()) });
  });
  context.on('requestfailed', request => {
    const url = new URL(request.url()), message = request.failure()?.errorText;
    if (navigation && request.method() === 'GET' && url.pathname === '/api/local-compute/library' && message === 'net::ERR_ABORTED')
      controlledAborts.push({ key: keyOf(request.url()), phase: navigation.phase, request_index: requestOrder.get(request), message });
    else diagnostics.requestFailures.push({ phase, path: url.pathname, query: url.search, message });
  });
  context.on('page', target => {
    target.setDefaultTimeout(45000); target.setDefaultNavigationTimeout(60000);
    target.on('pageerror', error => diagnostics.pageErrors.push({ phase, message: error.message }));
    target.on('console', message => { if (message.type() === 'error') consoleMessages.push({ phase, message: message.text(), key: message.location().url ? keyOf(message.location().url) : '' }); });
  });
  page = await context.newPage();

  await check('Prove golden cache, maintenance and drained state before permitting a scientific action', async () => {
    const health = await paused();
    const value = await api('/api/design-evaluation/lookup', { method: 'POST', headers: { Origin: base.origin, 'X-EEG-Compute-Token': health.token }, data: baseline });
    assert.equal(value.hit, true); assert.equal(value.job?.cached, true); assert.equal(value.job?.status, 'completed'); assert.deepEqual(value.job.request, baseline);
    cached = value.job; originalRecord = (await api('/api/local-compute/library/' + cached.key)).record;
    return { scientific_key: cached.key, result_sha256: hash(cached.result), maintenance: true, drained: true };
  });
  await check('JSON import shows 64 unevaluated rows without fabricated projected positions', async () => {
    await navigate('/coordinates');
    await page.getByLabel(t('导入CSV或JSON'), { exact: true }).setInputFiles({ name: 'coordinate-review.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(imported)) });
    await assertReview(false); assert.equal(admittedCachedJobs, 0); await shot('01-json-not-evaluated-en.png');
    return { rows: 64, not_evaluated: 64, scientific_submissions: 0 };
  });
  await check('Cached evaluation shows each original point, actual point and projection distance without changing science', async () => {
    jsonJob = await evaluate(imported); await assertReview(true);
    const section = await details('逐电极坐标检查');
    const review = JSON.parse(await saveDownload(section, t('导出逐电极检查JSON'), '02-json-evaluated-review.json'));
    assert.equal(review.schema, 'electrode-coordinate-review/1'); assert.equal(review.evaluated, true); assert.equal(review.rows.length, 64);
    assert.deepEqual(review.rows.map(row => row.name), names); assert.deepEqual(review.rows.map(row => row.region), baseline.design.region_indices);
    assert.deepEqual(review.rows.map(row => row.input_xyz_mm), baseline.design.xyz_mm); assert.deepEqual(review.rows.map(row => row.evaluated_xyz_mm), cached.result.evaluated_xyz_mm);
    for (const [index, row] of review.rows.entries()) assert.ok(Math.abs(row.movement_mm - Math.hypot(...row.evaluated_xyz_mm.map((value, axis) => value - baseline.design.xyz_mm[index][axis]))) <= 1e-12);
    await shot('02-json-evaluated-en.png');
    return { scientific_key: jsonJob.key, cached: true, annotation_id: jsonJob.annotation_id, reviewed_rows: 64, exact_review_download: true };
  });
  await check('BIDS UI downloads retain original coordinates and paired declarations, including region metadata', async () => {
    const section = await details('坐标文件（BIDS、MNE、EEGLAB）'); bidsFiles = [];
    for (const name of ['electrodes.tsv', 'coordsystem.json', 'electrodes.json'])
      bidsFiles.push({ name, text: await saveDownload(section, `${t('下载')} ${name}`, '03-' + name) });
    bidsDesign = parseBIDSElectrodes(bidsFiles);
    assert.equal(bidsDesign.name, baseline.design.name); assert.deepEqual(bidsDesign.xyz_mm, baseline.design.xyz_mm);
    assert.deepEqual(bidsDesign.region_indices, baseline.design.region_indices); assert.deepEqual(bidsDesign.electrode_names, names);
    assert.equal(bidsDesign.source_metadata.coordinate_system, 'ernie_native_mm'); assert.equal(bidsDesign.source_metadata.unit, 'mm');
    return { downloaded_files: bidsFiles.map(file => file.name), input_coordinates_preserved: true, explicit_frame_and_unit: true };
  });
  await check('Paired BIDS import resets review status and evaluates the same scientific cache with a separate source annotation', async () => {
    await page.getByLabel(t('导入BIDS坐标文件'), { exact: true }).setInputFiles(filePayloads(bidsFiles));
    await assertReview(false); bidsJob = await evaluate(bidsDesign); await assertReview(true);
    assert.notEqual(bidsJob.annotation_id, jsonJob.annotation_id); assert.equal(bidsJob.key, jsonJob.key);
    assert.deepEqual(bidsJob.electrode_annotation.source_metadata, bidsDesign.source_metadata);
    const section = await details('逐电极坐标检查');
    assert.ok((await section.innerText()).includes('electrodes.tsv + coordsystem.json'));
    const review = JSON.parse(await saveDownload(section, t('导出逐电极检查JSON'), '04-bids-evaluated-review.json'));
    assert.deepEqual(review.source, bidsDesign.source_metadata); assert.deepEqual(review.rows.map(row => row.input_xyz_mm), baseline.design.xyz_mm);
    await shot('04-bids-evaluated-en.png');
    return { scientific_key: bidsJob.key, cached: true, distinct_source_annotation: true, original_scientific_result_sha256: hash(bidsJob.result) };
  });
  await check('Chinese and English coordinate review retain the same loaded scientific result', async () => {
    const before = admittedCachedJobs;
    await switchLanguage('zh-CN'); await assertReview(true);
    assert.ok((await (await details('逐电极坐标检查')).innerText()).includes('坐标声明：Ernie原生空间，单位mm。此接口不执行坐标配准。'));
    await shot('05-bids-evaluated-zh.png');
    await switchLanguage('en'); await assertReview(true);
    assert.equal(admittedCachedJobs, before); return { languages: ['en', 'zh-CN'], scientific_submissions_during_language_switch: 0 };
  });
  await check('A real project snapshot retains the BIDS source declarations independently of scientific payload', async () => {
    const health = await paused(), headers = { Origin: base.origin, 'X-EEG-Compute-Token': health.token };
    const created = await api('/api/projects', { method: 'POST', headers, data: { title: 'Coordinate BIDS acceptance ' + Date.now(), owner_name: 'Browser verification' } });
    assert.match(created.access_key, /^[a-f0-9]{64}$/); secrets.push(created.access_key);
    const path = `/api/projects/${created.project.id}`, projectHeaders = { ...headers, 'X-EEG-Project-Key': created.access_key };
    const attached = await api(path + '/entries', { method: 'POST', headers: projectHeaders, data: { revision: 1, kind: 'layout', record_id: cached.key, annotation_id: bidsJob.annotation_id } });
    const copy = await api(path + '/entries/' + attached.entry.id, { headers: { 'X-EEG-Project-Key': created.access_key } });
    assert.deepEqual(copy.snapshot.electrode_annotation.source_metadata, bidsDesign.source_metadata); assert.deepEqual(copy.snapshot.electrode_annotation.electrode_names, names);
    assert.deepEqual(copy.snapshot.payload.original_record.result, cached.result); assert.deepEqual(copy.snapshot.payload.reproduction.request, baseline);
    await writeFile(join(output, '06-bids-project-snapshot.json'), JSON.stringify(copy.snapshot, null, 2) + '\n', { mode: 0o600 }); artifacts.push('06-bids-project-snapshot.json');
    return { project_id: created.project.id, entry_id: attached.entry.id, annotation_id: bidsJob.annotation_id, source_metadata_preserved: true, scientific_payload_sha256: hash(copy.snapshot.payload) };
  });
  const invalidCases = [
    { name: 'Wrong units', error: 'BIDS坐标接口目前只接受明确的mm单位，不执行单位推断或换算。', change: files => { const value = JSON.parse(files[1].text); value.EEGCoordinateUnits = 'm'; files[1].text = JSON.stringify(value); } },
    { name: 'Undeclared Ernie frame', error: '仅接受显式声明Ernie原生坐标系的文件；MNI、head及其他坐标须先在外部配准。', change: files => { const value = JSON.parse(files[1].text); delete value.EEGLayoutLabCoordinateSystem; files[1].text = JSON.stringify(value); } },
    { name: 'Missing explicit regions', error: 'electrodes.tsv须包含name、x、y、z和明确分配的region列；不能自动分配区域。', change: files => { files[0].text = files[0].text.split('\n').map(line => line.split('\t').slice(0, 4).join('\t')).join('\n'); } },
  ];
  for (const [index, item] of invalidCases.entries()) await check(`Reject invalid BIDS input before scientific submission: ${item.name}`, async () => {
    await page.waitForLoadState('networkidle'); const before = admittedCachedJobs, files = bidsFiles.map(file => ({ ...file })); item.change(files);
    await page.getByLabel(t('导入BIDS坐标文件'), { exact: true }).setInputFiles(filePayloads(files));
    await page.getByRole('alert').filter({ hasText: t(item.error) }).waitFor(); await page.waitForLoadState('networkidle');
    assert.equal(admittedCachedJobs, before); assert.equal(await button(page, '评价当前坐标').isDisabled(), true);
    await shot(`07-invalid-${index + 1}.png`); return { explicit_error: t(item.error), scientific_submissions: 0 };
  });
  await check('Reopen the saved BIDS annotation using its precise URL with GET only', async () => {
    const before = admittedCachedJobs;
    await navigate(`/coordinates?a=${cached.key}&annotation_a=${bidsJob.annotation_id}`);
    await button(page, '导出实际评价坐标').waitFor(); await assertReview(true);
    await page.getByRole('heading', { name: t('已读取保存的坐标评价'), exact: true }).waitFor();
    assert.ok((await (await details('逐电极坐标检查')).innerText()).includes(bidsDesign.source_metadata.coordinate_system_description));
    assert.equal(admittedCachedJobs, before); await shot('08-bids-saved-reopened.png');
    return { annotation_id: bidsJob.annotation_id, original_coordinates_and_result_restored: true, scientific_submissions: 0 };
  });
  await check('Verify unchanged original science and classify any navigation cancellation against subsequent success', async () => {
    await page.waitForLoadState('networkidle'); await paused();
    assert.deepEqual((await api('/api/local-compute/library/' + cached.key)).record, originalRecord); assert.equal(admittedCachedJobs, 2);
    for (const aborted of controlledAborts) assert.ok(successfulReads.some(read => read.key === aborted.key && read.request_index > aborted.request_index), 'A cancelled navigation directory did not reload successfully.');
    for (const message of consoleMessages) {
      if (message.message.includes('net::ERR_ABORTED') && controlledAborts.some(aborted => aborted.key === message.key && aborted.phase === message.phase)) continue;
      diagnostics.consoleErrors.push(message);
    }
    for (const issues of Object.values(diagnostics)) assert.deepEqual(issues, []);
    return { cached_submissions: 2, new_fem_submissions: 0, original_record_sha256: hash(originalRecord), original_record_unchanged: true, controlled_navigation_aborts: controlledAborts.length, all_cancelled_directories_reloaded: true };
  });
} catch (error) {
  failure = scrub(error.message); process.exitCode = 1;
  if (page && !page.isClosed()) {
    await shot('failure.png').catch(() => {});
    await writeFile(join(output, 'failure-page.txt'), scrub(await page.locator('body').innerText().catch(() => '')), { mode: 0o600 });
  }
} finally {
  const report = scrub({ stage: 2, base: base.origin, output, finished_at: new Date().toISOString(),
    totals: { passed: observations.filter(value => value.pass).length, failed: observations.filter(value => !value.pass).length }, failure,
    scientific_key: cached?.key, admitted_cached_submissions: admittedCachedJobs, observations, diagnostics, controlled_aborts: controlledAborts, requests, artifacts,
    scope: 'Actual Chrome and unmodified API responses. Every scientific submit is the exact already-cached golden request, while maintenance and drained states are required. Source metadata is saved in a real project snapshot. No native computation, service startup or fabricated responses.' });
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
  console.log(JSON.stringify({ output, totals: report.totals, failure }));
  await context?.close(); await browser?.close();
}
