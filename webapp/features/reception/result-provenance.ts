/** Describe the recorded field origin; never infer a new solve from page order. */
export function recordedForwardOrigin(provenance: Record<string, unknown>) {
  if (provenance.forward_mode === 'exact_bank') return '本结果使用坐标精确匹配的已有前向库。';
  if (provenance.shared_forward_producer && provenance.forward_mode === 'native_fem_cache') return '本结果复用布局评价准备的精确前向场。';
  if (provenance.forward_mode === 'native_fem_cache') return '本结果使用已保存的精确FEM前向场。';
  if (provenance.fem_recomputed === true) return '本结果的前向场由精确FEM计算生成。';
  return '前向场来源见原始记录。';
}
