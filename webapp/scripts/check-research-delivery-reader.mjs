import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  openResearchDelivery,
  DELIVERY_INPUT_LIMIT,
} from '../features/projects/research-delivery-reader.ts';
const sha = (value) => createHash('sha256').update(value).digest('hex');
const entryId = '18358bf4-143e-4431-8456-b99328462b38';
const recordId = 'a'.repeat(64),
  annotationId = 'b'.repeat(64);
// One 64-electrode layout delivered with its pretty-printed snapshot (optionally with electrode names, or with legacy
// metrics without median and P90), built by the Python service's builder; tests/service/test_delivery.py checks
// that Node's builder makes the same bytes from the same inputs.
const fixtures = resolve(
  import.meta.dirname,
  '../../tests/service/fixtures/delivery',
);
function fixture({ named = false, legacy = false } = {}) {
  if (named && legacy) throw new Error('No named legacy delivery fixture.');
  const name = named ? 'reader-named' : legacy ? 'reader-legacy' : 'reader';
  return JSON.parse(readFileSync(resolve(fixtures, `${name}.json`), 'utf8'));
}
function rehash(value) {
  for (const file of value.files) {
    file.size_bytes = Buffer.byteLength(file.content);
    file.sha256 = sha(file.content);
  }
  for (const record of value.records)
    record.snapshot_sha256 = value.files.find(
      (file) => file.path === record.path,
    )?.sha256;
  const { manifest_sha256: _checksum, files, ...metadata } = value;
  value.manifest_sha256 = sha(
    JSON.stringify({
      ...metadata,
      files: files.map(({ content: _content, ...file }) => file),
    }),
  );
  return value;
}
for (const options of [{}, { named: true }, { legacy: true }])
  void test(`delivery reader preserves original text and numerical values ${JSON.stringify(options)}`, async () => {
    const bundle = fixture(options),
      raw = JSON.stringify(bundle, null, 2) + '\n';
    const opened = await openResearchDelivery(raw);
    assert.equal(opened.original_text, raw);
    assert.equal(opened.entries[0].snapshot_json, bundle.files[1].content);
    assert.deepEqual(
      opened.entries[0].snapshot.payload,
      JSON.parse(bundle.files[1].content).payload,
    );
    assert.equal(
      opened.entries[0].entry.notes,
      '<script>never executed</script>',
    );
    assert.equal(
      opened.project.entries[0].annotation_id,
      options.named ? annotationId : undefined,
    );
  });
for (const [name, mutate] of [
  [
    'content',
    (b) => {
      b.files[1].content += ' ';
    },
  ],
  [
    'size',
    (b) => {
      b.files[1].size_bytes++;
    },
  ],
  [
    'manifest',
    (b) => {
      b.project.notes = 'changed';
    },
  ],
  [
    'path',
    (b) => {
      b.files[1].path = '../records/file.json';
      rehash(b);
    },
  ],
  [
    'duplicate path',
    (b) => {
      b.files[1].path = 'README.md';
      rehash(b);
    },
  ],
  [
    'missing file',
    (b) => {
      b.files.pop();
      rehash(b);
    },
  ],
  [
    'credential field',
    (b) => {
      b.project.access_key = 'secret';
      rehash(b);
    },
  ],
  [
    'nonfinite coordinate',
    (b) => {
      const s = JSON.parse(b.files[1].content);
      s.payload.record.layout.xyzMm[0][0] = null;
      b.files[1].content = JSON.stringify(s);
      rehash(b);
    },
  ],
  [
    'name identity',
    (b) => {
      const s = JSON.parse(b.files[1].content);
      s.electrode_annotation.record_id = 'd'.repeat(64);
      b.files[1].content = JSON.stringify(s);
      rehash(b);
    },
  ],
  [
    'duplicate names',
    (b) => {
      const s = JSON.parse(b.files[1].content);
      s.electrode_annotation.electrode_names[1] =
        s.electrode_annotation.electrode_names[0];
      b.files[1].content = JSON.stringify(s);
      rehash(b);
    },
  ],
  [
    'unsafe workflow',
    (b) => {
      b.project.workflow = {
        reference_entry_id: entryId,
        candidate_entry_id: null,
        comparison_href: 'https://example.com/',
      };
      rehash(b);
    },
  ],
])
  void test(`delivery reader rejects ${String(name)}`, async () => {
    const bundle = fixture({ named: true });
    mutate(bundle);
    await assert.rejects(openResearchDelivery(JSON.stringify(bundle)));
  });
