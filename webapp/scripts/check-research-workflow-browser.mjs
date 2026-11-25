/**
 * Opt-in real Chrome checks against an isolated, already-built server.
 * Stage 1 is read-only: a real cache lookup is briefly held to observe the
 * pre-result draft, then forwarded unchanged. No task submission is permitted.
 */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { access, mkdir, writeFile } from 'node:fs/promises';
import { isAbsolute, join, relative, resolve } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { chromium } from 'playwright';
import { translateText } from '../lib/i18n/core.ts';
import { runProjectAssociationChecks } from './helpers/project-association-browser.mjs';
import { runLocalDeliveryChecks } from './helpers/local-delivery-browser.mjs';
import { playwrightCookies, scriptServer } from './helpers/service-session.mjs';

// EEG_REPOSITORY_ROOT is the root the server serves (default this checkout); the evidence and the fixtures the stages
// read are below its artifacts. The server is the Python service (eeglayoutlab serve --cache-only): with
// EEG_SERVICE_RUNTIME (its <workspace>/.eeglayoutlab/runtime.json), or EEG_SERVICE_TOKEN and EEG_TEST_URL, every
// browser context holds its session cookie. Stages 2 and 3 save workspace projects, which need no credential there,
// and take EEG_SIGNAL_FIXTURE, EEG_SECOND_LAYOUT_ID and EEG_EDITOR_RECORD_KEY as their helpers say; stage 1 also runs
// against a legacy Node host at EEG_TEST_URL alone.
const projectRoot = resolve(process.env.EEG_REPOSITORY_ROOT || resolve(import.meta.dirname, '../..'));
assert.ok(process.argv.slice(2).length <= 1 && process.argv.slice(2).every(value => ['--stage2', '--stage3'].includes(value)), 'Use no arguments for Stage 1, --stage2 for associations or --stage3 for local deliveries.');
const stage = process.argv.includes('--stage3') ? 3 : process.argv.includes('--stage2') ? 2 : 1;
const { base, service } = await scriptServer({ node: stage === 1 });
const origin = new URL(base);
assert.ok(origin.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(origin.hostname) && origin.port && origin.port !== '3000', 'Use an explicit non-3000 loopback server.');
const artifactRoot = join(projectRoot, 'artifacts/research-workflow/2026-11-14');
const output = process.env.EEG_QA_OUTPUT || join(artifactRoot, `stage${stage}-browser`);
const outputPath = relative(artifactRoot, output);
assert.ok(isAbsolute(output) && outputPath && outputPath !== '..' && !outputPath.startsWith('../') && !isAbsolute(outputPath), 'Keep evidence in a named directory under artifacts/research-workflow/2026-11-14.');
const executablePath = process.env.EEG_BROWSER_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
assert.ok(isAbsolute(executablePath), 'EEG_BROWSER_EXECUTABLE must be an absolute Chrome executable path.');
await access(executablePath);
await mkdir(output, { recursive: true, mode: 0o700 });

const observations = [], requests = [], artifacts = [], lookupControls = [];
const diagnostics = { pageErrors: [], consoleErrors: [], httpFailures: [], requestFailures: [], blockedWrites: [], blockedReaderApis: [], routeErrors: [] };
const contexts = [], gates = new Set();
const secrets = [], controlledAborts = [], directorySuccesses = [];
// The session cookie and the CSRF token never reach the report.
if (service) secrets.push(service.cookie.slice(service.cookie.indexOf('=') + 1), service.csrf);
const sessionCookies = service ? playwrightCookies(service) : [];
// The project record directory loads these three together and aborts them on a project change.
const directoryPaths = new Set(['/api/local-compute/library', '/api/electrode-editor/records', '/api/community/records']);
const scrub = value => typeof value === 'string' ? secrets.reduce((text, secret) => text.replaceAll(secret, '[credential]'), value)
  : Array.isArray(value) ? value.map(scrub) : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, scrub(item)])) : value;
let browser, page, failure, fixtures, browserVersion;
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const t = (source, locale) => translateText(source, locale);
const escape = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const button = (target, source, locale) => target.getByRole('button', { name: t(source, locale), exact: true });
const heading = (target, source, locale) => target.getByRole('heading', { level: 1, name: t(source, locale), exact: true });
const jobPosts = () => requests.filter(request => request.method === 'POST' && /\/jobs(?:\/|$)/.test(request.path));

