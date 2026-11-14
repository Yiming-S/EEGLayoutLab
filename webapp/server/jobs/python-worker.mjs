import { spawn } from 'node:child_process';
import { StringDecoder } from 'node:string_decoder';

/** Bounded NDJSON worker transport. Scientific event and result rules belong to callers. */
export function startPythonWorker({ spawnProcess = spawn, executable, args, options,
  input, timeoutMs, maxOutputBytes, killAfterMs = 2000,
  onEvent = () => {}, onLog = () => {}, onStderr = () => {},
  onError = () => {}, onStop = () => {}, onClose = () => {},
}) {
  const processGroup = process.platform !== 'win32' && spawnProcess === spawn;
  const child = spawnProcess(executable, args, { ...options, detached: processGroup, shell: false });
  const stdout = new StringDecoder('utf8'), stderr = new StringDecoder('utf8');
  let buffer = '', bytes = 0, diagnostic = '', reason = null;
  let closed = false, closeSeen = false, killTimer, groupTimer;
  const appendDiagnostic = text => {
    diagnostic = (diagnostic + text).slice(-16000);
    onStderr(diagnostic);
  };
  const reportError = error => { appendDiagnostic(error.message); onError(error); };
  const groupAlive = () => {
    const pid = child.pid;
    if (!processGroup || typeof pid !== 'number' || !Number.isInteger(pid)) return false;
    try { process.kill(-pid, 0); return true; }
    catch (error) { return error.code !== 'ESRCH'; }
  };
  const signal = value => {
    try {
      const pid = child.pid;
      if (processGroup && typeof pid === 'number' && Number.isInteger(pid)) process.kill(-pid, value);
      else child.kill(value);
    } catch (error) { if (error.code !== 'ESRCH') reportError(error); }
  };
  const stop = value => {
    if (closed || reason) return false;
    reason = value;
    onStop(value);
    signal('SIGTERM');
    killTimer = setTimeout(() => signal('SIGKILL'), killAfterMs);
    return true;
  };
  const parse = line => {
    if (!line.trim()) return;
    let event;
    try { event = JSON.parse(line); }
    catch { onLog(line.slice(0, 2000)); return; }
    if (!event || typeof event !== 'object' || Array.isArray(event)) {
      onLog(line.slice(0, 2000)); return;
    }
    onEvent(event, appendDiagnostic);
  };
  const timer = setTimeout(() => stop('timeout'), timeoutMs);
  child.stdout.on('data', chunk => {
    if (closeSeen || reason === 'output_limit') return;
    bytes += Buffer.byteLength(chunk);
    if (bytes > maxOutputBytes) { stop('output_limit'); return; }
    buffer += stdout.write(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    const lines = buffer.split('\n'); buffer = lines.pop();
    for (const line of lines) parse(line);
  });
  child.stderr.on('data', chunk => {
    if (!closeSeen) appendDiagnostic(stderr.write(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
  });
  child.on('error', reportError);
  child.stdin?.on('error', error => {
    reportError(error);
    // A failed input pipe is not evidence that the computation process has exited.
    stop('input_error');
  });
  child.once('close', (code, exitSignal) => {
    closeSeen = true;
    clearTimeout(timer);
    if (reason !== 'output_limit') parse(buffer + stdout.end());
    appendDiagnostic(stderr.end());
    const complete = () => {
      if (closed) return;
      closed = true; clearTimeout(killTimer); clearInterval(groupTimer);
      onClose(code, exitSignal);
    };
    // Native subprocesses inherit the worker's process group. Do not release the
    // computation permit while a descendant is still running after its parent exits.
    if (groupAlive()) {
      signal('SIGTERM');
      if (!killTimer) killTimer = setTimeout(() => signal('SIGKILL'), killAfterMs);
      groupTimer = setInterval(() => { if (!groupAlive()) complete(); }, 25);
    } else complete();
  });
  if (input !== undefined) {
    try { child.stdin.end(typeof input === 'string' ? input : JSON.stringify(input)); }
    catch (error) { reportError(error); stop('input_error'); }
  }
  return { child, stop, get closed() { return closed; } };
}
