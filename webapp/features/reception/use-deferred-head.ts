'use client';
import { useEffect, useState } from 'react';

/** Activate once; scrolling away preserves the viewer's camera and selection. */
export function useDeferredHead() {
  const [element, setElement] = useState<HTMLDivElement | null>(null);
  const [active, setActive] = useState(false);
  useEffect(() => {
    if (active || !element) return;
    let disposed = false;
    if (typeof IntersectionObserver === 'undefined') {
      queueMicrotask(() => {
        if (!disposed) setActive(true);
      });
      return () => {
        disposed = true;
      };
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (!disposed && entries.some((entry) => entry.isIntersecting)) {
          observer.disconnect();
          setActive(true);
        }
      },
      { rootMargin: '200px' },
    );
    observer.observe(element);
    return () => {
      disposed = true;
      observer.disconnect();
    };
  }, [active, element]);
  return { active, hostRef: setElement, activate: () => setActive(true) };
}
