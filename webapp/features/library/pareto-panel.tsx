import { useMemo, useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { Button } from '@/components/ui/button';
import type { CatalogEntry } from '@/lib/records-catalog';
import { DEFAULT_OBJECTIVES, PARETO_OBJECTIVES, comparisonGroup, paretoAnalysis, summaryObjectives, type ObjectiveId } from '@/lib/pareto';
import { conductivityScenarioLabel, dataPriorLabel, noiseModelLabel } from '../../contracts/scientific-options.mjs';

type LayoutEntry = Extract<CatalogEntry, { summary: unknown }>;
const format = (value: number, unit: string) => unit === 'ratio' ? `${(100 * value).toFixed(2)}%` : unit === 'mm' ? `${value.toFixed(1)} mm` : `${value.toFixed(1)} cm²`;
const groupLabel = (key: string) => {
  const g = JSON.parse(key) as { noise: unknown; scenario: string | null; head: string | null; prior?: unknown };
  return [g.prior ? dataPriorLabel(g.prior) : noiseModelLabel(g.noise ?? undefined), g.scenario ? conductivityScenarioLabel(g.scenario) : '',
    g.head ? `头模 ${g.head}` : ''].filter(Boolean).join(' · ');
};

/** Pareto ranks of the listed layouts under chosen objectives; one evaluation condition at a time. */
export function ParetoPanel({ entries, title, onChoose }: { entries: CatalogEntry[]; title: (entry: CatalogEntry) => string; onChoose: (id: string) => void }) {
  const { tx } = useLanguage();
  const [objectives, setObjectives] = useState<ObjectiveId[]>(DEFAULT_OBJECTIVES);
  const [axes, setAxes] = useState<[ObjectiveId, ObjectiveId]>(['field', 'localization']);
  const groups = useMemo(() => {
    const map = new Map<string, LayoutEntry[]>();
    for (const entry of entries) {
      if (!('summary' in entry)) continue;
      const key = comparisonGroup(entry.summary);
      if (key) map.set(key, [...(map.get(key) ?? []), entry as LayoutEntry]);
    }
    return [...map.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [entries]);
  const [groupKey, setGroupKey] = useState('');
  const active = groups.find(([key]) => key === groupKey) ?? groups[0];
  const analysis = useMemo(() => active && objectives.length
    ? paretoAnalysis(active[1].map(item => ({ item, values: summaryObjectives(item.summary) })), objectives) : null, [active, objectives]);
  if (!groups.length) return null;
  const toggle = (id: ObjectiveId) => setObjectives(list => list.includes(id) ? list.filter(value => value !== id) : PARETO_OBJECTIVES.map(o => o.id).filter(o => o === id || list.includes(o)));
  const front = analysis?.rows.filter(row => row.rank === 1) ?? [];
  const x = PARETO_OBJECTIVES.find(o => o.id === axes[0])!, y = PARETO_OBJECTIVES.find(o => o.id === axes[1])!;
  const plotted = (active?.[1] ?? []).map(item => ({ item, v: summaryObjectives(item.summary) }))
    .filter(p => Number.isFinite(p.v[x.id]) && Number.isFinite(p.v[y.id])) as { item: LayoutEntry; v: Record<ObjectiveId, number> }[];
  const rankOf = new Map(analysis?.rows.map(row => [row.item.id, row.rank]) ?? []);
  const span = (values: number[]) => { const lo = Math.min(...values), hi = Math.max(...values), pad = (hi - lo || Math.abs(hi) || 1) * .08; return [lo - pad, hi + pad]; };
  const [x0, x1] = span(plotted.map(p => p.v[x.id])), [y0, y1] = span(plotted.map(p => p.v[y.id]));
  const W = 520, H = 300, L = 56, B = 36;
  const px = (v: number) => L + (v - x0) / (x1 - x0) * (W - L - 12), py = (v: number) => H - B - (v - y0) / (y1 - y0) * (H - B - 12);
  return (
    <details className="lab-panel mt-4">
      <summary className="cursor-pointer font-semibold">{tx('多目标比较（Pareto前沿）')}</summary>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">
        {tx('在当前筛选的已完成布局中，找出没有被其他布局在全部所选目标上同时超过的方案（第1层）。只比较同一评价条件下的记录；历史实验按原协议单独解释。')}
      </p>
      <div className="mt-3 grid gap-3 md:grid-cols-[1fr_2fr]">
        <label className="lab-label">{tx('评价条件')}
          <select className="lab-select" value={active?.[0] ?? ''} onChange={event => setGroupKey(event.target.value)}>
            {groups.map(([key, list]) => <option key={key} value={key}>{tx(groupLabel(key))} · {tx(`${list.length}条`)}</option>)}
          </select>
        </label>
        <fieldset className="text-sm"><legend className="lab-label">{tx('比较目标')}</legend>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
            {PARETO_OBJECTIVES.map(o => <label key={o.id} className="flex items-center gap-1.5"><input type="checkbox" checked={objectives.includes(o.id)} onChange={() => toggle(o.id)} />{tx(o.label)}{tx(o.direction === 'min' ? '（越小越好）' : '')}</label>)}
          </div>
        </fieldset>
      </div>
      {!objectives.length ? <p className="mt-3 text-sm text-warning">{tx('请至少选择一个目标。')}</p> : analysis && <>
        <p className="mt-3 text-sm">{tx(`${analysis.rows.length}条记录参与比较，${front.length}条位于Pareto前沿。`)}
          {analysis.excluded.length > 0 && <span className="text-muted-foreground">{tx(`另有${analysis.excluded.length}条缺少所选目标（如面积只属于搜索记录，稳健性只属于加评稳健性的坐标评价），未参与。`)}</span>}</p>
        <div className="mt-2 overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm">
          <thead><tr className="border-b text-muted-foreground"><th className="py-2">{tx('层')}</th><th>{tx('布局')}</th>{analysis.objectives.map(o => <th key={o.id}>{tx(o.label)}</th>)}<th><span className="sr-only">{tx('操作')}</span></th></tr></thead>
          <tbody>{analysis.rows.slice(0, 20).map(row => (
            <tr key={row.item.id} className="border-b last:border-0">
              <td className="py-2 tabular-nums">{row.rank}</td>
              <td>{title(row.item)}{row.dominated_by > 0 && <span className="block text-xs text-muted-foreground">{tx(`被${row.dominated_by}条记录全面超过`)}</span>}</td>
              {row.values.map((value, k) => <td key={k} className="tabular-nums">{format(value, analysis.objectives[k].unit)}</td>)}
              <td><Button size="sm" variant="outline" onClick={() => onChoose(row.item.id)}>{tx('查看结果')}</Button></td>
            </tr>))}</tbody>
        </table></div>
        {analysis.rows.length > 20 && <p className="mt-1 text-xs text-muted-foreground">{tx(`只列出前20条，共${analysis.rows.length}条。`)}</p>}
      </>}
      <div className="mt-4 flex flex-wrap gap-3 text-sm">
        {(['横轴', '纵轴'] as const).map((name, k) => <label key={name} className="lab-label">{tx(name)}
          <select className="lab-select" value={axes[k]} onChange={event => setAxes(a => (k ? [a[0], event.target.value as ObjectiveId] : [event.target.value as ObjectiveId, a[1]]))}>
            {PARETO_OBJECTIVES.map(o => <option key={o.id} value={o.id}>{tx(o.label)}</option>)}
          </select></label>)}
      </div>
      {plotted.length > 0 ? <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full max-w-[640px]">
        <title>{tx('两项目标的散点图，前沿方案以实心点表示')}</title>
        <line x1={L} y1={H - B} x2={W - 12} y2={H - B} stroke="currentColor" strokeOpacity=".3" />
        <line x1={L} y1={12} x2={L} y2={H - B} stroke="currentColor" strokeOpacity=".3" />
        {[x0, x1].map((v, i) => <text key={'x' + i} x={px(v)} y={H - B + 16} fontSize="11" textAnchor={i ? 'end' : 'start'} fill="currentColor" opacity=".7">{format(v, x.unit)}</text>)}
        {[y0, y1].map((v, i) => <text key={'y' + i} x={L - 4} y={py(v) + (i ? 10 : 0)} fontSize="11" textAnchor="end" fill="currentColor" opacity=".7">{format(v, y.unit)}</text>)}
        <text x={(W + L) / 2} y={H - 4} fontSize="12" textAnchor="middle" fill="currentColor">{tx(x.label)}</text>
        {plotted.map(p => { const rank = rankOf.get(p.item.id); return (
          <circle key={p.item.id} cx={px(p.v[x.id])} cy={py(p.v[y.id])} r={rank === 1 ? 5 : 3.5} className="cursor-pointer"
            fill={rank === 1 ? 'var(--primary)' : 'transparent'} stroke="var(--primary)" strokeOpacity={rank === 1 ? 1 : .55} onClick={() => onChoose(p.item.id)}>
            <title>{title(p.item)}</title>
          </circle>); })}
      </svg> : <p className="mt-2 text-sm text-muted-foreground">{tx('当前条件下没有同时具有这两项目标的记录。')}</p>}
      <p className="mt-1 text-xs text-muted-foreground">{tx('纵轴：')}{tx(y.label)}{tx('。实心点为所选全部目标下的第1层；点击打开记录。')}</p>
    </details>
  );
}
