"""Small isolated fixtures for QA workspace preparation; no scientific solver."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

SPEC = importlib.util.spec_from_file_location(
    "verification_workspace", Path(__file__).resolve().parents[1] / "scripts/prepare_verification_workspace.py")
workspace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workspace)


def write(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.fixture
def source(tmp_path):
    root = tmp_path.resolve() / "checkout"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    write(root, '.gitignore', b'artifacts/\n.runtime/\nwebapp/node_modules/\nwebapp/dist/\n')
    write(root, 'README.md', b'Current source\n')
    write(root, 'src/compact_eeg/core.py', b'ANSWER = 1\n')
    write(root, 'webapp/server/start.mjs', b'export const server = 1;\n')
    write(root, 'webapp/public/models/example.bin', b'display bytes\x00')
    payload = []
    for name, content in [('data/external/model.bin', b'frozen mesh'),
                          ('results/v2/current_inputs.json', b'{"fixed":true}'),
                          ('data/SOURCES.md', b'attribution')]:
        file = write(root, name, content)
        payload.append({'path': name, 'size_bytes': len(content), 'sha256': workspace.sha256_file(file)})
    manifest = {'schema_version': 'eeglayoutlab-data-bundle/1', 'bundle_id': 'test-data',
                'files': payload, 'total_size_bytes': sum(row['size_bytes'] for row in payload)}
    write(root, 'data/manifest.json', json.dumps(manifest).encode())
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    write(root, 'src/compact_eeg/new.py', b'NEW = True\n')
    return root


def output(source, name='run-1'):
    return source / 'artifacts' / 'verification' / name


def runtime(source):
    root = source / '.runtime' / 'original'
    write(root, 'bin/python3.11', b'fake interpreter')
    (root / 'bin/python').symlink_to('python3.11')
    write(root, 'conda-meta/python.json', b'{"name":"python"}')
    return root


def test_dry_run_verifies_current_source_and_data_without_creating_destination(source):
    target = output(source)
    report = workspace.prepare(source, target)
    assert report['mode'] == 'plan'
    assert not (source / 'artifacts').exists()
    assert 'src/compact_eeg/new.py' in {row['path'] for row in report['sources']}
    assert len(report['data']) == 3


def test_copy_includes_current_edits_and_new_sources_but_not_deleted_files_or_private_history(source):
    write(source, 'README.md', b'Uncommitted edit\n')
    (source / 'src/compact_eeg/core.py').unlink()
    for name in ['results/v2/history/private.json', 'releases/old.zip', '.env.secret', 'webapp/node_modules/private.txt']:
        write(source, name, b'not part of QA')
    subprocess.run(['git', '-C', str(source), 'add', '-f', 'results/v2/history/private.json', '.env.secret'], check=True)
    target = output(source)
    report = workspace.prepare(source, target, execute=True)
    assert (target / 'README.md').read_bytes() == b'Uncommitted edit\n'
    assert (target / 'src/compact_eeg/new.py').exists()
    assert not (target / 'src/compact_eeg/core.py').exists()
    assert not (target / '.git').exists()
    for name in ['results/v2/history/private.json', 'releases', '.env.secret', 'webapp/node_modules']:
        assert not (target / name).exists()
    assert (target / 'webapp/public/models/example.bin').read_bytes() == b'display bytes\x00'
    stored = json.loads((target / workspace.REPORT).read_text())
    assert stored == report
    assert {str(p.relative_to(target)) for p in (target / 'results').rglob('*') if p.is_file()} == {'results/v2/current_inputs.json'}
    for row in report['sources'] + report['data']:
        assert workspace.sha256_file(target / row['path']) == row['sha256']
    assert (source / 'README.md').stat().st_ino != (target / 'README.md').stat().st_ino
    (target / 'README.md').write_text('QA edit')
    assert (source / 'README.md').read_bytes() == b'Uncommitted edit\n'


@pytest.mark.parametrize('relative', ['', 'results/new', '.runtime/new', 'releases/new', 'artifacts'])
def test_output_cannot_overlap_repository_or_user_data(source, relative):
    with pytest.raises(workspace.WorkspaceError):
        workspace.prepare(source, source / relative)


def test_existing_output_and_symlink_ancestors_are_rejected(source, tmp_path):
    target = output(source)
    write(target, 'personal.txt', b'keep this')
    with pytest.raises(workspace.WorkspaceError, match='already exists'):
        workspace.prepare(source, target, execute=True)
    assert (target / 'personal.txt').read_bytes() == b'keep this'
    (source / 'artifacts/link').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(workspace.WorkspaceError):
        workspace.prepare(source, source / 'artifacts/link/new', execute=True)


def test_bad_frozen_data_fails_before_any_copy(source):
    write(source, 'data/external/model.bin', b'corruption')
    with pytest.raises(ValueError, match='mismatch'):
        workspace.prepare(source, output(source), execute=True)
    assert not (source / 'artifacts').exists()


def test_source_symlink_cannot_include_external_files(source, tmp_path):
    outside = write(tmp_path, 'personal.txt', b'private')
    (source / 'src/compact_eeg/link.py').symlink_to(outside)
    with pytest.raises(ValueError, match='Symlink'):
        workspace.prepare(source, output(source), execute=True)
    assert not output(source).exists()


def test_environment_files_are_excluded_even_if_tracked_but_templates_remain(source):
    private = ['configs/deploy/server.env', 'configs/deploy/server.env.old', 'configs/.env.local']
    for name in private + ['configs/deploy/server.env.example', 'configs/.env.example']:
        write(source, name, b'fixture configuration')
        subprocess.run(['git', '-C', str(source), 'add', '-f', name], check=True)
    names = {row['path'] for row in workspace.current_sources(source)}
    assert not names.intersection(private)
    assert {'configs/deploy/server.env.example', 'configs/.env.example'} <= names


def test_runtime_copy_preserves_internal_links_without_sharing_mutable_files(source):
    environment = runtime(source)
    (environment / 'bin/absolute-python').symlink_to(environment / 'bin/python3.11')
    target = output(source)
    report = workspace.prepare(source, target, runtime=environment, execute=True)
    copied = target / workspace.RUNTIME
    assert report['runtime_source'] == str(environment)
    assert report['runtime_copy']['symlinks'] == 2
    assert (copied / 'bin/python').readlink() == Path('python3.11')
    assert not (copied / 'bin/absolute-python').readlink().is_absolute()
    assert (copied / 'bin/absolute-python').resolve() == copied / 'bin/python3.11'
    (copied / 'bin/python3.11').write_bytes(b'changed QA runtime')
    assert (environment / 'bin/python3.11').read_bytes() == b'fake interpreter'


def test_runtime_external_link_is_rejected_before_copy(source, tmp_path):
    environment = runtime(source)
    (environment / 'external').symlink_to(write(tmp_path, 'external.bin', b'external'))
    with pytest.raises(workspace.WorkspaceError, match='escapes'):
        workspace.prepare(source, output(source), runtime=environment, execute=True)
    assert not output(source).exists()


def test_node_dependencies_are_explicit_qa_symlink_and_dist_is_an_independent_copy(source):
    write(source, 'webapp/node_modules/pkg/index.js', b'library')
    write(source, 'webapp/dist/server.js', b'built code')
    target = output(source)
    report = workspace.prepare(source, target, node_modules=True, dist=True, execute=True)
    assert (target / 'webapp/node_modules').is_symlink()
    assert (target / 'webapp/node_modules').resolve() == source / 'webapp/node_modules'
    assert report['node_modules']['mode'] == 'qa_symlink'
    (target / 'webapp/dist/server.js').write_bytes(b'new build')
    assert (source / 'webapp/dist/server.js').read_bytes() == b'built code'


def test_changed_source_during_execution_fails_without_publishing_workspace(source, monkeypatch):
    original = workspace.copy_verified
    def changed(root, destination, record):
        if record['path'] == 'README.md':
            write(root, 'README.md', b'concurrent edit')
        return original(root, destination, record)
    monkeypatch.setattr(workspace, 'copy_verified', changed)
    with pytest.raises(workspace.WorkspaceError, match='changed after planning'):
        workspace.prepare(source, output(source), execute=True)
    assert not output(source).exists()
    assert not list((source / 'artifacts/verification').glob('.verification-*'))
