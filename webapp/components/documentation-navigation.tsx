'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useState, type MouseEvent, type ReactNode } from 'react';
import { useLanguage } from '@/components/language-provider';
import { documentationHref, type DocumentationPage } from '@/lib/documentation';

export function DocumentationLink({ target, section = '', children, className, current }: {
  target: DocumentationPage; section?: string; children: ReactNode; className?: string; current?: boolean;
}) {
  const [href, setHref] = useState('/' + target + (section ? '#' + section : ''));
  useEffect(() => {
    const restore = () => setHref(documentationHref(window.location.pathname, window.location.search, target, section));
    restore(); window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, [target, section]);
  const refresh = (event: MouseEvent<HTMLAnchorElement>) => {
    event.currentTarget.href = documentationHref(window.location.pathname, window.location.search, target, section);
  };
  return <a href={href} onClick={refresh} onAuxClick={refresh} onContextMenu={refresh}
    aria-current={current ? 'page' : undefined} className={className}>{children}</a>;
}

export function DocumentationNavigation({ current }: { current: DocumentationPage }) {
  const { tx } = useLanguage();
  return <nav aria-label={tx('帮助文档导航')} className="mt-6 grid gap-3 sm:grid-cols-2">
    {([
      ['guide', '使用指南', '按操作顺序：查看、设计、编辑、仿真、保存。'],
      ['method', '建模与原理', '按计算顺序：脑源、传播、接收、重建、评价。'],
    ] as const).map(([target, title, body]) => <DocumentationLink key={target} target={target} current={current === target}
      className={'rounded-xl border p-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ' + (current === target ? 'border-primary bg-card' : 'border-border hover:bg-card/70')}>
      <span className="block text-base font-semibold text-primary">{tx(title)}</span>
      <span className="mt-1 block text-sm leading-6 text-muted-foreground">{tx(body)}</span>
    </DocumentationLink>)}
  </nav>;
}
