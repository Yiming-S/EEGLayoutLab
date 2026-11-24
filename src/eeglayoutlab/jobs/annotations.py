"""Electrode-name annotations: Node's ``annotations/electrode-names.mjs`` (``electrodeNames``, ``designSubmission``,
``validateElectrodeAnnotation`` and ``ElectrodeAnnotations``).

An annotation is immutable, content-addressed presentation metadata for a saved design evaluation (its 64
electrode names and, optionally, where the coordinates came from); it never enters a scientific key. A file is
``{id, schema, owner, record_id, request_sha256, xyz_sha256, regions_sha256, electrode_names, source_metadata?}``
with ``id = sha256(JSON.stringify(<the file without id>))``, so the owner Node stored is covered by the id.

The local service has one user (design 0001, decision 6): annotations are read without regard to their owner, from
several directories in order: the workspace's ``W/annotations/electrode-names/`` first, then Node's
``R/results/v2/design_evaluation_jobs/electrode_annotations/``. Each directory is checked as Node checks its own:
below a base resolved with ``fs.realpathSync``, every component must be a directory, not a link, whose real path
is itself; a missing component means no annotations there. Errors are ``AnnotationError`` with Node's status and
message (the routes answer with them); any other failure while reading a file is ``Electrode name storage is
unavailable.`` (409), as in Node.

New annotations are written only to the workspace directory, under the local owner (``LOCAL_OWNER``), so their ids
differ from Node's for the same names (the id covers the owner) and are stable across runs. ``create`` is Node's,
call for call: the file is ``JSON.stringify({id, ...identity})`` as UTF-8, written to a ``.<uuid>.tmp`` opened
``wx`` with mode 0600, synced, renamed to ``<id>.json`` and the directory synced; the directories are created one
component at a time with mode 0700 and checked as above. A file that already has the id is read, never rewritten.
One difference: a ``.<uuid>.tmp`` that disappears between the directory listing and its ``lstat`` is skipped, by
``create``'s inspection and by ``list``, where Node fails (503 and 409). The library lists in a request thread while
``create`` renames on the event loop; Node's single thread meets that only through an outside removal.
``design_submission`` unwraps the ``design-submission/1`` envelope with Node's checks and messages, before the
request is normalized.
"""
from __future__ import annotations

import copy
import errno
import os
import re
import stat as stat_module
from typing import Any, Iterable, Optional, Sequence
import uuid

from ..schemas import jsjson
from ..server.workspace import LOCAL_OWNER
from . import nodefs, nodepath, records
from .identity import UNDEFINED, _js_string, js_truthy
from .records import scandir

__all__ = ['ANNOTATION_LIMITS', 'WORKSPACE_ANNOTATIONS', 'NODE_ANNOTATIONS', 'LOCAL_OWNER', 'SUBMISSION_SCHEMA',
           'AnnotationError', 'CoordinateSourceError', 'electrode_names', 'design_submission',
           'validate_electrode_annotation', 'public_value', 'ElectrodeAnnotations']

ANNOTATION_LIMITS = {'files': 2000, 'bytes': 64 * 1024 * 1024, 'fileBytes': 32768, 'referencesPerOwner': 20,
                     'referencesPerTask': 100}
SCHEMA = 'eeg-electrode-annotation/1'
SUBMISSION_SCHEMA = 'design-submission/1'
_SUBMISSION_KEYS = ('electrode_names', 'request', 'schema', 'source_metadata')
WORKSPACE_ANNOTATIONS = ('annotations', 'electrode-names')
NODE_ANNOTATIONS = ('results', 'v2', 'design_evaluation_jobs', 'electrode_annotations')
_SHA = re.compile('[a-f0-9]{64}')
_FILE = re.compile('[a-f0-9]{64}\\.json')
_TEMPORARY = re.compile('\\.[a-f0-9-]{36}\\.tmp')
_STORED_KEYS = 'electrode_names,id,owner,record_id,regions_sha256,request_sha256,schema,xyz_sha256'
_PUBLIC_KEYS = 'electrode_names,id,record_id,request_sha256,schema'

