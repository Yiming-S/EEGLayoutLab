import {
  normalizeReceptionRequest,
  validateReceptionResult,
} from '../../contracts/source-reception.mjs';
import { validateCoordinateSource } from '../../contracts/coordinate-source.mjs';

export const DELIVERY_INPUT_LIMIT = 34 * 1024 * 1024;
const WIRE_LIMIT = 32 * 1024 * 1024;
const SNAPSHOT_LIMIT = 16 * 1024 * 1024;
const UUID =
  /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
const SHA = /^[a-f0-9]{64}$/;
const object = (v) => Boolean(v && typeof v === 'object' && !Array.isArray(v));
const fields = (v, names) =>
  object(v) && Object.keys(v).every((key) => names.includes(key));
const text = (v, max, required = false) =>
  typeof v === 'string' && v.length <= max && (!required || v.length > 0);
const date = (v) => typeof v === 'string' && Number.isFinite(Date.parse(v));
const requireValue = (pass, message) => {
  if (!pass) throw new Error(message);
};
const abort = (signal) => {
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
};
const bytes = (v) => new TextEncoder().encode(v);
const hash = async (v) =>
  [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes(v)))]
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
const xyz = (v, n) =>
  Array.isArray(v) &&
  v.length > 0 &&
  v.length <= 64 &&
  (n === undefined || v.length === n) &&
  v.every(
    (row) =>
      Array.isArray(row) &&
      row.length === 3 &&
      row.every(
        (x) =>
          typeof x === 'number' && Number.isFinite(x) && Math.abs(x) <= 500,
      ),
  );
const metrics = (v) =>
  object(v) &&
  ['field_relative', 'sensitivity_tail', 'localization_relative'].every(
    (k) => k in v,
  ) &&
  [
    'field_relative',
    'sensitivity_tail',
    'localization_relative',
    'median_mm',
    'p90_mm',
    'conditional_global',
    'field_absolute',
    'reference_field_absolute',
    'reference_median_mm',
    'reference_p90_mm',
  ].every(
    (k) =>
      !(k in v) ||
      v[k] === null ||
      (typeof v[k] === 'number' && Number.isFinite(v[k])),
  );
const regions = (v, n) =>
  Array.isArray(v) &&
  v.length === n &&
  v.every((x) => Number.isInteger(x) && x >= 0 && x <= 5);

const finiteOrNull = (value) =>
  value === null || (typeof value === 'number' && Number.isFinite(value));
/** An entry's summary as the project service writes it; a layout's also says whether signal simulation accepts it. */
function summaryShape(value) {
  if (
    !fields(value, [
      'protocol',
      'electrode_count',
      'region_count',
      'parent_id',
      'mode',
      'brain_region',
      'brain_regions',
      'source_index',
      'seed',
      'simulation',
    ])
  )
    return false;
  for (const key of ['protocol', 'mode', 'brain_region'])
    if (key in value && !text(value[key], 200, true)) return false;
  for (const key of ['electrode_count', 'region_count', 'source_index', 'seed'])
    if (key in value && (!Number.isSafeInteger(value[key]) || value[key] < 0))
      return false;
  return (
    (!('simulation' in value) || typeof value.simulation === 'boolean') &&
    (!('parent_id' in value) || SHA.test(value.parent_id)) &&
    (!('brain_regions' in value) ||
      (Array.isArray(value.brain_regions) &&
        value.brain_regions.length <= 6 &&
        value.brain_regions.every((region) => text(region, 200, true))))
  );
}

/** Historical service validators assume their own producer. Uploaded files also need every field consumed by the view. */
function sourceViewShape(payload) {
  requireValue(
    object(payload.metrics) &&
      finiteOrNull(payload.metrics.pure_brain_amplitude_ratio) &&
      object(payload.provenance) &&
      object(payload.protocol),
    '交付信号结果格式无效',
  );
  const source = payload.source,
    count = source?.xyz_mm?.length,
    waveforms = payload.waveforms;
  requireValue(
    object(source) &&
      xyz(source.xyz_mm) &&
      Number.isInteger(source.patch_count) &&
      source.patch_count === count &&
      Array.isArray(waveforms.source_nam) &&
      waveforms.source_nam.length === count &&
      waveforms.source_nam.every(
        (row) =>
          Array.isArray(row) &&
          row.length === 400 &&
          row.every(Number.isFinite),
      ),
    '交付信号结果格式无效',
  );
  if (source.normals_mri !== undefined)
    requireValue(xyz(source.normals_mri, count), '交付信号结果格式无效');
  for (const condition of [...payload.conditions, ...payload.strength_curve]) {
    for (const side of ['baseline', 'candidate'])
      if ('brain_noise_ratio_db' in condition[side])
        requireValue(
          finiteOrNull(condition[side].brain_noise_ratio_db),
          '交付信号结果格式无效',
        );
  }
}

