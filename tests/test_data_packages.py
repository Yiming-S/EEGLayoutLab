"""Data packages (src/eeglayoutlab/data): manifests, catalog, archives, install, verify and remove."""
from __future__ import annotations

import errno
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tarfile

import pytest

from eeglayoutlab.data import catalog
from eeglayoutlab.data import cli as data_cli
from eeglayoutlab.data import compose
from eeglayoutlab.data.archive import archive_size, extract_archive, write_archive
from eeglayoutlab.data.manifest import PackageError, accepts, loads, parse, relative_path
from eeglayoutlab.data.store import Store, data_dir, read_source


def _write(root: Path, path: str, data: bytes) -> str:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _table(root: Path, pointer: str, directory: str, seed: bytes) -> None:
    digest = _write(root, f'{directory}/manifest.json', b'{"table": "%s"}' % seed)
    _write(root, f'{directory}/index.npz', seed * 100)
    _write(root, f'{directory}/rows.npy', seed * 3000)
    _write(root, pointer, json.dumps({'manifest_path': f'{directory}/manifest.json', 'manifest_sha256': digest}).encode())


def _head(root: Path, head_id: str, dataset: dict, home: bool = False) -> None:
    base = f'results/v2/heads/{head_id}'
    files = {name: _write(root, f'{base}/{name}', f'{head_id}:{name}'.encode() * 50)
             for name in ('scalp.npz', 'admissibility.npz', 'sources.npz', 'mapping.npz')}
    package = {'schema': 'head-package/1', 'head_id': head_id, 'dataset': dataset, 'files': files}
    if home:
        package['inputs'] = {'ernie_m2m': '/Users/someone/data/m2m_ernie'}
    _write(root, f'{base}/package.json', json.dumps(package).encode())
    _write(root, f'{base}/stages.json', b'{}')
    _table(root, f'{base}/table.json', f'results/v2/heads/{head_id}/scalp_node_table/t', head_id.encode())


@pytest.fixture
def science(tmp_path: Path) -> Path:
    root = tmp_path / 'science'
    records = []
    for path, data in (('data/external/m2m_ernie/ernie.msh', b'mesh' * 1000), ('data/SOURCES.md', b'# Sources\n'),
                       ('results/v2/current_multiregion_bank.json', b'{"bank": 1}')):
        records.append({'path': path, 'size_bytes': len(data), 'sha256': _write(root, path, data)})
    _write(root, 'data/manifest.json', json.dumps({
        'schema_version': 'eeglayoutlab-data-bundle/1', 'bundle_id': 'test-bundle', 'files': records}).encode())
    _table(root, 'results/v2/current_scalp_node_table.json', 'results/v2/scalp_node_table/nominal', b'n')
    _table(root, 'results/v2/scalp_node_table_scenarios/skull_x2/current.json',
           'results/v2/scalp_node_table_scenarios/skull_x2/table', b's')
    _head(root, 'ixi002', {'name': 'IXI', 'subject': 'IXI002', 'license': 'CC BY-SA 3.0'}, home=True)
    _head(root, 'ernie_xh', {'name': 'SimNIBS example dataset v4.1', 'subject': 'ernie'})
    _write(root, 'results/v2/heads/ixi014/stages.json', b'{}')
    return root


def _by_name(science: Path, **kwargs) -> dict[str, catalog.Candidate]:
    return {c.name: c for c in catalog.discover(science, **kwargs)}


