import type { ElectrodeDesign, DesignResult } from '../../lib/design-decision';

/** Inspect saved coordinates without projection, rounding, reordering or request mutation. */
export function coordinateReview(design: ElectrodeDesign, result: DesignResult | null = null) {
  const evaluated = result?.evaluated_xyz_mm;
  const complete = evaluated?.length === design.xyz_mm.length && evaluated.every(point => point.length === 3 && point.every(Number.isFinite));
  return {
    schema: 'electrode-coordinate-review/1', coordinate_system: design.coordinate_system, unit: design.unit,
    source: design.source_metadata ?? { name: design.name, declaration: design.coordinate_system },
    evaluated: Boolean(complete),
    rows: design.xyz_mm.map((input, index) => {
      const actual = complete ? evaluated![index] : null;
      const movement_mm = actual ? Math.hypot(...actual.map((value, axis) => value - input[axis])) : null;
      return { index, name: design.electrode_names?.[index] ?? `E${index + 1}`, region: design.region_indices[index], input_xyz_mm: input,
        evaluated_xyz_mm: actual, movement_mm, status: movement_mm === null ? 'not_evaluated' : movement_mm <= 2 + 1e-7 ? 'within_projection_limit' : 'outside_projection_limit' };
    }),
  };
}
