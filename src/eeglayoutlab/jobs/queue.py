"""Durable workspace FIFO queue and startup receipt reconciliation (phase 2 slices 4–6).

Ports the local-workspace subset of ``webapp/server/community-queue.mjs`` together with the receipt recovery rules of
``webapp/server/operations/reconciliation.mjs`` and ``scripts/inspect_service_reconciliation.mjs``:

- One live queue owner per workspace directory (``worker.lock`` + ``acquiring.lock``); corrupt ``queue.json`` files
  are refused without overwriting a single byte.
- Single shared ``ExecutionSlot`` across all workflow adapters; FIFO dispatch; pending-key deduplication for
  ``queued`` and ``running`` receipts (never ``cancelling``); cache hits bypass a busy worker and reuse receipts
  without moving a computed receipt into the cached retention pool.
- Electrode-name sidecars (slice 5): ``design-submission/1`` envelopes create content-addressed sidecars in
  ``W/annotations/electrode-names/`` on hit or enqueue (never on lookup miss), enforce the 100-variant per-receipt
  bound without writing files, and return ``annotation_id`` + ``electrode_annotation`` when requested.
- Startup recovery reconciles ``running`` and restart-interrupted ``failed`` receipts when a verified on-disk cache
  exists, while blocking dispatch if a prior worker PID is still alive or an unconfirmed spawn marker remains.
- ``cache_only`` replaces Node's public maintenance mode: lookups and cache hits succeed, uncached submissions raise
  503, and ``tick`` reconciles active completion without starting new queued work.
"""
from __future__ import annotations

import errno
import hashlib
import inspect
import math
import os
import re
import stat
import threading
from typing import Any, Callable, Optional
import uuid

from ..schemas import jsjson
from ..server.workspace import LOCAL_OWNER, iso_now
from . import nodefs, nodepath
from .annotations import ANNOTATION_LIMITS, ElectrodeAnnotations
from .records import KEY
from .worker import ExecutionSlot

__all__ = [
    'INTERRUPTED_MESSAGE', 'RECONCILIATION_KINDS', 'RECEIPT_LIMITS', 'QueueError', 'WorkspaceQueue',
    'radius_adapter', 'receipt_catalog', 'retain_receipts', 'eligible_receipt', 'validate_queue',
    'build_reconciliation', 'read_strict_cache', 'inspect_receipt',
]

INTERRUPTED_MESSAGE = '服务重启中断了计算，可重新提交'
RECONCILIATION_KINDS = ('local-compute', 'source-reception', 'design-evaluation', 'electrode-editor')
RECEIPT_LIMITS = {'computed': 1000, 'cached': 300, 'cachedPerNetwork': 40}
_PENDING = frozenset({'queued', 'running', 'cancelling'})
_MAX_SAFE_INT = 2**53 - 1
_SHA = re.compile('[a-f0-9]{64}')
_LIMIT_BYTES = 64 * 1024 * 1024


