'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useState } from 'react';
import { useLanguage } from './language-provider';
import { RuntimeMessage } from './runtime-message';
import { activeTaskLink, completedTaskLink, type ExperimentReceipt } from '@/lib/records-catalog';
import { downloadExperimentReceipt } from './catalog-experiment-details';
import { Button, buttonVariants } from '@/components/ui/button';
import { hasVisitorCounts, refreshCommunityStatus, type CommunityStatus } from './community-status-model';
import { cn } from '@/lib/utils';

type Task = ExperimentReceipt & { queue_position: number; message: string; progress?: number; cached?: boolean };
type Status = Omit<CommunityStatus, 'jobs'> & { jobs: Task[] };
const labels: Record<string, string> = {
  'local-compute': '区域设计', 'design-evaluation': '坐标评价', 'electrode-editor': '电极编辑', 'source-reception': '信号仿真',
  queued: '排队中', running: '计算中', cancelling: '正在停止', completed: '已完成', no_layout: '未构造出布局', failed: '未完成', cancelled: '已取消', timeout: '已超时',
};
/** The tasks this browser submitted, refreshed every 15 s; shared by the header indicator and the workspace home. */
export function useTaskStatus() {
  const [status, setStatus] = useState<Status | null>(null);
  const [failure, setFailure] = useState('');
  useEffect(() => {
    let stopped = false, inflight = false;
    const refresh = async () => {
      if (inflight) return;
      inflight = true;
      try {
        // A plain read of the queue on both hosts; a host that counts visitors (Node) also gets its heartbeat.
        const data = await refreshCommunityStatus(document.visibilityState === 'visible') as Status;
        if (!stopped) setStatus(data);
      } catch { if (!stopped) setStatus(null); }
      finally { inflight = false; }
    };
    void refresh();
    const timer = setInterval(() => { void refresh(); }, 15000);
    document.addEventListener('visibilitychange', refresh);
    return () => { stopped = true; clearInterval(timer); document.removeEventListener('visibilitychange', refresh); };
  }, []);
  const act = async (task: Task, cancel: boolean) => {
    setFailure('');
    try {
      if (!cancel && task.kind === 'source-reception') { await downloadExperimentReceipt(task); return; }
      const health = await fetch('/api/local-compute/health').then(r => r.json());
      const response = await fetch(`/api/${task.kind}/jobs/${task.id}${cancel ? '/cancel' : ''}`, {
        method: cancel ? 'POST' : 'GET', headers: { 'x-eeg-compute-token': health.token }, signal: AbortSignal.timeout(30000),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      if (cancel) {
        setStatus(s => s ? { ...s, jobs: s.jobs.map(j => j.id === task.id ? data.job : j) } : s);
      } else {
        if (!data.job.result) throw new Error(data.job.message);
        const url = URL.createObjectURL(new Blob([JSON.stringify(data.job.result, null, 2)], { type: 'application/json' }));
        const link = document.createElement('a'); link.href = url; link.download = `eeg-result-${task.id}.json`; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (e) { setFailure(e instanceof Error ? e.message : '无法读取任务'); }
  };
  return { status, failure, act };
}

/** The visitor count and access-log notice matter on a shared server; folded so they do not lead the task list.
 * Only a host that counts visitors (Node) shows them; the Python service has no visitors (community-status-model). */
export function VisitorNotice({ status, className }: { status: Status | null; className?: string }) {
  const { tx } = useLanguage();
  if (!hasVisitorCounts(status)) return null;
  return <details className={cn('text-xs text-muted-foreground', className)}>
    <summary className="cursor-pointer">{tx('访客与访问记录')}</summary>
    <p className="mt-2">{tx('在线访客')}：{status.online_visitors}</p>
    <p className="mt-2">{tx('在线访客按最近90秒活跃的浏览器估算，同一浏览器多个标签页计为一个。')}</p>
    <p className="mt-2">{tx('无需登录。后台记录IP用于访问日志和限流，日志保留7天，不公开显示。')}</p>
  </details>;
}

export function TaskList({ status, failure, act }: ReturnType<typeof useTaskStatus>) {
  const { tx, date } = useLanguage();
  return <>
      {status && <p className="mt-2 text-sm">{tx(`运行中：${status.running_tasks}项 · 等待中：${status.queued_tasks}项`)}</p>}
      <VisitorNotice status={status} className="mt-2" />
      {(status?.recovery_blocked || status?.available === false) && <p className="mt-2 text-warning">{tx('队列暂停，等待服务检查')}</p>}
      {!status?.jobs.length && <p className="mt-3 text-muted-foreground">{tx('当前浏览器暂无计算任务')}</p>}
      {status?.jobs.map(task => <div key={task.id} className="mt-3 border-t pt-3">
        <div className="flex justify-between gap-2"><span>{tx(labels[task.kind] || task.kind)}</span><span>{tx(task.cached && task.status === 'completed' ? '已读取已有结果' : labels[task.status] || task.status)}</span></div>
        <div className="mt-1 text-xs text-muted-foreground">{date(task.created_at, true)} · {task.id.slice(0, 8)}</div>
        {task.status === 'queued' && <p className="mt-1 text-xs">{tx(`前方等待任务：${Math.max(0, task.queue_position - 1)}项；按提交顺序执行。`)}</p>}
        {task.status === 'running' && <div className="mt-2 space-y-1"><p className="text-xs"><RuntimeMessage message={task.message} /></p>{Number.isFinite(task.progress) && <><progress aria-label={tx('计算进度')} max={1} value={task.progress} className="h-2 w-full accent-primary" /><p className="text-xs tabular-nums">{Math.round(Math.max(0, Math.min(1, task.progress!)) * 100)}%</p></>}</div>}
        {['queued', 'running', 'cancelling'].includes(task.status) ? <div className="mt-2 flex flex-wrap gap-2">
            {activeTaskLink(task) && <a className={buttonVariants({ size: 'sm' })} href={activeTaskLink(task)!}>{tx('回到任务页面')}</a>}
            <Button size="sm" variant="outline" onClick={() => void act(task, true)} disabled={task.status === 'cancelling'}>{tx('取消等待或计算')}</Button>
          </div>
          : ['completed', 'no_layout'].includes(task.status) ? <div className="mt-2 flex flex-wrap gap-2">
            {completedTaskLink(task) && <a className={buttonVariants({ size: 'sm' })} href={completedTaskLink(task)!}>{tx(task.kind === 'source-reception' ? '打开信号实验' : task.kind === 'electrode-editor' ? '打开电极编辑' : '打开结果')}</a>}
            <Button size="sm" variant="outline" onClick={() => void act(task, false)}>{tx('下载计算结果')}</Button>
          </div> : <details className="mt-2 text-xs"><summary className="cursor-pointer">{tx('查看任务详情')}</summary><p className="mt-2 break-words"><RuntimeMessage message={task.message} /></p><p className="mt-1 break-all text-muted-foreground">{task.id}</p></details>}
      </div>)}
      {failure && <p role="alert" className="mt-3 text-danger">{tx(failure)}</p>}
  </>;
}

/** Header indicator: the queue at a glance; the list itself lives on the workspace home. */
export function CommunityStatus() {
  const { tx } = useLanguage();
  const { status } = useTaskStatus();
  return <a href="/#tasks" className="rounded-lg px-2 py-2 text-xs text-ink-soft hover:bg-secondary" aria-label={tx('查看任务与计算队列')}>
    {tx('任务 / 队列')}{status ? <> {status.queued_tasks}{status.running_tasks > 0 && <> · {tx('计算中')} {status.running_tasks}</>}</> : <span className="hidden sm:inline"> · {tx('服务未连接')}</span>}
  </a>;
}
