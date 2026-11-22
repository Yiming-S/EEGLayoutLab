'use client';
import { useState, type ReactNode } from 'react';
import { Dialog } from '@base-ui/react/dialog';
import { useLanguage } from '@/components/language-provider';
import { buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';

type Request = { title: string; message: string; confirmLabel: string; destructive: boolean; resolve: (confirmed: boolean) => void };

/**
 * In-app replacement for window.confirm. `confirm()` resolves true only when
 * the confirm button is pressed; Escape, the backdrop and Cancel resolve false.
 * Render `dialog` once in the component that calls `confirm`.
 */
export function useConfirmDialog(): { confirm: (options: { title: string; message: string; confirmLabel: string; destructive?: boolean }) => Promise<boolean>; dialog: ReactNode } {
  const { tx } = useLanguage();
  // The last request stays mounted while the dialog animates closed.
  const [request, setRequest] = useState<Request | null>(null), [open, setOpen] = useState(false);
  const confirm = (options: { title: string; message: string; confirmLabel: string; destructive?: boolean }) =>
    new Promise<boolean>(resolve => { setRequest({ destructive: false, ...options, resolve }); setOpen(true); });
  const settle = (confirmed: boolean) => { if (open) request?.resolve(confirmed); setOpen(false); };
  const dialog = <Dialog.Root open={open} onOpenChange={open => { if (!open) settle(false); }}>
    <Dialog.Portal>
      <Dialog.Backdrop className="fixed inset-0 z-50 bg-brand/35 transition-opacity duration-150 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0" />
      <Dialog.Popup className="fixed top-1/2 left-1/2 z-50 w-[min(440px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-xl border bg-card p-5 shadow-2xl outline-none transition-[opacity,scale] duration-150 data-[ending-style]:scale-95 data-[ending-style]:opacity-0 data-[starting-style]:scale-95 data-[starting-style]:opacity-0">
        <Dialog.Title className="text-base font-semibold">{request && tx(request.title)}</Dialog.Title>
        <Dialog.Description className="mt-2 text-sm leading-6 text-muted-foreground">{request && tx(request.message)}</Dialog.Description>
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <Dialog.Close className={buttonVariants({ variant: 'outline', size: 'lg' })}>{tx('取消')}</Dialog.Close>
          <button type="button" className={cn(buttonVariants({ variant: request?.destructive ? 'destructive' : 'default', size: 'lg' }), 'px-4')} onClick={() => settle(true)}>{request && tx(request.confirmLabel)}</button>
        </div>
      </Dialog.Popup>
    </Dialog.Portal>
  </Dialog.Root>;
  return { confirm, dialog };
}
