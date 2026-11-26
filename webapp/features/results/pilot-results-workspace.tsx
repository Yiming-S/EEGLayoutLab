'use client';
import { useLanguage } from '@/components/language-provider';

// Archived first-batch comparison; unified optimization is at /results.

/* oxlint-disable next/no-html-link-for-pages -- preserve the existing vinext navigation behavior */
import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { ArrowRight, Info, RefreshCcw } from 'lucide-react';
import { SiteHeader } from '@/components/site-header';
import { parseAR, methodLink } from '@/lib/lab-workflow';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { apiFetch } from '@/client/task-client';
import {
  atSnr,
  checkResults,
  RESULT_FAMILIES,
  retentionPercent,
  selectRecordedLayout,
  type Fixed64Results,
} from '@/lib/fixed64-results';
import { PilotComparisonTablesSection } from './pilot-comparison-tables-section';

const ClusterHeadViewer = lazy(() =>
  import('@/components/cluster-head-viewer').then((m) => ({
    default: m.ClusterHeadViewer,
  })),
);
const RADII = [20, 30, 40, 50];
const SELECT_STYLE = 'lab-select';
const PANEL_STYLE = 'lab-panel';
const mm = (value?: number | null) =>
  value == null ? '未计算' : `${value.toFixed(2)} mm`;

function MetricCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  const { tx } = useLanguage();
  return (
    <div className={PANEL_STYLE}>
      <h3 className="text-xs font-medium text-ink-soft">{tx(label)}</h3>
      <p className="my-2 font-mono text-2xl font-semibold tracking-tight text-primary tabular-nums sm:text-3xl">
        {tx(value)}
      </p>
      <p className="text-xs leading-5 text-ink-soft">{tx(detail)}</p>
    </div>
  );
}

