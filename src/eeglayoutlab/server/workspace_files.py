"""Hardened file access for the workspace's private records: the I/O half of Node's ``ProjectStore``
(``webapp/server/projects/store.mjs:96-128, 143-151``), shared by robustness studies (slice 8,
``server.workspace_studies``) and workspace projects (slice 9).

A store keeps one directory per record, named by a UUID v4, under its own directory in the workspace
(``W/studies``, ``W/projects``). Every access fails closed, with Node's statuses and messages:

- ``safe_directory(path)``: ``lstat`` finds a directory, not a link, and ``realpath(3)`` of the path is the path
  itself (no link anywhere above it either); else 409 ``Project directory is not a regular directory.``.
- ``record_directory(id)`` (Node's ``projectDirectory``): ``id`` is a lowercase UUID v4 (else 400 ``Invalid project
  identifier.``), and the store's directory and the record's are both safe.
- ``file(path, maximum)``: ``lstat`` finds a regular file with one link (``nlink == 1``; a caller may accept more
  that it has counted) and at most ``maximum`` bytes (else 409 ``Project file failed integrity checks.``); it is
  opened ``O_RDONLY | O_NOFOLLOW``, and ``fstat`` must still name the same device and inode within the bound (409
  ``Project file changed while reading.``); a file that grew past the bound while it was read is 413 ``Project file
  is too large.``.
- ``ready()`` (Node's memoized ``initialize``): the parent is created (0700, with its own parents) and resolved with
  ``realpath(3)``, the store's directory is created (0700) unless it exists, and checked. The outcome is kept: a
  failure is raised again by every later call, as Node's rejected promise is.
- ``serialize(operation)``: Node's promise chain. Operations run one after another in call order, each once the one
  before it has settled; a closed store refuses new ones (503 ``Project store is stopping.``); ``flush()`` waits for
  the last one, ``pending_writes`` counts those not yet settled.

Writes are ``records.atomic_json`` and ``records.atomic_bytes`` (Node's ``atomicJson`` and ``atomicBytes``: a new
``<path>.<uuid4>.tmp`` opened ``wx`` with mode 0600, fsync, rename, fsync of the directory). File-system failures are
``nodefs`` system errors with Node's code, syscall and path (``records.error_code(error) == 'ENOENT'``), so callers
tell a missing file from a refused one as Node's do. The checks and reads are blocking; the stores run them in
worker threads, one serialized operation at a time.
"""
from __future__ import annotations

import asyncio
import os
import re
import stat
import threading
from typing import Any, Awaitable, Callable, Optional, TypeVar

from ..jobs import nodefs, nodepath

__all__ = ['UUID', 'SHA', 'ProjectError', 'project_error', 'valid_project_id', 'basename', 'mkdir', 'lstat',
           'WorkspaceFiles']

T = TypeVar('T')

UUID = re.compile('[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}')
SHA = re.compile('[a-f0-9]{64}')

# Node's messages (projects/store.mjs), verbatim.
UNSAFE_DIRECTORY = 'Project directory is not a regular directory.'
INVALID_ID = 'Invalid project identifier.'
FILE_INTEGRITY = 'Project file failed integrity checks.'
FILE_CHANGED = 'Project file changed while reading.'
FILE_TOO_LARGE = 'Project file is too large.'
STOPPING = 'Project store is stopping.'

_CHUNK = 1 << 20


class ProjectError(ValueError):
    """``projectError(message, status)``: a refusal shown with its status and message (``projectSafe``)."""

    project_safe = True

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def project_error(message: str, status: int = 400) -> ProjectError:
    return ProjectError(message, status)


def valid_project_id(value: Any) -> bool:
    """``validProjectId(value)``: a string that is a lowercase UUID v4."""
    return isinstance(value, str) and UUID.fullmatch(value) is not None


def basename(path: str) -> str:
    """``path.posix.basename`` of a resolved path (no trailing slash): the text after the last ``/``."""
    return path[path.rfind('/') + 1:]


def lstat(path: str) -> os.stat_result:
    """``await lstat(path)``, with Node's system error."""
    return nodefs.lstat(path)


def mkdir(path: str, mode: int = 0o777) -> None:
    """``await mkdir(path, {mode})``: one directory, ``mode`` less the umask; Node's system error (``EEXIST`` ...)."""
    try:
        os.mkdir(nodefs.encode(path), mode)
    except OSError as error:
        raise nodefs.system_error(error, 'mkdir', path) from None


def _mkdir_recursive(path: str, mode: int) -> None:
    """``await mkdir(path, {recursive: true, mode})``: the missing parents too; an existing directory is fine."""
    try:
        os.makedirs(nodefs.encode(path), mode, exist_ok=True)
    except OSError as error:
        raise nodefs.system_error(error, 'mkdir', path) from None


