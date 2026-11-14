"""Offline release/backup boundaries using tiny synthetic files, never real FEM."""
import json
import fcntl
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

import pytest

import backup_service as service
import release_manifest as release


def write(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return path


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path.resolve() / 'checkout'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    write(root, '.gitignore', 'artifacts/\nresults/\n.runtime/\n.env*\n')
    write(root, 'README.md', 'Original source\n')
    write(root, 'src/compact_eeg/core.py', 'VALUE = 1\n')
    write(root, 'webapp/package.json', '{"version":"0.1.2"}')
    write(root, 'webapp/package-lock.json', '{"lockfileVersion":3}')
    write(root, 'configs/runtime/manifest.json', json.dumps({
        'schema': 'eeglayoutlab-runtime-lock/1', 'platform': 'fixture-only', 'python': 'fixture'}))
    write(root, 'scripts/inspect_reception_runtime.py',
          'import json\nprint(json.dumps({"schema":"reception-runtime-digest/1","sha256":"' + 'a' * 64 + '"}))\n')
    frozen = write(root, 'data/external/model.bin', b'frozen model\x00')
    pointer = write(root, 'results/v2/current_inputs.json', '{"frozen":true}')
    rows = [{'path': str(path.relative_to(root)), 'size_bytes': path.stat().st_size,
             'sha256': release.sha256_file(path)} for path in [frozen, pointer]]
    write(root, 'data/manifest.json', json.dumps({'schema_version': 'eeglayoutlab-data-bundle/1',
        'bundle_id': 'test-bundle', 'files': rows, 'total_size_bytes': sum(row['size_bytes'] for row in rows)}))
    queue = {'version': 1, 'sequence': 1, 'maintenance': True,
             'tasks': [{'id': 'receipt', 'sequence': 1, 'status': 'queued', 'owners': ['visitor']}]}
    write(root, service.QUEUE + '/queue.json', json.dumps(queue))
    write(root, service.QUEUE + '/session-secret.json', json.dumps({'key': 'b' * 64}))
    write(root, service.RECORDS[0] + '/' + 'c' * 64 + '/cache.json', '{"original":true}')
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    return root


def output(root, name):
    return root / 'artifacts' / 'maintenance' / name


def snapshot(root, name='backup'):
    return service.backup(root, output(root, name), python=sys.executable, execute=True)


def test_release_inventory_tracks_current_bytes_additions_and_deletions(checkout):
    write(checkout, 'README.md', 'Current uncommitted source\n')
    (checkout / 'src/compact_eeg/core.py').unlink()
    write(checkout, 'src/compact_eeg/new.py', 'NEW = True\n')
    for name in ['.env.secret', 'configs/server.env', 'configs/server.env.old', 'artifacts/private.json', 'results/private.json', '.runtime/private.json']:
        write(checkout, name, 'excluded')
        subprocess.run(['git', '-C', str(checkout), 'add', '-f', name], check=True)
    value = release.release_manifest(checkout)
    names = {row['path'] for row in value['source']['files']}
    assert value['source']['dirty'] is True
    assert value['source']['revision'] is None
    assert 'src/compact_eeg/new.py' in names
    assert 'src/compact_eeg/core.py' not in names
    assert not any(name.startswith(('.env', 'artifacts/', 'results/', '.runtime/')) for name in names)
    assert not names.intersection({'configs/server.env', 'configs/server.env.old'})
    assert value['source']['inventory_sha256'] == release.digest(value['source']['files'])
    assert value['runtime']['observed'] is None
    assert value['data']['payload_verified'] is False


def test_release_uses_existing_runtime_inspection_protocol_and_verifies_data(checkout):
    value = release.release_manifest(checkout, python=sys.executable, verify_data=True)
    observed = value['runtime']['observed']
    assert observed['native_identity']['sha256'] == 'a' * 64
    assert observed['executable_sha256'] == release.sha256_file(Path(sys.executable).resolve())
    assert value['data']['payload_verified'] is True
    write(checkout, 'data/external/model.bin', 'changed')
    with pytest.raises(ValueError, match='mismatch'):
        release.release_manifest(checkout, verify_data=True)


def test_backup_preview_has_no_writes_and_execute_requires_observed_runtime(checkout):
    report = service.backup(checkout, output(checkout, 'plan'))
    assert report['mode'] == 'plan'
    assert not (checkout / 'artifacts').exists()
    assert not (checkout / service.QUEUE / 'acquiring.lock').exists()
    with pytest.raises(ValueError, match='requires --python'):
        service.backup(checkout, output(checkout, 'execute'), execute=True)


def test_roundtrip_preserves_private_queue_receipts_secret_and_record_bytes(checkout):
    write(checkout, service.QUEUE + '/access/log.jsonl', 'not included')
    write(checkout, 'results/v2/reception_forward/identity/forward_fields.npz', b'original FEM cache')
    report = snapshot(checkout)
    backup = Path(report['output'])
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700
    assert stat.S_IMODE((backup / 'payload' / service.QUEUE / 'session-secret.json').stat().st_mode) == 0o600
    names = {row['path'] for row in report['manifest']['files']}
    assert not any('access/' in name or name.endswith('.lock') or name.startswith('data/external/') for name in names)
    assert 'results/v2/current_inputs.json' not in names
    assert 'results/v2/reception_forward/identity/forward_fields.npz' in names
    assert not (checkout / service.QUEUE / 'acquiring.lock').exists()
    target = output(checkout, 'restored')
    preview = service.restore(checkout, backup, target, manifest_sha256=report['manifest_sha256'])
    assert preview['ready_to_start'] is False and not target.exists()
    service.restore(checkout, backup, target, manifest_sha256=report['manifest_sha256'], execute=True)
    for row in report['manifest']['files']:
        assert release.sha256_file(target / row['path']) == row['sha256']
    assert (target / service.QUEUE / 'queue.json').read_bytes() == (checkout / service.QUEUE / 'queue.json').read_bytes()
    assert (target / service.QUEUE / 'session-secret.json').read_bytes() == (checkout / service.QUEUE / 'session-secret.json').read_bytes()
    assert not (target / 'data/external').exists()
    assert not (target / '.runtime').exists()
    assert not (target / '.restore-incomplete').exists()
    assert (target / 'README.md').stat().st_ino != (checkout / 'README.md').stat().st_ino


@pytest.mark.parametrize('external_queue', [False, True])
def test_project_archive_survives_backup_restore_independently_of_queue_receipts(checkout, external_queue):
    queue = checkout / service.QUEUE
    if external_queue:
        external = checkout.parent / 'external-queue'
        shutil.copytree(queue, external)
        queue = external
    payloads = {
        'projects/experiment/project.json': b'{"title":"Long-term study","revision":3,"owner_hash":"private"}',
        'projects/experiment/snapshots/source.json': b'{"values":[1.42e-14,-0.00000000000001],"seed":2026}',
    }
    for name, content in payloads.items():
        write(queue, name, content)
    # No task receipt is required to preserve a saved project experiment.
    state = json.loads((queue / 'queue.json').read_bytes())
    state['tasks'] = []
    (queue / 'queue.json').write_text(json.dumps(state))
    report = service.backup(checkout, output(checkout, 'project-backup'),
                            queue_directory=queue, python=sys.executable, execute=True)
    target = output(checkout, 'project-restored')
    service.restore(checkout, Path(report['output']), target,
                    manifest_sha256=report['manifest_sha256'], execute=True)
    for name, content in payloads.items():
        restored = target / service.QUEUE / name
        assert restored.read_bytes() == content
        assert stat.S_IMODE(restored.stat().st_mode) == 0o600


def test_project_archive_symlinks_are_refused_before_backup_publication(checkout, tmp_path):
    project = checkout / service.QUEUE / 'projects'
    project.mkdir()
    (project / 'external').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='Symlink|symlink'):
        snapshot(checkout, 'unsafe-project')
    assert not output(checkout, 'unsafe-project').exists()


