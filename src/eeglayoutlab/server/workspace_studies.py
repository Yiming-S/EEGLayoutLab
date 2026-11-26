"""Robustness studies of the workspace: Node's ``StudyStore`` (``webapp/server/studies/store.mjs:37-457``) and
``RobustnessStudyService`` (``studies/service.mjs:21-658``), statement by statement, for the one local user.

A study is an explicitly started sequence of 1 to 12 design evaluations (``jobs.studies``: the protocol, the
normalized cases and the aggregation). Each case is a coordinate evaluation submitted to the workspace queue
(``jobs.queue.WorkspaceQueue``, kind ``design-evaluation``) as any other: its receipt, worker and record are the
coordinate evaluation's (slice 5). When the case completes, the exact bytes of its ``cache.json``
(``R/results/v2/design_evaluation_jobs/<key>/cache.json``) are copied into the study, so a study keeps each case's
key and result even after the receipt ages out of retention or the record is replaced.

Storage (``W/studies``, never Node's ``R/results/web-service/studies``)::

    W/studies/<uuid4>/study.json                   eeg-robustness-study/1, JSON.stringify bytes
    W/studies/<uuid4>/snapshots/<sha256>.json      the exact cache.json bytes of a completed case (its SHA-256)

``StudyStore`` reads and writes it through ``server.workspace_files`` (Node's ``ProjectStore`` I/O: no links, one
link per file, ``O_NOFOLLOW``, the device and inode checked again, atomic writes), and fails closed with Node's
statuses and messages: an entry that is not a UUID directory, a ``snapshots`` directory or a ``study.json`` /
``<sha256>.json`` file (or one of their ``.<uuid>.tmp`` temporaries) is 409; metadata that fails ``validate_study``
(Node's ``validate``) is 409 ``Study metadata failed integrity checks.``; a snapshot whose bytes, size or cache no
longer match its case is 409; the size bounds are Node's (``jobs.studies.STUDY_LIMITS``: 256 KiB of metadata, 16 MiB
per snapshot, 64 MiB per study, 512 MiB in all, 36 snapshot files per study). Writes are serialized; each one checks
the hook ``before_write`` first (Node's ``admit``) unless it is a control write (cancellation).

``validate_study_cache`` binds a snapshot to its case: the cache's key is the case's, its identity hashes with the
case's request to that key (``sha256(JSON.stringify({request, identity}))``), its ``result_sha256`` is the result's,
the result was computed for exactly that request, and ``validateDesignResult`` accepts it.

``RobustnessStudyService`` is Node's service: ``create`` normalizes the study, prepares every case through the queue's
design-evaluation adapter (no job is started) and stores a draft whose ``identity_sha256`` is
``sha256(JSON.stringify(ctx.identity))`` of the shared scientific identity, or for ``heads`` (one identity per head
package) ``sha256(JSON.stringify([case identity_sha256, ...]))`` with each case's own (B18). ``start``, ``resume`` and
``cancel`` change the parent explicitly; reads (``get``, ``list``, ``export``) and restart recovery never submit work.
A running study is pumped one case at a time: the case is prepared again (a changed key or identity fails the pending
cases), marked ``submitting`` with an operation id, submitted with its expected key and a guard that stops admission
once the study is cancelled or the service stops, and followed through its receipt until its cache is archived. A
restart pauses running studies (``paused_recovery``); an explicit resume reconciles a ``submitting`` case with the
queue's receipts of the same request and key, or with a verified stored cache, and never submits it blindly.

Differences from Node, deliberate (design 0001, phase 2, slice 8; plan section 5.1):

- One local user. Records carry the local owner (``server.workspace.LOCAL_OWNER``) and are read whatever their owner;
  ``list`` shows every study of the workspace. Node's per-browser ownership, the per-network, per-owner and total
  study counts (15, 10, 100) and the 7-day pruning of unstarted drafts are not ported; the size bounds are.
  Creating a study still reads every stored study first, so an unsafe or corrupt entry refuses it as in Node.
- At most one parent study runs at a time in the workspace (Node: one per browser), with Node's 429 and message.
- A queue receipt has no owners: a case's receipt is the workspace's receipt of that request and key, and cancelling
  the study cancels it (Node only removes the browser from a receipt another browser shares).
- A record's ``cache.json`` may also be linked by B16's ``cache.json.<uuid4>.tmp`` beside it (a publish between its
  link and its unlink, or one that crashed there): those links are accepted, any other is refused as in Node, where
  a renamed cache always has one link.
- ``validate_study`` accepts creation and update times that are ISO 8601 date-time strings (``Date.parse``'s date
  time string format, ``iso_date_finite``); a time in another of V8's legacy formats, or one that is not a string,
  fails the check (Node parses those). Every time this store writes is ``toISOString()``.
- The store's file work runs in worker threads, one serialized write at a time; the clock, the identifiers and the
  poll interval can be injected.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import stat
import time
from typing import Any, AsyncIterable, Callable, Iterable, Optional, Union
import uuid

from ..jobs import nodefs, nodepath, records
from ..jobs.annotations import electrode_names
from ..jobs.design_result import normalize_design_request, validate_design_result
from ..jobs.identity import UNDEFINED, _js_string, _same, js_truthy
from ..jobs.kinds import resolve
from ..jobs.queue import INTERRUPTED_MESSAGE, iso
from ..jobs.studies import (CASE_STATUSES, STUDY_LIMITS, STUDY_PROTOCOLS, STUDY_STATUSES, StudyError,
                            aggregate_study, normalize_study_input, study_action, summarize_study_case,
                            terminal_case)
from ..schemas import jsjson
from .workspace import LOCAL_OWNER
from .workspace_files import SHA, UUID, WorkspaceFiles, basename, lstat, mkdir, valid_project_id

__all__ = [
    'STUDY_SCHEMA', 'EXPORT_SCHEMA', 'STUDIES', 'BODY_LIMIT', 'SNAPSHOT_FILES', 'POLL_SECONDS', 'ResourceError',
    'StudyStore', 'RobustnessStudyService', 'validate_study', 'validate_study_cache', 'iso_date_finite',
    'safe_failure', 'error_answer', 'study_path',
]

STUDY_SCHEMA = 'eeg-robustness-study/1'
EXPORT_SCHEMA = 'eeg-robustness-study-export/1'
STUDIES = 'studies'  # W/studies
BODY_LIMIT = 65536
SNAPSHOT_FILES = 36
POLL_SECONDS = 0.5
DESIGN_KIND = 'design-evaluation'
DESIGN_RECORDS = 'results/v2/design_evaluation_jobs'  # a literal path (B20)
SUBMISSION_SCHEMA = 'design-submission/1'

# Node's messages, verbatim. The store's:
NOT_FOUND = 'Study not found.'
INTEGRITY = 'Study metadata failed integrity checks.'
CACHE_MISMATCH = 'Study scientific cache identity mismatch.'
DIRECTORY_INSPECTION = 'Study directory needs inspection.'
UNSAFE_ENTRY = 'Study storage contains an unsafe entry.'
STORAGE_INSPECTION = 'Study storage needs inspection.'
METADATA_SIZE = 'Study metadata exceeds the size limit.'
CAPACITY = 'Study storage capacity reached.'
METADATA_PATH = 'Study metadata path is unsafe.'
CASE_NOT_FOUND = 'Study case not found.'
SNAPSHOT_TOO_LARGE = 'Study case snapshot is too large.'
SNAPSHOT_FILE_LIMIT = 'Study snapshot file limit reached.'
SNAPSHOT_PATH = 'Study snapshot path is unsafe.'
SNAPSHOT_CHECKSUM = 'Study snapshot checksum mismatch.'
SNAPSHOT_CAPACITY = 'Study snapshot capacity reached.'
# The service's:
STOPPING = 'Study service is stopping.'
IDENTITY_PREPARING = 'Scientific identity changed while preparing the study.'
ACTIVE_STUDY = 'This browser already has an active study.'
START_STATE = 'Start a draft study or explicitly resume a paused study.'
RECEIPT_MISMATCH = 'Study child receipt identity mismatch.'
PAUSED = 'Study processing paused. Inspect the recorded cases before resuming.'
CACHE_INVALID = 'Completed case failed scientific cache integrity checks.'
OUTCOME_UNKNOWN = ('No owned receipt or verified cache confirms the interrupted submission. It was not '
                   'resubmitted.')
IDENTITY_CHANGED = 'Scientific identity changed. Create a new study to use the updated model.'
DEFERRED = 'The original queue deferred this case. Resume explicitly when resources are available.'
UNCERTAIN = 'Submission did not return a confirmed receipt. Resume only to reconcile its original outcome.'
SUBSCRIPTION_REMOVED = 'This browser no longer owns the child subscription.'
CANCEL_PAUSED = ('Cancellation is recorded. Saving an existing completed result is paused until resources are '
                 'available.')
# The middleware's:
JSON_REQUIRED = 'JSON is required.'
TOO_LARGE = 'Study request is too large.'
INVALID_JSON = 'Invalid study JSON.'
QUERIES = 'Study API queries are not supported.'
METHOD = 'Unsupported study method.'
CONTROL_BODY = 'Study control requests require an empty JSON object.'
OPERATION = 'Unsupported study operation.'
UNAVAILABLE = 'Study storage or scientific input is unavailable.'

_STUDY_FILE = re.compile(r'(?:study|[a-f0-9]{64})\.json(?:\.[a-f0-9-]{36}\.tmp)?')
_SNAPSHOT_FILE = re.compile(r'[a-f0-9]{64}\.json(?:\.[a-f0-9-]{36}\.tmp)?')
_STUDY_PATH = re.compile(r'/api/robustness-studies/([a-f0-9-]{36})(?:/(start|resume|cancel|export))?')
_PATH_PARTS = re.compile(r'[\\/]')
_PUBLISH_TEMPORARY = re.compile(r'cache\.json\.' + UUID.pattern + r'\.tmp')  # records._temporary of cache.json
_ANNOTATION_KEYS = ('electrode_names', 'source_metadata')
_RUNNING = ('running', 'cancelling')
_RECEIPT_PENDING = ('queued', 'running', 'cancelling')
_PARENT_DONE = ('completed', 'completed_with_failures', 'cancelled')
_SAFE_INTEGER = 2 ** 53 - 1
_log = logging.getLogger(__name__)


class ResourceError(Exception):
    """A refusal of new work for want of resources, or because the service is stopping (Node's ``resourceSafe``
    errors, which ``admit`` raises): shown with its status and message; ``retry_after`` (seconds) becomes the
    ``Retry-After`` header. A ``before_write`` hook raises it."""

    resource_safe = True

    def __init__(self, message: str, status: int = 503, retry_after: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.retry_after = retry_after


class _Invalid(Exception):
    """A failed metadata check (Node's bare ``throw new Error()`` inside ``validate``)."""


# --- JavaScript values -------------------------------------------------------------------------------------------

def _get(value: Any, key: str) -> Any:
    """``value.key`` of a parsed object: ``UNDEFINED`` when absent or when ``value`` is not an object."""
    if isinstance(value, dict):
        return value.get(key, UNDEFINED)
    return UNDEFINED


def _stringify(value: Any) -> Optional[str]:
    """``JSON.stringify(value)``; ``None`` stands for its ``undefined``."""
    return None if value is UNDEFINED else jsjson.stringify(value)


def _json_hash(value: Any) -> str:
    """``createHash('sha256').update(JSON.stringify(value)).digest('hex')``: ``undefined`` cannot be hashed."""
    if value is UNDEFINED:
        raise nodepath.InvalidArgTypeError('The "data" argument must be of type string or an instance of Buffer, '
                                           'TypedArray, or DataView. Received undefined')
    return jsjson.sha256_hex(value)


def _digest(data: bytes) -> str:
    """``digestStudyBytes(bytes)``."""
    return hashlib.sha256(data).hexdigest()


def _parse(data: bytes) -> Any:
    """``JSON.parse(buffer)``: the bytes as UTF-8 with U+FFFD for invalid sequences, then JavaScript's parser."""
    return jsjson.parse(jsjson.decode_body(data))


def _sha(value: Any) -> bool:
    """``/^[a-f0-9]{64}$/.test(value)``: the value converted with ``String``."""
    return SHA.fullmatch(_js_string(value)) is not None


def _clone(value: Any) -> Any:
    """``structuredClone`` of parsed JSON."""
    if isinstance(value, dict):
        return {key: _clone(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone(item) for item in value]
    return value


def _object_keys(value: Any) -> list:
    """``Object.keys(value)`` of a truthy value: an object's names, an array's or a string's indices, none for a
    number or a boolean."""
    if isinstance(value, dict):
        return list(value)
    if isinstance(value, list):
        return [str(index) for index in range(len(value))]
    if isinstance(value, str):
        return [str(index) for index in range(len(value.encode('utf-16-le', errors='surrogatepass')) // 2)]
    return []


def _units(text: str) -> int:
    return len(text.encode('utf-16-le', errors='surrogatepass')) // 2


def _safe_integer(value: Any) -> bool:
    """``Number.isSafeInteger(value)``."""
    return jsjson.is_integer(value) and abs(jsjson.to_number(value)) <= _SAFE_INTEGER


def _includes(options: Iterable[str], value: Any) -> bool:
    return isinstance(value, str) and value in options


def _distinct_count(values: list) -> int:
    """``new Set(values).size``: SameValueZero, so ``-0`` and ``0`` are one value and ``NaN`` is itself."""
    seen = set()
    for value in values:
        if isinstance(value, bool):
            seen.add(('boolean', value))
        elif jsjson.is_number(value):
            number = jsjson.to_number(value)
            seen.add(('number', 'NaN' if number != number else number))
        elif isinstance(value, str):
            seen.add(('string', value))
        elif value is None or value is UNDEFINED:
            seen.add((repr(value),))
        else:
            seen.add(('object', id(value)))
    return len(seen)


def _case_at(cases: list, index: Any) -> Any:
    """``record.cases[index]`` for a number: ``UNDEFINED`` unless it names an element (parsed JSON numbers may be
    floats)."""
    if jsjson.is_number(index):
        number = jsjson.to_number(index)
        if number.is_integer() and 0 <= number < len(cases):
            return cases[int(number)]
    return UNDEFINED


def _status(error: BaseException) -> Any:
    return getattr(error, 'status', None)


def _resource_safe(error: BaseException) -> bool:
    return getattr(error, 'resource_safe', False) is True


def safe_failure(code: str, message: Any) -> dict:
    """``safeFailure(code, message)``: ``{code, message}`` with the message cut to 500 UTF-16 units."""
    return {'code': code, 'message': jsjson.slice_utf16(_js_string(message), 500)}


def _now_iso() -> str:
    """``new Date().toISOString()``."""
    return iso(time.time() * 1000)


# --- Date.parse ------------------------------------------------------------------------------------------------------

_ISO_DATE = re.compile(r'(?:([0-9]{4})|([+-])([0-9]{6}))(?:-([0-9]{2})(?:-([0-9]{2}))?)?'
                       r'(?:T([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:\.([0-9]+))?)?(Z|[+-][0-9]{2}:[0-9]{2})?)?')
_MAX_TIME = 8.64e15
# A local date-time is converted with the local offset (at most 14 hours) before V8 clips it; one this close to the
# limit is refused so that every accepted text is finite in any time zone.
_LOCAL_MARGIN = 15 * 3600000


def _days_from_civil(year: int, month: int, day: int) -> int:
    """Days from 1970-01-01 of a proleptic Gregorian date (``MakeDay``)."""
    year -= month <= 2
    era = year // 400  # floor division: the era of a negative year is negative
    year_of_era = year - era * 400
    day_of_year = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    return era * 146097 + day_of_era - 719468


def iso_date_finite(value: Any) -> bool:
    """``Number.isFinite(Date.parse(value))`` for a string in ``Date.parse``'s date time string format
    (``YYYY[-MM[-DD]][THH:mm[:ss[.s+]][Z|±HH:mm]]``, or a signed six-digit year) with V8's ranges: a month of 1
    to 12, a day of 1 to 31 (it carries into the next month), ``24:00`` only at midnight, an offset of at most
    23:59, and the time within 8.64e15 ms of the epoch (a local time, which V8 converts with the host's offset,
    within 15 hours less). Every other value is not finite here (V8 also reads some legacy formats; see the
    module docstring)."""
    if not isinstance(value, str):
        return False
    match = _ISO_DATE.fullmatch(value)
    if match is None:
        return False
    year, sign, wide, month, day, hour, minute, second, fraction, zone = match.groups()
    if wide is not None:
        if sign == '-' and int(wide) == 0:
            return False
        number = int(wide) * (-1 if sign == '-' else 1)
    else:
        number = int(year)
    month_number, day_number = int(month or 1), int(day or 1)
    if not 1 <= month_number <= 12 or not 1 <= day_number <= 31:
        return False
    milliseconds = 0
    if hour is not None:
        hours, minutes, seconds = int(hour), int(minute), int(second or 0)
        part = int(fraction[:3].ljust(3, '0')) if fraction else 0
        if hours == 24:
            if minutes or seconds or (fraction and int(fraction)):
                return False
        elif hours > 23 or minutes > 59 or seconds > 59:
            return False
        milliseconds = ((hours * 60 + minutes) * 60 + seconds) * 1000 + part
    moment = (_days_from_civil(number, month_number, 1) + day_number - 1) * 86400000 + milliseconds
    if zone is not None and zone != 'Z':
        if int(zone[1:3]) > 23 or int(zone[4:6]) > 59:
            return False
        offset = (int(zone[1:3]) * 60 + int(zone[4:6])) * 60000
        moment -= offset if zone[0] == '+' else -offset
    if hour is not None and zone is None:
        return abs(moment) <= _MAX_TIME - _LOCAL_MARGIN
    return abs(moment) <= _MAX_TIME


# --- Integrity checks --------------------------------------------------------------------------------------------

def _coordinate_source(value: Any) -> None:
    """``validateCoordinateSource(value)`` (the phase 1 schema)."""
    from ..schemas.coordinate_source import normalize_coordinate_source
    normalize_coordinate_source(value)


def _check(record: Any) -> None:
    if not isinstance(record, dict):
        raise _Invalid()
    get = record.get
    cancel = get('cancel_requested', UNDEFINED)
    if cancel is not UNDEFINED and not isinstance(cancel, bool):
        raise _Invalid()
    title, notes, cases = get('title', UNDEFINED), get('notes', UNDEFINED), get('cases', UNDEFINED)
    revision = get('revision', UNDEFINED)
    if (not _same(get('schema', UNDEFINED), STUDY_SCHEMA) or not valid_project_id(get('id', UNDEFINED))
            or not _sha(get('owner', UNDEFINED)) or not _includes(STUDY_PROTOCOLS, get('protocol', UNDEFINED))
            or not _includes(STUDY_STATUSES, get('status', UNDEFINED)) or not _safe_integer(revision) or revision < 1
            or not isinstance(title, str) or not jsjson.js_trim(title) or _units(title) > 200
            or not isinstance(notes, str) or _units(notes) > 2000
            or not all(iso_date_finite(get(name, UNDEFINED)) for name in ('created_at', 'updated_at'))
            or not _sha(get('identity_sha256', UNDEFINED))
            or not isinstance(cases, list) or not cases or len(cases) > STUDY_LIMITS['cases']):
        raise _Invalid()
    annotation = get('annotation', UNDEFINED)
    if not js_truthy(annotation) or any(key not in _ANNOTATION_KEYS for key in _object_keys(annotation)):
        raise _Invalid()
    if _get(annotation, 'electrode_names') is not UNDEFINED:
        electrode_names(annotation['electrode_names'])
    if _get(annotation, 'source_metadata') is not UNDEFINED:
        _coordinate_source(annotation['source_metadata'])
    protocol = record['protocol']
    requests = set()
    for index, entry in enumerate(cases):
        if not isinstance(entry, dict):
            raise _Invalid()
        field = entry.get
        request = field('request', UNDEFINED)
        receipt = field('receipt_id', UNDEFINED)
        if (not _same(field('index', UNDEFINED), index) or not _sha(field('key', UNDEFINED))
                or not _includes(CASE_STATUSES, field('status', UNDEFINED))
                or not (receipt is None or valid_project_id(receipt))
                or jsjson.stringify(normalize_design_request(request)) != _stringify(request)):
            raise _Invalid()
        if (_stringify(_get(request, 'design')) != _stringify(get('design', UNDEFINED))
                or _stringify(_get(request, 'noise_model')) != _stringify(get('noise_model', UNDEFINED))
                or not _same(_get(request, 'conductivity_scenario'), get('conductivity_scenario', UNDEFINED))
                or not _same(_get(request, 'action'), study_action(protocol))
                or (protocol == 'heads') != isinstance(_get(request, 'head_id'), str)):
            raise _Invalid()
        source, size = field('source_sha256', UNDEFINED), field('source_bytes', UNDEFINED)
        if source is not UNDEFINED and (not _sha(source) or not _safe_integer(size) or size < 2
                                        or size > STUDY_LIMITS['caseBytes']):
            raise _Invalid()
        status, operation = field('status'), field('operation_id', UNDEFINED)
        if status == 'completed' and source is UNDEFINED:
            raise _Invalid()
        if operation is not UNDEFINED and not valid_project_id(operation):
            raise _Invalid()
        if status == 'submitting' and not valid_project_id(operation):
            raise _Invalid()
        for name in ('annotation_id', 'identity_sha256'):
            if field(name, UNDEFINED) is not UNDEFINED and not _sha(field(name)):
                raise _Invalid()
        if get('network', UNDEFINED) is not UNDEFINED and not _sha(get('network')):
            raise _Invalid()
        text = _stringify(request)
        if text in requests:
            raise _Invalid()
        requests.add(text)
    requested = [entry['request'] for entry in cases]
    if study_action(protocol) == 'evaluate' and _distinct_count([_get(value, 'radius_mm')
                                                                for value in requested]) != 1:
        raise _Invalid()
    if protocol == 'heads' and (_distinct_count([_get(value, 'head_id') for value in requested]) != len(cases)
                                or _distinct_count([_get(value, 'seed') for value in requested]) != 1):
        raise _Invalid()
    # Heads bind every case identity; other protocols keep the one shared identity, as older servers expect.
    identities = [entry.get('identity_sha256', UNDEFINED) for entry in cases]
    if protocol == 'heads':
        if any(value is UNDEFINED for value in identities) or not _same(_json_hash(identities),
                                                                        get('identity_sha256')):
            raise _Invalid()
    elif any(value is not UNDEFINED for value in identities):
        raise _Invalid()


def validate_study(record: Any) -> Any:
    """``validate(record)``: the record, or ``StudyError`` 409 ``Study metadata failed integrity checks.`` for any
    failed check, whatever raised it."""
    try:
        _check(record)
    except Exception:  # noqa: BLE001 - Node's catch-all
        raise StudyError(INTEGRITY, 409) from None
    return record


def validate_study_cache(cache: Any, entry: Any) -> Any:
    """``validateStudyCache(cache, entry)``: the cache, if it is the one this case's request and key name; else
    ``StudyError`` 409 ``Study scientific cache identity mismatch.``. A cache without a result cannot be hashed (a
    ``TypeError``, as in Node), and ``validateDesignResult`` raises its own refusal."""
    request = _get(entry, 'request')
    key = _get(entry, 'key')
    if not isinstance(cache, dict) or not js_truthy(cache):
        raise StudyError(CACHE_MISMATCH, 409)
    result = cache.get('result', UNDEFINED)
    if (not _same(cache.get('key', UNDEFINED), key) or not js_truthy(cache.get('identity', UNDEFINED))
            or not _same(_json_hash({'request': request, 'identity': cache['identity']}), key)
            or not _same(_json_hash(result), cache.get('result_sha256', UNDEFINED))
            or _stringify(_get(result, 'request')) != _stringify(request)):
        raise StudyError(CACHE_MISMATCH, 409)
    validate_design_result(result, request)
    return cache


# --- The store -----------------------------------------------------------------------------------------------------

class StudyStore:
    """``StudyStore`` on ``directory`` (``W/studies``).

    ``before_write`` (plain or async; Node's ``beforeWrite``) runs before every write that is not a control write and
    may raise ``ResourceError`` or ``StudyError``; ``now`` gives the ISO time of a write, ``random_uuid`` a study's
    identifier, ``limits`` replaces some of ``STUDY_LIMITS`` and ``owner`` is the owner written into new records. The
    public methods are coroutines; their file work runs in worker threads. ``load`` ignores the owner."""

    def __init__(self, directory: str, *, before_write: Optional[Callable[[], Any]] = None,
                 now: Optional[Callable[[], str]] = None, limits: Optional[dict] = None,
                 random_uuid: Optional[Callable[[], str]] = None, owner: str = LOCAL_OWNER):
        self.io = WorkspaceFiles(directory)
        self.before_write = before_write or (lambda: None)
        self.now = now or _now_iso
        self.limits = {**STUDY_LIMITS, **(limits or {})}
        self.random_uuid = random_uuid or (lambda: str(uuid.uuid4()))
        self.owner = owner

    @property
    def directory(self) -> str:
        return self.io.directory

    @property
    def pending_writes(self) -> int:
        return self.io.pending_writes

    @property
    def closed(self) -> bool:
        return self.io.closed

    def close(self) -> None:
        self.io.close()

    async def flush(self) -> None:
        await self.io.flush()

    # --- Reads (worker threads) ------------------------------------------------------------------------------------

    def root(self, create: bool = False) -> bool:
        """``root(create)``: whether the studies directory exists (created when ``create``); its parent is
        resolved again each time."""
        directory = self.io.directory
        try:
            self.io.directory = nodepath.join(nodefs.realpath(nodepath.dirname(directory)), basename(directory))
        except Exception as error:
            if not create and records.error_code(error) == 'ENOENT':
                return False
            raise
        try:
            self.io.safe_directory(self.io.directory)
            return True
        except Exception as error:
            if records.error_code(error) != 'ENOENT':
                raise
            if not create:
                return False
            self.io.ready()
            return True

    def ids_sync(self) -> list[str]:
        """``ids()``: the study directories; any other entry is 409 ``Study directory needs inspection.``."""
        if not self.root():
            return []
        rows = records.scandir(self.directory)
        for name, is_directory in rows:
            if not valid_project_id(name) or not is_directory:
                raise StudyError(DIRECTORY_INSPECTION, 409)
            self.io.safe_directory(nodepath.join(self.directory, name))
        return [name for name, _ in rows]

    def load_sync(self, id: Any) -> dict:
        """``load(id)``: the checked record, or 404 ``Study not found.``."""
        if not valid_project_id(id):
            raise StudyError(NOT_FOUND, 404)
        try:
            if not self.root():
                raise StudyError(NOT_FOUND, 404)
            folder = self.io.record_directory(id)
            value = validate_study(_parse(self.io.file(nodepath.join(folder, 'study.json'),
                                                       self.limits['metadataBytes'])))
            if not _same(value['id'], id):
                raise StudyError(NOT_FOUND, 404)
            return value
        except Exception as error:
            if records.error_code(error) == 'ENOENT':
                raise StudyError(NOT_FOUND, 404) from None
            raise

    def all_sync(self) -> list[dict]:
        """``all()``: every readable study; an interrupted, unpublished create (404) is skipped."""
        out = []
        for id in self.ids_sync():
            try:
                out.append(self.load_sync(id))
            except Exception as error:
                if _status(error) != 404:
                    raise
        return out

    def usage_sync(self) -> int:
        """``usage()``: the bytes of every file under the studies directory, which holds only study directories,
        their ``snapshots`` and the files Node names."""
        total = 0

        def walk(folder: str) -> None:
            nonlocal total
            self.io.safe_directory(folder)
            for name, _ in records.scandir(folder):
                path = nodepath.join(folder, name)
                info = lstat(path)
                directory = stat.S_ISDIR(info.st_mode)
                if stat.S_ISLNK(info.st_mode) or (not directory and (not stat.S_ISREG(info.st_mode)
                                                                     or info.st_nlink != 1)):
                    raise StudyError(UNSAFE_ENTRY, 409)
                if directory:
                    if not (name == 'snapshots' or valid_project_id(name)):
                        raise StudyError(STORAGE_INSPECTION, 409)
                    walk(path)
                else:
                    if not _STUDY_FILE.fullmatch(name):
                        raise StudyError(STORAGE_INSPECTION, 409)
                    total += info.st_size

        if self.root():
            walk(self.directory)
        return total

    def snapshot_sync(self, record: dict, entry: dict) -> tuple[Any, str]:
        """``snapshot(record, entry)``: the case's archived cache and its exact text."""
        folder = nodepath.join(self.io.record_directory(record['id']), 'snapshots')
        self.io.safe_directory(folder)
        data = self.io.file(nodepath.join(folder, _js_string(entry.get('source_sha256', UNDEFINED)) + '.json'),
                            self.limits['caseBytes'])
        if not _same(len(data), entry.get('source_bytes', UNDEFINED)) or not _same(
                _digest(data), entry.get('source_sha256', UNDEFINED)):
            raise StudyError(SNAPSHOT_CHECKSUM, 409)
        return validate_study_cache(_parse(data), entry), jsjson.decode_body(data)

    def present_sync(self, id: Any, export: bool = False) -> dict:
        """``present(id, owner, exportCache)``: the study as the browser sees it (no owner, network or identity
        hashes; each completed case with its summary; the aggregation), or the ``eeg-robustness-study-export/1``
        envelope with each case's archived cache and its exact text."""
        record = self.load_sync(id)
        study = _clone(record)
        caches = []
        for name in ('owner', 'network', 'identity_sha256'):
            study.pop(name, None)
        for entry in study['cases']:
            entry.pop('identity_sha256', None)
            entry['summary'] = None
            cache = cache_json = None
            if entry['status'] == 'completed':
                cache, cache_json = self.snapshot_sync(record, entry)
                entry['summary'] = summarize_study_case(cache.get('result', UNDEFINED))
            if export:
                source = entry.get('source_sha256')
                caches.append({'index': entry['index'], 'key': entry['key'],
                               'source_sha256': None if source is UNDEFINED else source, 'cache': cache,
                               'cache_json': cache_json})
        study['aggregation'] = aggregate_study(study['protocol'], study['cases'])
        return {'schema': EXPORT_SCHEMA, 'study': study, 'cases': caches} if export else study

    # --- Writes (worker threads, serialized) ---------------------------------------------------------------------

    def save_sync(self, record: dict) -> None:
        """``save(record)``: checked, within the metadata and total bounds, written atomically over a plain
        ``study.json`` (a link or a file with a second link there is 409)."""
        validate_study(record)
        size = len(records.json_bytes(record))
        if size > self.limits['metadataBytes']:
            raise StudyError(METADATA_SIZE, 413)
        if self.usage_sync() + size > self.limits['totalBytes']:
            raise StudyError(CAPACITY, 507)
        path = nodepath.join(self.io.record_directory(record['id']), 'study.json')
        try:
            info = lstat(path)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise StudyError(METADATA_PATH, 409)
        except OSError as error:
            if records.error_code(error) != 'ENOENT':
                raise
        records.atomic_json(path, record)

    def _create(self, prepared: dict) -> dict:
        self.root(True)
        # Node prunes week-old drafts and counts the studies here (both dropped); reading every study still fails
        # closed on an unsafe or corrupt one.
        self.all_sync()
        id, at = self.random_uuid(), self.now()
        record = {'schema': STUDY_SCHEMA, 'id': id, 'owner': self.owner, **_clone(prepared), 'status': 'draft',
                  'revision': 1, 'created_at': at, 'updated_at': at}
        validate_study(record)
        mkdir(nodepath.join(self.directory, id), 0o700)
        mkdir(nodepath.join(self.directory, id, 'snapshots'), 0o700)
        self.save_sync(record)
        return _clone(record)

    def _archive(self, id: str, index: int, data: bytes) -> Any:
        record = self.load_sync(id)
        cases = record['cases']
        entry = _case_at(cases, index)
        if not js_truthy(entry):
            raise StudyError(CASE_NOT_FOUND, 404)
        if len(data) > self.limits['caseBytes']:
            raise StudyError(SNAPSHOT_TOO_LARGE, 413)
        cache = validate_study_cache(_parse(data), entry)
        sha256 = _digest(data)
        folder = nodepath.join(self.io.record_directory(id), 'snapshots')
        self.io.safe_directory(folder)
        existing_bytes = 0
        names = [name for name, _ in records.scandir(folder)]
        if len(names) >= SNAPSHOT_FILES:
            raise StudyError(SNAPSHOT_FILE_LIMIT, 507)
        for name in names:
            item = lstat(nodepath.join(folder, name))
            if not stat.S_ISREG(item.st_mode) or item.st_nlink != 1 or not _SNAPSHOT_FILE.fullmatch(name):
                raise StudyError(SNAPSHOT_PATH, 409)
            existing_bytes += item.st_size
        path = nodepath.join(folder, sha256 + '.json')
        exists = False
        try:
            if _digest(self.io.file(path, self.limits['caseBytes'])) != sha256:
                raise StudyError(SNAPSHOT_CHECKSUM, 409)
            exists = True
        except Exception as error:
            if records.error_code(error) != 'ENOENT':
                raise
        added = 0 if exists else len(data)
        if (existing_bytes + added > self.limits['studyBytes']
                or self.usage_sync() + added > self.limits['totalBytes']):
            raise StudyError(SNAPSHOT_CAPACITY, 507)
        if not exists:
            records.atomic_bytes(path, data)
        entry['status'] = 'completed'
        entry['source_sha256'] = sha256
        entry['source_bytes'] = len(data)
        entry['error'] = None
        record['revision'] = record['revision'] + 1
        record['updated_at'] = self.now()
        self.save_sync(record)
        return _clone(cache['result'])

    # --- The coroutines ------------------------------------------------------------------------------------------

    async def _before_write(self) -> None:
        await resolve(self.before_write())

    async def ids(self) -> list[str]:
        return await asyncio.to_thread(self.ids_sync)

    async def load(self, id: Any) -> dict:
        return await asyncio.to_thread(self.load_sync, id)

    async def all(self) -> list[dict]:
        return await asyncio.to_thread(self.all_sync)

    async def usage(self) -> int:
        return await asyncio.to_thread(self.usage_sync)

    async def snapshot(self, record: dict, entry: dict) -> tuple[Any, str]:
        return await asyncio.to_thread(self.snapshot_sync, record, entry)

    async def present(self, id: Any, export: bool = False) -> dict:
        return await asyncio.to_thread(self.present_sync, id, export)

    async def save(self, record: dict) -> None:
        await asyncio.to_thread(self.save_sync, record)

    async def create(self, prepared: dict) -> dict:
        """``create(owner, prepared)``: a new draft ``{schema, id, owner, ...prepared, status, revision, created_at,
        updated_at}`` in its own directory (with ``snapshots``); returns a copy."""
        async def operation() -> dict:
            await self._before_write()
            return await asyncio.to_thread(self._create, prepared)
        return await self.io.serialize(operation)

    async def update(self, id: Any, change: Callable[[dict], Any], control: bool = False) -> dict:
        """``update(id, owner, change, {control})``: ``change(record)`` (plain or async, on the event loop) on the
        loaded record, then the next revision is saved; returns a copy. A control write skips ``before_write``:
        cancellation stops accepted work and must not need new-work admission."""
        async def operation() -> dict:
            if not control:
                await self._before_write()
            record = await asyncio.to_thread(self.load_sync, id)
            await resolve(change(record))
            record['revision'] = record['revision'] + 1
            record['updated_at'] = self.now()
            await asyncio.to_thread(self.save_sync, record)
            return _clone(record)
        return await self.io.serialize(operation)

    async def control_update(self, id: Any, change: Callable[[dict], Any]) -> dict:
        return await self.update(id, change, control=True)

    async def archive(self, id: Any, index: int, data: bytes) -> Any:
        """``archive(id, owner, index, bytes)``: the case's cache bytes, checked against the case, are kept as
        ``snapshots/<sha256>.json`` (once) and the case becomes ``completed``; returns a copy of the result."""
        async def operation() -> Any:
            await self._before_write()
            return await asyncio.to_thread(self._archive, id, index, data)
        return await self.io.serialize(operation)


# --- The service -------------------------------------------------------------------------------------------------

def _publish_links(path: str) -> int:
    """The links of a record's ``cache.json`` that B16's publish leaves beside it: ``records.publish_cache`` links its
    ``cache.json.<uuid4>.tmp`` to ``cache.json`` and removes it after a directory sync, so a read in between, or a
    crash, finds that temporary as a second link to the same file. The lookup and ``DesignJobs.stored_finish`` ignore
    it; the study counts those of the same device and inode as accepted links. Node's rename never leaves one. A link
    count of one, or a file or directory that cannot be read, counts none, and the hardened read decides."""
    try:
        info = nodefs.lstat(path)
        if info.st_nlink == 1:
            return 0
        directory = nodepath.dirname(path)
        names = nodefs.readdir(directory)
    except OSError:
        return 0
    count = 0
    for name in names:
        if _PUBLISH_TEMPORARY.fullmatch(name):
            try:
                other = nodefs.lstat(nodepath.join(directory, name))
            except OSError:
                continue  # removed since the listing: the link count fell with it
            if (other.st_dev, other.st_ino) == (info.st_dev, info.st_ino):
                count += 1
    return count


def _own_task(task: dict, entry: dict) -> bool:
    """``ownTask(task, entry, visitor)`` without owners: the workspace's design-evaluation receipt of the case's key
    and exact request."""
    return (task.get('kind') == DESIGN_KIND and task.get('key') == entry['key']
            and jsjson.stringify(task.get('request')) == jsjson.stringify(entry['request']))


def error_answer(error: BaseException) -> tuple[int, dict, dict]:
    """The middleware's catch: ``(status, {error}, headers)``. A refusal Node marks safe (``StudyError``,
    ``ProjectError``, ``ResourceError``) shows its message; anything else the generic one, logged."""
    safe = any(getattr(error, name, False) is True for name in ('study_safe', 'resource_safe', 'project_safe'))
    status = _status(error)
    if not (isinstance(status, int) and not isinstance(status, bool) and status):
        status = 500
    headers = {}
    retry = getattr(error, 'retry_after', None)
    if _resource_safe(error) and js_truthy(retry):
        headers['Retry-After'] = _js_string(retry)
    if not safe:
        _log.error('study request failed', exc_info=error)
    message = getattr(error, 'message', None)
    return status, {'error': message if safe and isinstance(message, str) else UNAVAILABLE}, headers


def study_path(path: str) -> bool:
    """Whether the middleware serves ``path`` (the path of the request target, without its query)."""
    return path == '/api/robustness-studies' or path.startswith('/api/robustness-studies/')


class RobustnessStudyService:
    """``RobustnessStudyService`` over the workspace queue ``scheduler`` (its ``design-evaluation`` adapter
    prepares the cases) and the scientific root ``root`` (``R``, whose ``results/v2/design_evaluation_jobs`` holds the
    caches a completed case is archived from).

    Built on a running event loop: the restart recovery (``ready()`` waits for it) and the poll of active studies
    (every ``poll_seconds``) start at once. ``store`` defaults to ``StudyStore(directory)``; ``clock`` gives a case's
    ``submission_started_at`` and ``random_uuid`` its operation id. ``stop()`` refuses new work and stops the poll,
    ``flush()`` waits for the studies being pumped and the store's writes, ``close()`` stops and closes the store,
    ``aclose()`` does all three.

    Coroutines (Node's methods without the visitor): ``get(id)`` -> ``{study}``, ``list()`` -> ``{studies}``,
    ``create(input)`` -> ``{study}``, ``start(id, resume=False)``, ``cancel(id)``, ``export(id)``; ``handle`` is the
    HTTP middleware after the access policy and the token check."""

    def __init__(self, scheduler: Any, root: str, *, store: Optional[StudyStore] = None,
                 directory: Optional[str] = None, before_write: Optional[Callable[[], Any]] = None,
                 poll_seconds: float = POLL_SECONDS, clock: Optional[Callable[[], str]] = None,
                 random_uuid: Optional[Callable[[], str]] = None):
        if store is None:
            if directory is None:
                raise TypeError('A study store or its directory is required.')
            store = StudyStore(directory, before_write=before_write)
        self.scheduler = scheduler
        self.root = root
        self.store = store
        self.adapter = scheduler.adapters[DESIGN_KIND]
        self.poll_seconds = poll_seconds
        self.clock = clock or _now_iso
        self.random_uuid = random_uuid or (lambda: str(uuid.uuid4()))
        self.active: dict[str, None] = {}
        self.inflight: dict[str, asyncio.Future] = {}
        self.needs_pump: set[str] = set()
        self.recovery: set[str] = set()
        self.blocked: dict[str, dict] = {}
        self.stop_requested: set[str] = set()
        self.starting = False  # Node's startReservations of the one local user
        self.closed = False
        loop = asyncio.get_running_loop()
        self.initialization = loop.create_task(self.recover())
        self.initialization.add_done_callback(_retrieve)
        self.timer: Optional[asyncio.Future] = loop.create_task(self._poll())

    async def _poll(self) -> None:
        while not self.closed:
            await asyncio.sleep(self.poll_seconds)
            for id in list(self.active):
                self.run(id)

    async def recover(self) -> None:
        """Restart recovery: a running or cancelling study is paused (``paused_recovery``; a cancelling one keeps
        ``cancel_requested``) and resumes only when asked. A resource or capacity refusal of that write leaves the
        record as it was, with the pause shown by the overlay."""
        for record in await self.store.all():
            if record['status'] in _RUNNING:
                if self.closed:
                    return
                self.recovery.add(record['id'])

                def pause(value: dict) -> None:
                    if value['status'] == 'cancelling':
                        value['cancel_requested'] = True
                    value['status'] = 'paused_recovery'
                try:
                    await self.store.update(record['id'], pause)
                except Exception as error:
                    if not _resource_safe(error) and _status(error) != 507:
                        raise

    async def ready(self) -> None:
        await asyncio.shield(self.initialization)

    def stop(self) -> None:
        self.closed = True
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        self.active.clear()

    async def flush(self) -> None:
        await self.ready()
        while self.inflight:
            await asyncio.wait(list(self.inflight.values()))
        await self.store.flush()

    def close(self) -> None:
        self.stop()
        self.store.close()

    async def aclose(self) -> None:
        """Node's dispose of the studies: stop, wait for the pumps and writes, close the store."""
        self.stop()
        try:
            await self.flush()
        except Exception:  # noqa: BLE001 - a recovery that failed has nothing left to wait for
            _log.warning('study service stopped after a failed recovery', exc_info=True)
        self.close()

    # --- Reads -------------------------------------------------------------------------------------------------------

    async def get(self, id: Any) -> dict:
        await self.ready()
        study = await self.store.present(id)
        if id in self.recovery and study['status'] in _RUNNING:
            study['status'] = 'paused_recovery'
        if id in self.blocked:
            study['status'] = 'paused_resource'
            study['last_error'] = self.blocked[id]
        return {'study': study}

    async def list(self) -> dict:
        await self.ready()
        rows = []
        for record in await self.store.all():
            id = record['id']
            rows.append({
                'id': id, 'title': record['title'], 'protocol': record['protocol'],
                'status': ('paused_resource' if id in self.blocked else
                           'paused_recovery' if id in self.recovery else record['status']),
                'created_at': record['created_at'], 'updated_at': record['updated_at'],
                'case_count': len(record['cases']),
                'completed_cases': sum(1 for entry in record['cases'] if entry['status'] == 'completed'),
            })
        return {'studies': rows}

    async def export(self, id: Any) -> dict:
        """``present(id, owner, true)``: the ``eeg-robustness-study-export/1`` envelope."""
        return await self.store.present(id, True)

    # --- Create and control ------------------------------------------------------------------------------------------

    async def create(self, raw: Any) -> dict:
        """A new draft: every case prepared (its key, and for ``heads`` its own identity hash), none submitted."""
        await self.ready()
        if self.closed:
            raise StudyError(STOPPING, 503)
        normalized = normalize_study_input(raw)
        heads = normalized['protocol'] == 'heads'
        cases = []
        identity: Optional[str] = None
        for index, request in enumerate(normalized['requests']):
            prepared = await self.adapter.prepare(request)
            current = _json_hash(_get(prepared['ctx'], 'identity'))
            # Each head adds its own package files to the identity; other protocols share one model.
            if not heads and identity is not None and current != identity:
                raise StudyError(IDENTITY_PREPARING, 409)
            identity = current
            entry = {'index': index, 'request': prepared['request'], 'key': prepared['key']}
            if heads:
                entry['identity_sha256'] = current
            entry.update({'status': 'pending', 'receipt_id': None, 'error': None})
            cases.append(entry)
        if self.closed:
            raise StudyError(STOPPING, 503)
        metadata = {name: value for name, value in normalized.items() if name != 'requests'}
        # Non-head records keep the single shared identity that older servers verify.
        record = await self.store.create({
            **metadata,
            'identity_sha256': _json_hash([entry['identity_sha256'] for entry in cases]) if heads else identity,
            'cases': cases,
        })
        return await self.get(record['id'])

    async def start(self, id: Any, resume: bool = False) -> dict:
        """``start`` (a draft) or ``resume`` (a paused study); at most one study runs at a time in the workspace."""
        await self.ready()
        if self.closed:
            raise StudyError(STOPPING, 503)
        if id in self.active:
            return await self.get(id)
        if self.starting:
            raise StudyError(ACTIVE_STUDY, 429)
        self.starting = True
        try:
            others = await self.store.all()
            if any(record['id'] != id and record['id'] in self.active for record in others):
                raise StudyError(ACTIVE_STUDY, 429)

            def begin(record: dict) -> None:
                allowed = ['paused_recovery', 'paused_resource'] if resume else ['draft']
                if resume and (id in self.recovery or id in self.blocked) and record['status'] in _RUNNING:
                    allowed.append(record['status'])
                if record['status'] not in allowed:
                    raise StudyError(START_STATE, 409)
                if record['status'] == 'cancelling':
                    record['cancel_requested'] = True
                record['status'] = 'cancelling' if js_truthy(record.get('cancel_requested', UNDEFINED)) else 'running'
                record['last_error'] = None

            started = await self.store.update(id, begin)
            self.recovery.discard(id)
            self.blocked.pop(id, None)
            if js_truthy(started.get('cancel_requested', UNDEFINED)):
                self.stop_requested.add(id)
            else:
                self.stop_requested.discard(id)
            self.active[id] = None
            self.run(id)
            return await self.get(id)
        finally:
            self.starting = False

    async def cancel(self, id: Any) -> dict:
        """Cancels the remaining cases and the receipts of submitted ones; a finished study is left as it is. A
        control write: it needs no new-work admission."""
        await self.ready()
        if self.closed:
            raise StudyError(STOPPING, 503)
        before = await self.store.load(id)
        if before['status'] in _PARENT_DONE:
            self.recovery.discard(id)
            self.blocked.pop(id, None)
            return await self.get(id)
        self.stop_requested.add(id)

        def request(record: dict) -> None:
            if record['status'] in _PARENT_DONE:
                return
            record['cancel_requested'] = True
            record['status'] = 'cancelling'
            for entry in record['cases']:
                if entry['status'] == 'pending':
                    entry['status'] = 'cancelled'

        await self.store.control_update(id, request)
        self.recovery.discard(id)
        self.blocked.pop(id, None)
        record = await self.store.load(id)
        try:
            for entry in record['cases']:
                if js_truthy(entry.get('receipt_id')) and not terminal_case(entry['status']):
                    await self.cancel_child(id, entry)
        except Exception as error:
            if not _resource_safe(error) and _status(error) != 507:
                raise
            self.active.pop(id, None)
            self.blocked[id] = safe_failure('resource_unavailable', CANCEL_PAUSED)
            return await self.get(id)
        self.active[id] = None
        self.run(id)
        return await self.get(id)

    # --- The pump ----------------------------------------------------------------------------------------------------

    def run(self, id: str) -> None:
        """``run(id)``: pump the study in the background, once at a time; a failure pauses it (``blocked``)."""
        if self.closed:
            return
        if id in self.inflight:
            self.needs_pump.add(id)
            return

        async def pump() -> None:
            try:
                await self.pump(id)
            except Exception as error:  # noqa: BLE001 - Node's catch: the study pauses for inspection
                _log.warning('study %s paused', id, exc_info=error)
                self.active.pop(id, None)
                self.blocked[id] = safe_failure(
                    'resource_unavailable' if _resource_safe(error) else 'study_storage_unavailable', PAUSED)

        def settled(_: asyncio.Future) -> None:
            self.inflight.pop(id, None)
            again = id in self.needs_pump
            self.needs_pump.discard(id)
            if again and id in self.active and not self.closed:
                self.run(id)

        task = asyncio.ensure_future(pump())
        task.add_done_callback(settled)
        self.inflight[id] = task

    async def set_case(self, id: str, index: int, change: dict, control: bool = False) -> dict:
        """``setCase``: ``Object.assign(record.cases[index], change)``."""
        return await self.store.update(id, lambda record: _case_at(record['cases'], index).update(change),
                                       control=control)

    def cache_bytes(self, entry: dict) -> bytes:
        """``cache(entry)``: the exact bytes of the case's ``cache.json`` under the real root, every directory on the
        way a plain one, the file checked as a snapshot is (B16's temporaries of it allowed as further links,
        ``_publish_links``), and bound to the case (``validate_study_cache``)."""
        root = nodefs.realpath(self.root)
        path = nodepath.join(root, DESIGN_RECORDS, entry['key'], 'cache.json')
        cursor = root
        for part in _PATH_PARTS.split(nodepath.relative(root, nodepath.join(path, '..'))):
            cursor = nodepath.join(cursor, part)
            self.store.io.safe_directory(cursor)
        data = self.store.io.file(path, self.store.limits['caseBytes'], 1 + _publish_links(path))
        validate_study_cache(_parse(data), entry)
        return data

    async def finish_cache(self, id: str, entry: dict) -> None:
        try:
            data = await asyncio.to_thread(self.cache_bytes, entry)
        except Exception as error:
            if _resource_safe(error) or _status(error) == 507:
                raise
            await self.set_case(id, entry['index'], {
                'status': 'failed', 'error': safe_failure('scientific_cache_invalid', CACHE_INVALID)})
            return
        await self.store.archive(id, entry['index'], data)

    async def reconcile(self, id: str, entry: dict, cancelling: bool = False) -> None:
        """A ``submitting`` case after a restart: the newest receipt of its request and key (a pending one, else a
        completed one, else the newest), or else a verified stored cache; otherwise ``failed_uncertain`` (or
        ``cancelled``), never resubmitted."""
        tasks = sorted((task for task in self.scheduler.tasks if _own_task(task, entry)),
                       key=lambda task: task['sequence'], reverse=True)
        task = (next((value for value in tasks if value['status'] in _RECEIPT_PENDING), None)
                or next((value for value in tasks if value['status'] == 'completed'), None)
                or (tasks[0] if tasks else None))
        if task is not None:
            status = task['status']
            await self.set_case(id, entry['index'], {
                'receipt_id': task['id'],
                'status': ('running' if status == 'completed' else status if status in _RECEIPT_PENDING
                           else 'cancelled' if status == 'cancelled' else 'failed'),
                'error': None,
            }, cancelling)
            if task['status'] == 'completed':
                await self.finish_cache(id, entry)
            if cancelling and task['status'] in _RECEIPT_PENDING:
                await self.cancel_child(id, {**entry, 'receipt_id': task['id']})
            return
        try:
            data = await asyncio.to_thread(self.cache_bytes, entry)
        except Exception as error:
            if _resource_safe(error) or _status(error) == 507:
                raise
            await self.set_case(id, entry['index'], {
                'status': 'cancelled' if cancelling else 'failed_uncertain',
                'error': safe_failure('submission_outcome_unknown', OUTCOME_UNKNOWN),
            }, cancelling)
            return
        await self.store.archive(id, entry['index'], data)

    async def pump(self, id: str) -> None:
        while not self.closed:
            record = await self.store.load(id)
            if id in self.stop_requested and record['status'] == 'running':
                return
            if record['status'] not in _RUNNING:
                self.active.pop(id, None)
                return
            entry = next((value for value in record['cases'] if not terminal_case(value['status'])), None)
            if entry is None:
                def finish(value: dict) -> None:
                    value['status'] = (
                        'cancelled' if js_truthy(value.get('cancel_requested', UNDEFINED))
                        or value['status'] == 'cancelling' else
                        'completed_with_failures' if any(row['status'] != 'completed' for row in value['cases'])
                        else 'completed')
                await self.store.update(id, finish, control=(record['status'] == 'cancelling'
                                                             or record.get('cancel_requested') is True))
                self.active.pop(id, None)
                return
            index = int(entry['index'])  # a checked record: the case's position
            if entry['status'] == 'submitting':
                await self.reconcile(id, entry, record['status'] == 'cancelling')
                continue
            if entry['status'] == 'pending':
                if record['status'] == 'cancelling':
                    await self.set_case(id, index, {'status': 'cancelled'}, True)
                    continue
                prepared = await self.adapter.prepare(entry['request'])
                if self.closed:
                    return
                # Only head cases carry their own identity; others share the record identity.
                expected = entry.get('identity_sha256')
                if expected is None or expected is UNDEFINED:
                    expected = record['identity_sha256']
                if prepared['key'] != entry['key'] or _json_hash(_get(prepared['ctx'], 'identity')) != expected:
                    def fail(value: dict) -> None:
                        for row in value['cases']:
                            if row['status'] == 'pending':
                                row['status'] = 'failed'
                                row['error'] = safe_failure('scientific_identity_changed', IDENTITY_CHANGED)
                    await self.store.update(id, fail)
                    continue
                authorized = False

                def authorize(value: dict) -> None:
                    nonlocal authorized
                    if (self.closed or id in self.stop_requested or value['status'] != 'running'
                            or value['cases'][index]['status'] != 'pending'):
                        return
                    authorized = True
                    value['cases'][index].update({'status': 'submitting', 'operation_id': self.random_uuid(),
                                                  'submission_started_at': self.clock()})

                await self.store.update(id, authorize)
                if not authorized:
                    continue
                if self.closed:
                    return
                annotation = record['annotation']
                raw = ({'schema': SUBMISSION_SCHEMA, 'request': entry['request'], **annotation}
                       if js_truthy(_get(annotation, 'electrode_names')) else entry['request'])
                try:
                    result = await self.scheduler.submit(
                        DESIGN_KIND, raw, False, entry['key'],
                        lambda: not self.closed and id not in self.stop_requested)
                except Exception as error:
                    if getattr(error, 'study_admission_cancelled', False):
                        if self.closed and id not in self.stop_requested:
                            def interrupted(value: dict) -> None:
                                value['status'] = 'paused_recovery'
                                value['cases'][index]['status'] = 'pending'
                            await self.store.update(id, interrupted)
                            return
                        await self.set_case(id, index, {'status': 'cancelled', 'error': None}, True)
                        continue
                    if getattr(error, 'admission_rejected', False) or _status(error) == 429 or _resource_safe(error):
                        def defer(value: dict) -> None:
                            value['status'] = 'paused_resource'
                            value['last_error'] = safe_failure('submission_deferred', DEFERRED)
                            value['cases'][index].update({'status': 'pending', 'error': value['last_error']})
                        await self.store.update(id, defer)
                    else:
                        _log.warning('study %s: submission without a confirmed receipt', id, exc_info=error)

                        def uncertain(value: dict) -> None:
                            value['status'] = 'paused_recovery'
                            value['last_error'] = safe_failure('submission_uncertain', UNCERTAIN)
                        await self.store.update(id, uncertain)
                    self.active.pop(id, None)
                    return
                job = _get(result, 'job')
                if not _same(_get(job, 'key'), entry['key']) or not valid_project_id(_get(job, 'id')):
                    raise StudyError(RECEIPT_MISMATCH, 409)
                status = _get(job, 'status')
                change = {'receipt_id': job['id'], 'status': 'running' if status == 'completed' else status}
                if js_truthy(_get(job, 'annotation_id')):
                    change['annotation_id'] = job['annotation_id']
                change['error'] = None
                await self.set_case(id, index, change)
                latest = await self.store.load(id)
                if latest['status'] == 'cancelling':
                    await self.cancel_child(id, {**entry, 'receipt_id': job['id']})
                elif status == 'completed':
                    await self.finish_cache(id, entry)
                continue
            try:
                task = self.scheduler.own(entry['receipt_id'], DESIGN_KIND)
            except Exception as error:
                if _status(error) != 404:
                    raise
                await self.set_case(id, index, {
                    'status': 'cancelled', 'error': safe_failure('subscription_removed', SUBSCRIPTION_REMOVED)})
                continue
            if task['status'] == 'completed':
                await self.finish_cache(id, entry)
                continue
            if task['status'] == 'failed' and task.get('message') == INTERRUPTED_MESSAGE:
                # The original worker may have durably saved its full cache before its receipt's final state
                # reached disk. Recover that exact result only.
                await self.finish_cache(id, entry)
                continue
            if task['status'] in ('failed', 'timeout', 'cancelled', 'no_layout'):
                message = task.get('message')
                await self.set_case(id, index, {
                    'status': 'cancelled' if task['status'] == 'cancelled' else 'failed',
                    'error': safe_failure('child_' + task['status'],
                                          message if js_truthy(message) else task['status']),
                })
                continue
            if entry['status'] != task['status']:
                await self.set_case(id, index, {'status': task['status']})
            return

    async def cancel_child(self, id: str, entry: dict) -> None:
        index = entry['index']
        try:
            job = await self.scheduler.cancel(entry['receipt_id'], DESIGN_KIND)
        except Exception as error:
            if _status(error) != 404:
                raise
            await self.set_case(id, index, {
                'status': 'cancelled', 'error': safe_failure('subscription_removed', SUBSCRIPTION_REMOVED)}, True)
            return
        status = _get(job, 'status')
        if status == 'completed':
            await self.finish_cache(id, entry)
        elif status in ('failed', 'timeout', 'no_layout'):
            message = _get(job, 'message')
            await self.set_case(id, index, {
                'status': 'failed', 'error': safe_failure('child_' + status, message if js_truthy(message) else status),
            }, True)
        else:
            await self.set_case(id, index, {'status': 'cancelling' if status == 'cancelling' else 'cancelled',
                                            'error': None}, True)

    # --- HTTP ----------------------------------------------------------------------------------------------------

    async def body(self, content_type: Optional[str], chunks: Union[bytes, AsyncIterable[bytes]]) -> Any:
        """``body(req)``: a JSON body of at most 65,536 bytes as received (415 ``JSON is required.``, 413 ``Study
        request is too large.`` as soon as the bound is passed, 400 ``Invalid study JSON.``). ``chunks`` is the body,
        or an async iterator of its chunks (``Request.stream()``)."""
        if not (content_type if isinstance(content_type, str) else 'undefined').startswith('application/json'):
            raise StudyError(JSON_REQUIRED, 415)
        data = bytearray()
        if isinstance(chunks, (bytes, bytearray)):
            data += chunks
            if len(data) > BODY_LIMIT:
                raise StudyError(TOO_LARGE, 413)
        else:
            async for chunk in chunks:
                data += chunk
                if len(data) > BODY_LIMIT:
                    raise StudyError(TOO_LARGE, 413)
        try:
            return _parse(bytes(data))
        except Exception:  # noqa: BLE001 - any parse failure, as Node's catch
            raise StudyError(INVALID_JSON) from None

    async def handle(self, method: str, path: str, *, query: bool = False, content_type: Optional[str] = None,
                     body: Union[bytes, AsyncIterable[bytes]] = b'') -> tuple[int, Any, dict]:
        """The middleware (service.mjs:601-657) after the access policy and, for a POST, the token: ``(status,
        value, headers)`` for ``method`` on ``path`` (the raw path, which ``study_path`` accepts), with ``query`` true
        when the target had a query. GET and POST ``/api/robustness-studies`` list and create (201); ``GET
        /<id>`` and ``/<id>/export``; ``POST /<id>/{start,resume,cancel}`` with exactly an empty object."""
        try:
            if query:
                raise StudyError(QUERIES)
            if method not in ('GET', 'POST'):
                return 405, {'error': METHOD}, {}
            if path == '/api/robustness-studies':
                if method == 'GET':
                    return 200, await self.list(), {}
                return 201, await self.create(await self.body(content_type, body)), {}
            match = _STUDY_PATH.fullmatch(path)
            if match is None or not valid_project_id(match[1]):
                raise StudyError(NOT_FOUND, 404)
            id, action = match[1], match[2]
            await self.store.load(id)
            if method == 'GET' and not action:
                return 200, await self.get(id), {}
            if method == 'GET' and action == 'export':
                return 200, await self.export(id), {}
            if method == 'POST' and action in ('start', 'resume', 'cancel'):
                value = await self.body(content_type, body)
                if not js_truthy(value) or isinstance(value, list) or _object_keys(value):
                    raise StudyError(CONTROL_BODY)
                answer = await self.cancel(id) if action == 'cancel' else await self.start(id, action == 'resume')
                return 200, answer, {}
            return 405, {'error': OPERATION}, {}
        except Exception as error:  # noqa: BLE001 - the middleware's catch
            return error_answer(error)


def _retrieve(task: asyncio.Future) -> None:
    """``initialization.catch(() => {})``: a failed recovery is raised by ``ready()``, never reported unhandled."""
    if not task.cancelled():
        task.exception()
