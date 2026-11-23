"""Interpreter identity for cache keys: Node's ``runtime/python-fingerprint.mjs``.

Keys made on macOS before the fingerprint existed keep their format, so it is added only on other platforms:
a result computed on the Mac is never reused on the Linux server, and a numpy or SciPy upgrade there yields new
keys. The value is memoized per interpreter string for the life of the process, as in Node, so an upgrade in
place is seen only after a restart.
"""
from __future__ import annotations

import errno
import os
import selectors
import subprocess
import sys
import time
from typing import Any, Callable, Optional

from ..schemas import jsjson

__all__ = ['PROBE', 'python_fingerprint', 'runtime_identity']

PROBE = '\n'.join([
    'import json, platform, sys',
    'versions = {}',
    'for name in ("numpy", "scipy"):',
    '    try:',
    '        versions[name] = __import__(name).__version__',
    '    except Exception:',
    '        versions[name] = None',
    'print(json.dumps({"python": sys.version.split()[0], "system": platform.system(), "machine": platform.machine(), **versions}, sort_keys=True))',
])

# execFileSync's defaults: output beyond maxBuffer (1 MiB) fails the call.
_TIMEOUT_SECONDS = 30
_MAX_BUFFER = 1024 * 1024
_READ_SIZE = 65536


# glibc's execvp goes on to the next PATH entry after these errors (and remembers EACCES); any other error ends it.
_EXECVP_SKIP = frozenset({errno.EACCES, errno.ENOENT, errno.ESTALE, errno.ENOTDIR, errno.ENODEV, errno.ETIMEDOUT})


def _exec_file(candidate: str, argv: list[str], options: dict) -> subprocess.Popen:
    """One ``execve`` of glibc's ``execvp``: a file without a ``#!`` line or binary header (``ENOEXEC``) is run
    again with ``/bin/sh``."""
    try:
        return subprocess.Popen(argv, executable=candidate, **options)
    except OSError as error:
        if error.errno != errno.ENOEXEC:
            raise
    return subprocess.Popen(['/bin/sh', candidate, *argv[1:]], **options)


def _spawn(argv: list[str], platform: str) -> subprocess.Popen:
    """libuv's spawn of ``argv``.

    On macOS libuv uses ``posix_spawn``, and Python's own search is kept. Elsewhere it calls ``execvp``, which
    Python's ``subprocess`` does not reproduce: it tries every PATH entry and reports the first error that is not
    ``ENOENT``, and it never runs a file without a ``#!`` line. glibc's ``execvp`` takes the first entry it can
    execute, skipping ``EACCES`` (a directory, a file without the x bit), and runs a file without a ``#!`` line
    with ``/bin/sh``. So off macOS the search is glibc's: PATH (``/bin:/usr/bin`` when unset), an empty entry
    being the working directory.
    """
    options = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.PIPE, 'stderr': subprocess.DEVNULL}
    if platform == 'darwin':
        return subprocess.Popen(argv, **options)
    name = argv[0]
    if '/' in name:
        return _exec_file(name, argv, options)
    if not name:
        raise OSError(errno.ENOENT, os.strerror(errno.ENOENT), name)
    denied = False
    for directory in os.environ.get('PATH', os.defpath).split(':'):
        candidate = f'{directory}/{name}' if directory else f'./{name}'
        try:
            return _exec_file(candidate, argv, options)
        except OSError as error:
            if error.errno not in _EXECVP_SKIP:
                raise
            denied = denied or error.errno == errno.EACCES
    number = errno.EACCES if denied else errno.ENOENT
    raise OSError(number, os.strerror(number), name)


def _run(python: str, args: list[str], platform: str = sys.platform) -> str:
    """``execFileSync(python, args, {encoding: 'utf8', timeout: 30000, stdio: ['ignore', 'pipe', 'ignore']})``.

    Fails, as Node's call throws, on a non-zero exit or a signal, after 30 s, and as soon as stdout passes 1 MiB:
    the child is killed then, so an interpreter that floods its output is never buffered in full.
    """
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    with _spawn([python, *args], platform) as process:
        try:
            chunks: list[bytes] = []
            size = 0
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(python, _TIMEOUT_SECONDS)
                    if not selector.select(remaining):
                        continue
                    chunk = os.read(process.stdout.fileno(), _READ_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > _MAX_BUFFER:
                        raise OSError(errno.ENOBUFS, 'stdout maxBuffer length exceeded')
                    chunks.append(chunk)
            returncode = process.wait(timeout=max(deadline - time.monotonic(), 0))
        except BaseException:
            process.kill()
            raise
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, python)
    return b''.join(chunks).decode('utf-8', errors='replace')


_memo: dict[str, Any] = {}


def python_fingerprint(python: str, run: Optional[Callable[[str, list[str]], str]] = None) -> Any:
    """``JSON.parse`` of the probe's last output line (keys machine, numpy, python, scipy, system), or
    ``{'python': None}`` when the interpreter cannot be run or prints anything else."""
    if python not in _memo:
        try:
            output = (run or _run)(python, ['-I', '-c', PROBE])
            value = jsjson.parse(jsjson.js_trim(str(output)).split('\n')[-1])
        except Exception:
            value = {'python': None}
        _memo[python] = value
    return _memo[python]


def runtime_identity(python: str, platform: str = sys.platform) -> Any:
    """The ``runtime`` member of a cache identity, or ``None`` on macOS, where legacy keys must stay unchanged."""
    return None if platform == 'darwin' else python_fingerprint(python)
