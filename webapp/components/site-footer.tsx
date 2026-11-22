'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useState, type MouseEvent } from 'react';
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
    // Some design controls replace the query without a popstate event.
    event.currentTarget.href = copyrightHref(window.location.pathname, window.location.search, section);
  };
  return (
    <footer className="border-t border-border bg-background text-sm text-ink-soft">
      <div className="mx-auto flex max-w-[1500px] flex-col gap-3 px-4 py-5 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:px-6 lg:px-8">
        <p className="leading-6">{COPYRIGHT_NOTICE} <span aria-hidden="true">·</span> EEG Layout Lab</p>
        <nav aria-label={tx('版权与许可导航')} className="flex flex-wrap items-center gap-x-5 gap-y-2">
          {(['about-copyright', 'third-party-licenses'] as const).map((section) => (
            <a key={section} href={copyrightHref(location.pathname, location.search, section)}
              onClick={(event) => updateLink(event, section)} onAuxClick={(event) => updateLink(event, section)}
              onContextMenu={(event) => updateLink(event, section)}
              className="inline-flex min-h-9 items-center rounded-sm underline-offset-4 hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
              {tx(section === 'about-copyright' ? '关于与版权' : '第三方许可')}
            </a>
          ))}
        </nav>
      </div>
    </footer>
  );
}
