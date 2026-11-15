import { createHash, randomUUID } from "node:crypto";
import { join, relative } from "node:path";
import { realpath } from "node:fs/promises";
import { StudyStore, validateStudyCache } from "./store.mjs";
import { normalizeStudyInput, studyError, terminalCase } from "./protocol.mjs";
import { validProjectId } from "../projects/store.mjs";
import { INTERRUPTED_MESSAGE } from "../operations/reconciliation.mjs";

const hash = (value) => createHash("sha256").update(JSON.stringify(value)).digest("hex");
const ownTask = (task, entry, visitor) =>
  task.kind === "design-evaluation" &&
  task.key === entry.key &&
  task.owners.includes(visitor.id) &&
  JSON.stringify(task.request) === JSON.stringify(entry.request);
const safeFailure = (code, message) => ({
  code,
  message: String(message).slice(0, 500),
});

/** Explicitly started sequential composition. GETs and restart recovery never submit work. */
export class RobustnessStudyService {
  constructor({
    queue,
    scheduler,
    guard,
    send,
    tokenMatches,
    beforeWrite = async () => {},
    store,
    pollMs = 500,
  } = {}) {
    this.queue = queue;
    this.scheduler = scheduler;
    this.guard = guard;
    this.send = send;
    this.tokenMatches = tokenMatches;
    this.store =
      store ??
      new StudyStore(join(queue.runtime.queueDirectory, "studies"), {
        beforeWrite,
      });
    this.adapter = scheduler.adapters["design-evaluation"];
    this.active = new Map();
    this.inflight = new Map();
    this.needsPump = new Set();
    this.recovery = new Set();
    this.blocked = new Map();
    this.stopRequested = new Set();
    this.startReservations = new Set();
    this.closed = false;
    this.initialization = this.recover();
    this.initialization.catch(() => {});
    this.timer = setInterval(() => {
      for (const [id, visitor] of this.active) this.run(id, visitor);
    }, pollMs);
    this.timer.unref();
  }
  async recover() {
    for (const record of await this.store.all())
      if (["running", "cancelling"].includes(record.status)) {
        if (this.closed) return;
        this.recovery.add(record.id);
        try {
          await this.store.update(record.id, record.owner, (value) => {
            if (value.status === "cancelling") value.cancel_requested = true;
            value.status = "paused_recovery";
          });
        } catch (error) {
          if (!error.resourceSafe && error.status !== 507) throw error;
        }
      }
  }
  async ready() {
    await this.initialization;
  }
  stop() {
    this.closed = true;
    clearInterval(this.timer);
    this.active.clear();
  }
  async flush() {
    await this.initialization;
    while (this.inflight.size) await Promise.allSettled(this.inflight.values());
    await this.store.flush();
  }
  close() {
    this.stop();
    this.store.close();
  }
  async get(id, visitor) {
    await this.ready();
    const study = await this.store.present(id, visitor.id);
    if (this.recovery.has(id) && ["running", "cancelling"].includes(study.status))
      study.status = "paused_recovery";
    if (this.blocked.has(id)) {
      study.status = "paused_resource";
      study.last_error = this.blocked.get(id);
    }
    return { study };
  }
  async list(visitor) {
    await this.ready();
    return {
      studies: (await this.store.all())
        .filter((record) => record.owner === visitor.id)
        .map((record) => ({
          id: record.id,
          title: record.title,
          protocol: record.protocol,
          status: this.blocked.has(record.id)
            ? "paused_resource"
            : this.recovery.has(record.id)
              ? "paused_recovery"
              : record.status,
          created_at: record.created_at,
          updated_at: record.updated_at,
          case_count: record.cases.length,
          completed_cases: record.cases.filter((entry) => entry.status === "completed").length,
        })),
    };
  }
  async create(input, visitor) {
    await this.ready();
    if (this.closed) throw studyError("Study service is stopping.", 503);
    const normalized = normalizeStudyInput(input),
      cases = [];
    let identity;
    for (const [index, request] of normalized.requests.entries()) {
      const prepared = await this.adapter.prepare(request),
        current = hash(prepared.ctx.identity);
      if (identity && current !== identity)
        throw studyError("Scientific identity changed while preparing the study.", 409);
      identity = current;
      cases.push({
        index,
        request: prepared.request,
        key: prepared.key,
        status: "pending",
        receipt_id: null,
        error: null,
      });
    }
    if (this.closed) throw studyError("Study service is stopping.", 503);
    const { requests: _requests, ...metadata } = normalized;
    const record = await this.store.create(visitor.id, {
      ...metadata,
      identity_sha256: identity,
      cases,
    });
    return this.get(record.id, visitor);
  }
  async start(id, visitor, resume = false) {
    await this.ready();
    if (this.closed) throw studyError("Study service is stopping.", 503);
    if (this.active.has(id)) return this.get(id, visitor);
    if (this.startReservations.has(visitor.id))
      throw studyError("This browser already has an active study.", 429);
    this.startReservations.add(visitor.id);
    try {
      const others = await this.store.all();
      if (
        others.some(
          (record) => record.id !== id && record.owner === visitor.id && this.active.has(record.id),
        )
      )
        throw studyError("This browser already has an active study.", 429);
      const started = await this.store.update(id, visitor.id, (record) => {
        const allowed = resume ? ["paused_recovery", "paused_resource"] : ["draft"];
        if (
          resume &&
          (this.recovery.has(id) || this.blocked.has(id)) &&
          ["running", "cancelling"].includes(record.status)
        )
          allowed.push(record.status);
        if (!allowed.includes(record.status))
          throw studyError("Start a draft study or explicitly resume a paused study.", 409);
        if (record.status === "cancelling") record.cancel_requested = true;
        record.status = record.cancel_requested ? "cancelling" : "running";
        record.last_error = null;
      });
      this.recovery.delete(id);
      this.blocked.delete(id);
      if (started.cancel_requested) this.stopRequested.add(id);
      else this.stopRequested.delete(id);
      this.active.set(id, visitor);
      this.run(id, visitor);
      return this.get(id, visitor);
    } finally {
      this.startReservations.delete(visitor.id);
    }
  }
  run(id, visitor) {
    if (this.closed) return;
    if (this.inflight.has(id)) {
      this.needsPump.add(id);
      return;
    }
    const promise = Promise.resolve()
      .then(() => this.pump(id, visitor))
      .catch((error) => {
        this.active.delete(id);
        this.blocked.set(
          id,
          safeFailure(
            error.resourceSafe ? "resource_unavailable" : "study_storage_unavailable",
            "Study processing paused. Inspect the recorded cases before resuming.",
          ),
        );
      })
      .finally(() => {
        this.inflight.delete(id);
        if (this.needsPump.delete(id) && this.active.has(id) && !this.closed) this.run(id, visitor);
      });
    this.inflight.set(id, promise);
  }
  async setCase(id, visitor, index, change, control = false) {
    return this.store.update(
      id,
      visitor.id,
      (record) => Object.assign(record.cases[index], change),
      { control },
    );
  }
  async cache(entry) {
    const root = await realpath(this.queue.root),
      path = join(root, "results/v2/design_evaluation_jobs", entry.key, "cache.json");
    let cursor = root;
    for (const part of relative(root, join(path, "..")).split(/[\\/]/)) {
      cursor = join(cursor, part);
      await this.store.io.safeDirectory(cursor);
    }
    const bytes = await this.store.io.file(path, this.store.limits.caseBytes);
    validateStudyCache(JSON.parse(bytes), entry);
    return bytes;
  }
  async finishCache(id, visitor, entry) {
    let bytes;
    try {
      bytes = await this.cache(entry);
    } catch (error) {
      if (error.resourceSafe || error.status === 507) throw error;
      await this.setCase(id, visitor, entry.index, {
        status: "failed",
        error: safeFailure(
          "scientific_cache_invalid",
          "Completed case failed scientific cache integrity checks.",
        ),
      });
      return;
    }
    await this.store.archive(id, visitor.id, entry.index, bytes);
  }
  async reconcile(id, visitor, entry, cancelling = false) {
    const tasks = this.scheduler.tasks
      .filter((task) => ownTask(task, entry, visitor))
      .sort((a, b) => b.sequence - a.sequence);
    const task =
      tasks.find((value) => ["queued", "running", "cancelling"].includes(value.status)) ??
      tasks.find((value) => value.status === "completed") ??
      tasks[0];
    if (task) {
      await this.setCase(
        id,
        visitor,
        entry.index,
        {
          receipt_id: task.id,
          status:
            task.status === "completed"
              ? "running"
              : ["queued", "running", "cancelling"].includes(task.status)
                ? task.status
                : task.status === "cancelled"
                  ? "cancelled"
                  : "failed",
          error: null,
        },
        cancelling,
      );
      if (task.status === "completed") await this.finishCache(id, visitor, entry);
      if (cancelling && ["queued", "running", "cancelling"].includes(task.status))
        await this.cancelChild(id, visitor, { ...entry, receipt_id: task.id });
      return;
    }
    let bytes;
    try {
      bytes = await this.cache(entry);
    } catch (error) {
      if (error.resourceSafe || error.status === 507) throw error;
      await this.setCase(
        id,
        visitor,
        entry.index,
        {
          status: cancelling ? "cancelled" : "failed_uncertain",
          error: safeFailure(
            "submission_outcome_unknown",
            "No owned receipt or verified cache confirms the interrupted submission. It was not resubmitted.",
          ),
        },
        cancelling,
      );
      return;
    }
    await this.store.archive(id, visitor.id, entry.index, bytes);
  }
  async pump(id, visitor) {
    while (!this.closed) {
      const record = await this.store.load(id, visitor.id);
      if (this.stopRequested.has(id) && record.status === "running") return;
      if (!["running", "cancelling"].includes(record.status)) {
        this.active.delete(id);
        return;
      }
      const entry = record.cases.find((value) => !terminalCase(value.status));
      if (!entry) {
        await this.store.update(
          id,
          visitor.id,
          (value) => {
            value.status =
              value.cancel_requested || value.status === "cancelling"
                ? "cancelled"
                : value.cases.some((row) => row.status !== "completed")
                  ? "completed_with_failures"
                  : "completed";
          },
          { control: record.status === "cancelling" || record.cancel_requested === true },
        );
        this.active.delete(id);
        return;
      }
      if (entry.status === "submitting") {
        await this.reconcile(id, visitor, entry, record.status === "cancelling");
        continue;
      }
      if (entry.status === "pending") {
        if (record.status === "cancelling") {
          await this.setCase(id, visitor, entry.index, { status: "cancelled" }, true);
          continue;
        }
        const prepared = await this.adapter.prepare(entry.request);
        if (this.closed) return;
        if (prepared.key !== entry.key || hash(prepared.ctx.identity) !== record.identity_sha256) {
          await this.store.update(id, visitor.id, (value) => {
            for (const row of value.cases)
              if (row.status === "pending") {
                row.status = "failed";
                row.error = safeFailure(
                  "scientific_identity_changed",
                  "Scientific identity changed. Create a new study to use the updated model.",
                );
              }
          });
          continue;
        }
        let authorized = false;
        await this.store.update(id, visitor.id, (value) => {
          if (
            this.closed ||
            this.stopRequested.has(id) ||
            value.status !== "running" ||
            value.cases[entry.index].status !== "pending"
          )
            return;
          authorized = true;
          Object.assign(value.cases[entry.index], {
            status: "submitting",
            operation_id: randomUUID(),
            submission_started_at: new Date().toISOString(),
          });
        });
        if (!authorized) continue;
        if (this.closed) return;
        const raw = record.annotation.electrode_names
          ? {
              schema: "design-submission/1",
              request: entry.request,
              ...record.annotation,
            }
          : entry.request;
        let result;
        try {
          result = await this.scheduler.submit(
            "design-evaluation",
            raw,
            visitor,
            false,
            entry.key,
            () => !this.closed && !this.stopRequested.has(id),
          );
        } catch (error) {
          if (error.studyAdmissionCancelled) {
            if (this.closed && !this.stopRequested.has(id)) {
              await this.store.update(id, visitor.id, (value) => {
                value.status = "paused_recovery";
                value.cases[entry.index].status = "pending";
              });
              return;
            }
            await this.setCase(
              id,
              visitor,
              entry.index,
              {
                status: "cancelled",
                error: null,
              },
              true,
            );
            continue;
          } else if (error.admissionRejected || error.status === 429 || error.resourceSafe) {
            await this.store.update(id, visitor.id, (value) => {
              value.status = "paused_resource";
              value.last_error = safeFailure(
                "submission_deferred",
                "The original queue deferred this case. Resume explicitly when resources are available.",
              );
              Object.assign(value.cases[entry.index], {
                status: "pending",
                error: value.last_error,
              });
            });
          } else
            await this.store.update(id, visitor.id, (value) => {
              value.status = "paused_recovery";
              value.last_error = safeFailure(
                "submission_uncertain",
                "Submission did not return a confirmed receipt. Resume only to reconcile its original outcome.",
              );
            });
          this.active.delete(id);
          return;
        }
        if (result.job?.key !== entry.key || !validProjectId(result.job?.id))
          throw studyError("Study child receipt identity mismatch.", 409);
        await this.setCase(id, visitor, entry.index, {
          receipt_id: result.job.id,
          status: result.job.status === "completed" ? "running" : result.job.status,
          ...(result.job.annotation_id ? { annotation_id: result.job.annotation_id } : {}),
          error: null,
        });
        const latest = await this.store.load(id, visitor.id);
        if (latest.status === "cancelling")
          await this.cancelChild(id, visitor, {
            ...entry,
            receipt_id: result.job.id,
          });
        else if (result.job.status === "completed") await this.finishCache(id, visitor, entry);
        continue;
      }
      let task;
      try {
        task = this.scheduler.own(entry.receipt_id, visitor, "design-evaluation");
      } catch (error) {
        if (error.status !== 404) throw error;
        await this.setCase(id, visitor, entry.index, {
          status: "cancelled",
          error: safeFailure(
            "subscription_removed",
            "This browser no longer owns the child subscription.",
          ),
        });
        continue;
      }
      if (task.status === "completed") {
        await this.finishCache(id, visitor, entry);
        continue;
      }
      if (task.status === "failed" && task.message === INTERRUPTED_MESSAGE) {
        // The original worker may have durably saved its full cache before its
        // receipt's final state reached disk. Recover that exact result only.
        await this.finishCache(id, visitor, entry);
        continue;
      }
      if (["failed", "timeout", "cancelled", "no_layout"].includes(task.status)) {
        await this.setCase(id, visitor, entry.index, {
          status: task.status === "cancelled" ? "cancelled" : "failed",
          error: safeFailure("child_" + task.status, task.message || task.status),
        });
        continue;
      }
      if (entry.status !== task.status)
        await this.setCase(id, visitor, entry.index, { status: task.status });
      return;
    }
  }
  async cancelChild(id, visitor, entry) {
    let job;
    try {
      job = await this.scheduler.cancel(entry.receipt_id, visitor, "design-evaluation");
    } catch (error) {
      if (error.status !== 404) throw error;
      await this.setCase(
        id,
        visitor,
        entry.index,
        {
          status: "cancelled",
          error: safeFailure(
            "subscription_removed",
            "This browser no longer owns the child subscription.",
          ),
        },
        true,
      );
      return;
    }
    if (job.status === "completed") await this.finishCache(id, visitor, entry);
    else if (["failed", "timeout", "no_layout"].includes(job.status))
      await this.setCase(
        id,
        visitor,
        entry.index,
        {
          status: "failed",
          error: safeFailure("child_" + job.status, job.message || job.status),
        },
        true,
      );
    else
      await this.setCase(
        id,
        visitor,
        entry.index,
        {
          status: job.status === "cancelling" ? "cancelling" : "cancelled",
          error: null,
        },
        true,
      );
  }
  async cancel(id, visitor) {
    await this.ready();
    if (this.closed) throw studyError("Study service is stopping.", 503);
    const before = await this.store.load(id, visitor.id);
    if (["completed", "completed_with_failures", "cancelled"].includes(before.status)) {
      this.recovery.delete(id);
      this.blocked.delete(id);
      return this.get(id, visitor);
    }
    this.stopRequested.add(id);
    await this.store.controlUpdate(id, visitor.id, (record) => {
      if (["completed", "completed_with_failures", "cancelled"].includes(record.status)) return;
      record.cancel_requested = true;
      record.status = "cancelling";
      for (const entry of record.cases) if (entry.status === "pending") entry.status = "cancelled";
    });
    this.recovery.delete(id);
    this.blocked.delete(id);
    const record = await this.store.load(id, visitor.id);
    try {
      for (const entry of record.cases)
        if (entry.receipt_id && !terminalCase(entry.status))
          await this.cancelChild(id, visitor, entry);
    } catch (error) {
      if (!error.resourceSafe && error.status !== 507) throw error;
      this.active.delete(id);
      this.blocked.set(
        id,
        safeFailure(
          "resource_unavailable",
          "Cancellation is recorded. Saving an existing completed result is paused until resources are available.",
        ),
      );
      return this.get(id, visitor);
    }
    this.active.set(id, visitor);
    this.run(id, visitor);
    return this.get(id, visitor);
  }
  async body(req) {
    if (!String(req.headers["content-type"]).startsWith("application/json"))
      throw studyError("JSON is required.", 415);
    const chunks = [];
    let bytes = 0;
    for await (const chunk of req) {
      const data = Buffer.from(chunk);
      bytes += data.length;
      if (bytes > 65536) throw studyError("Study request is too large.", 413);
      chunks.push(data);
    }
    try {
      return JSON.parse(Buffer.concat(chunks, bytes).toString("utf8"));
    } catch {
      throw studyError("Invalid study JSON.");
    }
  }
  middleware(next) {
    return async (req, res, fallback) => {
      const path = req.url?.split("?")[0] ?? "/";
      if (path !== "/api/robustness-studies" && !path.startsWith("/api/robustness-studies/"))
        return next(req, res, fallback);
      const send = (status, value) => this.send(res, status, value);
      if (!this.guard(req)) return send(403, { error: "Request rejected by access policy." });
      try {
        if (req.url.includes("?")) throw studyError("Study API queries are not supported.");
        if (!["GET", "POST"].includes(req.method))
          return send(405, { error: "Unsupported study method." });
        if (
          req.method === "POST" &&
          !this.tokenMatches(req.headers["x-eeg-compute-token"], this.queue.token)
        )
          return send(403, {
            error: "Refresh the page before changing a study.",
          });
        const visitor = this.scheduler.session(req, res);
        if (req.method === "POST") this.scheduler.rate(visitor);
        if (path === "/api/robustness-studies")
          return req.method === "GET"
            ? send(200, await this.list(visitor))
            : send(201, await this.create(await this.body(req), visitor));
        const match = path.match(
          /^\/api\/robustness-studies\/([a-f0-9-]{36})(?:\/(start|resume|cancel|export))?$/,
        );
        if (!match || !validProjectId(match[1])) throw studyError("Study not found.", 404);
        const [, id, action] = match;
        await this.store.load(id, visitor.id);
        if (req.method === "GET" && !action) return send(200, await this.get(id, visitor));
        if (req.method === "GET" && action === "export")
          return send(200, await this.store.present(id, visitor.id, true));
        if (req.method === "POST" && ["start", "resume", "cancel"].includes(action)) {
          const input = await this.body(req);
          if (!input || Array.isArray(input) || Object.keys(input).length)
            throw studyError("Study control requests require an empty JSON object.");
          return send(
            200,
            action === "cancel"
              ? await this.cancel(id, visitor)
              : await this.start(id, visitor, action === "resume"),
          );
        }
        return send(405, { error: "Unsupported study operation." });
      } catch (error) {
        if (error.resourceSafe && error.retryAfter && !res.headersSent)
          res.setHeader("Retry-After", String(error.retryAfter));
        return send(error.status || 500, {
          error:
            error.studySafe || error.resourceSafe || error.projectSafe
              ? error.message
              : "Study storage or scientific input is unavailable.",
        });
      }
    };
  }
}
