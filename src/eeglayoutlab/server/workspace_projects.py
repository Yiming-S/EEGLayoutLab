"""Research projects of the workspace: Node's ``ProjectStore`` (``webapp/server/projects/store.mjs``) and
``ProjectService`` (``projects/service.mjs:18-142``), statement by statement, for the one local user (design 0001,
phase 2, slice 9).

A project (``research-project/1``) is a title, a researcher's name, notes, a revision and up to 100 entries, each a
frozen snapshot (``research-project-snapshot/1``) of one scientific result: a library layout (with, for a named
evaluation, its electrode-name annotation), an editor evaluation or a signal-reception result. Optional comparison
settings (``workflow``) name two saved layouts and a ``/decision?`` link to their comparison.

Storage (``W/projects``, never Node's ``R/results/web-service/projects``)::

    W/projects/<uuid4>/project.json              research-project/1, JSON.stringify bytes
    W/projects/<uuid4>/snapshots/<sha256>.json   a snapshot's JSON.stringify bytes (their SHA-256)

``ProjectStore`` reads and writes it through ``server.workspace_files`` (no links, one link per file,
``O_NOFOLLOW``, the device and inode checked again, atomic writes) and fails closed with Node's statuses and messages:
metadata that fails ``validate_record`` (Node's ``validateRecord``) is 409 ``Project metadata failed integrity
checks.``; a snapshot whose bytes, size, digest or identity no longer match its entry is 409; a file in
``snapshots`` that is neither ``<sha256>.json`` nor its ``.<uuid4>.tmp`` temporary is 409. The bounds are Node's:
16 MiB per snapshot, 100 entries, 128 MiB of snapshots per project (entries and stored files), 512 KiB of metadata.
Writes are serialized in call order; a change names the revision it replaces (409 ``Project changed. Reload it
before saving.`` otherwise) and increments it. Detaching an entry never deletes its snapshot.

``ProjectService`` resolves a new entry's snapshot from the workspace's records: a completed library layout
(``Library.get``, its bundle by ``jobs.bundle.experiment_bundle``), a completed editor evaluation (``EditorJobs``: its
cache re-hashed and validated), or a completed signal-reception receipt of the queue (its saved result through the
adapter), with the electrode-name annotation it names; ``handle`` is the HTTP middleware after the access policy.

Differences from Node, deliberate (plan, slice 9):

- One local user: the store takes no credential and every caller is the owner (``role`` ``'owner'``). A new project's
  ``owner_key_hash`` is the SHA-256 of a fresh random key that is never stored or returned, ``viewer_key_hash`` is
  ``null`` and there is no ``creator_network``; ``create`` still answers with ``access_key``, another fresh random
  key that is not stored, so the unchanged interface keeps working. ``X-EEG-Project-Key`` is ignored; ``share`` and
  ``revoke-share`` are 404 ``Project endpoint not found.``. The library visibility check (``readable``) and the
  per-browser rate and receipt ownership are not ported.
- ``GET /api/projects`` lists the workspace's projects (Node has no list): ``{projects: [{id, title, owner_name,
  revision, created_at, updated_at, entry_count}]}``, most recently updated first. A directory without
  ``project.json`` (an interrupted create) is skipped; any other unreadable project refuses the list.
- No pruning of unused projects and no count caps (1,000 projects, 30 per network); the size bounds are kept.
- ``validate_record`` accepts creation and update times that are ISO 8601 date-time strings
  (``workspace_studies.iso_date_finite``), as slice 8's studies do; every time the store writes is ``toISOString()``.
- File work runs in worker threads, one serialized write at a time; the clock, the identifiers and the random keys
  can be injected.
"""
from __future__ import annotations

import asyncio
import datetime
import hashlib
import inspect
import logging
import re
import secrets
import stat
from typing import Any, AsyncIterable, Awaitable, Callable, Optional, Union
import uuid

from ..jobs import nodepath, records
from ..schemas import jsjson
from ..schemas.projects import (ATTACHMENT_FIELDS, ENTRY_KINDS, ENTRY_PATCH_FIELDS, NOTES_UNITS, OWNER_UNITS,
                                PATCH_FIELDS, CREATE_FIELDS, PROJECT_SCHEMA, SNAPSHOT_SCHEMA, TITLE_UNITS, UNDEFINED,
                                ProjectRequestError, attachment, coalesce, defined, fields, is_object, js_string,
                                revision, safe_integer, same, sha_test, string_to_number, text, truthy, valid_uuid,
                                workflow)
from .workspace_files import SHA, ProjectError, WorkspaceFiles, lstat, mkdir

__all__ = [
    'PROJECTS', 'PROJECT_LIMITS', 'BODY_LIMIT', 'ProjectStore', 'ProjectService', 'validate_record',
    'public_project', 'error_answer', 'project_path',
]

PROJECTS = 'projects'  # W/projects
PROJECT_LIMITS = {'entries': 100, 'snapshot_bytes': 16 * 1024 * 1024, 'project_bytes': 128 * 1024 * 1024,
                  'metadata_bytes': 512 * 1024}
BODY_LIMIT = 65536
COMPARISON_DATASETS = ('cache', 'strict_area', 'design_evaluation')
SIGNAL_SCHEMAS = ('source-reception/1', 'source-reception/2')
SIGNAL_SUMMARY = ('brain_region', 'brain_regions', 'source_index', 'seed')

