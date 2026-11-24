/** Opt-in actual browser acceptance against an isolated, already-built server. */
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve, relative, join } from 'node:path';
import { chromium } from 'playwright';
import { createHash } from 'node:crypto';
import { translateText } from '../lib/i18n/core.ts';

const root = resolve(import.meta.dirname, '../..');
const base = process.env.EEG_TEST_URL;
assert.ok(base, 'Set EEG_TEST_URL to the isolated verification server.');
const origin = new URL(base);
assert.ok(origin.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(origin.hostname) && origin.port && origin.port !== '3000');
const includeDelivery = process.argv.includes('--with-delivery');
assert.ok(process.argv.slice(2).every(arg => arg === '--with-delivery'), 'Unknown browser QA argument.');
const output = process.env.EEG_QA_OUTPUT || join(root, 'artifacts/productization/2026-11-13', includeDelivery ? 'stage3-browser' : 'stage2-browser');
assert.ok(relative(root, output).startsWith('artifacts/'), 'Keep verification evidence inside the project artifacts directory.');
await mkdir(output, { recursive: true, mode: 0o700 });
const fixture = JSON.parse(await readFile(process.env.EEG_SIGNAL_FIXTURE || join(root, 'artifacts/performance-optimizations/2026-11-13/bank-signal-result.json'), 'utf8'));
const layoutIds = [fixture.request.record_id, '1c23da5c1dae629610c0f2a39fe7b48d8c0fba86d41c1c77276f2b90a937b0f4'];
assert.ok(layoutIds.every(id => /^[a-f0-9]{64}$/.test(id)) && layoutIds[0] !== layoutIds[1]);
const observations = [], requests = [], pageErrors = [], consoleErrors = [], httpFailures = [], requestFailures = [], blockedDependencies = [], secrets = [];
let browser, ownerContext, ownerPage, viewerContext, viewerPage, chineseContext, chinesePage, project, ownerKey, viewerKey, sourceEntry, signalHref, failure;
const t = (text, locale = 'en') => translateText(text, locale);
const decoded = value => { let text = value; for (let i = 0; i < 3; i++) { try { const next = decodeURIComponent(text); if (next === text) break; text = next; } catch { break; } } return text; };
const redact = value => secrets.reduce((text, secret) => text.replaceAll(secret, '[credential]'), value);
const scrub = value => typeof value === 'string' ? redact(value) : Array.isArray(value) ? value.map(scrub) : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, scrub(item)])) : value;

