'use client';
import { useLanguage } from '@/components/language-provider';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useId, type ReactNode } from 'react';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Button } from '@/components/ui/button';
import { MASK_NAMES } from '@/lib/ui-language';
import { REGION_COUNTS } from '@/lib/lab-workflow';
import { placementChoices, placementDesignLink, type PlacementChoice, type PlacementProtocol } from '@/lib/placement-options';
import protocolData from '@/public/data/experiment_protocol_v2.json';

export function LocationRadios({ label, value, onChange, options, compact = false }: {
  label: string; value: string; onChange: (value: string) => void;
  options: Array<{ id: string; label: string; description?: string }>; compact?: boolean;
}) {
  const { tx } = useLanguage();
  const id = useId();
  return <fieldset className="min-w-0"><legend className="mb-3 text-sm font-semibold">{tx(label)}</legend>
    <RadioGroup value={value} onValueChange={(v) => onChange(String(v))} className={compact ? 'grid grid-cols-3 gap-2' : 'grid gap-3 sm:grid-cols-2'}>
      {tx(options.map((option, i) => <label key={option.id} htmlFor={id + '-' + i} className={`flex cursor-pointer items-start gap-2 rounded-lg border p-3 text-sm leading-6 ${value === option.id ? 'border-primary bg-primary/5 text-foreground' : 'border-border bg-card hover:border-primary/50'}`}>
        <RadioGroupItem id={id + '-' + i} value={option.id} className="mt-1" />
        <span><span className="font-medium">{tx(option.label)}</span>{tx(option.description && <span className="mt-1 block text-sm text-muted-foreground">{tx(option.description)}</span>)}</span>
      </label>))}
    </RadioGroup>
  </fieldset>;
}

export function HomePlacementOptions({ domain, setDomain, children }: { domain: string; setDomain: (value: string) => void; children?: ReactNode }) {
  const { tx } = useLanguage();
  return <section className="lab-panel mb-4 space-y-3" aria-labelledby="placement-options-title">
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
  return <section id="create-layout" className="lab-panel mt-6 scroll-mt-[calc(var(--workspace-header-height,160px)+16px)] space-y-4" aria-labelledby="create-layout-title">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 id="create-layout-title" className="text-lg font-semibold">{tx('按部位创建布局')}</h2><span className="rounded-full bg-secondary px-3 py-1 text-xs text-muted-foreground">{tx('每区半径约束 · 新建设计')}</span></div>
      <p className="mt-1 text-sm leading-6 text-muted-foreground">{tx("以下组合直接填入设计条件，保留AR。每区半径初始为35 mm，可再调整；不沿用上方总面积约束、不自动计算。")}</p>
      <div className="mt-3 space-y-3">{tx(REGION_COUNTS.map((count) => <div key={count} className="grid gap-2 sm:grid-cols-[110px_1fr]">
        <p className="pt-2 text-sm font-semibold">{tx(`${count}个区域`)}<span className="mt-1 block text-xs font-normal text-muted-foreground">{tx(Array.from({ length: count }, (_, i) => Math.floor(64 / count) + Number(i < 64 % count)).join('+'))} {tx(" 电极")}</span></p>
        <div className="flex flex-wrap gap-2">{tx(placementChoices(protocolData as PlacementProtocol, count, MASK_NAMES).filter((c) => c.mode === 'preset').map((c) => <a key={c.id} href={placementDesignLink(c, count, ar)} aria-label={tx(`用此组合创建设计：${c.label}`)} className="rounded-lg border bg-card px-3 py-2 text-sm leading-6 text-foreground hover:border-primary hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"><span className="block">{tx(c.label)}</span><span className="block text-xs text-primary">{tx('创建设计 →')}</span></a>))}</div>
      </div>))}</div>
      <a href={'/design?ar=' + ar} className="mt-4 inline-block text-sm font-semibold text-primary underline underline-offset-4">{tx("不使用预设：逐个区域从9个部位自由组合 →")}</a>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{tx("位置范围按模型坐标定义。布局构造后评价三项指标；眼电干扰在信号仿真页单独设置。")}</p>
  </section>;
}

export function DesignPlacementOptions({ count, choices, selected, slots, onSelect, onSlot, onCount }: {
  count: number; choices: PlacementChoice[]; selected: string; slots: string[];
  onSelect: (choice: PlacementChoice) => void; onSlot: (index: number, value: string) => void;
  onCount: (count: number) => void;
}) {
  const { tx } = useLanguage();
  return <section className="lab-panel mb-4 space-y-5" aria-label={tx("平铺的布置范围与区域部位")}>
    <div><h2 className="text-lg font-semibold">{tx("1 · 选择区域数与允许布置范围")}</h2><fieldset className="mt-3 flex flex-wrap gap-2" aria-label={tx("电极分布区域数")}>{tx(REGION_COUNTS.map((r) => <Button key={r} variant={count === r ? 'default' : 'outline'} aria-pressed={count === r} onClick={() => onCount(r)}>{tx(`${r}个区域`)}</Button>))}</fieldset><p className="mt-2 text-sm text-muted-foreground">{tx("总电极数始终64；下方每个区域标明分配数量。")}</p></div>
    <LocationRadios label={tx("允许布置范围")} value={selected} onChange={(id) => { const c = choices.find((v) => v.id === id); if (c) onSelect(c); }} options={choices.filter((c) => c.mode !== 'preset')} />
    <div><p className="mb-2 text-sm font-semibold">{tx("常用组合 · ")}{tx(`${count}个区域`)}</p><div className="flex flex-wrap gap-2">{tx(choices.filter((c) => c.mode === 'preset').map((c) => <Button key={c.id} variant={selected === c.id ? 'default' : 'outline'} className="h-auto whitespace-normal py-2 text-left" aria-pressed={selected === c.id} onClick={() => onSelect(c)}>{tx(c.label)}</Button>))}</div></div>
    <div className="border-t pt-4">
      <h2 className="text-base font-semibold">{tx("自由组合部位 · 每个区域选一项")}</h2>
      <p className="mt-1 text-sm leading-6 text-muted-foreground">{tx("可选择预设之外的组合，也可在多个区域选择同一部位。顺序对应各区电极数；仍须满足不同电极、最小间距与区域分离要求。")}</p>
      <div className="mt-4 grid items-start gap-5 lg:grid-cols-2 xl:grid-cols-3">{tx(Array.from({ length: count }, (_, i) => <LocationRadios key={i} label={tx(`区域${i + 1} · ${Math.floor(64 / count) + Number(i < 64 % count)}个电极`)} value={slots[i] ?? ''} onChange={(v) => onSlot(i, v)} options={Object.entries(MASK_NAMES).map(([id, label]) => ({ id, label }))} compact />))}</div>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">{tx("所有部位均按模型坐标近似划定。耳后邻近区覆盖近耳后外侧，耳周扩展区覆盖更大范围，眶周上外侧排除模型中的眼球近似区。眼电干扰在信号仿真页单独评价。")}</p>
    </div>
  </section>;
}