class WorkspaceFiles:
    """The hardened I/O of one store directory (``directory`` is resolved, never through links, as Node's
    ``path.resolve``); ``directory`` is reassigned to its real parent's spelling by ``ready`` and by the stores, as
    Node's is."""

    def __init__(self, directory: str):
        self.directory = nodepath.resolve(directory)
        self.pending_writes = 0
        self.closed = False
        self._tail: Optional[asyncio.Future] = None
        self._initialized: Optional[tuple[bool, Optional[BaseException]]] = None
        self._initializing = threading.Lock()

    # --- Initialization --------------------------------------------------------------------------------------------

    def _initialize(self) -> None:
        parent = nodepath.dirname(self.directory)
        _mkdir_recursive(parent, 0o700)
        self.directory = nodepath.join(nodefs.realpath(parent), basename(self.directory))
        try:
            mkdir(self.directory, 0o700)
        except OSError as error:
            if getattr(error, 'code', None) != 'EEXIST':
                raise
        self.safe_directory(self.directory)

    def ready(self) -> None:
        """``ready()``: ``initialize()`` once; its failure is raised again by every later call."""
        with self._initializing:
            if self._initialized is None:
                try:
                    self._initialize()
                    self._initialized = (True, None)
                except Exception as error:  # noqa: BLE001 - kept, as Node keeps the rejected promise
                    self._initialized = (False, error)
        ok, error = self._initialized
        if not ok:
            assert error is not None
            raise error

    # --- Checks and reads ------------------------------------------------------------------------------------------

    def safe_directory(self, path: str) -> None:
        """``safeDirectory(path)``: a directory, not a link, whose real path is itself; ``lstat`` and ``realpath``
        failures are raised as Node's system errors (``ENOENT`` ...)."""
        info = nodefs.lstat(path)
        if not stat.S_ISDIR(info.st_mode) or nodefs.realpath(path) != path:
            raise ProjectError(UNSAFE_DIRECTORY, 409)

    def record_directory(self, id: Any) -> str:
        """``projectDirectory(id)``: the record's safe directory."""
        if not valid_project_id(id):
            raise ProjectError(INVALID_ID)
        self.safe_directory(self.directory)
        path = nodepath.join(self.directory, id)
        self.safe_directory(path)
        return path

    def file(self, path: str, maximum: int, links: int = 1) -> bytes:
        """``file(path, maximum)``: the bytes of a regular file with one link, read through ``O_NOFOLLOW`` and
        checked again on the open descriptor. ``links`` raises the bound for a caller that has counted links it
        accepts (never below one)."""
        info = nodefs.lstat(path)
        if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_nlink <= links or info.st_size > maximum:
            raise ProjectError(FILE_INTEGRITY, 409)
        try:
            fd = os.open(nodefs.encode(path), os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
        except OSError as error:
            raise nodefs.system_error(error, 'open', path) from None
        try:
            actual = os.fstat(fd)
            if actual.st_ino != info.st_ino or actual.st_dev != info.st_dev or actual.st_size > maximum:
                raise ProjectError(FILE_CHANGED, 409)
            chunks = []
            while True:
                try:
                    chunk = os.read(fd, _CHUNK)
                except OSError as error:
                    raise nodefs.system_error(error, 'read', None) from None
                if not chunk:
                    break
                chunks.append(chunk)
            data = b''.join(chunks)
            if len(data) > maximum:
                raise ProjectError(FILE_TOO_LARGE, 413)
            return data
        finally:
            os.close(fd)

    # --- Serialized writes -----------------------------------------------------------------------------------------

    async def serialize(self, operation: Callable[[], Awaitable[T]]) -> T:
        """``serialize(operation)``: runs ``operation()`` once every earlier one has settled and returns its value
        (or raises its error). The operation runs to its end even when the caller is cancelled."""
        if self.closed:
            raise ProjectError(STOPPING, 503)
        self.pending_writes += 1
        previous = self._tail

        async def run() -> T:
            if previous is not None:
                await asyncio.wait([previous])
            return await operation()

        task = asyncio.ensure_future(run())
        task.add_done_callback(self._settled)
        self._tail = task
        return await asyncio.shield(task)

    def _settled(self, task: asyncio.Future) -> None:
        self.pending_writes -= 1
        if not task.cancelled():
            task.exception()  # retrieved: the caller that awaited it has it, or it was cancelled meanwhile

    def close(self) -> None:
        self.closed = True

    async def flush(self) -> None:
        """``flush()``: until the last operation started so far has settled."""
        tail = self._tail
        if tail is not None:
            await asyncio.wait([tail])
