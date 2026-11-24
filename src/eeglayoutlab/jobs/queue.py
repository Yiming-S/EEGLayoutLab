"""The durable workspace queue: Node's ``CommunityQueue`` (community-queue.mjs:29-437) for one local user.

One FIFO across every job kind (``jobs.kinds``), stored in ``W/.eeglayoutlab/queue.json``::

    {"schema":"eeglayoutlab-queue/1","sequence":N,"boot_id":"<the kernel's boot id>","tasks":[...]}

A task (a receipt) has Node's members (jobs.md section 5.2) without ``owners`` and ``networks``: ``id``,
``sequence``, ``kind``, ``key``, ``request``, ``status``, ``created_at``, ``progress``, ``cached``, ``catalog`` and,
when set, ``finished_at``, ``message``, ``backend_id``, ``worker_pid``, ``starting`` and ``annotation_refs`` (a
list of annotation ids). ``boot_id`` names the boot of the machine that last wrote the file (left out when it
cannot be read). The file is written as Node writes records (``records.atomic_json``: a new temporary, fsync,
rename, fsync of the directory), so a crash leaves the previous file or the new one, never a mix.

Behaviour follows Node statement by statement, with one ``asyncio.Lock`` in place of ``serial()`` around submit,
cancel and dispatch:

- ``submit`` prepares the identity (``adapter.prepare``), reads the stored result (``adapter.lookup``, never the
  execution slot), answers a hit with one cached receipt per kind, key and status (reused, written only when new),
  joins a pending task of the same kind and key, and otherwise appends a ``queued`` receipt. A lookup never adds a
  queued task. A shutdown or a failed write during any await refuses the request (503) before anything is added.
- ``tick`` (dispatch) re-prepares the next queued task and fails it with ``排队后模型或代码已更新，请重新提交`` when
  its key changed; it persists the spawn intent (``starting``) before ``adapter.start``. A start that confirms it
  launched nothing (``busy``) puts the task back in its place; one that throws keeps the intent, which blocks
  dispatch after a restart. A permit known to be held gates dispatch before the intent, as in Node: the slot's
  ``busy`` and ``paused``, and (``ExecutionSlot.available``) the installation lock held by another workspace, which
  is probed before the task is prepared and again before the intent is written. While another workspace computes,
  the task stays queued and nothing is written; the ``busy`` answer of a start is left for a lock taken between the
  probe and the start. A lock that cannot be used fails the task at the second probe, after ``prepare`` and the
  key check, so a changed key is reported first, as Node reports it before its record store meets the same root.
  That failure comes before the intent, so its receipt does not block a restart; Node's run path refuses such a
  root inside ``adapter.start``, and its receipt keeps the intent.
- At startup running and cancelling tasks become ``failed`` with ``服务重启中断了计算，可重新提交``; queued ones
  stay queued. A worker group still alive (``worker_pid``) or a spawn intent without a pid blocks dispatch
  (``recovery_blocked``), until the group is gone, the machine has rebooted or the person clears it.
- A corrupt ``queue.json`` is never overwritten: the constructor raises ``QueueStateError`` and leaves its bytes.
- A failed write stops new work (503) until a later write succeeds.

Dropped with the public service (plan sections 0 and 5.1): owners, networks, visitors and their limits and rates,
online visitors, library claims, the resource gate and operator maintenance (``cache_only`` replaces the last: misses
are refused with Node's maintenance status and message, hits are served, nothing is dispatched). The global bound on
pending tasks stays (429). Deliberate differences:

- Finalization runs from the kind's completion callback (``adapter.on_finish``): the terminal view is kept until the
  next ``tick`` uses it, so a finished job can never be evicted from the service's bounded job map before its
  receipt is final (jobs.md section 5.6). ``start()`` runs a dispatcher that ticks on every submit, cancel and
  completion, and once a second while work waits on something no callback announces (a pid, a held permit, a write).
- Liveness covers the whole process group (``killpg(pid, 0)``), and a ``worker_pid`` whose group is gone is dropped
  from its receipt, so a reused pid cannot block a later restart.
- A spawn intent or a ``worker_pid`` from before a reboot is resolved without a probe: the ``boot_id`` of the last
  write, which came at or after every intent and pid the file holds, is not the kernel's boot id now
  (``kern.bootsessionuuid``, ``/proc/sys/kernel/random/boot_id``), so no process of that run is left, and a live
  process with the same pid is another one. A boot id changes only at a boot; the boot time, which both kernels
  derive from the wall clock, moves when the clock is set. Without both ids nothing is resolved this way.
  ``clear_interrupted`` (``eeglayoutlab serve --clear-interrupted``) resolves both as well, once the person has
  checked that no worker of an earlier run still computes: Node's operator repaired these receipts with its
  reconciliation tool.
- ``recover()`` (startup) promotes a receipt the restart interrupted to ``completed``/``no_layout`` when the kind's
  own lookup finds a valid stored result for its unchanged key, with the stored finish time (the adapter's
  ``finished_at`` where its views have none): the startup form of Node's offline reconciliation
  (operations/reconciliation.mjs, check-reconciliation.mjs).
- A submit whose write fails takes its new receipt back, so the refused request never runs later.
- Leftover temporaries of an interrupted write (``queue.json.<uuid>.tmp``) are removed at startup.
"""
from __future__ import annotations

import asyncio
import ctypes
import ctypes.util
from datetime import datetime, timedelta, timezone
import logging
import math
import os
import re
import stat
import sys
import time
from typing import Any, Callable, Optional
import uuid

from ..schemas import jsjson
from . import nodepath, records
from .annotations import ANNOTATION_LIMITS
from .identity import UNDEFINED, js_truthy
from .kinds import Adapter, resolve

__all__ = [
    'QUEUE_FILE', 'QUEUE_SCHEMA', 'STATUSES', 'PENDING', 'RECEIPT_LIMITS', 'MAX_QUEUED', 'STATS_JOBS',
    'INTERRUPTED_MESSAGE', 'QueueError', 'QueueStateError', 'WorkspaceQueue', 'retain_receipts', 'task_view',
    'receipt_catalog', 'public_message', 'boot_id', 'group_alive', 'iso',
]

QUEUE_FILE = 'queue.json'
QUEUE_SCHEMA = 'eeglayoutlab-queue/1'
# The eight statuses of webapp/client/task-client.ts:25.
STATUSES = ('queued', 'running', 'cancelling', 'completed', 'no_layout', 'failed', 'cancelled', 'timeout')
PENDING = ('queued', 'running', 'cancelling')
DONE = ('completed', 'no_layout')
TERMINAL = tuple(status for status in STATUSES if status not in PENDING)
# Node's RECEIPT_LIMITS without the per-network share of cache hits.
RECEIPT_LIMITS = {'computed': 1000, 'cached': 300}
MAX_QUEUED = 50
STATS_JOBS = 12
RETRY_SECONDS = 1.0
_OUTCOME_LIMIT = 64

