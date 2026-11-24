"""The computation permit: Node's ``jobs/execution-slot.mjs``, and a lock for the installation.

``ExecutionSlot`` is one permit per workspace (design 0001, decision 6). A run path takes it after its cache lookup
(a hit never takes it), hands it to the job and releases it only when the worker's process group has exited, the
result is validated and the durable records are written. ``acquire(owner)`` returns the release function, or
``None`` while the permit is held or the slot is paused (the service's cache-only mode); a release takes effect once,
and one that has gone stale (the permit has passed to another owner) does nothing. Releasing still works while
paused. Lookups take no permit and no lock.

Node had one slot per checkout. Two workspaces of one installation share its record trees, so a slot built with an
``InstallationLock`` also holds ``flock(2)`` on ``R/results/v2/.eeglayoutlab-execution.lock`` with its permit: two
workspaces then compute one at a time, and two never publish the same ``cache.json`` at once. The lock is taken
without waiting (``LOCK_NB``), so the event loop never blocks on it: when another process holds it, ``acquire``
returns ``None`` and ``contended`` is set, and the caller tries again later (no release here tells it when).
``available()`` asks the same question without taking anything (the lock is tried and dropped at once), so the
queue can leave a task queued, and write nothing, while another workspace computes, as Node's tick reads
``executionSlot.busy`` before it writes a spawn intent. The kernel drops the lock when its holder exits, however it
exits. The file lives beside the record trees, never inside a ``*_jobs`` directory, whose listing must not see it;
the descriptor is not inherited by workers. It is opened for writing (read-only only when this user may not write
it): Linux NFS emulates ``flock`` with byte-range locks, and an exclusive one needs a descriptor open for writing.
A directory between the root and the file that resolves out of the root is refused with ``createBatch``'s
``RecordError`` (``Record directory leaves the repository.``), the message Node's run path gives on that root. The
root and each directory are resolved with ``realpath(3)`` (``records.realpath``), as ``createBatch`` resolves them:
on macOS it returns the on-disk case and Unicode normalization, so a link that spells the root another way still
resolves inside it, and a dangling link raises ``ENOENT``.
"""
from __future__ import annotations

import errno
import fcntl
import os
import stat
from typing import Any, Callable, Optional

from . import nodepath
from .records import RecordError, realpath

__all__ = ['LOCK_DIRECTORY', 'LOCK_NAME', 'LockError', 'execution_lock_path', 'InstallationLock', 'ExecutionSlot']

LOCK_DIRECTORY = 'results/v2'
LOCK_NAME = '.eeglayoutlab-execution.lock'
_FLAGS = os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, 'O_CLOEXEC', 0)
# flock(2): on NFS an exclusive lock needs a file open for writing; read-only is the fallback for a lock file this
# user may not write (another user's 0644 file) or a read-only file system.
_OPEN = os.O_RDWR | _FLAGS
_OPEN_READ_ONLY = os.O_RDONLY | _FLAGS
_ATTEMPTS = 3


class LockError(OSError):
    """The execution lock cannot be used: a link or not a regular file."""


def execution_lock_path(root: str) -> str:
    """``R/results/v2/.eeglayoutlab-execution.lock``."""
    return nodepath.join(nodepath.resolve(root), LOCK_DIRECTORY, LOCK_NAME)


class InstallationLock:
    """``flock(2)`` on the installation's execution lock, taken without waiting.

    ``root`` is the scientific root; ``path`` defaults to ``execution_lock_path(root)``. Missing directories between
    the root and the file are created one at a time, each resolved (``realpath(3)``) inside the real root before
    the next, as ``RecordStore.create_batch`` creates a batch. Two locks of one file conflict also within one process.
    """

    def __init__(self, root: str, path: Optional[str] = None):
        self.root = nodepath.resolve(root)
        self.path = nodepath.resolve(path) if path is not None else execution_lock_path(self.root)
        self._fd: Optional[int] = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def _parent(self) -> None:
        parent = nodepath.dirname(self.path)
        relative = nodepath.relative(self.root, parent)
        if not relative or relative == '..' or relative.startswith('../'):
            return  # outside the root (a path given for tests): the directory must exist
        root = realpath(self.root)
        cursor = self.root
        for part in relative.split('/'):
            cursor = nodepath.join(cursor, part)
            try:
                os.mkdir(cursor)
            except FileExistsError:
                pass
            if not realpath(cursor).startswith(root + '/'):
                raise RecordError('Record directory leaves the repository.')

    def _open(self) -> int:
        self._parent()
        try:
            fd = os.open(self.path, _OPEN, 0o644)
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EROFS):
                raise
            fd = os.open(self.path, _OPEN_READ_ONLY, 0o644)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise LockError(errno.EINVAL, 'The execution lock is not a regular file', self.path)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def try_acquire(self) -> bool:
        """``True`` when this object now holds the lock; ``False`` when another holder has it. Other failures
        (a file system without locks, a link in place of the file) raise ``OSError``, and a directory out of the
        root ``RecordError``; the descriptor is closed then, so no lock is left that nothing refers to."""
        if self._fd is not None:
            raise RuntimeError('The execution lock is already held by this object.')
        for _ in range(_ATTEMPTS):
            fd = self._open()
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # The file locked must still be the one the path names (it may have been removed and created again).
                try:
                    same = os.path.samestat(os.stat(self.path, follow_symlinks=False), os.fstat(fd))
                except FileNotFoundError:
                    same = False
            except BlockingIOError:  # EWOULDBLOCK: another holder
                os.close(fd)
                return False
            except BaseException:
                os.close(fd)
                raise
            if same:
                self._fd = fd
                return True
            os.close(fd)
        return False

    def release(self) -> None:
        """Drops the lock (no-op when not held)."""
        fd, self._fd = self._fd, None
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


class ExecutionSlot:
    """``new ExecutionSlot()``: one process permit; held through result verification and storage."""

    def __init__(self, lock: Optional[InstallationLock] = None):
        self._owner: Optional[list] = None
        self._paused = False
        self.lock = lock
        self.contended = False
        """The last ``acquire`` was refused because another process holds the installation lock."""

    @property
    def busy(self) -> bool:
        return self._owner is not None

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def available(self) -> bool:
        """Whether ``acquire`` would succeed now, taking nothing: ``False`` while the permit is held, the slot is
        paused or (``contended``) another process holds the installation lock, which is tried and dropped at once.
        Raises what ``InstallationLock.try_acquire`` raises."""
        if self.busy or self.paused:
            return False
        if self.lock is not None:
            if not self.lock.try_acquire():
                self.contended = True
                return False
            self.lock.release()
        self.contended = False
        return True

    def acquire(self, owner: Any) -> Optional[Callable[[], None]]:
        """The release function, or ``None`` when busy, paused or (``contended``) locked by another process."""
        if owner is None:
            raise TypeError('Execution permit requires an owner.')
        if self.busy or self.paused:
            return None
        if self.lock is not None:
            if not self.lock.try_acquire():
                self.contended = True
                return None
        self.contended = False
        token = [owner]
        self._owner = token

        def release() -> None:
            if self._owner is token:
                self._owner = None
                if self.lock is not None:
                    self.lock.release()
        return release
