/** Opt-in real-browser workflows. The target must be an isolated verification host. */
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { isAbsolute, join, relative, resolve } from 'node:path';
import { translateText } from '../lib/i18n/core.ts';

const base = process.env.EEG_TEST_URL || 'http://127.0.0.1:4317';
const origin = new URL(base);
assert.ok(origin.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(origin.hostname) && origin.port !== '3000', 'Use an explicit isolated loopback server, never the working app.');
const project = resolve(import.meta.dirname, '../..');
const output = process.env.EEG_QA_OUTPUT || join(project, 'artifacts/web-refactor/2026-11-13/workflows-browser');
assert.ok(isAbsolute(output) && relative(project, output).startsWith('artifacts/'), 'QA output must be an absolute project artifacts directory.');
await mkdir(output, { recursive: true });
const observations = [], diagnostics = { pageErrors: [], consoleErrors: [], httpFailures: [], requestFailures: [] }, requests = [];
const ownedJobs = [];
let expectedOffline = false, browser, page, context, failure;
const t = (source, locale = 'en') => translateText(source, locale);
const regex = text => new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
const submitCount = () => requests.filter(r => r.method === 'POST' && /\/api\/[^/]+\/jobs$/.test(new URL(r.url).pathname)).length;
async function check(name, work) {
  const start = Date.now();
  try { const details = await work(); observations.push({ name, pass: true, seconds: (Date.now() - start) / 1000, ...details }); console.log(JSON.stringify(observations.at(-1))); }
  catch (error) { observations.push({ name, pass: false, error: error.message }); throw error; }
}
function observe(target) {
  target.setDefaultTimeout(30000); target.setDefaultNavigationTimeout(60000);
  target.on('pageerror', error => diagnostics.pageErrors.push({ url: target.url(), message: error.message }));
  target.on('console', event => { if (event.type() === 'error') diagnostics.consoleErrors.push({ url: target.url(), location: event.location(), message: event.text(), expectedOffline }); });
  target.on('request', request => requests.push({ url: request.url(), method: request.method() }));
  target.on('response', response => { if (response.status() >= 400) diagnostics.httpFailures.push({ url: response.url(), status: response.status() }); });
  target.on('requestfailed', request => diagnostics.requestFailures.push({ url: request.url(), message: request.failure()?.errorText, expectedOffline }));
}
async function read(path) {
  const response = await context.request.get(base + path);
  const value = await response.json(); assert.ok(response.ok(), `${path}: ${response.status()} ${value.error ?? ''}`); return value;
}
const go = path => page.goto(base + path, { waitUntil: 'networkidle' });
const button = source => page.getByRole('button', { name: t(source), exact: true });
const label = source => page.getByLabel(regex(t(source)));
async function range(locator, value) {
  const min = Number(await locator.getAttribute('min')), step = Number(await locator.getAttribute('step') || 1);
  await locator.focus(); await locator.press('Home');
  for (let n = min; n < value; n += step) await locator.press('ArrowRight');
  assert.equal(await locator.inputValue(), String(value));
}
async function submit(locator, endpoint) {
  const responsePromise = page.waitForResponse(r => new URL(r.url()).pathname === endpoint + '/jobs' && r.request().method() === 'POST');
  await locator.click();
  const response = await responsePromise, value = await response.json();
  assert.ok(response.ok(), `${endpoint}: ${response.status()} ${value.error ?? ''}`); assert.ok(value.job?.id);
  ownedJobs.push({ endpoint, id: value.job.id }); return value.job;
}
async function terminal(endpoint, initial) {
  let job = initial;
  const deadline = Date.now() + 600000;
  while (['queued', 'running', 'cancelling'].includes(job.status)) {
    assert.ok(Date.now() < deadline, `${endpoint} exceeded the workflow deadline`);
    await page.waitForTimeout(400); job = (await read(`${endpoint}/jobs/${job.id}`)).job;
  }
  return job;
}
async function layoutId(id) {
  const record = (await read('/api/local-compute/library/' + id)).record;
  await page.locator('.head-stage').first().scrollIntoViewIfNeeded();
  await page.waitForFunction(id => [...document.querySelectorAll('.head-stage canvas')].some(canvas => canvas.dataset.layoutId === id && canvas.dataset.electrodeCount === '64' && Number(canvas.dataset.renderCount) > 0), record.layout.id);
}