def test_catalog_finds_complete_packages_and_reports_the_rest(science: Path) -> None:
    found = _by_name(science)
    assert sorted(found) == ['base', 'head-ernie_xh', 'head-ixi002', 'head-ixi014', 'scalp-node-table',
                             'scalp-node-table-skull_x2']
    assert found['head-ixi014'].manifest is None
    assert 'incomplete head package' in found['head-ixi014'].problems[0]
    base = found['base'].manifest
    assert [entry.path for entry in base.files][1] == 'data/SOURCES.md'
    head = found['head-ixi002'].manifest
    assert head.requires == ('base',)
    assert [entry.path.rsplit('/', 1)[-1] for entry in head.files] == [
        'package.json', 'scalp.npz', 'admissibility.npz', 'sources.npz', 'mapping.npz', 'table.json', 'stages.json',
        'manifest.json', 'index.npz', 'rows.npy']
    assert {item['license'] for item in head.licenses} == {'CC-BY-SA-3.0', 'CC-BY-NC-4.0'}
    assert any('Open question' in note for note in head.notes)
    assert found['head-ixi002'].home_paths == ['results/v2/heads/ixi002/package.json (1)']
    assert found['head-ernie_xh'].home_paths == []
    assert found['scalp-node-table-skull_x2'].manifest.requires == ('base', 'scalp-node-table')


def test_catalog_refuses_files_that_differ_from_what_their_package_records(science: Path) -> None:
    _write(science, 'results/v2/heads/ixi002/mapping.npz', b'changed')
    _write(science, 'results/v2/scalp_node_table/nominal/manifest.json', b'{"table": "other"}')
    found = _by_name(science, only={'head-ixi002', 'scalp-node-table'})
    assert 'differs from the SHA-256 its package records' in found['head-ixi002'].problems[0]
    assert 'does not match the SHA-256' in found['scalp-node-table'].problems[0]


def test_manifest_round_trip_and_validation(science: Path) -> None:
    manifest = _by_name(science, only={'head-ixi002'})['head-ixi002'].manifest
    assert loads(manifest.dumps()) == manifest
    value = json.loads(manifest.dumps())
    for change in ({'total_size': 1}, {'schema': 'other'}, {'name': 'Head'}, {'version': '1.0'},
                   {'archive': {'name': 'other.tar', 'size': 1, 'sha256': '0' * 64}}):
        with pytest.raises(PackageError):
            parse({**value, **change})
    tampered = json.loads(manifest.dumps())
    tampered['files'][0]['sha256'] = '0' * 64
    with pytest.raises(PackageError, match='content_sha256'):
        parse(tampered)
    for bad in ('../results/v2/x', '/results/v2/x', 'results/v2/../x', 'results/v2//x', 'src/x.py', 'C:/x',
                'results\\v2\\x'):
        with pytest.raises(PackageError):
            relative_path(bad)
    assert accepts('>=0.2.0,<1.0.0', '0.2.0') and not accepts('>=0.2.0,<1.0.0', '1.0.0')
    assert accepts('==1.2.3', '1.2.3') and not accepts('>0.2.0', '0.2.0')


def test_archive_is_deterministic_and_its_size_is_known_in_advance(science: Path, tmp_path: Path) -> None:
    manifest = _by_name(science, only={'base'})['base'].manifest
    first = write_archive(science, manifest, tmp_path / 'a.tar')
    second = write_archive(science, manifest, tmp_path / 'b.tar')
    assert first == second
    assert first[0] == archive_size(manifest) == (tmp_path / 'a.tar').stat().st_size


def test_archive_refuses_a_file_that_changed_since_hashing(science: Path, tmp_path: Path) -> None:
    manifest = _by_name(science, only={'base'})['base'].manifest
    _write(science, 'data/SOURCES.md', b'# Sources!\n')
    with pytest.raises(PackageError, match='no longer matches'):
        write_archive(science, manifest, tmp_path / 'a.tar')
    assert not list(tmp_path.glob('a.tar*'))


def _publish(science: Path, out: Path, name: str) -> Path:
    assert data_cli.main(['data', 'build', '--root', str(science), '--out', str(out), '--only', name,
                          '--archive', name]) == 0
    return out / f'{name}-1.0.0.json'


