import {
  combinedTrace,
  sourcePass,
  type SourceCondition,
  type SourceResult,
} from '../../lib/source-reception.ts';
import {
  SOURCE_ROI_DEFINITION,
  UNASSIGNED_SOURCE_COLOR,
  sourceRegion,
} from '../../lib/source-regions.ts';

/** Display projections only. Scores and recorded scientific coordinates remain unchanged. */
export function peakSourceTime(waveforms: SourceResult['waveforms']) {
  const energy = waveforms.time_s.map((_, time) =>
    waveforms.source_nam.reduce((sum, row) => sum + row[time] ** 2, 0),
  );
  return energy.indexOf(Math.max(...energy));
}

export function sourcePresentation(result: SourceResult) {
  const regions =
    result.source.region_definition === SOURCE_ROI_DEFINITION
      ? (result.source.source_regions ?? [])
      : result.source.xyz_mm.map(() => null);
  return {
    regions,
    colors: result.source.xyz_mm.map(
      (_, i) => sourceRegion(regions[i])?.color ?? UNASSIGNED_SOURCE_COLOR,
    ),
  };
}

export function receiverTraces(
  result: SourceResult,
  channels: number[],
  condition: SourceCondition,
) {
  return (['baseline', 'candidate'] as const).map((side, i) =>
    combinedTrace(result.waveforms[side], channels[i], condition).map(
      (value, time) => ({ time: result.waveforms.time_s[time], ...value }),
    ),
  );
}

export function reconstructionTrace(
  result: SourceResult,
  channel: number,
  condition: SourceCondition,
) {
  const baseline = combinedTrace(
    result.waveforms.baseline,
    channel,
    condition,
    true,
  );
  const candidate = combinedTrace(
    result.waveforms.candidate,
    channel,
    condition,
    true,
  );
  return result.waveforms.time_s.map((time, i) => ({
    time,
    truth: result.waveforms.baseline.brain_uv[channel][i],
    baseline: baseline[i].mixed,
    candidate: candidate[i].mixed,
  }));
}

export function sharedAmplitude(traces: ReturnType<typeof receiverTraces>) {
  return (
    Math.max(
      1e-3,
      ...traces
        .flat()
        .flatMap((row) => [
          Math.abs(row.brain),
          Math.abs(row.artifact),
          Math.abs(row.mixed),
        ]),
    ) * 1.08
  );
}

export function strengthCurve(
  result: SourceResult,
  condition: SourceCondition,
  ar: number,
) {
  const scores = result.strength_curve.filter(
    (score) => score.condition === condition,
  );
  return {
    curve: scores.map((score) => ({
      strength: score.artifact_scale,
      baseline: score.baseline.explained_energy * 100,
      candidate: score.candidate.explained_energy * 100,
      retention:
        score.field_retention == null ? null : score.field_retention * 100,
    })),
    passing: scores.filter(
      (score) => sourcePass(score.field_retention, ar) === 'pass',
    ),
  };
}

export function sourceTraceAt(result: SourceResult, sourceIndex: number) {
  return result.waveforms.time_s.map((time, i) => ({
    time,
    source: result.waveforms.source_nam[sourceIndex][i],
  }));
}

export function layoutPresentation(result: SourceResult) {
  const counts = new Set(result.layout.regionIndices).size;
  return {
    counts,
    allocation: Array.from(
      { length: counts },
      (_, region) =>
        result.layout.regionIndices.filter((value) => value === region).length,
    ),
    baselineAllocation: [64],
    baselineLayout: {
      id: result.request.record_id + '-baseline',
      xyzMm: result.layout.referenceXyzMm,
      referenceXyzMm: result.layout.referenceXyzMm,
      regionIndices: Array<number>(64).fill(0),
    },
    candidateLayout: { id: result.request.record_id, ...result.layout },
  };
}
