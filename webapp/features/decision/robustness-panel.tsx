import { useLanguage } from '@/components/language-provider';
import { pct } from '@/lib/design-decision';
import {
  criticalElectrodes,
  robustnessRows,
  type RobustnessBlock,
  type RobustnessRow,
  type RobustnessStats,
} from '@/lib/design-robustness';

const cell = (value: RobustnessStats | null) =>
  value ? `${pct(value.median)} (P10 ${pct(value.p10)})` : '无有效试验';

const isFiniteStats = (value: RobustnessStats | null | undefined): value is RobustnessStats =>
  Boolean(
    value &&
      Number.isFinite(value.median) &&
      Number.isFinite(value.p10) &&
      Number.isFinite(value.minimum),
  );

function computePercentDomain(values: number[]): [number, number] {
  if (!values.length) return [0, 100];
  const minVal = Math.min(...values),
    maxVal = Math.max(...values);
  const domainMin =
    minVal < 0
      ? Math.floor(minVal / 10) * 10
      : minVal >= 55
        ? Math.max(0, Math.floor((minVal - 4) / 10) * 10)
        : 0;
  const rawMax = maxVal > 100 ? Math.ceil(maxVal / 5) * 5 : 100;
  return rawMax - domainMin < 10 ? [Math.max(0, rawMax - 10), rawMax] : [domainMin, rawMax];
}

const formatPercentTick = (value: number) => {
  const clean = Math.abs(value) < 1e-9 ? 0 : value;
  return `${Number.isInteger(clean) ? clean.toFixed(0) : clean.toFixed(1)}%`;
};

