const MIB = 1024 * 1024;
function megabytes(env, name, fallback, maximum) {
  const value = env[name] === undefined ? fallback : Number(env[name]);
  if (!Number.isSafeInteger(value) || value < 0 || value > maximum || (env[name] !== undefined && !/^\d+$/.test(env[name]))) throw new Error(`Invalid ${name}.`);
  return value * MIB;
}
/** Resource policies are operational settings; they never enter scientific identities. */
export function operationsConfig(env = process.env) {
  const logMaxBytes = megabytes(env, 'EEG_OPERATIONS_LOG_MB', 5, 10);
  if (logMaxBytes < MIB) throw new Error('EEG_OPERATIONS_LOG_MB must be 1 through 10.');
  return Object.freeze({
    minFreeDiskBytes: megabytes(env, 'EEG_MIN_FREE_DISK_MB', 512, 1024 * 1024),
    maxHostRssBytes: megabytes(env, 'EEG_MAX_HOST_RSS_MB', 0, 1024 * 1024),
    logMaxBytes, logRetentionDays: 7, logQueueLimit: 128,
  });
}
