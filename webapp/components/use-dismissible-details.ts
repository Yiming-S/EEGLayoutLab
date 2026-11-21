'use client';
import { useEffect, useRef } from 'react';

/** Closes a `<details>` popover on Escape or on a pointer press outside it, as a menu would. */
export function useDismissibleDetails() {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const press = (event: PointerEvent) => {
      const element = ref.current;
      if (element?.open && !element.contains(event.target as Node)) element.open = false;
    };
    const key = (event: KeyboardEvent) => {
      const element = ref.current;
      if (event.key !== 'Escape' || !element?.open) return;
      const focused = element.contains(document.activeElement);
      element.open = false;
      if (focused) element.querySelector('summary')?.focus();
    };
    document.addEventListener('pointerdown', press);
    document.addEventListener('keydown', key);
    return () => {
      document.removeEventListener('pointerdown', press);
      document.removeEventListener('keydown', key);
    };
  }, []);
  return ref;
}
