'use client';

import { conductivityScenarioLabel, dataPriorLabel, noiseModelLabel, NOISE_MODEL_PRESETS } from '../../contracts/scientific-options.mjs';
import { RuntimeMessage } from '@/components/runtime-message';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { lazy, Suspense, useMemo, useState } from 'react';
import { ChevronDown, Download } from 'lucide-react';
import { SiteHeader } from '@/components/site-header';
import { Button } from '@/components/ui/button';
import type { SavedRecord } from '@/lib/local-library';
import { protocolName } from '@/lib/ui-language';
import type { Locale } from '@/lib/i18n/core';
import { localizedRecordTitle } from '@/lib/i18n/records';
import {
  decisionMarkdown,
  decisionCriteriaSummary,
  decisionHref,
  decisionThresholdMode,
  designCSV,
  exportDesign,
  isConductivityScenario,
  isPerturbationRadius,
  minimumDistance,
  PERTURBATION_RADII,
  mm,
  parseDesign,
  pct,
  qualification,
  type DecisionThresholds,
  type ElectrodeDesign,
} from '@/lib/design-decision';
import { figureSpacing, layoutFigureSvg } from '@/lib/layout-figure';
import { useDecisionController } from './use-decision-controller';
import { RecordPicker } from './record-picker';
import { ComparisonConclusion } from './comparison-conclusion';
import { layoutHref } from '@/lib/layout-page';
import { SaveToProject } from '@/features/projects/project-context';
import { DecisionRequirements } from './decision-requirements';
import { CoordinateReviewPanel } from './coordinate-review-panel';
import { RobustnessPanel } from './robustness-panel';
import { EvaluationConditions } from '@/features/conditions/evaluation-conditions';
import { bidsNeedsMniSurface, parseBIDSElectrodes, parseElectrodeLabels } from '@/lib/bids-electrodes';
import { loadErnieMniSurface } from '@/lib/ernie-mni';
import { parseBrowserMontageFile, type RegionCount } from '@/lib/head-frame-import';
import type { MontageUnit } from '@/lib/montage-files';
import { CoordinateFileExports } from './coordinate-file-exports';
import { LayoutFigureExport } from './layout-figure-export';
import { evaluationPresentation } from './evaluation-presentation';
import { CoordinateStudyLink } from '@/features/robustness/coordinate-study-link';
import { FilePicker } from '@/components/ui/file-picker';
import { useLanguage } from '@/components/language-provider';
import { OutcomeBadge } from '@/components/retention-bar';
import { cn } from '@/lib/utils';

const Head = lazy(() =>
  import('@/components/cluster-head-viewer').then((m) => ({
    default: m.ClusterHeadViewer,
  })),
);

