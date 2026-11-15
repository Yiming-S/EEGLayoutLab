'use client';
import { useEffect, useRef, useState } from 'react';
import { DELIVERY_INPUT_LIMIT, openResearchDelivery, type OpenResearchDelivery } from './research-delivery-reader';

export function useDeliveryReader() {
  const [opened, setOpened] = useState<{ delivery: OpenResearchDelivery; file: File } | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [selectedId, setSelectedId] = useState('');
  const current = useRef<AbortController | null>(null);
  useEffect(() => () => { current.current?.abort(); current.current = null; }, []);

  const clear = (cancelled = false) => {
    current.current?.abort(); current.current = null;
    setOpened(null); setSelectedId(''); setError(''); setStatus('idle');
    setNotice(cancelled ? '读取已取消。' : '');
  };
  const openFile = async (file: File) => {
    current.current?.abort();
    const controller = new AbortController(); current.current = controller;
    setOpened(null); setSelectedId(''); setError(''); setNotice(''); setStatus('loading');
    try {
      if (!Number.isSafeInteger(file.size) || file.size < 0 || file.size > DELIVERY_INPUT_LIMIT) throw new Error('交付包超过大小上限');
      const raw = await file.text();
      if (controller.signal.aborted || current.current !== controller) return;
      const delivery = await openResearchDelivery(raw, controller.signal);
      if (controller.signal.aborted || current.current !== controller) return;
      setOpened({ delivery, file }); setSelectedId(delivery.entries[0]?.entry.id ?? ''); setStatus('ready');
    } catch (caught) {
      if (!controller.signal.aborted && current.current === controller) {
        setError(caught instanceof Error ? caught.message : '交付包无法打开'); setStatus('error');
      }
    } finally { if (current.current === controller) current.current = null; }
  };
  const selected = opened?.delivery.entries.find(row => row.entry.id === selectedId) ?? null;
  const select = (id: string) => { if (opened?.delivery.entries.some(row => row.entry.id === id)) setSelectedId(id); };
  return { opened, status, error, notice, selected, openFile, select, clear };
}
