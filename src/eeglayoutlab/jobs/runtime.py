"""The scientific root and the interpreter strings, as Node's ``runtime/config.mjs`` and ``host/config.mjs`` choose
them in a checkout, and as design 0002 chooses them in the installed form.

Both strings enter request keys: the root through ``identity.python`` and library provenance, the
interpreter as ``identity.python`` itself. So in a checkout they follow Node's spelling rules exactly (design 0001,
phase 2):

- the default root is the real path of the checkout that holds this package, as Node's comes from
  ``import.meta.url``: Node resolves its main module with ``fs.realpathSync``, which resolves link targets
  lexically (``nodefs.realpath_sync``), not as ``os.path.realpath`` does;
- an explicit root (``--root`` or ``EEG_REPOSITORY_ROOT``) must be absolute and is only normalized, never
  resolved through symbolic links;
- the native workflows (design evaluation, electrode editor, reception v2) use the managed interpreter when
  the checkout has one, whatever ``python`` or ``EEG_COMPUTE_PYTHON`` say; the service's own
  ``sys.executable`` never enters an identity.

The installed form (design 0002, decision U17 of the phase 3 plan) has no Node counterpart. The package lies in
``P/lib/pythonX.Y/site-packages`` of a conda prefix P (``sys.prefix``) and R in ``P/share/eeglayoutlab/root``:

- the default root is a checkout's when the package is in one, else the real path of the installed root when it
  holds ``src/compact_eeg``;
- the worker interpreter is ``<real path of P>/bin/python`` after a managed runtime and before ``python3``, only
  when the package is not in a checkout and R is the installed root. A checkout's strings never change.

The functions take ``prefix`` (default ``sys.prefix``) and ``package_file`` (default this module) so that both
forms can be tested in one process.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Mapping, Optional

from ..schemas import jsjson
from . import nodefs, nodepath

__all__ = [
    'NATIVE_RUNTIME_RELATIVE', 'TABLE_RUNTIME_RELATIVE', 'INSTALLED_ROOT_RELATIVE', 'RuntimeConfig',
    'checkout_root', 'installed_root', 'installed_form', 'installed_environment', 'environment_python',
    'default_repository_root', 'repository_root', 'native_python_path', 'table_python_path', 'managed_python',
    'runtime_config', 'unwritable_root',
]

NATIVE_RUNTIME_RELATIVE = '.runtime/simnibs-4.6.0'
# Linux runtime without SimNIBS (configs/runtime/manifest-linux-64.json): new coordinates come from published
# scalp-node tables; it cannot solve FEM.
TABLE_RUNTIME_RELATIVE = '.runtime/compute-linux-64'
# R of the installed form, relative to the prefix (design 0002, layout).
INSTALLED_ROOT_RELATIVE = 'share/eeglayoutlab/root'


def checkout_root(package_file: Optional[str] = None) -> Optional[str]:
    """The real path of the checkout that contains this package, or ``None`` outside a checkout."""
    checkout = Path(nodefs.realpath_sync(nodepath.resolve(package_file or __file__))).parents[3]
    if (checkout / 'pyproject.toml').is_file() and (checkout / 'src/compact_eeg').is_dir():
        return str(checkout)
    return None


def installed_root(prefix: Optional[str] = None) -> Optional[str]:
    """The real path of ``P/share/eeglayoutlab/root`` when it holds ``src/compact_eeg``, else ``None``."""
    selected = prefix or sys.prefix
    if not selected:
        return None
    candidate = nodepath.join(nodepath.resolve(selected), INSTALLED_ROOT_RELATIVE)
    if not os.path.isdir(nodepath.join(candidate, 'src/compact_eeg')):
        return None
    try:
        return nodefs.realpath_sync(candidate)
    except (OSError, TypeError):
        return None


def installed_form(root: str, prefix: Optional[str] = None, package_file: Optional[str] = None) -> bool:
    """Whether the package is installed, not in a checkout, and ``root`` is the installed root (U17). The root is
    compared by its real path, so a spelling through a link is the same root."""
    if checkout_root(package_file) is not None:
        return False
    installed = installed_root(prefix)
    if installed is None:
        return False
    try:
        return nodefs.realpath_sync(nodepath.resolve(root)) == installed
    except (OSError, TypeError):
        return False


def installed_environment(root: str, prefix: Optional[str] = None,
                          package_file: Optional[str] = None) -> Optional[str]:
    """The real path of P when in the installed form for ``root`` (U17), else ``None``."""
    if not installed_form(root, prefix, package_file):
        return None
    try:
        return nodefs.realpath_sync(nodepath.resolve(prefix or sys.prefix))
    except (OSError, TypeError):
        return None


def environment_python(prefix: Optional[str] = None) -> Optional[str]:
    """``<real path of P>/bin/python`` when it exists (following links, as ``existsSync`` does), else ``None``."""
    selected = prefix or sys.prefix
    try:
        python = nodepath.join(nodefs.realpath_sync(nodepath.resolve(selected)), 'bin/python')
    except (OSError, TypeError):
        return None
    return python if os.path.exists(python) else None


def default_repository_root(prefix: Optional[str] = None, package_file: Optional[str] = None) -> Optional[str]:
    """The checkout that contains this package, else the installed root, else ``None``."""
    return checkout_root(package_file) or installed_root(prefix)


def repository_root(explicit: Optional[str] = None, env: Mapping[str, str] = os.environ,
                    prefix: Optional[str] = None, package_file: Optional[str] = None) -> str:
    """``hostConfig``'s root: ``explicit || EEG_REPOSITORY_ROOT`` (absolute), else ``default_repository_root``."""
    selected = explicit or env.get('EEG_REPOSITORY_ROOT') or ''
    if selected and not nodepath.is_absolute(selected):
        raise ValueError('EEG_REPOSITORY_ROOT must be absolute.')
    if not selected:
        selected = default_repository_root(prefix, package_file) or ''
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


