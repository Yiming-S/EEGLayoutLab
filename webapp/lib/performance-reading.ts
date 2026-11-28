import type { ComputeResult } from './local-compute';
import { assessment, METRICS } from './lab-workflow.ts';

export const METRIC_QUESTIONS = {
  field_relative: '当前布局能捕获目标实验场景多少比例的头皮空间电场信息？',
  sensitivity_tail: '对当前场景中接收最弱的10%脑源，电位差幅度保留了多少？',
  localization_relative: '基于这套电极采集的信号，对场景脑源定位的相对效用如何？',
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
  if (reading.gapPoints === 0) return '恰好位于参考线 τ';
  const distance = Math.abs(reading.gapPoints);
  // A rounded 0.00 must never imply equality when the raw value is below target.
  if (distance < 0.01) return reading.state === 'pass' ? '高于参考线不足0.01个百分点' : '低于参考线不足0.01个百分点';
  return reading.state === 'pass'
    ? `高于参考线 +${distance.toFixed(2)} 个百分点`
    : `距参考线 -${distance.toFixed(2)} 个百分点`;
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
