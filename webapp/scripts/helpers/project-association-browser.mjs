import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { translateText } from '../../lib/i18n/core.ts';
import { assertCacheOnly } from './service-session.mjs';

/**
 * Stage 2 shares the runner's real Chrome, safety routing and diagnostic report. The cached signal result is
 * EEG_SIGNAL_FIXTURE (default the root's bank signal result) and the other completed layout EEG_SECOND_LAYOUT_ID
 * (default the installation's 1c23da5c...). A workspace project needs no credential: every browser of the session opens
 * it by its identifier.
 */
export async function runProjectAssociationChecks({ root, base, check, newContext, read, button, screenshot, requests, keepSecret, setPage }) {
  const fixture = JSON.parse(await readFile(process.env.EEG_SIGNAL_FIXTURE || join(root, 'artifacts/performance-optimizations/2026-11-13/bank-signal-result.json'), 'utf8'));
  const golden = JSON.parse(await readFile(process.env.EEG_GOLDEN_REQUEST || join(root, 'artifacts/productization/2026-11-13/scientific-baseline/design-request.json'), 'utf8'));
  const english = await newContext('en'), { context, state } = english;
  let page = await context.newPage(); setPage(page);
  let project, signalReceipt, aliases, referenceEntry, candidateEntry, aliasEntries, signalEntry;
  const t = (value, locale = 'en') => translateText(value, locale);
  const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const sourceId = fixture.request.record_id, otherId = process.env.EEG_SECOND_LAYOUT_ID || '1c23da5c1dae629610c0f2a39fe7b48d8c0fba86d41c1c77276f2b90a937b0f4';
  const snapshots = new Map(), originalRecords = new Map();
  async function lookup(path, body) {
    assert.ok(['/api/source-reception/lookup', '/api/design-evaluation/lookup'].includes(path));
    const health = await read(context, '/api/local-compute/health');
    assertCacheOnly(health); keepSecret(health.token);
    requests.push({ locale: 'en', transport: 'real-fixture-lookup', method: 'POST', path, query: '' });
    const response = await context.request.post(base + path, { headers: { Origin: base, 'X-EEG-Compute-Token': health.token }, data: body });
    assert.equal(response.status(), 200); const value = await response.json();
    assert.equal(value.hit, true, 'Prepare the exact cached fixture; this test cannot submit a scientific job.');
    assert.equal(value.job.status, 'completed'); assert.equal(value.job.cached, true);
    return value.job;
  }
  async function transition(marker, work, targetState = state) {
    assert.equal(targetState.projectTransition, null); targetState.projectTransition = marker;
    try { await work(); await page.waitForLoadState('networkidle'); }
    finally { targetState.projectTransition = null; }
  }
  async function openDetails(source, locale = 'en') {
    const summary = page.locator('summary').filter({ hasText: new RegExp('^' + escape(t(source, locale)) + '$') });
    await summary.waitFor(); assert.equal(await summary.count(), 1);
    if (!await summary.locator('..').evaluate(element => element.open)) await summary.click();
  }
  async function mutation(path, method, action) {
    const waiting = page.waitForResponse(response => new URL(response.url()).pathname === path && response.request().method() === method);
    await action(); const response = await waiting; assert.ok(response.ok(), `${method} ${path}: ${response.status()}`); return response.json();
  }
  const label = (name, locale = 'en') => page.getByLabel(t(name, locale), { exact: true });
  const entriesRegion = (locale = 'en') => page.getByRole('region', { name: t('项目实验记录', locale), exact: true });
  const card = id => page.locator(`article[data-project-entry-id="${id}"]`);
  async function attach(value, title) {
    await openDetails('保存已完成结果到项目');
    const select = label('选择已完成记录'); await select.locator(`option[value="${value}"]`).waitFor({ state: 'attached' });
    const form = page.locator('form').filter({ has: select });
    await select.selectOption(value); await form.getByLabel(t('实验名称'), { exact: true }).fill(title);
    const result = await mutation(`/api/projects/${project.id}/entries`, 'POST', () => button(page, '保存到项目', 'en').click());
    project = result.project; await card(result.entry.id).waitFor(); await page.waitForLoadState('networkidle'); return result.entry;
  }
  async function selectCandidate(id) {
    await label('项目参考布局').selectOption(candidateEntry.id); await label('项目候选布局').selectOption(id);
    const result = await mutation(`/api/projects/${project.id}`, 'PATCH', () => button(page, '保存研究任务选择', 'en').click());
    project = result.project; assert.equal(project.workflow.candidate_entry_id, id);
    await page.locator('[data-candidate-source-total]').filter({ hasText: /./ }).waitFor();
  }
  async function storedProject() {
    const response = await context.request.get(`${base}/api/projects/${project.id}`);
    assert.equal(response.status(), 200); return (await response.json()).project;
  }
  const field = (scope, source, locale = 'en') => scope.locator('dt').filter({ hasText: new RegExp('^' + escape(t(source, locale)) + '$') }).locator('..').locator('dd');
  async function inspectSignal(locale = 'en') {
    const row = card(signalEntry.id); await row.waitFor();
    assert.equal(await field(row, '父布局', locale).innerText(), referenceEntry.title);
    assert.equal(await field(row, '父布局科学编号', locale).innerText(), sourceId);
    assert.equal(await field(row, '场景模式', locale).innerText(), fixture.request.mode);
    assert.equal(await field(row, '随机种子', locale).innerText(), String(fixture.request.seed));
    const summary = row.locator('summary').filter({ hasText: new RegExp('^' + escape(t('已保存的脑源请求条件', locale)) + '$') });
    if (!await summary.locator('..').evaluate(element => element.open)) await summary.click();
    assert.equal(await field(row, '请求的源编号', locale).innerText(), String(fixture.request.source_index));
    assert.equal(await field(row, '请求的脑区', locale).innerText(), t('未记录', locale));
    assert.equal(await field(row, '请求的跨区脑源区域', locale).innerText(), t('未记录', locale));
  }

  await check('Use actual cache lookups for a source receipt and two name aliases, without submitting scientific jobs', async () => {
    signalReceipt = await lookup('/api/source-reception/lookup', fixture.request); assert.deepEqual(signalReceipt.result, fixture);
    aliases = [];
    for (const version of ['A', 'B']) {
      const names = Array.from({ length: 64 }, (_, i) => `Association-${version}-${i + 1}`);
      const job = await lookup('/api/design-evaluation/lookup', { schema: 'design-submission/1', request: golden, electrode_names: names });
      assert.match(job.annotation_id, /^[a-f0-9]{64}$/); aliases.push(job);
    }
    assert.equal(aliases[0].key, aliases[1].key); assert.notEqual(aliases[0].annotation_id, aliases[1].annotation_id);
    assert.deepEqual(aliases[0].result, aliases[1].result);
    for (const id of [sourceId, otherId, aliases[0].key]) originalRecords.set(id, (await read(context, '/api/local-compute/library/' + id)).record);
    assert.equal(new Set(originalRecords.keys()).size, 3);
    return { source_key: signalReceipt.key, parent_id: sourceId, alias_scientific_key: aliases[0].key, alias_annotations_different: true, new_scientific_jobs: 0 };
  });
  await check('Create a real project and attach four layout copies plus the completed signal through visible forms', async () => {
    await transition('Open project workspace', () => page.goto(base + '/projects', { waitUntil: 'networkidle' }));
    await label('项目名称').fill('Signal associations ' + Date.now()); await label('负责人姓名').fill('Browser verification');
    await transition('Create project and refresh record directory', async () => {
      const value = await mutation('/api/projects', 'POST', () => button(page, '创建项目', 'en').click());
      if (typeof value.access_key === 'string' && value.access_key) keepSecret(value.access_key);
      project = value.project;
      await page.getByRole('heading', { name: project.title, exact: true }).waitFor();
    });
    referenceEntry = await attach('layout:' + sourceId, 'Source parent layout');
    candidateEntry = await attach('layout:' + otherId, 'Other candidate layout');
    aliasEntries = [];
    for (const [index, alias] of aliases.entries()) aliasEntries.push(await attach(`layout:${alias.key}:${alias.annotation_id}`, 'Named layout copy ' + (index + 1)));
    signalEntry = await attach('source:' + signalReceipt.id, 'Saved signal for source parent');
    assert.equal(project.entries.length, 5);
    for (const entry of project.entries) {
      const response = await context.request.get(`${base}/api/projects/${project.id}/entries/${entry.id}`);
      assert.equal(response.status(), 200); snapshots.set(entry.id, (await response.json()).snapshot);
    }
    assert.deepEqual(snapshots.get(signalEntry.id).payload, fixture);
    return { project_id: project.id, layout_copies: 4, distinct_scientific_layouts: 3, signal_records: 1 };
  });
  await check('Candidate-specific counts and filtering expose the saved source request and explicit missing fields', async () => {
    await selectCandidate(referenceEntry.id);
    assert.equal(await page.locator('[data-project-source-total]').innerText(), '1'); assert.equal(await page.locator('[data-candidate-source-total]').innerText(), '1');
    await button(page, '查看候选布局的信号记录', 'en').click();
    assert.equal(await button(page, '只看当前候选的信号记录', 'en').getAttribute('aria-pressed'), 'true');
    assert.equal(await entriesRegion().getByRole('article').count(), 1); await inspectSignal();
    await screenshot(page, 'en-candidate-signal-conditions.png');
    return { all_signals: 1, candidate_signals: 1, source_index: fixture.request.source_index, seed: fixture.request.seed, missing_fields_not_inferred: true };
  });
  await check('Switching to a different scientific candidate preserves history and shows zero associated signals', async () => {
    // The reference must remain distinct from this candidate.
    await label('项目参考布局').selectOption(referenceEntry.id); await label('项目候选布局').selectOption(candidateEntry.id);
    project = (await mutation(`/api/projects/${project.id}`, 'PATCH', () => button(page, '保存研究任务选择', 'en').click())).project;
    assert.equal(await page.locator('[data-project-source-total]').innerText(), '1'); assert.equal(await page.locator('[data-candidate-source-total]').innerText(), '0');
    assert.equal(await entriesRegion().getByRole('article').count(), 0);
    await page.getByText(t('当前候选布局尚无已关联的信号记录。'), { exact: true }).waitFor();
    const fresh = await storedProject(); assert.deepEqual(fresh.entries, project.entries);
    await screenshot(page, 'en-candidate-no-signals.png');
    return { all_signals: 1, candidate_signals: 0, historical_entries: fresh.entries.length };
  });
  await check('Name aliases share one scientific layout count and identical candidate association behavior', async () => {
    for (const alias of aliasEntries) { await selectCandidate(alias.id); assert.equal(await page.locator('[data-candidate-source-total]').innerText(), '0'); }
    await page.getByText(t('已保存布局副本') + '：4', { exact: true }).waitFor();
    await page.getByText(t('不同科学布局') + '：3', { exact: true }).waitFor();
    assert.deepEqual(snapshots.get(aliasEntries[0].id).payload, snapshots.get(aliasEntries[1].id).payload);
    await selectCandidate(referenceEntry.id); await button(page, '全部实验记录', 'en').click();
    assert.equal(await entriesRegion().getByRole('article').count(), 5);
    return { saved_layout_copies: 4, distinct_scientific_layouts: 3, aliases_are_one_scientific_record: true };
  });
  await check('A fresh Chinese browser opens the workspace project and can filter the same archived association', async () => {
    await page.waitForLoadState('networkidle');
    const chinese = await newContext('zh-CN'); page = await chinese.context.newPage(); setPage(page);
    await transition('Open the Chinese project by its identifier and refresh record directory', async () => {
      await page.goto(`${base}/projects?project=${project.id}`, { waitUntil: 'networkidle' });
      await page.getByRole('heading', { name: project.title, exact: true }).waitFor();
    }, chinese.state);
    assert.equal(await page.locator('[data-project-source-total]').innerText(), '1');
    await button(page, '只看当前候选的信号记录', 'zh-CN').click(); assert.equal(await entriesRegion('zh-CN').getByRole('article').count(), 1);
    await inspectSignal('zh-CN'); await screenshot(page, 'zh-candidate-signal-conditions.png');
    return { restored_in_fresh_context: true, candidate_signals: 1, source_id_unchanged: true };
  });
  await check('All original science and immutable project snapshots survive candidate and view changes unchanged', async () => {
    const fresh = await storedProject(); assert.equal(fresh.entries.length, snapshots.size);
    for (const entry of fresh.entries) {
      const response = await context.request.get(`${base}/api/projects/${project.id}/entries/${entry.id}`);
      assert.equal(response.status(), 200); assert.ok(isDeepStrictEqual((await response.json()).snapshot, snapshots.get(entry.id)));
    }
    for (const [id, record] of originalRecords) assert.deepEqual((await read(context, '/api/local-compute/library/' + id)).record, record);
    const health = await read(context, '/api/local-compute/health'); assertCacheOnly(health);
    return { snapshots_unchanged: snapshots.size, original_records_unchanged: originalRecords.size, maintenance: true, drained: true };
  });
  return { project_id: project.id, source_parent_id: sourceId, alternate_layout_id: otherId, alias_scientific_key: aliases[0].key, project_entries: project.entries.length };
}
