import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import { LanguageProvider } from '@/components/language-provider';
import { SiteFooter } from '@/components/site-footer';
import './globals.css';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

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
    <html lang="en">
      <head><link rel="icon" type="image/svg+xml" href="/favicon.svg" /></head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <LanguageProvider initialLocale="en">
          {children}
          <SiteFooter />
        </LanguageProvider>
      </body>
    </html>
  );
}
