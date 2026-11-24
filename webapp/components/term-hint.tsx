'use client';
import { useId, useState } from 'react';
import { CircleHelp } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { methodLink, parseAR } from '@/lib/lab-workflow';
import { TERMS, type Term } from '@/lib/term-hints';
import { cn } from '@/lib/utils';

/**
 * A question beside a term that opens a short definition in place, with a link to
 * the method chapter. The link returns to the page it was opened from.
 */
export function TermHint({ term, ar, className }: { term: Term; ar?: number; className?: string }) {
  const { tx } = useLanguage();
  const id = useId();
  // Read on demand: the address is only known in the browser, after the reader asks.
  const [href, setHref] = useState<string | null>(null);
  const { question, text, hash } = TERMS[term];
  const toggle = () => setHref(open => open ? null : methodLink(window.location.pathname + window.location.search,
    ar ?? parseAR(new URLSearchParams(window.location.search).get('ar')), hash));
  return <span className={cn('block text-xs font-normal', className)}>
    <button type="button" aria-expanded={!!href} aria-controls={id} onClick={toggle}
      onKeyDown={event => { if (event.key === 'Escape' && href) { event.stopPropagation(); setHref(null); } }}
      className="inline-flex items-center gap-1 rounded text-muted-foreground underline decoration-dotted underline-offset-4 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
      <CircleHelp aria-hidden className="size-3.5" />{tx(question)}
    </button>
    {href && <span id={id} role="note" className="mt-1 block leading-5 text-muted-foreground">
      {tx(text)} <a href={href} className="text-primary underline underline-offset-4">{tx('详细说明')}</a>
    </span>}
  </span>;
}
