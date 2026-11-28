'use client';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { lazy, Suspense } from 'react';
import { ChevronDown } from 'lucide-react';
import {
  conductivityScenarioLabel,
  dataPriorLabel,
  noiseModelLabel,
  NOISE_MODEL_PRESETS,
} from '../../contracts/scientific-options.mjs';
import { RuntimeMessage } from '@/components/runtime-message';
import { Button } from '@/components/ui/button';
import { useLanguage } from '@/components/language-provider';
import { EvaluationConditions } from '@/features/conditions/evaluation-conditions';
import { SaveToProject } from '@/features/projects/project-context';
import { CoordinateStudyLink } from '@/features/robustness/coordinate-study-link';
import type { ConductivityScenarioId, PerturbationRadius } from '@/lib/api-types';
import {
  decisionCriteriaSummary,
  decisionHref,
  designCSV,
  isConductivityScenario,
  isPerturbationRadius,
  minimumDistance,
  mm,
  pct,
  PERTURBATION_RADII,
  type DecisionThresholds,
  type DesignJob,
  type DesignResult,
  type ElectrodeDesign,
  type qualification,
} from '@/lib/design-decision';
import { layoutHref } from '@/lib/layout-page';
import type { ComputedLayout, DataPrior } from '@/lib/local-compute';
import type { SavedRecord } from '@/lib/local-library';
import { CoordinateFileExports } from './coordinate-file-exports';
import { CoordinateImportFields } from './coordinate-import-fields';
import { CoordinateReviewPanel } from './coordinate-review-panel';
import { downloadTextFile } from './decision-download';
import { evaluationPresentation } from './evaluation-presentation';
import { LayoutFigureExport } from './layout-figure-export';
import { RobustnessPanel } from './robustness-panel';

const Head = lazy(() =>
  import('@/components/cluster-head-viewer').then((m) => ({
    default: m.ClusterHeadViewer,
  })),
);