# Node's messages, verbatim. The store's:
NOT_FOUND = 'Project not found.'
INTEGRITY = 'Project metadata failed integrity checks.'
METADATA_SIZE = 'Project metadata is too large.'
METADATA_PATH = 'Project metadata path is invalid.'
CHANGED = 'Project changed. Reload it before saving.'
INVALID_SNAPSHOT = 'Invalid scientific snapshot.'
SNAPSHOT_SIZE = 'Scientific snapshot exceeds the project size limit.'
ENTRY_LIMIT = 'Project entry or storage limit reached.'
DUPLICATE = 'This scientific result is already saved in the project.'
UNEXPECTED_FILE = 'Unexpected scientific snapshot file.'
SNAPSHOT_PATH = 'Scientific snapshot path is invalid.'
STORAGE_LIMIT = 'Project snapshot storage limit reached.'
SNAPSHOT_INTEGRITY = 'Scientific snapshot failed integrity checks.'
SNAPSHOT_MISSING = 'Scientific snapshot is missing.'
SNAPSHOT_IDENTITY = 'Scientific snapshot identity mismatch.'
ELECTRODE_NAMES = 'Project electrode names failed integrity checks.'
INVALID_ENTRY_ID = 'Invalid project entry identifier.'
NO_ENTRY_CHANGES = 'No entry changes supplied.'
NO_PROJECT_CHANGES = 'No project changes supplied.'
ENTRY_NOT_FOUND = 'Project entry not found.'
EXPORT_SIZE = 'Project export exceeds the size limit.'
STOPPING = 'Project store is stopping.'
# The service's:
CHOOSE_LAYOUT = 'Choose a completed layout evaluation.'
EDIT_NOT_FOUND = 'Completed electrode edit not found.'
EDIT_INTEGRITY = 'Electrode edit failed integrity checks.'
SIGNAL_INCOMPLETE = 'Only completed signal results can be saved.'
SIGNAL_INTEGRITY = 'Saved signal result failed integrity checks.'
RECORD_IDENTITY = 'Scientific record identity is invalid.'
ANNOTATION_UNAVAILABLE = 'Electrode name annotation is unavailable.'
JSON_REQUIRED = 'JSON is required.'
TOO_LARGE = 'Project request is too large.'
INVALID_JSON = 'Invalid project JSON.'
METHOD = 'Unsupported project method.'
QUERY = 'Project API credentials and parameters must not use a query string.'
OPENED_WITH_ID = 'Projects are opened with their identifier and credential.'
ENDPOINT = 'Project endpoint not found.'
OPERATION = 'Unsupported project operation.'
UNAVAILABLE = 'Project storage or scientific record is unavailable.'

_FINAL_SNAPSHOT = re.compile(r'[a-f0-9]{64}\.json')
_TEMPORARY_SNAPSHOT = re.compile(r'[a-f0-9]{64}\.json\.[a-f0-9-]{36}\.tmp')
_PROJECT_PATH = re.compile(r'/api/projects/([a-f0-9-]{36})(?:/(share|revoke-share|entries|export)(?:/([a-f0-9-]{36}))?)?')
_WORKFLOW_DEFAULT = {'reference_entry_id': None, 'candidate_entry_id': None, 'comparison_href': None}

_log = logging.getLogger(__name__)


# --- JavaScript values -------------------------------------------------------------------------------------------

def _clone(value: Any) -> Any:
    """``JSON.parse(JSON.stringify(value))`` of parsed JSON (tuples become lists, ``UNDEFINED`` members are left
    out)."""
    if isinstance(value, dict):
        return {key: _clone(item) for key, item in value.items() if item is not UNDEFINED}
    if isinstance(value, (list, tuple)):
        return [None if item is UNDEFINED else _clone(item) for item in value]
    return value


def _get(value: Any, key: str) -> Any:
    """``value.key``: ``UNDEFINED`` when absent or when ``value`` is a primitive, an array or a string; ``null`` and
    ``undefined`` throw JavaScript's ``TypeError``."""
    if value is None or value is UNDEFINED:
        raise TypeError(f"Cannot read properties of {'null' if value is None else 'undefined'} (reading '{key}')")
    if isinstance(value, dict):
        return value.get(key, UNDEFINED)
    if key == 'length' and isinstance(value, (list, tuple, str)):
        return _length(value)
    return UNDEFINED


def _optional(value: Any, key: str) -> Any:
    """``value?.key``."""
    return UNDEFINED if value is None or value is UNDEFINED else _get(value, key)


def _length(value: Any) -> Any:
    """``value.length``."""
    if isinstance(value, (list, tuple)):
        return len(value)
    if isinstance(value, str):
        return len(value.encode('utf-16-le', errors='surrogatepass')) // 2
    return _get(value, 'length')


def _defined(*members: tuple[str, Any]) -> dict:
    """An object literal as ``JSON.stringify`` writes it: members whose value is ``undefined`` are left out."""
    return {key: value for key, value in members if value is not UNDEFINED}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash(value: Any) -> str:
    """``createHash('sha256').update(JSON.stringify(value))``; ``undefined`` throws as ``update(undefined)`` does."""
    if value is UNDEFINED:
        raise TypeError('The "data" argument must be of type string or an instance of Buffer, TypedArray, or DataView. '
                        'Received undefined')
    return jsjson.sha256_hex(value)


def _now_iso() -> str:
    """``new Date().toISOString()``."""
    moment = datetime.datetime.now(datetime.timezone.utc)
    return moment.strftime('%Y-%m-%dT%H:%M:%S.') + f'{moment.microsecond // 1000:03d}Z'


def _date_finite(value: Any) -> bool:
    from .workspace_studies import iso_date_finite  # here: that module imports job modules

    return iso_date_finite(value)


def _status(error: BaseException) -> Any:
    return getattr(error, 'status', None)


# --- Records -----------------------------------------------------------------------------------------------------

def public_project(record: dict) -> dict:
    """``publicProject(record)``: the metadata without credentials, with the comparison settings (all ``null`` when
    the project has none)."""
    keys = ('schema', 'id', 'title', 'owner_name', 'notes', 'revision', 'created_at', 'updated_at', 'entries')
    out = {key: record.get(key, UNDEFINED) for key in keys}
    out['workflow'] = coalesce(record.get('workflow'), _WORKFLOW_DEFAULT)
    return _clone(out)