# Node's messages (community-queue.mjs, operations/reconciliation.mjs, http/public-errors.mjs), verbatim.
QUEUED_MESSAGE = '已加入计算队列'
INTERRUPTED_MESSAGE = '服务重启中断了计算，可重新提交'
DISPATCH_KEY_CHANGED = '排队后模型或代码已更新，请重新提交'
VIEW_KEY_CHANGED = '模型或代码已更新，请重新提交'
VIEW_CACHE_MISSING = '计算记录无法读取，请重新提交'
NO_RESULT = '计算进程未返回结果'
START_WITHOUT_JOB = '计算资源被其他进程占用，请重新提交'
UNAVAILABLE = '计算队列不可用，请稍后重试'
NOT_FOUND = '任务不存在或不属于当前浏览器'
IDENTITY_CHANGED = 'Scientific identity changed before task acceptance.'
STUDY_ADMISSION = 'Study no longer authorizes this child submission.'
MAINTENANCE = '服务维护中，已有结果仍可读取；请稍后提交新计算'
QUEUE_FULL = '队列已满，请稍后提交；已有结果仍可读取'
UNKNOWN_ENDPOINT = 'Unknown queue endpoint'
ANNOTATIONS_UNAVAILABLE = 'Electrode name storage is unavailable.'
ANNOTATION_NOT_FOUND = 'Electrode name annotation not found.'
TASK_VARIANTS = 'This task already has 100 electrode name variants.'
NOT_JSON = '请求内容不是有效的JSON'
INTERNAL_MESSAGE = '服务器内部错误，已记录；请稍后重试'

_TEMPORARY = re.compile(re.escape(QUEUE_FILE) + r'\.[a-f0-9-]{36}\.tmp')
_SAFE_INTEGER = 2**53 - 1
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_log = logging.getLogger(__name__)


class QueueError(Exception):
    """A refused request: ``status`` and ``message`` are Node's (the routes answer with them)."""

    def __init__(self, message: str, status: int, *, admission_rejected: bool = False,
                 study_admission_cancelled: bool = False):
        super().__init__(message)
        self.message = message
        self.status = status
        self.admission_rejected = admission_rejected
        self.study_admission_cancelled = study_admission_cancelled


class QueueStateError(Exception):
    """``queue.json`` cannot be used. It is left exactly as it was; the message says what to do."""


class _Failure(Exception):
    """A dispatch failure whose message the receipt shows (Node's ``throw new Error(...)``)."""


# --- JavaScript helpers ------------------------------------------------------------------------------------------

def iso(milliseconds: float) -> str:
    """``new Date(milliseconds).toISOString()``."""
    moment = _EPOCH + timedelta(milliseconds=math.trunc(milliseconds))
    return (f'{moment.year:04d}-{moment.month:02d}-{moment.day:02d}T{moment.hour:02d}:{moment.minute:02d}:'
            f'{moment.second:02d}.{moment.microsecond // 1000:03d}Z')


def _parse_date(value: Any) -> Optional[float]:
    """Seconds since the epoch of an ISO 8601 date-time (as ``toISOString`` writes it), else ``None``."""
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T[0-9:.]+(?:Z|[+-]\d{2}:\d{2})', value):
        return None
    try:
        moment = datetime.fromisoformat(value[:-1] + '+00:00' if value.endswith('Z') else value)
    except ValueError:
        return None
    return moment.timestamp()


def _get(value: Any, key: str) -> Any:
    """``value?.[key]`` on JSON data: ``UNDEFINED`` for a missing member or a value that has none."""
    if isinstance(value, dict):
        return value.get(key, UNDEFINED)
    return UNDEFINED


def _nullish(value: Any) -> bool:
    return value is None or value is UNDEFINED


def _length(value: Any) -> Any:
    """``value.length``: an array's length, a string's UTF-16 length, else ``undefined``."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, str):
        return len(value.encode('utf-16-le')) // 2
    return UNDEFINED


def _defined(value: dict) -> dict:
    """The object as ``JSON.stringify`` writes it: members whose value is ``undefined`` are left out."""
    return {key: item for key, item in value.items() if item is not UNDEFINED}


def pending(task: dict) -> bool:
    return task.get('status') in PENDING


def group_alive(pid: Any) -> bool:
    """Node's ``alive(pid)`` (``process.kill(pid, 0)``) for the process or any member of its process group: a
    worker leads its own group, so a descendant that outlived it still counts."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    for probe in (os.kill, os.killpg):
        try:
            probe(pid, 0)
            return True
        except PermissionError:
            return True
        except OSError:
            continue
    return False


def boot_id() -> Optional[str]:
    """The kernel's identifier of this boot, which changes only at a boot: ``kern.bootsessionuuid`` on macOS,
    ``/proc/sys/kernel/random/boot_id`` on Linux; ``None`` when it cannot be read."""
    try:
        if sys.platform == 'darwin':
            libc = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True)
            value = ctypes.create_string_buffer(64)
            size = ctypes.c_size_t(ctypes.sizeof(value))
            if libc.sysctlbyname(b'kern.bootsessionuuid', value, ctypes.byref(size), None, ctypes.c_size_t(0)) != 0:
                return None
            text = value.value.decode('ascii')
        else:
            with open('/proc/sys/kernel/random/boot_id', 'rb') as handle:
                text = handle.read().decode('ascii').strip()
    except (OSError, AttributeError, UnicodeDecodeError):
        return None
    return text or None


def internal_fault(error: BaseException) -> bool:
    """``internalFault``: a system error or a programming error, rather than a refused request. The services'
    refusals (``jobs.radius.RadiusJobError``, Node's plain ``Error``: the editor's parent checks at dispatch among
    them) are refused requests, as in ``routes.compute``."""
    code = getattr(error, 'code', None)
    if isinstance(code, str) and re.fullmatch('E[A-Z]+', code):
        return True
    # Not imported: the radius search needs Pydantic and the queue does not; its errors exist once it is loaded.
    radius = sys.modules.get(f'{__package__}.radius')
    if radius is not None and isinstance(error, radius.RadiusJobError):
        return False
    return isinstance(error, (OSError, TypeError, NameError, AttributeError, LookupError, ArithmeticError,
                              AssertionError, RuntimeError))


