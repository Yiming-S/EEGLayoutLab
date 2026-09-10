'use client';

import { RuntimeMessage } from '@/components/runtime-message';
import { localizedRecordTitle } from '@/lib/i18n/records';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { lazy, Suspense } from 'react';
import { Download } from 'lucide-react';
import { SiteHeader } from '@/components/site-header';
import { Button } from '@/components/ui/button';
import type { SavedRecord } from '@/lib/local-library';
import { protocolName } from '@/lib/ui-language';
import {
  decisionMarkdown,
  designCSV,
  exportDesign,
  minimumDistance,
  mm,
  parseDesign,
  pct,
  qualification,
} from '@/lib/design-decision';
import { useDecisionController } from './use-decision-controller';

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
    runEvaluation,
    cancel,
    preview,
  } = useDecisionController(mode);
  return (
    <main className="lab-page">
      <SiteHeader
        current={mode === 'coordinates' ? 'coordinates' : 'decision'}
        selection={{
          id:
            mode === 'coordinates'
              ? result && action === 'evaluate'
                ? (job?.key ?? null)
                : null
              : (shown.find((r) => r.id === ids[0])?.id ?? null),
          phase:
            mode === 'coordinates' && !(result && action === 'evaluate')
              ? 'draft'
              : 'saved',
          channels: mode === 'coordinates' && design ? 64 : undefined,
        }}
        arPercent={thresholds.field}
        returnHref={here}
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
            <p role="alert" className="lab-panel text-red-800">
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
              {tx(
                ['方案A', '方案B'].map((label, i) => (
                  <label key={label} className="lab-label">
                    {tx(label)}
                    <select
                      className="lab-select mt-2"
                      value={ids[i]}
                      onChange={(e) =>
                        setIds((old) =>
                          old.map((v, k) => (k === i ? e.target.value : v)),
                        )
                      }
                    >
                      <option value="">{tx('选择已计算布局')}</option>
                      {tx(
                        choices.map((r) => (
                          <option
                            key={r.id}
                            value={r.id}
                            disabled={r.id === ids[1 - i]}
                          >
                            {localizedRecordTitle(r, locale)}
                          </option>
                        )),
                      )}
                    </select>
                  </label>
                )),
              )}
            </section>
            <section className="lab-panel">
              <h2 className="text-lg font-semibold">{tx('接受条件')}</h2>
              <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <label className="lab-label">
                  {tx('重建保留率 AR（%）')}
                  <input
                    className="lab-select mt-2"
                    type="number"
                    min={1}
                    max={100}
                    value={thresholds.field}
                    onChange={(e) => {
                      const n = Number(e.target.value);
                      if (Number.isInteger(n) && n >= 1 && n <= 100)
                        setThresholds((t) => ({ ...t, field: n }));
                    }}
                  />
                </label>
                {tx(
                  (
                    [
                      ['sensitivity', '幅度保留率下限（%）'],
                      ['localization', '相对定位评分下限（%）'],
                      ['p90_mm', '定位误差P90上限（mm）'],
                    ] as const
                  ).map(([key, label]) => (
                    <label className="lab-label" key={key}>
                      {tx(label)}
                      <input
                        className="lab-select mt-2"
                        type="number"
                        min={0}
                        max={key === 'p90_mm' ? 500 : 100}
                        placeholder={tx('不启用')}
                        value={thresholds[key] ?? ''}
                        onChange={(e) => {
                          const n = Number(e.target.value);
                          if (
                            !e.target.value ||
                            (Number.isFinite(n) &&
                              n >= 0 &&
                              n <= (key === 'p90_mm' ? 500 : 100))
                          )
                            setThresholds((t) => ({
                              ...t,
                              [key]: e.target.value === '' ? null : n,
                            }));
                        }}
                      />
                    </label>
                  )),
                )}
              </div>
              <p className="mt-3 text-sm text-muted-foreground">
                {tx(
                  '默认按重建AR判断；其他指标可分别设限。阈值变化只重新判断现有结果。',
                )}
              </p>
            </section>
            {tx(
              loaded && shown.length > 0 && (
                <section className="lab-panel overflow-x-auto">
                  <h2 className="text-lg font-semibold">{tx('原记录对照')}</h2>
                  {tx(
                    notes.map((n) => (
                      <p className="mt-2 text-sm text-amber-900" key={n}>
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
                          </tr>
                        )),
                      )}
                      <tr>
                        <th className="py-3">{tx('所选条件判定')}</th>
                        {tx(
                          shown.map((r) => {
                            const q = qualification(r, thresholds);
                            return (
                              <td
                                key={r.id}
                                className={
                                  q.state === 'pass'
                                    ? 'text-emerald-800'
                                    : 'text-amber-900'
                                }
                              >
                                {tx(
                                  q.state === 'pass'
                                    ? '达到所选阈值'
                                    : q.state === 'missing'
                                      ? '数据不完整'
                                      : '未达到：' + q.failed.join('、'),
                                )}
                              </td>
                            );
                          }),
                        )}
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
                    <input
                      className="mt-2 block w-full text-sm"
                      type="file"
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
                  {tx(
                    importError && (
                      <p role="alert" className="text-sm text-red-800">
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
                    '/coordinates?a=' +
                    (ids[0] ?? '') +
                    '&ar=' +
                    thresholds.field
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
                  <p role="alert" className="text-red-800 text-sm">
                    <RuntimeMessage message={computeError} />
                  </p>
                ),
              )}
              {tx(
                job && (
                  <p aria-live="polite" className="text-sm">
                    <RuntimeMessage message={job.message} status={job.status} />
                    {tx(
                      computing ? ` · ${Math.round(job.progress * 100)}%` : '',
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
            </div>
          </div>
          {tx(
            result && (
              <div className="mt-5 overflow-x-auto border-t pt-4">
                <h3 className="font-semibold">
                  {tx('本次新评价 ·')}
                  {tx(' ')}
                  {tx(
                    result.forward_mode === 'direct_fem'
                      ? '新位置FEM'
                      : '直接FEM缓存',
                  )}
                </h3>
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
                {tx(
                  action === 'evaluate' && job?.key && (
                    <a
                      className="mt-3 inline-block text-sm font-semibold text-primary underline"
                      href={
                        '/reception?record=' +
                        job.key +
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
                  {tx('本次坐标评价：')}
                  {tx(
                    resultQualification?.state === 'pass'
                      ? '达到所选阈值'
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
