import { createHash } from 'node:crypto';

export const DELIVERY_SCHEMA = 'eeg-research-delivery/1';
export const MAX_DELIVERY_BYTES = 32 * 1024 * 1024;
const hash = value => createHash('sha256').update(value).digest('hex');
const fail = (message, status = 409) => Object.assign(new Error(message), { status, projectSafe: true });
const object = value => value && typeof value === 'object' && !Array.isArray(value);
const clone = value => JSON.parse(JSON.stringify(value));
const cleanText = value => String(value ?? '').replace(/[\r\n|]/g, ' ').replace(/`/g, "'");
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
const SHA = /^[a-f0-9]{64}$/;
const kinds = ['layout', 'editor', 'source'];
const timestamp = value => typeof value === 'string' && Number.isFinite(Date.parse(value));
const fields = (value, allowed) => object(value) && Object.keys(value).every(key => allowed.includes(key));
function validateProject(project) {
  return fields(project, ['id', 'title', 'owner_name', 'notes', 'revision', 'created_at', 'updated_at', 'workflow']) && UUID.test(project.id) &&
    typeof project.title === 'string' && project.title.length > 0 && project.title.length <= 200 && typeof project.owner_name === 'string' &&
    project.owner_name.length > 0 && project.owner_name.length <= 120 && typeof project.notes === 'string' && project.notes.length <= 8000 &&
    Number.isSafeInteger(project.revision) && project.revision > 0 && timestamp(project.created_at) && timestamp(project.updated_at) &&
    (project.workflow === undefined || object(project.workflow));
}
function validateHost(host) {
  if (!fields(host, ['application_version', 'data_manifest_sha256', 'data_bundle_id', 'runtime_lock_sha256', 'source_files'])) return false;
  for (const name of ['data_manifest_sha256', 'runtime_lock_sha256']) if (host[name] !== undefined && !SHA.test(host[name])) return false;
  for (const name of ['application_version', 'data_bundle_id']) if (host[name] !== undefined && (typeof host[name] !== 'string' || !host[name] || host[name].length > 200)) return false;
  if (host.source_files !== undefined && (!Array.isArray(host.source_files) || host.source_files.some(row => !fields(row, ['path', 'sha256']) ||
    typeof row.path !== 'string' || row.path.startsWith('/') || row.path.split('/').some(part => !part || part === '.' || part === '..') || !SHA.test(row.sha256)))) return false;
  return true;
}
const manifest = bundle => {
  const { manifest_sha256: _checksum, files, ...metadata } = bundle;
  return { ...metadata, files: files.map(({ content: _content, ...file }) => file) };
};

function publicProject(project) {
  if (!object(project) || project.schema !== 'research-project/1' || !Array.isArray(project.entries)) throw fail('Invalid project for research delivery.');
  // Exclude project credentials and operational configuration; keep calculation provenance in snapshots.
  const { id, title, owner_name, notes, revision, created_at, updated_at, workflow } = project;
  return clone({ id, title, owner_name, notes, revision, created_at, updated_at, ...(workflow ? { workflow } : {}) });
}

const reading = value => value === undefined ? 'unrecorded / 未记录' : value === null ? 'null / 原记录不可计算' : cleanText(value);
function savedReadings(rows) {
  const lines = [];
  for (const { record, payload } of rows) {
    const metrics = record.kind === 'layout' ? payload.record?.metrics : record.kind === 'editor' ? payload.cache?.result?.edited_metrics : null;
    if (metrics) lines.push(`| ${cleanText(record.title)} | ${cleanText(record.summary.protocol)} | ${reading(metrics.field_relative)} | ${reading(metrics.sensitivity_tail)} | ${reading(metrics.localization_relative)} | ${reading(metrics.p90_mm)} |`);
  }
  if (!lines.length) return [];
  return ['', '## Saved layout readings / 保存的布局读数', '',
    '| Record / 记录 | Protocol / 协议 | Field ratio / 场保留比值 | Amplitude ratio / 幅度保留比值 | Localization ratio / 定位效用比值 | P90 (mm) |',
    '| --- | --- | --- | --- | --- | --- |', ...lines, '',
    'Values are copied from the saved metrics without rounding or recomputation. Interpret each protocol separately.',
    '读数直接取自保存指标，没有重新计算或舍入；各评价协议分别解释。'];
}

export function deliveryReadme(project, records, versions, rows = []) {
  const selected = name => records.find(record => record.id === project.workflow?.[name]);
  const reference = selected('reference_entry_id'), candidate = selected('candidate_entry_id');
  const comparison = project.workflow?.comparison_href ? new URL(project.workflow.comparison_href, 'http://localhost') : null;
  const requirements = comparison ? [...comparison.searchParams].filter(([name]) => !['a', 'b'].includes(name)).map(([name, value]) => `- ${name}: ${value}`) : [];
  const lines = [
    `# ${cleanText(project.title)}`,
    '',
    'EEG Layout Lab research delivery / 科研交付包',
    '',
    `Project / 项目: ${project.id}`,
    `Researcher / 负责人: ${cleanText(project.owner_name)}`,
    `Project revision / 项目版本: ${project.revision}`,
    '',
    project.notes || '',
    '',
    '| Record / 记录 | Kind / 类型 | Protocol / 协议 | Scientific identity / 科学身份 |',
    '| --- | --- | --- | --- |',
    ...records.map(record => `| ${cleanText(record.title)} | ${record.kind} | ${cleanText(record.summary.protocol)} | ${record.record_id} |`),
    '',
    '## Study comparison / 研究比较',
    '',
    `Reference / 参考布局: ${reference ? cleanText(reference.title) + ' · ' + reference.record_id : 'unselected / 未选择'}`,
    `Candidate / 候选布局: ${candidate ? cleanText(candidate.title) + ' · ' + candidate.record_id : 'unselected / 未选择'}`,
    ...requirements,
    ...(requirements.length ? ['', 'ar, sensitivity and localization use percent; p90 uses millimetres. thresholdMode records joint or independent requirements.',
      'ar、sensitivity、localization 使用百分数，p90 使用毫米；thresholdMode 记录共同要求或独立要求。'] : []),
    ...savedReadings(rows),
    ...rows.filter(row => row.record.kind === 'source').flatMap(({ record, payload }) => ['', `## ${cleanText(record.title)}`, '',
      '| Signal condition / 信号条件 | Saved field retention / 保存的场保留比值 |', '| --- | --- |',
      ...(Array.isArray(payload.conditions) ? payload.conditions.map(condition => `| ${cleanText(condition.condition)} | ${reading(condition.field_retention)} |`) : [])]),
    '',
    '## Read the saved results / 读取保存结果',
    '',
    'Each file.content is the exact UTF-8 JSON text of a verified project snapshot. Parse that text as JSON to read snapshot.payload. file.sha256 checks the original text bytes.',
    '每个 file.content 是已验证项目快照的原始 UTF-8 JSON 文本。将该文本解析为 JSON 后读取 snapshot.payload；file.sha256 用于核对原始文本字节。',
    '',
    'Layout payloads include the existing reproducibility bundle; edited-layout payloads include the saved record and evaluation cache; signal payloads contain the complete scientific result, including requests, conditions and waveforms.',
    '布局快照包含原有复现包；编辑快照包含记录与评价缓存；信号快照包含完整科学结果，包括请求、条件与波形。',
    '',
    'Use each record under its saved model, coordinate system, units, source/noise conditions, protocol and runtime identity. Different evaluation protocols retain their own metric definitions.',
    '按各记录保存的头模、坐标系、单位、源与噪声条件、评价协议及运行环境身份解释结果；不同协议保留各自的指标定义。',
    '',
    '## Reproduce / 复现',
    '',
    'Install the matching scientific source, frozen model bundle and qualified runtime listed in the saved identities. Layout payload.reproduction specifies its request and entry point. Signal payload.request and payload.provenance retain the corresponding inputs and scientific identity.',
    '安装保存身份所对应的科学源码、冻结模型包和已验证运行环境。布局 payload.reproduction 记录请求与入口；信号 payload.request 和 payload.provenance 记录其输入及科学身份。',
    '',
    `Export host version / 导出宿主版本: ${cleanText(versions.application_version ?? 'unrecorded')}`,
    `Frozen data manifest SHA-256 / 冻结数据清单: ${versions.data_manifest_sha256 ?? 'unrecorded'}`,
    '',
    'The host version describes this export. The identities inside saved snapshots describe the original calculation. Model files are referenced by the data manifest and scientific identities, rather than duplicated in each delivery.',
    '宿主版本说明本次导出；快照内部身份说明原始计算。模型文件通过数据清单与科学身份引用，不在每份交付包中重复保存。',
    '',
  ];
  return lines.join('\n');
}

