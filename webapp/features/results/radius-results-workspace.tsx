'use client';
import { useLanguage } from '@/components/language-provider';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { ArrowRight, Download, Info, RefreshCcw } from 'lucide-react';
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
import { retentionPercent as pct } from '@/lib/fixed64-results';
import {
  allocationFor,
  arDecision,
  bestVariant,
  checkSingleHeadResults,
  CRITERIA,
  familyLabel,
  metricAt,
  REGION_COLORS,
  REGION_COUNTS,
  type Criterion,
  type SingleHeadResults,
} from '@/lib/single-head-results';

const Head = lazy(() =>
  import('@/components/cluster-head-viewer').then((m) => ({
    default: m.ClusterHeadViewer,
  })),
);
const panel = 'rounded-2xl border border-[#d6e1de] bg-white p-5 sm:p-6';
const select =
  'mt-2 h-11 w-full rounded-xl border border-[#cbdcd6] bg-white px-3 text-sm text-[#173640] focus:ring-2 focus:ring-[#117d72]';
const mm = (value?: number | null) =>
  value == null ? '指标无法计算' : `${value.toFixed(2)} mm`;

export default function ResultsPage() {
  const { tx } = useLanguage();
  const [data, setData] = useState<SingleHeadResults | null>(null);
  const [error, setError] = useState(''),
    [retry, setRetry] = useState(0);
  const [regions, setRegions] = useState(2),
    [family, setFamily] = useState('r2_whole_scalp_free');
  const [radius, setRadius] = useState(50),
    [spacing, setSpacing] = useState(4),
    [snr, setSnr] = useState(20);
  const [ar, setAr] = useState(90),
    [criterion, setCriterion] = useState<Criterion>('field_relative');
  const [objective, setObjective] = useState('field_20db'),
    [curveMode, setCurveMode] = useState('whole_scalp_free');
  const [ready, setReady] = useState(false);
  const here = '/results?' + new URLSearchParams({ ar: String(ar), r: String(regions), radius: String(radius), spacing: String(spacing), snr: String(snr), family, metric: criterion, objective, domain: curveMode }).toString();
  useEffect(() => { if (ready) window.history.replaceState(null, '', here); }, [ready, here]);
  useEffect(() => {
    const restore = () => {
      const q = new URLSearchParams(window.location.search);
      setAr(parseAR(q.get('ar')));
      const r = Number(q.get('r')), a = Number(q.get('radius')), sp = Number(q.get('spacing')), db = Number(q.get('snr'));
      setRegions([1, 2, 3, 4, 6].includes(r) ? r : 2);
      setRadius([20, 30, 40, 50, 65, 80].includes(a) ? a : 50);
      setSpacing(sp === 6 ? 6 : 4); setSnr(q.has('snr') && [0, 10, 20].includes(db) ? db : 20);
      setFamily(q.get('family') || 'r2_whole_scalp_free');
      setCriterion(CRITERIA.find((c) => c.id === q.get('metric'))?.id ?? 'field_relative');
      setObjective(q.get('objective') === 'min_field_sensitivity_20db' ? 'min_field_sensitivity_20db' : 'field_20db');
      setCurveMode(q.get('domain') === 'low_hair_free' ? 'low_hair_free' : 'whole_scalp_free'); setReady(true);
    };
    restore(); window.addEventListener('popstate', restore); return () => window.removeEventListener('popstate', restore);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    fetch('/data/single_head_optimization.json', { signal: controller.signal })
      .then((r) => {
        if (!r.ok)
          throw new Error(`结果文件尚未就绪或无法读取（HTTP ${r.status}）`);
        return r.json();
      })
      .then((value) => {
        setData(checkSingleHeadResults(value));
        setError('');
      })
      .catch((reason: Error) => {
        if (!controller.signal.aborted) setError(reason.message);
      });
    return () => controller.abort();
  }, [retry]);
  const available =
    data?.conditions.filter(
      (c) =>
        c.family_id === family && c.spacing_mm === spacing && c.variants.length,
    ) ?? [];
  const selected =
    available.find((c) => c.radius_mm === radius) ?? available.at(-1);
  const variant =
    selected?.variants.find((v) => v.objective === objective) ??
    selected?.variants[0];
  const metrics = metricAt(variant, snr),
    baseline = data?.baseline.conditions.find((c) => c.snr_db === snr);
  const decision = arDecision(metrics, ar / 100);
  const recorded =
    variant && data
      ? {
          id: variant.id,
          xyzMm: variant.xyz_mm,
          regionIndices: variant.region_indices,
          referenceXyzMm: data.baseline.xyz_mm,
        }
      : undefined;
  const curve = useMemo(
    () =>
      data?.config.radius_caps_mm.map((a) => {
        const row: Record<string, number | null> = { radius: a };
        for (const r of REGION_COUNTS) {
          const c = data.conditions.find(
            (c) =>
              c.family_id === `r${r}_${curveMode}` &&
              c.radius_mm === a &&
              c.spacing_mm === spacing,
          );
          const m = metricAt(bestVariant(c, snr, criterion), snr);
          row[`r${r}`] = m?.[criterion] == null ? null : m[criterion]! * 100;
        }
        return row;
      }) ?? [],
    [data, curveMode, spacing, snr, criterion],
  );
  const passRows =
    data?.conditions
      .filter((c) => c.spacing_mm === spacing && c.mode === curveMode)
      .flatMap((c) =>
        c.variants
          .filter((v) => arDecision(metricAt(v, snr), ar / 100) === 'pass')
          .map((v) => ({ c, v })),
      )
      .sort((a, b) => a.c.R - b.c.R || a.c.radius_mm - b.c.radius_mm) ?? [];
  const arValues =
    data?.conditions
      .filter((c) => c.spacing_mm === spacing && c.mode === curveMode)
      .flatMap((c) =>
        c.variants.map((v) => metricAt(v, snr)?.conditional_global),
      )
      .filter((v): v is number => v != null && Number.isFinite(v)) ?? [];
  const highestFoundAR = arValues.length ? Math.max(...arValues) : null;
  const scored = data?.conditions.filter((c) => c.variants.length).length ?? 0;
  const unique = data
    ? new Set(data.conditions.flatMap((c) => c.variants.map((v) => v.id))).size
    : 0;
  function changeRegions(r: number) {
    setRegions(r);
    setFamily(`r${r}_${curveMode}`);
  }

  return (
    <main className="min-h-screen bg-[#f4f7f4] text-[#102a34]">
      <SiteHeader current="results" arPercent={ar} returnHref={here} />
      <div className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 sm:px-6 lg:px-8">
        <a className="inline-block text-sm font-semibold text-primary underline" href={'/?ar=' + ar}>{tx("← 返回当前已有结果")}</a>
        <header className="flex flex-wrap items-end justify-between gap-5">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-[.16em] text-[#117d72]">
              {tx("历史批次 · 固定64电极")}</p>
            <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
              {tx("历史半径实验 · 原始比较")}</h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-[#536c72]">
              {tx("本页保留早期半径实验，允许区域相交，不等同于当前严格分离区域比较。原始布局、指标和曲线保留，只读查看。")}</p>
          </div>
          <a
            className="inline-flex items-center gap-2 rounded-xl border border-[#cbdcd6] bg-white px-4 py-3 text-sm font-medium"
            href="/data/single_head_optimization.json"
            download
          >
            <Download className="size-4" />
            {tx("下载实验数据")}</a>
        </header>
        {tx(!data && (
          <section className={panel} aria-live="polite">
            <h2 className="font-semibold">
              {tx(error ? '完整实验记录未载入' : '读取并校验实验记录')}
            </h2>
            <p className="my-3 text-sm text-[#60757b]">
              {tx(error ||
                '正在读取单头模实验的204项状态记录及布局坐标。')}
            </p>
            <button
              className="inline-flex items-center gap-2 text-sm text-[#117d72]"
              onClick={() => setRetry((v) => v + 1)}
            >
              <RefreshCcw className="size-4" />
              {tx("重新读取")}</button>
          </section>
        ))}
        {tx(data && (
          <>
            <section
              className="grid gap-3 sm:grid-cols-4"
              aria-label={tx("实验完成情况")}
            >
              {tx([
                ['条件检查', '204 / 204', '每项有明确的终态记录'],
                [
                  '获得完整布局',
                  `${scored}`,
                  `${204 - scored}项在限定预算内未构造成功`,
                ],
                ['不同评分布局', `${unique}`, '同一64点集合只评价一次'],
                ['本历史批次头模', '1', '跨头模验证：另列阶段，未开始'],
              ].map(([label, value, detail]) => (
                <div className={panel} key={label}>
                  <p className="text-sm text-[#60757b]">{tx(label)}</p>
                  <p className="my-2 font-mono text-3xl font-semibold">
                    {tx(value)}
                  </p>
                  <p className="text-xs leading-5 text-[#60757b]">{tx(detail)}</p>
                </div>
              )))}
            </section>
            <aside className="flex gap-3 rounded-xl border border-[#dcc998] bg-[#fff9e9] px-5 py-4 text-sm leading-6 text-[#6d5829]">
              <Info className="mt-1 size-4 shrink-0" />
              <p>
                {tx("百分比为相对全头64点的模型内指标。搜索由信号重建和敏感度引导，定位在最终布局上统一评估。AR用于当前头模与当前SNR的阈值筛选。")}</p>
            </aside>
            <section className="grid items-start gap-6 xl:grid-cols-[330px_minmax(0,1fr)]">
              <div className={`${panel} space-y-5`}>
                <div>
                  <h2 className="text-xl font-semibold">{tx("所选布局条件（历史记录）")}</h2>
                  <p className="mt-2 text-sm leading-6 text-[#60757b]">
                    {tx("只显示已生成完整64点的尺寸。未构造成功的条件单独列在下方。")}</p>
                </div>
                <label className="block text-sm font-medium">
                  {tx("区域数量")}<select
                    className={select}
                    value={regions}
                    onChange={(e) => changeRegions(Number(e.target.value))}
                  >
                    {tx(REGION_COUNTS.map((r) => (
                      <option key={r} value={r}>
                        {tx(r)}{tx("区 · ")}{tx(allocationFor(r).join(' + '))}{tx("点")}</option>
                    )))}
                  </select>
                </label>
                <label className="block text-sm font-medium">
                  {tx("位置约束")}<select
                    className={select}
                    value={family}
                    onChange={(e) => setFamily(e.target.value)}
                  >
                    {tx(data.families
                      .filter((f) => f.R === regions)
                      .map((f) => (
                        <option key={f.id} value={f.id}>
                          {tx(familyLabel(f.id))}
                        </option>
                      )))}
                  </select>
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <label className="block text-sm font-medium">
                    {tx("最小电极间距")}<select
                      className={select}
                      value={spacing}
                      onChange={(e) => setSpacing(Number(e.target.value))}
                    >
                      {tx(data.config.minimum_chord_spacings_mm.map((d) => (
                        <option key={d} value={d}>
                          {tx(d)} mm
                        </option>
                      )))}
                    </select>
                  </label>
                  <label className="block text-sm font-medium">
                    {tx("半径上限")}<select
                      className={select}
                      value={selected?.radius_mm ?? ''}
                      onChange={(e) => setRadius(Number(e.target.value))}
                      disabled={!available.length}
                    >
                      {tx(!available.length && (
                        <option value="">{tx("无评分布局")}</option>
                      ))}
                      {tx(available.map((c) => (
                        <option key={c.id} value={c.radius_mm}>
                          {tx(c.radius_mm)} mm
                        </option>
                      )))}
                    </select>
                  </label>
                </div>
                <label className="block text-sm font-medium">
                  {tx("优化分支")}<select
                    className={select}
                    value={objective}
                    onChange={(e) => setObjective(e.target.value)}
                  >
                    <option value="field_20db">{tx("优先信号重建")}</option>
                    <option value="min_field_sensitivity_20db">
                      {tx("提高信号重建与敏感度的较低项")}</option>
                  </select>
                </label>
                <label className="block text-sm font-medium">
                  {tx("统一噪声档位")}<select
                    className={select}
                    value={snr}
                    onChange={(e) => setSnr(Number(e.target.value))}
                  >
                    {tx([0, 10, 20].map((s) => (
                      <option key={s} value={s}>
                        {tx("全头基准 SNR ")}{tx(s)} dB
                      </option>
                    )))}
                  </select>
                </label>
                <p className="border-t border-[#e0e8e5] pt-4 text-xs leading-5 text-[#60757b]">
                  {tx("点距为欧氏弦距；半径为网格边路径上限。少毛发候选区为坐标近似范围，人体可佩戴范围尚待审核。")}</p>
              </div>
              <div className="min-w-0 space-y-4">
                {tx(variant && selected && recorded ? (
                  <>
                    <Suspense
                      fallback={
                        <div className={`${panel} h-[500px]`}>{tx("载入3D头模…")}</div>
                      }
                    >
                      <Head
                        regionCount={selected.R}
                        allocation={allocationFor(selected.R)}
                        domainMode="whole_surface"
                        radiusCm={selected.radius_mm / 10}
                        recordedLayout={recorded}
                      />
                    </Suspense>
                    <div className={`${panel} text-sm leading-6`}>
                      <p className="font-semibold">
                        {tx(familyLabel(selected.family_id))} · {tx(selected.R)}{tx("区 ·")}{tx(' ')}
                        {tx(variant.accepted_moves)}{tx("次接受的优化移动")}</p>
                      <p className="mt-2 text-[#60757b]">
                        {tx("20 dB信号重建：")}{tx(pct(variant.initial.field20))} →{tx(' ')}
                        {tx(pct(metricAt(variant, 20)?.field_relative))}{tx("；敏感度：")}{tx(pct(variant.initial.sensitivity_tail))} →{tx(' ')}
                        {tx(pct(metricAt(variant, 20)?.sensitivity_tail))}。
                      </p>
                      <p className="mt-1 text-[#60757b]">
                        {tx("允许贴片面积约")}{tx(' ')}
                        {tx(variant.region_areas_cm2
                          .map((a) => a.toFixed(1))
                          .join(' / '))}{tx(' ')}
                        {tx("cm²。面积由区域内网格顶点分摊近似计算。")}</p>
                      <p className="mt-2 font-mono text-xs text-[#7a898d]">
                        layout {tx(variant.id)}
                      </p>
                    </div>
                  </>
                ) : (
                  <div className={panel}>
                    {tx("本批搜索在此区域组合和点距下未找到完整布局，整体几何可行性仍待判定。")}</div>
                ))}
              </div>
            </section>
            <section className={panel}>
              <h2 className="text-xl font-semibold">
                {tx("与全头64点放在同一个尺度上比较")}</h2>
              <div className="mt-5 overflow-x-auto">
                <table className="w-full min-w-[650px] text-left text-sm">
                  <thead>
                    <tr className="border-b border-[#d6e1de] text-[#60757b]">
                      <th className="py-3">{tx("指标")}</th>
                      <th>{tx("所选布局")}</th>
                      <th>{tx("全头64点")}</th>
                      <th>{tx("相对保留率")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b border-[#edf1ef]">
                      <th className="py-4 font-medium">{tx("干净全头场能量解释率")}</th>
                      <td>{tx(pct(metrics?.field_absolute))}</td>
                      <td>{tx(pct(baseline?.field_absolute))}</td>
                      <td>{tx(pct(metrics?.field_relative))}</td>
                    </tr>
                    <tr className="border-b border-[#edf1ef]">
                      <th className="py-4 font-medium">
                        {tx("相对幅度比最低10%源面积的平均值")}</th>
                      <td>{tx("以全头归一化")}</td>
                      <td>100%</td>
                      <td>{tx(pct(metrics?.sensitivity_tail))}</td>
                    </tr>
                    <tr className="border-b border-[#edf1ef]">
                      <th className="py-4 font-medium">
                        {tx("下尾定位评分 U（0—1）")}</th>
                      <td>
                        {tx(metrics?.localization_utility?.toFixed(4) ?? '指标无法计算')}
                      </td>
                      <td>{tx(baseline?.loc_util?.toFixed(4) ?? '指标无法计算')}</td>
                      <td>{tx(pct(metrics?.localization_relative))}</td>
                    </tr>
                    <tr>
                      <th className="py-4 font-medium">
                        {tx("定位误差：中位数 / P90 / P95")}</th>
                      <td>
                        {tx(mm(metrics?.median_mm))} / {tx(mm(metrics?.p90_mm))} /{tx(' ')}
                        {tx(mm(metrics?.p95_mm))}
                      </td>
                      <td>
                        {tx(mm(baseline?.median_mm))} / {tx(mm(baseline?.p90_mm))} /{tx(' ')}
                        {tx(mm(baseline?.p95_mm))}
                      </td>
                      <td>{tx("绝对误差，越小越好")}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="mt-4 text-xs leading-6 text-[#60757b]">
                {tx("U：每次试验取 max(0, 1 − 误差/50 mm)，先对同一源的16次噪声取均值，再取最低10%源面积的加权均值。基准U为零时比值和三项最低相对评分G未定义。各指标分别报告。")}</p>
            </section>
            <section className={panel}>
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div>
                  <h2 className="text-xl font-semibold">
                    {tx("曲线比较条件（独立于上方布局选择）")}</h2>
                  <p className="mt-2 text-sm text-[#60757b]">
                    {tx("各点取两个优化分支中当前指标的较高值，对应布局可随半径和指标变化；曲线范围为已计算布局。 比较固定每区半径；区域数量变化时，总贴片面积也随之变化。")}</p>
                </div>
                <div className="flex flex-wrap gap-3">
                  <label className="text-sm text-[#60757b]">
                    {tx("比较范围")}<select
                      className={select}
                      value={curveMode}
                      onChange={(e) => setCurveMode(e.target.value)}
                    >
                      <option value="whole_scalp_free">{tx("全头自由中心")}</option>
                      <option value="low_hair_free">{tx("低毛发近似约束")}</option>
                    </select>
                  </label>
                  <label className="text-sm text-[#60757b]">
                    {tx("曲线指标")}<select
                      className={select}
                      value={criterion}
                      onChange={(e) =>
                        setCriterion(e.target.value as Criterion)
                      }
                    >
                      {tx(CRITERIA.map((c) => (
                        <option key={c.id} value={c.id}>
                          {tx(c.label)}
                        </option>
                      )))}
                    </select>
                  </label>
                </div>
              </div>
              <figure
                className="mt-6 h-[360px]"
                aria-label={tx("五种区域数量的半径与性能比较")}
              >
                <ResponsiveContainer width="100%" height={360}>
                  <LineChart
                    data={curve}
                    margin={{ left: 0, right: 20, top: 15, bottom: 10 }}
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
                      domain={[20, 80]}
                      ticks={data.config.radius_caps_mm}
                      tickFormatter={(v) => tx(`${v} mm`)}
                    />
                    <YAxis
                      width={55}
                      domain={[0, 'auto']}
                      tickFormatter={(v) => tx(`${v}%`)}
                    />
                    <Tooltip
                      formatter={(v) =>
                        tx(typeof v === 'number' ? `${v.toFixed(2)}%` : '指标无法计算')
                      }
                      labelFormatter={(v) => tx(`半径上限 ${v} mm`)}
                    />
                    <Legend />
                    <ReferenceLine
                      y={100}
                      stroke="#718589"
                      strokeDasharray="4 4"
                      ifOverflow="extendDomain"
                    />
                    {tx(criterion === 'conditional_global' && (
                      <ReferenceLine
                        y={ar}
                        stroke="#b86b29"
                        strokeDasharray="6 4"
                        ifOverflow="extendDomain"
                        label={tx(`AR ${ar}%`)}
                      />
                    ))}
                    {tx(REGION_COUNTS.map((r, i) => (
                      <Line
                        key={r}
                        dataKey={`r${r}`}
                        name={tx(`${r}个区域`)}
                        stroke={REGION_COLORS[i]}
                        strokeWidth={2.5}
                        type="linear"
                        dot={{ r: 4 }}
                        connectNulls={false}
                        isAnimationActive={false}
                      />
                    )))}
                  </LineChart>
                </ResponsiveContainer>
              </figure>
              <p className="mt-3 text-xs leading-6 text-[#60757b]">
                {tx("当前统一档位：")}{tx(snr)} {tx(" dB、点距")}{tx(spacing)}{tx(' ')}
                {tx("mm。空缺为未获得布局或指标未定义，不画成0%。连线仅连接计算点，不估计中间半径。")}</p>
            </section>
            <section className="grid gap-6 lg:grid-cols-2">
              <div className={panel}>
                <h2 className="text-xl font-semibold">
                  {tx("接受阈值 AR（本历史批次）")}</h2>
                <label
                  className="mt-5 flex items-center justify-between text-sm"
                  htmlFor="conditional-ar"
                >
                  {tx("要求三项相对保留率均达到")}<span className="font-mono text-2xl font-semibold">
                    {tx(ar)}%
                  </span>
                </label>
                <input
                  id="conditional-ar"
                  className="my-5 w-full accent-[#117d72]"
                  type="range"
                  min="10"
                  max="100"
                  step="1"
                  value={ar}
                  onChange={(e) => setAr(Number(e.target.value))}
                />
                <p className="rounded-xl bg-[#f0f6f3] p-4 text-sm leading-6">
                  {tx("所选布局：")}{tx(decision === 'pass'
                    ? '通过此模型条件阈值'
                    : decision === 'fail'
                      ? '未通过此模型条件阈值'
                      : '指标无法计算，无法判断是否达到AR')}
                  {tx("。三项最低相对评分 ")}{tx(pct(metrics?.conditional_global))}。
                </p>
                <p className="mt-4 text-sm leading-6 text-[#60757b]">
                  {tx("在曲线所选范围、")}{tx(spacing)} {tx(" mm点距及")}{tx(snr)} {tx(" dB下，")}{tx(passRows.length
                    ? `找到${passRows.length}个通过的配置／分支；按区域数优先、再按半径排序，首个为${passRows[0].c.R}区、半径上限${passRows[0].c.radius_mm} mm。`
                    : '本批已评分布局均未达到当前AR；其他布局仍待搜索。')}
                  {tx("此范围已找到的最高三项最低相对评分 G为")}{tx(' ')}
                  {tx(highestFoundAR == null ? '指标无法计算' : pct(highestFoundAR))}。
                </p>
                <p className="mt-3 text-xs leading-5 text-[#60757b]">
                  {tx("筛选范围为本批有限搜索得到的布局，阈值适用于当前模型条件。总电极数固定为64，跨人群阈值另行验证。")}</p>
                <div className="mt-5 overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-[#d6e1de] text-[#60757b]">
                        <th className="py-3">{tx("区域数")}</th>
                        <th>{tx("达到AR的最小已测半径")}</th>
                        <th>{tx("已找到最高 G")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tx(REGION_COUNTS.map((r) => {
                        const first = passRows.find((row) => row.c.R === r);
                        const values = data.conditions
                          .filter(
                            (c) =>
                              c.R === r &&
                              c.mode === curveMode &&
                              c.spacing_mm === spacing,
                          )
                          .flatMap((c) =>
                            c.variants.map(
                              (v) => metricAt(v, snr)?.conditional_global,
                            ),
                          )
                          .filter(
                            (v): v is number => v != null && Number.isFinite(v),
                          );
                        return (
                          <tr className="border-b border-[#edf1ef]" key={r}>
                            <th className="py-3 font-medium">{tx(r)}{tx("区")}</th>
                            <td>
                              {tx(first ? (
                                <button
                                  className="font-medium text-[#117d72] underline underline-offset-4"
                                  onClick={() => {
                                    setRegions(r);
                                    setFamily(first.c.family_id);
                                    setRadius(first.c.radius_mm);
                                    setObjective(first.v.objective);
                                  }}
                                >
                                  {tx(first.c.radius_mm)} {tx(" mm · 查看布局")}</button>
                              ) : (
                                '未找到'
                              ))}
                            </td>
                            <td>
                              {tx(values.length
                                ? pct(Math.max(...values))
                                : '指标无法计算')}
                            </td>
                          </tr>
                        );
                      }))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className={panel}>
                <h2 className="text-xl font-semibold">{tx("实验阶段与适用范围")}</h2>
                <ol className="mt-5 space-y-4 text-sm leading-6">
                  <li>
                    <span className="font-semibold text-[#117d72]">
                      {tx("历史阶段一 · 本批半径实验结果")}</span>
                    <br />
                    {tx("单Ernie FEM；5,387候选点；1/2/3/4/6区；204条件；有限中心与坐标交换搜索；统一场、敏感度及离散定位评价。")}</li>
                  <li>
                    <span className="font-semibold">
                      {tx("阶段二 · 独立头模验证，未开始")}</span>
                    <br />
                    {tx("冻结本阶段入围布局，再检验不同解剖、导电率、源分布与噪声。本历史批次完成单头模评价，独立头模验证另列阶段。")}</li>
                  <li>
                    <span className="font-semibold">{tx("后续评价范围")}</span>
                    <br />
                    {tx("连续位置最优性、最小面积、真实毛发范围、人体定位误差及MI/P300分类表现均尚待评价。")}</li>
                </ol>
                <a
                  className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-[#117d72]"
                  href={methodLink(here, ar, '#single-head-optimization')}
                >
                  {tx("查看计算定义与限制")}<ArrowRight className="size-4" />
                </a>
              </div>
            </section>
            <section className={panel}>
              <h2 className="text-xl font-semibold">
                {tx("全量检查：每种区域数是否完成比较")}</h2>
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[560px] text-left text-sm">
                  <thead>
                    <tr className="border-b text-[#60757b]">
                      <th className="py-3">{tx("区域数 / 点数分配")}</th>
                      <th>{tx("已检查")}</th>
                      <th>{tx("获得评分布局")}</th>
                      <th>{tx("预算内未构造成功")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tx(REGION_COUNTS.map((r) => {
                      const all = data.conditions.filter((c) => c.R === r);
                      const ok = all.filter((c) => c.variants.length).length;
                      return (
                        <tr key={r} className="border-b border-[#edf1ef]">
                          <th className="py-4 font-medium">
                            {tx(r)}{tx("区 · ")}{tx(allocationFor(r).join('+'))}
                          </th>
                          <td>{tx(all.length)}</td>
                          <td>{tx(ok)}</td>
                          <td>{tx(all.length - ok)}</td>
                        </tr>
                      );
                    }))}
                  </tbody>
                </table>
              </div>
              <details className="mt-5">
                <summary className="cursor-pointer text-sm font-medium text-[#536c72]">
                  {tx("查看本轮搜索未获得完整布局的条件")}</summary>
                <ul className="mt-3 max-h-72 space-y-2 overflow-auto text-xs leading-5 text-[#60757b]">
                  {tx(data.conditions
                    .filter((c) => !c.variants.length)
                    .map((c) => (
                      <li key={c.id}>
                        {tx(c.R)}{tx("区 · ")}{tx(familyLabel(c.family_id))} {tx(" · 半径")}{tx(c.radius_mm)}{tx(' ')}
                        {tx("mm · 点距")}{tx(c.spacing_mm)} mm：
                        {tx(c.failure_reason ||
                          '预算内未找到满足全部约束的64点布局')}
                        {tx("；各区域最大达到点数")}{tx(' ')}
                        {tx(c.max_achieved_counts?.join(' / ') ?? '无可用中心')}
                        {tx("（各值可对应不同布局）。")}</li>
                    )))}
                </ul>
              </details>
            </section>
            <footer className="flex flex-wrap justify-between gap-4 py-4 text-xs leading-6 text-[#718289]">
              <div>
                {tx("运行 ")}{tx(data.provenance.run_id)}
                <br />
                {tx("数据SHA256 ")}{tx(data.provenance.report_sha256)}
              </div>
              <a className="text-[#117d72] underline" href={'/pilot-results?ar=' + ar}>
                {tx("保留的首批双区域原型结果")}</a>
            </footer>
          </>
        ))}
      </div>
    </main>
  );
}