export function PositionEvaluationSection({
  mode,
  ids,
  shown,
  thresholds,
  testTarget,
  setTestTarget,
  selectedTargetRecord,
  draftNotice,
  importError,
  setImported,
  setImportError,
  design,
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
  job,
  computeError,
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
  savedEvaluation,
  simulationReady,
}: {
  mode: 'compare' | 'coordinates';
  ids: string[];
  shown: SavedRecord[];
  thresholds: DecisionThresholds;
  testTarget: string;
  setTestTarget: (target: string) => void;
  selectedTargetRecord?: SavedRecord;
  draftNotice: string;
  importError: string;
  setImported: (design: ElectrodeDesign | null) => void;
  setImportError: (message: string) => void;
  design: ElectrodeDesign | null;
  radius: PerturbationRadius;
  setRadius: (radius: PerturbationRadius) => void;
  seed: number;
  setSeed: (seed: number) => void;
  noiseModelId: string;
  setNoiseModelId: (id: string) => void;
  scenarioId: ConductivityScenarioId | '';
  setScenarioId: (id: ConductivityScenarioId | '') => void;
  robustness: boolean;
  setRobustness: (enabled: boolean) => void;
  dataPrior: DataPrior | null;
  dataPriorSource: string;
  setDataPrior: (prior: DataPrior | null, source?: string) => void;
  action: 'evaluate' | 'perturb';
  showEvaluated: boolean;
  setShowEvaluated: (show: boolean) => void;
  here: string;
  job: DesignJob | null;
  computeError: string;
  requestIdentity: string;
  jobIdentity: string;
  result: DesignResult | null;
  resultQualification: ReturnType<typeof qualification> | null;
  computing: boolean;
  connection?: string;
  reconnect?: () => void;
  runEvaluation: (action: 'evaluate' | 'perturb') => void;
  cancel: () => void;
  preview: ComputedLayout | undefined;
  savedEvaluation: boolean;
  simulationReady: boolean;
}) {
  const { tx } = useLanguage();
  const presentation = result ? evaluationPresentation(job, result) : null;

  return (
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
          {mode === 'compare' && selectedTargetRecord && !design && (
            <p className="rounded-xl border border-border/75 bg-muted/35 px-3.5 py-2.5 text-xs leading-5 text-muted-foreground">
              {tx(
                '当前所选方案使用少于64导或跨区自适应配额；上方已完成并排性能与空间对比，下方跨条件坐标评价与网格偏移仅适用于均衡分配的64电极方案。',
              )}
            </p>
          )}
          {mode === 'coordinates' ? (
            <CoordinateImportFields
              draftNotice={draftNotice}
              importError={importError}
              templateSourceRecord={shown[0]}
              onImported={(parsed) => {
                setImported(parsed);
                setImportError('');
                setTestTarget('import');
              }}
              onImportError={(message) => {
                setImported(null);
                setImportError(message);
              }}
            />
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
          {connection === 'blocked' && job && reconnect && (
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
                <ChevronDown
                  aria-hidden
                  className="size-4 text-muted-foreground transition-transform group-open/names:rotate-180"
                />
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
                        <td className="px-3 py-1.5 font-medium">
                          {design.electrode_names?.[index] ?? `E${index + 1}`}
                        </td>
                        <td className="px-2.5 py-1.5 font-mono tabular-nums">
                          {design.region_indices[index]}
                        </td>
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
                    downloadTextFile(
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
                {tx(
                  '此评价已按其噪声模型或电导率情景标注保存到结果库；信号仿真只接受默认协议下的布局。',
                )}
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
                    <td className="px-3 font-mono tabular-nums">
                      {tx(pct(result.nominal.field_absolute))}
                    </td>
                    <td className="px-4 font-mono tabular-nums">
                      {tx(pct(result.nominal.reference_field_absolute))}
                    </td>
                  </tr>
                  <tr className="border-b border-border/65">
                    <th className="px-4 py-2.5 font-normal">{tx('定位误差中位数')}</th>
                    <td className="px-3 font-mono tabular-nums">
                      {tx(mm(result.nominal.median_mm))}
                    </td>
                    <td className="px-4 font-mono tabular-nums">
                      {tx(mm(result.nominal.reference_median_mm))}
                    </td>
                  </tr>
                  <tr>
                    <th className="px-4 py-2.5 font-normal">{tx('定位误差P90')}</th>
                    <td className="px-3 font-mono tabular-nums">
                      {tx(mm(result.nominal.p90_mm))}
                    </td>
                    <td className="px-4 font-mono tabular-nums">
                      {tx(mm(result.nominal.reference_p90_mm))}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="text-sm">
              <span className="mb-1.5 block text-xs text-muted-foreground">
                {tx(decisionCriteriaSummary(thresholds))}
              </span>
              <span className="font-medium">
                {tx('本次坐标评价：')}
                {tx(
                  resultQualification?.state === 'pass'
                    ? '均高于启用参考线'
                    : resultQualification?.state === 'missing'
                      ? '所选参考条件数据不完整'
                      : '低于参考线：' + resultQualification?.failed.join('、'),
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
                            <tr
                              key={t.index}
                              className="border-b border-border/65 last:border-0"
                            >
                              <td className="px-3.5 py-2.5 font-mono tabular-nums">
                                {tx(t.index + 1)}
                              </td>
                              <td className="px-3 py-2.5 font-mono tabular-nums">
                                {tx(mm(t.actual_mean_mm))} / {tx(mm(t.actual_max_mm))}
                              </td>
                              <td className="px-3 py-2.5 font-mono tabular-nums">
                                {tx(mm(t.target_error_max_mm))}
                              </td>
                              <td className="px-3 py-2.5 font-mono tabular-nums">
                                {tx(pct(t.unchanged_fraction))}
                              </td>
                              <td className="px-3 py-2.5 font-mono tabular-nums">
                                {tx(pct(t.field_relative))}
                              </td>
                              <td className="px-3 py-2.5 font-mono tabular-nums">
                                {tx(pct(t.fixed_estimator_field_relative))}
                              </td>
                              <td className="px-3.5 py-2.5 text-xs">
                                {tx(
                                  t.status === 'completed' ? '64点互异，点距通过' : t.message,
                                )}
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
                downloadTextFile(
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
  );
}
