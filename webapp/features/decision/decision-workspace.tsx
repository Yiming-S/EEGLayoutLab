'use client';

import { CONDUCTIVITY_SCENARIOS, NOISE_MODEL_PRESETS, conductivityScenarioLabel, noiseModelLabel } from '../../contracts/scientific-options.mjs';
import { RuntimeMessage } from '@/components/runtime-message';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { lazy, Suspense } from 'react';
import { Download } from 'lucide-react';
import { SiteHeader } from '@/components/site-header';
import { Button } from '@/components/ui/button';
import type { SavedRecord } from '@/lib/local-library';
import { protocolName } from '@/lib/ui-language';
import {
  decisionMarkdown,
  decisionCriteriaSummary,
  decisionHref,
  designCSV,
  exportDesign,
  minimumDistance,
  mm,
  parseDesign,
  pct,
  qualification,
} from '@/lib/design-decision';
import { useDecisionController } from './use-decision-controller';
import { RecordPicker } from './record-picker';
import { SaveToProject } from '@/features/projects/project-context';
import { DecisionRequirements } from './decision-requirements';
import { CoordinateReviewPanel } from './coordinate-review-panel';
import { bidsNeedsMniSurface, parseBIDSElectrodes, parseElectrodeLabels } from '@/lib/bids-electrodes';
import { loadErnieMniSurface } from '@/lib/ernie-mni';
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

