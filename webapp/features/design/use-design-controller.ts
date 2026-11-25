'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import { apiJson } from '@/client/task-client';
import { requestKey, type ComputeRequest, type ComputeResult, type ComputeJob, type DataPrior, type SearchNoiseModel } from '@/lib/local-compute';
import { dataPriorParam, parseDataPriorParam } from '@/lib/data-prior';
import { NOISE_MODEL_PRESETS, noiseModelId as presetIdFor, normalizeDataPrior } from '../../contracts/scientific-options.mjs';
import { comparisonLink, parseAR, REGION_COUNTS } from '@/lib/lab-workflow';
import type { SavedRecord } from '@/lib/local-library';
import { MASK_NAMES } from '@/lib/ui-language';
import { placementChoices, choiceFromSlots, type PlacementChoice as Choice, type PlacementProtocol as Protocol } from '@/lib/placement-options';

const MASKS = MASK_NAMES;
const choicesFor = (protocol: Protocol | null, count: number) => placementChoices(protocol, count, MASKS);
/** Noise presets usable by layout search (brain background is localization-only). */
export const SEARCH_NOISE_PRESETS = NOISE_MODEL_PRESETS.filter((preset) => preset.search);
const searchNoise = (id: string) => SEARCH_NOISE_PRESETS.find((preset) => preset.id === id)?.value as SearchNoiseModel | undefined;

