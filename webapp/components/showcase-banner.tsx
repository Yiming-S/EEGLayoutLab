'use client';
import { ArrowUpRight, Eye } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { SHOWCASE, SHOWCASE_INSTALL_URL } from '@/lib/showcase';
import { installShowcaseApi } from '@/lib/showcase-api';
import { cn } from '@/lib/utils';

// Installed when this module loads, before any page effect sends a request.
if (SHOWCASE) installShowcaseApi();

/** Shown where a calculation would start, in place of a "service unavailable" state. */
export function ShowcaseComputeNotice({ className }: { className?: string }) {
  const { tx } = useLanguage();
  return (
    <p
      role="note"
      className={cn(
        'flex flex-wrap items-center gap-x-2.5 gap-y-1.5 rounded-lg border border-[#2451D8]/22 bg-[#2451D8]/[0.06] px-3.5 py-2.5 text-[0.9375rem] leading-6 text-foreground dark:border-[#60A5FA]/28 dark:bg-[#60A5FA]/10',
        className,
      )}
    >
      <span>{tx('这是只读展示版，不运行计算，也不保存数据。安装 EEGLayoutLab 本地版后即可计算。')}</span>
      <a
        className="inline-flex items-center gap-1 font-semibold text-[#2451D8] underline underline-offset-4 hover:opacity-80 dark:text-[#7DB3FF]"
        href={SHOWCASE_INSTALL_URL}
        target="_blank"
        rel="noreferrer"
      >
        {tx('安装说明')}
        <ArrowUpRight aria-hidden className="size-4" />
      </a>
    </p>
  );
}

/** Prominent top banner on every page of the read-only showcase; renders nothing in the local application. */
export function ShowcaseBanner() {
  const { tx } = useLanguage();
  if (!SHOWCASE) return null;
  return (
    <div
      role="note"
      className="border-b border-[#183396] bg-[#1F42B6] text-white shadow-[0_2px_10px_rgba(31,66,182,0.18)] dark:border-[#60A5FA]/25 dark:bg-[#1B3480]"
    >
      <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-x-4 gap-y-2.5 px-4 py-3 sm:px-6 sm:py-3.5 lg:px-8">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <span className="inline-flex items-center gap-1.5 rounded-md bg-white/16 px-2.5 py-1 text-[0.9375rem] font-semibold tracking-wide text-white ring-1 ring-inset ring-white/25">
            <Eye aria-hidden className="size-4 shrink-0" />
            {tx('只读展示版')}
          </span>
          <span className="text-[0.9375rem] font-medium leading-6 text-white/95 sm:text-base">
            {tx('可浏览示例结果、三维头模和方法说明；计算、保存与导入需要安装本地版。')}
          </span>
        </div>
        <a
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-white px-3.5 py-1.5 text-sm font-semibold text-[#1B3AA8] shadow-xs transition-colors hover:bg-white/92 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/80 focus-visible:ring-offset-2 focus-visible:ring-offset-[#1F42B6]"
          href={SHOWCASE_INSTALL_URL}
          target="_blank"
          rel="noreferrer"
        >
          {tx('安装说明')}
          <ArrowUpRight aria-hidden className="size-4" />
        </a>
      </div>
    </div>
  );
}