def test_install_verify_and_remove(science: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    published = _publish(science, tmp_path / 'out', 'head-ixi002')
    store_dir = tmp_path / 'store'
    store = Store(store_dir)
    installed, written = store.install(read_source(str(published)))
    assert written and installed.path == store_dir / 'packages/head-ixi002/1.0.0'
    assert (installed.path / 'results/v2/heads/ixi002/mapping.npz').read_bytes() == \
        (science / 'results/v2/heads/ixi002/mapping.npz').read_bytes()
    assert store.verify() == {'head-ixi002-1.0.0': []}
    assert store.install(read_source(str(published)))[1] is False
    assert not [p for p in (store_dir / 'packages').iterdir() if p.name.startswith('.')]

    assert data_cli.main(['data', '--data-dir', str(store_dir), 'list']) == 0
    assert 'head-ixi002  1.0.0  head' in capsys.readouterr().out
    assert data_cli.main(['data', '--data-dir', str(store_dir), 'verify']) == 0

    # Installed files are read-only. A corrupted copy, an unlisted file and a missing file are each reported, and
    # verify exits 1.
    target = installed.path / 'results/v2/heads/ixi002/sources.npz'
    assert not stat.S_IMODE(target.stat().st_mode) & 0o222
    target.chmod(0o644)
    data = bytearray(target.read_bytes())
    data[3] ^= 1
    target.write_bytes(bytes(data))
    (installed.path / 'results/v2/heads/ixi002/extra.npy').write_bytes(b'x')
    (installed.path / 'results/v2/heads/ixi002/stages.json').unlink()
    problems = store.verify(['head-ixi002'])['head-ixi002-1.0.0']
    assert problems == ['results/v2/heads/ixi002/sources.npz: SHA-256 differs from the manifest',
                        'results/v2/heads/ixi002/stages.json: missing',
                        'results/v2/heads/ixi002/extra.npy: not in the manifest']
    assert data_cli.main(['data', '--data-dir', str(store_dir), 'verify', 'head-ixi002']) == 1
    assert store.verify(['base']) == {'base': ['not installed']}

    store.remove('head-ixi002')
    assert store.installed() == [] and not (store_dir / 'packages/head-ixi002').exists()
    with pytest.raises(PackageError, match='not installed'):
        store.remove('head-ixi002')


def test_install_from_a_file_address_and_from_a_root(science: Path, tmp_path: Path) -> None:
    published = _publish(science, tmp_path / 'out', 'base')
    store = Store(tmp_path / 'store')
    store.install(read_source(published.as_uri()))
    assert store.verify() == {'base-1.0.0': []}
    other = Store(tmp_path / 'store2')
    other.install(read_source(str(published)), from_root=science)
    assert other.verify() == {'base-1.0.0': []}
    with pytest.raises(PackageError, match='https:// and file://'):
        read_source('http://example.org/base-1.0.0.json')


def test_install_leaves_nothing_behind_when_the_archive_is_damaged(science: Path, tmp_path: Path) -> None:
    published = _publish(science, tmp_path / 'out', 'head-ixi002')
    archive = tmp_path / 'out/head-ixi002-1.0.0.tar'
    data = bytearray(archive.read_bytes())
    data[data.index(b'ixi002:sources.npz')] ^= 1
    archive.write_bytes(bytes(data))
    store = Store(tmp_path / 'store')
    with pytest.raises(PackageError, match='sources.npz does not match'):
        store.install(read_source(str(published)))
    assert store.installed() == []
    assert list((tmp_path / 'store/packages').iterdir()) == []


def test_install_refuses_a_code_version_the_manifest_does_not_accept(science: Path, tmp_path: Path) -> None:
    published = _publish(science, tmp_path / 'out', 'base')
    value = json.loads(published.read_text())
    value['accepts_code'] = '>=9.0.0'
    published.write_text(json.dumps(value))
    with pytest.raises(PackageError, match='needs code >=9.0.0'):
        Store(tmp_path / 'store').install(read_source(str(published)))


def _tar(members: list[tuple[tarfile.TarInfo, bytes]]) -> io.BytesIO:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.PAX_FORMAT) as tar:
        for info, data in members:
            tar.addfile(info, io.BytesIO(data) if info.isreg() else None)
    buffer.seek(0)
    return buffer


