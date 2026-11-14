'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import { projectRequest, type ProjectEntryKind, type ProjectResponse } from '@/client/projects';
import { useActiveProject } from './use-active-project';
import { projectWorkflowFromComparison } from './project-workflow';

export function SaveToProject({ kind, recordId, receiptId }: { kind: ProjectEntryKind; recordId?: string; receiptId?: string }) {
  const { tx } = useLanguage(), active = useActiveProject();
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [savedIdentity, setSavedIdentity] = useState('');
  const identity = `${active?.project_id}:${kind}:${recordId ?? receiptId}`;
  const saved = savedIdentity === identity;
  if (!active) return <a className="text-sm text-primary underline" href={'/projects' + (recordId ? '?record=' + recordId : '')}>{tx('选择项目以保存结果')}</a>;
  if (active.role !== 'owner') return <span className="text-xs text-muted-foreground">{tx('当前项目为只读访问')}</span>;
  return <div className="flex flex-wrap items-center gap-2">
    <Button type="button" variant="outline" size="sm" disabled={busy || saved || (kind === 'source' ? !receiptId : !recordId)} onClick={() => {
      setBusy(true); setError('');
      void (async () => {
        const current = await projectRequest<ProjectResponse>(active);
        if (current.role !== 'owner') throw new Error('当前项目为只读访问');
        if (recordId && current.project.entries.some(entry => entry.kind === kind && entry.record_id === recordId)) { setSavedIdentity(identity); return; }
        await projectRequest<ProjectResponse>(active, '/entries', { method: 'POST', body: JSON.stringify({
          revision: current.project.revision, kind, ...(kind === 'source' ? { receipt_id: receiptId } : { record_id: recordId }),
        }) });
        setSavedIdentity(identity);
      })().catch(caught => setError(caught instanceof Error ? caught.message : '项目操作失败')).finally(() => setBusy(false));
    }}>{tx(saved ? '已保存到当前项目' : kind === 'source' ? '保存信号实验到项目' : '保存当前布局到项目')}</Button>
    {error && <span role="alert" className="max-w-lg text-xs text-red-800"><RuntimeMessage message={error} /></span>}
  </div>;
}

export function ProjectContext({ recordId, here, currentIsProjects }: { recordId?: string; here: string; currentIsProjects: boolean }) {
  const { tx } = useLanguage(), active = useActiveProject();
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  if (!active || currentIsProjects) return null;
  const comparison = new URL(here, 'http://localhost').pathname === '/decision';
  return <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-x-4 gap-y-2 border-t px-4 py-2 text-sm sm:px-6 lg:px-8" aria-label={tx('当前研究项目')}>
    <a className="font-medium text-primary underline" href={'/projects?project=' + active.project_id}>{tx('当前研究项目')} · {active.title || active.project_id.slice(0, 8)}</a>
    {recordId && <SaveToProject kind="layout" recordId={recordId} />}
    {comparison && active.role === 'owner' && <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => {
      setBusy(true); setMessage('');
      void (async () => {
        const current = await projectRequest<ProjectResponse>(active);
        const workflow = projectWorkflowFromComparison(current.project, here);
        await projectRequest(active, '', { method: 'PATCH', body: JSON.stringify({ revision: current.project.revision, workflow }) });
        setMessage('已保存当前对比设置。');
      })().catch(caught => setMessage(caught instanceof Error ? caught.message : '项目操作失败')).finally(() => setBusy(false));
    }}>{tx('保存当前对比设置到项目')}</Button>}
    {message && <span className="text-xs"><RuntimeMessage message={message} /></span>}
  </div>;
}