def validate_record(record: Any, id: Any) -> Any:
    """``validateRecord(record, id)``: every failure is 409 ``Project metadata failed integrity checks.``."""
    try:
        if (not is_object(record) or not same(record.get('schema', UNDEFINED), PROJECT_SCHEMA)
                or not same(record.get('id', UNDEFINED), id) or not sha_test(record.get('owner_key_hash', UNDEFINED))
                or 'viewer_key_hash' not in record
                or not (record['viewer_key_hash'] is None or sha_test(record['viewer_key_hash']))
                or not isinstance(record.get('entries'), list) or len(record['entries']) > PROJECT_LIMITS['entries']):
            raise ValueError()
        text(record.get('title', UNDEFINED), 'project title', TITLE_UNITS, True)
        text(record.get('owner_name', UNDEFINED), 'researcher name', OWNER_UNITS, True)
        text(record.get('notes', UNDEFINED), 'project notes', NOTES_UNITS)
        revision(record.get('revision', UNDEFINED))
        if not all(isinstance(value, str) and _date_finite(value)
                   for value in (record.get('created_at'), record.get('updated_at'))):
            raise ValueError()
        ids: set = set()
        total = 0
        for entry in record['entries']:
            if not isinstance(entry, dict):
                raise ValueError()
            if defined(entry, 'annotation_id') and (not same(entry.get('kind'), 'layout')
                                                    or not sha_test(entry['annotation_id'])):
                raise ValueError()
            if (not valid_uuid(entry.get('id')) or entry['id'] in ids
                    or not (isinstance(entry.get('kind'), str) and entry['kind'] in ENTRY_KINDS)
                    or not sha_test(entry.get('record_id', UNDEFINED)) or not sha_test(entry.get('snapshot_sha256', UNDEFINED))
                    or not safe_integer(entry.get('snapshot_bytes')) or entry['snapshot_bytes'] < 2
                    or entry['snapshot_bytes'] > PROJECT_LIMITS['snapshot_bytes'] or not is_object(entry.get('summary'))):
                raise ValueError()
            ids.add(entry['id'])
            total += entry['snapshot_bytes']
            text(entry.get('title', UNDEFINED), 'entry title', TITLE_UNITS, True)
            text(entry.get('notes', UNDEFINED), 'entry notes', NOTES_UNITS)
            if not (isinstance(entry.get('created_at'), str) and _date_finite(entry['created_at'])):
                raise ValueError()
        if total > PROJECT_LIMITS['project_bytes']:
            raise ValueError()
        if defined(record, 'workflow'):
            workflow(record['workflow'], record['entries'])
        if defined(record, 'creator_network') and not sha_test(record['creator_network']):
            raise ValueError()
    except Exception:  # noqa: BLE001 - Node's catch: any failure, a TypeError included
        raise ProjectError(INTEGRITY, 409) from None
    return record


def _validate_annotation(snapshot: dict, id: Any) -> None:
    """``validateAnnotation(snapshot, id)``: a layout snapshot carries exactly the annotation its entry names."""
    from ..jobs.annotations import validate_electrode_annotation  # here: building the application loads no job module

    annotation = snapshot.get('electrode_annotation', UNDEFINED)
    if id is UNDEFINED and annotation is UNDEFINED:
        return
    try:
        if not same(snapshot.get('kind'), 'layout') or not sha_test(id) or not same(_optional(annotation, 'id'), id):
            raise ValueError()
        validate_electrode_annotation(annotation, snapshot.get('record_id'))
    except Exception:  # noqa: BLE001 - Node's catch
        raise ProjectError(ELECTRODE_NAMES, 409) from None


async def _failed(error: BaseException) -> Any:
    """A promise rejected with ``error``."""
    raise error


# --- Store -------------------------------------------------------------------------------------------------------

