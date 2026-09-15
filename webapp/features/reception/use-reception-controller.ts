'use client';
import { useLanguage } from '@/components/language-provider';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useMemo, useState } from 'react';

import { safeReturnHref } from '@/lib/ui-language';
import { parseAR } from '@/lib/lab-workflow';
import type { LocalLibrary } from '@/lib/local-library';
import {
  BRAIN_REGIONS,
  sourceKey,
  sourceBackLink,
  type SourceJob,
  type SourceRequest,
  type SourceCatalog,
} from '@/lib/source-reception';

export const running = (job: SourceJob | null) =>
  Boolean(job && ['queued', 'running', 'cancelling'].includes(job.status));
type SourceResponse = { job: SourceJob; error?: string; hit?: boolean };

export function useReceptionController() {
  const { tx, locale } = useLanguage();
  const [library, setLibrary] = useState<LocalLibrary | null>(null),
    [id, setId] = useState(''),
    [ready, setReady] = useState(false);
  const [region, setRegion] = useState('frontal'),
    [waveform, setWaveform] = useState<'burst' | 'rhythm'>('burst'),
    [scale, setScale] = useState(1),
    [seed, setSeed] = useState(2026),
    [ar, setAR] = useState(90);
  const [mode, setMode] = useState<'multi_source' | 'single_source'>(
    'multi_source',
  );
  const [singleIndex, setSingleIndex] = useState(0);
  const [catalog, setCatalog] = useState<SourceCatalog | null>(null);
  const [catalogError, setCatalogError] = useState('');
  const [back, setBack] = useState('/design'),
    [token, setToken] = useState(''),
    [fatal, setFatal] = useState(''),
    [retry, setRetry] = useState(0);
  const [active, setActive] = useState<SourceJob | null>(null),
    [stored, setStored] = useState<SourceJob | null>(null),
    [submitting, setSubmitting] = useState(false);
  const [lookup, setLookup] = useState({ key: '', message: '' }),
    [error, setError] = useState({ key: '', message: '' });
  useEffect(() => {
    const restore = () => {
      const q = new URLSearchParams(window.location.search),
        value = q.get('record') ?? '';
      if (value && !/^[a-f0-9]{64}$/.test(value)) {
        setFatal('方案编号无效，请从计算记录重新选择。');
        setId(value);
        setReady(true);
        return;
      }
      setFatal('');
      setRegion('frontal');
      setWaveform('burst');
      setScale(1);
      setSeed(2026);
      setSingleIndex(0);
      setId(value);
      setAR(parseAR(q.get('ar')));
      setMode(
        q.get('sourceMode') === 'single_source'
          ? 'single_source'
          : 'multi_source',
      );
      if (
        q.has('source') &&
        Number.isInteger(Number(q.get('source'))) &&
        Number(q.get('source')) >= 0 &&
        Number(q.get('source')) < 256
      )
        setSingleIndex(Number(q.get('source')));
      if (BRAIN_REGIONS.some(([key]) => key === q.get('region')))
        setRegion(q.get('region')!);
      if (q.get('wave') === 'rhythm') setWaveform('rhythm');
      if (q.has('scale') && [0, 0.5, 1, 2, 4].includes(Number(q.get('scale'))))
        setScale(Number(q.get('scale')));
      if (
        q.has('seed') &&
        Number.isInteger(Number(q.get('seed'))) &&
        Number(q.get('seed')) >= 0 &&
        Number(q.get('seed')) <= 9999
      )
        setSeed(Number(q.get('seed')));
      const from = q.get('returnTo');
      setBack(safeReturnHref(from, '/design'));
      setReady(true);
    };
    restore();
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  useEffect(() => {
    const c = new AbortController();
    void Promise.all([
      fetch('/api/source-reception/layouts', {
        signal: c.signal,
        cache: 'no-store',
      }),
      fetch('/api/source-reception/health', {
        signal: c.signal,
        cache: 'no-store',
      }),
    ])
      .then(async ([l, h]) => {
        if (!l.ok || !h.ok)
          throw new Error('源实验服务未连接，请确认本地App正在运行。');
        const data = (await l.json()) as LocalLibrary,
          health = (await h.json()) as {
            token: string;
            active_job: SourceJob | null;
          };
        if (c.signal.aborted) return;
        setLibrary(data);
        setToken(health.token);
        setActive(health.active_job);
        setFatal('');
      })
      .catch((e) => {
        if (!c.signal.aborted) setFatal(e.message);
      });
    return () => c.abort();
  }, [retry]);
  useEffect(() => {
    if (mode !== 'single_source') return;
    const c = new AbortController();
    fetch('/api/source-reception/catalog', {
      signal: c.signal,
      cache: 'no-store',
    })
      .then(async (r) => {
        const data = (await r.json()) as SourceCatalog & { error?: string };
        if (!r.ok) throw new Error(data.error);
        return data;
      })
      .then((value) => {
        if (!c.signal.aborted) {
          setCatalog(value);
          setCatalogError('');
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) setCatalogError(e.message);
      });
    return () => c.abort();
  }, [mode, retry]);
  const records = useMemo(
    () =>
      library?.records.filter(
        (r) => r.status === 'completed' && r.dataset_id !== 'offline_radius',
      ) ?? [],
    [library],
  );
  const selected = records.find((r) => r.id === id);
  const request = useMemo<SourceRequest>(() => {
    const common = { record_id: id, waveform, artifact_scale: scale, seed };
    return mode === 'single_source'
      ? { ...common, mode, source_index: singleIndex }
      : selected?.dataset_id === 'design_evaluation'
        ? { ...common, mode, brain_region: region }
        : { ...common, brain_region: region };
  }, [
    id,
    region,
    waveform,
    scale,
    seed,
    mode,
    singleIndex,
    selected?.dataset_id,
  ]);
  const key = sourceKey(request);
  const job =
    active && sourceKey(active.request) === key
      ? active
      : stored && sourceKey(stored.request) === key
        ? stored
        : null;
  const result =
    job?.status === 'completed' &&
    job.result &&
    sourceKey(job.result.request) === key
      ? job.result
      : null;
  const returnHref = sourceBackLink(back, ar);
  const here = `/reception?record=${id}&ar=${ar}&region=${region}&wave=${waveform}&scale=${scale}&seed=${seed}&sourceMode=${mode}&source=${singleIndex}&returnTo=${encodeURIComponent(returnHref)}`;
  useEffect(() => {
    if (ready) window.history.replaceState(null, '', here);
  }, [ready, here]);
  useEffect(() => {
    if (!token || !selected || !ready) return;
    const c = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const r = await fetch('/api/source-reception/lookup', {
          method: 'POST',
          signal: c.signal,
          headers: {
            'Content-Type': 'application/json',
            'X-EEG-Compute-Token': token,
          },
          body: key,
        });
        const value = (await r.json()) as SourceResponse;
        if (!r.ok) throw new Error(value.error || '缓存读取失败');
        if (c.signal.aborted) return;
        if (value.hit) setStored(value.job);
        setLookup({
          key,
          message: value.hit
            ? '已读取本地缓存，不重新计算。'
            : '该源场景尚未计算。点击下方按钮运行；改变AR不触发计算。',
        });
        setError({ key, message: '' });
      } catch (e) {
        if (!c.signal.aborted)
          setError({
            key,
            message: e instanceof Error ? e.message : '读取失败',
          });
      }
    }, 250);
    return () => {
      clearTimeout(timer);
      c.abort();
    };
  }, [key, token, selected, ready]);
  const busy = running(active);
  const activeId = active?.id;
  const activeRequestKey = active ? sourceKey(active.request) : '';
  useEffect(() => {
    if (!busy || !activeId) return;
    const c = new AbortController(),
      jobId = activeId,
      activeKey = activeRequestKey;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const r = await fetch('/api/source-reception/jobs/' + jobId, {
          signal: c.signal,
          cache: 'no-store',
        });
        const value = (await r.json()) as SourceResponse;
        if (!r.ok) throw new Error(value.error || '任务连接中断');
        if (c.signal.aborted) return;
        setActive(value.job);
        if (running(value.job)) timer = setTimeout(poll, 900);
      } catch (e) {
        if (!c.signal.aborted) {
          setError({
            key: activeKey,
            message: e instanceof Error ? e.message : '任务连接中断',
          });
          setActive((a) =>
            a
              ? {
                  ...a,
                  status: 'failed',
                  result: null,
                  message: '连接中断，请刷新服务并重新读取',
                }
              : null,
          );
        }
      }
    };
    timer = setTimeout(poll, 300);
    return () => {
      clearTimeout(timer);
      c.abort();
    };
  }, [activeId, activeRequestKey, busy]);
  const submit = async () => {
    if (!selected || busy || submitting || !token) return;
    setSubmitting(true);
    setError({ key, message: '' });
    try {
      const r = await fetch('/api/source-reception/jobs', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-EEG-Compute-Token': token,
        },
        body: key,
      });
      const data = (await r.json()) as SourceResponse;
      if (!r.ok) throw new Error(data.error || '本机正忙，请稍后手动重试');
      setActive(data.job);
    } catch (e) {
      setError({ key, message: e instanceof Error ? e.message : '提交失败' });
    } finally {
      setSubmitting(false);
    }
  };
  const cancel = async () => {
    if (!active || !token) return;
    try {
      const r = await fetch(`/api/source-reception/jobs/${active.id}/cancel`, {
        method: 'POST',
        headers: { 'X-EEG-Compute-Token': token },
      });
      const data = (await r.json()) as SourceResponse;
      if (!r.ok) throw new Error(data.error);
      setActive(data.job);
    } catch {
      setError({ key, message: '停止请求失败，请刷新服务确认任务状态' });
    }
  };
  return {
    tx,
    locale,
    library,
    id,
    setId,
    ready,
    region,
    setRegion,
    waveform,
    setWaveform,
    scale,
    setScale,
    seed,
    setSeed,
    ar,
    setAR,
    mode,
    setMode,
    singleIndex,
    setSingleIndex,
    catalog,
    catalogError,
    token,
    fatal,
    setRetry,
    active,
    submitting,
    lookup,
    error,
    records,
    selected,
    request,
    key,
    job,
    result,
    returnHref,
    here,
    busy,
    submit,
    cancel,
  };
}