class QueueError(Exception):
    """Queue refusal carrying an HTTP status code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _pid_alive(pid: Any) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as err:
        return err.errno != errno.ESRCH


def _plain(value: Any) -> bool:
    return isinstance(value, dict)


def _safe_int(value: Any) -> bool:
    return jsjson.is_integer(value) and abs(int(value)) <= _MAX_SAFE_INT


def _iso_valid(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', value))


def _save_atomic(path: str, value: Any) -> None:
    tmp = f'{path}.{uuid.uuid4()}.tmp'
    payload = jsjson.stringify(value).encode('utf-8')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0), 0o600)
    try:
        try:
            view = memoryview(payload)
            written = 0
            while written < len(view):
                written += os.write(fd, view[written:])
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    parent = os.path.dirname(path)
    dir_fd = os.open(parent, os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0))
    try:
        try:
            os.fsync(dir_fd)
        except OSError as err:
            if err.errno not in (errno.EINVAL, errno.ENOTSUP):
                raise
    finally:
        os.close(dir_fd)


def _call_maybe_async(fn: Callable[..., Any], *args: Any) -> Any:
    out = fn(*args)
    if inspect.isawaitable(out):
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            return asyncio.run(out)
        result_box: list[Any] = []
        err_box: list[BaseException] = []

        def runner() -> None:
            try:
                result_box.append(asyncio.run(out))
            except BaseException as exc:  # noqa: BLE001
                err_box.append(exc)

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join()
        if err_box:
            raise err_box[0]
        return result_box[0]
    return out


# --- Reconciliation & strict cache inspection --------------------------------------------------------------------

def eligible_receipt(task: dict[str, Any]) -> bool:
    status = task.get('status')
    return status == 'running' or (status == 'failed' and task.get('message') == INTERRUPTED_MESSAGE)


def validate_queue(value: Any) -> dict[str, Any]:
    if (not _plain(value) or value.get('version') != 1 or not _safe_int(value.get('sequence'))
            or int(value['sequence']) < 0 or not isinstance(value.get('tasks'), list)):
        raise ValueError('Unsupported queue state.')
    ids: set[str] = set()
    for task in value['tasks']:
        tid = task.get('id') if _plain(task) else None
        seq = task.get('sequence') if _plain(task) else None
        owners = task.get('owners') if _plain(task) else None
        if (not _plain(task) or not isinstance(tid, str) or not tid or tid in ids
                or not _safe_int(seq) or int(seq) < 1
                or (owners is not None and (not isinstance(owners, list) or not owners
                                            or any(not isinstance(o, str) or not o for o in owners)))
                or not _plain(task.get('request')) or not isinstance(task.get('status'), str)
                or not isinstance(task.get('kind'), str) or not isinstance(task.get('key'), str)):
            raise ValueError('Invalid queue receipt.')
        ids.add(tid)
    return value


def build_reconciliation(queue: dict[str, Any], observations: Any) -> dict[str, Any]:
    validate_queue(queue)
    if not isinstance(observations, list):
        raise ValueError('Invalid cache observations.')
    observed: dict[str, dict[str, Any]] = {}
    for item in observations:
        if not _plain(item) or not isinstance(item.get('id'), str) or item['id'] in observed:
            raise ValueError('Duplicate or invalid cache observation.')
        observed[item['id']] = item

    changes: list[dict[str, Any]] = []
    retained: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    for task in queue['tasks']:
        item = observed.get(task['id'])
        if not eligible_receipt(task):
            reason: Optional[str] = 'status_not_recoverable'
        elif task['kind'] not in RECONCILIATION_KINDS:
            reason = 'unsupported_kind'
        elif item is None:
            reason = 'cache_not_inspected'
        elif item.get('verdict') != 'verified':
            reason = item.get('reason') or 'cache_not_verified'
        elif (item.get('key') != task['key'] or item.get('kind') != task['kind']
              or item.get('request_sha256') != jsjson.sha256_hex(task['request'])):
            reason = 'receipt_identity_changed'
        elif (item.get('status') not in ('completed', 'no_layout')
              or (item.get('status') == 'no_layout' and task['kind'] != 'local-compute')
              or not _SHA.fullmatch(str(item.get('cache_sha256', '')))
              or not _SHA.fullmatch(str(item.get('identity_sha256', '')))
              or not _iso_valid(item.get('finished_at'))
              or not _plain(item.get('catalog'))):
            reason = 'invalid_verified_observation'
        else:
            reason = None

        if reason is not None:
            retained.append({'id': task['id'], 'status': task['status'], 'reason': reason})
            tasks.append(task)
            continue

        assert item is not None
        nxt = {
            **task,
            'status': item['status'],
            'cached': True,
            'progress': 1,
            'finished_at': item['finished_at'],
            'message': '已核对停机前保存的完整缓存',
            'catalog': {**(task.get('catalog') or {}), **item['catalog']},
        }
        for field in ('starting', 'workerPid', 'backendId'):
            nxt.pop(field, None)
        changes.append({
            'id': task['id'], 'kind': task['kind'], 'key': task['key'],
            'from': task['status'], 'to': item['status'],
            'cache_path': item.get('cache_path'),
            'cache_sha256': item['cache_sha256'],
            'identity_sha256': item['identity_sha256'],
        })
        tasks.append(nxt)

    return {'changes': changes, 'retained': retained, 'proposed_queue': {**queue, 'tasks': tasks}}


def read_strict_cache(root: str, path: str) -> tuple[bytes, dict[str, Any]]:
    """Reads a cache file strictly inside ``root`` without following symlinks or accepting hardlinks."""
    real_root = nodefs.realpath(root)
    parent = nodefs.realpath(os.path.dirname(path))
    if parent != real_root and not parent.startswith(real_root + '/'):
        raise ValueError('Cache path leaves scientific root.')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
    except OSError as err:
        if err.errno == errno.ELOOP:
            raise ValueError('Cache path cannot be a symbolic link.') from None
        raise
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > _LIMIT_BYTES:
            raise ValueError('Invalid cache file state.')
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > _LIMIT_BYTES:
                raise ValueError('Invalid cache file state.')
            chunks.append(chunk)
        after = os.fstat(fd)
        if any(getattr(before, attr) != getattr(after, attr)
               for attr in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')):
            raise ValueError('Cache file changed while reading.')
        raw = b''.join(chunks)
        parsed = jsjson.parse(raw.decode('utf-8'))
        if not _plain(parsed):
            raise ValueError('Invalid cache JSON object.')
        return raw, parsed
    finally:
        os.close(fd)


def _default_cache_file(root: str, kind: str, key: str) -> Optional[str]:
    table = {
        'local-compute': 'results/v2/local_app_jobs',
        'design-evaluation': 'results/v2/design_evaluation_jobs',
        'electrode-editor': 'results/v2/electrode_editor_jobs',
        'source-reception': 'results/v2/source_reception_v2_jobs',
    }
    directory = table.get(kind)
    if directory is None or not KEY.fullmatch(key):
        return None
    return nodepath.join(root, directory, key, 'cache.json')


def inspect_receipt(
    task: dict[str, Any],
    *,
    root: str,
    adapters: dict[str, Any],
    cache_file: Optional[Callable[[str, str], Optional[str]]] = None,
) -> dict[str, Any]:
    """Inspects one receipt against its strict on-disk cache and current adapter identity twice."""
    tid, kind, key = task.get('id'), task.get('kind'), task.get('key')
    base = {'id': tid, 'kind': kind, 'key': key}
    if not eligible_receipt(task):
        return {**base, 'verdict': 'retained', 'reason': 'status_not_recoverable'}
    adapter = adapters.get(str(kind))
    if adapter is None:
        return {**base, 'verdict': 'retained', 'reason': 'unsupported_kind'}
    locate = cache_file or (lambda knd, k: _default_cache_file(root, knd, k))
    path = locate(str(kind), str(key))
    if not path or not os.path.lexists(path):
        return {**base, 'verdict': 'retained', 'reason': 'missing_cache'}
    try:
        raw_before, stored = read_strict_cache(root, path)
        prepared_1 = _call_maybe_async(adapter['prepare'], task['request'])
        if prepared_1.get('key') != key:
            return {**base, 'verdict': 'retained', 'reason': 'current_key_mismatch'}
        identity = (prepared_1.get('ctx') or {}).get('identity')
        if identity is None:
            return {**base, 'verdict': 'retained', 'reason': 'missing_current_identity'}
        if stored.get('key') != key or stored.get('result') is None:
            return {**base, 'verdict': 'retained', 'reason': 'cache_key_mismatch'}
        if stored.get('result_sha256') != jsjson.sha256_hex(stored['result']):
            return {**base, 'verdict': 'retained', 'reason': 'result_checksum_mismatch'}
        has_stored_identity = 'identity' in stored and stored['identity'] is not None
        if has_stored_identity and jsjson.stringify(stored['identity']) != jsjson.stringify(identity):
            return {**base, 'verdict': 'retained', 'reason': 'stored_identity_mismatch'}
        looked_up = _call_maybe_async(adapter['lookup'], prepared_1)
        if not looked_up.get('hit'):
            return {**base, 'verdict': 'retained', 'reason': 'production_lookup_miss'}
        job = looked_up.get('job') or {}
        status = job.get('status')
        if status not in ('completed', 'no_layout') or (status == 'no_layout' and kind != 'local-compute'):
            return {**base, 'verdict': 'retained', 'reason': 'invalid_terminal_status'}
        prepared_2 = _call_maybe_async(adapter['prepare'], task['request'])
        raw_after, _ = read_strict_cache(root, path)
        if prepared_2.get('key') != key or raw_after != raw_before:
            return {**base, 'verdict': 'retained', 'reason': 'concurrent_change'}
        finished_at = stored.get('finished_at') or job.get('finished_at') or iso_now()
        return {
            **base,
            'verdict': 'verified',
            'status': status,
            'identity_evidence': ('stored_identity_and_original_key_definition' if has_stored_identity
                                  else 'original_key_definition_and_production_validation'),
            'request_sha256': jsjson.sha256_hex(prepared_1['request']),
            'identity_sha256': jsjson.sha256_hex(identity),
            'cache_sha256': hashlib.sha256(raw_before).hexdigest(),
            'cache_path': path,
            'finished_at': finished_at,
            'catalog': receipt_catalog(str(kind), prepared_1, job.get('result')),
        }
    except Exception as err:  # noqa: BLE001
        return {**base, 'verdict': 'retained', 'reason': str(err)}


# --- Receipt catalog & retention ---------------------------------------------------------------------------------

def receipt_catalog(kind: str, prepared: dict[str, Any], result: Any = None) -> dict[str, Any]:
    request = prepared.get('request') or {}
    ctx = prepared.get('ctx') or {}
    parent = ctx.get('record') or ctx.get('parent') if _plain(ctx) else None
    catalog: dict[str, Any] = {}
    if _plain(parent):
        catalog['parent_label'] = parent.get('label')
        catalog['region_count'] = parent.get('region_count')
        req = parent.get('request')
        catalog['mask_codes'] = req.get('mask_codes', []) if _plain(req) else []
        catalog['location_mode'] = parent.get('mode')
        layout = parent.get('layout')
        if _plain(layout) and isinstance(layout.get('xyzMm'), list):
            catalog['electrode_count'] = len(layout['xyzMm'])
    if kind == 'source-reception':
        catalog['parent_id'] = request.get('record_id')
        res_schema = result.get('schema_version') if _plain(result) else None
        catalog['protocol'] = res_schema or ('source-reception/2' if request.get('mode') else 'source-reception/1')
        res_layout = result.get('layout') if _plain(result) else None
        if _plain(res_layout) and isinstance(res_layout.get('xyzMm'), list):
            catalog['electrode_count'] = len(res_layout['xyzMm'])
        conditions = result.get('conditions') if _plain(result) else None
        if isinstance(conditions, list):
            catalog['conditions'] = [
                {
                    'condition': c.get('condition'),
                    'field_retention': c.get('field_retention'),
                    'baseline_explained_energy': (c.get('baseline') or {}).get('explained_energy'),
                    'candidate_explained_energy': (c.get('candidate') or {}).get('explained_energy'),
                }
                for c in conditions if _plain(c)
            ]
    if kind == 'electrode-editor':
        catalog['parent_id'] = request.get('parent_id')
        res_schema = result.get('schema') if _plain(result) else None
        catalog['protocol'] = res_schema or 'electrode-editor/1'
        if request.get('action') == 'evaluate' and isinstance(request.get('slots'), list):
            catalog['electrode_count'] = sum(1 for slot in request['slots'] if _plain(slot) and slot.get('enabled'))
    return catalog


def retain_receipts(tasks: list[dict[str, Any]], limits: dict[str, int] = RECEIPT_LIMITS) -> list[dict[str, Any]]:
    terminal = [t for t in tasks if t.get('status') not in _PENDING and not t.get('workerPid') and not t.get('starting')]
    computed_limit = limits.get('computed', 1000)
    cached_limit = limits.get('cached', 300)
    per_net_limit = limits.get('cachedPerNetwork', 40)
    computed = [t for t in terminal if not t.get('cached')]
    keep_ids = {id(t) for t in (computed[-computed_limit:] if computed_limit > 0 else [])}
    per_network: dict[str, int] = {}
    cached_kept = 0
    for t in reversed([t for t in terminal if t.get('cached')]):
        if cached_kept >= cached_limit:
            break
        nets = t.get('networks')
        net = nets[0] if isinstance(nets, list) and nets else ''
        count = per_network.get(net, 0)
        if count >= per_net_limit:
            continue
        per_network[net] = count + 1
        keep_ids.add(id(t))
        cached_kept += 1
    return [t for t in tasks
            if t.get('status') in _PENDING or t.get('workerPid') or t.get('starting') or id(t) in keep_ids]


def _task_view(task: dict[str, Any]) -> dict[str, Any]:
    cached = bool(task.get('cached'))
    return {
        'id': task['id'],
        'key': task['key'],
        'kind': task['kind'],
        'request': task['request'],
        'status': task['status'],
        'stage': task['status'],
        'created_at': task['created_at'],
        'finished_at': task.get('finished_at'),
        'cached': cached,
        'source': 'local_cache' if cached else 'local_compute',
        'catalog': task.get('catalog'),
    }


def radius_adapter(service: Any) -> dict[str, Callable[..., Any]]:
    """Adapter binding ``RadiusService`` into ``WorkspaceQueue``."""
    def prepare(raw: Any) -> dict[str, Any]:
        request = service.normalize_request(raw) if hasattr(service, 'normalize_request') else normalize_radius(raw)
        identity, key = service.identity_for(request)
        return {'request': request, 'key': key, 'ctx': {'identity': identity, 'key': key}}

    def normalize_radius(raw: Any) -> dict[str, Any]:
        from ..schemas.radius_search import normalize_request
        return normalize_request(raw)

    return {
        'prepare': prepare,
        'lookup': lambda p: service.lookup(p['request'], (p['ctx']['identity'], p['key'])),
        'start': lambda r: service.submit(r),
        'get': lambda job_id: service.get(job_id),
        'busy': lambda: bool(service.busy),
        'pid': lambda: service.pid(),
        'cancel': lambda job_id: service.cancel(job_id),
    }


# --- WorkspaceQueue ----------------------------------------------------------------------------------------------

class WorkspaceQueue:
    """Single-workspace durable FIFO scheduler (phase 2 slices 4–6)."""

    def __init__(
        self,
        directory: str,
        adapters: dict[str, dict[str, Callable[..., Any]]],
        *,
        root: Optional[str] = None,
        owner: str = LOCAL_OWNER,
        annotations: Optional[ElectrodeAnnotations] = None,
        execution_slot: Optional[ExecutionSlot] = None,
        cache_only: bool = False,
        max_queued: int = 50,
        poll_ms: Optional[float] = 250,
        receipt_limits: Optional[dict[str, int]] = None,
        before_new_work: Optional[Callable[[], Any]] = None,
        now_fn: Optional[Callable[[], str]] = None,
    ):
        self.directory = directory
        self.root = root
        self.owner = owner
        self.annotations = annotations
        self.adapters = adapters
        self.execution_slot = execution_slot
        self.cache_only = bool(cache_only)
        self.max_queued = max_queued
        self.receipt_limits = {**RECEIPT_LIMITS, **(receipt_limits or {})}
        self.before_new_work = before_new_work or (lambda: None)
        self._now_iso = now_fn or iso_now

        self._serial = threading.RLock()
        self.tasks: list[dict[str, Any]] = []
        self.sequence = 0
        self.disposed = False
        self.stopping = False
        self.failure: Optional[str] = None
        self.persist_failed = False
        self.active_id: Optional[str] = None
        self.launching: Optional[str] = None
        self.blocked_pids: list[int] = []
        self.unconfirmed_worker = False

        os.makedirs(directory, mode=0o700, exist_ok=True)
        self.lock_path = os.path.join(directory, 'worker.lock')
        self.lock_token = str(uuid.uuid4())
        guard_path = os.path.join(directory, 'acquiring.lock')
        try:
            guard_fd = os.open(guard_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError as err:
            raise RuntimeError('Queue lock acquisition is already in progress.') from err
        try:
            os.write(guard_fd, str(os.getpid()).encode('ascii'))
            if os.path.exists(self.lock_path):
                try:
                    with open(self.lock_path, 'rb') as handle:
                        lock_data = jsjson.parse(jsjson.decode_body(handle.read()))
                except Exception as err:
                    raise RuntimeError('Invalid worker.lock; inspect the queue directory.') from err
                pid = lock_data.get('pid') if _plain(lock_data) else None
                if not jsjson.is_integer(pid) or _pid_alive(int(pid)):
                    raise RuntimeError('The computation queue is already owned by another server.')
                os.unlink(self.lock_path)
            lock_fd = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                os.write(lock_fd, jsjson.stringify({'pid': os.getpid(), 'token': self.lock_token}).encode('utf-8'))
                os.fsync(lock_fd)
            finally:
                os.close(lock_fd)
        finally:
            os.close(guard_fd)
            try:
                os.unlink(guard_path)
            except FileNotFoundError:
                pass

        try:
            queue_path = os.path.join(directory, 'queue.json')
            if os.path.exists(queue_path):
                with open(queue_path, 'rb') as handle:
                    raw_bytes = handle.read()
                try:
                    data = jsjson.parse(raw_bytes.decode('utf-8'))
                except Exception as err:
                    raise ValueError('Unsupported queue state; preserve the file for recovery.') from err
            else:
                data = {'version': 1, 'sequence': 0, 'tasks': []}
            if (not _plain(data) or data.get('version') != 1 or not isinstance(data.get('tasks'), list)
                    or not _safe_int(data.get('sequence', 0)) or int(data.get('sequence', 0)) < 0
                    or (data.get('maintenance') is not None and not isinstance(data.get('maintenance'), bool))):
                raise ValueError('Unsupported queue state; preserve the file for recovery.')
            self.tasks = list(data['tasks'])
            self.sequence = int(data.get('sequence', 0))
            for task in self.tasks:
                if not _plain(task):
                    raise ValueError('Unsupported queue state; preserve the file for recovery.')
                pid = task.get('workerPid')
                if pid is not None and _pid_alive(int(pid) if jsjson.is_integer(pid) else -1):
                    self.blocked_pids.append(int(pid))
                if task.get('starting') and not pid:
                    self.unconfirmed_worker = True
            if not self.blocked_pids and not self.unconfirmed_worker and self.root:
                observations = [
                    inspect_receipt(task, root=self.root, adapters=self.adapters)
                    for task in self.tasks if eligible_receipt(task)
                ]
                if observations:
                    repaired = build_reconciliation(
                        {'version': 1, 'sequence': int(max(self.sequence, len(self.tasks))),
                         'tasks': [
                             {**t, 'owners': t.get('owners') or [self.owner]}
                             for t in self.tasks
                         ]},
                        observations,
                    )
                    self.tasks = repaired['proposed_queue']['tasks']
            for task in self.tasks:
                if task.get('status') in ('running', 'cancelling'):
                    task['status'] = 'failed'
                    task['message'] = INTERRUPTED_MESSAGE
                    task['finished_at'] = self._now_iso()
            self._persist()
        except BaseException:
            self._release_lock()
            raise

        self._stop_event = threading.Event()
        self._timer_thread: Optional[threading.Thread] = None
        if poll_ms is not None and poll_ms < 600000:
            interval = max(0.02, poll_ms / 1000.0)

            def loop() -> None:
                while not self._stop_event.wait(interval):
                    try:
                        self.tick()
                    except Exception as err:  # noqa: BLE001
                        self._fail_closed(err)

            self._timer_thread = threading.Thread(target=loop, name='workspace-queue', daemon=True)
            self._timer_thread.start()

    def _fail_closed(self, err: BaseException) -> None:
        self.failure = str(err)

    def _persist(self) -> None:
        self.tasks = retain_receipts(self.tasks, self.receipt_limits)
        try:
            _save_atomic(os.path.join(self.directory, 'queue.json'), {
                'version': 1,
                'sequence': self.sequence,
                'tasks': self.tasks,
            })
        except BaseException as err:
            self.persist_failed = True
            self._fail_closed(err)
            raise

    def recover_persistence(self) -> bool:
        if not self.persist_failed or self.disposed or self.stopping:
            return False
        try:
            _save_atomic(os.path.join(self.directory, 'queue.json'), {
                'version': 1,
                'sequence': self.sequence,
                'tasks': self.tasks,
            })
        except BaseException:  # noqa: BLE001
            return False
        self.persist_failed = False
        self.failure = None
        return True

    def _guarded(self) -> bool:
        return (self.unconfirmed_worker
                or any(_pid_alive(pid) for pid in self.blocked_pids)
                or any(bool(t.get('starting')) or _pid_alive(t.get('workerPid')) for t in self.tasks))

    def drained(self) -> bool:
        return bool(
            self.cache_only
            and not self.disposed
            and not self.failure
            and self.active_id is None
            and not self._guarded()
            and not (self.execution_slot and self.execution_slot.busy)
            and not any(a['busy']() for a in self.adapters.values())
        )

    def _receipt(self, kind: str, prepared: dict[str, Any], status: str) -> dict[str, Any]:
        if status in ('completed', 'no_layout'):
            same = next(
                (t for t in self.tasks
                 if t.get('kind') == kind and t.get('key') == prepared['key'] and t.get('status') == status),
                None,
            )
            if same is not None:
                return same
        self.sequence += 1
        task: dict[str, Any] = {
            'id': str(uuid.uuid4()),
            'sequence': self.sequence,
            'kind': kind,
            'key': prepared['key'],
            'request': prepared['request'],
            'owners': [self.owner],
            'status': status,
            'created_at': self._now_iso(),
            'progress': 0,
            'cached': False,
            'catalog': receipt_catalog(kind, prepared),
        }
        self.tasks.append(task)
        return task

    @staticmethod
    def _task_annotation_ids(task: Optional[dict[str, Any]]) -> list[str]:
        if not _plain(task):
            return []
        refs = task.get('annotation_refs')
        if not _plain(refs):
            return []
        out: list[str] = []
        for ids in refs.values():
            if isinstance(ids, list):
                for item in ids:
                    if isinstance(item, str) and item not in out:
                        out.append(item)
        return out

    @staticmethod
    def _latest_annotation_id(task: dict[str, Any], owner: str) -> Optional[str]:
        refs = task.get('annotation_refs')
        if not _plain(refs):
            return None
        own_ids = refs.get(owner)
        if isinstance(own_ids, list) and own_ids and isinstance(own_ids[-1], str):
            return own_ids[-1]
        for ids in refs.values():
            if isinstance(ids, list) and ids and isinstance(ids[-1], str):
                return ids[-1]
        return None

    def _annotation_for(
        self,
        prepared: dict[str, Any],
        task: Optional[dict[str, Any]],
        *,
        admitted: bool = False,
    ) -> Optional[dict[str, Any]]:
        if not prepared.get('electrode_names'):
            return None
        if self.annotations is None:
            raise QueueError('Electrode name storage is unavailable.', 503)
        ann_id = self.annotations.identity(prepared, self.owner)['id']
        existing_ids = self._task_annotation_ids(task)
        if ann_id in existing_ids:
            return self.annotations.read(ann_id, prepared['key'])
        total_refs = sum(
            len(ids) for ids in ((task or {}).get('annotation_refs') or {}).values()
            if isinstance(ids, list)
        )
        if total_refs >= ANNOTATION_LIMITS['referencesPerTask']:
            raise QueueError('This task already has 100 electrode name variants.', 413)
        if not admitted:
            _call_maybe_async(self.before_new_work)
            if self.disposed or self.stopping or self.failure:
                raise QueueError('计算队列不可用，请稍后重试', 503)
        return self.annotations.create(prepared, self.owner)

    def _attach_annotation(self, task: dict[str, Any], annotation: Optional[dict[str, Any]]) -> None:
        if annotation is None:
            return
        refs = task.setdefault('annotation_refs', {})
        prev = refs.get(self.owner)
        prev_list = [aid for aid in prev if aid != annotation['id']] if isinstance(prev, list) else []
        refs[self.owner] = [*prev_list, annotation['id']]

    def _annotation_view(self, task: dict[str, Any], selected_id: Optional[str]) -> dict[str, Any]:
        if selected_id is None:
            return {}
        if selected_id not in self._task_annotation_ids(task) or self.annotations is None:
            raise QueueError('Electrode name annotation not found.', 404)
        return {
            'annotation_id': selected_id,
            'electrode_annotation': self.annotations.read(selected_id, task['key']),
        }

    def submit(self, kind: str, raw: Any, *, lookup_only: bool = False) -> dict[str, Any]:
        with self._serial:
            if self.disposed or self.stopping or self.failure:
                raise QueueError('计算队列不可用，请稍后重试', 503)
            adapter = self.adapters.get(kind)
            if adapter is None:
                raise QueueError('Unknown queue endpoint', 404)
            prepared = _call_maybe_async(adapter['prepare'], raw)
            if self.disposed or self.stopping or self.failure:
                raise QueueError('计算队列不可用，请稍后重试', 503)
            ready = _call_maybe_async(adapter['lookup'], prepared)
            if self.disposed or self.stopping or self.failure:
                raise QueueError('计算队列不可用，请稍后重试', 503)
            if ready.get('hit'):
                status = ready['job']['status']
                previous = next(
                    (t for t in self.tasks
                     if t.get('kind') == kind and t.get('key') == prepared['key'] and t.get('status') == status),
                    None,
                )
                annotation = self._annotation_for(prepared, previous, admitted=False)
                if self.disposed or self.stopping or self.failure:
                    raise QueueError('计算队列不可用，请稍后重试', 503)
                before_len = len(self.tasks)
                task = self._receipt(kind, prepared, status)
                self._attach_annotation(task, annotation)
                created = len(self.tasks) != before_len
                if created:
                    task['cached'] = True
                    task['finished_at'] = ready['job'].get('finished_at') or self._now_iso()
                    task['catalog'] = receipt_catalog(kind, prepared, ready['job'].get('result'))
                if created or annotation is not None:
                    self._persist()
                ann_fields = self._annotation_view(task, annotation['id'] if annotation is not None else None)
                return {
                    'hit': True,
                    'job': {
                        **ready['job'],
                        **_task_view(task),
                        'cached': True,
                        'source': 'local_cache',
                        **ann_fields,
                    },
                }

            existing = next(
                (t for t in self.tasks
                 if t.get('kind') == kind and t.get('key') == prepared['key']
                 and t.get('status') in ('queued', 'running')),
                None,
            )
            if existing is not None:
                annotation = self._annotation_for(prepared, existing, admitted=False)
                if self.disposed or self.stopping or self.failure:
                    raise QueueError('计算队列不可用，请稍后重试', 503)
                self._attach_annotation(existing, annotation)
                if annotation is not None:
                    self._persist()
                return {
                    'hit': True,
                    'job': self.view(
                        existing,
                        include_result=True,
                        annotation_id=annotation['id'] if annotation is not None else None,
                    ),
                }

            if lookup_only:
                return {'hit': False}
            if self.cache_only:
                raise QueueError('服务维护中，已有结果仍可读取；请稍后提交新计算', 503)
            pending_count = sum(1 for t in self.tasks if t.get('status') in _PENDING)
            if pending_count >= self.max_queued:
                raise QueueError('队列已满，请稍后提交；已有结果仍可读取', 429)
            _call_maybe_async(self.before_new_work)
            if self.disposed or self.stopping or self.failure:
                raise QueueError('计算队列不可用，请稍后重试', 503)
            if self.cache_only:
                raise QueueError('服务维护中，已有结果仍可读取；请稍后提交新计算', 503)
            annotation = self._annotation_for(prepared, None, admitted=True)
            if self.disposed or self.stopping or self.failure:
                raise QueueError('计算队列不可用，请稍后重试', 503)
            if self.cache_only:
                raise QueueError('服务维护中，已有结果仍可读取；请稍后提交新计算', 503)
            task = self._receipt(kind, prepared, 'queued')
            self._attach_annotation(task, annotation)
            self._persist()
            return {
                'job': self.view(
                    task,
                    include_result=True,
                    annotation_id=annotation['id'] if annotation is not None else None,
                ),
            }

    def get_task(self, task_id: str, kind: Optional[str] = None) -> dict[str, Any]:
        with self._serial:
            task = next(
                (t for t in self.tasks if t.get('id') == task_id and (kind is None or t.get('kind') == kind)),
                None,
            )
            if task is None:
                raise QueueError('任务不存在或不属于当前浏览器', 404)
            return task

    def view(
        self,
        task: dict[str, Any],
        *,
        include_result: bool = True,
        annotation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        adapter = self.adapters[task['kind']]
        worker = adapter['get'](task['backendId']) if task.get('backendId') else None
        value: dict[str, Any] = worker or {}
        if not worker and include_result and task.get('status') in ('completed', 'no_layout'):
            prepared = _call_maybe_async(adapter['prepare'], task['request'])
            if prepared.get('key') != task.get('key'):
                return {**_task_view(task), 'status': 'failed', 'message': '模型或代码已更新，请重新提交', 'result': None}
            cached = _call_maybe_async(adapter['lookup'], prepared)
            if not cached.get('hit'):
                return {**_task_view(task), 'status': 'failed', 'message': '计算记录无法读取，请重新提交', 'result': None}
            value = cached['job']
        position = (
            sum(1 for t in self.tasks if t.get('status') == 'queued' and int(t['sequence']) <= int(task['sequence']))
            if task.get('status') == 'queued'
            else 0
        )
        progress = value.get('progress', task.get('progress', 0))
        is_cached = bool(task.get('cached') or value.get('cached'))
        combined: dict[str, Any] = {
            **value,
            **_task_view(task),
            'progress': progress,
            'cached': is_cached,
            'source': 'local_cache' if is_cached else 'local_compute',
            'queue_position': position,
        }
        combined['message'] = (
            '已加入计算队列' if task.get('status') == 'queued'
            else task.get('message') or value.get('message') or task['status']
        )
        if include_result:
            combined['result'] = value.get('result') if task.get('status') in ('completed', 'no_layout') else None
        else:
            combined.pop('result', None)
        return {**combined, **self._annotation_view(task, annotation_id)}

    def cancel(self, task_id: str, kind: Optional[str] = None) -> dict[str, Any]:
        with self._serial:
            task = self.get_task(task_id, kind)
            if task.get('status') not in _PENDING:
                return self.view(task, include_result=True)
            if task['status'] == 'queued':
                task['status'] = 'cancelled'
                task['finished_at'] = self._now_iso()
            else:
                if task.get('backendId'):
                    self.adapters[task['kind']]['cancel'](task['backendId'])
                task['status'] = 'cancelling'
            self._persist()
            return self.view(task, include_result=True)

    def tick(self) -> None:
        with self._serial:
            if self.failure and not self.recover_persistence():
                return
            if self.disposed or self.stopping or self.failure:
                return
            self.blocked_pids = [pid for pid in self.blocked_pids if _pid_alive(pid)]
            if self.blocked_pids or self.unconfirmed_worker:
                return
            if self.active_id is not None:
                active_task = next((t for t in self.tasks if t.get('id') == self.active_id), None)
                if active_task is not None:
                    adapter = self.adapters[active_task['kind']]
                    if adapter['busy']():
                        return
                    worker = adapter['get'](active_task.get('backendId')) if active_task.get('backendId') else None
                    active_task['status'] = (worker or {}).get('status') or 'failed'
                    active_task['message'] = (worker or {}).get('message') or '计算进程未返回结果'
                    active_task['finished_at'] = self._now_iso()
                    raw_prog = (worker or {}).get('progress', 0)
                    active_task['progress'] = raw_prog if jsjson.is_number(raw_prog) and math.isfinite(float(raw_prog)) else 0
                    if worker and worker.get('result') is not None:
                        active_task['catalog'] = {
                            **(active_task.get('catalog') or {}),
                            **receipt_catalog(active_task['kind'], {'request': active_task['request']}, worker['result']),
                        }
                    active_task['cached'] = bool((worker or {}).get('cached'))
                    active_task.pop('workerPid', None)
                    active_task.pop('starting', None)
                self.active_id = None
                self._persist()

            if (self.cache_only
                    or (self.execution_slot and self.execution_slot.busy)
                    or any(a['busy']() for a in self.adapters.values())):
                return
            nxt = next((t for t in self.tasks if t.get('status') == 'queued'), None)
            if nxt is None:
                return
            adapter = self.adapters[nxt['kind']]
        # Allow prepare/start callbacks to yield if tests coordinate concurrent slot/shutdown hooks.
        try:
            prepared = _call_maybe_async(adapter['prepare'], nxt['request'])
            with self._serial:
                if (self.disposed or self.stopping or self.failure or self.cache_only
                        or (self.execution_slot and self.execution_slot.busy)
                        or any(a['busy']() for a in self.adapters.values())):
                    return
                if prepared.get('key') != nxt.get('key'):
                    raise RuntimeError('排队后模型或代码已更新，请重新提交')
            _call_maybe_async(self.before_new_work)
            with self._serial:
                if (self.disposed or self.stopping or self.failure or self.cache_only
                        or (self.execution_slot and self.execution_slot.busy)
                        or any(a['busy']() for a in self.adapters.values())):
                    return
                nxt['status'] = 'running'
                nxt['starting'] = True
                self.active_id = nxt['id']
                self.launching = nxt['id']
                self._persist()
            try:
                started = _call_maybe_async(adapter['start'], nxt['request'])
            finally:
                with self._serial:
                    self.launching = None
            with self._serial:
                if self.disposed:
                    return
                if started.get('busy'):
                    nxt['status'] = 'queued'
                    nxt.pop('starting', None)
                    nxt.pop('workerPid', None)
                    nxt.pop('backendId', None)
                    self.active_id = None
                    self._persist()
                    return
                job = started.get('job')
                if not job:
                    raise RuntimeError('计算资源被其他进程占用，请重新提交')
                nxt['backendId'] = job['id']
                pid = adapter['pid']()
                if pid is not None:
                    nxt['workerPid'] = pid
                nxt['starting'] = False
                self._persist()
                if job.get('key') != nxt.get('key'):
                    adapter['cancel'](nxt['backendId'])
                    raise RuntimeError('排队后模型或代码已更新，请重新提交')
        except Exception as err:  # noqa: BLE001
            with self._serial:
                if self.disposed or self.stopping:
                    return
                if nxt.get('starting') and not nxt.get('workerPid') and not nxt.get('backendId'):
                    self.unconfirmed_worker = True
                nxt['status'] = 'failed'
                nxt['message'] = str(err)
                nxt['finished_at'] = self._now_iso()
                self.active_id = None
                self._persist()

    def _safe_task_summary(self, task: dict[str, Any]) -> dict[str, Any]:
        latest_ann = self._latest_annotation_id(task, self.owner)
        try:
            return self.view(task, include_result=False, annotation_id=latest_ann)
        except Exception:  # noqa: BLE001
            return self.view(task, include_result=False)

    def stats(self) -> dict[str, Any]:
        with self._serial:
            recent = list(reversed(self.tasks[-12:]))
            jobs = [self._safe_task_summary(t) for t in recent]
            return {
                'queued_tasks': sum(1 for t in self.tasks if t.get('status') == 'queued'),
                'running_tasks': int(bool(self.active_id is not None or self.blocked_pids)),
                'available': not self.failure and not self.disposed and not self.stopping,
                'resource_blocked': False,
                'recovery_blocked': bool(self.blocked_pids) or bool(self.unconfirmed_worker),
                'maintenance': self.cache_only,
                'drained': self.drained(),
                'jobs': jobs,
            }

    def records(self) -> dict[str, Any]:
        with self._serial:
            newest: dict[str, dict[str, Any]] = {}
            for task in self.tasks:
                if task.get('kind') != 'source-reception' or task.get('status') != 'completed':
                    continue
                prev = newest.get(task['key'])
                if prev is None or int(task['sequence']) > int(prev['sequence']):
                    newest[task['key']] = task
            ordered = sorted(newest.values(), key=lambda t: int(t['sequence']), reverse=True)
            return {
                'schema': 'browser-experiment-records/1',
                'scope': 'current_browser',
                'receipt_limit': self.receipt_limits['computed'],
                'records': [_task_view(t) for t in ordered],
            }

    def active(self, kind: str) -> Optional[dict[str, Any]]:
        with self._serial:
            task = next((t for t in self.tasks if t.get('kind') == kind and t.get('status') in _PENDING), None)
            return self._safe_task_summary(task) if task is not None else None

    def _release_lock(self) -> None:
        if os.path.exists(self.lock_path):
            try:
                with open(self.lock_path, 'rb') as handle:
                    data = jsjson.parse(jsjson.decode_body(handle.read()))
                if _plain(data) and data.get('token') == self.lock_token:
                    os.unlink(self.lock_path)
            except OSError:
                pass

    def stop_scheduling(self) -> None:
        self.stopping = True
        self._stop_event.set()

    def dispose(self) -> None:
        with self._serial:
            if self.disposed:
                return
            self.stop_scheduling()
            self.disposed = True
            if self.launching is not None:
                launching_task = next(
                    (t for t in self.tasks
                     if t.get('id') == self.launching and t.get('starting') and not t.get('workerPid')),
                    None,
                )
                if launching_task is not None:
                    launching_task['status'] = 'queued'
                    launching_task.pop('starting', None)
                    launching_task.pop('backendId', None)
                    if self.active_id == launching_task['id']:
                        self.active_id = None
            try:
                self._persist()
            except OSError:
                pass
            self._release_lock()
