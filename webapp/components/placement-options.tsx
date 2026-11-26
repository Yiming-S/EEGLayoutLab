'use client';
import { useLanguage } from '@/components/language-provider';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { ArrowUpRight, ChevronDown } from 'lucide-react';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Button } from '@/components/ui/button';
import { MASK_NAMES } from '@/lib/ui-language';
import { REGION_COUNTS } from '@/lib/lab-workflow';
import { cn } from '@/lib/utils';
import { placementChoices, placementDesignLink, type PlacementChoice, type PlacementProtocol } from '@/lib/placement-options';
import { apiFetch } from '@/client/task-client';

export function LocationRadios({ label, value, onChange, options, compact = false, stacked = false }: {
  label: string; value: string; onChange: (value: string) => void;
  options: Array<{ id: string; label: string; description?: string }>; compact?: boolean;
  /** One option per row, for narrow side panels. */
  stacked?: boolean;
}) {
  const { tx } = useLanguage();
  const id = useId();
  return <fieldset className="min-w-0"><legend className="mb-2.5 text-sm font-semibold text-foreground">{tx(label)}</legend>
    <RadioGroup value={value} onValueChange={(v) => onChange(String(v))} className={stacked ? 'grid gap-2' : compact ? 'grid grid-cols-3 gap-2' : 'grid gap-2.5 sm:grid-cols-2'}>
      {tx(options.map((option, i) => <label key={option.id} htmlFor={id + '-' + i} className={cn(
        'flex cursor-pointer items-start gap-2.5 rounded-xl border p-3 text-sm leading-5 transition-all',
        value === option.id
          ? 'border-primary/65 bg-primary/[0.06] text-foreground shadow-[0_1px_3px_rgba(15,46,58,0.06),inset_0_0_0_1px_color-mix(in_oklch,var(--primary)_20%,transparent)]'
          : 'border-border/80 bg-card/90 hover:border-primary/35 hover:bg-muted/35',
      )}>
        <RadioGroupItem id={id + '-' + i} value={option.id} className="mt-0.5" />
        <span><span className="font-medium">{tx(option.label)}</span>{tx(option.description && <span className="mt-1 block text-xs leading-5 text-muted-foreground">{tx(option.description)}</span>)}</span>
      </label>))}
    </RadioGroup>
  </fieldset>;
}

export function HomePlacementOptions({ domain, setDomain, children }: { domain: string; setDomain: (value: string) => void; children?: ReactNode }) {
  const { tx } = useLanguage();
  return <section className="lab-panel mb-5 space-y-4" aria-labelledby="placement-options-title">
    <div className="grid items-center gap-4 md:grid-cols-[1fr_2fr]">
    <div><h2 id="placement-options-title" className="text-base font-semibold">{tx('查看已有结果')}</h2><p className="mt-1 text-xs text-muted-foreground">{tx('总面积约束 · 已计算数据')}</p></div>
    <LocationRadios label={tx("允许布置范围")} value={domain} onChange={setDomain} options={[
      { id: 'whole_scalp_free', label: '全头候选区' },
      { id: 'low_hair_free', label: '少毛发候选区（模型近似）' },
    ]} />
    </div>
    {children}
  </section>;
}

export function PlacementDesignPresets({ ar }: { ar: number }) {
  const { tx } = useLanguage();
  const [protocolData, setProtocolData] = useState<PlacementProtocol | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    apiFetch('/data/experiment_protocol_v2.json', { signal: controller.signal })
      .then(async (response) => { if (!response.ok) throw new Error('protocol'); return response.json() as Promise<PlacementProtocol>; })
      .then(setProtocolData)
      .catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, []);
  return <section id="create-layout" className="lab-panel mt-6 scroll-mt-[calc(var(--workspace-header-height,160px)+16px)] space-y-4" aria-labelledby="create-layout-title">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 id="create-layout-title" className="text-lg font-semibold">{tx('按部位创建布局')}</h2><span className="lab-chip">{tx('每区半径约束 · 新建设计')}</span></div>
      <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">{tx("以下组合直接填入设计条件，保留AR。每区半径初始为35 mm，可再调整；不沿用上方总面积约束、不自动计算。")}</p>
      {!protocolData && <p className="text-sm text-muted-foreground">{tx(error ? '部位组合未载入，可进入布局设计重新读取。' : '正在读取部位组合…')}</p>}
      <div className="mt-3 space-y-2.5">{protocolData && tx(REGION_COUNTS.map((count) => <div key={count} className="grid gap-3 rounded-xl border border-border/65 bg-muted/30 p-3.5 sm:grid-cols-[120px_1fr]">
        <p className="pt-1 text-sm font-semibold">{tx(`${count}个区域`)}<span className="mt-0.5 block font-mono text-xs font-normal text-muted-foreground tabular-nums">{tx(Array.from({ length: count }, (_, i) => Math.floor(64 / count) + Number(i < 64 % count)).join('+'))} {tx(" 电极")}</span></p>
        <div className="flex flex-wrap gap-2">{tx(placementChoices(protocolData as PlacementProtocol, count, MASK_NAMES).filter((c) => c.mode === 'preset').map((c) => <a key={c.id} href={placementDesignLink(c, count, ar)} aria-label={tx(`用此组合创建设计：${c.label}`)} className="group rounded-xl border border-border/80 bg-card px-3.5 py-2 text-sm leading-5 text-foreground shadow-2xs transition-all hover:-translate-y-px hover:border-primary/50 hover:shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"><span className="block font-medium group-hover:text-primary">{tx(c.label)}</span><span className="mt-1 inline-flex items-center gap-0.5 text-xs font-medium text-primary">{tx('创建设计 →')}</span></a>))}</div>
      </div>))}</div>
      <div className="pt-1">
        <a href={'/design?ar=' + ar} className="lab-link-pill text-sm">{tx("不使用预设：逐个区域从9个部位自由组合 →")}<ArrowUpRight aria-hidden className="size-3.5" /></a>
      </div>
      <p className="text-xs leading-5 text-muted-foreground">{tx("位置范围按模型坐标定义。布局构造后评价三项指标；眼电干扰在信号仿真页单独设置。")}</p>
  </section>;
}

