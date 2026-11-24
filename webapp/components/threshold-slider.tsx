'use client';
import { useLanguage } from '@/components/language-provider';
import { TermHint } from '@/components/term-hint';
import type { Term } from '@/lib/term-hints';
import { cn } from '@/lib/utils';

/**
 * The one control for a retention requirement (AR) on every page: name and
 * current value on one line, a 1% step slider, and an optional note.
 */
export function ThresholdSlider({ value, onChange, label = '最低保留要求', ariaLabel, hint, min = 10, max = 100, className, term }: {
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
  const control = <label className={cn('lab-label', !term && className)}>
    <span className="flex items-baseline justify-between gap-3"><span>{tx(label)}</span><span className="font-mono text-base font-semibold tabular-nums text-primary">{value}%</span></span>
    <input className="mt-3 w-full accent-primary" type="range" min={min} max={max} step={1} value={value}
      aria-label={tx(ariaLabel ?? label)} aria-valuetext={`${value}%`} onChange={event => onChange(Number(event.target.value))} />
    <span aria-hidden className="flex justify-between text-xs font-normal text-muted-foreground tabular-nums"><span>{min}%</span><span>{max}%</span></span>
    {hint && <span className="mt-1 block text-xs font-normal leading-5 text-muted-foreground">{tx(hint)}</span>}
  </label>;
  return term ? <div className={className}>{control}<TermHint term={term} ar={value} className="mt-1.5" /></div> : control;
}
