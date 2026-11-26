"""The legacy import: the Node host's research projects, robustness studies and signal records copied into a
workspace (design 0001, phase 2, slice 9; ``eeglayoutlab workspace import-legacy``).

The Node host keeps them in its queue directory Q (``R/results/web-service`` by default)::

    Q/projects/<uuid4>/project.json, snapshots/<sha256>.json   research-project/1 (ProjectStore)
    Q/studies/<uuid4>/study.json, snapshots/<sha256>.json      eeg-robustness-study/1 (StudyStore)
    Q/queue.json                                 {version: 1, sequence, maintenance, tasks} (CommunityQueue)

The Python service never writes Q (plan, rule 2) and reads it only here. Q is opened read-only: every file through
``O_RDONLY | O_NOFOLLOW``, no directory created (``_ReadOnlyFiles``), nothing renamed or removed. What is imported:

- **Projects.** Each ``Q/projects/<uuid4>`` is checked as Node's ``ProjectStore`` reads it (``validate_record``, and
  ``snapshot`` for every entry: bytes, size, SHA-256, schema, kind, record and electrode names); every
  ``snapshots/<sha256>.json``, detached ones included, must be a regular file with one link (else Node's ``attach``
  message, ``Scientific snapshot path is invalid.``) whose SHA-256 is its name. ``project.json`` and the snapshots are
  copied byte for byte to ``W/projects/<uuid4>``, with the same identifier and file names.
- **Studies.** Each ``Q/studies/<uuid4>`` is checked as Node's ``StudyStore`` reads it (``validate_study``, and for
  every completed case its snapshot: bytes, size, SHA-256 and ``validate_study_cache``); its files are copied to
  ``W/studies/<uuid4>`` the same way. A study is refused when the workspace's studies would exceed their total bound
  (512 MiB), which every later study write checks.
- **Signal records.** The completed ``source-reception`` receipts of ``Q/queue.json``, the newest of each key, are
  added to the workspace queue (``W/.eeglayoutlab/queue.json``, ``jobs.queue``'s format) with Node's members
  (``backendId`` as ``backend_id``) but without ``owners``, ``networks``, ``workerPid``, ``starting`` and
  ``annotation_refs``, so ``WorkspaceQueue.records()`` lists them as Node's ``records`` lists them for one visitor
  who owns them all, and ``saved_result`` reads their stored results (which stay in ``R/results/v2``; one without
  its result there is listed but cannot be downloaded, in Node as here, and the report counts them). They are
  placed among the workspace's receipts by creation time and every receipt is numbered again in that order (only
  their order is ever read); the queue's retention bounds then apply. A key the workspace already lists is not added.
  Receipts of other kinds, receipts that are not completed and malformed receipts (named in the report) are not
  imported.

What is not copied: temporaries of interrupted writes (``<name>.json.<uuid>.tmp``, never results) and any other entry
of a record directory, which the stores never read (a link among them is never followed); they are listed in the
report. A link, a file with a second link or another file type where a store reads refuses the record, with the
store's message, as Node refuses it.

Refusals are per record: a record that fails a check, or whose identifier the workspace already holds with other
bytes (a collision), is not imported and is named in the report with the reason; the workspace's record is kept. A
record the workspace already holds byte for byte (an earlier import) is reported as present, so the import can be run
again to add the records that are new since; a record changed since, in W or in Q, is then a collision. The report
names a Node host that still serves Q (a live ``worker.lock``): what it adds later needs another run, and what it
changes in a record imported already is not imported.

Consistency (the choice for a failure midway): the import holds the workspace lock, so no service writes W meanwhile
(a served workspace is refused). Each project or study is written into a staging directory in the workspace's state
directory (``W/.eeglayoutlab/legacy-import-<uuid4>``, which no store reads), synced, then published by one rename of
its directory; the receipts by one atomic replace of ``queue.json``, after the projects and studies. A failure or a
crash at any point leaves every record either complete or absent and the queue file old or new; the import stops at
the first failed write, and the next run removes a leftover staging directory and imports what is left.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
from typing import Any, Callable, Optional
import uuid

from ..jobs import nodefs, nodepath, records
from ..jobs import queue as workspace_queue
from ..jobs.identity import js_truthy
from ..jobs.studies import StudyError
from ..schemas import jsjson
from . import workspace_projects as projects
from . import workspace_studies as studies
from .workspace import NODE_QUEUE_DIRECTORY, STATE, Workspace, inside
from .workspace_files import SHA, UUID, ProjectError, WorkspaceFiles, basename, valid_project_id

__all__ = ['QUEUE_DIRECTORY', 'STAGING', 'LegacyImportError', 'default_queue_directory', 'import_legacy',
           'succeeded', 'describe']

QUEUE_DIRECTORY = NODE_QUEUE_DIRECTORY  # Node's default Q under the scientific root
STAGING = 'legacy-import-'
RECEIPT_KIND = 'source-reception'
# The members a workspace receipt keeps (jobs.queue's names), kept in the order Node's receipt has them. A completed
# receipt has no worker pid or spawn intent; its electrode-name references are per visitor (never on this kind).
RECEIPT_MEMBERS = {'id': 'id', 'sequence': 'sequence', 'kind': 'kind', 'key': 'key', 'request': 'request',
                   'status': 'status', 'created_at': 'created_at', 'progress': 'progress', 'cached': 'cached',
                   'catalog': 'catalog', 'finished_at': 'finished_at', 'message': 'message', 'backendId': 'backend_id'}
# Bound on reading Q/queue.json (Node keeps at most 1,300 terminal receipts and 50 pending ones).
QUEUE_BYTES = 64 * 1024 * 1024
RESULT_DIRECTORIES = ('results/v2/source_reception_jobs', 'results/v2/source_reception_v2_jobs')  # Node's savedResult

NODE_QUEUE_STATE = 'Unsupported queue state; preserve the file for recovery.'  # community-queue.mjs, verbatim
# Either copy may have changed after an earlier import: the workspace's, or the Node host's in Q.
COLLISION = {'projects': 'The workspace holds this project with other content (one of the two copies changed after an '
                         "earlier import); the workspace's copy was kept.",
             'studies': 'The workspace holds this study with other content (one of the two copies changed after an '
                        "earlier import); the workspace's copy was kept."}
RECEIPT_COLLISION = 'A different receipt with this identifier is already in the workspace queue; it was kept.'

_FINAL = re.compile(r'[a-f0-9]{64}\.json')
_STAGING = re.compile(re.escape(STAGING) + UUID.pattern)
_SAFE_INTEGER = 2**53 - 1


class LegacyImportError(Exception):
    """The import cannot run at all (no queue directory, a workspace inside it ...); nothing was written."""


class _NotListed(Exception):
    """A record directory Node's store does not list: no metadata file yet (an interrupted create), or one that names
    another study."""


# --- Reading Q (never written) -----------------------------------------------------------------------------------

class _ReadOnlyFiles(WorkspaceFiles):
    """``WorkspaceFiles`` on a directory of Q (or of W in a dry run): ``ready`` resolves and checks it as Node's
    ``initialize`` does, but creates neither it nor its parent."""

    def _initialize(self) -> None:
        self.directory = nodepath.join(nodefs.realpath(nodepath.dirname(self.directory)), basename(self.directory))
        self.safe_directory(self.directory)


class _Record:
    """A checked project or study of Q: its files (relative path, exact bytes), the metadata file last."""

    def __init__(self, kind: str, id: str):
        self.kind = kind
        self.id = id
        self.files: list[tuple[str, bytes]] = []

    @property
    def size(self) -> int:
        return sum(len(data) for _, data in self.files)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reason(error: BaseException) -> str:
    """What the report says about a refusal: the store's message, or Node's text of a system error."""
    message = getattr(error, 'message', None)
    if isinstance(message, str) and message:
        return message
    return records.node_message(error) or type(error).__name__


def _snapshots(io: WorkspaceFiles, folder: str, maximum: int, unsafe: Callable[[], Exception],
               mismatch: Callable[[], Exception], skipped: list, prefix: str) -> list[tuple[str, bytes]]:
    """The final snapshots of ``folder`` (``<sha256>.json``: a regular file with one link whose SHA-256 is its name),
    as ``(snapshots/<name>, bytes)``; temporaries and other entries are listed in ``skipped``, never read."""
    io.safe_directory(folder)
    files = []
    for name, _ in records.scandir(folder):
        if not _FINAL.fullmatch(name):
            skipped.append(f'{prefix}/{name}')
            continue
        path = nodepath.join(folder, name)
        info = nodefs.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise unsafe()
        data = io.file(path, maximum)
        if _digest(data) != name[:64]:
            raise mismatch()
        files.append((f'snapshots/{name}', data))
    return files


def _metadata(io: WorkspaceFiles, path: str, maximum: int, what: str) -> bytes:
    try:
        return io.file(path, maximum)
    except OSError as error:
        if records.error_code(error) == 'ENOENT':
            raise _NotListed(f'no {what} (an interrupted create)') from None
        raise


def _read_project(store: projects.ProjectStore, id: str, skipped: list) -> _Record:
    """``Q/projects/<id>`` as Node's ``ProjectStore`` loads it and reads each entry's snapshot."""
    io = store.io
    directory = io.record_directory(id)
    try:
        metadata = _metadata(io, nodepath.join(directory, 'project.json'), projects.PROJECT_LIMITS['metadata_bytes'],
                             'project.json')
    except Exception as error:  # noqa: BLE001 - load's catch
        if isinstance(error, _NotListed) or getattr(error, 'project_safe', False):
            raise
        raise ProjectError(projects.INTEGRITY, 409) from None
    try:
        value = jsjson.parse(jsjson.decode_body(metadata))
    except Exception:  # noqa: BLE001 - load's catch
        raise ProjectError(projects.INTEGRITY, 409) from None
    record = projects.validate_record(value, id)
    for entry in record['entries']:
        store.snapshot_sync(record, entry)
    found = _Record('projects', id)
    for name, _ in records.scandir(directory):
        if name == 'snapshots':
            found.files.extend(_snapshots(
                io, nodepath.join(directory, name), projects.PROJECT_LIMITS['snapshot_bytes'],
                lambda: ProjectError(projects.SNAPSHOT_PATH, 409),
                lambda: ProjectError(projects.SNAPSHOT_INTEGRITY, 409),
                skipped, f'projects/{id}/snapshots'))
        elif name != 'project.json':
            skipped.append(f'projects/{id}/{name}')
    found.files.append(('project.json', metadata))
    return found


def _read_study(store: studies.StudyStore, id: str, skipped: list) -> _Record:
    """``Q/studies/<id>`` as Node's ``StudyStore`` loads it and reads each completed case's snapshot."""
    io = store.io
    directory = io.record_directory(id)
    metadata = _metadata(io, nodepath.join(directory, 'study.json'), store.limits['metadataBytes'], 'study.json')
    try:
        value = jsjson.parse(jsjson.decode_body(metadata))
    except Exception:  # noqa: BLE001 - JSON.parse fails before validate (Node's 500)
        raise StudyError(studies.INTEGRITY, 409) from None
    record = studies.validate_study(value)
    if record['id'] != id:
        raise _NotListed('its study.json names another study')
    for entry in record['cases']:
        if entry['status'] != 'completed':
            continue
        try:
            store.snapshot_sync(record, entry)
        except OSError as error:
            if records.error_code(error) == 'ENOENT':
                raise StudyError(f"Study snapshot snapshots/{entry['source_sha256']}.json is missing.", 409) from None
            raise
    found = _Record('studies', id)
    for name, _ in records.scandir(directory):
        if name == 'snapshots':
            found.files.extend(_snapshots(
                io, nodepath.join(directory, name), store.limits['caseBytes'],
                lambda: StudyError(studies.SNAPSHOT_PATH, 409), lambda: StudyError(studies.SNAPSHOT_CHECKSUM, 409),
                skipped, f'studies/{id}/snapshots'))
        elif name != 'study.json':
            skipped.append(f'studies/{id}/{name}')
    found.files.append(('study.json', metadata))
    return found


def _source(kind: str, queue_directory: str) -> Optional[tuple[Any, Callable[[Any, str, list], _Record]]]:
    """The read-only store of ``Q/<kind>`` and its reader, or ``None`` when Q has no such directory."""
    directory = nodepath.join(queue_directory, kind)
    try:
        nodefs.lstat(directory)
    except OSError as error:
        if records.error_code(error) == 'ENOENT':
            return None
        raise
    store: Any = projects.ProjectStore(directory) if kind == 'projects' else studies.StudyStore(directory)
    store.io = _ReadOnlyFiles(directory)
    store.io.ready()
    return store, (_read_project if kind == 'projects' else _read_study)


def _node_receipts(queue_directory: str, section: dict) -> list[dict]:
    """The completed signal-reception receipts of ``Q/queue.json``, newest of each key, as workspace receipts (oldest
    first); the others are counted in ``section``, malformed ones refused."""
    path = nodepath.join(queue_directory, 'queue.json')
    try:
        nodefs.lstat(path)
    except OSError as error:
        if records.error_code(error) == 'ENOENT':
            return []
        raise
    try:
        data = WorkspaceFiles(queue_directory).file(path, QUEUE_BYTES)
    except ProjectError:
        raise LegacyImportError('queue.json is not a regular file with one link (a link is not followed), or it is '
                                'larger than 64 MiB.') from None
    try:
        value = jsjson.parse(jsjson.decode_body(data))
    except jsjson.JSONSyntaxError:
        raise LegacyImportError('queue.json is not valid JSON.') from None
    # The checks of Node's CommunityQueue constructor (a missing maintenance flag is false; null is refused).
    if (not isinstance(value, dict) or not (jsjson.is_number(value.get('version')) and value['version'] == 1)
            or not isinstance(value.get('tasks'), list) or not isinstance(value.get('maintenance', False), bool)):
        raise LegacyImportError(NODE_QUEUE_STATE)
    newest: dict[str, dict] = {}
    ids: set = set()
    for number, task in enumerate(value['tasks'], 1):
        if not isinstance(task, dict):
            section['refused'].append({'id': f'task {number}', 'reason': f'task {number} is not an object'})
            continue
        if task.get('kind') != RECEIPT_KIND:
            section['other_kinds'] += 1
            continue
        if task.get('status') != 'completed':
            section['not_completed'] += 1
            continue
        receipt = {RECEIPT_MEMBERS[name]: item for name, item in task.items() if name in RECEIPT_MEMBERS}
        problem = _receipt_problem(receipt, number)
        if problem is None and receipt['id'] in ids:
            problem = f'task {number} repeats the id of an earlier receipt'
        if problem is not None:
            label = receipt.get('id') if isinstance(receipt.get('id'), str) else f'task {number}'
            section['refused'].append({'id': label, 'reason': problem})
            continue
        ids.add(receipt['id'])
        previous = newest.get(receipt['key'])
        if previous is not None:
            section['older_duplicates'] += 1
            if previous['sequence'] >= receipt['sequence']:  # records(): the first of equal sequences stays
                continue
        newest[receipt['key']] = receipt
    return sorted(newest.values(), key=lambda receipt: receipt['sequence'])


def _receipt_problem(receipt: dict, number: int) -> Optional[str]:
    """Why a completed Node receipt cannot be a workspace receipt, or ``None``."""
    if not valid_project_id(receipt.get('id')):
        return f'task {number} has no UUID id'
    if not (isinstance(receipt.get('key'), str) and SHA.fullmatch(receipt['key'])):
        return f'task {number} has no SHA-256 key'
    if not isinstance(receipt.get('request'), dict):
        return f'task {number} has no request object'
    sequence = receipt.get('sequence')
    if not (jsjson.is_number(sequence) and jsjson.is_integer(sequence) and 1 <= sequence <= _SAFE_INTEGER):
        return f'task {number} has an invalid sequence'
    if workspace_queue._parse_date(receipt.get('created_at')) is None:
        return f'task {number} has an invalid created_at'
    try:
        workspace_queue._check_task(receipt, number, _SAFE_INTEGER)  # as the workspace queue loads it
    except ValueError as error:
        return str(error)
    return None


def _has_result(root: str, receipt: dict) -> bool:
    """Whether the receipt's stored result is in the record tree, where Node's ``savedResult`` reads it (v2 when the
    request has a ``mode``). Only its directory entry is looked at."""
    directory = RESULT_DIRECTORIES[1 if js_truthy(receipt['request'].get('mode')) else 0]
    try:
        info = nodefs.lstat(nodepath.join(root, directory, receipt['key'], 'cache.json'))
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode)


# --- Writing W ---------------------------------------------------------------------------------------------------

def _mkdir(path: str) -> None:
    try:
        os.mkdir(nodefs.encode(path), 0o700)
    except OSError as error:
        raise nodefs.system_error(error, 'mkdir', path) from None


def _write_new(path: str, data: bytes) -> None:
    """A new file holding ``data`` (mode 0600, as Node's writes), synced."""
    try:
        fd = os.open(nodefs.encode(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                     | getattr(os, 'O_CLOEXEC', 0), 0o600)
    except OSError as error:
        raise nodefs.system_error(error, 'open', path) from None
    try:
        view = memoryview(data)
        while view:
            try:
                written = os.write(fd, view)
            except OSError as error:
                raise nodefs.system_error(error, 'write', path) from None
            view = view[written:]
        records.fsync(fd)
    finally:
        os.close(fd)


def _sync_directory(path: str) -> None:
    fd = os.open(nodefs.encode(path), os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0))
    try:
        records.fsync(fd)
    finally:
        os.close(fd)


def _absent(path: str) -> bool:
    try:
        nodefs.lstat(path)
    except OSError as error:
        if records.error_code(error) == 'ENOENT':
            return True
        raise
    return False


def _publish(staged: str, target: str) -> None:
    """Moves a complete staged record directory to ``target`` in one rename. The workspace lock keeps every other
    writer out, so ``target`` is still absent."""
    if not _absent(target):
        raise LegacyImportError(f'{target} appeared during the import.')
    try:
        os.rename(nodefs.encode(staged), nodefs.encode(target))
    except OSError as error:
        raise nodefs.system_error(error, 'rename', staged, target) from None
    _sync_directory(nodepath.dirname(target))


class _Staging:
    """``W/.eeglayoutlab/legacy-import-<uuid4>``: records are written here completely, then published."""

    def __init__(self, state: str):
        self.path = nodepath.join(state, f'{STAGING}{uuid.uuid4()}')
        self.made: set = set()

    def _directory(self, path: str) -> None:
        if path not in self.made:
            _mkdir(path)
            self.made.add(path)

    def stage(self, record: _Record) -> str:
        self._directory(self.path)
        kind = nodepath.join(self.path, record.kind)
        self._directory(kind)
        staged = nodepath.join(kind, record.id)
        _mkdir(staged)
        _mkdir(nodepath.join(staged, 'snapshots'))
        for relative, data in record.files:
            _write_new(nodepath.join(staged, relative), data)
        _sync_directory(nodepath.join(staged, 'snapshots'))
        _sync_directory(staged)
        return staged

    def remove(self) -> None:
        if self.path in self.made:
            shutil.rmtree(nodefs.encode(self.path), ignore_errors=True)


def _clear_staging(state: str) -> None:
    """Removes what an interrupted import left in the state directory (the workspace lock is held)."""
    for name in nodefs.readdir(state):
        if not _STAGING.fullmatch(name):
            continue
        path = nodepath.join(state, name)
        if stat.S_ISDIR(nodefs.lstat(path).st_mode):
            shutil.rmtree(nodefs.encode(path))
        else:
            os.unlink(nodefs.encode(path))


def _holds(io: WorkspaceFiles, target: str, record: _Record) -> bool:
    """Whether the workspace's record directory ``target`` holds every file of ``record`` byte for byte."""
    try:
        io.safe_directory(target)
        return all(io.file(nodepath.join(target, relative), len(data)) == data for relative, data in record.files)
    except Exception:  # noqa: BLE001 - anything else is a different record
        return False


# --- The workspace queue -----------------------------------------------------------------------------------------

def _read_queue(path: str) -> tuple[int, list[dict], Optional[str], bool]:
    """The workspace queue file as ``WorkspaceQueue`` loads it: ``(sequence, tasks, boot_id, exists)``."""
    try:
        fd = os.open(nodefs.encode(path), os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
    except FileNotFoundError:
        return 0, [], workspace_queue.boot_id(), False
    except OSError as error:
        raise _unusable(path, error.strerror or str(error)) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise _unusable(path, 'it is not a regular file')
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(fd)
    try:
        value = jsjson.parse(b''.join(chunks).decode('utf-8'))
        sequence, tasks, boot = workspace_queue._check_state(value)
    except UnicodeDecodeError:
        raise _unusable(path, 'it is not UTF-8 text') from None
    except jsjson.JSONSyntaxError:
        raise _unusable(path, 'it is not valid JSON') from None
    except ValueError as error:
        raise _unusable(path, str(error)) from None
    return sequence, tasks, boot, True


def _write_queue(path: str, value: dict) -> None:
    """Replaces the workspace queue file at once (``jobs.queue``'s write)."""
    records.atomic_json(path, value)


def _unusable(path: str, reason: str) -> LegacyImportError:
    return LegacyImportError(f'The workspace queue {path} cannot be read ({reason}); it was kept unchanged.')


def _merge(existing: list[dict], imported: list[dict]) -> list[dict]:
    """The two lists, each in its own order, interleaved by creation time (a workspace receipt first on a tie)."""
    merged = []
    i = j = 0
    while i < len(imported) and j < len(existing):
        later = workspace_queue._parse_date(existing[j]['created_at'])
        if later is not None and workspace_queue._parse_date(imported[i]['created_at']) < later:
            merged.append(imported[i])
            i += 1
        else:
            merged.append(existing[j])
            j += 1
    return merged + imported[i:] + existing[j:]


def _import_receipts(report: dict, queue_directory: str, state: Optional[str], root: Optional[str],
                     dry_run: bool) -> None:
    section = report['receipts']
    try:
        receipts = _node_receipts(queue_directory, section)
    except Exception as error:  # noqa: BLE001 - the whole file is refused
        section['refused'].append({'id': 'queue.json', 'reason': _reason(error)})
        return
    if root is not None:
        section['without_result'] = [receipt['id'] for receipt in receipts if not _has_result(root, receipt)]
    path = nodepath.join(state, workspace_queue.QUEUE_FILE) if state is not None else None
    try:
        sequence, tasks, boot, exists = _read_queue(path) if path is not None else (0, [], None, False)
    except LegacyImportError as error:
        section['refused'].append({'id': 'workspace queue', 'reason': str(error)})
        return
    by_id = {task['id']: task for task in tasks}
    listed = {task['key'] for task in tasks if task['kind'] == RECEIPT_KIND and task['status'] == 'completed'}
    added = []
    for receipt in receipts:
        same = by_id.get(receipt['id'])
        if same is not None:
            if (same['kind'], same['key'], jsjson.stringify(same['request'])) == (
                    receipt['kind'], receipt['key'], jsjson.stringify(receipt['request'])):
                section['present'].append(receipt['id'])
            else:
                section['refused'].append({'id': receipt['id'], 'reason': RECEIPT_COLLISION})
        elif receipt['key'] in listed:
            section['listed'] += 1
        else:
            added.append(receipt)
    if not added:
        return
    merged = _merge(tasks, added)
    for number, task in enumerate(merged, 1):
        task['sequence'] = number
    kept = workspace_queue.retain_receipts(merged, workspace_queue.RECEIPT_LIMITS)
    retained = {id(task) for task in kept}
    new = {id(task) for task in added}
    section['retention'] = sum(1 for task in added if id(task) not in retained)
    section['workspace_retention'] = sum(1 for task in merged if id(task) not in retained and id(task) not in new)
    imported = [task['id'] for task in added if id(task) in retained]
    if not dry_run and imported:
        value = {'schema': workspace_queue.QUEUE_SCHEMA, 'sequence': len(merged), 'boot_id': boot, 'tasks': kept}
        if boot is None:
            del value['boot_id']
        _write_queue(path, value)
    section['imported'].extend(imported)


# --- The import --------------------------------------------------------------------------------------------------

def default_queue_directory(root: str) -> str:
    """Node's default queue directory of the scientific root ``root``."""
    return nodepath.join(root, QUEUE_DIRECTORY)


def _node_host(queue_directory: str) -> Optional[int]:
    """The pid in Node's ``worker.lock`` when that process lives: the Node host still serves the queue directory."""
    try:
        data = WorkspaceFiles(queue_directory).file(nodepath.join(queue_directory, 'worker.lock'), 4096)
        pid = jsjson.parse(jsjson.decode_body(data)).get('pid')
    except Exception:  # noqa: BLE001 - no lock, or not Node's
        return None
    if not (jsjson.is_integer(pid) and 0 < pid < 2**31):
        return None
    pid = int(pid)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return pid
    except OSError:
        return None
    return pid


def _check_directories(workspace: str, queue_directory: str) -> None:
    try:
        info = os.stat(nodefs.encode(queue_directory))
    except OSError as error:
        raise LegacyImportError(f'No legacy queue directory at {queue_directory} ({error.strerror}).') from None
    if not stat.S_ISDIR(info.st_mode):
        raise LegacyImportError(f'{queue_directory} is not a directory.')
    if inside(workspace, queue_directory):
        raise LegacyImportError(f'The workspace {workspace} is the legacy queue directory or inside it; nothing is '
                                'ever written there. Choose a workspace elsewhere.')
    if inside(queue_directory, workspace):
        raise LegacyImportError(f'The legacy queue directory {queue_directory} is inside the workspace {workspace}.')


def _section() -> dict:
    return {'imported': [], 'present': [], 'refused': [], 'ignored': []}


def _new_report(workspace: str, queue_directory: str, root: Optional[str], dry_run: bool) -> dict:
    return {
        'workspace': workspace, 'queue_directory': queue_directory, 'root': root, 'dry_run': dry_run,
        'projects': _section(), 'studies': _section(),
        'receipts': {'imported': [], 'present': [], 'refused': [], 'other_kinds': 0, 'not_completed': 0,
                     'older_duplicates': 0, 'listed': 0, 'retention': 0, 'workspace_retention': 0,
                     'without_result': None},
        'skipped_files': [], 'failure': None, 'node_host_pid': _node_host(queue_directory),
    }


def _target(kind: str, workspace: str, dry_run: bool) -> tuple[WorkspaceFiles, int, int]:
    """The workspace's directory of ``kind`` (created unless ``dry_run``) with its reader, the bytes its studies hold
    and their bound. The dry run resolves an existing directory as the import does (its parent's real path)."""
    if kind == 'projects':
        io = (_ReadOnlyFiles if dry_run else WorkspaceFiles)(nodepath.join(workspace, kind))
        if not (dry_run and _absent(io.directory)):
            io.ready()
        return io, 0, 0
    store = studies.StudyStore(nodepath.join(workspace, kind))
    present = store.root(not dry_run)
    return store.io, store.usage_sync() if present else 0, store.limits['totalBytes']


def _import_records(report: dict, kind: str, queue_directory: str, workspace: str, dry_run: bool,
                    staging: Optional[_Staging]) -> None:
    section = report[kind]
    try:
        source = _source(kind, queue_directory)
    except Exception as error:  # noqa: BLE001 - the whole directory is refused
        section['refused'].append({'id': kind, 'reason': _reason(error)})
        return
    if source is None:
        return
    store, read = source
    try:
        names = records.scandir(store.io.directory)
        io, usage, bound = _target(kind, workspace, dry_run)
    except Exception as error:  # noqa: BLE001
        section['refused'].append({'id': kind, 'reason': _reason(error)})
        return
    for name, _ in names:
        if not valid_project_id(name):
            section['ignored'].append(f'{kind}/{name}')
            continue
        try:
            record = read(store, name, report['skipped_files'])
        except _NotListed as note:
            section['ignored'].append(f'{kind}/{name}: {note}')
            continue
        except Exception as error:  # noqa: BLE001 - this record is refused
            section['refused'].append({'id': name, 'reason': _reason(error)})
            continue
        target = nodepath.join(io.directory, name)
        if not _absent(target):
            if _holds(io, target, record):
                section['present'].append(name)
            else:
                section['refused'].append({'id': name, 'reason': COLLISION[kind]})
            continue
        if bound and usage + record.size > bound:
            section['refused'].append({'id': name, 'reason': studies.CAPACITY})
            continue
        usage += record.size
        if staging is not None:
            try:
                _publish(staging.stage(record), target)
            except Exception as error:  # noqa: BLE001 - the import stops; W keeps whole records only
                report['failure'] = f'{kind[:-1]} {name}: {_reason(error)}'
                raise _Stop() from error
        section['imported'].append(name)


class _Stop(Exception):
    """A write failed: nothing more is imported."""


def import_legacy(workspace: str, queue_directory: str, *, root: Optional[str] = None,
                  dry_run: bool = False) -> dict:
    """Imports the projects, studies and completed signal records of the Node queue directory ``queue_directory`` into
    the workspace ``workspace`` (created when missing) and returns the report; ``dry_run`` reports what would be
    imported and writes nothing (the workspace is not even created). ``root`` (the scientific root) only says which
    imported signal records have their stored result.

    The report: ``projects`` and ``studies`` each ``{imported, present, refused: [{id, reason}], ignored}``
    (identifiers; ``ignored`` names entries Node's stores do not list); ``receipts`` ``{imported, present, refused, other_kinds,
    not_completed, older_duplicates, listed, retention, workspace_retention, without_result}`` (``listed``: keys the
    workspace already lists; ``retention``: receipts the workspace queue's bounds leave out, ``workspace_retention``:
    its own receipts they drop; ``without_result``: imported or not, the ids whose stored result is not under ``root``,
    ``None`` without ``root``); ``skipped_files`` (files of Q not copied); ``failure`` (the write that stopped the
    import, or ``None``); ``node_host_pid`` (a live Node host still serving Q, or ``None``).

    Raises ``LegacyImportError`` when the import cannot run (no queue directory, a workspace inside it, or the reverse),
    ``WorkspaceInUse`` when a service holds the workspace and ``WorkspaceError`` when it cannot be used; nothing is
    written then. A refused record or a failed write is in the report (``succeeded(report)`` is false)."""
    workspace = nodepath.resolve(workspace)
    queue_directory = nodepath.resolve(queue_directory)
    _check_directories(workspace, queue_directory)
    report = _new_report(workspace, queue_directory, root, dry_run)
    opened = None if dry_run else Workspace.open(workspace)
    try:
        state = None if dry_run and _absent(nodepath.join(workspace, STATE)) else nodepath.join(workspace, STATE)
        staging = None
        if opened is not None:
            _clear_staging(opened.state)
            staging = _Staging(opened.state)
        try:
            for kind in ('projects', 'studies'):
                _import_records(report, kind, queue_directory, workspace, dry_run, staging)
            try:
                _import_receipts(report, queue_directory, state, root, dry_run)
            except Exception as error:  # noqa: BLE001 - the queue file is replaced whole or not at all
                report['failure'] = f'workspace queue: {_reason(error)}'
        except _Stop:
            pass
        finally:
            if staging is not None:
                staging.remove()
    finally:
        if opened is not None:
            opened.close()
    return report


def succeeded(report: dict) -> bool:
    """Whether everything the queue directory holds was imported or was already in the workspace."""
    return report['failure'] is None and not any(report[name]['refused']
                                                 for name in ('projects', 'studies', 'receipts'))


_PLURALS = {'project': 'projects', 'study': 'studies', 'signal record': 'signal records'}


def _count(number: int, noun: str) -> str:
    return f'{number} {noun if number == 1 else _PLURALS[noun]}'


def describe(report: dict) -> str:
    """The report for the person who ran the command."""
    verb = 'would be imported' if report['dry_run'] else 'imported'
    lines = [f"{'Dry run: nothing was written. ' if report['dry_run'] else ''}"
             f"Legacy import from {report['queue_directory']} into {report['workspace']}:"]
    if report['node_host_pid'] is not None:
        lines.append(f"  The Node host (PID {report['node_host_pid']}) still serves this queue directory; stop it "
                     'before importing. Another run adds only records that are new; a project or study the Node host '
                     'changes after this run is refused then, and the workspace keeps its copy.')
    for kind, noun in (('projects', 'project'), ('studies', 'study')):
        section = report[kind]
        parts = [f"{_count(len(section['imported']), noun)} {verb}"]
        if section['present']:
            parts.append(f"{len(section['present'])} already in the workspace")
        if section['refused']:
            parts.append(f"{len(section['refused'])} refused")
        lines.append(f'  {kind}: ' + ', '.join(parts))
        for name in section['imported']:
            lines.append(f'    {name}')
    receipts = report['receipts']
    parts = [f"{_count(len(receipts['imported']), 'signal record')} {verb}"]
    if receipts['present']:
        parts.append(f"{len(receipts['present'])} already in the workspace")
    if receipts['listed']:
        parts.append(f"{receipts['listed']} whose result the workspace already lists")
    if receipts['refused']:
        parts.append(f"{len(receipts['refused'])} refused")
    lines.append('  ' + ', '.join(parts))
    others = [(receipts['other_kinds'], 'of other kinds'), (receipts['not_completed'], 'not completed'),
              (receipts['older_duplicates'], 'older receipts of the same result'),
              (receipts['retention'], "beyond the workspace queue's retention")]
    others = [f'{number} {what}' for number, what in others if number]
    if others:
        lines.append('    not imported: ' + ', '.join(others) + ' (receipts)')
    if receipts['workspace_retention']:
        lines.append(f"    {receipts['workspace_retention']} older receipts of the workspace leave its queue "
                     '(retention)')
    missing = receipts['without_result']
    if missing:
        imported = set(receipts['imported'])
        count = sum(1 for id in missing if id in imported)
        if count:
            lines.append(f"    {count} of them have no stored result under {report['root']}/results/v2; they are "
                         'listed but cannot be downloaded')
    refused = [(kind, row) for kind in ('projects', 'studies', 'receipts') for row in report[kind]['refused']]
    if refused:
        lines.append('Refused (not imported):')
        names = {'projects': 'project', 'studies': 'study', 'receipts': 'signal record'}
        lines.extend(f"  {names[kind]} {row['id']}: {row['reason']}" for kind, row in refused)
    ignored = report['projects']['ignored'] + report['studies']['ignored']
    if ignored:
        lines.append('Ignored entries of the queue directory (not records Node lists):')
        lines.extend(f'  {name}' for name in ignored)
    if report['skipped_files']:
        lines.append('Not copied (temporaries of interrupted writes and files the stores never read):')
        lines.extend(f'  {name}' for name in report['skipped_files'])
    if report['failure']:
        lines.append(f"The import stopped: {report['failure']}. Every record is in the workspace whole or not at "
                     'all; run the command again to import the rest.')
    return '\n'.join(lines)
