'use client';
import { useLanguage } from '@/components/language-provider';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useState } from 'react';

import { canCompareRecord } from '@/lib/workspace-navigation';
import { safeReturnHref } from '@/lib/ui-language';
import type { LocalLibrary, SavedRecord } from '@/lib/local-library';

import {
  comparisonNotes,
  parseDecisionThresholds,
  decisionHref,
  exportDesign,
  validateDesign,
  qualification,
  type ElectrodeDesign,
  type DecisionThresholds,
  type DesignJob,
} from '@/lib/design-decision';

export function useDecisionController(
  mode: 'compare' | 'coordinates' = 'compare',
) {
  const { tx, locale } = useLanguage();
  const [library, setLibrary] = useState<LocalLibrary | null>(null),
    [ids, setIds] = useState<string[]>(['', '']);
  const [records, setRecords] = useState<SavedRecord[]>([]),
    [error, setError] = useState(''),
    [ready, setReady] = useState(false);
  const [selectionError, setSelectionError] = useState('');
  const [draftNotice, setDraftNotice] = useState('');
  const [returnTo, setReturnTo] = useState('');
  const [thresholds, setThresholds] = useState<DecisionThresholds>({
    field: 90,
    sensitivity: null,
    localization: null,
    p90_mm: null,
  });
  const [imported, setImported] = useState<ElectrodeDesign | null>(null),
    [importError, setImportError] = useState('');
  const [job, setJob] = useState<DesignJob | null>(null);
  const [busy, setBusy] = useState(false),
    [computeError, setComputeError] = useState(''),
    [testTarget, setTestTarget] = useState(
      mode === 'coordinates' ? 'import' : 'a',
    );
  const [radius, setRadius] = useState(6),
    [seed, setSeed] = useState(42);
  const [action, setAction] = useState<'evaluate' | 'perturb'>('evaluate');
  const [showEvaluated, setShowEvaluated] = useState(true);
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const controller = new AbortController();
    void Promise.resolve().then(() => {
      if (controller.signal.aborted) return;
      setReturnTo(q.get('returnTo') ?? '');
      if (mode === 'coordinates' && q.get('resume') === '1') {
        try {
          const raw = sessionStorage.getItem('eeg-coordinate-tab-draft');
          if (raw) {
            const draft = JSON.parse(raw);
            setImported(validateDesign(draft.design));
            if (
              Number.isInteger(draft.seed) &&
              draft.seed >= 0 &&
              draft.seed <= 9999
            )
              setSeed(draft.seed);
            setDraftNotice('已恢复坐标草稿；尚未重新评价。');
          }
        } catch {
          setImportError('坐标草稿无法恢复，请重新导入文件。');
        }
      }
    });
    fetch('/api/local-compute/library', { signal: controller.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error('启动本地App后可读取方案目录。');
        const data = (await r.json()) as LocalLibrary;
        if (data.schema !== 'local-data-library/1')
          throw new Error('目录格式错误');
        setThresholds(parseDecisionThresholds(q));
        setLibrary(data);
        const eligible = data.records.filter(canCompareRecord);
        const a = q.has('a')
          ? eligible.find((r) => r.id === q.get('a'))
          : (eligible.find(
              (r) =>
                r.dataset_id === 'strict_area' &&
                r.area_cap_cm2 === 60 &&
                r.region_count === 2 &&
                r.mode.includes('whole'),
            ) ?? eligible[0]);
        const b = q.has('b')
          ? eligible.find((r) => r.id === q.get('b'))
          : eligible.find(
              (r) =>
                r.id !== a?.id &&
                r.dataset_id === a?.dataset_id &&
                r.area_cap_cm2 === a?.area_cap_cm2 &&
                r.region_count === 4 &&
                r.mode === a?.mode,
            );
        setIds([a?.id ?? '', b?.id !== a?.id ? (b?.id ?? '') : '']);
        if ((q.has('a') && !a) || (q.has('b') && !b))
          setSelectionError('指定记录不支持此工具，请重新选择布局。');
        setReady(true);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [mode]);
  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    Promise.all(
      ids.filter(Boolean).map(async (id) => {
        const r = await fetch('/api/local-compute/library/' + id, {
          signal: controller.signal,
        });
        if (!r.ok) throw new Error('所选记录读取失败');
        const value = (await r.json()) as { record: SavedRecord };
        if (value.record?.id !== id) throw new Error('返回记录身份不匹配');
        return value.record as SavedRecord;
      }),
    )
      .then((rows) => {
        setRecords(rows);
        setError('');
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [ids, ready]);
  const hereUrl = new URL(
    decisionHref(ids, thresholds).replace(
      '/decision?',
      mode === 'coordinates' ? '/coordinates?' : '/decision?',
    ),
    'http://localhost',
  );
  if (returnTo)
    hereUrl.searchParams.set('returnTo', safeReturnHref(returnTo, '/library'));
  if (mode === 'coordinates' && imported)
    hereUrl.searchParams.set('resume', '1');
  const here = hereUrl.pathname + hereUrl.search;
  useEffect(() => {
    if (mode !== 'coordinates' || !imported) return;
    try {
      sessionStorage.setItem(
        'eeg-coordinate-tab-draft',
        JSON.stringify({ design: imported, seed }),
      );
    } catch {
      void Promise.resolve().then(() =>
        setDraftNotice('当前标签页无法暂存坐标；离开前请保留原始文件。'),
      );
    }
  }, [mode, imported, seed]);
  useEffect(() => {
    if (ready) window.history.replaceState(null, '', here);
  }, [ready, here]);
  const shown = records.filter((r) => ids.includes(r.id));
  const loaded =
    ready && ids.filter(Boolean).every((id) => shown.some((r) => r.id === id));
  const choices = library?.records.filter(canCompareRecord) ?? [];
  const notes = loaded ? comparisonNotes(shown) : [];
  const targetRecord = shown.find(
    (r) => r.id === ids[testTarget === 'b' ? 1 : 0],
  );
  const design =
    testTarget === 'import'
      ? imported
      : targetRecord
        ? exportDesign(targetRecord)
        : null;
  const requestIdentity = JSON.stringify({
    action,
    design,
    radius_mm: radius,
    seed,
  });
  const [jobIdentity, setJobIdentity] = useState('');
  const result =
    jobIdentity === requestIdentity && job?.status === 'completed'
      ? job.result
      : null;
  const resultQualification = result
    ? qualification({ metrics: result.nominal }, thresholds)
    : null;
  const jobId = job?.id,
    jobStatus = job?.status;
  useEffect(() => {
    if (!jobId || !jobStatus || !['running', 'cancelling'].includes(jobStatus))
      return;
    const controller = new AbortController();
    const timer = setInterval(() => {
      fetch('/api/design-evaluation/jobs/' + jobId, {
        signal: controller.signal,
      })
        .then(async (r) => {
          if (!r.ok)
            throw new Error('任务连接中断，请读取相同配置的缓存或重试。');
          const data = (await r.json()) as { job: DesignJob };
          setJob(data.job);
        })
        .catch((e) => {
          if (!controller.signal.aborted) {
            setComputeError(e.message);
            setJob((j) => (j ? { ...j, status: 'connection_lost' } : j));
          }
        });
    }, 1000);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [jobId, jobStatus]);
  const computing =
    busy || (!!job && ['running', 'cancelling'].includes(job.status));
  async function runEvaluation(action: 'evaluate' | 'perturb') {
    if (!design) return;
    const submittedIdentity = JSON.stringify({
      action,
      design,
      radius_mm: radius,
      seed,
    });
    setAction(action);
    setBusy(true);
    setComputeError('');
    try {
      const healthResponse = await fetch('/api/local-compute/health');
      if (!healthResponse.ok) throw new Error('本地计算服务未连接');
      const health = (await healthResponse.json()) as { token: string };
      const response = await fetch('/api/design-evaluation/jobs', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-EEG-Compute-Token': health.token,
        },
        body: JSON.stringify({ action, design, radius_mm: radius, seed }),
      });
      if (!response.headers.get('content-type')?.includes('application/json'))
        throw new Error('设计评价接口未加载，请重启本地App后再试。');
      const data = (await response.json()) as {
        error?: string;
        job: DesignJob;
      };
      if (!response.ok) throw new Error(data.error ?? '计算未启动');
      setJobIdentity(submittedIdentity);
      setJob(data.job);
    } catch (e) {
      setComputeError(e instanceof Error ? e.message : '计算未启动');
    } finally {
      setBusy(false);
    }
  }
  async function cancel() {
    if (!job) return;
    try {
      const h = (await (await fetch('/api/local-compute/health')).json()) as {
        token: string;
      };
      const r = await fetch(
        '/api/design-evaluation/jobs/' + job.id + '/cancel',
        { method: 'POST', headers: { 'X-EEG-Compute-Token': h.token } },
      );
      const data = (await r.json()) as { error?: string; job: DesignJob };
      if (!r.ok) throw new Error(data.error);
      setJob(data.job);
    } catch (e) {
      setComputeError(e instanceof Error ? e.message : '停止请求失败');
    }
  }
  const referenceLayout = shown[0]?.layout;
  const preview =
    design && referenceLayout
      ? {
          id: design.name,
          xyzMm:
            showEvaluated && result ? result.evaluated_xyz_mm : design.xyz_mm,
          regionIndices: design.region_indices,
          referenceXyzMm: referenceLayout.referenceXyzMm,
        }
      : undefined;
  return {
    tx,
    locale,
    ids,
    imported,
    setIds: (next: React.SetStateAction<string[]>) => {
      setSelectionError('');
      setIds(next);
    },
    records,
    error: selectionError || error,
    draftNotice,
    thresholds,
    setThresholds,
    setImported: (value: ElectrodeDesign | null) => {
      setDraftNotice('');
      setImported(value);
    },
    importError,
    setImportError,
    job,
    computeError,
    testTarget,
    setTestTarget,
    radius,
    setRadius,
    seed,
    setSeed,
    action,
    showEvaluated,
    setShowEvaluated,
    here,
    shown,
    loaded,
    choices,
    notes,
    design,
    requestIdentity,
    jobIdentity,
    result,
    resultQualification,
    computing,
    runEvaluation,
    cancel,
    preview,
  };
}
