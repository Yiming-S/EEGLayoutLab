'use client';
import { useLanguage } from '@/components/language-provider';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useState } from 'react';
import { parseAR } from '@/lib/lab-workflow';
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
