import test from 'node:test';
import assert from 'node:assert/strict';
import { empiricalSummary, summarizeStudyCase, aggregateStudy } from '../server/studies/protocol.mjs';

void test('type7 empirical quantiles interpolate known finite observations and retain the actual count', () => {
  const known = empiricalSummary([30, 0, 20, 10]);
  assert.equal(known.n, 4); assert.equal(known.median, 15); assert.equal(known.p90, 27);
  assert.ok(Math.abs(known.p10 - 3) <= 4 * Number.EPSILON);
  assert.deepEqual(empiricalSummary([null, undefined, NaN, Infinity]), { n: 0, median: null, p10: null, p90: null });
  assert.deepEqual(empiricalSummary([.125, null]), { n: 1, median: .125, p10: .125, p90: .125 });
});
const trial = value => value === null ? { status: 'geometry_rejected', field_relative: null, fixed_estimator_field_relative: null } : { status: 'completed', field_relative: value, fixed_estimator_field_relative: value, sensitivity_tail: value };
const result = values => ({ nominal: { field_relative: .75, sensitivity_tail: .5, localization_relative: null }, trials: values.map(trial) });
void test('position-study distribution gives each case equal weight while keeping every rejected trial', () => {
  const a = result([0, 0, 0, 0]), b = result([100, null, null, null]);
  const before = JSON.stringify([a, b]);
  const cases = [
    { request: { radius_mm: 3 }, status: 'completed', summary: summarizeStudyCase(a) },
    { request: { radius_mm: 3 }, status: 'completed', summary: summarizeStudyCase(b) },
    { request: { radius_mm: 3 }, status: 'failed', summary: null, error: { code: 'child_failed' } },
    { request: { radius_mm: 3 }, status: 'cancelled', summary: null },
    { request: { radius_mm: 6 }, status: 'pending', summary: null },
  ];
  const copy = structuredClone(cases), report = aggregateStudy('grid_displacements', cases);
  assert.equal(report.case_count, 5); assert.equal(report.completed_cases, 2); assert.equal(report.failed_cases, 1); assert.equal(report.cancelled_cases, 1); assert.equal(report.pending_cases, 1);
  assert.deepEqual(report.groups[0].trial_case_medians.field_relative, { n: 2, median: 50, p10: 10, p90: 90 });
  assert.equal(report.groups[0].nominal.localization_relative.n, 0);
  assert.equal(report.groups[1].trial_case_medians.field_relative.median, null);
  assert.equal(cases[1].summary.rejected_trials, 3); assert.equal(cases[1].summary.trials.length, 4);
  assert.equal(JSON.stringify([a, b]), before); assert.deepEqual(cases, copy);
});
void test('an all-rejected position case stays completed with zero finite trial readings', () => {
  const summary = summarizeStudyCase(result([null, null, null, null]));
  assert.equal(summary.valid_trials, 0); assert.equal(summary.rejected_trials, 4);
  assert.deepEqual(summary.trial_metrics.field_relative, { n: 0, median: null, p10: null, p90: null });
  const report = aggregateStudy('grid_displacements', [{ request: { radius_mm: 10 }, status: 'completed', summary }]);
  assert.equal(report.completed_cases, 1); assert.equal(report.groups[0].trial_case_medians.field_relative.n, 0);
});
