'use client';

import type { ReactNode } from 'react';
import { Dialog } from '@base-ui/react/dialog';
import { X } from 'lucide-react';

import { buttonVariants } from '@/components/ui/button';

/** Right-side panel built on the Base UI dialog: focus trap, Escape and backdrop close. */
export function Sheet({ open, onOpenChange, title, description, closeLabel, children }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  closeLabel: string;
  children: ReactNode;
}) {
  return <Dialog.Root open={open} onOpenChange={(next) => onOpenChange(next)}>
    <Dialog.Portal>
      <Dialog.Backdrop className="fixed inset-0 z-50 bg-[#102f3a]/35 transition-opacity duration-200 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0" />
      <Dialog.Popup className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[960px] flex-col bg-background shadow-2xl outline-none transition-transform duration-200 data-[ending-style]:translate-x-full data-[starting-style]:translate-x-full">
        <div className="flex items-start justify-between gap-3 border-b bg-card px-5 py-3">
          <div className="min-w-0">
            <Dialog.Title className="text-base font-semibold">{title}</Dialog.Title>
            {description && <Dialog.Description className="mt-0.5 text-sm text-muted-foreground">{description}</Dialog.Description>}
          </div>
          <Dialog.Close aria-label={closeLabel} className={buttonVariants({ variant: 'outline', size: 'icon' })}><X /></Dialog.Close>
        </div>
        <div className="@container min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
      </Dialog.Popup>
    </Dialog.Portal>
  </Dialog.Root>;
}
