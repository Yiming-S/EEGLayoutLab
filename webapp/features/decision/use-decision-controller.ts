'use client';
import { CONDUCTIVITY_SCENARIOS, NOISE_MODEL_PRESETS, normalizeDataPrior } from '../../contracts/scientific-options.mjs';
import { useLanguage } from '@/components/language-provider';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useRef, useState } from 'react';

import { followTask, submitTask, cancelTask, isTaskRunning, type TaskConnection } from '@/client/task-client';

import { canCompareRecord } from '@/lib/workspace-navigation';
import { safeReturnHref } from '@/lib/ui-language';
import type { LocalLibrary, SavedRecord } from '@/lib/local-library';
import type { DataPrior } from '@/lib/local-compute';

import {
  comparisonNotes,
  jointDecisionThresholds,
  parseDecisionThresholds,
  decisionHref,
  exportDesign,
  designSubmission,
  restoreDesignEvaluation,
  validateDesign,
  qualification,
  type ElectrodeDesign,
  type DecisionThresholds,
  type DesignJob,
  type NoiseModel,
} from '@/lib/design-decision';

/** What a result was computed for: the fields the request carries, after the defaults each option implies. */
function evaluationIdentity(value: { action: string; design: unknown; radius_mm?: number; seed?: number; noise: string; scenario: string; robustness: boolean; prior: DataPrior | null }) {
  const evaluate = value.action === 'evaluate';
  return JSON.stringify({ action: value.action, design: value.design, radius_mm: value.radius_mm, seed: value.seed,
    // A data prior carries its own noise, so the noise choice is not part of the request.
    noise: value.prior ? '' : value.noise, scenario: evaluate ? value.scenario : '', robustness: evaluate && !value.scenario && value.robustness, prior: value.prior });
}

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
  const [annotationRefs, setAnnotationRefs] = useState<Record<string, string>>({});
  const [draftNotice, setDraftNotice] = useState('');
  const [returnTo, setReturnTo] = useState('');
  const [thresholds, setThresholds] = useState<DecisionThresholds>(jointDecisionThresholds());
  const [imported, setImported] = useState<ElectrodeDesign | null>(null),
    [importError, setImportError] = useState('');
  const [pollRevision, setPollRevision] = useState(0);
  const [connection, setConnection] = useState<TaskConnection>('connected');
  const alive = useRef(true);
  const requestController = useRef<AbortController | null>(null);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; requestController.current?.abort(); };
  }, []);
  const [job, setJob] = useState<DesignJob | null>(null);
  const [jobIdentity, setJobIdentity] = useState('');
  const [restoredRecord, setRestoredRecord] = useState('');
  const [busy, setBusy] = useState(false),
    [computeError, setComputeError] = useState(''),
    [testTarget, setTestTarget] = useState(
      mode === 'coordinates' ? 'import' : 'a',
    );
  const [radius, setRadius] = useState(6),
    [seed, setSeed] = useState(42),
    [noiseModelId, setNoiseModelId] = useState('iid'),
    [scenarioId, setScenarioId] = useState(''),
    [robustness, setRobustness] = useState(false),
    [dataPrior, setDataPrior] = useState<DataPrior | null>(null),
    [dataPriorSource, setDataPriorSource] = useState('');
  const noiseModel = NOISE_MODEL_PRESETS.find((preset) => preset.id === noiseModelId)?.value as NoiseModel | undefined;
  const [action, setAction] = useState<'evaluate' | 'perturb'>('evaluate');
  const [showEvaluated, setShowEvaluated] = useState(true);
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const controller = new AbortController();
    void Promise.resolve().then(() => {
      if (controller.signal.aborted) return;
      setReturnTo(q.get('returnTo') ?? '');
      if (mode === 'coordinates' && q.has('a') && q.get('resume') !== '1') setTestTarget('a');
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
            if ([3, 6, 10].includes(draft.radius_mm)) setRadius(draft.radius_mm);
            if (['evaluate', 'perturb'].includes(draft.action)) setAction(draft.action);
            if (NOISE_MODEL_PRESETS.some((preset) => preset.id === draft.noise_model_id)) setNoiseModelId(draft.noise_model_id);
            if (CONDUCTIVITY_SCENARIOS.some((scenario) => scenario.id === draft.conductivity_scenario)) setScenarioId(draft.conductivity_scenario);
            if (draft.robustness === true) setRobustness(true);
            try {
              const prior = normalizeDataPrior(draft.data_prior) as DataPrior | undefined;
              if (prior) { setDataPrior(prior); setDataPriorSource(typeof draft.data_prior_source === 'string' ? draft.data_prior_source.slice(0, 200) : ''); }
            } catch { /* An invalid stored prior is dropped; the draft still restores. */ }
            setDraftNotice('已恢复坐标草稿；尚未重新评价。');
          }
        } catch {
          setImportError('坐标草稿无法恢复，请重新导入文件。');
        }
      }
    });
    fetch('/api/local-compute/library', { signal: controller.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error('方案目录暂时无法读取，请稍后重试。');
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
        const refs: Record<string, string> = {};
        for (const [row, key] of [[a, 'annotation_a'], [b, 'annotation_b']] as const) {
          const value = q.get(key);
          if (row && value && /^[a-f0-9]{64}$/.test(value)) refs[row.id] = value;
        }
        setAnnotationRefs(refs);
        if (mode === 'coordinates' && a?.dataset_id === 'design_evaluation' && q.has('a') && q.get('resume') !== '1') setRestoredRecord(a.id);
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
        const r = await fetch('/api/local-compute/library/' + id + (annotationRefs[id] ? '?annotation_id=' + annotationRefs[id] : ''), {
          signal: controller.signal,
        });
        if (!r.ok) throw new Error('所选记录读取失败');
        const value = (await r.json()) as { record: SavedRecord };
        if (value.record?.id !== id) throw new Error('返回记录身份不匹配');
        let saved;
        if (id === restoredRecord) {
          const response = await fetch('/api/local-compute/library/' + id + '/bundle' + (annotationRefs[id] ? '?annotation_id=' + annotationRefs[id] : ''), { signal: controller.signal });
          if (!response.ok) throw new Error('保存的坐标评价读取失败');
          saved = restoreDesignEvaluation(await response.json(), value.record);
        }
        return { record: value.record, saved };
      }),
    )
      .then((rows) => {
        if (controller.signal.aborted) return;
        setRecords(rows.map(row => row.record));
        const saved = rows.find(row => row.saved);
        if (saved?.saved) {
          const { design, action, radius_mm, seed, noise_model_id, conductivity_scenario, robustness: robust, data_prior, result } = saved.saved;
          setImported(design); setTestTarget('import'); setAction(action); setRadius(radius_mm); setSeed(seed); setNoiseModelId(noise_model_id); setScenarioId(conductivity_scenario); setRobustness(robust);
          setDataPrior(data_prior ?? null); setDataPriorSource('');
          setJobIdentity(evaluationIdentity({ action, design, radius_mm, seed, noise: noise_model_id, scenario: conductivity_scenario, robustness: robust, prior: data_prior ?? null }));
          setJob({ id: 'saved-' + saved.record.id, key: saved.record.id, status: 'completed', message: '已载入保存的坐标评价。', progress: 1, result, cached: true,
            ...(saved.record.electrode_annotation ? { annotation_id: saved.record.electrode_annotation.id, electrode_annotation: saved.record.electrode_annotation } : {}) });
        }
        setError('');
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [ids, ready, annotationRefs, restoredRecord]);
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
  const requestIdentity = evaluationIdentity({ action, design, radius_mm: radius, seed, noise: noiseModelId, scenario: scenarioId, robustness, prior: dataPrior });
  const result =
    jobIdentity === requestIdentity && job?.status === 'completed'
      ? job.result
      : null;
  const resultQualification = result
    ? qualification({ metrics: result.nominal }, thresholds)
    : null;
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
  ids.forEach((id, index) => { if (annotationRefs[id]) hereUrl.searchParams.set(index ? 'annotation_b' : 'annotation_a', annotationRefs[id]); });
  if (restoredRecord && job?.key === restoredRecord && result) hereUrl.searchParams.delete('resume');
  const here = hereUrl.pathname + hereUrl.search;
  useEffect(() => {
    if (mode !== 'coordinates' || !imported) return;
    try {
      sessionStorage.setItem(
        'eeg-coordinate-tab-draft',
        JSON.stringify({ design: imported, seed, radius_mm: radius, action, noise_model_id: noiseModelId, conductivity_scenario: scenarioId, robustness,
          ...(dataPrior ? { data_prior: dataPrior, data_prior_source: dataPriorSource } : {}) }),
      );
    } catch {
      void Promise.resolve().then(() =>
        setDraftNotice('当前标签页无法暂存坐标；离开前请保留原始文件。'),
      );
    }
  }, [mode, imported, seed, radius, action, noiseModelId, scenarioId, robustness, dataPrior, dataPriorSource]);
  useEffect(() => {
    if (ready) window.history.replaceState(null, '', here);
  }, [ready, here]);
  const jobSnapshot = useRef(job);
  useEffect(() => { jobSnapshot.current = job; }, [job]);
  // An evaluation runs for up to ten minutes; a visitor who leaves and comes back gets it back.
  useEffect(() => {
    if (mode !== 'coordinates') return;
    const controller = new AbortController();
    fetch('/api/design-evaluation/health', { signal: controller.signal, cache: 'no-store' })
      .then((response) => (response.ok ? response.json() : null))
      .then((health: { active_job?: DesignJob | null } | null) => {
        const active = health?.active_job, request = active?.request;
        if (controller.signal.aborted || !active || !request || !isTaskRunning(active) || jobSnapshot.current) return;
        if (request.action !== 'evaluate' && request.action !== 'perturb') return;
        let restored: ElectrodeDesign, prior: DataPrior | undefined;
        try { restored = validateDesign(request.design); prior = normalizeDataPrior(request.data_prior) as DataPrior | undefined; } catch { return; }
        const noise = NOISE_MODEL_PRESETS.find((preset) => JSON.stringify(preset.value ?? null) === JSON.stringify(request.noise_model ?? null))?.id ?? 'iid';
        const scenario = request.action === 'evaluate' ? (request.conductivity_scenario ?? '') : '';
        setImported(restored); setTestTarget('import');
        if (typeof request.radius_mm === 'number') setRadius(request.radius_mm);
        if (typeof request.seed === 'number') setSeed(request.seed);
        const robust = request.action === 'evaluate' && request.robustness === 'standard/1';
        setAction(request.action); setNoiseModelId(noise); setScenarioId(scenario); setRobustness(robust); setDataPrior(prior ?? null); setDataPriorSource('');
        setJobIdentity(evaluationIdentity({ action: request.action, design: restored, radius_mm: request.radius_mm, seed: request.seed, noise, scenario, robustness: robust, prior: prior ?? null }));
        setJob(active); setPollRevision((value) => value + 1);
        setDraftNotice('已恢复离开前提交的坐标评价，正在继续查询进度。');
      })
      .catch(() => { /* Without the service, the page works as before. */ });
    return () => controller.abort();
  }, [mode]);
  /** After repeated failed polls, the visitor can ask again instead of reloading the page. */
  const reconnect = () => { setConnection('connected'); setComputeError(''); setPollRevision((value) => value + 1); };
  const jobId = job?.id,
    jobStatus = job?.status;
  useEffect(() => {
    const initial = jobSnapshot.current;
    if (!initial || !isTaskRunning(initial)) return;
    const controller = new AbortController();
    void followTask({
      service: 'design-evaluation', initial, signal: controller.signal,
      onJob(value) { setJob((current) => current?.id === jobId ? value : current); },
      onConnection(state, failure) {
        setConnection(state);
        setComputeError(failure?.message ?? '');
      },
    }).catch(() => { /* Connection errors are separate from backend task status. */ });
    return () => controller.abort();
  }, [jobId, jobStatus, pollRevision]);
  const computing = busy || (isTaskRunning(job) && connection !== 'blocked');
  async function runEvaluation(action: 'evaluate' | 'perturb') {
    if (!design || computing) return;
    const submittedIdentity = evaluationIdentity({ action, design, radius_mm: radius, seed, noise: noiseModelId, scenario: scenarioId, robustness, prior: dataPrior });
    setAction(action);
    setBusy(true);
    setComputeError('');
    try {
      const controller = new AbortController();
      requestController.current = controller;
      const data = await submitTask<{ job: DesignJob }>('design-evaluation',
        designSubmission(design, action, radius, seed, noiseModel, scenarioId || undefined, robustness, dataPrior ?? undefined), { signal: controller.signal, errorMessage: '计算未启动' });
      if (!alive.current) return;
      setConnection('connected');
      setPollRevision(value => value + 1);
      setJobIdentity(submittedIdentity);
      setJob(data.job);
    } catch (e) {
      if (alive.current) setComputeError(e instanceof Error ? e.message : '计算未启动');
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  async function cancel() {
    if (!job) return;
    try {
      const id = job.id;
      const data = await cancelTask<{ job: DesignJob }>('design-evaluation', id);
      if (alive.current) setJob(current => current?.id === id ? data.job : current);
    } catch (e) {
      if (alive.current) setComputeError(e instanceof Error ? e.message : '停止请求失败');
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
    connection,
    testTarget,
    setTestTarget,
    radius,
    setRadius,
    seed,
    setSeed,
    noiseModelId,
    scenarioId,
    setScenarioId,
    robustness,
    setRobustness,
    setNoiseModelId,
    dataPrior,
    dataPriorSource,
    setDataPrior: (value: DataPrior | null, source = '') => { setDataPrior(value); setDataPriorSource(value ? source : ''); },
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
    reconnect,
    runEvaluation,
    cancel,
    preview,
  };
}