def public_message(error: BaseException) -> str:
    """``publicMessage(error)``: the text a receipt shows for a failure (without ``redactPaths``, R2)."""
    message = getattr(error, 'message', None)
    if not isinstance(message, str):
        message = str(error)
    status = getattr(error, 'status', None)
    if isinstance(status, int) and not isinstance(status, bool) and 400 <= status < 600:
        return message
    if isinstance(error, jsjson.JSONSyntaxError):
        return NOT_JSON
    if internal_fault(error):
        _log.error('internal error', exc_info=error)
        return INTERNAL_MESSAGE
    return message


# --- Receipts ----------------------------------------------------------------------------------------------------

def task_view(task: dict) -> dict:
    """``taskView(t)``."""
    cached = task.get('cached')
    finished = task.get('finished_at')
    catalog = task.get('catalog')
    return {'id': task['id'], 'key': task['key'], 'kind': task['kind'], 'request': task['request'],
            'status': task['status'], 'stage': task['status'], 'created_at': task['created_at'],
            'finished_at': None if finished is None else finished, 'cached': cached,
            'source': 'local_cache' if js_truthy(cached) else 'local_compute',
            'catalog': None if catalog is None else catalog}


def receipt_catalog(kind: str, prepared: Any, result: Any = UNDEFINED) -> dict:
    """``receiptCatalog(kind, prepared, result)``: the small, bounded metadata a receipt keeps for lists."""
    request = _get(prepared, 'request')
    ctx = _get(prepared, 'ctx')
    parent = _get(ctx, 'record')
    if _nullish(parent):
        parent = _get(ctx, 'parent')
    catalog: dict[str, Any] = {}
    if js_truthy(parent):
        catalog['parent_label'] = _get(parent, 'label')
        catalog['region_count'] = _get(parent, 'region_count')
        masks = _get(_get(parent, 'request'), 'mask_codes')
        catalog['mask_codes'] = [] if _nullish(masks) else masks
        catalog['location_mode'] = _get(parent, 'mode')
        xyz = _get(_get(parent, 'layout'), 'xyzMm')
        if js_truthy(xyz):
            catalog['electrode_count'] = _length(xyz)
    if kind == 'source-reception':
        catalog['parent_id'] = _get(request, 'record_id')
        schema = _get(result, 'schema_version')
        catalog['protocol'] = (schema if not _nullish(schema) else
                               'source-reception/2' if js_truthy(_get(request, 'mode')) else 'source-reception/1')
        xyz = _get(_get(result, 'layout'), 'xyzMm')
        if js_truthy(xyz):
            catalog['electrode_count'] = _length(xyz)
        conditions = _get(result, 'conditions')
        if js_truthy(conditions):
            if not isinstance(conditions, list):
                raise TypeError('result.conditions.map is not a function')
            rows = []
            for item in conditions:
                if _nullish(item):
                    raise TypeError('Cannot destructure a condition of null or undefined')
                baseline, candidate = _get(item, 'baseline'), _get(item, 'candidate')
                if _nullish(baseline) or _nullish(candidate):
                    raise TypeError("Cannot read properties of undefined (reading 'explained_energy')")
                rows.append(_defined({'condition': _get(item, 'condition'),
                                      'field_retention': _get(item, 'field_retention'),
                                      'baseline_explained_energy': _get(baseline, 'explained_energy'),
                                      'candidate_explained_energy': _get(candidate, 'explained_energy')}))
            catalog['conditions'] = rows
    if kind == 'electrode-editor':
        catalog['parent_id'] = _get(request, 'parent_id')
        schema = _get(result, 'schema')
        catalog['protocol'] = schema if not _nullish(schema) else 'electrode-editor/1'
        if _get(request, 'action') == 'evaluate':
            slots = _get(request, 'slots')
            if not isinstance(slots, list):
                raise TypeError('request.slots.filter is not a function')
            catalog['electrode_count'] = sum(1 for slot in slots if js_truthy(_get(slot, 'enabled')))
    return _defined(catalog)


def retain_receipts(tasks: list[dict], limits: dict) -> list[dict]:
    """``retainReceipts``: pending tasks and tasks with a worker or a spawn intent always stay; of the terminal
    receipts the newest ``computed`` ones that ran and the newest ``cached`` cache hits."""
    terminal = [task for task in tasks
                if not pending(task) and not js_truthy(task.get('worker_pid')) and not task.get('starting')]
    computed = [task for task in terminal if not js_truthy(task.get('cached'))]
    keep = {id(task) for task in computed[-limits['computed']:]}
    count = 0
    for task in reversed([task for task in terminal if js_truthy(task.get('cached'))]):
        if count >= limits['cached']:
            break
        keep.add(id(task))
        count += 1
    return [task for task in tasks
            if pending(task) or js_truthy(task.get('worker_pid')) or task.get('starting') or id(task) in keep]


# --- Loading -----------------------------------------------------------------------------------------------------

def _integer(value: Any, minimum: int) -> Optional[int]:
    if jsjson.is_number(value) and jsjson.is_integer(value) and minimum <= value <= _SAFE_INTEGER:
        return int(value)
    return None


def _check_task(task: Any, number: int, sequence: int) -> dict:
    """One receipt of a loaded file, with its integers as ``int``; ``ValueError`` names what is wrong. Its
    ``finished_at`` may be any value: a cache hit's receipt takes the stored record's, unchecked, as Node's does
    (``ready.job.finished_at || now``), and only views show it."""
    where = f'task {number}'
    if not isinstance(task, dict):
        raise ValueError(f'{where} is not an object')
    for name in ('id', 'kind', 'key', 'created_at'):
        if not isinstance(task.get(name), str) or not task[name]:
            raise ValueError(f'{where} has no {name}')
    own = _integer(task.get('sequence'), 1)
    if own is None or own > sequence:
        raise ValueError(f'{where} has an invalid sequence')
    task['sequence'] = own
    if task.get('status') not in STATUSES:
        raise ValueError(f'{where} has an unknown status')
    if 'request' not in task:
        raise ValueError(f'{where} has no request')
    if not jsjson.is_number(task.get('progress')):
        raise ValueError(f'{where} has an invalid progress')
    if not isinstance(task.get('cached'), bool):
        raise ValueError(f'{where} has an invalid cached flag')
    if not (task.get('catalog') is None or isinstance(task.get('catalog'), dict)):
        raise ValueError(f'{where} has an invalid catalog')
    for name in ('message', 'backend_id'):
        if name in task and not isinstance(task[name], str):
            raise ValueError(f'{where} has an invalid {name}')
    if 'worker_pid' in task:
        pid = _integer(task['worker_pid'], 1)
        if pid is None:
            raise ValueError(f'{where} has an invalid worker_pid')
        task['worker_pid'] = pid
    if 'starting' in task and not isinstance(task['starting'], bool):
        raise ValueError(f'{where} has an invalid starting flag')
    refs = task.get('annotation_refs', [])
    if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
        raise ValueError(f'{where} has invalid annotation_refs')
    return task


