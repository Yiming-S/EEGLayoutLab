import test from 'node:test';
import assert from 'node:assert/strict';
import { createHookHarness } from './helpers/hook-harness.mjs';
import { readActiveProject, writeActiveProject, activateProject, ACTIVE_PROJECT_EVENT, ACTIVE_PROJECT_STORAGE } from '../features/projects/active-project.ts';
import { comparableProjectEntries, projectWorkflowFor, projectWorkflowFromComparison } from '../features/projects/project-workflow.ts';
import { projectSnapshotView } from '../features/projects/project-snapshot-view.ts';
import { recordedForwardOrigin } from '../features/reception/result-provenance.ts';
import { safeReturnHref } from '../lib/ui-language.ts';
import { workspaceLinks } from '../lib/workspace-navigation.ts';
import { documentationHref } from '../lib/documentation.ts';
import { ProjectService } from '../server/projects/service.mjs';

const credential = { project_id: '00000000-0000-4000-8000-000000000001', access_key: 'a'.repeat(64), role: 'owner', title: 'Study A' };
const entry = (id, record_id, kind = 'layout', protocol = 'cache') => ({ id, record_id, kind, title: id, notes: '', summary: { protocol, electrode_count: kind === 'editor' ? 63 : 64 } });
const entries = [entry('ref', 'b'.repeat(64)), entry('candidate', 'c'.repeat(64)), entry('edit', 'd'.repeat(64), 'editor', 'electrode-editor/1'), entry('signal', 'e'.repeat(64), 'source', 'source-reception/2')];
const store = () => { const map = new Map(); return { getItem: key => map.get(key) ?? null, setItem: (key, value) => map.set(key, value), removeItem: key => map.delete(key) }; };

void test('the active project is per-tab UI context and clearing it leaves another tab unchanged', () => {
  const a = store(), b = store();
  writeActiveProject(a, credential);
  assert.deepEqual(readActiveProject(a), credential); assert.equal(readActiveProject(b), null);
  writeActiveProject(a, null); assert.equal(readActiveProject(a), null);
  b.setItem(ACTIVE_PROJECT_STORAGE, '{"project_id":"../../bad"}'); assert.equal(readActiveProject(b), null);
  assert.equal(readActiveProject({ getItem() { throw new Error('Storage blocked'); } }), null);
});

void test('active-project hook restores and follows tab changes without making network requests', async t => {
  const listeners = new Map(), sessionStorage = store(); writeActiveProject(sessionStorage, credential);
  const window = { sessionStorage, addEventListener: (type, callback) => listeners.set(type, callback), removeEventListener: type => listeners.delete(type), dispatchEvent: event => listeners.get(event.type)?.() };
  let requests = 0;
  const harness = await createHookHarness({ filename: new URL('../features/projects/use-active-project.ts', import.meta.url), exportName: 'useActiveProject',
    imports: { readActiveProject, ACTIVE_PROJECT_EVENT }, globals: { window, fetch: () => { requests++; throw new Error('Unexpected request'); } } });
  t.after(() => harness.dispose()); await harness.waitFor(value => value?.project_id === credential.project_id);
  await harness.act(() => activateProject({ ...credential, role: 'viewer', title: 'Shared view' }));
  assert.equal(harness.current.role, 'viewer'); assert.equal(harness.current.title, 'Shared view');
  await harness.act(() => activateProject(null)); assert.equal(harness.current, null); assert.equal(requests, 0);
  harness.dispose(); assert.equal(listeners.size, 0);
});

void test('research selections preserve existing independent thresholds and never use edited layouts as fixed-layout comparisons', () => {
  const project = { entries, workflow: { reference_entry_id: 'ref', candidate_entry_id: 'candidate', comparison_href: `/decision?a=${entries[0].record_id}&b=${entries[1].record_id}&ar=47&thresholdMode=custom&sensitivity=62&localization=58&p90=19.5` } };
  const before = JSON.stringify(project);
  assert.equal(comparableProjectEntries(entries).length, 2);
  const result = projectWorkflowFor(project, 'ref', 'candidate');
  const q = new URL(result.comparison_href, 'http://localhost').searchParams;
  for (const [key, value] of [['ar', '47'], ['thresholdMode', 'custom'], ['sensitivity', '62'], ['localization', '58'], ['p90', '19.5']]) assert.equal(q.get(key), value);
  assert.equal(JSON.stringify(project), before);
  assert.throws(() => projectWorkflowFor(project, 'ref', 'ref'));
  assert.throws(() => projectWorkflowFor(project, 'ref', 'edit'));
  assert.equal(projectWorkflowFor(project, 'ref', null).comparison_href, null);
});