function download(name: string, body: string, mime: string) {
  const url = URL.createObjectURL(new Blob([body], { type: mime }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function safeExportDesign(record: SavedRecord): ElectrodeDesign | null {
  try {
    return exportDesign(record);
  } catch {
    return null;
  }
}

type Difference = {
  get: (r: SavedRecord) => number | null | undefined;
  unit: 'pp' | 'mm' | 'cm²';
  better?: 'higher' | 'lower';
};
/** Rows of the record table that have a meaningful B − A difference. */
const DIFFERENCES: Record<string, Difference> = {
  实际区域面积: { get: (r) => r.geometry?.union_area_cm2, unit: 'cm²' },
  实际最小直线点距: { get: (r) => r.geometry?.minimum_chord_distance_mm, unit: 'mm' },
  信号重建保留率: { get: (r) => r.metrics?.field_relative, unit: 'pp', better: 'higher' },
  '幅度保留率（最差10%）': { get: (r) => r.metrics?.sensitivity_tail, unit: 'pp', better: 'higher' },
  相对定位评分: { get: (r) => r.metrics?.localization_relative, unit: 'pp', better: 'higher' },
  '定位误差 · 中位数': { get: (r) => r.metrics?.median_mm, unit: 'mm', better: 'lower' },
  '定位误差 · P90': { get: (r) => r.metrics?.p90_mm, unit: 'mm', better: 'lower' },
};

function deltaHalfRatio(spec: Difference, x: number, y: number, scaledDelta: number) {
  const denom =
    spec.unit === 'pp'
      ? 25
      : spec.unit === 'mm'
        ? Math.max(Math.abs(x), Math.abs(y), 10)
        : Math.max(Math.abs(x), Math.abs(y), 60);
  return Math.min(1, Math.abs(scaledDelta) / denom);
}

function DifferenceCell({ spec, a, b }: { spec?: Difference; a?: SavedRecord; b?: SavedRecord }) {
  const { tx } = useLanguage();
  const x = a && spec?.get(a),
    y = b && spec?.get(b);
  if (!spec || x == null || y == null || !Number.isFinite(x) || !Number.isFinite(y))
    return <td className="px-4 py-2.5 text-muted-foreground">—</td>;
  const d = y - x,
    scaled = spec.unit === 'pp' ? d * 100 : d,
    digits = spec.unit === 'mm' ? 1 : 2;
  const zero = Math.abs(scaled) < 0.5 * 10 ** -digits;
  const text =
    (zero ? '±' : d > 0 ? '+' : '−') +
    Math.abs(scaled).toFixed(digits) +
    (spec.unit === 'pp' ? tx(' 个百分点') : ' ' + spec.unit);
  const tone =
    zero || !spec.better ? '' : (spec.better === 'higher') === d > 0 ? 'text-success' : 'text-warning';
  const barColor =
    tone === 'text-success'
      ? 'bg-success'
      : tone === 'text-warning'
        ? 'bg-warning'
        : 'bg-primary/55';
  const ratio = zero ? 0 : deltaHalfRatio(spec, x, y, scaled),
    halfPct = ratio * 50;
  return (
    <td className={cn('px-4 py-2.5 font-mono whitespace-nowrap tabular-nums', tone)}>
      <div className="leading-tight">
        {text}
        {tone && <span className="sr-only">{tx(tone === 'text-success' ? '（B更好）' : '（B更差）')}</span>}
      </div>
      <div
        aria-hidden="true"
        className="relative mt-1 h-1.5 w-28 overflow-hidden rounded-full bg-muted"
      >
        <span className="absolute inset-y-0 left-1/2 w-px bg-foreground/30" />
        {halfPct > 0 && (
          <span
            className={cn('absolute inset-y-0 rounded-full', barColor)}
            style={
              d >= 0
                ? { left: '50%', width: `${halfPct}%` }
                : { left: `${50 - halfPct}%`, width: `${halfPct}%` }
            }
          />
        )}
      </div>
    </td>
  );
}

function LayoutPairComparisonPanel({
  shown,
  ids,
  locale,
  testTarget,
  onSelectTarget,
}: {
  shown: SavedRecord[];
  ids: string[];
  locale: Locale;
  testTarget: string;
  onSelectTarget: (slot: 'a' | 'b') => void;
}) {
  const { tx } = useLanguage();
  const cards = useMemo(
    () =>
      shown.map((record) => {
        const slotIndex = ids.indexOf(record.id) === 1 ? 1 : 0,
          slotKey = (slotIndex === 1 ? 'b' : 'a') as 'a' | 'b',
          slotName = slotIndex === 1 ? '方案B' : '方案A',
          design = safeExportDesign(record),
          crowded = design ? figureSpacing(design) < 16 : true;
        return { record, slotKey, slotName, design, crowded };
      }),
    [shown, ids],
  );
  const defaultShowLabels = cards.length > 0 && cards.every((card) => !card.crowded);
  const pairIdentity = cards.map((card) => card.record.id).join(':');
  const [labelChoice, setLabelChoice] = useState<{ key: string; show: boolean } | null>(null);
  const showLabels = labelChoice?.key === pairIdentity ? labelChoice.show : defaultShowLabels;

  const rendered = useMemo(
    () =>
      cards.map((card) => {
        const titleText = `${tx(card.slotName)} · ${localizedRecordTitle(card.record, locale)}`;
        if (!card.design) return { ...card, titleText, svg: null, preview: null };
        const regionCount = Math.max(...card.design.region_indices) + 1;
        const svg = layoutFigureSvg(
          card.design,
          {
            title: titleText,
            subtitle: tx(`64个电极 · ${regionCount}个区域 · Ernie模板头`),
            region: (index) => (locale === 'en' ? `Region ${index + 1}` : `区域${index + 1}`),
            caption: [
              tx('圆为NAS–LPA–RPA平面，低于该平面的电极画在圆外。位置为模板头上的设计位置，不是实测位置。'),
            ],
          },
          { labels: showLabels },
        );
        return {
          ...card,
          titleText,
          svg,
          preview: 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg),
        };
      }),
    [cards, locale, showLabels, tx],
  );

  return (
    <section className="lab-panel space-y-4" data-layout-pair-comparison>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{tx('方案空间布局并排对照')}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {tx('同尺度等距方位投影（鼻尖朝上，圆为NAS–LPA–RPA基准平面），直观对照两套方案的区域覆盖与电极疏密。')}
          </p>
        </div>
        {rendered.some((card) => card.svg) && (
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border/75 bg-muted/40 px-3 py-1.5 text-xs font-medium">
            <input
              type="checkbox"
              className="accent-primary"
              checked={showLabels}
              onChange={(event) =>
                setLabelChoice({ key: pairIdentity, show: event.target.checked })
              }
            />
            {tx('显示电极名称')}
          </label>
        )}
      </div>
      <div className={cn('grid gap-4', rendered.length > 1 ? 'md:grid-cols-2' : 'max-w-xl')}>
        {rendered.map((card) => {
          const activeTarget = testTarget === card.slotKey;
          return (
            <div
              key={card.record.id}
              className={cn(
                'flex flex-col justify-between rounded-2xl border border-border/80 bg-muted/25 p-4 transition-all',
                activeTarget && 'border-primary/50 ring-1 ring-primary/35',
              )}
            >
              <div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span
                    className={cn(
                      'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold',
                      card.slotKey === 'a'
                        ? 'bg-primary/15 text-primary'
                        : 'bg-sky-500/15 text-sky-700 dark:text-sky-300',
                    )}
                  >
                    {tx(card.slotName)} · {card.record.region_count}
                    {tx('区')}
                  </span>
                  <div className="flex flex-wrap items-center gap-2 font-mono text-xs text-muted-foreground tabular-nums">
                    <span>
                      {card.record.geometry
                        ? `${card.record.geometry.union_area_cm2.toFixed(1)} cm²`
                        : tx('未提供')}
                    </span>
                    <span>·</span>
                    <span>
                      {tx(`最小直线点距：${mm(card.record.geometry?.minimum_chord_distance_mm)}`)}
                    </span>
                  </div>
                </div>
                {card.preview ? (
                  /* oxlint-disable-next-line next/no-img-element -- data URI preview of generated 2D layout SVG */
                  <img
                    className="mt-3 w-full rounded-xl border border-border/75 bg-white shadow-2xs"
                    src={card.preview}
                    alt={tx(`${card.titleText}的二维布局图`)}
                  />
                ) : (
                  <p className="mt-3 rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
                    {tx('该记录暂无可绘制的64点模板坐标。')}
                  </p>
                )}
              </div>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant={activeTarget ? 'default' : 'outline'}
                  aria-pressed={activeTarget}
                  onClick={() => onSelectTarget(card.slotKey)}
                >
                  {tx(activeTarget ? '当前偏移测试对象' : '设为偏移测试对象')}
                </Button>
                {card.svg && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      download(
                        `eeg-${card.slotKey.toUpperCase()}-layout.svg`,
                        card.svg!,
                        'image/svg+xml;charset=utf-8',
                      )
                    }
                  >
                    {tx('下载')} SVG
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

const niceErrorCeiling = (maxVal: number) => {
  if (!Number.isFinite(maxVal) || maxVal <= 0) return 20;
  const padded = maxVal * 1.15,
    mag = 10 ** Math.floor(Math.log10(padded)),
    norm = padded / mag,
    step = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((item) => item >= norm) ?? 10;
  return step * mag;
};

function PairedMetricsVisual({
  a,
  b,
  thresholds,
}: {
  a: SavedRecord;
  b: SavedRecord;
  thresholds: DecisionThresholds;
}) {
  const { tx } = useLanguage();
  const joint = decisionThresholdMode(thresholds) === 'joint';
  const retentionRows = [
    {
      label: '信号重建保留率',
      va: a.metrics?.field_relative,
      vb: b.metrics?.field_relative,
      limit: thresholds.field,
    },
    {
      label: '幅度保留率（最差10%）',
      va: a.metrics?.sensitivity_tail,
      vb: b.metrics?.sensitivity_tail,
      limit: joint ? thresholds.field : thresholds.sensitivity,
    },
    {
      label: '相对定位评分',
      va: a.metrics?.localization_relative,
      vb: b.metrics?.localization_relative,
      limit: joint ? thresholds.field : thresholds.localization,
    },
  ];
  const retentionVals = retentionRows.flatMap((row) =>
    [row.va, row.vb]
      .filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
      .map((v) => v * 100),
  );
  const retMin = retentionVals.length && Math.min(...retentionVals) < 0
      ? Math.floor(Math.min(...retentionVals) / 10) * 10
      : 0,
    retMax = retentionVals.length && Math.max(...retentionVals) > 100
      ? Math.ceil(Math.max(...retentionVals) / 10) * 10
      : 100,
    retSpan = Math.max(1e-9, retMax - retMin);

  const errorRows = [
    {
      label: '定位误差 · 中位数',
      va: a.metrics?.median_mm,
      vb: b.metrics?.median_mm,
      limit: null as number | null,
    },
    {
      label: '定位误差 · P90',
      va: a.metrics?.p90_mm,
      vb: b.metrics?.p90_mm,
      limit: joint ? null : thresholds.p90_mm,
    },
  ];
  const errorVals = [
    ...errorRows.flatMap((row) =>
      [row.va, row.vb].filter((v): v is number => typeof v === 'number' && Number.isFinite(v)),
    ),
    ...(thresholds.p90_mm != null && !joint ? [thresholds.p90_mm] : []),
  ];
  const errMax = niceErrorCeiling(errorVals.length ? Math.max(...errorVals) : 20);

  return (
    <div className="mt-4 rounded-xl border border-border/75 bg-muted/25 p-4 space-y-3" data-paired-metrics-visual>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-semibold text-foreground">{tx('核心指标直观对照')}</span>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-2.5 w-4 rounded-sm bg-primary" />
            <span>{tx('方案A')}</span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-2.5 w-4 rounded-sm bg-sky-600 dark:bg-sky-400" />
            <span>{tx('方案B')}</span>
          </span>
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">
            {tx('保留率对比（%，越高越优；竖线为启用阈值）')}
          </p>
          {retentionRows.map((row) => {
            const zeroPct = ((0 - retMin) / retSpan) * 100;
            const barStyle = (raw: number | null | undefined) => {
              if (raw == null || !Number.isFinite(raw)) return null;
              const val = raw * 100,
                pos = ((Math.min(retMax, Math.max(retMin, val)) - retMin) / retSpan) * 100;
              return val >= 0
                ? { left: `${zeroPct}%`, width: `${Math.max(0.8, pos - zeroPct)}%` }
                : { left: `${pos}%`, width: `${Math.max(0.8, zeroPct - pos)}%` };
            };
            const styleA = barStyle(row.va),
              styleB = barStyle(row.vb),
              limitPct =
                row.limit != null ? ((Math.min(retMax, Math.max(retMin, row.limit)) - retMin) / retSpan) * 100 : null;
            return (
              <div key={row.label} className="space-y-1 text-xs">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-medium">{tx(row.label)}</span>
                  <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                    A {tx(pct(row.va))} · B {tx(pct(row.vb))}
                  </span>
                </div>
                <div
                  aria-hidden="true"
                  className="relative h-5 rounded-md bg-card ring-1 ring-inset ring-border/70"
                >
                  {retMin < 0 && (
                    <span
                      className="absolute inset-y-0 w-px bg-foreground/30"
                      style={{ left: `${zeroPct}%` }}
                    />
                  )}
                  {styleA && (
                    <span
                      className="absolute top-0.5 h-1.5 rounded-sm bg-primary"
                      style={styleA}
                    />
                  )}
                  {styleB && (
                    <span
                      className="absolute bottom-0.5 h-1.5 rounded-sm bg-sky-600 dark:bg-sky-400"
                      style={styleB}
                    />
                  )}
                  {limitPct !== null && (
                    <span
                      className="absolute -inset-y-0.5 w-0.5 bg-foreground/75"
                      style={{ left: `calc(${limitPct}% - 1px)` }}
                    />
                  )}
                </div>
              </div>
            );
          })}
        </div>
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">
            {tx('定位误差对比（mm，越低越优）')}
          </p>
          {errorRows.map((row) => {
            const widthPct = (raw: number | null | undefined) =>
              raw != null && Number.isFinite(raw) && raw >= 0
                ? `${Math.max(0.8, Math.min(100, (raw / errMax) * 100))}%`
                : null;
            const wA = widthPct(row.va),
              wB = widthPct(row.vb),
              limitPct =
                row.limit != null ? Math.min(100, Math.max(0, (row.limit / errMax) * 100)) : null;
            return (
              <div key={row.label} className="space-y-1 text-xs">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-medium">{tx(row.label)}</span>
                  <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                    A {tx(mm(row.va))} · B {tx(mm(row.vb))}
                  </span>
                </div>
                <div
                  aria-hidden="true"
                  className="relative h-5 rounded-md bg-card ring-1 ring-inset ring-border/70"
                >
                  {wA && (
                    <span
                      className="absolute left-0 top-0.5 h-1.5 rounded-sm bg-primary"
                      style={{ width: wA }}
                    />
                  )}
                  {wB && (
                    <span
                      className="absolute bottom-0.5 left-0 h-1.5 rounded-sm bg-sky-600 dark:bg-sky-400"
                      style={{ width: wB }}
                    />
                  )}
                  {limitPct !== null && (
                    <span
                      className="absolute -inset-y-0.5 w-0.5 bg-foreground/75"
                      style={{ left: `calc(${limitPct}% - 1px)` }}
                    />
                  )}
                </div>
              </div>
            );
          })}
          <div className="flex justify-between pt-0.5 font-mono text-[10px] tabular-nums text-muted-foreground">
            <span>0 mm</span>
            <span>{(errMax / 2).toFixed(errMax % 2 === 0 ? 0 : 1)} mm</span>
            <span>{errMax} mm</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function DecisionPage({
  mode = 'compare',
}: {
  mode?: 'compare' | 'coordinates';
}) {
  const {
    tx,
    locale,
    ids,
    setIds,
    error,
    thresholds,
    setThresholds,
    setImported,
    importError,
    draftNotice,
    setImportError,
    job,
    computeError,
    testTarget,
    setTestTarget,
    radius,
    setRadius,
    seed,
    setSeed,
    noiseModelId,
    setNoiseModelId,
    scenarioId,
    setScenarioId,
    robustness,
    setRobustness,
    dataPrior,
    dataPriorSource,
    setDataPrior,
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
    connection,
    reconnect,
    runEvaluation,
    cancel,
    preview,
  } = useDecisionController(mode);
  // Used only for files without a region column, and for the unit of .sfp files, which declare none.
  const [regionCount, setRegionCount] = useState<RegionCount | 0>(0);
  const [montageUnit, setMontageUnit] = useState<MontageUnit>('mm');
  const importOptions = { regionCount: regionCount || undefined };
  const recordA = shown.find((r) => ids.indexOf(r.id) === 0),
    recordB = shown.find((r) => ids.indexOf(r.id) === 1);
  const pair = !!recordA && !!recordB;
  const presentation = result ? evaluationPresentation(job, result) : null;
  // Every coordinate evaluation is a library record (labelled with its conditions);
  // signal simulation takes only the default protocol.
  const savedEvaluation = !!result && action === 'evaluate';
  const simulationReady = savedEvaluation && noiseModelId === 'iid' && !scenarioId && !dataPrior;
  return (
    <main className="lab-page">
      <SiteHeader
        current={mode === 'coordinates' ? 'coordinates' : 'decision'}
        selection={{
          id:
            mode === 'coordinates'
              ? savedEvaluation
                ? (job?.key ?? null)
                : testTarget !== 'import'
                  ? (shown.find((r) => r.id === ids[testTarget === 'b' ? 1 : 0])?.id ?? null)
                  : null
              : (shown.find((r) => r.id === ids[0])?.id ?? null),
          phase:
            mode === 'coordinates' && testTarget === 'import' && !savedEvaluation
              ? 'draft'
              : 'saved',
          channels: mode === 'coordinates' && design ? 64 : undefined,
        }}
        arPercent={thresholds.field}
        returnHref={
          result && job?.annotation_id
            ? here + '&annotation_record=' + job.key + '&annotation_id=' + job.annotation_id
            : here
        }
      />
      <div className="lab-container space-y-5 pb-10">
        <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border pt-6 pb-4">
          <div>
            <h1 className="text-[1.45rem] font-semibold tracking-[-0.03em]">
              {tx(mode === 'coordinates' ? '坐标导入与评价' : '方案对比与设计报告')}
            </h1>
            <p className="mt-1 text-[0.8125rem] text-muted-foreground">
              {tx(
                mode === 'coordinates'
                  ? '导入已有64点坐标，评价后保存为独立布局；不运行区域布局搜索。'
                  : '选择两个64电极方案，核对约束与性能，再检查坐标偏移对重建的影响。',
              )}
            </p>
          </div>
          {mode === 'compare' && (
            <Button
              size="sm"
              disabled={!loaded || !shown.length}
              variant="outline"
              onClick={() =>
                download(
                  'EEG-design-comparison.md',
                  decisionMarkdown(shown, thresholds, result, locale),
                  'text/markdown;charset=utf-8',
                )
              }
            >
              <Download className="size-3.5" />
              {tx('导出对比报告')}
            </Button>
          )}
        </header>
        {tx(
          error && (
            <p role="alert" className="lab-panel border-danger/35 bg-danger-surface/65 text-danger">
              <RuntimeMessage message={error} />
            </p>
          ),
        )}
        {mode === 'compare' && (
          <>
            <section
              id="compare-pick"
              className="lab-panel grid scroll-mt-32 gap-4 lg:grid-cols-2"
              aria-label={tx('选择对比方案')}
            >
              {['方案A', '方案B'].map((label, i) => (
                <RecordPicker
                  key={label}
                  label={tx(label)}
                  records={choices}
                  value={ids[i]}
                  exclude={ids[1 - i]}
                  onChange={(id) => setIds((old) => old.map((v, k) => (k === i ? id : v)))}
                />
              ))}
            </section>
            <DecisionRequirements thresholds={thresholds} onChange={setThresholds} />
            {loaded && <ComparisonConclusion a={recordA} b={recordB} thresholds={thresholds} />}
            {loaded && shown.length > 0 && (
              <LayoutPairComparisonPanel
                shown={shown}
                ids={ids}
                locale={locale}
                testTarget={testTarget}
                onSelectTarget={(slot) => setTestTarget(slot)}
              />
            )}
            {tx(
              loaded && shown.length > 0 && (
                <section className="lab-panel relative">
                  <h2 className="text-lg font-semibold">{tx('原记录对照')}</h2>
                  <p className="mt-1.5 text-sm font-medium text-ink-soft">{tx(decisionCriteriaSummary(thresholds))}</p>
                  {tx(
                    notes.map((n) => (
                      <p className="mt-2 text-sm text-warning" key={n}>
                        {tx(n)}
                      </p>
                    )),
                  )}
                  {pair && recordA && recordB && (
                    <PairedMetricsVisual a={recordA} b={recordB} thresholds={thresholds} />
                  )}
                  <div className="lab-table-frame mt-4">
                    <table className="w-full min-w-[640px] text-left text-sm">
                      <thead>
                        <tr className="border-b border-border/75 bg-muted/55 text-xs font-semibold tracking-wide text-ink-soft">
                          <th className="px-4 py-3">{tx('项目')}</th>
                          {tx(
                            shown.map((r) => (
                              <th key={r.id} className="px-3 py-3">
                                {tx(ids.indexOf(r.id) === 0 ? '方案A' : '方案B')} ·{tx(' ')}
                                {tx(r.region_count)}
                                {tx('区')}
                              </th>
                            )),
                          )}
                          {pair && <th className="px-4 py-3 whitespace-nowrap">{tx('差值（B − A）')}</th>}
                        </tr>
                      </thead>
                      <tbody>
                        {tx(
                          (
                            [
                              ['实验类型', (r: SavedRecord) => protocolName(r.dataset_id)],
                              [
                                '面积上限',
                                (r: SavedRecord) =>
                                  r.area_cap_cm2 ? r.area_cap_cm2 + ' cm²' : '按每区半径约束',
                              ],
                              [
                                '实际区域面积',
                                (r: SavedRecord) =>
                                  r.geometry ? r.geometry.union_area_cm2.toFixed(2) + ' cm²' : '未提供',
                              ],
                              [
                                '实际最小直线点距',
                                (r: SavedRecord) => mm(r.geometry?.minimum_chord_distance_mm),
                              ],
                              ['信号重建保留率', (r: SavedRecord) => pct(r.metrics?.field_relative)],
                              [
                                '幅度保留率（最差10%）',
                                (r: SavedRecord) => pct(r.metrics?.sensitivity_tail),
                              ],
                              [
                                '相对定位评分',
                                (r: SavedRecord) => pct(r.metrics?.localization_relative),
                              ],
                              ['定位误差 · 中位数', (r: SavedRecord) => mm(r.metrics?.median_mm)],
                              ['定位误差 · P90', (r: SavedRecord) => mm(r.metrics?.p90_mm)],
                              [
                                '标准64重建解释率',
                                (r: SavedRecord) => pct(r.metrics?.reference_field_absolute),
                              ],
                              [
                                '标准64定位中位数',
                                (r: SavedRecord) => mm(r.metrics?.reference_median_mm),
                              ],
                            ] as const
                          ).map(([label, show]) => (
                            <tr key={label} className="border-b border-border/65 transition-colors hover:bg-primary/[0.03]">
                              <th className="px-4 py-2.5 font-normal text-muted-foreground">{tx(label)}</th>
                              {tx(
                                shown.map((r) => (
                                  <td className="px-3 py-2.5 font-mono tabular-nums" key={r.id}>
                                    {tx(show(r))}
                                  </td>
                                )),
                              )}
                              {pair && <DifferenceCell spec={DIFFERENCES[label]} a={recordA} b={recordB} />}
                            </tr>
                          )),
                        )}
                        <tr className="bg-muted/25">
                          <th className="px-4 py-3 font-medium">{tx('所选条件判定')}</th>
                          {tx(
                            shown.map((r) => {
                              const q = qualification(r, thresholds);
                              return (
                                <td key={r.id} className="px-3 py-3">
                                  <OutcomeBadge
                                    outcome={
                                      q.state === 'pass'
                                        ? 'pass'
                                        : q.state === 'missing'
                                          ? 'undefined'
                                          : 'fail'
                                    }
                                    className="whitespace-normal text-xs"
                                  >
                                    {tx(
                                      q.state === 'pass'
                                        ? '达到全部启用要求'
                                        : q.state === 'missing'
                                          ? '数据不完整'
                                          : '未达到：' + q.failed.join('、'),
                                    )}
                                  </OutcomeBadge>
                                </td>
                              );
                            }),
                          )}
                          {pair && <td className="px-4 py-3 text-muted-foreground">—</td>}
                        </tr>
                      </tbody>
                    </table>
                  </div>
                  <p className="mt-3 text-xs text-muted-foreground">
                    {tx('当前表格读取原实验评分；512独立源复评另有记录。点击方案的坐标导出可保留完整三维位置。')}
                  </p>
                  <div className="mt-4 flex flex-wrap gap-2.5">
                    {tx(
                      shown.map((r) => (
                        <Button
                          key={r.id}
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            download(
                              `eeg-${ids.indexOf(r.id) === 0 ? 'A' : 'B'}-coordinates.csv`,
                              designCSV(exportDesign(r)),
                              'text/csv;charset=utf-8',
                            )
                          }
                        >
                          {tx('导出方案')}
                          {tx(ids.indexOf(r.id) === 0 ? 'A' : 'B')}
                          {tx('坐标')}
                        </Button>
                      )),
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        download(
                          'eeg-comparison.json',
                          JSON.stringify(
                            {
                              thresholds,
                              notes,
                              records: shown,
                              new_evaluation: result,
                            },
                            null,
                            2,
                          ),
                          'application/json',
                        )
                      }
                    >
                      {tx('导出完整JSON')}
                    </Button>
                  </div>
                </section>
              ),
            )}
          </>
        )}
        <section className="lab-panel">
          <h2 className="text-lg font-semibold">
            {tx(mode === 'coordinates' ? '坐标文件与评价条件' : '位置偏移测试')}
          </h2>
          <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
            {tx(
              mode === 'coordinates'
                ? '导入Ernie原生毫米坐标系中的64点设计。已在前向库中的点直接使用原FEM结果；新位置执行新的FEM计算。其他头模的数字化坐标须先配准。'
                : '固定所选布局，检查网格位置偏移前后的重建表现；外部坐标在布局设计的坐标导入中评价。',
            )}
          </p>
          <div className="mt-4 grid items-start gap-5 lg:grid-cols-2">
            <div className="space-y-3.5">
              {mode === 'compare' && (
                <label className="lab-label">
                  {tx('测试对象')}
                  <select
                    className="lab-select mt-2"
                    value={testTarget}
                    onChange={(e) => setTestTarget(e.target.value)}
                  >
                    <option value="a">{tx('方案A')}</option>
                    <option value="b">{tx('方案B')}</option>
                  </select>
                </label>
              )}
              {mode === 'coordinates' ? (
                <>
                  {draftNotice && (
                    <output className="block rounded-xl border border-primary/25 bg-primary/[0.04] px-3.5 py-2.5 text-xs text-ink-soft">
                      {tx(draftNotice)}
                    </output>
                  )}
                  <div className="lab-subpanel space-y-3">
                    <label className="lab-label">
                      {tx('导入CSV或JSON')}
                      <FilePicker
                        accept=".csv,.json"
                        onChange={async (e) => {
                          const file = e.target.files?.[0];
                          if (!file) return;
                          try {
                            if (file.size > 65536) throw new Error('坐标文件上限64 KB');
                            const d = parseDesign(await file.text(), file.name);
                            setImported(d);
                            setImportError('');
                            setTestTarget('import');
                          } catch (err) {
                            setImported(null);
                            setImportError(err instanceof Error ? err.message : '导入失败');
                          }
                        }}
                      />
                    </label>
                    <label className="lab-label">
                      {tx('没有region列时的区域数')}
                      <select
                        className="lab-select mt-2"
                        value={regionCount}
                        onChange={(event) => setRegionCount(Number(event.target.value) as RegionCount | 0)}
                      >
                        <option value={0}>{tx('不自动分区（文件须含region列）')}</option>
                        {[1, 2, 3, 4, 6].map((count) => (
                          <option key={count} value={count}>
                            {tx(`按空间位置均衡分为${count}区`)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <p className="text-xs leading-5 text-muted-foreground">
                      {tx(
                        '数字化坐标和电极名称列表通常没有本软件的region列。选择区域数后，软件把64个电极按位置分成大小均衡的区域，并在坐标来源中记录分区方法。',
                      )}
                    </p>
                  </div>
                  <div className="lab-subpanel space-y-2.5">
                    <label className="lab-label">
                      {tx('导入BIDS坐标文件')}
                      <FilePicker
                        multiple
                        accept=".tsv,.json"
                        onChange={async (event) => {
                          const files = Array.from(event.target.files ?? []);
                          if (!files.length) return;
                          try {
                            if (files.length > 3 || files.some((file) => file.size > 65536))
                              throw new Error('请成对选择electrodes.tsv和coordsystem.json，每个文件不超过64 KB。');
                            const coordinateFiles = await Promise.all(
                              files.map(async (file) => ({ name: file.name, text: await file.text() })),
                            );
                            const parsed = parseBIDSElectrodes(
                              coordinateFiles,
                              bidsNeedsMniSurface(coordinateFiles) ? await loadErnieMniSurface() : undefined,
                              importOptions,
                            );
                            setImported(parsed);
                            setImportError('');
                            setTestTarget('import');
                          } catch (caught) {
                            setImported(null);
                            setImportError(caught instanceof Error ? caught.message : '导入失败');
                          }
                        }}
                      />
                    </label>
                    <p className="text-xs leading-5 text-muted-foreground">
                      {tx(
                        '同时选择electrodes.tsv和coordsystem.json；region列为本软件的零基区域扩展，可附electrodes.json说明。坐标须为Ernie原生空间或MNI模板空间，单位mm；MNI坐标经SimNIBS非线性变换映射到Ernie头皮。',
                      )}
                    </p>
                    <p className="text-xs leading-5 text-muted-foreground">
                      {tx(
                        '数字化的头坐标（如CapTrak）须在coordsystem.json中给出NAS、LPA、RPA基准点，单位可为mm、cm或m。软件先按基准点对齐，再拟合到Ernie头皮并投影；这是模板头上的放置，不是个体解剖配准。',
                      )}
                    </p>
                  </div>
                  <div className="lab-subpanel space-y-2.5">
                    <label className="lab-label">
                      {tx('导入MNE或EEGLAB电极文件（.elc、.sfp）')}
                      <FilePicker
                        accept=".elc,.sfp"
                        onChange={async (event) => {
                          const file = event.target.files?.[0];
                          if (!file) return;
                          try {
                            if (file.size > 65536) throw new Error('电极坐标文件不超过64 KB。');
                            setImported(
                              parseBrowserMontageFile(
                                { name: file.name, text: await file.text() },
                                await loadErnieMniSurface(),
                                { ...importOptions, sfpUnit: montageUnit },
                              ),
                            );
                            setImportError('');
                            setTestTarget('import');
                          } catch (caught) {
                            setImported(null);
                            setImportError(caught instanceof Error ? caught.message : '导入失败');
                          }
                        }}
                      />
                    </label>
                    <label className="lab-label">
                      {tx('.sfp坐标单位')}
                      <select
                        className="lab-select mt-2"
                        value={montageUnit}
                        onChange={(event) => setMontageUnit(event.target.value as MontageUnit)}
                      >
                        {(['mm', 'cm', 'm'] as const).map((unit) => (
                          <option key={unit} value={unit}>
                            {unit}
                          </option>
                        ))}
                      </select>
                    </label>
                    <p className="text-xs leading-5 text-muted-foreground">
                      {tx(
                        '文件须含64个电极和Nz/LPA/RPA（或FidNz/FidT9/FidT10）基准点；.elc自带单位，.sfp没有单位字段，请先选择单位。本软件导出的文件按原坐标读回。',
                      )}
                    </p>
                  </div>
                  <div className="lab-subpanel space-y-2.5">
                    <label className="lab-label">
                      {tx('按10-05电极名称导入')}
                      <FilePicker
                        accept=".tsv,.csv,.txt"
                        onChange={async (event) => {
                          const file = event.target.files?.[0];
                          if (!file) return;
                          try {
                            if (file.size > 65536)
                              throw new Error('请选择不超过64 KB的.tsv、.csv或.txt电极名称文件。');
                            setImported(
                              parseElectrodeLabels(
                                { name: file.name, text: await file.text() },
                                importOptions,
                              ),
                            );
                            setImportError('');
                            setTestTarget('import');
                          } catch (caught) {
                            setImported(null);
                            setImportError(caught instanceof Error ? caught.message : '导入失败');
                          }
                        }}
                      />
                    </label>
                    <p className="text-xs leading-5 text-muted-foreground">
                      {tx(
                        '表头为name和region两列，共64行。位置取SimNIBS 10-05电极帽在Ernie头皮上的模板坐标，与标准64导参考同一来源；T3、T4、T5、T6按T7、T8、P7、P8读取。',
                      )}
                    </p>
                  </div>
                  {tx(
                    importError && (
                      <p role="alert" className="rounded-lg border border-danger/30 bg-danger-surface/65 px-3 py-2 text-sm text-danger">
                        {tx(importError)}
                      </p>
                    ),
                  )}
                  {tx(
                    shown[0] && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          download(
                            'eeg-design-template.json',
                            JSON.stringify(exportDesign(shown[0]), null, 2),
                            'application/json',
                          )
                        }
                      >
                        {tx('下载带实际坐标的JSON模板')}
                      </Button>
                    ),
                  )}
                </>
              ) : (
                <a
                  className="lab-link-pill text-sm"
                  href={decisionHref([ids[0] ?? ''], thresholds).replace('/decision?', '/coordinates?')}
                >
                  {tx('导入外部电极坐标 →')}
                </a>
              )}
              {tx(
                design && (
                  <p className="rounded-xl border border-primary/25 bg-primary/[0.04] px-3.5 py-2 font-mono text-xs font-medium text-foreground tabular-nums">
                    {tx('已载入64点 · ')}
                    {tx(new Set(design.region_indices).size)}
                    {tx('区 · 最小直线点距 ')}
                    {tx(minimumDistance(design).toFixed(2))} mm
                  </p>
                ),
              )}
              <div className="lab-subpanel grid grid-cols-2 gap-3">
                {mode === 'compare' && (
                  <label className="lab-label">
                    {tx('网格偏移上限')}
                    <select
                      className="lab-select mt-2"
                      value={radius}
                      onChange={(e) => {
                        const value = Number(e.target.value);
                        if (isPerturbationRadius(value)) setRadius(value);
                      }}
                    >
                      {tx(
                        PERTURBATION_RADII.map((r) => (
                          <option key={r} value={r}>
                            {tx(r)} mm
                          </option>
                        )),
                      )}
                    </select>
                  </label>
                )}
                {/* One condition form for both buttons: the offset test ignores the scenario and robustness. */}
                <EvaluationConditions className="col-span-2" action="evaluate" disabled={computing}
                  values={{
                    noiseModelId,
                    scenarioId,
                    robustness,
                    ...(mode === 'coordinates' ? { dataPrior, dataPriorSource } : {}),
                  }}
                  hints={{
                    scenario:
                      '只用于“评价当前坐标”。数据由改变颅骨电导率的头模生成，重建与定位仍使用名义模型。',
                    robustness:
                      '只用于“评价当前坐标”；名义分数不变，另加约数秒计算。重新佩戴需要预计算头皮节点表。',
                    robustnessBlocked:
                      '稳健性只在名义电导率下评价；请先把数据生成头模电导率设为默认。',
                  }}
                  onChange={(patch) => {
                    if (patch.noiseModelId !== undefined) setNoiseModelId(patch.noiseModelId);
                    if (
                      patch.scenarioId !== undefined &&
                      (patch.scenarioId === '' || isConductivityScenario(patch.scenarioId))
                    )
                      setScenarioId(patch.scenarioId);
                    if (patch.robustness !== undefined) setRobustness(patch.robustness);
                    if ('dataPrior' in patch)
                      setDataPrior(patch.dataPrior ?? null, patch.dataPriorSource);
                  }}
                />
                <label className="lab-label">
                  {tx('随机种子')}
                  <input
                    type="number"
                    className="lab-select mt-2 font-mono tabular-nums"
                    min={0}
                    max={9999}
                    value={seed}
                    onChange={(e) => {
                      const n = Number(e.target.value);
                      if (Number.isInteger(n) && n >= 0 && n <= 9999) setSeed(n);
                    }}
                  />
                </label>
              </div>
              {mode === 'compare' && (
                <p className="text-xs leading-5 text-muted-foreground">
                  {tx(
                    '网格测试固定区域标签，对每区施加同方向目标偏移，再匹配邻近候选点。输出实际位移、目标匹配误差和未移动比例；这是离散网格敏感性检查。',
                  )}
                </p>
              )}
              <div className="flex flex-wrap gap-2">
                <Button disabled={!design || computing} onClick={() => runEvaluation('evaluate')}>
                  {tx('评价当前坐标')}
                </Button>
                {mode === 'compare' && (
                  <Button
                    variant="outline"
                    disabled={!design || computing}
                    onClick={() => runEvaluation('perturb')}
                  >
                    {tx('运行4次网格偏移')}
                  </Button>
                )}
                {tx(
                  computing && (
                    <Button variant="outline" onClick={cancel}>
                      {tx('停止')}
                    </Button>
                  ),
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                {tx('每次一项任务，坐标评价使用单线程；结果保存为独立缓存。新位置FEM计算最多运行10分钟。')}
              </p>
              {tx(
                computeError && (
                  <p role="alert" className="text-danger text-sm">
                    <RuntimeMessage message={computeError} />
                  </p>
                ),
              )}
              {connection === 'blocked' && job && (
                <Button type="button" size="sm" variant="outline" onClick={reconnect}>
                  {tx('重新查询任务')}
                </Button>
              )}
              {tx(
                job && (
                  <p aria-live="polite" className="text-sm font-medium text-primary">
                    <RuntimeMessage
                      message={job.message}
                      status={job.status}
                      queuePosition={job.queue_position}
                    />
                    {tx(computing && job.status !== 'queued' ? ` · ${Math.round(job.progress * 100)}%` : '')}
                    {tx(job.cached ? ' · 已读取缓存' : '')}
                    {tx(jobIdentity !== requestIdentity ? ' · 来自修改前的测试条件' : '')}
                  </p>
                ),
              )}
            </div>
            <div>
              {tx(
                result && (
                  <label className="mb-3 inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border/75 bg-muted/40 px-3 py-1.5 text-xs font-medium">
                    <input
                      type="checkbox"
                      className="accent-primary"
                      checked={showEvaluated}
                      onChange={(e) => setShowEvaluated(e.target.checked)}
                    />
                    {tx('显示实际评价坐标（取消后显示导入原坐标）')}
                  </label>
                ),
              )}
              {tx(
                preview && (
                  <Suspense fallback={<p className="lab-panel">{tx('加载三维布局…')}</p>}>
                    <Head
                      regionCount={new Set(preview.regionIndices).size}
                      allocation={Array.from(new Set(preview.regionIndices))
                        .sort((a, b) => a - b)
                        .map((r) => preview.regionIndices.filter((v) => v === r).length)}
                      domainMode="whole_surface"
                      radiusCm={3.5}
                      recordedLayout={preview}
                    />
                  </Suspense>
                ),
              )}
              {design && (
                <details className="group/names mt-3 rounded-xl border border-border/75 bg-muted/25 p-3.5">
                  <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium select-none [&::-webkit-details-marker]:hidden">
                    <span>{tx('查看电极名称与区域')}</span>
                    <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open/names:rotate-180" />
                  </summary>
                  <div className="lab-table-frame mt-3 max-h-64">
                    <table className="w-full text-left text-xs">
                      <thead>
                        <tr className="border-b border-border/75 bg-muted/55 font-semibold text-ink-soft">
                          <th className="px-3 py-2">{tx('电极')}</th>
                          <th className="px-2.5 py-2">{tx('区域')}</th>
                          <th className="px-2.5 py-2">X (mm)</th>
                          <th className="px-2.5 py-2">Y (mm)</th>
                          <th className="px-3 py-2">Z (mm)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {design.xyz_mm.map((point, index) => (
                          <tr key={index} className="border-b border-border/60 last:border-0">
                            <td className="px-3 py-1.5 font-medium">{design.electrode_names?.[index] ?? `E${index + 1}`}</td>
                            <td className="px-2.5 py-1.5 font-mono tabular-nums">{design.region_indices[index]}</td>
                            {point.map((value, axis) => (
                              <td className="px-2.5 py-1.5 font-mono tabular-nums" key={axis}>
                                {value}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              )}
              {design && <CoordinateReviewPanel design={design} result={result} />}
              {design && mode === 'coordinates' && <CoordinateStudyLink design={design} />}
              {mode === 'coordinates' && design && <CoordinateFileExports design={design} />}
              {mode === 'coordinates' && design && <LayoutFigureExport design={design} />}
            </div>
          </div>
          {tx(
            result && (
              <div className="mt-5 border-t border-border/75 pt-5 space-y-3">
                <div>
                  <h3 className="text-base font-semibold">{tx(presentation!.heading)}</h3>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {tx('原结果来源')} · {tx(presentation!.origin)}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {tx('噪声模型')} ·{' '}
                    {tx(
                      dataPrior
                        ? dataPriorLabel(dataPrior)
                        : noiseModelLabel(
                            NOISE_MODEL_PRESETS.find((preset) => preset.id === noiseModelId)?.value,
                          ),
                    )}
                    {action === 'evaluate' && scenarioId && (
                      <>
                        {' '}
                        · {tx('数据生成头模电导率')} · {tx(conductivityScenarioLabel(scenarioId))}
                      </>
                    )}
                  </p>
                </div>
                <p className="rounded-xl border border-border/75 bg-muted/30 px-3.5 py-2.5 text-sm font-mono tabular-nums">
                  {tx('重建保留率 ')}
                  {tx(pct(result.nominal?.field_relative))} {tx(' · 幅度保留率')}
                  {tx(' ')}
                  {tx(pct(result.nominal?.sensitivity_tail))} {tx(' · 相对定位评分')}
                  {tx(' ')}
                  {tx(pct(result.nominal?.localization_relative))}
                  {tx('。坐标最大调整距离')}
                  {tx(' ')}
                  {tx(mm(result.projection_max_mm))}。
                </p>
                {result.robustness && (
                  <RobustnessPanel block={result.robustness} names={design?.electrode_names} />
                )}
                {action === 'evaluate' && job?.key && (
                  <div className="flex flex-wrap items-center gap-2.5">
                    {savedEvaluation && (
                      <>
                        <SaveToProject
                          kind="layout"
                          recordId={job.key}
                          annotationId={job.annotation_id}
                        />
                        <a
                          className="lab-link-pill"
                          href={
                            layoutHref({ id: job.key }, thresholds.field) +
                            (job.annotation_id ? '&annotation_id=' + job.annotation_id : '')
                          }
                        >
                          {tx('打开布局详情')}
                        </a>
                      </>
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        design &&
                        download(
                          'eeg-evaluated-coordinates.csv',
                          designCSV({ ...design, xyz_mm: result.evaluated_xyz_mm }),
                          'text/csv;charset=utf-8',
                        )
                      }
                    >
                      {tx('导出实际评价坐标')}
                    </Button>
                  </div>
                )}
                {action === 'evaluate' && job?.key && !simulationReady && (
                  <p className="text-xs text-muted-foreground">
                    {tx('此评价已按其噪声模型或电导率情景标注保存到结果库；信号仿真只接受默认协议下的布局。')}
                  </p>
                )}
                {tx(
                  action === 'evaluate' && job?.key && simulationReady && (
                    <a
                      className="lab-link-pill text-sm"
                      href={
                        '/reception?record=' +
                        job.key +
                        (job.annotation_id ? '&annotation_id=' + job.annotation_id : '') +
                        '&ar=' +
                        thresholds.field +
                        '&returnTo=' +
                        encodeURIComponent(here)
                      }
                    >
                      {tx('用实际评价坐标进行源—接收仿真 →')}
                    </a>
                  ),
                )}
                <div className="lab-table-frame">
                  <table className="w-full min-w-[420px] text-left text-sm">
                    <thead>
                      <tr className="border-b border-border/75 bg-muted/55 text-xs font-semibold tracking-wide text-ink-soft">
                        <th className="px-4 py-2.5">{tx('绝对指标')}</th>
                        <th className="px-3 py-2.5">{tx('当前坐标')}</th>
                        <th className="px-4 py-2.5">{tx('标准全头64')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-b border-border/65">
                        <th className="px-4 py-2.5 font-normal">{tx('重建解释率')}</th>
                        <td className="px-3 font-mono tabular-nums">{tx(pct(result.nominal.field_absolute))}</td>
                        <td className="px-4 font-mono tabular-nums">{tx(pct(result.nominal.reference_field_absolute))}</td>
                      </tr>
                      <tr className="border-b border-border/65">
                        <th className="px-4 py-2.5 font-normal">{tx('定位误差中位数')}</th>
                        <td className="px-3 font-mono tabular-nums">{tx(mm(result.nominal.median_mm))}</td>
                        <td className="px-4 font-mono tabular-nums">{tx(mm(result.nominal.reference_median_mm))}</td>
                      </tr>
                      <tr>
                        <th className="px-4 py-2.5 font-normal">{tx('定位误差P90')}</th>
                        <td className="px-3 font-mono tabular-nums">{tx(mm(result.nominal.p90_mm))}</td>
                        <td className="px-4 font-mono tabular-nums">{tx(mm(result.nominal.reference_p90_mm))}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p className="text-sm">
                  <span className="mb-1.5 block text-xs text-muted-foreground">{tx(decisionCriteriaSummary(thresholds))}</span>
                  <span className="font-medium">
                    {tx('本次坐标评价：')}
                    {tx(
                      resultQualification?.state === 'pass'
                        ? '达到全部启用要求'
                        : resultQualification?.state === 'missing'
                          ? '所选判据数据不完整'
                          : '未达到：' + resultQualification?.failed.join('、'),
                    )}
                    。
                  </span>
                </p>
                {tx(
                  result.trials?.length > 0 && (
                    <>
                      <div className="lab-table-frame">
                        <table className="w-full min-w-[700px] text-left text-sm">
                          <thead>
                            <tr className="border-b border-border/75 bg-muted/55 text-xs font-semibold tracking-wide text-ink-soft">
                              <th className="px-3.5 py-2.5">{tx('偏移试验')}</th>
                              <th className="px-3 py-2.5">{tx('实际位移（平均 / 最大）')}</th>
                              <th className="px-3 py-2.5">{tx('目标匹配误差（最大）')}</th>
                              <th className="px-3 py-2.5">{tx('未移动比例')}</th>
                              <th className="px-3 py-2.5">{tx('重标定后重建')}</th>
                              <th className="px-3 py-2.5">{tx('沿用原重建器')}</th>
                              <th className="px-3.5 py-2.5">{tx('几何状态')}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {tx(
                              result.trials.map((t) => (
                                <tr key={t.index} className="border-b border-border/65 last:border-0">
                                  <td className="px-3.5 py-2.5 font-mono tabular-nums">{tx(t.index + 1)}</td>
                                  <td className="px-3 py-2.5 font-mono tabular-nums">
                                    {tx(mm(t.actual_mean_mm))} / {tx(mm(t.actual_max_mm))}
                                  </td>
                                  <td className="px-3 py-2.5 font-mono tabular-nums">{tx(mm(t.target_error_max_mm))}</td>
                                  <td className="px-3 py-2.5 font-mono tabular-nums">{tx(pct(t.unchanged_fraction))}</td>
                                  <td className="px-3 py-2.5 font-mono tabular-nums">{tx(pct(t.field_relative))}</td>
                                  <td className="px-3 py-2.5 font-mono tabular-nums">{tx(pct(t.fixed_estimator_field_relative))}</td>
                                  <td className="px-3.5 py-2.5 text-xs">
                                    {tx(t.status === 'completed' ? '64点互异，点距通过' : t.message)}
                                  </td>
                                </tr>
                              )),
                            )}
                          </tbody>
                        </table>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {tx(
                          '参照64布局固定；偏移后重新标定与沿用原重建器分别计算。保留原区域标签，未重新验证贴片边界和区域分离。4次试验为检查样本，不表示人群分布。',
                        )}
                      </p>
                    </>
                  ),
                )}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    download(
                      'eeg-position-evaluation.json',
                      JSON.stringify(result, null, 2),
                      'application/json',
                    )
                  }
                >
                  {tx('导出本次评价与偏移坐标')}
                </Button>
              </div>
            ),
          )}
        </section>
        {/* Import comes first; the requirements only re-judge the result above. */}
        {mode === 'coordinates' && (
          <DecisionRequirements thresholds={thresholds} onChange={setThresholds} />
        )}
        <section className="lab-panel">
          <h2 className="text-lg font-semibold">{tx('验证阶段')}</h2>
          <p className="mt-2 text-sm leading-7 text-ink-soft">
            {tx(
              '已完成：单头模布局实验、独立源复评与多种噪声控制。进行中：数值和搜索稳定性核查。待独立数据：新头模上的冻结布局迁移、实测噪声校准和同步采集对照。',
            )}
          </p>
          <a
            className="mt-3 lab-link-pill"
            href={'/method?ar=' + thresholds.field + '&returnTo=' + encodeURIComponent(here)}
          >
            {tx('查看指标定义与建模方法')}
          </a>
        </section>
      </div>
    </main>
  );
}
