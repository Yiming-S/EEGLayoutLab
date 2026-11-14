'use client';
import { useLanguage } from '@/components/language-provider';

// Archived first-batch comparison; unified optimization is at /results.

/* oxlint-disable next/no-html-link-for-pages -- preserve the existing vinext navigation behavior */
import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import {
  ArrowRight,
  ChartNoAxesCombined,
  Download,
  Info,
  RefreshCcw,
} from 'lucide-react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { SiteHeader } from '@/components/site-header';
import { parseAR, methodLink } from '@/lib/lab-workflow';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  atSnr,
  checkResults,
  RESULT_FAMILIES,
  retentionPercent,
  selectRecordedLayout,
  type Fixed64Results,
} from '@/lib/fixed64-results';

const ClusterHeadViewer = lazy(() =>
  import('@/components/cluster-head-viewer').then((m) => ({
    default: m.ClusterHeadViewer,
  })),
);
const RADII = [20, 30, 40, 50];
const SELECT_STYLE =
  'h-11 w-full rounded-xl border border-[#cbdcd6] bg-white px-3 text-sm font-medium text-[#173640] focus:outline-none focus:ring-2 focus:ring-[#117d72]';
const PANEL_STYLE = 'rounded-2xl border border-[#d6e1de] bg-white p-5 sm:p-6';
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
      <h3 className="text-sm font-medium text-[#536c72]">{tx(label)}</h3>
      <p className="my-2 font-mono text-3xl font-semibold tracking-tight text-[#102f3a]">
        {tx(value)}
      </p>
      <p className="text-sm leading-6 text-[#60757b]">{tx(detail)}</p>
    </div>
  );
}

