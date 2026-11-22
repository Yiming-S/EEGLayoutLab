'use client';
import type { ReactNode } from 'react';
import { Check, Minus, X } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { metricPercent } from '@/lib/ui-language';
import { cn } from '@/lib/utils';

export type Outcome = 'pass' | 'fail' | 'undefined';

const OUTCOME_STYLE: Record<Outcome, string> = {
  pass: 'bg-success-surface text-success',
  fail: 'bg-warning-surface text-warning',
  undefined: 'bg-secondary text-muted-foreground',
};

/** Pass or shortfall at a glance: colour, icon and words together, never colour alone. */
export function OutcomeBadge({ outcome, children, className }: { outcome: Outcome; children: ReactNode; className?: string }) {
  const Icon = outcome === 'pass' ? Check : outcome === 'fail' ? X : Minus;
  return <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap', OUTCOME_STYLE[outcome], className)}>
    <Icon aria-hidden className="size-3" strokeWidth={2.5} />{children}
  </span>;
}

/**
 * A retention ratio as a number and a bar against the requirement. The bar is
 * decorative; the number and the optional badge carry the reading.
 */
export function RetentionBar({ value, threshold, showBadge = false, className }: {
  value: number | null | undefined;
  /** Requirement as a ratio (0.9 for 90%); omitted when no requirement applies. */
  threshold?: number;
  showBadge?: boolean;
  className?: string;
}) {
  const { tx } = useLanguage();
  const valid = value != null && Number.isFinite(value);
  if (!valid) return <span className={cn('text-muted-foreground', className)}>{tx(metricPercent(value))}</span>;
  const outcome: Outcome = threshold == null ? 'undefined' : value >= threshold ? 'pass' : 'fail';
  return <span className={cn('block min-w-28', className)}>
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className="font-mono tabular-nums">{tx(metricPercent(value))}</span>
      {showBadge && threshold != null && <OutcomeBadge outcome={outcome}>{tx(outcome === 'pass' ? '达标' : '未达标')}</OutcomeBadge>}
    </span>
    <span aria-hidden className="relative mt-1.5 block h-1.5 w-full max-w-36 rounded-full bg-muted">
      <span className={cn('absolute inset-y-0 left-0 rounded-full', outcome === 'pass' ? 'bg-success' : outcome === 'fail' ? 'bg-warning' : 'bg-primary/60')}
        style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
      {threshold != null && <span className="absolute -inset-y-0.5 w-0.5 rounded-full bg-foreground/70" style={{ left: `calc(${Math.max(0, Math.min(1, threshold)) * 100}% - 1px)` }} />}
    </span>
  </span>;
}
