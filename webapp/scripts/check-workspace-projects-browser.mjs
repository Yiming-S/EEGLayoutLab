/** Actual project controls of a workspace on the Python service; no scientific jobs, no credentials. */
import assert from 'node:assert/strict';
import { access, mkdir, writeFile } from 'node:fs/promises';
import { isAbsolute, join, relative, resolve } from 'node:path';
import { chromium } from 'playwright';
import { translateText } from '../lib/i18n/core.ts';
import { playwrightCookies, scriptServer } from './helpers/service-session.mjs';

// The Python service (eeglayoutlab serve, --cache-only is enough): with EEG_SERVICE_RUNTIME (its
// <workspace>/.eeglayoutlab/runtime.json), or EEG_SERVICE_TOKEN and EEG_TEST_URL, every browser holds its session
// cookie. A workspace belongs to one local user: its projects are listed by GET /api/projects and opened by their
// identifier, with no access key, role, sharing link or credential file. EEG_LAYOUT_ID is the completed library layout
// saved to the project (default the first one the library lists).
// EEG_REPOSITORY_ROOT is the root the service serves (default this checkout); the report goes below its artifacts
// (or EEG_QA_OUTPUT there). EEG_BROWSER_EXECUTABLE chooses Chrome.
const root = resolve(process.env.EEG_REPOSITORY_ROOT || resolve(import.meta.dirname, '../..'));
assert.equal(process.argv.length, 2, 'This check takes no arguments.');
const { base, service } = await scriptServer({ node: false });
const output = process.env.EEG_QA_OUTPUT || join(root, 'artifacts/productization/2026-11-25/workspace-projects-browser');
const inside = relative(join(root, 'artifacts'), output);
assert.ok(isAbsolute(output) && inside && !inside.startsWith('..') && !isAbsolute(inside), 'Keep the evidence below the root\'s artifacts.');
const executablePath = process.env.EEG_BROWSER_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
assert.ok(isAbsolute(executablePath)); await access(executablePath);
await mkdir(output, { recursive: true, mode: 0o700 });

const observations = [], requests = [], diagnostics = { pageErrors: [], consoleErrors: [], httpFailures: [] };
// The session cookie, the CSRF token and any key a response still carries never reach the report.
const secrets = [service.cookie.slice(service.cookie.indexOf('=') + 1), service.csrf];
const scrub = value => typeof value === 'string' ? secrets.reduce((text, secret) => text.replaceAll(secret, '[credential]'), value)
  : Array.isArray(value) ? value.map(scrub) : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, scrub(item)])) : value;
const t = source => translateText(source, 'en');
const button = (target, source) => target.getByRole('button', { name: t(source), exact: true });
// Titles unique to this run: a workspace keeps the projects of earlier runs.
const stamp = Date.now();
let browser, page, failure, project, layoutId, snapshotBefore;

