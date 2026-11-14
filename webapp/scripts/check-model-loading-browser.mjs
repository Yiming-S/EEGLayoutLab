/** Real-browser model-loading benchmark against an explicitly selected isolated server. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { isAbsolute, join, relative, resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { chromium } from 'playwright';
import { translateText } from '../lib/i18n/core.ts';

const project = resolve(import.meta.dirname, '../..');
assert.ok(process.env.EEG_TEST_URL, 'Set EEG_TEST_URL to the isolated verification server.');
const origin = new URL(process.env.EEG_TEST_URL);
assert.ok(origin.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(origin.hostname) && origin.port && origin.port !== '3000', 'Use an explicit isolated loopback port, never the working app.');
const expectShared = process.argv.includes('--expect-shared');
const expectDeferred = process.argv.includes('--expect-deferred');
const label = process.env.EEG_BENCHMARK_LABEL || (expectShared ? 'shared' : 'baseline');
assert.match(label, /^[a-z0-9-]+$/);
const output = process.env.EEG_QA_OUTPUT || join(project, 'artifacts/performance/2026-11-13', label);
assert.ok(isAbsolute(output) && relative(project, output).startsWith('artifacts/'), 'Store benchmark output in this project artifacts directory.');
await mkdir(output, { recursive: true });
const fixturePath = process.env.EEG_SIGNAL_FIXTURE || join(project, 'artifacts/web-refactor/2026-11-13/workflows-browser/signal-result.json');
const fixture = JSON.parse(await readFile(fixturePath, 'utf8'));
assert.equal(fixture.request.mode, 'single_source');
assert.equal(fixture.layout.xyzMm.length, 64);
const query = new URLSearchParams({ record: fixture.request.record_id, sourceMode: fixture.request.mode,
  source: String(fixture.request.source_index), seed: String(fixture.request.seed), wave: fixture.request.waveform,
  scale: String(fixture.request.artifact_scale), ar: '46' });
const url = `${origin.origin}/reception?${query}`;
const t = source => translateText(source, 'en');
const diagnostics = { pageErrors: [], consoleErrors: [], httpFailures: [], requestFailures: [] };
const requests = [], modelRequests = new Map(), phases = [];
const networkProfile = { latencyMs: 40, downloadBitsPerSecond: 10_000_000, uploadBitsPerSecond: 10_000_000 };
let browser, context, page, cdp, phase = 'setup', failure;

function modelResources() {
  return page.evaluate(() => performance.getEntriesByType('resource').filter(entry => new URL(entry.name).pathname.startsWith('/models/ernie/')).map(entry => ({
    path: new URL(entry.name).pathname, startTimeMs: entry.startTime, durationMs: entry.duration,
    transferSize: entry.transferSize, encodedBodySize: entry.encodedBodySize, decodedBodySize: entry.decodedBodySize,
  })));
}
function phaseNetwork(name) {
  const items = [...modelRequests.values()].filter(item => item.phase === name);
  return { requests: items, requestCount: items.length, encodedDataLength: items.reduce((sum, item) => sum + (item.encodedDataLength || 0), 0) };
}
async function waitForReady() {
  const target = page.locator('[data-deferred-head], .head-stage').first();
  await target.waitFor();
  await target.scrollIntoViewIfNeeded();
  await page.waitForFunction(() => {
    const canvases = [...document.querySelectorAll('.head-stage canvas')];
    return canvases.length === 2 && canvases.every(canvas => canvas.dataset.potentialCount === '64' && canvas.dataset.electrodeCount === '64' && Number(canvas.dataset.renderCount) > 0);
  });
  return page.locator('.head-stage canvas').evaluateAll(canvases => canvases.map(canvas => ({ ...canvas.dataset })));
}
async function verifyIndependentViews() {
  const channels = page.getByLabel(t('查看电极'), { exact: false });
  assert.equal(await channels.count(), 2);
  await channels.nth(0).selectOption('1');
  await channels.nth(1).selectOption('2');
  await page.waitForFunction(() => {
    const canvases = [...document.querySelectorAll('.head-stage canvas')];
    return canvases.length === 2 && canvases[0].dataset.selectedElectrode === '1' && canvases[1].dataset.selectedElectrode === '2';
  });
  const states = await page.locator('.head-stage canvas').evaluateAll(canvases => canvases.map(canvas => ({ ...canvas.dataset })));
  for (const state of states) {
    assert.equal(state.potentialCount, '64'); assert.equal(state.electrodeCount, '64');
    assert.equal(state.viewMode, 'brain'); assert.equal(state.sourcePartitions, 'dk40-six-roi-v1');
    assert.ok(Number(state.renderCount) > 0); assert.equal(state.renderPaused, 'false');
  }
  assert.notEqual(states[0].layoutId, states[1].layoutId);
  assert.equal(states[0].potentialLimit, states[1].potentialLimit);
  return states;
}
async function capture(name) {
  await page.locator('.head-stage').first().scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(output, `${name}-both-viewers.png`) });
  await page.locator('.head-stage').nth(0).screenshot({ path: join(output, `${name}-reference-head.png`) });
  await page.locator('.head-stage').nth(1).screenshot({ path: join(output, `${name}-candidate-head.png`) });
}
async function navigation(name, reload = false) {
  phase = name;
  const lookupPromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/source-reception/lookup' && response.request().method() === 'POST');
  const started = performance.now();
  if (reload) await page.reload({ waitUntil: 'domcontentloaded' });
  else await page.goto(url, { waitUntil: 'domcontentloaded' });
  const lookup = await lookupPromise, value = await lookup.json();
  assert.equal(lookup.status(), 200); assert.equal(value.hit, true); assert.equal(value.job.status, 'completed');
  assert.deepEqual(value.job.request, fixture.request);
  assert.deepEqual(value.job.result, fixture, 'The browser must restore the exact existing scientific result.');
  let deferredBeforeScroll;
  if (expectDeferred && name === 'cold') {
    await page.locator('[data-deferred-head]').first().waitFor();
    deferredBeforeScroll = await page.locator('[data-deferred-head]').evaluateAll(elements => elements.map(element => ({
      state: element.dataset.deferredHead, top: element.getBoundingClientRect().top,
      viewportHeight: innerHeight,
    })));
    assert.equal(deferredBeforeScroll.length, 2);
    assert.ok(deferredBeforeScroll.every(item => item.state === 'waiting' && item.top > item.viewportHeight + 200));
    assert.equal((await modelResources()).filter(item => item.path.endsWith('.bin')).length, 0, 'Off-screen receivers must not download binary models.');
  }
  const readyCanvases = await waitForReady();
  const modelReadyMs = performance.now() - started;
  const selectedCanvases = await verifyIndependentViews();
  await page.waitForLoadState('networkidle');
  await capture(name);
  const resources = await modelResources();
  const entry = { name, modelReadyMs, timingDefinition: 'Navigation to both visible canvases rendered with 64 potentials; includes cached-result lookup, code loading and rendering.',
    cachedScientificResult: true, deferredBeforeScroll, readyCanvases, selectedCanvases, resources,
    performanceTransferBytes: resources.reduce((sum, resource) => sum + resource.transferSize, 0), network: phaseNetwork(name) };
  phases.push(entry); console.log(JSON.stringify({ phase: name, modelReadyMs, modelRequests: entry.network.requestCount, performanceTransferBytes: entry.performanceTransferBytes }));
}

try {
  browser = await chromium.launch({ headless: true, executablePath: process.env.EEG_BROWSER_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
  await context.addCookies([{ name: 'eeg-layout-language', value: 'en', url: origin.origin }]);
  page = await context.newPage(); page.setDefaultTimeout(60000); page.setDefaultNavigationTimeout(60000);
  page.on('pageerror', error => diagnostics.pageErrors.push({ phase, message: error.message }));
  page.on('console', event => { if (event.type() === 'error') diagnostics.consoleErrors.push({ phase, message: event.text(), location: event.location() }); });
  page.on('request', request => requests.push({ phase, path: new URL(request.url()).pathname, method: request.method() }));
  page.on('response', response => { if (response.status() >= 400) diagnostics.httpFailures.push({ phase, url: response.url(), status: response.status() }); });
  page.on('requestfailed', request => diagnostics.requestFailures.push({ phase, url: request.url(), message: request.failure()?.errorText }));
  cdp = await context.newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.clearBrowserCache');
  await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: networkProfile.latencyMs,
    downloadThroughput: networkProfile.downloadBitsPerSecond / 8, uploadThroughput: networkProfile.uploadBitsPerSecond / 8 });
  cdp.on('Network.requestWillBeSent', event => {
    if (new URL(event.request.url).pathname.startsWith('/models/ernie/')) modelRequests.set(event.requestId, { phase, path: new URL(event.request.url).pathname, startTimestamp: event.timestamp, servedFromCache: false });
  });
  cdp.on('Network.requestServedFromCache', event => { const entry = modelRequests.get(event.requestId); if (entry) entry.servedFromCache = true; });
  cdp.on('Network.responseReceived', event => { const entry = modelRequests.get(event.requestId); if (entry) Object.assign(entry, { status: event.response.status, fromDiskCache: Boolean(event.response.fromDiskCache), fromServiceWorker: Boolean(event.response.fromServiceWorker), mimeType: event.response.mimeType }); });
  cdp.on('Network.loadingFinished', event => { const entry = modelRequests.get(event.requestId); if (entry) Object.assign(entry, { encodedDataLength: event.encodedDataLength, durationMs: (event.timestamp - entry.startTimestamp) * 1000 }); });
  await navigation('cold');

  phase = 'same-document-remount';
  const summaries = page.locator('summary').filter({ hasText: t('三维电位与源位置 · ') });
  assert.equal(await summaries.count(), 2);
  await summaries.nth(0).click(); await summaries.nth(1).click();
  await page.waitForFunction(() => document.querySelectorAll('.head-stage canvas').length === 0);
  const resourcesBefore = (await modelResources()).length;
  const remountStarted = performance.now();
  await summaries.nth(0).click(); await summaries.nth(1).click();
  const remounted = await waitForReady();
  const remountReadyMs = performance.now() - remountStarted;
  assert.equal(remounted[0].selectedElectrode, '1'); assert.equal(remounted[1].selectedElectrode, '2');
  const selectedCanvases = await verifyIndependentViews();
  await page.waitForLoadState('networkidle');
  const remountResources = (await modelResources()).slice(resourcesBefore);
  await capture(phase);
  phases.push({ name: phase, modelReadyMs: remountReadyMs, timingDefinition: 'Opening both previously closed 3D panels to both rendered canvases; same JavaScript document.',
    selectedCanvases, resources: remountResources, performanceTransferBytes: remountResources.reduce((sum, item) => sum + item.transferSize, 0), network: phaseNetwork(phase) });
  console.log(JSON.stringify({ phase, modelReadyMs: remountReadyMs, modelRequests: phases.at(-1).network.requestCount, performanceTransferBytes: phases.at(-1).performanceTransferBytes }));

  await page.evaluate(() => window.scrollTo(0, 0));
  await navigation('normal-reload', true);
  const jobSubmissions = requests.filter(request => request.method === 'POST' && /\/api\/[^/]+\/jobs$/.test(request.path));
  assert.equal(jobSubmissions.length, 0, 'This benchmark must never submit a computation.');
  for (const [name, events] of Object.entries(diagnostics)) assert.equal(events.length, 0, `${name}: ${JSON.stringify(events)}`);
  if (expectShared) {
    const cold = phases.find(item => item.name === 'cold');
    const cortex = cold.resources.filter(item => item.path.endsWith('/source-roi-cortex.bin'));
    assert.equal(cortex.length, 1, 'Cold two-viewer load must make exactly one cortex request.');
    assert.ok(cortex[0].transferSize > 0, 'Cold cache must actually transfer the cortex.');
    const remount = phases.find(item => item.name === 'same-document-remount');
    assert.equal(remount.network.requests.filter(item => item.path.endsWith('.bin')).length, 0, 'Same-document remount must reuse binary model assets without requests; small index revalidation is allowed.');
    assert.equal(phases.find(item => item.name === 'normal-reload').resources.filter(item => item.path.endsWith('/source-roi-cortex.bin')).length, 1);
  }
} catch (error) {
  failure = { message: error.message, stack: error.stack };
  if (page) await page.screenshot({ path: join(output, 'failure.png'), fullPage: true }).catch(() => {});
  console.error(error);
} finally {
  await writeFile(join(output, 'report.json'), JSON.stringify({ pass: !failure, label, expectShared, expectDeferred, url, fixturePath,
    fixtureSha256: createHash('sha256').update(JSON.stringify(fixture)).digest('hex'), browserVersion: browser?.version(),
    conditions: { viewport: { width: 1440, height: 1100 }, headless: true, renderer: 'SwiftShader', networkProfile, coldCache: 'Fresh browser/context plus Network.clearBrowserCache; normal HTTP cache stays enabled.',
      note: 'Synthetic fixed network profile on a local verification server; timings are measurements of this run, not an estimate of production server or user-device performance.' },
    phases, requests, noNewJobs: !requests.some(request => request.method === 'POST' && /\/api\/[^/]+\/jobs$/.test(request.path)), diagnostics, failure }, null, 2) + '\n');
  await browser?.close();
}
if (failure) process.exitCode = 1;
