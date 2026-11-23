"""The ``eeglayoutlab-data-package/1`` manifest.

A manifest names one package and one version, lists every file with its size and SHA-256 by its path relative to
the scientific root, and records the licences and sources of the data, the packages it needs and the code
versions that accept it. ``content_sha256`` identifies the file set independently of the version label. When the
package is published as an archive, ``archive`` gives the archive's file name, size and SHA-256; the archive sits
beside the manifest.

Example::

    {"schema": "eeglayoutlab-data-package/1", "name": "head-ixi002", "version": "1.0.0", "kind": "head",
     "description": "...", "accepts_code": ">=0.2.0,<1.0.0", "requires": ["base"],
     "licenses": [{"source": "IXI", "license": "CC-BY-SA-3.0", "url": "...", "applies_to": ["..."]}],
     "notes": [], "files": [{"path": "results/v2/heads/ixi002/package.json", "size": 5120, "sha256": "..."}],
     "total_size": 1073741824, "content_sha256": "...",
     "archive": {"name": "head-ixi002-1.0.0.tar", "size": 1073750016, "sha256": "..."}}
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import pathlib
from pathlib import PurePosixPath
import re
from typing import Any, Iterable, Mapping, Optional

SCHEMA = 'eeglayoutlab-data-package/1'
KINDS = ('base', 'scalp-node-table', 'conductivity-scenario-table', 'head')
NAME = re.compile(r'^[a-z0-9]+(?:[._-][a-z0-9]+)*$')
VERSION = re.compile(r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')
SHA256 = re.compile(r'^[0-9a-f]{64}$')
# Package files live only under these parts of the scientific root.
NAMESPACES = ('data/external/', 'results/v2/')
EXTRA_FILES = ('data/SOURCES.md',)
CHUNK = 1 << 20


class PackageError(ValueError):
    """A manifest, an archive or an installed package failed validation."""


def relative_path(value: Any) -> str:
    """``value`` when it is a plain POSIX path relative to the scientific root, inside the package namespaces."""
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value
            or any(ord(c) < 32 for c in value)):
        raise PackageError(f'unsafe path {value!r}')
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ('', '.', '..') for part in value.split('/')) or str(path) != value:
        raise PackageError(f'unsafe path {value!r}')
    if not (value.startswith(NAMESPACES) or value in EXTRA_FILES):
        raise PackageError(f'{value} is outside data/external/ and results/v2/')
    return value


def sha256_file(path: pathlib.Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(CHUNK), b''):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


@dataclass(frozen=True)
class FileEntry:
    path: str
    size: int
    sha256: str

    def as_json(self) -> dict[str, Any]:
        return {'path': self.path, 'size': self.size, 'sha256': self.sha256}


def content_sha256(files: Iterable[FileEntry]) -> str:
    """SHA-256 of the sorted ``<sha256> <size> <path>`` lines: the identity of the file set."""
    lines = sorted(f'{entry.sha256} {entry.size} {entry.path}\n' for entry in files)
    return hashlib.sha256(''.join(lines).encode('utf-8')).hexdigest()


def _version_key(text: str) -> tuple[int, int, int]:
    match = VERSION.match(text)
    if not match:
        raise PackageError(f'invalid version {text!r}; use MAJOR.MINOR.PATCH')
    return int(match[1]), int(match[2]), int(match[3])


def accepts(requirement: str, code_version: str) -> bool:
    """Whether ``code_version`` meets ``requirement``, a comma-separated list of ``>=``, ``>``, ``<=``, ``<`` and
    ``==`` clauses on MAJOR.MINOR.PATCH versions."""
    have = _version_key(code_version)
    for clause in requirement.split(','):
        match = re.fullmatch(r'\s*(>=|<=|==|>|<)\s*([0-9.]+)\s*', clause)
        if not match:
            raise PackageError(f'invalid version requirement {requirement!r}')
        want = _version_key(match[2])
        ok = {'>=': have >= want, '<=': have <= want, '==': have == want, '>': have > want, '<': have < want}[match[1]]
        if not ok:
            return False
    return True


@dataclass(frozen=True)
class Manifest:
    name: str
    version: str
    kind: str
    description: str
    accepts_code: str
    files: tuple[FileEntry, ...]
    requires: tuple[str, ...] = ()
    licenses: tuple[Mapping[str, Any], ...] = ()
    notes: tuple[str, ...] = ()
    archive: Optional[Mapping[str, Any]] = None

    @property
    def total_size(self) -> int:
        return sum(entry.size for entry in self.files)

    @property
    def content_sha256(self) -> str:
        return content_sha256(self.files)

    @property
    def stem(self) -> str:
        return f'{self.name}-{self.version}'

    def with_archive(self, name: str, size: int, sha256: str) -> 'Manifest':
        return Manifest(self.name, self.version, self.kind, self.description, self.accepts_code, self.files,
                        self.requires, self.licenses, self.notes, {'name': name, 'size': size, 'sha256': sha256})

    def as_json(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            'schema': SCHEMA, 'name': self.name, 'version': self.version, 'kind': self.kind,
            'description': self.description, 'accepts_code': self.accepts_code, 'requires': list(self.requires),
            'licenses': [dict(item) for item in self.licenses], 'notes': list(self.notes),
            'files': [entry.as_json() for entry in self.files], 'total_size': self.total_size,
            'content_sha256': self.content_sha256,
        }
        if self.archive is not None:
            value['archive'] = dict(self.archive)
        return value

    def dumps(self) -> str:
        return json.dumps(self.as_json(), indent=2, ensure_ascii=False) + '\n'


def parse(value: Any) -> Manifest:
    """A validated manifest from parsed JSON."""
    if not isinstance(value, dict) or value.get('schema') != SCHEMA:
        raise PackageError(f'not an {SCHEMA} manifest')
    name, version, kind = value.get('name'), value.get('version'), value.get('kind')
    if not isinstance(name, str) or not NAME.match(name) or len(name) > 64:
        raise PackageError(f'invalid package name {name!r}')
    if not isinstance(version, str):
        raise PackageError('invalid version')
    _version_key(version)
    if kind not in KINDS:
        raise PackageError(f'invalid kind {kind!r}')
    accepts_code = value.get('accepts_code')
    if not isinstance(accepts_code, str):
        raise PackageError('accepts_code must be a string')
    accepts(accepts_code, '0.0.0')  # syntax check
    requires = value.get('requires', [])
    if not isinstance(requires, list) or not all(isinstance(r, str) and NAME.match(r) for r in requires):
        raise PackageError('requires must list package names')
    raw_files = value.get('files')
    if not isinstance(raw_files, list) or not raw_files:
        raise PackageError('files must be a nonempty list')
    files, folded = [], set()
    for item in raw_files:
        if not isinstance(item, dict):
            raise PackageError('invalid file entry')
        path = relative_path(item.get('path'))
        size, digest = item.get('size'), item.get('sha256')
        if type(size) is not int or size < 0:
            raise PackageError(f'invalid size for {path}')
        if not isinstance(digest, str) or not SHA256.match(digest):
            raise PackageError(f'invalid sha256 for {path}')
        if path.casefold() in folded:
            raise PackageError(f'duplicate or case-ambiguous path {path}')
        folded.add(path.casefold())
        files.append(FileEntry(path, size, digest))
    for entry in files:
        if any(str(parent).casefold() in folded for parent in PurePosixPath(entry.path).parents):
            raise PackageError(f'{entry.path} is inside another file path')
    manifest = Manifest(name, version, kind, str(value.get('description', '')), accepts_code, tuple(files),
                        tuple(requires), tuple(value.get('licenses', [])), tuple(value.get('notes', [])),
                        value.get('archive'))
    if value.get('total_size') != manifest.total_size:
        raise PackageError('total_size does not match the files')
    if value.get('content_sha256') != manifest.content_sha256:
        raise PackageError('content_sha256 does not match the files')
    archive = manifest.archive
    if archive is not None:
        if (not isinstance(archive, dict) or archive.get('name') != f'{manifest.stem}.tar'
                or type(archive.get('size')) is not int or not SHA256.match(str(archive.get('sha256')))):
            raise PackageError('invalid archive entry')
    return manifest


def loads(text: str) -> Manifest:
    try:
        value = json.loads(text)
    except ValueError as error:
        raise PackageError(f'manifest is not JSON: {error}') from error
    return parse(value)
