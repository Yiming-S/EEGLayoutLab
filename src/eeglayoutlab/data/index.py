"""Release data-package index ``data/packages.json`` (``eeglayoutlab-data-index/1``, phase 3 slice 8; U18, U19).

Pins the exact package versions, ``content_sha256``, ``manifest_sha256``, sizes, requirements and manifest URLs
accepted by this code release, resolves transitive dependencies in installation order, and checks the ``base``
package against ``R/data/manifest.json``.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import pathlib
from typing import Any, Iterable, Optional, Sequence
import urllib.parse

from .archive import archive_size
from .manifest import KINDS, NAME, SHA256, Manifest, PackageError, _version_key, accepts

__all__ = [
    'INDEX_SCHEMA', 'DEFAULT_PACKAGES', 'DEFAULT_EXAMPLE_HEADS',
    'IndexEntry', 'DataIndex', 'build_index', 'load_index',
    'examples_packages', 'verify_manifest_against_index', 'verify_base_against_bundle',
]

INDEX_SCHEMA = 'eeglayoutlab-data-index/1'
DEFAULT_PACKAGES: tuple[str, ...] = ('base', 'scalp-node-table')
DEFAULT_EXAMPLE_HEADS: tuple[str, ...] = (
    'head-ernie_xh', 'head-ixi002', 'head-ixi012', 'head-ixi013', 'head-ixi015', 'head-ixi017',
    'head-ixi019', 'head-ixi020', 'head-ixi035', 'head-ixi230', 'head-ixi231',
)


def _is_url(location: str) -> bool:
    return urllib.parse.urlsplit(location).scheme in ('https', 'http', 'file', 'ftp')


@dataclass(frozen=True)
class IndexEntry:
    name: str
    version: str
    kind: str
    accepts_code: str
    requires: tuple[str, ...]
    total_size: int
    archive_size: int
    content_sha256: str
    manifest_sha256: str
    urls: tuple[str, ...] = ()

    @property
    def stem(self) -> str:
        return f'{self.name}-{self.version}'

    def as_json(self) -> dict[str, Any]:
        return {
            'name': self.name,
            'version': self.version,
            'kind': self.kind,
            'accepts_code': self.accepts_code,
            'requires': list(self.requires),
            'total_size': self.total_size,
            'archive_size': self.archive_size,
            'content_sha256': self.content_sha256,
            'manifest_sha256': self.manifest_sha256,
            'urls': list(self.urls),
        }


def _parse_entry(raw: Any) -> IndexEntry:
    if not isinstance(raw, dict):
        raise PackageError('invalid package entry in data/packages.json')
    name = raw.get('name')
    version = raw.get('version')
    kind = raw.get('kind')
    accepts_code = raw.get('accepts_code')
    if not isinstance(name, str) or not NAME.match(name) or len(name) > 64:
        raise PackageError(f'invalid package name {name!r} in index')
    if not isinstance(version, str):
        raise PackageError(f'invalid version for {name} in index')
    _version_key(version)
    if kind not in KINDS:
        raise PackageError(f'invalid kind {kind!r} for {name} in index')
    if not isinstance(accepts_code, str):
        raise PackageError(f'invalid accepts_code for {name} in index')
    accepts(accepts_code, '0.0.0')
    requires = raw.get('requires', [])
    if not isinstance(requires, list) or not all(isinstance(r, str) and NAME.match(r) for r in requires):
        raise PackageError(f'invalid requires list for {name} in index')
    total_size = raw.get('total_size')
    arch_size = raw.get('archive_size')
    if type(total_size) is not int or total_size < 0 or type(arch_size) is not int or arch_size < 0:
        raise PackageError(f'invalid size for {name} in index')
    content_sha = raw.get('content_sha256')
    manifest_sha = raw.get('manifest_sha256')
    if not isinstance(content_sha, str) or not SHA256.match(content_sha):
        raise PackageError(f'invalid content_sha256 for {name} in index')
    if not isinstance(manifest_sha, str) or not SHA256.match(manifest_sha):
        raise PackageError(f'invalid manifest_sha256 for {name} in index')
    urls = raw.get('urls', [])
    if not isinstance(urls, list) or not all(isinstance(u, str) and u for u in urls):
        raise PackageError(f'invalid urls for {name} in index')
    for url in urls:
        if urllib.parse.urlsplit(url).scheme not in ('https', 'file'):
            raise PackageError(f'index URL must use https:// or file://: {url}')
    return IndexEntry(
        name=name,
        version=version,
        kind=kind,
        accepts_code=accepts_code,
        requires=tuple(requires),
        total_size=total_size,
        archive_size=arch_size,
        content_sha256=content_sha,
        manifest_sha256=manifest_sha,
        urls=tuple(urls),
    )


@dataclass(frozen=True)
class DataIndex:
    code_version: str
    entries: tuple[IndexEntry, ...]

    @property
    def by_name(self) -> dict[str, IndexEntry]:
        return {entry.name: entry for entry in self.entries}

    def resolve(self, names: Sequence[str]) -> list[IndexEntry]:
        """Resolves ``names`` and all transitive ``requires`` in topological installation order."""
        lookup = self.by_name
        unknown = [name for name in names if name not in lookup]
        if unknown:
            raise PackageError(f'unknown data package: {", ".join(unknown)}')
        ordered: list[IndexEntry] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(pkg_name: str) -> None:
            if pkg_name in visited:
                return
            if pkg_name in visiting:
                raise PackageError(f'cyclic package dependency involving {pkg_name}')
            if pkg_name not in lookup:
                raise PackageError(f'required package {pkg_name} is missing from data/packages.json')
            visiting.add(pkg_name)
            entry = lookup[pkg_name]
            for req in entry.requires:
                visit(req)
            visiting.remove(pkg_name)
            visited.add(pkg_name)
            ordered.append(entry)

        for name in names:
            visit(name)
        return ordered

    def manifest_locations(self, entry: IndexEntry, mirror: Optional[str] = None) -> list[str]:
        """Candidate manifest locations (``--from URL|DIR`` mirror override, else ``entry.urls``)."""
        filename = f'{entry.stem}.json'
        if mirror:
            if _is_url(mirror):
                base = mirror.rstrip('/') + '/'
                return [urllib.parse.urljoin(base, filename)]
            directory = pathlib.Path(mirror).expanduser().resolve()
            return [str(directory / filename)]
        if entry.urls:
            return list(entry.urls)
        raise PackageError(
            f'{entry.stem} has no published download URL in data/packages.json yet; '
            'pass --from <URL|DIR> to install from a mirror or local package directory'
        )

    def as_json(self) -> dict[str, Any]:
        return {
            'schema': INDEX_SCHEMA,
            'code_version': self.code_version,
            'packages': [entry.as_json() for entry in self.entries],
        }

    def dumps(self) -> str:
        return json.dumps(self.as_json(), indent=2, ensure_ascii=False) + '\n'


def build_index(
    manifests: Iterable[Manifest],
    version: str,
    *,
    url_base: Optional[str] = None,
) -> DataIndex:
    entries: list[IndexEntry] = []
    seen: set[str] = set()
    clean_base = (url_base.rstrip('/') + '/') if url_base else None
    if clean_base and urllib.parse.urlsplit(clean_base).scheme not in ('https', 'file'):
        raise PackageError(f'--url-base must be an https:// or file:// URL: {url_base}')
    for manifest in manifests:
        if manifest.name in seen:
            raise PackageError(f'duplicate package {manifest.name} in index')
        seen.add(manifest.name)
        raw_text = manifest.dumps().encode('utf-8')
        manifest_sha = hashlib.sha256(raw_text).hexdigest()
        arch_size = int(manifest.archive['size']) if manifest.archive is not None else archive_size(manifest)
        urls = (urllib.parse.urljoin(clean_base, f'{manifest.stem}.json'),) if clean_base else ()
        entries.append(
            IndexEntry(
                name=manifest.name,
                version=manifest.version,
                kind=manifest.kind,
                accepts_code=manifest.accepts_code,
                requires=manifest.requires,
                total_size=manifest.total_size,
                archive_size=arch_size,
                content_sha256=manifest.content_sha256,
                manifest_sha256=manifest_sha,
                urls=urls,
            )
        )
    return DataIndex(code_version=version, entries=tuple(entries))


def load_index(path: pathlib.Path) -> DataIndex:
    try:
        raw = json.loads(path.read_text('utf-8'))
    except OSError as error:
        raise PackageError(f'cannot read package index {path}: {error.strerror or error}') from error
    except ValueError as error:
        raise PackageError(f'package index {path} is not valid JSON: {error}') from error
    if not isinstance(raw, dict) or raw.get('schema') != INDEX_SCHEMA:
        raise PackageError(f'{path} is not an {INDEX_SCHEMA} package index')
    code_ver = raw.get('code_version')
    if not isinstance(code_ver, str):
        raise PackageError(f'{path} has no valid code_version')
    _version_key(code_ver)
    raw_packages = raw.get('packages')
    if not isinstance(raw_packages, list):
        raise PackageError(f'{path} has no packages list')
    entries = []
    seen: set[str] = set()
    for item in raw_packages:
        entry = _parse_entry(item)
        if entry.name in seen:
            raise PackageError(f'duplicate package {entry.name} in {path}')
        seen.add(entry.name)
        entries.append(entry)
    return DataIndex(code_version=code_ver, entries=tuple(entries))


def examples_packages(root: Optional[pathlib.Path] = None) -> tuple[str, ...]:
    """The packages needed for all three examples: default set plus the eleven heads of example 3."""
    heads_file = (root / 'examples/03-cross-head/heads.json') if root is not None else None
    if heads_file is not None and heads_file.is_file():
        try:
            spec = json.loads(heads_file.read_text('utf-8'))
            head_names = tuple(f"head-{item['head_id']}" for item in spec['cases'])
            return (*DEFAULT_PACKAGES, *head_names)
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return (*DEFAULT_PACKAGES, *DEFAULT_EXAMPLE_HEADS)


def verify_manifest_against_index(manifest: Manifest, raw_bytes: bytes, entry: IndexEntry) -> None:
    """Checks a fetched manifest's raw SHA-256 and identity fields against its pinned index entry."""
    actual_sha = hashlib.sha256(raw_bytes).hexdigest()
    if actual_sha != entry.manifest_sha256:
        raise PackageError(
            f'manifest SHA-256 for {entry.stem} differs from data/packages.json '
            f'(expected {entry.manifest_sha256}, got {actual_sha})'
        )
    if (manifest.name, manifest.version, manifest.content_sha256) != (
        entry.name, entry.version, entry.content_sha256
    ):
        raise PackageError(f'manifest {manifest.stem} does not match the indexed {entry.stem} content digest')


def verify_base_against_bundle(manifest: Manifest, root: pathlib.Path) -> None:
    """Checks that ``base``'s file list, sizes and SHA-256 digests match ``R/data/manifest.json``."""
    if manifest.name != 'base':
        return
    bundle_path = root / 'data/manifest.json'
    if not bundle_path.is_file():
        raise PackageError(f'{bundle_path} is missing; cannot verify base package against the scientific root')
    try:
        bundle = json.loads(bundle_path.read_text('utf-8'))
    except (OSError, ValueError) as error:
        raise PackageError(f'cannot read {bundle_path}: {error}') from error
    if not isinstance(bundle, dict) or bundle.get('schema_version') != 'eeglayoutlab-data-bundle/1':
        raise PackageError(f'{bundle_path} is not an eeglayoutlab-data-bundle/1 manifest')
    expected = {
        str(rec['path']): (int(rec['size_bytes']), str(rec['sha256']))
        for rec in bundle.get('files', [])
    }
    actual = {entry.path: (entry.size, entry.sha256) for entry in manifest.files}
    if actual != expected:
        raise PackageError(
            f'base package ({manifest.stem}) files or SHA-256 digests do not match {bundle_path}'
        )
