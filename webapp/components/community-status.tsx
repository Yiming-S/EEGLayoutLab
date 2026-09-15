'use client';
import { useEffect, useState } from 'react';
import { useLanguage } from './language-provider';

type Task = { id: string; kind: string; status: string; queue_position: number; created_at: string; message: string };
type Status = { online_visitors: number; queued_tasks: number; running_tasks: number; available: boolean; recovery_blocked: boolean; jobs: Task[] };
const labels: Record<string, string> = {
  'local-compute': '区域设计', 'design-evaluation': '坐标评价', 'electrode-editor': '电极编辑', 'source-reception': '信号仿真',
  queued: '排队中', running: '计算中', cancelling: '正在停止', completed: '已完成', no_layout: '未构造出布局', failed: '未完成', cancelled: '已取消', timeout: '已超时',
};
export function CommunityStatus() {
  const { tx, date } = useLanguage();
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
  return <details className="relative text-sm">
    <summary className="cursor-pointer rounded-lg border bg-white px-3 py-2 text-[#53686e]">
      {status ? <>{tx('在线访客')} {status.online_visitors} · {tx('等待')} {status.queued_tasks} · {tx('计算中')} {status.running_tasks}</> : tx('服务状态暂不可用')}
    </summary>
    <div className="absolute right-0 z-50 mt-2 max-h-[70vh] w-[min(360px,90vw)] overflow-y-auto rounded-xl border bg-white p-4 shadow-lg">
      <h2 className="font-semibold">{tx('当前浏览器的任务')}</h2>
      <p className="mt-2 text-xs text-muted-foreground">{tx('在线访客按最近90秒活跃的浏览器估算，同一浏览器多个标签页计为一个。')}</p>
      <p className="mt-2 text-xs text-muted-foreground">{tx('无需登录。后台记录IP用于访问日志和限流，日志保留7天，不公开显示。')}</p>
      {(status?.recovery_blocked || status?.available === false) && <p className="mt-2 text-amber-800">{tx('队列暂停，等待服务检查')}</p>}
      {!status?.jobs.length && <p className="mt-3 text-muted-foreground">{tx('当前浏览器暂无计算任务')}</p>}
      {status?.jobs.map(task => <div key={task.id} className="mt-3 border-t pt-3">
        <div className="flex justify-between gap-2"><span>{tx(labels[task.kind] || task.kind)}</span><span>{tx(labels[task.status] || task.status)}{task.status === 'queued' && ` · ${task.queue_position}`}</span></div>
        <div className="mt-1 text-xs text-muted-foreground">{date(task.created_at, true)} · {task.id.slice(0, 8)}</div>
        {task.status === 'queued' && <p className="mt-1 text-xs">{tx('数字为等待队列中的位置，按提交顺序执行。')}</p>}
        {['queued', 'running', 'cancelling'].includes(task.status) ? <button onClick={() => void act(task, true)} disabled={task.status === 'cancelling'} className="mt-2 rounded border px-3 py-1">{tx('取消等待或计算')}</button>
          : ['completed', 'no_layout'].includes(task.status) ? <button onClick={() => void act(task, false)} className="mt-2 rounded border px-3 py-1">{tx('下载计算结果')}</button> : <p className="mt-1 text-xs">{tx(task.message)}</p>}
      </div>)}
      {failure && <p role="alert" className="mt-3 text-red-700">{tx(failure)}</p>}
    </div>
  </details>;
}
