import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { translateText } from '../../lib/i18n/core.ts';
import { DELIVERY_INPUT_LIMIT } from '../../features/projects/research-delivery-reader.ts';
import { assertCacheOnly } from './service-session.mjs';

const digest = bytes => createHash('sha256').update(bytes).digest('hex');
/**
 * Stage 3: the older delivery below the root, the cached signal result EEG_SIGNAL_FIXTURE (default the root's bank
 * signal result), the other completed layout EEG_SECOND_LAYOUT_ID (default the installation's 1c23da5c...) and the
 * completed electrode edit EEG_EDITOR_RECORD_KEY (default the installation's 18fa179e...). The current delivery is
 * prepared in a workspace project, which needs no credential.
 */
export async function runLocalDeliveryChecks({ root, output, base, check, newContext, read, button, screenshot, requests, keepSecret, setPage }) {
  const oldPath = join(root, 'artifacts/productization/2026-11-13/stage4-browser/owner-research-delivery.json');
  const oldBytes = await readFile(oldPath), oldBundle = JSON.parse(oldBytes.toString('utf8'));
  const sourceFixture = JSON.parse(await readFile(process.env.EEG_SIGNAL_FIXTURE || join(root, 'artifacts/performance-optimizations/2026-11-13/bank-signal-result.json'), 'utf8'));
  const golden = JSON.parse(await readFile(join(root, 'artifacts/productization/2026-11-13/scientific-baseline/design-request.json'), 'utf8'));
  const setup = await newContext('en');
  const editorKey = process.env.EEG_EDITOR_RECORD_KEY || '18fa179ed208203da9ae07f013a4e81c69f635889a4ee1436f0fc12409fadc06';
  const otherId = process.env.EEG_SECOND_LAYOUT_ID || '1c23da5c1dae629610c0f2a39fe7b48d8c0fba86d41c1c77276f2b90a937b0f4';
  let page = await setup.context.newPage(); setPage(page);
  let project, currentBytes, currentBundle;
  const t = (text, locale = 'en') => translateText(text, locale);
  const escape = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  async function server(path, method = 'GET', body) {
    assert.ok(!/\/jobs(?:\/|$)/.test(path), 'Fixture preparation cannot submit scientific jobs.');
    const headers = { Origin: base };
    if (method !== 'GET') {
      const health = await read(setup.context, '/api/local-compute/health');
      assertCacheOnly(health); keepSecret(health.token); headers['X-EEG-Compute-Token'] = health.token;
    }
    requests.push({ locale: 'fixture', transport: 'real-delivery-preparation', method, path, query: '' });
    const response = await setup.context.request.fetch(base + path, { method, headers, ...(body ? { data: body } : {}) });
    assert.ok(response.ok(), `Actual delivery fixture ${method} ${path}: ${response.status()}`);
    return response;
  }
  function verifyBundle(bundle) {
    assert.equal(bundle.schema, 'eeg-research-delivery/1'); assert.equal(bundle.scientific_results_recomputed, false);
    for (const file of bundle.files) { assert.equal(Buffer.byteLength(file.content), file.size_bytes); assert.equal(digest(file.content), file.sha256); }
    const { manifest_sha256, files, ...metadata } = bundle;
    assert.equal(digest(JSON.stringify({ ...metadata, files: files.map(({ content: _content, ...file }) => file) })), manifest_sha256);
  }
  async function freshReader(locale) {
    const created = await newContext(locale); created.state.localReader = true;
    page = await created.context.newPage(); setPage(page);
    await page.goto(base + '/deliveries', { waitUntil: 'networkidle' });
    await page.getByRole('heading', { level: 1, name: t('打开本地交付包', locale), exact: true }).waitFor();
    return created.context;
  }
  // The file picker's button and chosen name follow the label text in the input's accessible name.
  const input = (locale = 'en') => page.getByLabel(new RegExp('^' + escape(t('项目交付包 JSON', locale))));
  const verified = (locale = 'en') => page.getByRole('region', { name: t('已校验的交付项目', locale), exact: true });
  async function upload(bytes, name, bundle, locale = 'en') {
    await input(locale).setInputFiles({ name, mimeType: 'application/json', buffer: bytes });
    await verified(locale).getByRole('heading', { name: bundle.project.title, exact: true }).waitFor();
  }
  async function selected(entry, locale = 'en') {
    await page.getByRole('combobox', { name: new RegExp('^' + escape(t('选择交付记录', locale))) }).selectOption(entry.id);
    const row = page.locator(`article[data-delivery-entry-id="${entry.id}"]`); await row.waitFor(); return row;
  }
  async function openDetails(scope, source, locale = 'en', prefix = false) {
    const summary = scope.locator('summary').filter({ hasText: new RegExp('^' + escape(t(source, locale)) + (prefix ? '(?:\\s*·|$)' : '$')) });
    await summary.waitFor(); if (!await summary.locator('..').evaluate(element => element.open)) await summary.click(); return summary.locator('..');
  }
  async function downloaded(source, name, locale = 'en') {
    const waiting = page.waitForEvent('download'); await button(page, source, locale).click();
    const file = join(output, name); await (await waiting).saveAs(file); return readFile(file);
  }
  async function noPersistence(context, localePreference = false) {
    const storage = await context.pages().at(-1).evaluate(() => ({ local: Object.entries(localStorage), session: Object.entries(sessionStorage) }));
    assert.deepEqual(storage.session, []);
    assert.ok(storage.local.every(([key]) => localePreference && key === 'eeg-layout-language'), 'A package or credential was stored in browser storage.');
  }

  await check('Prepare a current real delivery from exact caches and verify the original older delivery independently', async () => {
    verifyBundle(oldBundle);
    const source = await (await server('/api/source-reception/lookup', 'POST', sourceFixture.request)).json();
    assert.equal(source.hit, true); assert.equal(source.job.status, 'completed'); assert.deepEqual(source.job.result, sourceFixture);
    const names = Array.from({ length: 64 }, (_, i) => `Delivery-Channel-${i + 1}`);
    const named = await (await server('/api/design-evaluation/lookup', 'POST', { schema: 'design-submission/1', request: golden, electrode_names: names })).json();
    assert.equal(named.hit, true); assert.equal(named.job.cached, true); assert.match(named.job.annotation_id, /^[a-f0-9]{64}$/);
    const editorRecords = await read(setup.context, '/api/electrode-editor/records');
    assert.ok(editorRecords.records.some(record => record.key === editorKey), 'Prepare the actual completed editor cache before read-only delivery QA.');
    const created = await (await server('/api/projects', 'POST', { title: 'Local delivery acceptance ' + Date.now(), owner_name: 'Browser verification', notes: 'Read as plain text: <img src="/api/local-file-probe" onerror="window.__unsafeDeliveryNote=true">' })).json();
    // The service may still answer with an unused key; it must not reach the delivery.
    const unusedKey = typeof created.access_key === 'string' && created.access_key ? created.access_key : null;
    if (unusedKey) keepSecret(unusedKey);
    project = created.project;
    const added = [];
    for (const attachment of [{ kind: 'layout', record_id: sourceFixture.request.record_id }, { kind: 'layout', record_id: otherId }, { kind: 'layout', record_id: named.job.key, annotation_id: named.job.annotation_id }, { kind: 'source', receipt_id: source.job.id }, { kind: 'editor', record_id: editorKey }]) {
      const result = await (await server(`/api/projects/${project.id}/entries`, 'POST', { revision: project.revision, ...attachment })).json(); project = result.project; added.push(result.entry);
    }
    const href = `/decision?a=${added[0].record_id}&b=${added[1].record_id}&ar=87&thresholdMode=custom&sensitivity=63&localization=52&p90=28.5`;
    project = (await (await server(`/api/projects/${project.id}`, 'PATCH', { revision: project.revision, workflow: { reference_entry_id: added[0].id, candidate_entry_id: added[1].id, comparison_href: href } })).json()).project;
    currentBytes = await (await server(`/api/projects/${project.id}/export`)).body(); currentBundle = JSON.parse(currentBytes.toString('utf8')); verifyBundle(currentBundle);
    assert.equal(currentBundle.project.id, project.id); assert.ok(!unusedKey || !currentBytes.includes(Buffer.from(unusedKey))); assert.equal(currentBundle.records.length, 5);
    await writeFile(join(output, 'actual-current-delivery.json'), currentBytes, { mode: 0o600 });
    return { old_project_id: oldBundle.project.id, current_project_id: project.id, current_records: 5, actual_editor_key: editorKey, original_source_payload_unchanged: true, scientific_jobs_submitted: 0 };
  });
  await check('The project workspace exposes the local delivery reader', async () => {
    await page.goto(base + '/projects', { waitUntil: 'networkidle' });
    await page.getByRole('link', { name: t('打开本地交付包'), exact: true }).click();
    await page.waitForURL(url => url.pathname === '/deliveries'); await page.waitForLoadState('networkidle');
    await page.getByRole('heading', { level: 1, name: t('打开本地交付包'), exact: true }).waitFor();
    return { visible_projects_entry: true };
  });
  const english = await freshReader('en');
  await check('A fresh API-blocked English reader opens the older package and downloads its exact original bytes and readme', async () => {
    await upload(oldBytes, 'older-actual-delivery.json', oldBundle);
    assert.deepEqual(await downloaded('下载原始交付包', 'older-original-downloaded.json'), oldBytes);
    assert.deepEqual(await downloaded('下载交付说明', 'older-README-downloaded.md'), Buffer.from(oldBundle.files.find(file => file.path === 'README.md').content));
    await noPersistence(english); return { original_package_sha256: digest(oldBytes), api_access_required: false };
  });
  for (const kind of ['layout', 'editor', 'source']) await check(`Read the older ${kind} snapshot and download its exact scientific text with original APIs blocked`, async () => {
    const entry = oldBundle.records.find(row => row.kind === kind); assert.ok(entry, 'The older real delivery must cover layout, edited and source records.');
    const row = await selected(entry), file = oldBundle.files.find(file => file.path === entry.path);
    if (kind !== 'source') {
      const details = await openDetails(row, '查看已保存坐标', 'en', true); assert.ok(await details.locator('tbody tr').count() > 0);
    } else {
      const slider = row.getByRole('slider', { name: t('波形观察时间'), exact: true }); await slider.waitFor();
      const before = await slider.inputValue(); await button(row, '播放时间标记', 'en').click();
      await page.waitForFunction(({ id, label, value }) => [...document.querySelectorAll(`article[data-delivery-entry-id="${id}"] input[type=range]`)].some(node => node.getAttribute('aria-label') === label && node.value !== value), { id: entry.id, label: t('波形观察时间'), value: before });
      await button(row, '暂停时间标记', 'en').click();
      const scene = JSON.parse(await downloaded('导出本场景JSON', 'older-scene-downloaded.json'));
      assert.deepEqual(scene, JSON.parse(file.content).payload);
    }
    const bytes = await downloaded('下载此记录的原始快照', `older-${kind}-snapshot-downloaded.json`);
    assert.deepEqual(bytes, Buffer.from(file.content)); assert.equal(digest(bytes), file.sha256);
    await screenshot(page, `en-older-${kind}-view.png`); await noPersistence(english);
    return { kind, snapshot_sha256: digest(bytes), scientific_text_unchanged: true };
  });
  await check('A fresh Chinese reader opens the current package, preserves names and renders notes as plain text', async () => {
    const chinese = await freshReader('zh-CN'); await upload(currentBytes, 'current-actual-delivery.json', currentBundle, 'zh-CN');
    assert.equal(await page.locator('img[src="/api/local-file-probe"]').count(), 0); assert.equal(await page.evaluate(() => window.__unsafeDeliveryNote), undefined);
    await verified('zh-CN').getByText(currentBundle.project.notes, { exact: true }).waitFor();
    const named = currentBundle.records.find(record => record.annotation_id); assert.ok(named); const row = await selected(named, 'zh-CN');
    const details = await openDetails(row, '查看已保存坐标', 'zh-CN', true), snapshot = JSON.parse(currentBundle.files.find(file => file.path === named.path).content);
    assert.deepEqual(await details.locator('tbody td:first-child').allTextContents(), snapshot.electrode_annotation.electrode_names);
    assert.deepEqual(await downloaded('下载原始交付包', 'current-original-downloaded.json', 'zh-CN'), currentBytes);
    await noPersistence(chinese); await screenshot(page, 'zh-current-named-layout.png');
    const editor = currentBundle.records.find(record => record.kind === 'editor' && record.record_id === editorKey); assert.ok(editor);
    const editorRow = await selected(editor, 'zh-CN'), coordinates = await openDetails(editorRow, '查看已保存坐标', 'zh-CN', true);
    const editorFile = currentBundle.files.find(file => file.path === editor.path), editorSnapshot = JSON.parse(editorFile.content);
    assert.equal(editorSnapshot.payload.cache.key, editorKey); assert.equal(editorSnapshot.payload.cache.result.status, 'completed');
    assert.equal(await coordinates.locator('tbody tr').count(), editorSnapshot.payload.cache.result.electrode_count);
    const editorBytes = await downloaded('下载此记录的原始快照', 'current-actual-editor-snapshot-downloaded.json', 'zh-CN');
    assert.deepEqual(editorBytes, Buffer.from(editorFile.content)); assert.equal(digest(editorBytes), editorFile.sha256);
    await screenshot(page, 'zh-current-actual-editor.png'); await noPersistence(chinese);
    return { names_preserved: true, notes_escaped: true, actual_editor_key: editorKey, actual_editor_snapshot_sha256: digest(editorBytes), original_package_sha256: digest(currentBytes) };
  });
  await check('Damaged and oversized local packages are rejected without retaining the previously open project', async () => {
    const damaged = structuredClone(currentBundle); damaged.files[0].content += '\nchanged';
    await input('zh-CN').setInputFiles({ name: 'damaged.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(damaged)) });
    await page.getByRole('alert').waitFor(); assert.equal(await verified('zh-CN').count(), 0);
    await input('zh-CN').setInputFiles({ name: 'oversized.json', mimeType: 'application/json', buffer: Buffer.alloc(DELIVERY_INPUT_LIMIT + 1, 32) });
    await page.getByRole('alert').filter({ hasText: t('交付包超过大小上限', 'zh-CN') }).waitFor(); assert.equal(await verified('zh-CN').count(), 0);
    return { corrupted_file_rejected: true, oversized_file_rejected: true };
  });
  await check('Cancel and rapid reselection cannot display an older File.text result', async () => {
    await page.evaluate(() => {
      // oxlint-disable-next-line typescript/unbound-method -- call the preserved native method with its original File receiver
      const original = File.prototype.text; window.__deliveryNativeText = original;
      File.prototype.text = async function () {
        if (this.name.startsWith('slow-')) { await new Promise(resolve => { window.__releaseDeliveryRead = resolve; }); const value = await original.call(this); window.__slowDeliveryReadFinished = true; return value; }
        return original.call(this);
      };
    });
    try {
      await input('zh-CN').setInputFiles({ name: 'slow-cancel.json', mimeType: 'application/json', buffer: oldBytes });
      await button(page, '取消读取', 'zh-CN').click(); await page.evaluate(() => window.__releaseDeliveryRead());
      await page.waitForFunction(() => window.__slowDeliveryReadFinished === true); assert.equal(await verified('zh-CN').count(), 0);
      await page.evaluate(() => { window.__slowDeliveryReadFinished = false; });
      await input('zh-CN').setInputFiles({ name: 'slow-old.json', mimeType: 'application/json', buffer: oldBytes });
      await button(page, '取消读取', 'zh-CN').waitFor();
      await upload(currentBytes, 'current-after-reselect.json', currentBundle, 'zh-CN');
      await page.evaluate(() => window.__releaseDeliveryRead()); await page.waitForFunction(() => window.__slowDeliveryReadFinished === true);
      await verified('zh-CN').getByRole('heading', { name: currentBundle.project.title, exact: true }).waitFor();
      assert.equal(await page.getByRole('heading', { name: oldBundle.project.title, exact: true }).count(), 0);
    } finally { await page.evaluate(() => { File.prototype.text = window.__deliveryNativeText; delete window.__deliveryNativeText; delete window.__releaseDeliveryRead; delete window.__slowDeliveryReadFinished; }); }
    return { actual_file_text_used: true, scheduling_only_delayed: true, stale_results_ignored: true };
  });
  return { old_project_id: oldBundle.project.id, current_project_id: currentBundle.project.id, old_manifest_sha256: oldBundle.manifest_sha256, current_manifest_sha256: currentBundle.manifest_sha256 };
}
