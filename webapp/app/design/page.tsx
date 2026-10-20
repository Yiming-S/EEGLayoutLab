'use client';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from "@/components/runtime-message";
import { localizedRecordTitle } from "@/lib/i18n/records";

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { SiteHeader } from '@/components/site-header';
import { LocalComputePanel } from '@/components/local-compute-panel';
import { PerformanceSummary, percent } from '@/components/performance-summary';
import { Button } from '@/components/ui/button';
import { requestKey, type ComputeRequest, type ComputeResult, type ComputeJob } from '@/lib/local-compute';
import { comparisonLink, methodLink, parseAR, recordLink, REGION_COUNTS, METRICS } from '@/lib/lab-workflow';
import type { SavedRecord } from '@/lib/local-library';
import { sourceExperimentLink } from '@/lib/source-reception';
import { MASK_NAMES } from '@/lib/ui-language';
import { editorLink } from '@/lib/electrode-editor';
import { DesignPlacementOptions } from '@/components/placement-options';
import { placementChoices, choiceFromSlots, type PlacementChoice as Choice, type PlacementProtocol as Protocol } from '@/lib/placement-options';

const Head = lazy(() => import('@/components/cluster-head-viewer').then((m) => ({ default: m.ClusterHeadViewer })));
const MASKS = MASK_NAMES;
const choicesFor = (protocol: Protocol | null, count: number) => placementChoices(protocol, count, MASKS);
export default function DesignPage() {
  const { tx, locale } = useLanguage();
  const [protocol, setProtocol] = useState<Protocol | null>(null), [ready, setReady] = useState(false), [error, setError] = useState('');
  const [source, setSource] = useState<SavedRecord | null>(null), [originId, setOriginId] = useState(''), [originKind, setOriginKind] = useState('saved');
  const [editing, setEditing] = useState(true), [draft, setDraft] = useState(false);
  const [regions, setRegions] = useState(2), [choiceId, setChoiceId] = useState('PL,PR'), [radius, setRadius] = useState(35), [ar, setAR] = useState(90);
  const [computed, setComputed] = useState<ComputeResult | null>(null), [status, setStatus] = useState<ComputeJob | null>(null);
  const [notice, setNotice] = useState('');
  const [routeParams, setRouteParams] = useState('');
  const [extraChoice, setExtraChoice] = useState<Choice | null>(null);
  const [customSlots, setCustomSlots] = useState<string[]>(['PL', 'PR']);
  const settingsRef = useRef<HTMLDetailsElement>(null);
  useEffect(() => { if (settingsRef.current) settingsRef.current.open = window.matchMedia('(min-width: 68.75rem)').matches; }, [ready]);
  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      const q = new URLSearchParams(window.location.search);
      setRouteParams(q.toString());
      setAR(parseAR(q.get('ar')));
      const response = await fetch('/data/experiment_protocol_v2.json', { signal: controller.signal });
      if (!response.ok) throw new Error('设计配置未载入');
      const p = await response.json() as Protocol; setProtocol(p);
      const id = q.get('saved') ?? q.get('from');
      if (id) {
        if (!/^[a-f0-9]{64}$/.test(id)) throw new Error('方案编号无效，请从计算记录重新选择');
        const res = await fetch('/api/local-compute/library/' + id, { signal: controller.signal, cache: 'no-store' });
        if (!res.ok) throw new Error('所选方案无法读取，请从计算记录重新选择');
        const { record } = await res.json() as { record: SavedRecord };
        if (record.id !== id || (q.has('saved') ? record.dataset_id !== 'cache' || !record.request : record.dataset_id !== 'strict_area')) throw new Error('记录不兼容当前入口，请在计算记录中按原协议查看');
        // Historical radius records restore constraints only. Current scores and
        // coordinates still come exclusively from the current-version lookup.
        if (q.has('saved') && !record.compatible) setNotice('已恢复旧记录的区域与半径条件。下方优先读取当前版本的匹配结果，也可手动启动搜索。原记录可单独查阅。');
        setSource(record); setOriginId(id); setOriginKind(q.has('saved') ? 'saved' : 'from');
        if (record.request) {
          const r = record.request; const key = r.mode === 'preset' ? r.mask_codes!.join(',') : r.mode;
          setRegions(r.region_count); setRadius(r.radius_mm); setChoiceId(key);
          setCustomSlots(r.mask_codes ? [...r.mask_codes] : []);
          if (!choicesFor(p, r.region_count).some((c) => c.id === key)) setExtraChoice({ id: key, label: r.mask_codes!.map((m) => MASKS[m] ?? m).join(' + '), mode: r.mode, maskCodes: r.mask_codes });
        } else { setEditing(false); setRegions(record.region_count); }
      }
      if (q.get('draft') === '1') {
        const r = Number(q.get('r')), a = Number(q.get('radius')), mode = q.get('mode');
        if (!REGION_COUNTS.includes(r) || !Number.isInteger(a) || a < 15 || a > 80 || a % 5 || !['whole_surface', 'low_hair', 'preset', 'choose'].includes(mode || '')) throw new Error('草稿参数无效');
        const masks = q.has('masks') ? q.get('masks')!.split(',') : [];
        if (mode === 'preset' && (masks.length !== r || masks.some((m) => !(m in MASKS)))) throw new Error('草稿位置组合无效');
        if (mode === 'choose' && (masks.length > r || masks.some((m) => m && !(m in MASKS)))) throw new Error('草稿区域部位无效');
        setRegions(r); setRadius(a); setChoiceId(mode === 'choose' ? '' : mode === 'preset' ? masks.join(',') : mode!);
        setCustomSlots(mode === 'preset' || mode === 'choose' ? masks : []);
        if (mode === 'preset') setExtraChoice({ id: masks.join(','), label: masks.map((m) => MASKS[m]).join(' + '), mode, maskCodes: masks });
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
  const request = useMemo<ComputeRequest | null>(() => choice ? { region_count: regions, radius_mm: radius, mode: choice.mode, ...(choice.mode === 'preset' ? { mask_codes: choice.maskCodes } : {}) } : null, [choice, regions, radius]);
  const result = editing && request && computed && requestKey(computed.request) === requestKey(request) ? computed : null;
  const currentStatus = request && status && requestKey(status.request) === requestKey(request) ? status : null;
  const layout = editing ? result?.layout : source?.layout;
  const count = editing ? regions : source?.region_count ?? regions;
  const geometry = editing ? result?.geometry : source?.geometry;
  const metrics = editing ? result?.metrics : source?.metrics;
  const here = useMemo(() => {
    const q = new URLSearchParams(routeParams);
    for (const key of ['saved', 'from', 'draft', 'r', 'radius', 'mode', 'masks', 'layoutRecord', 'layoutState', 'layoutChannels', 'layoutRegions']) q.delete(key);
    q.set('ar', String(ar));
    if (originId) q.set(originKind, originId);
    if (draft) {
      q.set('draft', '1'); q.set('r', String(regions)); q.set('radius', String(radius)); q.set('mode', choice?.mode ?? 'choose');
      if (choice?.maskCodes) q.set('masks', choice.maskCodes.join(','));
      else if (!choice && customSlots.some(Boolean)) q.set('masks', customSlots.join(','));
    }
    return '/design?' + q.toString();
  }, [ar, originId, originKind, draft, regions, radius, choice, customSlots, routeParams]);
  useEffect(() => { if (ready) window.history.replaceState(null, '', here); }, [ready, here]);
  const changeRegions = (n: number) => {
    if (n === regions) return;
    setDraft(true); setRegions(n);
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
  const startRadius = () => {
    if (!source) return;
    setRegions(source.region_count); setChoiceId(source.mode.includes('whole') ? 'whole_surface' : 'low_hair'); setRadius(35);
    setCustomSlots([]);
    setEditing(true); setDraft(true);
    setNotice('已新建每区半径约束方案：仅保留区域数和允许位置域，半径初始值为35 mm。区域中心、64点位置和指标由新配置重新计算。');
  };
  const pendingText = currentStatus?.status === 'no_layout' ? '本次搜索未找到完整64点布局。可扩大半径或调整位置范围后再次计算。' :
    currentStatus && ['failed', 'timeout', 'cancelled'].includes(currentStatus.status) ? currentStatus.message :
    currentStatus && ['queued', 'running', 'cancelling'].includes(currentStatus.status) ? '当前方案正在计算，完成后显示布局与指标。' :
    !choice ? '请先选择与区域数量兼容的位置组合。' : undefined;
  const comparison = comparisonLink(source, ar);
  const receptionId = layout ? editing ? currentStatus?.status === 'completed' ? currentStatus.key : null : source?.id : null;
  return <main className="lab-page">
    <SiteHeader current="design" arPercent={ar} labHref={comparison} returnHref={here} selection={{ id: receptionId ?? null, phase: receptionId ? "saved" : "draft", channels: 64, regions: count }} receptionHref={receptionId ? sourceExperimentLink(receptionId, ar, here) : undefined} />
    <div className="lab-container">
      <header className="py-5"><h1 className="text-2xl font-semibold">{tx("布局设计：设置条件并生成64电极布局")}</h1><p className="mt-2 text-base text-muted-foreground">{tx("先设置区域数、位置范围和每区半径，再点击“开始布局计算”。算法选择电极坐标；拖动3D只旋转视角，不会移动电极。")}</p></header>
      {tx(error ? <div role="alert" className="lab-panel text-red-800"><RuntimeMessage message={error} />。<a href={'/library?ar=' + ar} className="ml-2 underline">{tx("返回计算记录")}</a></div> : !ready ? <p className="lab-panel">{tx("正在恢复所选方案与AR…")}</p> : <>
        {tx(source && <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3 text-sm"><span>{tx("来源：")}{localizedRecordTitle(source, locale)}</span><a className="text-primary underline" href={recordLink(source, ar)}>{tx("打开原记录")}</a></div>)}
        {tx(notice && <output className="mb-4 block rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm leading-6">{tx(notice)}</output>)}
        <div className="grid items-start gap-4 md:grid-cols-[minmax(0,1fr)_300px] min-[68.75rem]:grid-cols-[260px_minmax(0,1fr)_300px]">
          <details className="lab-panel md:col-span-2 min-[68.75rem]:col-span-1" ref={settingsRef} open>
            <summary className="cursor-pointer text-base font-semibold">{tx('布局参数')} · {count} {tx('个区域')}{editing && <> · {radius} mm</>}</summary>
            <div className="mt-5 space-y-5">
            {editing && <DesignPlacementOptions count={regions} choices={choices} selected={choice?.id ?? ''} slots={customSlots} onSelect={selectChoice} onSlot={selectSlot} onCount={changeRegions} compact />}
            <h2 className="text-lg font-semibold">{tx(editing ? '2 · 设置尺寸并计算' : '总面积上限约束记录 · 只读')}</h2>
            {tx(!editing && source ? <>
              <p className="text-sm leading-7">{tx(source.region_count)}{tx("个严格分离区域")}<br />{tx("总面积上限 ")}{tx(source.area_cap_cm2)} cm²<br />{tx("实际总面积 ")}{tx(source.geometry?.union_area_cm2.toFixed(2))} cm²</p>
              <p className="text-sm leading-6 text-muted-foreground">{tx("这是总面积上限约束实验的原始布局。按需计算使用每区半径约束，创建新配置后重新搜索和评价。")}</p>
              <Button onClick={startRadius} className="w-full">{tx("新建每区半径约束方案")}</Button>
              <p className="text-xs leading-5 text-muted-foreground">{tx("新建不会覆盖原方案，也不会立即启动计算。")}</p>
            </> : <>
              <p className="text-sm leading-6">{tx(choice?.label ?? '请先补全上方区域部位')}<br />{tx("各区电极数：")}{tx(Array.from({ length: regions }, (_, i) => Math.floor(64 / regions) + Number(i < 64 % regions)).join(' + '))}</p>
              <label className="lab-label">{tx("每区表面半径上限 · ")}{tx(radius)} mm<input className="mt-3 w-full accent-primary" type="range" aria-label={tx("每区半径上限")} min={15} max={80} step={5} value={radius} onChange={(e) => { setRadius(Number(e.target.value)); setDraft(true); }} /><span className="mt-1 block text-xs font-normal leading-5 text-muted-foreground">{tx("半径按头表面网格路径计算；实际半径同时受区域分离约束。")}</span></label>
            </>)}
            <label className="lab-label border-t pt-4">{tx("接受阈值 AR · ")}{tx(ar)}%<input className="mt-3 w-full accent-primary" type="range" aria-label={tx("设计接受阈值AR")} min={10} max={100} step={1} value={ar} onChange={(e) => setAR(Number(e.target.value))} /><span className="mt-1 block text-xs font-normal text-muted-foreground">{tx("只更新结果判断，不改变点位或运行计算。")}</span></label>
            {tx(editing && request && <LocalComputePanel key={originId + ':editor'} request={request} arPercent={ar} onResult={setComputed} onStatus={setStatus} compact />)}
            <details className="border-t pt-4 text-sm"><summary className="cursor-pointer font-medium">{tx("计算设置与限制")}</summary><p className="mt-3 text-xs leading-6 text-muted-foreground">{tx("固定64电极 · 最小电极直线间距4 mm · 单Ernie头模 · 标准64导名义SNR＝20 dB。各布局使用相同物理噪声尺度。算法在有限候选网格内搜索，位置范围按模型坐标近似定义。")}</p><a href={methodLink(here, ar, '#local-compute')} className="mt-2 inline-block text-primary underline">{tx("完整方法")}</a></details>
            </div>
          </details>
          {metrics && <dl className="grid grid-cols-3 gap-2 rounded-xl border bg-card p-3 text-xs md:hidden" aria-label={tx('当前布局指标摘要')}>
            {METRICS.map((metric) => <div key={metric.key}><dt className="leading-5 text-muted-foreground">{tx(metric.label)}</dt><dd className="mt-1 font-mono text-base font-semibold">{percent(metrics[metric.key])}</dd></div>)}
          </dl>}
          <div className="min-w-0">
            <p className="mb-2 text-sm font-semibold">{tx(layout ? editing ? '3 · 已生成并评估的布局' : '总面积上限原记录 · 未修改点位' : choice ? '布局示意 · 待计算' : '请先选择各区域部位')}</p>
            {receptionId && layout?.regionPatchVertexIndices && <a className="mb-3 inline-flex rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground" href={editorLink(receptionId, ar)}>{tx('编辑此布局的电极 →')}</a>}
            {tx(choice || !editing ? <Suspense fallback={<div className="lab-panel min-h-[520px]">{tx("加载三维头部…")}</div>}><Head compact regionCount={count} allocation={Array.from({ length: count }, (_, i) => Math.floor(64 / count) + Number(i < 64 % count))} domainMode={!editing ? source?.mode.includes('whole') ? 'whole_surface' : 'low_hair' : choice!.mode} maskCodes={editing ? choice?.maskCodes : undefined} radiusCm={!editing ? (geometry?.common_graph_radius_mm ?? 35) / 10 : radius / 10} recordedLayout={layout ?? undefined} /></Suspense> : <div className="lab-panel min-h-[400px] grid place-items-center text-muted-foreground">{tx("选择位置组合后显示示意预览")}</div>)}
            {tx(geometry && <div className="mt-3 rounded-lg border bg-card p-4 text-sm leading-7">{tx("实际 ")}{tx(geometry.union_connected_component_count)} {tx(" 个分离区域 · 实际共用表面半径 ")}{tx(geometry.common_graph_radius_mm.toFixed(2))} {tx(" mm · 总面积 ")}{tx(geometry.union_area_cm2.toFixed(2))} {tx(" cm² · 最小电极直线间距 ")}{tx(geometry.minimum_chord_distance_mm.toFixed(2))} mm</div>)}
          </div>
          <div><PerformanceSummary compact metrics={metrics} ar={ar} returnHref={here} basis={tx(editing ? '每区半径上限约束搜索；新结果自动保存为计算记录' : '总面积上限约束原实验；只读，不触发计算')} empty={tx(pendingText)} emptyTitle={tx(currentStatus?.status === 'no_layout' ? '本次未构造出完整布局' : currentStatus && ['failed', 'timeout', 'cancelled'].includes(currentStatus.status) ? '计算未完成' : undefined)} /></div>
        </div>
        <section className="lab-panel mt-5 flex flex-wrap items-center justify-between gap-4"><div><h2 className="font-semibold">{tx("用同一脑源测试这个布局")}</h2><p className="mt-1 text-sm text-muted-foreground">{tx("对照标准64的时间波形与重建，分别加入模拟心电和眼电。固定点位，不重新优化。")}</p></div>{tx(receptionId ? <a className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground" href={sourceExperimentLink(receptionId, ar, here)}>{tx("打开信号仿真 →")}</a> : <span className="text-sm text-muted-foreground">{tx("先计算出完整64点布局后可进入")}</span>)}</section>
        <p className="mt-5 text-sm text-muted-foreground"><a className="text-primary underline" href={comparison}>{tx(source?.dataset_id === 'strict_area' ? '返回来源比较' : '查看已有结果')}</a> {tx(" · 新半径方案不会加入固定面积曲线；在")}<a className="text-primary underline" href={'/library?ar=' + ar}>{tx("计算记录")}</a>{tx("中查看。")}</p>
      </>)}
    </div>
  </main>;
}
