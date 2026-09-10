'use client';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from "@/components/runtime-message";

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */

import { useEffect, useId, useRef, useState } from 'react';
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
import {
  createHeadScene,
  loadHeadAssets,
  REGION_COLORS,
  type HeadScene,
  type ViewName,
  type LayoutOptions,
} from '@/lib/anatomical-head-scene';

export type { DomainMode } from '@/lib/anatomical-head-scene';
type Props = LayoutOptions;
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
    [showRegions, setShowRegions] = useState(true);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>(
      'loading',
    ),
    [error, setError] = useState('');
  const [view, setView] = useState<ViewName | null>('oblique');
  const [focusedRegion, setFocusedRegion] = useState<number | null>(null);
  const {
    regionCount,
    allocation,
    domainMode,
    maskCodes,
    radiusCm,
    recordedLayout,
    sourceXyzMm,
    sourceNormals,
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
  ]);
  useEffect(() => {
    if (status === 'ready') runtime.current?.setSignals({ electrodeValues: props.electrodeValues, potentialLimit: props.potentialLimit, selectedElectrode: props.selectedElectrode, selectedSource: props.selectedSource, onElectrodeSelect: props.onElectrodeSelect, onSourceSelect: props.onSourceSelect });
  }, [status, recordedLayout, sourceXyzMm, sourceNormals, props.electrodeValues, props.potentialLimit, props.selectedElectrode, props.selectedSource, props.onElectrodeSelect, props.onSourceSelect]);
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
  return (
    <div
      className={`head-stage flex flex-col overflow-hidden ${expanded ? 'fixed inset-0 z-[80] h-[100dvh] rounded-none sm:inset-4 sm:h-auto sm:rounded-2xl' : 'relative h-[640px] rounded-2xl sm:h-[690px]'}`}
    >
      <div className="relative z-10 flex flex-wrap items-center justify-between gap-2 border-b border-[#e0e7eb] bg-white/90 px-3 py-3 sm:px-5">
        <fieldset
          className="flex rounded-xl bg-[#f0f4f6] p-1"
          aria-label={tx("解剖显示方式")}
        >
          <button
            type="button"
            className="head-choice flex items-center gap-1.5"
            aria-pressed={!brain}
            onClick={() => setBrain(false)}
          >
            <ScanFace className="size-4" />
            {tx("头皮视图")}</button>
          <button
            type="button"
            className="head-choice flex items-center gap-1.5"
            aria-pressed={brain}
            onClick={() => setBrain(true)}
          >
            <Brain className="size-4" />
            {tx("透视大脑")}</button>
        </fieldset>
        <div className="flex gap-1.5">
          <Button
            className="head-tool"
            variant="outline"
            size="icon-sm"
            aria-label={tx("复位三维视角")} title={tx("复位视角")}
            onClick={() => changeView('oblique')}
          >
            <RotateCcw className="size-4" />
          </Button>
          <Button
            className="head-tool"
            variant="outline"
            size="icon-sm"
            aria-label={tx(expanded ? '退出全屏三维视图' : '全屏查看三维视图')} title={tx(expanded ? '退出全屏' : '全屏查看')}
            aria-pressed={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {tx(expanded ? (
              <Minimize2 className="size-4" />
            ) : (
              <Maximize2 className="size-4" />
            ))}
          </Button>
        </div>
      </div>
      <fieldset
        aria-label={tx("电极显示")}
        className="relative z-10 flex flex-wrap items-center gap-x-6 gap-y-3 border-b border-[#e0e7eb] bg-white/95 px-4 py-3 text-sm text-[#405963] sm:px-5"
      >
        <label
          htmlFor={controlId + '-reference'}
          className="flex cursor-pointer items-center gap-2.5"
        >
          <Switch
            id={controlId + '-reference'}
            checked={showReference}
            onCheckedChange={setShowReference}
          />
          <span>{tx("标准64导布局")}</span>
        </label>
        <label
          htmlFor={controlId + '-regions'}
          className="flex cursor-pointer items-center gap-2.5"
        >
          <Switch
            id={controlId + '-regions'}
            checked={showRegions}
            onCheckedChange={setShowRegions}
          />
          <span>{props.editor ? tx(`启用电极：${props.editor.active.filter(Boolean).length}`) : tx("所选布局（64电极）")}</span>
        </label>
      </fieldset>
      <div className="relative min-h-0 flex-1">
        <div ref={hostRef} className="absolute inset-0" />
        {tx(status !== 'ready' && (
          <output className="absolute inset-0 grid place-items-center bg-[#f8fafb] px-8 text-center text-sm leading-6 text-[#5a6e79]">
            {tx(status === 'loading' ? (
              '加载头皮、耳廓与脑表面…'
            ) : (
              <span>
                <RuntimeMessage message={error} />
                <br />
                {tx("重新加载页面可重试。")}</span>
            ))}
          </output>
        ))}
        {tx(status === 'ready' && (
          <>
            <div className="pointer-events-none absolute left-4 top-4 max-w-[170px] rounded-lg bg-white/80 px-2.5 py-2 text-sm text-[#405963] sm:left-6 sm:top-6">
              <span className="flex items-center gap-2">
                <span
                  className={`size-3 rounded-full border-[3px] ${showReference ? 'border-[#8c9da7]' : showRegions ? 'border-[#128a80]' : 'border-[#d1d9dd]'} bg-white`}
                />
                {tx(showReference
                  ? recordedLayout
                    ? '标准64导布局'
                    : '标准64导模板位置'
                  : showRegions
                    ? props.editor ? `启用电极：${props.editor.active.filter(Boolean).length}` : '64 个区域电极'
                    : '电极已隐藏')}
              </span>
              <span className="mt-1.5 block text-xs leading-5 text-[#768891]">
                {tx(recordedLayout
                  ? '记录坐标 · 触点外观示意'
                  : '贴片式圆形触点 · 表面示意')}
              </span>
            </div>
            <div className="absolute bottom-4 right-3 flex flex-col gap-2">
              <Button
                className="head-tool"
                variant="outline"
                size="icon-sm"
                aria-label={tx("放大头部")}
                onClick={() => runtime.current?.zoom(0.82)}
              >
                <Plus className="size-4" />
              </Button>
              <Button
                className="head-tool"
                variant="outline"
                size="icon-sm"
                aria-label={tx("缩小头部")}
                onClick={() => runtime.current?.zoom(1.22)}
              >
                <Minus className="size-4" />
              </Button>
            </div>
          </>
        ))}
      </div>
      <div className="relative z-10 border-t border-[#e0e7eb] bg-white/95 px-3 py-3 sm:px-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <fieldset
            className="flex flex-wrap gap-0.5"
            aria-label={tx("头部观察方向")}
          >
            {tx(VIEWS.map((item) => (
              <button
                key={item.id}
                type="button"
                className="head-choice px-2.5 py-1.5"
                aria-pressed={view === item.id}
                onClick={() => changeView(item.id)}
              >
                {tx(item.label)}
              </button>
            )))}
          </fieldset>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-[#5e727e]">
          <span>{tx("共 ")}{tx(props.regionCount)} {tx(" 个区域：")}</span>
          {tx(props.allocation.map((count, index) => (
            <button type="button" className="head-choice flex items-center gap-1.5 border border-[#dce5e9] px-3 py-2" key={index}
              disabled={!recordedLayout || status !== 'ready'} aria-pressed={focusedRegion === index}
              aria-label={tx(`查看区域${index+1}，${count}个电极`)}
              onClick={() => { runtime.current?.focusRegion(index); setFocusedRegion(index); setView(null); }}>
              <span
                className="size-2.5 rounded-full"
                style={{ background: REGION_COLORS[index] }}
              />
              {tx("查看区域 ")}{tx(index + 1)} · {tx(count)} {tx(" 点")}{tx(recordedLayout?.regionAreasCm2?.[index] !== undefined && ` · ${recordedLayout.regionAreasCm2[index].toFixed(2)} cm²`)}
            </button>
          )))}
        </div>
        <p className="mt-2 text-xs leading-5 text-[#768891]">
          {tx(props.editor ? '编辑模式下拖动电极，吸附到原区域候选点；空白处旋转。灰色点已停用。' : "拖动旋转视角（不移动电极）· 双指 / 滚轮缩放 · 右键平移。")}{tx(recordedLayout
            ? `点位采用记录坐标；${recordedLayout.regionPatchVertexIndices ? '彩色面片与面积计算使用同一组表面顶点。点击区域按钮可转到对应区域。' : '此历史记录未保存区域边界。'} 触点大小及离表面偏移用于显示。`
            : '当前为几何示意。计算后将显示满足约束的记录坐标与对应指标。')}
        </p>
        <p className="mt-1 text-xs text-[#768891]">{tx("头部表面：SimNIBS Ernie · CC BY-NC 4.0 · ")}<a href="/method#anatomical-display" className="underline">{tx("来源与显示说明")}</a></p>
      </div>
      <p className="sr-only">
        {tx("显示同一个 SimNIBS Ernie 头模型中的头皮、脸部、双耳和脑表面。")}{tx(recordedLayout
          ? '标准与彩色点位取自所选FEM布局的实际记录坐标；底层显示网格不参与计算。'
          : '标准64点与彩色区域点位仅用于解释空间布局，不参与性能计算。')}
      </p>
    </div>
  );
}