async function check(name, work) {
  const started = Date.now();
  try {
    const details = await work();
    observations.push({ name, pass: true, seconds: (Date.now() - started) / 1000, ...details });
    console.log(JSON.stringify(scrub(observations.at(-1))));
  } catch (error) {
    observations.push({ name, pass: false, error: error.message });
    throw error;
  }
}
async function read(context, path, locale = 'fixture') {
  requests.push({ locale, transport: 'api-read', method: 'GET', path, query: '' });
  const response = await context.request.get(origin.origin + path);
  assert.equal(response.status(), 200, `GET ${path}: ${response.status()}`);
  return response.json();
}
async function screenshot(target, name) {
  await target.screenshot({ path: join(output, name), fullPage: true, mask: [target.locator('input[type=password], input[readonly]')] });
  artifacts.push(name);
}
function armLookupGate(state) {
  assert.equal(state.gate, null);
  let release;
  const value = { captured: false, promise: new Promise(resolve => { release = resolve; }), release: () => release() };
  state.gate = value; gates.add(value);
  return value;
}
async function newContext(locale) {
  const context = await browser.newContext({ viewport: { width: 1000, height: 1050 }, serviceWorkers: 'block' });
  contexts.push(context);
  const state = { gate: null, projectTransition: null, localReader: false };
  const requestOrder = new Map();
  await context.addCookies([{ name: 'eeg-layout-language', value: locale, url: origin.origin }, ...sessionCookies]);
  await context.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method();
    if (state.localReader) { diagnostics.blockedReaderApis.push({ locale, method, path }); await route.abort('blockedbyclient'); return; }
    if (stage === 2 && ((method === 'POST' && /^\/api\/projects(?:\/[a-f0-9-]{36}\/entries)?$/.test(path)) || method === 'PATCH' && /^\/api\/projects\/[a-f0-9-]{36}$/.test(path))) return route.continue();
    if (!['GET', 'HEAD'].includes(method) && !(method === 'POST' && ['/api/local-compute/lookup', '/api/community/heartbeat'].includes(path))) {
      diagnostics.blockedWrites.push({ locale, method, path });
      await route.abort('blockedbyclient'); return;
    }
    const gate = state.gate;
    if (gate && !gate.captured && method === 'POST' && path === '/api/local-compute/lookup') {
      gate.captured = true;
      lookupControls.push({ locale, method, path, control: 'Delay forwarding until draft assertions finish; actual response is unchanged.' });
      await gate.promise;
      state.gate = null; gates.delete(gate);
    }
    try { await route.continue(); }
    catch (error) { diagnostics.routeErrors.push({ locale, path, message: error.message }); }
  });
  context.on('request', request => {
    const url = new URL(request.url());
    requestOrder.set(request, requests.length);
    requests.push({ locale, transport: 'browser', method: request.method(), path: url.pathname, query: url.search, local_reader: state.localReader });
  });
  context.on('response', response => {
    const path = new URL(response.url()).pathname;
    if (response.status() >= 400) diagnostics.httpFailures.push({ locale, path, status: response.status() });
    if (directoryPaths.has(path) && response.status() === 200) directorySuccesses.push({ locale, path, request_index: requestOrder.get(response.request()) });
  });
  context.on('requestfailed', request => {
    const path = new URL(request.url()).pathname, message = request.failure()?.errorText;
    if (stage === 2 && state.projectTransition && request.method() === 'GET' && directoryPaths.has(path) && message === 'net::ERR_ABORTED') controlledAborts.push({ locale, path, message, request_index: requestOrder.get(request), transition: state.projectTransition });
    else diagnostics.requestFailures.push({ locale, path, message });
  });
  context.on('page', target => {
    target.setDefaultTimeout(45000); target.setDefaultNavigationTimeout(60000);
    target.on('pageerror', error => diagnostics.pageErrors.push({ locale, message: error.message }));
    target.on('console', message => { if (message.type() === 'error') diagnostics.consoleErrors.push({ locale, message: message.text() }); });
  });
  return { context, state };
}
const settings = (target, locale) => target.locator('summary').filter({ hasText: new RegExp('^' + escape(t('布局参数', locale)) + '\\s*·') }).locator('..');
async function assertPhase(target, phase) {
  await target.locator(`header[data-design-state="${phase}"]`).waitFor();
  assert.equal(await target.locator('header[data-design-state]').count(), 1);
}
function waitForLookup(target, request) {
  return target.waitForResponse(response => {
    if (response.request().method() !== 'POST' || new URL(response.url()).pathname !== '/api/local-compute/lookup') return false;
    return !request || isDeepStrictEqual(response.request().postDataJSON(), request);
  });
}
async function lookupValue(response) {
  assert.equal(response.status(), 200);
  return response.json();
}
async function assertSavedLayoutRendered(target, layout) {
  assert.ok(layout && typeof layout.id === 'string' && layout.xyzMm.length === 64);
  await target.locator('.head-stage').first().scrollIntoViewIfNeeded();
  await target.waitForFunction(id => [...document.querySelectorAll('.head-stage canvas')].some(canvas => canvas.dataset.layoutId === id && canvas.dataset.electrodeCount === '64' && Number(canvas.dataset.renderCount) > 0), layout.id);
}
function assertCachedResult(value, record) {
  assert.equal(value.hit, true, 'Prepare a current-version compatible radius cache before this read-only test.');
  assert.equal(value.job.status, 'completed'); assert.equal(value.job.cached, true); assert.equal(value.job.key, record.id);
  assert.deepEqual(value.job.request, record.request);
  assert.deepEqual(value.job.result.request, record.request);
  for (const field of ['layout', 'metrics', 'geometry']) assert.deepEqual(value.job.result[field], record[field], `Cached ${field} changed.`);
}

