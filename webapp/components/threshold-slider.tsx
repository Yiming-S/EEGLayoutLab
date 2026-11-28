'use client';
import { useLanguage } from '@/components/language-provider';
import { TermHint } from '@/components/term-hint';
import type { Term } from '@/lib/term-hints';
import { cn } from '@/lib/utils';

const SCENARIO_PRESETS = [
  { value: 35, label: '轻便穿戴 35%' },
  { value: 60, label: '靶向脑区 60%' },
  { value: 85, label: '全脑高密 85%' },
] as const;

/**
 * The one control for a scenario reference target (AR / tau) on every page: name and
 * current value on one line, optional scenario quick presets, a precision-filled 1% step slider, and an optional note.
 */
export function ThresholdSlider({
  value,
  onChange,
  label = '场景目标参考线 τ',
  ariaLabel,
  hint,
  min = 10,
  max = 100,
  className,
  term,
}: {
  value: number;
  onChange: (value: number) => void;
  label?: string;
  /** Distinguishes several requirement sliders for assistive technology. */
  ariaLabel?: string;
  hint?: string;
  min?: number;
  max?: number;
  className?: string;
  /** A term to explain under the control; the explanation sits outside the label. */
  term?: Term;
}) {
  const { tx } = useLanguage();
  const ratio = Math.max(0, Math.min(1, (value - min) / Math.max(1, max - min)));
  const showPresets = min <= 35 && max >= 85;
  const control = (
    <div className={cn(!term && className)}>
      <label className="lab-label">
        <span className="flex items-center justify-between gap-3">
          <span>{tx(label)}</span>
          <span className="inline-flex items-center rounded border border-border bg-secondary/75 px-2 py-0.5 font-mono text-xs font-semibold tabular-nums text-foreground">
            {value}%
          </span>
        </span>
        <span className="relative mt-2.5 block">
          <span
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-0 h-1 -translate-y-1/2 rounded-l-full bg-primary"
            style={{ width: `${ratio * 100}%` }}
          />
          <input
            className="relative z-10 block w-full accent-primary"
            type="range"
            min={min}
            max={max}
            step={1}
            value={value}
            aria-label={tx(ariaLabel ?? label)}
            aria-valuetext={`${value}%`}
            onChange={(event) => onChange(Number(event.target.value))}
          />
        </span>
        <span
          aria-hidden
          className="mt-0.5 flex justify-between font-mono text-[10px] font-normal text-muted-foreground tabular-nums"
        >
          <span>{min}%</span>
          <span>50%</span>
          <span>{max}%</span>
        </span>
      </label>
      {showPresets && (
        <fieldset className="mt-1.5 flex flex-wrap gap-1" aria-label={tx('典型场景参考档位')}>
          {SCENARIO_PRESETS.map((preset) => (
            <button
              key={preset.value}
              type="button"
              onClick={() => onChange(preset.value)}
              aria-pressed={value === preset.value}
              className={cn(
                'rounded-md border px-2 py-0.5 text-[11px] font-medium transition-colors',
                value === preset.value
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border/80 bg-card text-muted-foreground hover:border-foreground/30 hover:text-foreground',
              )}
            >
              {tx(preset.label)}
            </button>
          ))}
        </fieldset>
      )}
      {hint && (
        <span className="mt-1.5 block text-xs font-normal leading-5 text-muted-foreground">
          {tx(hint)}
        </span>
      )}
    </div>
  );
  return term ? (
    <div className={className}>
      {control}
      <TermHint term={term} ar={value} className="mt-1.5" />
    </div>
  ) : (
    control
  );
}
