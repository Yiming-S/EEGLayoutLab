/** Actual project controls on an isolated verification host; no scientific jobs. */
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { chmod, mkdir, readFile, writeFile } from 'node:fs/promises';
import { isAbsolute, join, relative, resolve } from 'node:path';
import { translateText } from '../lib/i18n/core.ts';

const projectRoot = resolve(import.meta.dirname, '../..');
const base = new URL(process.env.EEG_TEST_URL || 'http://127.0.0.1:4394');
assert.ok(base.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(base.hostname) && base.port && base.port !== '3000');
const output = process.env.EEG_QA_OUTPUT || join(projectRoot, 'artifacts/productization/2026-11-13/stage1-browser');
assert.ok(isAbsolute(output) && relative(projectRoot, output).startsWith('artifacts/'));
await mkdir(output, { recursive: true, mode: 0o700 });
const observations = [], errors = [], requests = [];
let browser, page, failure;
const t = source => translateText(source, 'en');
const button = (page, source) => page.getByRole('button', { name: t(source), exact: true });
async function openDetails(page, source) {
  const summary = page.locator('summary').filter({ hasText: new RegExp('^' + t(source).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$') });
  if (!await summary.locator('..').evaluate(element => element.open)) await summary.click();
}
async function check(name, work) {
  const details = await work(); observations.push({ name, pass: true, ...details }); console.log(JSON.stringify(observations.at(-1)));
}
async function context() {
  const value = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  await value.addCookies([{ name: 'eeg-layout-language', value: 'en', url: base.origin }]);
  value.on('page', page => {
    page.setDefaultTimeout(30000);
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => requests.push({ method: request.method(), path: new URL(request.url()).pathname, query: new URL(request.url()).search }));
  });
  return value;
}
try {
  browser = await chromium.launch({ headless: true, executablePath: process.env.EEG_BROWSER_EXECUTABLE || undefined,
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const ownerContext = await context(); page = await ownerContext.newPage();
  await page.goto(base.origin + '/projects', { waitUntil: 'networkidle' });
  let access, savedProject, snapshotBefore;
  await check('Create a private named project through the English interface', async () => {
    await page.getByLabel(t('项目名称'), { exact: true }).fill('Product acceptance study');
    await page.getByLabel(t('负责人姓名'), { exact: true }).fill('Local QA');
    const created = page.waitForResponse(response => new URL(response.url()).pathname === '/api/projects' && response.request().method() === 'POST');
    await button(page, '创建项目').click();
    const response = await created; assert.equal(response.status(), 201);
    const data = await response.json(); access = { project_id: data.project.id, access_key: data.access_key }; savedProject = data.project;
    await page.getByRole('heading', { name: savedProject.title, exact: true }).waitFor();
    assert.ok(!page.url().includes(access.access_key));
    return { project_id: savedProject.id };
  });
  const recordId = '4ba9cad24899bfcc7c712be42529b2aac732aa05f0b47e4a3744ef14b0689dd4';
  await check('Save a completed layout without submitting a calculation', async () => {
    await openDetails(page, '保存已完成结果到项目');
    const choice = page.getByLabel(t('选择已完成记录'), { exact: true });
    await choice.locator(`option[value="layout:${recordId}"]`).waitFor({ state: 'attached' });
    await choice.selectOption(`layout:${recordId}`);
    await page.getByLabel(t('实验名称'), { exact: true }).fill('Reference layout');
    const saved = page.waitForResponse(response => new URL(response.url()).pathname === `/api/projects/${savedProject.id}/entries` && response.request().method() === 'POST');
    await button(page, '保存到项目').click();
    const response = await saved; assert.equal(response.status(), 201);
    savedProject = (await response.json()).project;
    assert.equal(savedProject.entries.length, 1); assert.equal(savedProject.entries[0].record_id, recordId);
    return { record_id: recordId, entries: savedProject.entries.length };
  });
  await check('Project renaming preserves the exact saved scientific snapshot', async () => {
    const entry = savedProject.entries[0], headers = { 'X-EEG-Project-Key': access.access_key };
    snapshotBefore = await (await ownerContext.request.get(`${base.origin}/api/projects/${savedProject.id}/entries/${entry.id}`, { headers })).json();
    const details = page.locator(`section[aria-label="${t('项目详情')}"]`);
    await openDetails(page, '项目说明、凭据与分享');
    await details.getByLabel(t('项目名称'), { exact: true }).fill('Renamed research study');
    await details.getByLabel(t('项目备注'), { exact: true }).fill('选择理由：保持原始坐标与科学结果。');
    const saved = page.waitForResponse(response => new URL(response.url()).pathname === `/api/projects/${savedProject.id}` && response.request().method() === 'PATCH');
    await button(page, '保存项目说明').click(); assert.equal((await saved).status(), 200);
    await page.getByRole('heading', { name: 'Renamed research study', exact: true }).waitFor();
    const after = await (await ownerContext.request.get(`${base.origin}/api/projects/${savedProject.id}/entries/${entry.id}`, { headers })).json();
    assert.deepEqual(after.snapshot, snapshotBefore.snapshot);
    const downloading = page.waitForEvent('download'); await button(page, '下载项目凭据').click();
    const path = join(output, 'private-project-access.json'); await (await downloading).saveAs(path); await chmod(path, 0o600);
    const file = JSON.parse(await readFile(path, 'utf8')); assert.equal(file.project_id, access.project_id); assert.ok(file.access_key === access.access_key, 'Downloaded access credential differs.');
    return { snapshot_sha256: entry.snapshot_sha256, access_file_mode: '0600' };
  });
  await check('A fresh browser restores the project from its access file', async () => {
    const restoredContext = await context(), restored = await restoredContext.newPage();
    await restored.goto(base.origin + '/projects', { waitUntil: 'networkidle' });
    await restored.locator('input[type=file]').setInputFiles(join(output, 'private-project-access.json'));
    await restored.getByRole('heading', { name: 'Renamed research study', exact: true }).waitFor();
    await openDetails(restored, '项目说明、凭据与分享');
    assert.equal(await button(restored, '保存项目说明').count(), 1);
    await restored.screenshot({ path: join(output, 'restored-project.png'), fullPage: true });
    await restoredContext.close();
    return { restored_in_independent_browser_context: true };
  });
  let share;
  await check('Read-only sharing restores access without revealing an owner credential', async () => {
    await openDetails(page, '项目说明、凭据与分享');
    await page.getByText(t('新链接生成后，之前的只读链接将失效。查看项目和下载文件不会更换链接。'), { exact: true }).waitFor();
    assert.equal(await button(page, '生成新的只读链接').getAttribute('aria-describedby'), 'project-share-replacement');
    const sharing = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/share') && response.request().method() === 'POST');
    await button(page, '生成新的只读链接').click(); assert.equal((await sharing).status(), 200);
    share = await page.getByLabel(t('只读分享链接'), { exact: true }).inputValue();
    assert.ok(!share.includes(access.access_key));
    const viewerContext = await context(), viewer = await viewerContext.newPage();
    await viewer.goto(share, { waitUntil: 'networkidle' });
    await viewer.getByRole('heading', { name: 'Renamed research study', exact: true }).waitFor();
    assert.equal(new URL(viewer.url()).hash, '');
    await openDetails(viewer, '项目说明、凭据与分享');
    assert.equal(await button(viewer, '保存项目说明').count(), 0);
    assert.equal(await viewer.getByRole('button', { name: t('保存到项目'), exact: true, includeHidden: true }).count(), 0);
    await viewer.screenshot({ path: join(output, 'readonly-project.png'), fullPage: true });
    await viewerContext.close();
    return { readonly_controls: true, fragment_cleared: true };
  });
  await check('Explicitly generating a new link invalidates the previous link without changing scientific snapshots', async () => {
    const previousKey = new URLSearchParams(new URL(share).hash.slice(1)).get('access');
    await openDetails(page, '项目说明、凭据与分享');
    const replacement = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/share') && response.request().method() === 'POST');
    await button(page, '生成新的只读链接').click(); assert.equal((await replacement).status(), 200);
    share = await page.getByLabel(t('只读分享链接'), { exact: true }).inputValue();
    const currentKey = new URLSearchParams(new URL(share).hash.slice(1)).get('access');
    assert.notEqual(currentKey, previousKey);
    const oldRead = await ownerContext.request.get(`${base.origin}/api/projects/${savedProject.id}`, { headers: { 'X-EEG-Project-Key': previousKey } });
    assert.equal(oldRead.status(), 403);
    const currentRead = await ownerContext.request.get(`${base.origin}/api/projects/${savedProject.id}`, { headers: { 'X-EEG-Project-Key': currentKey } });
    assert.equal(currentRead.status(), 200);
    const snapshot = await (await ownerContext.request.get(`${base.origin}/api/projects/${savedProject.id}/entries/${savedProject.entries[0].id}`, { headers: { 'X-EEG-Project-Key': access.access_key } })).json();
    assert.deepEqual(snapshot.snapshot, snapshotBefore.snapshot);
    return { old_link_status: 403, new_link_status: 200, scientific_snapshot_unchanged: true };
  });
  await check('Revoking a share denies its credential while preserving the owner and science', async () => {
    await openDetails(page, '项目说明、凭据与分享');
    const revoked = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/revoke-share') && response.request().method() === 'POST');
    await button(page, '撤销只读分享').click(); assert.equal((await revoked).status(), 200);
    const viewerKey = new URLSearchParams(new URL(share).hash.slice(1)).get('access');
    const response = await ownerContext.request.get(`${base.origin}/api/projects/${savedProject.id}`, { headers: { 'X-EEG-Project-Key': viewerKey } });
    assert.equal(response.status(), 403);
    const snapshot = await (await ownerContext.request.get(`${base.origin}/api/projects/${savedProject.id}/entries/${savedProject.entries[0].id}`, { headers: { 'X-EEG-Project-Key': access.access_key } })).json();
    assert.deepEqual(snapshot.snapshot, snapshotBefore.snapshot);
    return { revoked_status: response.status() };
  });
  await check('Project operations produce no scientific submissions, URL credentials or page errors', async () => {
    assert.deepEqual(errors, []);
    assert.equal(requests.filter(request => request.method === 'POST' && request.path.endsWith('/jobs')).length, 0);
    assert.ok(requests.every(request => !request.query.includes(access.access_key) && !/access_key|project_key/.test(request.query)));
    return { scientific_jobs_submitted: 0, page_errors: 0 };
  });
} catch (error) {
  failure = { message: error.message, stack: error.stack }; process.exitCode = 1;
  await page?.screenshot({ path: join(output, 'failure.png'), fullPage: true, mask: [page.locator('input[type=password], input[readonly]')] }).catch(() => {});
  await writeFile(join(output, 'failure-page.txt'), await page?.locator('body').innerText().catch(() => '') || '');
}
finally {
  const report = { passed: !failure, observations, failure, errors, requests, scope: 'Actual browser controls and isolated service; no simulated API responses or new scientific jobs.' };
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ passed: report.passed, checks: observations.length, failure }));
  await browser?.close();
}
