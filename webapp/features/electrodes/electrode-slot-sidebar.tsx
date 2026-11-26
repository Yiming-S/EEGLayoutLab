'use client';

import type { Dispatch, SetStateAction } from 'react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useLanguage } from '@/components/language-provider';
import {
  editHistory,
  initialSlots,
  type EditHistory,
  type EditorDomain,
  type Slot,
} from '@/lib/electrode-editor';
import { MASK_NAMES } from '@/lib/ui-language';

export function ElectrodeSlotSidebar({
  domain,
  layout,
  allocation,
  slots,
  selection,
  setSelection,
  select,
  commit,
  history,
  setHistory,
  coords,
  candidate,
  setCandidate,
  move,
  busy,
  evaluate,
  saveDraft,
  readDraft,
}: {
  domain: EditorDomain;
  layout: { regionIndices: number[] };
  allocation: number[];
  slots: Slot[];
  selection: number[];
  setSelection: Dispatch<SetStateAction<number[]>>;
  select: (index: number, additive: boolean) => void;
  commit: (next: Slot[]) => void;
  history: EditHistory;
  setHistory: Dispatch<SetStateAction<EditHistory>>;
  coords: number[] | null | undefined;
  candidate: string;
  setCandidate: Dispatch<SetStateAction<string>>;
  move: (slotIndex: number, bankIndex: number) => void;
  busy: boolean;
  evaluate: () => void;
  saveDraft: () => void;
  readDraft: () => void;
}) {
  const { tx } = useLanguage();

  return (
    <aside className="space-y-4">
      <section className="lab-panel space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-baseline gap-2">
            <h2 className="text-base font-semibold">{tx('选择电极')}</h2>
            <span className="text-xs font-medium text-primary tabular-nums">
              {tx(`已选中 ${selection.length} 个电极`)}
            </span>
          </div>
          <div className="flex gap-1.5">
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                setSelection(Array.from({ length: 64 }, (_, i) => i))
              }
            >
              {tx('全选')}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!selection.length}
              onClick={() => setSelection([])}
            >
              {tx('清空选择')}
            </Button>
          </div>
        </div>
        <p className="text-xs leading-5 text-muted-foreground">
          {tx(
            '点击点位选择；Shift点击多选。也可在下方按编号选择。拖动仅在编辑模式生效。',
          )}
        </p>
        <div className="max-h-[340px] space-y-3 overflow-y-auto pr-1">
          {allocation.map((count, r) => (
            <fieldset className="rounded-lg border p-2.5" key={r}>
              <legend className="px-1.5 text-xs font-semibold">
                <span
                  aria-hidden="true"
                  className="mr-1.5 inline-block size-2.5 rounded-full align-middle"
                  style={{
                    backgroundColor:
                      [
                        '#128a80',
                        '#376ec6',
                        '#c8811b',
                        '#8655ac',
                        '#c34f68',
                        '#598d37',
                      ][r] ?? '#128a80',
                  }}
                />
                {tx(
                  MASK_NAMES[domain.parent.request?.mask_codes?.[r] ?? ''] ??
                    `原区域 ${r + 1}`,
                )}{' '}
                ·{' '}
                {tx(
                  `启用 ${count} / 原有 ${layout.regionIndices.filter((v) => v === r).length} 点`,
                )}
              </legend>
              <button
                type="button"
                className="mb-2 text-xs text-primary underline underline-offset-2"
                onClick={() =>
                  setSelection(
                    layout.regionIndices.flatMap((v, i) =>
                      v === r ? [i] : [],
                    ),
                  )
                }
              >
                {tx('选择此区域全部点')}
              </button>
              <div className="grid grid-cols-4 gap-1.5 sm:grid-cols-6 lg:grid-cols-4 xl:grid-cols-5">
                {slots.map((s, i) =>
                  layout.regionIndices[i] !== r ? null : (
                    <label
                      key={i}
                      className={`flex min-h-8 cursor-pointer items-center gap-1 rounded border px-1.5 font-mono text-xs transition-colors ${selection.includes(i) ? 'border-primary bg-primary/10 font-medium' : ''} ${s.enabled ? '' : 'bg-muted text-muted-foreground line-through'}`}
                    >
                      <Checkbox
                        checked={selection.includes(i)}
                        onCheckedChange={() => select(i, true)}
                        aria-label={`E${i + 1}`}
                      />
                      E{String(i + 1).padStart(2, '0')}
                    </label>
                  ),
                )}
              </div>
            </fieldset>
          ))}
        </div>
      </section>
      <section className="lab-panel space-y-3.5">
        <h2 className="text-base font-semibold">{tx('编辑与保存评价')}</h2>
        <div className="grid grid-cols-2 gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={!selection.length || busy}
            onClick={() =>
              commit(
                slots.map((s, i) =>
                  selection.includes(i) ? { ...s, enabled: false } : s,
                ),
              )
            }
          >
            {tx('移除选中电极')}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={!selection.length || busy}
            onClick={() =>
              commit(
                slots.map((s, i) =>
                  selection.includes(i) ? { ...s, enabled: true } : s,
                ),
              )
            }
          >
            {tx('恢复选中电极')}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={!history.past.length || busy}
            onClick={() => setHistory((h) => editHistory(h, 'undo'))}
          >
            {tx('撤销')}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={!history.future.length || busy}
            onClick={() => setHistory((h) => editHistory(h, 'redo'))}
          >
            {tx('重做')}
          </Button>
        </div>
        <Button
          size="sm"
          variant="outline"
          className="w-full"
          disabled={busy}
          onClick={() => commit(initialSlots(domain))}
        >
          {tx('恢复原始布局')}
        </Button>
        {selection.length === 1 ? (
          <div className="border-t pt-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <strong>E{String(selection[0] + 1).padStart(2, '0')}</strong>
              <span className="font-mono text-xs text-muted-foreground">
                {coords?.map((v: number) => v.toFixed(3)).join(', ')} mm
              </span>
            </div>
            <label
              id="editor-candidate-label"
              className="mt-2.5 block text-xs font-medium"
            >
              {tx('候选点位（编号）')}
            </label>
            <Select
              value={candidate || String(slots[selection[0]].bank_index)}
              disabled={busy}
              onValueChange={(value) => setCandidate(value ?? '')}
            >
              <SelectTrigger
                aria-labelledby="editor-candidate-label"
                className="mt-1.5 min-h-10 w-full"
              >
                <SelectValue>
                  {candidate || String(slots[selection[0]].bank_index)}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {domain.regions[
                  layout.regionIndices[selection[0]]
                ].bank_indices.map((n, i) => (
                  <SelectItem value={String(n)} key={n}>
                    {n} ·{' '}
                    {domain.regions[layout.regionIndices[selection[0]]].xyz_mm[
                      i
                    ]
                      .map((v) => v.toFixed(1))
                      .join(', ')}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              size="sm"
              variant="outline"
              className="mt-2 w-full"
              disabled={busy || !candidate}
              onClick={() => {
                move(selection[0], Number(candidate));
                setCandidate('');
              }}
            >
              {tx('移动到此点')}
            </Button>
          </div>
        ) : (
          <p className="border-t pt-3 text-xs leading-5 text-muted-foreground">
            {tx('选择一个电极，可用候选编号精确移动；也可直接拖动。')}
          </p>
        )}
        <p className="border-t pt-3 text-xs leading-5 text-muted-foreground">
          {tx('区内候选点吸附 · 最小点距4 mm · 移除不补点 · 原编号保持不变')}
        </p>
        <div className="space-y-2">
          <Button className="w-full" disabled={busy} onClick={evaluate}>
            {tx('评价并另存此布局')}
          </Button>
          <div className="grid grid-cols-2 gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={saveDraft}
              disabled={busy}
            >
              {tx('保存草稿到当前浏览器')}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={readDraft}
              disabled={busy}
            >
              {tx('读取已存草稿')}
            </Button>
          </div>
        </div>
      </section>
    </aside>
  );
}