try {
  browser = await chromium.launch({ executablePath, headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  browserVersion = browser.version();
  if (stage === 3) {
    fixtures = await runLocalDeliveryChecks({ root: projectRoot, output, base: origin.origin, check, newContext, read, button, screenshot, requests, keepSecret: value => secrets.push(value), setPage: value => { page = value; } });
    await check('Local delivery views made no API requests and produced no unexpected browser errors', async () => {
      assert.deepEqual(jobPosts(), []);
      assert.deepEqual(requests.filter(request => request.local_reader && request.path.startsWith('/api/')), []);
      for (const value of Object.values(diagnostics)) assert.deepEqual(value, []);
      return { local_reader_api_requests: 0, new_scientific_jobs: 0 };
    });
  } else if (stage === 2) {
    fixtures = await runProjectAssociationChecks({ root: projectRoot, base: origin.origin, check, newContext, read, button, screenshot, requests, keepSecret: value => secrets.push(value), setPage: value => { page = value; } });
    await check('Project associations have no unexpected errors or scientific job submissions', async () => {
      assert.deepEqual(jobPosts(), []);
      for (const aborted of controlledAborts) assert.ok(directorySuccesses.some(success => success.locale === aborted.locale && success.path === aborted.path && success.request_index > aborted.request_index), 'Cancelled project directory did not successfully reload.');
      for (const value of Object.values(diagnostics)) assert.deepEqual(value, []);
      return { new_scientific_jobs: 0, controlled_project_directory_aborts: controlledAborts.length, all_cancelled_directories_reloaded: true };
    });
  } else {
  const fixtureContext = await browser.newContext(); contexts.push(fixtureContext);
  await fixtureContext.addCookies(sessionCookies);
  const records = (await read(fixtureContext, '/api/local-compute/library')).records;
  const area = records.find(record => record.dataset_id === 'strict_area' && record.status === 'completed' && record.mode === 'whole_scalp_free' && record.area_cap_cm2 === 120 && record.region_count === 2)
    ?? records.find(record => record.dataset_id === 'strict_area' && record.status === 'completed');
  const availableRadius = records.filter(record => record.dataset_id === 'cache' && record.status === 'completed' && record.compatible && record.request);
  const radius = availableRadius.find(record => record.request.region_count === 2 && record.request.radius_mm === 35 && record.request.mask_codes?.join(',') === 'AL,AR') ?? availableRadius[0];
  assert.ok(area && radius, 'Prepare an actual strict-area layout and compatible completed radius cache in the isolated scientific root.');
  const areaRecord = (await read(fixtureContext, '/api/local-compute/library/' + area.id)).record;
  const radiusRecord = (await read(fixtureContext, '/api/local-compute/library/' + radius.id)).record;
  assert.ok(areaRecord.layout?.xyzMm.length === 64 && radiusRecord.layout?.xyzMm.length === 64);
  const originalArea = structuredClone(areaRecord), originalRadius = structuredClone(radiusRecord);
  fixtures = { area_record_id: area.id, radius_record_id: radius.id, area_record_sha256: hash(originalArea), radius_record_sha256: hash(originalRadius) };

  for (const locale of ['en', 'zh-CN']) {
    const { context, state } = await newContext(locale); page = await context.newPage();
    await check(`${locale}: an area record has a read-only heading and one explicit radius-creation action`, async () => {
      const start = requests.length;
      await page.goto(`${origin.origin}/design?from=${area.id}&ar=87`, { waitUntil: 'networkidle' });
      await assertPhase(page, 'area-record');
      await heading(page, '查看已有面积约束布局', locale).waitFor();
      assert.equal(await button(page, '新建每区半径约束方案', locale).count(), 1);
      assert.equal(await button(page, '开始布局计算', locale).count(), 0);
      assert.equal(await page.getByRole('slider', { name: t('每区半径上限', locale), exact: true }).count(), 0);
      await assertSavedLayoutRendered(page, areaRecord.layout);
      const seen = requests.slice(start).filter(request => request.locale === locale);
      assert.ok(seen.length > 0 && seen.every(request => request.method === 'GET' || request.method === 'POST' && request.path === '/api/community/heartbeat'), 'Area-record viewing sent a scientific mutation or lookup request.');
      assert.equal(new URL(page.url()).searchParams.get('from'), area.id);
      await screenshot(page, `${locale}-01-area-readonly.png`);
      return { record_id: area.id, record_requests_only_get: true, visitor_heartbeat_posts: seen.filter(request => request.path === '/api/community/heartbeat').length, creation_actions: 1 };
    });

    await check(`${locale}: explicit creation shows a real radius draft and its schematic, and its action expands settings`, async () => {
      const gate = armLookupGate(state), lookup = waitForLookup(page);
      try {
        await button(page, '新建每区半径约束方案', locale).click();
        await assertPhase(page, 'draft'); await heading(page, '设置半径约束布局', locale).waitFor();
        await page.getByText(t('布局示意（非计算结果）', locale), { exact: true }).waitFor();
        assert.equal(await button(page, '新建每区半径约束方案', locale).count(), 0);
        const parameters = settings(page, locale);
        if (await parameters.evaluate(element => element.open)) await parameters.locator('summary').first().click();
        assert.equal(await parameters.evaluate(element => element.open), false);
        await button(page, '查看布局参数与计算', locale).click();
        assert.equal(await parameters.evaluate(element => element.open), true);
        const slider = page.getByRole('slider', { name: t('每区半径上限', locale), exact: true });
        await slider.waitFor(); assert.equal(await slider.inputValue(), '35');
        const q = new URL(page.url()).searchParams;
        for (const [key, value] of Object.entries({ from: area.id, ar: '87', draft: '1', r: String(area.region_count), radius: '35', mode: area.mode.includes('whole') ? 'whole_surface' : 'low_hair' })) assert.equal(q.get(key), value);
        assert.deepEqual((await read(context, '/api/local-compute/library/' + area.id, locale)).record, originalArea);
        await screenshot(page, `${locale}-02-radius-draft.png`);
        await page.waitForFunction(() => document.querySelector('header[data-design-state]')?.dataset.designState === 'draft');
      } finally { gate.release(); }
      const value = await lookupValue(await lookup);
      assert.equal(gate.captured, true, 'No real cache lookup was observed.');
      await page.waitForLoadState('networkidle');
      return { lookup_forwarded_unchanged: true, lookup_hit: value.hit, source_record_unchanged: true, new_scientific_jobs: jobPosts().length };
    });

    await check(`${locale}: a completed cache is shown and reopened with exactly the saved scientific values`, async () => {
      let lookup = waitForLookup(page, radiusRecord.request);
      await page.goto(`${origin.origin}/design?saved=${radius.id}&ar=87`, { waitUntil: 'networkidle' });
      const first = await lookupValue(await lookup); assertCachedResult(first, radiusRecord);
      await assertPhase(page, 'completed'); await heading(page, '查看已完成的半径约束布局', locale).waitFor();
      await page.getByText(t('已有结果已读取，未重新计算。', locale), { exact: true }).first().waitFor();
      await assertSavedLayoutRendered(page, radiusRecord.layout);
      assert.equal(new URL(page.url()).searchParams.get('saved'), radius.id);
      await screenshot(page, `${locale}-03-cached-completed.png`);
      lookup = waitForLookup(page, radiusRecord.request);
      await page.reload({ waitUntil: 'networkidle' });
      const reopened = await lookupValue(await lookup); assertCachedResult(reopened, radiusRecord);
      assert.deepEqual(reopened.job.result, first.job.result);
      await assertPhase(page, 'completed'); await heading(page, '查看已完成的半径约束布局', locale).waitFor();
      await assertSavedLayoutRendered(page, radiusRecord.layout);
      assert.equal(new URL(page.url()).searchParams.get('ar'), '87');
      await screenshot(page, `${locale}-04-cached-reopened.png`);
      return { cached: true, record_id: radius.id, original_scientific_values_unchanged: true, cached_result_sha256: hash(first.job.result), new_scientific_jobs: jobPosts().length };
    });
    await context.close();
  }

  await check('Actual source records remain unchanged, and no job submissions or unexpected browser errors occurred', async () => {
    assert.deepEqual((await read(fixtureContext, '/api/local-compute/library/' + area.id)).record, originalArea);
    assert.deepEqual((await read(fixtureContext, '/api/local-compute/library/' + radius.id)).record, originalRadius);
    assert.deepEqual(jobPosts(), []);
    for (const value of Object.values(diagnostics)) assert.deepEqual(value, []);
    const browserWrites = requests.filter(request => request.transport === 'browser' && !['GET', 'HEAD'].includes(request.method));
    assert.ok(browserWrites.every(request => request.method === 'POST' && ['/api/local-compute/lookup', '/api/community/heartbeat'].includes(request.path)));
    return { new_scientific_jobs: 0, fabricated_responses: 0, readonly_lookup_posts: browserWrites.filter(request => request.path === '/api/local-compute/lookup').length, visitor_heartbeat_posts: browserWrites.filter(request => request.path === '/api/community/heartbeat').length, original_record_hashes: fixtures };
  });
  }
} catch (error) {
  failure = scrub(error.message); process.exitCode = 1;
  if (page && !page.isClosed()) {
    await screenshot(page, 'failure.png').catch(() => {});
    await writeFile(join(output, 'failure-page.txt'), scrub(await page.locator('body').innerText().catch(() => '')), { mode: 0o600 });
  }
} finally {
  for (const gate of gates) gate.release();
  const report = scrub({ stage, base: origin.origin, output, finished_at: new Date().toISOString(), browser: { executable: executablePath, version: browserVersion },
    totals: { passed: observations.filter(value => value.pass).length, failed: observations.filter(value => !value.pass).length }, failure,
    fixtures, observations, diagnostics, controlled_aborts: controlledAborts, directory_successes: directorySuccesses, lookup_controls: lookupControls, artifacts, requests,
    scope: stage === 1 ? 'Real Chrome and real isolated-server payloads. Each locale briefly delays one unchanged cache lookup to inspect its pre-result draft. No scientific job submissions. Queued/failure states are covered separately by hook tests, not fabricated browser responses.' : stage === 2 ? 'Real project metadata and cached source snapshots; candidate filters and name aliases never submit scientific jobs. Only real cache lookups create fixture receipts and name annotations. Project-directory lifecycle cancellations require successful replacements.' : 'Old actual delivery and current server-exported delivery, opened as local files in fresh contexts with all APIs blocked. Original packages and scientific snapshot text are compared byte for byte; controlled File.text delays alter scheduling only. No fabricated backend responses or scientific jobs.' });
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
  console.log(JSON.stringify({ output, totals: report.totals, failure, new_scientific_jobs: jobPosts().length }));
  for (const context of contexts) await context.close().catch(() => {});
  await browser?.close();
}
