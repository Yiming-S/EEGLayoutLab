'use client';
/* oxlint-disable next/no-html-link-for-pages -- vinext production link prefetch is not runtime-safe */
import { useEffect, useState } from 'react';
import { BookOpen } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { SiteHeader } from '@/components/site-header';
import { DocumentationLink } from '@/components/documentation-navigation';
import { MethodBackLink } from '@/components/method-context';
import { CopyrightNotice } from '@/components/copyright-notice';
import { useDocsSite } from '@/components/docs-site';
import { METHOD_CONTENTS } from '@/lib/documentation';
import { METHOD_GROUPS, docsHref, movedSection } from '@/lib/method-index';

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
    <div className="lab-container max-w-5xl space-y-6 py-6">
      <header>
        <MethodBackLink />
        <h1 className="text-3xl font-semibold tracking-[-0.03em]">{tx('建模与原理')}</h1>
        <p className="mt-3 max-w-3xl text-base leading-7 text-muted-foreground">{tx('完整的方法说明写在项目文档中，按主题分章；本页是目录。首次操作请查看“使用指南”。')}</p>
        <p className="mt-2 text-sm text-muted-foreground">{tx(site === 'local' ? '文档由本机服务提供（/docs/）。'
          : '文档链接打开GitHub上的原文；用本机服务（eeglayoutlab）运行并构建文档后，链接改为本机的/docs/。')}</p>
      </header>
      {moved && <output className="lab-panel block border-l-4 border-l-primary text-base">
        {tx(`“${moved.title}”一节已移到文档。`)} <a className="font-semibold text-primary underline underline-offset-4" href={docsHref(moved.doc, site)} {...external}>{tx('打开该章节')}</a>
      </output>}
      <nav aria-label={tx('建模与原理目录')} className="flex flex-wrap gap-x-6 gap-y-2 text-base">
        {METHOD_CONTENTS.map(([id, title]) => <a key={id} href={'#' + id} className="text-primary underline underline-offset-4">{tx(title)}</a>)}
      </nav>
      {METHOD_GROUPS.map(group => <section key={group.id} id={group.id} aria-labelledby={group.id + '-title'} className="lab-panel scroll-mt-40">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id={group.id + '-title'} className="flex items-center gap-2 text-xl font-semibold"><BookOpen aria-hidden className="size-5 text-primary" />{tx(group.title)}</h2>
          <a className="text-sm font-semibold text-primary underline underline-offset-4" href={docsHref(group.page + '/', site)} {...external}>{tx('阅读整章')}</a>
        </div>
        <p className="mt-2 text-base leading-7 text-muted-foreground">{tx(group.text)}</p>
        <ul className="mt-4 grid gap-x-6 gap-y-1 sm:grid-cols-2">
          {group.entries.map(entry => <li key={entry.ids[0]} id={entry.ids[0]} className="scroll-mt-40 rounded-md px-2 py-1.5 target:bg-primary/10">
            {entry.ids.slice(1).map(alias => <span key={alias} id={alias} className="scroll-mt-40" />)}
            <a className="text-primary underline-offset-4 hover:underline" href={docsHref(entry.doc, site)} {...external}>{tx(entry.title)}</a>
          </li>)}
        </ul>
      </section>)}
      <DocumentationLink target="guide" className="inline-block text-base font-semibold text-primary underline underline-offset-4">{tx('返回使用指南，继续操作')}</DocumentationLink>
      <CopyrightNotice />
    </div>
  </main>;
}
