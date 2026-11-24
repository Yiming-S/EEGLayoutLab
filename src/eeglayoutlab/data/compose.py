"""Places the files of installed packages in a scientific root (``eeglayoutlab data compose``).

The service and the workers read data at root-relative paths under the scientific root, which is the checkout by
default. Composing puts every file of the chosen packages at its path there:

- a hard link to the installed file when the store and the root are on one file system, so no space is used twice;
- otherwise a copy, checked against the size and SHA-256 in the manifest and renamed into place.

Installed files and their links are read-only. A program that rewrites such a file in place therefore fails instead
of changing the installed package; a program that writes a new file and renames it over the old one replaces the
link and leaves the store unchanged.

Nothing is written while any path conflicts: a path that holds different bytes, a directory or a symbolic link, or
that lies below a symbolic link. A file that is already in place with the manifest's bytes is left alone, so composing
again completes an interrupted run. Compose checks the size of each installed file; ``verify`` checks the SHA-256.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import errno
import os
import pathlib
import secrets
import stat
from typing import Callable, Optional

from .manifest import FileEntry, PackageError, sha256_file
from .store import Installed, Store, copy_checked, read_only

# Errors after which a hard link cannot be made and the file is copied instead.
LINK_UNSUPPORTED = {errno.EXDEV, errno.EPERM, errno.EMLINK, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EACCES}


@dataclass(frozen=True)
class Placement:
    package: str
    entry: FileEntry
    source: pathlib.Path
    target: pathlib.Path


@dataclass
class Plan:
    root: pathlib.Path
    packages: list[Installed]
    place: list[Placement] = field(default_factory=list)
    present: list[Placement] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)

    @property
    def place_bytes(self) -> int:
        return sum(item.entry.size for item in self.place)


@dataclass
class Outcome:
    linked: int = 0
    copied: int = 0
    copied_bytes: int = 0


def _select(store: Store, names: Optional[list[str]]) -> tuple[list[Installed], list[tuple[str, str]]]:
    installed = {item.manifest.name: item for item in store.installed()}
    if names:
        unknown = sorted(set(names) - set(installed))
        if unknown:
            raise PackageError(f'not installed: {", ".join(unknown)}')
        wanted = set(names)
    else:
        wanted = set(installed)
    missing: list[tuple[str, str]] = []
    pending = sorted(wanted)
    while pending:
        name = pending.pop()
        for requirement in installed[name].manifest.requires:
            if requirement in installed:
                if requirement not in wanted:
                    wanted.add(requirement)
                    pending.append(requirement)
            elif (name, requirement) not in missing:
                missing.append((name, requirement))
    return [installed[name] for name in sorted(wanted)], sorted(missing)


def _parent_problem(root: pathlib.Path, relative: str, checked: dict[str, Optional[str]]) -> Optional[str]:
    """Why the directories above ``relative`` cannot hold it, or ``None``."""
    parts = relative.split('/')[:-1]
    for depth in range(1, len(parts) + 1):
        prefix = '/'.join(parts[:depth])
        if prefix not in checked:
            try:
                mode = (root / prefix).lstat().st_mode
            except FileNotFoundError:
                checked[prefix] = None
                return None
            if stat.S_ISLNK(mode):
                checked[prefix] = f'{prefix} is a symbolic link'
            elif not stat.S_ISDIR(mode):
                checked[prefix] = f'{prefix} is not a directory'
            else:
                checked[prefix] = None
        if checked[prefix]:
            return checked[prefix]
    return None


def plan(store: Store, root: pathlib.Path, names: Optional[list[str]] = None,
         on_hash: Optional[Callable[[str], None]] = None) -> Plan:
    """What composing ``names`` (every installed package when empty) and the packages they need into ``root`` does."""
    packages, missing = _select(store, names)
    result = Plan(root, packages, missing=missing)
    claimed: dict[str, Placement] = {}
    checked: dict[str, Optional[str]] = {}
    for installed in packages:
        manifest = installed.manifest
        for entry in manifest.files:
            placement = Placement(manifest.name, entry, installed.path / entry.path, root / entry.path)
            earlier = claimed.get(entry.path)
            if earlier is not None:
                if earlier.entry.sha256 != entry.sha256:
                    result.conflicts.append(f'{entry.path}: {earlier.package} and {manifest.name} hold different files')
                continue
            claimed[entry.path] = placement
            try:
                source = placement.source.lstat()
            except FileNotFoundError:
                source = None
            if source is None or not stat.S_ISREG(source.st_mode) or source.st_size != entry.size:
                result.conflicts.append(f'{entry.path}: the installed copy in {manifest.stem} is missing or damaged; '
                                        f'run eeglayoutlab data verify {manifest.name}')
                continue
            problem = _parent_problem(root, entry.path, checked)
            if problem:
                result.conflicts.append(f'{entry.path}: {problem}')
                continue
            try:
                target = placement.target.lstat()
            except FileNotFoundError:
                result.place.append(placement)
                continue
            if not stat.S_ISREG(target.st_mode):
                result.conflicts.append(f'{entry.path}: is a {"symbolic link" if stat.S_ISLNK(target.st_mode) else "directory or special file"}')
            elif (target.st_dev, target.st_ino) == (source.st_dev, source.st_ino):
                result.present.append(placement)
            elif target.st_size != entry.size:
                result.conflicts.append(f'{entry.path}: holds a different file ({target.st_size} bytes, '
                                        f'package {entry.size})')
            else:
                if on_hash:
                    on_hash(entry.path)
                if sha256_file(placement.target)[0] == entry.sha256:
                    result.present.append(placement)
                else:
                    result.conflicts.append(f'{entry.path}: holds a different file of the same size')
    return result


def apply(work: Plan, copy: bool = False, progress: Optional[Callable[[int], None]] = None) -> Outcome:
    """Places the files of a plan without conflicts."""
    if work.conflicts:
        raise PackageError(f'{len(work.conflicts)} path(s) conflict; nothing was written')
    outcome = Outcome()
    link = not copy
    for item in work.place:
        item.target.parent.mkdir(parents=True, exist_ok=True)
        if link:
            read_only(item.source)
            try:
                os.link(item.source, item.target)
                outcome.linked += 1
                if progress:
                    progress(item.entry.size)
                continue
            except OSError as error:
                if error.errno not in LINK_UNSUPPORTED:
                    raise
                link = False
        partial = item.target.with_name(f'.{item.target.name}.compose-{secrets.token_hex(4)}')
        try:
            copy_checked(item.source, partial, item.entry.size, item.entry.sha256, progress)
            read_only(partial)
            os.rename(partial, item.target)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        outcome.copied += 1
        outcome.copied_bytes += item.entry.size
    return outcome


def shared_files(installed: Installed) -> int:
    """The installed files that have another hard link, such as a composed root."""
    count = 0
    for entry in installed.manifest.files:
        try:
            if (installed.path / entry.path).lstat().st_nlink > 1:
                count += 1
        except FileNotFoundError:
            pass
    return count
