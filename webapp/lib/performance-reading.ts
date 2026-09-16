import type { ComputeResult } from './local-compute';
import { assessment, METRICS } from './lab-workflow.ts';

export const METRIC_QUESTIONS = {
  field_relative: '只用这套电极，能把标准全头64导的信号还原到什么程度？',
  sensitivity_tail: '对相对接收最弱的那部分脑源，信号幅度还剩多少？',
  localization_relative: '根据收到的信号，能多好地判断脑源来自哪里？',
} as const;

/** Display-only interpretation. Never round or clamp a value before judging it. */
export function metricReading(value: number | null | undefined, thresholdPercent: number) {
  if (value === undefined) return { value, state: 'missing' as const, gapPoints: null };
  if (value === null || !Number.isFinite(value)) return { value, state: 'unavailable' as const, gapPoints: null };
  const threshold = thresholdPercent / 100;
  return {
    value,
    state: value >= threshold ? 'pass' as const : 'fail' as const,
    gapPoints: (value - threshold) * 100,
  };
}

export function marginText(reading: ReturnType<typeof metricReading>) {
  if (reading.gapPoints === null) return reading.state === 'missing' ? '尚未计算' : '指标无法计算';
  if (reading.gapPoints === 0) return '恰好达到最低保留要求';
  const distance = Math.abs(reading.gapPoints);
  // A rounded 0.00 must never imply equality when the raw value is below target.
  if (distance < 0.01) return reading.state === 'pass' ? '超过要求不足0.01个百分点' : '还差不足0.01个百分点';
  return reading.state === 'pass'
    ? `超过要求 ${distance.toFixed(2)} 个百分点`
    : `还差 ${distance.toFixed(2)} 个百分点`;
}

export function performanceReading(metrics: ComputeResult['metrics'], thresholdPercent: number) {
  const items = METRICS.map((metric) => ({
    ...metric,
    question: METRIC_QUESTIONS[metric.key],
    ...metricReading(metrics?.[metric.key], thresholdPercent),
  }));
  return {
    ...assessment(metrics, thresholdPercent),
    items,
    passed: items.filter((item) => item.state === 'pass').length,
    unavailable: items.filter((item) => item.state === 'missing' || item.state === 'unavailable').length,
  };
}
