"""The author side: the data packages a scientific root holds, read the way the application reads them.

- ``base``: the files of the base data bundle listed in ``data/manifest.json`` (``eeglayoutlab-data-bundle/1``).
- ``scalp-node-table``: ``results/v2/current_scalp_node_table.json`` and the table it names.
- ``scalp-node-table-<scenario>``: ``results/v2/scalp_node_table_scenarios/<scenario>/current.json`` and its table.
- ``head-<id>``: ``results/v2/heads/<id>/`` with the files the evaluation reads, ``stages.json`` and its table.

A package is offered only when it is complete and consistent (the checks of
``webapp/server/runtime/scientific-context.mjs`` and ``DesignEvaluationService.heads``); anything else is listed
with the reason. Each file is hashed once, here. JSON files that name a path in a home directory are reported:
their bytes enter scientific identities, so they are published as they are or rebuilt, never edited.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import pathlib
import re
from typing import Any, Callable, Optional

from .manifest import FileEntry, Manifest, PackageError, relative_path, sha256_file

ACCEPTS_CODE = '>=0.2.0,<1.0.0'
HEAD_FILES = ('package.json', 'scalp.npz', 'admissibility.npz', 'sources.npz', 'mapping.npz', 'table.json')
HEAD_ID = re.compile(r'^[a-z0-9]+(?:[_-][a-z0-9]+)*$')
SCENARIO = re.compile(r'^[a-z0-9]+(?:[_.][a-z0-9]+)*$')
HOME_PATH = re.compile(rb'/(?:Users|home)/[^/"\s]+/')

ERNIE = {
    'source': 'SimNIBS example dataset v4.1 (Ernie)', 'license': 'CC-BY-NC-4.0',
    'copyright': '© SimNIBS developers 2024',
    'url': 'https://github.com/simnibs/example-dataset/releases/tag/v4.1',
    'license_url': 'https://creativecommons.org/licenses/by-nc/4.0/',
}
IXI = {
    'source': 'IXI dataset', 'license': 'CC-BY-SA-3.0',
    'url': 'https://brain-development.org/ixi-dataset/',
    'license_url': 'https://creativecommons.org/licenses/by-sa/3.0/',
}
CODE = 'EEGLayoutLab code that produced the files: GPL-3.0-only (the files themselves carry the data licences).'


@dataclass
class Candidate:
    """A package found in a root: its manifest when complete, else the reasons it is not."""
    name: str
    kind: str
    manifest: Optional[Manifest] = None
    problems: list[str] = field(default_factory=list)
    home_paths: list[str] = field(default_factory=list)


def _read_json(root: pathlib.Path, path: str) -> Any:
    try:
        return json.loads((root / path).read_text('utf-8'))
    except (OSError, ValueError) as error:
        raise PackageError(f'{path}: {error}') from error


def _table_files(root: pathlib.Path, pointer_path: str, pointer: Any) -> list[str]:
    manifest_path = pointer.get('manifest_path') if isinstance(pointer, dict) else None
    if not isinstance(manifest_path, str) or not manifest_path.endswith('/manifest.json'):
        raise PackageError(f'{pointer_path} names no table manifest')
    relative_path(manifest_path)
    digest, _ = sha256_file(root / manifest_path)
    if digest != pointer.get('manifest_sha256'):
        raise PackageError(f'{manifest_path} does not match the SHA-256 in {pointer_path}')
    directory = manifest_path.rsplit('/', 1)[0]
    return [manifest_path, f'{directory}/index.npz', f'{directory}/rows.npy']


def _hash(root: pathlib.Path, paths: list[str], progress: Optional[Callable[[str], None]]) -> tuple[FileEntry, ...]:
    entries = []
    for path in paths:
        relative_path(path)
        file = root / path
        if file.is_symlink() or not file.is_file():
            raise PackageError(f'{path} is missing or not a regular file')
        if progress:
            progress(path)
        digest, size = sha256_file(file)
        entries.append(FileEntry(path, size, digest))
    return tuple(entries)


def _home_paths(root: pathlib.Path, paths: list[str]) -> list[str]:
    found = []
    for path in paths:
        if path.endswith('.json'):
            count = len(HOME_PATH.findall((root / path).read_bytes()))
            if count:
                found.append(f'{path} ({count})')
    return found


def _candidate(name: str, kind: str, root: pathlib.Path, build: Callable[[], dict[str, Any]], version: str,
               progress: Optional[Callable[[str], None]]) -> Candidate:
    candidate = Candidate(name, kind)
    try:
        spec = build()
        files = _hash(root, spec['files'], progress)
        for entry in files:
            expected = spec.get('expect', {}).get(entry.path)
            if expected is not None and expected != entry.sha256:
                raise PackageError(f'{entry.path} differs from the SHA-256 its package records')
        candidate.manifest = Manifest(name, version, kind, spec['description'], ACCEPTS_CODE, files,
                                      tuple(spec.get('requires', ())), tuple(spec['licenses']), tuple(spec.get('notes', ())))
        candidate.home_paths = _home_paths(root, spec['files'])
    except PackageError as error:
        candidate.problems.append(str(error))
    except OSError as error:
        candidate.problems.append(f'{error.filename or name}: {error.strerror}')
    return candidate


def _base(root: pathlib.Path) -> dict[str, Any]:
    bundle = _read_json(root, 'data/manifest.json')
    if bundle.get('schema_version') != 'eeglayoutlab-data-bundle/1':
        raise PackageError('data/manifest.json is not an eeglayoutlab-data-bundle/1 manifest')
    records = bundle['files']
    for record in records:
        file = root / relative_path(record['path'])
        if not file.is_file() or file.stat().st_size != record['size_bytes']:
            raise PackageError(f'{record["path"]} is missing or differs from data/manifest.json')
    return {
        'files': [record['path'] for record in records],
        'expect': {record['path']: record['sha256'] for record in records},
        'description': f'Base data bundle {bundle["bundle_id"]}: the Ernie FEM mesh, the frozen forward bank, '
                       'candidate geometry, scalp mappings, source arrays and the supplied result records.',
        'licenses': [dict(ERNIE, applies_to=['all files except data/SOURCES.md']),
                     {'source': 'EEGLayoutLab', 'license': 'GPL-3.0-only', 'applies_to': ['data/SOURCES.md']}],
        'notes': [CODE, 'The per-file sources and roles are in data/manifest.json of the matching code release.'],
    }


def _nominal(root: pathlib.Path) -> dict[str, Any]:
    pointer_path = 'results/v2/current_scalp_node_table.json'
    files = [pointer_path, *_table_files(root, pointer_path, _read_json(root, pointer_path))]
    return {
        'files': files, 'requires': ['base'],
        'description': 'Scalp-node superposition table of the nominal Ernie model: evaluation of new coordinates '
                       'without a FEM solve.',
        'licenses': [dict(ERNIE, applies_to=['all files'])], 'notes': [CODE],
    }


def _scenario(root: pathlib.Path, scenario: str) -> dict[str, Any]:
    pointer_path = f'results/v2/scalp_node_table_scenarios/{scenario}/current.json'
    files = [pointer_path, *_table_files(root, pointer_path, _read_json(root, pointer_path))]
    return {
        'files': files, 'requires': ['base', 'scalp-node-table'],
        'description': f'Scalp-node table of the Ernie model under the conductivity scenario {scenario} '
                       '(configs/conductivity_scenarios.json).',
        'licenses': [dict(ERNIE, applies_to=['all files'])], 'notes': [CODE],
    }


def _head(root: pathlib.Path, head_id: str) -> dict[str, Any]:
    base = f'results/v2/heads/{head_id}'
    missing = [name for name in HEAD_FILES if not (root / base / name).is_file()]
    if missing:
        raise PackageError(f'incomplete head package: no {", ".join(missing)}')
    package = _read_json(root, f'{base}/package.json')
    if package.get('head_id') != head_id:
        raise PackageError(f'{base}/package.json names head {package.get("head_id")!r}')
    files = [f'{base}/{name}' for name in HEAD_FILES]
    recorded = package.get('files') or {}
    expect = {f'{base}/{name}': recorded.get(name) for name in HEAD_FILES if name.endswith('.npz')}
    if None in expect.values():
        raise PackageError(f'{base}/package.json does not record every array file')
    if (root / base / 'stages.json').is_file():
        files.append(f'{base}/stages.json')
    files += _table_files(root, f'{base}/table.json', _read_json(root, f'{base}/table.json'))
    dataset = package.get('dataset') or {}
    if dataset.get('name') == 'IXI':
        licenses = [dict(IXI, subject=dataset.get('subject', ''),
                         applies_to=['all files: segmentation, scalp, sources, admissibility and table of this subject']),
                    dict(ERNIE, applies_to=[f'{base}/mapping.npz: Ernie scalp positions mapped onto this head'])]
        notes = [CODE, 'Open question before publication: this package combines IXI-derived data (CC BY-SA 3.0, '
                       'ShareAlike) with an Ernie-derived mapping (CC BY-NC 4.0, NonCommercial). One licence for '
                       'the whole package needs a decision; the two terms are not compatible as one adaptation.']
    else:
        licenses = [dict(ERNIE, applies_to=['all files'])]
        notes = [CODE, 'Ernie packaged with the cross-head protocol (head-package source sampling).']
    return {
        'files': files, 'requires': ['base'], 'expect': expect,
        'description': f'Head package {head_id} ({dataset.get("name", "")} {dataset.get("subject", "")}) with its '
                       'scalp-node table, for cross-head evaluation.',
        'licenses': licenses, 'notes': notes,
    }


def discover(root: pathlib.Path, version: str = '1.0.0', only: Optional[set[str]] = None,
             progress: Optional[Callable[[str], None]] = None) -> list[Candidate]:
    """Every package of ``root``, complete or not; ``only`` restricts the names that are hashed."""
    plans: list[tuple[str, str, Callable[[], dict[str, Any]]]] = [
        ('base', 'base', lambda: _base(root)),
        ('scalp-node-table', 'scalp-node-table', lambda: _nominal(root)),
    ]
    scenarios = root / 'results/v2/scalp_node_table_scenarios'
    if scenarios.is_dir():
        for entry in sorted(scenarios.iterdir()):
            if entry.is_dir() and SCENARIO.match(entry.name):
                plans.append((f'scalp-node-table-{entry.name}', 'conductivity-scenario-table',
                              lambda name=entry.name: _scenario(root, name)))
    heads = root / 'results/v2/heads'
    if heads.is_dir():
        for entry in sorted(heads.iterdir()):
            if entry.is_dir() and HEAD_ID.match(entry.name):
                plans.append((f'head-{entry.name}', 'head', lambda name=entry.name: _head(root, name)))
    return [_candidate(name, kind, root, build, version, progress)
            for name, kind, build in plans if only is None or name in only]