try {
  browser = await chromium.launch({ headless: true, executablePath: process.env.EEG_BROWSER_EXECUTABLE || undefined,
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, acceptDownloads: true });
  await context.addCookies([{ name: 'eeg-layout-language', value: 'en', url: origin.origin }]);
  page = await context.newPage(); observe(page);
  const records = (await read('/api/local-compute/library')).records;
  const radius = records.find(r => r.dataset_id === 'cache' && r.compatible && r.request?.region_count === 2 && r.request?.radius_mm === 35 && r.request?.mask_codes?.join(',') === 'AL,AR');
  assert.ok(radius, 'Prepare the isolated AL,AR 35 mm radius fixture before browser QA.');
  const area = records.find(r => r.dataset_id === 'strict_area' && r.mode === 'whole_scalp_free' && r.area_cap_cm2 === 120 && r.region_count === 2);
  const otherArea = records.find(r => r.dataset_id === 'strict_area' && r.mode === area.mode && r.area_cap_cm2 === area.area_cap_cm2 && r.region_count === 4);
  assert.ok(area && otherArea);

  await check('English overview → records → overview preserves selection, filters and AR without computation', async () => {
    const before = submitCount();
    await go('/?domain=whole_scalp_free&area=120&r=2&ar=43'); await layoutId(area.id);
    await page.getByRole('link', { name: t('布局记录'), exact: true }).click();
    await page.waitForURL(url => url.pathname === '/library');
    await label('布局实验协议').selectOption('cache');
    await page.getByRole('button', { name: t('查看结果'), exact: true }).first().click();
    await layoutId(radius.id);
    await range(page.getByRole('slider', { name: t('记录接受阈值AR'), exact: true }), 47);
    await page.waitForURL(url => url.searchParams.get('ar') === '47' && url.searchParams.get('record') === radius.id);
    await page.getByRole('link', { name: t('实验总览'), exact: true }).click();
    await page.waitForURL(url => url.pathname === '/' && url.searchParams.get('ar') === '47');
    assert.equal(new URL(page.url()).searchParams.get('filter'), 'cache');
    await page.getByRole('link', { name: t('布局记录'), exact: true }).click();
    await page.waitForURL(url => url.pathname === '/library');
    assert.equal(await label('布局实验协议').inputValue(), 'cache');
    assert.equal(submitCount(), before);
    await page.screenshot({ path: join(output, '01-english-records.png'), fullPage: true });
    return { selectedRecord: radius.id, ar: 47 };
  });

  await check('Chinese overview, records and draft controls retain their localized labels and AR', async () => {
    const zh = await browser.newContext({ viewport: { width: 1440, height: 1050 } });
    await zh.addCookies([{ name: 'eeg-layout-language', value: 'zh-CN', url: origin.origin }]);
    const target = await zh.newPage(); observe(target);
    try {
      await target.goto(base + '/?ar=39&r=2&area=120', { waitUntil: 'networkidle' });
      await target.getByRole('heading', { name: t('实验总览', 'zh-CN'), exact: true }).waitFor();
      await target.getByRole('link', { name: t('布局记录', 'zh-CN'), exact: true }).click();
      await target.getByRole('button', { name: t('刷新记录', 'zh-CN'), exact: true }).waitFor();
      await target.getByLabel(regex(t('布局实验协议', 'zh-CN'))).selectOption('cache');
      assert.equal(await target.getByRole('slider', { name: t('记录接受阈值AR', 'zh-CN'), exact: true }).inputValue(), '39');
      await target.screenshot({ path: join(output, '02-chinese-records.png'), fullPage: true });
      const before = submitCount();
      await target.goto(base + '/design?draft=1&r=2&radius=35&mode=preset&masks=AL,AR&ar=39', { waitUntil: 'networkidle' });
      await target.getByRole('button', { name: t('读取已保存结果', 'zh-CN'), exact: true }).waitFor();
      assert.equal(await target.getByRole('slider', { name: t('设计接受阈值AR', 'zh-CN'), exact: true }).inputValue(), '39');
      assert.equal(submitCount(), before);
      return { locale: 'zh-CN', ar: 39 };
    } finally { await zh.close(); }
  });

  await check('Design draft link and refresh preserve ordered masks, radius and AR without implicit jobs', async () => {
    const before = submitCount();
    await go('/design?draft=1&r=2&radius=35&mode=preset&masks=AL,AR&ar=46');
    await button('读取已保存结果').waitFor(); await page.reload({ waitUntil: 'networkidle' }); await button('读取已保存结果').waitFor();
    assert.equal(await page.getByRole('slider', { name: t('每区半径上限'), exact: true }).inputValue(), '35');
    assert.equal(await page.getByRole('slider', { name: t('设计接受阈值AR'), exact: true }).inputValue(), '46');
    assert.equal(new URL(page.url()).searchParams.get('masks'), 'AL,AR');
    assert.equal(submitCount(), before);
  });

  await check('Saved radius lookup and explicit same-configuration submit replay the exact cached result', async () => {
    const before = submitCount();
    await go(`/design?saved=${radius.id}&ar=46`); await button('读取已保存结果').waitFor(); await layoutId(radius.id);
    assert.equal(submitCount(), before);
    const job = await terminal('/api/local-compute', await submit(button('读取已保存结果'), '/api/local-compute'));
    assert.equal(job.status, 'completed'); assert.equal(job.cached, true); assert.equal(job.key, radius.id);
    assert.equal(job.result.layout.xyzMm.length, 64);
    await page.screenshot({ path: join(output, '03-radius-cache.png'), fullPage: true });
    return { key: job.key, cached: job.cached };
  });

  await check('Disconnected GET shows recovery controls and explicit reconnect restores the cached layout', async () => {
    expectedOffline = true;
    const pattern = '**/api/local-compute/health';
    await page.route(pattern, route => route.abort('internetdisconnected'));
    await go(`/design?saved=${radius.id}&ar=46`);
    await button('重新连接').waitFor();
    await page.unroute(pattern); await button('重新连接').click();
    await button('读取已保存结果').waitFor(); await layoutId(radius.id);
    expectedOffline = false;
    return { transport: 'actual GET aborted by Playwright; original server stayed running' };
  });

  await check('Electrode editor deactivates E1, evaluates 63 electrodes and preserves the original 64', async () => {
    await go(`/electrodes?parent=${radius.id}&ar=46`);
    await page.getByRole('checkbox', { name: 'E1 E01', exact: true }).waitFor();
    await page.getByRole('checkbox', { name: 'E1 E01', exact: true }).check(); await button('移除选中电极').click();
    await page.getByText(t('当前启用 63 点 · 2 个有电极区域 / 2 个原区域'), { exact: true }).waitFor();
    const job = await terminal('/api/electrode-editor', await submit(button('评价并另存此布局'), '/api/electrode-editor'));
    assert.equal(job.status, 'completed'); assert.equal(job.result.electrode_count, 63);
    assert.equal(job.result.request.slots[0].enabled, false);
    await page.locator('#records').getByText(regex(t('信号重建保留率'))).first().waitFor();
    assert.doesNotMatch(await page.locator('#records').innerText(), /场Reconstruction/);
    const original = (await read('/api/local-compute/library/' + radius.id)).record;
    assert.equal(original.layout.xyzMm.length, 64);
    assert.ok((await read('/api/electrode-editor/records')).records.some(record => record.key === job.key && record.electrode_count === 63));
    await page.screenshot({ path: join(output, '04-editor-63.png'), fullPage: true });
    return { key: job.key, cached: job.cached, originalCount: 64, editedCount: 63 };
  });

  await check('Compare Layouts restores both current record IDs and the shared AR', async () => {
    const before = submitCount();
    await go(`/decision?a=${area.id}&b=${otherArea.id}&ar=46&thresholdMode=joint`);
    const selection = page.getByRole('region', { name: t('选择对比方案'), exact: true });
    const a = selection.getByLabel(regex(t('方案A'))), b = selection.getByLabel(regex(t('方案B')));
    await a.waitFor();
    await page.waitForFunction(({ a, b }) => [...document.querySelectorAll('select')].some(select => select.value === a) && [...document.querySelectorAll('select')].some(select => select.value === b), { a: area.id, b: otherArea.id });
    assert.equal(await a.inputValue(), area.id); assert.equal(await b.inputValue(), otherArea.id);
    assert.equal(new URL(page.url()).searchParams.get('ar'), '46'); assert.equal(submitCount(), before);
    return { a: area.id, b: otherArea.id };
  });

  await check('Signal simulation uses the selected source/layout and supports playback, channels and original JSON download', async () => {
    const before = submitCount();
    await go(`/reception?record=${radius.id}&sourceMode=single_source&source=2&seed=2026&ar=46`);
    await label('冻结生成源').selectOption('3');
    await page.waitForURL(url => url.searchParams.get('source') === '3');
    await label('冻结生成源').selectOption('2');
    const run = page.getByRole('button', { name: new RegExp(`${t('3 · 开始信号仿真')}|${t('读取已保存结果')}`) });
    await run.waitFor(); await page.waitForFunction(() => [...document.querySelectorAll('button')].some(button => /Run signal simulation|Load saved result/.test(button.textContent) && !button.disabled));
    assert.equal(submitCount(), before);
    const job = await terminal('/api/source-reception', await submit(run, '/api/source-reception'));
    assert.equal(job.status, 'completed'); assert.equal(job.request.record_id, radius.id); assert.equal(job.request.source_index, 2);
    await button('导出本场景JSON').waitFor();
    const time = page.getByRole('slider', { name: t('波形观察时间'), exact: true });
    const initial = await time.inputValue(); await button('播放时间标记').click();
    await page.waitForFunction(({ name, initial }) => document.querySelector(`input[aria-label="${name}"]`)?.value !== initial, { name: t('波形观察时间'), initial });
    await button('暂停时间标记').click();
    const channels = page.getByLabel(t('查看电极'), { exact: false });
    assert.equal(await channels.count(), 2); await channels.nth(0).selectOption('1'); await channels.nth(1).selectOption('2');
    assert.equal(await channels.nth(0).inputValue(), '1'); assert.equal(await channels.nth(1).inputValue(), '2');
    await page.locator('[data-deferred-head], .head-stage').first().scrollIntoViewIfNeeded();
    await page.waitForFunction(() => {
      const canvases = [...document.querySelectorAll('.head-stage canvas')];
      return canvases.length === 2 && canvases.every(canvas => Number(canvas.dataset.renderCount) > 0 && canvas.dataset.potentialCount === '64') &&
        canvases[0].dataset.selectedElectrode === '1' && canvases[1].dataset.selectedElectrode === '2';
    });
    await page.locator('.head-stage').nth(0).screenshot({ path: join(output, '06-source-reference-head.png') });
    await page.locator('.head-stage').nth(1).screenshot({ path: join(output, '07-source-candidate-head.png') });
    const downloading = page.waitForEvent('download'); await button('导出本场景JSON').click();
    const download = await downloading, target = join(output, 'signal-result.json'); await download.saveAs(target);
    const saved = JSON.parse(await readFile(target, 'utf8'));
    assert.equal(saved.request.record_id, radius.id); assert.equal(saved.request.source_index, 2); assert.equal(saved.layout.xyzMm.length, 64);
    assert.deepEqual(saved.request, job.request);
    await page.screenshot({ path: join(output, '05-signal-playback.png'), fullPage: true });
    return { key: job.key, cached: job.cached, source: 2, selectedChannels: [1, 2], download: target };
  });

  await check('An explicitly submitted uncached signal task can be cancelled without a completed result', async () => {
    await go(`/reception?record=${radius.id}&sourceMode=single_source&source=3&seed=${Date.now() % 10000}&ar=46`);
    const run = button('3 · 开始信号仿真'); await run.waitFor();
    const job = await submit(run, '/api/source-reception');
    assert.ok(['queued', 'running'].includes(job.status), 'Cancellation fixture unexpectedly hit a completed cache.');
    await button('停止计算').click();
    const stopped = await terminal('/api/source-reception', job);
    assert.equal(stopped.status, 'cancelled'); assert.equal(stopped.result, null);
    return { id: job.id, statusAtSubmission: job.status, terminal: stopped.status, usesMockResponses: false };
  });

  await check('No unexpected page, console or asset/API HTTP errors', async () => {
    assert.deepEqual(diagnostics.pageErrors, []);
    assert.deepEqual(diagnostics.httpFailures, []);
    assert.deepEqual(diagnostics.consoleErrors.filter(error => !error.expectedOffline), []);
    const unexpected = diagnostics.requestFailures.filter(error => !error.expectedOffline && !error.message?.includes('ERR_ABORTED'));
    assert.deepEqual(unexpected, []);
    return { expectedOfflineErrors: diagnostics.consoleErrors.filter(error => error.expectedOffline).length };
  });
} catch (error) {
  failure = error.message; process.exitCode = 1;
  await page?.screenshot({ path: join(output, 'failure.png'), fullPage: true }).catch(() => {});
  await writeFile(join(output, 'failure-page.txt'), await page?.locator('body').innerText().catch(() => '') || '');
} finally {
  if (context) {
    for (const { endpoint, id } of ownedJobs) {
      try {
        const job = (await read(`${endpoint}/jobs/${id}`)).job;
        if (['queued', 'running', 'cancelling'].includes(job.status)) {
          const health = await read('/api/local-compute/health');
          await context.request.post(base + `${endpoint}/jobs/${id}/cancel`, { headers: { Origin: origin.origin, 'X-EEG-Compute-Token': health.token } });
        }
      } catch { /* Preserve the original failure and all collected diagnostics. */ }
    }
  }
  const report = { base, output, finishedAt: new Date().toISOString(), totals: { passed: observations.filter(item => item.pass).length, failed: observations.filter(item => !item.pass).length }, failure, observations, diagnostics,
    scope: 'Actual browser controls and isolated server results; network-abort recovery uses no fabricated HTTP payloads.' };
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  await browser?.close();
}
