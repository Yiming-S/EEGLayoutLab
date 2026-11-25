'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useLanguage } from './language-provider';
import { RuntimeMessage } from './runtime-message';
import { activeTaskLink, completedTaskLink, type ExperimentReceipt } from '@/lib/records-catalog';
import { downloadExperimentReceipt } from './catalog-experiment-details';
import { Button, buttonVariants } from '@/components/ui/button';
import { fetchCommunityStatus, type CommunityStatus } from './community-status-model';
import {
  ApiError, cancelTask, isServiceUnreachable, readTask, SERVICE_CONNECTION_EVENT, SERVICE_UNREACHABLE_MESSAGE, SESSION_REOPEN_MESSAGE,
} from '@/client/task-client';
import { cn } from '@/lib/utils';

type Task = ExperimentReceipt & { queue_position: number; message: string; progress?: number; cached?: boolean };
type Status = Omit<CommunityStatus, 'jobs'> & { jobs: Task[] };
const labels: Record<string, string> = {
  'local-compute': '区域设计', 'design-evaluation': '坐标评价', 'electrode-editor': '电极编辑', 'source-reception': '信号仿真',
  queued: '排队中', running: '计算中', cancelling: '正在停止', completed: '已完成', no_layout: '未构造出布局', failed: '未完成', cancelled: '已取消', timeout: '已超时',
};
/** Why there is no status: not read yet, the session of an earlier run (401), no server at all (the service stopped,
 * or restarted on another port), or another failure (a timeout, an answer the menu cannot show). */
export type Offline = 'loading' | 'expired' | 'unreachable' | 'failed' | null;
/** The reopen advice for a tab whose service has ended, else null. */
export const reopenMessage = (offline: Offline) =>
  offline === 'expired' ? SESSION_REOPEN_MESSAGE : offline === 'unreachable' ? SERVICE_UNREACHABLE_MESSAGE : null;
/** The workspace's latest tasks, refreshed every 15 s and at once when a request of the page finds the session ended
 * or no server (SERVICE_CONNECTION_EVENT); shared by the header indicator and the workspace home. */
