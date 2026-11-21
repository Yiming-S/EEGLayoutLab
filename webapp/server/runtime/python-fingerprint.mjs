/**
 * Interpreter identity for cache keys. Keys made on macOS before this existed keep their
 * format, so it is added only on other platforms: a result computed on the Mac is never
 * reused on the Linux server, and a numpy or SciPy upgrade there yields new keys.
 */
import { execFileSync } from 'node:child_process';

const PROBE = [
  'import json, platform, sys',
  'versions = {}',
  'for name in ("numpy", "scipy"):',
  '    try:',
  '        versions[name] = __import__(name).__version__',
  '    except Exception:',
  '        versions[name] = None',
  'print(json.dumps({"python": sys.version.split()[0], "system": platform.system(), "machine": platform.machine(), **versions}, sort_keys=True))',
].join('\n');
const memo = new Map();

export function pythonFingerprint(python, run = execFileSync) {
  if (!memo.has(python)) {
    let value;
    try {
      const output = run(python, ['-I', '-c', PROBE], { encoding: 'utf8', timeout: 30000, stdio: ['ignore', 'pipe', 'ignore'] });
      value = JSON.parse(String(output).trim().split('\n').pop());
    } catch { value = { python: null }; }
    memo.set(python, value);
  }
  return memo.get(python);
}

/** The runtime part of a cache identity, or null where legacy keys must stay unchanged. */
export function runtimeIdentity(python, platform = process.platform) {
  return platform === 'darwin' ? null : pythonFingerprint(python);
}
