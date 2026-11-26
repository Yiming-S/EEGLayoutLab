'use client';

/* oxlint-disable next/no-html-link-for-pages -- preserve the existing vinext navigation behavior */
import { ChartNoAxesCombined, ChevronDown, Download } from 'lucide-react';
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
import { useLanguage } from '@/components/language-provider';
import { buttonVariants } from '@/components/ui/button';
import {
  atSnr,
  RESULT_FAMILIES,
  retentionPercent,
  selectRecordedLayout,
  type Fixed64Results,
} from '@/lib/fixed64-results';

const RADII = [20, 30, 40, 50];
const PANEL_STYLE = 'lab-panel';
const mm = (value?: number | null) =>
  value == null ? '未计算' : `${value.toFixed(2)} mm`;

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
      <p className="mb-4 mt-1 text-sm leading-6 text-ink-soft">
        {tx(sensitivity
          ? '相对幅度保留率最低的10%皮层面积，按面积加权；不随噪声档位变化。'
          : `相对全头64点 · ${snr} dB · 最小电极间距 ${spacing} mm`)}
      </p>
      <figure
        className="h-[310px] w-full rounded-xl border border-border/65 bg-muted/20 p-3"
        aria-label={
          tx(sensitivity
            ? '敏感度随已计算半径变化，数值见下方配置表'
            : '信号重建保留率随已计算半径变化，数值见下方配置表')
        }
      >
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={rows}
            margin={{ top: 12, right: 16, left: 0, bottom: 5 }}
            accessibilityLayer
          >
            <CartesianGrid
              strokeDasharray="3 3"
              vertical={false}
              stroke="var(--border)"
            />
            <XAxis
              dataKey="radius"
              type="number"
              domain={[20, 50]}
              ticks={RADII}
              tick={{ fontSize: 12 }}
              tickFormatter={(v) => tx(`${v} mm`)}
            />
            <YAxis
              domain={[0, 'auto']}
              width={48}
              tick={{ fontSize: 12 }}
              tickFormatter={(v) => tx(`${v}%`)}
            />
            <Tooltip
              labelFormatter={(v) => tx(`半径上限 ${v} mm`)}
              formatter={(v) =>
                tx(typeof v === 'number' ? `${v.toFixed(2)}%` : '未计算')
              }
              contentStyle={{ borderRadius: 12, borderColor: 'var(--border)', fontSize: 13 }}
            />
            <Legend wrapperStyle={{ fontSize: 13, paddingTop: 12 }} />
            <ReferenceLine
              y={100}
              stroke="var(--chart-reference)"
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
                strokeWidth={2.25}
                dot={{ r: 4 }}
                activeDot={{ r: 6 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            )))}
          </LineChart>
        </ResponsiveContainer>
      </figure>
      <p className="mt-3 text-xs leading-6 text-ink-soft">
        {tx("虚线为全头基准的100%相对值。连线仅连接已计算点，不产生中间半径的估计。")}
      </p>
    </section>
  );
}

export interface PilotComparisonTablesSectionProps {
  data: Fixed64Results;
  family: string;
  radius: number;
  spacing: number;
  snr: number;
  onSelectCell: (familyId: string, radiusMm: number) => void;
}

