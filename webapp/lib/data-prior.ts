import { DATA_PRIOR_REGION_LABELS, dataPriorFromFile, normalizeDataPrior } from '../contracts/scientific-options.mjs';
import type { DataPrior } from './local-compute';

/** What the interface shows about an eeg-data-prior/1 file besides its request value. */
export type DataPriorDetails = {
  id: string;
  summaries: number;
  excluded: number;
  channels: number;
  band_hz: [number, number];
  relative_residual: number;
  uniform_relative_residual: number;
  data_snr_db: number | null;
  fitted_region_gain: number[];
  shrinkage: number;
  held_out: { summaries: number; better: number; prior_median: number; uniform_median: number } | null;
};

export const DATA_PRIOR_FILE_BYTES = 20 * 1024 * 1024;
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

/** Request value and displayed fit of a prior file; throws on anything the page would show wrongly. */
export function readDataPriorFile(text: string): { value: DataPrior; details: DataPriorDetails } {
  if (text.length > DATA_PRIOR_FILE_BYTES) throw new Error('数据先验文件超过20 MB');
  let document: Record<string, unknown>;
  try { document = JSON.parse(text); } catch { throw new Error('数据先验文件不是有效的JSON'); }
  const value = dataPriorFromFile(document) as DataPrior;
  const fit = document.fit as Record<string, unknown>, band = document.band_hz as unknown[];
  const held = fit.held_out as Record<string, unknown> | null;
  const inputs = document.inputs, channels = document.channels as unknown[], excluded = document.summaries_excluded;
  const fitted = fit.fitted_region_gain;
  if (typeof document.id !== 'string' || !Array.isArray(inputs) || !inputs.length || !Array.isArray(band) || band.length !== 2 || !band.every(finite) ||
      !finite(fit.relative_residual) || !finite(fit.uniform_relative_residual) || !finite(fit.shrinkage) ||
      !(fit.data_snr_db === null || finite(fit.data_snr_db)) || !Array.isArray(fitted) || fitted.length !== DATA_PRIOR_REGION_LABELS.length ||
      !fitted.every(finite) || (held !== null && (typeof held !== 'object' || !finite(held.summaries) || !finite(held.prior_better_count) ||
        !finite(held.prior_relative_residual_median) || !finite(held.uniform_relative_residual_median))))
    throw new Error('数据先验文件缺少拟合记录');
  return {
    value,
    details: {
      id: document.id, summaries: inputs.length, excluded: Array.isArray(excluded) ? excluded.length : 0, channels: channels.length,
      band_hz: [band[0] as number, band[1] as number], relative_residual: fit.relative_residual, uniform_relative_residual: fit.uniform_relative_residual,
      data_snr_db: fit.data_snr_db as number | null, fitted_region_gain: fitted as number[], shrinkage: fit.shrinkage,
      held_out: held && { summaries: held.summaries as number, better: held.prior_better_count as number,
        prior_median: held.prior_relative_residual_median as number, uniform_median: held.uniform_relative_residual_median as number },
    },
  };
}

/** Region rows for display. */
export function dataPriorRows(value: DataPrior) {
  return value.region_gain.map((gain, index) => ({ label: DATA_PRIOR_REGION_LABELS[index] as string, gain }));
}

/** Compact URL form of a prior request: seven gains, rho, length (0 when the noise is independent). */
export function dataPriorParam(value: DataPrior) {
  return [...value.region_gain, value.rho, value.length_mm ?? 0].join(',');
}

export function parseDataPriorParam(text: string): DataPrior {
  const numbers = text.split(',').map(Number);
  if (numbers.length !== DATA_PRIOR_REGION_LABELS.length + 2 || text.length > 200) throw new Error('数据先验参数无效');
  const length = numbers.at(-1)!;
  return normalizeDataPrior({ region_gain: numbers.slice(0, -2), rho: numbers.at(-2), length_mm: length === 0 ? null : length }) as DataPrior;
}
