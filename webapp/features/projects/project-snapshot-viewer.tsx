'use client';
import { useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { PerformanceSummary } from '@/components/performance-summary';
import { ExperimentResult } from '@/features/reception/experiment-result';
import type { ProjectEntry } from '@/client/projects';
import { metricDistance, metricPercent } from '@/lib/ui-language';
import { projectSnapshotView } from './project-snapshot-view';

export function ProjectSnapshotViewer({ entry, snapshot }: { entry: ProjectEntry; snapshot: unknown }) {
  const { tx } = useLanguage(), [ar, setAR] = useState(90);
  let view;
  try { view = projectSnapshotView(entry, snapshot); }
  catch (error) { return <p role="alert">{tx(error instanceof Error ? error.message : '项目科学副本格式无效')}</p>; }
  if (view.kind === 'source') return <ExperimentResult result={view.result} label={entry.title} ar={ar} setAR={setAR} cached archived />;
  const xyz = view.kind === 'layout' ? view.record.layout!.xyzMm : view.result.evaluated_xyz_mm;
  return <div className="space-y-4">
    <p className="text-sm text-muted-foreground">{tx('直接读取项目保存的坐标与指标，不依赖原任务回执或重新计算。')}</p>
    {view.kind === 'layout' ? <>
      <label className="lab-label">{tx('项目副本的显示保留要求')} · {ar}%<input className="mt-2 w-full accent-primary" type="range" aria-label={tx('项目副本的显示保留要求')} min={10} max={100} value={ar} onChange={event => setAR(Number(event.target.value))} /></label>
      <PerformanceSummary metrics={view.record.metrics} ar={ar} basis="项目保存的原始布局评价" returnHref="/projects" compact />
    </> : <section className="rounded-lg border p-4"><h3 className="font-semibold">{tx('编辑副本的原始指标')}</h3><dl className="mt-3 grid gap-3 sm:grid-cols-3">
      <div><dt>{tx('场重建保留率')}</dt><dd>{metricPercent(view.result.edited_metrics.field_relative)}</dd></div>
      <div><dt>{tx('幅度保留率')}</dt><dd>{metricPercent(view.result.edited_metrics.sensitivity_tail)}</dd></div>
      <div><dt>{tx('定位效用保留率')}</dt><dd>{metricPercent(view.result.edited_metrics.localization_relative)}</dd></div>
      <div><dt>{tx('定位中位误差')}</dt><dd>{metricDistance(view.result.edited_metrics.median_mm)}</dd></div>
      <div><dt>{tx('定位90分位误差')}</dt><dd>{metricDistance(view.result.edited_metrics.p90_mm)}</dd></div>
      <div><dt>{tx('实际电极数')}</dt><dd>{view.result.electrode_count}</dd></div>
    </dl><p className="mt-3 text-xs text-muted-foreground">{tx('编辑副本保留其独立评价协议，不进入固定64点信号仿真。')}</p></section>}
    <details className="rounded-lg border p-4"><summary className="cursor-pointer font-medium">{tx('查看已保存坐标')} · {xyz.length}</summary>
      <p className="mt-2 text-xs text-muted-foreground">{tx('坐标系：Ernie 原生空间，单位毫米。')}</p>
      <div className="mt-3 max-h-80 overflow-auto"><table className="w-full text-left text-sm"><thead><tr><th>{tx('电极')}</th>{view.kind === 'layout' && <th>{tx('区域')}</th>}<th>X (mm)</th><th>Y (mm)</th><th>Z (mm)</th></tr></thead><tbody>{xyz.map((point, index) => <tr key={index}><td>{view.kind === 'layout' ? view.record.electrode_annotation?.electrode_names[index] ?? `E${index + 1}` : `E${index + 1}`}</td>{view.kind === 'layout' && <td>{view.record.layout!.regionIndices[index]}</td>}{point.map((value, axis) => <td key={axis} className="font-mono">{value.toFixed(6)}</td>)}</tr>)}</tbody></table></div>
    </details>
  </div>;
}
