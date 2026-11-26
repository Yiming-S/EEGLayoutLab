'use client';

import { useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { useLanguage } from '@/components/language-provider';
import type { SavedRecord } from '@/lib/local-library';
import type { Locale } from '@/lib/i18n/core';
import { localizedRecordTitle } from '@/lib/i18n/records';
import {
  exportRecordCoordinates,
  mm,
  recordElectrodeCount,
  tryExportDesign,
} from '@/lib/design-decision';
import { plotFigureSpacing, plotFigureSvg, sharedPlotFigureRadius } from '@/lib/layout-figure';
import { cn } from '@/lib/utils';
import { downloadTextFile } from './decision-download';

export function LayoutPairComparisonPanel({
  shown,
  ids,
  locale,
  testTarget,
  onSelectTarget,
}: {
  shown: SavedRecord[];
  ids: string[];
  locale: Locale;
  testTarget: string;
  onSelectTarget: (slot: 'a' | 'b') => void;
}) {
  const { tx } = useLanguage();
  const cards = useMemo(
    () =>
      shown.map((record) => {
        const slotIndex = ids.indexOf(record.id) === 1 ? 1 : 0,
          slotKey = (slotIndex === 1 ? 'b' : 'a') as 'a' | 'b',
          slotName = slotIndex === 1 ? '方案B' : '方案A',
          plot = exportRecordCoordinates(record),
          design = tryExportDesign(record);
        return { record, slotKey, slotName, plot, design };
      }),
    [shown, ids],
  );
  const { radius, defaultShowLabels } = useMemo(() => {
    const plots = cards.flatMap(({ plot }) => (plot ? [plot] : []));
    const radius = plots.length > 0 ? sharedPlotFigureRadius(plots) : 236;
    return {
      radius,
      defaultShowLabels:
        cards.length > 0 &&
        cards.every(({ plot }) => plot && plotFigureSpacing(plot, radius) >= 16),
    };
  }, [cards]);
  const pairIdentity = cards.map((card) => card.record.id).join(':');
  const [labelChoice, setLabelChoice] = useState<{ key: string; show: boolean } | null>(null);
  const showLabels = labelChoice?.key === pairIdentity ? labelChoice.show : defaultShowLabels;

  const rendered = useMemo(
    () =>
      cards.map((card) => {
        const titleText = `${tx(card.slotName)} · ${localizedRecordTitle(card.record, locale)}`;
        if (!card.plot) return { ...card, titleText, svg: null, preview: null };
        const regionCount = Math.max(...card.plot.region_indices) + 1;
        const total = card.plot.xyz_mm.length;
        const subtitle =
          total === 64
            ? tx(`64个电极 · ${regionCount}个区域 · Ernie模板头`)
            : tx(`${total}导 · ${regionCount}个区域 · Ernie模板头`);
        const svg = plotFigureSvg(
          card.plot,
          {
            title: titleText,
            subtitle,
            region: (index) => (locale === 'en' ? `Region ${index + 1}` : `区域${index + 1}`),
            caption: [
              tx(
                '圆为NAS–LPA–RPA平面，低于该平面的电极画在圆外。位置为模板头上的设计位置，不是实测位置。',
              ),
            ],
          },
          { labels: showLabels, radius },
        );
        return {
          ...card,
          titleText,
          svg,
          preview: 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg),
        };
      }),
    [cards, locale, radius, showLabels, tx],
  );

  return (
    <section className="lab-panel space-y-4" data-layout-pair-comparison>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{tx('方案空间布局并排对照')}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {tx(
              '同尺度等距方位投影（鼻尖朝上，圆为NAS–LPA–RPA基准平面），直观对照两套方案的区域覆盖与电极疏密。',
            )}
          </p>
        </div>
        {rendered.some((card) => card.svg) && (
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border/75 bg-muted/40 px-3 py-1.5 text-xs font-medium">
            <input
              type="checkbox"
              className="accent-primary"
              checked={showLabels}
              onChange={(event) =>
                setLabelChoice({ key: pairIdentity, show: event.target.checked })
              }
            />
            {tx('显示电极名称')}
          </label>
        )}
      </div>
      <div className={cn('grid gap-4', rendered.length > 1 ? 'md:grid-cols-2' : 'max-w-xl')}>
        {rendered.map((card) => {
          const activeTarget = testTarget === card.slotKey;
          const channels = recordElectrodeCount(card.record);
          return (
            <div
              key={card.record.id}
              className={cn(
                'flex flex-col justify-between rounded-2xl border border-border/80 bg-muted/25 p-4 transition-all',
                activeTarget && 'border-primary/50 ring-1 ring-primary/35',
              )}
            >
              <div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span
                    className={cn(
                      'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold',
                      card.slotKey === 'a'
                        ? 'bg-primary/15 text-primary'
                        : 'bg-sky-500/15 text-sky-700 dark:text-sky-300',
                    )}
                  >
                    {tx(card.slotName)} · {channels} {tx('电极')} · {card.record.region_count}
                    {tx('区')}
                  </span>
                  <div className="flex flex-wrap items-center gap-2 font-mono text-xs text-muted-foreground tabular-nums">
                    <span>
                      {card.record.geometry
                        ? `${card.record.geometry.union_area_cm2.toFixed(1)} cm²`
                        : tx('未提供')}
                    </span>
                    <span>·</span>
                    <span>
                      {tx(
                        `最小直线点距：${mm(card.record.geometry?.minimum_chord_distance_mm)}`,
                      )}
                    </span>
                  </div>
                </div>
                {card.preview ? (
                  /* oxlint-disable-next-line next/no-img-element -- data URI preview of generated 2D layout SVG */
                  <img
                    className="mt-3 w-full rounded-xl border border-border/75 bg-white shadow-2xs"
                    src={card.preview}
                    alt={tx(`${card.titleText}的二维布局图`)}
                  />
                ) : (
                  <p className="mt-3 rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
                    {tx('该记录暂无可绘制的64点模板坐标。')}
                  </p>
                )}
              </div>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                {card.design ? (
                  <Button
                    type="button"
                    size="sm"
                    variant={activeTarget ? 'default' : 'outline'}
                    aria-pressed={activeTarget}
                    onClick={() => onSelectTarget(card.slotKey)}
                  >
                    {tx(activeTarget ? '当前偏移测试对象' : '设为偏移测试对象')}
                  </Button>
                ) : (
                  <span className="text-xs text-muted-foreground">
                    {tx('仅64导均衡方案支持偏移测试')}
                  </span>
                )}
                {card.svg && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      downloadTextFile(
                        `eeg-${card.slotKey.toUpperCase()}-layout.svg`,
                        card.svg!,
                        'image/svg+xml;charset=utf-8',
                      )
                    }
                  >
                    {tx('下载')} SVG
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
