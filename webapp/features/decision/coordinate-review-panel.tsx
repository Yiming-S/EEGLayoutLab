'use client';
import React from 'react';
import { useLanguage } from '@/components/language-provider';
import { Button } from '@/components/ui/button';
import type { ElectrodeDesign, DesignResult } from '@/lib/design-decision';
import { coordinateReview } from './coordinate-review';
import { coordinateSourceFiles } from '@/contracts/coordinate-source.mjs';

export function CoordinateReviewPanel({
  design,
  result,
}: {
  design: ElectrodeDesign;
  result: DesignResult | null;
}) {
  const { tx } = useLanguage(),
    review = coordinateReview(design, result);
  const [sortByMovement, setSortByMovement] = React.useState(false);
  const source = design.source_metadata;
  const download = () => {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(review, null, 2) + '\n'], { type: 'application/json' }),
    );
    const link = document.createElement('a');
    link.href = url;
    link.download = 'eeg-coordinate-review.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const displayedRows =
    review.evaluated && sortByMovement
      ? [...review.rows].sort(
          (a, b) => (b.movement_mm ?? -1) - (a.movement_mm ?? -1) || a.index - b.index,
        )
      : review.rows;

  const stats = (() => {
    if (!review.evaluated) return null;
    const movements = review.rows
      .map((row) => row.movement_mm)
      .filter((value): value is number => value !== null && Number.isFinite(value))
      .sort((a, b) => a - b);
    if (!movements.length) return null;
    const mid = Math.floor(movements.length / 2),
      median =
        movements.length % 2 === 0
          ? (movements[mid - 1] + movements[mid]) / 2
          : movements[mid],
      max = movements[movements.length - 1],
      passCount = review.rows.filter((row) => row.status === 'within_projection_limit').length,
      overCount = review.rows.filter((row) => row.status === 'outside_projection_limit').length,
      scaleMax = Math.max(2.5, max * 1.15);
    return { median, max, passCount, overCount, total: review.rows.length, scaleMax };
  })();

  return (
    <details className="mt-4 rounded-lg border p-4">
      <summary className="cursor-pointer font-medium">{tx('逐电极坐标检查')}</summary>
      <p className="mt-3 text-sm">{tx('坐标声明：Ernie原生空间，单位mm。此接口不执行坐标配准。')}</p>
      <p className="mt-2 break-words text-xs text-muted-foreground">
        {tx('坐标来源')} · {source ? coordinateSourceFiles(source) : design.name}
      </p>
      {source && (
        <p className="mt-2 whitespace-pre-wrap text-xs text-muted-foreground">
          {source.coordinate_system_description}
        </p>
      )}
      <p className="mt-2 text-xs text-muted-foreground">
        {tx(
          review.evaluated
            ? '合格表示已验证结果的逐点投影移动不超过现有2 mm限制；数值评分另行显示。'
            : '尚未评价；原输入坐标不能作为已投影合格的结果。',
        )}
      </p>
      {stats && (
        <div
          className="mt-3 space-y-2.5 rounded-lg border bg-muted/20 p-3"
          data-projection-displacement-chart
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-xs font-semibold text-foreground">
                {tx('64电极投影位移分布（2.0 mm 合格上限）')}
              </p>
              <p className="mt-0.5 font-mono text-[11px] tabular-nums text-muted-foreground">
                {tx(
                  `合格 ${stats.passCount}/${stats.total} · 超限 ${stats.overCount} · 中位 ${stats.median.toFixed(3)} mm · 最大 ${stats.max.toFixed(3)} mm`,
                )}
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              aria-pressed={sortByMovement}
              onClick={() => setSortByMovement((prev) => !prev)}
            >
              {tx(sortByMovement ? '按原电极顺序' : '按位移降序排列')}
            </Button>
          </div>
          <svg
            viewBox="0 0 640 72"
            className="h-18 w-full overflow-visible"
            aria-label={tx('64电极投影位移分布（2.0 mm 合格上限）')}
          >
            <title>{tx('64电极投影位移分布（2.0 mm 合格上限）')}</title>
            <line
              x1={8}
              x2={632}
              y1={62}
              y2={62}
              className="stroke-border"
              strokeWidth={1}
            />
            {(() => {
              const limitY = 62 - (2 / stats.scaleMax) * 52;
              return (
                <>
                  <line
                    x1={8}
                    x2={632}
                    y1={limitY}
                    y2={limitY}
                    className="stroke-warning"
                    strokeWidth={1.2}
                    strokeDasharray="4 3"
                  />
                  <text
                    x={630}
                    y={Math.max(10, limitY - 3)}
                    textAnchor="end"
                    fontSize="9.5"
                    className="fill-warning font-mono"
                  >
                    {tx('2.0 mm 上限')}
                  </text>
                </>
              );
            })()}
            {displayedRows.map((row, idx) => {
              const val = row.movement_mm ?? 0,
                barH = Math.max(1.5, Math.min(54, (val / stats.scaleMax) * 52)),
                x = 10 + idx * (620 / Math.max(1, displayedRows.length)),
                over = row.status === 'outside_projection_limit';
              return (
                <rect
                  key={row.index}
                  x={x}
                  y={62 - barH}
                  width={Math.max(3, 620 / displayedRows.length - 2.2)}
                  height={barH}
                  rx={1.2}
                  className={over ? 'fill-warning' : 'fill-primary/80'}
                >
                  <title>{`${row.name}: ${val.toFixed(4)} mm`}</title>
                </rect>
              );
            })}
          </svg>
        </div>
      )}
      <div className="mt-3 max-h-96 overflow-auto">
        <table className="w-full min-w-[850px] text-left text-xs">
          <thead>
            <tr>
              <th>{tx('电极')}</th>
              <th>{tx('区域')}</th>
              <th>{tx('原输入坐标（mm）')}</th>
              <th>{tx('实际评价坐标（mm）')}</th>
              <th>{tx('投影移动（mm）')}</th>
              <th>{tx('坐标检查')}</th>
            </tr>
          </thead>
          <tbody>
            {displayedRows.map((row) => (
              <tr className="border-t align-top" key={row.index}>
                <td className="py-2">{row.name}</td>
                <td>{row.region}</td>
                <td className="font-mono">{row.input_xyz_mm.join(', ')}</td>
                <td className="font-mono">{row.evaluated_xyz_mm?.join(', ') ?? '—'}</td>
                <td
                  className="font-mono"
                  title={row.movement_mm === null ? undefined : String(row.movement_mm)}
                >
                  <span>{row.movement_mm === null ? '—' : row.movement_mm.toFixed(6)}</span>
                  {row.movement_mm !== null && stats && (
                    <span
                      aria-hidden="true"
                      className="relative mt-1 block h-1 w-20 overflow-hidden rounded-full bg-muted"
                    >
                      <span
                        className={`block h-full rounded-full ${
                          row.status === 'outside_projection_limit' ? 'bg-warning' : 'bg-primary'
                        }`}
                        style={{
                          width: `${Math.min(100, (row.movement_mm / stats.scaleMax) * 100)}%`,
                        }}
                      />
                      <span
                        className="absolute inset-y-0 w-px bg-warning"
                        style={{ left: `${Math.min(100, (2 / stats.scaleMax) * 100)}%` }}
                      />
                    </span>
                  )}
                </td>
                <td>
                  {tx(
                    row.status === 'not_evaluated'
                      ? '未评价'
                      : row.status === 'within_projection_limit'
                        ? '合格'
                        : '超出投影限制',
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Button className="mt-3" size="sm" variant="outline" onClick={download}>
        {tx('导出逐电极检查JSON')}
      </Button>
    </details>
  );
}
