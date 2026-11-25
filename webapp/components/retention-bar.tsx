'use client';
import type { ReactNode } from 'react';
import { Check, Minus, X } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { metricPercent } from '@/lib/ui-language';
import { cn } from '@/lib/utils';

export type Outcome = 'pass' | 'fail' | 'undefined';

const OUTCOME_STYLE: Record<Outcome, string> = {
  pass: 'bg-success-surface text-success ring-1 ring-inset ring-success/25',
  fail: 'bg-secondary/90 text-foreground/85 ring-1 ring-inset ring-border',
  undefined: 'bg-secondary/70 text-muted-foreground ring-1 ring-inset ring-border/70',
};

/** Pass or shortfall at a glance: colour, icon and words together, never colour alone. */
export function OutcomeBadge({
  outcome,
  children,
  className,
}: {
  outcome: Outcome;
  children: ReactNode;
  className?: string;
}) {
  const Icon = outcome === 'pass' ? Check : outcome === 'fail' ? X : Minus;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium whitespace-nowrap',
        OUTCOME_STYLE[outcome],
        className,
      )}
    >
      <Icon aria-hidden className="size-3" strokeWidth={2.25} />
      {children}
    </span>
  );
}

/**
 * A retention ratio as a number and a bar against the requirement. The bar is
 * decorative; the number and the optional badge carry the reading.
 */
export function RetentionBar({
  value,
  threshold,
  showBadge = false,
  className,
}: {
  value: number | null | undefined;
  /** Requirement as a ratio (0.9 for 90%); omitted when no requirement applies. */
  threshold?: number;
  showBadge?: boolean;
  className?: string;
}) {
  const { tx } = useLanguage();
  const valid = value != null && Number.isFinite(value);
  if (!valid)
    return (
      <span className={cn('text-muted-foreground', className)}>
        {tx(metricPercent(value))}
      </span>
    );
  const outcome: Outcome =
    threshold == null ? 'undefined' : value >= threshold ? 'pass' : 'fail';
  return (
    <span className={cn('block min-w-28', className)}>
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-mono text-[0.8125rem] font-medium tabular-nums">
          {tx(metricPercent(value))}
        </span>
        {showBadge && threshold != null && (
          <OutcomeBadge outcome={outcome}>
            {tx(outcome === 'pass' ? '达标' : '未达标')}
          </OutcomeBadge>
        )}
      </span>
      <span
        aria-hidden
        className="relative mt-1.5 block h-1.5 w-full max-w-36 rounded-full bg-secondary"
      >
        <span
          className={cn(
            'absolute inset-y-0 left-0 rounded-full transition-[width] duration-200',
            outcome === 'pass'
              ? 'bg-success'
              : outcome === 'fail'
                ? 'bg-foreground/35'
                : 'bg-foreground/65',
          )}
          style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
        />
        {threshold != null && (
          <span
            className="absolute -inset-y-0.5 w-0.5 rounded-full bg-foreground/85 shadow-[0_0_0_1px_var(--card)]"
            style={{
              left: `calc(${Math.max(0, Math.min(1, threshold)) * 100}% - 1px)`,
            }}
          />
        )}
      </span>
    </span>
  );
}
