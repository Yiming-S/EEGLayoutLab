import { useLanguage } from '@/components/language-provider';
import { pct } from '@/lib/design-decision';
import { criticalElectrodes, robustnessRows, type RobustnessBlock, type RobustnessStats } from '@/lib/design-robustness';

const cell = (value: RobustnessStats | null) => value ? `${pct(value.median)} (P10 ${pct(value.p10)})` : '无有效试验';

/** Session robustness of one evaluated layout beside standard64 under the same draws. */
export function RobustnessPanel({ block, names }: { block: RobustnessBlock; names?: string[] }) {
  const { tx } = useLanguage();
  const rows = robustnessRows(block);
  const critical = criticalElectrodes(block, names);
  return (
    <div className="mt-5">
      <h4 className="font-semibold">{tx('跨会话稳健性')}</h4>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">
        {tx('重建保留率的中位数与P10，均相对未扰动的标准全头64；标准64在同一批随机抽样下计算。电极脱落后其余电极重新平均参考并重新估计；噪声不均时典型电极保持名义噪声，重建器已知各通道噪声；重新佩戴为整帽绕头中心随机轴旋转加2 mm独立抖动。')}
      </p>
      <table className="mt-2 w-full min-w-[560px] text-left text-sm">
        <thead><tr><th className="py-2">{tx('扰动')}</th><th>{tx('当前坐标')}</th><th>{tx('标准全头64')}</th></tr></thead>
        <tbody>
          {rows.map(row => (
            <tr key={row.label} className="border-t">
              <th className="py-2 font-normal">{tx(row.label)}{row.note && <span className="block text-xs text-muted-foreground">{tx(row.note)}</span>}</th>
              <td>{tx(cell(row.candidate))}</td>
              <td>{tx(cell(row.reference))}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {block.replacement.status === 'unavailable' && <p className="mt-2 text-xs text-muted-foreground">{tx(block.replacement.reason)}</p>}
      <p className="mt-3 text-sm">
        {tx('单个电极脱落影响最大的电极：')}
        {critical.map(item => `${item.name} ${pct(item.retention)}`).join('，')}
        {tx(`。标准64中位数${pct(block.dropout.single.reference.median)}。`)}
      </p>
    </div>
  );
}
