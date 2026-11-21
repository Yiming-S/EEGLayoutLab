'use client';
import { lazy, Suspense, type ComponentProps } from 'react';
import type { ClusterHeadViewer } from '@/components/cluster-head-viewer';
import { useLanguage } from '@/components/language-provider';
import { useDeferredHead } from './use-deferred-head';

const Head = lazy(() =>
  import('@/components/cluster-head-viewer').then((module) => ({
    default: module.ClusterHeadViewer,
  })),
);

export function DeferredHeadViewer(
  props: ComponentProps<typeof ClusterHeadViewer>,
) {
  const { tx, locale } = useLanguage();
  const { active, hostRef, activate } = useDeferredHead();
  const height = props.sourceXyzMm?.length
    ? 'h-[min(80svh,700px)] sm:h-[790px]'
    : props.compact
      ? 'h-[min(75svh,580px)] sm:h-[520px]'
      : 'h-[min(75svh,640px)] sm:h-[690px]';
  const placeholder = (
    <div
      className={`${height} flex items-center justify-center rounded-2xl border bg-muted/20`}
    >
      {active ? (
        <output>{tx('加载3D…')}</output>
      ) : (
        <button
          type="button"
          onClick={activate}
          className="rounded-lg border px-4 py-2 text-sm"
        >
          {locale === 'en' ? 'Load 3D view' : '加载三维视图'}
        </button>
      )}
    </div>
  );
  return (
    <div ref={hostRef} data-deferred-head={active ? 'active' : 'waiting'}>
      {active ? (
        <Suspense fallback={placeholder}>
          <Head {...props} />
        </Suspense>
      ) : (
        placeholder
      )}
    </div>
  );
}