async function snapshotShape(snapshot, entry) {
  requireValue(
    fields(snapshot, [
      'schema',
      'kind',
      'record_id',
      'payload',
      'electrode_annotation',
    ]),
    '交付快照格式无效',
  );
  const s = snapshot;
  requireValue(
    s.schema === 'research-project-snapshot/1' &&
      s.kind === entry.kind &&
      s.record_id === entry.record_id &&
      object(s.payload),
    '交付快照与记录不匹配',
  );
  const payload = s.payload;
  if (entry.kind === 'layout') {
    const record = payload.record;
    requireValue(
      object(record) &&
        record.id === entry.record_id &&
        object(record.layout) &&
        xyz(record.layout.xyzMm, 64) &&
        regions(record.layout.regionIndices, 64) &&
        metrics(record.metrics),
      '交付布局坐标或指标无效',
    );
  } else if (entry.kind === 'editor') {
    const result = payload.cache?.result;
    requireValue(
      object(payload.record) &&
        payload.record.key === entry.record_id &&
        object(payload.cache) &&
        payload.cache.key === entry.record_id &&
        object(result) &&
        result.status === 'completed' &&
        result.schema === 'electrode-editor/1' &&
        Number.isInteger(result.electrode_count) &&
        result.electrode_count >= 2 &&
        result.electrode_count <= 64 &&
        xyz(result.evaluated_xyz_mm, result.electrode_count) &&
        metrics(result.edited_metrics),
      '交付编辑结果格式无效',
    );
    requireValue(
      payload.cache.result_sha256 === (await hash(JSON.stringify(result))),
      '交付编辑结果格式无效',
    );
  } else {
    requireValue(
      ['source-reception/1', 'source-reception/2'].includes(
        payload.schema_version,
      ) &&
        object(payload.layout) &&
        xyz(payload.layout.xyzMm, 64) &&
        xyz(payload.layout.referenceXyzMm, 64) &&
        regions(payload.layout.regionIndices, 64),
      '交付信号结果格式无效',
    );
    try {
      validateReceptionResult(
        payload,
        normalizeReceptionRequest(payload.request),
        { layout: payload.layout },
      );
      sourceViewShape(payload);
    } catch {
      throw new Error('交付信号结果格式无效');
    }
  }
  if (s.electrode_annotation !== undefined) {
    const a = s.electrode_annotation;
    requireValue(
      entry.kind === 'layout' &&
        fields(a, [
          'schema',
          'id',
          'record_id',
          'request_sha256',
          'electrode_names',
          'source_metadata',
        ]) &&
        a.schema === 'eeg-electrode-annotation/1' &&
        SHA.test(a.id ?? '') &&
        a.record_id === entry.record_id &&
        SHA.test(a.request_sha256 ?? '') &&
        Array.isArray(a.electrode_names) &&
        a.electrode_names.length === 64 &&
        new Set(a.electrode_names).size === 64 &&
        a.electrode_names.every(
          (v) =>
            text(v, 128, true) &&
            v.trim() &&
            !Array.from(v).some(
              (char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127,
            ),
        ),
      '交付电极名称与记录不匹配',
    );
    if (a.source_metadata !== undefined)
      validateCoordinateSource(a.source_metadata);
    if (object(payload.reproduction?.request))
      requireValue(
        a.request_sha256 ===
          (await hash(JSON.stringify(payload.reproduction.request))),
        '交付电极名称与记录不匹配',
      );
  }
}

function workflowShape(workflow, entries) {
  if (workflow === undefined) return;
  requireValue(
    fields(workflow, [
      'reference_entry_id',
      'candidate_entry_id',
      'comparison_href',
    ]),
    '交付比较条件无效',
  );
  const value = workflow;
  const selected = ['reference_entry_id', 'candidate_entry_id'].map((key) => {
    const id = value[key];
    requireValue(
      id === null || (typeof id === 'string' && UUID.test(id)),
      '交付比较条件无效',
    );
    const entry = entries.find((row) => row.entry.id === id)?.entry;
    requireValue(
      id === null || entry?.kind === 'layout',
      '交付比较条件与记录不匹配',
    );
    return entry;
  });
  requireValue(
    !selected[0] || !selected[1] || selected[0].id !== selected[1].id,
    '交付比较条件无效',
  );
  if (value.comparison_href === null) return;
  requireValue(
    typeof value.comparison_href === 'string' &&
      value.comparison_href.length <= 4096 &&
      selected.every(Boolean),
    '交付比较条件无效',
  );
  const url = new URL(value.comparison_href, 'http://localhost');
  requireValue(
    value.comparison_href.startsWith('/decision?') &&
      url.origin === 'http://localhost' &&
      url.pathname === '/decision' &&
      !url.hash &&
      [...url.searchParams.keys()].every(
        (k) =>
          [
            'a',
            'b',
            'ar',
            'thresholdMode',
            'sensitivity',
            'localization',
            'p90',
          ].includes(k) && url.searchParams.getAll(k).length === 1,
      ),
    '交付比较条件无效',
  );
  requireValue(
    url.searchParams.get('a') === selected[0].record_id &&
      url.searchParams.get('b') === selected[1].record_id,
    '交付比较条件与记录不匹配',
  );
  for (const key of ['ar', 'sensitivity', 'localization', 'p90']) {
    const raw = url.searchParams.get(key);
    if (raw !== null)
      requireValue(
        raw.trim() !== '' &&
          Number.isFinite(Number(raw)) &&
          Number(raw) >= (key === 'ar' ? 1 : 0) &&
          Number(raw) <= (key === 'p90' ? 500 : 100) &&
          (key !== 'ar' || Number.isInteger(Number(raw))),
        '交付比较条件无效',
      );
  }
  requireValue(
    !url.searchParams.has('thresholdMode') ||
      ['joint', 'custom'].includes(url.searchParams.get('thresholdMode')),
    '交付比较条件无效',
  );
  requireValue(
    selected.every((entry) =>
      ['strict_area', 'cache', 'design_evaluation'].includes(
        entry?.summary?.protocol ?? '',
      ),
    ),
    '交付比较条件无效',
  );
  const mode = url.searchParams.get('thresholdMode');
  const joint =
    mode === 'joint' ||
    (mode !== 'custom' &&
      !['sensitivity', 'localization', 'p90'].some((key) =>
        url.searchParams.has(key),
      ));
  if (joint) {
    const field = Number(url.searchParams.get('ar') ?? 90);
    requireValue(
      field >= 10 &&
        field <= 100 &&
        !url.searchParams.has('p90') &&
        ['sensitivity', 'localization'].every(
          (key) =>
            !url.searchParams.has(key) ||
            Number(url.searchParams.get(key)) === field,
        ),
      '交付比较条件无效',
    );
  }
}

/** Read only local delivered bytes. No project credentials, API calls or computation. */
export async function openResearchDelivery(raw, signal) {
  abort(signal);
  requireValue(
    typeof raw === 'string' && bytes(raw).byteLength <= DELIVERY_INPUT_LIMIT,
    '交付包超过大小上限',
  );
  let value;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new Error('交付包不是有效JSON');
  }
  requireValue(
    fields(value, [
      'schema',
      'exported_at',
      'project',
      'host',
      'records',
      'files',
      'manifest_sha256',
      'scientific_results_recomputed',
    ]) &&
      value.schema === 'eeg-research-delivery/1' &&
      date(value.exported_at) &&
      value.scientific_results_recomputed === false &&
      SHA.test(value.manifest_sha256 ?? ''),
    '交付包格式无效',
  );
  requireValue(
    bytes(JSON.stringify(value)).byteLength <= WIRE_LIMIT,
    '交付包超过大小上限',
  );
  const project = value.project;
  requireValue(
    fields(project, [
      'id',
      'title',
      'owner_name',
      'notes',
      'revision',
      'created_at',
      'updated_at',
      'workflow',
    ]) &&
      UUID.test(project.id ?? '') &&
      text(project.title, 200, true) &&
      text(project.owner_name, 120, true) &&
      text(project.notes, 8000) &&
      Number.isSafeInteger(project.revision) &&
      project.revision > 0 &&
      date(project.created_at) &&
      date(project.updated_at),
    '交付项目说明无效',
  );
  const host = value.host;
  requireValue(
    fields(host, [
      'application_version',
      'data_manifest_sha256',
      'data_bundle_id',
      'runtime_lock_sha256',
      'source_files',
    ]),
    '交付版本说明无效',
  );
  for (const name of ['application_version', 'data_bundle_id'])
    if (host[name] !== undefined)
      requireValue(text(host[name], 200, true), '交付版本说明无效');
  for (const name of ['data_manifest_sha256', 'runtime_lock_sha256'])
    if (host[name] !== undefined)
      requireValue(SHA.test(host[name]), '交付版本说明无效');
  if (host.source_files !== undefined)
    requireValue(
      Array.isArray(host.source_files) &&
        host.source_files.length <= 100 &&
        host.source_files.every(
          (r) =>
            fields(r, ['path', 'sha256']) &&
            text(r.path, 512, true) &&
            !r.path.startsWith('/') &&
            !r.path.includes('\\') &&
            r.path.split('/').every((p) => p && p !== '.' && p !== '..') &&
            SHA.test(r.sha256),
        ),
      '交付版本说明无效',
    );
  requireValue(
    Array.isArray(value.records) &&
      value.records.length <= 100 &&
      Array.isArray(value.files) &&
      value.files.length === value.records.length + 1,
    '交付文件清单无效',
  );
  const files = new Map();
  let total = 0;
  for (const file of value.files) {
    abort(signal);
    requireValue(
      fields(file, [
        'path',
        'media_type',
        'encoding',
        'size_bytes',
        'sha256',
        'content',
      ]) &&
        typeof file.path === 'string' &&
        !files.has(file.path) &&
        file.encoding === 'utf-8' &&
        typeof file.content === 'string' &&
        Number.isSafeInteger(file.size_bytes) &&
        file.size_bytes >= 0 &&
        SHA.test(file.sha256 ?? ''),
      '交付文件清单无效',
    );
    const readme = file.path === 'README.md';
    requireValue(
      readme ||
        (/^records\/[a-f0-9-]{36}\.json$/.test(file.path) &&
          UUID.test(file.path.slice(8, -5))),
      '交付文件路径无效',
    );
    requireValue(
      file.media_type === (readme ? 'text/markdown' : 'application/json') &&
        file.size_bytes <= (readme ? 512 * 1024 : SNAPSHOT_LIMIT),
      '交付文件清单无效',
    );
    const size = bytes(file.content).byteLength;
    requireValue(
      size === file.size_bytes && (await hash(file.content)) === file.sha256,
      '交付文件大小或校验值不一致',
    );
    total += size;
    requireValue(total <= WIRE_LIMIT, '交付包超过大小上限');
    files.set(file.path, file);
  }
  requireValue(files.has('README.md'), '交付包缺少说明文件');
  const { manifest_sha256: checksum, files: _files, ...metadata } = value;
  const manifest = {
    ...metadata,
    files: value.files.map(({ content: _content, ...rest }) => rest),
  };
  requireValue(
    (await hash(JSON.stringify(manifest))) === checksum,
    '交付清单校验失败',
  );
  const entries = [],
    ids = new Set();
  for (const record of value.records) {
    abort(signal);
    requireValue(
      fields(record, [
        'id',
        'kind',
        'record_id',
        'title',
        'notes',
        'created_at',
        'summary',
        'path',
        'snapshot_sha256',
        'annotation_id',
      ]) &&
        UUID.test(record.id ?? '') &&
        !ids.has(record.id) &&
        ['layout', 'editor', 'source'].includes(record.kind) &&
        SHA.test(record.record_id ?? '') &&
        record.path === `records/${record.id}.json` &&
        text(record.title, 200, true) &&
        text(record.notes, 8000) &&
        date(record.created_at) &&
        summaryShape(record.summary),
      '交付记录说明无效',
    );
    ids.add(record.id);
    const file = files.get(record.path);
    requireValue(
      file && file.sha256 === record.snapshot_sha256,
      '交付记录缺少科学文件',
    );
    let snapshot;
    try {
      snapshot = JSON.parse(file.content);
    } catch {
      throw new Error('交付快照格式无效');
    }
    const entry = { ...record, snapshot_bytes: file.size_bytes };
    await snapshotShape(snapshot, entry);
    requireValue(
      (record.annotation_id === undefined &&
        snapshot.electrode_annotation === undefined) ||
        record.annotation_id === snapshot.electrode_annotation?.id,
      '交付电极名称与记录不匹配',
    );
    entries.push({ entry, snapshot, snapshot_json: file.content });
  }
  workflowShape(project.workflow, entries);
  abort(signal);
  return {
    project: {
      schema: 'research-project/1',
      ...project,
      entries: entries.map((row) => row.entry),
    },
    entries,
    readme: files.get('README.md').content,
    original_text: raw,
    manifest_sha256: value.manifest_sha256,
    exported_at: value.exported_at,
    total_bytes: total,
  };
}