function PerformanceCurve({
  data,
  snr,
  spacing,
  sensitivity,
}: {
  data: Fixed64Results;
  snr: number;
  spacing: number;
  sensitivity: boolean;
}) {
  const { tx } = useLanguage();
  const rows = RADII.map((radius) => {
    const values: Record<string, number | null> = { radius };
    RESULT_FAMILIES.forEach((family) => {
      const layout = selectRecordedLayout(data, family.id, radius, spacing);
      const value = sensitivity
        ? layout?.metrics.sensitivity_tail
        : atSnr(layout?.metrics.conditions ?? null, snr)?.field_relative;
      values[family.id] = value == null ? null : value * 100;
    });
    return values;
  });
  return (
    <section className={`${PANEL_STYLE} min-w-0`}>
      <h2 className="text-lg font-semibold">
        {tx(sensitivity ? '幅度保留率（最差10%）' : '区域大小与信号重建')}
      </h2>
      <p className="mb-4 mt-1 text-sm leading-6 text-[#60757b]">
        {tx(sensitivity
          ? '相对幅度保留率最低的10%皮层面积，按面积加权；不随噪声档位变化。'
          : `相对全头64点 · ${snr} dB · 最小电极间距 ${spacing} mm`)}
      </p>
      <figure
        className="h-[310px] w-full"
        aria-label={
          tx(sensitivity
            ? '敏感度随已计算半径变化，数值见下方配置表'
            : '信号重建保留率随已计算半径变化，数值见下方配置表')
        }
      >
        <ResponsiveContainer width="100%" height={310}>
          <LineChart
            data={rows}
            margin={{ top: 12, right: 16, left: 0, bottom: 5 }}
            accessibilityLayer
          >
            <CartesianGrid
              strokeDasharray="3 3"
              vertical={false}
              stroke="#e0e8e5"
            />
            <XAxis
              dataKey="radius"
              type="number"
              domain={[20, 50]}
              ticks={RADII}
              tick={{ fontSize: 14 }}
              tickFormatter={(v) => tx(`${v} mm`)}
            />
            <YAxis
              domain={[0, 'auto']}
              width={48}
              tick={{ fontSize: 14 }}
              tickFormatter={(v) => tx(`${v}%`)}
            />
            <Tooltip
              labelFormatter={(v) => tx(`半径上限 ${v} mm`)}
              formatter={(v) =>
                tx(typeof v === 'number' ? `${v.toFixed(2)}%` : '未计算')
              }
              contentStyle={{ borderRadius: 12, fontSize: 14 }}
            />
            <Legend wrapperStyle={{ fontSize: 14, paddingTop: 14 }} />
            <ReferenceLine
              y={100}
              stroke="#73868c"
              strokeDasharray="4 4"
              ifOverflow="extendDomain"
            />
            {tx(RESULT_FAMILIES.map((family) => (
              <Line
                key={family.id}
                type="linear"
                dataKey={family.id}
                name={tx(family.label)}
                stroke={family.color}
                strokeWidth={2.5}
                dot={{ r: 4 }}
                activeDot={{ r: 6 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            )))}
          </LineChart>
        </ResponsiveContainer>
      </figure>
      <p className="mt-3 text-sm leading-6 text-[#687c82]">
        {tx("虚线为全头基准的100%相对值。连线仅连接已计算点，不产生中间半径的估计。")}</p>
    </section>
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
    fetch('/data/fixed64_results.json', { signal: abort.signal })
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
    <main className="min-h-screen bg-[#f4f7f4] text-[#102a34]">
      <SiteHeader current="results" arPercent={ar} returnHref={here} />
      <div className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 sm:px-6 lg:px-8">
        <a className="inline-block text-sm font-semibold text-primary underline" href={'/?ar=' + ar}>{tx("← 返回当前已有结果")}</a>
        <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
          <div>
            <div className="mb-3 flex flex-wrap gap-2">
              <Badge className="bg-[#102f3a] text-white">
                {tx("已计算 · 固定64电极")}</Badge>
              <Badge
                variant="outline"
                className="border-[#deb968] bg-[#fff8e6] text-[#765814]"
              >
                {tx("早期单头模原型 · 未做跨头模验证")}</Badge>
            </div>
            <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
              {tx("历史原型：双区域初始布局")}</h1>
            <p className="mt-3 max-w-3xl text-base leading-7 text-[#536c72]">
              {tx("同样64个电极，集中到两个区域后，保留了多少全头电位场信息？切换已计算配置查看结果与实际点位。")}</p>
          </div>
          <a
            href={methodLink(here, ar, '#first-batch')}
            className="inline-flex shrink-0 items-center gap-2 text-sm font-semibold text-[#117d72]"
          >
            {tx("本批怎么算 ")}<ArrowRight className="size-4" />
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
              className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
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
                  className="rounded-xl border border-[#d6e1de] bg-white px-4 py-3"
                >
                  <p className="text-sm text-[#60757b]">{tx(label)}</p>
                  <p className="mt-1 text-base font-semibold">{tx(value)}</p>
                </div>
              )))}
            </section>

            <section
              className={`${PANEL_STYLE} space-y-4`}
              aria-label={tx("选择已计算配置")}
            >
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-[2fr_1fr_1fr_1.2fr]">
                <label className="space-y-2 text-sm font-semibold">
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
                <label className="space-y-2 text-sm font-semibold">
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
                <label className="space-y-2 text-sm font-semibold">
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
                <label className="space-y-2 text-sm font-semibold">
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
              <p className="text-sm leading-6 text-[#60757b]">
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
                <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_310px]">
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
                  <aside className={`${PANEL_STYLE} h-fit space-y-5`}>
                    <div>
                      <h2 className="text-lg font-semibold">
                        {tx("这64个点来自计算记录")}</h2>
                      <p className="mt-2 text-sm leading-6 text-[#60757b]">
                        {tx("位置取自本批FEM的MRI坐标，仅换算单位；触点外观沿法向抬高1.2 mm用于显示，计算使用原始坐标。基准为BioSemi64名称匹配的Ernie-SPM12全头模板。")}</p>
                    </div>
                    <dl className="space-y-3 text-sm">
                      <div className="flex justify-between gap-3">
                        <dt>{tx("配置编号")}</dt>
                        <dd className="font-mono">
                          {tx(selected.index + 1)} / {tx(data.configuration_count)}
                        </dd>
                      </div>
                      {tx(selected.region_areas_cm2.map((area, i) => (
                        <div className="flex justify-between gap-3" key={i}>
                          <dt>{tx("区域 ")}{tx(i + 1)} {tx(" · 候选面积")}</dt>
                          <dd className="font-mono">{tx(area.toFixed(2))} cm²</dd>
                        </div>
                      )))}
                    </dl>
                    <p className="text-sm leading-6 text-[#60757b]">
                      {tx("候选贴片面积是离散近似，不等于电极凸包面积。耳后邻近和耳周均为近似坐标掩膜，尚未审核为严格无毛区域。")}</p>
                    <div className="rounded-xl border border-[#e5c882] bg-[#fff8e8] p-4 text-sm leading-6 text-[#765814]">
                      <Info className="mb-2 size-5" />
                      {tx("本历史批次采用预设位置进行性能评价；群体阈值与最小面积需另行验证。")}</div>
                    <a
                      href="https://github.com/simnibs/example-dataset/releases/tag/v4.1"
                      className="block text-sm text-[#117d72] underline"
                    >
                      {tx("头模：SimNIBS Ernie · CC BY-NC 4.0")}</a>
                  </aside>
                </section>
              </>
            ) : (
              <section
                className="rounded-2xl border border-[#e5c882] bg-[#fff8e8] p-6"
                aria-live="polite"
              >
                <h2 className="text-lg font-semibold text-[#765814]">
                  {tx("本历史批次未找到该配置的完整布局")}</h2>
                <p className="mt-2 text-base leading-7 text-[#806a37]">
                  {tx("20 mm半径、6 mm点距下，本批贪心构造未找到完整64点布局，该条件的几何可行性仍待判定。可选择30、40、50 mm，或4 mm点距。")}</p>
              </section>
            ))}

            <div className="grid gap-5 xl:grid-cols-2">
              <PerformanceCurve
                data={data}
                snr={snr}
                spacing={spacing}
                sensitivity={false}
              />
              <PerformanceCurve
                data={data}
                snr={snr}
                spacing={spacing}
                sensitivity
              />
            </div>

            <section className={PANEL_STYLE}>
              <h2 className="flex items-center gap-2 text-xl font-semibold">
                <ChartNoAxesCombined className="size-5 text-[#117d72]" />
                {tx("已计算配置对比 · ")}{tx(snr)} dB / {tx(spacing)} {tx(" mm点距")}</h2>
              <p className="mt-2 text-sm leading-6 text-[#60757b]">
                {tx("每格为“信号重建相对保留率 / 幅度保留率（最差10%）”；点击数值可切换3D点位。全头64点的两项相对值均为100%，作为本批相对比较基准。")}</p>
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[660px] text-left text-sm">
                  <caption className="sr-only">
                    {tx("区域半径与各组合的已计算物理保留率")}</caption>
                  <thead>
                    <tr className="border-b border-[#d6e1de]">
                      <th scope="col" className="p-3 font-semibold">
                        {tx("半径上限")}</th>
                      {tx(RESULT_FAMILIES.map((f) => (
                        <th
                          scope="col"
                          className="p-3 font-semibold"
                          key={f.id}
                        >
                          {tx(f.label)}
                        </th>
                      )))}
                    </tr>
                  </thead>
                  <tbody>
                    {tx(RADII.map((r) => (
                      <tr
                        key={r}
                        className="border-b border-[#e5ece9] last:border-0"
                      >
                        <th scope="row" className="p-3 font-medium">
                          {tx(r)} mm
                        </th>
                        {tx(RESULT_FAMILIES.map((f) => {
                          const row = selectRecordedLayout(
                            data,
                            f.id,
                            r,
                            spacing,
                          );
                          const score = atSnr(
                            row?.metrics.conditions ?? null,
                            snr,
                          );
                          return (
                            <td key={f.id} className="p-2">
                              {tx(row ? (
                                <button
                                  type="button"
                                  aria-label={tx(`${f.label}，半径${r}mm，信号重建${retentionPercent(score?.field_relative)}，敏感度${retentionPercent(row.metrics.sensitivity_tail)}`)}
                                  onClick={() => {
                                    setFamily(f.id);
                                    setRadius(r);
                                  }}
                                  className={`rounded-lg px-2 py-3 text-left font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#117d72] ${family === f.id && radius === r ? 'bg-[#e3f3ed] font-semibold text-[#0c6d62]' : 'hover:bg-[#f1f7f4]'}`}
                                >
                                  {tx(retentionPercent(score?.field_relative))} /{tx(' ')}
                                  {tx(retentionPercent(
                                    row.metrics.sensitivity_tail,
                                  ))}
                                </button>
                              ) : (
                                <span className="px-2 text-[#71858b]">
                                  {tx("未生成")}</span>
                              ))}
                            </td>
                          );
                        }))}
                      </tr>
                    )))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className={PANEL_STYLE}>
              <h2 className="text-xl font-semibold">
                {tx("定位诊断子实验 · 固定30 mm / 6 mm · ")}{tx(snr)} dB
              </h2>
              <p className="mt-2 max-w-4xl text-sm leading-6 text-[#60757b]">
                {tx("这四个布局在计算性能前选定，与上方半径和点距选择无关。每项为256个源×16次噪声，共4,096次模拟试验。生成源不在反演字典上，但使用同一头模和导电率，仍存在同模型反演偏差。")}</p>
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[560px] text-left text-sm">
                  <caption className="sr-only">
                    {tx("固定原型定位误差，单位毫米")}</caption>
                  <thead>
                    <tr className="border-b border-[#d6e1de]">
                      <th scope="col" className="p-3">
                        {tx("布局")}</th>
                      <th scope="col" className="p-3">
                        {tx("中位误差")}</th>
                      <th scope="col" className="p-3">
                        {tx("P90误差")}</th>
                      <th scope="col" className="p-3">
                        {tx("P95误差")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tx([
                      {
                        name: '全头64点基准',
                        values: data.reference.localization,
                      },
                      ...RESULT_FAMILIES.map((f) => ({
                        name: f.label,
                        values:
                          selectRecordedLayout(data, f.id, 30, 6)
                            ?.localization ?? null,
                      })),
                    ].map((row) => {
                      const loc = atSnr(row.values, snr);
                      return (
                        <tr
                          key={row.name}
                          className="border-b border-[#e5ece9] last:border-0"
                        >
                          <th scope="row" className="p-3 font-medium">
                            {row.name}
                          </th>
                          <td className="p-3 font-mono">
                            {tx(mm(loc?.median_mm))}
                          </td>
                          <td className="p-3 font-mono">{tx(mm(loc?.p90_mm))}</td>
                          <td className="p-3 font-mono">{tx(mm(loc?.p95_mm))}</td>
                        </tr>
                      );
                    }))}
                  </tbody>
                </table>
              </div>
              <p className="mt-4 rounded-xl bg-[#fff8e8] p-4 text-sm leading-6 text-[#765814]">
                {tx("独立无噪声检查中，全头基准仍有10.73 mm中位误差、20.57 mm的P90误差。这些误差反映固定法向离散字典的匹配限制；人体定位精度与群体阈值需独立验证。")}</p>
            </section>

            <section className={`${PANEL_STYLE} space-y-4`}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-xl font-semibold">{tx("数据来源与适用范围")}</h2>
                <a
                  href="/data/fixed64_results.json"
                  download="fixed64_results.json"
                  className="inline-flex items-center gap-2 rounded-xl border border-[#cbdcd6] px-4 py-2 text-sm font-semibold text-[#117d72]"
                >
                  <Download className="size-4" />
                  {tx("下载结果与64点坐标")}</a>
              </div>
              <ul className="list-disc space-y-2 pl-5 text-sm leading-6 text-[#60757b]">
                <li>
                  {tx("结果范围为一个Ernie头模与本批双区域组合，最高值取自已计算布局。1/3/4/6区域见后续实验，跨头模置信区间尚待评价。")}</li>
                <li>
                  {tx("皮层域来自注册图谱。108 / 4,352个源采用最近灰质恢复，最大距离1.55 mm；四个曲面点与血液组织分割不一致，保留了明确的灰质近似模型。")}</li>
                <li>
                  {tx("源先验按皮层面积加权，信号重建与尾部幅度分别评价。任务分类属于后续验证。")}</li>
                <li>
                  {tx("本页筛选并展示已保存的早期原型。新布局可在布局设计页计算并判定AR，跨头模验证另列阶段。")}</li>
              </ul>
              <details className="rounded-xl border border-[#dce6e1] p-4 text-sm">
                <summary className="cursor-pointer font-semibold">
                  {tx("查看可追溯标识")}</summary>
                <dl className="mt-4 space-y-3 break-all font-mono text-xs leading-6 text-[#60757b]">
                  <div>
                    <dt>Run</dt>
                    <dd>{tx(data.run_id)}</dd>
                  </div>
                  <div>
                    <dt>{tx("原始报告 SHA-256")}</dt>
                    <dd>{tx(data.provenance.report_sha256)}</dd>
                  </div>
                  <div>
                    <dt>{tx("前向矩阵 SHA-256")}</dt>
                    <dd>{tx(data.provenance.forward_sha256)}</dd>
                  </div>
                  <div>
                    <dt>{tx("指标数据 SHA-256")}</dt>
                    <dd>{tx(data.provenance.metrics_sha256)}</dd>
                  </div>
                </dl>
              </details>
            </section>
          </>
        ))}
      </div>
    </main>
  );
}
