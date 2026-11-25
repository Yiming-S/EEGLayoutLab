"""The workspace directory W of one service process (design 0001, decisions 6 and 7).

Layout::

    W/eeglayoutlab-workspace.json   {"schema":"eeglayoutlab-workspace/1","id":<uuid4>,"created_at":<ISO ms Z>}
    W/.eeglayoutlab/                mode 0700, ignored by git through its own .gitignore ("*")
        lock                        flock held for the life of the process
        runtime.json                mode 0600: {"schema":"eeglayoutlab-runtime/1","pid","port","token","root",
                                                "started_at"}
        open.html                   mode 0600: a page that redirects to the launch URL, which the launcher opens
                                    so that the token is not in a browser's command line

One process serves a workspace at a time. A second ``eeglayoutlab serve`` finds the lock held, reads
``runtime.json`` and opens the running instance instead (decision 6, instance reuse); while the holder is still
starting or stopping (it has no runtime file then), it waits and retries the lock. The runtime file is removed when
the process stops; one left behind by a process that died is replaced at the next start.

The state directory holds the launch token, so it is trusted only when it is a directory, not a link, of this user,
and no other user can read or write it: a looser mode is tightened to 0700 when the workspace is opened, and the
reader of ``runtime.json`` takes only a private regular file of this user. Files in it are opened relative to a
descriptor of the directory, never through a link, and written under new random names, then renamed. A file system
that keeps the mode open after chmod (FAT, exFAT, NTFS or SMB mounts) is refused before a token is written.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import html
import os
import re
import secrets
import stat
import sys
import threading
import time
from typing import Any, Optional
import uuid

from ..schemas import jsjson

__all__ = [
    'MARKER', 'STATE', 'WORKSPACE_SCHEMA', 'RUNTIME_SCHEMA', 'LOCAL_OWNER', 'WorkspaceError', 'WorkspaceInUse',
    'UserContext', 'Workspace', 'is_workspace', 'inside', 'NODE_QUEUE_DIRECTORY', 'read_runtime', 'open_url',
    'write_open_page', 'user_data_dir', 'iso_now',
]

MARKER = 'eeglayoutlab-workspace.json'
# The Node host's queue directory Q under the scientific root (its default), which the Python service never writes.
NODE_QUEUE_DIRECTORY = 'results/web-service'
STATE = '.eeglayoutlab'
RUNTIME = 'runtime.json'
OPEN_PAGE = 'open.html'
WORKSPACE_SCHEMA = 'eeglayoutlab-workspace/1'
RUNTIME_SCHEMA = 'eeglayoutlab-runtime/1'
# The single local user of decision 6. It is 64 hex digits because Node's study and visibility records require a
# visitor-shaped owner (storage.md section 8.2).
LOCAL_OWNER = hashlib.sha256(b'eeglayoutlab-local-user/1').hexdigest()
_TOKEN = re.compile(r'[0-9a-f]{64}')
# How long a second start waits for an instance that holds the lock without a runtime file: one that is starting,
# or stopping (up to uvicorn's 5 s graceful shutdown).
RUNTIME_WAIT_SECONDS = 10.0
# Opened without following a link; a FIFO put in place of a file does not block the open.
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_NO_LINK = os.O_NOFOLLOW | os.O_NONBLOCK


class WorkspaceError(Exception):
    """A workspace that cannot be used; the message is for the person running the command."""


class WorkspaceInUse(Exception):
    """Another process holds the workspace lock; ``runtime`` is its runtime file, or ``None`` when that is missing
    or invalid."""

    def __init__(self, path: str, runtime: Optional[dict[str, Any]]):
        super().__init__(path)
        self.path = path
        self.runtime = runtime


@dataclass(frozen=True)
class UserContext:
    """The user context every request carries (decision 6). In local mode there is one user."""

    owner: str
    """64 hex digits; the owner of new studies, annotations and queue receipts."""
    workspace: str
    """W: projects, studies, task history and name sets of this workspace."""
    records_root: str
    """The root of the shared record trees ``results/v2/*_jobs``: R until 1.0 (decision U1)."""
    data_dir: str
    """D, the user data directory (decision 7); not written in phase 2."""

    @classmethod
    def local(cls, workspace: str, root: str) -> 'UserContext':
        return cls(owner=LOCAL_OWNER, workspace=workspace, records_root=root, data_dir=user_data_dir())


def user_data_dir() -> str:
    """``~/Library/Application Support/EEGLayoutLab`` on macOS, ``$XDG_DATA_HOME/eeglayoutlab`` elsewhere."""
    home = os.path.expanduser('~')
    if sys.platform == 'darwin':
        return os.path.join(home, 'Library', 'Application Support', 'EEGLayoutLab')
    base = os.environ.get('XDG_DATA_HOME') or ''
    if not os.path.isabs(base):
        base = os.path.join(home, '.local', 'share')
    return os.path.join(base, 'eeglayoutlab')


def iso_now() -> str:
    """``new Date().toISOString()``: UTC with milliseconds and ``Z``."""
    now = datetime.now(timezone.utc)
    return now.strftime('%Y-%m-%dT%H:%M:%S.') + f'{now.microsecond // 1000:03d}Z'


def is_workspace(path: str) -> bool:
    return os.path.isfile(os.path.join(path, MARKER))


def inside(path: str, directory: str) -> bool:
    """Whether ``path`` (existing or not) is the existing ``directory`` or inside it, compared by the device and
    inode of ``path`` resolved through links and of each existing directory above it (so another spelling, on a
    case-insensitive file system, counts too)."""
    try:
        info = os.stat(directory)
    except OSError:
        return False
    current = os.path.realpath(path)
    while True:
        try:
            found = os.stat(current)
            if (found.st_dev, found.st_ino) == (info.st_dev, info.st_ino):
                return True
        except OSError:
            pass
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent


def _read_marker(path: str) -> dict[str, Any]:
    marker = os.path.join(path, MARKER)
    try:
        with open(marker, 'rb') as handle:
            value = jsjson.parse(jsjson.decode_body(handle.read()))
    except (OSError, ValueError) as error:
        raise WorkspaceError(f'{marker} is not a readable workspace marker: {error}') from error
    if not (isinstance(value, dict) and value.get('schema') == WORKSPACE_SCHEMA and isinstance(value.get('id'), str)
            and isinstance(value.get('created_at'), str)):
        raise WorkspaceError(f'{marker} is not an {WORKSPACE_SCHEMA} marker.')
    return value


def _create_exclusive(path: str, text: str, mode: int, dir_fd: Optional[int] = None) -> bool:
    """Writes ``text`` to a new file; ``False`` when the file (or a link) exists."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=dir_fd)
    except FileExistsError:
        return False
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def _require_private(fd: int, path: str) -> None:
    """Refuses ``path`` (open as ``fd``) when it is still open to other users after chmod: a FAT, exFAT, NTFS or SMB
    mount accepts chmod but keeps the mode the mount gives, and the launch token must not go there."""
    mode = stat.S_IMODE(os.fstat(fd).st_mode)
    if mode & 0o077:
        raise WorkspaceError(f'{path} cannot be made private on this file system (it keeps mode {mode:04o}); choose a '
                             'workspace on a local disk.')


def _write_private(state_fd: int, state: str, name: str, text: str) -> None:
    """Writes ``name`` in the state directory ``state`` atomically with mode 0600: a new file under a random name
    (never an existing file or a link someone put there), made private before ``text`` goes in, then renamed over
    ``name``."""
    temporary = f'{name}.{secrets.token_hex(8)}.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=state_fd)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            os.fchmod(fd, 0o600)
            _require_private(fd, os.path.join(state, name))
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, name, src_dir_fd=state_fd, dst_dir_fd=state_fd)
    except BaseException:
        try:
            os.unlink(temporary, dir_fd=state_fd)
        except OSError:
            pass
        raise


def _unlink(state_fd: int, name: str) -> bool:
    try:
        os.unlink(name, dir_fd=state_fd)
    except FileNotFoundError:
        return False
    return True


def _state_fd(path: str, create: bool = False) -> int:
    """A descriptor of ``W/.eeglayoutlab``: a directory, not a link, of this user. With ``create`` it is made when
    missing and its mode set to 0700 (refused when the file system keeps it open); without, a mode that lets
    another user in is refused. ``WorkspaceError`` when it cannot be trusted, ``OSError`` when it cannot be
    opened."""
    state = os.path.join(path, STATE)
    if create:
        try:
            os.mkdir(state, 0o700)
        except FileExistsError:
            pass
    try:
        fd = os.open(state, _DIRECTORY)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise WorkspaceError(f'{state} exists and is not a directory (a link is not accepted).') from None
        raise
    try:
        status = os.fstat(fd)
        if status.st_uid != os.geteuid():
            raise WorkspaceError(f'{state} belongs to another user. Remove it, or choose a workspace of your own.')
        mode = stat.S_IMODE(status.st_mode)
        if create and mode != 0o700:
            os.fchmod(fd, 0o700)
            _require_private(fd, state)
        elif not create and mode & 0o077:
            raise WorkspaceError(f'{state} is open to other users.')
    except BaseException:
        os.close(fd)
        raise
    return fd


def _private_file(status: os.stat_result) -> bool:
    """A regular file of this user, readable by no one else and with no other name."""
    return (stat.S_ISREG(status.st_mode) and status.st_uid == os.geteuid() and not stat.S_IMODE(status.st_mode) & 0o077
            and status.st_nlink == 1)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_runtime_at(state_fd: int) -> Optional[dict[str, Any]]:
    try:
        fd = os.open(RUNTIME, os.O_RDONLY | _NO_LINK, dir_fd=state_fd)
    except OSError:
        return None
    with os.fdopen(fd, 'rb') as handle:
        try:
            if not _private_file(os.fstat(fd)):
                return None
            value = jsjson.parse(jsjson.decode_body(handle.read()))
        except (OSError, ValueError):
            return None
    if not isinstance(value, dict) or value.get('schema') != RUNTIME_SCHEMA:
        return None
    pid, port, token = value.get('pid'), value.get('port'), value.get('token')
    # jsjson reads every number as a double.
    if not (jsjson.is_integer(pid) and 0 < pid < 2**31 and jsjson.is_integer(port) and 0 < port < 65536
            and isinstance(token, str) and _TOKEN.fullmatch(token)):
        return None
    value = {**value, 'pid': int(pid), 'port': int(port)}
    return value if _pid_alive(value['pid']) else None


def read_runtime(path: str) -> Optional[dict[str, Any]]:
    """The runtime file of the instance serving workspace ``path``, or ``None`` when it is missing, invalid, not a
    private file of this user in a private state directory, or names a process that has exited."""
    try:
        state_fd = _state_fd(path)
    except (OSError, WorkspaceError):
        return None
    try:
        return _read_runtime_at(state_fd)
    finally:
        os.close(state_fd)


def open_url(runtime: dict[str, Any]) -> str:
    return f'http://127.0.0.1:{runtime["port"]}/open?token={runtime["token"]}'


def _open_page(url: str) -> str:
    target = html.escape(url, quote=True)
    return ('<!doctype html><html><head><meta charset="utf-8">'
            f'<meta http-equiv="refresh" content="0;url={target}"><title>EEG Layout Lab</title></head>'
            f'<body><p><a href="{target}">EEG Layout Lab</a></p></body></html>\n')


def write_open_page(path: str, url: str) -> str:
    """Writes ``W/.eeglayoutlab/open.html``, a private page that redirects to ``url``, and returns its path.

    A browser started with the launch URL on its command line shows the token to every local user (``ps``,
    ``/proc/<pid>/cmdline``); started with this page, it shows only the file name (Jupyter's redirect file)."""
    state_fd = _state_fd(path)
    try:
        _write_private(state_fd, os.path.join(path, STATE), OPEN_PAGE, _open_page(url))
    finally:
        os.close(state_fd)
    return os.path.join(path, STATE, OPEN_PAGE)


class Workspace:
    """An open workspace: the marker exists and this process holds the lock until ``close``."""

    def __init__(self, path: str, marker: dict[str, Any], lock_fd: int, state_fd: int):
        self.path = path
        self.marker = marker
        self._lock_fd: Optional[int] = lock_fd
        self._state_fd = state_fd
        self._runtime: Optional[dict[str, Any]] = None
        # The browser thread writes the open page while the signal handler (on the main thread, which may hold it
        # already) or close removes the runtime file.
        self._guard = threading.RLock()

    @property
    def state(self) -> str:
        return os.path.join(self.path, STATE)

    @property
    def runtime_path(self) -> str:
        return os.path.join(self.state, RUNTIME)

    @classmethod
    def open(cls, path: str, wait: float = RUNTIME_WAIT_SECONDS) -> 'Workspace':
        """Opens ``path`` (an absolute directory, created when missing) as a workspace and takes its lock.

        Raises ``WorkspaceInUse`` when another process holds the lock: at once with its runtime file, or after
        ``wait`` seconds of retrying the lock without one. ``WorkspaceError`` when the directory cannot be used.
        """
        if os.path.lexists(path) and not os.path.isdir(path):
            raise WorkspaceError(f'{path} is not a directory.')
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as error:
            raise WorkspaceError(f'Cannot create the workspace directory {path}: {error.strerror}.') from error
        state = os.path.join(path, STATE)
        try:
            state_fd = _state_fd(path, create=True)
        except OSError as error:
            raise WorkspaceError(f'Cannot write the service state in {state}: {error.strerror}.') from error
        try:
            fd = cls._lock(path, state_fd, wait)
            try:
                marker = cls._marker(path)
                # The lock is ours, so these are left over from a process that died.
                _unlink(state_fd, RUNTIME)
                _unlink(state_fd, OPEN_PAGE)
            except BaseException:
                os.close(fd)
                raise
        except BaseException:
            os.close(state_fd)
            raise
        return cls(path, marker, fd, state_fd)

    @staticmethod
    def _lock(path: str, state_fd: int, wait: float) -> int:
        state = os.path.join(path, STATE)
        try:
            _create_exclusive('.gitignore', '*\n', 0o644, dir_fd=state_fd)
            fd = os.open('lock', os.O_RDWR | os.O_CREAT | _NO_LINK, 0o600, dir_fd=state_fd)
        except OSError as error:
            raise WorkspaceError(f'Cannot write the service state in {state}: {error.strerror}.') from error
        try:
            status = os.fstat(fd)
            if not stat.S_ISREG(status.st_mode) or status.st_uid != os.geteuid():
                raise WorkspaceError(f'{os.path.join(state, "lock")} is not a file of yours; remove it.')
            deadline = time.monotonic() + wait
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return fd
                except OSError as error:
                    if error.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                        raise WorkspaceError(
                            f'Cannot lock the workspace {path} ({error.strerror}). Network and synchronized folders '
                            'may not support file locks; choose a workspace on a local disk.') from error
                # The holder is running (it has written its runtime file), or starting or stopping: the lock is
                # tried again, so a process that stops or fails to start does not keep this one out.
                runtime = _read_runtime_at(state_fd)
                if runtime is not None:
                    raise WorkspaceInUse(path, runtime)
                if time.monotonic() >= deadline:
                    raise WorkspaceInUse(path, None)
                time.sleep(0.1)
        except BaseException:
            os.close(fd)
            raise

    @staticmethod
    def _marker(path: str) -> dict[str, Any]:
        if not os.path.lexists(os.path.join(path, MARKER)):
            marker = {'schema': WORKSPACE_SCHEMA, 'id': str(uuid.uuid4()), 'created_at': iso_now()}
            try:
                _create_exclusive(os.path.join(path, MARKER), jsjson.stringify(marker) + '\n', 0o644)
            except OSError as error:
                raise WorkspaceError(f'Cannot write {os.path.join(path, MARKER)}: {error.strerror}.') from error
        return _read_marker(path)

    def user_context(self, root: str) -> UserContext:
        return UserContext.local(self.path, root)

    def write_runtime(self, port: int, token: str, root: str) -> dict[str, Any]:
        """Writes ``runtime.json`` atomically with mode 0600."""
        runtime = {'schema': RUNTIME_SCHEMA, 'pid': os.getpid(), 'port': port, 'token': token, 'root': root,
                   'started_at': iso_now()}
        with self._guard:
            _write_private(self._state_fd, self.state, RUNTIME, jsjson.stringify(runtime) + '\n')
            self._runtime = runtime
        return runtime

    def write_open_page(self, url: str) -> Optional[str]:
        """``write_open_page`` for this workspace while its runtime file is there; the page is removed with it.
        ``None`` once the runtime file is removed (the service is stopping), so that no page outlives it."""
        with self._guard:
            if self._runtime is None:
                return None
            _write_private(self._state_fd, self.state, OPEN_PAGE, _open_page(url))
        return os.path.join(self.state, OPEN_PAGE)

    def remove_runtime(self) -> bool:
        """Removes ``runtime.json`` (and the open page) if it is still the one this process wrote."""
        with self._guard:
            mine = self._runtime
            if mine is None:
                return False
            current = _read_runtime_at(self._state_fd)
            if current is None or current.get('pid') != mine['pid'] or current.get('token') != mine['token']:
                return False
            if not _unlink(self._state_fd, RUNTIME):
                return False
            _unlink(self._state_fd, OPEN_PAGE)
            self._runtime = None
            return True

    def close(self) -> None:
        """Removes the runtime file (if ours) and releases the lock; no open page is written after this."""
        with self._guard:
            if self._lock_fd is None:
                return
            try:
                self.remove_runtime()
            finally:
                self._runtime = None
                os.close(self._lock_fd)
                os.close(self._state_fd)
                self._lock_fd = None
                self._state_fd = -1