def _installed_python(root: str, prefix: Optional[str], package_file: Optional[str]) -> Optional[str]:
    return environment_python(prefix) if installed_form(root, prefix, package_file) else None


@dataclass(frozen=True)
class RuntimeConfig:
    """``runtimeConfig(...)`` without the queue directory, which the workspace replaces."""

    repository_root: str
    python: str
    """``computePython``: the radius worker's interpreter and the one its fingerprint describes."""
    native_python: str
    """The interpreter of the native workflows, and ``identity.python`` of design and editor keys."""


def runtime_config(repository_root: str, python: Optional[str] = None, env: Mapping[str, str] = os.environ,
                   prefix: Optional[str] = None, package_file: Optional[str] = None) -> RuntimeConfig:
    """``runtimeConfig({repositoryRoot, python, env})``: ``python || EEG_COMPUTE_PYTHON || managed || 'python3'``,
    with the environment's interpreter before ``'python3'`` in the installed form.

    The ``or`` chain follows JavaScript's ``||``: an empty string falls through, like an absent value. The
    installed form is looked at only when everything before it is empty.
    """
    if not isinstance(repository_root, str) or not jsjson.js_trim(repository_root):
        raise ValueError('A repository root is required.')
    root = nodepath.resolve(repository_root)
    managed = managed_python(root)
    compute = (python or env.get('EEG_COMPUTE_PYTHON') or managed or _installed_python(root, prefix, package_file)
               or 'python3')
    return RuntimeConfig(repository_root=root, python=compute,
                         native_python=managed if managed is not None else compute)


def _writable(path: str) -> bool:
    effective = os.access in os.supports_effective_ids
    return os.access(path, os.W_OK | os.X_OK, effective_ids=effective)


def unwritable_root(root: str, prefix: Optional[str] = None, package_file: Optional[str] = None) -> Optional[str]:
    """Why records cannot be written under ``root``, or ``None``: R must be writable, and so must the deepest of
    ``results/v2`` and ``results`` that exists (records stay at ``R/results/v2/*_jobs``, U1). The installed form
    names 0002's remedy (decision 3: read-only prefixes are unsupported); a checkout gets a generic one. Nothing is
    written to find out, and the superuser passes every check."""
    candidates = [root]
    for relative in ('results/v2', 'results'):
        path = nodepath.join(root, relative)
        if os.path.isdir(path):
            candidates.append(path)
            break
    blocked = next((path for path in candidates if not _writable(path)), None)
    if blocked is None:
        return None
    if installed_form(root, prefix, package_file):
        return (f'{blocked} is not writable. The installed application keeps its records and data in its '
                'environment, so a read-only installation is not supported: create a user environment (for example '
                'with Miniforge or micromamba in your home directory) and install eeglayoutlab into it.')
    return (f'{blocked} is not writable. Records and data are written under the scientific root; use a root you can '
            'write (--root or EEG_REPOSITORY_ROOT).')