@pytest.mark.parametrize('kind', ['unlisted', 'traversal', 'symlink', 'twice'])
def test_extraction_refuses_unsafe_members(science: Path, tmp_path: Path, kind: str) -> None:
    manifest = _by_name(science, only={'base'})['base'].manifest
    members = []
    for entry in manifest.files:
        info = tarfile.TarInfo(entry.path)
        info.size = entry.size
        members.append((info, (science / entry.path).read_bytes()))
    if kind == 'twice':
        members.append(members[0])
    elif kind == 'symlink':
        link = tarfile.TarInfo(manifest.files[0].path)
        link.type, link.linkname = tarfile.SYMTYPE, '/etc/passwd'
        members[0] = (link, b'')
    else:
        info = tarfile.TarInfo('results/v2/extra.json' if kind == 'unlisted' else '../evil')
        info.size = 1
        members.insert(0, (info, b'x'))
    staging = tmp_path / 'staging'
    staging.mkdir()
    with pytest.raises(PackageError):
        extract_archive(_tar(members), manifest, staging)
    assert not (tmp_path / 'evil').exists()


def test_build_writes_the_catalog_and_the_size_report(science: Path, tmp_path: Path) -> None:
    out = tmp_path / 'out'
    assert data_cli.main(['data', 'build', '--root', str(science), '--out', str(out), '--archive', 'base']) == 0
    summary = json.loads((out / 'catalog.json').read_text())
    packages = {item['name']: item for item in summary['packages']}
    assert set(packages) == {'base', 'scalp-node-table', 'scalp-node-table-skull_x2', 'head-ixi002', 'head-ernie_xh'}
    assert packages['base']['archive_written'] and not packages['head-ixi002']['archive_written']
    assert packages['base']['archive_size'] == (out / 'base-1.0.0.tar').stat().st_size
    assert packages['head-ixi002']['home_paths'] == ['results/v2/heads/ixi002/package.json (1)']
    assert summary['not_packaged'][0]['name'] == 'head-ixi014'
    assert summary['zenodo']['fits_one_record'] is True
    assert loads((out / 'head-ixi002-1.0.0.json').read_text()).archive is None
    assert 'Zenodo accepts 50.00 GB and 100 files per record' in (out / 'report.md').read_text()
    assert str(science) not in (out / 'catalog.json').read_text()


def test_data_directory_follows_the_platform() -> None:
    assert data_dir({'EEGLAYOUTLAB_DATA_DIR': '/d'}, 'linux') == Path('/d')
    assert data_dir({'HOME': '/h'}, 'darwin') == Path('/h/Library/Application Support/EEGLayoutLab')
    assert data_dir({'HOME': '/h'}, 'linux') == Path('/h/.local/share/eeglayoutlab')
    assert data_dir({'HOME': '/h', 'XDG_DATA_HOME': '/x'}, 'linux') == Path('/x/eeglayoutlab')
    assert data_dir({'HOME': '/h', 'LOCALAPPDATA': '/l'}, 'win32') == Path('/l/EEGLayoutLab')


def _installed(science: Path, tmp_path: Path, *names: str) -> Path:
    store_dir = tmp_path / 'store'
    for name in names:
        Store(store_dir).install(read_source(str(_publish(science, tmp_path / 'out', name))))
    return store_dir


def _checkout(tmp_path: Path) -> Path:
    root = tmp_path / 'checkout'
    (root / 'configs').mkdir(parents=True)
    return root


def _files(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob('*') if not path.is_dir()}


