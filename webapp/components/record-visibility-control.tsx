'use client';
import { useState } from 'react';
import { Globe2, Lock } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import { Button } from '@/components/ui/button';
import { setRecordVisibility } from '@/client/library';
import type { RecordVisibility } from '@/lib/local-library';

/** Short state text for list rows. In the shared scope only an owner's removed record has one. */
export function visibilityLabel(visibility: RecordVisibility | undefined): string | null {
  if (!visibility) return null;
  if (visibility.scope !== 'owner') return visibility.owned && visibility.state === 'removed' ? '已被管理员从共享库移除' : null;
  if (!visibility.owned) return '共享库 · 其他访客公开';
  return { private: '仅本浏览器可见', pending: '已申请公开 · 等待审核', public: '已公开到共享库', removed: '已被管理员从共享库移除' }[visibility.state];
}

/** Owner control: publish to the shared library after an explicit confirmation, or withdraw. */
export function RecordVisibilityControl({ id, name, visibility, onChange }: {
  id: string; name: string; visibility: RecordVisibility | undefined; onChange?: (value: RecordVisibility) => void;
}) {
  const { tx } = useLanguage();
  const [current, setCurrent] = useState(visibility), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const label = visibilityLabel(current);
  if (!current || !label) return null;
  const change = async (value: boolean) => {
    if (value && !window.confirm(tx(`公开后，所有访客都能在共享库看到这条记录：名称「${name}」、电极坐标、计算参数和指标。可随时撤回公开。确认公开？`))) return;
    setBusy(true); setError('');
    try { const next = await setRecordVisibility(id, value); setCurrent(next); onChange?.(next); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };
  const Icon = current.state === 'public' || current.state === 'pending' ? Globe2 : Lock;
  return <section aria-label={tx('共享库可见范围')} className="lab-panel flex flex-wrap items-center justify-between gap-3 text-sm">
    <div className="min-w-0 space-y-1">
      <p className="flex items-center gap-2 font-medium"><Icon className="size-4" aria-hidden="true" />{tx(label)}</p>
      {current.owned && current.state === 'private' && <p className="text-muted-foreground">{tx('只有提交过这条记录的浏览器能在列表中看到它；持有记录链接的人仍可打开。')}</p>}
      {current.owned && current.state === 'pending' && <p className="text-muted-foreground">{tx('管理员审核通过后，其他访客才能在共享库看到它。')}</p>}
      {current.owned && current.state === 'public' && !current.published_by_me && <p className="text-muted-foreground">{tx('提交过同一配置的另一个浏览器已公开这条记录。')}</p>}
      {current.state === 'removed' && current.reason && <p className="text-muted-foreground">{tx('移除原因：')}{current.reason}</p>}
      {error && <p role="alert" className="text-red-800"><RuntimeMessage message={error} /></p>}
    </div>
    {current.owned && current.scope === 'owner' && (current.published_by_me
      ? <Button variant="outline" size="sm" disabled={busy} onClick={() => void change(false)}>{tx('撤回公开')}</Button>
      : current.state !== 'removed' && current.state !== 'public' && <Button variant="outline" size="sm" disabled={busy} onClick={() => void change(true)}>{tx('公开到共享库')}</Button>)}
  </section>;
}
