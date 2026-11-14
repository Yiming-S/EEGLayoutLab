'use client';
import { useEffect, useState } from 'react';
import type { SourceResult } from '../../lib/source-reception';
import { peakSourceTime } from './result-view-model';

/** One timeline drives both receiver views, source trace and reconstruction. */
export function useResultPlayback(waveforms: SourceResult['waveforms']) {
  const [time, setTime] = useState(() => peakSourceTime(waveforms));
  const [playing, setPlaying] = useState(false);
  const count = waveforms.time_s.length;
  useEffect(() => {
    if (!playing) return;
    const page = typeof document === 'undefined' ? undefined : document;
    let timer: ReturnType<typeof setInterval> | undefined;
    const stop = () => {
      if (timer !== undefined) clearInterval(timer);
      timer = undefined;
    };
    const syncVisibility = () => {
      stop();
      if (!page?.hidden)
        timer = setInterval(() => {
          if (!page?.hidden) setTime((index) => (index + 5) % count);
        }, 100);
    };
    syncVisibility();
    page?.addEventListener('visibilitychange', syncVisibility);
    return () => {
      stop();
      page?.removeEventListener('visibilitychange', syncVisibility);
    };
  }, [playing, count]);
  return { time, setTime, playing, setPlaying };
}
