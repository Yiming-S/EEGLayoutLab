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

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" data-showcase={SHOWCASE ? '1' : undefined}>
      <head><link rel="icon" type="image/svg+xml" href="/favicon.svg" /></head>
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
