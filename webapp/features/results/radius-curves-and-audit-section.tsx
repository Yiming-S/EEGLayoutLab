'use client';

import { ChevronDown } from 'lucide-react';
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
import {
  allocationFor,
  CRITERIA,
  familyLabel,
  REGION_COLORS,
  REGION_COUNTS,
  type Criterion,
  type SingleHeadResults,
} from '@/lib/single-head-results';

const panel = 'lab-panel';
const select = 'lab-select';

export interface RadiusCurvesAndAuditSectionProps {
  data: SingleHeadResults;
  curve: Array<Record<string, number | null>>;
  curveMode: string;
  criterion: Criterion;
  ar: number;
  snr: number;
  spacing: number;
  onChangeCurveMode: (mode: string) => void;
  onChangeCriterion: (criterion: Criterion) => void;
}

export function RadiusCurvesSection({
  data,
  curve,
  curveMode,
  criterion,
  ar,
  snr,
  spacing,
  onChangeCurveMode,
  onChangeCriterion,
}: RadiusCurvesAndAuditSectionProps) {
  const { tx } = useLanguage();

  return (
    <section className={panel}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-3xl">
          <h2 className="text-lg font-semibold">
            {tx("曲线比较条件（独立于上方布局选择）")}
          </h2>
          <p className="mt-1.5 text-sm text-ink-soft">
            {tx("各点取两个优化分支中当前指标的较高值，对应布局可随半径和指标变化；曲线范围为已计算布局。 比较固定每区半径；区域数量变化时，总贴片面积也随之变化。")}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <label className="lab-label min-w-[180px]">
            {tx("比较范围")}<select
              className={select}
              value={curveMode}
              onChange={(e) => onChangeCurveMode(e.target.value)}
            >
              <option value="whole_scalp_free">{tx("全头自由中心")}</option>
              <option value="low_hair_free">{tx("低毛发近似约束")}</option>
            </select>
          </label>
          <label className="lab-label min-w-[200px]">
            {tx("曲线指标")}<select
              className={select}
              value={criterion}
              onChange={(e) => onChangeCriterion(e.target.value as Criterion)}
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
        className="mt-5 h-[350px] rounded-xl border border-border/65 bg-muted/20 p-3"
        aria-label={tx("五种区域数量的半径与性能比较")}
      >
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={curve}
            margin={{ left: 0, right: 20, top: 15, bottom: 10 }}
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
              domain={[20, 80]}
              ticks={data.config.radius_caps_mm}
              tick={{ fontSize: 12 }}
              tickFormatter={(v) => tx(`${v} mm`)}
            />
            <YAxis
              width={55}
              domain={[0, 'auto']}
              tick={{ fontSize: 12 }}
              tickFormatter={(v) => tx(`${v}%`)}
            />
            <Tooltip
              contentStyle={{ borderRadius: '0.75rem', borderColor: 'var(--border)' }}
              formatter={(v) =>
                tx(typeof v === 'number' ? `${v.toFixed(2)}%` : '指标无法计算')
              }
              labelFormatter={(v) => tx(`半径上限 ${v} mm`)}
            />
            <Legend />
            <ReferenceLine
              y={100}
              stroke="var(--chart-reference)"
              strokeDasharray="4 4"
              ifOverflow="extendDomain"
            />
            {tx(criterion === 'conditional_global' && (
              <ReferenceLine
                y={ar}
                stroke="var(--chart-threshold)"
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
                strokeWidth={2.25}
                type="linear"
                dot={{ r: 4 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            )))}
          </LineChart>
        </ResponsiveContainer>
      </figure>
      <p className="mt-3 text-xs leading-6 text-ink-soft">
        {tx("当前统一档位：")}{tx(snr)} {tx(" dB、点距")}{tx(spacing)}{tx(' ')}
        {tx("mm。空缺为未获得布局或指标未定义，不画成0%。连线仅连接计算点，不估计中间半径。")}
      </p>
    </section>
  );
}

export function RadiusBatchAuditSection({ data }: { data: SingleHeadResults }) {
  const { tx } = useLanguage();

  return (
    <section className={panel}>
      <h2 className="text-lg font-semibold">
        {tx("全量检查：每种区域数是否完成比较")}
      </h2>
      <div className="lab-table-frame mt-4">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead>
            <tr className="border-b border-border/75 bg-muted/55 text-xs font-semibold tracking-wide text-ink-soft">
              <th className="px-4 py-3">{tx("区域数 / 点数分配")}</th>
              <th className="px-3 py-3">{tx("已检查")}</th>
              <th className="px-3 py-3">{tx("获得评分布局")}</th>
              <th className="px-4 py-3">{tx("预算内未构造成功")}</th>
            </tr>
          </thead>
          <tbody>
            {tx(REGION_COUNTS.map((r) => {
              const all = data.conditions.filter((c) => c.R === r);
              const ok = all.filter((c) => c.variants.length).length;
              return (
                <tr key={r} className="border-b border-border/65 last:border-0">
                  <th className="px-4 py-3 font-medium">
                    {tx(r)}{tx("区 · ")}{tx(allocationFor(r).join('+'))}
                  </th>
                  <td className="px-3 font-mono tabular-nums">{tx(all.length)}</td>
                  <td className="px-3 font-mono tabular-nums">{tx(ok)}</td>
                  <td className="px-4 font-mono tabular-nums">{tx(all.length - ok)}</td>
                </tr>
              );
            }))}
          </tbody>
        </table>
      </div>
      <details className="group/fail mt-4 rounded-xl border border-border/70 bg-muted/25 px-3.5 py-2.5">
        <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium text-ink-soft select-none [&::-webkit-details-marker]:hidden">
          <span>{tx("查看本轮搜索未获得完整布局的条件")}</span>
          <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open/fail:rotate-180" />
        </summary>
        <ul className="mt-3 max-h-72 space-y-2 overflow-auto text-xs leading-5 text-ink-soft">
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
                {tx("（各值可对应不同布局）。")}
              </li>
            )))}
        </ul>
      </details>
    </section>
  );
}