class ProjectStore:
    """``ProjectStore(directory, {now})`` without credentials. ``now()`` gives every time written (``toISOString``),
    ``random_uuid()`` a project's and an entry's identifier, ``random_key()`` the random keys of ``create`` (64 hex
    digits each).

    Reads are coroutines: ``get(id)`` -> ``{project, role}``, ``list()`` -> ``{projects}``, ``get_entry(id, entry_id)``
    -> ``{entry, snapshot}``, ``read_snapshots(id, max_bytes=...)`` -> ``{project, role, entries: [{entry, snapshot,
    snapshot_json}]}``. Writes are called as Node calls them, on the running event loop: ``create(input)``,
    ``patch(id, input)``, ``attach(id, input, snapshot, summary)``, ``patch_entry(id, entry_id, input)`` and
    ``detach(id, entry_id, expected_revision)`` check their input at once (raising where Node throws synchronously),
    register their write in call order, and return an awaitable of ``{project, role, ...}`` (with ``access_key`` for
    a new project, ``entry`` for a new or changed entry). ``close()`` refuses new writes (503), ``flush()`` waits for
    the accepted ones."""

    def __init__(self, directory: str, *, now: Optional[Callable[[], str]] = None,
                 random_uuid: Optional[Callable[[], str]] = None, random_key: Optional[Callable[[], str]] = None):
        self.io = WorkspaceFiles(directory)
        self.now = now if now is not None else _now_iso
        self.random_uuid = random_uuid if random_uuid is not None else (lambda: str(uuid.uuid4()))
        self.random_key = random_key if random_key is not None else (lambda: secrets.token_hex(32))

    @property
    def directory(self) -> str:
        return self.io.directory

    @property
    def closed(self) -> bool:
        return self.io.closed

    @property
    def pending_writes(self) -> int:
        return self.io.pending_writes

    def close(self) -> None:
        self.io.close()

    async def flush(self) -> None:
        await self.io.flush()

    # --- Reads ---------------------------------------------------------------------------------------------------

    def load_sync(self, id: Any) -> dict:
        """``load(id)``: the validated record; 404 ``Project not found.`` for a missing project."""
        try:
            self.io.ready()
            directory = self.io.record_directory(id)
            try:
                value = jsjson.parse(jsjson.decode_body(
                    self.io.file(nodepath.join(directory, 'project.json'), PROJECT_LIMITS['metadata_bytes'])))
            except Exception as error:  # noqa: BLE001 - Node's catch
                if getattr(error, 'project_safe', False) or records.error_code(error) == 'ENOENT':
                    raise
                raise ProjectError(INTEGRITY, 409) from None
            return validate_record(value, id)
        except Exception as error:  # noqa: BLE001 - Node's catch
            if records.error_code(error) == 'ENOENT':
                raise ProjectError(NOT_FOUND, 404) from None
            raise

    def snapshot_sync(self, record: dict, entry: dict) -> dict:
        """``snapshot(record, entry)``: ``{snapshot, snapshot_json}`` of an entry, its bytes, digest and identity
        checked."""
        directory = self.io.record_directory(record['id'])
        snapshots = nodepath.join(directory, 'snapshots')
        self.io.safe_directory(snapshots)
        try:
            data = self.io.file(nodepath.join(snapshots, f"{js_string(entry['snapshot_sha256'])}.json"),
                                PROJECT_LIMITS['snapshot_bytes'])
        except Exception as error:  # noqa: BLE001 - Node's catch
            if records.error_code(error) == 'ENOENT':
                raise ProjectError(SNAPSHOT_MISSING, 409) from None
            raise
        if not same(len(data), entry['snapshot_bytes']) or not same(_digest(data), entry['snapshot_sha256']):
            raise ProjectError(SNAPSHOT_INTEGRITY, 409)
        text_value = jsjson.decode_body(data)
        try:
            value = jsjson.parse(text_value)
        except Exception:  # noqa: BLE001 - Node's catch
            raise ProjectError(SNAPSHOT_INTEGRITY, 409) from None
        if (not same(_get(value, 'schema'), SNAPSHOT_SCHEMA) or not same(_get(value, 'kind'), entry['kind'])
                or not same(_get(value, 'record_id'), entry['record_id']) or not is_object(_get(value, 'payload'))):
            raise ProjectError(SNAPSHOT_IDENTITY, 409)
        _validate_annotation(value, entry.get('annotation_id', UNDEFINED))
        return {'snapshot': value, 'snapshot_json': text_value}

    def get_sync(self, id: Any) -> dict:
        return {'project': public_project(self.load_sync(id)), 'role': 'owner'}

    def list_sync(self) -> dict:
        """The workspace's projects, most recently updated first."""
        self.io.ready()
        self.io.safe_directory(self.io.directory)
        rows = []
        for name, _ in records.scandir(self.io.directory):
            if not valid_uuid(name):
                continue
            try:
                record = self.load_sync(name)
            except Exception as error:  # noqa: BLE001
                if _status(error) == 404:
                    continue  # an interrupted create: its directory has no project.json yet
                raise
            rows.append({'id': record['id'], 'title': record['title'], 'owner_name': record['owner_name'],
                         'revision': record['revision'], 'created_at': record['created_at'],
                         'updated_at': record['updated_at'], 'entry_count': len(record['entries'])})
        rows.sort(key=lambda row: row['id'])
        rows.sort(key=lambda row: row['updated_at'], reverse=True)
        return {'projects': rows}

    def get_entry_sync(self, id: Any, entry_id: Any) -> dict:
        if not valid_uuid(entry_id):
            raise ProjectError(INVALID_ENTRY_ID)
        record = self.load_sync(id)
        entry = next((value for value in record['entries'] if same(value.get('id'), entry_id)), None)
        if entry is None:
            raise ProjectError(ENTRY_NOT_FOUND, 404)
        return {'entry': _clone(entry), 'snapshot': self.snapshot_sync(record, entry)['snapshot']}

    def read_snapshots_sync(self, id: Any, max_bytes: Any = PROJECT_LIMITS['project_bytes']) -> dict:
        record = self.load_sync(id)
        total = sum(entry['snapshot_bytes'] for entry in record['entries'])
        if not safe_integer(max_bytes) or max_bytes < 1 or total > max_bytes:
            raise ProjectError(EXPORT_SIZE, 413)
        # Sequential reads keep peak memory bounded and preserve the saved order.
        entries = [{'entry': _clone(entry), **self.snapshot_sync(record, entry)} for entry in record['entries']]
        return {'project': public_project(record), 'role': 'owner', 'entries': entries}

    async def load(self, id: Any) -> dict:
        return await asyncio.to_thread(self.load_sync, id)

    async def snapshot(self, record: dict, entry: dict) -> dict:
        return await asyncio.to_thread(self.snapshot_sync, record, entry)

    async def get(self, id: Any) -> dict:
        return await asyncio.to_thread(self.get_sync, id)

    async def list(self) -> dict:
        return await asyncio.to_thread(self.list_sync)

    async def get_entry(self, id: Any, entry_id: Any) -> dict:
        return await asyncio.to_thread(self.get_entry_sync, id, entry_id)

    async def read_snapshots(self, id: Any, max_bytes: Any = PROJECT_LIMITS['project_bytes']) -> dict:
        return await asyncio.to_thread(self.read_snapshots_sync, id, max_bytes)

    # --- Writes --------------------------------------------------------------------------------------------------

    def save_sync(self, record: dict) -> None:
        """``save(record)``: validated, within the metadata bound, written atomically over a regular file."""
        validate_record(record, record.get('id'))
        if len(jsjson.stringify(record).encode('utf-8')) > PROJECT_LIMITS['metadata_bytes']:
            raise ProjectError(METADATA_SIZE, 413)
        directory = self.io.record_directory(record['id'])
        path = nodepath.join(directory, 'project.json')
        try:
            info = lstat(path)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ProjectError(METADATA_PATH, 409)
        except Exception as error:  # noqa: BLE001 - Node's catch
            if records.error_code(error) != 'ENOENT':
                raise
        records.atomic_json(path, record)

    def _create_sync(self, values: dict) -> dict:
        self.io.ready()
        id, access_key, owner_key, at = self.random_uuid(), self.random_key(), self.random_key(), self.now()
        mkdir(nodepath.join(self.io.directory, id), 0o700)
        mkdir(nodepath.join(self.io.directory, id, 'snapshots'), 0o700)
        record = {'schema': PROJECT_SCHEMA, 'id': id, **values, 'revision': 1, 'created_at': at, 'updated_at': at,
                  'owner_key_hash': _digest(owner_key.encode('utf-8')), 'viewer_key_hash': None, 'entries': []}
        self.save_sync(record)
        return {'project': public_project(record), 'role': 'owner', 'access_key': access_key}

    def create(self, input: Any) -> Awaitable[dict]:
        """``create(input)``: a new project ``{title, owner_name, notes}`` in its own directory (with ``snapshots``);
        ``{project, role, access_key}``."""
        try:
            fields(input, CREATE_FIELDS)
            values = {'title': text(input.get('title', UNDEFINED), 'project title', TITLE_UNITS, True),
                      'owner_name': text(input.get('owner_name', UNDEFINED), 'researcher name', OWNER_UNITS, True),
                      'notes': text(coalesce(input.get('notes'), ''), 'project notes', NOTES_UNITS)}
            task = self.io.enqueue(lambda: asyncio.to_thread(self._create_sync, values))
        except Exception as error:  # noqa: BLE001 - an async function rejects
            return _failed(error)
        return asyncio.shield(task)

    def _mutate(self, id: Any, expected: Any, operation: Callable[[dict], Optional[dict]]) -> Awaitable[dict]:
        """``mutate(id, key, expectedRevision, operation)``: ``operation(record)`` (blocking, in the write's worker
        thread) on the record at revision ``expected``, then the next revision is saved."""
        def run() -> dict:
            record = self.load_sync(id)
            if not same(record['revision'], expected):
                raise ProjectError(CHANGED, 409)
            extra = operation(record) or {}
            record['revision'] = record['revision'] + 1
            record['updated_at'] = self.now()
            self.save_sync(record)
            return {'project': public_project(record), 'role': 'owner', **extra}

        try:
            revision(expected)
            task = self.io.enqueue(lambda: asyncio.to_thread(run))
        except Exception as error:  # noqa: BLE001 - an async function rejects
            return _failed(error)
        return asyncio.shield(task)

    def patch(self, id: Any, input: Any) -> Awaitable[dict]:
        """``patch(id, key, input)``: the title, researcher name, notes or comparison settings."""
        fields(input, PATCH_FIELDS)
        if len(input) < 2:
            raise ProjectRequestError(NO_PROJECT_CHANGES)
        values = {name: text(input[name], name, NOTES_UNITS if name == 'notes' else TITLE_UNITS if name == 'title'
                             else OWNER_UNITS, name != 'notes')
                  for name in ('title', 'owner_name', 'notes') if defined(input, name)}

        def operation(record: dict) -> None:
            record.update(values)
            if defined(input, 'workflow'):
                record['workflow'] = workflow(input['workflow'], record['entries'])

        return self._mutate(id, input.get('revision', UNDEFINED), operation)

    def attach(self, id: Any, input: Any, snapshot: Any, summary: Any) -> Awaitable[dict]:
        """``attach(id, key, input, snapshot, summary)``: a new entry whose snapshot is stored once under its
        SHA-256 (a stored copy is checked, not rewritten)."""
        fields(input, ATTACHMENT_FIELDS)
        if (not is_object(snapshot) or not same(snapshot.get('schema', UNDEFINED), SNAPSHOT_SCHEMA)
                or not (isinstance(snapshot.get('kind'), str) and snapshot['kind'] in ENTRY_KINDS)
                or not sha_test(snapshot.get('record_id', UNDEFINED))
                or not same(snapshot.get('kind'), input.get('kind', UNDEFINED))
                or not is_object(snapshot.get('payload')) or not is_object(summary)):
            raise ProjectRequestError(INVALID_SNAPSHOT)
        _validate_annotation(snapshot, input.get('annotation_id', UNDEFINED))
        snapshot_json = jsjson.stringify(snapshot)
        frozen_summary = _clone(summary)
        data = snapshot_json.encode('utf-8')
        snapshot_bytes, snapshot_sha256 = len(data), _digest(data)
        if snapshot_bytes > PROJECT_LIMITS['snapshot_bytes']:
            raise ProjectError(SNAPSHOT_SIZE, 413)
        kind, record_id = snapshot['kind'], snapshot['record_id']
        # `${kind} ${record_id.slice(0, 8)}`: a record id that passed String() as a digest may be an array.
        title = text(coalesce(input.get('title'), f'{js_string(kind)} {js_string(record_id[:8])}'), 'entry title',
                     TITLE_UNITS, True)
        notes = text(coalesce(input.get('notes'), ''), 'entry notes', NOTES_UNITS)
        annotation_id = input.get('annotation_id', UNDEFINED)

        def operation(record: dict) -> dict:
            entries = record['entries']
            if (len(entries) >= PROJECT_LIMITS['entries']
                    or sum((entry['snapshot_bytes'] for entry in entries), snapshot_bytes) > PROJECT_LIMITS['project_bytes']):
                raise ProjectError(ENTRY_LIMIT, 413)
            if any(same(entry['kind'], kind) and same(entry['record_id'], record_id)
                   and same(entry.get('annotation_id', UNDEFINED), annotation_id) for entry in entries):
                raise ProjectError(DUPLICATE, 409)
            directory = self.io.record_directory(id)
            snapshots = nodepath.join(directory, 'snapshots')
            self.io.safe_directory(snapshots)
            path = nodepath.join(snapshots, f'{snapshot_sha256}.json')
            # Detached immutable copies still consume storage; count them in the budget.
            stored_bytes = stored_count = 0
            already = False
            for name, _ in records.scandir(snapshots):
                final = _FINAL_SNAPSHOT.fullmatch(name) is not None
                temporary = _TEMPORARY_SNAPSHOT.fullmatch(name) is not None and valid_uuid(name[70:-4])
                if not final and not temporary:
                    raise ProjectError(UNEXPECTED_FILE, 409)
                info = lstat(nodepath.join(snapshots, name))
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ProjectError(SNAPSHOT_PATH, 409)
                # An interrupted atomic write can leave an unpublished temporary file: it is kept and counted, so a
                # retry stays within the budget, and never loaded as a scientific result.
                stored_bytes += info.st_size
                stored_count += 1
                if name == f'{snapshot_sha256}.json':
                    already = True
            if (stored_bytes + (0 if already else snapshot_bytes) > PROJECT_LIMITS['project_bytes']
                    or stored_count + (0 if already else 1) > PROJECT_LIMITS['entries']):
                raise ProjectError(STORAGE_LIMIT, 413)
            try:
                if _digest(self.io.file(path, PROJECT_LIMITS['snapshot_bytes'])) != snapshot_sha256:
                    raise ProjectError(SNAPSHOT_INTEGRITY, 409)
            except Exception as error:  # noqa: BLE001 - Node's catch
                if records.error_code(error) != 'ENOENT':
                    raise
                records.atomic_bytes(path, data)  # atomicJson(path, JSON.parse(snapshot_json)): the same bytes
            entry = {'id': self.random_uuid(), 'kind': kind, 'record_id': record_id,
                     **({'annotation_id': annotation_id} if truthy(annotation_id) else {}),
                     'title': title, 'notes': notes, 'created_at': self.now(), 'snapshot_sha256': snapshot_sha256,
                     'snapshot_bytes': snapshot_bytes, 'summary': frozen_summary}
            entries.append(entry)
            return {'entry': _clone(entry)}

        return self._mutate(id, input.get('revision', UNDEFINED), operation)

    def patch_entry(self, id: Any, entry_id: Any, input: Any) -> Awaitable[dict]:
        """``patchEntry(id, key, entryId, input)``: an entry's title or notes."""
        fields(input, ENTRY_PATCH_FIELDS)
        if not valid_uuid(entry_id):
            raise ProjectRequestError(INVALID_ENTRY_ID)
        if len(input) < 2:
            raise ProjectRequestError(NO_ENTRY_CHANGES)
        values = {name: text(input[name], name, NOTES_UNITS if name == 'notes' else TITLE_UNITS, name == 'title')
                  for name in ('title', 'notes') if defined(input, name)}

        def operation(record: dict) -> dict:
            entry = next((value for value in record['entries'] if same(value.get('id'), entry_id)), None)
            if entry is None:
                raise ProjectError(ENTRY_NOT_FOUND, 404)
            entry.update(values)
            return {'entry': _clone(entry)}

        return self._mutate(id, input.get('revision', UNDEFINED), operation)

    def detach(self, id: Any, entry_id: Any, expected_revision: Any) -> Awaitable[dict]:
        """``detach(id, key, entryId, expectedRevision)``: the entry leaves the project (its snapshot stays), and
        comparison settings that named it are cleared."""
        if not valid_uuid(entry_id):
            raise ProjectRequestError(INVALID_ENTRY_ID)

        def operation(record: dict) -> None:
            before = len(record['entries'])
            record['entries'] = [value for value in record['entries'] if not same(value.get('id'), entry_id)]
            if before == len(record['entries']):
                raise ProjectError(ENTRY_NOT_FOUND, 404)
            saved = record.get('workflow', UNDEFINED)
            if truthy(saved) and any(same(saved.get(key, UNDEFINED), entry_id)
                                     for key in ('reference_entry_id', 'candidate_entry_id')):
                for key in ('reference_entry_id', 'candidate_entry_id'):
                    if same(saved.get(key, UNDEFINED), entry_id):
                        saved[key] = None
                saved['comparison_href'] = None

        return self._mutate(id, expected_revision, operation)


