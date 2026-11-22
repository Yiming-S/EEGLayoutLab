/**
 * Session-robustness results of a coordinate evaluation (protocol standard/1, see
 * src/compact_eeg/workflows/design_robustness.py). Every value is field retention relative to the
 * unperturbed standard64 reference at 20 dB, like `field_relative`.
 */
export type RobustnessStats = { median: number; p10: number; minimum: number; count: number };
type Paired = { candidate: RobustnessStats; reference: RobustnessStats };
type ReplacementSide = { completed: number; rejected: number; fixed_estimator: RobustnessStats | null; redigitized: RobustnessStats | null; displacement_rms_mm: number | null };
export type RobustnessBlock = {
  protocol: 'standard/1';
  snr_db: 20;
  dropout: { single: { candidate: number[]; reference: RobustnessStats }; random: Array<Paired & { removed: number; draws: number }> };
  impedance: Array<Paired & { log_sd: number; draws: number }>;
  replacement: { status: 'unavailable'; reason: string }
    | { status: 'completed'; centre_mm: number[]; jitter_mm: number; table_id: string;
        levels: Array<{ rms_mm: number; trials: number; rotation_deg: number; candidate: ReplacementSide; reference: ReplacementSide }> };
};
/** The library's per-record summary (contracts/scientific-options.mjs robustnessSummary). */
export type RobustnessSummary = {
  protocol: 'standard/1';
  dropout: { removed: number[]; candidate: (number | null)[]; reference: (number | null)[] };
  impedance: { log_sd: number[]; candidate: (number | null)[]; reference: (number | null)[] };
  replacement: null | { rms_mm: number[]; fixed: { candidate: (number | null)[]; reference: (number | null)[] }; redigitized: { candidate: (number | null)[]; reference: (number | null)[] } };
};

export type RobustnessRow = { label: string; candidate: RobustnessStats | null; reference: RobustnessStats | null; note?: string };

/** Table rows in display order: dropout, unequal noise, re-placement (fixed and re-measured positions). */
export function robustnessRows(block: RobustnessBlock): RobustnessRow[] {
  const rows: RobustnessRow[] = block.dropout.random.map(level => ({ label: `随机脱落${level.removed}个电极`, candidate: level.candidate, reference: level.reference }));
  rows.push(...block.impedance.map(level => ({ label: `电极噪声不均（对数标准差${level.log_sd}）`, candidate: level.candidate, reference: level.reference })));
  if (block.replacement.status === 'completed')
    for (const level of block.replacement.levels) {
      const note = level.candidate.rejected || level.reference.rejected ? `${level.trials}次中当前布局${level.candidate.rejected}次、标准64 ${level.reference.rejected}次移出可用头皮，不计入。` : undefined;
      rows.push({ label: `重新佩戴${level.rms_mm} mm · 沿用原位置的重建器`, candidate: level.candidate.fixed_estimator, reference: level.reference.fixed_estimator, note });
      rows.push({ label: `重新佩戴${level.rms_mm} mm · 重新测量电极位置`, candidate: level.candidate.redigitized, reference: level.reference.redigitized });
    }
  return rows;
}

/** Electrodes whose single loss costs the most, worst first. */
export function criticalElectrodes(block: RobustnessBlock, names: string[] | undefined, count = 5) {
  return block.dropout.single.candidate.map((value, index) => ({ index, name: names?.[index] ?? `E${index + 1}`, retention: value }))
    .sort((a, b) => a.retention - b.retention || a.index - b.index).slice(0, count);
}
