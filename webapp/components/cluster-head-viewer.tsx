'use client';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from "@/components/runtime-message";

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import {
  Brain,
  Maximize2,
  Minimize2,
  Minus,
  Plus,
  RotateCcw,
  ScanFace,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { SOURCE_REGIONS } from '@/lib/source-regions';
import {
  createHeadScene,
  loadHeadAssets,
  REGION_COLORS,
  type HeadScene,
  type ViewName,
  type LayoutOptions,
} from '@/lib/anatomical-head-scene';

export type { DomainMode } from '@/lib/anatomical-head-scene';
type Props = LayoutOptions & { compact?: boolean };
const VIEWS: { id: ViewName; label: string }[] = [
  { id: 'oblique', label: '斜前' },
  { id: 'front', label: '正面' },
  { id: 'left', label: '左侧' },
  { id: 'right', label: '右侧' },
  { id: 'back', label: '后面' },
  { id: 'top', label: '顶部' },
];
export function ClusterHeadViewer(props: Props) {
  const { tx } = useLanguage();
  const controlId = useId();
  const hostRef = useRef<HTMLDivElement>(null),
    runtime = useRef<HeadScene | null>(null);
  const [expanded, setExpanded] = useState(false),
    [brain, setBrain] = useState(Boolean(props.sourceXyzMm?.length)),
    [showReference, setShowReference] = useState(false),
    [showRegions, setShowRegions] = useState(true),
    [showRearView, setShowRearView] = useState(true);
  const [showSourcePartitions, setShowSourcePartitions] = useState(true);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>(
      'loading',
    ),
    [error, setError] = useState('');
  const [view, setView] = useState<ViewName | null>('oblique');
  const [focusedRegion, setFocusedRegion] = useState<number | null>(null);
  const editing = Boolean(props.editor?.enabled);
  const electrodeCount = props.editor
    ? props.editor.active.filter(Boolean).length
    : props.allocation.reduce((sum, count) => sum + count, 0);
  // Callers build these small arrays inline; keyed by content, a re-render with the same
  // values does not rebuild the scene's electrodes and regions.
  const allocationKey = props.allocation.join(','),
    maskKey = props.maskCodes ? 'm:' + props.maskCodes.join(',') : '';
  const allocation = useMemo(() => (allocationKey ? allocationKey.split(',').map(Number) : []), [allocationKey]);
  const maskCodes = useMemo(() => (maskKey ? maskKey.slice(2).split(',').filter(Boolean) : undefined), [maskKey]);
  const {
    regionCount,
    domainMode,
    radiusCm,
    recordedLayout,
    sourceXyzMm,
    sourceNormals,
    sourceRegions,
  } = props;
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const controller = new AbortController();
    let disposed = false;
    loadHeadAssets(controller.signal)
      .then(([scalp, cortex]) => {
        if (disposed) {
          scalp.dispose();
          cortex.dispose();
          return;
        }
        try {
          runtime.current = createHeadScene(host, scalp, cortex);
          setStatus('ready');
        } catch (reason) {
          scalp.dispose();
          cortex.dispose();
          throw reason;
        }
      })
      .catch((reason) => {
        if (!disposed) {
          setError(
            reason instanceof Error ? reason.message : '三维视图暂不可用',
          );
          setStatus('error');
        }
      });
    return () => {
      disposed = true;
      controller.abort();
      runtime.current?.dispose();
      runtime.current = null;
    };
  }, []);
  useEffect(() => {
    if (status === 'ready')
      runtime.current?.setLayout({
        regionCount,
        allocation,
        domainMode,
        maskCodes,
        radiusCm,
        recordedLayout,
        sourceXyzMm,
        sourceNormals,
        sourceRegions,
      });
  }, [
    status,
    regionCount,
    allocation,
    domainMode,
    maskCodes,
    radiusCm,
    recordedLayout,
    sourceXyzMm,
    sourceNormals,
    sourceRegions,
  ]);
  useEffect(() => {
    if (status === 'ready') runtime.current?.setSignals({ electrodeValues: props.electrodeValues, potentialLimit: props.potentialLimit, selectedElectrode: props.selectedElectrode, selectedSource: props.selectedSource, onElectrodeSelect: props.onElectrodeSelect, onSourceSelect: props.onSourceSelect });
  }, [status, recordedLayout, sourceXyzMm, sourceNormals, sourceRegions, props.electrodeValues, props.potentialLimit, props.selectedElectrode, props.selectedSource, props.onElectrodeSelect, props.onSourceSelect]);
  useEffect(() => { runtime.current?.setSourcePartitions(showSourcePartitions); }, [status, showSourcePartitions]);
  useEffect(() => {
    runtime.current?.setReference(showReference);
  }, [status, showReference]);
  useEffect(() => { if (status === 'ready') runtime.current?.setEditor(props.editor); }, [status, recordedLayout, props.editor]);
  useEffect(() => {
    runtime.current?.setBrain(brain);
  }, [status, brain]);
  useEffect(() => {
    runtime.current?.setRegions(showRegions);
  }, [status, showRegions]);
  useEffect(() => {
    runtime.current?.setRearView(showRearView);
  }, [status, showRearView]);
  useEffect(() => {
    runtime.current?.setGestureCapture(expanded);
  }, [status, expanded]);
  useEffect(() => {
    if (!expanded) return;
    const overflow = document.body.style.overflow;
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setExpanded(false);
    };
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', escape);
    return () => {
      document.body.style.overflow = overflow;
      window.removeEventListener('keydown', escape);
    };
  }, [expanded]);
  const changeView = (name: ViewName) => {
    setView(name);
    setFocusedRegion(null);
    runtime.current?.setView(name);
  };
  useEffect(() => {
    runtime.current?.canvas.setAttribute('aria-label', props.editor
      ? tx(`可旋转的头部与电极布局，启用${props.editor.active.filter(Boolean).length}点，方向键旋转，加减键缩放`)
      : tx('可旋转的真实头部与64电极布局，方向键旋转，加减键缩放'));
  }, [status, tx, props.editor]);
  const gestureNote = editing
    ? '编辑模式下拖动电极，吸附到原区域候选点；空白处旋转。灰色点已停用。'
    : '拖动旋转视角（不移动电极）· 双指 / 滚轮缩放 · 右键平移。';
  const coordinateNote = recordedLayout
    ? `点位采用记录坐标；${recordedLayout.regionPatchVertexIndices ? '彩色面片与面积计算使用同一组表面顶点。点击区域按钮可转到对应区域。' : '此历史记录未保存区域边界。'} 触点大小及离表面偏移用于显示。`
    : '当前为几何示意。计算后将显示满足约束的记录坐标与对应指标。';
  return (
    <div
      data-compact={props.compact ? 'true' : 'false'}
      className={`head-stage @container flex flex-col overflow-hidden ${expanded ? 'fixed inset-0 z-[80] h-[100dvh] rounded-none sm:inset-4 sm:h-auto sm:rounded-2xl' : props.compact ? (brain ? 'relative rounded-2xl sm:h-[580px]' : 'relative rounded-2xl sm:h-[520px]') : brain ? 'relative rounded-2xl sm:h-[730px]' : 'relative rounded-2xl sm:h-[680px]'}`}
    >
      <div className="relative z-10 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border bg-white/95 px-3 py-2 sm:px-4">
        <fieldset
          className="flex shrink-0 rounded-lg bg-background p-0.5"
          aria-label={tx('解剖显示方式')}
        >
          <button
            type="button"
            className="head-choice flex items-center gap-1.5 px-2.5 py-1 text-xs sm:text-sm"
            aria-pressed={!brain}
            onClick={() => setBrain(false)}
          >
            <ScanFace className="size-3.5 sm:size-4" />
            {tx('头皮视图')}
          </button>
          <button
            type="button"
            className="head-choice flex items-center gap-1.5 px-2.5 py-1 text-xs sm:text-sm"
            aria-pressed={brain}
            onClick={() => setBrain(true)}
          >
            <Brain className="size-3.5 sm:size-4" />
            {tx('透视大脑')}
          </button>
        </fieldset>
        <fieldset
          aria-label={tx('电极显示')}
          className="order-3 flex w-full flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border/60 pt-1.5 text-xs text-foreground @[780px]:order-none @[780px]:w-auto @[780px]:border-t-0 @[780px]:pt-0"
        >
          <label
            htmlFor={controlId + '-reference'}
            className="flex cursor-pointer items-center gap-1.5"
          >
            <Switch
              size="sm"
              id={controlId + '-reference'}
              checked={showReference}
              onCheckedChange={setShowReference}
            />
            <span>{tx('标准64导布局')}</span>
          </label>
          <label
            htmlFor={controlId + '-regions'}
            className="flex cursor-pointer items-center gap-1.5"
          >
            <Switch
              size="sm"
              id={controlId + '-regions'}
              checked={showRegions}
              onCheckedChange={setShowRegions}
            />
            <span>
              {tx('当前布局电极')} · {electrodeCount}
            </span>
          </label>
          <label
            htmlFor={controlId + '-rear'}
            className="flex cursor-pointer items-center gap-1.5"
          >
            <Switch
              size="sm"
              id={controlId + '-rear'}
              checked={showRearView}
              onCheckedChange={setShowRearView}
            />
            <span>{tx('后视小窗')}</span>
          </label>
        </fieldset>
        <div className="ml-auto flex shrink-0 gap-1.5 @[780px]:ml-0">
          <Button
            className="head-tool"
            variant="outline"
            size="icon-sm"
            aria-label={tx('复位三维视角')}
            title={tx('复位视角')}
            onClick={() => changeView('oblique')}
          >
            <RotateCcw className="size-4" />
          </Button>
          <Button
            className="head-tool"
            variant="outline"
            size="icon-sm"
            aria-label={tx(expanded ? '退出全屏三维视图' : '全屏查看三维视图')}
            title={tx(expanded ? '退出全屏' : '全屏查看')}
            aria-pressed={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? (
              <Minimize2 className="size-4" />
            ) : (
              <Maximize2 className="size-4" />
            )}
          </Button>
        </div>
      </div>
      {brain && (
        <div className="relative z-10 border-b border-border bg-card/95 px-3 py-1.5 text-xs sm:px-4">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <label
              className="flex shrink-0 cursor-pointer items-center gap-1.5 font-medium"
              htmlFor={controlId + '-source-partitions'}
            >
              <Switch
                size="sm"
                id={controlId + '-source-partitions'}
                checked={showSourcePartitions}
                onCheckedChange={setShowSourcePartitions}
              />
              {tx('DK图谱研究分区')}
            </label>
            {showSourcePartitions && (
              <div
                className="flex flex-wrap items-center gap-1"
                aria-label={tx('六个DK图谱研究区')}
              >
                {SOURCE_REGIONS.map((item) => (
                  <button
                    type="button"
                    key={item.id}
                    className="flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] transition-colors hover:bg-secondary"
                    disabled={status !== 'ready'}
                    onClick={() => {
                      runtime.current?.focusSourceRegion(item.id);
                      setView(null);
                      setFocusedRegion(null);
                    }}
                  >
                    <span
                      aria-hidden="true"
                      className="size-2 rounded-xs"
                      style={{ backgroundColor: item.color }}
                    />
                    {tx(item.label)}
                    {sourceRegions?.includes(item.id) && (
                      <span aria-label={tx('本次已启用源')}>●</span>
                    )}
                  </button>
                ))}
                <span className="flex items-center gap-1 px-1.5 py-0.5 text-[11px] text-ink-soft">
                  <span className="size-2 rounded-xs bg-[#92999f]" />
                  {tx('其他皮层或分区边界')}
                </span>
              </div>
            )}
          </div>
          {showSourcePartitions && (
            <p className="mt-1 text-[11px] leading-4 text-ink-soft">
              {tx(
                '颜色按Ernie皮层的DK图谱标签分组，选源与着色使用同一规则。灰色为其他皮层或分区边界。S编号标记实际生成源；点击图例调整视角。',
              )}
            </p>
          )}
        </div>
      )}
      {/* On phones the stage grows with its panels and the canvas keeps a bounded height,
          so the page can still be scrolled past the viewer. */}
      <div
        className={`relative min-h-0 ${expanded ? 'flex-1' : 'h-[min(62svh,480px)] flex-none sm:h-auto sm:flex-1'}`}
      >
        <div ref={hostRef} className="absolute inset-0" />
        {status !== 'ready' && (
          <output className="absolute inset-0 grid place-items-center bg-background px-8 text-center text-sm leading-6 text-ink-soft">
            {status === 'loading' ? (
              tx('加载头皮、耳廓与脑表面…')
            ) : (
              <span>
                <RuntimeMessage message={error} />
                <br />
                {tx('重新加载页面可重试。')}
              </span>
            )}
          </output>
        )}
        {status === 'ready' && (
          <>
            <div
              className="pointer-events-none absolute left-3 top-3 max-w-[168px] rounded-lg border border-border bg-card/90 px-2 py-1.5 text-[11px] leading-4 text-foreground backdrop-blur-xs"
              aria-label={tx('电极形状图例')}
            >
              <span className="flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className="size-2.5 shrink-0 border-2 border-[#71838e] bg-white"
                />
                <span>
                  {tx('方形：标准64导')}
                  {!showReference && (
                    <span className="ml-1 text-ink-soft">{tx('已隐藏')}</span>
                  )}
                </span>
              </span>
              <span className="mt-1 flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className="size-2.5 shrink-0 rounded-full border-2 border-primary bg-white"
                />
                <span>
                  {tx('圆形：当前布局')}
                  {!showRegions && (
                    <span className="ml-1 text-ink-soft">{tx('已隐藏')}</span>
                  )}
                </span>
              </span>
              <span
                className={`mt-1 block border-t border-border pt-1 font-medium ${editing ? 'text-warning' : 'text-foreground'}`}
              >
                {tx(editing ? '编辑模式 · 拖动电极' : '观察模式 · 拖动旋转')}
              </span>
            </div>
            {showRearView && (
              <div
                data-rear-overview className="pointer-events-none absolute right-3 top-3 aspect-[8/9] w-[clamp(96px,28%,160px)] rounded-lg border border-border shadow-sm"
                aria-label={tx('同一布局的固定后视总览')}
              >
                <span className="absolute inset-x-0 top-0 rounded-t-lg border-b border-border bg-white/90 px-2 py-1 text-center text-[10px] font-medium text-foreground">
                  {tx('后视总览')}
                </span>
              </div>
            )}
            <div className="absolute bottom-4 right-3 flex flex-col gap-2">
              <Button
                className="head-tool"
                variant="outline"
                size="icon-sm"
                aria-label={tx('放大头部')}
                onClick={() => runtime.current?.zoom(0.82)}
              >
                <Plus className="size-4" />
              </Button>
              <Button
                className="head-tool"
                variant="outline"
                size="icon-sm"
                aria-label={tx('缩小头部')}
                onClick={() => runtime.current?.zoom(1.22)}
              >
                <Minus className="size-4" />
              </Button>
            </div>
          </>
        )}
      </div>
      <div className="relative z-10 border-t border-border bg-card/95 px-3 py-2 sm:px-4">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
          <fieldset
            className="flex flex-wrap gap-0.5"
            aria-label={tx('头部观察方向')}
          >
            {VIEWS.map((item) => (
              <button
                key={item.id}
                type="button"
                className="head-choice px-2 py-1 text-xs"
                aria-pressed={view === item.id}
                onClick={() => changeView(item.id)}
              >
                {tx(item.label)}
              </button>
            ))}
          </fieldset>
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-ink-soft">
            <span>
              {tx('共 ')}
              {tx(props.regionCount)} {tx(' 个区域：')}
            </span>
            {props.allocation.map((count, index) => (
              <button
                type="button"
                className="head-choice flex items-center gap-1 border border-border px-2 py-1 text-xs"
                key={index}
                disabled={status !== 'ready'}
                aria-pressed={focusedRegion === index}
                aria-label={tx(`查看区域${index + 1}，${count}个电极`)}
                onClick={() => {
                  runtime.current?.focusRegion(index);
                  setFocusedRegion(index);
                  setView(null);
                }}
              >
                <span
                  aria-hidden="true"
                  className="flex size-4 items-center justify-center rounded-full text-[10px] font-semibold text-white"
                  style={{ background: REGION_COLORS[index] }}
                >
                  {index + 1}
                </span>
                {tx('查看区域 ')}
                {tx(index + 1)} · {tx(count)} {tx(' 点')}
                {tx(
                  recordedLayout?.regionAreasCm2?.[index] !== undefined &&
                    ` · ${recordedLayout.regionAreasCm2[index].toFixed(2)} cm²`,
                )}
              </button>
            ))}
          </div>
        </div>
        <div className="mt-1.5 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-t border-border/60 pt-1.5 text-[11px] leading-4 text-ink-soft">
          {!props.compact && <span>{tx(gestureNote)}</span>}
          {props.compact ? <details className="min-w-0 open:w-full leading-5">
            <summary className="cursor-pointer font-medium text-foreground">{tx('坐标与显示说明')}</summary>
            <p className="mt-1">{tx(gestureNote)} {tx(coordinateNote)}</p>
          </details> : null}
          <span className="ml-auto">
            {tx('头部表面：SimNIBS Ernie · CC BY-NC 4.0 · ')}
            <a href="/method#anatomical-display" className="underline hover:text-foreground">
              {tx('来源与显示说明')}
            </a>
          </span>
          {!props.compact && (
            <details className="w-full leading-5">
              <summary className="cursor-pointer font-medium text-foreground">
                {tx('坐标与显示说明')}
              </summary>
              <p className="mt-1">{tx(coordinateNote)}</p>
            </details>
          )}
        </div>
      </div>
      <p className="sr-only">
        {tx('显示同一个 SimNIBS Ernie 头模型中的头皮、脸部、双耳和脑表面。')}
        {tx(
          recordedLayout
            ? '标准与彩色点位取自所选FEM布局的实际记录坐标；底层显示网格不参与计算。'
            : '标准64点与彩色区域点位仅用于解释空间布局，不参与性能计算。',
        )}
      </p>
    </div>
  );
}
