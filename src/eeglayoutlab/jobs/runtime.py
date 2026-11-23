"""The checkout root and the interpreter strings, as Node's ``runtime/config.mjs`` and ``host/config.mjs`` choose them.

Both strings enter request keys: the root through ``identity.python`` and library provenance, the
interpreter as ``identity.python`` itself. So they follow Node's spelling rules exactly (design 0001, phase 2):

- the default root is the real path of the checkout that holds this package, as Node's comes from
  ``import.meta.url``: Node resolves its main module with ``fs.realpathSync``, which resolves link targets
  lexically (``nodefs.realpath_sync``), not as ``os.path.realpath`` does;
- an explicit root (``--root`` or ``EEG_REPOSITORY_ROOT``) must be absolute and is only normalized, never
  resolved through symbolic links;
- the native workflows (design evaluation, electrode editor, reception v2) use the managed interpreter when
  the checkout has one, whatever ``python`` or ``EEG_COMPUTE_PYTHON`` say; the service's own
  ``sys.executable`` never enters an identity.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping, Optional

from ..schemas import jsjson
from . import nodefs, nodepath

__all__ = [
    'NATIVE_RUNTIME_RELATIVE', 'TABLE_RUNTIME_RELATIVE', 'RuntimeConfig', 'default_repository_root',
    'repository_root', 'native_python_path', 'table_python_path', 'managed_python', 'runtime_config',
]

NATIVE_RUNTIME_RELATIVE = '.runtime/simnibs-4.6.0'
# Linux runtime without SimNIBS (configs/runtime/manifest-linux-64.json): new coordinates come from published
# scalp-node tables; it cannot solve FEM.
TABLE_RUNTIME_RELATIVE = '.runtime/compute-linux-64'


def default_repository_root() -> Optional[str]:
    """The real path of the checkout that contains this package, or ``None`` outside a checkout."""
    checkout = Path(nodefs.realpath_sync(nodepath.resolve(__file__))).parents[3]
    if (checkout / 'pyproject.toml').is_file() and (checkout / 'src/compact_eeg').is_dir():
        return str(checkout)
    return None


def repository_root(explicit: Optional[str] = None, env: Mapping[str, str] = os.environ) -> str:
    """``hostConfig``'s root: ``explicit || EEG_REPOSITORY_ROOT`` (absolute), else the checkout of this package."""
    selected = explicit or env.get('EEG_REPOSITORY_ROOT') or ''
    if selected and not nodepath.is_absolute(selected):
        raise ValueError('EEG_REPOSITORY_ROOT must be absolute.')
    if not selected:
        selected = default_repository_root() or ''
        if not selected:
            raise ValueError('A repository root is required.')
    root = nodepath.resolve(selected)
    if not os.path.exists(root):
        raise ValueError('The scientific repository root does not exist.')
    return root


def native_python_path(root: str) -> str:
    """``nativePythonPath(root)``."""
    return nodepath.join(root, NATIVE_RUNTIME_RELATIVE, 'bin/python')


def table_python_path(root: str) -> str:
    """``tablePythonPath(root)``."""
    return nodepath.join(root, TABLE_RUNTIME_RELATIVE, 'bin/python')


def managed_python(root: str) -> Optional[str]:
    """The SimNIBS runtime's interpreter, else the Linux table runtime's, else ``None``.

    ``existsSync`` follows symbolic links, as ``os.path.exists`` does: a dangling link is absent.
    """
    native, table = native_python_path(root), table_python_path(root)
    if os.path.exists(native):
        return native
    if os.path.exists(table):
        return table
    return None


@dataclass(frozen=True)
class RuntimeConfig:
    """``runtimeConfig(...)`` without the queue directory, which the workspace replaces."""

    repository_root: str
    python: str
    """``computePython``: the radius worker's interpreter and the one its fingerprint describes."""
    native_python: str
    """The interpreter of the native workflows, and ``identity.python`` of design and editor keys."""


def runtime_config(repository_root: str, python: Optional[str] = None,
                   env: Mapping[str, str] = os.environ) -> RuntimeConfig:
    """``runtimeConfig({repositoryRoot, python, env})``: ``python || EEG_COMPUTE_PYTHON || managed || 'python3'``.

    The ``or`` chain follows JavaScript's ``||``: an empty string falls through, like an absent value.
    """
    if not isinstance(repository_root, str) or not jsjson.js_trim(repository_root):
        raise ValueError('A repository root is required.')
    root = nodepath.resolve(repository_root)
    managed = managed_python(root)
    compute = python or env.get('EEG_COMPUTE_PYTHON') or managed or 'python3'
    return RuntimeConfig(repository_root=root, python=compute,
                         native_python=managed if managed is not None else compute)
