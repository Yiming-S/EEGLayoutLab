'use client';
import { useLanguage } from '@/components/language-provider';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import type { ComputeResult } from '@/lib/local-compute';
import { assessment, METRICS, methodLink } from '@/lib/lab-workflow';
import { metricPercent, metricDistance } from '@/lib/ui-language';
export const percent = metricPercent;
const mm = metricDistance;
export function PerformanceSummary({ metrics, ar, basis, returnHref, emptyTitle = '等待评估', empty = '当前配置尚未评估。已有结果会自动读取；没有记录时，点击“开始布局计算”。' }: {
  metrics: ComputeResult['metrics']; ar: number; basis: string; returnHref?: string; empty?: string; emptyTitle?: string;
}) {
  const { tx } = useLanguage();
  const result = assessment(metrics, ar);
  return <section className="lab-panel" aria-label={tx("方案性能与64导对照")}>
    <p className="lab-eyebrow">{tx("与标准全头64导相比")}</p>
    <h2 className="mt-2 text-xl font-semibold">{tx(!metrics ? emptyTitle : result.state === 'pass' ? `三项均达到 AR ${ar}%` : result.state === 'undefined' ? '指标不完整，无法判断' : `未满足 AR ${ar}%`)}</h2>
    <p className="mt-2 text-sm leading-6 text-muted-foreground">{tx(!metrics ? empty : result.state === 'fail' ? `未达阈值：${result.limiting.join('、')}。` : '此结论只适用于本记录的头模与实验条件。')}</p>
    {tx(metrics && <>
      <div className="mt-5 space-y-5">{tx(METRICS.map((m) => {
        const value = metrics[m.key], valid = value != null && Number.isFinite(value), pass = valid && value >= ar / 100;
        return <div key={m.key}>
          <div className="flex justify-between gap-3 text-sm"><span className="font-medium">{tx(m.label)}</span><span className="font-mono font-semibold">{tx(percent(value))} <span className={pass ? 'text-primary' : 'text-amber-800'}>{tx(!valid ? '无法判断' : pass ? '达标' : '未达标')}</span></span></div>
          <div className="relative mt-2 h-2 rounded bg-secondary"><div className={`h-2 rounded ${pass ? 'bg-primary' : 'bg-amber-600'}`} style={{ width: `${Math.max(0, Math.min(100, (valid ? value : 0) * 100))}%` }} /><span className="absolute top-[-3px] h-3.5 border-l-2 border-foreground/60" style={{ left: `${ar}%` }} /></div>
          <p className="mt-1.5 text-sm leading-6 text-muted-foreground">{tx(m.explanation)}{tx("；全头基准为100%。")}</p>
        </div>;
      }))}</div>
      <dl className="mt-6 space-y-3 border-t pt-4 text-sm">
        <div className="flex justify-between gap-2"><dt>{tx("当前布局定位中位误差")}</dt><dd className="font-mono">{tx(mm(metrics.median_mm))}</dd></div>
        <div className="flex justify-between gap-2"><dt>{tx("标准64导定位中位误差")}</dt><dd className="font-mono">{tx(mm(metrics.reference_median_mm))}</dd></div>
        <div className="flex justify-between gap-2"><dt>{tx("三项最低相对评分 G")}</dt><dd className="font-mono">{tx(percent(metrics.conditional_global))}</dd></div>
      </dl>
    </>)}
    <p className="mt-5 border-t pt-3 text-xs leading-5 text-muted-foreground">{tx(basis)}{tx("。三项指标以标准64导归一化为100%；阈值按完整精度数值判断。")}</p>
    <a href={methodLink(returnHref ?? '/?ar=' + ar, ar, '#retention-guide')} className="mt-3 inline-block text-sm font-semibold text-primary underline underline-offset-4">{tx("三项相对指标如何计算？→")}</a>
  </section>;
}
