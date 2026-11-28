'use client';
import { useLanguage } from '@/components/language-provider';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import type { ComputeResult } from '@/lib/local-compute';
import { methodLink } from '@/lib/lab-workflow';
import { marginText, performanceReading } from '@/lib/performance-reading';
import { metricPercent, metricDistance } from '@/lib/ui-language';
export const percent = metricPercent;
const mm = metricDistance;

function RetentionScaleTrack({
  value,
  ar,
  pass,
}: {
  value: number;
  ar: number;
  pass: boolean;
}) {
  const { tx } = useLanguage();
  const valPct = value * 100,
    lo = valPct < 0 ? Math.floor(valPct / 10) * 10 : 0,
    hi = valPct > 100 ? Math.ceil(valPct / 10) * 10 : 100,
    span = Math.max(1e-9, hi - lo),
    zeroRatio = (0 - lo) / span,
    valRatio = (valPct - lo) / span,
    arRatio = (ar - lo) / span,
    baseRatio = (100 - lo) / span,
    barStart = Math.min(zeroRatio, valRatio) * 100,
    barWidth = Math.max(0.8, Math.abs(valRatio - zeroRatio) * 100);
  return (
    <div aria-hidden="true" className="mt-2 space-y-1" data-retention-scale>
      <div className="relative h-2 w-full rounded-full bg-muted">
        {lo < 0 && (
          <span
            className="absolute -inset-y-0.5 w-px bg-foreground/35"
            style={{ left: `${zeroRatio * 100}%` }}
          />
        )}
        <span
          className={`absolute inset-y-0 rounded-full ${pass ? 'bg-primary' : 'bg-primary/60'}`}
          style={{ left: `${barStart}%`, width: `${barWidth}%` }}
        />
        <span
          className="absolute -inset-y-1 w-0.5 rounded-full bg-foreground/80"
          style={{ left: `calc(${arRatio * 100}% - 1px)` }}
        />
        {hi > 100 && (
          <span
            className="absolute -inset-y-0.5 w-px border-l border-dashed border-foreground/50"
            style={{ left: `${baseRatio * 100}%` }}
          />
        )}
      </div>
      <div className="flex justify-between font-mono text-[10px] tabular-nums text-muted-foreground">
        <span>{lo}%</span>
        <span>{tx(`参考线 τ ${ar}% · 64导刻度 100%`)}</span>
        <span>{hi}%</span>
      </div>
    </div>
  );
}