def test_compose_links_installed_files_into_a_root(science: Path, tmp_path: Path,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    store_dir = _installed(science, tmp_path, 'base', 'head-ixi002')
    root = _checkout(tmp_path)
    _write(root, 'data/SOURCES.md', (science / 'data/SOURCES.md').read_bytes())
    command = ['data', '--data-dir', str(store_dir), 'compose', '--root', str(root)]

    # Naming the head brings in base, which it needs; the identical tracked file is left as it is.
    assert data_cli.main(command + ['head-ixi002', '--dry-run']) == 0
    assert 'Dry run' in capsys.readouterr().out and _files(root) == {'data/SOURCES.md'}
    assert data_cli.main(command + ['head-ixi002']) == 0
    out = capsys.readouterr().out
    assert 'Packages: base-1.0.0, head-ixi002-1.0.0' in out and '1 already in place' in out
    installed = Store(store_dir).find('head-ixi002')
    for entry in installed.manifest.files:
        placed, kept = root / entry.path, installed.path / entry.path
        assert os.path.samestat(placed.stat(), kept.stat())
        assert not stat.S_IMODE(placed.stat().st_mode) & 0o222
    assert not os.path.samestat((root / 'data/SOURCES.md').stat(),
                                (store_dir / 'packages/base/1.0.0/data/SOURCES.md').stat())

    # Composing again places nothing; the store is intact.
    assert data_cli.main(command) == 0
    assert '0 file(s) to place' in capsys.readouterr().out
    assert all(not problems for problems in Store(store_dir).verify().values())
    if os.geteuid() != 0:
        with pytest.raises(PermissionError):
            (root / 'results/v2/heads/ixi002/mapping.npz').write_bytes(b'changed in place')

    # Removing the package says that the root still holds links; the root keeps its files.
    assert data_cli.main(['data', '--data-dir', str(store_dir), 'remove', 'head-ixi002']) == 0
    assert 'still hard-linked elsewhere' in capsys.readouterr().out
    assert (root / 'results/v2/heads/ixi002/mapping.npz').read_bytes() == \
        (science / 'results/v2/heads/ixi002/mapping.npz').read_bytes()


def test_compose_writes_nothing_while_a_path_conflicts(science: Path, tmp_path: Path,
                                                       capsys: pytest.CaptureFixture[str]) -> None:
    store_dir = _installed(science, tmp_path, 'base', 'head-ixi002')
    root = _checkout(tmp_path)
    _write(root, 'data/SOURCES.md', b'# Edited\n')
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (root / 'results/v2').mkdir(parents=True)
    (root / 'results/v2/heads').symlink_to(elsewhere)
    before = _files(root)
    assert data_cli.main(['data', '--data-dir', str(store_dir), 'compose', '--root', str(root)]) == 1
    out = capsys.readouterr().out
    assert 'Nothing was written' in out
    assert 'data/SOURCES.md: holds a different file' in out
    assert 'results/v2/heads/ixi002/package.json: results/v2/heads is a symbolic link' in out
    assert _files(root) == before and list(elsewhere.iterdir()) == []
    assert data_cli.main(['data', '--data-dir', str(store_dir), 'compose', '--root', str(tmp_path)]) == 1
    assert 'no configs/ directory' in capsys.readouterr().err
    assert data_cli.main(['data', '--data-dir', str(store_dir), 'compose', 'head-ernie_xh', '--root', str(root)]) == 1
    assert 'not installed: head-ernie_xh' in capsys.readouterr().err


def test_compose_copies_when_a_hard_link_cannot_be_made(science: Path, tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    store_dir = _installed(science, tmp_path, 'base')
    store = Store(store_dir)

    def cross_device(source: object, target: object) -> None:
        raise OSError(errno.EXDEV, 'Invalid cross-device link')

    monkeypatch.setattr(compose.os, 'link', cross_device)
    root = _checkout(tmp_path)
    outcome = compose.apply(compose.plan(store, root))
    assert (outcome.linked, outcome.copied) == (0, len(store.find('base').manifest.files))
    monkeypatch.undo()
    other = _checkout(tmp_path / 'b')
    assert compose.apply(compose.plan(store, other), copy=True).copied == outcome.copied
    for placed_root in (root, other):
        replan = compose.plan(store, placed_root)
        assert replan.place == [] and replan.conflicts == [] and len(replan.present) == outcome.copied
        placed = placed_root / 'data/external/m2m_ernie/ernie.msh'
        assert not os.path.samestat(placed.stat(), (store.find('base').path / 'data/external/m2m_ernie/ernie.msh').stat())
        assert not stat.S_IMODE(placed.stat().st_mode) & 0o222
    assert not [path for path in _files(root) if '.compose-' in path]