void test('delivery reader rejects excess input and honours cancellation before parsing', async () => {
  await assert.rejects(
    openResearchDelivery(' '.repeat(DELIVERY_INPUT_LIMIT + 1)),
    /上限/,
  );
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    openResearchDelivery(JSON.stringify(fixture()), controller.signal),
    { name: 'AbortError' },
  );
  await assert.rejects(openResearchDelivery('not JSON'), /JSON/);
});

function editorFixture() {
  const b = fixture(),
    record = b.records[0],
    file = b.files[1];
  record.kind = 'editor';
  record.summary = { protocol: 'electrode-editor/1' };
  const result = {
    schema: 'electrode-editor/1',
    status: 'completed',
    electrode_count: 2,
    evaluated_xyz_mm: [
      [1, 2, 3],
      [4, 5, 6],
    ],
    edited_metrics: {
      field_relative: 0.9,
      sensitivity_tail: 0.8,
      localization_relative: 0.7,
    },
  };
  file.content = JSON.stringify({
    schema: 'research-project-snapshot/1',
    kind: 'editor',
    record_id: recordId,
    payload: {
      record: { key: recordId },
      cache: {
        key: recordId,
        result,
        result_sha256: sha(JSON.stringify(result)),
      },
    },
  });
  return rehash(b);
}
void test('completed editor delivery binds both saved keys and the result checksum', async () => {
  const b = editorFixture();
  assert.equal(
    (await openResearchDelivery(JSON.stringify(b))).entries[0].entry.kind,
    'editor',
  );
  for (const mutate of [
    (s) => {
      s.payload.cache.result.status = 'failed';
      s.payload.cache.result_sha256 = sha(
        JSON.stringify(s.payload.cache.result),
      );
    },
    (s) => {
      s.payload.cache.key = 'd'.repeat(64);
    },
    (s) => {
      s.payload.record.key = 'd'.repeat(64);
    },
    (s) => {
      s.payload.cache.result_sha256 = 'd'.repeat(64);
    },
  ]) {
    const changed = structuredClone(b),
      snapshot = JSON.parse(changed.files[1].content);
    mutate(snapshot);
    changed.files[1].content = JSON.stringify(snapshot);
    rehash(changed);
    await assert.rejects(
      openResearchDelivery(JSON.stringify(changed)),
      /编辑结果/,
    );
  }
});
void test('uploaded metric and summary display values retain their original scalar types', async () => {
  for (const mutate of [
    (b) => {
      const s = JSON.parse(b.files[1].content);
      s.payload.record.metrics.reference_median_mm = {};
      b.files[1].content = JSON.stringify(s);
    },
    (b) => {
      b.records[0].summary.protocol = {};
    },
  ]) {
    const b = fixture();
    mutate(b);
    rehash(b);
    await assert.rejects(openResearchDelivery(JSON.stringify(b)));
  }
});
void test('a layout summary saying whether signal simulation accepts the layout opens, and only as a boolean', async () => {
  for (const simulation of [true, false]) {
    const b = fixture();
    b.records[0].summary = { ...b.records[0].summary, simulation };
    rehash(b);
    const opened = await openResearchDelivery(JSON.stringify(b));
    assert.equal(opened.project.entries[0].summary.simulation, simulation);
  }
  for (const simulation of ['true', 1, null]) {
    const b = fixture();
    b.records[0].summary = { ...b.records[0].summary, simulation };
    rehash(b);
    await assert.rejects(openResearchDelivery(JSON.stringify(b)));
  }
});