export function useDesignController() {
  const [protocol, setProtocol] = useState<Protocol | null>(null), [ready, setReady] = useState(false), [error, setError] = useState('');
  const [source, setSource] = useState<SavedRecord | null>(null), [originId, setOriginId] = useState(''), [originKind, setOriginKind] = useState('saved');
  const [editing, setEditing] = useState(true), [draft, setDraft] = useState(false);
  const [regions, setRegions] = useState(2), [choiceId, setChoiceId] = useState('PL,PR'), [radius, setRadius] = useState(35), [ar, setAR] = useState(90);
  const [allocationMode, setAllocationMode] = useState<'balanced' | 'adaptive'>('balanced');
  const [objectiveMode, setObjectiveMode] = useState<'min' | 'composite'>('min');
  const [computed, setComputed] = useState<ComputeResult | null>(null), [status, setStatus] = useState<ComputeJob | null>(null);
  const [notice, setNotice] = useState('');
  const [routeParams, setRouteParams] = useState('');
  const [extraChoice, setExtraChoice] = useState<Choice | null>(null);
  const [customSlots, setCustomSlots] = useState<string[]>(['PL', 'PR']);
  const [noiseModelId, setNoiseModelId] = useState('iid');
  const [dataPrior, setDataPrior] = useState<DataPrior | null>(null), [dataPriorSource, setDataPriorSource] = useState('');
  const settingsRef = useRef<HTMLDetailsElement>(null);
  useEffect(() => { if (settingsRef.current) settingsRef.current.open = window.matchMedia('(min-width: 64rem)').matches; }, [ready]);
  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      const q = new URLSearchParams(window.location.search);
      setRouteParams(q.toString());
      setAR(parseAR(q.get('ar')));
      const p = await apiJson<Protocol>('/data/experiment_protocol_v2.json', { signal: controller.signal, cache: 'default', errorMessage: '设计配置未载入' });
      setProtocol(p);
      const id = q.get('saved') ?? q.get('from');
      if (id) {
        if (!/^[a-f0-9]{64}$/.test(id)) throw new Error('方案编号无效，请从计算记录重新选择');
        const { record } = await apiJson<{ record: SavedRecord }>('/api/local-compute/library/' + id, { signal: controller.signal, errorMessage: '所选方案无法读取，请从计算记录重新选择' });
        if (record.id !== id || (q.has('saved') ? record.dataset_id !== 'cache' || !record.request : record.dataset_id !== 'strict_area')) throw new Error('记录不兼容当前入口，请在计算记录中按原协议查看');
        // Historical radius records restore constraints only. Current scores and
        // coordinates still come exclusively from the current-version lookup.
        if (q.has('saved') && !record.compatible) setNotice('已恢复旧记录的区域与半径条件。下方优先读取当前版本的匹配结果，也可手动启动搜索。原记录可单独查阅。');
        setSource(record); setOriginId(id); setOriginKind(q.has('saved') ? 'saved' : 'from');
        if (record.request) {
          const r = record.request; const key = r.mode === 'preset' ? r.mask_codes!.join(',') : r.mode;
          setRegions(r.region_count); setRadius(r.radius_mm); setChoiceId(key);
          setAllocationMode(r.allocation_mode === 'adaptive' && r.region_count > 1 ? 'adaptive' : 'balanced');
          setObjectiveMode(r.objective_mode === 'composite' ? 'composite' : 'min');
          setCustomSlots(r.mask_codes ? [...r.mask_codes] : []);
          setNoiseModelId(presetIdFor(r.noise_model));
          setDataPrior((normalizeDataPrior(r.data_prior) as DataPrior | undefined) ?? null);
          if (!choicesFor(p, r.region_count).some((c) => c.id === key)) setExtraChoice({ id: key, label: r.mask_codes!.map((m) => MASKS[m] ?? m).join(' + '), mode: r.mode, maskCodes: r.mask_codes });
        } else { setEditing(false); setRegions(record.region_count); }
      }
      if (q.get('draft') === '1') {
        const r = Number(q.get('r')), a = Number(q.get('radius')), mode = q.get('mode');
        if (!REGION_COUNTS.includes(r) || !Number.isInteger(a) || a < 15 || a > 80 || a % 5 || !['whole_surface', 'low_hair', 'preset', 'choose'].includes(mode || '')) throw new Error('草稿参数无效');
        const masks = q.has('masks') ? q.get('masks')!.split(',') : [];
        if (mode === 'preset' && (masks.length !== r || masks.some((m) => !(m in MASKS)))) throw new Error('草稿位置组合无效');
        if (mode === 'choose' && (masks.length > r || masks.some((m) => m && !(m in MASKS)))) throw new Error('草稿区域部位无效');
        const alloc = q.get('allocation') ?? 'balanced';
        if (!['balanced', 'adaptive'].includes(alloc) || (alloc === 'adaptive' && r === 1)) throw new Error('草稿配额模式无效');
        const obj = q.get('objective') ?? 'min';
        if (!['min', 'composite'].includes(obj)) throw new Error('草稿优化目标无效');
        setRegions(r); setRadius(a); setChoiceId(mode === 'choose' ? '' : mode === 'preset' ? masks.join(',') : mode!);
        setAllocationMode(alloc as 'balanced' | 'adaptive');
        setObjectiveMode(obj as 'min' | 'composite');
        setCustomSlots(mode === 'preset' || mode === 'choose' ? masks : []);
        if (mode === 'preset') setExtraChoice({ id: masks.join(','), label: masks.map((m) => MASKS[m]).join(' + '), mode, maskCodes: masks });
        const noise = q.get('noise') ?? 'iid';
        if (!SEARCH_NOISE_PRESETS.some((preset) => preset.id === noise)) throw new Error('草稿噪声模型无效');
        setNoiseModelId(noise);
        if (q.has('prior')) {
          try { setDataPrior(parseDataPriorParam(q.get('prior')!)); } catch { throw new Error('草稿数据先验无效'); }
        }
        setEditing(true); setDraft(true);
      }
      setReady(true);
    };
    void load().catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, []);
  const choices = useMemo(() => {
    const items = choicesFor(protocol, regions);
    if (extraChoice && extraChoice.maskCodes?.length === regions && !items.some((c) => c.id === extraChoice.id)) items.push(extraChoice);
    return items;
  }, [protocol, regions, extraChoice]);
  const choice = choices.find((c) => c.id === choiceId);
  const request = useMemo<ComputeRequest | null>(() => {
    if (!choice) return null;
    const noise_model = searchNoise(noiseModelId);
    // A data prior carries its own noise and replaces the noise model.
    return { region_count: regions, radius_mm: radius, mode: choice.mode, ...(choice.mode === 'preset' ? { mask_codes: choice.maskCodes } : {}),
      ...(noise_model && !dataPrior ? { noise_model } : {}), ...(dataPrior ? { data_prior: dataPrior } : {}),
      ...(allocationMode === 'adaptive' && regions > 1 ? { allocation_mode: 'adaptive' as const } : {}),
      ...(objectiveMode === 'composite' ? { objective_mode: 'composite' as const } : {}) };
  }, [choice, regions, radius, noiseModelId, dataPrior, allocationMode, objectiveMode]);
  const result = editing && request && computed && requestKey(computed.request) === requestKey(request) ? computed : null;
  const currentStatus = request && status && requestKey(status.request) === requestKey(request) ? status : null;
  const layout = editing ? result?.layout : source?.layout;
  const count = editing ? regions : source?.region_count ?? regions;
  const geometry = editing ? result?.geometry : source?.geometry;
  const metrics = editing ? result?.metrics : source?.metrics;
  const here = useMemo(() => {
    const q = new URLSearchParams(routeParams);
    for (const key of ['saved', 'from', 'draft', 'r', 'radius', 'mode', 'masks', 'noise', 'prior', 'allocation', 'objective', 'layoutRecord', 'layoutState', 'layoutChannels', 'layoutRegions']) q.delete(key);
    q.set('ar', String(ar));
    if (originId) q.set(originKind, originId);
    if (draft) {
      q.set('draft', '1'); q.set('r', String(regions)); q.set('radius', String(radius)); q.set('mode', choice?.mode ?? 'choose');
      if (choice?.maskCodes) q.set('masks', choice.maskCodes.join(','));
      else if (!choice && customSlots.some(Boolean)) q.set('masks', customSlots.join(','));
      if (noiseModelId !== 'iid') q.set('noise', noiseModelId);
      if (dataPrior) q.set('prior', dataPriorParam(dataPrior));
      if (allocationMode === 'adaptive' && regions > 1) q.set('allocation', 'adaptive');
      if (objectiveMode === 'composite') q.set('objective', 'composite');
    }
    return '/design?' + q.toString();
  }, [ar, originId, originKind, draft, regions, radius, choice, customSlots, noiseModelId, dataPrior, allocationMode, objectiveMode, routeParams]);
  useEffect(() => { if (ready) window.history.replaceState(null, '', here); }, [ready, here]);
  const changeRegions = (n: number) => {
    if (n === regions) return;
    setDraft(true); setRegions(n);
    if (n === 1) setAllocationMode('balanced');
    setCustomSlots([]);
    if (choice?.mode === 'preset' && choice.maskCodes?.length !== n) { setChoiceId(''); setNotice('区域数量已改变，请重新选择各区域的部位。'); }
  };
  const selectChoice = (c: Choice) => {
    setChoiceId(c.id); setCustomSlots(c.maskCodes ? [...c.maskCodes] : []); setDraft(true); setNotice('');
  };
  const selectSlot = (index: number, value: string) => {
    const slots = Array.from({ length: regions }, (_, i) => i === index ? value : customSlots[i] ?? '');
    const selected = choiceFromSlots(slots, regions, MASKS);
    setCustomSlots(slots); setExtraChoice(selected); setChoiceId(selected?.id ?? ''); setDraft(true);
    setNotice(selected ? '' : `已选${slots.filter(Boolean).length}/${regions}个区域的部位。请补全每个区域后开始计算。`);
  };
  const selectNoiseModel = (id: string) => {
    if (!SEARCH_NOISE_PRESETS.some((preset) => preset.id === id)) return;
    setNoiseModelId(id); setDraft(true);
  };
  const selectDataPrior = (value: DataPrior | null, from = '') => {
    setDataPrior(value); setDataPriorSource(value ? from : ''); setDraft(true);
  };
  const selectAllocationMode = (mode: 'balanced' | 'adaptive') => {
    if (regions === 1 && mode === 'adaptive') return;
    setAllocationMode(mode); setDraft(true);
  };
  const selectObjectiveMode = (mode: 'min' | 'composite') => {
    setObjectiveMode(mode); setDraft(true);
  };
  const startRadius = () => {
    if (!source) return;
    setRegions(source.region_count); setChoiceId(source.mode.includes('whole') ? 'whole_surface' : 'low_hair'); setRadius(35); setAllocationMode('balanced'); setObjectiveMode('min'); setNoiseModelId('iid'); setDataPrior(null); setDataPriorSource('');
    setCustomSlots([]);
    setEditing(true); setDraft(true);
    setNotice('已新建每区半径约束方案：仅保留区域数和允许位置域，半径初始值为35 mm。区域中心、64点位置和指标由新配置重新计算。');
  };
  const pendingText = currentStatus?.status === 'no_layout' ? '本次搜索未找到完整64点布局。可扩大半径或调整位置范围后再次计算。' :
    currentStatus && ['failed', 'timeout', 'cancelled'].includes(currentStatus.status) ? currentStatus.message :
    currentStatus && ['queued', 'running', 'cancelling'].includes(currentStatus.status) ? '当前方案正在计算，完成后显示布局与指标。' :
    !choice ? '请先选择与区域数量兼容的位置组合。' : undefined;
  const comparison = comparisonLink(source, ar);
  // Signal simulation and the electrode editor keep independent noise and the area prior.
  const shown = editing ? request : source?.request;
  const correlatedNoise = Boolean(shown?.noise_model || shown?.data_prior);
  const savedId = layout ? editing ? currentStatus?.status === 'completed' ? currentStatus.key : null : source?.id ?? null : null;
  const receptionId = correlatedNoise ? null : savedId;
  return { error, ready, ar, comparison, here, savedId, receptionId, correlatedNoise, count, source, notice, settingsRef, editing, radius, regions, allocationMode, selectAllocationMode, objectiveMode, selectObjectiveMode, choices, choice, customSlots, selectChoice, selectSlot, changeRegions, startRadius, setRadius, noiseModelId, selectNoiseModel, dataPrior, dataPriorSource, selectDataPrior, setDraft, setAR, request, originId, setComputed, setStatus, metrics, layout, geometry, pendingText, currentStatus };
}
