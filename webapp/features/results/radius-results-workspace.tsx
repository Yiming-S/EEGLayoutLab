'use client';
import { useLanguage } from '@/components/language-provider';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, Download, RefreshCcw } from 'lucide-react';
import { SiteHeader } from '@/components/site-header';
import { buttonVariants } from '@/components/ui/button';
import { parseAR, methodLink } from '@/lib/lab-workflow';
import { retentionPercent as pct } from '@/lib/fixed64-results';
import { apiFetch } from '@/client/task-client';
import {
  arDecision,
  bestVariant,
  checkSingleHeadResults,
  CRITERIA,
  metricAt,
  REGION_COUNTS,
  type Criterion,
  type SingleHeadResults,
} from '@/lib/single-head-results';
import { RadiusConditionInspector } from './radius-condition-inspector';
import {
  RadiusBatchAuditSection,
  RadiusCurvesSection,
} from './radius-curves-and-audit-section';

const panel = 'lab-panel';
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
    apiFetch('/data/single_head_optimization.json', { signal: controller.signal })
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
  const available = data?.conditions.filter((c) => c.family_id === family && c.spacing_mm === spacing && c.variants.length) ?? [];
  const selected = available.find((c) => c.radius_mm === radius) ?? available.at(-1);
  const variant = selected?.variants.find((v) => v.objective === objective) ?? selected?.variants[0];
  const metrics = metricAt(variant, snr), baseline = data?.baseline.conditions.find((c) => c.snr_db === snr);
  const decision = arDecision(metrics, ar / 100);
  const recorded = variant && data
    ? { id: variant.id, xyzMm: variant.xyz_mm, regionIndices: variant.region_indices, referenceXyzMm: data.baseline.xyz_mm }
    : undefined;
  const curve = useMemo(
    () =>
      data?.config.radius_caps_mm.map((a) => {
        const row: Record<string, number | null> = { radius: a };
        for (const r of REGION_COUNTS) {
          const c = data.conditions.find((item) => item.family_id === `r${r}_${curveMode}` && item.radius_mm === a && item.spacing_mm === spacing);
          const m = metricAt(bestVariant(c, snr, criterion), snr);
          row[`r${r}`] = m?.[criterion] == null ? null : m[criterion]! * 100;
        }
        return row;
      }) ?? [],
    [data, curveMode, spacing, snr, criterion],
  );
  const passRows = data?.conditions
    .filter((c) => c.spacing_mm === spacing && c.mode === curveMode)
    .flatMap((c) => c.variants.filter((v) => arDecision(metricAt(v, snr), ar / 100) === 'pass').map((v) => ({ c, v })))
    .sort((a, b) => a.c.R - b.c.R || a.c.radius_mm - b.c.radius_mm) ?? [];
  const arValues = data?.conditions
    .filter((c) => c.spacing_mm === spacing && c.mode === curveMode)
    .flatMap((c) => c.variants.map((v) => metricAt(v, snr)?.conditional_global))
    .filter((v): v is number => v != null && Number.isFinite(v)) ?? [];
  const highestFoundAR = arValues.length ? Math.max(...arValues) : null;
  const scored = data?.conditions.filter((c) => c.variants.length).length ?? 0;
  const unique = data ? new Set(data.conditions.flatMap((c) => c.variants.map((v) => v.id))).size : 0;
  function changeRegions(r: number) {
    setRegions(r);
    setFamily(`r${r}_${curveMode}`);
  }

  return (
    <main className="lab-page">
      <SiteHeader current="results" arPercent={ar} returnHref={here} />
      <div className="lab-container space-y-6 py-6">
        <a className="lab-link-pill" href={'/findings?ar=' + ar}>{tx("← 返回当前已有结果")}</a>
        <header className="flex flex-wrap items-end justify-between gap-5">
          <div>
            <p className="lab-eyebrow mb-1.5">{tx("历史批次 · 固定64电极")}</p>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              {tx("历史半径实验 · 原始比较")}
            </h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-ink-soft">
              {tx("本页保留早期半径实验，允许区域相交，不等同于当前严格分离区域比较。原始布局、指标和曲线保留，只读查看。")}
            </p>
          </div>
          <a
            className={buttonVariants({ variant: 'outline' })}
            href="/data/single_head_optimization.json"
            download
          >
            <Download className="size-4" />
            {tx("下载实验数据")}
          </a>
        </header>
        {tx(!data && (
          <section className={panel} aria-live="polite">
            <h2 className="font-semibold">
              {tx(error ? '完整实验记录未载入' : '读取并校验实验记录')}
            </h2>
            <p className="my-3 text-sm text-ink-soft">
              {tx(error || '正在读取单头模实验的204项状态记录及布局坐标。')}
            </p>
            <button
              className="lab-link-pill"
              onClick={() => setRetry((v) => v + 1)}
            >
              <RefreshCcw className="size-3.5" />
              {tx("重新读取")}
            </button>
          </section>
        ))}
        {tx(data && (
          <>
            <RadiusConditionInspector
              data={data}
              scored={scored}
              unique={unique}
              regions={regions}
              family={family}
              spacing={spacing}
              snr={snr}
              objective={objective}
              available={available}
              selected={selected}
              variant={variant}
              recorded={recorded}
              onChangeRegions={changeRegions}
              onChangeFamily={setFamily}
              onChangeSpacing={setSpacing}
              onChangeRadius={setRadius}
              onChangeObjective={setObjective}
              onChangeSnr={setSnr}
            />
            <section className={panel}>
              <h2 className="text-lg font-semibold">
                {tx("与全头64点放在同一个尺度上比较")}
              </h2>
              <div className="lab-table-frame mt-4">
                <table className="w-full min-w-[650px] text-left text-sm">
                  <thead>
                    <tr className="border-b border-border/75 bg-muted/55 text-xs font-semibold tracking-wide text-ink-soft">
                      <th className="px-4 py-3">{tx("指标")}</th>
                      <th className="px-3 py-3">{tx("所选布局")}</th>
                      <th className="px-3 py-3">{tx("全头64点")}</th>
                      <th className="px-4 py-3">{tx("相对保留率")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b border-border/65">
                      <th className="px-4 py-3.5 font-medium">{tx("干净全头场能量解释率")}</th>
                      <td className="px-3 font-mono tabular-nums">{tx(pct(metrics?.field_absolute))}</td>
                      <td className="px-3 font-mono tabular-nums">{tx(pct(baseline?.field_absolute))}</td>
                      <td className="px-4 font-mono font-medium tabular-nums">{tx(pct(metrics?.field_relative))}</td>
                    </tr>
                    <tr className="border-b border-border/65">
                      <th className="px-4 py-3.5 font-medium">{tx("相对幅度比最低10%源面积的平均值")}</th>
                      <td className="px-3">{tx("以全头归一化")}</td>
                      <td className="px-3 font-mono">100%</td>
                      <td className="px-4 font-mono font-medium tabular-nums">{tx(pct(metrics?.sensitivity_tail))}</td>
                    </tr>
                    <tr className="border-b border-border/65">
                      <th className="px-4 py-3.5 font-medium">{tx("下尾定位评分 U（0—1）")}</th>
                      <td className="px-3 font-mono tabular-nums">
                        {tx(metrics?.localization_utility?.toFixed(4) ?? '指标无法计算')}
                      </td>
                      <td className="px-3 font-mono tabular-nums">{tx(baseline?.loc_util?.toFixed(4) ?? '指标无法计算')}</td>
                      <td className="px-4 font-mono font-medium tabular-nums">{tx(pct(metrics?.localization_relative))}</td>
                    </tr>
                    <tr>
                      <th className="px-4 py-3.5 font-medium">{tx("定位误差：中位数 / P90 / P95")}</th>
                      <td className="px-3 font-mono tabular-nums">
                        {tx(mm(metrics?.median_mm))} / {tx(mm(metrics?.p90_mm))} /{tx(' ')}
                        {tx(mm(metrics?.p95_mm))}
                      </td>
                      <td className="px-3 font-mono tabular-nums">
                        {tx(mm(baseline?.median_mm))} / {tx(mm(baseline?.p90_mm))} /{tx(' ')}
                        {tx(mm(baseline?.p95_mm))}
                      </td>
                      <td className="px-4 text-muted-foreground">{tx("绝对误差，越小越好")}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-xs leading-6 text-ink-soft">
                {tx("U：每次试验取 max(0, 1 − 误差/50 mm)，先对同一源的16次噪声取均值，再取最低10%源面积的加权均值。基准U为零时比值和三项最低相对评分G未定义。各指标分别报告。")}
              </p>
            </section>
            <RadiusCurvesSection
              data={data}
              curve={curve}
              curveMode={curveMode}
              criterion={criterion}
              ar={ar}
              snr={snr}
              spacing={spacing}
              onChangeCurveMode={setCurveMode}
              onChangeCriterion={setCriterion}
            />
            <section className="grid gap-5 lg:grid-cols-2">
              <div className={panel}>
                <h2 className="text-lg font-semibold">{tx("接受阈值 AR（本历史批次）")}</h2>
                <label
                  className="mt-4 flex items-center justify-between text-sm"
                  htmlFor="conditional-ar"
                >
                  <span>{tx("要求三项相对保留率均达到")}</span>
                  <span className="rounded-md bg-primary/10 px-2.5 py-0.5 font-mono text-lg font-semibold tabular-nums text-primary ring-1 ring-inset ring-primary/20">
                    {tx(ar)}%
                  </span>
                </label>
                <input
                  id="conditional-ar"
                  className="my-4 w-full accent-primary"
                  type="range"
                  min="10"
                  max="100"
                  step="1"
                  value={ar}
                  onChange={(e) => setAr(Number(e.target.value))}
                />
                <p className="lab-subpanel text-sm leading-6">
                  {tx("所选布局：")}{tx(decision === 'pass'
                    ? '通过此模型条件阈值'
                    : decision === 'fail'
                      ? '未通过此模型条件阈值'
                      : '指标无法计算，无法判断是否达到AR')}
                  {tx("。三项最低相对评分 ")}{tx(pct(metrics?.conditional_global))}。
                </p>
                <p className="mt-3.5 text-sm leading-6 text-ink-soft">
                  {tx("在曲线所选范围、")}{tx(spacing)} {tx(" mm点距及")}{tx(snr)} {tx(" dB下，")}{tx(passRows.length
                    ? `找到${passRows.length}个通过的配置／分支；按区域数优先、再按半径排序，首个为${passRows[0].c.R}区、半径上限${passRows[0].c.radius_mm} mm。`
                    : '本批已评分布局均未达到当前AR；其他布局仍待搜索。')}
                  {tx("此范围已找到的最高三项最低相对评分 G为")}{tx(' ')}
                  {tx(highestFoundAR == null ? '指标无法计算' : pct(highestFoundAR))}。
                </p>
                <p className="mt-2.5 text-xs leading-5 text-ink-soft">
                  {tx("筛选范围为本批有限搜索得到的布局，阈值适用于当前模型条件。总电极数固定为64，跨人群阈值另行验证。")}
                </p>
                <div className="lab-table-frame mt-4">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-border/75 bg-muted/55 font-semibold text-ink-soft">
                        <th className="px-3.5 py-2.5">{tx("区域数")}</th>
                        <th className="px-3 py-2.5">{tx("达到AR的最小已测半径")}</th>
                        <th className="px-3.5 py-2.5">{tx("已找到最高 G")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tx(REGION_COUNTS.map((r) => {
                        const first = passRows.find((row) => row.c.R === r);
                        const values = data.conditions
                          .filter((c) => c.R === r && c.mode === curveMode && c.spacing_mm === spacing)
                          .flatMap((c) => c.variants.map((v) => metricAt(v, snr)?.conditional_global))
                          .filter((v): v is number => v != null && Number.isFinite(v));
                        return (
                          <tr className="border-b border-border/65 last:border-0" key={r}>
                            <th className="px-3.5 py-2.5 font-medium">{tx(r)}{tx("区")}</th>
                            <td className="px-3 py-2.5">
                              {tx(first ? (
                                <button
                                  className="font-medium text-primary underline underline-offset-4"
                                  onClick={() => {
                                    setRegions(r);
                                    setFamily(first.c.family_id);
                                    setRadius(first.c.radius_mm);
                                    setObjective(first.v.objective);
                                  }}
                                >
                                  {tx(first.c.radius_mm)} {tx(" mm · 查看布局")}
                                </button>
                              ) : (
                                '未找到'
                              ))}
                            </td>
                            <td className="px-3.5 py-2.5 font-mono tabular-nums">
                              {tx(values.length ? pct(Math.max(...values)) : '指标无法计算')}
                            </td>
                          </tr>
                        );
                      }))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className={panel}>
                <h2 className="text-lg font-semibold">{tx("实验阶段与适用范围")}</h2>
                <ol className="mt-4 space-y-3.5 text-sm leading-6">
                  <li className="lab-subpanel">
                    <span className="font-semibold text-primary">{tx("历史阶段一 · 本批半径实验结果")}</span>
                    <br />
                    {tx("单Ernie FEM；5,387候选点；1/2/3/4/6区；204条件；有限中心与坐标交换搜索；统一场、敏感度及离散定位评价。")}
                  </li>
                  <li className="lab-subpanel">
                    <span className="font-semibold">{tx("阶段二 · 独立头模验证，未开始")}</span>
                    <br />
                    {tx("冻结本阶段入围布局，再检验不同解剖、导电率、源分布与噪声。本历史批次完成单头模评价，独立头模验证另列阶段。")}
                  </li>
                  <li className="lab-subpanel">
                    <span className="font-semibold">{tx("后续评价范围")}</span>
                    <br />
                    {tx("连续位置最优性、最小面积、真实毛发范围、人体定位误差及MI/P300分类表现均尚待评价。")}
                  </li>
                </ol>
                <a
                  className="mt-4 lab-link-pill text-sm"
                  href={methodLink(here, ar, '#single-head-optimization')}
                >
                  {tx("查看计算定义与限制")}<ArrowRight className="size-3.5" />
                </a>
              </div>
            </section>
            <RadiusBatchAuditSection data={data} />
            <footer className="flex flex-wrap items-center justify-between gap-4 py-3 text-xs leading-6 text-ink-soft">
              <div className="font-mono">
                {tx("运行 ")}{tx(data.provenance.run_id)}
                <br />
                {tx("数据SHA256 ")}{tx(data.provenance.report_sha256)}
              </div>
              <a className="lab-link-pill" href={'/pilot-results?ar=' + ar}>
                {tx("保留的首批双区域原型结果")}
              </a>
            </footer>
          </>
        ))}
      </div>
    </main>
  );
}