/** Preserve exact scientific text; project annotations stay outside each payload. */
export function buildResearchDelivery({ project: sourceProject, entries }, versions = {}, { now = () => new Date().toISOString(), maxBytes = MAX_DELIVERY_BYTES } = {}) {
  const project = publicProject(sourceProject);
  if (!validateProject(project)) throw fail('Project delivery metadata is invalid.');
  if (!Array.isArray(entries) || entries.length !== sourceProject.entries.length || !Number.isSafeInteger(maxBytes) || maxBytes < 1) throw fail('Project delivery entries are incomplete.');
  const seen = new Set(), records = [], files = [], readings = [];
  let total = 0;
  for (const { entry, snapshot_json } of entries) {
    const listed = sourceProject.entries.find(value => value.id === entry?.id);
    if (!listed || seen.has(entry.id) || !UUID.test(entry.id) || !kinds.includes(entry.kind) || typeof snapshot_json !== 'string') throw fail('Project delivery entry identity mismatch.');
    seen.add(entry.id);
    const bytes = Buffer.byteLength(snapshot_json), sha256 = hash(snapshot_json);
    if (sha256 !== entry.snapshot_sha256 || sha256 !== listed.snapshot_sha256 || bytes !== entry.snapshot_bytes || bytes !== listed.snapshot_bytes) throw fail('Project snapshot checksum mismatch.');
    let snapshot;
    try { snapshot = JSON.parse(snapshot_json); } catch { throw fail('Project snapshot is not valid JSON.'); }
    if (snapshot.schema !== 'research-project-snapshot/1' || snapshot.kind !== entry.kind || snapshot.record_id !== entry.record_id || !object(snapshot.payload)) throw fail('Project snapshot scientific identity mismatch.');
    total += bytes;
    if (total > maxBytes) throw fail('Project delivery exceeds the export size limit.', 413);
    const path = `records/${entry.id}.json`;
    records.push(clone({ id: entry.id, kind: entry.kind, record_id: entry.record_id, title: entry.title, notes: entry.notes,
      created_at: entry.created_at, summary: entry.summary, path, snapshot_sha256: sha256 }));
    readings.push({ record: records.at(-1), payload: snapshot.payload });
    files.push({ path, media_type: 'application/json', encoding: 'utf-8', size_bytes: bytes, sha256, content: snapshot_json });
  }
  // Only explicitly selected host metadata is exported, never environment values.
  const host = clone({ application_version: versions.application_version, data_manifest_sha256: versions.data_manifest_sha256,
    data_bundle_id: versions.data_bundle_id, runtime_lock_sha256: versions.runtime_lock_sha256, source_files: versions.source_files });
  if (!validateHost(host)) throw fail('Research delivery host metadata is invalid.');
  const readme = deliveryReadme(project, records, host, readings);
  files.unshift({ path: 'README.md', media_type: 'text/markdown', encoding: 'utf-8', size_bytes: Buffer.byteLength(readme), sha256: hash(readme), content: readme });
  const bundle = { schema: DELIVERY_SCHEMA, exported_at: now(), project, host, records, files, scientific_results_recomputed: false };
  bundle.manifest_sha256 = hash(JSON.stringify(manifest(bundle)));
  // Escaped embedded JSON can exceed its original byte count; bound the wire object too.
  if (Buffer.byteLength(JSON.stringify(bundle)) > maxBytes) throw fail('Project delivery exceeds the export size limit.', 413);
  return bundle;
}

