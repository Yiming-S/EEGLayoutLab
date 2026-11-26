'use client';

import type { ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import { useLanguage } from '@/components/language-provider';
import type { EditorResult } from '@/lib/electrode-editor';

function EditedMetricBar({
  edited,
  parent,
  unit,
  thresholdPct,
  maxMm,
}: {
  edited: number | null | undefined;
  parent: number | null | undefined;
  unit: 'percent' | 'mm';
  thresholdPct?: number;
  maxMm: number;
}) {
  if (edited == null || !Number.isFinite(edited)) return null;
  if (unit === 'mm') {
    const editedRatio = Math.max(0.015, Math.min(1, edited / maxMm)),
      parentRatio =
        parent != null && Number.isFinite(parent)
          ? Math.max(0, Math.min(1, parent / maxMm))
          : null,
      worse =
        parent != null && Number.isFinite(parent) && edited > parent + 1e-6;
    return (
      <span
        aria-hidden="true"
        className="relative mt-1 block h-1.5 w-28 overflow-hidden rounded-full bg-muted"
      >
        <span
          className={`block h-full rounded-full ${worse ? 'bg-warning' : 'bg-primary'}`}
          style={{ width: `${editedRatio * 100}%` }}
        />
        {parentRatio !== null && (
          <span
            className="absolute inset-y-0 w-0.5 bg-foreground/65"
            style={{ left: `calc(${parentRatio * 100}% - 1px)` }}
          />
        )}
      </span>
    );
  }
  const edPct = edited * 100,
    parPct = parent != null && Number.isFinite(parent) ? parent * 100 : null,
    lo =
      Math.min(0, edPct, parPct ?? 0) < 0
        ? Math.floor(Math.min(0, edPct, parPct ?? 0) / 10) * 10
        : 0,
    hi =
      Math.max(100, edPct, parPct ?? 100) > 100
        ? Math.ceil(Math.max(100, edPct, parPct ?? 100) / 10) * 10
        : 100,
    span = Math.max(1e-9, hi - lo),
    zeroPos = (0 - lo) / span,
    edPos = (edPct - lo) / span,
    parPos = parPct !== null ? (parPct - lo) / span : null,
    arPos = thresholdPct != null ? (thresholdPct - lo) / span : null,
    belowThreshold = thresholdPct != null && edPct < thresholdPct;
  return (
    <span
      aria-hidden="true"
      className="relative mt-1 block h-1.5 w-28 rounded-full bg-muted"
    >
      <span
        className={`absolute inset-y-0 rounded-full ${belowThreshold ? 'bg-warning' : 'bg-primary'}`}
        style={{
          left: `${Math.min(zeroPos, edPos) * 100}%`,
          width: `${Math.max(1, Math.abs(edPos - zeroPos) * 100)}%`,
        }}
      />
      {parPos !== null && (
        <span
          className="absolute -inset-y-0.5 w-0.5 bg-foreground/55"
          style={{ left: `calc(${parPos * 100}% - 1px)` }}
        />
      )}
      {arPos !== null && (
        <span
          className="absolute -inset-y-0.5 w-0.5 bg-primary"
          style={{ left: `calc(${arPos * 100}% - 1px)` }}
        />
      )}
    </span>
  );
}

function EditedDeltaBar({
  delta,
  parent,
  unit,
}: {
  delta: number | null;
  parent: number | null | undefined;
  unit: 'percent' | 'mm';
}) {
  if (delta == null || !Number.isFinite(delta)) return null;
  const zero = Math.abs(delta) < 0.005,
    improved = unit === 'mm' ? delta < 0 : delta > 0,
    denom = unit === 'percent' ? 25 : Math.max(Math.abs(parent ?? 0), 10),
    halfWidth = zero ? 0 : Math.min(1, Math.abs(delta) / denom) * 50;
  return (
    <span
      aria-hidden="true"
      className="relative mt-1 block h-1.5 w-24 overflow-hidden rounded-full bg-muted"
    >
      <span className="absolute inset-y-0 left-1/2 w-px bg-foreground/30" />
      {halfWidth > 0 && (
        <span
          className={`absolute inset-y-0 rounded-full ${improved ? 'bg-success' : 'bg-warning'}`}
          style={
            delta >= 0
              ? { left: '50%', width: `${halfWidth}%` }
              : { left: `${50 - halfWidth}%`, width: `${halfWidth}%` }
          }
        />
      )}
    </span>
  );
}

export function EditorComparisonSection({
  result,
  activeCount,
  ar,
  cached,
  exportResult,
  arControl,
}: {
  result: EditorResult | null | undefined;
  activeCount: number;
  ar: number;
  cached?: boolean;
  exportResult: () => void;
  arControl: ReactNode;
}) {
  const { tx } = useLanguage();
  const editorMaxMm = (() => {
    if (!result) return 30;
    const vals = (['median_mm', 'p90_mm'] as const)
      .flatMap((k) => [
        result.baseline[k],
        result.parent_metrics[k],
        result.edited_metrics[k],
      ])
      .filter(
        (v): v is number =>
          typeof v === 'number' && Number.isFinite(v) && v >= 0,
      );
    return vals.length ? Math.max(15, ...vals) * 1.12 : 30;
  })();

  return (
    <section className="lab-panel mt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">
          {tx('标准64、原始布局与编辑布局')}
        </h2>
        {result && (
          <span className="text-xs text-muted-foreground">
            {tx('原始64点竖线对照')} · τ {ar}%
          </span>
        )}
      </div>
      <p className="my-3 text-sm leading-6 text-muted-foreground">
        {tx(
          '三套布局按本次统一协议重新评价：同一头模与源先验、相同物理噪声、固定标准64重建目标。历史定位分数不直接混入此表。',
        )}
      </p>
      {!result ? (
        <p className="rounded-lg bg-muted p-4">
          {tx('当前草稿尚未评价。下方原评分不作为编辑后结果。')}
        </p>
      ) : (
        <>
          <div className="overflow-x-auto" data-editor-comparison-table>
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b">
                  <th className="p-3">{tx('评价指标')}</th>
                  {[
                    '标准全头64导',
                    '原始区域布局 · 64点',
                    `编辑布局 · ${activeCount}点`,
                    '相对原布局变化',
                  ].map((t) => (
                    <th className="p-3" key={t}>
                      {tx(t)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    ['field_absolute', '重建解释率（绝对）', 'percent', false],
                    ['field_relative', '场重建保留率', 'percent', true],
                    ['sensitivity_tail', '弱源敏感度', 'percent', true],
                    [
                      'localization_relative',
                      '定位效用保留率',
                      'percent',
                      true,
                    ],
                    ['median_mm', '定位误差中位数', 'mm', false],
                    ['p90_mm', '定位误差90分位数', 'mm', false],
                  ] as const
                ).map(([key, label, unit, usesThreshold]) => {
                  const a = result.edited_metrics[key],
                    b = result.parent_metrics[key],
                    delta =
                      a == null || b == null
                        ? null
                        : (a - b) * (unit === 'mm' ? 1 : 100),
                    improved =
                      delta != null &&
                      Math.abs(delta) >= 0.005 &&
                      (unit === 'mm' ? delta < 0 : delta > 0),
                    degraded =
                      delta != null &&
                      Math.abs(delta) >= 0.005 &&
                      (unit === 'mm' ? delta > 0 : delta < 0);
                  return (
                    <tr className="border-b" key={key}>
                      <th className="p-3 font-medium">{tx(label)}</th>
                      {[
                        result.baseline,
                        result.parent_metrics,
                        result.edited_metrics,
                      ].map((m, i) => (
                        <td className="p-3 font-mono tabular-nums" key={i}>
                          <div>
                            {m[key] == null
                              ? tx('指标无法计算')
                              : unit === 'mm'
                                ? `${m[key].toFixed(2)} mm`
                                : `${(m[key] * 100).toFixed(2)}%`}
                          </div>
                          {i === 2 && (
                            <EditedMetricBar
                              edited={a}
                              parent={b}
                              unit={unit}
                              thresholdPct={usesThreshold ? ar : undefined}
                              maxMm={editorMaxMm}
                            />
                          )}
                        </td>
                      ))}
                      <td
                        className={`p-3 font-mono tabular-nums ${
                          improved
                            ? 'text-success'
                            : degraded
                              ? 'text-warning'
                              : ''
                        }`}
                      >
                        <div>
                          {delta == null
                            ? '—'
                            : `${delta > 0 ? '+' : ''}${delta.toFixed(2)} ${unit === 'mm' ? 'mm' : tx('百分点')}`}
                        </div>
                        <EditedDeltaBar
                          delta={delta}
                          parent={
                            b != null ? b * (unit === 'mm' ? 1 : 100) : null
                          }
                          unit={unit}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {result.edited_metrics.localization_unavailable ===
            'single_contrast_unknown_amplitude' && (
            <p className="mt-3 text-sm">
              {tx(
                '两个电极只有一个参考无关维度；当前未知振幅定位模型无法辨识源位置，不提供三项共同达标结论。',
              )}
            </p>
          )}
          {arControl}
          <p className="mt-2 font-medium">
            {tx(
              result.edited_metrics.conditional_global == null
                ? '部分指标不可用，不能给出三项共同达标结论'
                : result.edited_metrics.conditional_global >= ar / 100
                  ? '三项均达到最低保留要求'
                  : '尚未全部达到最低保留要求',
            )}
          </p>
          <Button className="mt-4" variant="outline" onClick={exportResult}>
            {tx('导出本次评价JSON')}
          </Button>
          {cached && (
            <span className="ml-3 text-sm">{tx('本次评价读取有效缓存')}</span>
          )}
        </>
      )}
    </section>
  );
}