export function PilotComparisonTablesSection({
  data,
  family,
  radius,
  spacing,
  snr,
  onSelectCell,
}: PilotComparisonTablesSectionProps) {
  const { tx } = useLanguage();

  return (
    <>
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
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          <ChartNoAxesCombined className="size-5 text-primary" />
          {tx("已计算配置对比 · ")}{tx(snr)} dB / {tx(spacing)} {tx(" mm点距")}
        </h2>
        <p className="mt-1.5 text-sm leading-6 text-ink-soft">
          {tx("每格为“信号重建相对保留率 / 幅度保留率（最差10%）”；点击数值可切换3D点位。全头64点的两项相对值均为100%，作为本批相对比较基准。")}
        </p>
        <div className="lab-table-frame mt-4">
          <table className="w-full min-w-[660px] text-left text-sm">
            <caption className="sr-only">
              {tx("区域半径与各组合的已计算物理保留率")}
            </caption>
            <thead>
              <tr className="border-b border-border/75 bg-muted/55 text-xs font-semibold tracking-wide text-ink-soft">
                <th scope="col" className="px-4 py-3">
                  {tx("半径上限")}
                </th>
                {tx(RESULT_FAMILIES.map((f) => (
                  <th scope="col" className="px-3 py-3" key={f.id}>
                    {tx(f.label)}
                  </th>
                )))}
              </tr>
            </thead>
            <tbody>
              {tx(RADII.map((r) => (
                <tr key={r} className="border-b border-border/65 last:border-0">
                  <th scope="row" className="px-4 py-3 font-mono font-medium tabular-nums">
                    {tx(r)} mm
                  </th>
                  {tx(RESULT_FAMILIES.map((f) => {
                    const row = selectRecordedLayout(data, f.id, r, spacing);
                    const score = atSnr(row?.metrics.conditions ?? null, snr);
                    return (
                      <td key={f.id} className="p-2">
                        {tx(row ? (
                          <button
                            type="button"
                            aria-label={tx(`${f.label}，半径${r}mm，信号重建${retentionPercent(score?.field_relative)}，敏感度${retentionPercent(row.metrics.sensitivity_tail)}`)}
                            onClick={() => onSelectCell(f.id, r)}
                            className={`rounded-lg px-2.5 py-2 text-left font-mono text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${family === f.id && radius === r ? 'bg-primary/12 font-semibold text-primary ring-1 ring-inset ring-primary/22' : 'hover:bg-muted/70'}`}
                          >
                            {tx(retentionPercent(score?.field_relative))} /{tx(' ')}
                            {tx(retentionPercent(row.metrics.sensitivity_tail))}
                          </button>
                        ) : (
                          <span className="px-2 text-xs text-ink-soft">
                            {tx("未生成")}
                          </span>
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
        <h2 className="text-lg font-semibold">
          {tx("定位诊断子实验 · 固定30 mm / 6 mm · ")}{tx(snr)} dB
        </h2>
        <p className="mt-1.5 max-w-4xl text-sm leading-6 text-ink-soft">
          {tx("这四个布局在计算性能前选定，与上方半径和点距选择无关。每项为256个源×16次噪声，共4,096次模拟试验。生成源不在反演字典上，但使用同一头模和导电率，仍存在同模型反演偏差。")}
        </p>
        <div className="lab-table-frame mt-4">
          <table className="w-full min-w-[560px] text-left text-sm">
            <caption className="sr-only">
              {tx("固定原型定位误差，单位毫米")}
            </caption>
            <thead>
              <tr className="border-b border-border/75 bg-muted/55 text-xs font-semibold tracking-wide text-ink-soft">
                <th scope="col" className="px-4 py-3">{tx("布局")}</th>
                <th scope="col" className="px-3 py-3">{tx("中位误差")}</th>
                <th scope="col" className="px-3 py-3">{tx("P90误差")}</th>
                <th scope="col" className="px-4 py-3">{tx("P95误差")}</th>
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
                  values: selectRecordedLayout(data, f.id, 30, 6)?.localization ?? null,
                })),
              ].map((row) => {
                const loc = atSnr(row.values, snr);
                return (
                  <tr key={row.name} className="border-b border-border/65 last:border-0">
                    <th scope="row" className="px-4 py-3 font-medium">{row.name}</th>
                    <td className="px-3 py-3 font-mono tabular-nums">{tx(mm(loc?.median_mm))}</td>
                    <td className="px-3 py-3 font-mono tabular-nums">{tx(mm(loc?.p90_mm))}</td>
                    <td className="px-4 py-3 font-mono tabular-nums">{tx(mm(loc?.p95_mm))}</td>
                  </tr>
                );
              }))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 rounded-xl border border-warning/30 bg-warning-surface/75 p-3.5 text-xs leading-5 text-warning">
          {tx("独立无噪声检查中，全头基准仍有10.73 mm中位误差、20.57 mm的P90误差。这些误差反映固定法向离散字典的匹配限制；人体定位精度与群体阈值需独立验证。")}
        </p>
      </section>

      <section className={`${PANEL_STYLE} space-y-4`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">{tx("数据来源与适用范围")}</h2>
          <a
            href="/data/fixed64_results.json"
            download="fixed64_results.json"
            className={buttonVariants({ variant: 'outline', size: 'sm' })}
          >
            <Download className="size-4" />
            {tx("下载结果与64点坐标")}
          </a>
        </div>
        <ul className="list-disc space-y-2 pl-5 text-sm leading-6 text-ink-soft">
          <li>
            {tx("结果范围为一个Ernie头模与本批双区域组合，最高值取自已计算布局。1/3/4/6区域见后续实验，跨头模置信区间尚待评价。")}
          </li>
          <li>
            {tx("皮层域来自注册图谱。108 / 4,352个源采用最近灰质恢复，最大距离1.55 mm；四个曲面点与血液组织分割不一致，保留了明确的灰质近似模型。")}
          </li>
          <li>
            {tx("源先验按皮层面积加权，信号重建与尾部幅度分别评价。任务分类属于后续验证。")}
          </li>
          <li>
            {tx("本页筛选并展示已保存的早期原型。新布局可在布局设计页计算并判定AR，跨头模验证另列阶段。")}
          </li>
        </ul>
        <details className="group/trace rounded-xl border border-border/70 bg-muted/25 p-3.5 text-sm">
          <summary className="flex cursor-pointer list-none items-center justify-between font-semibold select-none [&::-webkit-details-marker]:hidden">
            <span>{tx("查看可追溯标识")}</span>
            <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open/trace:rotate-180" />
          </summary>
          <dl className="mt-3 space-y-2.5 break-all font-mono text-xs leading-5 text-ink-soft">
            <div>
              <dt className="font-sans text-muted-foreground">Run</dt>
              <dd>{tx(data.run_id)}</dd>
            </div>
            <div>
              <dt className="font-sans text-muted-foreground">{tx("原始报告 SHA-256")}</dt>
              <dd>{tx(data.provenance.report_sha256)}</dd>
            </div>
            <div>
              <dt className="font-sans text-muted-foreground">{tx("前向矩阵 SHA-256")}</dt>
              <dd>{tx(data.provenance.forward_sha256)}</dd>
            </div>
            <div>
              <dt className="font-sans text-muted-foreground">{tx("指标数据 SHA-256")}</dt>
              <dd>{tx(data.provenance.metrics_sha256)}</dd>
            </div>
          </dl>
        </details>
      </section>
    </>
  );
}
