import { EDITOR_WORKFLOW } from './project-paths.mjs';
/** Local-only, independently versioned editor. Fixed64 caches remain untouched. */
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { DesignEvaluationService } from './design-evaluation-server.mjs';
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const id = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

export function normalizeEditorRequest(raw) {
  if (!raw || !['prepare', 'evaluate'].includes(raw.action) || !id(raw.parent_id)) throw new Error('Invalid editor request');
  if (raw.action === 'prepare') {
    if (Object.keys(raw).sort().join(',') !== 'action,parent_id') throw new Error('Invalid preparation fields');
    return { action: 'prepare', parent_id: raw.parent_id };
  }
  if (Object.keys(raw).sort().join(',') !== 'action,parent_digest,parent_id,seed,slots' || !id(raw.parent_digest) || raw.seed !== 2026) throw new Error('Invalid editor protocol');
  if (!Array.isArray(raw.slots) || raw.slots.length !== 64 || raw.slots.some(s => !s || Object.keys(s).sort().join(',') !== 'bank_index,enabled' || !Number.isInteger(s.bank_index) || s.bank_index < 0 || s.bank_index > 1000000 || typeof s.enabled !== 'boolean')) throw new Error('Invalid stable electrode slots');
  if (raw.slots.filter(s => s.enabled).length < 2) throw new Error('At least two active electrodes are required');
  return { action: 'evaluate', parent_id: raw.parent_id, parent_digest: raw.parent_digest, seed: 2026,
    slots: raw.slots.map(s => ({ bank_index: s.bank_index, enabled: s.enabled })) };
}
export function validateEditorResult(r, request) {
  if (r?.schema !== 'electrode-editor/1' || r.status !== 'completed' || JSON.stringify(r.request) !== JSON.stringify(request)) throw new Error('Editor result identity mismatch');
  if (request.action === 'prepare') {
    if (r.parent?.id !== request.parent_id || r.original_indices?.length !== 64 || r.regions?.length !== r.parent.region_count || r.regions.some(a => !a.bank_indices?.length || a.bank_indices.length !== a.xyz_mm?.length)) throw new Error('Invalid editor region data');
    return;
  }
  const n = request.slots.filter(s => s.enabled).length;
  if (r.electrode_count !== n || r.evaluated_xyz_mm?.length !== n || r.active_slots?.length !== n || r.region_indices?.length !== n) throw new Error('Invalid edited electrode count');
  if (JSON.stringify(request.slots.flatMap((s, i) => s.enabled ? [i] : [])) !== JSON.stringify(r.active_slots)) throw new Error('Stable electrode identities changed');
  if (!Number.isFinite(r.minimum_distance_mm) || r.minimum_distance_mm < 4 - 1e-7 || r.evaluated_xyz_mm.some(p => p.length !== 3 || !p.every(Number.isFinite))) throw new Error('Invalid edited geometry');
  for (const m of [r.baseline, r.parent_metrics, r.edited_metrics]) {
    if (!m || !Number.isFinite(m.field_relative) || !Number.isFinite(m.field_absolute)) throw new Error('Missing field metric');
    for (const k of ['sensitivity_tail', 'localization_relative', 'median_mm', 'p90_mm']) if (m[k] !== null && !Number.isFinite(m[k])) throw new Error('Invalid editor metric');
  }
  for (const m of [r.parent_metrics, r.edited_metrics]) {
    const values = [m.field_relative, m.sensitivity_tail, m.localization_relative], expected = values.includes(null) ? null : Math.min(...values);
    if (expected === null ? m.conditional_global !== null : !Number.isFinite(m.conditional_global) || Math.abs(expected - m.conditional_global) > 1e-10) throw new Error('Invalid editor decision score');
  }
}
export class ElectrodeEditorService extends DesignEvaluationService {
  constructor(queue, options) { super(queue, options); this.scriptName = 'scripts/electrode_editor.py'; this.recordKind = 'editor'; }
  normalize(raw) { return normalizeEditorRequest(raw); }
  validate(result, request) { return validateEditorResult(result, request); }
  async context(request) {
    const parent = await this.queue.library.get(request.parent_id);
    if (parent?.status !== 'completed' || !parent.layout?.regionPatchVertexIndices || parent.layout.xyzMm?.length !== 64) throw new Error('Choose a completed layout with saved region boundaries');
    if (parent.request?.noise_model) throw new Error('The electrode editor scores with independent noise; choose a layout searched under independent noise');
    const parent_digest = hash(parent);
    if (request.action === 'evaluate' && request.parent_digest !== parent_digest) throw new Error('Parent changed; reload the layout before editing');
    const base = await super.context(request);
    let geometry = parent.provenance.geometry_sha256;
    if (parent.dataset_id === 'strict_area') {
      const report = parent.provenance.file;
      if (await this.inputs.digest(report) !== parent.provenance.sha256) throw new Error('Parent report identity mismatch');
      geometry = JSON.parse(await readFile(join(this.root, report), 'utf8')).identity?.geometry_sha256;
    }
    if (geometry !== base.admission.geometry_sha256 || parent.provenance.surface_admissibility_sha256 !== base.admission.sha256) throw new Error('Parent region geometry or surface-admission identity differs');
    const identity = { ...base.identity, schema: 'electrode-editor-cache/1', parent_digest, editor_sha256: await this.inputs.digest(this.scriptName), editor_implementation_sha256: Object.fromEntries(await Promise.all(EDITOR_WORKFLOW.map(async p => [p, await this.inputs.digest(p)]))) };
    return { ...base, parent, parent_digest, identity, key: hash({ request, identity }) };
  }
  workerInput(j) { return { request: j.request, parent: j.ctx.parent }; }
  view(j) { return { ...super.view(j), parent_digest: j.ctx?.parent_digest ?? (j.result?.parent ? hash(j.result.parent) : j.result?.request?.parent_digest) }; }
  async records() {
    const entries = await this.store.keys(this.recordKind);
    const records = [];
    for (const key of entries.filter(id)) {
      try {
        const c = await this.store.read(this.store.path(this.recordKind, key, 'cache.json')), r = c.result;
        if (r?.request?.action !== 'evaluate' || hash(r) !== c.result_sha256 || c.key !== key || hash({ request: r.request, identity: c.identity }) !== key) continue;
        this.validate(r, r.request);
        records.push({ key, finished_at: c.finished_at, parent_id: r.request.parent_id, parent_label: r.parent_label,
          electrode_count: r.electrode_count, active_regions: r.active_regions, metrics: r.edited_metrics, request: r.request, protocol: r.schema, restored_as: 'draft_requires_current_evaluation' });
      } catch { /* Never expose incomplete evaluations as scores. */ }
    }
    return records.sort((a, b) => b.finished_at.localeCompare(a.finished_at));
  }
  /** Library layouts with region patches; `visible` narrows the library rows to one browser's view first. */
  async parents(visible = rows => rows) {
    const library = await this.queue.library.list();
    const records = [];
    for (const summary of visible(library.records).filter(r => r.status === 'completed' && ['strict_area', 'cache'].includes(r.dataset_id) && !r.request?.noise_model && !r.request?.electrode_count)) {
      const r = await this.queue.library.get(summary.id);
      if (r?.layout?.regionPatchVertexIndices && r.layout.xyzMm?.length === 64) records.push(summary);
    }
    return records;
  }
  async handle(req, res, path, send) {
    if (req.method === 'GET' && path === '/api/electrode-editor/parents') return send(res, 200, { records: await this.parents() });
    if (req.method === 'GET' && path === '/api/electrode-editor/records') return send(res, 200, { records: await this.records() });
    if (req.method === 'POST' && path === '/api/electrode-editor/jobs') {
      if (!String(req.headers['content-type']).startsWith('application/json')) return send(res, 415, { error: 'JSON required' });
      let body = '';
      for await (const chunk of req) { body += chunk; if (Buffer.byteLength(body) > 32768) return send(res, 413, { error: 'Editor request too large' }); }
      let request;
      try { request = this.normalize(JSON.parse(body)); } catch (e) { return send(res, 400, { error: e.message }); }
      const v = await this.submit(request); return send(res, v.busy ? 409 : 202, v);
    }
    const match = path.match(/^\/api\/electrode-editor\/jobs\/([a-f0-9-]{36})(\/cancel)?$/);
    if (match) {
      const j = this.jobs.get(match[1]);
      if (!j) return send(res, 404, { error: 'Job expired; submit again to read the saved result' });
      if (req.method === 'GET' && !match[2]) return send(res, 200, { job: this.view(j) });
      if (req.method === 'POST' && match[2]) { this.cancel(j.id); return send(res, 202, { job: this.view(j) }); }
    }
    return send(res, 404, { error: 'Unknown editor endpoint' });
  }
}
