'use client';
import { useEffect, useMemo, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { Button } from '@/components/ui/button';
import { apiJson } from '@/client/task-client';
import { ERNIE_MNI_MAPPING, type Point } from '@/lib/ernie-mni';
import { ERNIE_CRANIAL_FRAME } from '@/lib/head-personalization';
import {
  analyzeHardwareSizing,
  exportHardwareCadCsv,
  exportHardwareCadJson,
  podMountLabel,
  type PodMountType,
  type ShellSizingMode,
} from '@/lib/hardware-sizing';
import { localizedRecordTitle } from '@/lib/i18n/records';
import type { ElectrodeDesign } from '@/lib/design-decision';
import type { LocalLibrary, SavedRecord, SavedSummary } from '@/lib/local-library';
import { cn } from '@/lib/utils';

function downloadDataUrl(filename: string, content: string, mime: string) {
  const anchor = document.createElement('a');
  anchor.href = `data:${mime};charset=utf-8,${encodeURIComponent(content)}`;
  anchor.download = filename;
  anchor.click();
}

const MOUNT_BADGE: Record<PodMountType, string> = {
  rigid_pod: 'bg-success-surface text-success ring-1 ring-inset ring-success/25',
  spring_plunger: 'bg-primary/10 text-primary ring-1 ring-inset ring-primary/25',
  slotted_rail: 'bg-warning-surface text-warning ring-1 ring-inset ring-warning/25',
};

export function HardwareSizingPanel({
  draftDesign,
}: {
  draftDesign?: ElectrodeDesign | null;
}) {
  const { tx, locale } = useLanguage();
  const [sizingMode, setSizingMode] = useState<ShellSizingMode>('three_size_sml');
  const [library, setLibrary] = useState<SavedSummary[]>([]);
  const [libraryState, setLibraryState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [selectedId, setSelectedId] = useState<string>('');
  const [loadedRecord, setLoadedRecord] = useState<SavedRecord | null>(null);
  const [failedId, setFailedId] = useState<string | null>(null);
  // Until the user picks one, the draft (when there is one) or the newest saved layout is shown.
  const activeId = selectedId || (draftDesign ? '__draft__' : library[0]?.id ?? '');
  const recordId = activeId && activeId !== '__draft__' ? activeId : null;

  useEffect(() => {
    const ctrl = new AbortController();
    apiJson<LocalLibrary>('/api/local-compute/library', { signal: ctrl.signal })
      .then((res) => {
        setLibrary(res.records.filter((r) => r.status === 'completed'));
        setLibraryState('ready');
      })
      .catch(() => {
        if (!ctrl.signal.aborted) setLibraryState('error');
      });
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    if (!recordId) return;
    const ctrl = new AbortController();
    apiJson<{ record: SavedRecord }>('/api/local-compute/library/' + recordId, {
      signal: ctrl.signal,
    })
      .then((res) => setLoadedRecord(res.record))
      .catch(() => {
        if (!ctrl.signal.aborted) setFailedId(recordId);
      });
    return () => ctrl.abort();
  }, [recordId]);

  const draftLayout = useMemo(
    () =>
      draftDesign
        ? {
            name: draftDesign.name || '研究草稿布局',
            xyzMm: draftDesign.xyz_mm as Point[],
            regionIndices: draftDesign.region_indices,
            electrodeNames: draftDesign.electrode_names,
          }
        : null,
    [draftDesign],
  );

  // Null while the catalog or the chosen record is loading, or when the record has no coordinates.
  const targetLayout = useMemo(() => {
    if (!recordId) {
      if (draftLayout) return draftLayout;
      if (libraryState === 'loading') return null;
      // No saved layout and no draft: the labelled reference example.
      const wearable12 = [
        'AF7', 'Fp1', 'Fpz', 'Fp2', 'AF8', 'Fz',
        'FT7', 'T7', 'TP7', 'FT8', 'T8', 'TP8',
      ];
      const capMap = new Map(
        ERNIE_MNI_MAPPING.labels.positions_mm.map((r) => [
          String(r[0]),
          [Number(r[1]), Number(r[2]), Number(r[3])] as Point,
        ]),
      );
      const pts = wearable12.map((n) => capMap.get(n)!).filter(Boolean);
      return {
        name: '12导前额+双耳周头戴参考示例',
        xyzMm: pts,
        regionIndices: pts.map((_, i) => (i < 6 ? 0 : i < 9 ? 1 : 2)),
        electrodeNames: wearable12,
      };
    }
    if (loadedRecord?.id !== recordId || !loadedRecord.layout?.xyzMm?.length) return null;
    return {
      name: localizedRecordTitle(loadedRecord, locale),
      xyzMm: loadedRecord.layout.xyzMm as Point[],
      regionIndices:
        loadedRecord.layout.regionIndices ?? loadedRecord.layout.xyzMm.map(() => 0),
      electrodeNames: undefined,
    };
  }, [recordId, draftLayout, libraryState, loadedRecord, locale]);
  const unavailable =
    !targetLayout &&
    (recordId ? failedId === recordId || loadedRecord?.id === recordId : libraryState === 'error');

  const report = useMemo(
    () =>
      targetLayout &&
      analyzeHardwareSizing(targetLayout.xyzMm, targetLayout.regionIndices, {
        designName: targetLayout.name,
        sizingMode,
        electrodeNames: targetLayout.electrodeNames,
      }),
    [targetLayout, sizingMode],
  );

  return (
    <section
      className="lab-panel space-y-4"
      aria-labelledby="hardware-sizing-heading"
      data-hardware-sizing-panel
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-4">
        <div className="max-w-3xl">
          <p className="lab-eyebrow">{tx('头戴式硬件工业设计参考 · S/M/L 分尺码与弹性公差')}</p>
          <h2 id="hardware-sizing-heading" className="mt-1 text-lg font-semibold">
            {tx('跨头型分尺码电极坐标与机械结构公差分析')}
          </h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            {tx(
              '面向头戴式脑电设备厂商：将选定的最佳布局（8–64导均可）投射至成人 S（P10）/ M（P50）/ L（P90）头围分档及长头型/圆阔头型极值，计算各电极位的三维壳体坐标、弹簧顶针法向行程与切向漂移包络，直接辅助刚性壳体、弹性悬臂或滑槽结构选型。',
            )}
          </p>
        </div>
        <fieldset
          className="inline-flex rounded-lg border border-border bg-secondary/65 p-0.5 text-xs"
          aria-label={tx('头戴壳体分码策略')}
        >
          {(
            [
              ['three_size_sml', 'S / M / L 三尺码分档壳体'],
              ['one_size_universal', '单均码通用可调壳体'],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-pressed={sizingMode === id}
              onClick={() => setSizingMode(id)}
              className={cn(
                'rounded-md px-3 py-1.5 font-medium transition-colors',
                sizingMode === id
                  ? 'bg-card text-foreground shadow-2xs'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {tx(label)}
            </button>
          ))}
        </fieldset>
      </div>

      <div className="grid items-start gap-5 lg:grid-cols-[1.12fr_0.88fr]">
        <div className="space-y-4">
          <label className="lab-label">
            {tx('选择用于硬件结构评估的布局方案（8–64导）')}
            <select
              className="lab-select mt-1.5"
              value={activeId}
              onChange={(e) => setSelectedId(e.target.value)}
            >
              {draftDesign && (
                <option value="__draft__">
                  {tx('当前研究草稿布局')} · {draftDesign.name} ({draftDesign.xyz_mm.length}{' '}
                  {tx('电极')})
                </option>
              )}
              {library.slice(0, 30).map((rec) => (
                <option key={rec.id} value={rec.id}>
                  {localizedRecordTitle(rec, locale)}
                </option>
              ))}
              {!draftDesign && library.length === 0 && (
                <option value="">
                  {tx(libraryState === 'loading' ? '读取方案目录…' : '12导前额+双耳周头戴参考示例')}
                </option>
              )}
            </select>
          </label>

          {report ? (
            <>
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <div className="rounded-xl border border-border/80 bg-card p-3">
              <span className="block text-[11px] text-muted-foreground">
                {tx('最大法向弹簧行程')}
              </span>
              <span className="mt-1 block font-mono text-base font-semibold text-primary tabular-nums">
                {report.summary.maxRadialStrokeMm.toFixed(2)} mm
              </span>
            </div>
            <div className="rounded-xl border border-border/80 bg-card p-3">
              <span className="block text-[11px] text-muted-foreground">
                {tx('最大切向弧面漂移')}
              </span>
              <span className="mt-1 block font-mono text-base font-semibold tabular-nums">
                {report.summary.maxTangentialDriftMm.toFixed(2)} mm
              </span>
            </div>
            <div className="rounded-xl border border-border/80 bg-card p-3">
              <span className="block text-[11px] text-muted-foreground">
                {tx('长/圆头型极值偏移')}
              </span>
              <span className="mt-1 block font-mono text-base font-semibold tabular-nums">
                {report.summary.maxCephalicDriftMm.toFixed(2)} mm
              </span>
            </div>
            <div className="rounded-xl border border-border/80 bg-card p-3">
              <span className="block text-[11px] text-muted-foreground">
                {tx('全尺码最小电极间距')}
              </span>
              <span className="mt-1 block font-mono text-base font-semibold text-success tabular-nums">
                {report.summary.worstMinSpacingMm.toFixed(2)} mm
              </span>
            </div>
          </div>

          <div className="rounded-xl border border-border/75 bg-muted/25 p-3.5">
            <h3 className="text-xs font-semibold text-foreground">
              {tx('各电极位机械结构选型建议汇总')}
            </h3>
            <div className="mt-2.5 grid gap-2 sm:grid-cols-3">
              {(['rigid_pod', 'spring_plunger', 'slotted_rail'] as const).map((kind) => (
                <div
                  key={kind}
                  className="flex items-center justify-between rounded-lg border border-border/80 bg-card px-3 py-2 text-xs"
                >
                  <span className="text-ink-soft">{tx(podMountLabel(kind))}</span>
                  <span className="font-mono text-sm font-semibold tabular-nums">
                    {report.summary.mountCounts[kind]}
                  </span>
                </div>
              ))}
            </div>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              {tx(
                sizingMode === 'three_size_sml'
                  ? '采用 S/M/L 三尺码分档壳体后，大跨度头围差异由尺码承接，单个尺码壳体主要只需吸收长圆头型差异，显著降低弹簧顶针所需行程。'
                  : '单均码壳体需同时覆盖 54.0–60.5 cm 头围与长圆头型差异，外周颞区与额极电极通常需要更大行程的弹性悬臂或分档滑槽。',
              )}
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              onClick={() =>
                downloadDataUrl(
                  `eeg-hardware-cad-${sizingMode}.csv`,
                  exportHardwareCadCsv(report),
                  'text/csv',
                )
              }
            >
              {tx('导出硬件 CAD 坐标与法向表 CSV')}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() =>
                downloadDataUrl(
                  `eeg-hardware-sizing-${sizingMode}.json`,
                  exportHardwareCadJson(report),
                  'application/json',
                )
              }
            >
              {tx('导出分尺码公差工程规范 JSON')}
            </Button>
          </div>
            </>
          ) : (
            <output className="block rounded-xl border border-border/80 bg-card p-3 text-sm text-muted-foreground">
              {tx(unavailable ? '指定记录无法读取，请刷新记录或重新选择。' : '读取方案目录…')}
            </output>
          )}
        </div>

        {report && (
        <div className="rounded-xl border border-border/80 bg-card p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">
              {tx('S / M / L 传感器散布包络与顶针法向俯视图')}
            </h3>
            <span className="font-mono text-xs text-muted-foreground tabular-nums">
              {report.electrodeCount} {tx('通道')} · {report.regionCount} {tx('区')}
            </span>
          </div>
          <svg
            viewBox="-130 -140 260 275"
            className="mx-auto mt-3 block max-h-[320px] w-full"
            aria-label={tx('S、M、L多尺码传感器坐标散布与法向矢量俯视图')}
          >
            <title>{tx('S、M、L多尺码传感器坐标散布与法向矢量俯视图')}</title>
            {/* S / M / L concentric cranial contours */}
            {[
              { rx: 74.2, ry: 94.5, stroke: '#94a3b8', dash: '3 3' },
              { rx: 78.3, ry: 100.6, stroke: '#2563eb', dash: undefined },
              { rx: 82.6, ry: 107.0, stroke: '#0d9488', dash: '4 2' },
            ].map((c, idx) => (
              <ellipse
                key={idx}
                cx="0"
                cy="0"
                rx={c.rx}
                ry={c.ry}
                fill="none"
                stroke={c.stroke}
                strokeOpacity={idx === 1 ? '0.65' : '0.4'}
                strokeWidth={idx === 1 ? '1.5' : '1.1'}
                strokeDasharray={c.dash}
              />
            ))}
            {report.electrodes.map((e) => {
              const ox = ERNIE_CRANIAL_FRAME.origin[0];
              const oy = ERNIE_CRANIAL_FRAME.origin[1];
              const sx = e.coordsBySizeMm.S[0] - ox;
              const sy = -(e.coordsBySizeMm.S[1] - oy);
              const mx = e.coordsBySizeMm.M[0] - ox;
              const my = -(e.coordsBySizeMm.M[1] - oy);
              const lx = e.coordsBySizeMm.L[0] - ox;
              const ly = -(e.coordsBySizeMm.L[1] - oy);
              const nx = e.normal[0] * 10;
              const ny = -e.normal[1] * 10;
              return (
                <g key={e.index}>
                  {/* S-to-L travel line */}
                  <line x1={sx} y1={sy} x2={lx} y2={ly} stroke="#f59e0b" strokeWidth="2" strokeLinecap="round" />
                  {/* Outward normal plunger axis */}
                  <line x1={mx} y1={my} x2={mx + nx} y2={my + ny} stroke="#2563eb" strokeOpacity="0.45" strokeWidth="1" />
                  <circle cx={mx} cy={my} r="3" fill="#2563eb" stroke="#ffffff" strokeWidth="0.9">
                    <title>
                      {`${e.name}: M(${e.coordsBySizeMm.M[0].toFixed(1)}, ${e.coordsBySizeMm.M[1].toFixed(1)}, ${e.coordsBySizeMm.M[2].toFixed(1)}) mm · ${tx('行程')} ${e.radialStrokeMm.toFixed(2)} mm · ${tx('漂移')} ${e.tangentialDriftMm.toFixed(2)} mm`}
                    </title>
                  </circle>
                </g>
              );
            })}
          </svg>
          <div className="mt-2 flex flex-wrap items-center justify-center gap-3 text-[11px] text-muted-foreground">
            <span>{tx('内虚线：S 小码')}</span>
            <span className="font-medium text-primary">{tx('实线蓝点：M 中码基准与法向轴')}</span>
            <span>{tx('外虚线：L 大码')}</span>
            <span className="text-amber-600 dark:text-amber-400">{tx('橙色线段：S–L 尺码跨度')}</span>
          </div>
        </div>
        )}
      </div>

      {report && (
      <details className="group/bom rounded-xl border border-border/75 bg-muted/20 p-3.5">
        <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-semibold select-none [&::-webkit-details-marker]:hidden">
          <span>{tx('展开逐通道 S / M / L 坐标、法向矢量与结构选型明细表')}</span>
          <ChevronDown
            aria-hidden
            className="size-4 text-muted-foreground transition-transform group-open/bom:rotate-180"
          />
        </summary>
        <div className="lab-table-frame mt-3 max-h-72">
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead>
              <tr className="border-b border-border/75 bg-muted/55 font-semibold text-ink-soft">
                <th className="px-3 py-2">{tx('通道')}</th>
                <th className="px-2.5 py-2">{tx('区域')}</th>
                <th className="px-2.5 py-2">{tx('M 中码坐标 (mm)')}</th>
                <th className="px-2.5 py-2">{tx('外法向轴 (nx, ny, nz)')}</th>
                <th className="px-2.5 py-2">{tx('法向行程')}</th>
                <th className="px-2.5 py-2">{tx('切向漂移')}</th>
                <th className="px-3 py-2">{tx('推荐硬件安装结构')}</th>
              </tr>
            </thead>
            <tbody>
              {report.electrodes.map((e) => (
                <tr key={e.index} className="border-b border-border/60 last:border-0">
                  <td className="px-3 py-1.5 font-medium">{e.name}</td>
                  <td className="px-2.5 py-1.5 font-mono tabular-nums">{e.region}</td>
                  <td className="px-2.5 py-1.5 font-mono tabular-nums">
                    {e.coordsBySizeMm.M.map((v) => v.toFixed(1)).join(', ')}
                  </td>
                  <td className="px-2.5 py-1.5 font-mono tabular-nums">
                    {e.normal.map((v) => v.toFixed(2)).join(', ')}
                  </td>
                  <td className="px-2.5 py-1.5 font-mono tabular-nums">
                    {e.radialStrokeMm.toFixed(2)} mm
                  </td>
                  <td className="px-2.5 py-1.5 font-mono tabular-nums">
                    {e.tangentialDriftMm.toFixed(2)} mm
                  </td>
                  <td className="px-3 py-1.5">
                    <span
                      className={cn(
                        'inline-flex rounded-md px-2 py-0.5 text-[11px] font-medium',
                        MOUNT_BADGE[e.mountType],
                      )}
                    >
                      {tx(podMountLabel(e.mountType))}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      )}
    </section>
  );
}
