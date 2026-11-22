'use client';
import { useState, type ChangeEvent, type InputHTMLAttributes } from 'react';
import { Upload } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/**
 * File input with a localized button and file name. Place it inside the field's
 * <label>: the native input stays focusable for keyboards and screen readers,
 * and a click anywhere on the label opens the browser's file dialog.
 */
export function FilePicker({ className, buttonLabel, onChange, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & { buttonLabel?: string }) {
  const { tx } = useLanguage();
  const [names, setNames] = useState<string[]>([]);
  const change = (event: ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(event.target.files ?? []).map(file => file.name);
    if (picked.length) setNames(picked);
    onChange?.(event);
  };
  return <span className={cn('mt-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 font-normal', className)}>
    <input {...props} type="file" className="peer sr-only" onChange={change} />
    <span className={cn(buttonVariants({ variant: 'outline' }), 'cursor-pointer bg-card peer-focus-visible:border-ring peer-focus-visible:ring-3 peer-focus-visible:ring-ring/50 peer-disabled:cursor-not-allowed peer-disabled:bg-muted peer-disabled:text-muted-foreground')}>
      <Upload aria-hidden />{tx(buttonLabel ?? (props.multiple ? '选择文件（可多选）' : '选择文件'))}
    </span>
    <span className="min-w-0 truncate text-sm text-muted-foreground" aria-live="polite">{names.length ? names.join(', ') : tx('未选择文件')}</span>
  </span>;
}
