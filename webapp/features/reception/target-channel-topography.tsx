'use client';

import { useId, useMemo, useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import biosemi from '@/lib/biosemi64-reference.json';
import {
  combinedTrace,
  type SourceCondition,
  type SourceResult,
} from '@/lib/source-reception';

export const pct = (n: number | null | undefined) =>
  n == null ? '指标无法计算' : `${(n * 100).toFixed(2)}%`;

export const fixed = (n: number | null | undefined, unit = '') =>
  n == null ? '无干扰' : `${n.toFixed(2)}${unit}`;

const BIOSEMI_PROJECTED = (() => {
  const projected = biosemi.channels.map((ch) => {
    const [x, y, z] = ch.xyz_m,
      r = Math.atan2(Math.hypot(x, y), z) / (Math.PI / 2),
      azimuth = Math.atan2(y, x);
    return { name: ch.name, x: r * Math.cos(azimuth), y: r * Math.sin(azimuth), r };
  });
  const maxR = Math.max(1, ...projected.map((p) => p.r)),
    scale = Math.min(92, 108 / maxR);
  return {
    headRadius: scale,
    points: projected.map((p) => ({
      name: p.name,
      cx: 130 + p.x * scale,
      cy: 136 - p.y * scale,
    })),
  };
})();

const mixChannel = (a: number, b: number, t: number) =>
  Math.round(a + (b - a) * t);
const rgbCss = (rgb: [number, number, number]) =>
  `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;

function r2FillColor(r2: number | null): string {
  if (r2 == null || !Number.isFinite(r2)) return '#cbd5e1';
  const clamped = Math.max(0, Math.min(1, r2));
  const low: [number, number, number] = [217, 119, 6],
    mid: [number, number, number] = [226, 232, 240],
    high: [number, number, number] = [18, 138, 128];
  if (clamped < 0.5) {
    const t = clamped / 0.5;
    return rgbCss([
      mixChannel(low[0], mid[0], t),
      mixChannel(low[1], mid[1], t),
      mixChannel(low[2], mid[2], t),
    ]);
  }
  const t = (clamped - 0.5) / 0.5;
  return rgbCss([
    mixChannel(mid[0], high[0], t),
    mixChannel(mid[1], high[1], t),
    mixChannel(mid[2], high[2], t),
  ]);
}

function deltaR2FillColor(delta: number | null): string {
  if (delta == null || !Number.isFinite(delta)) return '#cbd5e1';
  const clamped = Math.max(-0.3, Math.min(0.3, delta));
  const neg: [number, number, number] = [192, 71, 104],
    zero: [number, number, number] = [241, 245, 249],
    pos: [number, number, number] = [18, 138, 128];
  if (clamped < 0) {
    const t = (clamped + 0.3) / 0.3;
    return rgbCss([
      mixChannel(neg[0], zero[0], t),
      mixChannel(neg[1], zero[1], t),
      mixChannel(neg[2], zero[2], t),
    ]);
  }
  const t = clamped / 0.3;
  return rgbCss([
    mixChannel(zero[0], pos[0], t),
    mixChannel(zero[1], pos[1], t),
    mixChannel(zero[2], pos[2], t),
  ]);
}

function computeChannelR2(
  result: SourceResult,
  condition: SourceCondition,
): { cand: number | null; base: number | null; delta: number | null }[] {
  return Array.from({ length: 64 }, (_, channel) => {
    const truth = result.waveforms.baseline.brain_uv[channel];
    let energy = 0;
    for (let t = 0; t < truth.length; t++) energy += truth[t] * truth[t];
    if (!Number.isFinite(energy) || energy <= 1e-18) {
      return { cand: null, base: null, delta: null };
    }
    const baseTrace = combinedTrace(
        result.waveforms.baseline,
        channel,
        condition,
        true,
      ),
      candTrace = combinedTrace(
        result.waveforms.candidate,
        channel,
        condition,
        true,
      );
    let baseErr = 0,
      candErr = 0;
    for (let t = 0; t < truth.length; t++) {
      const db = baseTrace[t].mixed - truth[t],
        dc = candTrace[t].mixed - truth[t];
      baseErr += db * db;
      candErr += dc * dc;
    }
    const base = 1 - baseErr / energy,
      cand = 1 - candErr / energy;
    return {
      cand: Number.isFinite(cand) ? cand : null,
      base: Number.isFinite(base) ? base : null,
      delta: Number.isFinite(cand) && Number.isFinite(base) ? cand - base : null,
    };
  });
}

function buildIdwContourCells(
  scores: { cand: number | null; delta: number | null }[],
  mode: 'candidate' | 'delta',
  cx: number,
  cy: number,
  radius: number,
) {
  const valid = BIOSEMI_PROJECTED.points
    .map((pt, idx) => ({
      x: pt.cx,
      y: pt.cy,
      val: mode === 'candidate' ? scores[idx]?.cand : scores[idx]?.delta,
    }))
    .filter((item): item is { x: number; y: number; val: number } =>
      typeof item.val === 'number' && Number.isFinite(item.val),
    );
  if (valid.length < 3) return [];
  const step = 6;
  const half = step / 2;
  const smoothSq = 20 * 20;
  const cells: { x: number; y: number; fill: string }[] = [];
  for (let y = cy - radius; y <= cy + radius; y += step) {
    for (let x = cx - radius; x <= cx + radius; x += step) {
      const px = x + half;
      const py = y + half;
      if ((px - cx) ** 2 + (py - cy) ** 2 > (radius + step) ** 2) continue;
      let num = 0;
      let den = 0;
      for (const s of valid) {
        const d2 = (px - s.x) ** 2 + (py - s.y) ** 2;
        const w = 1 / ((d2 + smoothSq) * Math.sqrt(d2 + smoothSq));
        num += w * s.val;
        den += w;
      }
      const raw = den > 0 ? num / den : 0;
      const quantized =
        mode === 'candidate'
          ? Math.round(Math.max(0, Math.min(1, raw)) * 12) / 12
          : Math.round(Math.max(-0.3, Math.min(0.3, raw)) * 20) / 20;
      cells.push({
        x,
        y,
        fill:
          mode === 'candidate'
            ? r2FillColor(quantized)
            : deltaR2FillColor(quantized),
      });
    }
  }
  return cells;
}

export function TargetChannelTopography({
  result,
  condition,
  targetChannel,
  onSelectChannel,
}: {
  result: SourceResult;
  condition: SourceCondition;
  targetChannel: number;
  onSelectChannel: (channel: number) => void;
}) {
  const { tx } = useLanguage();
  const clipId = useId();
  const [mapMode, setMapMode] = useState<'candidate' | 'delta'>('candidate');
  const [smoothField, setSmoothField] = useState(true);
  const channelScores = useMemo(
    () => computeChannelR2(result, condition),
    [result, condition],
  );
  const current = channelScores[targetChannel],
    r = BIOSEMI_PROJECTED.headRadius,
    cx = 130,
    cy = 136;
  const contourCells = useMemo(
    () =>
      smoothField ? buildIdwContourCells(channelScores, mapMode, cx, cy, r) : [],
    [smoothField, channelScores, mapMode, r],
  );

  return (
    <div
      className="flex flex-col justify-between rounded-xl border bg-muted/20 p-3.5"
      data-target-channel-topography
    >
      <div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">
            {tx('64导目标通道重建拓扑（点击选点）')}
          </h3>
          <div className="flex flex-wrap items-center gap-1.5">
            <div className="inline-flex rounded-md border bg-background p-0.5 text-[11px]">
              <button
                type="button"
                aria-pressed={mapMode === 'candidate'}
                onClick={() => setMapMode('candidate')}
                className={`rounded px-2 py-0.5 font-medium transition-colors ${
                  mapMode === 'candidate'
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {tx('自定义64解释率')}
              </button>
              <button
                type="button"
                aria-pressed={mapMode === 'delta'}
                onClick={() => setMapMode('delta')}
                className={`rounded px-2 py-0.5 font-medium transition-colors ${
                  mapMode === 'delta'
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {tx('相对标准64差值')}
              </button>
            </div>
            <div className="inline-flex rounded-md border bg-background p-0.5 text-[11px]">
              <button
                type="button"
                aria-pressed={smoothField}
                onClick={() => setSmoothField(true)}
                className={`rounded px-2 py-0.5 font-medium transition-colors ${
                  smoothField
                    ? 'bg-secondary text-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {tx('等势热力')}
              </button>
              <button
                type="button"
                aria-pressed={!smoothField}
                onClick={() => setSmoothField(false)}
                className={`rounded px-2 py-0.5 font-medium transition-colors ${
                  !smoothField
                    ? 'bg-secondary text-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {tx('离散点位')}
              </button>
            </div>
          </div>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {tx('预览波形逐通道解释率（1−NMSE）；点击头表电极切换右侧重建波形。')}
        </p>
        <svg
          viewBox="0 0 260 264"
          className="mx-auto mt-2 w-full max-w-[260px]"
          aria-label={tx('64导目标通道重建拓扑（点击选点）')}
        >
          <title>{tx('64导目标通道重建拓扑（点击选点）')}</title>
          <defs>
            <clipPath id={clipId}>
              <circle cx={cx} cy={cy} r={r - 0.8} />
            </clipPath>
          </defs>
          {smoothField && contourCells.length > 0 && (
            <g clipPath={`url(#${clipId})`} opacity={0.48}>
              {contourCells.map((cell, i) => (
                <rect
                  key={i}
                  x={cell.x}
                  y={cell.y}
                  width={6.4}
                  height={6.4}
                  fill={cell.fill}
                />
              ))}
            </g>
          )}
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            className="stroke-border"
            strokeWidth={1.5}
          />
          <path
            d={`M ${(cx - r * 0.1).toFixed(1)} ${(cy - r * 0.99).toFixed(1)} L ${cx} ${(cy - r * 1.1).toFixed(1)} L ${(cx + r * 0.1).toFixed(1)} ${(cy - r * 0.99).toFixed(1)}`}
            fill="none"
            className="stroke-border"
            strokeWidth={1.5}
            strokeLinejoin="round"
          />
          {[-1, 1].map((side) => (
            <path
              key={side}
              d={`M ${(cx + side * r).toFixed(1)} ${(cy - r * 0.12).toFixed(1)} q ${(side * r * 0.08).toFixed(1)} ${(r * 0.02).toFixed(1)} ${(side * r * 0.08).toFixed(1)} ${(r * 0.12).toFixed(1)} t ${(-side * r * 0.08).toFixed(1)} ${(r * 0.12).toFixed(1)}`}
              fill="none"
              className="stroke-border"
              strokeWidth={1.5}
            />
          ))}
          {BIOSEMI_PROJECTED.points.map((pt, index) => {
            const sc = channelScores[index],
              selected = index === targetChannel,
              fill =
                mapMode === 'candidate'
                  ? r2FillColor(sc.cand)
                  : deltaR2FillColor(sc.delta);
            return (
              <g
                key={pt.name}
                className="cursor-pointer"
                onClick={() => onSelectChannel(index)}
              >
                <title>
                  {`${pt.name} · ${tx('自定义64')} ${tx(pct(sc.cand))} · ${tx('标准64')} ${tx(pct(sc.base))}`}
                </title>
                {selected && (
                  <circle
                    cx={pt.cx}
                    cy={pt.cy}
                    r={9.2}
                    fill="none"
                    stroke="var(--primary)"
                    strokeWidth={2}
                  />
                )}
                <circle
                  cx={pt.cx}
                  cy={pt.cy}
                  r={selected ? 6.2 : 4.6}
                  fill={fill}
                  stroke={selected ? 'var(--foreground)' : 'var(--card)'}
                  strokeWidth={selected ? 1.8 : 1.2}
                />
                {selected && (
                  <text
                    x={pt.cx}
                    y={pt.cy - 11}
                    textAnchor="middle"
                    fontSize="10"
                    fontWeight="600"
                    fill="currentColor"
                  >
                    {pt.name}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="space-y-2 pt-1">
        {mapMode === 'candidate' ? (
          <div>
            <div
              aria-hidden="true"
              className="h-2 rounded bg-gradient-to-r from-[#d97706] via-[#e2e8f0] to-[#128a80]"
            />
            <div className="mt-0.5 flex justify-between font-mono text-[10px] text-muted-foreground">
              <span>≤0%</span>
              <span>50%</span>
              <span>100%</span>
            </div>
          </div>
        ) : (
          <div>
            <div
              aria-hidden="true"
              className="h-2 rounded bg-gradient-to-r from-[#c04768] via-[#f1f5f9] to-[#128a80]"
            />
            <div className="mt-0.5 flex justify-between font-mono text-[10px] text-muted-foreground">
              <span>−30 pp</span>
              <span>0</span>
              <span>+30 pp</span>
            </div>
          </div>
        )}
        <p className="rounded-md bg-background/80 px-2.5 py-1.5 font-mono text-xs tabular-nums">
          {tx(
            `当前目标 ${biosemi.channels[targetChannel].name} · 自定义 ${tx(pct(current?.cand))} · 标准64 ${tx(pct(current?.base))}`,
          )}
        </p>
      </div>
    </div>
  );
}
