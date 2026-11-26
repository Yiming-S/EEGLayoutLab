'use client';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { Download } from 'lucide-react';
import { RuntimeMessage } from '@/components/runtime-message';
import { SiteHeader } from '@/components/site-header';
import { Button } from '@/components/ui/button';
import { decisionMarkdown } from '@/lib/design-decision';
import { ComparisonConclusion } from './comparison-conclusion';
import { ComparisonRecordsPanel } from './comparison-records-panel';
import { DecisionRequirements } from './decision-requirements';
import { downloadTextFile } from './decision-download';
import { LayoutPairComparisonPanel } from './layout-pair-comparison-panel';
import { PositionEvaluationSection } from './position-evaluation-section';
import { RecordPicker } from './record-picker';
import { useDecisionController } from './use-decision-controller';

export default function DecisionPage({
  mode = 'compare',
}: {
  mode?: 'compare' | 'coordinates';
}) {
  const {
    tx,
    locale,
    ids,
    setIds,
    error,
    thresholds,
    setThresholds,
    setImported,
    importError,
    draftNotice,
    setImportError,
    job,
    computeError,
    testTarget,
    setTestTarget,
    radius,
    setRadius,
    seed,
    setSeed,
    noiseModelId,
    setNoiseModelId,
    scenarioId,
    setScenarioId,
    robustness,
    setRobustness,
    dataPrior,
    dataPriorSource,
    setDataPrior,
    action,
    showEvaluated,
    setShowEvaluated,
    here,
    shown,
    loaded,
    choices,
    notes,
    design,
    requestIdentity,
    jobIdentity,
    result,
    resultQualification,
    computing,
    connection,
    reconnect,
    runEvaluation,
    cancel,
    preview,
  } = useDecisionController(mode);

  const recordA = shown.find((r) => ids.indexOf(r.id) === 0),
    recordB = shown.find((r) => ids.indexOf(r.id) === 1);
  const selectedTargetRecord = shown.find(
    (r) => r.id === ids[testTarget === 'b' ? 1 : 0],
  );
  // Every coordinate evaluation is a library record (labelled with its conditions);
  // signal simulation takes only the default protocol.
  const savedEvaluation = !!result && action === 'evaluate';
  const simulationReady =
    savedEvaluation && noiseModelId === 'iid' && !scenarioId && !dataPrior;

  return (
    <main className="lab-page">
      <SiteHeader
        current={mode === 'coordinates' ? 'coordinates' : 'decision'}
        selection={{
          id:
            mode === 'coordinates'
              ? savedEvaluation
                ? (job?.key ?? null)
                : testTarget !== 'import'
                  ? (shown.find((r) => r.id === ids[testTarget === 'b' ? 1 : 0])?.id ?? null)
                  : null
              : (shown.find((r) => r.id === ids[0])?.id ?? null),
          phase:
            mode === 'coordinates' && testTarget === 'import' && !savedEvaluation
              ? 'draft'
              : 'saved',
          channels: mode === 'coordinates' && design ? 64 : undefined,
        }}
        arPercent={thresholds.field}
        returnHref={
          result && job?.annotation_id
            ? here + '&annotation_record=' + job.key + '&annotation_id=' + job.annotation_id
            : here
        }
      />
      <div className="lab-container space-y-5 pb-10">
        <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border pt-7 pb-5">
          <div>
            <h1 className="text-2xl font-semibold tracking-[-0.028em] sm:text-[1.65rem]">
              {tx(mode === 'coordinates' ? '坐标导入与评价' : '方案对比与设计报告')}
            </h1>
            <p className="mt-1.5 text-sm text-muted-foreground">
              {tx(
                mode === 'coordinates'
                  ? '导入已有64点坐标，评价后保存为独立布局；不运行区域布局搜索。'
                  : '选择两个已保存布局（支持8–64导及跨区自适应配额），并排核对约束、空间分布与三项保留率；64导均衡方案还可检查网格位置偏移。',
              )}
            </p>
          </div>
          {mode === 'compare' && (
            <Button
              size="sm"
              disabled={!loaded || !shown.length}
              variant="outline"
              onClick={() =>
                downloadTextFile(
                  'EEG-design-comparison.md',
                  decisionMarkdown(shown, thresholds, result, locale),
                  'text/markdown;charset=utf-8',
                )
              }
            >
              <Download className="size-3.5" />
              {tx('导出对比报告')}
            </Button>
          )}
        </header>
        {tx(
          error && (
            <p
              role="alert"
              className="lab-panel border-danger/35 bg-danger-surface/65 text-danger"
            >
              <RuntimeMessage message={error} />
            </p>
          ),
        )}
        {mode === 'compare' && (
          <>
            <section
              id="compare-pick"
              className="lab-panel grid scroll-mt-32 gap-4 lg:grid-cols-2"
              aria-label={tx('选择对比方案')}
            >
              {['方案A', '方案B'].map((label, i) => (
                <RecordPicker
                  key={label}
                  label={tx(label)}
                  records={choices}
                  value={ids[i]}
                  exclude={ids[1 - i]}
                  onChange={(id) => setIds((old) => old.map((v, k) => (k === i ? id : v)))}
                />
              ))}
            </section>
            <DecisionRequirements thresholds={thresholds} onChange={setThresholds} />
            {loaded && (
              <ComparisonConclusion a={recordA} b={recordB} thresholds={thresholds} />
            )}
            {loaded && shown.length > 0 && (
              <LayoutPairComparisonPanel
                shown={shown}
                ids={ids}
                locale={locale}
                testTarget={testTarget}
                onSelectTarget={(slot) => setTestTarget(slot)}
              />
            )}
            {loaded && shown.length > 0 && (
              <ComparisonRecordsPanel
                shown={shown}
                ids={ids}
                thresholds={thresholds}
                notes={notes}
                result={result}
                recordA={recordA}
                recordB={recordB}
              />
            )}
          </>
        )}
        <PositionEvaluationSection
          mode={mode}
          ids={ids}
          shown={shown}
          thresholds={thresholds}
          testTarget={testTarget}
          setTestTarget={setTestTarget}
          selectedTargetRecord={selectedTargetRecord}
          draftNotice={draftNotice}
          importError={importError}
          setImported={setImported}
          setImportError={setImportError}
          design={design}
          radius={radius}
          setRadius={setRadius}
          seed={seed}
          setSeed={setSeed}
          noiseModelId={noiseModelId}
          setNoiseModelId={setNoiseModelId}
          scenarioId={scenarioId}
          setScenarioId={setScenarioId}
          robustness={robustness}
          setRobustness={setRobustness}
          dataPrior={dataPrior}
          dataPriorSource={dataPriorSource}
          setDataPrior={setDataPrior}
          action={action}
          showEvaluated={showEvaluated}
          setShowEvaluated={setShowEvaluated}
          here={here}
          job={job}
          computeError={computeError}
          requestIdentity={requestIdentity}
          jobIdentity={jobIdentity}
          result={result}
          resultQualification={resultQualification}
          computing={computing}
          connection={connection}
          reconnect={reconnect}
          runEvaluation={runEvaluation}
          cancel={cancel}
          preview={preview}
          savedEvaluation={savedEvaluation}
          simulationReady={simulationReady}
        />
        {/* Import comes first; the requirements only re-judge the result above. */}
        {mode === 'coordinates' && (
          <DecisionRequirements thresholds={thresholds} onChange={setThresholds} />
        )}
        <section className="lab-panel">
          <h2 className="text-lg font-semibold">{tx('验证阶段')}</h2>
          <p className="mt-2 text-sm leading-7 text-ink-soft">
            {tx(
              '已完成：单头模布局实验、独立源复评与多种噪声控制。进行中：数值和搜索稳定性核查。待独立数据：新头模上的冻结布局迁移、实测噪声校准和同步采集对照。',
            )}
          </p>
          <a
            className="mt-3 lab-link-pill"
            href={'/method?ar=' + thresholds.field + '&returnTo=' + encodeURIComponent(here)}
          >
            {tx('查看指标定义与建模方法')}
          </a>
        </section>
      </div>
    </main>
  );
}
