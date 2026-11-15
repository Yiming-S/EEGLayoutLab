import test from 'node:test';
import assert from 'node:assert/strict';
import { exportRobustnessStudy } from '../client/robustness.ts';
const id = '18358bf4-143e-4431-8456-b99328462b37';
async function response(raw, version, run) {
  const original = globalThis.fetch;
  globalThis.fetch = async path => { assert.equal(path, '/api/robustness-studies/' + id + '/export'); return new Response(raw, { headers: version ? { 'X-EEG-API-Version': version } : {} }); };
  try { await run(); } finally { globalThis.fetch = original; }
}
void test('study download validates its envelope and retains exact original response bytes', async () => {
  const raw = '{"schema":"eeg-robustness-study-export/1","study":{"id":"' + id + '"},"cases":[{"cache_json":"{\\\"v\\\":-0,\\\"x\\\":1e-15}\\r\\n"}]}\r\n';
  await response(raw, '1', async () => assert.equal(await exportRobustnessStudy(id), raw));
});
void test('study download rejects an incompatible API version before downloading its data', async () => {
  await response('{}', '2', async () => assert.rejects(exportRobustnessStudy(id), { status: 426 }));
});
void test('study download rejects HTML, wrong schemas and another study identity', async () => {
  for (const raw of ['<!doctype html>', '{}', JSON.stringify({ schema: 'eeg-robustness-study-export/1', study: { id: '18358bf4-143e-4431-8456-b99328462b38' }, cases: [] })]) await response(raw, '1', async () => assert.rejects(exportRobustnessStudy(id), { status: 502 }));
});
