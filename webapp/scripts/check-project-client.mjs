import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {
  PROJECT_ACCESS_STORAGE, validateProjectAccess, readProjectAccess, saveProjectAccess, forgetProjectAccess,
  projectAccessFile, parseProjectAccessFile, projectShareHref, projectAccessFromFragment,
  projectRequest, createProject,
} from '../client/projects.ts';
import { translateText } from '../lib/i18n/core.ts';
import { safeReturnHref } from '../lib/ui-language.ts';
import { workspaceLinks, workingPage } from '../lib/workspace-navigation.ts';
import { collectProjectRecordChoices, projectRecordChoices } from '../features/projects/project-record-choices.ts';

const credential = { project_id: 'abcde123-1234-4321-abcd-0123456789ab', access_key: 'a'.repeat(64), role: 'owner', title: 'Motor layout study' };
function storage() {
  const map = new Map();
  return { getItem: key => map.get(key) ?? null, setItem: (key, value) => map.set(key, value) };
}

void test('project access files validate their format, limits and credential fields', () => {
  assert.deepEqual(parseProjectAccessFile(projectAccessFile(credential)), credential);
  for (const value of [null, {}, { ...credential, project_id: '../secret' }, { ...credential, access_key: 'short' }, { ...credential, access_key: 'a'.repeat(64) + '\n' }])
    assert.throws(() => validateProjectAccess(value));
  assert.throws(() => parseProjectAccessFile(JSON.stringify(credential)), /格式/);
  assert.throws(() => parseProjectAccessFile(' '.repeat(8193)), /过大/);
  assert.deepEqual(readProjectAccess({ getItem() { throw new Error('Storage blocked'); } }), []);
});

void test('browser vault deduplicates projects and never replaces owner access with a read-only share', () => {
  const local = storage();
  saveProjectAccess(local, credential);
  const viewer = { ...credential, access_key: 'b'.repeat(64), role: 'viewer' };
  saveProjectAccess(local, viewer);
  assert.deepEqual(readProjectAccess(local), [credential]);
  const other = { ...credential, project_id: '00000000-0000-4000-8000-000000000001', title: 'Second project' };
  saveProjectAccess(local, other);
  assert.deepEqual(readProjectAccess(local), [other, credential]);
  assert.deepEqual(forgetProjectAccess(local, credential.project_id), [other]);
  local.setItem(PROJECT_ACCESS_STORAGE, JSON.stringify([other, { project_id: '../bad', access_key: 'abc' }]));
  assert.deepEqual(readProjectAccess(local), [other]);
});

void test('sharing puts credentials only in the fragment and project navigation accepts no remote return', () => {
  const url = new URL(projectShareHref('https://eeg.example.org', credential));
  assert.equal(url.pathname, '/projects'); assert.equal(url.search, '');
  assert.ok(!url.pathname.includes(credential.access_key));
  assert.deepEqual(projectAccessFromFragment(url.hash), { project_id: credential.project_id, access_key: credential.access_key });
  assert.equal(projectAccessFromFragment('#section'), null);
  assert.throws(() => projectAccessFromFragment('#project=bad&access=short'));
  assert.equal(safeReturnHref('/projects?project=' + credential.project_id, '/'), '/projects?project=' + credential.project_id);
  assert.equal(safeReturnHref('https://elsewhere.example/projects', '/'), '/');
  assert.equal(workingPage('/projects'), 'projects');
  assert.equal(workspaceLinks('/projects', 90, null, { id: null, phase: 'saved' }).projects, '/projects');
});

void test('project HTTP writes use both headers and never send credentials in the request URL or scientific jobs', async t => {
  const original = globalThis.fetch, calls = [];
  t.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, status: 200, headers: new Headers({ 'X-EEG-API-Version': '1' }), json: async () =>
      url === '/api/local-compute/health' ? { token: 'session-token' } : { project: { id: credential.project_id }, role: 'owner' } };
  };
  const body = { revision: 4, title: 'Changed description', notes: 'No scientific data changed' };
  const encoded = JSON.stringify(body);
  await projectRequest(credential, '', { method: 'PATCH', body: encoded });
  assert.equal(calls.length, 2); assert.equal(calls[0].url, '/api/local-compute/health');
  assert.equal(calls[1].url, '/api/projects/' + credential.project_id);
  assert.equal(calls[1].options.headers.get('X-EEG-Project-Key'), credential.access_key);
  assert.equal(calls[1].options.headers.get('X-EEG-Compute-Token'), 'session-token');
  assert.equal(calls[1].options.body, encoded); assert.equal(JSON.stringify(body), encoded);
  assert.ok(calls.every(call => !call.url.includes(credential.access_key) && !call.url.includes('/jobs')));
  await projectRequest(credential);
  assert.equal(calls.length, 3); assert.equal(calls[2].options.headers.get('X-EEG-Project-Key'), credential.access_key);
  await assert.rejects(projectRequest(credential, '/../other'), /路径/);
  const before = calls.length;
  await createProject({ title: 'Study', owner_name: 'Researcher' });
  assert.equal(calls.length, before + 2);
  assert.equal(calls.at(-1).url, '/api/projects');
  assert.equal(calls.at(-1).options.headers.get('X-EEG-Project-Key'), null);
});

void test('an uncertain project write is not automatically submitted again', async t => {
  const original = globalThis.fetch, calls = [];
  t.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async (url) => {
    calls.push(url);
    if (url.endsWith('/health')) return { ok: true, status: 200, json: async () => ({ token: 'session-token' }) };
    throw new Error('Disconnected after send');
  };
  await assert.rejects(projectRequest(credential, '/entries', { method: 'POST', body: '{"revision":1}' }));
  assert.equal(calls.filter(url => url.endsWith('/entries')).length, 1);
});

void test('project display vocabulary is bilingual and scientific identity is not translated', async () => {
  const catalog = JSON.parse(await readFile(new URL('../lib/i18n/projects-catalog.json', import.meta.url), 'utf8'));
  for (const entry of Object.values(catalog)) {
    assert.equal(translateText(entry.source, 'en'), entry.en);
    assert.equal(translateText(entry.source, 'zh-CN'), entry.source);
    assert.doesNotMatch(entry.en, /[\u3400-\u9fff]/);
  }
  assert.equal(translateText(credential.project_id, 'en'), credential.project_id);
  assert.equal(translateText('a'.repeat(64), 'zh-CN'), 'a'.repeat(64));
});

void test('completed record choices retain each actual service identity and exclude unfinished tasks', () => {
  const sourceId = '00000000-0000-4000-8000-000000000001';
  const layouts = { schema: 'local-data-library/1', records: [
    { id: 'a'.repeat(64), label: 'Original scientific layout', status: 'completed', metrics: { field: -.23 } },
    { id: 'b'.repeat(64), label: 'No layout', status: 'no_layout' },
  ] };
  const editors = { records: [{ key: 'c'.repeat(64), parent_id: 'a'.repeat(64), electrode_count: 63 }] };
  const sources = { schema: 'browser-experiment-records/1', records: [
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
