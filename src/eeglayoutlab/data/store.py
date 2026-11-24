"""The user side: packages installed in the user data directory.

Layout::

    <data dir>/packages/<name>/<version>/manifest.json
    <data dir>/packages/<name>/<version>/<the package files at their root-relative paths>

The data directory is ``EEGLAYOUTLAB_DATA_DIR`` when set, else ``~/Library/Application Support/EEGLayoutLab`` on
macOS, ``%LOCALAPPDATA%\\EEGLayoutLab`` on Windows and ``$XDG_DATA_HOME/eeglayoutlab`` (default
``~/.local/share/eeglayoutlab``) elsewhere. One version of a package is installed at a time, because two versions
hold the same root-relative paths.

An install writes into a staging directory beside its destination, checks the size and SHA-256 of every file (and of
the archive), makes the files read-only, writes the manifest last and renames the directory into place: a package
directory is complete or absent. A removal renames the directory away before deleting it. Archives are read as a stream, from a local file or
over HTTPS (redirects only to HTTPS), and never stored whole.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.metadata
import os
import pathlib
import secrets
import shutil
import stat
import sys
from typing import BinaryIO, Callable, Iterator, Mapping, Optional
import urllib.parse
import urllib.request

from .archive import Progress, extract_archive
from .manifest import CHUNK, Manifest, PackageError, accepts, loads, sha256_file

DISTRIBUTION = 'compact-eeg'
MANIFEST = 'manifest.json'
MAX_MANIFEST_BYTES = 16 << 20
# Room kept free beyond the package itself.
DISK_MARGIN = 256 << 20
TIMEOUT_SECONDS = 60


def data_dir(env: Mapping[str, str] = os.environ, platform: str = sys.platform) -> pathlib.Path:
    if env.get('EEGLAYOUTLAB_DATA_DIR'):
        return pathlib.Path(env['EEGLAYOUTLAB_DATA_DIR']).expanduser()
    home = pathlib.Path(env.get('HOME') or pathlib.Path.home())
    if platform == 'darwin':
        return home / 'Library/Application Support/EEGLayoutLab'
    if platform.startswith('win'):
        return pathlib.Path(env.get('LOCALAPPDATA') or home / 'AppData/Local') / 'EEGLayoutLab'
    return pathlib.Path(env.get('XDG_DATA_HOME') or home / '.local/share') / 'eeglayoutlab'


def code_version() -> str:
    """The version of the running code: the checkout's ``pyproject.toml`` when the package runs from a checkout (an
    interpreter can hold an older installed copy), else the installed distribution's metadata."""
    import tomllib
    pyproject = pathlib.Path(__file__).resolve().parents[3] / 'pyproject.toml'
    if pyproject.is_file():
        project = tomllib.loads(pyproject.read_text('utf-8')).get('project', {})
        if project.get('name') == DISTRIBUTION and project.get('version'):
            return str(project['version'])
    return importlib.metadata.version(DISTRIBUTION)


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if urllib.parse.urlsplit(newurl).scheme != 'https':
            raise PackageError(f'refusing a redirect to {newurl}')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _is_url(location: str) -> bool:
    return urllib.parse.urlsplit(location).scheme in ('https', 'http', 'file', 'ftp')


def _open_url(url: str) -> BinaryIO:
    if urllib.parse.urlsplit(url).scheme not in ('https', 'file'):
        raise PackageError(f'only https:// and file:// addresses are accepted: {url}')
    opener = urllib.request.build_opener(_HttpsOnly)
    opener.addheaders = [('User-Agent', 'eeglayoutlab-data')]
    try:
        return opener.open(url, timeout=TIMEOUT_SECONDS)
    except OSError as error:
        raise PackageError(f'cannot open {url}: {error}') from error


@dataclass(frozen=True)
class Source:
    """Where a manifest was read and how to open the archive beside it."""
    manifest: Manifest
    location: str

    def open_archive(self) -> BinaryIO:
        archive = self.manifest.archive
        if archive is None:
            raise PackageError(f'{self.manifest.stem} is published without an archive; install it with --from-root')
        if _is_url(self.location):
            return _open_url(urllib.parse.urljoin(self.location, archive['name']))
        return (pathlib.Path(self.location).parent / archive['name']).open('rb')


def read_source(location: str) -> Source:
    """The manifest at a local path or an https:// or file:// address."""
    if _is_url(location):
        with _open_url(location) as response:
            text = response.read(MAX_MANIFEST_BYTES + 1)
    else:
        try:
            with open(location, 'rb') as stream:
                text = stream.read(MAX_MANIFEST_BYTES + 1)
        except OSError as error:
            raise PackageError(f'cannot read {location}: {error.strerror}') from error
    if len(text) > MAX_MANIFEST_BYTES:
        raise PackageError(f'{location} is too large to be a manifest')
    try:
        return Source(loads(text.decode('utf-8')), location)
    except UnicodeDecodeError as error:
        raise PackageError(f'{location} is not UTF-8') from error


@dataclass(frozen=True)
class Installed:
    manifest: Manifest
    path: pathlib.Path


def read_only(path: pathlib.Path) -> None:
    """Removes the write permissions of an installed file (and of every hard link to it)."""
    mode = path.stat().st_mode
    if mode & 0o222:
        os.chmod(path, stat.S_IMODE(mode) & ~0o222)


