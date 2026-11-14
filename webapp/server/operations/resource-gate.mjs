import { statfs as diskStat } from 'node:fs/promises';
import { operationsConfig } from './config.mjs';

const safeBytes = value => {
  const bytes = BigInt(value);
  if (bytes < 0n) throw new Error('Invalid resource observation.');
  return Number(bytes > BigInt(Number.MAX_SAFE_INTEGER) ? BigInt(Number.MAX_SAFE_INTEGER) : bytes);
};
const actionFor = code => code === 'low_disk'
  ? 'Free disk space or apply the approved retention policy before accepting new work.'
  : code === 'host_memory_limit'
    ? 'Inspect host memory use and finish or stop active work before accepting new work.'
    : 'Check the resource probe and filesystem access before accepting new work.';
export class ResourceGate {
  constructor({ directories, config = operationsConfig(), statfs = diskStat, memoryUsage = process.memoryUsage, now = () => new Date().toISOString(), sampleTimeoutMs = 2000 }) {
    if (!Array.isArray(directories) || directories.length < 1 || directories.length > 2 || directories.some(entry => !['queue', 'scientific'].includes(entry.scope) || typeof entry.path !== 'string')) throw new Error('Explicit scientific and queue directories are required.');
    this.directories = directories; this.config = config; this.statfs = statfs; this.memoryUsage = memoryUsage; this.now = now;
    if (!Number.isSafeInteger(sampleTimeoutMs) || sampleTimeoutMs < 1 || sampleTimeoutMs > 60000) throw new Error('Invalid resource probe timeout.');
    this.sampleTimeoutMs = sampleTimeoutMs; this.diskChecks = new Map(); this.lastSample = null;
  }
  async observeDisk(path) {
    let pending = this.diskChecks.get(path);
    if (!pending) {
      pending = Promise.resolve().then(() => this.statfs(path, { bigint: true })); this.diskChecks.set(path, pending);
      const clear = () => { if (this.diskChecks.get(path) === pending) this.diskChecks.delete(path); };
      void pending.then(clear, clear);
    }
    let timer;
    try { return await Promise.race([pending, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Resource observation timed out.')), this.sampleTimeoutMs); })]); }
    finally { clearTimeout(timer); }
  }
  async sample() {
    const alerts = [], disks = []; let host_rss_bytes = null;
    try {
      const observed = this.memoryUsage().rss;
      if (!Number.isSafeInteger(observed) || observed < 0) throw new Error('Invalid RSS.');
      host_rss_bytes = observed;
      if (this.config.maxHostRssBytes > 0 && observed > this.config.maxHostRssBytes) alerts.push({ code: 'host_memory_limit', scope: 'host', action: actionFor('host_memory_limit') });
    } catch { alerts.push({ code: 'memory_sampling_failed', scope: 'host', action: actionFor('memory_sampling_failed') }); }
    const observations = await Promise.all(this.directories.map(async entry => {
      try {
        const stats = await this.observeDisk(entry.path);
        const block = BigInt(stats.bsize), available = BigInt(stats.bavail);
        if (block <= 0n || available < 0n) throw new Error('Invalid filesystem observation.');
        const free_bytes = safeBytes(block * available);
        return { disk: { scope: entry.scope, free_bytes }, alert: free_bytes < this.config.minFreeDiskBytes ? { code: 'low_disk', scope: entry.scope, action: actionFor('low_disk') } : null };
      } catch { return { disk: { scope: entry.scope, free_bytes: null }, alert: { code: 'disk_sampling_failed', scope: entry.scope, action: actionFor('disk_sampling_failed') } }; }
    }));
    for (const observation of observations) { disks.push(observation.disk); if (observation.alert) alerts.push(observation.alert); }
    this.lastSample = { allowed: alerts.length === 0, sampled_at: this.now(), host_rss_bytes, min_free_disk_bytes: this.config.minFreeDiskBytes,
      max_host_rss_bytes: this.config.maxHostRssBytes, memory_scope: 'Node host current RSS only; scientific worker peak memory is not measured.', disks, alerts };
    return this.lastSample;
  }
  async assertAvailable() {
    const sample = await this.sample();
    if (!sample.allowed) throw Object.assign(new Error('New work is temporarily unavailable because resource checks failed. Existing results remain readable.'), { status: 503, code: 'resource_unavailable', retryAfter: 30, resourceSafe: true });
    return sample;
  }
}
