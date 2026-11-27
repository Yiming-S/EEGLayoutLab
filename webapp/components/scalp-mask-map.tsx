'use client';

import { useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { FIGURE_REGION_COLORS } from '@/lib/layout-figure';
import { MASK_NAMES } from '@/lib/ui-language';
import { cn } from '@/lib/utils';

type PatchDef = {
  code: string;
  path: string;
  labelX: number;
  labelY: number;
  badgeX: number;
  badgeY: number;
};

const MASK_PATCHES: PatchDef[] = [
  {
    code: 'OL',
    path: 'M 74 70 Q 98 40 132 34 L 136 56 Q 108 62 90 84 Z',
    labelX: 105,
    labelY: 57,
    badgeX: 84,
    badgeY: 46,
  },
  {
    code: 'OR',
    path: 'M 246 70 Q 222 40 188 34 L 184 56 Q 212 62 230 84 Z',
    labelX: 215,
    labelY: 57,
    badgeX: 236,
    badgeY: 46,
  },
  {
    code: 'FL',
    path: 'M 94 88 Q 114 66 140 60 L 143 92 Q 120 96 106 112 Z',
    labelX: 121,
    labelY: 86,
    badgeX: 102,
    badgeY: 98,
  },
  {
    code: 'FM',
    path: 'M 142 54 Q 160 50 178 54 L 176 90 Q 160 87 144 90 Z',
    labelX: 160,
    labelY: 73,
    badgeX: 160,
    badgeY: 44,
  },
  {
    code: 'FR',
    path: 'M 226 88 Q 206 66 180 60 L 177 92 Q 200 96 214 112 Z',
    labelX: 199,
    labelY: 86,
    badgeX: 218,
    badgeY: 98,
  },
  {
    code: 'AL',
    path: 'M 54 106 Q 60 84 78 78 L 94 98 Q 82 118 84 146 L 58 148 Q 50 126 54 106 Z',
    labelX: 70,
    labelY: 118,
    badgeX: 46,
    badgeY: 112,
  },
  {
    code: 'AR',
    path: 'M 266 106 Q 260 84 242 78 L 226 98 Q 238 118 236 146 L 262 148 Q 270 126 266 106 Z',
    labelX: 250,
    labelY: 118,
    badgeX: 274,
    badgeY: 112,
  },
  {
    code: 'PL',
    path: 'M 58 154 L 85 152 Q 90 176 108 196 L 88 214 Q 64 190 58 154 Z',
    labelX: 79,
    labelY: 182,
    badgeX: 58,
    badgeY: 196,
  },
  {
    code: 'PR',
    path: 'M 262 154 L 235 152 Q 230 176 212 196 L 232 214 Q 256 190 262 154 Z',
    labelX: 241,
    labelY: 182,
    badgeX: 262,
    badgeY: 196,
  },
];

export function ScalpMaskMap({
  count,
  slots,
  onSlot,
}: {
  count: number;
  slots: string[];
  onSlot: (index: number, code: string) => void;
}) {
  const { tx } = useLanguage();
  const [rawTargetSlot, setTargetSlot] = useState(0);
  const targetSlot = rawTargetSlot < count ? rawTargetSlot : 0;

  const assignMask = (code: string) => {
    onSlot(targetSlot, code);
    const nextEmpty = Array.from({ length: count }, (_, idx) => idx).find(
      (idx) => idx !== targetSlot && !slots[idx],
    );
    if (nextEmpty !== undefined) {
      setTargetSlot(nextEmpty);
    } else if (count > 1) {
      setTargetSlot((targetSlot + 1) % count);
    }
  };

  return (
    <div
      data-scalp-mask-map
      className="rounded-xl border border-border/80 bg-card/95 p-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold text-foreground">
            {tx('九部位头皮俯视示意（鼻尖朝上）')}
          </p>
          <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
            {tx('先选下方目标区域编号，再点击示意图中的解剖部位即可直接填入。')}
          </p>
        </div>
        <fieldset
          className="flex flex-wrap gap-1"
          aria-label={tx('点击示意图时填入的目标区域')}
        >
          {Array.from({ length: count }, (_, idx) => {
            const code = slots[idx] ?? '';
            const active = targetSlot === idx;
            return (
              <button
                key={idx}
                type="button"
                aria-pressed={active}
                onClick={() => setTargetSlot(idx)}
                className={cn(
                  'inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-medium transition-colors',
                  active
                    ? 'border-primary bg-primary/10 text-foreground ring-1 ring-inset ring-primary/30'
                    : 'border-border bg-background/80 text-muted-foreground hover:text-foreground',
                )}
              >
                <span
                  aria-hidden="true"
                  className="inline-flex size-3.5 items-center justify-center rounded-full text-[9px] font-bold text-white"
                  style={{
                    backgroundColor:
                      FIGURE_REGION_COLORS[idx] ?? FIGURE_REGION_COLORS[0],
                  }}
                >
                  {idx + 1}
                </span>
                <span>{code ? `${code}` : tx('待选')}</span>
              </button>
            );
          })}
        </fieldset>
      </div>

      <div className="mt-2 grid items-center gap-3 sm:grid-cols-[228px_minmax(0,1fr)]">
        <svg
          viewBox="0 0 320 248"
          className="mx-auto w-full max-w-[232px] select-none"
          aria-label={tx('九个少毛发与前额耳周候选部位俯视示意图')}
        >
          <title>{tx('九部位头皮俯视示意（鼻尖朝上）')}</title>
          <path
            d="M 146 29 L 160 12 L 174 29"
            fill="none"
            className="stroke-border"
            strokeWidth={1.8}
            strokeLinejoin="round"
          />
          <path
            d="M 52 114 Q 36 120 36 136 Q 36 152 52 158"
            fill="none"
            className="stroke-border"
            strokeWidth={1.8}
          />
          <path
            d="M 268 114 Q 284 120 284 136 Q 284 152 268 158"
            fill="none"
            className="stroke-border"
            strokeWidth={1.8}
          />
          <circle
            cx={160}
            cy={136}
            r={108}
            className="fill-secondary/45 stroke-border"
            strokeWidth={1.6}
          />
          <ellipse
            cx={160}
            cy={152}
            rx={64}
            ry={68}
            className="fill-muted/65 stroke-border/70"
            strokeDasharray="3 3"
            strokeWidth={1.1}
          />
          <text
            x={160}
            y={156}
            textAnchor="middle"
            className="fill-muted-foreground text-[9px]"
          >
            {tx('中央有发头顶区')}
          </text>
          <text
            x={160}
            y={10}
            textAnchor="middle"
            className="fill-muted-foreground font-mono text-[9px]"
          >
            NAS
          </text>

          {MASK_PATCHES.map((patch) => {
            const assignedRegions = slots
              .slice(0, count)
              .map((code, idx) => (code === patch.code ? idx : -1))
              .filter((idx) => idx >= 0);
            const primaryIdx = assignedRegions[0];
            const primaryColor =
              primaryIdx !== undefined
                ? FIGURE_REGION_COLORS[primaryIdx]
                : undefined;
            const isTargetCurrent = slots[targetSlot] === patch.code;
            const fullName = tx(MASK_NAMES[patch.code] ?? patch.code);

            return (
              <g
                key={patch.code}
                onClick={() => assignMask(patch.code)}
                className="cursor-pointer transition-opacity hover:opacity-90"
              >
                <title>{`${patch.code} · ${fullName}`}</title>
                <path
                  d={patch.path}
                  fill={primaryColor ?? 'var(--card)'}
                  fillOpacity={primaryColor ? 0.24 : 0.92}
                  stroke={
                    primaryColor ??
                    (isTargetCurrent ? 'var(--primary)' : 'var(--border)')
                  }
                  strokeWidth={primaryColor ? 2 : 1.3}
                />
                <text
                  x={patch.labelX}
                  y={patch.labelY}
                  textAnchor="middle"
                  dominantBaseline="central"
                  className="pointer-events-none font-mono text-[10px] font-semibold fill-foreground"
                >
                  {patch.code}
                </text>
                {assignedRegions.length > 0 && (
                  <g className="pointer-events-none">
                    <circle
                      cx={patch.badgeX}
                      cy={patch.badgeY}
                      r={8}
                      fill={primaryColor}
                      stroke="var(--card)"
                      strokeWidth={1.4}
                    />
                    <text
                      x={patch.badgeX}
                      y={patch.badgeY + 0.5}
                      textAnchor="middle"
                      dominantBaseline="central"
                      fill="#ffffff"
                      className="font-mono text-[8.5px] font-bold"
                    >
                      {assignedRegions.length > 1
                        ? `${assignedRegions.length}×`
                        : `R${primaryIdx! + 1}`}
                    </text>
                  </g>
                )}
              </g>
            );
          })}
        </svg>

        <ul className="grid grid-cols-1 gap-1 text-[11px] leading-4 sm:grid-cols-1">
          {Object.entries(MASK_NAMES).map(([code, name]) => {
            const assigned = slots
              .slice(0, count)
              .map((v, idx) => (v === code ? idx : -1))
              .filter((idx) => idx >= 0);
            return (
              <li key={code}>
                <button
                  type="button"
                  onClick={() => assignMask(code)}
                  className={cn(
                    'flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-left transition-colors hover:bg-secondary/65',
                    assigned.length > 0 && 'bg-secondary/45 font-medium',
                  )}
                >
                  <span className="truncate">
                    <span className="mr-1.5 font-mono font-semibold text-foreground">
                      {code}
                    </span>
                    <span className="text-muted-foreground">{tx(name)}</span>
                  </span>
                  {assigned.length > 0 && (
                    <span className="flex shrink-0 gap-0.5">
                      {assigned.map((idx) => (
                        <span
                          key={idx}
                          className="inline-flex size-4 items-center justify-center rounded-full font-mono text-[9px] font-bold text-white"
                          style={{
                            backgroundColor:
                              FIGURE_REGION_COLORS[idx] ??
                              FIGURE_REGION_COLORS[0],
                          }}
                        >
                          {idx + 1}
                        </span>
                      ))}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
