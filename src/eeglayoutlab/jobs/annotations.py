"""Electrode-name annotations, read and write sides: Node's ``annotations/electrode-names.mjs``
(``electrodeNames``, ``designSubmission``, ``validateElectrodeAnnotation`` and ``ElectrodeAnnotations``).

An annotation is immutable, content-addressed presentation metadata for a saved design evaluation (its 64
electrode names and, optionally, where the coordinates came from); it never enters a scientific key. A file is
``{id, schema, owner, record_id, request_sha256, xyz_sha256, regions_sha256, electrode_names, source_metadata?}``
with ``id = sha256(JSON.stringify(<the file without id>))``, so the owner stored in the file is covered by the id.

The local service has one user (design 0001, decision 6): annotations are read without regard to their owner, from
several directories in order: the workspace's ``W/annotations/electrode-names/`` first, then Node's
``R/results/v2/design_evaluation_jobs/electrode_annotations/``. New annotations are written atomically to the first
directory in ``self.directories`` (``W/annotations/electrode-names/`` when configured for a workspace) with mode
``0600`` inside ``0700`` directories.
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
from . import nodefs, nodepath
from .identity import UNDEFINED, _js_string, js_truthy
from .records import scandir

__all__ = [
    'ANNOTATION_LIMITS', 'WORKSPACE_ANNOTATIONS', 'NODE_ANNOTATIONS', 'AnnotationError', 'electrode_names',
    'design_submission', 'validate_electrode_annotation', 'public_value', 'ElectrodeAnnotations',
]

ANNOTATION_LIMITS = {'files': 2000, 'bytes': 64 * 1024 * 1024, 'fileBytes': 32768, 'referencesPerOwner': 20,
                     'referencesPerTask': 100}
SCHEMA = 'eeg-electrode-annotation/1'
WORKSPACE_ANNOTATIONS = ('annotations', 'electrode-names')
NODE_ANNOTATIONS = ('results', 'v2', 'design_evaluation_jobs', 'electrode_annotations')
_SHA = re.compile('[a-f0-9]{64}')
_FILE = re.compile('[a-f0-9]{64}\\.json')
_TEMPORARY = re.compile('\\.[a-f0-9-]{36}\\.tmp')
_STORED_KEYS = 'electrode_names,id,owner,record_id,regions_sha256,request_sha256,schema,xyz_sha256'
_PUBLIC_KEYS = 'electrode_names,id,record_id,request_sha256,schema'
_SUBMISSION_KEYS = frozenset({'electrode_names', 'request', 'schema', 'source_metadata'})

NOT_FOUND = 'Electrode name annotation not found.'
INTEGRITY = 'Electrode name annotation failed integrity checks.'
UNAVAILABLE = 'Electrode name storage is unavailable.'
INSPECTION = 'Electrode name storage needs inspection.'
LIMIT = 'Electrode name storage limit reached.'
TOO_LARGE = 'Electrode name metadata is too large.'
INVALID_IDENTITY = 'Invalid electrode annotation identity.'
INVALID_SUBMISSION = 'Invalid design submission metadata.'
NAMES = '需要64个不重复的电极名称，每个名称最多128个字符且不含控制字符。'


class AnnotationError(Exception):
    """Node's ``annotationSafe`` errors: shown to the browser with their status."""

    annotation_safe = True

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _sha(value: Any) -> bool:
    """``SHA.test(value)`` (the argument converted to a string)."""
    return bool(_SHA.fullmatch(_js_string(value)))


def _hash(value: Any) -> str:
    return jsjson.sha256_hex(value)


def _utf16_length(text: str) -> int:
    return len(text.encode('utf-16-le', errors='surrogatepass')) // 2