type Difference = { get: (r: SavedRecord) => number | null | undefined; unit: 'pp' | 'mm' | 'cm²'; better?: 'higher' | 'lower' };
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
function DifferenceCell({ spec, a, b }: { spec?: Difference; a?: SavedRecord; b?: SavedRecord }) {
  const { tx } = useLanguage();
  const x = a && spec?.get(a), y = b && spec?.get(b);
  if (!spec || x == null || y == null || !Number.isFinite(x) || !Number.isFinite(y)) return <td className="text-muted-foreground">—</td>;
  const d = y - x, scaled = spec.unit === 'pp' ? d * 100 : d, digits = spec.unit === 'mm' ? 1 : 2;
  const zero = Math.abs(scaled) < 0.5 * 10 ** -digits;
  const text = (zero ? '±' : d > 0 ? '+' : '−') + Math.abs(scaled).toFixed(digits) + (spec.unit === 'pp' ? tx(' 个百分点') : ' ' + spec.unit);
  const tone = zero || !spec.better ? '' : (spec.better === 'higher') === d > 0 ? 'text-success' : 'text-warning';
  return <td className={cn('font-mono whitespace-nowrap', tone)}>{text}{tone && <span className="sr-only">{tx(tone === 'text-success' ? '（B更好）' : '（B更差）')}</span>}</td>;
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
  const recordA = shown.find((r) => ids.indexOf(r.id) === 0), recordB = shown.find((r) => ids.indexOf(r.id) === 1);
  const pair = !!recordA && !!recordB;
  const presentation = result ? evaluationPresentation(job, result) : null;
  // Every coordinate evaluation is a library record (labelled with its conditions);
  // signal simulation takes only the default protocol.
  const savedEvaluation = !!result && action === 'evaluate';
  const simulationReady = savedEvaluation && noiseModelId === 'iid' && !scenarioId;
  return (
    <main className="lab-page">
      <SiteHeader
        current={mode === 'coordinates' ? 'coordinates' : 'decision'}
        selection={{
          id:
            mode === 'coordinates'
              ? savedEvaluation
                ? (job?.key ?? null)
                : testTarget !== 'import' ? (shown.find(r => r.id === ids[testTarget === 'b' ? 1 : 0])?.id ?? null) : null
              : (shown.find((r) => r.id === ids[0])?.id ?? null),
          phase:
            mode === 'coordinates' && testTarget === 'import' && !savedEvaluation
              ? 'draft'
              : 'saved',
          channels: mode === 'coordinates' && design ? 64 : undefined,
        }}
        arPercent={thresholds.field}
        returnHref={result && job?.annotation_id ? here + '&annotation_record=' + job.key + '&annotation_id=' + job.annotation_id : here}
      />
      <div className="lab-container space-y-5 pb-10">
        <header className="flex flex-wrap items-end justify-between gap-4 pt-6">
          <div>
            <h1 className="text-2xl font-semibold">
              {tx(
                mode === 'coordinates'
                  ? '坐标导入与评价'
                  : '方案对比与设计报告',
              )}
            </h1>
            <p className="mt-2 text-base text-muted-foreground">
              {tx(
                mode === 'coordinates'
                  ? '导入已有64点坐标，评价后保存为独立布局；不运行区域布局搜索。'
                  : '选择两个64电极方案，核对约束与性能，再检查坐标偏移对重建的影响。',
              )}
            </p>
          </div>
          {mode === 'compare' && (
            <Button
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
              <Download className="size-4" />
              {tx('导出对比报告')}
            </Button>
          )}
        </header>
        {tx(
          error && (
            <p role="alert" className="lab-panel text-danger">
              <RuntimeMessage message={error} />
            </p>
          ),
        )}
        {mode === 'compare' && (
          <>
            <section
              className="lab-panel grid gap-4 lg:grid-cols-2"
              aria-label={tx('选择对比方案')}
            >
              {['方案A', '方案B'].map((label, i) => (
                <RecordPicker key={label} label={tx(label)} records={choices} value={ids[i]} exclude={ids[1 - i]}
                  onChange={(id) => setIds((old) => old.map((v, k) => (k === i ? id : v)))} />
              ))}
            </section>
            <DecisionRequirements thresholds={thresholds} onChange={setThresholds} />
            {tx(
              loaded && shown.length > 0 && (
                <section className="lab-panel overflow-x-auto">
                  <h2 className="text-lg font-semibold">{tx('原记录对照')}</h2>
                  <p className="mt-2 text-sm font-medium">{tx(decisionCriteriaSummary(thresholds))}</p>
                  {tx(
                    notes.map((n) => (
                      <p className="mt-2 text-sm text-warning" key={n}>
                        {tx(n)}
                      </p>
                    )),
                  )}
                  <table className="mt-4 w-full min-w-[620px] text-left text-sm">
                    <thead>
                      <tr className="border-b">
                        <th className="py-3">{tx('项目')}</th>
                        {tx(
                          shown.map((r) => (
                            <th key={r.id}>
                              {tx(ids.indexOf(r.id) === 0 ? '方案A' : '方案B')}{' '}
                              ·{tx(' ')}
                              {tx(r.region_count)}
                              {tx('区')}
                            </th>
                          )),
                        )}
                        {pair && <th className="whitespace-nowrap">{tx('差值（B − A）')}</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {tx(
                        (
                          [
                            [
                              '实验类型',
                              (r: SavedRecord) => protocolName(r.dataset_id),
                            ],
                            [
                              '面积上限',
                              (r: SavedRecord) =>
                                r.area_cap_cm2
                                  ? r.area_cap_cm2 + ' cm²'
                                  : '按每区半径约束',
                            ],
                            [
                              '实际区域面积',
                              (r: SavedRecord) =>
                                r.geometry
                                  ? r.geometry.union_area_cm2.toFixed(2) +
                                    ' cm²'
                                  : '未提供',
                            ],
                            [
                              '实际最小直线点距',
                              (r: SavedRecord) =>
                                mm(r.geometry?.minimum_chord_distance_mm),
                            ],
                            [
                              '信号重建保留率',
                              (r: SavedRecord) =>
                                pct(r.metrics?.field_relative),
                            ],
                            [
                              '幅度保留率（最差10%）',
                              (r: SavedRecord) =>
                                pct(r.metrics?.sensitivity_tail),
                            ],
                            [
                              '相对定位评分',
                              (r: SavedRecord) =>
                                pct(r.metrics?.localization_relative),
                            ],
                            [
                              '定位误差 · 中位数',
                              (r: SavedRecord) => mm(r.metrics?.median_mm),
                            ],
                            [
                              '定位误差 · P90',
                              (r: SavedRecord) => mm(r.metrics?.p90_mm),
                            ],
                            [
                              '标准64重建解释率',
                              (r: SavedRecord) =>
                                pct(r.metrics?.reference_field_absolute),
                            ],
                            [
                              '标准64定位中位数',
                              (r: SavedRecord) =>
                                mm(r.metrics?.reference_median_mm),
                            ],
                          ] as const
                        ).map(([label, show]) => (
                          <tr key={label} className="border-b">
                            <th className="py-3 font-normal text-muted-foreground">
                              {tx(label)}
                            </th>
                            {tx(
                              shown.map((r) => (
                                <td className="font-mono" key={r.id}>
                                  {tx(show(r))}
                                </td>
                              )),
                            )}
                            {pair && <DifferenceCell spec={DIFFERENCES[label]} a={recordA} b={recordB} />}
                          </tr>
                        )),
                      )}
                      <tr>
                        <th className="py-3">{tx('所选条件判定')}</th>
                        {tx(
                          shown.map((r) => {
                            const q = qualification(r, thresholds);
                            return (
                              <td key={r.id} className="py-3">
                                <OutcomeBadge outcome={q.state === 'pass' ? 'pass' : q.state === 'missing' ? 'undefined' : 'fail'} className="whitespace-normal text-sm">
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
                        {pair && <td className="text-muted-foreground">—</td>}
                      </tr>
                    </tbody>
                  </table>
                  <p className="mt-3 text-sm text-muted-foreground">
                    {tx(
                      '当前表格读取原实验评分；512独立源复评另有记录。点击方案的坐标导出可保留完整三维位置。',
                    )}
                  </p>
                  <div className="mt-4 flex flex-wrap gap-3">
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
            {tx(mode === 'coordinates' ? '坐标导入与评价' : '位置偏移测试')}
          </h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {tx(
              mode === 'coordinates'
                ? '导入Ernie原生毫米坐标系中的64点设计。已在前向库中的点直接使用原FEM结果；新位置执行新的FEM计算。其他头模的数字化坐标须先配准。'
                : '固定所选布局，检查网格位置偏移前后的重建表现；外部坐标在布局设计的坐标导入中评价。',
            )}
          </p>
          <div className="mt-4 grid items-start gap-4 lg:grid-cols-2">
            <div className="space-y-4">
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
                    <output className="block text-sm text-muted-foreground">
                      {tx(draftNotice)}
                    </output>
                  )}
                  <label className="lab-label">
                    {tx('导入CSV或JSON')}
                    <FilePicker
                      accept=".csv,.json"
                      onChange={async (e) => {
                        const file = e.target.files?.[0];
                        if (!file) return;
                        try {
                          if (file.size > 65536)
                            throw new Error('坐标文件上限64 KB');
                          const d = parseDesign(await file.text(), file.name);
                          setImported(d);
                          setImportError('');
                          setTestTarget('import');
                        } catch (err) {
                          setImported(null);
                          setImportError(
                            err instanceof Error ? err.message : '导入失败',
                          );
                        }
                      }}
                    />
                  </label>
                  <label className="lab-label">{tx('导入BIDS坐标文件')}
                    <FilePicker multiple accept=".tsv,.json" onChange={async event => {
                      const files = Array.from(event.target.files ?? []);
                      if (!files.length) return;
                      try {
                        if (files.length > 3 || files.some(file => file.size > 65536)) throw new Error('请成对选择electrodes.tsv和coordsystem.json，每个文件不超过64 KB。');
                        const coordinateFiles = await Promise.all(files.map(async file => ({ name: file.name, text: await file.text() })));
                        const design = parseBIDSElectrodes(coordinateFiles, bidsNeedsMniSurface(coordinateFiles) ? await loadErnieMniSurface() : undefined);
                        setImported(design); setImportError(''); setTestTarget('import');
                      } catch (caught) { setImported(null); setImportError(caught instanceof Error ? caught.message : '导入失败'); }
                    }} />
                  </label>
                  <p className="text-xs text-muted-foreground">{tx('同时选择electrodes.tsv和coordsystem.json；region列为本软件的零基区域扩展，可附electrodes.json说明。坐标须为Ernie原生空间或MNI模板空间，单位mm；MNI坐标经SimNIBS非线性变换映射到Ernie头皮。')}</p>
                  <label className="lab-label">{tx('按10-05电极名称导入')}
                    <FilePicker accept=".tsv,.csv,.txt" onChange={async event => {
                      const file = event.target.files?.[0];
                      if (!file) return;
                      try {
                        if (file.size > 65536) throw new Error('请选择不超过64 KB的.tsv、.csv或.txt电极名称文件。');
                        setImported(parseElectrodeLabels({ name: file.name, text: await file.text() })); setImportError(''); setTestTarget('import');
                      } catch (caught) { setImported(null); setImportError(caught instanceof Error ? caught.message : '导入失败'); }
                    }} />
                  </label>
                  <p className="text-xs text-muted-foreground">{tx('表头为name和region两列，共64行。位置取SimNIBS 10-05电极帽在Ernie头皮上的模板坐标，与标准64导参考同一来源；T3、T4、T5、T6按T7、T8、P7、P8读取。')}</p>
                  {tx(
                    importError && (
                      <p role="alert" className="text-sm text-danger">
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
                  className="text-primary underline"
                  href={
                    decisionHref([ids[0] ?? ''], thresholds).replace('/decision?', '/coordinates?')
                  }
                >
                  {tx('导入外部电极坐标 →')}
                </a>
              )}
              {tx(
                design && (
                  <p className="text-sm">
                    {tx('已载入64点 · ')}
                    {tx(new Set(design.region_indices).size)}
                    {tx('区 · 最小直线点距 ')}
                    {tx(minimumDistance(design).toFixed(2))} mm
                  </p>
                ),
              )}
              <div className="grid grid-cols-2 gap-3">
                {mode === 'compare' && (
                  <label className="lab-label">
                    {tx('网格偏移上限')}
                    <select
                      className="lab-select mt-2"
                      value={radius}
                      onChange={(e) => setRadius(Number(e.target.value))}
                    >
                      {tx(
                        [3, 6, 10].map((r) => (
                          <option key={r} value={r}>
                            {tx(r)} mm
                          </option>
                        )),
                      )}
                    </select>
                  </label>
                )}
                <label className="lab-label col-span-2">
                  {tx('噪声模型')}
                  <select
                    className="lab-select mt-2"
                    value={noiseModelId}
                    onChange={(e) => setNoiseModelId(e.target.value)}
                  >
                    {NOISE_MODEL_PRESETS.map((preset) => (
                      <option key={preset.id} value={preset.id}>
                        {tx(preset.label)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="lab-label col-span-2">
                  {tx('数据生成头模电导率')}
                  <select
                    className="lab-select mt-2"
                    value={scenarioId}
                    onChange={(e) => setScenarioId(e.target.value)}
                  >
                    {CONDUCTIVITY_SCENARIOS.map((scenario) => (
                      <option key={scenario.id} value={scenario.id}>
                        {tx(scenario.label)}
                      </option>
                    ))}
                  </select>
                  <span className="mt-1 block text-xs font-normal leading-5 text-muted-foreground">{tx('只用于“评价当前坐标”。数据由改变颅骨电导率的头模生成，重建与定位仍使用名义模型。')}</span>
                </label>
                <label className="lab-label">
                  {tx('随机种子')}
                  <input
                    type="number"
                    className="lab-select mt-2"
                    min={0}
                    max={9999}
                    value={seed}
                    onChange={(e) => {
                      const n = Number(e.target.value);
                      if (Number.isInteger(n) && n >= 0 && n <= 9999)
                        setSeed(n);
                    }}
                  />
                </label>
              </div>
              {mode === 'compare' && (
                <p className="text-sm leading-6 text-muted-foreground">
                  {tx(
                    '网格测试固定区域标签，对每区施加同方向目标偏移，再匹配邻近候选点。输出实际位移、目标匹配误差和未移动比例；这是离散网格敏感性检查。',
                  )}
                </p>
              )}
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={!design || computing}
                  onClick={() => runEvaluation('evaluate')}
                >
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
              <p className="text-sm text-muted-foreground">
                {tx(
                  '每次一项任务，坐标评价使用单线程；结果保存为独立缓存。新位置FEM计算最多运行10分钟。',
                )}
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
                  <p aria-live="polite" className="text-sm">
                    <RuntimeMessage message={job.message} status={job.status} queuePosition={job.queue_position} />
                    {tx(
                      computing && job.status !== 'queued' ? ` · ${Math.round(job.progress * 100)}%` : '',
                    )}
                    {tx(job.cached ? ' · 已读取缓存' : '')}
                    {tx(
                      jobIdentity !== requestIdentity
                        ? ' · 来自修改前的测试条件'
                        : '',
                    )}
                  </p>
                ),
              )}
            </div>
            <div>
              {tx(
                result && (
                  <label className="mb-3 flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={showEvaluated}
                      onChange={(e) => setShowEvaluated(e.target.checked)}
                    />
                    {tx('显示实际评价坐标（取消后显示导入原坐标）')}
                  </label>
                ),
              )}
              {tx(
                preview && (
                  <Suspense
                    fallback={
                      <p className="lab-panel">{tx('加载三维布局…')}</p>
                    }
                  >
                    <Head
                      regionCount={new Set(preview.regionIndices).size}
                      allocation={Array.from(new Set(preview.regionIndices))
                        .sort((a, b) => a - b)
                        .map(
                          (r) =>
                            preview.regionIndices.filter((v) => v === r).length,
                        )}
                      domainMode="whole_surface"
                      radiusCm={3.5}
                      recordedLayout={preview}
                    />
                  </Suspense>
                ),
              )}
              {design && <details className="mt-3 rounded-lg border p-3"><summary className="cursor-pointer text-sm">{tx('查看电极名称与区域')}</summary>
                <div className="mt-2 max-h-64 overflow-auto"><table className="w-full text-left text-sm"><thead><tr><th>{tx('电极')}</th><th>{tx('区域')}</th><th>X (mm)</th><th>Y (mm)</th><th>Z (mm)</th></tr></thead>
                  <tbody>{design.xyz_mm.map((point, index) => <tr key={index}><td>{design.electrode_names?.[index] ?? `E${index + 1}`}</td><td>{design.region_indices[index]}</td>{point.map((value, axis) => <td className="font-mono" key={axis}>{value}</td>)}</tr>)}</tbody>
                </table></div>
              </details>}
              {design && <CoordinateReviewPanel design={design} result={result} />}
              {design && mode === 'coordinates' && <CoordinateStudyLink design={design} />}
              {mode === 'coordinates' && design && <CoordinateFileExports design={design} />}
              {mode === 'coordinates' && design && <LayoutFigureExport design={design} />}
            </div>
          </div>
          {tx(
            result && (
              <div className="mt-5 overflow-x-auto border-t pt-4">
                <h3 className="font-semibold">
                  {tx(presentation!.heading)}
                </h3>
                <p className="mt-1 text-xs text-muted-foreground">{tx('原结果来源')} · {tx(presentation!.origin)}</p>
                <p className="mt-1 text-xs text-muted-foreground">{tx('噪声模型')} · {tx(noiseModelLabel(NOISE_MODEL_PRESETS.find((preset) => preset.id === noiseModelId)?.value))}{action === 'evaluate' && scenarioId && <> · {tx('数据生成头模电导率')} · {tx(conductivityScenarioLabel(scenarioId))}</>}</p>
                <p className="mt-2 text-sm">
                  {tx('重建保留率 ')}
                  {tx(pct(result.nominal?.field_relative))}{' '}
                  {tx(' · 幅度保留率')}
                  {tx(' ')}
                  {tx(pct(result.nominal?.sensitivity_tail))}{' '}
                  {tx(' · 相对定位评分')}
                  {tx(' ')}
                  {tx(pct(result.nominal?.localization_relative))}
                  {tx('。坐标最大调整距离')}
                  {tx(' ')}
                  {tx(mm(result.projection_max_mm))}。
                </p>
                {action === 'evaluate' && job?.key && <div className="mt-3 flex flex-wrap items-center gap-3">
                  {savedEvaluation && <>
                    <SaveToProject kind="layout" recordId={job.key} annotationId={job.annotation_id} />
                    <a className="text-sm text-primary underline" href={'/coordinates?a=' + job.key + (job.annotation_id ? '&annotation_a=' + job.annotation_id : '')}>{tx('打开保存的坐标评价')}</a>
                  </>}
                  <Button variant="outline" size="sm" onClick={() => design && download('eeg-evaluated-coordinates.csv', designCSV({ ...design, xyz_mm: result.evaluated_xyz_mm }), 'text/csv;charset=utf-8')}>{tx('导出实际评价坐标')}</Button>
                </div>}
                {action === 'evaluate' && job?.key && !simulationReady && (
                  <p className="mt-2 text-xs text-muted-foreground">{tx('此评价已按其噪声模型或电导率情景标注保存到结果库；信号仿真只接受默认协议下的布局。')}</p>
                )}
                {tx(
                  action === 'evaluate' && job?.key && simulationReady && (
                    <a
                      className="mt-3 inline-block text-sm font-semibold text-primary underline"
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
                <table className="mt-3 w-full min-w-[420px] text-left text-sm">
                  <thead>
                    <tr>
                      <th className="py-2">{tx('绝对指标')}</th>
                      <th>{tx('当前坐标')}</th>
                      <th>{tx('标准全头64')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-t">
                      <th className="py-2 font-normal">{tx('重建解释率')}</th>
                      <td>{tx(pct(result.nominal.field_absolute))}</td>
                      <td>
                        {tx(pct(result.nominal.reference_field_absolute))}
                      </td>
                    </tr>
                    <tr className="border-t">
                      <th className="py-2 font-normal">
                        {tx('定位误差中位数')}
                      </th>
                      <td>{tx(mm(result.nominal.median_mm))}</td>
                      <td>{tx(mm(result.nominal.reference_median_mm))}</td>
                    </tr>
                    <tr className="border-t">
                      <th className="py-2 font-normal">{tx('定位误差P90')}</th>
                      <td>{tx(mm(result.nominal.p90_mm))}</td>
                      <td>{tx(mm(result.nominal.reference_p90_mm))}</td>
                    </tr>
                  </tbody>
                </table>
                <p className="mt-3 text-sm">
                  <span className="block mb-2">{tx(decisionCriteriaSummary(thresholds))}</span>
                  {tx('本次坐标评价：')}
                  {tx(
                    resultQualification?.state === 'pass'
                      ? '达到全部启用要求'
                      : resultQualification?.state === 'missing'
                        ? '所选判据数据不完整'
                        : '未达到：' + resultQualification?.failed.join('、'),
                  )}
                  。
                </p>
                {tx(
                  result.trials?.length > 0 && (
                    <>
                      <table className="mt-4 w-full min-w-[700px] text-sm text-left">
                        <thead>
                          <tr>
                            <th>{tx('偏移试验')}</th>
                            <th>{tx('实际位移（平均 / 最大）')}</th>
                            <th>{tx('目标匹配误差（最大）')}</th>
                            <th>{tx('未移动比例')}</th>
                            <th>{tx('重标定后重建')}</th>
                            <th>{tx('沿用原重建器')}</th>
                            <th>{tx('几何状态')}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {tx(
                            result.trials.map((t) => (
                              <tr key={t.index} className="border-t">
                                <td className="py-3">{tx(t.index + 1)}</td>
                                <td>
                                  {tx(mm(t.actual_mean_mm))} /{' '}
                                  {tx(mm(t.actual_max_mm))}
                                </td>
                                <td>{tx(mm(t.target_error_max_mm))}</td>
                                <td>{tx(pct(t.unchanged_fraction))}</td>
                                <td>{tx(pct(t.field_relative))}</td>
                                <td>
                                  {tx(pct(t.fixed_estimator_field_relative))}
                                </td>
                                <td>
                                  {tx(
                                    t.status === 'completed'
                                      ? '64点互异，点距通过'
                                      : t.message,
                                  )}
                                </td>
                              </tr>
                            )),
                          )}
                        </tbody>
                      </table>
                      <p className="mt-3 text-sm text-muted-foreground">
                        {tx(
                          '参照64布局固定；偏移后重新标定与沿用原重建器分别计算。保留原区域标签，未重新验证贴片边界和区域分离。4次试验为检查样本，不表示人群分布。',
                        )}
                      </p>
                    </>
                  ),
                )}
                <Button
                  className="mt-3"
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
        {mode === 'coordinates' && <DecisionRequirements thresholds={thresholds} onChange={setThresholds} />}
        <section className="lab-panel">
          <h2 className="text-lg font-semibold">{tx('验证阶段')}</h2>
          <p className="mt-2 text-sm leading-7">
            {tx(
              '已完成：单头模布局实验、独立源复评与多种噪声控制。进行中：数值和搜索稳定性核查。待独立数据：新头模上的冻结布局迁移、实测噪声校准和同步采集对照。',
            )}
          </p>
          <a
            className="mt-2 inline-block text-sm text-primary underline"
            href={
              '/method?ar=' +
              thresholds.field +
              '&returnTo=' +
              encodeURIComponent(here)
            }
          >
            {tx('查看指标定义与建模方法')}
          </a>
        </section>
      </div>
    </main>
  );
}