@pytest.mark.parametrize('change', ['live_owner', 'acquiring', 'running', 'cancelling', 'starting', 'live_worker', 'not_paused', 'bad_secret', 'bad_pid'])
def test_backup_refuses_live_ambiguous_or_unmaintained_queue(checkout, change):
    directory = checkout / service.QUEUE
    path = directory / 'queue.json'
    value = json.loads(path.read_bytes())
    if change == 'live_owner':
        write(directory, 'worker.lock', json.dumps({'pid': os.getpid()}))
    elif change == 'acquiring':
        write(directory, 'acquiring.lock', str(os.getpid()))
    elif change in ('running', 'cancelling'):
        value['tasks'][0]['status'] = change
    elif change == 'starting':
        value['tasks'][0]['starting'] = True
    elif change == 'live_worker':
        value['tasks'][0]['workerPid'] = os.getpid()
    elif change == 'not_paused':
        value['maintenance'] = False
    elif change == 'bad_secret':
        write(directory, 'session-secret.json', '{}')
    else:
        write(directory, 'worker.lock', '{"pid":0}')
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        service.backup(checkout, output(checkout, 'refused'), python=sys.executable, execute=True)
    assert not output(checkout, 'refused').exists()


def test_snapshot_holds_startup_guard_and_removes_it_after_failure(checkout, monkeypatch):
    original = service.copy_checked
    def copy(origin, destination, row):
        guard = checkout / service.QUEUE / 'acquiring.lock'
        with pytest.raises(FileExistsError):
            os.open(guard, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        original(origin, destination, row)
        raise ValueError('copy failed')
    monkeypatch.setattr(service, 'copy_checked', copy)
    with pytest.raises(ValueError, match='copy failed'):
        snapshot(checkout)
    assert not (checkout / service.QUEUE / 'acquiring.lock').exists()
    assert not output(checkout, 'backup').exists()
    assert not list(output(checkout, 'backup').parent.glob('.backup-*'))


@pytest.mark.parametrize('mutation', ['source', 'new_record', 'queue', 'data'])
def test_snapshot_detects_mutation_during_copy_without_publishing(checkout, monkeypatch, mutation):
    original = service.copy_checked
    changed = False
    def copy(origin, destination, row):
        nonlocal changed
        original(origin, destination, row)
        if not changed:
            changed = True
            path = {'source': 'README.md', 'new_record': service.RECORDS[0] + '/new.json',
                    'queue': service.QUEUE + '/queue.json', 'data': 'data/external/model.bin'}[mutation]
            if mutation == 'queue':
                value = json.loads((checkout / path).read_bytes()); value['sequence'] += 1
                write(checkout, path, json.dumps(value))
            else:
                write(checkout, path, 'concurrent edit')
    monkeypatch.setattr(service, 'copy_checked', copy)
    with pytest.raises(ValueError):
        snapshot(checkout)
    assert not output(checkout, 'backup').exists()
    assert not (checkout / service.QUEUE / 'acquiring.lock').exists()


@pytest.mark.parametrize('mutation', ['corrupt_payload', 'extra_file', 'empty_directory', 'symlink', 'manifest', 'traversal', 'duplicate'])
def test_restore_rejects_invalid_snapshot_before_creating_target(checkout, mutation):
    report = snapshot(checkout)
    backup = Path(report['output']); expected = report['manifest_sha256']
    if mutation == 'corrupt_payload':
        write(backup, 'payload/README.md', 'corrupt')
    elif mutation == 'extra_file':
        write(backup, 'extra.json', '{}')
    elif mutation == 'empty_directory':
        (backup / 'empty').mkdir()
    elif mutation == 'symlink':
        (backup / 'payload/README.md').unlink()
        (backup / 'payload/README.md').symlink_to(checkout / 'README.md')
    elif mutation == 'manifest':
        (backup / service.MANIFEST).write_text('{}')
    else:
        manifest = json.loads((backup / service.MANIFEST).read_bytes())
        if mutation == 'traversal':
            manifest['files'][0]['path'] = '../escape'
        else:
            manifest['files'].append(manifest['files'][0])
        (backup / service.MANIFEST).write_bytes(release.encoded(manifest))
        expected = release.digest(manifest)
    target = output(checkout, 'restored')
    with pytest.raises(ValueError):
        service.restore(checkout, backup, target, manifest_sha256=expected, execute=True)
    assert not target.exists()


def test_restore_detects_snapshot_changed_during_copy(checkout, monkeypatch):
    report = snapshot(checkout)
    backup = Path(report['output'])
    original = service.copy_checked
    def copy(origin, destination, row):
        original(origin, destination, row)
        write(backup, 'late-entry', 'added during restore')
    monkeypatch.setattr(service, 'copy_checked', copy)
    with pytest.raises(ValueError, match='extra'):
        service.restore(checkout, backup, output(checkout, 'restored'), manifest_sha256=report['manifest_sha256'], execute=True)
    assert not output(checkout, 'restored').exists()


def test_existing_output_live_root_and_symlink_ancestors_are_never_overwritten(checkout):
    report = snapshot(checkout)
    existing = output(checkout, 'existing'); existing.mkdir()
    for target in (existing, checkout, checkout / 'results/new', checkout / 'artifacts'):
        with pytest.raises(ValueError):
            service.restore(checkout, report['output'], target, manifest_sha256=report['manifest_sha256'], execute=True)
    (checkout / 'artifacts/link').symlink_to(checkout / 'results', target_is_directory=True)
    with pytest.raises(ValueError):
        service.restore(checkout, report['output'], checkout / 'artifacts/link/new', manifest_sha256=report['manifest_sha256'], execute=True)
    assert existing.exists() and not list(existing.iterdir())


def test_backup_records_distinct_host_and_scientific_checkouts(checkout):
    science = output(checkout, 'science')
    shutil.copytree(checkout, science, ignore=shutil.ignore_patterns('.git', 'artifacts'))
    write(checkout, 'webapp/new-host.mjs', 'export const current = true;')
    write(checkout, 'configs/deploy/server.env.example', 'EEG_PORT=4002\n')
    queue = science / 'separate-queue'
    shutil.move(science / service.QUEUE, queue)
    report = service.backup(science, output(checkout, 'backup'), source_root=checkout,
                            queue_directory=queue, python=sys.executable, execute=True)
    assert report['manifest']['release']['source_root'] == str(checkout)
    assert report['manifest']['release']['repository_root'] == str(science)
    assert (Path(report['output']) / 'payload/webapp/new-host.mjs').is_file()
    assert (Path(report['output']) / 'payload/configs/deploy/server.env.example').is_file()
    write(science, 'src/compact_eeg/core.py', 'DIFFERENT = True\n')
    with pytest.raises(ValueError, match='mismatch'):
        service.backup(science, output(checkout, 'different'), source_root=checkout, queue_directory=queue)


def test_release_preserves_invoked_python_symlink_in_runtime_identity(checkout):
    python = checkout / '.runtime/bin/python'
    python.parent.mkdir(parents=True)
    python.symlink_to(Path(sys.executable).resolve())
    write(checkout, 'scripts/inspect_reception_runtime.py',
          'import hashlib,json,sys\nprint(json.dumps({"schema":"reception-runtime-digest/1",'
          '"sha256":hashlib.sha256(sys.executable.encode()).hexdigest()}))\n')
    value = release.release_manifest(checkout, python=python)
    assert value['runtime']['observed']['python'] == str(python)
    assert value['runtime']['observed']['native_identity']['sha256'] == release.hashlib.sha256(str(python).encode()).hexdigest()


def test_source_changes_during_runtime_inspection_reject_release(checkout, monkeypatch):
    def changed(root, python):
        write(root, 'new-source.py', 'concurrent source')
        return None
    monkeypatch.setattr(release, 'observed_runtime', changed)
    with pytest.raises(ValueError, match='inventory changed'):
        release.release_manifest(checkout)


@pytest.mark.parametrize('field', ['source', 'scientific_source', 'data', 'runtime'])
def test_restore_cross_checks_manifest_identities_against_payload(checkout, field):
    report = snapshot(checkout)
    path = Path(report['output']) / service.MANIFEST
    manifest = json.loads(path.read_bytes())
    manifest['release'][field] = {}
    path.write_bytes(release.encoded(manifest))
    with pytest.raises(ValueError):
        service.restore(checkout, report['output'], output(checkout, 'restore'),
                        manifest_sha256=release.digest(manifest), execute=True)
    assert not output(checkout, 'restore').exists()


def test_publication_never_overwrites_file_created_concurrently(checkout, monkeypatch):
    report = snapshot(checkout)
    destination = output(checkout, 'restore')
    original = os.link
    def collide(source, target, **kwargs):
        if Path(target) == destination / 'README.md':
            Path(target).write_text('concurrent user file')
        return original(source, target, **kwargs)
    monkeypatch.setattr(service.os, 'link', collide)
    with pytest.raises(FileExistsError):
        service.restore(checkout, report['output'], destination,
                        manifest_sha256=report['manifest_sha256'], execute=True)
    assert (destination / 'README.md').read_text() == 'concurrent user file'
    assert (destination / '.restore-incomplete').exists()


def test_record_directory_symlinks_and_existing_snapshot_are_rejected(checkout, tmp_path):
    report = snapshot(checkout)
    with pytest.raises(ValueError, match='already exists'):
        snapshot(checkout)
    folder = checkout / service.RECORDS[0]
    shutil.rmtree(folder)
    folder.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='Symlink'):
        service.backup(checkout, output(checkout, 'other'))
    assert (Path(report['output']) / service.MANIFEST).is_file()


