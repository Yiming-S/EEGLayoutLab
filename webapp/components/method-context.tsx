'use client';
import { useLanguage } from '@/components/language-provider';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useState, type ReactNode } from 'react';
import { parseAR } from '@/lib/lab-workflow';
import { isRetentionGuideHash } from '@/lib/retention-guide';
import { isCopyrightHash } from '@/lib/copyright';
import { isSimulationGuideHash } from '@/lib/simulation-guide';
import { safeReturnHref } from '@/lib/ui-language';
export function MethodBackLink() {
  const { tx } = useLanguage();
  const [href, setHref] = useState('/');
  useEffect(() => {
    const restore = () => { const q = new URLSearchParams(window.location.search); setHref(safeReturnHref(q.get('returnTo'), '/?ar=' + parseAR(q.get('ar')))); };
    restore(); window.addEventListener('popstate', restore); return () => window.removeEventListener('popstate', restore);
  }, []);
  return <a href={href} className="mb-4 inline-block text-sm font-semibold text-primary">{tx("← 返回刚才的页面与设置")}</a>;
}
export function TechnicalDetails({ children }: { children: ReactNode }) {
  const { tx } = useLanguage();
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const reveal = () => {
      const hash = window.location.hash;
      if (hash && !isRetentionGuideHash(window.location.hash) && !isCopyrightHash(window.location.hash) && !isSimulationGuideHash(window.location.hash)
        && !['#electrode-editor', '#design-decision', '#source-field-interaction', '#model-terms'].includes(hash)) setOpen(true);
    };
    reveal(); window.addEventListener('hashchange', reveal); return () => window.removeEventListener('hashchange', reveal);
  }, []);
  useEffect(() => {
    if (!open || !window.location.hash) return;
    const frame = window.requestAnimationFrame(() => {
      const target = document.getElementById(window.location.hash.slice(1));
      if (target?.closest('[data-technical-details]')) target.scrollIntoView({ block: 'start' });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open]);
  return <details data-technical-details open={open} onToggle={(e) => setOpen(e.currentTarget.open)} className="rounded-xl border bg-card p-5"><summary className="cursor-pointer text-lg font-semibold">{tx("技术详情、历史实验与验证协议")}</summary><div className="mt-8 space-y-10">{children}</div></details>;
}
