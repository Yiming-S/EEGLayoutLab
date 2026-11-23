'use client';
import { Eye } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { SHOWCASE, SHOWCASE_INSTALL_URL } from '@/lib/showcase';
import { installShowcaseApi } from '@/lib/showcase-api';
import { cn } from '@/lib/utils';

// Installed when this module loads, before any page effect sends a request.
if (SHOWCASE) installShowcaseApi();

/** Shown where a calculation would start, in place of a "service unavailable" state. */
export function ShowcaseComputeNotice({ className }: { className?: string }) {
  const { tx } = useLanguage();
  return <p role="note" className={cn('text-sm leading-6 text-ink-soft', className)}>
    {tx('这是只读展示版，不运行计算，也不保存数据。安装 EEGLayoutLab 本地版后即可计算。')}{' '}
    <a className="font-medium text-primary underline underline-offset-4" href={SHOWCASE_INSTALL_URL} target="_blank" rel="noreferrer">{tx('安装说明')}</a>
  </p>;
}

/** The strip above every page of the read-only showcase; renders nothing in the application. */
export function ShowcaseBanner() {
  const { tx } = useLanguage();
  if (!SHOWCASE) return null;
  return <div role="note" className="border-b border-brand/20 bg-brand text-sm text-brand-foreground">
    <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 sm:px-6 lg:px-8">
      <Eye aria-hidden className="size-4 shrink-0" />
      <span className="font-semibold">{tx('只读展示版')}</span>
      <span className="text-white/85 max-sm:hidden">{tx('可浏览示例结果、三维头模和方法说明；计算、保存与导入需要安装本地版。')}</span>
      <a className="font-medium underline underline-offset-4 hover:text-white" href={SHOWCASE_INSTALL_URL} target="_blank" rel="noreferrer">{tx('安装说明')}</a>
    </div>
  </div>;
}
