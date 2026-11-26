'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { Button } from '@/components/ui/button';
import type { ProjectWorkflow, ResearchProject } from '@/client/projects';
import { decisionCriteriaSummary, parseDecisionThresholds } from '@/lib/design-decision';
import { comparableProjectEntries, emptyWorkflow, projectWorkflowFor } from './project-workflow';
import { projectExperimentAssociations } from './project-experiment-associations';

export function ProjectWorkflowEditor({ project, busy, save, showCandidateSignals }: {
  project: ResearchProject; busy: boolean; save: (workflow: ProjectWorkflow) => void;
  showCandidateSignals?: () => void;
}) {
  const { tx } = useLanguage(), workflow = project.workflow ?? emptyWorkflow;
  const [reference, setReference] = useState(workflow.reference_entry_id ?? ''), [candidate, setCandidate] = useState(workflow.candidate_entry_id ?? '');
  const [error, setError] = useState('');
  const layouts = comparableProjectEntries(project.entries);
  const associations = projectExperimentAssociations(project.entries, workflow.candidate_entry_id);
  const selected = layouts.find(entry => entry.id === workflow.candidate_entry_id);
  const comparison = workflow.comparison_href;
  const criteria = comparison ? decisionCriteriaSummary(parseDecisionThresholds(new URL(comparison, 'http://localhost').searchParams)) : '';
  return <section className="lab-panel space-y-4" aria-label={tx('研究任务进度')}>
    <h2 className="text-lg font-semibold">{tx('继续这次研究')}</h2>
    <ol className="grid gap-3 text-sm md:grid-cols-5">
      <li className="rounded-lg border p-3"><strong>1 · {tx('选择布局')}</strong><p className="mt-2 text-muted-foreground">{tx('已保存布局副本')}：{associations.layoutCopies}</p><p className="text-muted-foreground">{tx('不同科学布局')}：{associations.distinctLayoutCount}</p><a className="mt-2 inline-block text-primary underline" href="/library">{tx('浏览已有布局')}</a></li>
      <li className="rounded-lg border p-3"><strong>2 · {tx('修改并评价')}</strong><p className="mt-2 text-muted-foreground">{tx('完成评价后，将新结果保存到当前项目。')}</p><div className="mt-2 flex flex-wrap gap-2"><a className="text-primary underline" href="/design">{tx('区域设计')}</a><a className="text-primary underline" href="/coordinates">{tx('坐标导入')}</a></div></li>
      <li className="rounded-lg border p-3"><strong>3 · {tx('信号仿真')}</strong><dl className="mt-2 text-muted-foreground"><div><dt>{tx('项目全部信号记录')}</dt><dd data-project-source-total>{associations.signals.length}</dd></div><div className="mt-2"><dt>{tx('当前候选布局的信号记录')}</dt><dd data-candidate-source-total>{associations.candidateRecordId ? associations.candidateSignals.length : tx('尚未选择')}</dd></div></dl>{showCandidateSignals && <Button className="mt-2" variant="outline" size="sm" disabled={!associations.candidateRecordId} onClick={showCandidateSignals}>{tx('查看候选布局的信号记录')}</Button>}{selected?.summary?.electrode_count !== 64 ? <p className="mt-2 text-muted-foreground">{tx('选择已评价的64电极候选布局。')}</p> : selected.summary.simulation === false ? <p className="mt-2 text-muted-foreground">{tx('该布局不进入信号仿真：信号仿真只接受独立噪声下得到的已评价64电极布局。')}</p> : <a className="mt-2 inline-block text-primary underline" href={'/reception?record=' + selected.record_id}>{tx('使用候选布局仿真')}</a>}</li>
      <li className="rounded-lg border p-3"><strong>4 · {tx('比较方案')}</strong><p className="mt-2 text-muted-foreground">{tx(comparison ? '对比方案与要求已保存。' : '选择项目中的参考布局与候选布局。')}</p>{comparison && <a className="mt-2 inline-block text-primary underline" href={comparison}>{tx('打开保存的方案对比')}</a>}</li>
      <li className="rounded-lg border p-3"><strong>5 · {tx('导出与交接')}</strong><p className="mt-2 text-muted-foreground">{tx('保留原始结果、实验说明和比较条件。')}</p><a className="mt-2 inline-block text-primary underline" href="#project-delivery">{tx('查看项目交付')}</a></li>
    </ol>
    <form className="space-y-3 border-t pt-4" onSubmit={event => {
      event.preventDefault(); setError('');
      try { save(projectWorkflowFor(project, reference || null, candidate || null)); }
      catch (caught) { setError(caught instanceof Error ? caught.message : '项目操作失败'); }
    }}>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="lab-label">{tx('项目参考布局')}<select aria-label={tx('项目参考布局')} className="lab-select" value={reference} onChange={event => setReference(event.target.value)}><option value="">{tx('尚未选择')}</option>{layouts.map(entry => <option value={entry.id} key={entry.id}>{entry.title}</option>)}</select></label>
        <label className="lab-label">{tx('项目候选布局')}<select aria-label={tx('项目候选布局')} className="lab-select" value={candidate} onChange={event => setCandidate(event.target.value)}><option value="">{tx('尚未选择')}</option>{layouts.map(entry => <option value={entry.id} key={entry.id}>{entry.title}</option>)}</select></label>
      </div>
      <Button type="submit" variant="outline" disabled={busy}>{tx('保存研究任务选择')}</Button>
      {error && <p role="alert" className="text-sm text-danger">{tx(error)}</p>}
      <p className="text-xs text-muted-foreground">{tx('保存选择不会启动计算。需要调整比较要求时，打开方案对比页并将设置保存回项目。')}</p>
    </form>
    {criteria && <p className="rounded-lg bg-muted p-3 text-sm">{tx(criteria)}</p>}
    <p className="text-xs text-muted-foreground">{tx('项目副本可以独立查看。工具页的新计算使用服务器当前可用的原始记录与科学环境。')}</p>
  </section>;
}