function RobustnessIntervalChart({
  rows,
  critical,
  singleReferenceMedian,
}: {
  rows: RobustnessRow[];
  critical: ReturnType<typeof criticalElectrodes>;
  singleReferenceMedian: number;
}) {
  const { tx } = useLanguage();
  const points: number[] = [];
  for (const row of rows) {
    if (isFiniteStats(row.candidate)) {
      points.push(row.candidate.p10 * 100, row.candidate.median * 100);
    }
    if (isFiniteStats(row.reference)) {
      points.push(row.reference.p10 * 100, row.reference.median * 100);
    }
  }
  for (const item of critical) {
    if (Number.isFinite(item.retention)) points.push(item.retention * 100);
  }
  if (Number.isFinite(singleReferenceMedian)) {
    points.push(singleReferenceMedian * 100);
  }
  const [domainMin, domainMax] = computePercentDomain(points),
    span = Math.max(1e-9, domainMax - domainMin),
    padX = 8,
    trackWidth = 344,
    toX = (percentValue: number) =>
      padX +
      (Math.min(domainMax, Math.max(domainMin, percentValue)) - domainMin) /
        span *
        trackWidth,
    ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => domainMin + span * ratio);

  return (
    <div className="mt-3 space-y-3 rounded-lg border bg-muted/20 p-3.5" data-robustness-interval-chart>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold text-foreground">
            {tx('当前坐标 vs 标准全头64（P10–中位数区间图）')}
          </p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {tx('左端竖线为 P10 下分位，实心标记为中位数；竖虚线为未扰动标准64基准（100%）。')}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block size-2.5 rotate-45 bg-primary" />
            <span className="font-medium text-foreground">{tx('当前坐标')}</span>
            <span>({tx('P10–中位数')})</span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block size-2.5 rounded-full bg-sky-600 dark:bg-sky-400" />
            <span className="font-medium text-foreground">{tx('标准全头64')}</span>
            <span>({tx('P10–中位数')})</span>
          </span>
        </div>
      </div>

      <div className="space-y-2">
        {rows.map((row) => {
          const candOk = isFiniteStats(row.candidate),
            refOk = isFiniteStats(row.reference),
            candP10X = candOk ? toX(Math.min(row.candidate!.p10, row.candidate!.median) * 100) : padX,
            candMedX = candOk ? toX(row.candidate!.median * 100) : padX,
            refP10X = refOk ? toX(Math.min(row.reference!.p10, row.reference!.median) * 100) : padX,
            refMedX = refOk ? toX(row.reference!.median * 100) : padX,
            labelText = tx(row.label),
            ariaLabel = tx(
              `${row.label}：当前坐标 P10 ${candOk ? pct(row.candidate!.p10) : '无有效试验'}、中位数 ${candOk ? pct(row.candidate!.median) : '无有效试验'}；标准64 P10 ${refOk ? pct(row.reference!.p10) : '无有效试验'}、中位数 ${refOk ? pct(row.reference!.median) : '无有效试验'}`,
            );
          return (
            <div
              key={row.label}
              className="grid items-center gap-2 rounded-md bg-background/60 px-2.5 py-1.5 text-xs sm:grid-cols-[minmax(160px,220px)_minmax(0,1fr)_minmax(145px,180px)]"
            >
              <div className="min-w-0">
                <p className="truncate font-medium text-foreground" title={labelText}>
                  {labelText}
                </p>
                {row.note && (
                  <p className="mt-0.5 line-clamp-1 text-[11px] text-muted-foreground" title={tx(row.note)}>
                    {tx(row.note)}
                  </p>
                )}
              </div>
              <svg
                viewBox="0 0 360 34"
                className="h-8 w-full overflow-visible"
                aria-label={ariaLabel}
              >
                <title>{ariaLabel}</title>
                {ticks.map((tick, index) => {
                  const x = toX(tick);
                  return (
                    <line
                      key={index}
                      x1={x}
                      x2={x}
                      y1={3}
                      y2={31}
                      className="stroke-border"
                      strokeWidth={1}
                    />
                  );
                })}
                {domainMin < 0 && domainMax > 0 && (
                  <line
                    x1={toX(0)}
                    x2={toX(0)}
                    y1={2}
                    y2={32}
                    className="stroke-foreground/35"
                    strokeWidth={1}
                    strokeDasharray="2 2"
                  />
                )}
                {domainMin <= 100 && domainMax >= 100 && (
                  <line
                    x1={toX(100)}
                    x2={toX(100)}
                    y1={2}
                    y2={32}
                    className="stroke-foreground/45"
                    strokeWidth={1}
                    strokeDasharray="3 2"
                  />
                )}
                <line
                  x1={padX}
                  x2={padX + trackWidth}
                  y1={11}
                  y2={11}
                  className="stroke-border/80"
                  strokeWidth={1}
                  strokeDasharray={candOk ? undefined : '3 3'}
                />
                {candOk && (
                  <>
                    <rect
                      x={candP10X}
                      y={7}
                      width={Math.max(2, candMedX - candP10X)}
                      height={8}
                      rx={2}
                      className="fill-primary/20"
                    />
                    <line
                      x1={candP10X}
                      x2={candMedX}
                      y1={11}
                      y2={11}
                      className="stroke-primary"
                      strokeWidth={2}
                    />
                    <line
                      x1={candP10X}
                      x2={candP10X}
                      y1={6}
                      y2={16}
                      className="stroke-primary"
                      strokeWidth={1.75}
                    />
                    <polygon
                      points={`${candMedX},5.5 ${candMedX + 4.5},11 ${candMedX},16.5 ${candMedX - 4.5},11`}
                      className="fill-primary stroke-background"
                      strokeWidth={1}
                    />
                  </>
                )}
                <line
                  x1={padX}
                  x2={padX + trackWidth}
                  y1={24}
                  y2={24}
                  className="stroke-border/80"
                  strokeWidth={1}
                  strokeDasharray={refOk ? undefined : '3 3'}
                />
                {refOk && (
                  <>
                    <rect
                      x={refP10X}
                      y={20}
                      width={Math.max(2, refMedX - refP10X)}
                      height={8}
                      rx={2}
                      className="fill-sky-500/20"
                    />
                    <line
                      x1={refP10X}
                      x2={refMedX}
                      y1={24}
                      y2={24}
                      className="stroke-sky-600 dark:stroke-sky-400"
                      strokeWidth={2}
                    />
                    <line
                      x1={refP10X}
                      x2={refP10X}
                      y1={19}
                      y2={29}
                      className="stroke-sky-600 dark:stroke-sky-400"
                      strokeWidth={1.75}
                    />
                    <circle
                      cx={refMedX}
                      cy={24}
                      r={3.6}
                      className="fill-sky-600 stroke-background dark:fill-sky-400"
                      strokeWidth={1}
                    />
                  </>
                )}
              </svg>
              <div className="space-y-0.5 text-right font-mono text-[11px] tabular-nums">
                <div className="text-foreground">
                  {candOk ? (
                    <span>
                      {pct(row.candidate!.p10)} – <strong>{pct(row.candidate!.median)}</strong>
                    </span>
                  ) : (
                    <span className="text-muted-foreground">{tx('无有效试验')}</span>
                  )}
                </div>
                <div className="text-sky-700 dark:text-sky-300">
                  {refOk ? (
                    <span>
                      {pct(row.reference!.p10)} – {pct(row.reference!.median)}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">{tx('无有效试验')}</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
        <div className="grid items-center gap-2 px-2.5 text-[10px] text-muted-foreground sm:grid-cols-[minmax(160px,220px)_minmax(0,1fr)_minmax(145px,180px)]">
          <span className="hidden sm:inline" />
          <div className="flex justify-between font-mono tabular-nums">
            {ticks.map((tick, index) => (
              <span key={index}>{formatPercentTick(tick)}</span>
            ))}
          </div>
          <span className="hidden text-right font-mono sm:inline">
            P10 – {tx('中位数')}
          </span>
        </div>
      </div>

      {critical.length > 0 && (
        <div className="border-t pt-3 space-y-2" data-critical-dropout-chart>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="font-semibold text-foreground">
              {tx('单电极脱落最敏感通道（前5名）')}
            </span>
            {Number.isFinite(singleReferenceMedian) && (
              <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
                <span aria-hidden="true" className="inline-block h-3 w-0.5 border-l border-dashed border-sky-600 dark:border-sky-400" />
                {tx('标准64单点脱落中位数')} {pct(singleReferenceMedian)}
              </span>
            )}
          </div>
          <div className="grid gap-1.5 sm:grid-cols-5">
            {critical.map((item) => {
              const valPct = item.retention * 100,
                barRatio = Math.max(0, Math.min(1, (valPct - domainMin) / span)),
                refRatio = Number.isFinite(singleReferenceMedian)
                  ? Math.max(0, Math.min(1, (singleReferenceMedian * 100 - domainMin) / span))
                  : null;
              return (
                <div
                  key={item.index}
                  className="rounded-md border bg-background/70 px-2.5 py-1.5 text-xs"
                >
                  <div className="flex items-baseline justify-between gap-1">
                    <span className="truncate font-medium text-foreground" title={item.name}>
                      {item.name}
                    </span>
                    <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                      {pct(item.retention)}
                    </span>
                  </div>
                  <div
                    aria-hidden="true"
                    className="relative mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted"
                  >
                    <div
                      className="h-full rounded-full bg-primary/75"
                      style={{ width: `${barRatio * 100}%` }}
                    />
                    {refRatio !== null && (
                      <div
                        className="absolute inset-y-0 w-0.5 bg-sky-600 dark:bg-sky-400"
                        style={{ left: `calc(${refRatio * 100}% - 1px)` }}
                      />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/** Session robustness of one evaluated layout beside standard64 under the same draws. */
export function RobustnessPanel({ block, names }: { block: RobustnessBlock; names?: string[] }) {
  const { tx } = useLanguage();
  const rows = robustnessRows(block);
  const critical = criticalElectrodes(block, names);
  return (
    <div className="mt-5">
      <h4 className="font-semibold">{tx('跨会话稳健性')}</h4>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">
        {tx(
          '重建保留率的中位数与P10，均相对未扰动的标准全头64；标准64在同一批随机抽样下计算。电极脱落后其余电极重新平均参考并重新估计；噪声不均时典型电极保持名义噪声，重建器已知各通道噪声；重新佩戴为整帽绕头中心随机轴旋转加2 mm独立抖动。',
        )}
      </p>
      <RobustnessIntervalChart
        rows={rows}
        critical={critical}
        singleReferenceMedian={block.dropout.single.reference.median}
      />
      <table className="mt-3 w-full min-w-[560px] text-left text-sm">
        <thead>
          <tr>
            <th className="py-2">{tx('扰动')}</th>
            <th>{tx('当前坐标')}</th>
            <th>{tx('标准全头64')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className="border-t">
              <th className="py-2 font-normal">
                {tx(row.label)}
                {row.note && (
                  <span className="block text-xs text-muted-foreground">{tx(row.note)}</span>
                )}
              </th>
              <td>{tx(cell(row.candidate))}</td>
              <td>{tx(cell(row.reference))}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {block.replacement.status === 'unavailable' && (
        <p className="mt-2 text-xs text-muted-foreground">{tx(block.replacement.reason)}</p>
      )}
      <p className="mt-3 text-sm">
        {tx('单个电极脱落影响最大的电极：')}
        {critical.map((item) => `${item.name} ${pct(item.retention)}`).join('，')}
        {tx(`。标准64中位数${pct(block.dropout.single.reference.median)}。`)}
      </p>
    </div>
  );
}
