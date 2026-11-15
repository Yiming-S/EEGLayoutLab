/** Durable study metadata and exact scientific cache copies, separate from all scientific records. */
import { createHash, randomUUID } from "node:crypto";
import { lstat, mkdir, open, readdir, realpath, rename, unlink } from "node:fs/promises";
import { basename, dirname, join } from "node:path";
import { ProjectStore, validProjectId } from "../projects/store.mjs";
import { atomicJson } from "../storage/records.mjs";
import { normalizeDesignRequest, validateDesignResult } from "../design-evaluation-server.mjs";
import { electrodeNames } from "../annotations/electrode-names.mjs";
import { validateCoordinateSource } from "../../contracts/coordinate-source.mjs";
import { STUDY_LIMITS, aggregateStudy, studyError, summarizeStudyCase } from "./protocol.mjs";

const SHA = /^[a-f0-9]{64}$/;
export const digestStudyBytes = (bytes) => createHash("sha256").update(bytes).digest("hex");
const jsonHash = (value) => digestStudyBytes(JSON.stringify(value));
const clone = (value) => structuredClone(value);
const statuses = [
  "draft",
  "running",
  "paused_recovery",
  "paused_resource",
  "cancelling",
  "completed",
  "completed_with_failures",
  "cancelled",
];
const caseStatuses = [
  "pending",
  "submitting",
  "queued",
  "running",
  "cancelling",
  "completed",
  "failed",
  "cancelled",
  "failed_uncertain",
];
export function validateStudyCache(cache, entry) {
  if (
    !cache ||
    cache.key !== entry.key ||
    !cache.identity ||
    jsonHash({ request: entry.request, identity: cache.identity }) !== entry.key ||
    jsonHash(cache.result) !== cache.result_sha256 ||
    JSON.stringify(cache.result?.request) !== JSON.stringify(entry.request)
  )
    throw studyError("Study scientific cache identity mismatch.", 409);
  validateDesignResult(cache.result, entry.request);
  return cache;
}
function validate(record) {
  try {
    if (record.cancel_requested !== undefined && typeof record.cancel_requested !== "boolean")
      throw new Error();
    if (
      record.schema !== "eeg-robustness-study/1" ||
      !validProjectId(record.id) ||
      !SHA.test(record.owner) ||
      !["noise_seeds", "grid_displacements"].includes(record.protocol) ||
      !statuses.includes(record.status) ||
      !Number.isSafeInteger(record.revision) ||
      record.revision < 1 ||
      typeof record.title !== "string" ||
      !record.title.trim() ||
      record.title.length > 200 ||
      typeof record.notes !== "string" ||
      record.notes.length > 2000 ||
      ![record.created_at, record.updated_at].every((value) =>
        Number.isFinite(Date.parse(value)),
      ) ||
      !SHA.test(record.identity_sha256) ||
      !Array.isArray(record.cases) ||
      !record.cases.length ||
      record.cases.length > STUDY_LIMITS.cases
    )
      throw new Error();
    const requests = new Set();
    if (
      !record.annotation ||
      Object.keys(record.annotation).some(
        (key) => !["electrode_names", "source_metadata"].includes(key),
      )
    )
      throw new Error();
    if (record.annotation.electrode_names !== undefined)
      electrodeNames(record.annotation.electrode_names);
    if (record.annotation.source_metadata !== undefined)
      validateCoordinateSource(record.annotation.source_metadata);
    for (const [index, entry] of record.cases.entries()) {
      if (
        entry.index !== index ||
        !SHA.test(entry.key) ||
        !caseStatuses.includes(entry.status) ||
        !(entry.receipt_id === null || validProjectId(entry.receipt_id)) ||
        JSON.stringify(normalizeDesignRequest(entry.request)) !== JSON.stringify(entry.request) ||
        JSON.stringify(entry.request.design) !== JSON.stringify(record.design) ||
        entry.request.action !== (record.protocol === "noise_seeds" ? "evaluate" : "perturb")
      )
        throw new Error();
      if (
        entry.source_sha256 !== undefined &&
        (!SHA.test(entry.source_sha256) ||
          !Number.isSafeInteger(entry.source_bytes) ||
          entry.source_bytes < 2 ||
          entry.source_bytes > STUDY_LIMITS.caseBytes)
      )
        throw new Error();
      if (entry.status === "completed" && entry.source_sha256 === undefined) throw new Error();
      if (entry.operation_id !== undefined && !validProjectId(entry.operation_id))
        throw new Error();
      if (entry.status === "submitting" && !validProjectId(entry.operation_id)) throw new Error();
      if (entry.annotation_id !== undefined && !SHA.test(entry.annotation_id)) throw new Error();
      const request = JSON.stringify(entry.request);
      if (requests.has(request)) throw new Error();
      requests.add(request);
    }
    if (
      record.protocol === "noise_seeds" &&
      new Set(record.cases.map((entry) => entry.request.radius_mm)).size !== 1
    )
      throw new Error();
  } catch {
    throw studyError("Study metadata failed integrity checks.", 409);
  }
  return record;
}
async function atomicBytes(path, bytes) {
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    const handle = await open(temporary, "wx", 0o600);
    try {
      await handle.writeFile(bytes);
      await handle.sync();
    } finally {
      await handle.close();
    }
    await rename(temporary, path);
    const directory = await open(dirname(path), "r");
    try {
      await directory.sync();
    } finally {
      await directory.close();
    }
  } finally {
    await unlink(temporary).catch((error) => {
      if (error.code !== "ENOENT") throw error;
    });
  }
}