# --- Service -----------------------------------------------------------------------------------------------------

async def _call(function: Callable, *args: Any) -> Any:
    """A dependency's method: a coroutine function on the loop, a blocking one in a worker thread."""
    if inspect.iscoroutinefunction(function):
        return await function(*args)
    result = await asyncio.to_thread(function, *args)
    return await result if inspect.isawaitable(result) else result


def error_answer(error: BaseException) -> tuple[int, dict, dict]:
    """The middleware's catch: ``(status, {error[, code]}, headers)``. The status is the error's integer status, else
    500; the message is shown for a refusal Node marks safe (``projectSafe``, ``resourceSafe``) and for any status
    below 500, else the generic one (logged). A resource refusal adds ``code: 'resource_unavailable'`` and its
    ``Retry-After`` (1 to 3600 seconds)."""
    status = _status(error)
    if not (jsjson.is_integer(status) and status):
        status = 500
    status = int(status)
    resource = getattr(error, 'resource_safe', False) is True
    headers = {}
    retry = getattr(error, 'retry_after', None)
    if resource and jsjson.is_integer(retry) and 0 < retry <= 3600:
        headers['Retry-After'] = jsjson.number_to_string(retry)
    safe = getattr(error, 'project_safe', False) is True or resource or status < 500
    if not safe:
        _log.error('project request failed', exc_info=error)
    message = getattr(error, 'message', None)
    value: dict[str, Any] = {'error': (message if isinstance(message, str) else str(error)) if safe else UNAVAILABLE}
    if resource:
        value['code'] = 'resource_unavailable'
    return status, value, headers