export function useTaskStatus() {
  const [status, setStatus] = useState<Status | null>(null);
  const [offline, setOffline] = useState<Offline>('loading');
  const [failure, setFailure] = useState('');
  useEffect(() => {
    let stopped = false, inflight = false;
    const refresh = async () => {
      if (inflight) return;
      inflight = true;
      try {
        const data = await fetchCommunityStatus() as Status;
        if (!stopped) { setStatus(data); setOffline(null); }
      } catch (error) {
        if (!stopped) {
          setStatus(null);
          setOffline(error instanceof ApiError && error.status === 401 ? 'expired' : isServiceUnreachable(error) ? 'unreachable' : 'failed');
        }
      } finally { inflight = false; }
    };
    void refresh();
    const timer = setInterval(() => { void refresh(); }, 15000);
    document.addEventListener('visibilitychange', refresh);
    window.addEventListener(SERVICE_CONNECTION_EVENT, refresh);
    return () => {
      stopped = true; clearInterval(timer);
      document.removeEventListener('visibilitychange', refresh); window.removeEventListener(SERVICE_CONNECTION_EVENT, refresh);
    };
  }, []);
  const act = async (task: Task, cancel: boolean) => {
    setFailure('');
    try {
      if (!cancel && task.kind === 'source-reception') { await downloadExperimentReceipt(task); return; }
      if (cancel) {
        const { job } = await cancelTask<{ job: Task }>(task.kind, task.id, { timeoutMs: 30000 });
        setStatus(s => s ? { ...s, jobs: s.jobs.map(j => j.id === task.id ? job : j) } : s);
      } else {
        const job = await readTask<Task & { result?: unknown }>(task.kind, task.id, AbortSignal.timeout(30000));
        if (!job.result) throw new Error(job.message);
        const url = URL.createObjectURL(new Blob([JSON.stringify(job.result, null, 2)], { type: 'application/json' }));
        const link = document.createElement('a'); link.href = url; link.download = `eeg-result-${task.id}.json`; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (e) { setFailure(e instanceof Error ? e.message : '无法读取任务'); }
  };
  return { status, offline, expired: offline === 'expired', failure, act };
}

export function TaskList({ status, offline, failure, act }: ReturnType<typeof useTaskStatus>) {
  const { tx, date } = useLanguage();
  const reopen = reopenMessage(offline);
  return <>
      {reopen && <p role="alert" className="mt-2 text-warning">{tx(reopen)}</p>}
      {offline === 'failed' && <p role="alert" className="mt-2 text-warning">{tx('计算服务未连接')}</p>}
      {status && <p className="mt-2 text-sm">{tx(`运行中：${status.running_tasks}项 · 等待中：${status.queued_tasks}项`)}</p>}
      {(status?.recovery_blocked || status?.available === false) && <p className="mt-2 text-warning">{tx('队列暂停，等待服务检查')}</p>}
      {status && !status.jobs.length && <p className="mt-3 text-muted-foreground">{tx('此工作区暂无计算任务')}</p>}
      {status?.jobs.map(task => <div key={task.id} className="mt-3 border-t pt-3">
        <div className="flex justify-between gap-2"><span>{tx(labels[task.kind] || task.kind)}</span><span>{tx(task.cached && task.status === 'completed' ? '已读取已有结果' : labels[task.status] || task.status)}</span></div>
        <div className="mt-1 font-mono text-xs text-muted-foreground">{date(task.created_at, true)} · {task.id.slice(0, 8)}</div>
        {task.status === 'queued' && <p className="mt-1 text-xs">{tx(`前方等待任务：${Math.max(0, task.queue_position - 1)}项；按提交顺序执行。`)}</p>}
        {task.status === 'running' && <div className="mt-2 space-y-1"><p className="text-xs"><RuntimeMessage message={task.message} /></p>{Number.isFinite(task.progress) && <><progress aria-label={tx('计算进度')} max={1} value={task.progress} className="h-1.5 w-full" /><p className="font-mono text-xs tabular-nums">{Math.round(Math.max(0, Math.min(1, task.progress!)) * 100)}%</p></>}</div>}
        {['queued', 'running', 'cancelling'].includes(task.status) ? <div className="mt-2 flex flex-wrap gap-2">
            {activeTaskLink(task) && <a className={buttonVariants({ size: 'sm' })} href={activeTaskLink(task)!}>{tx('回到任务页面')}</a>}
            <Button size="sm" variant="outline" onClick={() => void act(task, true)} disabled={task.status === 'cancelling'}>{tx('取消等待或计算')}</Button>
          </div>
          : ['completed', 'no_layout'].includes(task.status) ? <div className="mt-2 flex flex-wrap gap-2">
            {completedTaskLink(task) && <a className={buttonVariants({ size: 'sm' })} href={completedTaskLink(task)!}>{tx(task.kind === 'source-reception' ? '打开信号实验' : task.kind === 'electrode-editor' ? '打开电极编辑' : '打开结果')}</a>}
            <Button size="sm" variant="outline" onClick={() => void act(task, false)}>{tx('下载计算结果')}</Button>
          </div> : <details className="mt-2 text-xs"><summary className="cursor-pointer">{tx('查看任务详情')}</summary><p className="mt-2 break-words"><RuntimeMessage message={task.message} /></p><p className="mt-1 break-all font-mono text-muted-foreground">{task.id}</p></details>}
      </div>)}
      {failure && <p role="alert" className="mt-3 text-danger">{tx(failure)}</p>}
  </>;
}

/** Header indicator: sleek instrument status capsule. A tab whose service has ended also gets the reopen advice as a
 * notice at the foot of the window, at every width (a portal: the header's backdrop filter would hold it). */
export function CommunityStatus() {
  const { tx } = useLanguage();
  const { status, offline } = useTaskStatus();
  const active = (status?.running_tasks ?? 0) > 0;
  const reopen = reopenMessage(offline);
  return <>
    {reopen && createPortal(<p role="alert" className="fixed inset-x-4 bottom-4 z-50 mx-auto max-w-2xl rounded-lg border border-warning bg-card px-4 py-3 text-sm text-foreground shadow-[0_14px_32px_-10px_rgba(0,0,0,0.2)]">{tx(reopen)}</p>, document.body)}
    <a
      href="/#tasks"
      className="inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-card px-3 text-[0.8125rem] font-medium text-ink-soft shadow-[0_1px_1px_rgba(0,0,0,0.02)] transition-colors hover:border-foreground/30 hover:text-foreground"
      aria-label={tx('查看任务与计算队列')}
    >
      <span
        aria-hidden
        className={cn(
          'size-2 rounded-full',
          !status ? 'bg-warning' : active ? 'bg-success animate-pulse' : 'bg-foreground/28',
        )}
      />
      <span>{tx('任务 / 队列')}</span>
      {status ? (
        <span className="rounded bg-secondary px-1.5 py-0.5 font-mono text-xs font-medium text-foreground tabular-nums">
          {status.queued_tasks}
          {active && <> · {tx('计算中')} {status.running_tasks}</>}
        </span>
      ) : offline !== 'loading' && (
        <span className="hidden text-xs text-muted-foreground sm:inline">· {tx(offline === 'expired' ? '会话已失效' : '服务未连接')}</span>
      )}
    </a>
  </>;
}
