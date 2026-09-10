import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  atSnr,
  checkResults,
  mriMmToDisplay,
  RESULT_FAMILIES,
  retentionPercent,
  selectRecordedLayout,
} from '../lib/fixed64-results.ts';

const raw = readFileSync(
  new URL('../public/data/fixed64_results.json', import.meta.url),
  'utf8',
);
const data = checkResults(JSON.parse(raw));

void test('export contains 28 configurations, 26 unique layouts and one head', () => {
  assert.equal(data.layouts.length, 28);
  assert.equal(data.configuration_count, 28);
  assert.equal(data.head_count, 1);
  const keys = data.layouts.map((layout) =>
    layout.xyz_mm
      .map((xyz) => xyz.join(','))
      .sort()
      .join(';'),
  );
  assert.equal(new Set(keys).size, 26);
  assert.equal(data.unique_layout_count, 26);
  assert.equal(data.formal_ar, false);
  assert.equal(data.provenance.byte_reproducible, true);
  assert.equal(data.provenance.repeat_batches.length, 2);
});

void test('every computed configuration maps to 64 distinct coordinates and 32+32 allocation', () => {
  assert.equal(data.reference.xyz_mm.length, 64);
  for (const layout of data.layouts) {
    assert.equal(new Set(layout.xyz_mm.map((p) => p.join(','))).size, 64);
    assert.equal(layout.region_indices.filter((r) => r === 0).length, 32);
    assert.equal(layout.region_indices.filter((r) => r === 1).length, 32);
    assert.equal(
      selectRecordedLayout(
        data,
        layout.family_id,
        layout.radius_cap_mm,
        layout.spacing_min_mm,
      ),
      layout,
    );
  }
});

void test('unconstructed and intermediate configurations return null, never interpolated scores', () => {
  for (const family of RESULT_FAMILIES) {
    assert.equal(selectRecordedLayout(data, family.id, 20, 6), null);
    assert.equal(selectRecordedLayout(data, family.id, 35, 6), null);
    assert.equal(selectRecordedLayout(data, family.id, 30, 5), null);
  }
  assert.equal(selectRecordedLayout(data, 'uncomputed-family', 30, 6), null);
});

void test('only the four geometry-prefrozen 30 mm / 6 mm prototypes contain localization', () => {
  const localized = data.layouts.filter(
    (layout) => layout.localization !== null,
  );
  assert.deepEqual(
    localized.map((layout) => layout.index),
    [2, 9, 16, 23],
  );
  for (const layout of localized) {
    assert.equal(layout.radius_cap_mm, 30);
    assert.equal(layout.spacing_min_mm, 6);
    assert.deepEqual(
      layout.localization.map((loc) => loc.snr_db),
      [0, 10, 20],
    );
  }
  assert.equal(
    data.layouts.filter((layout) => layout.localization === null).length,
    24,
  );
  assert.equal(atSnr(null, 20), null);
  assert.equal(atSnr(data.reference.localization, 15), null);
});

void test('relative field values use the noisy baseline denominator; baseline absolute is not 100%', () => {
  for (const snr of data.snr_db) {
    const baseline = atSnr(data.reference.metrics.conditions, snr);
    assert.equal(baseline.field_relative, 1);
    assert.ok(baseline.field_absolute > 0 && baseline.field_absolute < 1);
    for (const layout of data.layouts) {
      const condition = atSnr(layout.metrics.conditions, snr);
      assert.ok(
        Math.abs(
          condition.field_relative -
            condition.field_absolute / baseline.field_absolute,
        ) < 1e-12,
      );
    }
  }
});

void test('default displayed values agree with the audited bilateral near-ear prototype', () => {
  const layout = selectRecordedLayout(data, RESULT_FAMILIES[0].id, 30, 6);
  const condition = atSnr(layout.metrics.conditions, 20);
  assert.equal(retentionPercent(condition.field_relative), '55.53%');
  assert.equal(retentionPercent(condition.field_absolute), '55.15%');
  assert.equal(retentionPercent(layout.metrics.sensitivity_tail), '13.05%');
  assert.equal(atSnr(layout.localization, 20).p90_mm.toFixed(2), '55.60');
});

void test('MRI conversion preserves axes, signs and exact linear scale without projection', () => {
  assert.deepEqual(mriMmToDisplay([-75, 50, 120]), [-0.75, 0.5, 1.2]);
  for (const xyz of [
    ...data.reference.xyz_mm,
    ...data.layouts.flatMap((layout) => layout.xyz_mm),
  ]) {
    const display = mriMmToDisplay(xyz);
    xyz.forEach((value, axis) => assert.equal(display[axis], value / 100));
  }
  assert.throws(() => mriMmToDisplay([NaN, 0, 0]));
});

void test('missing metrics are not rendered as zeros and values above 100% are not clipped', () => {
  assert.equal(retentionPercent(null), '未计算');
  assert.equal(retentionPercent(undefined), '未计算');
  assert.equal(retentionPercent(NaN), '未计算');
  assert.equal(retentionPercent(0), '0.00%');
  assert.equal(retentionPercent(1.05), '105.00%');
});

void test('loader rejects malformed data, false evidence labels and non-64 coordinate sets', () => {
  for (const value of [
    null,
    {},
    [],
    { ...data, formal_ar: true },
    { ...data, head_count: 2 },
    { ...data, schema_version: 'unknown' },
  ]) {
    assert.throws(() => checkResults(value));
  }
  for (const mutate of [
    (copy) => {
      copy.layouts[0].xyz_mm.pop();
    },
    (copy) => {
      copy.layouts[0].xyz_mm[0][0] = null;
    },
    (copy) => {
      copy.layouts[0].region_indices[0] = 1;
    },
    (copy) => {
      copy.layouts[0].metrics.conditions[0].field_relative = null;
    },
    (copy) => {
      copy.reference.localization = null;
    },
  ]) {
    const copy = structuredClone(data);
    mutate(copy);
    assert.throws(() => checkResults(copy));
  }
});

void test('public payload contains hashes but no local home paths', () => {
  assert.doesNotMatch(raw, /\/Users\/|\/home\//);
  for (const key of ['report_sha256', 'forward_sha256', 'metrics_sha256']) {
    assert.match(data.provenance[key], /^[a-f0-9]{64}$/);
  }
});