def _has_name_control(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def electrode_names(value: Any) -> list[str]:
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
    """``validateCoordinateSource(value)`` through the coordinate-source schema."""
    from ..schemas.coordinate_source import normalize_coordinate_source
    return normalize_coordinate_source(value)


def design_submission(raw: Any) -> dict[str, Any]:
    """``designSubmission(raw)`` (webapp/server/annotations/electrode-names.mjs): unwraps ``design-submission/1``
    into ``{request, electrode_names?, source_metadata?}`` or passes bare requests through as ``{request: raw}``."""
    if not isinstance(raw, dict) or raw.get('schema') != 'design-submission/1':
        return {'request': raw}
    if any(key not in _SUBMISSION_KEYS for key in raw) or not js_truthy(raw.get('request', UNDEFINED)):
        raise AnnotationError(INVALID_SUBMISSION)
    out: dict[str, Any] = {
        'request': raw['request'],
        'electrode_names': electrode_names(raw.get('electrode_names', UNDEFINED)),
    }
    if 'source_metadata' in raw and raw['source_metadata'] is not UNDEFINED:
        out['source_metadata'] = _coordinate_source(raw['source_metadata'])
    return out


def validate_electrode_annotation(value: Any, record_id: Any) -> Any:
    """``validateElectrodeAnnotation(value, recordId)``: a public annotation (without owner) carried in a snapshot
    or delivery. Raises ``AnnotationError`` (400), or the schema's ``ValueError`` for its source metadata."""
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


class ElectrodeAnnotations:
    """Annotation files in several directories, read without regard to their owner and created in the first.

    ``directories`` are ``(base, parts)`` pairs in search order: the base is resolved with ``fs.realpathSync`` (a
    missing base holds no annotations), and each part below it must be a real directory (Node's ``directory()``).
    ``local(workspace, root)`` gives the service's two: ``W/annotations/electrode-names`` and Node's
    ``R/results/v2/design_evaluation_jobs/electrode_annotations``.
    """

    def __init__(self, directories: Iterable[tuple[Optional[str], Sequence[str]]], limits: Optional[dict] = None):
        self.directories = tuple((base, tuple(parts)) for base, parts in directories if base)
        self.limits = {**ANNOTATION_LIMITS, **(limits or {})}
        self._verified: dict[str, tuple[tuple[int, int, int], dict]] = {}

    @classmethod
    def local(cls, workspace_directory: Optional[str], root: str, *,
              limits: Optional[dict] = None) -> 'ElectrodeAnnotations':
        """The workspace's annotation directory (``W/annotations/electrode-names``, given in full) and Node's."""
        directories: list[tuple[Optional[str], Sequence[str]]] = []
        if workspace_directory:
            path = nodepath.resolve(workspace_directory)
            suffix = '/' + '/'.join(WORKSPACE_ANNOTATIONS)
            if path.endswith(suffix) and len(path) > len(suffix):
                directories.append((path[:-len(suffix)], WORKSPACE_ANNOTATIONS))
            else:
                parent = nodepath.dirname(path)
                directories.append((parent, (path[len(parent):].lstrip('/'),)))
        if root:
            directories.append((root, NODE_ANNOTATIONS))
        return cls(directories, limits=limits)

    def directory(self, base: str, parts: Sequence[str], *, create: bool = False) -> Optional[str]:
        """``directory(create)``: the checked directory, or ``None`` when a component is missing and ``create`` is
        false."""
        try:
            current = nodefs.realpath_sync(base)
        except OSError as error:
            if error.errno in (errno.ENOENT, errno.ENOTDIR) and not create:
                return None
            raise
        for part in parts:
            current = nodepath.join(current, part)
            encoded = nodefs.encode(current)
            if not os.path.lexists(encoded):
                if not create:
                    return None
                os.mkdir(encoded, 0o700)
            info = nodefs.lstat(current)
            if (not stat_module.S_ISDIR(info.st_mode) or stat_module.S_ISLNK(info.st_mode)
                    or nodefs.realpath_sync(current) != current):
                raise AnnotationError(UNAVAILABLE, 409)
        return current

    def write_directory(self, *, create: bool = False) -> Optional[str]:
        """The primary writable annotation directory (the first configured ``(base, parts)`` pair)."""
        if not self.directories:
            if create:
                raise AnnotationError(UNAVAILABLE, 503)
            return None
        base, parts = self.directories[0]
        assert base is not None
        return self.directory(base, parts, create=create)

    def identity(self, prepared: dict[str, Any], owner: str = LOCAL_OWNER) -> dict[str, Any]:
        """``identity(prepared, owner)``: the content-addressed stored annotation dict with ``id`` first."""
        names = electrode_names(prepared.get('electrode_names', UNDEFINED))
        key = prepared.get('key', UNDEFINED)
        if not _sha(key) or not isinstance(owner, str) or not owner or _utf16_length(owner) > 128:
            raise AnnotationError(INVALID_IDENTITY)
        req = prepared['request']
        design = req['design']
        body: dict[str, Any] = {
            'schema': SCHEMA,
            'owner': owner,
            'record_id': key,
            'request_sha256': _hash(req),
            'xyz_sha256': _hash(design['xyz_mm']),
            'regions_sha256': _hash(design['region_indices']),
            'electrode_names': names,
        }
        if 'source_metadata' in prepared and prepared['source_metadata'] is not UNDEFINED:
            body['source_metadata'] = _coordinate_source(prepared['source_metadata'])
        return {'id': _hash(body), **body}

    def create(self, prepared: dict[str, Any], owner: str = LOCAL_OWNER) -> dict[str, Any]:
        """``create(prepared, owner)``: validates and atomically writes the annotation sidecar if absent, returning
        its public value (without ``owner``)."""
        value = self.identity(prepared, owner)
        ann_id = value['id']
        raw = jsjson.stringify(value).encode('utf-8')
        if len(raw) > self.limits['fileBytes']:
            raise AnnotationError(TOO_LARGE, 413)
        try:
            directory = self.write_directory(create=True)
            if directory is None:
                raise AnnotationError(UNAVAILABLE, 503)
            path = nodepath.join(directory, f'{ann_id}.json')
            if os.path.lexists(nodefs.encode(path)):
                return self.read(ann_id, prepared['key'])
            total_bytes = 0
            count = 0
            for name, _ in scandir(directory):
                if not _FILE.fullmatch(name) and not _TEMPORARY.fullmatch(name):
                    raise AnnotationError(INSPECTION, 409)
                item = nodefs.lstat(nodepath.join(directory, name))
                if stat_module.S_ISLNK(item.st_mode) or not _plain_file(item, self.limits['fileBytes']):
                    raise AnnotationError(INSPECTION, 409)
                count += 1
                total_bytes += item.st_size
            if count >= self.limits['files'] or total_bytes + len(raw) > self.limits['bytes']:
                raise AnnotationError(LIMIT, 507)
            temporary = nodepath.join(directory, f'.{uuid.uuid4()}.tmp')
            tmp_enc = nodefs.encode(temporary)
            fd = os.open(tmp_enc, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0),
                         0o600)
            try:
                try:
                    view = memoryview(raw)
                    written = 0
                    while written < len(view):
                        written += os.write(fd, view[written:])
                    os.fsync(fd)
                finally:
                    os.close(fd)
                os.replace(tmp_enc, nodefs.encode(path))
                dir_fd = os.open(nodefs.encode(directory), os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0))
                try:
                    try:
                        os.fsync(dir_fd)
                    except OSError as err:
                        if err.errno not in (errno.EINVAL, errno.ENOTSUP):
                            raise
                finally:
                    os.close(dir_fd)
            finally:
                if os.path.lexists(tmp_enc):
                    try:
                        os.unlink(tmp_enc)
                    except OSError:
                        pass
            return public_value(value)
        except AnnotationError:
            raise
        except Exception:  # noqa: BLE001 - Node reports storage write failures as 503
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
                if path and os.path.lexists(nodefs.encode(path)):
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
                        info = nodefs.lstat(path)
                        if stat_module.S_ISLNK(info.st_mode) or not _plain_file(info, self.limits['fileBytes']):
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
