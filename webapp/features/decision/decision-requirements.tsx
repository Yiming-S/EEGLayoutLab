'use client';

import { useLanguage } from '@/components/language-provider';
import {
  decisionCriteriaSummary,
  decisionThresholdMode,
  jointDecisionThresholds,
  type DecisionThresholds,
} from '@/lib/design-decision';

export function DecisionRequirements({
  thresholds,
  onChange,
}: {
  thresholds: DecisionThresholds;
  onChange: (thresholds: DecisionThresholds) => void;
}) {
  const { tx } = useLanguage();
  const joint = decisionThresholdMode(thresholds) === 'joint';
  return (
    <section className="lab-panel" aria-label={tx('判定要求')}>
      <h2 className="text-lg font-semibold">{tx('判定要求')}</h2>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <label className="lab-label">
          {tx('判定方式')}
          <select
            className="lab-select mt-2"
            value={joint ? 'joint' : 'custom'}
            onChange={(e) => onChange(e.target.value === 'joint'
              ? jointDecisionThresholds(thresholds.field)
              : { ...thresholds, mode: 'custom' })}
          >
            <option value="joint">{tx('三项共同要求（与实验总览一致）')}</option>
            <option value="custom">{tx('自定义各项要求')}</option>
          </select>
        </label>
        <label className="lab-label">
          {tx(joint ? '三项最低保留要求（%）' : '场重建保留率下限（%）')}
          <input
            className="lab-select mt-2"
            type="number"
            min={joint ? 10 : 1}
            max={100}
            value={thresholds.field}
            onChange={(e) => {
              const field = Number(e.target.value);
              if (Number.isInteger(field) && field >= (joint ? 10 : 1) && field <= 100)
                onChange(joint ? jointDecisionThresholds(field) : { ...thresholds, field });
            }}
          />
        </label>
      </div>
      {!joint && (
        <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {([
            ['sensitivity', '幅度保留率下限（%）'],
            ['localization', '相对定位评分下限（%）'],
            ['p90_mm', '定位误差P90上限（mm）'],
          ] as const).map(([key, label]) => (
            <label className="lab-label" key={key}>
              {tx(label)}
              <input
                className="lab-select mt-2"
                type="number"
                min={0}
                max={key === 'p90_mm' ? 500 : 100}
                placeholder={tx('不启用')}
                value={thresholds[key] ?? ''}
                onChange={(e) => {
                  const value = Number(e.target.value);
                  if (e.target.value === '' || (Number.isFinite(value) && value >= 0 && value <= (key === 'p90_mm' ? 500 : 100)))
                    onChange({ ...thresholds, [key]: e.target.value === '' ? null : value });
                }}
              />
            </label>
          ))}
        </div>
      )}
      <p className="mt-3 text-sm font-medium" aria-live="polite">{tx(decisionCriteriaSummary(thresholds))}</p>
      <p className="mt-2 text-sm text-muted-foreground">{tx('修改要求只重新判断现有指标，不启动计算。自定义模式下，留空的指标不参与判定。')}</p>
    </section>
  );
}
