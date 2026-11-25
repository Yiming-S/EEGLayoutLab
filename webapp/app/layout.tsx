import type { Metadata } from 'next';
import { LanguageProvider } from '@/components/language-provider';
import { ShowcaseBanner } from '@/components/showcase-banner';
import { SiteFooter } from '@/components/site-footer';
import { SHOWCASE } from '@/lib/showcase';
import './globals.css';

// Static export: the page is rendered once at build time, so the language is chosen in the browser
// (saved choice, then the browser's languages) by LanguageProvider.
export const metadata: Metadata = {
  title: { default: 'EEG Layout Lab | EEG Electrode Layout Simulation', template: '%s｜EEG Layout Lab' },
  description: 'Explore fixed 64-electrode EEG layouts, compare region size and placement, and evaluate signal retention using local simulations.',
};

const THEME_INIT_SCRIPT = `(function(){try{var k='eeg-layout-lab/theme',v=localStorage.getItem(k),d=v==='dark'||((!v||v==='system')&&window.matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.classList.toggle('dark',d);}catch(e){}})();`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning data-showcase={SHOWCASE ? '1' : undefined}>
      <head>
        <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="antialiased">
        <LanguageProvider initialLocale="en">
          <ShowcaseBanner />
          {children}
          <SiteFooter />
        </LanguageProvider>
      </body>
    </html>
  );
}