void test('saving comparison context keeps only canonical scientific decision controls and requires both project layouts', () => {
  const project = { entries };
  const href = `/decision?a=${entries[0].record_id}&b=${entries[1].record_id}&ar=71&thresholdMode=joint&returnTo=%2Fprojects&access=forbidden`;
  const result = projectWorkflowFromComparison(project, href), q = new URL(result.comparison_href, 'http://localhost').searchParams;
  assert.equal(result.reference_entry_id, 'ref'); assert.equal(result.candidate_entry_id, 'candidate');
  assert.equal(q.get('ar'), '71'); assert.equal(q.get('sensitivity'), '71'); assert.equal(q.get('localization'), '71');
  assert.equal(q.has('returnTo'), false); assert.equal(q.has('access'), false);
  assert.throws(() => projectWorkflowFromComparison(project, '/decision?a=' + entries[0].record_id));
  assert.throws(() => projectWorkflowFromComparison(project, 'https://elsewhere.example' + href));
});

void test('sharing credentials cannot be forwarded into header or documentation query links', () => {
  const shared = `/projects#project=${credential.project_id}&access=${credential.access_key}`;
  assert.equal(safeReturnHref(shared, '/'), '/projects');
  const links = workspaceLinks(shared, 90, null, { id: null, phase: 'saved' });
  for (const value of Object.values(links)) assert.ok(!decodeURIComponent(value).includes(credential.access_key), value);
  const guide = documentationHref('/guide', '?returnTo=' + encodeURIComponent(shared), 'method');
  assert.equal(new URL(guide, 'http://localhost').searchParams.get('returnTo'), '/projects');
  assert.ok(!decodeURIComponent(guide).includes(credential.access_key));
});

void test('archived scientific views reuse exact saved objects without record-cache access or data projection', () => {
  const payload = { schema_version: 'source-reception/2', conditions: [{ field_retention: -0.12345678901234566 }], waveforms: { time_s: [0, .1], candidate: [[-0, 1e-15]] } };
  const source = { schema: 'research-project-snapshot/1', kind: 'source', record_id: entries[3].record_id, payload };
  const before = JSON.stringify(source), view = projectSnapshotView(entries[3], source);
  assert.equal(view.result, payload); assert.equal(view.result.waveforms, payload.waveforms); assert.equal(Object.is(payload.waveforms.candidate[0][0], -0), true);
  assert.equal(JSON.stringify(source), before);
  const record = { id: entries[0].record_id, layout: { xyzMm: [[1e-15, -45.12345678901234, 78]] }, metrics: { field_relative: -.23 } };
  assert.equal(projectSnapshotView(entries[0], { schema: 'research-project-snapshot/1', kind: 'layout', record_id: record.id, payload: { record } }).record, record);
  const edited = { schema: 'electrode-editor/1', evaluated_xyz_mm: [[1, 2, 3]] };
  assert.equal(projectSnapshotView(entries[2], { schema: 'research-project-snapshot/1', kind: 'editor', record_id: entries[2].record_id, payload: { cache: { result: edited } } }).result, edited);
  assert.throws(() => projectSnapshotView(entries[0], source), /不匹配/);
});

void test('field provenance distinguishes an archived shared field, ordinary FEM cache and a new solve', () => {
  assert.match(recordedForwardOrigin({ forward_mode: 'exact_bank', fem_recomputed: false }), /精确匹配/);
  assert.match(recordedForwardOrigin({ forward_mode: 'native_fem_cache', shared_forward_producer: { workflow: 'design_evaluation' }, fem_recomputed: false }), /布局评价准备/);
  assert.match(recordedForwardOrigin({ forward_mode: 'native_fem_cache', fem_recomputed: false }), /已保存/);
  assert.match(recordedForwardOrigin({ forward_mode: 'native_fem', fem_recomputed: true }), /计算生成/);
  assert.match(recordedForwardOrigin({ forward_mode: 'scalp_node_table', fem_recomputed: false }), /头皮节点预计算/);
  assert.match(recordedForwardOrigin({}), /原始记录/);
});

void test('project layout summaries mark whether signal simulation accepts the layout', async () => {
  const xyzMm = Array.from({ length: 64 }, () => [0, 0, 80]), spatial = { kind: 'spatial', rho: 0.5, length_mm: 20 };
  const record = (id, extra) => ({ id, status: 'completed', dataset_id: 'cache', layout: { xyzMm }, region_count: 4, request: { region_count: 4 }, ...extra });
  const records = { ['f'.repeat(64)]: record('f'.repeat(64)), ['9'.repeat(64)]: record('9'.repeat(64), { request: { region_count: 4, noise_model: spatial } }), ['8'.repeat(64)]: record('8'.repeat(64), { layout: { xyzMm: xyzMm.slice(1) } }) };
  const service = new ProjectService({ queue: { root: '/unused', python: 'unused', library: { get: async id => records[id] } }, store: {}, delivery: {}, bundle: async (_root, value) => ({ record: value }) });
  const simulation = async record_id => (await service.resolveSnapshot({ kind: 'layout', record_id }, { id: 'browser' })).summary.simulation;
  assert.equal(await simulation('f'.repeat(64)), true);
  assert.equal(await simulation('9'.repeat(64)), false);
  assert.equal(await simulation('8'.repeat(64)), false);
});
