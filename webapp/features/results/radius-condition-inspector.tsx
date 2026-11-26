'use client';

import { lazy, Suspense } from 'react';
import { Info } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { retentionPercent as pct } from '@/lib/fixed64-results';
import {
  allocationFor,
  familyLabel,
  metricAt,
  REGION_COUNTS,
  type SingleHeadResults,
} from '@/lib/single-head-results';

const Head = lazy(() =>
  import('@/components/cluster-head-viewer').then((m) => ({
    default: m.ClusterHeadViewer,
  })),
);

const panel = 'lab-panel';
const select = 'lab-select';

type Condition = SingleHeadResults['conditions'][number];
type Variant = Condition['variants'][number];

export interface RadiusConditionInspectorProps {
  data: SingleHeadResults;
  scored: number;
  unique: number;
  regions: number;
  family: string;
  spacing: number;
  snr: number;
  objective: string;
  available: Condition[];
  selected: Condition | undefined;
  variant: Variant | undefined;
  recorded:
    | {
        id: string;
        xyzMm: SingleHeadResults['baseline']['xyz_mm'];
        regionIndices: number[];
        referenceXyzMm: SingleHeadResults['baseline']['xyz_mm'];
      }
    | undefined;
  onChangeRegions: (regions: number) => void;
  onChangeFamily: (family: string) => void;
  onChangeSpacing: (spacing: number) => void;
  onChangeRadius: (radius: number) => void;
  onChangeObjective: (objective: string) => void;
  onChangeSnr: (snr: number) => void;
}

export function RadiusConditionInspector({
  data,
  scored,
  unique,
  regions,
  family,
  spacing,
  snr,
  objective,
  available,
  selected,
  variant,
  recorded,
  onChangeRegions,
  onChangeFamily,
  onChangeSpacing,
  onChangeRadius,
  onChangeObjective,
  onChangeSnr,
}: RadiusConditionInspectorProps) {
  const { tx } = useLanguage();

  return (
    <>
      <section
        className="grid gap-3.5 sm:grid-cols-4"
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
            <p className="text-xs font-medium text-ink-soft">{tx(label)}</p>
            <p className="my-2 font-mono text-2xl font-semibold tabular-nums sm:text-3xl">
              {tx(value)}
            </p>
            <p className="text-xs leading-5 text-ink-soft">{tx(detail)}</p>
          </div>
        )))}
      </section>
      <aside className="flex gap-3 rounded-xl border border-warning/30 bg-warning-surface/75 px-4 py-3 text-xs leading-5 text-warning shadow-2xs">
        <Info className="mt-0.5 size-4 shrink-0" />
        <p>
          {tx("百分比为相对全头64点的模型内指标。搜索由信号重建和敏感度引导，定位在最终布局上统一评估。AR用于当前头模与当前SNR的阈值筛选。")}
        </p>
      </aside>
      <section className="grid items-start gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
        <div className={`${panel} space-y-4`}>
          <div>
            <h2 className="text-lg font-semibold">{tx("所选布局条件（历史记录）")}</h2>
            <p className="mt-1.5 text-xs leading-5 text-ink-soft">
              {tx("只显示已生成完整64点的尺寸。未构造成功的条件单独列在下方。")}
            </p>
          </div>
          <label className="lab-label">
            {tx("区域数量")}<select
              className={select}
              value={regions}
              onChange={(e) => onChangeRegions(Number(e.target.value))}
            >
              {tx(REGION_COUNTS.map((r) => (
                <option key={r} value={r}>
                  {tx(r)}{tx("区 · ")}{tx(allocationFor(r).join(' + '))}{tx("点")}
                </option>
              )))}
            </select>
          </label>
          <label className="lab-label">
            {tx("位置约束")}<select
              className={select}
              value={family}
              onChange={(e) => onChangeFamily(e.target.value)}
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
            <label className="lab-label">
              {tx("最小电极间距")}<select
                className={select}
                value={spacing}
                onChange={(e) => onChangeSpacing(Number(e.target.value))}
              >
                {tx(data.config.minimum_chord_spacings_mm.map((d) => (
                  <option key={d} value={d}>
                    {tx(d)} mm
                  </option>
                )))}
              </select>
            </label>
            <label className="lab-label">
              {tx("半径上限")}<select
                className={select}
                value={selected?.radius_mm ?? ''}
                onChange={(e) => onChangeRadius(Number(e.target.value))}
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
          <label className="lab-label">
            {tx("优化分支")}<select
              className={select}
              value={objective}
              onChange={(e) => onChangeObjective(e.target.value)}
            >
              <option value="field_20db">{tx("优先信号重建")}</option>
              <option value="min_field_sensitivity_20db">
                {tx("提高信号重建与敏感度的较低项")}
              </option>
            </select>
          </label>
          <label className="lab-label">
            {tx("统一噪声档位")}<select
              className={select}
              value={snr}
              onChange={(e) => onChangeSnr(Number(e.target.value))}
            >
              {tx([0, 10, 20].map((s) => (
                <option key={s} value={s}>
                  {tx("全头基准 SNR ")}{tx(s)} dB
                </option>
              )))}
            </select>
          </label>
          <p className="border-t border-border/70 pt-3.5 text-xs leading-5 text-ink-soft">
            {tx("点距为欧氏弦距；半径为网格边路径上限。少毛发候选区为坐标近似范围，人体可佩戴范围尚待审核。")}
          </p>
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
                  {tx(variant.accepted_moves)}{tx("次接受的优化移动")}
                </p>
                <p className="mt-1.5 text-ink-soft">
                  {tx("20 dB信号重建：")}{tx(pct(variant.initial.field20))} →{tx(' ')}
                  {tx(pct(metricAt(variant, 20)?.field_relative))}{tx("；敏感度：")}{tx(pct(variant.initial.sensitivity_tail))} →{tx(' ')}
                  {tx(pct(metricAt(variant, 20)?.sensitivity_tail))}。
                </p>
                <p className="mt-1 text-ink-soft">
                  {tx("允许贴片面积约")}{tx(' ')}
                  {tx(variant.region_areas_cm2
                    .map((a) => a.toFixed(1))
                    .join(' / '))}{tx(' ')}
                  {tx("cm²。面积由区域内网格顶点分摊近似计算。")}
                </p>
                <p className="mt-2 font-mono text-xs text-ink-soft">
                  layout {tx(variant.id)}
                </p>
              </div>
            </>
          ) : (
            <div className={panel}>
              {tx("本批搜索在此区域组合和点距下未找到完整布局，整体几何可行性仍待判定。")}
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
