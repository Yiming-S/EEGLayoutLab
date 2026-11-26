"""Deterministic package archives and their safe extraction.

An archive is an uncompressed POSIX (pax) tar of the package's files at their root-relative paths, in manifest
order, with fixed owner, mode and time, so the same files always give the same bytes. The forward tables are
binary arrays that compress little, so the archive is not compressed.

Extraction reads the archive as a stream and never calls ``extract``/``extractall``: each member must be a regular
file listed in the manifest, listed once, and its bytes are written under the staging directory while their size and
SHA-256 are checked; the archive's own size and SHA-256 are checked at the end.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import tarfile
from typing import BinaryIO, Callable, Optional

from .manifest import CHUNK, FileEntry, Manifest, PackageError, sha256_file

Progress = Callable[[int], None]
ENCODING = 'utf-8'


def _member(entry: FileEntry) -> tarfile.TarInfo:
    info = tarfile.TarInfo(entry.path)
    info.size, info.mode, info.mtime = entry.size, 0o644, 0
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    return info


def archive_size(manifest: Manifest) -> int:
    """The exact size of the archive ``write_archive`` writes for ``manifest``, without reading any file."""
    size = 0
    for entry in manifest.files:
        size += len(_member(entry).tobuf(tarfile.PAX_FORMAT, ENCODING, 'surrogateescape'))
        size += -(-entry.size // tarfile.BLOCKSIZE) * tarfile.BLOCKSIZE
    size += 2 * tarfile.BLOCKSIZE
    return -(-size // tarfile.RECORDSIZE) * tarfile.RECORDSIZE


class _HashSink:
    """File-like write sink that counts and hashes tar bytes in memory without touching disk."""

    def __init__(self) -> None:
        self.digest = hashlib.sha256()
        self.size = 0

    def write(self, data: bytes) -> int:
        self.digest.update(data)
        self.size += len(data)
        return len(data)


def archive_digest(root: pathlib.Path, manifest: Manifest,
                   progress: Optional[Progress] = None) -> tuple[int, str]:
    """Computes the exact ``(size, sha256)`` of ``write_archive(root, manifest, ...)`` without writing an archive."""
    sink = _HashSink()
    with tarfile.open(fileobj=sink, mode='w|', format=tarfile.PAX_FORMAT, encoding=ENCODING) as tar:  # type: ignore[call-overload]
        for entry in manifest.files:
            with (root / entry.path).open('rb') as stream:
                checked = _CheckedReader(stream, entry.path, entry.size, entry.sha256, progress)
                tar.addfile(_member(entry), checked)
                checked.finish()
    return sink.size, sink.digest.hexdigest()


def write_archive(root: pathlib.Path, manifest: Manifest, out: pathlib.Path,
                  progress: Optional[Progress] = None) -> tuple[int, str]:
    """Writes the archive of ``manifest``'s files from ``root`` to ``out``; returns its size and SHA-256. Each file
    is checked against the manifest while it is read."""
    partial = out.with_name(out.name + '.partial')
    try:
        with tarfile.open(partial, 'w', format=tarfile.PAX_FORMAT, encoding=ENCODING) as tar:
            for entry in manifest.files:
                with (root / entry.path).open('rb') as stream:
                    checked = _CheckedReader(stream, entry.path, entry.size, entry.sha256, progress)
                    tar.addfile(_member(entry), checked)
                    checked.finish()
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    os.replace(partial, out)
    digest, size = sha256_file(out)
    return size, digest


class _CheckedReader:
    """A reader that hashes what it passes on and fails when the file differs from the manifest."""

    def __init__(self, stream: BinaryIO, path: str, size: int, sha256: str, progress: Optional[Progress]):
        self._stream, self._path, self._size, self._sha256 = stream, path, size, sha256
        self._digest, self._read, self._progress = hashlib.sha256(), 0, progress

    def read(self, count: int = -1) -> bytes:
        block = self._stream.read(count)
        self._digest.update(block)
        self._read += len(block)
        if self._progress and block:
            self._progress(len(block))
        return block

    def finish(self) -> None:
        if self._stream.read(1) or self._read != self._size or self._digest.hexdigest() != self._sha256:
            raise PackageError(f'{self._path} changed: it no longer matches the manifest')


class _HashingReader:
    """Passes a stream on while counting and hashing every byte read from it."""

    def __init__(self, stream: BinaryIO):
        self._stream, self.digest, self.size = stream, hashlib.sha256(), 0

    def read(self, count: int = -1) -> bytes:
        block = self._stream.read(count)
        self.digest.update(block)
        self.size += len(block)
        return block


def extract_archive(stream: BinaryIO, manifest: Manifest, staging: pathlib.Path,
                    progress: Optional[Progress] = None) -> None:
    """Writes the files of the archive read from ``stream`` under ``staging``, in one pass, so a download is never
    stored twice. Raises ``PackageError`` on any member that is not listed, not a regular file, repeated, of the
    wrong size or hash, on any listed file the archive lacks, and when the archive's own size or SHA-256 differs from
    ``manifest.archive``."""
    expected = {entry.path: entry for entry in manifest.files}
    seen: set[str] = set()
    reader = _HashingReader(stream)
    try:
        tar = tarfile.open(fileobj=reader, mode='r|', encoding=ENCODING)  # type: ignore[call-overload]
    except tarfile.TarError as error:
        raise PackageError(f'not a readable archive: {error}') from error
    try:
        with tar:
            for member in tar:
                _extract_member(tar, member, expected, seen, staging, progress)
    except tarfile.TarError as error:
        raise PackageError(f'archive is damaged: {error}') from error
    missing = sorted(set(expected) - seen)
    if missing:
        raise PackageError(f'archive lacks {len(missing)} file(s), first {missing[0]}')
    while reader.read(CHUNK):
        pass
    archive = manifest.archive
    if archive is not None and (reader.size != archive['size'] or reader.digest.hexdigest() != archive['sha256']):
        raise PackageError(f'the archive differs from {manifest.stem}: size {reader.size}, expected {archive["size"]}')


def _extract_member(tar: tarfile.TarFile, member: tarfile.TarInfo, expected: dict[str, FileEntry], seen: set[str],
                    staging: pathlib.Path, progress: Optional[Progress]) -> None:
    entry = expected.get(member.name)
    if entry is None:
        raise PackageError(f'archive member {member.name!r} is not in the manifest')
    if member.name in seen:
        raise PackageError(f'archive member {member.name} appears twice')
    if not member.isreg():
        raise PackageError(f'archive member {member.name} is not a regular file')
    if member.size != entry.size:
        raise PackageError(f'{member.name}: size {member.size}, manifest {entry.size}')
    seen.add(member.name)
    source = tar.extractfile(member)
    if source is None:
        raise PackageError(f'archive member {member.name} has no data')
    target = staging.joinpath(*member.name.split('/'))
    target.parent.mkdir(parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    with source, open(target, 'xb') as out:
        for block in iter(lambda: source.read(CHUNK), b''):
            digest.update(block)
            size += len(block)
            out.write(block)
            if progress:
                progress(len(block))
    if size != entry.size or digest.hexdigest() != entry.sha256:
        raise PackageError(f'{member.name} does not match its SHA-256 in the manifest')
