"""Electrode-name annotations, read side: Node's ``annotations/electrode-names.mjs`` (``electrodeNames``,
``validateElectrodeAnnotation`` and the reads of ``ElectrodeAnnotations``).

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
"""
from __future__ import annotations

import copy
import errno
import os
import re
import stat as stat_module
from typing import Any, Iterable, Optional, Sequence

from ..schemas import jsjson
from . import nodefs, nodepath
from .identity import UNDEFINED, _js_string, js_truthy
from .records import scandir

__all__ = ['ANNOTATION_LIMITS', 'WORKSPACE_ANNOTATIONS', 'NODE_ANNOTATIONS', 'AnnotationError', 'electrode_names',
           'validate_electrode_annotation', 'public_value', 'ElectrodeAnnotations']

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

NOT_FOUND = 'Electrode name annotation not found.'
INTEGRITY = 'Electrode name annotation failed integrity checks.'
UNAVAILABLE = 'Electrode name storage is unavailable.'
INSPECTION = 'Electrode name storage needs inspection.'
LIMIT = 'Electrode name storage limit reached.'
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
    """``validateCoordinateSource(value)`` through the phase 1 schema (the service extra)."""
    from ..schemas.coordinate_source import normalize_coordinate_source
    return normalize_coordinate_source(value)


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
    """Annotation files in several directories, read without regard to their owner.

    ``directories`` are ``(base, parts)`` pairs in search order: the base is resolved with ``fs.realpathSync`` (a
    missing base holds no annotations), and each part below it must be a real directory (Node's ``directory()``).
    ``local(workspace, root)`` gives the service's two: ``W/annotations/electrode-names`` and Node's
    ``R/results/v2/design_evaluation_jobs/electrode_annotations``.
    """

    def __init__(self, directories: Iterable[tuple[Optional[str], Sequence[str]]], limits: Optional[dict] = None):
        self.directories = tuple((base, tuple(parts)) for base, parts in directories if base)
        self.limits = dict(limits or ANNOTATION_LIMITS)
        self._verified: dict[str, tuple[tuple[int, int, int], dict]] = {}

    @classmethod
    def local(cls, workspace_directory: Optional[str], root: str) -> 'ElectrodeAnnotations':
        """The workspace's annotation directory (``W/annotations/electrode-names``, given in full) and Node's."""
        directories: list[tuple[Optional[str], Sequence[str]]] = []
        if workspace_directory:
            path = nodepath.resolve(workspace_directory)
            parent = nodepath.dirname(path)
            directories.append((parent, (path[len(parent):].lstrip('/'),)))
        directories.append((root, NODE_ANNOTATIONS))
        return cls(directories)

    def directory(self, base: str, parts: Sequence[str]) -> Optional[str]:
        """``directory()``: the checked directory, or ``None`` when a component is missing."""
        try:
            current = nodefs.realpath_sync(base)
        except OSError as error:
            if error.errno in (errno.ENOENT, errno.ENOTDIR):
                return None
            raise
        for part in parts:
            current = nodepath.join(current, part)
            if not os.path.exists(nodefs.encode(current)):
                return None
            info = nodefs.lstat(current)
            if (not stat_module.S_ISDIR(info.st_mode) or stat_module.S_ISLNK(info.st_mode)
                    or nodefs.realpath_sync(current) != current):
                raise AnnotationError(UNAVAILABLE, 409)
        return current

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