export default function ResultsPage() {
  const { tx } = useLanguage();
  const [data, setData] = useState<Fixed64Results | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [family, setFamily] = useState<string>(RESULT_FAMILIES[0].id);
  const [radius, setRadius] = useState(30);
  const [spacing, setSpacing] = useState(6);
  const [snr, setSnr] = useState(20);
  const [ar, setAr] = useState(90), [ready, setReady] = useState(false);
  const here = '/pilot-results?' + new URLSearchParams({ ar: String(ar), family, radius: String(radius), spacing: String(spacing), snr: String(snr) }).toString();
  useEffect(() => {
    const restore = () => {
      const q = new URLSearchParams(window.location.search), a = Number(q.get('radius')), db = Number(q.get('snr'));
      setAr(parseAR(q.get('ar'))); setFamily(RESULT_FAMILIES.find((f) => f.id === q.get('family'))?.id ?? RESULT_FAMILIES[0].id);
      setRadius([20, 30, 40, 50].includes(a) ? a : 30); setSpacing(q.get('spacing') === '4' ? 4 : 6);
      setSnr(q.has('snr') && [0, 10, 20].includes(db) ? db : 20); setReady(true);
    };
    restore(); window.addEventListener('popstate', restore); return () => window.removeEventListener('popstate', restore);
  }, []);
  useEffect(() => { if (ready) window.history.replaceState(null, '', here); }, [ready, here]);
  useEffect(() => {
    const abort = new AbortController();
    apiFetch('/data/fixed64_results.json', { signal: abort.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((value) => {
        setData(checkResults(value));
        setError('');
      })
      .catch((reason: Error) => {
        if (!abort.signal.aborted) setError(reason.message);
      });
    return () => abort.abort();
  }, [attempt]);
  const selected = data
    ? selectRecordedLayout(data, family, radius, spacing)
    : null;
  const recordedLayout = useMemo(
    () =>
      selected && data
        ? {
            id: selected.id,
            xyzMm: selected.xyz_mm,
            regionIndices: selected.region_indices,
            referenceXyzMm: data.reference.xyz_mm,
          }
        : undefined,
    [selected, data],
  );
  const condition = atSnr(selected?.metrics.conditions ?? null, snr);
  const baseline = atSnr(data?.reference.metrics.conditions ?? null, snr);
  const localization = atSnr(selected?.localization ?? null, snr);

  return (
    <main className="lab-page">
      <SiteHeader current="results" arPercent={ar} returnHref={here} />
      <div className="lab-container space-y-6 py-6">
        <a className="lab-link-pill" href={'/findings?ar=' + ar}>{tx("← 返回当前已有结果")}</a>
        <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
          <div>
            <div className="mb-2.5 flex flex-wrap gap-2">
              <Badge className="bg-brand text-brand-foreground">
                {tx("已计算 · 固定64电极")}</Badge>
              <Badge
                variant="outline"
                className="border-warning/40 bg-warning-surface text-warning"
              >
                {tx("早期单头模原型 · 未做跨头模验证")}</Badge>
            </div>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              {tx("历史原型：双区域初始布局")}</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-ink-soft sm:text-base">
              {tx("同样64个电极，集中到两个区域后，保留了多少全头电位场信息？切换已计算配置查看结果与实际点位。")}</p>
          </div>
          <a
            href={methodLink(here, ar, '#first-batch')}
            className="lab-link-pill shrink-0 text-sm"
          >
            {tx("本批怎么算 ")}<ArrowRight className="size-3.5" />
          </a>
        </header>

        {tx(!data && (
          <section className={PANEL_STYLE} aria-live="polite">
            <p className="text-base">
              {tx(error ? `结果加载失败：${error}` : '正在读取已核验的仿真数据…')}
            </p>
            {tx(error && (
              <Button className="mt-4" onClick={() => setAttempt((v) => v + 1)}>
                <RefreshCcw className="size-4" />
                {tx("重新读取")}</Button>
            ))}
          </section>
        ))}

        {tx(data && (
          <>
            <section
              className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4"
              aria-label={tx("本批实验规模")}
            >
              {tx([
                [
                  '完整配置',
                  `${data.configuration_count} 组 / ${data.unique_layout_count} 种点位组合`,
                ],
                ['区域与预算', '2 区 × 32 电极 = 64'],
                ['计算源集合', '4,096 字典源 / 256 测试源'],
                [
                  '重复性',
                  `${data.provenance.repeat_batches.length} 次运行 · ${data.provenance.byte_reproducible ? '数据逐字节一致' : '尚未确认一致'}`,
                ],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className={PANEL_STYLE}
                >
                  <p className="text-xs font-medium text-ink-soft">{tx(label)}</p>
                  <p className="mt-1.5 text-sm font-semibold sm:text-base">{tx(value)}</p>
                </div>
              )))}
            </section>

            <section
              className={`${PANEL_STYLE} space-y-4`}
              aria-label={tx("选择已计算配置")}
            >
              <div className="grid gap-4 rounded-xl border border-border/65 bg-muted/30 p-3.5 sm:grid-cols-2 xl:grid-cols-[2fr_1fr_1fr_1.2fr]">
                <label className="lab-label">
                  {tx("区域组合")}<select
                    aria-label={tx("仿真区域组合")}
                    value={family}
                    onChange={(e) => setFamily(e.target.value)}
                    className={SELECT_STYLE}
                  >
                    {tx(RESULT_FAMILIES.map((f) => (
                      <option key={f.id} value={f.id}>
                        {tx(f.label)}
                      </option>
                    )))}
                  </select>
                </label>
                <label className="lab-label">
                  {tx("区域半径上限")}<select
                    aria-label={tx("已计算区域半径")}
                    value={radius}
                    onChange={(e) => setRadius(Number(e.target.value))}
                    className={SELECT_STYLE}
                  >
                    {tx(RADII.map((r) => (
                      <option key={r} value={r}>
                        {tx(r)} mm（{tx(r / 10)} cm）
                      </option>
                    )))}
                  </select>
                </label>
                <label className="lab-label">
                  {tx("最小电极间距约束")}<select
                    aria-label={tx("仿真最小电极间距")}
                    value={spacing}
                    onChange={(e) => setSpacing(Number(e.target.value))}
                    className={SELECT_STYLE}
                  >
                    {tx([4, 6].map((d) => (
                      <option key={d} value={d}>
                        {tx(d)} mm
                      </option>
                    )))}
                  </select>
                </label>
                <label className="lab-label">
                  {tx("参考噪声条件")}<select
                    aria-label={tx("仿真SNR")}
                    value={snr}
                    onChange={(e) => setSnr(Number(e.target.value))}
                    className={SELECT_STYLE}
                  >
                    {tx(data.snr_db.map((s) => (
                      <option key={s} value={s}>
                        {tx(s)} dB
                        {tx(s === 20
                          ? ' · 较低噪声'
                          : s === 0
                            ? ' · 较高噪声'
                            : '')}
                      </option>
                    )))}
                  </select>
                </label>
              </div>
              <p className="text-xs leading-5 text-ink-soft">
                {tx("半径是坐标区域裁剪后的图路径上限，点距是欧氏弦距，采用离散几何定义。本历史批次仅包含2个区域；1、3、4、6区域请查看首页后续实验。所有布局使用按标准64导标定的同一物理噪声强度。")}</p>
            </section>

            {tx(selected ? (
              <>
                <section
                  className="grid gap-4 md:grid-cols-3"
                  aria-live="polite"
                  aria-label={tx("所选配置指标")}
                >
                  <MetricCard
                    label={tx("信号重建 · 相对全头64点")}
                    value={retentionPercent(condition?.field_relative)}
                    detail={`候选重建解释率 ${retentionPercent(condition?.field_absolute)}；基准 ${retentionPercent(baseline?.field_absolute)}。`}
                  />
                  <MetricCard
                    label={tx("幅度保留率（最差10%）")}
                    value={retentionPercent(selected.metrics.sensitivity_tail)}
                    detail="按相对幅度保留率排序，取最低10%皮层面积的加权均值。"
                  />
                  <MetricCard
                    label={tx("离散定位诊断 · P90误差")}
                    value={mm(localization?.p90_mm)}
                    detail={
                      localization
                        ? `中位误差 ${mm(localization.median_mm)}。数值越小越好；受固定法向字典限制。`
                        : '定位结果覆盖半径上限30 mm、最小电极直线间距6 mm的四个预设布局。'
                    }
                  />
                </section>
                <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
                  <div className="min-w-0">
                    <Suspense
                      fallback={
                        <div className="head-stage grid h-[640px] place-items-center rounded-2xl">
                          {tx("加载已计算布局…")}</div>
                      }
                    >
                      <ClusterHeadViewer
                        regionCount={2}
                        allocation={[32, 32]}
                        domainMode="preset"
                        radiusCm={radius / 10}
                        recordedLayout={recordedLayout}
                      />
                    </Suspense>
                  </div>
                  <aside className={`${PANEL_STYLE} h-fit space-y-4`}>
                    <div>
                      <h2 className="text-lg font-semibold">
                        {tx("这64个点来自计算记录")}</h2>
                      <p className="mt-1.5 text-xs leading-5 text-ink-soft">
                        {tx("位置取自本批FEM的MRI坐标，仅换算单位；触点外观沿法向抬高1.2 mm用于显示，计算使用原始坐标。基准为BioSemi64名称匹配的Ernie-SPM12全头模板。")}</p>
                    </div>
                    <dl className="divide-y divide-border/65 rounded-xl border border-border/70 bg-muted/30 px-3.5 py-1 text-xs">
                      <div className="flex justify-between gap-3 py-2">
                        <dt className="text-muted-foreground">{tx("配置编号")}</dt>
                        <dd className="font-mono font-medium tabular-nums">
                          {tx(selected.index + 1)} / {tx(data.configuration_count)}
                        </dd>
                      </div>
                      {tx(selected.region_areas_cm2.map((area, i) => (
                        <div className="flex justify-between gap-3 py-2" key={i}>
                          <dt className="text-muted-foreground">{tx("区域 ")}{tx(i + 1)} {tx(" · 候选面积")}</dt>
                          <dd className="font-mono font-medium tabular-nums">{tx(area.toFixed(2))} cm²</dd>
                        </div>
                      )))}
                    </dl>
                    <p className="text-xs leading-5 text-ink-soft">
                      {tx("候选贴片面积是离散近似，不等于电极凸包面积。耳后邻近和耳周均为近似坐标掩膜，尚未审核为严格无毛区域。")}</p>
                    <div className="rounded-xl border border-warning/30 bg-warning-surface/75 p-3.5 text-xs leading-5 text-warning">
                      <Info className="mb-1.5 size-4" />
                      {tx("本历史批次采用预设位置进行性能评价；群体阈值与最小面积需另行验证。")}</div>
                    <a
                      href="https://github.com/simnibs/example-dataset/releases/tag/v4.1"
                      className="lab-link-pill"
                    >
                      {tx("头模：SimNIBS Ernie · CC BY-NC 4.0")}</a>
                  </aside>
                </section>
              </>
            ) : (
              <section
                className="rounded-2xl border border-warning/35 bg-warning-surface/80 p-6"
                aria-live="polite"
              >
                <h2 className="text-lg font-semibold text-warning">
                  {tx("本历史批次未找到该配置的完整布局")}</h2>
                <p className="mt-2 text-sm leading-6 text-warning">
                  {tx("20 mm半径、6 mm点距下，本批贪心构造未找到完整64点布局，该条件的几何可行性仍待判定。可选择30、40、50 mm，或4 mm点距。")}</p>
              </section>
            ))}

            <PilotComparisonTablesSection
              data={data}
              family={family}
              radius={radius}
              spacing={spacing}
              snr={snr}
              onSelectCell={(familyId, radiusMm) => {
                setFamily(familyId);
                setRadius(radiusMm);
              }}
            />
          </>
        ))}
      </div>
    </main>
  );
}
