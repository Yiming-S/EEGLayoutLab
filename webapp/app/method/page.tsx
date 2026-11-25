'use client';
/* oxlint-disable next/no-html-link-for-pages -- vinext production link prefetch is not runtime-safe */
import { useEffect, useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { SiteHeader } from '@/components/site-header';
import { DocumentationLink } from '@/components/documentation-navigation';
import { MethodBackLink } from '@/components/method-context';
import { CopyrightNotice } from '@/components/copyright-notice';
import { useDocsSite } from '@/components/docs-site';
import { METHOD_CONTENTS } from '@/lib/documentation';
import { METHOD_GROUPS, docsHref, movedSection } from '@/lib/method-index';
import { SHOWCASE } from '@/lib/showcase';

export default function MethodPage() {
  const { tx } = useLanguage();
  const site = useDocsSite();
  const [hash, setHash] = useState('');
  useEffect(() => {
    const read = () => setHash(window.location.hash);
    read(); window.addEventListener('hashchange', read);
    return () => window.removeEventListener('hashchange', read);
  }, []);
  const moved = movedSection(hash);
  const external = site === 'github' ? { target: '_blank', rel: 'noreferrer' } : {};
  return <main className="lab-page">
    <SiteHeader current="method" />
    <div className="lab-container max-w-5xl space-y-5 py-6">
      <header className="lab-hero overflow-hidden">
        <div className="bg-card/90 p-6 sm:p-7">
          <MethodBackLink />
          <h1 className="mt-2 text-2xl font-semibold tracking-[-0.03em] sm:text-[1.75rem]">{tx('建模与原理')}</h1>
          <p className="mt-2.5 max-w-3xl text-sm leading-7 text-ink-soft">{tx('完整的方法说明写在项目文档中，按主题分章；本页是目录。首次操作请查看“使用指南”。')}</p>
          <p className="mt-2 font-mono text-xs text-muted-foreground">{site !== 'local' ? tx('文档链接打开GitHub上的原文；用本机服务（eeglayoutlab）运行并构建文档后，链接改为本机的/docs/。')
            : SHOWCASE ? tx('文档与本站一起发布（/docs/）。') : tx('文档由本机服务提供（/docs/）。')}</p>
          <nav aria-label={tx('建模与原理目录')} className="mt-4 flex flex-wrap gap-2">
            {METHOD_CONTENTS.map(([id, title]) => <a key={id} href={'#' + id} className="lab-link-pill">{tx(title)}</a>)}
          </nav>
        </div>
      </header>
      {moved && <output className="lab-panel block border-l-2 border-l-foreground text-sm">
        {tx(`“${moved.title}”一节已移到文档。`)} <a className="lab-link-pill ml-2" href={docsHref(moved.doc, site)} {...external}>{tx('打开该章节')}</a>
      </output>}
      {METHOD_GROUPS.map((group, groupIndex) => <section key={group.id} id={group.id} aria-labelledby={group.id + '-title'} className="lab-panel scroll-mt-36 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
          <h2 id={group.id + '-title'} className="flex items-baseline gap-2.5 text-base font-semibold sm:text-lg">
            <span aria-hidden className="rounded border border-border bg-secondary/75 px-2 py-0.5 font-mono text-[11px] font-semibold text-foreground">
              0{groupIndex + 1}
            </span>
            {tx(group.title)}
          </h2>
          <a className="lab-link-pill" href={docsHref(group.page + '/', site)} {...external}>{tx('阅读整章')}<ArrowUpRight aria-hidden className="size-3.5" /></a>
        </div>
        <p className="text-[0.8125rem] leading-6.5 text-ink-soft">{tx(group.text)}</p>
        <ul className="grid divide-y divide-border overflow-hidden rounded-lg border border-border bg-card sm:grid-cols-2 sm:divide-x sm:divide-y-0">
          {group.entries.map((entry, idx) => <li key={entry.ids[0]} id={entry.ids[0]} className="scroll-mt-36 border-border transition-colors hover:bg-secondary/45 target:bg-secondary/75 sm:[&:nth-child(n+3)]:border-t">
            {entry.ids.slice(1).map(alias => <span key={alias} id={alias} className="scroll-mt-36" />)}
            <a className="group flex items-center justify-between gap-2 px-4 py-3 text-[0.8125rem] font-medium text-foreground" href={docsHref(entry.doc, site)} {...external}>
              <span className="flex items-center gap-2.5 min-w-0">
                <span className="font-mono text-[11px] text-muted-foreground">{groupIndex + 1}.{idx + 1}</span>
                <span className="truncate">{tx(entry.title)}</span>
              </span>
              <ArrowUpRight aria-hidden className="size-3.5 shrink-0 text-muted-foreground/50 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-foreground" />
            </a>
          </li>)}
        </ul>
      </section>)}
      <div>
        <DocumentationLink target="guide" className="lab-link-pill text-sm">{tx('返回使用指南，继续操作')}</DocumentationLink>
      </div>
      <CopyrightNotice />
    </div>
  </main>;
}
