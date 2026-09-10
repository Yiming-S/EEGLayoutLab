'use client';
import { useState } from 'react';
import { useLanguage } from './language-provider';

/** Unknown worker diagnostics remain available verbatim, beneath a localized status. */
export function RuntimeMessage({ message, status = 'failed' }: { message: string; status?: string }) {
  const { tx, locale } = useLanguage();
  const [showRaw, setShowRaw] = useState(false);
  const translated = tx(message);
  const needsRaw = locale === 'en' && /[\u3400-\u9fff]/.test(translated);
  if (!needsRaw) return <>{translated}</>;
  const summary = status === 'running' ? 'Computation in progress.'
    : status === 'queued' ? 'Waiting to start.'
      : status === 'completed' ? 'Computation completed.'
        : status === 'no_layout' ? 'No complete layout was found within this search budget.'
          : status === 'cancelling' ? 'Stopping computation.'
            : status === 'cancelled' ? 'Computation stopped.'
              : status === 'timeout' ? 'The computation reached its time limit.'
                : 'The operation could not be completed.';
  return <span>{summary}{' '}<button type="button" className="underline underline-offset-2" aria-expanded={showRaw} onClick={() => setShowRaw((v) => !v)}>Raw Details</button>
    {showRaw && <span className="mt-1 block whitespace-pre-wrap break-words text-xs" lang="zh-CN">{message}</span>}</span>;
}
