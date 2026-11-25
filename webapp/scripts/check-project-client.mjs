import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createProject, listProjects, projectRequest, projectSummary, readProjectDirectory } from '../client/projects.ts';
import { translateText } from '../lib/i18n/core.ts';
import { safeReturnHref } from '../lib/ui-language.ts';
import { workspaceLinks, workingPage } from '../lib/workspace-navigation.ts';
import { collectProjectRecordChoices, projectRecordChoices } from '../features/projects/project-record-choices.ts';

const projectId = 'abcde123-1234-4321-abcd-0123456789ab';
const response = value => ({ ok: true, status: 200, headers: new Headers({ 'X-EEG-API-Version': '1' }), json: async () => value });

void test('the project directory lists the workspace projects and skips rows that name no project', async t => {
  const row = { id: projectId, title: 'Motor layout study', owner_name: 'Researcher', revision: 3,
    created_at: '2026-11-20T08:00:00.000Z', updated_at: '2026-11-25T09:00:00.000Z', entry_count: 2 };
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => { calls.push({ url, options }); return response({ projects: [row,
    { ...row, id: '../other' }, { ...row, id: projectId.toUpperCase() }, { ...row, title: 7 }, { ...row, entry_count: -0.5 }, null] }); });
  assert.deepEqual(await listProjects(), [row]);
  assert.equal(calls.length, 1); assert.equal(calls[0].url, '/api/projects');
  assert.equal(calls[0].options.method, undefined); assert.equal(calls[0].options.body, undefined);
  for (const value of [null, [], { projects: null }, { schema: 'wrong' }]) assert.throws(() => readProjectDirectory(value), /格式/);
  const project = { ...row, notes: '', entries: [{ id: 'a' }, { id: 'b' }, { id: 'c' }] };
  assert.deepEqual(projectSummary(project), { ...row, entry_count: 3 });
  assert.equal(translateText('项目目录格式无效', 'en'), 'The project directory is invalid');
  assert.equal(translateText('3条实验记录', 'en'), '3 records'); assert.equal(translateText('1条实验记录', 'en'), '1 record');
});

void test('project navigation accepts no remote return', () => {
  assert.equal(safeReturnHref('/projects?project=' + projectId, '/'), '/projects?project=' + projectId);
  assert.equal(safeReturnHref('https://elsewhere.example/projects', '/'), '/');
  assert.equal(workingPage('/projects'), 'projects');
  assert.equal(workspaceLinks('/projects', 90, null, { id: null, phase: 'saved' }).projects, '/projects');
});

void test('project HTTP writes send the session token and keep their bytes, with no project key and nothing in the URL', async t => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options });
    return response(url === '/api/local-compute/health' ? { token: 'session-token' } : { project: { id: projectId } });
  });
  const body = { revision: 4, title: 'Changed description', notes: 'No scientific data changed' };
  const encoded = JSON.stringify(body);
  await projectRequest(projectId, '', { method: 'PATCH', body: encoded });
  assert.equal(calls.length, 2); assert.equal(calls[0].url, '/api/local-compute/health');
  assert.equal(calls[1].url, '/api/projects/' + projectId);
  assert.equal(calls[1].options.headers.get('X-EEG-Compute-Token'), 'session-token');
  assert.equal(calls[1].options.headers.get('Content-Type'), 'application/json');
  assert.equal(calls[1].options.body, encoded); assert.equal(JSON.stringify(body), encoded);
  // Reads need neither the token nor a body; the cookie alone signs them in.
  await projectRequest(projectId, '/export');
  assert.equal(calls.length, 3); assert.equal(calls[2].url, `/api/projects/${projectId}/export`);
  assert.equal(calls[2].options.headers.get('X-EEG-Compute-Token'), null);
  await projectRequest(projectId, '/entries/' + '0'.repeat(8) + '-0000-4000-8000-' + '0'.repeat(12), { method: 'DELETE', body: '{"revision":4}' });
  assert.ok(calls.every(call => !call.options.headers.has('X-EEG-Project-Key') && !call.url.includes('?') && !call.url.includes('/jobs')));
  // Credentials and sharing are gone with their routes; other ids and paths are refused before any request.
  const before = calls.length;
  for (const suffix of ['/share', '/revoke-share', '/../other', '?access=key']) await assert.rejects(projectRequest(projectId, suffix), /路径/);
  for (const id of ['../secret', projectId.toUpperCase(), '']) await assert.rejects(projectRequest(id), /编号/);
  assert.equal(calls.length, before);
  await createProject({ title: 'Study', owner_name: 'Researcher' });
  assert.equal(calls.length, before + 2);
  assert.equal(calls.at(-1).url, '/api/projects');
  assert.equal(calls.at(-1).options.headers.get('X-EEG-Compute-Token'), 'session-token');
  assert.equal(calls.at(-1).options.headers.get('X-EEG-Project-Key'), null);
});

