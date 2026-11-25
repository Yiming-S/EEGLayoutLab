import { useId } from 'react';
import { cn } from '@/lib/utils';

/**
 * Bespoke EEG Layout Lab emblem ("3D Geodesic Cranial Mesh & Ultramarine Regional Patch"):
 * - Warm porcelain ceramic squircle in light mode; matte carbon squircle in dark mode
 * - Tilted (-22°) 3D orthographic cranial sphere with orthogonal geodesic meridians
 * - Analytically bounded spherical patch sector + International Ultramarine (#2451D8) regional arc
 */
export function BrandMark({
  size = 'md',
  className,
}: {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}) {
  const gradId = useId();
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 64 64"
      fill="none"
      className={cn(
        'shrink-0 select-none',
        size === 'sm' ? 'size-5.5' : size === 'lg' ? 'size-12' : 'size-9.5',
        className,
      )}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#FFFFFF" className="dark:[stop-color:#232328]" />
          <stop offset="100%" stopColor="#F2EFE8" className="dark:[stop-color:#18181C]" />
        </linearGradient>
      </defs>

      {/* Ceramic / Carbon squircle plaque */}
      <rect
        x="2"
        y="2"
        width="60"
        height="60"
        rx="15"
        fill={`url(#${gradId})`}
        strokeWidth="2"
        className="stroke-[#D5D2C8] dark:stroke-white/14"
      />

      <g transform="rotate(-22 32 32)">
        {/* Exact curvilinear spherical patch bounded by outer sphere & two meridians */}
        <path
          d="M 32 11.5 A 20.5 20.5 0 0 1 52.5 32 A 20.5 8.5 0 0 0 40.81 24.32 A 9.5 20.5 0 0 0 32 11.5 Z"
          className="fill-[#2451D8]/18 dark:fill-[#60A5FA]/24"
        />

        {/* Cranial sphere boundary */}
        <circle
          cx="32"
          cy="32"
          r="20.5"
          strokeWidth={size === 'sm' ? 3.2 : 2.5}
          className="stroke-[#18181B] dark:stroke-[#F3F1EC]"
        />

        {/* Orthogonal 3D geodesic meridians */}
        <ellipse
          cx="32"
          cy="32"
          rx="9.5"
          ry="20.5"
          strokeWidth={size === 'sm' ? 2.4 : 2}
          className="stroke-[#18181B]/34 dark:stroke-[#F3F1EC]/34"
        />
        {size !== 'sm' && (
          <ellipse
            cx="32"
            cy="32"
            rx="20.5"
            ry="8.5"
            strokeWidth="2"
            className="stroke-[#18181B]/34 dark:stroke-[#F3F1EC]/34"
          />
        )}

        {/* Concentrated regional electrode patch arc */}
        <path
          d="M 32 11.5 A 20.5 20.5 0 0 1 52.5 32"
          strokeWidth={size === 'sm' ? 5.8 : 5}
          strokeLinecap="round"
          className="stroke-[#2451D8] dark:stroke-[#60A5FA]"
        />
      </g>
    </svg>
  );
}

/**
 * Custom Parallel-Channel Geometric "EEG" Logotype (Option 03):
 * Twin architectural channel strokes echoing multi-lead EEG traces,
 * accented by an international ultramarine active channel in the center E.
 */
function EegChannelLogotype({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 108 32"
      fill="none"
      className={cn('h-[18px] w-auto shrink-0', className)}
    >
      {/* First E */}
      <path
        d="M 30 3 H 3 V 29 H 30"
        strokeWidth="2.35"
        strokeLinecap="square"
        strokeLinejoin="miter"
        className="stroke-foreground"
      />
      <path
        d="M 30 7.4 H 7.4 V 13.8 H 27"
        strokeWidth="2.35"
        strokeLinecap="square"
        strokeLinejoin="miter"
        className="stroke-foreground"
      />
      <path
        d="M 27 18.2 H 7.4 V 24.6 H 30"
        strokeWidth="2.35"
        strokeLinecap="square"
        strokeLinejoin="miter"
        className="stroke-foreground"
      />

      {/* Second E with active ultramarine center channel */}
      <path
        d="M 66 3 H 39 V 29 H 66"
        strokeWidth="2.35"
        strokeLinecap="square"
        strokeLinejoin="miter"
        className="stroke-foreground"
      />
      <path
        d="M 66 7.4 H 43.4 V 11.4"
        strokeWidth="2.35"
        strokeLinecap="square"
        strokeLinejoin="miter"
        className="stroke-foreground"
      />
      <path
        d="M 43.4 20.6 V 24.6 H 66"
        strokeWidth="2.35"
        strokeLinecap="square"
        strokeLinejoin="miter"
        className="stroke-foreground"
      />
      <line
        x1="43.4"
        y1="13.8"
        x2="63.5"
        y2="13.8"
        strokeWidth="2.45"
        strokeLinecap="square"
        className="stroke-[#2451D8] dark:stroke-[#60A5FA]"
      />
      <line
        x1="43.4"
        y1="18.2"
        x2="63.5"
        y2="18.2"
        strokeWidth="2.45"
        strokeLinecap="square"
        className="stroke-[#2451D8] dark:stroke-[#60A5FA]"
      />

      {/* Circular geometric G */}
      <path
        d="M 99.96 7.64 A 13 13 0 1 0 103 16 H 90.5"
        strokeWidth="2.35"
        strokeLinecap="square"
        strokeLinejoin="miter"
        className="stroke-foreground"
      />
      <path
        d="M 96.59 10.47 A 8.6 8.6 0 1 0 97.39 20.4 H 90.5"
        strokeWidth="2.35"
        strokeLinecap="square"
        strokeLinejoin="miter"
        className="stroke-foreground"
      />
    </svg>
  );
}

/**
 * Option 03 Custom Geometric Wordmark Lockup:
 * - Parallel-channel vector "EEG" with ultramarine center channel
 * - Clean geometric "Layout Lab" optically aligned on baseline
 * - Locale-aware airy subtitle rhythm
 */
export function BrandWordmark({
  subtitle,
  locale = 'zh-CN',
  className,
}: {
  subtitle?: string;
  locale?: string;
  className?: string;
}) {
  const isZh = locale.startsWith('zh');
  return (
    <span className={cn('block leading-none', className)}>
      <span className="flex items-center gap-2">
        <EegChannelLogotype className="translate-y-[0.5px]" />
        <span className="sr-only">EEG </span>
        <span className="text-[1.1rem] font-medium tracking-[-0.022em] text-foreground">
          Layout Lab
        </span>
      </span>
      {subtitle && (
        <span
          className={cn(
            'mt-1.5 hidden text-[11px] font-normal text-muted-foreground sm:block',
            isZh ? 'tracking-[0.16em]' : 'tracking-[0.015em]',
          )}
        >
          {subtitle}
        </span>
      )}
    </span>
  );
}
