"""Filesystem observations for reusing the existing numerical-runtime digest.

The digest itself remains reception_forward_provider._native_runtime_identity.
This module only determines when the host must run that full inspection again.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys

from reception_forward_provider import (
    NATIVE_LIBRARY_PATTERNS, NATIVE_PACKAGES, SIMNIBS_SOURCE_FILES,
    _json_sha, _native_runtime_identity, _native_runtime_locations,
)

SCHEMA = "reception-runtime-watch/1"
_NUMERICAL_SUFFIXES = {".py", ".so", ".dylib", ".pyd"}


def _lstat(path):
    try:
        return path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return None


def _stamp(info, full):
    if info is None:
        return None
    values = [info.st_dev, info.st_ino, info.st_mode]
    if full:
        values.extend([info.st_size, info.st_mtime_ns, info.st_ctime_ns])
    return ":".join(str(value) for value in values)


def observe_filesystem(locations, *, search_paths=None, module_paths=None):
    """Watch files plus discovery directories, including symlink ancestors.

    Ancestors use inode/type/mode identity only: an unrelated sibling file must
    not invalidate a numerical environment. Direct discovery directories use
    full timestamps, so new or removed numerical files trigger inspection.
    """
    targets = {}
    expanded = set()

    def add(path, full=True):
        path = Path(path).absolute()
        pending = [(path, full)]
        while pending:
            current, complete = pending.pop()
            token = str(current)
            previous = targets.get(token)
            targets[token] = bool(previous or complete)
            if token in expanded:
                continue
            expanded.add(token)
            info = _lstat(current)
            if info is not None and stat.S_ISLNK(info.st_mode):
                targets[token] = True
                target = Path(os.readlink(current))
                pending.append((target if target.is_absolute() else current.parent / target, True))
                # Keep both the lexical link chain and its final target. This
                # also covers a link whose target traverses another directory link.
                pending.append((current.resolve(), True))
            if current.parent != current:
                pending.append((current.parent, False))

    prefix = Path(locations["prefix"])
    add(prefix)
    add(locations["executable"])
    conda = prefix / "conda-meta"
    add(conda)
    for path in conda.glob("*.json"):
        add(path)
    libraries = prefix / "lib"
    add(libraries)
    for pattern in NATIVE_LIBRARY_PATTERNS:
        for path in libraries.glob(pattern):
            add(path)
    for name in NATIVE_PACKAGES:
        package = locations["packages"][name]
        folder = Path(package["root"])
        add(folder)
        add(package["origin"])
        for path in package["metadata"]:
            add(path)
            add(Path(path).parent)
        for path in folder.rglob("*"):
            if path.is_dir() or path.is_symlink() or path.suffix in _NUMERICAL_SUFFIXES:
                add(path)
    simnibs = Path(locations["packages"]["simnibs"]["root"])
    for name in SIMNIBS_SOURCE_FILES:
        add(simnibs / name)

    # Import and metadata discovery can change without editing the currently
    # selected package, for example a new earlier module on sys.path.
    for raw in sys.path if search_paths is None else search_paths:
        directory = Path(raw or os.curdir).absolute()
        add(directory)
        if not directory.is_dir():
            continue
        for name in (*NATIVE_PACKAGES, "sitecustomize", "usercustomize"):
            for path in directory.glob(name + "*"):
                add(path)
                if path.is_dir():
                    add(path / "__init__.py")
        for path in directory.glob("*.pth"):
            add(path)
        for pattern in ("*.dist-info", "*.egg-info"):
            for folder in directory.glob(pattern):
                add(folder)
                if folder.is_dir():
                    for name in ("METADATA", "RECORD", "WHEEL", "direct_url.json", "PKG-INFO"):
                        add(folder / name)
    if module_paths is None:
        module_paths = [path for module in list(sys.modules.values())
                        for path in (getattr(module, "__file__", None), getattr(module, "__cached__", None))
                        if isinstance(path, str) and not path.startswith("<")]
    for path in module_paths:
        add(path)
    add(__file__)
    # The compatibility shim replaces its sys.modules entry with the real
    # implementation, so module.__file__ cannot reveal the executed shim.
    for name in ("reception_forward_provider.py", "inspect_reception_runtime.py",
                 "inspect_reception_runtime_snapshot.py"):
        add(Path(__file__).with_name(name))
    return {"schema": SCHEMA, "entries": [
        [path, full, _stamp(_lstat(Path(path)), full)]
        for path, full in sorted(targets.items())
    ]}


def inspect_snapshot(*, identity_reader=None, locations_reader=None,
                     search_paths=None, module_paths=None):
    identity_reader = identity_reader or _native_runtime_identity
    locations_reader = locations_reader or _native_runtime_locations
    # Discovery primes lazily imported metadata helpers before observation.
    locations = locations_reader()
    before = observe_filesystem(locations, search_paths=search_paths, module_paths=module_paths)
    identity = identity_reader()
    after = observe_filesystem(locations_reader(), search_paths=search_paths, module_paths=module_paths)
    if before != after:
        raise ValueError("Numerical runtime changed during identity inspection")
    return {"schema": "reception-runtime-digest/1", "sha256": _json_sha(identity), "watch": after}
