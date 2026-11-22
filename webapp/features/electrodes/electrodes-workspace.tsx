'use client';
/* oxlint-disable next/no-html-link-for-pages */
import { lazy, Suspense } from 'react';
import { SiteHeader } from '@/components/site-header';

import { RuntimeMessage } from '@/components/runtime-message';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { MASK_NAMES } from '@/lib/ui-language';
import { localizedRecordTitle, localizedEditorParentTitle } from '@/lib/i18n/records';

import { initialSlots, editHistory, editorLink } from '@/lib/electrode-editor';
import { useElectrodesController, running } from './use-electrodes-controller';
import { useConfirmDialog } from '@/components/ui/confirm-dialog';

const Head = lazy(() =>
  import('@/components/cluster-head-viewer').then((m) => ({
    default: m.ClusterHeadViewer,
  })),
);

export default function ElectrodesPage() {
  const {
    tx,
    locale,
    date,
    parents,
    parentId,
    setParentId,
    domain,
    history,
    setHistory,
    selection,
    setSelection,
    editMode,
    setEditMode,
    ar,
    setAr,
    candidate,
    setCandidate,
    job,
    pending,
    connection,
    error,
    notice,
    records,
    slots,
    busy,
    commit,
    select,
    move,
    layout,
    allocation,
    editor,
    result,
    activeCount,
    originalLayout,
    coords,
    evaluate,
    cancel,
    reconnect,
    saveDraft,
    readDraft,
    switchLayout: loadLayout,
    dirty,
    exportResult,
  } = useElectrodesController();
  const { confirm, dialog } = useConfirmDialog();
  const switchLayout = async (id: string, record?: Parameters<typeof loadLayout>[1]) => {
    if (dirty && !(await confirm({ title: '切换布局', message: '当前有未保存的编辑，确认切换布局？', confirmLabel: '放弃编辑并切换', destructive: true }))) return;
    loadLayout(id, record);
  };
  return (
    <main className="lab-page">
      {dialog}
      <SiteHeader
        current="electrodes"
        selection={{
          id: domain?.parent.id ?? null,
          phase: domain && !originalLayout ? 'edited' : 'saved',
          channels: domain ? activeCount : undefined,
          regions: domain ? allocation.filter((n) => n > 0).length : undefined,
        }}
        arPercent={ar}
        returnHref={
          domain
            ? editorLink(domain.parent.id, ar) +
              (!originalLayout ? '&resume=1' : '')
            : '/electrodes?ar=' + ar
        }
      />
      <div className="lab-container">
        <header className="py-5">
          <h1 className="text-2xl font-semibold">
            {tx('电极编辑：调整点位与启用数量')}
          </h1>
          <p className="mt-2 text-base text-muted-foreground">
            {tx('从已有布局创建副本。原区域边界不变，原始64点记录不被覆盖。')}
          </p>
        </header>
        <section className="lab-panel mb-4 flex flex-wrap items-end gap-3">
          <div className="min-w-0 flex-1 text-sm font-medium">
            <label id="editor-parent-label">{tx('选择来源布局')}</label>
            <Select
              value={parentId || null}
              onValueChange={(value) => setParentId(value ?? '')}
              disabled={busy}
            >
              <SelectTrigger
                aria-labelledby="editor-parent-label"
                className="mt-2 min-h-11 w-full"
              >
                <SelectValue>
                  {parents.find((p) => p.id === parentId)
                    ? localizedRecordTitle(
                        parents.find((p) => p.id === parentId)!,
                        locale,
                      )
                    : tx('选择来源布局')}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {parents.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {localizedRecordTitle(p, locale)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            disabled={!parentId || busy}
            onClick={() => void switchLayout(parentId)}
          >
            {tx('载入编辑器')}
          </Button>
          <p className="w-full text-sm text-muted-foreground">
            {tx(
              '载入后显示真实点位与可移动范围。历史记录若未保存区域边界，需要先在布局设计中生成新版布局。',
            )}
          </p>
        </section>
        {error && (
          <div
            role="alert"
            className="lab-panel mb-4 border-danger/40 text-danger"
          >
            <strong>{tx('本次操作未完成')}</strong>
            <details className="mt-2 text-sm">
              <summary>{tx('查看诊断详情')}</summary>
              <RuntimeMessage message={error} />
            </details>
          </div>
        )}
        {notice && (
          <output
            className="mb-4 block rounded-lg border border-warning/40 bg-warning-surface p-3 text-sm"
            aria-live="polite"
          >
            {tx(notice)}
          </output>
        )}
        {job && connection !== 'connected' && (
          <div className="lab-panel mb-4">
            <p className="mb-3">{tx('状态连接中断，后台任务尚未确认结束。')}</p>
            <Button onClick={reconnect} disabled={pending}>
              {tx('重新查询任务')}
            </Button>
            <Button variant="outline" className="ml-2" onClick={cancel}>
              {tx('停止当前任务')}
            </Button>
          </div>
        )}
        {busy && (
          <output className="lab-panel mb-4 block">
            <div className="flex items-center justify-between">
              <span>
                {job?.status === 'queued'
                  ? <RuntimeMessage message={job.message} status="queued" queuePosition={job.queue_position} />
                  : <>{tx('正在处理布局')} · {Math.round((job?.progress ?? 0) * 100)}%</>}
              </span>
              <Button
                variant="outline"
                onClick={cancel}
                disabled={!running(job)}
              >
                {tx('停止当前任务')}
              </Button>
            </div>
            <progress
              className="mt-3 w-full"
              value={job?.progress ?? 0}
              max={1}
            />
          </output>
        )}
        {domain && layout && (
          <>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <p className="text-lg font-semibold">
                {tx(
                  `当前启用 ${activeCount} 点 · ${allocation.filter(Boolean).length} 个有电极区域 / ${allocation.length} 个原区域`,
                )}
              </p>
              <div className="flex gap-2">
                <Button
                  variant={!editMode ? 'default' : 'outline'}
                  aria-pressed={!editMode}
                  onClick={() => setEditMode(false)}
                >
                  {tx('查看模式')}
                </Button>
                <Button
                  variant={editMode ? 'default' : 'outline'}
                  disabled={busy}
                  aria-pressed={editMode}
                  onClick={() => setEditMode(true)}
                >
                  {tx('编辑模式')}
                </Button>
              </div>
            </div>
            <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
              <Suspense
                fallback={
                  <div className="lab-panel min-h-[600px]">
                    {tx('加载三维头部…')}
                  </div>
                }
              >
                <Head
                  regionCount={domain.parent.region_count}
                  allocation={allocation}
                  domainMode="whole_surface"
                  radiusCm={3.5}
                  recordedLayout={layout}
                  editor={editor}
                />
              </Suspense>
              <aside className="lab-panel space-y-4">
                <h2 className="text-lg font-semibold">{tx('选择电极')}</h2>
                <p className="text-sm leading-6 text-muted-foreground">
                  {tx(
                    '点击点位选择；Shift点击多选。也可在下方按编号选择。拖动仅在编辑模式生效。',
                  )}
                </p>
                <div className="grid grid-cols-2 gap-2">
                  <Button
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
                    variant="outline"
                    disabled={!history.past.length || busy}
                    onClick={() => setHistory((h) => editHistory(h, 'undo'))}
                  >
                    {tx('撤销')}
                  </Button>
                  <Button
                    variant="outline"
                    disabled={!history.future.length || busy}
                    onClick={() => setHistory((h) => editHistory(h, 'redo'))}
                  >
                    {tx('重做')}
                  </Button>
                </div>
                <Button
                  variant="outline"
                  className="w-full"
                  disabled={busy}
                  onClick={() => commit(initialSlots(domain))}
                >
                  {tx('恢复原始布局')}
                </Button>
                {selection.length === 1 ? (
                  <div className="border-t pt-3">
                    <strong>
                      E{String(selection[0] + 1).padStart(2, '0')}
                    </strong>
                    <p className="mt-1 font-mono text-sm">
                      {coords?.map((v: number) => v.toFixed(3)).join(', ')} mm
                    </p>
                    <label
                      id="editor-candidate-label"
                      className="mt-3 block text-sm"
                    >
                      {tx('候选点位（编号）')}
                    </label>
                    <Select
                      value={
                        candidate || String(slots[selection[0]].bank_index)
                      }
                      disabled={busy}
                      onValueChange={(value) => setCandidate(value ?? '')}
                    >
                      <SelectTrigger
                        aria-labelledby="editor-candidate-label"
                        className="mt-2 min-h-11 w-full"
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
                            {domain.regions[
                              layout.regionIndices[selection[0]]
                            ].xyz_mm[i]
                              .map((v) => v.toFixed(1))
                              .join(', ')}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
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
                  <p className="text-sm text-muted-foreground">
                    {tx('选择一个电极，可用候选编号精确移动；也可直接拖动。')}
                  </p>
                )}
                <p className="border-t pt-3 text-sm leading-6">
                  {tx(
                    '区内候选点吸附 · 最小点距4 mm · 移除不补点 · 原编号保持不变',
                  )}
                </p>
                <div className="flex flex-col gap-2">
                  <Button disabled={busy} onClick={evaluate}>
                    {tx('评价并另存此布局')}
                  </Button>
                  <Button variant="outline" onClick={saveDraft} disabled={busy}>
                    {tx('保存草稿到当前浏览器')}
                  </Button>
                  <Button variant="outline" onClick={readDraft} disabled={busy}>
                    {tx('读取已存草稿')}
                  </Button>
                </div>
              </aside>
            </div>
            <p className="my-3 text-sm text-muted-foreground">
              {tx(
                `继承区域总面积 ${(domain.parent.layout!.regionAreasCm2 ?? []).reduce((a, b) => a + b, 0).toFixed(2)} cm²；删点不会缩小区域边界。`,
              )}
            </p>
            <section className="lab-panel">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-lg font-semibold">{tx('选择电极')}</h2>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    onClick={() =>
                      setSelection(Array.from({ length: 64 }, (_, i) => i))
                    }
                  >
                    {tx('全选')}
                  </Button>
                  <Button variant="outline" onClick={() => setSelection([])}>
                    {tx('清空选择')}
                  </Button>
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                {allocation.map((count, r) => (
                  <fieldset className="rounded-lg border p-3" key={r}>
                    <legend className="px-2 font-semibold">
                      {tx(
                        MASK_NAMES[
                          domain.parent.request?.mask_codes?.[r] ?? ''
                        ] ?? `原区域 ${r + 1}`,
                      )}{' '}
                      ·{' '}
                      {tx(
                        `启用 ${count} / 原有 ${layout.regionIndices.filter((v) => v === r).length} 点`,
                      )}
                    </legend>
                    <button
                      type="button"
                      className="mb-3 text-sm text-primary underline"
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
                    <div className="grid grid-cols-4 gap-2 sm:grid-cols-6">
                      {slots.map((s, i) =>
                        layout.regionIndices[i] !== r ? null : (
                          <label
                            key={i}
                            className={`flex min-h-10 cursor-pointer items-center gap-1.5 rounded border px-2 text-sm ${selection.includes(i) ? 'border-primary bg-primary/10' : ''} ${s.enabled ? '' : 'bg-muted text-muted-foreground line-through'}`}
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
            <section className="lab-panel mt-4">
              <h2 className="text-lg font-semibold">
                {tx('标准64、原始布局与编辑布局')}
              </h2>
              <p className="my-3 text-sm leading-6 text-muted-foreground">
                {tx(
                  '三套布局按本次统一协议重新评价：同一头模与源先验、相同物理噪声、固定标准64重建目标。历史定位分数不直接混入此表。',
                )}
              </p>
              {!result ? (
                <p className="rounded-lg bg-muted p-4">
                  {tx('当前草稿尚未评价。下方原评分不作为编辑后结果。')}
                </p>
              ) : (
                <>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                      <thead>
                        <tr className="border-b">
                          <th className="p-3">{tx('评价指标')}</th>
                          {[
                            '标准全头64导',
                            '原始区域布局 · 64点',
                            `编辑布局 · ${activeCount}点`,
                            '相对原布局变化',
                          ].map((t) => (
                            <th className="p-3" key={t}>
                              {tx(t)}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {(
                          [
                            ['field_absolute', '重建解释率（绝对）', 'percent'],
                            ['field_relative', '场重建保留率', 'percent'],
                            ['sensitivity_tail', '弱源敏感度', 'percent'],
                            [
                              'localization_relative',
                              '定位效用保留率',
                              'percent',
                            ],
                            ['median_mm', '定位误差中位数', 'mm'],
                            ['p90_mm', '定位误差90分位数', 'mm'],
                          ] as const
                        ).map(([key, label, unit]) => {
                          const a = result.edited_metrics[key],
                            b = result.parent_metrics[key],
                            delta =
                              a == null || b == null
                                ? null
                                : (a - b) * (unit === 'mm' ? 1 : 100);
                          return (
                            <tr className="border-b" key={key}>
                              <th className="p-3 font-medium">{tx(label)}</th>
                              {[
                                result.baseline,
                                result.parent_metrics,
                                result.edited_metrics,
                              ].map((m, i) => (
                                <td className="p-3 tabular-nums" key={i}>
                                  {m[key] == null
                                    ? tx('指标无法计算')
                                    : unit === 'mm'
                                      ? `${m[key].toFixed(2)} mm`
                                      : `${(m[key] * 100).toFixed(2)}%`}
                                </td>
                              ))}
                              <td className="p-3 tabular-nums">
                                {delta == null
                                  ? '—'
                                  : `${delta > 0 ? '+' : ''}${delta.toFixed(2)} ${unit === 'mm' ? 'mm' : tx('百分点')}`}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  {result.edited_metrics.localization_unavailable ===
                    'single_contrast_unknown_amplitude' && (
                    <p className="mt-3 text-sm">
                      {tx(
                        '两个电极只有一个参考无关维度；当前未知振幅定位模型无法辨识源位置，不提供三项共同达标结论。',
                      )}
                    </p>
                  )}
                  <label className="mt-4 block text-sm font-medium">
                    {tx('最低保留要求')} · {ar}%
                    <input
                      type="range"
                      min={1}
                      max={100}
                      value={ar}
                      onChange={(e) => {
                        const value = Number(e.target.value);
                        setAr(value);
                        const href = new URL(window.location.href);
                        href.searchParams.set('ar', String(value));
                        if (!originalLayout)
                          href.searchParams.set('resume', '1');
                        window.history.replaceState(
                          null,
                          '',
                          href.pathname + href.search + href.hash,
                        );
                      }}
                      className="mt-2 block w-full accent-primary"
                    />
                  </label>
                  <p className="mt-2 font-medium">
                    {tx(
                      result.edited_metrics.conditional_global == null
                        ? '部分指标不可用，不能给出三项共同达标结论'
                        : result.edited_metrics.conditional_global >= ar / 100
                          ? '三项均达到最低保留要求'
                          : '尚未全部达到最低保留要求',
                    )}
                  </p>
                  <Button
                    className="mt-4"
                    variant="outline"
                    onClick={exportResult}
                  >
                    {tx('导出本次评价JSON')}
                  </Button>
                  {job?.cached && (
                    <span className="ml-3 text-sm">
                      {tx('本次评价读取有效缓存')}
                    </span>
                  )}
                </>
              )}
            </section>
          </>
        )}
        <section className="lab-panel mt-5" id="records">
          <h2 className="text-lg font-semibold">{tx('独立电极编辑记录')}</h2>
          <p className="my-3 text-sm leading-6 text-muted-foreground">
            {tx(
              '已完成评价单独缓存，不加入固定64点实验曲线。载入后可继续编辑；再次评价相同配置会优先读取有效缓存。',
            )}
          </p>
          {!records.length ? (
            <p className="text-sm text-muted-foreground">
              {tx('尚无电极编辑评价记录。')}
            </p>
          ) : (
            <ul className="space-y-3">
              {records.map((r) => (
                <li
                  key={r.key}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3"
                >
                  <div>
                    <p className="font-medium">
                      {tx(`编辑布局 · ${r.electrode_count}点`)} ·{' '}
                      {localizedEditorParentTitle(r, parents, locale)}
                    </p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {date(r.finished_at, true)} · {tx('信号重建保留率')}{' '}
                      {(r.metrics.field_relative * 100).toFixed(2)}%
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {tx('已保存评分')} · {r.protocol} ·{' '}
                      {tx('载入为草稿，重新评价时检查协议与缓存')}
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() => void switchLayout(r.parent_id, r)}
                  >
                    {tx('载入此编辑记录')}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  );
}
