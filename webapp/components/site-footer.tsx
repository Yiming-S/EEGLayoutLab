'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useState, type MouseEvent } from 'react';
import { CranialMark } from '@/components/site-header';
import { useLanguage } from '@/components/language-provider';
import { COPYRIGHT_NOTICE, copyrightHref, type CopyrightSection } from '@/lib/copyright';

export function SiteFooter() {
  const { tx } = useLanguage();
  const [location, setLocation] = useState({ pathname: '/', search: '' });
  useEffect(() => {
    const restore = () => setLocation({ pathname: window.location.pathname, search: window.location.search });
    restore();
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  const updateLink = (event: MouseEvent<HTMLAnchorElement>, section: CopyrightSection) => {
    event.currentTarget.href = copyrightHref(window.location.pathname, window.location.search, section);
  };
  return (
    <footer className="border-t border-border bg-card/65 text-xs text-muted-foreground">
      <div className="mx-auto flex max-w-[1440px] flex-col gap-3 px-4 py-5 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:px-6 lg:px-8">
        <p className="flex items-center gap-2 leading-6">
          <span aria-hidden="true" className="grid size-5 place-items-center rounded-[5px] bg-foreground text-background">
            <CranialMark className="size-3" />
          </span>
          <span>{COPYRIGHT_NOTICE} <span aria-hidden="true">·</span> EEG Layout Lab</span>
        </p>
        <nav aria-label={tx('版权与许可导航')} className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
          {(['about-copyright', 'third-party-licenses'] as const).map((section) => (
            <a key={section} href={copyrightHref(location.pathname, location.search, section)}
              onClick={(event) => updateLink(event, section)} onAuxClick={(event) => updateLink(event, section)}
              onContextMenu={(event) => updateLink(event, section)}
              className="inline-flex min-h-7.5 items-center rounded-md px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-secondary/75 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              {tx(section === 'about-copyright' ? '关于与版权' : '第三方许可')}
            </a>
          ))}
        </nav>
      </div>
    </footer>
  );
}
