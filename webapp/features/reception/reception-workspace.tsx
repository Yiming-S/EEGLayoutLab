'use client';

import { RuntimeMessage } from '@/components/runtime-message';
import { localizedRecordTitle } from '@/lib/i18n/records';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */

import { Button } from '@/components/ui/button';
import { SiteHeader } from '@/components/site-header';

import { BRAIN_REGIONS, sourceKey } from '@/lib/source-reception';

import { useReceptionController, running } from './use-reception-controller';
import { ExperimentResult } from './experiment-result';

export default function ReceptionPage() {
  const {
    tx,
    locale,
    library,
    id,
    setId,
    ready,
    region,
    setRegion,
    waveform,
    setWaveform,
    scale,
    setScale,
    seed,
    setSeed,
    ar,
    setAR,
    mode,
    setMode,
    singleIndex,
    setSingleIndex,
    catalog,
    catalogError,
    token,
    fatal,
    setRetry,
    active,
    submitting,
    lookup,
    error,
    records,
    selected,
    key,
    job,
    result,
    returnHref,
    here,
    busy,
    submit,
    cancel,
  } = useReceptionController();
  return (
    <main className="lab-page">
      <SiteHeader
        current="reception"
        arPercent={ar}
        labHref={returnHref}
        returnHref={here}
        selection={{ id: selected?.id ?? null, phase: 'saved' }}
      />
      <div className="lab-container">
        <header className="py-5">
          <a className="text-sm text-primary underline" href={returnHref}>
            {tx('← 返回来源页面')}
          </a>
          <h1 className="mt-3 text-2xl font-semibold">{tx('信号仿真')}</h1>
          <p className="mt-2 text-base text-muted-foreground">
            {tx(
              '选择已计算布局，再设置脑源位置、波形和干扰。对比标准全头64导与所选64电极布局的接收和重建；本页不重新优化电极位置。',
            )}
          </p>
        </header>
        <div className="mb-5 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-950">
          {tx(
            '单头模仿真：脑信号通过已有FEM传递矩阵投影；心电、眼电采用假设性空间场。源区由坐标定义，用于表示皮层位置。本页AR用于当前场景的信号重建判定；布局评估采用三项联合判定。',
          )}
        </div>
        {tx(
          !id && (
            <div className="lab-panel mb-4 text-base leading-7">
              {tx('尚未选择布局。可从下方列表选择，或先去')}
              <a
                className="mx-1 text-primary underline"
                href={'/design?ar=' + ar}
              >
                {tx('布局设计')}
              </a>
              {tx('生成64个电极坐标。选择和浏览不会自动开始新仿真。')}
            </div>
          ),
        )}
        {tx(
          fatal && (
            <p role="alert" className="lab-panel mb-4 text-red-800">
              <RuntimeMessage message={fatal} />
              {tx(' ')}
              <Button variant="outline" onClick={() => setRetry((n) => n + 1)}>
                {tx('刷新服务')}
              </Button>
            </p>
          ),
        )}
        <section className="lab-panel mb-4" aria-label={tx('源模式')}>
          <h2 className="font-semibold">{tx('实验源模式')}</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              variant={mode === 'multi_source' ? 'default' : 'outline'}
              aria-pressed={mode === 'multi_source'}
              onClick={() => setMode('multi_source')}
            >
              {tx('区域多源场景（原有模式）')}
            </Button>
            <Button
              variant={mode === 'single_source' ? 'default' : 'outline'}
              aria-pressed={mode === 'single_source'}
              onClick={() => setMode('single_source')}
            >
              {tx('固定法向单源探索')}
            </Button>
          </div>
          <p className="mt-3 text-sm leading-6">
            {tx(
              mode === 'single_source'
                ? '从256个已冻结、不同于反演字典网格的生成源中选择一个位置。方向使用原皮层法向，重建器仍使用全脑源先验。每个源单独保存结果，不改变布局的全脑指标。'
                : '保留原来的区域内6源场景、节律/间歇波形和四组干扰对照。已有前向库布局继续读取原版本缓存。',
            )}
          </p>
          {tx(
            mode === 'single_source' && (
              <label className="lab-label mt-3 block">
                {tx('冻结生成源')}
                <select
                  className="lab-select"
                  value={singleIndex}
                  onChange={(e) => setSingleIndex(Number(e.target.value))}
                  disabled={!catalog}
                >
                  {tx(
                    !catalog ? (
                      <option value={singleIndex}>{tx('读取源目录…')}</option>
                    ) : (
                      catalog.sources.map((s) => (
                        <option key={s.id} value={s.id}>
                          {tx('源')}
                          {tx(s.id)} · (
                          {tx(s.xyz_mm.map((v) => v.toFixed(1)).join(', '))}) mm
                        </option>
                      ))
                    ),
                  )}
                </select>
                {tx(
                  catalog && (
                    <span className="mt-2 block text-xs font-normal">
                      {tx('皮层法向：')}
                      {tx(
                        catalog.sources[singleIndex].normal
                          .map((v) => v.toFixed(4))
                          .join(', '),
                      )}{' '}
                      {tx(' · 坐标系：Ernie MRI RAS / mm')}
                    </span>
                  ),
                )}
                {tx(
                  catalogError && (
                    <span role="alert" className="mt-2 block text-red-800">
                      <RuntimeMessage message={catalogError} />
                    </span>
                  ),
                )}
              </label>
            ),
          )}
        </section>
        <section
          className="lab-panel grid items-end gap-4 md:grid-cols-3 xl:grid-cols-6"
          aria-label={tx('源实验设置')}
        >
          <label className="lab-label md:col-span-3 xl:col-span-2">
            {tx('1 · 选择已计算布局（64电极）')}
            <select
              className="lab-select"
              value={id}
              onChange={(e) => setId(e.target.value)}
            >
              <option value="">{tx('选择已计算布局')}</option>
              {tx(
                id && !selected && (
                  <option value={id}>{tx('指定记录正在读取或不可用')}</option>
                ),
              )}
              {tx(
                records.map((r) => (
                  <option key={r.id} value={r.id}>
                    {tx(
                      r.dataset_id === 'cache' && !r.compatible
                        ? '历史布局 · '
                        : '',
                    )}
                    {localizedRecordTitle(r, locale)}
                  </option>
                )),
              )}
            </select>
          </label>
          <label className="lab-label" hidden={mode === 'single_source'}>
            {tx('2 · 模拟脑源位置')}
            <select
              className="lab-select"
              value={region}
              onChange={(e) => setRegion(e.target.value)}
            >
              {tx(
                BRAIN_REGIONS.map(([k, label]) => (
                  <option key={k} value={k}>
                    {tx(label)}
                  </option>
                )),
              )}
            </select>
          </label>
          <label className="lab-label">
            {tx('脑源波形')}
            <select
              className="lab-select"
              value={waveform}
              onChange={(e) =>
                setWaveform(e.target.value as 'burst' | 'rhythm')
              }
            >
              <option value="burst">{tx('间歇振荡')}</option>
              <option value="rhythm">{tx('持续振荡')}</option>
            </select>
          </label>
          <label className="lab-label">
            {tx('模拟干扰幅度倍数')}
            <select
              className="lab-select"
              value={scale}
              onChange={(e) => setScale(Number(e.target.value))}
            >
              {tx(
                [0, 0.5, 1, 2, 4].map((a) => (
                  <option key={a} value={a}>
                    {tx(a)}×
                  </option>
                )),
              )}
            </select>
          </label>
          <label className="lab-label">
            {tx('随机种子（控制重复生成）')}
            <input
              className="lab-select"
              type="number"
              min={0}
              max={9999}
              step={1}
              value={seed}
              onChange={(e) => {
                const n = Number(e.target.value);
                if (Number.isInteger(n) && n >= 0 && n <= 9999) setSeed(n);
              }}
            />
          </label>
          <p className="md:col-span-3 xl:col-span-6 text-sm text-muted-foreground">
            {tx(
              selected?.dataset_id === 'design_evaluation' &&
                '已评价坐标使用独立前向缓存；首次接收仿真会在本机计算精确FEM，随后复用。',
            )}
            {tx(
              '1×标定：心电为标准64全脑先验信号标准差的1倍，眼电为3倍；随后共用同一空间场采样两套布局。2×表示干扰幅度翻倍、功率变为4倍。幅度倍数与接收SNR分别表示。',
            )}
          </p>
          {tx(
            selected?.dataset_id === 'cache' && !selected.compatible && (
              <p className="md:col-span-3 xl:col-span-6 rounded-lg bg-amber-50 p-3 text-sm text-amber-950">
                {tx(
                  '历史布局：沿用该记录的原始64点坐标进行源场景对照。其计算版本与当前布局搜索不同，本页不重新检验当前表面准入或区域分离条件；结果归属于原坐标协议。',
                )}
              </p>
            ),
          )}
          <div className="md:col-span-3 xl:col-span-6 flex flex-wrap items-center justify-between gap-3 border-t pt-4">
            <div className="text-sm text-muted-foreground">
              {tx(
                lookup.key === key
                  ? lookup.message
                  : selected
                    ? '查询相同源场景的缓存…'
                    : '请先选择一个已计算的完整布局。',
              )}
              {tx(
                busy && (
                  <output className="mt-1 block text-primary">
                    {tx(
                      sourceKey(active!.request) !== key
                        ? '另一源场景正在计算。'
                        : '',
                    )}
                    <RuntimeMessage
                      message={active!.message}
                      status={active!.status}
                    />{' '}
                    · {tx(Math.round(active!.progress * 100))}%
                  </output>
                ),
              )}
              {tx(
                job && !running(job) && job.status !== 'completed' && (
                  <p className="mt-1 text-red-800">
                    <RuntimeMessage message={job.message} status={job.status} />
                  </p>
                ),
              )}
            </div>
            <div className="flex gap-2">
              {tx(
                busy && (
                  <Button variant="outline" onClick={cancel}>
                    {tx('停止计算')}
                  </Button>
                ),
              )}
              <Button
                onClick={submit}
                disabled={!selected || !ready || !token || busy || submitting}
              >
                {tx(
                  submitting
                    ? '正在提交…'
                    : result
                      ? '读取已保存结果'
                      : '3 · 开始信号仿真',
                )}
              </Button>
            </div>
          </div>
          {tx(
            error.key === key && error.message && (
              <p
                role="alert"
                className="text-sm text-red-800 md:col-span-3 xl:col-span-6"
              >
                <RuntimeMessage message={error.message} />
              </p>
            ),
          )}
        </section>
        {tx(
          library && id && !selected && (
            <p role="alert" className="lab-panel mt-4">
              {tx('指定记录没有可用的完整布局。请选择其他已计算布局。')}
            </p>
          ),
        )}
        {tx(
          result && selected ? (
            <ExperimentResult
              key={key}
              result={result}
              label={localizedRecordTitle(selected, locale)}
              ar={ar}
              setAR={setAR}
              cached={Boolean(job?.cached)}
            />
          ) : (
            <section className="lab-panel my-5 py-10 text-center">
              <h2 className="text-lg font-semibold">
                {tx(
                  busy && sourceKey(active!.request) === key
                    ? '正在计算当前场景'
                    : '等待当前源场景的结果',
                )}
              </h2>
              <p className="mt-3 text-base text-muted-foreground">
                {tx(
                  '完成后显示：源位置、两套接收波形、干净脑信号重建，以及0–4×干扰强度曲线。',
                )}
              </p>
              <p className="mt-2 text-sm text-muted-foreground">
                {tx(
                  '20秒模拟 · 200 Hz计算 · 8秒50 Hz预览 · 不下载新头模 · 结果独立缓存',
                )}
              </p>
            </section>
          ),
        )}
      </div>
    </main>
  );
}