async function check(name, work) {
  const start = Date.now();
  try { const details = await work(); observations.push({ name, pass: true, seconds: (Date.now() - start) / 1000, ...details }); console.log(JSON.stringify(scrub(observations.at(-1)))); }
  catch (error) { observations.push({ name, pass: false, message: redact(error.message.slice(0, 3000)) }); throw error; }
}
async function context(locale) {
  const result = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  await result.addCookies([{ name: 'eeg-layout-language', value: locale, url: base }]);
  // A regression must never dispatch an unexpected scientific job.
  await result.route('**/api/**/jobs', route => route.request().method() === 'POST' ? route.abort('blockedbyclient') : route.continue());
  result.on('request', request => {
    const url = new URL(request.url());
    requests.push({ context: locale, method: request.method(), path: url.pathname, query: url.search });
  });
  result.on('response', response => { if (response.status() >= 400) httpFailures.push({ context: locale, path: new URL(response.url()).pathname, status: response.status() }); });
  result.on('requestfailed', request => requestFailures.push({ context: locale, path: new URL(request.url()).pathname, message: request.failure()?.errorText }));
  result.on('page', page => {
    page.setDefaultTimeout(45000);
    page.on('pageerror', error => pageErrors.push({ context: locale, message: error.message }));
    page.on('console', message => { if (message.type() === 'error') consoleErrors.push({ context: locale, message: message.text() }); });
  });
  return result;
}
const button = (page, source, locale = 'en') => page.getByRole('button', { name: t(source, locale), exact: true });
const label = (page, source, locale = 'en') => page.getByLabel(t(source, locale), { exact: true });
async function mutation(page, path, method, action) {
  const waiting = page.waitForResponse(response => new URL(response.url()).pathname === path && response.request().method() === method);
  await action(); const response = await waiting;
  assert.ok(response.ok(), `Project mutation returned ${response.status()}`);
  return response.json();
}
async function openProject(page, locale = 'en') {
  await page.goto(`${base}/projects?project=${project.id}`, { waitUntil: 'domcontentloaded' });
  await page.getByRole('heading', { name: project.title, exact: true }).waitFor();
  await page.getByRole('region', { name: t('研究任务进度', locale), exact: true }).count().catch(() => 0);
}
async function assertNoCredentialLinks(page) {
  const links = await page.locator('a[href]').evaluateAll(nodes => nodes.map(node => node.getAttribute('href')));
  assert.ok(links.every(href => secrets.every(secret => !decoded(href || '').includes(secret))), 'A project credential appeared in a navigation link.');
}
async function openDetails(page, source, locale = 'en') {
  const summary = page.locator('summary').filter({ hasText: new RegExp('^' + t(source, locale).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$') });
  const parent = summary.locator('..');
  if (!await parent.evaluate(element => element.open)) await summary.click();
  return parent;
}
async function archiveResult(page, locale = 'en') {
  const row = page.getByRole('article', { name: sourceEntry.title, exact: true });
  await button(row, '查看保存的科学数据', locale).click();
  const slider = page.getByRole('slider', { name: t('波形观察时间', locale), exact: true });
  await slider.waitFor();
  return slider;
}
function verifyDelivery(bundle) {
  const hash = value => createHash('sha256').update(value).digest('hex');
  assert.equal(bundle.schema, 'eeg-research-delivery/1'); assert.equal(bundle.project.id, project.id);
  assert.equal(bundle.project.revision, project.revision); assert.equal(bundle.scientific_results_recomputed, false);
  assert.deepEqual(bundle.project.workflow, project.workflow);
  assert.ok(bundle.host.application_version); assert.match(bundle.host.data_manifest_sha256, /^[a-f0-9]{64}$/);
  for (const file of bundle.files) {
    assert.equal(file.encoding, 'utf-8'); assert.equal(Buffer.byteLength(file.content), file.size_bytes);
    assert.equal(hash(file.content), file.sha256);
  }
  const { manifest_sha256: checksum, files, ...metadata } = bundle;
  const manifest = { ...metadata, files: files.map(({ content: _content, ...file }) => file) };
  assert.equal(hash(JSON.stringify(manifest)), checksum);
  assert.ok(secrets.every(secret => !JSON.stringify(bundle).includes(secret)), 'A credential appeared in the downloaded research package.');
  const source = bundle.records.find(record => record.kind === 'source'); assert.ok(source);
  const sourceFile = bundle.files.find(file => file.path === source.path);
  assert.deepEqual(JSON.parse(sourceFile.content).payload, fixture);
  return { files: bundle.files.length, records: bundle.records.length, manifest_sha256: checksum };
}
async function downloadDelivery(page, target, locale = 'en', readme = false) {
  const waiting = page.waitForEvent('download');
  await button(page, readme ? '下载交付说明' : '下载项目交付包', locale).click();
  const download = await waiting; await download.saveAs(join(output, target));
  return readFile(join(output, target), 'utf8');
}

try {
  browser = await chromium.launch({ headless: true,
    ...(process.env.EEG_BROWSER_EXECUTABLE ? { executablePath: process.env.EEG_BROWSER_EXECUTABLE } : {}),
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  ownerContext = await context('en'); ownerPage = await ownerContext.newPage();
  await check('Create a project through the visible form and retain its active context', async () => {
    await ownerPage.goto(`${base}/projects`, { waitUntil: 'domcontentloaded' });
    const title = `Stage 2 study ${Date.now()}`;
    await label(ownerPage, '项目名称').fill(title);
    await label(ownerPage, '负责人姓名').fill('Verification');
    const created = await mutation(ownerPage, '/api/projects', 'POST', () => button(ownerPage, '创建项目').click());
    project = created.project; ownerKey = created.access_key; secrets.push(ownerKey);
    await ownerPage.getByRole('heading', { name: title, exact: true }).waitFor();
    const active = await ownerPage.evaluate(() => JSON.parse(sessionStorage.getItem('eeg-active-project/1') || 'null'));
    assert.equal(active.project_id, project.id); assert.equal(active.role, 'owner');
    await assertNoCredentialLinks(ownerPage);
    return { project_id: project.id, noScientificJobs: true };
  });

  const savedLayouts = [];
  await check('Save two actual completed layouts through their shared header actions', async () => {
    for (const recordId of layoutIds) {
      await ownerPage.goto(`${base}/layout?id=${recordId}&ar=87`, { waitUntil: 'domcontentloaded' });
      const result = await mutation(ownerPage, `/api/projects/${project.id}/entries`, 'POST', () => button(ownerPage, '保存当前布局到项目').click());
      assert.equal(result.entry.record_id, recordId); assert.equal(result.entry.kind, 'layout');
      savedLayouts.push(result.entry); project = result.project;
      await button(ownerPage, '已保存到当前项目').waitFor();
    }
    return { saved_layout_ids: savedLayouts.map(entry => entry.record_id), project_entries: project.entries.length };
  });

  await check('Select project reference/candidate layouts without changing their scientific records', async () => {
    await openProject(ownerPage);
    await label(ownerPage, '项目参考布局').selectOption(savedLayouts[0].id);
    await label(ownerPage, '项目候选布局').selectOption(savedLayouts[1].id);
    const value = await mutation(ownerPage, `/api/projects/${project.id}`, 'PATCH', () => button(ownerPage, '保存研究任务选择').click());
    assert.equal(value.project.workflow.reference_entry_id, savedLayouts[0].id);
    assert.equal(value.project.workflow.candidate_entry_id, savedLayouts[1].id);
    project = value.project;
    await ownerPage.screenshot({ path: join(output, '01-project-workflow.png'), fullPage: true, mask: [ownerPage.locator('input[type="password"], input[readonly]')] });
    return { workflow: project.workflow, source_snapshot_hashes: project.entries.map(entry => entry.snapshot_sha256) };
  });

  await check('Save independent comparison requirements exactly from the existing comparison page', async () => {
    const q = new URLSearchParams({ a: layoutIds[0], b: layoutIds[1], ar: '87', thresholdMode: 'custom', sensitivity: '63', localization: '52', p90: '28.5' });
    await ownerPage.goto(`${base}/decision?${q}`, { waitUntil: 'domcontentloaded' });
    const value = await mutation(ownerPage, `/api/projects/${project.id}`, 'PATCH', () => button(ownerPage, '保存当前对比设置到项目').click());
    project = value.project;
    const actual = new URL(project.workflow.comparison_href, base);
    for (const [key, expected] of q) assert.equal(actual.searchParams.get(key), expected, `Comparison changed ${key}`);
    return { workflow: project.workflow };
  });

  await check('Load the real cached signal fixture and explicitly save its completed receipt to the active project', async () => {
    const request = fixture.request;
    const q = new URLSearchParams({ record: request.record_id, sourceMode: request.mode || 'multi_source', wave: request.waveform,
      seed: String(request.seed), scale: String(request.artifact_scale), ar: '87' });
    if (request.mode === 'single_source') q.set('source', String(request.source_index));
    else if (request.mode === 'cross_region') q.set('sources', request.brain_regions.join(','));
    else q.set('region', request.brain_region);
    const lookup = ownerPage.waitForResponse(response => new URL(response.url()).pathname === '/api/source-reception/lookup' && response.request().method() === 'POST');
    signalHref = `${base}/reception?${q}`;
    await ownerPage.goto(signalHref, { waitUntil: 'domcontentloaded' });
    const response = await lookup, value = await response.json();
    assert.equal(response.status(), 200); assert.equal(value.hit, true); assert.equal(value.job.status, 'completed');
    assert.deepEqual(value.job.result, fixture);
    const saved = await mutation(ownerPage, `/api/projects/${project.id}/entries`, 'POST', () => button(ownerPage, '保存信号实验到项目').click());
    sourceEntry = saved.entry; project = saved.project;
    assert.equal(sourceEntry.kind, 'source'); assert.equal(sourceEntry.record_id, value.job.key);
    return { signal_key: value.job.key, cached: true, receipt_id: value.job.id };
  });

  await check('Revisiting a saved cached signal does not submit a duplicate project attachment', async () => {
    const lookup = ownerPage.waitForResponse(response => new URL(response.url()).pathname === '/api/source-reception/lookup' && response.request().method() === 'POST');
    await ownerPage.goto(signalHref, { waitUntil: 'domcontentloaded' });
    const response = await lookup, value = await response.json();
    assert.equal(value.hit, true); assert.equal(value.job.key, sourceEntry.record_id);
    const before = requests.filter(request => request.method === 'POST' && request.path === `/api/projects/${project.id}/entries`).length;
    await button(ownerPage, '保存信号实验到项目').click();
    await button(ownerPage, '已保存到当前项目').waitFor();
    assert.equal(requests.filter(request => request.method === 'POST' && request.path === `/api/projects/${project.id}/entries`).length, before);
    const saved = await ownerContext.request.get(`${base}/api/projects/${project.id}`, { headers: { 'X-EEG-Project-Key': ownerKey } });
    assert.equal(saved.status(), 200); const data = await saved.json();
    assert.equal(data.project.revision, project.revision); assert.equal(data.project.entries.filter(entry => entry.kind === 'source').length, 1);
    return { additional_attachment_posts: 0, source_entries: 1, project_revision_unchanged: true };
  });

  await check('Replay, play and download the immutable project signal while old record/source endpoints are blocked', async () => {
    const blocked = route => { blockedDependencies.push(new URL(route.request().url()).pathname); return route.abort('blockedbyclient'); };
    await ownerPage.route('**/api/source-reception/**', blocked);
    await ownerPage.route('**/api/local-compute/library/*', blocked);
    await openProject(ownerPage);
    const slider = await archiveResult(ownerPage), initial = await slider.inputValue();
    await button(ownerPage, '播放时间标记').click();
    await ownerPage.waitForFunction(({ name, initial }) => document.querySelector(`input[aria-label="${name}"]`)?.value !== initial, { name: t('波形观察时间'), initial });
    await button(ownerPage, '暂停时间标记').click();
    const channels = ownerPage.getByLabel(t('查看电极'), { exact: false });
    assert.equal(await channels.count(), 2); await channels.nth(0).selectOption('1'); await channels.nth(1).selectOption('2');
    const downloading = ownerPage.waitForEvent('download'); await button(ownerPage, '导出本场景JSON').click();
    const downloaded = await downloading, target = join(output, 'archived-signal-result.json'); await downloaded.saveAs(target);
    assert.deepEqual(JSON.parse(await readFile(target, 'utf8')), fixture);
    assert.deepEqual(blockedDependencies, [], 'Archive replay attempted to read an old task/cache endpoint.');
    await ownerPage.screenshot({ path: join(output, '02-archived-signal.png'), fullPage: true, mask: [ownerPage.locator('input[type="password"], input[readonly]')] });
    await ownerPage.unroute('**/api/source-reception/**', blocked); await ownerPage.unroute('**/api/local-compute/library/*', blocked);
    return { independent_of_original_task: true, download_matches_full_fixture: true, selected_channels: [1, 2], original_source_requests: blockedDependencies.length };
  });

  await check('Read-only sharing survives documentation navigation without exposing owner or viewer credentials in URLs', async () => {
    await openProject(ownerPage);
    const details = await openDetails(ownerPage, '项目说明、凭据与分享');
    const shared = await mutation(ownerPage, `/api/projects/${project.id}/share`, 'POST', () => button(ownerPage, '生成新的只读链接').click());
    project = shared.project; viewerKey = shared.access_key; secrets.push(viewerKey);
    const link = await label(ownerPage, '只读分享链接').inputValue();
    assert.equal(new URLSearchParams(new URL(link).hash.slice(1)).get('access'), viewerKey);
    await details.locator('summary').first().click();
    viewerContext = await context('en'); const page = viewerPage = await viewerContext.newPage();
    await page.goto(link, { waitUntil: 'domcontentloaded' });
    await page.getByRole('heading', { name: project.title, exact: true }).waitFor();
    await page.waitForFunction(() => location.hash === '');
    assert.equal(await button(page, '保存研究任务选择').count(), 0);
    assert.equal(await button(page, '生成新的只读链接').count(), 0);
    await assertNoCredentialLinks(page);
    await page.getByRole('link', { name: t('文档'), exact: true }).click();
    await page.waitForURL(url => url.pathname === '/guide');
    await assertNoCredentialLinks(page);
    assert.ok(secrets.every(secret => !decoded(page.url()).includes(secret)), 'A project credential appeared in the documentation URL.');
    assert.ok(requests.every(request => secrets.every(secret => !decoded(request.query).includes(secret))), 'A project credential appeared in a network query.');
    return { readonly: true, credentials_in_navigation_or_queries: false };
  });

  await check('A fresh Chinese browser restores owner access and opens the saved signal without the original receipt', async () => {
    chineseContext = await context('zh-CN'); const page = chinesePage = await chineseContext.newPage();
    await page.goto(`${base}/projects`, { waitUntil: 'domcontentloaded' });
    await label(page, '项目编号', 'zh-CN').fill(project.id);
    await label(page, '项目访问凭据', 'zh-CN').fill(ownerKey);
    await button(page, '打开项目', 'zh-CN').click();
    await page.getByRole('heading', { name: project.title, exact: true }).waitFor();
    assert.equal(await page.locator('html').getAttribute('lang'), 'zh-CN');
    const slider = await archiveResult(page, 'zh-CN'); assert.ok(Number.isInteger(Number(await slider.inputValue())));
    await assertNoCredentialLinks(page);
    return { locale: 'zh-CN', independent_browser: true, archived_signal_visible: true };
  });

  if (includeDelivery) {
    let ownerDelivery;
    await check('Add an actual completed electrode edit so delivery covers all saved scientific record types', async () => {
      await openProject(ownerPage); await openDetails(ownerPage, '保存已完成结果到项目');
      const select = label(ownerPage, '选择已完成记录');
      await ownerPage.waitForFunction(name => [...document.querySelector(`select[aria-label="${name}"]`).options].some(option => option.value.startsWith('editor:')), t('选择已完成记录'));
      const value = await select.locator('option').evaluateAll(options => options.find(option => option.value.startsWith('editor:'))?.value);
      assert.ok(value); await select.selectOption(value);
      const saved = await mutation(ownerPage, `/api/projects/${project.id}/entries`, 'POST', () => button(ownerPage, '保存到项目').click());
      project = saved.project; assert.equal(saved.entry.kind, 'editor');
      return { editor_record_id: saved.entry.record_id, record_count: project.entries.length };
    });

    await check('Owner downloads the real delivery package with valid manifest and unchanged raw snapshots', async () => {
      await openProject(ownerPage);
      ownerDelivery = JSON.parse(await downloadDelivery(ownerPage, 'owner-research-delivery.json'));
      const checked = verifyDelivery(ownerDelivery);
      assert.deepEqual([...new Set(ownerDelivery.records.map(record => record.kind))].sort((a, b) => a.localeCompare(b)), ['editor', 'layout', 'source']);
      for (const record of ownerDelivery.records) {
        const response = await ownerContext.request.get(`${base}/api/projects/${project.id}/entries/${record.id}`, { headers: { 'X-EEG-Project-Key': ownerKey } });
        assert.equal(response.status(), 200); const saved = await response.json();
        const file = ownerDelivery.files.find(file => file.path === record.path);
        assert.equal(file.content, JSON.stringify(saved.snapshot));
      }
      await ownerPage.locator('#project-delivery').screenshot({ path: join(output, '03-delivery-package.png') });
      return { ...checked, all_raw_snapshot_strings_identical: true, full_signal_payload_matches_fixture: true };
    });

    await check('Delivery notes reuse the same verified package and preserve their original UTF-8 text', async () => {
      const before = requests.filter(request => request.path === `/api/projects/${project.id}/export`).length;
      const readme = await downloadDelivery(ownerPage, 'README.md', 'en', true);
      assert.equal(readme, ownerDelivery.files.find(file => file.path === 'README.md').content);
      assert.equal(requests.filter(request => request.path === `/api/projects/${project.id}/export`).length, before);
      return { shared_download_cache: true, readme_bytes: Buffer.byteLength(readme) };
    });

    await check('A read-only collaborator can download the same scientific copies without credentials in the package', async () => {
      await viewerPage.goto(`${base}/projects?project=${project.id}`, { waitUntil: 'domcontentloaded' });
      await viewerPage.getByRole('heading', { name: project.title, exact: true }).waitFor();
      const viewerDelivery = JSON.parse(await downloadDelivery(viewerPage, 'viewer-research-delivery.json'));
      const checked = verifyDelivery(viewerDelivery);
      for (const file of ownerDelivery.files.filter(file => file.path.startsWith('records/')))
        assert.equal(viewerDelivery.files.find(candidate => candidate.path === file.path).content, file.content);
      await assertNoCredentialLinks(viewerPage);
      return { ...checked, read_only_export_allowed: true, same_scientific_bytes: true };
    });

    await check('The Chinese project page downloads an equivalent delivery package', async () => {
      await openProject(chinesePage, 'zh-CN');
      const chineseDelivery = JSON.parse(await downloadDelivery(chinesePage, 'zh-research-delivery.json', 'zh-CN'));
      const checked = verifyDelivery(chineseDelivery);
      for (const file of ownerDelivery.files.filter(file => file.path.startsWith('records/')))
        assert.equal(chineseDelivery.files.find(candidate => candidate.path === file.path).content, file.content);
      return { ...checked, locale: 'zh-CN', same_scientific_bytes: true };
    });

    await check('Cancel and changing the active project abort pending delivery reads without a late download or error', async () => {
      let downloads = 0; const countDownload = () => { downloads++; }; ownerPage.on('download', countDownload);
      const path = `/api/projects/${project.id}/export`;
      // Observe the actual signal passed to fetch. Forward every real request
      // unchanged; a held protocol interception delays requestfailed events.
      await ownerPage.addInitScript(({ path }) => {
        const original = window.fetch.bind(window); window.__deliveryFetchSignals = [];
        window.fetch = (input, options) => {
          const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
          if (new URL(url, location.href).pathname === path) {
            const signal = options?.signal ?? (input instanceof Request ? input.signal : null);
            const observed = { aborted: signal?.aborted ?? false }; window.__deliveryFetchSignals.push(observed);
            signal?.addEventListener('abort', () => { observed.aborted = true; }, { once: true });
          }
          return original(input, options);
        };
      }, { path });
      for (const action of ['cancel', 'switch-project']) {
        await openProject(ownerPage);
        let announce, release;
        const held = new Promise(resolve => { announce = resolve; }), gate = new Promise(resolve => { release = resolve; });
        const handler = async route => { announce(); await gate; await route.abort('aborted').catch(() => {}); };
        await ownerPage.route(`${base}${path}`, handler);
        try {
          await button(ownerPage, '下载项目交付包').click(); await held;
          if (action === 'cancel') await button(ownerPage, '取消下载准备').click();
          else {
            await openDetails(ownerPage, '新建、恢复或切换项目');
            const form = ownerPage.getByRole('heading', { name: t('新建项目'), exact: true }).locator('..');
            await label(form, '项目名称').fill(`Abort cleanup study ${Date.now()}`);
            await label(form, '负责人姓名').fill('Verification');
            const changed = await mutation(ownerPage, '/api/projects', 'POST', () => button(form, '创建项目').click());
            secrets.push(changed.access_key);
          }
          await ownerPage.waitForFunction(() => window.__deliveryFetchSignals?.at(-1)?.aborted === true, null, { timeout: 10000, polling: 50 });
          if (action === 'cancel') assert.equal(await ownerPage.locator('#project-delivery [role="alert"]').count(), 0);
        } finally { release(); await ownerPage.unroute(`${base}${path}`, handler); }
      }
      ownerPage.off('download', countDownload); assert.equal(downloads, 0);
      return { explicit_cancel_and_project_change_abort: true, actual_fetch_signal_observed: true, late_downloads: 0, synthetic_http_payloads: false };
    });
  }

  await check('No new scientific jobs or unexpected browser/network errors', async () => {
    assert.equal(requests.filter(request => request.method === 'POST' && /\/api\/[^/]+\/jobs$/.test(request.path)).length, 0);
    assert.deepEqual(pageErrors, []); assert.deepEqual(httpFailures, []); assert.deepEqual(consoleErrors, []);
    assert.deepEqual(requestFailures.filter(error => !error.message?.includes('ERR_ABORTED')), []);
    assert.ok(requests.every(request => secrets.every(secret => !decoded(request.query).includes(secret))));
    return { no_scientific_jobs: true, page_errors: 0, http_errors: 0, browser_version: browser.version() };
  });
} catch (error) {
  failure = { message: redact(error.message.slice(0, 3000)), stack: redact(error.stack?.slice(0, 5000) || '') };
  process.exitCode = 1;
  await ownerPage?.screenshot({ path: join(output, 'failure.png'), fullPage: true, mask: [ownerPage.locator('input[type="password"], input[readonly]')] }).catch(() => {});
  await writeFile(join(output, 'failure-page.txt'), redact(await ownerPage?.locator('body').innerText().catch(() => '') || ''), { mode: 0o600 });
} finally {
  const report = scrub({ finished_at: new Date().toISOString(), base, includeDelivery, totals: { passed: observations.filter(item => item.pass).length, failed: observations.filter(item => !item.pass).length },
    observations, failure, diagnostics: { pageErrors, consoleErrors, httpFailures, requestFailures, blockedDependencies }, requests,
    scope: 'Actual Chrome UI and isolated production APIs. Cached lookup only; project metadata writes do not submit scientific jobs. No fabricated API responses.' });
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
  console.log(JSON.stringify(report, null, 2));
  await browser?.close();
}