export class StudyStore {
  constructor(
    directory,
    {
      beforeWrite = async () => {},
      now = () => new Date().toISOString(),
      limits = STUDY_LIMITS,
    } = {},
  ) {
    this.io = new ProjectStore(directory);
    this.beforeWrite = beforeWrite;
    this.now = now;
    this.limits = limits;
  }
  get directory() {
    return this.io.directory;
  }
  get pendingWrites() {
    return this.io.pendingWrites;
  }
  get closed() {
    return this.io.closed;
  }
  close() {
    this.io.close();
  }
  flush() {
    return this.io.flush();
  }
  async root(create = false) {
    try {
      this.io.directory = join(
        await realpath(dirname(this.io.directory)),
        basename(this.io.directory),
      );
    } catch (error) {
      if (!create && error.code === "ENOENT") return false;
      throw error;
    }
    try {
      await this.io.safeDirectory(this.directory);
      return true;
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      if (!create) return false;
      await this.io.ready();
      return true;
    }
  }
  async ids() {
    if (!(await this.root())) return [];
    const rows = await readdir(this.directory, { withFileTypes: true });
    if (rows.length > this.limits.studies) throw studyError("Study directory limit exceeded.", 507);
    for (const row of rows) {
      if (!validProjectId(row.name) || !row.isDirectory() || row.isSymbolicLink())
        throw studyError("Study directory needs inspection.", 409);
      await this.io.safeDirectory(join(this.directory, row.name));
    }
    return rows.map((row) => row.name);
  }
  async load(id, owner) {
    if (!validProjectId(id)) throw studyError("Study not found.", 404);
    try {
      if (!(await this.root())) throw studyError("Study not found.", 404);
      const folder = await this.io.projectDirectory(id),
        value = validate(
          JSON.parse(await this.io.file(join(folder, "study.json"), this.limits.metadataBytes)),
        );
      if (value.id !== id || (owner !== undefined && value.owner !== owner))
        throw studyError("Study not found.", 404);
      return value;
    } catch (error) {
      if (error.code === "ENOENT") throw studyError("Study not found.", 404);
      throw error;
    }
  }
  async all() {
    const records = [];
    for (const id of await this.ids()) {
      try {
        records.push(await this.load(id));
      } catch (error) {
        if (error.status !== 404)
          throw error; /* An interrupted, unpublished create still counts against capacity. */
      }
    }
    return records;
  }
  async usage() {
    let bytes = 0;
    const walk = async (folder) => {
      await this.io.safeDirectory(folder);
      for (const entry of await readdir(folder, { withFileTypes: true })) {
        const path = join(folder, entry.name),
          metadata = await lstat(path);
        if (
          metadata.isSymbolicLink() ||
          (!metadata.isDirectory() && (!metadata.isFile() || metadata.nlink !== 1))
        )
          throw studyError("Study storage contains an unsafe entry.", 409);
        if (metadata.isDirectory()) {
          if (!(entry.name === "snapshots" || validProjectId(entry.name)))
            throw studyError("Study storage needs inspection.", 409);
          await walk(path);
        } else {
          if (!/^(?:study|[a-f0-9]{64})\.json(?:\.[a-f0-9-]{36}\.tmp)?$/.test(entry.name))
            throw studyError("Study storage needs inspection.", 409);
          bytes += metadata.size;
        }
      }
    };
    if (await this.root()) await walk(this.directory);
    return bytes;
  }
  async save(record) {
    validate(record);
    const bytes = Buffer.byteLength(JSON.stringify(record));
    if (bytes > this.limits.metadataBytes)
      throw studyError("Study metadata exceeds the size limit.", 413);
    if ((await this.usage()) + bytes > this.limits.totalBytes)
      throw studyError("Study storage capacity reached.", 507);
    const path = join(await this.io.projectDirectory(record.id), "study.json");
    try {
      const value = await lstat(path);
      if (!value.isFile() || value.isSymbolicLink() || value.nlink !== 1)
        throw studyError("Study metadata path is unsafe.", 409);
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    await atomicJson(path, record);
  }
  create(owner, prepared) {
    return this.io.serialize(async () => {
      await this.beforeWrite();
      await this.root(true);
      const all = await this.all();
      if (
        (await this.ids()).length >= this.limits.studies ||
        all.filter((record) => record.owner === owner).length >= this.limits.perOwner
      )
        throw studyError("Study count limit reached.", 429);
      const id = randomUUID(),
        at = this.now(),
        record = {
          schema: "eeg-robustness-study/1",
          id,
          owner,
          ...clone(prepared),
          status: "draft",
          revision: 1,
          created_at: at,
          updated_at: at,
        };
      validate(record);
      await mkdir(join(this.directory, id), { mode: 0o700 });
      await mkdir(join(this.directory, id, "snapshots"), { mode: 0o700 });
      await this.save(record);
      return clone(record);
    });
  }
  update(id, owner, change, { control = false } = {}) {
    return this.io.serialize(async () => {
      // Cancellation stops accepted work; it must not require new-work admission.
      // Ownership, safe paths, file/total limits and durable atomic writes still apply.
      if (!control) await this.beforeWrite();
      const record = await this.load(id, owner);
      await change(record);
      record.revision++;
      record.updated_at = this.now();
      await this.save(record);
      return clone(record);
    });
  }
  controlUpdate(id, owner, change) {
    return this.update(id, owner, change, { control: true });
  }
  archive(id, owner, index, bytes) {
    return this.io.serialize(async () => {
      await this.beforeWrite();
      const record = await this.load(id, owner),
        entry = record.cases[index];
      if (!entry) throw studyError("Study case not found.", 404);
      if (bytes.length > this.limits.caseBytes)
        throw studyError("Study case snapshot is too large.", 413);
      const cache = validateStudyCache(JSON.parse(bytes.toString("utf8")), entry),
        sha256 = digestStudyBytes(bytes),
        folder = join(await this.io.projectDirectory(id), "snapshots");
      await this.io.safeDirectory(folder);
      let existingBytes = 0;
      const files = await readdir(folder);
      if (files.length >= 36) throw studyError("Study snapshot file limit reached.", 507);
      for (const name of files) {
        const item = await lstat(join(folder, name));
        if (
          !item.isFile() ||
          item.isSymbolicLink() ||
          item.nlink !== 1 ||
          !/^[a-f0-9]{64}\.json(?:\.[a-f0-9-]{36}\.tmp)?$/.test(name)
        )
          throw studyError("Study snapshot path is unsafe.", 409);
        existingBytes += item.size;
      }
      const path = join(folder, sha256 + ".json");
      let exists = false;
      try {
        const existing = await this.io.file(path, this.limits.caseBytes);
        if (digestStudyBytes(existing) !== sha256)
          throw studyError("Study snapshot checksum mismatch.", 409);
        exists = true;
      } catch (error) {
        if (error.code !== "ENOENT") throw error;
      }
      if (
        existingBytes + (exists ? 0 : bytes.length) > this.limits.studyBytes ||
        (await this.usage()) + (exists ? 0 : bytes.length) > this.limits.totalBytes
      )
        throw studyError("Study snapshot capacity reached.", 507);
      if (!exists) await atomicBytes(path, bytes);
      entry.status = "completed";
      entry.source_sha256 = sha256;
      entry.source_bytes = bytes.length;
      entry.error = null;
      record.revision++;
      record.updated_at = this.now();
      await this.save(record);
      return clone(cache.result);
    });
  }
  async snapshot(record, entry) {
    const folder = join(await this.io.projectDirectory(record.id), "snapshots");
    await this.io.safeDirectory(folder);
    const bytes = await this.io.file(
      join(folder, entry.source_sha256 + ".json"),
      this.limits.caseBytes,
    );
    if (bytes.length !== entry.source_bytes || digestStudyBytes(bytes) !== entry.source_sha256)
      throw studyError("Study snapshot checksum mismatch.", 409);
    return {
      cache: validateStudyCache(JSON.parse(bytes), entry),
      cache_json: bytes.toString("utf8"),
    };
  }
  async present(id, owner, exportCache = false) {
    const record = await this.load(id, owner),
      study = clone(record),
      caches = [];
    delete study.owner;
    delete study.identity_sha256;
    for (const entry of study.cases) {
      entry.summary = null;
      let cache = null,
        cache_json = null;
      if (entry.status === "completed") {
        ({ cache, cache_json } = await this.snapshot(record, entry));
        entry.summary = summarizeStudyCase(cache.result);
      }
      if (exportCache)
        caches.push({
          index: entry.index,
          key: entry.key,
          source_sha256: entry.source_sha256 ?? null,
          cache,
          cache_json,
        });
    }
    study.aggregation = aggregateStudy(study.protocol, study.cases);
    return exportCache ? { schema: "eeg-robustness-study-export/1", study, cases: caches } : study;
  }
}