NOT_FOUND = 'Electrode name annotation not found.'
INTEGRITY = 'Electrode name annotation failed integrity checks.'
UNAVAILABLE = 'Electrode name storage is unavailable.'
INSPECTION = 'Electrode name storage needs inspection.'
LIMIT = 'Electrode name storage limit reached.'
TOO_LARGE = 'Electrode name metadata is too large.'
INVALID_IDENTITY = 'Invalid electrode annotation identity.'
INVALID_SUBMISSION = 'Invalid design submission metadata.'
NAMES = '需要64个不重复的电极名称，每个名称最多128个字符且不含控制字符。'
SOURCE = '坐标来源说明格式无效'


class AnnotationError(Exception):
    """Node's ``annotationSafe`` errors: shown to the browser with their status."""

    annotation_safe = True

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class CoordinateSourceError(ValueError):
    """``validateCoordinateSource``'s plain ``Error``: no status, so the routes answer 400 with its message."""

    def __init__(self) -> None:
        super().__init__(SOURCE)
        self.message = SOURCE


def _sha(value: Any) -> bool:
    """``SHA.test(value)`` (the argument converted to a string)."""
    return bool(_SHA.fullmatch(_js_string(value)))


def _hash(value: Any) -> str:
    return jsjson.sha256_hex(value)


def _utf16_length(text: str) -> int:
    return len(text.encode('utf-16-le', errors='surrogatepass')) // 2


