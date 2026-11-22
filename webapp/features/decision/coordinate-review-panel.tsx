'use client';
import { useLanguage } from '@/components/language-provider';
import { Button } from '@/components/ui/button';
import type { ElectrodeDesign, DesignResult } from '@/lib/design-decision';
import { coordinateReview } from './coordinate-review';
import { coordinateSourceFiles } from '@/contracts/coordinate-source.mjs';

export function CoordinateReviewPanel({ design, result }: { design: ElectrodeDesign; result: DesignResult | null }) {
  const { tx } = useLanguage(), review = coordinateReview(design, result);
  const source = design.source_metadata;
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(review, null, 2) + '\n'], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = 'eeg-coordinate-review.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <details className="mt-4 rounded-lg border p-4"><summary className="cursor-pointer font-medium">{tx('逐电极坐标检查')}</summary>
    <p className="mt-3 text-sm">{tx('坐标声明：Ernie原生空间，单位mm。此接口不执行坐标配准。')}</p>
    <p className="mt-2 break-words text-xs text-muted-foreground">{tx('坐标来源')} · {source ? coordinateSourceFiles(source) : design.name}</p>
    {source && <p className="mt-2 whitespace-pre-wrap text-xs text-muted-foreground">{source.coordinate_system_description}</p>}
    <p className="mt-2 text-xs text-muted-foreground">{tx(review.evaluated ? '合格表示已验证结果的逐点投影移动不超过现有2 mm限制；数值评分另行显示。' : '尚未评价；原输入坐标不能作为已投影合格的结果。')}</p>
    <div className="mt-3 max-h-96 overflow-auto"><table className="w-full min-w-[850px] text-left text-xs"><thead><tr>
      <th>{tx('电极')}</th><th>{tx('区域')}</th><th>{tx('原输入坐标（mm）')}</th><th>{tx('实际评价坐标（mm）')}</th><th>{tx('投影移动（mm）')}</th><th>{tx('坐标检查')}</th>
    </tr></thead><tbody>{review.rows.map(row => <tr className="border-t align-top" key={row.index}>
      <td className="py-2">{row.name}</td><td>{row.region}</td><td className="font-mono">{row.input_xyz_mm.join(', ')}</td><td className="font-mono">{row.evaluated_xyz_mm?.join(', ') ?? '—'}</td>
      <td className="font-mono" title={row.movement_mm === null ? undefined : String(row.movement_mm)}>{row.movement_mm === null ? '—' : row.movement_mm.toFixed(6)}</td>
      <td>{tx(row.status === 'not_evaluated' ? '未评价' : row.status === 'within_projection_limit' ? '合格' : '超出投影限制')}</td>
    </tr>)}</tbody></table></div>
    <Button className="mt-3" size="sm" variant="outline" onClick={download}>{tx('导出逐电极检查JSON')}</Button>
  </details>;
}
