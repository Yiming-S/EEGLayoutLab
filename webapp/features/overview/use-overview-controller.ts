'use client';
import { useEffect, useMemo, useState } from 'react';
import { apiJson } from '@/client/task-client';
import { preserveResultsContext } from '@/lib/results-library';
import { areaRows, parseAR, REGION_COUNTS, AREA_CAPS, METRICS } from '@/lib/lab-workflow';
import type { LocalLibrary } from '@/lib/local-library';

export function useOverviewController() {
  const [data, setData] = useState<LocalLibrary | null>(null);
  const [viewContext, setViewContext] = useState('');
  const [domain, setDomain] = useState('whole_scalp_free'), [area, setArea] = useState(120), [r, setR] = useState(2), [ar, setAR] = useState(90);
  const [metric, setMetric] = useState<(typeof METRICS)[number]['key']>('field_relative');
  const [error, setError] = useState(''), [retry, setRetry] = useState(0), [ready, setReady] = useState(false);
  useEffect(() => {
    const restore = () => {
      const q = new URLSearchParams(window.location.search);
      setViewContext(window.location.search);
      if (q.has('saved')) { window.location.replace(`/design?${q.toString()}`); return; }
      setDomain(q.get('domain') === 'low_hair_free' ? 'low_hair_free' : 'whole_scalp_free');
      setArea(AREA_CAPS.includes(Number(q.get('area'))) ? Number(q.get('area')) : 120);
      setR(REGION_COUNTS.includes(Number(q.get('r'))) ? Number(q.get('r')) : 2);
      setAR(parseAR(q.get('ar'))); setMetric(METRICS.find((m) => m.key === q.get('metric'))?.key ?? 'field_relative'); setReady(true);
    };
    restore(); window.addEventListener('popstate', restore); return () => window.removeEventListener('popstate', restore);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void apiJson<LocalLibrary>('/api/local-compute/library', { signal: controller.signal, errorMessage: '当前比较需要数据服务，请稍后重新读取。' }).then((value) => {
      if (value.schema !== 'local-data-library/1') throw new Error('结果目录格式不符');
      setData(value); setError('');
    }).catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [retry]);
  const rows = areaRows(data?.records ?? [], domain, area), selected = rows.find((row) => row?.region_count === r);
  useEffect(() => { if (ready) window.history.replaceState(null, '', preserveResultsContext(`/?domain=${domain}&area=${area}&r=${r}&ar=${ar}&metric=${metric}`, viewContext)); }, [ready, domain, area, r, ar, metric, viewContext]);
  const curve = useMemo(() => AREA_CAPS.map((a) => {
    const point: Record<string, number | null> = { area: a };
    areaRows(data?.records ?? [], domain, a).forEach((row, i) => { const value = row?.metrics?.[metric]; point[`r${REGION_COUNTS[i]}`] = value == null ? null : value * 100; });
    return point;
  }), [data, domain, metric]);
  const inspect = (count: number) => setR(count);
  const here = preserveResultsContext(`/?domain=${domain}&area=${area}&r=${r}&ar=${ar}&metric=${metric}`, viewContext);
  return { data, domain, setDomain, area, setArea, r, setR, ar, setAR, metric, setMetric, error, setRetry, rows, selected, curve, inspect, here };
}
