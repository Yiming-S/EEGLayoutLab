import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { metricReading, marginText, performanceReading, METRIC_QUESTIONS } from '../lib/performance-reading.ts';
import { assessment, METRICS } from '../lib/lab-workflow.ts';
import { metricPercent } from '../lib/ui-language.ts';

await test('metric status uses original precision, with equality passing', () => {
  assert.equal(metricReading(0.9, 90).state, 'pass');
  assert.equal(metricReading(0.899999999999, 90).state, 'fail');
  assert.equal(metricReading(0.900000000001, 90).state, 'pass');
  assert.equal(marginText(metricReading(0.9, 90)), '恰好达到最低保留要求');
  assert.equal(marginText(metricReading(0.899999999999, 90)), '还差不足0.01个百分点');
  assert.equal(marginText(metricReading(0.900000000001, 90)), '超过要求不足0.01个百分点');
  assert.equal(metricPercent(0.899999999999), '90.00%');
});

await test('margins are percentage points, not percent error or a clipped progress bar', () => {
  assert.ok(Math.abs(metricReading(0.72, 90).gapPoints + 18) < 1e-12);
  assert.equal(marginText(metricReading(0.72, 90)), '还差 18.00 个百分点');
  assert.equal(marginText(metricReading(0.95, 90)), '超过要求 5.00 个百分点');
  assert.equal(metricReading(-0.25, 90).value, -0.25);
  assert.equal(metricPercent(-0.25), '-25.00%');
  assert.equal(marginText(metricReading(-0.25, 90)), '还差 115.00 个百分点');
  assert.equal(metricReading(1.25, 90).value, 1.25);
  assert.equal(metricPercent(1.25), '125.00%');
  assert.equal(marginText(metricReading(1.25, 90)), '超过要求 35.00 个百分点');
});

await test('missing and unavailable metrics never become zero or pass', () => {
  assert.equal(metricReading(undefined, 90).state, 'missing');
  assert.equal(marginText(metricReading(undefined, 90)), '尚未计算');
  for (const value of [null, NaN, Infinity, -Infinity]) {
    const reading = metricReading(value, 90);
    assert.equal(reading.state, 'unavailable');
    assert.equal(reading.gapPoints, null);
    assert.equal(marginText(reading), '指标无法计算');
  }
});

await test('individual status never replaces the existing joint assessment', () => {
  for (const metrics of [
    null,
    undefined,
    { field_relative: 0.95, sensitivity_tail: 0.5, localization_relative: 0.92 },
    { field_relative: 0.95, sensitivity_tail: null, localization_relative: 0.92 },
    { field_relative: 0.95, sensitivity_tail: 0.91, localization_relative: 1.2 },
  ]) {
    const before = metrics && { ...metrics };
    const result = performanceReading(metrics, 90);
    assert.equal(result.state, assessment(metrics, 90).state);
    assert.deepEqual(result.limiting, assessment(metrics, 90).limiting);
    if (metrics) assert.deepEqual(metrics, before);
  }
  assert.equal(performanceReading({ field_relative: 0.95, sensitivity_tail: 0.5, localization_relative: 0.92 }, 90).passed, 2);
  const incomplete = performanceReading({ field_relative: 0.95, sensitivity_tail: null, localization_relative: 0.92 }, 90);
  assert.equal(incomplete.passed, 2);
  assert.equal(incomplete.unavailable, 1);
  assert.equal(incomplete.state, 'undefined');
});

await test('every metric keeps its explanation and bilingual plain-language question', async () => {
  const component = await readFile(new URL('../components/performance-summary.tsx', import.meta.url), 'utf8');
  const catalog = JSON.parse(await readFile(new URL('../lib/i18n/catalog.json', import.meta.url), 'utf8'));
  const entries = Object.values(catalog);
  for (const metric of METRICS) {
    assert.ok(METRIC_QUESTIONS[metric.key]);
    const entry = entries.find((entry) => entry.source === METRIC_QUESTIONS[metric.key]);
    assert.ok(entry?.en && !/[\u3400-\u9fff]/.test(entry.en));
  }
  for (const text of ['<details', 'item.explanation', 'metrics.p90_mm', 'metrics.reference_median_mm', 'metrics.conditional_global', 'String(item.value)', "methodLink(returnHref ?? '/?ar=' + ar, ar, '#retention-guide')"]) assert.ok(component.includes(text), text);
  assert.ok(!component.includes('Math.min(100'));
  assert.ok(!component.includes('/api/'));
});
