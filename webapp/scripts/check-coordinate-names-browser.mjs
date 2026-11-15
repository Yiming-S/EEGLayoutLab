/** Actual name round trips on an isolated, paused server; only proven cache hits may be submitted. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { access, mkdir, readFile, writeFile } from 'node:fs/promises';
import { isAbsolute, join, relative, resolve } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { chromium } from 'playwright';
import { translateText } from '../lib/i18n/core.ts';
import { parseDesign } from '../lib/design-decision.ts';

const root = resolve(import.meta.dirname, '../..');
assert.ok(process.env.EEG_TEST_URL, 'Set EEG_TEST_URL to the isolated paused verification server.');
const base = new URL(process.env.EEG_TEST_URL);
assert.ok(base.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(base.hostname) && base.port && base.port !== '3000');
assert.ok(base.pathname === '/' && !base.search && !base.hash && !base.username && !base.password);
assert.equal(process.argv.length, 2);
const artifactRoot = join(root, 'artifacts/research-workflow/2026-11-14');
const output = process.env.EEG_QA_OUTPUT || join(artifactRoot, 'stage1-names-browser');
const child = relative(artifactRoot, output);
assert.ok(isAbsolute(output) && child && child !== '..' && !child.startsWith('../') && !isAbsolute(child));
const executablePath = process.env.EEG_BROWSER_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
assert.ok(isAbsolute(executablePath)); await access(executablePath);
const baseline = JSON.parse(await readFile(join(root, 'artifacts/productization/2026-11-13/scientific-baseline/design-request.json'), 'utf8'));
assert.equal(baseline.action, 'evaluate'); assert.equal(baseline.radius_mm, 6); assert.equal(baseline.seed, 42);
assert.equal(baseline.design.name, 'Native FEM integration fixture'); assert.equal(baseline.design.xyz_mm.length, 64);
await mkdir(output, { recursive: true, mode: 0o700 });

const observations = [], requests = [], secrets = [], saved = [], artifacts = [];
const diagnostics = { pageErrors: [], consoleErrors: [], httpFailures: [], requestFailures: [], blockedWrites: [] };
const directoryPaths = new Set(['/api/local-compute/library', '/api/electrode-editor/records']);
const requestOrder = new Map(), directorySuccesses = [], controlledAborts = [], projectTransitions = [];
let browser, context, page, failure, project, cached, originalRecord, armedNames, permittedCachedJobs = 0;
let activeProjectTransition = null;
const t = source => translateText(source, 'en');
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const scrub = value => typeof value === 'string' ? secrets.reduce((text, secret) => text.replaceAll(secret, '[credential]'), value)
  : Array.isArray(value) ? value.map(scrub) : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, scrub(item)])) : value;
const button = (target, source) => target.getByRole('button', { name: t(source), exact: true });
const namesFor = version => Array.from({ length: 64 }, (_, i) => i === 0 ? `${version}-Fp1, left` : i === 1 ? `${version}-Cz "midline"` : i === 2 ? `${version}-电极03` : `${version}-Channel${String(i + 1).padStart(2, '0')}`);
const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
async function check(name, work) {
  const started = Date.now();
  try { const details = await work(); observations.push({ name, pass: true, seconds: (Date.now() - started) / 1000, ...details }); console.log(JSON.stringify(scrub(observations.at(-1)))); }
  catch (error) { observations.push({ name, pass: false, error: scrub(error.message) }); throw error; }
}
async function api(path, options = {}) {
  requests.push({ transport: 'api', method: options.method || 'GET', path: path.split('?')[0], query: path.includes('?') ? '?' + path.split('?')[1] : '' });
  const response = await context.request.fetch(base.origin + path, options);
  assert.ok(response.ok(), `${options.method || 'GET'} ${path}: ${response.status()}`);
  return response.json();
}
async function paused() {
  const health = await api('/api/local-compute/health');
  if (health.token) secrets.push(health.token);
  assert.equal(health.maintenance, true, 'Pause the isolated queue before this cache-only test.');
  assert.equal(health.drained, true, 'The isolated queue must be drained.');
  return health;
}
async function projectTransition(name, work) {
  assert.equal(activeProjectTransition, null);
  const marker = { name, start_request_index: requests.length };
  activeProjectTransition = marker; projectTransitions.push(marker);
  try { await work(); await page.waitForLoadState('networkidle'); }
  finally { marker.end_request_index = requests.length; activeProjectTransition = null; }
}
async function navigate(path) {
  const destination = new URL(path, base);
  const previous = new URL(page.url());
  const go = () => page.goto(destination.href, { waitUntil: 'networkidle' });
  if (destination.pathname === '/projects') await projectTransition('Restore project and refresh its record directory', go);
  else if (previous.pathname === '/projects') await projectTransition('Leave project page for the coordinate workflow', go);
  else await go();
}
async function openDetails(target, source, prefix = false) {
  const summary = target.locator('summary').filter({ hasText: new RegExp('^' + escape(t(source)) + (prefix ? '(?:\\s*·|$)' : '$')) });
  await summary.waitFor();
  assert.equal(await summary.count(), 1);
  const details = summary.locator('..');
  if (!await details.evaluate(element => element.open)) await summary.click();
  return details;
}
async function assertPreview(names) {
  const details = await openDetails(page, '查看电极名称与区域');
  const rows = await details.locator('tbody tr').evaluateAll(nodes => nodes.map(node => [...node.querySelectorAll('td')].map(cell => cell.textContent)));
  assert.deepEqual(rows.map(row => row[0]), names);
  assert.deepEqual(rows.map(row => Number(row[1])), baseline.design.region_indices);
  assert.deepEqual(rows.map(row => row.slice(2).map(Number)), baseline.design.xyz_mm);
}
async function download(source, filename) {
  const waiting = page.waitForEvent('download'); await button(page, source).click();
  await (await waiting).saveAs(join(output, filename)); artifacts.push(filename);
  return readFile(join(output, filename), 'utf8');
}
async function shot(filename) { await page.screenshot({ path: join(output, filename), fullPage: true }); artifacts.push(filename); }

try {
  browser = await chromium.launch({ executablePath, headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, serviceWorkers: 'block', acceptDownloads: true });
  await context.addCookies([{ name: 'eeg-layout-language', value: 'en', url: base.origin }]);
  await context.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method();
    if (['GET', 'HEAD'].includes(method)) return route.continue();
    if (method === 'POST' && path === '/api/community/heartbeat') return route.continue();
    if (method === 'POST' && (path === '/api/projects' || project && path === `/api/projects/${project.id}/entries`)) return route.continue();
    if (method === 'POST' && path === '/api/design-evaluation/jobs' && cached && armedNames) {
      const body = request.postDataJSON();
      if (body?.schema === 'design-submission/1' && isDeepStrictEqual(body.request, baseline) && isDeepStrictEqual(body.electrode_names, armedNames)) {
        permittedCachedJobs++; armedNames = null; return route.continue();
      }
    }
    diagnostics.blockedWrites.push({ method, path }); await route.abort('blockedbyclient');
  });
  context.on('request', request => { const url = new URL(request.url()); requestOrder.set(request, requests.length); requests.push({ transport: 'browser', method: request.method(), path: url.pathname, query: url.search }); });
  context.on('response', response => {
    const path = new URL(response.url()).pathname;
    if (response.status() >= 400) diagnostics.httpFailures.push({ path, status: response.status() });
    if (response.status() === 200 && directoryPaths.has(path)) directorySuccesses.push({ path, request_index: requestOrder.get(response.request()) });
  });
  context.on('requestfailed', request => {
    const path = new URL(request.url()).pathname, message = request.failure()?.errorText;
    if (activeProjectTransition && request.method() === 'GET' && directoryPaths.has(path) && message === 'net::ERR_ABORTED') {
      controlledAborts.push({ path, method: 'GET', message, request_index: requestOrder.get(request), project_transition: activeProjectTransition.name });
    } else diagnostics.requestFailures.push({ path, message });
  });
  context.on('page', target => {
    target.setDefaultTimeout(45000); target.setDefaultNavigationTimeout(60000);
    target.on('pageerror', error => diagnostics.pageErrors.push(error.message));
    target.on('console', message => { if (message.type() === 'error') diagnostics.consoleErrors.push(message.text()); });
  });
  page = await context.newPage();

  await check('Confirm the actual native-coordinate cache before allowing any evaluation click', async () => {
    const health = await paused();
    const value = await api('/api/design-evaluation/lookup', { method: 'POST', headers: { Origin: base.origin, 'X-EEG-Compute-Token': health.token }, data: baseline });
    assert.equal(value.hit, true, 'Golden native-coordinate cache is missing. No job submission is permitted.');
    assert.equal(value.job?.status, 'completed'); assert.equal(value.job.cached, true); assert.match(value.job.key, /^[a-f0-9]{64}$/);
    assert.deepEqual(value.job.request, baseline); assert.deepEqual(value.job.result.request, baseline);
    cached = value.job;
    originalRecord = (await api('/api/local-compute/library/' + cached.key)).record;
    assert.equal(originalRecord.id, cached.key);
    return { cached: true, key: cached.key, scientific_result_sha256: hash(cached.result), maintenance: true, drained: true };
  });

  await check('Create a new project through its visible form without logging its credential', async () => {
    await navigate('/projects');
    await page.getByLabel(t('项目名称'), { exact: true }).fill('Coordinate name round-trip ' + Date.now());
    await page.getByLabel(t('负责人姓名'), { exact: true }).fill('Browser verification');
    const waiting = page.waitForResponse(response => new URL(response.url()).pathname === '/api/projects' && response.request().method() === 'POST');
    await projectTransition('Create project and refresh its record directory', async () => {
      await button(page, '创建项目').click(); const response = await waiting; assert.equal(response.status(), 201);
      const value = await response.json(); assert.match(value.access_key, /^[a-f0-9]{64}$/); secrets.push(value.access_key); project = value.project;
      await page.getByRole('heading', { name: project.title, exact: true }).waitFor();
    });
    return { project_id: project.id };
  });

  for (const version of ['A', 'B']) {
    const names = namesFor(version);
    await check(`${version}: import names, evaluate only the proven cache, export actual CSV and save its own project entry`, async () => {
      await paused();
      await page.waitForLoadState('networkidle');
      await navigate('/coordinates');
      const imported = { ...baseline.design, electrode_names: names }, inputFilename = `names-${version}-input.json`;
      await writeFile(join(output, inputFilename), JSON.stringify(imported, null, 2) + '\n'); artifacts.push(inputFilename);
      await page.getByLabel(t('导入CSV或JSON'), { exact: true }).setInputFiles({ name: inputFilename, mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(imported)) });
      await assertPreview(names);
      armedNames = names;
      const waiting = page.waitForResponse(response => new URL(response.url()).pathname === '/api/design-evaluation/jobs' && response.request().method() === 'POST');
      await button(page, '评价当前坐标').click(); const response = await waiting; assert.ok(response.ok());
      const job = (await response.json()).job;
      assert.equal(job.cached, true); assert.equal(job.status, 'completed'); assert.equal(job.key, cached.key);
      assert.match(job.annotation_id, /^[a-f0-9]{64}$/); assert.deepEqual(job.result, cached.result);
      await button(page, '导出实际评价坐标').waitFor();
      const csv = parseDesign(await download('导出实际评价坐标', `names-${version}-evaluated.csv`));
      assert.deepEqual(csv.electrode_names, names); assert.deepEqual(csv.xyz_mm, cached.result.evaluated_xyz_mm); assert.deepEqual(csv.region_indices, baseline.design.region_indices);
      const reopenHref = await page.getByRole('link', { name: t('打开保存的坐标评价'), exact: true }).getAttribute('href');
      assert.equal(new URL(reopenHref, base).searchParams.get('annotation_a'), job.annotation_id);
      const saving = page.waitForResponse(result => new URL(result.url()).pathname === `/api/projects/${project.id}/entries` && result.request().method() === 'POST');
      await button(page, '保存当前布局到项目').last().click(); const attached = await saving; assert.equal(attached.status(), 201);
      const value = await attached.json(); project = value.project;
      assert.equal(value.entry.annotation_id, job.annotation_id); assert.equal(value.entry.record_id, cached.key);
      saved.push({ version, names, entry: value.entry, annotation_id: job.annotation_id, reopenHref });
      await shot(`names-${version}-evaluated.png`);
      return { key: job.key, cached: true, annotation_id: job.annotation_id, entry_id: value.entry.id, evaluated_csv_names_preserved: true };
    });
    await check(`${version}: reopen the exact saved annotation through its actual visible coordinate link`, async () => {
      const item = saved.at(-1);
      await page.waitForLoadState('networkidle');
      const loading = page.waitForResponse(response => new URL(response.url()).pathname === '/api/local-compute/library/' + cached.key && new URL(response.url()).searchParams.get('annotation_id') === item.annotation_id);
      await page.getByRole('link', { name: t('打开保存的坐标评价'), exact: true }).click();
      const response = await loading; assert.equal(response.status(), 200);
      const record = (await response.json()).record;
      assert.equal(record.electrode_annotation.id, item.annotation_id); assert.deepEqual(record.electrode_annotation.electrode_names, names);
      await assertPreview(names);
      await page.waitForLoadState('networkidle');
      return { exact_annotation_reopened: true, annotation_id: item.annotation_id };
    });
  }

  await check('Both project snapshots retain their own names while keeping the entire scientific payload identical', async () => {
    assert.notEqual(saved[0].annotation_id, saved[1].annotation_id);
    await navigate(`/projects?project=${project.id}`);
    await page.getByRole('heading', { name: project.title, exact: true }).waitFor();
    assert.equal(project.entries.length, 2); assert.equal(await page.getByRole('article').count(), 2);
    const snapshots = [];
    for (const [index, item] of saved.entries()) {
      const waiting = page.waitForResponse(response => new URL(response.url()).pathname === `/api/projects/${project.id}/entries/${item.entry.id}`);
      await button(page.getByRole('article').nth(index), '查看保存的科学数据').click();
      const response = await waiting; assert.equal(response.status(), 200); const value = await response.json();
      assert.equal(value.snapshot.electrode_annotation.id, item.annotation_id); assert.deepEqual(value.snapshot.electrode_annotation.electrode_names, item.names);
      const region = page.getByRole('region', { name: t('保存的科学数据'), exact: true });
      const details = await openDetails(region, '查看已保存坐标', true);
      assert.deepEqual(await details.locator('tbody tr td:first-child').allTextContents(), item.names);
      const downloaded = JSON.parse(await download('下载保存的科学数据', `names-${item.version}-snapshot.json`));
      assert.deepEqual(downloaded, value.snapshot); snapshots.push(value.snapshot);
      await shot(`names-${item.version}-project-snapshot.png`);
    }
    assert.deepEqual(snapshots[0].payload, snapshots[1].payload);
    return { scientific_key: cached.key, different_annotations: true, original_scientific_payloads_equal: true, payload_sha256: hash(snapshots[0].payload) };
  });

  await check('No original scientific record changed and no uncached task or browser error occurred', async () => {
    assert.deepEqual((await api('/api/local-compute/library/' + cached.key)).record, originalRecord);
    await paused(); assert.equal(permittedCachedJobs, 2);
    for (const aborted of controlledAborts) assert.ok(directorySuccesses.some(success => success.path === aborted.path && success.request_index > aborted.request_index), 'A deliberately cancelled directory did not successfully reload: ' + aborted.path);
    for (const errors of Object.values(diagnostics)) assert.deepEqual(errors, []);
    return { cached_task_submissions: 2, new_fem_submissions: 0, original_record_unchanged: true, original_record_sha256: hash(originalRecord), controlled_directory_aborts: controlledAborts.length, all_cancelled_directories_reloaded: true };
  });
} catch (error) {
  failure = scrub(error.message); process.exitCode = 1;
  if (page && !page.isClosed()) {
    await shot('failure.png').catch(() => {});
    await writeFile(join(output, 'failure-page.txt'), scrub(await page.locator('body').innerText().catch(() => '')), { mode: 0o600 });
  }
} finally {
  const report = scrub({ stage: 1, base: base.origin, output, finished_at: new Date().toISOString(),
    totals: { passed: observations.filter(value => value.pass).length, failed: observations.filter(value => !value.pass).length }, failure,
    project_id: project?.id, scientific_key: cached?.key, permitted_cached_submissions: permittedCachedJobs, observations, diagnostics, controlled_aborts: controlledAborts, directory_successes: directorySuccesses, project_transitions: projectTransitions, requests, artifacts,
    scope: 'Actual Chrome, real cache and UI downloads. Queue maintenance and an exact golden-request cache hit are required before two explicit cached submissions. Names are metadata; no uncached computation, native FEM, service startup or fabricated HTTP payloads.' });
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
  console.log(JSON.stringify({ output, totals: report.totals, failure }));
  await context?.close(); await browser?.close();
}
