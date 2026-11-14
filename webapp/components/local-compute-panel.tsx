'use client';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from "@/components/runtime-message";


/* oxlint-disable next/no-html-link-for-pages -- preserve the existing vinext-safe navigation */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Cpu, LoaderCircle, Play, Square, CheckCircle2, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { ApiError, apiJson, followTask, submitTask, cancelTask, type TaskConnection } from '@/client/task-client';
import { MANUAL_COMPUTE_DEFAULT } from '@/lib/lab-workflow';
import { currentAR, displayJob, jobRunning, matchingResult, requestKey,
  type ComputeHealth, type ComputeJob, type ComputeRequest, type ComputeResult } from '@/lib/local-compute';

type Props = { request: ComputeRequest; arPercent: number; onResult: (result: ComputeResult | null) => void; onStatus?: (job: ComputeJob | null) => void; compact?: boolean };
const pct = (value: number | null | undefined) => value == null ? '指标无法计算' : `${(value * 100).toFixed(2)}%`;
const mm = (value: number | null | undefined) => value == null ? '指标无法计算' : `${value.toFixed(2)} mm`;

export function LocalComputePanel({ request, arPercent, onResult, onStatus, compact = false }: Props) {
  const { tx } = useLanguage();
  const [health, setHealth] = useState<ComputeHealth | null>(null);
  const [connection, setConnection] = useState<'checking' | 'ready' | 'unavailable'>('checking');
  const [taskConnection, setTaskConnection] = useState<TaskConnection>('connected');
  const [pollRevision, setPollRevision] = useState(0);
  const [job, setJob] = useState<ComputeJob | null>(null);
  const [storedJob, setStoredJob] = useState<ComputeJob | null>(null);
  const [automatic, setAutomatic] = useState(MANUAL_COMPUTE_DEFAULT);
  const [submitting, setSubmitting] = useState(false);
  const [errorState, setErrorState] = useState({ key: '', message: '' });
  const [retry, setRetry] = useState(0);
  const [lookup, setLookup] = useState({ key: '', state: 'checking' as 'checking' | 'hit' | 'miss' | 'error' });
  const currentKey = requestKey(request);
  const latestKey = useRef(currentKey);
  useEffect(() => { latestKey.current = currentKey; }, [currentKey]);
  const mounted = useRef(true);
  const busy = jobRunning(job) && taskConnection !== 'blocked';
  const jobId = job?.id;
  const jobSnapshot = useRef(job);
  useEffect(() => { jobSnapshot.current = job; }, [job]);
  const error = errorState.key === currentKey ? errorState.message : '';
  const setError = useCallback((message: string) => setErrorState({ key: latestKey.current, message }), []);
  const shownJob = displayJob(job, storedJob, request);
  const result = matchingResult(shownJob, request);
  const unsupported = request.mode === 'preset' && !!health &&
    request.mask_codes?.some((code) => !health.supported_masks.includes(code));

  const refreshConnection = useCallback(() => {
    return fetch('/api/local-compute/health', { cache: 'no-store' }).then(async (response) => {
      if (!response.ok) throw new Error('unavailable');
      const data = await response.json() as ComputeHealth;
      if (!mounted.current) return;
      setHealth(data); setConnection(data.available ? 'ready' : 'unavailable');
      setJob((previous) => data.active_job ?? previous);
      setTaskConnection('connected');
      setPollRevision(value => value + 1);
    }).catch(() => { if (mounted.current) { setHealth(null); setConnection('unavailable'); } });
  }, []);

  useEffect(() => { mounted.current = true; void refreshConnection(); return () => { mounted.current = false; }; }, [refreshConnection]);
  useEffect(() => { onResult(result); }, [result, onResult]);
  useEffect(() => { onStatus?.(shownJob && requestKey(shownJob.request) === currentKey ? shownJob : null); }, [shownJob, currentKey, onStatus]);

  // Always read existing data, even when automatic computation is disabled or another job runs.
  // This endpoint never spawns Python. A miss alone cannot schedule work.
  useEffect(() => {
    if (!health || connection !== 'ready' || unsupported) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const data = await apiJson<{ hit: boolean; job?: ComputeJob }>('/api/local-compute/lookup', {
          method: 'POST', signal: controller.signal, token: health.token,
          headers: { 'Content-Type': 'application/json' }, body: currentKey,
          errorMessage: '无法读取本地记录',
        });
        if (controller.signal.aborted) return;
        if (data.hit && data.job) setStoredJob(data.job);
        setLookup({ key: currentKey, state: data.hit ? 'hit' : 'miss' });
      } catch (reason) {
        if (!controller.signal.aborted) {
          setLookup({ key: currentKey, state: 'error' });
          setError(reason instanceof Error ? reason.message : '无法读取本地记录');
        }
      }
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [currentKey, health, connection, unsupported, setError]);

  useEffect(() => {
    const initial = jobSnapshot.current;
    if (!initial || !jobRunning(initial) || !jobId) return;
    const controller = new AbortController();
    void followTask({
      service: 'local-compute', initial, signal: controller.signal,
      onJob(value) { setJob(current => current?.id === jobId ? value : current); },
      onConnection(state, failure) {
        setTaskConnection(state);
        setError(failure?.message ?? '');
        if (state === 'blocked') setConnection('unavailable');
      },
    }).catch(() => { /* The server status remains the last confirmed status. */ });
    return () => controller.abort();
  }, [jobId, job?.status, pollRevision, setError]);

  const submit = useCallback(async () => {
    if (!health || connection !== 'ready' || submitting || busy || unsupported) return;
    const submittedKey = requestKey(request);
    setSubmitting(true); setError('');
    try {
      const data = await submitTask<{ job?: ComputeJob }>('local-compute', submittedKey, {
        errorMessage: '计算服务忙，请稍后再试',
      });
      if (!mounted.current) return;
      if (!data.job) throw new Error('计算服务忙，请稍后再试');
      setTaskConnection('connected');
      // Track even an old in-flight submission; matchingResult prevents stale scores/coordinates.
      setJob(data.job);
    } catch (reason) {
      if (!mounted.current) return;
      if (reason instanceof ApiError && reason.status === 409 && reason.data?.active_job) {
        setTaskConnection('connected'); setJob(reason.data.active_job as ComputeJob); return;
      }
      setError(reason instanceof Error ? reason.message : '无法启动计算');
    }
    finally { if (mounted.current) setSubmitting(false); }
  }, [health, connection, submitting, busy, unsupported, request, setError]);

  // Debounce edits. If an older job is running, finish it first, then compute only the latest configuration.
  // AR is absent from the request/cache identity and never starts Python again.
  const attempted = useRef('');
  useEffect(() => {
    if (!automatic || connection !== 'ready' || unsupported || busy || submitting || lookup.key !== currentKey || lookup.state !== 'miss') return;
    const attempt = `${currentKey}:${retry}`;
    if (attempted.current === attempt || (job && requestKey(job.request) === currentKey && ['completed', 'no_layout'].includes(job.status))) return;
    const timer = setTimeout(() => {
      if (latestKey.current !== currentKey) return;
      attempted.current = attempt;
      void submit();
    }, 1000);
    return () => clearTimeout(timer);
  }, [automatic, connection, unsupported, busy, submitting, currentKey, retry, job, submit, lookup]);

  const cancel = async () => {
    if (!health || !job) return;
    setAutomatic(false);
    try {
      const id = job.id;
      const data = await cancelTask<{ job: ComputeJob }>('local-compute', id, { errorMessage: '无法停止任务' });
      if (mounted.current) setJob(current => current?.id === id ? data.job : current);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '无法停止任务'); }
  };
  const pass = currentAR(result?.metrics?.conditional_global, arPercent);
  const thisJob = shownJob && requestKey(shownJob.request) === currentKey;

  return (
    <div className="rounded-2xl border border-[#c9ddd6] bg-[#f2f8f5] p-4" aria-label={tx("本地仿真计算")}>
      <div className="flex items-center gap-2 font-semibold text-[#173640]">
        <Cpu className="size-4" /> {tx(compact ? '2 · 生成布局并评估' : '生成布局并评估（优先复用结果）')}
      </div>
      <p className="mt-2 text-sm leading-6 text-[#526b71]">
        {tx("先查相同配置的本地记录；没有结果时才优化64个点并保存。复用预计算的电位传递矩阵，直接计算各项指标。")}</p>
      {tx(connection === 'checking' ? <p className="mt-3 text-sm">{tx("正在连接本地计算服务…")}</p> : connection === 'unavailable' ? (
        <div className="mt-3 space-y-2 text-sm leading-6 text-[#806a37]">
          <p>{tx("本地计算服务未连接。此功能需在这台电脑运行本地App；公开网页不会调用电脑资源。")}</p>
          <Button size="sm" variant="outline" onClick={() => { attempted.current = ''; setConnection('checking'); void refreshConnection(); }}>{tx("重新连接")}</Button>
        </div>
      ) : (
        <>
          <details className="mt-3 text-sm"><summary className="cursor-pointer text-[#526b71]">{tx("修改条件后自动计算（默认关闭）")}</summary><label className="mt-3 flex cursor-pointer items-center gap-2 text-sm" htmlFor="automatic-local-compute">
            <Switch id="automatic-local-compute" checked={automatic} onCheckedChange={setAutomatic} />
            {tx("无已有结果时自动启动计算")}</label></details>
          <p className="mt-2 text-xs leading-5 text-[#687c82]">{tx("关闭自动计算仍会读取已有结果。新计算：每次1个任务 · 2线程 · 运行上限180秒，超时后可重新提交。")}</p>
          {tx(unsupported && <p className="mt-3 text-sm leading-6 text-[#806a37]">{tx("该位置范围暂不可计算。请选择全头候选区、少毛发候选区或当前支持的部位组合。")}</p>)}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" className="bg-[#117d72] hover:bg-[#0e6d64]" disabled={busy || submitting || !!unsupported}
              onClick={() => { attempted.current = `${currentKey}:${retry + 1}`; setRetry((value) => value + 1); void submit(); }}>
              {tx(submitting || busy ? <LoaderCircle className="size-4 animate-spin" /> : <Play className="size-4" />)}
              {tx(result ? '读取已保存结果' : shownJob?.status === 'no_layout' && requestKey(shownJob.request) === currentKey ? '读取本次搜索记录' : '开始布局计算')}
            </Button>
            {tx(busy && <Button size="sm" variant="outline" onClick={() => void cancel()}><Square className="size-4" />{tx("停止")}</Button>)}
          </div>
        </>
      ))}
      {tx(busy && job && <div className="mt-3 text-sm leading-6" aria-live="polite">
          <p>{requestKey(job.request) === currentKey ? <RuntimeMessage message={job.message} status={job.status} /> : tx(result ? '另一配置仍在计算；当前配置直接显示已有缓存。' : automatic ? '上一配置正在计算；当前没有匹配缓存，完成后处理最新参数。' : '上一配置正在计算；当前方案尚未提交，完成后可手动计算。')}</p>
          <progress aria-label={tx("仿真任务进度")} max={1} value={job.progress} className="mt-2 h-2 w-full accent-[#117d72]" />
        </div>)}
      <output className="mt-3 block text-sm leading-6" aria-live="polite">
        {tx(result?.metrics && compact ? <p className="font-medium text-[#117d72]">{tx(shownJob?.cached ? '已有结果已读取，未重新计算。' : '计算完成，结果已自动保存。')}</p> : result?.metrics ? <>
          <p className="flex items-center gap-2 font-semibold text-[#117d72]"><CheckCircle2 className="size-4" />{tx(shownJob?.cached ? '已读取本地缓存 · 未重新计算' : '新计算完成 · 已保存到本地')}</p>
          <dl className="mt-3 space-y-2 text-[#405963]">
            {tx([
              ['信号重建保留率', pct(result.metrics.field_relative)],
              ['幅度保留率（最差10%）', pct(result.metrics.sensitivity_tail)],
              ['相对定位评分', pct(result.metrics.localization_relative)],
              ['三项最低相对评分 G', pct(result.metrics.conditional_global)],
              ['定位中位误差', mm(result.metrics.median_mm)],
              ['全头64导中位误差', mm(result.metrics.reference_median_mm)],
            ].map(([label, value]) => <div key={label} className="flex justify-between gap-2"><dt>{tx(label)}</dt><dd className="font-mono font-semibold">{tx(value)}</dd></div>))}
          </dl>
          <p className="mt-3 font-semibold">{tx("最低保留要求 ")}{tx(arPercent)}%：{tx(pass === null ? '指标未定义，无法判断' : pass ? '当前模型点估计达到阈值' : '当前搜索结果未达到阈值')}</p>
          {tx(result.geometry && <p className="mt-2 text-xs leading-5 text-[#687c82]">
            {tx("实际")}{tx(result.geometry.union_connected_component_count)}{tx("个分离区域 · 半径")}{tx((result.geometry.common_graph_radius_mm / 10).toFixed(2))} {tx(" cm · 总面积")}{tx(result.geometry.union_area_cm2.toFixed(2))} {tx(" cm²。设定值为半径上限，实际半径由区域分离约束共同确定。")}</p>)}
        </> : thisJob && shownJob?.status === 'no_layout' ? <div className="text-[#806a37]">
          <p>{tx(shownJob.cached ? '已读取搜索记录：' : '')}{tx("本次搜索未找到完整64点布局，尚无性能指标。AR仅用于性能判定，布局构造由间距、半径和区域分离要求决定。")}</p>
          <p className="mt-2">{tx("相同版本和参数会复用这条记录。可增大半径或扩大允许位置范围后启动新搜索；该配置的整体几何可行性仍待判定。")}</p>
        </div>
          : thisJob && shownJob && ['failed', 'timeout', 'cancelled'].includes(shownJob.status) ? <p className="text-[#806a37]"><RuntimeMessage message={shownJob.message} status={shownJob.status} /></p>
          : busy ? null
          : connection === 'ready' && !unsupported ? <p className="text-[#526b71]">{tx(lookup.key !== currentKey || lookup.state === 'checking' ? '正在查找匹配的本地数据…' : lookup.state === 'error' ? '本地记录读取失败；未自动启动计算。' : automatic ? '没有匹配记录，等待参数稳定后计算…' : '没有匹配记录。点击按钮可计算并保存。')}</p> : null)}
      </output>
      {tx(error && <p role="alert" className="mt-3 text-sm leading-6 text-red-800"><AlertTriangle className="mr-1 inline size-4" /><RuntimeMessage message={error} /></p>)}
      {tx(!compact && <><p className="mt-3 border-t border-[#d7e4de] pt-3 text-xs leading-5 text-[#687c82]">
        {tx("单Ernie头模 · 标准64导名义SNR＝20 dB · 有限网格搜索。位置范围采用模型坐标近似；独立头模验证另列阶段。")}</p>
      <a href="/method#local-compute" className="mt-2 inline-block text-sm font-semibold text-[#117d72] underline underline-offset-2">{tx("本地计算的方法与限制")}</a>
      <a href="/library" className="mt-2 block text-sm font-semibold text-[#117d72] underline underline-offset-2">{tx("打开计算记录")}</a></>)}
    </div>
  );
}
