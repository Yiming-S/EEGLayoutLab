import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { playwrightCookies, scriptServer } from './helpers/service-session.mjs';

// The Python service (eeglayoutlab serve): with EEG_SERVICE_RUNTIME (its <workspace>/.eeglayoutlab/runtime.json), or
// EEG_SERVICE_TOKEN and EEG_TEST_URL, the browser holds its session cookie. With EEG_TEST_URL alone, the legacy Node
// host there. EEG_BROWSER_EXECUTABLE chooses the browser and EEG_QA_OUTPUT the capture directory.
const { base, service } = await scriptServer();
const output = (process.env.EEG_QA_OUTPUT || new URL('../outputs/head-viewer/', import.meta.url).pathname).replace(/\/?$/, '/');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.EEG_BROWSER_EXECUTABLE || undefined, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const errors = [];
const results = [];
let page;
try {
  page = await browser.newPage({ viewport: { width: 1440, height: 1050 }, deviceScaleFactor: 1 });
  page.setDefaultTimeout(30000);
  page.on('pageerror', error => errors.push(error.message));
  const url = base + '/';
  await page.context().addCookies([{ name: 'eeg-layout-language', value: 'zh-CN', url: base },
    ...(service ? playwrightCookies(service) : [])]);
  // Since design 0004 the viewer is on each layout's page (/layout?id=), not on the home page: the 120 cm²
  // whole-scalp strict-area record of each region count.
  const library = await (await page.request.get(new URL('/api/local-compute/library', url).href)).json();
  const areaRecord = n => {
    const selected = library.records.find(record => record.dataset_id === 'strict_area' && record.mode === 'whole_scalp_free' && record.area_cap_cm2 === 120 && record.region_count === n);
    if (!selected) throw new Error('Missing strict-area fixture for R=' + n);
    return selected;
  };
  await page.goto(new URL('/layout?id=' + areaRecord(2).id, url).href, { waitUntil: 'networkidle', timeout: 60000 });
  const canvas = page.locator('.head-stage canvas');
  await page.waitForFunction(() => document.querySelector('.head-stage canvas')?.dataset.electrodeCount === '64', null, { timeout: 60000 });
  const waitDataset = (key, value) => page.waitForFunction(({key,value}) => document.querySelector('.head-stage canvas')?.dataset[key] === value, {key,value});
  const referenceToggle = page.getByRole('switch', { name: '标准64导布局', exact: true });
  if (!await referenceToggle.isChecked()) await referenceToggle.click();
  await waitDataset('referenceCount','64');
  await page.locator('.head-stage').screenshot({ path: `${output}01-scalp.png` });
  await page.screenshot({ path: `${output}desktop.png`, fullPage: true });
  results.push({ check: 'Selected layout and enabled reference each have 64 contacts', pass: (await canvas.getAttribute('data-reference-count')) === '64' });
  const before = createHash('sha256').update(await canvas.screenshot()).digest('hex');
  const box = await canvas.boundingBox();
  await page.mouse.move(box.x + box.width * .5, box.y + box.height * .52);
  await page.mouse.down(); await page.mouse.move(box.x + box.width * .72, box.y + box.height * .58, { steps: 18 }); await page.mouse.up();
  await page.waitForTimeout(500);
  const after = createHash('sha256').update(await canvas.screenshot()).digest('hex');
  results.push({ check: 'Mouse drag changes rendered view', pass: before !== after });
  await page.getByRole('button', { name: '左侧', exact: true }).click();
  await page.locator('.head-stage').screenshot({ path: `${output}02-left.png` });
  await page.getByRole('button', { name: '透视大脑', exact: true }).click();
  await page.locator('.head-stage').screenshot({ path: `${output}03-brain.png` });
  results.push({ check: 'Brain transparency mode', pass: await canvas.getAttribute('data-view-mode') === 'brain' });
  await page.getByRole('button', { name: '头皮视图', exact: true }).click();
  for (const n of [1, 3, 4, 6, 2]) {
    const selected = areaRecord(n);
    await page.goto(new URL('/layout?id=' + selected.id, url).href, { waitUntil: 'networkidle', timeout: 60000 });
    const detail = await (await page.request.get(new URL('/api/local-compute/library/' + selected.id,url).href)).json();
    await waitDataset('layoutId', detail.record.layout.id);
    await waitDataset('electrodeCount','64');
    results.push({ check: `R=${n} keeps 64 contacts`, pass: true });
  }
  if (!await referenceToggle.isChecked()) await referenceToggle.click();
  await waitDataset('referenceCount','64');
  await referenceToggle.click();
  await waitDataset('referenceCount','0');
  results.push({ check: 'Hide reference overlay', pass: await canvas.getAttribute('data-reference-count') === '0' });
  await page.getByRole('switch', { name: /当前布局电极/ }).click();
  await waitDataset('visibleRegionCount','0');
  results.push({ check: 'Hide both electrode layers independently', pass: await canvas.getAttribute('data-reference-count') === '0' && await canvas.getAttribute('data-visible-region-count') === '0' });
  await page.getByRole('button', { name: '透视大脑', exact: true }).click();
  await waitDataset('viewMode','brain');
  results.push({ check: 'Hidden electrode layers stay hidden when changing view mode', pass: await canvas.getAttribute('data-visible-region-count') === '0' });
  await page.getByRole('switch', { name: '标准64导' }).click();
  await waitDataset('referenceCount','64');
  results.push({ check: 'Reference-only view', pass: await canvas.getAttribute('data-reference-count') === '64' && await canvas.getAttribute('data-visible-region-count') === '0' });
  await page.getByRole('switch', { name: /当前布局电极/ }).click();
  results.push({ check: 'Wire control removed', pass: await page.getByRole('button', { name: /导线/ }).count() === 0 });
  await page.getByRole('button', { name: '全屏查看三维视图' }).click();
  results.push({ check: 'Fullscreen locks body scroll', pass: await page.evaluate(() => document.body.style.overflow) === 'hidden' });
  await page.keyboard.press('Escape');
  results.push({ check: 'Escape restores scroll', pass: await page.evaluate(() => document.body.style.overflow) !== 'hidden' });
  await page.getByRole('button', { name: '复位三维视角' }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.head-stage').scrollIntoViewIfNeeded();
  await page.locator('.head-stage').screenshot({ path: `${output}04-mobile.png` });
  results.push({ check: 'Mobile document has no horizontal overflow', pass: await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth) });
  await page.getByRole('button', { name: '全屏查看三维视图' }).click();
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${output}05-mobile-fullscreen.png` });
  const fullscreenRender = await canvas.screenshot();
  results.push({ check: 'Mobile fullscreen contains rendered geometry', pass: fullscreenRender.byteLength > 15000, screenshotBytes: fullscreenRender.byteLength });
  const cdp = await page.context().newCDPSession(page);
  const touchBox = await canvas.boundingBox();
  const x = touchBox.x + touchBox.width * .4, y = touchBox.y + touchBox.height * .5;
  const touchBefore = createHash('sha256').update(fullscreenRender).digest('hex');
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y, id: 1 }] });
  for (let i = 1; i <= 12; i++) await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x + i * 7, y: y + i, id: 1 }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await page.waitForTimeout(400);
  results.push({ check: 'Touch drag changes rendered geometry', pass: touchBefore !== createHash('sha256').update(await canvas.screenshot()).digest('hex') });
  await cdp.detach();
  await page.keyboard.press('Escape');
  await page.goto(new URL('/method', url).href, { waitUntil: 'networkidle' });
  results.push({ check: 'Model attribution and display limits are present', pass: await page.locator('#anatomical-display').count() === 1 });
  results.push({ check: 'No page runtime errors', pass: errors.length === 0, errors });
  await writeFile(`${output}report.json`, JSON.stringify({ results }, null, 2));
  console.log(JSON.stringify({ results, output }, null, 2));
  if (results.some(result => !result.pass)) process.exitCode = 1;
} catch (error) {
  console.error(JSON.stringify({ error: error.message, errors, text: await page?.locator('body').innerText().catch(() => ''), datasets: await page?.locator('canvas').evaluateAll(es=>es.map(e=>Object.fromEntries(Object.entries(e.dataset)))).catch(()=>[]) }, null, 2));
  await page?.screenshot({ path: `${output}failure.png` }).catch(() => {});
  process.exitCode = 1;
} finally { await browser.close(); }
