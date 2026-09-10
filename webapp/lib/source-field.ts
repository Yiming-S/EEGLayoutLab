import {
  combinedTrace,
  type SourceCondition,
  type SourceResult,
} from './source-reception';
export type FieldLayer =
  | 'brain'
  | 'artifact'
  | 'mixed'
  | 'reconstruction'
  | 'residual';
export const FIELD_LAYERS: [FieldLayer, string][] = [
  ['brain', '脑源电位'],
  ['artifact', '心眼伪迹电位'],
  ['mixed', '混合接收电位'],
  ['reconstruction', '重建电位（标准64目标）'],
  ['residual', '重建残差（重建−真值）'],
];
export function fieldFrames(
  result: SourceResult,
  condition: SourceCondition,
  layer: FieldLayer,
) {
  const target = layer === 'reconstruction' || layer === 'residual';
  const sides = (['baseline', 'candidate'] as const).map((side) =>
    Array.from({ length: 64 }, (_, ch) =>
      combinedTrace(result.waveforms[side], ch, condition, target).map(
        (v, t) =>
          layer === 'residual'
            ? v.mixed - result.waveforms.baseline.brain_uv[ch][t]
            : layer === 'reconstruction'
              ? v.mixed
              : v[layer],
      ),
    ),
  );
  let limit = 0;
  for (const side of sides)
    for (const row of side)
      for (const value of row) limit = Math.max(limit, Math.abs(value));
  return { sides, limit: Math.max(limit, 1e-9), target };
}
