'use client';
/* oxlint-disable next/no-html-link-for-pages */
import { lazy, Suspense } from 'react';
import { SiteHeader } from '@/components/site-header';
import { RuntimeMessage } from '@/components/runtime-message';
import { ShowcaseComputeNotice } from '@/components/showcase-banner';
import { Button } from '@/components/ui/button';
import { useConfirmDialog } from '@/components/ui/confirm-dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { editorLink } from '@/lib/electrode-editor';
import {
  localizedEditorParentTitle,
  localizedRecordTitle,
} from '@/lib/i18n/records';
import { SHOWCASE } from '@/lib/showcase';
import { EditorComparisonSection } from './editor-comparison-section';
import { ElectrodeSlotSidebar } from './electrode-slot-sidebar';
import { running, useElectrodesController } from './use-electrodes-controller';

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
  const switchLayout = async (
    id: string,
    record?: Parameters<typeof loadLayout>[1],
  ) => {
    if (
      dirty &&
      !(await confirm({
        title: '切换布局',
        message: '当前有未保存的编辑，确认切换布局？',
        confirmLabel: '放弃编辑并切换',
        destructive: true,
      }))
    )
      return;
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
        <header className="mb-5 border-b border-border pt-7 pb-5">
          <h1 className="text-2xl font-semibold tracking-[-0.028em] sm:text-[1.65rem]">
            {tx('电极编辑：调整点位与启用数量')}
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
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
            disabled={!parentId || busy || SHOWCASE}
            onClick={() => void switchLayout(parentId)}
          >
            {tx('载入编辑器')}
          </Button>
          {SHOWCASE ? (
            <ShowcaseComputeNotice className="w-full" />
          ) : (
            <p className="w-full text-sm text-muted-foreground">
              {tx(
                '载入后显示真实点位与可移动范围。历史记录若未保存区域边界，需要先在布局设计中生成新版布局。',
              )}
            </p>
          )}
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
                {job?.status === 'queued' ? (
                  <RuntimeMessage
                    message={job.message}
                    status="queued"
                    queuePosition={job.queue_position}
                  />
                ) : (
                  <>
                    {tx('正在处理布局')} · {Math.round((job?.progress ?? 0) * 100)}
                    %
                  </>
                )}
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
            <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_380px] xl:grid-cols-[minmax(0,1fr)_420px]">
              <div className="min-w-0 lg:sticky lg:top-[calc(var(--workspace-header-height,0px)+0.75rem)]">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <p className="text-base font-semibold sm:text-lg">
                    {tx(
                      `当前启用 ${activeCount} 点 · ${allocation.filter(Boolean).length} 个有电极区域 / ${allocation.length} 个原区域`,
                    )}
                  </p>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant={!editMode ? 'default' : 'outline'}
                      aria-pressed={!editMode}
                      onClick={() => setEditMode(false)}
                    >
                      {tx('查看模式')}
                    </Button>
                    <Button
                      size="sm"
                      variant={editMode ? 'default' : 'outline'}
                      disabled={busy}
                      aria-pressed={editMode}
                      onClick={() => setEditMode(true)}
                    >
                      {tx('编辑模式')}
                    </Button>
                  </div>
                </div>
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
                <p className="mt-2.5 text-xs leading-5 text-muted-foreground sm:text-sm">
                  {tx(
                    `继承区域总面积 ${(domain.parent.layout!.regionAreasCm2 ?? []).reduce((a, b) => a + b, 0).toFixed(2)} cm²；删点不会缩小区域边界。`,
                  )}
                </p>
              </div>
              <ElectrodeSlotSidebar
                domain={domain}
                layout={layout}
                allocation={allocation}
                slots={slots}
                selection={selection}
                setSelection={setSelection}
                select={select}
                commit={commit}
                history={history}
                setHistory={setHistory}
                coords={coords}
                candidate={candidate}
                setCandidate={setCandidate}
                move={move}
                busy={busy}
                evaluate={evaluate}
                saveDraft={saveDraft}
                readDraft={readDraft}
              />
            </div>
            <EditorComparisonSection
              result={result}
              activeCount={activeCount}
              ar={ar}
              cached={job?.cached}
              exportResult={exportResult}
              arControl={
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
              }
            />
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
