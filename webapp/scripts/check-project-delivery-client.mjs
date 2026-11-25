import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { prepareProjectDelivery } from '../features/projects/project-delivery-download.ts';

const hash = value => createHash('sha256').update(value).digest('hex');
const project = { id: '00000000-0000-4000-8000-000000000001', revision: 7 };
function fixture({ readme = '# Study\r\n脑电研究\n', raw = '{"coordinates":[[-0,1e-15,-112.31415926535898]],"retention":-0.12345678901234566}\n' } = {}) {
  const file = (path, media_type, content) => ({ path, media_type, encoding: 'utf-8', size_bytes: Buffer.byteLength(content), sha256: hash(content), content });
  const value = { schema: 'eeg-research-delivery/1', exported_at: '2026-11-13T12:00:00Z', project: { ...project, notes: 'Original notes' }, host: { application_version: 'test' }, records: [],
    files: [file('README.md', 'text/markdown', readme), file('records/00000000-0000-4000-8000-000000000002.json', 'application/json', raw)], scientific_results_recomputed: false };
  // Independently assemble the documented manifest order without file content.
  const manifest = { schema: value.schema, exported_at: value.exported_at, project: value.project, host: value.host, records: value.records,
    scientific_results_recomputed: false, files: value.files.map(file => ({ path: file.path, media_type: file.media_type, encoding: file.encoding, size_bytes: file.size_bytes, sha256: file.sha256 })) };
  value.manifest_sha256 = hash(JSON.stringify(manifest));
  return value;
}

void test('the downloaded wrapper keeps every original file string, UTF-8 byte and scientific number representation', async () => {
  const value = fixture(), before = JSON.stringify(value);
  const result = await prepareProjectDelivery(value, project);
  assert.equal(result.bundle, value); assert.equal(result.readme, value.files[0]);
  assert.equal(result.readme.content, '# Study\r\n脑电研究\n');
  assert.equal(result.filename, `eeg-research-project-${project.id}-r7.json`);
  const downloaded = JSON.parse(result.text);
  for (let i = 0; i < value.files.length; i++) {
    assert.equal(downloaded.files[i].content, value.files[i].content);
    assert.equal(hash(downloaded.files[i].content), value.files[i].sha256);
  }
  assert.match(downloaded.files[1].content, /\[\[-0,1e-15,-112\.31415926535898\]\]/);
  assert.equal(result.totalBytes, value.files.reduce((sum, file) => sum + file.size_bytes, 0));
  assert.equal(JSON.stringify(value), before);
});

void test('a damaged file or changed manifest is rejected before preparing a download', async () => {
  for (const mutate of [
    value => { value.files[1].content += ' '; },
    value => { value.files[1].sha256 = '0'.repeat(64); },
    value => { value.project.notes = 'Changed after export'; },
    value => { value.manifest_sha256 = '0'.repeat(64); },
  ]) {
    const value = fixture(); mutate(value);
    await assert.rejects(prepareProjectDelivery(value, project), /校验|大小/);
  }
});

void test('an export for another project or revision cannot replace the selected project delivery', async () => {
  const value = fixture();
  await assert.rejects(prepareProjectDelivery(value, { ...project, id: '00000000-0000-4000-8000-000000000099' }), /格式/);
  await assert.rejects(prepareProjectDelivery(value, { ...project, revision: 8 }), /重新读取/);
  value.scientific_results_recomputed = true;
  await assert.rejects(prepareProjectDelivery(value, project), /格式/);
});

void test('unsafe inventory paths, duplicates and unexpected encodings are rejected', async () => {
  for (const mutate of [
    value => { value.files[1].path = '../outside.json'; },
    value => { value.files[1].path = '/absolute.json'; },
    value => { value.files[1].path = 'records\\outside.json'; },
    value => { value.files[1].path = 'records/line\nfeed.json'; },
    value => { value.files[1].path = 'README.md'; },
    value => { value.files[1].encoding = 'base64'; },
    value => { value.files.shift(); },
  ]) {
    const value = fixture(); mutate(value);
    await assert.rejects(prepareProjectDelivery(value, project), /清单|说明文档/);
  }
});

void test('an aborted request cannot produce a download', async () => {
  const controller = new AbortController(); controller.abort();
  await assert.rejects(prepareProjectDelivery(fixture(), project, controller.signal), { name: 'AbortError' });
  // Projects carry no access key, so a delivery is not searched for one.
  const value = fixture({ readme: '# Study\n' + '9'.repeat(64) });
  assert.equal((await prepareProjectDelivery(value, project)).readme.content, '# Study\n' + '9'.repeat(64));
});
