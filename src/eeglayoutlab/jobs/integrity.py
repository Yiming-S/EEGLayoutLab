"""File digests for scientific identities: Node's ``InputIntegrity`` (``webapp/server/local-input-integrity.mjs``)."""
from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Iterable

from ..schemas import jsjson
from . import nodefs, nodepath
from .identity import UNDEFINED, IdentityError, JSTypeError, _js_string, _member, _path, _same, js_truthy

__all__ = ['InputIntegrity', 'BANK_POINTER', 'ADMISSION_POINTER']

_CHUNK = 1 << 20
BANK_POINTER = 'results/v2/current_multiregion_bank.json'
ADMISSION_POINTER = 'results/v2/current_surface_admissibility.json'
_SHA256 = re.compile('[a-f0-9]{64}')


def _stamp(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


class InputIntegrity:
    """SHA-256 of files inside the checkout, read stably and memoized by real path and stat stamp.

    Node resolves the root and the inputs with different functions (``nodefs``): the root with
    ``fs.realpathSync`` (link targets lexically, its spelling kept) and each input with ``fs.promises.realpath``
    (``realpath(3)``: physically, and on macOS in the on-disk letter case and Unicode normalization). An input
    is digested only when that real path starts with ``root + '/'``, so on macOS a root spelled in another case
    or normalization than on disk refuses every input, and a link whose target spells the root differently is
    still inside it. A missing file raises ``FileNotFoundError``, as Node rejects with ``ENOENT``. The memo never
    enters a key.
    """

    def __init__(self, root: str):
        self.root = nodefs.realpath_sync(nodepath.resolve(root))
        self._memo: dict[str, tuple[tuple[int, int, int, int, int], str]] = {}

    def _real_path(self, relative_path: str) -> str:
        path = nodefs.realpath(nodepath.resolve(self.root, relative_path))
        if not path.startswith(self.root + '/'):
            raise IdentityError('输入文件超出本项目')
        return path

    def _known(self, path: str, stamp: tuple[int, int, int, int, int]):
        """The memoized digest when the file still has the stamp it was hashed with."""
        known = self._memo.get(path)
        return known[1] if known is not None and known[0] == stamp else None

    def _read(self, path: str, stamp: tuple[int, int, int, int, int]) -> str:
        """``createReadStream(path)`` read to the end, then the stamp again: a directory fails here (``EISDIR``)."""
        sha = hashlib.sha256()
        with open(nodefs.encode(path), 'rb') as stream:
            while chunk := stream.read(_CHUNK):
                sha.update(chunk)
        if _stamp(nodefs.stat(path)) != stamp:
            raise IdentityError('输入文件正在变化')
        digest = sha.hexdigest()
        self._memo[path] = (stamp, digest)
        return digest

    def digest(self, relative_path: str) -> str:
        """``await inputs.digest(relativePath)``."""
        return self.digest_all([relative_path])[relative_path]

    def digest_all(self, files: Iterable[Any]) -> dict[str, str]:
        """``Object.fromEntries(await Promise.all(files.map(async (p) => [p, await inputs.digest(p)])))``.

        A repeated path keeps its first position. Node starts every digest at once, so the error ``Promise.all``
        reports is the first to settle, not the first in the list. Errors thrown before any I/O settle first,
        in microtask order: a path that is not a string (``path.resolve``'s ``ERR_INVALID_ARG_TYPE``) before a
        path with a NUL byte (``realpath``'s argument check, one ``await`` deeper). Each digest then waits for
        ``realpath``, ``stat``, the stream's ``open`` and its reads in turn. With one thread-pool worker libuv runs
        the queued requests strictly in order, so the inputs move through these stages together, in list order:
        every real path (``ENOENT``, ``ELOOP``, outside the project) is resolved before any input is opened
        (``EACCES``; a directory opens), and every input is opened before any is read (``EISDIR``). This method
        reproduces that order. With the default pool of 4 it is only the usual one: an input can reach a later
        stage before another finishes an earlier one, so Node may report either of two failures in different
        stages, as it may for two in the same stage.
        """
        files = list(files)
        resolved = [nodepath.resolve(self.root, path) for path in files]
        for path in resolved:
            nodefs.check_path(path)
        real = [self._real_path(path) for path in files]
        stamps = [_stamp(nodefs.stat(path)) for path in real]
        known = [self._known(path, stamp) for path, stamp in zip(real, stamps)]
        for path, digest in zip(real, known):
            if digest is None:
                nodefs.open_check(path)
        digests: dict[str, str] = {}
        for path, real_path, stamp, digest in zip(files, real, stamps, known):
            digests[path] = digest if digest is not None else self._read(real_path, stamp)
        return digests

    def _read_json(self, relative_path: str) -> Any:
        """``JSON.parse(await readFile(join(this.root, relativePath), 'utf8'))``: no containment, links followed."""
        return jsjson.parse(nodefs.decode(nodefs.read_file(nodepath.join(self.root, relative_path))))

    def verify(self, provenance: Any) -> None:
        """``await inputs.verify(provenance)`` (local-input-integrity.mjs:20-35): a radius result's forward inputs
        (the bank pointer, bank, candidates, report and, for ``strict-radius-local/3`` results, the surface mask)
        still have the digests the result recorded. Raises ``IdentityError`` with Node's message; the checks and
        digests run one after another in Node's order, so the first failure is Node's."""
        pointer = self._read_json(BANK_POINTER)
        if (not js_truthy(provenance)
                or not _same(_member(provenance, 'bank_path'), _member(pointer, 'path'))
                or not _same(_member(provenance, 'geometry_path'), _member(pointer, 'candidates'))
                or not _same(_member(provenance, 'bank_sha256'), _member(pointer, 'sha256'))):
            raise IdentityError('缓存前向模型身份不一致')
        entries = [
            (BANK_POINTER, _member(provenance, 'pointer_sha256')),
            (_member(pointer, 'path'), _member(provenance, 'bank_sha256')),
            (_member(pointer, 'candidates'), _member(provenance, 'geometry_sha256')),
            (_member(pointer, 'report'), _member(provenance, 'bank_report_sha256')),
        ]
        version = _member(provenance, 'algorithm_version')
        if version is not None and version is not UNDEFINED and not isinstance(version, str):
            raise JSTypeError('provenance.algorithm_version?.startsWith is not a function')
        if isinstance(version, str) and version.startswith('strict-radius-local/3'):
            admission = self._read_json(ADMISSION_POINTER)
            if (not _same(_member(admission, 'path'), _member(provenance, 'surface_admissibility_path'))
                    or not _same(_member(admission, 'sha256'), _member(provenance, 'surface_admissibility_sha256'))
                    or not _same(_member(admission, 'schema_version'),
                                 _member(provenance, 'surface_admissibility_version'))):
                raise IdentityError('外部表面筛选版本已改变，请重新计算')
            entries.append((_member(admission, 'path'), _member(admission, 'sha256')))
        for path, expected in entries:
            # RegExp.prototype.test converts its argument to a string; the comparison with the digest is strict.
            if not _SHA256.fullmatch(_js_string(expected)) or not _same(self.digest(_path(path)), expected):
                raise IdentityError('本地前向数据发生变化，不能使用旧缓存；请核对模型文件')
