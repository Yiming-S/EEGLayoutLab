/** Scientific coordinates use millimetres in the Ernie MRI reference space.
 * Array order is electrode identity; consumers must preserve it with regionIndices.
 */
export type XYZ = [number, number, number];
export type DomainMode = 'whole_surface' | 'low_hair' | 'preset';

/** Existing recorded-layout wire format; rendering settings do not belong here. */
export type RecordedLayout = {
  id: string;
  xyzMm: XYZ[];
  regionIndices: number[];
  referenceXyzMm: XYZ[];
  regionPatchVertexIndices?: number[][];
  regionAreasCm2?: number[];
};
