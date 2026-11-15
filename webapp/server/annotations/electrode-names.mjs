/** Immutable presentation metadata. Scientific records and cache identities are never written. */
import { createHash, randomUUID } from 'node:crypto';
import { constants, closeSync, existsSync, fsyncSync, fstatSync, lstatSync, mkdirSync, openSync, readSync, readdirSync, realpathSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { validateCoordinateSource } from '../../contracts/coordinate-source.mjs';

const SHA = /^[a-f0-9]{64}$/;
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const error = (message, status = 400) => Object.assign(new Error(message), { status, annotationSafe: true });
export const ANNOTATION_LIMITS = Object.freeze({ files: 2000, bytes: 64 * 1024 * 1024, fileBytes: 32768, referencesPerOwner: 20, referencesPerTask: 100 });
function hasNameControl(value) {
  for (let index = 0; index < value.length; index++) if (value.charCodeAt(index) < 32 || value.charCodeAt(index) === 127) return true;
  return false;
}
export function electrodeNames(value) {
  if (!Array.isArray(value) || value.length !== 64 || new Set(value).size !== 64 || value.some(name => typeof name !== 'string' || !name.trim() || name.length > 128 || hasNameControl(name)))
    throw error('需要64个不重复的电极名称，每个名称最多128个字符且不含控制字符。');
  return [...value];
}
export function designSubmission(raw) {
  if (raw?.schema !== 'design-submission/1') return { request: raw };
  if (Object.keys(raw).some(key => !['electrode_names', 'request', 'schema', 'source_metadata'].includes(key)) || !raw.request) throw error('Invalid design submission metadata.');
  return { request: raw.request, electrode_names: electrodeNames(raw.electrode_names),
    ...(raw.source_metadata === undefined ? {} : { source_metadata: validateCoordinateSource(raw.source_metadata) }) };
}
function publicValue(value) {
  const { schema, id, record_id, request_sha256, electrode_names } = value;
  return { schema, id, record_id, request_sha256, electrode_names: [...electrode_names], ...(value.source_metadata ? { source_metadata: validateCoordinateSource(value.source_metadata) } : {}) };
}
export function validateElectrodeAnnotation(value, recordId) {
  if (!value || Object.keys(value).filter(key => key !== 'source_metadata').sort().join(',') !== 'electrode_names,id,record_id,request_sha256,schema' || value.schema !== 'eeg-electrode-annotation/1' ||
      !SHA.test(value.id) || value.record_id !== recordId || !SHA.test(value.request_sha256)) throw error('Invalid electrode name annotation.');
  electrodeNames(value.electrode_names); if (value.source_metadata !== undefined) validateCoordinateSource(value.source_metadata); return value;
}
export class ElectrodeAnnotations {
  constructor(root, { limits = ANNOTATION_LIMITS } = {}) { this.root = realpathSync(root); this.limits = limits; }
  directory(create = false) {
    let current = this.root;
    for (const part of ['results', 'v2', 'design_evaluation_jobs', 'electrode_annotations']) {
      current = join(current, part);
      if (!existsSync(current)) { if (!create) return null; mkdirSync(current, { mode: 0o700 }); }
      const entry = lstatSync(current);
      if (!entry.isDirectory() || entry.isSymbolicLink() || realpathSync(current) !== current) throw error('Electrode name storage is unavailable.', 409);
    }
    return current;
  }
  read(id, owner, recordId) {
    if (!SHA.test(id ?? '') || typeof owner !== 'string' || !SHA.test(recordId ?? '')) throw error('Electrode name annotation not found.', 404);
    try {
      const directory = this.directory(), path = directory && join(directory, `${id}.json`);
      if (!path || !existsSync(path)) throw error('Electrode name annotation not found.', 404);
      const stat = lstatSync(path);
      if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1 || stat.size > this.limits.fileBytes) throw error('Electrode name annotation failed integrity checks.', 409);
      const value = this.file(path);
      const { id: storedId, ...identity } = value;
      if (Object.keys(value).filter(key => key !== 'source_metadata').sort().join(',') !== 'electrode_names,id,owner,record_id,regions_sha256,request_sha256,schema,xyz_sha256' || storedId !== id || hash(identity) !== id || value.schema !== 'eeg-electrode-annotation/1' || !SHA.test(value.request_sha256) || !SHA.test(value.xyz_sha256) || !SHA.test(value.regions_sha256)) throw error('Electrode name annotation failed integrity checks.', 409);
      electrodeNames(value.electrode_names);
      if (value.source_metadata !== undefined) validateCoordinateSource(value.source_metadata);
      if (value.owner !== owner || value.record_id !== recordId) throw error('Electrode name annotation not found.', 404);
      return publicValue(value);
    } catch (cause) { if (cause.annotationSafe) throw cause; throw error('Electrode name storage is unavailable.', 409); }
  }
  file(path) {
    const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
      const stat = fstatSync(fd);
      if (!stat.isFile() || stat.nlink !== 1 || stat.size > this.limits.fileBytes) throw error('Electrode name annotation failed integrity checks.', 409);
      const buffer = Buffer.alloc(this.limits.fileBytes + 1); let length = 0;
      while (length < buffer.length) { const read = readSync(fd, buffer, length, buffer.length - length, null); if (!read) break; length += read; }
      const bytes = buffer.subarray(0, length);
      if (bytes.length > this.limits.fileBytes || bytes.length !== stat.size || fstatSync(fd).size !== stat.size) throw error('Electrode name annotation failed integrity checks.', 409);
      return JSON.parse(bytes.toString('utf8'));
    } finally { closeSync(fd); }
  }
  identity(prepared, owner) {
    const names = electrodeNames(prepared.electrode_names);
    if (!SHA.test(prepared.key) || typeof owner !== 'string' || !owner || owner.length > 128) throw error('Invalid electrode annotation identity.');
    const identity = { schema: 'eeg-electrode-annotation/1', owner, record_id: prepared.key,
      request_sha256: hash(prepared.request), xyz_sha256: hash(prepared.request.design.xyz_mm),
      regions_sha256: hash(prepared.request.design.region_indices), electrode_names: names,
      ...(prepared.source_metadata === undefined ? {} : { source_metadata: validateCoordinateSource(prepared.source_metadata) }) };
    return { id: hash(identity), ...identity };
  }
  create(prepared, owner) {
    const value = this.identity(prepared, owner), id = value.id, raw = JSON.stringify(value);
    if (Buffer.byteLength(raw) > this.limits.fileBytes) throw error('Electrode name metadata is too large.', 413);
    try {
      const directory = this.directory(true), path = join(directory, `${id}.json`);
      if (existsSync(path)) return this.read(id, owner, prepared.key);
      let bytes = 0, count = 0;
      for (const name of readdirSync(directory)) {
        if (!/^[a-f0-9]{64}\.json$/.test(name) && !/^\.[a-f0-9-]{36}\.tmp$/.test(name)) throw error('Electrode name storage needs inspection.', 409);
        const item = lstatSync(join(directory, name));
        if (!item.isFile() || item.isSymbolicLink() || item.nlink !== 1 || item.size > this.limits.fileBytes) throw error('Electrode name storage needs inspection.', 409);
        count++; bytes += item.size;
      }
      if (count >= this.limits.files || bytes + Buffer.byteLength(raw) > this.limits.bytes) throw error('Electrode name storage limit reached.', 507);
      const temporary = join(directory, `.${randomUUID()}.tmp`), fd = openSync(temporary, 'wx', 0o600);
      try { writeFileSync(fd, raw); fsyncSync(fd); } finally { closeSync(fd); }
      try { renameSync(temporary, path); const dir = openSync(directory, 'r'); try { fsyncSync(dir); } finally { closeSync(dir); } }
      finally { if (existsSync(temporary)) unlinkSync(temporary); }
      return publicValue(value);
    } catch (cause) { if (cause.annotationSafe) throw cause; throw error('Electrode name storage is unavailable.', 503); }
  }
  list(owner) {
    const directory = this.directory(); if (!directory) return [];
    const files = readdirSync(directory);
    if (files.length > this.limits.files) throw error('Electrode name storage limit reached.', 507);
    const result = [];
    try { for (const name of files) {
      if (/^\.[a-f0-9-]{36}\.tmp$/.test(name)) {
        const stat = lstatSync(join(directory, name));
        if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1 || stat.size > this.limits.fileBytes) throw error('Electrode name storage needs inspection.', 409);
        continue;
      }
      if (!/^[a-f0-9]{64}\.json$/.test(name)) throw error('Electrode name storage needs inspection.', 409);
      const path = join(directory, name), stat = lstatSync(path);
      if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1 || stat.size > this.limits.fileBytes) throw error('Electrode name storage needs inspection.', 409);
      const value = this.file(path), checked = this.read(name.slice(0, -5), value.owner, value.record_id);
      if (value.owner === owner) result.push(checked);
    } } catch (cause) { if (cause.annotationSafe) throw cause; throw error('Electrode name storage is unavailable.', 409); }
    return result;
  }
}
