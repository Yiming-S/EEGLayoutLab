import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import { cookies, headers } from 'next/headers';
import { LanguageProvider } from '@/components/language-provider';
import { SiteFooter } from '@/components/site-footer';
import { LANGUAGE_COOKIE, resolveLocale } from '@/lib/i18n/core';
import './globals.css';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

const localeForRequest = async () => resolveLocale((await cookies()).get(LANGUAGE_COOKIE)?.value, (await headers()).get('accept-language') ?? '');

export async function generateMetadata(): Promise<Metadata> {
  const locale = await localeForRequest();
  return {
  title: {
    default: locale === 'en' ? 'EEG Layout Lab | EEG Electrode Layout Simulation' : 'EEG Layout Lab｜脑电电极布局仿真',
    template: '%s｜EEG Layout Lab',
  },
  description:
    locale === 'en' ? 'Explore fixed 64-electrode EEG layouts, compare region size and placement, and evaluate signal retention using local simulations.' : '固定64电极，比较区域大小与空间布局，通过本机仿真评价相对全头64导的性能保留。',
  };
}

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale = await localeForRequest();
  return (
    <html lang={locale}>
      <head><link rel="icon" type="image/svg+xml" href="/favicon.svg" /></head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <LanguageProvider initialLocale={locale}>
          {children}
          <SiteFooter />
        </LanguageProvider>
      </body>
    </html>
  );
}
