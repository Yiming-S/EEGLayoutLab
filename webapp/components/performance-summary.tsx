'use client';
import { useLanguage } from '@/components/language-provider';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import type { ComputeResult } from '@/lib/local-compute';
import { methodLink } from '@/lib/lab-workflow';
import { marginText, performanceReading } from '@/lib/performance-reading';
import { metricPercent, metricDistance } from '@/lib/ui-language';
export const percent = metricPercent;
const mm = metricDistance;
export function PerformanceSummary({ metrics, ar, basis, returnHref, compact = false, emptyTitle = '等待评估', empty = '当前配置尚未评估。已有结果会自动读取；没有记录时，点击“开始布局计算”。' }: {
  metrics: ComputeResult['metrics']; ar: number; basis: string; returnHref?: string; compact?: boolean; empty?: string; emptyTitle?: string;
}) {
  const { tx } = useLanguage();
  const result = performanceReading(metrics, ar);
  return <section className="lab-panel" aria-label={tx("方案性能与64导对照")}>
    <p className="lab-eyebrow">{tx("与标准全头64导相比")}</p>
    <h2 className="mt-2 text-xl font-semibold">{tx(!metrics ? emptyTitle : `已达标 ${result.passed}/3 项`)}</h2>
    {(!compact || !metrics || result.state === 'undefined') && <p className="mt-2 text-sm leading-6 text-muted-foreground">{tx(!metrics ? empty : result.state === 'pass' ? '三项均达到最低保留要求。' : result.state === 'undefined' ? `有 ${result.unavailable} 项无法判断，尚不能确认三项共同达标。` : '尚未三项共同达标；下方分别显示达标项和差距。')}</p>}
    {metrics && <p className="mt-2 text-sm font-medium">{tx(`本次最低保留要求：${ar}% · 三项分别判断`)}</p>}
    {tx(metrics && <>
      <div className={compact ? 'mt-3 space-y-2' : 'mt-5 space-y-3'}>{result.items.map((item) => {
        const pass = item.state === 'pass', valid = pass || item.state === 'fail';
        return <div key={item.key} className={`rounded-xl border bg-background/70 ${compact ? 'p-3' : 'p-4'}`}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <h3 className="text-sm font-semibold">{tx(item.label)}</h3>
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${pass ? 'bg-primary/10 text-primary' : valid ? 'bg-warning-surface text-warning' : 'bg-secondary text-muted-foreground'}`}>{tx(!valid ? '无法判断' : pass ? '达标' : '未达标')}</span>
          </div>
          <p className={compact ? 'mt-1 text-xs leading-5 text-muted-foreground' : 'mt-2 text-sm leading-6 text-muted-foreground'}>{tx(item.question)}</p>
          <p className={`${compact ? 'mt-1 text-2xl' : 'mt-3 text-3xl'} break-words font-mono font-semibold tracking-tight tabular-nums`}>{tx(percent(item.value))}</p>
          <p className={`mt-1 ${compact ? 'text-xs' : 'text-sm'} font-medium ${pass ? 'text-primary' : valid ? 'text-warning' : 'text-muted-foreground'}`}>{tx(marginText(item))}</p>
        </div>;
      })}</div>
      <dl className={`${compact ? 'mt-3 space-y-2 pt-3 text-xs' : 'mt-6 space-y-3 pt-4 text-sm'} border-t`}>
        <div className="flex justify-between gap-2"><dt>{tx("当前布局定位中位误差")}</dt><dd className="font-mono">{tx(mm(metrics.median_mm))}</dd></div>
        <div className="flex justify-between gap-2"><dt>{tx("标准64导定位中位误差")}</dt><dd className="font-mono">{tx(mm(metrics.reference_median_mm))}</dd></div>
        <div className="flex justify-between gap-2"><dt>{tx("当前布局定位90分位误差")}</dt><dd className="font-mono">{tx(mm(metrics.p90_mm))}</dd></div>
      </dl>
      <details className="mt-5 rounded-xl border p-4 text-sm">
        <summary className="cursor-pointer font-semibold">{tx('评分口径与联合判断')}</summary>
        <div className="mt-3 space-y-4">
          {result.items.map((item) => <div key={item.key}>
            <h3 className="font-medium">{tx(item.label)}</h3>
            <p className="mt-1 leading-6 text-muted-foreground">{tx(item.explanation)}{tx("；全头基准为100%。")}</p>
            <p className="mt-1 break-all text-xs text-muted-foreground">{tx('原始相对比值：')} <code>{item.value != null && Number.isFinite(item.value) ? String(item.value) : tx(percent(item.value))}</code></p>
          </div>)}
          <div className="border-t pt-3">
            <p className="flex justify-between gap-3"><span>{tx("三项最低相对评分 G")}</span><span className="font-mono">{tx(percent(metrics.conditional_global))}</span></p>
            <p className="mt-2 leading-6 text-muted-foreground">{tx('G取三项最低值，仅用于三项联合判断；单项达标不代表三项共同达标。')}</p>
            <p className="mt-2 leading-6 text-muted-foreground">{tx('此结论只适用于本记录的头模与实验条件。')}</p>
          </div>
        </div>
      </details>
    </>)}
    <p className="mt-5 border-t pt-3 text-xs leading-5 text-muted-foreground">{tx(basis)}{tx("。三项指标以标准64导归一化为100%；阈值按完整精度数值判断。")}</p>
    <a href={methodLink(returnHref ?? '/?ar=' + ar, ar, '#retention-guide')} className="mt-3 inline-block text-sm font-semibold text-primary underline underline-offset-4">{tx("三项相对指标如何计算？→")}</a>
  </section>;
}
