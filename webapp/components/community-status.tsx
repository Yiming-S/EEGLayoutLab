'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useState } from 'react';
import { useLanguage } from './language-provider';
import { RuntimeMessage } from './runtime-message';
import { useDismissibleDetails } from './use-dismissible-details';
import { activeTaskLink, completedTaskLink, type ExperimentReceipt } from '@/lib/records-catalog';
import { downloadExperimentReceipt } from './catalog-experiment-details';

type Task = ExperimentReceipt & { queue_position: number; message: string; progress?: number; cached?: boolean };
type Status = { online_visitors: number; queued_tasks: number; running_tasks: number; available: boolean; recovery_blocked: boolean; jobs: Task[] };
const labels: Record<string, string> = {
  'local-compute': '区域设计', 'design-evaluation': '坐标评价', 'electrode-editor': '电极编辑', 'source-reception': '信号仿真',
  queued: '排队中', running: '计算中', cancelling: '正在停止', completed: '已完成', no_layout: '未构造出布局', failed: '未完成', cancelled: '已取消', timeout: '已超时',
};
export function CommunityStatus() {
  const { tx, date } = useLanguage();
  const menu = useDismissibleDetails();
  const [status, setStatus] = useState<Status | null>(null);
  const [failure, setFailure] = useState('');
  useEffect(() => {
    let stopped = false, inflight = false;
    const refresh = async () => {
      if (inflight) return;
      inflight = true;
      try {
        const h = await fetch('/api/local-compute/health', { signal: AbortSignal.timeout(8000), cache: 'no-store' });
        if (!h.ok) throw new Error('offline');
        const { token } = await h.json();
        const response = await fetch('/api/community/heartbeat', { method: 'POST',
          headers: { 'x-eeg-compute-token': token, 'x-eeg-visible': document.visibilityState === 'visible' ? '1' : '0' },
          signal: AbortSignal.timeout(8000), cache: 'no-store' });
        if (!response.ok) throw new Error('offline');
        const data = await response.json() as Status;
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
  return <details ref={menu} className="relative text-sm">
    <summary className="cursor-pointer rounded-lg px-2 py-2 text-xs text-[#53686e]" aria-label={tx('查看任务与计算队列')}>
      {tx('任务 / 队列')}{status ? <> {status.queued_tasks}{status.running_tasks > 0 && <> · {tx('计算中')} {status.running_tasks}</>}</> : <span className="hidden sm:inline"> · {tx('服务未连接')}</span>}
    </summary>
    <div className="absolute right-0 z-50 mt-2 max-h-[70vh] w-[min(360px,90vw)] overflow-y-auto rounded-xl border bg-white p-4 shadow-lg">
      <h2 className="font-semibold">{tx('当前浏览器的任务')}</h2>
      {status && <p className="mt-2 text-sm">{tx(`运行中：${status.running_tasks}项 · 等待中：${status.queued_tasks}项`)}</p>}
      {status && <p className="mt-2 text-xs text-muted-foreground">{tx('在线访客')}：{status.online_visitors}</p>}
      <p className="mt-2 text-xs text-muted-foreground">{tx('在线访客按最近90秒活跃的浏览器估算，同一浏览器多个标签页计为一个。')}</p>
      <p className="mt-2 text-xs text-muted-foreground">{tx('无需登录。后台记录IP用于访问日志和限流，日志保留7天，不公开显示。')}</p>
      {(status?.recovery_blocked || status?.available === false) && <p className="mt-2 text-amber-800">{tx('队列暂停，等待服务检查')}</p>}
      {!status?.jobs.length && <p className="mt-3 text-muted-foreground">{tx('当前浏览器暂无计算任务')}</p>}
      {status?.jobs.map(task => <div key={task.id} className="mt-3 border-t pt-3">
        <div className="flex justify-between gap-2"><span>{tx(labels[task.kind] || task.kind)}</span><span>{tx(task.cached && task.status === 'completed' ? '已读取已有结果' : labels[task.status] || task.status)}</span></div>
        <div className="mt-1 text-xs text-muted-foreground">{date(task.created_at, true)} · {task.id.slice(0, 8)}</div>
        {task.status === 'queued' && <p className="mt-1 text-xs">{tx(`前方等待任务：${Math.max(0, task.queue_position - 1)}项；按提交顺序执行。`)}</p>}
        {task.status === 'running' && <div className="mt-2 space-y-1"><p className="text-xs"><RuntimeMessage message={task.message} /></p>{Number.isFinite(task.progress) && <><progress aria-label={tx('计算进度')} max={1} value={task.progress} className="h-2 w-full accent-primary" /><p className="text-xs tabular-nums">{Math.round(Math.max(0, Math.min(1, task.progress!)) * 100)}%</p></>}</div>}
        {['queued', 'running', 'cancelling'].includes(task.status) ? <div className="mt-2 flex flex-wrap gap-2">
            {activeTaskLink(task) && <a className="rounded border bg-primary px-3 py-1 text-primary-foreground" href={activeTaskLink(task)!}>{tx('回到任务页面')}</a>}
            <button onClick={() => void act(task, true)} disabled={task.status === 'cancelling'} className="rounded border px-3 py-1">{tx('取消等待或计算')}</button>
          </div>
          : ['completed', 'no_layout'].includes(task.status) ? <div className="mt-2 flex flex-wrap gap-2">
            {completedTaskLink(task) && <a className="rounded border bg-primary px-3 py-1 text-primary-foreground" href={completedTaskLink(task)!}>{tx(task.kind === 'source-reception' ? '打开信号实验' : task.kind === 'electrode-editor' ? '打开电极编辑' : '打开结果')}</a>}
            <button onClick={() => void act(task, false)} className="rounded border px-3 py-1">{tx('下载计算结果')}</button>
          </div> : <details className="mt-2 text-xs"><summary className="cursor-pointer">{tx('查看任务详情')}</summary><p className="mt-2 break-words"><RuntimeMessage message={task.message} /></p><p className="mt-1 break-all text-muted-foreground">{task.id}</p></details>}
      </div>)}
      {failure && <p role="alert" className="mt-3 text-red-700">{tx(failure)}</p>}
    </div>
  </details>;
}