async function check(name, work) {
  const started = Date.now();
  try { const details = await work(); observations.push({ name, pass: true, seconds: (Date.now() - started) / 1000, ...details }); console.log(JSON.stringify(scrub(observations.at(-1)))); }
  catch (error) { observations.push({ name, pass: false, error: scrub(error.message) }); throw error; }
}
async function newContext() {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, serviceWorkers: 'block', acceptDownloads: true });
  await context.addCookies([{ name: 'eeg-layout-language', value: 'en', url: base }, ...playwrightCookies(service)]);
  // A regression must never dispatch a scientific job.
  await context.route('**/api/**/jobs', route => route.request().method() === 'POST' ? route.abort('blockedbyclient') : route.continue());
  context.on('request', request => { const url = new URL(request.url()); requests.push({ method: request.method(), path: url.pathname, query: url.search }); });
  context.on('response', response => { if (response.status() >= 400) diagnostics.httpFailures.push({ path: new URL(response.url()).pathname, status: response.status() }); });
  context.on('page', target => {
    target.setDefaultTimeout(45000); target.setDefaultNavigationTimeout(60000);
    target.on('pageerror', error => diagnostics.pageErrors.push(error.message));
    target.on('console', message => { if (message.type() === 'error') diagnostics.consoleErrors.push(message.text()); });
  });
  return context;
}
async function api(context, path, options = {}) {
  const response = await context.request.fetch(base + path, options);
  assert.ok(response.ok(), `${options.method || 'GET'} ${path}: ${response.status()}`);
  return response.json();
}
async function mutation(target, path, method, action) {
  const waiting = target.waitForResponse(response => new URL(response.url()).pathname === path && response.request().method() === method);
  await action(); const response = await waiting;
  const value = await response.json();
  assert.ok(response.ok(), `${method} ${path}: ${response.status()} ${value?.error ?? ''}`);
  if (typeof value?.access_key === 'string' && value.access_key) secrets.push(value.access_key);
  return { status: response.status(), value };
}
// Opens the collapsed section that holds `locator`, whatever its summary says.
async function reveal(locator) {
  await locator.waitFor({ state: 'attached' });
  if (!await locator.evaluate(element => { const details = element.closest('details'); return !details || details.open; })) {
    await locator.locator('xpath=ancestor::details[1]/summary').click();
  }
  return locator;
}
const details = target => target.getByRole('region', { name: t('项目详情'), exact: true });
// A textarea's label text includes its initial content, so the notes are found by the label's own words.
const notesField = section => section.locator('label').filter({ hasText: t('项目备注') }).locator('textarea');
// Opens a project from the workspace list (a button, a link or a select option), unless the page already shows it.
async function openFromList(target) {
  const heading = target.getByRole('heading', { name: project.title, exact: true });
  const select = target.locator('select').filter({ has: target.locator(`option[value="${project.id}"]`) });
  const entry = target.getByRole('button', { name: project.title, exact: true }).or(target.getByRole('link', { name: project.title, exact: true }));
  await heading.or(entry).or(select).filter({ visible: true }).first().waitFor();
  if (!await heading.isVisible()) {
    if (await select.count()) await reveal(select.first()).then(found => found.selectOption(project.id));
    else await reveal(entry.first()).then(found => found.click());
  }
  await heading.waitFor();
}
// No control, link or text of the removed credentials remains on the page.
async function assertNoCredentials(target) {
  for (const source of ['下载项目凭据', '生成新的只读链接', '撤销只读分享', '移除此浏览器的访问记录', '打开项目'])
    assert.equal(await button(target, source).count(), 0, `The credential control "${t(source)}" remains.`);
  for (const source of ['项目访问凭据', '只读分享链接', '或导入项目凭据文件'])
    assert.equal(await target.getByLabel(t(source), { exact: true }).count(), 0, `The credential field "${t(source)}" remains.`);
  for (const source of ['管理权限', '只读访问']) assert.equal(await target.getByText(t(source), { exact: true }).count(), 0, `The role "${t(source)}" remains.`);
  const links = await target.locator('a[href]').evaluateAll(nodes => nodes.map(node => node.getAttribute('href') || ''));
  assert.ok(links.every(href => !/[#&?]access=/.test(href)), 'A credential link remains.');
  const storage = await target.evaluate(() => JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)]));
  assert.ok(!storage.includes('eeg-layout-project-access/1') && !/access_key/.test(storage), 'The access-key vault remains.');
  assert.ok(secrets.every(secret => !storage.includes(secret)), 'A secret was stored in the browser.');
}

