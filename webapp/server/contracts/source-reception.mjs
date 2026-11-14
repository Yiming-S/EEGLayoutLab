/** Pure wire contracts shared by source services. No runtime, storage, or worker imports. */
export const SOURCE_REGIONS = [
  'frontal',
  'central',
  'parietal',
  'occipital',
  'temporal_left',
  'temporal_right',
];
const TYPES = ['clean', 'ecg', 'eog', 'mixed'];
const SCALES = [0, 0.5, 1, 2, 4];
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
export function normalizeSourceRequest(x) {
  if (
    !x ||
    Array.isArray(x) ||
    typeof x !== 'object' ||
    Object.keys(x).some(
      (k) =>
        ![
          'record_id',
          'brain_region',
          'waveform',
          'artifact_scale',
          'seed',
        ].includes(k),
    )
  )
    throw new Error('源实验配置字段无效');
  if (
    typeof x.record_id !== 'string' || !/^[a-f0-9]{64}$/.test(x.record_id) ||
    !SOURCE_REGIONS.includes(x.brain_region) ||
    !['burst', 'rhythm'].includes(x.waveform) ||
    !SCALES.includes(x.artifact_scale) ||
    !Number.isInteger(x.seed) ||
    x.seed < 0 ||
    x.seed > 9999
  )
    throw new Error('请选择已有完整布局、支持的源区与波形；种子范围0–9999');
  return {
    record_id: x.record_id,
    brain_region: x.brain_region,
    waveform: x.waveform,
    artifact_scale: x.artifact_scale,
    seed: x.seed,
  };
}
export function validateSourceResult(result, request, record) {
  if (
    result?.status !== 'completed' ||
    result.schema_version !== 'source-reception/1' ||
    !equal(normalizeSourceRequest(result.request), request)
  )
    throw new Error('源实验结果身份不一致');
  if (
    !equal(result.layout?.xyzMm, record.layout.xyzMm) ||
    !equal(result.layout?.regionIndices, record.layout.regionIndices) ||
    !equal(result.layout?.referenceXyzMm, record.layout.referenceXyzMm)
  )
    throw new Error('源实验替换了冻结点位');
  const wave = result.waveforms,
    n = wave?.time_s?.length;
  if (
    n !== 400 ||
    !wave.time_s.every(Number.isFinite) ||
    wave.time_s.some((t, i) => i && t <= wave.time_s[i - 1])
  )
    throw new Error('时间轴无效');
  for (const side of ['baseline', 'candidate'])
    for (const key of [
      'brain_uv',
      'ecg_uv',
      'eog_uv',
      'noise_uv',
      'reconstructed_brain_uv',
      'reconstructed_ecg_uv',
      'reconstructed_eog_uv',
      'reconstructed_noise_uv',
    ]) {
      const a = wave[side]?.[key];
      if (
        !Array.isArray(a) ||
        a.length !== 64 ||
        a.some(
          (row) =>
            !Array.isArray(row) ||
            row.length !== n ||
            !row.every(Number.isFinite),
        )
      )
        throw new Error('64通道波形无效');
    }
  if (
    !Array.isArray(result.conditions) ||
    result.conditions.length !== 4 ||
    new Set(result.conditions.map((c) => c.condition)).size !== 4 ||
    !Array.isArray(result.strength_curve) ||
    result.strength_curve.length !== 16
  )
    throw new Error('缺少对照条件');
  const combinations = [
    'clean:0',
    ...['ecg', 'eog', 'mixed'].flatMap((c) => SCALES.map((s) => `${c}:${s}`)),
  ].sort();
  if (
    !equal(
      result.strength_curve
        .map((c) => `${c.condition}:${c.artifact_scale}`)
        .sort(),
      combinations,
    )
  )
    throw new Error('干扰曲线点重复或缺失');
  if (
    result.conditions.some(
      (c) =>
        c.artifact_scale !==
        (c.condition === 'clean' ? 0 : request.artifact_scale),
    )
  )
    throw new Error('条件强度与请求不符');
  for (const c of [...result.conditions, ...result.strength_curve]) {
    if (!TYPES.includes(c.condition) || !SCALES.includes(c.artifact_scale))
      throw new Error('干扰条件无效');
    for (const side of ['baseline', 'candidate']) {
      const m = c[side];
      if (
        !m ||
        !Number.isFinite(m.nmse) ||
        m.nmse < 0 ||
        !Number.isFinite(m.explained_energy) ||
        Math.abs(m.explained_energy - (1 - m.nmse)) > 1e-8 ||
        (m.brain_artifact_ratio_db !== null &&
          !Number.isFinite(m.brain_artifact_ratio_db))
      )
        throw new Error('重建指标无效');
    }
    const expected =
      c.baseline.explained_energy > 1e-8
        ? c.candidate.explained_energy / c.baseline.explained_energy
        : null;
    if (
      expected === null
        ? c.field_retention !== null
        : !Number.isFinite(c.field_retention) ||
          Math.abs(expected - c.field_retention) >
            1e-8 * Math.max(1, Math.abs(expected))
    )
      throw new Error('AR相对保留率无效');
  }
  if (
    !result.source?.xyz_mm?.length ||
    result.source.xyz_mm.some(
      (x) => x.length !== 3 || !x.every(Number.isFinite),
    )
  )
    throw new Error('缺少实际源坐标');
}

