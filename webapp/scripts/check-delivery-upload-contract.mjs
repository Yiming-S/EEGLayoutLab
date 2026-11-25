/** UI-boundary regressions for local files with valid checksums; no external scientific data. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { openResearchDelivery } from '../features/projects/research-delivery-format.mjs';

const sha = value => createHash('sha256').update(value).digest('hex');
// The delivery of a complete synthetic signal result (64 electrodes, 400 samples) per schema, built by the Python
// service's builder; tests/service/test_delivery.py checks that Node's builder makes the same bytes, and the same
// bytes as delivery(schema, mutate) for each change below.
const fixtures = resolve(import.meta.dirname, '../../tests/service/fixtures/delivery');
const base = schema => readFileSync(resolve(fixtures, `upload-${schema.replace('/', '-')}.json`), 'utf8');
/** The fixture's delivery once `mutate` changed its result, every file, record and manifest checksum recomputed. */
function delivery(schema, mutate) {
  const bundle = JSON.parse(base(schema)), file = bundle.files[1], snapshot = JSON.parse(file.content);
  mutate(snapshot.payload);
  file.content = JSON.stringify(snapshot);
  file.size_bytes = Buffer.byteLength(file.content);
  file.sha256 = sha(file.content);
  bundle.records[0].snapshot_sha256 = file.sha256;
  const { manifest_sha256: _checksum, files, ...metadata } = bundle;
  bundle.manifest_sha256 = sha(JSON.stringify({ ...metadata,
    files: files.map(({ content: _content, ...rest }) => rest) }));
  return bundle;
}
for (const schema of ['source-reception/1', 'source-reception/2']) {
  void test(`local upload keeps a complete ${schema} snapshot byte-identical`, async () => {
    const bundle = JSON.parse(base(schema)), raw = JSON.stringify(bundle, null, 2) + '\n';
    const opened = await openResearchDelivery(raw);
    assert.equal(opened.original_text, raw);
    assert.equal(opened.entries[0].snapshot_json, bundle.files.find(file => file.path.startsWith('records/')).content);
  });
  for (const [name, mutate] of [
    ['missing provenance', result => { delete result.provenance; }],
    ['missing metrics', result => { delete result.metrics; }],
    ['object patch count', result => { result.source.patch_count = { poison: 'React child' }; }],
    ['missing source waveform', result => { delete result.waveforms.source_nam; }],
    ['short source waveform', result => { result.waveforms.source_nam[0].pop(); }],
    ['object amplitude ratio', result => { result.metrics.pure_brain_amplitude_ratio = { valueOf: 0, toString: 0 }; }],
  ]) void test(`local upload rejects hash-valid ${schema} ${String(name)}`, async () => {
    // Producer recomputes every file/record/manifest checksum for the malformed result.
    await assert.rejects(openResearchDelivery(JSON.stringify(delivery(schema, mutate))));
  });
}
