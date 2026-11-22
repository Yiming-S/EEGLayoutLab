'use client';
import { useMemo, useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { Button } from '@/components/ui/button';
import type { ElectrodeDesign } from '@/lib/design-decision';
import { figureSpacing, layoutFigureSvg, svgToPng } from '@/lib/layout-figure';

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** A 2D figure of the layout for papers and reports; the same SVG is the PNG source. */
export function LayoutFigureExport({ design }: { design: ElectrodeDesign }) {
  const { tx, locale } = useLanguage();
  const crowded = useMemo(() => figureSpacing(design) < 16, [design]);
  const [choice, setChoice] = useState<{ key: string; labels: boolean } | null>(null);
  const key = JSON.stringify([design.xyz_mm, design.electrode_names]);
  const labels = choice?.key === key ? choice.labels : !crowded;
  const [error, setError] = useState('');
  const count = Math.max(...design.region_indices) + 1;
  const svg = useMemo(() => layoutFigureSvg(design, {
    title: design.name,
    subtitle: tx(`64个电极 · ${count}个区域 · Ernie模板头`),
    // Too short for a catalog template; the phrase fallback would translate it as a plural.
    region: index => (locale === 'en' ? `Region ${index + 1}` : `区域${index + 1}`),
    caption: [
      tx('以Ernie模板基准点NAS、LPA、RPA建立头坐标系（x朝RPA，y朝NAS），按与竖直轴的夹角做等距方位投影。'),
      tx('圆为NAS–LPA–RPA平面，低于该平面的电极画在圆外。位置为模板头上的设计位置，不是实测位置。'),
    ],
  }, { labels }), [design, labels, count, tx, locale]);
  const preview = useMemo(() => 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg), [svg]);
  const base = (design.name.replace(/[\\/:*?"<>|\s]+/g, '_').replace(/^_+|_+$/g, '') || 'layout') + '_layout';
  const png = async () => {
    setError('');
    try { download(await svgToPng(svg), base + '.png'); }
    catch (caught) { setError(caught instanceof Error ? caught.message : '布局图渲染失败。'); }
  };
  return <details className="mt-3 rounded-lg border p-3"><summary className="cursor-pointer text-sm">{tx('布局图（SVG、PNG）')}</summary>
    <p className="mt-2 text-xs text-muted-foreground">{tx('二维布局图用于论文和报告：每个区域有各自的颜色和标记形状。PNG按3倍分辨率由同一SVG生成。')}</p>
    <label className="mt-2 flex items-center gap-2 text-sm">
      <input type="checkbox" checked={labels} onChange={event => setChoice({ key, labels: event.target.checked })} />
      {tx('显示电极名称')}
    </label>
    {crowded && <p className="mt-1 text-xs text-muted-foreground">{tx('电极排列紧密，名称会互相重叠，默认不显示。')}</p>}
    {/* oxlint-disable-next-line next/no-img-element -- a data URI preview of the file being exported; there is nothing to optimize */}
    <img className="mt-3 w-full max-w-md rounded border bg-white" src={preview} alt={tx(`${design.name}的二维布局图`)} />
    <div className="mt-3 flex flex-wrap gap-2">
      <Button variant="outline" size="sm" onClick={() => download(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }), base + '.svg')}>{tx('下载')} SVG</Button>
      <Button variant="outline" size="sm" onClick={() => void png()}>{tx('下载')} PNG</Button>
    </div>
    {error && <p role="alert" className="mt-2 text-sm text-danger">{tx(error)}</p>}
  </details>;
}