const CROSS_REGIONS = ['frontal', 'central', 'parietal', 'occipital', 'temporal_left', 'temporal_right'];
export function normalizeReceptionRequest(x) {
  if (x?.mode === undefined) return normalizeSourceRequest(x);
  if ('region_definition' in x && x.region_definition !== 'dk40-six-roi-v1') throw new Error('Unsupported source ROI definition');
  const single = x.mode === 'single_source';
  const cross = x.mode === 'cross_region';
  const expected = [
    'record_id',
    'mode',
    single ? 'source_index' : cross ? 'brain_regions' : 'brain_region',
    'waveform',
    'artifact_scale',
    'seed',
    ...('region_definition' in x ? ['region_definition'] : []),
  ]
    .sort()
    .join(',');
  if (
    !['single_source', 'multi_source', 'cross_region'].includes(x.mode) ||
    Object.keys(x).sort().join(',') !== expected
  )
    throw new Error('源模式或字段无效');
  const common = normalizeSourceRequest({
    record_id: x.record_id,
    brain_region: single || cross ? 'frontal' : x.brain_region,
    waveform: x.waveform,
    artifact_scale: x.artifact_scale,
    seed: x.seed,
  });
  if (
    single &&
    (!Number.isInteger(x.source_index) ||
      x.source_index < 0 ||
      x.source_index > 255)
  )
    throw new Error('选择0–255中的一个冻结生成源');
  const { brain_region, ...rest } = common;
  if (cross && (!Array.isArray(x.brain_regions) || x.brain_regions.length < 1 || x.brain_regions.length > 6 || new Set(x.brain_regions).size !== x.brain_regions.length || x.brain_regions.some(id => !CROSS_REGIONS.includes(id))))
    throw new Error('跨区域模式需要选择1–6个不同的源区域');
  return {
    ...rest,
    mode: x.mode,
    ...(x.region_definition ? { region_definition: x.region_definition } : {}),
    ...(single ? { source_index: x.source_index } : cross ? { brain_regions: CROSS_REGIONS.filter(id => x.brain_regions.includes(id)) } : { brain_region }),
  };
}
export function validateReceptionResult(result, request, record) {
  if (!request.mode) return validateSourceResult(result, request, record);
  if (
    result?.schema_version !== 'source-reception/2' ||
    JSON.stringify(normalizeReceptionRequest(result.request)) !==
      JSON.stringify(request)
  )
    throw new Error('新源协议结果身份不一致');
  const legacy = normalizeSourceRequest({
    record_id: request.record_id,
    brain_region: request.brain_region ?? 'frontal',
    waveform: request.waveform,
    artifact_scale: request.artifact_scale,
    seed: request.seed,
  });
  validateSourceResult(
    { ...result, schema_version: 'source-reception/1', request: legacy },
    legacy,
    record,
  );
  const n = request.mode === 'single_source' ? 1 : request.mode === 'cross_region' ? request.brain_regions.length : 6;
  if (
    result.source.mode !== request.mode ||
    result.source.xyz_mm.length !== n ||
    result.source.normals_mri?.length !== n ||
    result.waveforms.source_nam?.length !== n ||
    result.source.normals_mri.some(
      (v) =>
        !Array.isArray(v) ||
        v.length !== 3 ||
        !v.every(Number.isFinite) ||
        Math.abs(Math.hypot(...v) - 1) > 1e-5,
    ) ||
    result.waveforms.source_nam.some(
      (row) => row.length !== 400 || !row.every(Number.isFinite),
    )
  )
    throw new Error('固定源方向或波形记录不完整');
  if (
    request.mode === 'single_source' &&
    result.source.generation_source_indices?.[0] !== request.source_index
  )
    throw new Error('返回源与选择源不符');
  if (request.mode === 'cross_region' && (
    JSON.stringify(result.source.source_regions) !== JSON.stringify(request.brain_regions) ||
    result.source.patch_count !== n ||
    result.source.generation_source_indices?.length !== n ||
    new Set(result.source.generation_source_indices).size !== n ||
    result.source.generation_source_indices.some(i => !Number.isInteger(i) || i < 0 || i > 255) ||
    result.source.bank_source_indices?.length !== n ||
    result.source.bank_source_indices.some((i, index) => i !== 4096 + result.source.generation_source_indices[index])
  )) throw new Error('跨区域源位置记录与选择不一致');
  if (request.region_definition && (
    result.source.region_definition !== request.region_definition ||
    result.protocol.region_definition !== request.region_definition ||
    !/^[a-f0-9]{64}$/.test(result.source.atlas_sha256 ?? '') ||
    result.source.source_regions?.length !== n ||
    result.source.source_parcels?.length !== n ||
    (request.mode === 'multi_source' && result.source.source_regions.some(r => r !== request.brain_region))
  )) throw new Error('Atlas source membership is inconsistent');
}
