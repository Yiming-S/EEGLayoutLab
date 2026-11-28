'use client';
import { useLanguage } from '@/components/language-provider';
import { OutcomeBadge } from '@/components/retention-bar';
import { qualification, type DecisionThresholds } from '@/lib/design-decision';
import { evaluationLabels } from '@/lib/layout-page';
import type { SavedRecord } from '@/lib/local-library';

/** The answer first: whether each layout meets the requirement, and how far apart they are. */
export function ComparisonConclusion({ a, b, thresholds }: { a?: SavedRecord; b?: SavedRecord; thresholds: DecisionThresholds }) {
  const { tx } = useLanguage();
  if (!a && !b) return null;
  const verdict = (record: SavedRecord, name: string) => {
    const q = qualification(record, thresholds);
    return { name, state: q.state, text: q.state === 'pass' ? `${name}均高于启用参考线` : q.state === 'missing' ? `${name}数据不完整：${q.missing.join('、')}`
      : `${name}低于参考线：${q.failed.join('、')}` };
  };
  const rows = [...(a ? [verdict(a, '方案A')] : []), ...(b ? [verdict(b, '方案B')] : [])];
  const passed = rows.filter(row => row.state === 'pass');
  const summary = rows.length < 2 ? (a ? '选择方案B后显示对比结论。' : '选择方案A后显示对比结论。')
    : passed.length === 2 ? '两个方案均高于全部启用参考线。'
    : passed.length === 1 ? `${passed[0].name}高于全部启用参考线。` : '两个方案均有分项低于当前参考线（全头64导仅作100%刻度，请按目标场景权衡）。';
  const fa = a?.metrics?.field_relative, fb = b?.metrics?.field_relative;
  const gap = a && b && Number.isFinite(fa) && Number.isFinite(fb) ? (fb! - fa!) * 100 : null;
  const sameConditions = a && b && JSON.stringify(evaluationLabels(a).slice(1)) === JSON.stringify(evaluationLabels(b).slice(1));
  return <section aria-label={tx('对比结论')} className="lab-panel border-l-4 border-l-primary">
    <h2 className="text-lg font-semibold">{tx(summary)}</h2>
    <ul className="mt-2 flex flex-wrap gap-2 text-sm">
      {rows.map(row => <li key={row.name}><OutcomeBadge outcome={row.state === 'pass' ? 'pass' : row.state === 'missing' ? 'undefined' : 'fail'} className="whitespace-normal text-sm">{tx(row.text)}</OutcomeBadge></li>)}
    </ul>
    {gap !== null && <p className="mt-2 text-sm">{tx(Math.abs(gap) < 0.005 ? '两个方案的信号重建保留率相同。'
      : gap > 0 ? `方案B的信号重建保留率比方案A高${gap.toFixed(2)}个百分点。` : `方案B的信号重建保留率比方案A低${(-gap).toFixed(2)}个百分点。`)}</p>}
    {a && b && !sameConditions && <p className="mt-2 text-sm text-muted-foreground">{tx('两条记录的评价条件不同，差值只作参考；同一条件下的对比请在布局详情页选择相同条件。')}</p>}
  </section>;
}
