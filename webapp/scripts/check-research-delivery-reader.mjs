import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { buildResearchDelivery } from '../server/delivery/research-bundle.mjs';
import {
  openResearchDelivery,
  DELIVERY_INPUT_LIMIT,
} from '../features/projects/research-delivery-reader.ts';
const sha = (value) => createHash('sha256').update(value).digest('hex');
const id = '18358bf4-143e-4431-8456-b99328462b37';
const entryId = '18358bf4-143e-4431-8456-b99328462b38';
const recordId = 'a'.repeat(64),
  annotationId = 'b'.repeat(64),
  date = '2026-11-14T12:00:00.000Z';
function fixture({ named = false, legacy = false } = {}) {
  const snapshot = {
    schema: 'research-project-snapshot/1',
    kind: 'layout',
    record_id: recordId,
    payload: {
      record: {
        id: recordId,
        layout: {
          xyzMm: Array.from({ length: 64 }, (_, i) => [i, i / 3, -i]),
          regionIndices: Array.from({ length: 64 }, (_, i) => i % 2),
        },
        metrics: {
          field_relative: 0.975,
          sensitivity_tail: null,
          localization_relative: 1.001,
          ...(legacy ? {} : { median_mm: 1.234, p90_mm: 3.456 }),
        },
      },
    },
    ...(named
      ? {
          electrode_annotation: {
            schema: 'eeg-electrode-annotation/1',
            id: annotationId,
            record_id: recordId,
            request_sha256: 'c'.repeat(64),
            electrode_names: Array.from(
              { length: 64 },
              (_, i) => `名称, "${i}"`,
            ),
          },
        }
      : {}),
  };
  const snapshot_json = JSON.stringify(snapshot, null, 2) + '\n';
  const entry = {
    id: entryId,
    kind: 'layout',
    title: 'Original layout',
    notes: '<script>never executed</script>',
    record_id: recordId,
    ...(named ? { annotation_id: annotationId } : {}),
    created_at: date,
    snapshot_bytes: Buffer.byteLength(snapshot_json),
    snapshot_sha256: sha(snapshot_json),
    summary: { protocol: 'design_evaluation' },
  };
  const project = {
    schema: 'research-project/1',
    id,
    title: 'Delivery',
    owner_name: 'Researcher',
    notes: 'Saved evidence',
    revision: 1,
    created_at: date,
    updated_at: date,
    entries: [entry],
  };
  return buildResearchDelivery(
    { project, entries: [{ entry, snapshot_json }] },
    { application_version: '0.1.2' },
    { now: () => date },
  );
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