void test('an uncertain project write is not automatically submitted again', async t => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url) => {
    calls.push(url);
    if (url.endsWith('/health')) return { ok: true, status: 200, json: async () => ({ token: 'session-token' }) };
    throw new Error('Disconnected after send');
  });
  await assert.rejects(projectRequest(projectId, '/entries', { method: 'POST', body: '{"revision":1}' }));
  assert.equal(calls.filter(url => url.endsWith('/entries')).length, 1);
});

void test('project display vocabulary is bilingual and scientific identity is not translated', async () => {
  const catalog = JSON.parse(await readFile(new URL('../lib/i18n/projects-catalog.json', import.meta.url), 'utf8'));
  for (const entry of Object.values(catalog)) {
    assert.equal(translateText(entry.source, 'en'), entry.en);
    assert.equal(translateText(entry.source, 'zh-CN'), entry.source);
    assert.doesNotMatch(entry.en, /[\u3400-\u9fff]/);
  }
  assert.equal(translateText(projectId, 'en'), projectId);
  assert.equal(translateText('a'.repeat(64), 'zh-CN'), 'a'.repeat(64));
});

void test('completed record choices retain each actual service identity and exclude unfinished tasks', () => {
  const sourceId = '00000000-0000-4000-8000-000000000001';
  const layouts = { schema: 'local-data-library/1', records: [
    { id: 'a'.repeat(64), label: 'Original scientific layout', status: 'completed', metrics: { field: -.23 } },
    { id: 'b'.repeat(64), label: 'No layout', status: 'no_layout' },
  ] };
  const editors = { records: [{ key: 'c'.repeat(64), parent_id: 'a'.repeat(64), electrode_count: 63 }] };
  // The Python service's records: the workspace's signal receipts (scope 'workspace').
  const sources = { schema: 'browser-experiment-records/1', scope: 'workspace', receipt_limit: 1000, records: [
    { id: sourceId, key: 'd'.repeat(64), kind: 'source-reception', status: 'completed' },
    { id: '00000000-0000-4000-8000-000000000002', key: 'e'.repeat(64), kind: 'source-reception', status: 'queued' },
  ] };
  const before = JSON.stringify([layouts, editors, sources]);
  const result = collectProjectRecordChoices([layouts, editors, sources].map(value => ({ status: 'fulfilled', value })), 'en');
  assert.deepEqual(result.choices.map(({ kind, id }) => ({ kind, id })), [
    { kind: 'layout', id: 'a'.repeat(64) }, { kind: 'editor', id: 'c'.repeat(64) }, { kind: 'source', id: sourceId },
  ]);
  assert.deepEqual(result.warnings, []);
  assert.equal(JSON.stringify([layouts, editors, sources]), before);
});

void test('a failed or malformed directory exposes a diagnostic while other completed record types remain available', () => {
  const completed = { records: [{ id: 'a'.repeat(64), label: 'Saved result', status: 'completed' }] };
  const result = collectProjectRecordChoices([
    { status: 'fulfilled', value: completed },
    { status: 'rejected', reason: new Error('Editor directory disconnected') },
    { status: 'fulfilled', value: { records: null } },
  ], 'en');
  assert.equal(result.choices.length, 1);
  assert.deepEqual(result.warnings, [
    { kind: 'editor', message: 'Editor directory disconnected' },
    { kind: 'source', message: '记录目录格式无效' },
  ]);
  assert.throws(() => projectRecordChoices('layout', { schema: 'wrong' }, 'en'), /格式/);
});