export function PerformanceSummary({
  metrics,
  ar,
  basis,
  returnHref,
  compact = false,
  emptyTitle = '等待评估',
  empty = '当前配置尚未评估。已有结果会自动读取；没有记录时，点击“开始布局计算”。',
}: {
  metrics: ComputeResult['metrics'];
  ar: number;
  basis: string;
  returnHref?: string;
  compact?: boolean;
  empty?: string;
  emptyTitle?: string;
}) {
  const { tx } = useLanguage();
  const result = performanceReading(metrics, ar);
  const hasGlobal =
    metrics?.conditional_global != null && Number.isFinite(metrics.conditional_global);
  const hasMedianMm =
    metrics?.median_mm != null && Number.isFinite(metrics.median_mm);
  const errorMax = (() => {
    if (!metrics) return 25;
    const finiteErrs = [
      metrics.median_mm,
      metrics.reference_median_mm,
      metrics.p90_mm,
    ].filter((v): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0);
    return finiteErrs.length ? Math.max(10, ...finiteErrs) * 1.12 : 25;
  })();
  return (
    <section className="lab-panel" aria-label={tx('当前场景仿真效能画像')}>
      <p className="lab-eyebrow">{tx('当前场景仿真效能画像')}</p>
      <div className="mt-2 flex flex-wrap items-baseline gap-2.5">
        <h2 className="text-xl font-semibold tracking-tight">
          {tx(
            !metrics
              ? emptyTitle
              : hasGlobal
                ? `综合下界 ${percent(metrics.conditional_global)}`
                : '三项场景仿真指标',
          )}
        </h2>
        {metrics && hasMedianMm && (
          <span className="rounded-md border border-border bg-secondary/70 px-2 py-0.5 font-mono text-xs font-medium text-foreground tabular-nums">
            {tx(`定位中位误差 ${mm(metrics.median_mm)}`)}
          </span>
        )}
      </div>
      {(!compact || !metrics || result.state === 'undefined') && (
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          {tx(
            !metrics
              ? empty
              : result.state === 'undefined'
                ? `有 ${result.unavailable} 项指标不可计算，请结合有效指标与定位误差综合评估。`
                : `共 ${result.passed}/3 项高于当前场景参考线（τ = ${ar}%）；轻便穿戴或局部脑区方案请结合目标区域效用与毫米级误差权衡。`,
          )}
        </p>
      )}
      {metrics && (
        <p className="mt-2 text-xs leading-5 text-muted-foreground">
          {tx(`场景参考线 τ = ${ar}% · 全头64导仅作100%归一化刻度，不作硬性及格限制`)}
        </p>
      )}
      {tx(
        metrics && (
          <>
            <div className={compact ? 'mt-3 space-y-2' : 'mt-5 space-y-3'}>
              {result.items.map((item) => {
                const pass = item.state === 'pass',
                  valid = pass || item.state === 'fail',
                  hasFinite = item.value != null && Number.isFinite(item.value);
                return (
                  <div
                    key={item.key}
                    className={`rounded-xl border bg-background/70 ${compact ? 'p-3' : 'p-4'}`}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <h3 className="text-sm font-semibold">{tx(item.label)}</h3>
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-medium ${pass ? 'bg-primary/10 text-primary' : valid ? 'bg-secondary text-ink-soft' : 'bg-secondary text-muted-foreground'}`}
                      >
                        {tx(!valid ? '无法判断' : pass ? '高于参考线' : '低于参考线')}
                      </span>
                    </div>
                    <p
                      className={
                        compact
                          ? 'mt-1 text-xs leading-5 text-muted-foreground'
                          : 'mt-2 text-sm leading-6 text-muted-foreground'
                      }
                    >
                      {tx(item.question)}
                    </p>
                    <p
                      className={`${compact ? 'mt-1 text-2xl' : 'mt-3 text-3xl'} break-words font-mono font-semibold tracking-tight tabular-nums`}
                    >
                      {tx(percent(item.value))}
                    </p>
                    {hasFinite && (
                      <RetentionScaleTrack value={item.value!} ar={ar} pass={pass} />
                    )}
                    <p
                      className={`mt-1.5 ${compact ? 'text-xs' : 'text-sm'} font-medium ${pass ? 'text-primary' : 'text-muted-foreground'}`}
                    >
                      {tx(marginText(item))}
                    </p>
                  </div>
                );
              })}
            </div>
            <dl
              className={`${compact ? 'mt-3 space-y-2.5 pt-3 text-xs' : 'mt-6 space-y-3 pt-4 text-sm'} border-t`}
              data-localization-error-bars
            >
              {(
                [
                  ['当前布局定位中位误差', metrics.median_mm, 'bg-primary/80'],
                  ['64导参考刻度定位中位误差', metrics.reference_median_mm, 'bg-sky-600/75 dark:bg-sky-400/75'],
                  ['当前布局定位90分位误差', metrics.p90_mm, 'bg-amber-600/80 dark:bg-amber-400/80'],
                ] as const
              ).map(([label, val, colorClass]) => {
                const finiteVal = typeof val === 'number' && Number.isFinite(val) && val >= 0;
                const widthRatio = finiteVal ? Math.min(1, val / errorMax) : 0;
                return (
                  <div key={label} className="space-y-1">
                    <div className="flex justify-between gap-2">
                      <dt>{tx(label)}</dt>
                      <dd className="font-mono">{tx(mm(val))}</dd>
                    </div>
                    {finiteVal && (
                      <div aria-hidden="true" className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                        <div
                          className={`h-full rounded-full ${colorClass}`}
                          style={{ width: `${Math.max(1.5, widthRatio * 100)}%` }}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </dl>
            <details className="mt-5 rounded-xl border p-4 text-sm">
              <summary className="cursor-pointer font-semibold">{tx('评分口径与刻度说明')}</summary>
              <div className="mt-3 space-y-4">
                {result.items.map((item) => (
                  <div key={item.key}>
                    <h3 className="font-medium">{tx(item.label)}</h3>
                    <p className="mt-1 leading-6 text-muted-foreground">
                      {tx(item.explanation)}
                      {tx('；以同条件全头64导记作100%参考刻度。')}
                    </p>
                    <p className="mt-1 break-all text-xs text-muted-foreground">
                      {tx('原始相对比值：')}{' '}
                      <code>
                        {item.value != null && Number.isFinite(item.value)
                          ? String(item.value)
                          : tx(percent(item.value))}
                      </code>
                    </p>
                  </div>
                ))}
                <div className="border-t pt-3">
                  <p className="flex justify-between gap-3">
                    <span>{tx('三项最低相对评分 G')}</span>
                    <span className="font-mono">{tx(percent(metrics.conditional_global))}</span>
                  </p>
                  <p className="mt-2 leading-6 text-muted-foreground">
                    {tx('G取三项中的短板值，便于跨方案横向比较整体下界。')}
                  </p>
                  <p className="mt-2 leading-6 text-muted-foreground">
                    {tx('此结果对应当前所选头模、脑源先验与实验条件。')}
                  </p>
                </div>
              </div>
            </details>
          </>
        ),
      )}
      <p className="mt-5 border-t pt-3 text-xs leading-5 text-muted-foreground">
        {tx(basis)}
        {tx('。三项相对效用以同条件64导作100%刻度归一；参考线按完整精度数值对照。')}
      </p>
      <a
        href={methodLink(returnHref ?? '/?ar=' + ar, ar, '#retention-guide')}
        className="mt-3 inline-block text-sm font-semibold text-primary underline underline-offset-4"
      >
        {tx('三项相对指标如何计算？→')}
      </a>
    </section>
  );
}
