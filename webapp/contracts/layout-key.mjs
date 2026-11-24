/**
 * A layout's key (design 0004, section 2): the SHA-256 of this text, the Ernie-native millimetre coordinates and
 * region indices of `eeg-electrode-design/1`, in this member order. A coordinate evaluation is keyed by its
 * request's design, a search by its result's layout, so the evaluations of one design under every condition and
 * on every head share one key. The key is derived for listing: it is never stored in a record and enters no
 * scientific identity. Python mirror: src/eeglayoutlab/schemas/layout_key.py.
 */
export function layoutKeyText(xyzMm, regionIndices) {
  return JSON.stringify({ xyz_mm: xyzMm, region_indices: regionIndices });
}
