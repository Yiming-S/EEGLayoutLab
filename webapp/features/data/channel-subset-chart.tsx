'use client';
import { useMemo, useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { Button } from '@/components/ui/button';
import { channelSubsetFigureSvg, type SubsetReport } from '@/lib/channel-subset-figure';
import { svgToPng } from '@/lib/layout-figure';

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Error against subset size for a channel-subset report; the same SVG is the downloadable figure. */
export function ChannelSubsetChart({ report }: { report: SubsetReport }) {
  const { tx, locale } = useLanguage();
  const [error, setError] = useState('');
  const svg = useMemo(() => {
    const heldOut = report.test.length > 0, standard = report.standard_10_20;
    return channelSubsetFigureSvg(report, {
      title: tx('通道子集的重建误差'),
      subtitle: [tx(heldOut ? '留出摘要的平均误差' : '训练摘要上的误差'), tx(`${report.universe.length}个共同通道`), `${report.band_hz[0]}–${report.band_hz[1]} Hz`].join(' · '),
      xLabel: tx('子集通道数'),
      yLabel: tx('未解释方差（越低越好）'),
      names: {
        data: tx('按数据贪心选择'), data_prior: tx('按数据先验模型选择'), area_prior: tx('按面积先验模型选择'),
        random: tx('随机子集中位数与P10–P90'), standard: standard ? tx(`10-20系统（${standard.count}个）`) : '',
      },
      // Too short for a catalog template; the phrase fallback would not translate the count.
      channels: count => (locale === 'en' ? `${count} channels` : `${count}个通道`),
      caption: [
        tx('误差为全部共同通道平均参考信号的未解释方差比例。每个子集以自身的一个通道为参考，重建器由训练摘要拟合。'),
        tx(heldOut ? '曲线为留出摘要的平均误差；阴影为随机子集平均留出误差在各次抽取间的P10–P90。按数据贪心选择的曲线包含与10-20系统相同通道数的点。'
          : '未载入留出摘要，曲线为训练误差，按数据贪心选择的误差偏乐观；阴影为随机子集训练误差的P10–P90。'),
      ],
    });
  }, [report, tx, locale]);
  const png = async () => {
    setError('');
    try { download(await svgToPng(svg), 'eeg-channel-subset.png'); }
    catch (caught) { setError(caught instanceof Error ? caught.message : '布局图渲染失败。'); }
  };
  return (
    <div className="mt-2">
      {/* The SVG is built from report numbers and catalog text; every string in it is escaped. Values are also in the table below. */}
      <figure className="max-w-[640px] overflow-hidden rounded-lg border bg-white [&_svg]:h-auto [&_svg]:w-full"
        aria-label={tx('通道子集重建误差随通道数变化的曲线图；数值见下表。')} dangerouslySetInnerHTML={{ __html: svg }} />
      <div className="mt-2 flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={() => download(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }), 'eeg-channel-subset.svg')}>{tx('下载')} SVG</Button>
        <Button variant="outline" size="sm" onClick={() => void png()}>{tx('下载')} PNG</Button>
      </div>
      {error && <p role="alert" className="mt-2 text-sm text-destructive">{tx(error)}</p>}
    </div>
  );
}