def project_path(path: str) -> bool:
    """Whether the middleware serves ``path`` (the path of the request target as received, without its query)."""
    return path == '/api/projects' or path.startswith('/api/projects/')


class ProjectService:
    """``ProjectService`` over the workspace's records.

    ``store`` defaults to ``ProjectStore(directory)`` (``W/projects``). A new entry's snapshot is resolved from
    ``library`` (``jobs.library.Library``, or a factory of one: ``get(id)``), whose layouts are bundled by ``bundle``
    (``jobs.bundle.experiment_bundle(root, record, python)``; ``root`` defaults to the library's, ``python`` is the
    compute interpreter), from ``editor`` (``jobs.editor.EditorJobs``: ``records()``, ``store``, ``validate``), from
    ``queue`` (``jobs.queue.WorkspaceQueue``: ``own(id, kind)`` and the ``source-reception`` adapter's
    ``saved_result``) and from ``annotations`` (``jobs.annotations.ElectrodeAnnotations``: ``read(id, record_id)``).
    ``delivery`` (``export(id)``) defaults to ``server.delivery.ProjectDelivery(store, scientific_root=root)``.
    ``before_write()`` (sync or async) admits each write, as Node's ``beforeWrite``.

    Coroutines: ``create(input)``, ``list()``, ``get(id)``, ``patch(id, input)``, ``attach(id, input)`` (the
    attachment checked, the revision compared, the snapshot resolved, then stored), ``get_entry``, ``patch_entry``,
    ``detach``, ``export``; ``resolve_snapshot(input)``; ``handle`` is the HTTP middleware after the access policy
    and, for a write, the token."""

    def __init__(self, *, store: Optional[ProjectStore] = None, directory: Optional[str] = None, library: Any = None,
                 root: Optional[str] = None, python: Any = None, bundle: Optional[Callable] = None, editor: Any = None,
                 queue: Any = None, annotations: Any = None, delivery: Any = None,
                 before_write: Optional[Callable[[], Any]] = None):
        if before_write is not None and not callable(before_write):
            raise TypeError('Project write admission must be a function.')
        if store is None:
            if directory is None:
                raise TypeError('ProjectService needs a store or its directory')
            store = ProjectStore(directory)
        self.store = store
        self._library = library
        self._root = root
        self.python = python
        self._bundle = bundle
        self.editor = editor
        self.queue = queue
        self.annotations = annotations
        self.before_write = before_write
        self._delivery = delivery

    @property
    def library(self) -> Any:
        library = self._library
        if callable(library) and not hasattr(library, 'get'):
            library = self._library = library()
        return library

    @property
    def root(self) -> Any:
        return self._root if self._root is not None else getattr(self.library, 'root', None)

    @property
    def bundle(self) -> Callable:
        if self._bundle is None:
            from ..jobs.bundle import experiment_bundle  # here: building the application loads no job module

            self._bundle = experiment_bundle
        return self._bundle

    @property
    def delivery(self) -> Any:
        if self._delivery is None:
            from .delivery import ProjectDelivery

            self._delivery = ProjectDelivery(self.store, scientific_root=self.root)
        return self._delivery

    def close(self) -> None:
        self.store.close()

    async def flush(self) -> None:
        await self.store.flush()

    async def aclose(self) -> None:
        self.close()
        await self.flush()

    async def admit_write(self) -> None:
        """``admitWrite()``: a closed store refuses (503), then ``before_write`` decides."""
        if self.store.closed:
            raise ProjectError(STOPPING, 503)
        if self.before_write is not None:
            result = self.before_write()
            if inspect.isawaitable(result):
                await result
        if self.store.closed:
            raise ProjectError(STOPPING, 503)

    # --- Snapshots -----------------------------------------------------------------------------------------------

    async def resolve_snapshot(self, input: Any) -> dict:
        """``resolveSnapshot(input, visitor)``: ``{snapshot, summary}`` of the result an entry names."""
        attachment(input)
        kind = input['kind']
        if kind == 'layout':
            record = await _call(self.library.get, input['record_id'])
            if (not same(_optional(record, 'status'), 'completed') or not truthy(_get(record, 'layout'))):
                raise ProjectError(CHOOSE_LAYOUT, 404)
            payload = await _call(self.bundle, self.root, record, self.python)
            record_id = _get(record, 'id')
            # Same rule as the library's canSimulateRecord: signal simulation rejects layouts searched under
            # correlated noise.
            count = _length(_get(_get(record, 'layout'), 'xyzMm'))
            dataset = _get(record, 'dataset_id')
            summary = _defined(('protocol', dataset), ('electrode_count', count),
                               ('region_count', _get(record, 'region_count')),
                               ('simulation', isinstance(dataset, str) and dataset in COMPARISON_DATASETS
                                and same(count, 64) and not truthy(_optional(_get(record, 'request'), 'noise_model'))))
        elif kind == 'editor':
            editor = self.editor
            rows = await _call(editor.records)
            row = next((value for value in rows if same(_get(value, 'key'), input['record_id'])), None)
            if row is None:
                raise ProjectError(EDIT_NOT_FOUND, 404)
            cache = await asyncio.to_thread(
                lambda: editor.store.read(editor.store.path('editor', input['record_id'], 'cache.json')))
            result = _get(cache, 'result')
            request = _optional(result, 'request')
            if (not same(_get(cache, 'key'), input['record_id'])
                    or not same(_hash(result), _get(cache, 'result_sha256'))
                    or not same(_hash(_defined(('request', request), ('identity', _get(cache, 'identity')))),
                                input['record_id'])
                    or not same(_optional(request, 'action'), 'evaluate')):
                raise ProjectError(EDIT_INTEGRITY, 409)
            await _call(editor.validate, result, _get(result, 'request'))
            record_id = _get(cache, 'key')
            payload = {'record': row, 'cache': cache}
            summary = _defined(('protocol', _get(result, 'schema')), ('electrode_count', _get(result, 'electrode_count')),
                               ('region_count', _get(result, 'active_regions')),
                               ('parent_id', _get(_get(result, 'request'), 'parent_id')))
        else:
            task = self.queue.own(input['receipt_id'], 'source-reception')
            if not same(task.get('status'), 'completed'):
                raise ProjectError(SIGNAL_INCOMPLETE, 409)
            payload = await _call(self.queue.adapters['source-reception'].saved_result, task['key'], task['request'])
            if (not is_object(payload)
                    or not same(_optional(payload.get('request', UNDEFINED), 'record_id'), _get(task['request'], 'record_id'))
                    or not (isinstance(payload.get('schema_version'), str) and payload['schema_version'] in SIGNAL_SCHEMAS)):
                raise ProjectError(SIGNAL_INTEGRITY, 409)
            record_id = task['key']
            request = payload['request']
            mode = _get(request, 'mode')
            summary = _defined(('protocol', payload['schema_version']),
                               ('electrode_count', _length(_get(_get(payload, 'layout'), 'xyzMm'))),
                               ('parent_id', _get(request, 'record_id')),
                               ('mode', 'legacy' if mode is None or mode is UNDEFINED else mode))
            for name in SIGNAL_SUMMARY:
                if isinstance(request, dict) and name in request:
                    summary[name] = _clone(request[name])
        if not (isinstance(record_id, str) and SHA.fullmatch(record_id)):
            raise ProjectError(RECORD_IDENTITY, 409)
        annotation = UNDEFINED
        if 'annotation_id' in input:
            try:
                annotation = await asyncio.to_thread(self.annotations.read, input['annotation_id'], record_id)
            except Exception as cause:  # noqa: BLE001 - Node's catch
                message = getattr(cause, 'message', str(cause))
                status = _status(cause)
                raise ProjectError(message if getattr(cause, 'annotation_safe', False) is True else ANNOTATION_UNAVAILABLE,
                                   status if truthy(status) else 409) from None
        snapshot = {'schema': SNAPSHOT_SCHEMA, 'kind': kind, 'record_id': record_id, 'payload': payload}
        if truthy(annotation):
            snapshot['electrode_annotation'] = annotation
        return {'snapshot': snapshot, 'summary': summary}

    # --- Operations ----------------------------------------------------------------------------------------------

    async def list(self) -> dict:
        return await self.store.list()

    async def get(self, id: Any) -> dict:
        return await self.store.get(id)

    async def create(self, input: Any) -> dict:
        return await self.store.create(input)

    async def patch(self, id: Any, input: Any) -> dict:
        return await self.store.patch(id, input)

    async def attach(self, id: Any, input: Any, current_revision: Any = UNDEFINED) -> dict:
        """The entries POST after the body: the attachment, the revision against ``current_revision`` (the project's
        as read before; read now when not given), the snapshot, then the store's ``attach``."""
        attachment(input)
        if current_revision is UNDEFINED:
            current_revision = (await self.store.get(id))['project']['revision']
        if not same(input.get('revision', UNDEFINED), current_revision):
            raise ProjectError(CHANGED, 409)
        resolved = await self.resolve_snapshot(input)
        return await self.store.attach(id, input, resolved['snapshot'], resolved['summary'])

    async def get_entry(self, id: Any, entry_id: Any) -> dict:
        return await self.store.get_entry(id, entry_id)

    async def patch_entry(self, id: Any, entry_id: Any, input: Any) -> dict:
        return await self.store.patch_entry(id, entry_id, input)

    async def detach(self, id: Any, entry_id: Any, expected_revision: Any) -> dict:
        return await self.store.detach(id, entry_id, expected_revision)

    async def export(self, id: Any) -> dict:
        return await self.delivery.export(id)

    # --- HTTP ----------------------------------------------------------------------------------------------------

    async def body(self, content_type: Optional[str], chunks: Union[bytes, AsyncIterable[bytes]]) -> dict:
        """``body(req)``: a JSON object of at most 65,536 bytes as received (415 ``JSON is required.``, 413 ``Project
        request is too large.`` as soon as the bound is passed, 400 ``Invalid project JSON.``). ``chunks`` is the
        body, or an async iterator of its chunks (``Request.stream()``)."""
        if not (content_type if isinstance(content_type, str) else 'undefined').startswith('application/json'):
            raise ProjectError(JSON_REQUIRED, 415)
        data = bytearray()
        if isinstance(chunks, (bytes, bytearray)):
            data += chunks
            if len(data) > BODY_LIMIT:
                raise ProjectError(TOO_LARGE, 413)
        else:
            async for chunk in chunks:
                data += chunk
                if len(data) > BODY_LIMIT:
                    raise ProjectError(TOO_LARGE, 413)
        try:
            value = jsjson.parse(jsjson.decode_body(bytes(data)))
        except Exception:  # noqa: BLE001 - any parse failure, as Node's catch
            raise ProjectError(INVALID_JSON) from None
        if not is_object(value):
            raise ProjectError(INVALID_JSON)
        return value

    async def handle(self, method: str, path: str, *, query: bool = False, content_type: Optional[str] = None,
                     body: Union[bytes, AsyncIterable[bytes]] = b'', if_match: Optional[str] = None
                     ) -> tuple[int, Any, dict]:
        """The middleware (service.mjs:82-140) after the access policy and, for a write, the token: ``(status, value,
        headers)`` for ``method`` on ``path`` (the raw path, which ``project_path`` accepts), with ``query`` true when
        the target had a query and ``if_match`` the ``If-Match`` header as Node reads it (repeated headers joined
        with ``, ``), or ``None``."""
        try:
            write = method in ('POST', 'PATCH', 'DELETE')
            if method not in ('GET', 'POST', 'PATCH', 'DELETE'):
                return 405, {'error': METHOD}, {}
            if query:
                raise ProjectError(QUERY)
            if path == '/api/projects':
                if method == 'GET':
                    return 200, await self.list(), {}
                if method != 'POST':
                    return 405, {'error': OPENED_WITH_ID}, {}
                await self.admit_write()
                return 201, await self.create(await self.body(content_type, body)), {}
            match = _PROJECT_PATH.fullmatch(path)
            if match is None or not valid_uuid(match[1]) or match[2] in ('share', 'revoke-share'):
                raise ProjectError(ENDPOINT, 404)
            id, action, entry_id = match.groups()
            # The project is read before a request body or a scientific payload.
            access = await self.store.get(id)
            if write:
                await self.admit_write()
            if action == 'export' and not entry_id and method == 'GET':
                bundle = await self.export(id)
                return 200, bundle, {'Content-Disposition': f'attachment; filename="eeg-research-{id}.json"'}
            if not action:
                if method == 'GET':
                    return 200, access, {}
                if method == 'PATCH':
                    return 200, await self.store.patch(id, await self.body(content_type, body)), {}
            elif action == 'entries':
                if entry_id and method == 'GET':
                    return 200, await self.store.get_entry(id, entry_id), {}
                if entry_id and method == 'PATCH':
                    return 200, await self.store.patch_entry(id, entry_id, await self.body(content_type, body)), {}
                if entry_id and method == 'DELETE':
                    if if_match is None:
                        expected = (await self.body(content_type, body)).get('revision', UNDEFINED)
                    else:
                        # if-match.replace(/^"|"$/g, ''): one quote off each end.
                        value = if_match[1:] if if_match.startswith('"') else if_match
                        expected = string_to_number(value[:-1] if value.endswith('"') else value)
                    return 200, await self.store.detach(id, entry_id, expected), {}
                if not entry_id and method == 'POST':
                    input = await self.body(content_type, body)
                    return 201, await self.attach(id, input, access['project']['revision']), {}
            return 405, {'error': OPERATION}, {}
        except Exception as error:  # noqa: BLE001 - the middleware's catch
            return error_answer(error)