const PLACEMENT_MODES = [
  { id: 'whole_surface', label: '全头候选区', description: '不限制毛发位置，由算法选择区域。' },
  { id: 'low_hair', label: '少毛发候选区（模型近似）', description: '只在耳后、前额与眶周的近似少毛发范围内选择。' },
  { id: 'regions', label: '指定部位组合', description: '为每个区域指定部位：选常用组合，或逐区自由组合。' },
] as const;

/** Placement is one decision: a free domain, or named locations for every region. */
export function DesignPlacementOptions({ count, choices, selected, slots, onSelect, onSlot, onCount, compact = false }: {
  count: number; choices: PlacementChoice[]; selected: string; slots: string[];
  onSelect: (choice: PlacementChoice) => void; onSlot: (index: number, value: string) => void;
  onCount: (count: number) => void;
  compact?: boolean;
}) {
  const { tx } = useLanguage();
  const presets = choices.filter((c) => c.mode === 'preset');
  const [customOpen, setCustomOpen] = useState(() => slots.some(Boolean) && !presets.some((choice) => choice.id === selected));
  const lastRegions = useRef<PlacementChoice | null>(null);
  const current = choices.find((c) => c.id === selected);
  // Switching back from a free domain restores the last named combination.
  useEffect(() => { if (current?.mode === 'preset') lastRegions.current = current; }, [current]);
  const mode = selected === 'whole_surface' || selected === 'low_hair' ? selected : 'regions';
  const pickMode = (id: string) => {
    if (id !== 'regions') { const c = choices.find((v) => v.id === id); if (c) onSelect(c); return; }
    const previous = lastRegions.current;
    const next = previous && presets.some((c) => c.id === previous.id) ? previous : presets[0];
    if (next) onSelect(next); else setCustomOpen(true);
  };
  return <section className={compact ? 'mb-4 space-y-4' : 'lab-panel mb-4 space-y-5'} aria-label={tx("布置方式与区域部位")}>
    <div>
      <h2 className="text-base font-semibold">{tx("1 · 选择区域数与布置方式")}</h2>
      <fieldset className="mt-2.5 flex flex-wrap gap-1.5 rounded-xl border border-border/75 bg-muted/55 p-1" aria-label={tx("电极分布区域数")}>
        {tx(REGION_COUNTS.map((r) => <Button key={r} size="sm" variant={count === r ? 'default' : 'ghost'} className="flex-1 px-2" aria-pressed={count === r} onClick={() => onCount(r)}>{tx(`${r}个区域`)}</Button>))}
      </fieldset>
      <p className="mt-2 text-xs leading-5 text-muted-foreground">{tx("总电极数始终64；下方每个区域标明分配数量。")}</p>
    </div>
    <LocationRadios label={tx("布置方式")} value={mode} onChange={pickMode} options={PLACEMENT_MODES.map((m) => ({ ...m }))} stacked={compact} />
    {mode === 'regions' && <div className="space-y-3.5 rounded-xl border border-primary/25 bg-primary/[0.035] p-3.5">
      <div><p className="mb-2 text-xs font-semibold tracking-wide text-foreground/90">{tx("常用组合 · ")}{tx(`${count}个区域`)}</p><div className="flex flex-wrap gap-1.5">{tx(presets.map((c) => <Button key={c.id} size="sm" variant={selected === c.id ? 'default' : 'outline'} className="h-auto whitespace-normal py-1.5 text-left" aria-pressed={selected === c.id} onClick={() => onSelect(c)}>{tx(c.label)}</Button>))}</div></div>
      <details className="group/custom border-t border-border/70 pt-3" open={customOpen} onToggle={(event) => setCustomOpen(event.currentTarget.open)}>
        <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-semibold select-none [&::-webkit-details-marker]:hidden">
          <span>{tx("自由组合部位 · 每个区域选一项")}</span>
          <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open/custom:rotate-180" />
        </summary>
        <p className="mt-1.5 text-xs leading-5 text-muted-foreground">{tx("可选择预设之外的组合，也可在多个区域选择同一部位。顺序对应各区电极数；仍须满足不同电极、最小间距与区域分离要求。")}</p>
        <div className={'mt-3.5 grid items-start gap-4 ' + (compact ? '' : 'lg:grid-cols-2 xl:grid-cols-3')}>{tx(Array.from({ length: count }, (_, i) => <LocationRadios key={i} label={tx(`区域${i + 1} · ${Math.floor(64 / count) + Number(i < 64 % count)}个电极`)} value={slots[i] ?? ''} onChange={(v) => onSlot(i, v)} options={Object.entries(MASK_NAMES).map(([id, label]) => ({ id, label }))} compact />))}</div>
        <p className="mt-3 text-xs leading-5 text-muted-foreground">{tx("所有部位均按模型坐标近似划定。耳后邻近区覆盖近耳后外侧，耳周扩展区覆盖更大范围，眶周上外侧排除模型中的眼球近似区。眼电干扰在信号仿真页单独评价。")}</p>
      </details>
    </div>}
  </section>;
}
