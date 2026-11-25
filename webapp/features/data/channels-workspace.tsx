'use client';
import { SiteHeader } from '@/components/site-header';
import { useLanguage } from '@/components/language-provider';
import { ChannelSubsetPanel } from './channel-subset-panel';

/** Channel subsets chosen from recordings: works on covariance summaries, not on a layout. */
export default function ChannelsWorkspace() {
  const { tx } = useLanguage();
  return <main className="lab-page">
    <SiteHeader current="channels" />
    <div className="lab-container space-y-5 pb-10">
      <header className="border-b border-border pt-7 pb-5">
        <h1 className="text-2xl font-semibold tracking-[-0.028em] sm:text-[1.65rem]">{tx('通道子集')}</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">{tx('从已有记录的协方差摘要中，为给定通道数选出重建误差最小的通道子集。计算在浏览器内完成，不提交任务。')}</p>
      </header>
      <ChannelSubsetPanel />
    </div>
  </main>;
}