def copy_checked(source: pathlib.Path, target: pathlib.Path, size: int, sha256: str,
                  progress: Optional[Progress]) -> None:
    digest, copied = hashlib.sha256(), 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as stream, open(target, 'xb') as out:
        for block in iter(lambda: stream.read(CHUNK), b''):
            digest.update(block)
            copied += len(block)
            out.write(block)
            if progress:
                progress(len(block))
    if copied != size or digest.hexdigest() != sha256:
        raise PackageError(f'{source} does not match its SHA-256 in the manifest')


class Store:
    def __init__(self, root: pathlib.Path):
        self.root = root
        self.packages = root / 'packages'

    def installed(self) -> list[Installed]:
        """Every installed package; a directory whose manifest cannot be read is skipped (``verify`` reports it)."""
        found = []
        for directory in self._package_dirs():
            try:
                manifest = loads((directory / MANIFEST).read_text('utf-8'))
            except (OSError, PackageError):
                continue
            found.append(Installed(manifest, directory))
        return found

    def _package_dirs(self) -> Iterator[pathlib.Path]:
        if not self.packages.is_dir():
            return
        for name in sorted(self.packages.iterdir()):
            if name.name.startswith('.') or not name.is_dir():
                continue
            for version in sorted(name.iterdir()):
                if version.is_dir():
                    yield version

    def find(self, name: str) -> Optional[Installed]:
        return next((item for item in self.installed() if item.manifest.name == name), None)

    def install(self, source: Source, from_root: Optional[pathlib.Path] = None, check_code: bool = True,
                progress: Optional[Progress] = None) -> tuple[Installed, bool]:
        """Installs the package of ``source`` from its archive, or by copying its files from ``from_root``.
        Returns the installed package and whether anything was written."""
        manifest = source.manifest
        if check_code and not accepts(manifest.accepts_code, code_version()):
            raise PackageError(f'{manifest.stem} needs code {manifest.accepts_code}; this is {code_version()}')
        current = self.find(manifest.name)
        if current is not None:
            if current.manifest.version == manifest.version and current.manifest.content_sha256 == manifest.content_sha256:
                return current, False
            raise PackageError(f'{current.manifest.stem} is installed; remove it before installing {manifest.stem}')
        destination = self.packages / manifest.name / manifest.version
        if destination.exists():
            raise PackageError(f'{destination} exists but holds no readable package; remove it first')
        self.packages.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(self.packages).free
        if free < manifest.total_size + DISK_MARGIN:
            raise PackageError(f'{manifest.stem} needs {manifest.total_size / 1e9:.2f} GB; '
                               f'{free / 1e9:.2f} GB are free in {self.packages}')
        staging = self.packages / f'.staging-{manifest.stem}-{secrets.token_hex(4)}'
        staging.mkdir()
        try:
            if from_root is not None:
                for entry in manifest.files:
                    copy_checked(from_root / entry.path, staging / entry.path, entry.size, entry.sha256, progress)
            else:
                with source.open_archive() as stream:
                    extract_archive(stream, manifest, staging, progress)
            for entry in manifest.files:
                read_only(staging / entry.path)
            (staging / MANIFEST).write_text(manifest.dumps(), 'utf-8')
            destination.parent.mkdir(exist_ok=True)
            os.rename(staging, destination)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return Installed(manifest, destination), True

    def verify(self, names: Optional[list[str]] = None,
               on_file: Optional[Callable[[str], None]] = None) -> dict[str, list[str]]:
        """Problems of each installed package (an empty list when it is intact), keyed by ``name-version``."""
        results: dict[str, list[str]] = {}
        wanted = set(names) if names else None
        for directory in self._package_dirs():
            label = f'{directory.parent.name}-{directory.name}'
            try:
                manifest = loads((directory / MANIFEST).read_text('utf-8'))
            except (OSError, PackageError) as error:
                if wanted is None or directory.parent.name in wanted:
                    results[label] = [f'manifest: {error}']
                continue
            if wanted is not None and manifest.name not in wanted:
                continue
            if (manifest.name, manifest.version) != (directory.parent.name, directory.name):
                results[label] = [f'directory holds {manifest.stem}']
                continue
            results[manifest.stem] = _check_files(directory, manifest, on_file)
        if wanted is not None:
            for name in sorted(wanted - {key.rsplit('-', 1)[0] for key in results}):
                results[name] = ['not installed']
        return results

    def remove(self, name: str) -> Installed:
        current = self.find(name)
        if current is None:
            raise PackageError(f'{name} is not installed')
        trash = self.packages / f'.removing-{current.manifest.stem}-{secrets.token_hex(4)}'
        os.rename(current.path, trash)
        shutil.rmtree(trash)
        try:
            current.path.parent.rmdir()
        except OSError:
            pass
        return current


def _check_files(directory: pathlib.Path, manifest: Manifest, on_file: Optional[Callable[[str], None]]) -> list[str]:
    problems = []
    listed = {entry.path for entry in manifest.files}
    for entry in manifest.files:
        path = directory / entry.path
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            problems.append(f'{entry.path}: missing')
            continue
        if not stat.S_ISREG(mode):
            problems.append(f'{entry.path}: not a regular file')
            continue
        if on_file:
            on_file(entry.path)
        digest, size = sha256_file(path)
        if size != entry.size:
            problems.append(f'{entry.path}: size {size}, manifest {entry.size}')
        elif digest != entry.sha256:
            problems.append(f'{entry.path}: SHA-256 differs from the manifest')
    for path in sorted(directory.rglob('*')):
        relative = path.relative_to(directory).as_posix()
        if relative != MANIFEST and relative not in listed and (path.is_symlink() or not path.is_dir()):
            problems.append(f'{relative}: not in the manifest')
    return problems