def _check_state(value: Any) -> tuple[int, list[dict], Optional[str]]:
    if not isinstance(value, dict) or value.get('schema') != QUEUE_SCHEMA:
        raise ValueError(f'it is not an {QUEUE_SCHEMA} file')
    sequence = _integer(value.get('sequence'), 0)
    if sequence is None:
        raise ValueError('its sequence is invalid')
    boot = value.get('boot_id')
    if boot is not None and not (isinstance(boot, str) and boot):
        raise ValueError('its boot_id is invalid')
    tasks = value.get('tasks')
    if not isinstance(tasks, list):
        raise ValueError('its tasks are not a list')
    ids = set()
    checked = []
    for number, task in enumerate(tasks, 1):
        checked.append(_check_task(task, number, sequence))
        if task['id'] in ids:
            raise ValueError(f'task {number} repeats the id of an earlier task')
        ids.add(task['id'])
    return sequence, checked, boot


# --- The queue ---------------------------------------------------------------------------------------------------

class WorkspaceQueue:
    """The durable FIFO of one workspace (``directory`` is ``W/.eeglayoutlab``; the workspace lock keeps a second
    process out, as Node's ``worker.lock`` did).

    ``adapters`` maps each kind to a ``jobs.kinds.Adapter``. ``slot`` is the workspace's ``jobs.slot.ExecutionSlot``
    (its ``busy`` and ``paused`` gate dispatch, as in Node, and so does its ``available()``, the installation lock).
    ``annotations`` stores electrode-name variants:
    ``identity(prepared)`` (a dict with ``id``), ``read(id, key)`` and ``create(prepared)``, each for the local user
    and possibly async. ``now`` gives milliseconds since the epoch (``Date.now``). ``boot_id`` gives the kernel's
    boot id (tests inject it). The constructor loads (or creates) ``queue.json``, applies the restart rules and
    writes it; it raises ``QueueStateError`` and changes nothing when the file cannot be used. ``unsaved`` is the
    error of the last write, at ``dispose``, when it failed.
    """

    def __init__(self, directory: str, adapters: dict[str, Adapter], *, slot: Any = None, annotations: Any = None,
                 now: Optional[Callable[[], float]] = None, max_queued: int = MAX_QUEUED,
                 receipt_limits: Optional[dict] = None, cache_only: bool = False, clear_interrupted: bool = False,
                 boot_id: Callable[[], Optional[str]] = boot_id, retry_seconds: float = RETRY_SECONDS):
        self.directory = nodepath.resolve(directory)
        self.path = nodepath.join(self.directory, QUEUE_FILE)
        self.adapters = adapters
        self.slot = slot
        self.annotations = annotations
        self.now = now or (lambda: time.time() * 1000)
        self.max_queued = max_queued
        self.receipt_limits = {**RECEIPT_LIMITS, **(receipt_limits or {})}
        self.cache_only = cache_only
        self.retry_seconds = retry_seconds
        self.tasks: list[dict] = []
        self.sequence = 0
        self.disposed = False
        self.stopping = False
        self.failure: Optional[str] = None
        self.persist_failed = False
        self.unsaved: Optional[BaseException] = None
        self.boot = boot_id()
        self.active_id: Optional[str] = None
        self.blocked_pids: list[int] = []
        self.unconfirmed = False
        self._launching: Optional[str] = None
        self._lock = asyncio.Lock()
        self._outcomes: dict[str, dict] = {}
        self._recoverable: list[str] = []
        self._wakeup: Optional[asyncio.Event] = None
        self._dispatcher: Optional[asyncio.Task] = None
        try:
            os.makedirs(self.directory, mode=0o700, exist_ok=True)
        except OSError as error:
            raise QueueStateError(f'Cannot create the queue directory {self.directory}: {error.strerror}.') from error
        if cache_only and slot is not None:
            slot.pause()
        sequence, tasks, booted = self._load()
        self.sequence, self.tasks = sequence, tasks
        self._restart(booted, clear_interrupted)
        try:
            self._persist()
        except OSError as error:
            raise QueueStateError(f'Cannot write the workspace queue {self.path}: {error.strerror}.') from error
        for kind, adapter in adapters.items():
            register = getattr(adapter, 'on_finish', None)
            if register is not None:
                register(lambda id, view, kind=kind: self._finished(kind, id, view))

    # Loading and restart ------------------------------------------------------------------------------------------

    def _load(self) -> tuple[int, list[dict], Optional[str]]:
        """The saved sequence and tasks, and the boot id of their last write (``None`` without one)."""
        self._remove_temporaries()
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
        except FileNotFoundError:
            return 0, [], None
        except OSError as error:
            raise self._unusable(error.strerror or str(error)) from error
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise self._unusable('it is not a regular file')
            chunks = []
            while True:
                chunk = os.read(fd, 1 << 20)
                if not chunk:
                    break
                chunks.append(chunk)
        except OSError as error:
            raise self._unusable(error.strerror or str(error)) from error
        finally:
            os.close(fd)
        try:
            value = jsjson.parse(b''.join(chunks).decode('utf-8'))
            sequence, tasks, booted = _check_state(value)
        except UnicodeDecodeError as error:
            raise self._unusable('it is not UTF-8 text') from error
        except jsjson.JSONSyntaxError as error:
            raise self._unusable('it is not valid JSON') from error
        except ValueError as error:
            raise self._unusable(str(error)) from error
        return sequence, tasks, booted

    def _unusable(self, reason: str) -> QueueStateError:
        return QueueStateError(
            f'The workspace queue {self.path} cannot be read ({reason}). It was kept unchanged for recovery; move it '
            'aside to start with an empty queue.')

    def _remove_temporaries(self) -> None:
        """Temporaries left by a write that was interrupted; the rename never happened, so they hold nothing."""
        try:
            names = os.listdir(self.directory)
        except OSError:
            return
        for name in names:
            if _TEMPORARY.fullmatch(name):
                try:
                    os.unlink(nodepath.join(self.directory, name))
                except OSError:
                    pass

    def _restart(self, booted: Optional[str], clear: bool) -> None:
        """Node's constructor loop (community-queue.mjs:77-83), plus the dead-group, reboot and clear rules."""
        # The person cleared them, or the machine has booted since the last write (a boot id that is not this
        # boot's), which came at or after every intent and pid of the file: no process of that run is left.
        resolved = clear or (booted is not None and self.boot is not None and booted != self.boot)
        for task in self.tasks:
            pid = task.get('worker_pid')
            if pid is not None:
                if not resolved and group_alive(pid):
                    self.blocked_pids.append(pid)
                else:
                    # The group this receipt recorded is gone (after a reboot or a clear, a live one is another
                    # process's); its pid could be reused by an unrelated process.
                    del task['worker_pid']
            elif task.get('starting'):
                if resolved:
                    del task['starting']
                else:
                    self.unconfirmed = True
            status = task['status']
            if status in ('running', 'cancelling'):
                task['status'] = 'failed'
                task['message'] = INTERRUPTED_MESSAGE
                task['finished_at'] = iso(self.now())
                if status == 'running':
                    self._recoverable.append(task['id'])
            elif status == 'failed' and task.get('message') == INTERRUPTED_MESSAGE:
                self._recoverable.append(task['id'])

    def clear_interrupted(self) -> int:
        """Resolves every unconfirmed spawn and forgets the worker pids of earlier runs that block dispatch
        (``eeglayoutlab serve --clear-interrupted``): the person has checked that no worker of an earlier run is still
        computing. The task launching or running now keeps its guard. Returns how many receipts it changed."""
        changed = 0
        blocked = set(self.blocked_pids)
        for task in self.tasks:
            if task['id'] in (self._launching, self.active_id):
                continue
            if task.get('starting') and not task.get('worker_pid'):
                del task['starting']
                changed += 1
            elif task.get('worker_pid') in blocked and not pending(task):
                del task['worker_pid']
                changed += 1
        self.blocked_pids = []
        self.unconfirmed = False
        if changed:
            try:
                self._persist()
            except OSError:
                pass
        self._wake()
        return changed

    async def recover(self) -> list[str]:
        """Promotes the receipts a restart interrupted when their kind finds a valid stored result for the same
        request and key: ``completed`` or ``no_layout`` (the radius search only), ``cached``, with the result's
        ``finished_at``. Receipts whose worker may still run, cancellations, and receipts whose identity changed or
        whose result is missing or invalid stay ``failed``. Each receipt is checked under the queue's lock on its own,
        so submissions are not held up for the whole pass. Returns the promoted ids."""
        promoted = []
        candidates, self._recoverable = self._recoverable, []
        for id in candidates:
            async with self._lock:
                if self.disposed or self.stopping:
                    break
                task = self._find(id)
                if (task is None or task['status'] != 'failed' or task.get('message') != INTERRUPTED_MESSAGE
                        or task.get('starting') or group_alive(task.get('worker_pid'))):
                    continue
                adapter = self.adapters.get(task['kind'])
                if adapter is None:
                    continue
                try:
                    found = await self._observe(task, adapter)
                except Exception:  # noqa: BLE001 - an unreadable record keeps the receipt as it is
                    _log.warning('stored result of interrupted task %s not checked', id, exc_info=True)
                    continue
                if found is None or self.disposed or self.stopping:
                    continue
                status, finished, catalog, message = found
                task['status'], task['cached'], task['progress'], task['finished_at'] = status, True, 1, finished
                if isinstance(message, str) and message:
                    task['message'] = message
                else:
                    task.pop('message', None)
                task['catalog'] = {**(task.get('catalog') or {}), **catalog}
                for name in ('starting', 'worker_pid', 'backend_id'):
                    task.pop(name, None)
                promoted.append(id)
                try:
                    self._persist()
                except OSError:
                    pass  # failure is set; the dispatcher retries the write
        return promoted

    @staticmethod
    async def _observe(task: dict, adapter: Adapter) -> Optional[tuple]:
        """``inspectReceipt``'s checks through the kind's own key definition and production validator."""
        prepared = await adapter.prepare(task['request'])
        if (jsjson.stringify(prepared['request']) != jsjson.stringify(task['request'])
                or prepared['key'] != task['key']):
            return None
        found = await adapter.lookup(prepared)
        job = found.get('job') if isinstance(found, dict) and found.get('hit') is True else None
        if not isinstance(job, dict) or job.get('key') != task['key']:
            return None
        status = job.get('status')
        if status not in DONE or (status == 'no_layout' and task['kind'] != 'local-compute'):
            return None
        finished = job.get('finished_at')
        stored = getattr(adapter, 'finished_at', None)
        if stored is not None:  # the kind's views have no finish time: the stored record's
            finished = await resolve(stored(prepared, job))
        if _parse_date(finished) is None:
            return None
        return status, finished, receipt_catalog(task['kind'], prepared, job.get('result', UNDEFINED)), \
            job.get('message')

    # Persistence --------------------------------------------------------------------------------------------------

    def _save(self) -> None:
        state = {'schema': QUEUE_SCHEMA, 'sequence': self.sequence, 'boot_id': self.boot, 'tasks': self.tasks}
        if self.boot is None:
            del state['boot_id']
        records.atomic_json(self.path, state)

    def _persist(self) -> None:
        """``persist()``: retention, then the atomic write; a failure stops the queue until a write succeeds."""
        self.tasks = retain_receipts(self.tasks, self.receipt_limits)
        try:
            self._save()
        except Exception as error:
            self.persist_failed = True
            self._fail_closed(error)
            raise

    def _fail_closed(self, error: BaseException) -> None:
        self.failure = records.node_message(error) or type(error).__name__
        _log.error('computation queue stopped', exc_info=error)

    def _recover_persistence(self) -> bool:
        """``recoverPersistence()``: retry the write, so freeing disk space resumes service."""
        if not self.persist_failed or self.disposed or self.stopping:
            return False
        try:
            self._save()
        except Exception:  # noqa: BLE001 - still failing
            return False
        self.persist_failed = False
        self.failure = None
        return True

    def _commit(self, created: Optional[dict], sequence: int, task: Optional[dict], refs: Any) -> None:
        """Persists a submit; when the write fails, the receipt it created (or the annotation it attached) is taken
        back, so a refused request never runs later."""
        try:
            self._persist()
        except Exception:
            if created is not None:
                self.tasks = [item for item in self.tasks if item is not created]
                self.sequence = sequence
            elif task is not None and refs is not UNDEFINED:
                if refs is None:
                    task.pop('annotation_refs', None)
                else:
                    task['annotation_refs'] = refs
            raise

    # Lookups ------------------------------------------------------------------------------------------------------

    def _find(self, id: Any) -> Optional[dict]:
        return next((task for task in self.tasks if task['id'] == id), None)

    def _check_open(self) -> None:
        if self.disposed or self.stopping or self.failure:
            raise QueueError(UNAVAILABLE, 503)

    def _adapter(self, kind: str) -> Adapter:
        adapter = self.adapters.get(kind)
        if adapter is None:
            raise QueueError(UNKNOWN_ENDPOINT, 404)
        return adapter

    def _busy(self) -> bool:
        return any(adapter.busy() for adapter in self.adapters.values())

    def _held(self) -> bool:
        return self.slot is not None and (self.slot.paused or self.slot.busy)

    def _contended(self) -> bool:
        """Another process holds the installation's execution lock (``ExecutionSlot.available``, a probe that takes
        nothing). Raises what ``InstallationLock.try_acquire`` raises."""
        return self.slot is not None and not self.slot.available()

    def own(self, id: Any, kind: Optional[str] = None) -> dict:
        """``own(id, visitor, kind)``: the receipt, or 404 with Node's message."""
        task = next((task for task in self.tasks if task['id'] == id and (not kind or task['kind'] == kind)), None)
        if task is None:
            raise QueueError(NOT_FOUND, 404)
        return task

    # Views --------------------------------------------------------------------------------------------------------

    async def view(self, task: dict, result: bool = True, annotation_id: Optional[str] = None) -> dict:
        """``view(task, result, visitor, annotationId)``: the backend's view overlaid by the receipt. A finished
        receipt whose job the service no longer holds is read again from its stored result, through the current
        identity (a changed model or a missing record turns the view ``failed``)."""
        adapter = self.adapters.get(task['kind'])
        backend = task.get('backend_id')
        worker = adapter.get(backend) if adapter is not None and backend else None
        value = worker or {}
        if worker is None and result and task['status'] in DONE:
            if adapter is None:
                return {**task_view(task), 'status': 'failed', 'message': VIEW_CACHE_MISSING, 'result': None}
            prepared = await adapter.prepare(task['request'])
            if prepared['key'] != task['key']:
                return {**task_view(task), 'status': 'failed', 'message': VIEW_KEY_CHANGED, 'result': None}
            cached = await adapter.lookup(prepared)
            if not js_truthy(cached.get('hit')):
                return {**task_view(task), 'status': 'failed', 'message': VIEW_CACHE_MISSING, 'result': None}
            value = cached['job']
        position = (sum(1 for item in self.tasks if item['status'] == 'queued' and item['sequence'] <= task['sequence'])
                    if task['status'] == 'queued' else 0)
        combined = {**value, **task_view(task)}
        progress = value.get('progress')
        combined['progress'] = task['progress'] if progress is None else progress
        combined['cached'] = js_truthy(task.get('cached')) or js_truthy(value.get('cached'))
        combined['queue_position'] = position
        message = task.get('message')
        if task['status'] == 'queued':
            combined['message'] = QUEUED_MESSAGE
        elif js_truthy(message):
            combined['message'] = message
        elif js_truthy(value.get('message')):
            combined['message'] = value['message']
        else:
            combined['message'] = task['status']
        if result:
            stored = value.get('result') if task['status'] in DONE else None
            combined['result'] = None if stored is None else stored
        else:
            combined.pop('result', None)
        return {**combined, **(await self._annotation_view(task, annotation_id))}

    async def _annotation_view(self, task: dict, selected: Optional[str]) -> dict:
        """``annotationView``: the selected electrode-name variant of this receipt."""
        if not selected:
            return {}
        if selected not in (task.get('annotation_refs') or []):
            raise QueueError(ANNOTATION_NOT_FOUND, 404)
        return {'annotation_id': selected,
                'electrode_annotation': await resolve(self.annotations.read(selected, task['key']))}

    @staticmethod
    def _last_annotation(task: dict) -> Optional[str]:
        refs = task.get('annotation_refs') or []
        return refs[-1] if refs else None

    async def active(self, kind: str) -> Optional[dict]:
        """``active(kind, visitor)``: the first pending task of the kind, viewed without its result (health's
        ``active_job``)."""
        task = next((task for task in self.tasks if task['kind'] == kind and pending(task)), None)
        return await self.view(task, False, self._last_annotation(task)) if task is not None else None

    def maintenance_status(self) -> dict:
        """``maintenanceStatus()``: ``maintenance`` is the cache-only mode; ``drained`` means nothing runs or may
        still run."""
        guarded = (self.unconfirmed or any(group_alive(pid) for pid in self.blocked_pids)
                   or any(task.get('starting') or group_alive(task.get('worker_pid')) for task in self.tasks))
        drained = (self.cache_only and not self.disposed and not self.failure and not self.active_id and not guarded
                   and not (self.slot is not None and self.slot.busy) and not self._busy())
        return {'maintenance': self.cache_only, 'drained': bool(drained)}

    async def stats(self) -> dict:
        """``stats(visitor)`` (``GET /api/community/status``) without ``online_visitors``; ``jobs`` are the last 12
        receipts, newest first, viewed without their results."""
        jobs = self.tasks[-STATS_JOBS:][::-1]
        status = {
            'queued_tasks': sum(1 for task in self.tasks if task['status'] == 'queued'),
            'running_tasks': 1 if self.active_id or self.blocked_pids else 0,
            'available': not self.failure and not self.disposed and not self.stopping,
            'resource_blocked': False,
            'recovery_blocked': bool(self.blocked_pids) or self.unconfirmed,
            **self.maintenance_status(),
        }
        status['jobs'] = [await self.view(task, False, self._last_annotation(task)) for task in jobs]
        return status

    status = stats

    # Submit and cancel --------------------------------------------------------------------------------------------

    def _receipt(self, kind: str, prepared: dict, status: str) -> dict:
        """``receipt()``: the finished receipt of this kind, key and status, or a new one appended to the FIFO."""
        if status in DONE:
            same = next((task for task in self.tasks if task['kind'] == kind and task['key'] == prepared['key']
                         and task['status'] == status), None)
            if same is not None:
                return same
        self.sequence += 1
        task = {'id': str(uuid.uuid4()), 'sequence': self.sequence, 'kind': kind, 'key': prepared['key'],
                'request': prepared['request'], 'status': status, 'created_at': iso(self.now()), 'progress': 0,
                'cached': False, 'catalog': receipt_catalog(kind, prepared)}
        self.tasks.append(task)
        return task

    async def _annotation_for(self, prepared: dict, task: Optional[dict], accept: Callable[[], None]) -> Any:
        """``annotationFor``: the electrode-name variant a design submission carries, created at most once per
        receipt (100 per receipt; Node's per-owner bound of 20 and its per-network window are dropped, R1)."""
        if not js_truthy(prepared.get('electrode_names')):
            return None
        if self.annotations is None:
            raise QueueError(ANNOTATIONS_UNAVAILABLE, 503)
        id = (await resolve(self.annotations.identity(prepared)))['id']
        refs = (task or {}).get('annotation_refs') or []
        if id in refs:
            return await resolve(self.annotations.read(id, prepared['key']))
        if len(refs) >= ANNOTATION_LIMITS['referencesPerTask']:
            raise QueueError(TASK_VARIANTS, 413)
        accept()
        self._check_open()
        return await resolve(self.annotations.create(prepared))

    @staticmethod
    def _attach(task: dict, annotation: Any) -> Any:
        """``attachAnnotation``; returns the previous references (``UNDEFINED`` when nothing changed)."""
        if not annotation:
            return UNDEFINED
        previous = task.get('annotation_refs')
        refs = previous or []
        task['annotation_refs'] = [ref for ref in refs if ref != annotation['id']] + [annotation['id']]
        return None if previous is None else list(previous)

    async def submit(self, kind: str, raw: Any, lookup_only: bool = False, expected_key: Optional[str] = None,
                     can_accept: Optional[Callable[[], Any]] = None) -> dict:
        """``submit(kind, raw, visitor, lookupOnly, expectedKey, canAccept)``: ``{'hit': True, 'job'}`` for a stored
        result or a pending task of the same key, ``{'hit': False}`` for a lookup miss, else ``{'job'}`` for the new
        queued receipt. Raises ``QueueError`` (503 unavailable or cache-only, 429 queue full, 409 identity or study
        admission changed, 404 unknown kind) and whatever the kind's normalizer or lookup raises."""
        if can_accept is not None and not callable(can_accept):
            raise TypeError('Task admission guard must be a function.')

        def accept(prepared: dict) -> None:
            if expected_key is not None and prepared['key'] != expected_key:
                raise QueueError(IDENTITY_CHANGED, 409)
            if can_accept is not None and can_accept() is not True:
                raise QueueError(STUDY_ADMISSION, 409, study_admission_cancelled=True)

        async with self._lock:
            self._check_open()
            adapter = self._adapter(kind)
            prepared = await adapter.prepare(raw)
            accept(prepared)
            ready = await adapter.lookup(prepared)
            accept(prepared)
            self._check_open()
            if js_truthy(ready.get('hit')):
                job = ready['job']
                status = job.get('status')
                previous = next((task for task in self.tasks if task['kind'] == kind
                                 and task['key'] == prepared['key'] and task['status'] == status), None)
                annotation = await self._annotation_for(prepared, previous, lambda: accept(prepared))
                accept(prepared)
                self._check_open()
                count, sequence = len(self.tasks), self.sequence
                task = self._receipt(kind, prepared, status)
                refs = self._attach(task, annotation)
                created = len(self.tasks) != count
                if created:
                    task['cached'] = True
                    finished = job.get('finished_at')
                    task['finished_at'] = finished if js_truthy(finished) else iso(self.now())
                    task['catalog'] = receipt_catalog(kind, prepared, job.get('result', UNDEFINED))
                # Repeating a lookup of a result already held changes nothing durable.
                if created or annotation:
                    self._commit(task if created else None, sequence, task, refs)
                selected = await self._annotation_view(task, annotation['id'] if annotation else None)
                return {'hit': True, 'job': {**job, **task_view(task), 'cached': True, **selected}}
            existing = next((task for task in self.tasks if task['kind'] == kind and task['key'] == prepared['key']
                             and task['status'] in ('queued', 'running')), None)
            if existing is not None:
                annotation = await self._annotation_for(prepared, existing, lambda: accept(prepared))
                accept(prepared)
                self._check_open()
                if annotation:
                    self._commit(None, self.sequence, existing, self._attach(existing, annotation))
                return {'hit': True, 'job': await self.view(existing, True, annotation['id'] if annotation else None)}
            if lookup_only:
                return {'hit': False}
            if self.cache_only:
                raise QueueError(MAINTENANCE, 503, admission_rejected=True)
            if sum(1 for task in self.tasks if pending(task)) >= self.max_queued:
                raise QueueError(QUEUE_FULL, 429)
            annotation = await self._annotation_for(prepared, None, lambda: accept(prepared))
            accept(prepared)
            self._check_open()
            if self.cache_only or (self.slot is not None and self.slot.paused):
                raise QueueError(MAINTENANCE, 503, admission_rejected=True)
            sequence = self.sequence
            task = self._receipt(kind, prepared, 'queued')
            self._attach(task, annotation)
            self._commit(task, sequence, None, UNDEFINED)
            self._wake()
            return {'job': await self.view(task, True, annotation['id'] if annotation else None)}

    async def cancel(self, id: Any, kind: Optional[str] = None) -> dict:
        """``cancel(id, visitor, kind)``: a queued task is ``cancelled`` at once; a running one is stopped and stays
        ``cancelling`` until its job has finished. Returns the view."""
        async with self._lock:
            task = self.own(id, kind)
            if not pending(task):
                return await self.view(task)
            if task['status'] == 'queued':
                task['status'] = 'cancelled'
                task['finished_at'] = iso(self.now())
            else:
                adapter = self.adapters.get(task['kind'])
                if adapter is not None:
                    adapter.cancel(task.get('backend_id'))
                task['status'] = 'cancelling'
            self._persist()
            self._wake()
            return await self.view(task)

    # Dispatch -----------------------------------------------------------------------------------------------------

    def _finished(self, kind: str, id: Any, view: dict) -> None:
        """The kind's completion callback: keep the terminal view for the next tick and wake the dispatcher."""
        if not isinstance(id, str):
            return
        self._outcomes[id] = view
        while len(self._outcomes) > _OUTCOME_LIMIT:
            del self._outcomes[next(iter(self._outcomes))]
        self._wake()

    def _unblock(self) -> None:
        """Forget the worker groups that are gone (their receipts keep no pid)."""
        alive = [pid for pid in self.blocked_pids if group_alive(pid)]
        gone = set(self.blocked_pids) - set(alive)
        self.blocked_pids = alive
        if gone:
            for task in self.tasks:
                if task.get('worker_pid') in gone and not pending(task):
                    del task['worker_pid']

    async def tick(self) -> bool:
        """One step of ``tick()``: finalize the active task once its job is done, then dispatch the next queued task.
        Returns whether a receipt changed."""
        async with self._lock:
            return await self._tick()

    async def _tick(self) -> bool:
        if self.failure and not self._recover_persistence():
            return False
        if self.disposed or self.stopping or self.failure:
            return False
        self._unblock()
        if self.blocked_pids or self.unconfirmed:
            return False
        changed = False
        if self.active_id is not None:
            task = self._find(self.active_id)
            adapter = self.adapters.get(task['kind']) if task is not None else None
            # Services clear active only after result validation and durable record writes.
            if adapter is not None and adapter.busy():
                return False
            if task is not None:
                backend = task.get('backend_id')
                worker = self._outcomes.pop(backend, None) if backend else None
                if worker is None and adapter is not None and backend:
                    worker = adapter.get(backend)
                status = _get(worker, 'status')
                message = _get(worker, 'message')
                progress = _get(worker, 'progress')
                result = _get(worker, 'result')
                task['status'] = status if status in TERMINAL else 'failed'
                task['message'] = message if js_truthy(message) else NO_RESULT
                task['finished_at'] = iso(self.now())
                task['progress'] = progress if js_truthy(progress) else 0
                if js_truthy(result):
                    task['catalog'] = {**(task.get('catalog') or {}),
                                       **receipt_catalog(task['kind'], {'request': task['request']}, result)}
                task['cached'] = js_truthy(_get(worker, 'cached'))
                task.pop('worker_pid', None)
                task.pop('starting', None)
            self.active_id = None
            self._persist()
            changed = True
        if self.cache_only or self._held() or self._busy():
            return changed
        next_task = next((task for task in self.tasks if task['status'] == 'queued'), None)
        if next_task is None:
            return changed
        adapter = self.adapters.get(next_task['kind'])
        try:
            # Another workspace of the installation computing holds the permit, as Node's busy slot does: the task
            # waits in its place without being prepared or written, and the dispatcher looks again on its timer. A
            # lock that cannot be used raises again at the second probe, after the key check (Node's order).
            try:
                waiting = self._contended()
            except Exception:  # noqa: BLE001 - raised again below
                waiting = False
            if waiting:
                return changed
            if adapter is None:
                raise TypeError(f'No adapter for {next_task["kind"]}')
            prepared = await adapter.prepare(next_task['request'])
            if self.disposed or self.stopping or self.failure or self.cache_only or self._held() or self._busy():
                return changed
            if prepared['key'] != next_task['key']:
                raise _Failure(DISPATCH_KEY_CHANGED)
            if self._contended():
                return changed
            # Persist the spawn intent before launching a subprocess.
            next_task['status'] = 'running'
            next_task['starting'] = True
            self.active_id = next_task['id']
            self._persist()
            self._launching = next_task['id']
            try:
                started = await adapter.start(prepared)
            finally:
                self._launching = None
            if self.disposed:
                return True
            if js_truthy(started.get('busy')):
                # The slot was taken (or paused, or the installation lock taken by another workspace) during the
                # service's preparation: nothing was launched, so the receipt keeps its place and loses its intent.
                next_task['status'] = 'queued'
                for name in ('starting', 'worker_pid', 'backend_id'):
                    next_task.pop(name, None)
                self.active_id = None
                self._persist()
                return changed
            job = started.get('job')
            if not js_truthy(job):
                raise _Failure(START_WITHOUT_JOB)
            next_task['backend_id'] = job['id']
            pid = adapter.pid()
            if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
                next_task['worker_pid'] = pid
            else:
                next_task.pop('worker_pid', None)
            next_task['starting'] = False
            self._persist()
            if job.get('key') != next_task['key']:
                adapter.cancel(next_task['backend_id'])
                raise _Failure(DISPATCH_KEY_CHANGED)
            return True
        except Exception as error:
            if self.disposed or self.stopping:
                return changed
            next_task['status'] = 'failed'
            next_task['message'] = public_message(error)
            next_task['finished_at'] = iso(self.now())
            self.active_id = None
            self._persist()
            return True

    # Scheduling ---------------------------------------------------------------------------------------------------

    async def start(self) -> None:
        """Startup: ``recover()``, then a dispatcher that ticks whenever something changes (Node's interval)."""
        await self.recover()
        if self.disposed or self.stopping or self._dispatcher is not None:
            return
        self._wakeup = asyncio.Event()
        self._dispatcher = asyncio.get_running_loop().create_task(self._dispatch())
        self._wakeup.set()

    def _wake(self) -> None:
        if self._wakeup is not None and not (self.disposed or self.stopping):
            self._wakeup.set()

    def _polling(self) -> bool:
        """Work that waits on something no callback announces: a failed write, a worker group still alive, the
        active job (should its callback be lost), or queued tasks while the permit may be held elsewhere."""
        if self.failure:
            return self.persist_failed
        if self.unconfirmed:
            return False
        return bool(self.blocked_pids or self.active_id
                    or (not self.cache_only and any(task['status'] == 'queued' for task in self.tasks)))

    async def _dispatch(self) -> None:
        assert self._wakeup is not None
        while not (self.disposed or self.stopping):
            self._wakeup.clear()
            try:
                changed = await self.tick()
            except Exception as error:  # noqa: BLE001 - Node's interval: the queue stops, the process stays
                self._fail_closed(error)
                changed = False
            if self.disposed or self.stopping:
                return
            if changed:
                continue
            try:
                await asyncio.wait_for(self._wakeup.wait(), self.retry_seconds if self._polling() else None)
            except asyncio.TimeoutError:
                pass

    def stop_scheduling(self) -> None:
        """``stopScheduling()``: no new dispatch or admission; a start already running is still recorded."""
        self.stopping = True
        if self._wakeup is not None:
            self._wakeup.set()

    def dispose(self) -> None:
        """``dispose()``: stop scheduling and write the queue once more. A task whose launch is still in flight goes
        back to ``queued`` (the services refuse to spawn after their own disposal), so the restart does not see an
        unconfirmed spawn; a launch that failed with an unknown outcome keeps its guard. A failed write is kept in
        ``unsaved`` (Node's ``dispose`` throws it)."""
        if self.disposed:
            return
        self.stop_scheduling()
        self.disposed = True
        launching = self._find(self._launching) if self._launching is not None else None
        if launching is not None and launching.get('starting') and not launching.get('worker_pid'):
            launching['status'] = 'queued'
            launching.pop('starting', None)
            launching.pop('backend_id', None)
        try:
            self._persist()
        except Exception as error:  # noqa: BLE001 - logged by _persist; the next start applies the restart rules
            self.unsaved = error

    async def close(self, timeout: float = 10.0) -> None:
        """``dispose()``, then wait for the dispatcher to leave (cancelled after ``timeout`` seconds)."""
        self.dispose()
        dispatcher, self._dispatcher = self._dispatcher, None
        if dispatcher is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(dispatcher), timeout)
        except asyncio.TimeoutError:
            dispatcher.cancel()
            try:
                await dispatcher
            except asyncio.CancelledError:
                pass
