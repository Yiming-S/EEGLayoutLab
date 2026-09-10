import type { ComputeRequest } from './local-compute';

export type PlacementChoice = { id: string; label: string; mode: ComputeRequest['mode']; maskCodes?: string[] };
export type PlacementProtocol = { anatomical_preset_matrix: Record<string, Array<{ masks?: string[]; mirror_variants?: string[][] }>> };

export function placementChoices(protocol: PlacementProtocol | null, count: number, names: Record<string, string>): PlacementChoice[] {
  const base: PlacementChoice[] = [
    { id: 'whole_surface', label: '全头候选区', mode: 'whole_surface' },
    { id: 'low_hair', label: '少毛发候选区（模型近似）', mode: 'low_hair' },
  ];
  const combinations = protocol?.anatomical_preset_matrix[String(count)]?.flatMap((p) => p.mirror_variants ?? (p.masks ? [p.masks] : [])) ?? [];
  const unique = new Map<string, PlacementChoice>();
  for (const masks of combinations) {
    if (masks.length !== count || masks.some((m) => !(m in names))) continue;
    const id = masks.join(',');
    unique.set(id, { id, label: masks.map((m) => names[m]).join(' + '), mode: 'preset', maskCodes: [...masks] });
  }
  return [...base, ...unique.values()];
}

// Preserve region order and repeated masks: both affect allocation and cache identity.
export function choiceFromSlots(slots: string[], count: number, names: Record<string, string>): PlacementChoice | null {
  if (![1, 2, 3, 4, 6].includes(count) || slots.length !== count || slots.some((s) => !s || !(s in names))) return null;
  return { id: slots.join(','), label: slots.map((s) => names[s]).join(' + '), mode: 'preset', maskCodes: [...slots] };
}

export function placementDesignLink(choice: PlacementChoice, count: number, ar: number) {
  const q = new URLSearchParams({ ar: String(ar), draft: '1', r: String(count), radius: '35', mode: choice.mode });
  if (choice.maskCodes) q.set('masks', choice.maskCodes.join(','));
  return '/design?' + q.toString();
}
