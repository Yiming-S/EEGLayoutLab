/** Membership is supplied by DK40 atlas labels. Anchors control the camera only. */
export const SOURCE_ROI_DEFINITION = 'dk40-six-roi-v1' as const;
export const UNASSIGNED_SOURCE_COLOR = '#92999f';
export const SOURCE_REGIONS = [
  { id: 'frontal', label: '额叶研究区', color: '#d55e00', anchor: [0, 75, 40] },
  { id: 'central', label: '中央感觉运动区', color: '#0072b2', anchor: [0, 0, 70] },
  { id: 'parietal', label: '顶叶研究区', color: '#009e73', anchor: [0, -32, 64] },
  { id: 'occipital', label: '枕叶研究区', color: '#cc79a7', anchor: [0, -65, 20] },
  { id: 'temporal_left', label: '左颞叶研究区', color: '#b28500', anchor: [-52, 12, 9] },
  { id: 'temporal_right', label: '右颞叶研究区', color: '#56b4e9', anchor: [52, 12, 9] },
] as const;
export type SourceRegionId = typeof SOURCE_REGIONS[number]['id'];
export function canonicalSourceRegions(ids: readonly string[]): SourceRegionId[] {
  return SOURCE_REGIONS.filter(r => ids.includes(r.id)).map(r => r.id);
}
export function sourceRegion(id: string | null | undefined) {
  return SOURCE_REGIONS.find(region => region.id === id);
}