export function validateResearchDelivery(bundle) {
  if (!fields(bundle, ['schema', 'exported_at', 'project', 'host', 'records', 'files', 'manifest_sha256', 'scientific_results_recomputed']) ||
    bundle.schema !== DELIVERY_SCHEMA || !timestamp(bundle.exported_at) || !validateProject(bundle.project) || !validateHost(bundle.host) ||
    !Array.isArray(bundle.files) || !Array.isArray(bundle.records) || bundle.scientific_results_recomputed !== false) throw fail('Unsupported research delivery.');
  const names = new Set();
  for (const file of bundle.files) {
    if (!fields(file, ['path', 'media_type', 'encoding', 'size_bytes', 'sha256', 'content']) || typeof file.path !== 'string' ||
      !(file.path === 'README.md' || (file.path.startsWith('records/') && file.path.endsWith('.json') && UUID.test(file.path.slice(8, -5)))) ||
      names.has(file.path) || file.encoding !== 'utf-8' || file.media_type !== (file.path === 'README.md' ? 'text/markdown' : 'application/json') ||
      typeof file.content !== 'string' || file.size_bytes !== Buffer.byteLength(file.content) || file.sha256 !== hash(file.content)) throw fail('Research delivery file failed integrity checks.');
    names.add(file.path);
  }
  if (!names.has('README.md') || bundle.files.length !== bundle.records.length + 1 || bundle.manifest_sha256 !== hash(JSON.stringify(manifest(bundle)))) throw fail('Research delivery manifest failed integrity checks.');
  const recordIds = new Set(), recordPaths = new Set();
  for (const record of bundle.records) {
    if (!fields(record, ['id', 'kind', 'record_id', 'title', 'notes', 'created_at', 'summary', 'path', 'snapshot_sha256']) || !UUID.test(record.id) ||
      !kinds.includes(record.kind) || !SHA.test(record.record_id) || record.path !== `records/${record.id}.json` || !object(record.summary) ||
      typeof record.title !== 'string' || typeof record.notes !== 'string' || !timestamp(record.created_at) || recordIds.has(record.id) || recordPaths.has(record.path)) throw fail('Research delivery record identity mismatch.');
    recordIds.add(record.id); recordPaths.add(record.path);
    const file = bundle.files.find(value => value.path === record.path);
    if (!file || file.sha256 !== record.snapshot_sha256) throw fail('Research delivery record is missing.');
    const snapshot = JSON.parse(file.content);
    if (snapshot.schema !== 'research-project-snapshot/1' || snapshot.kind !== record.kind || snapshot.record_id !== record.record_id || !object(snapshot.payload)) throw fail('Research delivery record identity mismatch.');
  }
  return true;
}
