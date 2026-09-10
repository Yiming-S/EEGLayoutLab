import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';
import {
  allocationFor,
  arDecision,
  bestVariant,
  checkSingleHeadResults,
  metricAt,
} from '../lib/single-head-results.ts';

// Test-only synthetic values; these are never served as experimental data.
function metric(snr, field = 0.85, sens = 0.7, loc = 0.8) {
  return {
    snr_db: snr,
    field_relative: field,
    field_absolute: field * 0.95,
    sensitivity_tail: sens,
    localization_relative: loc,
    localization_utility: loc == null ? null : loc * 0.5,
    conditional_global: [field, sens, loc].every((v) => v != null)
      ? Math.min(field, sens, loc)
      : null,
    median_mm: 10,
    p90_mm: 20,
    p95_mm: 30,
    effective_rank: 12,
  };
}
function fixture() {
  const xyz = Array.from({ length: 64 }, (_, i) => [i, i % 7, i % 11]);
  return {
    schema: 'single-head-app/1',
    scope: {
      head_count: 1,
      physical_electrode_count: 64,
      formal_ar: false,
      conditional_ar: true,
    },
    baseline: { xyz_mm: xyz },
    conditions: Array.from({ length: 204 }, (_, i) => {
      const R = [1, 2, 3, 4, 6][i % 5];
      return {
        id: `fixture-${i}`,
        R,
        status: 'completed_best_found',
        variants: [
          {
            id: `layout-${i}`,
            xyz_mm: xyz,
            region_indices: allocationFor(R).flatMap((n, r) =>
              Array(n).fill(r),
            ),
            conditions: [0, 10, 20].map((s) => metric(s)),
          },
        ],
      };
    }),
  };
}
void test('balanced allocation always totals 64 with no fractional channels', () => {
  assert.deepEqual(allocationFor(3), [22, 21, 21]);
  assert.deepEqual(allocationFor(6), [11, 11, 11, 11, 10, 10]);
  for (const r of [1, 2, 3, 4, 6])
    assert.equal(
      allocationFor(r).reduce((a, b) => a + b),
      64,
    );
});
void test('all 204 terminal records and all five region counts are required', () => {
  assert.equal(checkSingleHeadResults(fixture()).conditions.length, 204);
  const d = fixture();
  d.conditions.pop();
  assert.throws(() => checkSingleHeadResults(d));
});
void test('AR uses all three metrics, selected SNR, inclusive threshold and null propagation', () => {
  assert.equal(arDecision(metric(20), 0.7), 'pass');
  assert.equal(arDecision(metric(20), 0.701), 'fail');
  assert.equal(arDecision(metric(20, 0.99, 0.99, null), 0.2), 'undefined');
  assert.equal(arDecision(undefined, 0.2), 'undefined');
  const variant = {
    conditions: [metric(0, 0.9, 0.9, 0.4), metric(20, 0.9, 0.9, 0.95)],
  };
  assert.equal(arDecision(metricAt(variant, 0), 0.8), 'fail');
  assert.equal(arDecision(metricAt(variant, 20), 0.8), 'pass');
  assert.equal(metricAt(variant, 15), undefined);
});
void test('missing or forged global values are rejected; values above one are not clipped', () => {
  const d = fixture();
  d.conditions[0].variants[0].conditions[0].conditional_global = 0.99;
  assert.throws(() => checkSingleHeadResults(d));
  const e = fixture();
  e.conditions[0].variants[0].conditions[0] = metric(0, 1.02, 1.1, 1.05);
  assert.equal(
    checkSingleHeadResults(e).conditions[0].variants[0].conditions[0]
      .conditional_global,
    1.02,
  );
});
void test('duplicate points and incorrectly balanced labels are rejected', () => {
  const d = fixture();
  d.conditions[0].variants[0].xyz_mm = [...d.conditions[0].variants[0].xyz_mm];
  d.conditions[0].variants[0].xyz_mm[1] = d.conditions[0].variants[0].xyz_mm[0];
  assert.throws(() => checkSingleHeadResults(d));
  const e = fixture();
  e.conditions[1].variants[0].region_indices[0] = 1;
  assert.throws(() => checkSingleHeadResults(e));
});
void test('branch choice ranks actual selected metric without modifying source array', () => {
  const a = { id: 'a', conditions: [metric(20, 0.95, 0.4, 0.8)] },
    b = { id: 'b', conditions: [metric(20, 0.8, 0.7, 0.8)] };
  const c = { variants: [a, b] };
  assert.equal(bestVariant(c, 20, 'field_relative'), a);
  assert.equal(bestVariant(c, 20, 'conditional_global'), b);
  assert.deepEqual(c.variants, [a, b]);
  assert.equal(bestVariant(c, 15, 'field_relative'), undefined);
});
const published = new URL(
  '../public/data/single_head_optimization.json',
  import.meta.url,
);
void test(
  'published real experiment passes frontend schema and scope checks',
  { skip: !existsSync(published) },
  () => {
    const d = checkSingleHeadResults(
      JSON.parse(readFileSync(published, 'utf8')),
    );
    assert.equal(d.conditions.length, 204);
    assert.equal(d.provenance.report_sha256.length, 64);
  },
);