def _has_name_control(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def electrode_names(value: Any) -> list:
    """``electrodeNames(value)``: 64 distinct names, each non-blank, at most 128 UTF-16 units, no control
    characters. Raises ``AnnotationError`` (400)."""
    if (not isinstance(value, list) or len(value) != 64
            or any(not isinstance(name, str) or not jsjson.js_trim(name) or _utf16_length(name) > 128
                   or _has_name_control(name) for name in value)
            or len(set(value)) != 64):
        raise AnnotationError(NAMES)
    return list(value)


def _sorted_keys(value: dict, skip: str = 'source_metadata') -> str:
    return ','.join(nodepath.js_sort(key for key in value if key != skip))


def _coordinate_source(value: Any) -> dict:
    """``validateCoordinateSource(value)`` through the phase 1 schema (the service extra): a copy in the input's key
    order, or ``CoordinateSourceError``."""
    from ..schemas.coordinate_source import normalize_coordinate_source
    try:
        return normalize_coordinate_source(value)
    except ValueError:
        raise CoordinateSourceError() from None


def _member(value: Any, name: str) -> Any:
    """``value.name`` of a parsed JSON value (``UNDEFINED`` when absent)."""
    return value.get(name, UNDEFINED) if isinstance(value, dict) else UNDEFINED


def design_submission(raw: Any) -> dict:
    """``designSubmission(raw)``: ``{'request': raw}`` unless ``raw.schema`` is ``design-submission/1``; then the
    envelope's ``request`` (not normalized here), its names and, when present, its canonical source metadata.
    Raises ``AnnotationError`` (400) for other keys, a falsy request or invalid names, and
    ``CoordinateSourceError`` for invalid source metadata (``null`` included), in Node's order."""
    if not _same_string(_member(raw, 'schema'), SUBMISSION_SCHEMA):
        return {'request': raw}
    if any(key not in _SUBMISSION_KEYS for key in raw) or not js_truthy(raw.get('request', UNDEFINED)):
        raise AnnotationError(INVALID_SUBMISSION)
    out = {'request': raw['request'], 'electrode_names': electrode_names(raw.get('electrode_names', UNDEFINED))}
    if 'source_metadata' in raw:
        out['source_metadata'] = _coordinate_source(raw['source_metadata'])
    return out


def validate_electrode_annotation(value: Any, record_id: Any) -> Any:
    """``validateElectrodeAnnotation(value, recordId)``: a public annotation (without owner) carried in a snapshot
    or delivery. Raises ``AnnotationError`` (400), or ``CoordinateSourceError`` for its source metadata."""
    if (not isinstance(value, dict) or _sorted_keys(value) != _PUBLIC_KEYS
            or value.get('schema') != SCHEMA or not _sha(value.get('id', UNDEFINED))
            or not _same_string(value.get('record_id', UNDEFINED), record_id)
            or not _sha(value.get('request_sha256', UNDEFINED))):
        raise AnnotationError('Invalid electrode name annotation.')
    electrode_names(value.get('electrode_names', UNDEFINED))
    if 'source_metadata' in value:
        _coordinate_source(value['source_metadata'])
    return value


def _same_string(a: Any, b: Any) -> bool:
    """``a === b`` where one side is a record id string."""
    return isinstance(a, str) and isinstance(b, str) and a == b


def public_value(value: dict) -> dict:
    """``publicValue(value)``: the stored annotation without its owner and geometry digests."""
    out = {'schema': value['schema'], 'id': value['id'], 'record_id': value['record_id'],
           'request_sha256': value['request_sha256'], 'electrode_names': list(value['electrode_names'])}
    if js_truthy(value.get('source_metadata', UNDEFINED)):
        out['source_metadata'] = _coordinate_source(value['source_metadata'])
    return out


def _plain_file(info: os.stat_result, limit: int) -> bool:
    return stat_module.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= limit


def _entry(path: str, name: str) -> Optional[os.stat_result]:
    """``lstat`` of a listed name; ``None`` for a temporary renamed or removed since the listing (a write that
    finished meanwhile: Node's single thread never lists in the middle of its own write, here a request thread may)."""
    try:
        return nodefs.lstat(path)
    except FileNotFoundError:
        if _TEMPORARY.fullmatch(name):
            return None
        raise


class ElectrodeAnnotations:
    """Annotation files in several directories, read without regard to their owner, and written to the first one.

    ``directories`` are ``(base, parts)`` pairs in search order: the base is resolved with ``fs.realpathSync`` (a
    missing base holds no annotations), and each part below it must be a real directory (Node's ``directory()``).
    With ``writable``, ``create`` writes to the first directory, creating its parts. ``owner`` is the owner of new
    annotations (Node's visitor id; the local user here). ``local(workspace, root)`` gives the service's two:
    ``W/annotations/electrode-names``, where new annotations go, and Node's
    ``R/results/v2/design_evaluation_jobs/electrode_annotations``, which is only read.

    For the workspace queue (``jobs.queue.WorkspaceQueue(annotations=...)``) it provides ``identity(prepared)``,
    ``read(id, key)`` and ``create(prepared)``, all synchronous.
    """

    def __init__(self, directories: Iterable[tuple[Optional[str], Sequence[str]]], limits: Optional[dict] = None, *,
                 owner: Any = LOCAL_OWNER, writable: bool = False):
        self.directories = tuple((base, tuple(parts)) for base, parts in directories if base)
        self.limits = dict(limits or ANNOTATION_LIMITS)
        self.owner = owner
        self.writable = writable and bool(self.directories)
        self._verified: dict[str, tuple[tuple[int, int, int], dict]] = {}

    @classmethod
    def local(cls, workspace_directory: Optional[str], root: str, *, owner: Any = LOCAL_OWNER,
              limits: Optional[dict] = None) -> 'ElectrodeAnnotations':
        """The workspace's annotation directory (``W/annotations/electrode-names``, given in full), writable, and
        Node's. Below the workspace W, ``annotations`` and ``electrode-names`` are both checked (and created) as
        Node checks the components below its root; another directory name is checked from its parent."""
        directories: list[tuple[Optional[str], Sequence[str]]] = []
        if workspace_directory:
            path = nodepath.resolve(workspace_directory)
            names = tuple(path.split('/')[1:])
            if names[-2:] == WORKSPACE_ANNOTATIONS and len(names) > 2:
                directories.append(('/' + '/'.join(names[:-2]), WORKSPACE_ANNOTATIONS))
            else:
                parent = nodepath.dirname(path)
                directories.append((parent, (path[len(parent):].lstrip('/'),)))
        directories.append((root, NODE_ANNOTATIONS))
        return cls(directories, limits, owner=owner, writable=bool(workspace_directory))

    def directory(self, base: str, parts: Sequence[str], create: bool = False) -> Optional[str]:
        """``directory(create)``: the checked directory. A missing component means ``None``, or with ``create`` is
        made with mode 0700 (``mkdirSync(current, {mode: 0o700})``); with ``create`` a missing base raises."""
        try:
            current = nodefs.realpath_sync(base)
        except OSError as error:
            if not create and error.errno in (errno.ENOENT, errno.ENOTDIR):
                return None
            raise
        for part in parts:
            current = nodepath.join(current, part)
            if not os.path.exists(nodefs.encode(current)):
                if not create:
                    return None
                os.mkdir(nodefs.encode(current), 0o700)
            info = nodefs.lstat(current)
            if (not stat_module.S_ISDIR(info.st_mode) or stat_module.S_ISLNK(info.st_mode)
                    or nodefs.realpath_sync(current) != current):
                raise AnnotationError(UNAVAILABLE, 409)
        return current

    def identity(self, prepared: Any) -> dict:
        """``identity(prepared, owner)`` with this store's owner: ``{id, schema, owner, record_id, request_sha256,
        xyz_sha256, regions_sha256, electrode_names[, source_metadata]}`` for what the design adapter prepares (the
        canonical ``request``, its ``key``, the ``electrode_names`` and, when sent, the ``source_metadata``). Raises
        ``AnnotationError`` (400) for invalid names, then for an invalid key or owner, and ``CoordinateSourceError``
        for invalid source metadata."""
        names = electrode_names(_member(prepared, 'electrode_names'))
        owner = self.owner
        if (not _sha(_member(prepared, 'key')) or not isinstance(owner, str) or not owner
                or _utf16_length(owner) > 128):
            raise AnnotationError(INVALID_IDENTITY)
        request = prepared['request']
        identity = {'schema': SCHEMA, 'owner': owner, 'record_id': prepared['key'], 'request_sha256': _hash(request),
                    'xyz_sha256': _hash(request['design']['xyz_mm']),
                    'regions_sha256': _hash(request['design']['region_indices']), 'electrode_names': names}
        source = _member(prepared, 'source_metadata')
        if source is not UNDEFINED:
            identity['source_metadata'] = _coordinate_source(source)
        return {'id': _hash(identity), **identity}

    def create(self, prepared: Any) -> dict:
        """``create(prepared, owner)``: the public value of the annotation of ``prepared``, written once to the
        first directory. A file with its id is read instead (never rewritten). Raises ``AnnotationError``: 413 for a
        file over ``fileBytes``, 409 for a directory holding anything but annotations and temporaries (or that is
        not a real directory), 507 at ``files`` files or beyond ``bytes`` in all, 503 when it cannot be written; and
        what ``identity`` and ``read`` raise."""
        value = self.identity(prepared)
        id = value['id']
        data = jsjson.stringify(value).encode('utf-8')
        if len(data) > self.limits['fileBytes']:
            raise AnnotationError(TOO_LARGE, 413)
        try:
            if not self.writable:
                raise AnnotationError(UNAVAILABLE, 503)
            directory = self.directory(*self.directories[0], create=True)
            path = nodepath.join(directory, f'{id}.json')
            if os.path.exists(nodefs.encode(path)):
                return self.read(id, prepared['key'])
            count = total = 0
            for name, _ in scandir(directory):
                if not _FILE.fullmatch(name) and not _TEMPORARY.fullmatch(name):
                    raise AnnotationError(INSPECTION, 409)
                info = _entry(nodepath.join(directory, name), name)
                if info is None:
                    continue
                if stat_module.S_ISLNK(info.st_mode) or not _plain_file(info, self.limits['fileBytes']):
                    raise AnnotationError(INSPECTION, 409)
                count += 1
                total += info.st_size
            if count >= self.limits['files'] or total + len(data) > self.limits['bytes']:
                raise AnnotationError(LIMIT, 507)
            # Node's calls: open 'wx' 0o600, write, fsync, close; rename, fsync the directory; unlink a leftover.
            temporary = nodepath.join(directory, f'.{uuid.uuid4()}.tmp')
            records._write_new(temporary, data)
            try:
                records._rename(temporary, path)
                records._sync_directory(directory)
            finally:
                if os.path.exists(nodefs.encode(temporary)):
                    os.unlink(nodefs.encode(temporary))
            return public_value(value)
        except AnnotationError:
            raise
        except Exception:  # noqa: BLE001 - Node reports every other failure this way
            raise AnnotationError(UNAVAILABLE, 503) from None

    def read(self, id: Any, record_id: Any) -> dict:
        """``read(id, owner, recordId)`` without the owner: the public value of annotation ``id`` of record
        ``record_id`` from the first directory that has the file. Raises ``AnnotationError``: 404 when it is
        missing or belongs to another record, 409 when it fails its checks, 400 for invalid names."""
        if not _sha('' if id is None else id) or not _sha('' if record_id is None else record_id):
            raise AnnotationError(NOT_FOUND, 404)
        try:
            for base, parts in self.directories:
                directory = self.directory(base, parts)
                path = directory and nodepath.join(directory, f'{id}.json')
                if path and os.path.exists(nodefs.encode(path)):
                    return self._read(path, id, record_id)
            raise AnnotationError(NOT_FOUND, 404)
        except AnnotationError:
            raise
        except Exception:  # noqa: BLE001 - Node reports every other failure this way
            raise AnnotationError(UNAVAILABLE, 409) from None

    def _read(self, path: str, id: str, record_id: Any) -> dict:
        """The checks of ``read`` on one file, after its directory and name."""
        if not _sha('' if record_id is None else record_id):
            raise AnnotationError(NOT_FOUND, 404)
        info = nodefs.lstat(path)
        if stat_module.S_ISLNK(info.st_mode) or not _plain_file(info, self.limits['fileBytes']):
            raise AnnotationError(INTEGRITY, 409)
        value = self._file(path)
        if value is None:
            raise AnnotationError(UNAVAILABLE, 409)  # destructuring null throws a TypeError
        if not isinstance(value, dict):
            raise AnnotationError(INTEGRITY, 409)
        identity = {key: item for key, item in value.items() if key != 'id'}
        if (_sorted_keys(value) != _STORED_KEYS or not _same_string(value.get('id'), id) or _hash(identity) != id
                or value.get('schema') != SCHEMA or not _sha(value['request_sha256'])
                or not _sha(value['xyz_sha256']) or not _sha(value['regions_sha256'])):
            raise AnnotationError(INTEGRITY, 409)
        electrode_names(value['electrode_names'])
        if 'source_metadata' in value:
            _coordinate_source(value['source_metadata'])
        if not _same_string(value['record_id'], record_id):
            raise AnnotationError(NOT_FOUND, 404)
        return public_value(value)

    def _file(self, path: str) -> Any:
        """``file(path)``: a regular file with one link, opened without following a link, read once whole."""
        limit = self.limits['fileBytes']
        fd = os.open(nodefs.encode(path), os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
        try:
            before = os.fstat(fd)
            if not _plain_file(before, limit):
                raise AnnotationError(INTEGRITY, 409)
            chunks, length = [], 0
            while length < limit + 1:
                chunk = os.read(fd, limit + 1 - length)
                if not chunk:
                    break
                chunks.append(chunk)
                length += len(chunk)
            data = b''.join(chunks)
            if len(data) > limit or len(data) != before.st_size or os.fstat(fd).st_size != before.st_size:
                raise AnnotationError(INTEGRITY, 409)
            return jsjson.parse(nodefs.decode(data))
        finally:
            os.close(fd)

    def list(self) -> list[dict]:
        """``list(owner)`` for every owner: the public values of all annotations, directory by directory in Node's
        name order (an id already listed from an earlier directory is skipped). Each file state is verified once.
        Raises ``AnnotationError``: 409 for a directory holding anything but annotations and temporary files, 507
        beyond the file limit."""
        result: list[dict] = []
        listed: set[str] = set()
        for base, parts in self.directories:
            directory = self.directory(base, parts)
            if directory is None:
                continue
            names = [name for name, _ in scandir(directory)]
            if len(names) > self.limits['files']:
                raise AnnotationError(LIMIT, 507)
            try:
                for name in names:
                    path = nodepath.join(directory, name)
                    if _TEMPORARY.fullmatch(name):
                        info = _entry(path, name)
                        if info is not None and (stat_module.S_ISLNK(info.st_mode)
                                                 or not _plain_file(info, self.limits['fileBytes'])):
                            raise AnnotationError(INSPECTION, 409)
                        continue
                    if not _FILE.fullmatch(name):
                        raise AnnotationError(INSPECTION, 409)
                    info = nodefs.lstat(path)
                    if stat_module.S_ISLNK(info.st_mode) or not _plain_file(info, self.limits['fileBytes']):
                        raise AnnotationError(INSPECTION, 409)
                    # Content-addressed files are never rewritten: verify each file state once.
                    stamp = (info.st_ino, info.st_size, info.st_mtime_ns)
                    known = self._verified.get(path)
                    if known is None or known[0] != stamp:
                        value = self._file(path)
                        if value is None:
                            raise AnnotationError(UNAVAILABLE, 409)
                        record_id = value.get('record_id', UNDEFINED) if isinstance(value, dict) else UNDEFINED
                        known = (stamp, self._read(path, name[:-5], record_id))
                        self._verified[path] = known
                    if known[1]['id'] not in listed:
                        listed.add(known[1]['id'])
                        result.append(copy.deepcopy(known[1]))
            except AnnotationError:
                raise
            except Exception:  # noqa: BLE001
                raise AnnotationError(UNAVAILABLE, 409) from None
        return result