def test_native_writer_lock_blocks_backup_and_is_held_during_copy(checkout, monkeypatch):
    path = write(checkout, service.NATIVE_LOCK, '')
    with path.open('rb') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='native reception writer'):
            service.backup(checkout, output(checkout, 'blocked'))
        fcntl.flock(owner, fcntl.LOCK_UN)
    original = service.copy_checked
    def copy(origin, destination, row):
        with path.open('rb') as competing:
            with pytest.raises(BlockingIOError):
                fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original(origin, destination, row)
    monkeypatch.setattr(service, 'copy_checked', copy)
    report = snapshot(checkout)
    assert service.NATIVE_LOCK not in {row['path'] for row in report['manifest']['files']}


@pytest.mark.parametrize('shim', ['source_reception.py', 'source_reception_v2.py', 'inspect_ernie_cortical_forward.py', 'export_history_coordinates.py'])
def test_scientific_checkout_shims_must_match_the_selected_host_version(checkout, shim):
    write(checkout, 'scripts/' + shim, 'ORIGINAL = True\n')
    science = output(checkout, 'science')
    shutil.copytree(checkout, science, ignore=shutil.ignore_patterns('.git', 'artifacts'))
    write(science, 'scripts/' + shim, 'CHANGED = True\n')
    with pytest.raises(ValueError, match='mismatch'):
        release.release_manifest(checkout, repository_root=science)


def test_release_scientific_inventory_covers_current_server_python_dependencies():
    root = Path(__file__).resolve().parents[1]
    paths = set()
    for file in (root / 'webapp/server').rglob('*.mjs'):
        paths.update(re.findall(r"['\"](scripts/[^'\"]+\.py)['\"]", file.read_text()))
    assert paths
    assert paths <= release.SCIENTIFIC_SCRIPTS