try {
  browser = await chromium.launch({ headless: true, executablePath, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const first = await newContext(); page = await first.newPage();

  await check('Create a named workspace project through the English interface', async () => {
    const library = await api(first, '/api/local-compute/library');
    const layout = process.env.EEG_LAYOUT_ID
      ? library.records.find(row => row.id === process.env.EEG_LAYOUT_ID)
      : library.records.find(row => row.status === 'completed' && /^[a-f0-9]{64}$/.test(row.id) && typeof row.label === 'string');
    assert.ok(layout, 'The library lists no completed layout to save (set EEG_LAYOUT_ID).'); layoutId = layout.id;
    await page.goto(base + '/projects', { waitUntil: 'networkidle' });
    const form = page.getByRole('heading', { name: t('新建项目'), exact: true }).locator('..');
    await reveal(form.getByLabel(t('项目名称'), { exact: true }));
    await form.getByLabel(t('项目名称'), { exact: true }).fill(`Workspace acceptance study ${stamp}`);
    await form.getByLabel(t('负责人姓名'), { exact: true }).fill('Local QA');
    const created = await mutation(page, '/api/projects', 'POST', () => button(form, '创建项目').click());
    assert.equal(created.status, 201); project = created.value.project;
    await page.getByRole('heading', { name: project.title, exact: true }).waitFor();
    const listed = await api(first, '/api/projects');
    assert.ok(listed.projects.some(row => row.id === project.id && row.title === project.title), 'GET /api/projects does not list the new project.');
    await assertNoCredentials(page);
    return { project_id: project.id, listed: true };
  });

  await check('Save a completed layout without submitting a calculation', async () => {
    const choice = page.getByLabel(t('选择已完成记录'), { exact: true });
    await reveal(choice);
    await choice.locator(`option[value="layout:${layoutId}"]`).waitFor({ state: 'attached' });
    await choice.selectOption(`layout:${layoutId}`);
    const form = page.locator('form').filter({ has: choice });
    await form.getByLabel(t('实验名称'), { exact: true }).fill('Reference layout');
    const saved = await mutation(page, `/api/projects/${project.id}/entries`, 'POST', () => button(form, '保存到项目').click());
    assert.equal(saved.status, 201); project = saved.value.project;
    assert.equal(project.entries.length, 1); assert.equal(project.entries[0].record_id, layoutId);
    await page.locator(`article[data-project-entry-id="${project.entries[0].id}"]`).waitFor();
    return { record_id: layoutId, entries: project.entries.length };
  });

  await check('Renaming the project keeps the exact saved scientific snapshot', async () => {
    const entry = project.entries[0];
    snapshotBefore = await api(first, `/api/projects/${project.id}/entries/${entry.id}`); const revision = project.revision;
    const section = details(page), notes = notesField(section);
    await reveal(notes);
    await section.getByLabel(t('项目名称'), { exact: true }).fill(`Renamed workspace study ${stamp}`);
    await notes.fill('选择理由：保持原始坐标与科学结果。');
    const saved = await mutation(page, `/api/projects/${project.id}`, 'PATCH', () => button(section, '保存项目说明').click());
    assert.equal(saved.status, 200); project = saved.value.project;
    assert.equal(project.title, `Renamed workspace study ${stamp}`); assert.ok(project.revision > revision);
    await page.getByRole('heading', { name: project.title, exact: true }).waitFor();
    const after = await api(first, `/api/projects/${project.id}/entries/${entry.id}`);
    assert.deepEqual(after.snapshot, snapshotBefore.snapshot); assert.equal(after.entry.snapshot_sha256, entry.snapshot_sha256);
    await page.screenshot({ path: join(output, 'renamed-project.png'), fullPage: true });
    return { snapshot_sha256: entry.snapshot_sha256, revision: project.revision };
  });

  await check('A fresh browser of the session finds the project in the workspace list and edits it', async () => {
    const fresh = await newContext(), other = await fresh.newPage();
    const listing = other.waitForResponse(response => new URL(response.url()).pathname === '/api/projects' && response.request().method() === 'GET');
    await other.goto(base + '/projects', { waitUntil: 'networkidle' });
    assert.equal((await listing).status(), 200);
    await openFromList(other);
    const section = details(other), notes = notesField(section);
    await section.getByText(project.id, { exact: true }).waitFor();
    await reveal(notes);
    assert.equal(await notes.inputValue(), project.notes);
    assert.equal(await button(section, '保存项目说明').count(), 1, 'The workspace project is not editable in another browser.');
    assert.equal(await other.locator('article[data-project-entry-id]').count(), 1);
    await assertNoCredentials(other);
    await other.screenshot({ path: join(output, 'fresh-browser-project.png'), fullPage: true });
    await fresh.close();
    return { opened_from_workspace_list: true, editable: true };
  });

  await check('The project address opens it in another browser without any credential', async () => {
    const fresh = await newContext(), other = await fresh.newPage();
    await other.goto(`${base}/projects?project=${project.id}`, { waitUntil: 'networkidle' });
    await other.getByRole('heading', { name: project.title, exact: true }).waitFor();
    await details(other).getByText(project.id, { exact: true }).waitFor();
    assert.equal(new URL(other.url()).hash, '');
    await assertNoCredentials(other);
    await fresh.close();
    return { opened_by_identifier: true };
  });

  await check('Sharing is gone: its endpoints are not found and no request names a key', async () => {
    for (const suffix of ['/share', '/revoke-share']) {
      const response = await first.request.post(`${base}/api/projects/${project.id}${suffix}`,
        { headers: { Origin: base, 'X-EEG-Compute-Token': service.csrf }, data: { revision: project.revision } });
      assert.equal(response.status(), 404, `${suffix}: ${response.status()}`);
    }
    const stored = await api(first, `/api/projects/${project.id}`);
    assert.equal(stored.project.revision, project.revision);
    assert.ok(requests.every(request => !/access_key|project_key|[?&]access=/.test(request.query)));
    return { share_endpoints: 404, revision_unchanged: true };
  });

  await check('Project operations submit no calculation and raise no page error', async () => {
    assert.equal(requests.filter(request => request.method === 'POST' && /\/api\/[^/]+\/jobs$/.test(request.path)).length, 0);
    assert.ok(requests.some(request => request.method === 'GET' && request.path === '/api/projects'), 'The interface never read GET /api/projects.');
    // Console messages and failed responses are reported, not judged: a missing record type only warns.
    assert.deepEqual(diagnostics.pageErrors, []);
    return { scientific_jobs_submitted: 0, page_errors: 0, browser_version: browser.version() };
  });
} catch (error) {
  failure = { message: scrub(error.message), stack: scrub(error.stack || '') }; process.exitCode = 1;
  await page?.screenshot({ path: join(output, 'failure.png'), fullPage: true }).catch(() => {});
  await writeFile(join(output, 'failure-page.txt'), scrub(await page?.locator('body').innerText().catch(() => '') || ''), { mode: 0o600 });
} finally {
  const report = scrub({ passed: !failure, base, finished_at: new Date().toISOString(), project_id: project?.id, layout_id: layoutId,
    totals: { passed: observations.filter(item => item.pass).length, failed: observations.filter(item => !item.pass).length },
    observations, failure, diagnostics, requests,
    scope: 'Actual Chrome controls on the Python service and its workspace projects; no credentials, no simulated API responses and no scientific jobs.' });
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
  console.log(JSON.stringify({ passed: report.passed, checks: observations.length, output, failure: report.failure }));
  await browser?.close();
}
