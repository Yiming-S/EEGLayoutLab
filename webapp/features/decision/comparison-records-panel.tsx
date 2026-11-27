'use client';

import { Button } from '@/components/ui/button';
import { useLanguage } from '@/components/language-provider';
import { OutcomeBadge } from '@/components/retention-bar';
import type { SavedRecord } from '@/lib/local-library';
import { protocolName } from '@/lib/ui-language';
import {
  decisionCriteriaSummary,
  decisionThresholdMode,
  designCSV,
  exportRecordCoordinates,
  mm,
  pct,
  qualification,
  recordElectrodeCount,
  type DecisionThresholds,
  type DesignResult,
} from '@/lib/design-decision';
import { cn } from '@/lib/utils';
import { downloadTextFile } from './decision-download';

function regionalSplitLabel(record: SavedRecord) {
  const total = recordElectrodeCount(record);
  if (!record.layout?.regionIndices?.length) return String(total);
  const split = Array.from({ length: record.region_count }, (_, r) =>
    record.layout!.regionIndices.filter((v) => v === r).length,
  ).join(' + ');
  return record.region_count > 1 ? `${total} (${split})` : String(total);
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

function DifferenceCell({
  spec,
  a,
  b,
}: {
  spec?: Difference;
  a?: SavedRecord;
  b?: SavedRecord;
}) {
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
    zero || !spec.better
      ? ''
      : (spec.better === 'higher') === d > 0
        ? 'text-success'
        : 'text-warning';
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
        {tone && (
          <span className="sr-only">
            {tx(tone === 'text-success' ? '（B更好）' : '（B更差）')}
          </span>
        )}
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

function DeltaPill({
  va,
  vb,
  unit,
  better,
}: {
  va: number | null | undefined;
  vb: number | null | undefined;
  unit: 'pp' | 'mm';
  better: 'higher' | 'lower';
}) {
  if (va == null || vb == null || !Number.isFinite(va) || !Number.isFinite(vb))
    return null;
  const raw = vb - va;
  const scaled = unit === 'pp' ? raw * 100 : raw;
  const digits = unit === 'mm' ? 1 : 2;
  const zero = Math.abs(scaled) < 0.5 * 10 ** -digits;
  const sign = zero ? '±' : raw > 0 ? '+' : '−';
  const improved = !zero && ((better === 'higher') === (raw > 0));
  const tone = zero
    ? 'border-border bg-secondary/50 text-muted-foreground'
    : improved
      ? 'border-success/35 bg-success-surface/85 text-success'
      : 'border-warning/35 bg-warning-surface/85 text-warning';
  return (
    <span
      className={cn(
        'inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold tabular-nums',
        tone,
      )}
    >
      Δ {sign}
      {Math.abs(scaled).toFixed(digits)} {unit}
    </span>
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
  const retMin =
      retentionVals.length && Math.min(...retentionVals) < 0
        ? Math.floor(Math.min(...retentionVals) / 10) * 10
        : 0,
    retMax =
      retentionVals.length && Math.max(...retentionVals) > 100
        ? Math.ceil(Math.max(...retentionVals) / 10) * 10
        : 100,
    retSpan = Math.max(1e-9, retMax - retMin);
  const baseline100Pct = ((100 - retMin) / retSpan) * 100;

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
    <div
      className="mt-4 rounded-xl border border-border/75 bg-muted/25 p-4 space-y-3"
      data-paired-metrics-visual
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-semibold text-foreground">{tx('核心指标直观对照')}</span>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-2.5 w-4 rounded-sm bg-primary" />
            <span>{tx('方案A')}</span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="inline-block h-2.5 w-4 rounded-sm bg-sky-600 dark:bg-sky-400"
            />
            <span>{tx('方案B')}</span>
          </span>
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            <span aria-hidden="true" className="inline-block h-3 w-0.5 bg-foreground/75" />
            <span>{tx('启用阈值')}</span>
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
                row.limit != null
                  ? ((Math.min(retMax, Math.max(retMin, row.limit)) - retMin) / retSpan) * 100
                  : null;
            return (
              <div key={row.label} className="space-y-1 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium">{tx(row.label)}</span>
                  <span className="inline-flex items-center gap-1.5 font-mono text-[11px] tabular-nums text-muted-foreground">
                    <span>
                      A {tx(pct(row.va))} · B {tx(pct(row.vb))}
                    </span>
                    <DeltaPill va={row.va} vb={row.vb} unit="pp" better="higher" />
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
                  {retMax > 100 && (
                    <span
                      className="absolute inset-y-0 border-l border-dashed border-muted-foreground/60"
                      style={{ left: `${baseline100Pct}%` }}
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
          <div className="flex justify-between pt-0.5 font-mono text-[10px] tabular-nums text-muted-foreground">
            <span>{retMin}%</span>
            <span>{Math.round((retMin + retMax) / 2)}%</span>
            <span>{retMax === 100 ? `100% (${tx('标准64导')})` : `${retMax}%`}</span>
          </div>
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
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium">{tx(row.label)}</span>
                  <span className="inline-flex items-center gap-1.5 font-mono text-[11px] tabular-nums text-muted-foreground">
                    <span>
                      A {tx(mm(row.va))} · B {tx(mm(row.vb))}
                    </span>
                    <DeltaPill va={row.va} vb={row.vb} unit="mm" better="lower" />
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

export function ComparisonRecordsPanel({
  shown,
  ids,
  thresholds,
  notes,
  result,
  recordA,
  recordB,
}: {
  shown: SavedRecord[];
  ids: string[];
  thresholds: DecisionThresholds;
  notes: string[];
  result: DesignResult | null;
  recordA?: SavedRecord;
  recordB?: SavedRecord;
}) {
  const { tx } = useLanguage();
  const pair = !!recordA && !!recordB;

  return (
    <section className="lab-panel relative">
      <h2 className="text-lg font-semibold">{tx('原记录对照')}</h2>
      <p className="mt-1.5 text-sm font-medium text-ink-soft">
        {tx(decisionCriteriaSummary(thresholds))}
      </p>
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
                    {recordElectrodeCount(r)} {tx('电极')} ·{tx(' ')}
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
                  ['电极数 / 各区分配', (r: SavedRecord) => regionalSplitLabel(r)],
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
                <tr
                  key={label}
                  className="border-b border-border/65 transition-colors hover:bg-primary/[0.03]"
                >
                  <th className="px-4 py-2.5 font-normal text-muted-foreground">{tx(label)}</th>
                  {tx(
                    shown.map((r) => (
                      <td className="px-3 py-2.5 font-mono tabular-nums" key={r.id}>
                        {tx(show(r))}
                      </td>
                    )),
                  )}
                  {pair && (
                    <DifferenceCell spec={DIFFERENCES[label]} a={recordA} b={recordB} />
                  )}
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
          shown.map((r) => {
            const coords = exportRecordCoordinates(r);
            return (
              <Button
                key={r.id}
                size="sm"
                variant="outline"
                disabled={!coords}
                onClick={() =>
                  coords &&
                  downloadTextFile(
                    `eeg-${ids.indexOf(r.id) === 0 ? 'A' : 'B'}-coordinates.csv`,
                    designCSV(coords),
                    'text/csv;charset=utf-8',
                  )
                }
              >
                {tx('导出方案')}
                {tx(ids.indexOf(r.id) === 0 ? 'A' : 'B')}
                {tx('坐标')}
              </Button>
            );
          }),
        )}
        <Button
          size="sm"
          variant="outline"
          onClick={() =>
            downloadTextFile(
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
  );
}
