"""The workspace and the ``eeglayoutlab serve`` command (phase 2 slice 2; design 0001, decisions 6, U3 and U6):
marker, lock, runtime file, instance reuse, and the real command in a subprocess."""
from __future__ import annotations

import errno
import fcntl
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time

import pytest

from eeglayoutlab.cli.main import choose_workspace
from eeglayoutlab.schemas import jsjson
from eeglayoutlab.server import workspace as workspace_module
from eeglayoutlab.server.workspace import (
    LOCAL_OWNER, MARKER, RUNTIME_SCHEMA, STATE, Workspace, WorkspaceError, WorkspaceInUse, is_workspace, open_url,
    read_runtime, write_open_page,
)

from .installed_support import MAIN, fake_prefix, needs_non_root, read_only, tree_state
from .key_parity_support import REQUIRED

ROOT = Path(__file__).resolve().parents[2]
ISO = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z')
UUID4 = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def opened(tmp_path):
    workspace = Workspace.open(str(tmp_path / 'w'))
    yield workspace
    workspace.close()


def test_a_new_workspace_gets_its_marker_and_private_state(opened):
    path = Path(opened.path)
    marker = (path / MARKER).read_text(encoding='utf-8')
    value = jsjson.parse(marker)
    assert list(value) == ['schema', 'id', 'created_at'] and value['schema'] == 'eeglayoutlab-workspace/1'
    assert UUID4.fullmatch(value['id']) and ISO.fullmatch(value['created_at'])
    assert marker == jsjson.stringify(value) + '\n' and opened.marker == value
    assert mode(path / STATE) == 0o700
    assert (path / STATE / '.gitignore').read_text(encoding='utf-8') == '*\n'
    assert (path / STATE / 'lock').is_file() and is_workspace(str(path))


def test_the_marker_is_kept_when_the_workspace_is_opened_again(tmp_path):
    first = Workspace.open(str(tmp_path / 'w'))
    marker = first.marker
    first.close()
    second = Workspace.open(str(tmp_path / 'w'))
    assert second.marker == marker
    second.close()


def test_the_runtime_file_is_private_atomic_and_removed_only_when_ours(opened):
    runtime = opened.write_runtime(41234, 'a' * 64, '/root')
    path = Path(opened.runtime_path)
    assert mode(path) == 0o600
    assert list(runtime) == ['schema', 'pid', 'port', 'token', 'root', 'started_at']
    assert runtime['schema'] == RUNTIME_SCHEMA and runtime['pid'] == os.getpid()
    assert ISO.fullmatch(runtime['started_at'])
    assert jsjson.parse(path.read_text(encoding='utf-8')) == runtime and read_runtime(opened.path) == runtime
    assert [entry.name for entry in path.parent.iterdir() if entry.name.endswith('.tmp')] == []
    assert open_url(runtime) == f'http://127.0.0.1:41234/open?token={"a" * 64}'
    # Another process's file (a newer instance after this one lost the lock) is not removed.
    path.write_text(jsjson.stringify({**runtime, 'token': 'b' * 64}), encoding='utf-8')
    assert opened.remove_runtime() is False and path.exists()
    path.write_text(jsjson.stringify(runtime), encoding='utf-8')
    assert opened.remove_runtime() is True and not path.exists()


def private_state(path: Path) -> Path:
    """``W/.eeglayoutlab`` as the service makes it (mode 0700)."""
    (path / STATE).mkdir(parents=True)
    (path / STATE).chmod(0o700)
    return path / STATE


def write_private(path: Path, text: str) -> None:
    path.write_text(text, encoding='utf-8')
    path.chmod(0o600)


def test_the_open_page_is_private_and_redirects_to_the_launch_url(opened):
    url = open_url({'port': 41234, 'token': 'f' * 64})
    # The page exists only with the runtime file: not before it is written, nor once it is removed.
    assert opened.write_open_page(url) is None
    opened.write_runtime(41234, 'f' * 64, '/root')
    page = Path(opened.write_open_page(url))
    assert page == Path(opened.path) / STATE / 'open.html' and mode(page) == 0o600
    text = page.read_text(encoding='utf-8')
    assert f'<meta http-equiv="refresh" content="0;url={url}">' in text and f'<a href="{url}">' in text
    # The same page for the instance-reuse path, which does not hold the workspace.
    assert write_open_page(opened.path, url) == str(page) and page.read_text(encoding='utf-8') == text
    assert opened.remove_runtime() is True and not page.exists()
    assert opened.write_open_page(url) is None and not page.exists()


def test_no_open_page_is_written_after_close(tmp_path):
    # The browser thread may still run while the main thread closes the workspace: it writes nothing then, and
    # never through the closed descriptor of the state directory.
    workspace = Workspace.open(str(tmp_path / 'w'))
    workspace.write_runtime(41234, 'f' * 64, '/root')
    workspace.close()
    assert workspace.write_open_page(open_url({'port': 41234, 'token': 'f' * 64})) is None
    assert sorted(os.listdir(tmp_path / 'w' / STATE)) == ['.gitignore', 'lock']


def test_a_second_open_finds_the_running_instance(opened, tmp_path):
    runtime = opened.write_runtime(41234, 'c' * 64, '/root')
    with pytest.raises(WorkspaceInUse) as caught:
        Workspace.open(opened.path, wait=0)
    assert caught.value.runtime == runtime and caught.value.path == opened.path


def test_a_locked_workspace_without_a_runtime_file_waits_then_reports_it(opened):
    started = time.monotonic()
    with pytest.raises(WorkspaceInUse) as caught:
        Workspace.open(opened.path, wait=0.3)
    assert caught.value.runtime is None and time.monotonic() - started >= 0.3


def test_a_lock_released_while_waiting_is_taken(opened):
    # The holder stops (or fails to start) without a runtime file: the waiting start takes the workspace.
    path = opened.path
    timer = threading.Timer(0.3, opened.close)
    timer.start()
    try:
        started = time.monotonic()
        second = Workspace.open(path, wait=5)
    finally:
        timer.join()
    assert time.monotonic() - started < 3
    second.close()


@pytest.mark.parametrize('content', [
    'not json', '{}', '{"schema":"eeglayoutlab-runtime/2","pid":1,"port":1,"token":"' + 'a' * 64 + '"}',
    '{"schema":"eeglayoutlab-runtime/1","pid":true,"port":1,"token":"' + 'a' * 64 + '"}',
    '{"schema":"eeglayoutlab-runtime/1","pid":1,"port":70000,"token":"' + 'a' * 64 + '"}',
    '{"schema":"eeglayoutlab-runtime/1","pid":1,"port":1,"token":"x&y=1"}',
])
def test_an_invalid_runtime_file_is_not_followed(tmp_path, content):
    write_private(private_state(tmp_path) / 'runtime.json', content)
    assert read_runtime(str(tmp_path)) is None


def test_the_runtime_file_is_read_only_as_a_private_file_of_this_user(tmp_path):
    state = private_state(tmp_path)
    runtime = {'schema': RUNTIME_SCHEMA, 'pid': os.getpid(), 'port': 41234, 'token': 'a' * 64}
    target = state / 'runtime.json'
    write_private(target, jsjson.stringify(runtime))
    assert read_runtime(str(tmp_path)) == runtime
    target.chmod(0o644)
    assert read_runtime(str(tmp_path)) is None
    target.chmod(0o600)
    os.link(target, tmp_path / 'second-name.json')
    assert read_runtime(str(tmp_path)) is None
    (tmp_path / 'second-name.json').unlink()
    state.chmod(0o755)
    assert read_runtime(str(tmp_path)) is None
    state.chmod(0o700)
    # A link, to a valid file elsewhere.
    elsewhere = tmp_path / 'elsewhere.json'
    target.rename(elsewhere)
    target.symlink_to(elsewhere)
    assert read_runtime(str(tmp_path)) is None
    # A FIFO does not block the reader.
    target.unlink()
    os.mkfifo(target, 0o600)
    assert read_runtime(str(tmp_path)) is None
    # A state directory that is a link.
    target.unlink()
    (tmp_path / 'w').mkdir()
    (tmp_path / 'w' / STATE).symlink_to(state, target_is_directory=True)
    write_private(target, jsjson.stringify(runtime))
    assert read_runtime(str(tmp_path)) == runtime and read_runtime(str(tmp_path / 'w')) is None


def test_an_open_state_directory_is_made_private(tmp_path):
    path = tmp_path / 'w'
    (path / STATE).mkdir(parents=True)
    (path / STATE).chmod(0o777)
    workspace = Workspace.open(str(path))
    try:
        assert mode(path / STATE) == 0o700
    finally:
        workspace.close()


def test_links_in_the_state_directory_are_not_followed(tmp_path):
    # Another user who could write W/.eeglayoutlab before it was made private left links where the service
    # writes; the files they point to stay as they were.
    path = tmp_path / 'w'
    state = path / STATE
    state.mkdir(parents=True)
    state.chmod(0o777)
    victims = {}
    for name in (f'runtime.json.{os.getpid()}.tmp', 'open.html.tmp'):
        victim = tmp_path / f'victim-{len(victims)}'
        victim.write_text('mine', encoding='utf-8')
        victim.chmod(0o644)
        (state / name).symlink_to(victim)
        victims[name] = victim
    workspace = Workspace.open(str(path))
    try:
        workspace.write_runtime(41234, 'a' * 64, '/root')
        workspace.write_open_page(open_url({'port': 41234, 'token': 'a' * 64}))
        for victim in victims.values():
            assert victim.read_text(encoding='utf-8') == 'mine' and mode(victim) == 0o644
        assert not (state / 'runtime.json').is_symlink() and mode(state / 'runtime.json') == 0o600
        assert read_runtime(str(path))['token'] == 'a' * 64
    finally:
        workspace.close()


def test_a_state_directory_that_is_a_link_is_refused(tmp_path):
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (tmp_path / 'w').mkdir()
    (tmp_path / 'w' / STATE).symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(WorkspaceError, match='not a directory'):
        Workspace.open(str(tmp_path / 'w'))
    assert list(elsewhere.iterdir()) == []


def test_a_state_directory_of_another_user_is_refused(tmp_path, monkeypatch):
    (tmp_path / 'w' / STATE).mkdir(parents=True)
    monkeypatch.setattr(os, 'geteuid', lambda: os.getuid() + 1)
    with pytest.raises(WorkspaceError, match='another user'):
        Workspace.open(str(tmp_path / 'w'))
    monkeypatch.undo()
    Workspace.open(str(tmp_path / 'w')).close()


def test_a_lock_that_is_a_link_is_refused(tmp_path):
    state = private_state(tmp_path / 'w')
    (tmp_path / 'other-lock').write_text('', encoding='utf-8')
    (state / 'lock').symlink_to(tmp_path / 'other-lock')
    with pytest.raises(WorkspaceError):
        Workspace.open(str(tmp_path / 'w'))


def test_a_runtime_file_of_an_exited_process_is_stale_and_replaced(tmp_path):
    child = subprocess.run([sys.executable, '-c', 'import os; print(os.getpid())'], capture_output=True, text=True)
    dead = int(child.stdout)
    path = tmp_path / 'w'
    runtime = private_state(path) / 'runtime.json'
    content = {'schema': RUNTIME_SCHEMA, 'pid': dead, 'port': 1, 'token': 'd' * 64}
    write_private(runtime, jsjson.stringify({**content, 'pid': os.getpid()}))
    assert read_runtime(str(path)) is not None
    write_private(runtime, jsjson.stringify(content))
    assert read_runtime(str(path)) is None
    workspace = Workspace.open(str(path))
    assert not runtime.exists()
    workspace.close()


def test_a_file_system_that_keeps_the_mode_open_is_refused(tmp_path, monkeypatch, capsys):
    # FAT, exFAT, NTFS and SMB mounts accept chmod but keep the mode the mount gives (0755 and 0644 under umask
    # 022). The token is not written there, and the person is told why, instead of a reuse that never works.
    from eeglayoutlab.cli import main as cli

    path = tmp_path / 'w'
    (path / STATE).mkdir(parents=True)
    (path / STATE).chmod(0o755)
    monkeypatch.setattr(os, 'fchmod', lambda fd, mode: None)
    with pytest.raises(WorkspaceError, match='cannot be made private on this file system .* local disk'):
        Workspace.open(str(path))
    monkeypatch.setattr(cli.importlib.util, 'find_spec', lambda name: object())
    monkeypatch.setattr(cli, '_run', lambda *args: pytest.fail('the service started'))
    assert cli.main(['serve', str(path), '--root', str(tmp_path), '--no-browser']) == 1
    assert f'{path / STATE} cannot be made private' in capsys.readouterr().err
    assert os.listdir(path / STATE) == []
    # A private directory whose files keep 0644: the runtime file is refused before the token goes in.
    monkeypatch.undo()
    workspace = Workspace.open(str(path))
    try:
        fchmod = os.fchmod
        monkeypatch.setattr(os, 'fchmod', lambda fd, mode: fchmod(fd, 0o644))
        with pytest.raises(WorkspaceError, match='runtime.json cannot be made private'):
            workspace.write_runtime(41234, 'a' * 64, '/root')
        assert sorted(os.listdir(path / STATE)) == ['.gitignore', 'lock']
    finally:
        monkeypatch.undo()
        workspace.close()


def test_a_file_system_without_locks_is_refused(tmp_path, monkeypatch):
    def no_locks(fd, operation):
        raise OSError(errno.ENOLCK, 'No locks available')

    monkeypatch.setattr(workspace_module.fcntl, 'flock', no_locks)
    with pytest.raises(WorkspaceError, match='local disk'):
        Workspace.open(str(tmp_path / 'w'))
    monkeypatch.undo()
    # The descriptor was closed: the workspace opens once locks work.
    Workspace.open(str(tmp_path / 'w')).close()


@pytest.mark.parametrize('marker', [
    '', 'null', '{"schema":"other/1","id":"x","created_at":"y"}', '{"schema":"eeglayoutlab-workspace/1"}',
])
def test_an_invalid_marker_is_refused_and_the_lock_released(tmp_path, marker):
    path = tmp_path / 'w'
    path.mkdir()
    (path / MARKER).write_text(marker, encoding='utf-8')
    with pytest.raises(WorkspaceError, match='marker'):
        Workspace.open(str(path))
    fd = os.open(path / STATE / 'lock', os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)


def test_a_file_is_not_a_workspace(tmp_path):
    (tmp_path / 'file').write_text('x', encoding='utf-8')
    with pytest.raises(WorkspaceError, match='not a directory'):
        Workspace.open(str(tmp_path / 'file'))


def test_the_local_user_context(opened):
    context = opened.user_context('/srv/root')
    assert context.owner == LOCAL_OWNER == hashlib.sha256(b'eeglayoutlab-local-user/1').hexdigest()
    assert re.fullmatch(r'[0-9a-f]{64}', context.owner)
    assert context.workspace == opened.path and context.records_root == '/srv/root'
    assert os.path.isabs(context.data_dir) and 'eeglayoutlab' in context.data_dir.lower()
    assert not os.path.exists(context.data_dir) or os.path.isdir(context.data_dir)


# --- Choosing the workspace (decision U3) ---------------------------------------------------------------------

def never(prompt):
    raise AssertionError('must not ask')


def test_an_explicit_workspace_is_taken_as_given(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert choose_workspace('study', str(tmp_path), False, never) == str(tmp_path / 'study')
    assert choose_workspace(str(tmp_path / 'x'), '/', False, never) == str(tmp_path / 'x')


def test_the_current_directory_when_it_is_a_workspace_or_empty(tmp_path):
    Workspace.open(str(tmp_path / 'w')).close()
    assert choose_workspace(None, str(tmp_path / 'w'), False, never) == str(tmp_path / 'w')
    (tmp_path / 'empty').mkdir()
    assert choose_workspace(None, str(tmp_path / 'empty'), True, never) == str(tmp_path / 'empty')


def test_a_non_empty_directory_needs_confirmation_or_a_path(tmp_path):
    (tmp_path / 'notes.txt').write_text('x', encoding='utf-8')
    asked = []
    assert choose_workspace(None, str(tmp_path), True, lambda prompt: asked.append(prompt) or 'y') == str(tmp_path)
    assert str(tmp_path) in asked[0]
    for answer in ('', 'n', 'no', 'maybe'):
        assert choose_workspace(None, str(tmp_path), True, lambda prompt: answer) is None
    # Not interactive: a path is required, also for an empty directory.
    for directory in (tmp_path, tmp_path / 'empty'):
        directory.mkdir(exist_ok=True)
        with pytest.raises(WorkspaceError, match='serve <directory>'):
            choose_workspace(None, str(directory), False, never)


# --- The command ------------------------------------------------------------------------------------------------

needs_service = pytest.mark.skipif(
    not REQUIRED and not all(importlib.util.find_spec(name) for name in ('fastapi', 'uvicorn', 'httpx')),
    reason='the service extra and httpx are required to run the command')


def command(*args: str) -> list[str]:
    return [sys.executable, '-m', 'eeglayoutlab.cli.main', 'serve', *args]


def environment() -> dict[str, str]:
    env = {name: value for name, value in os.environ.items() if not name.startswith('EEG_')}
    env['PYTHONPATH'] = os.pathsep.join(filter(None, [str(ROOT / 'src'), env.get('PYTHONPATH')]))
    return env


def wait_for_runtime(workspace: Path, process: subprocess.Popen, previous: str | None = None) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        runtime = read_runtime(str(workspace))
        if runtime is not None and runtime['token'] != previous:
            return runtime
        if process.poll() is not None:
            raise AssertionError(f'serve exited with {process.returncode}: {process.stderr.read()}')
        time.sleep(0.05)
    raise AssertionError('serve did not write its runtime file')


def stop(process: subprocess.Popen, number: int) -> tuple[int, str, str]:
    process.send_signal(number)
    try:
        out, err = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        out, err = process.communicate()
    return process.returncode, out, err


@needs_service
def test_serve_runs_and_a_second_serve_opens_the_running_instance(tmp_path):
    import httpx

    from .service_support import static_export, synthetic_root

    root = synthetic_root(tmp_path / 'root')
    static = static_export(tmp_path / 'static')
    workspace = tmp_path / 'workspace'
    args = command(str(workspace), '--root', str(root), '--static', str(static), '--no-browser')
    first = subprocess.Popen(args, cwd=tmp_path, env=environment(), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        runtime = wait_for_runtime(workspace, first)
        assert runtime['root'] == str(root) and runtime['pid'] == first.pid
        assert mode(workspace / STATE / 'runtime.json') == 0o600 and mode(workspace / STATE) == 0o700
        base = f'http://127.0.0.1:{runtime["port"]}'
        with httpx.Client(base_url=base, timeout=10) as client:
            assert client.get('/api/local-compute/health').status_code == 401
            opened = client.get(f'/open?token={runtime["token"]}')
            assert opened.status_code == 303 and opened.headers['location'] == '/'
            assert opened.headers['set-cookie'].startswith(f'eeglayoutlab-{runtime["port"]}=')
            health = client.get('/api/local-compute/health')
            assert health.status_code == 200 and health.headers['x-eeg-api-version'] == '1'
            assert health.json()['available'] is True and health.json()['local_only'] is True
            assert 'server' not in health.headers
            assert client.get('/design').text == '<!doctype html><title>design</title>'
            # The guard over a real socket: a foreign Host or Origin, and a write without the token.
            assert client.get('/api/local-compute/health', headers={'host': 'example.org'}).status_code == 403
            assert client.get('/design', headers={'origin': 'http://evil.example'}).status_code == 403
            rejected = client.post('/api/local-compute/jobs')
            assert rejected.status_code == 403 and rejected.json()['code'] == 'request_forbidden'
            # Forwarding headers are not trusted.
            assert client.get('/api/local-compute/health', headers={'x-forwarded-for': '10.0.0.1'}).status_code == 200
        second = subprocess.run(args, cwd=tmp_path, env=environment(), stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=60)
        assert second.returncode == 0, second.stderr
        assert open_url(runtime) in second.stdout
        assert first.poll() is None and read_runtime(str(workspace)) == runtime
        code, out, err = stop(first, signal.SIGTERM)
        assert code == 0, err
        assert f'EEG Layout Lab: {open_url(runtime)}' in out
        assert not (workspace / STATE / 'runtime.json').exists()
    finally:
        if first.poll() is None:
            first.kill()
            first.communicate()

    # Decision U6: a new port and a new token at every start; SIGINT stops it as SIGTERM does.
    third = subprocess.Popen(args, cwd=tmp_path, env=environment(), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        renewed = wait_for_runtime(workspace, third, previous=runtime['token'])
        assert renewed['token'] != runtime['token'] and renewed['pid'] == third.pid
        with httpx.Client(base_url=f'http://127.0.0.1:{renewed["port"]}', timeout=10) as client:
            assert client.get(f'/open?token={runtime["token"]}').status_code == 401
            assert client.get(f'/open?token={renewed["token"]}').status_code == 303
        code, _, err = stop(third, signal.SIGINT)
        assert code == 0, err
        assert not (workspace / STATE / 'runtime.json').exists()
    finally:
        if third.poll() is None:
            third.kill()
            third.communicate()


@needs_service
def test_serve_answers_while_the_browser_runs_and_hides_the_token_from_it(tmp_path):
    # A launcher that waits for its browser (a text browser, a BROWSER command) runs beside the service, which
    # answers meanwhile; the browser's command line names the open page, not the launch URL.
    import httpx

    from .service_support import static_export, synthetic_root

    root = synthetic_root(tmp_path / 'root')
    static = static_export(tmp_path / 'static')
    workspace = tmp_path / 'workspace'
    log = tmp_path / 'browser'
    browser = tmp_path / 'browser.sh'
    browser.write_text(f'#!/bin/sh\necho $$ > "{log}.pid"\nprintf "%s" "$*" > "{log}.args"\n'
                       'exec sleep 60 </dev/null >/dev/null 2>&1\n',
                       encoding='utf-8')
    browser.chmod(0o755)
    env = {**environment(), 'BROWSER': str(browser)}
    serve = subprocess.Popen(command(str(workspace), '--root', str(root), '--static', str(static)), cwd=tmp_path,
                             env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True)
    try:
        runtime = wait_for_runtime(workspace, serve)
        deadline = time.monotonic() + 30
        while not (log.with_suffix('.args').exists() and log.with_suffix('.pid').exists()):
            assert time.monotonic() < deadline, 'the browser was not started'
            time.sleep(0.05)
        args = log.with_suffix('.args').read_text(encoding='utf-8')
        page = workspace / STATE / 'open.html'
        assert args == page.as_uri() and runtime['token'] not in args
        assert open_url(runtime) in page.read_text(encoding='utf-8') and mode(page) == 0o600
        with httpx.Client(base_url=f'http://127.0.0.1:{runtime["port"]}', timeout=5) as client:
            assert client.get(f'/open?token={runtime["token"]}').status_code == 303
        code, _, err = stop(serve, signal.SIGTERM)
        assert code == 0, err
        assert not page.exists() and not (workspace / STATE / 'runtime.json').exists()
    finally:
        if serve.poll() is None:
            serve.kill()
            serve.communicate()
        if log.with_suffix('.pid').exists():
            try:
                os.kill(int(log.with_suffix('.pid').read_text(encoding='utf-8')), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass


@needs_service
def test_a_stopping_instance_is_not_reused(tmp_path):
    # SIGTERM removes the runtime file at once, while the graceful shutdown still holds the lock (here for up to
    # 5 s, for a response the client does not read); a second serve then waits for the lock and starts anew.
    import httpx

    from .service_support import static_export, synthetic_root

    root = synthetic_root(tmp_path / 'root')
    static = static_export(tmp_path / 'static')
    (static / 'large.bin').write_bytes(bytes(64 * 1024 * 1024))
    workspace = tmp_path / 'workspace'
    args = command(str(workspace), '--root', str(root), '--static', str(static), '--no-browser')
    first = subprocess.Popen(args, cwd=tmp_path, env=environment(), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    second = None
    stalled = socket.socket()
    try:
        runtime = wait_for_runtime(workspace, first)
        with httpx.Client(base_url=f'http://127.0.0.1:{runtime["port"]}', timeout=10) as client:
            client.get(f'/open?token={runtime["token"]}')
            cookie = '; '.join(f'{name}={value}' for name, value in client.cookies.items())
        stalled.connect(('127.0.0.1', runtime['port']))
        stalled.sendall(f'GET /large.bin HTTP/1.1\r\nHost: 127.0.0.1:{runtime["port"]}\r\nCookie: {cookie}\r\n\r\n'
                        .encode('ascii'))
        assert stalled.recv(64).startswith(b'HTTP/1.1 200')
        time.sleep(0.3)
        first.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + 3
        while (workspace / STATE / 'runtime.json').exists():
            assert time.monotonic() < deadline, 'the runtime file outlived SIGTERM'
            time.sleep(0.02)
        assert first.poll() is None, 'the graceful shutdown holds the lock'
        second = subprocess.Popen(args, cwd=tmp_path, env=environment(), stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        renewed = wait_for_runtime(workspace, second, previous=runtime['token'])
        assert renewed['pid'] == second.pid
        assert first.wait(timeout=30) == 0
        code, out, err = stop(second, signal.SIGTERM)
        assert code == 0 and 'already running' not in out, err
    finally:
        stalled.close()
        for process in (first, second):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()


@needs_service
def test_serve_without_a_path_and_without_a_terminal_asks_for_one(tmp_path):
    (tmp_path / 'notes.txt').write_text('x', encoding='utf-8')
    result = subprocess.run(command('--root', str(tmp_path), '--no-browser'), cwd=tmp_path, env=environment(),
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    assert result.returncode == 2 and 'serve <directory>' in result.stderr
    assert not (tmp_path / MARKER).exists() and not (tmp_path / STATE).exists()


@needs_service
def test_serve_on_a_port_in_use_fails_and_leaves_no_runtime_file(tmp_path):
    taken = socket.socket()
    taken.bind(('127.0.0.1', 0))
    taken.listen(1)
    try:
        port = taken.getsockname()[1]
        workspace = tmp_path / 'w'
        result = subprocess.run(command(str(workspace), '--root', str(tmp_path), '--port', str(port), '--no-browser'),
                                cwd=tmp_path, env=environment(), stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=60)
    finally:
        taken.close()
    assert result.returncode == 1 and f'127.0.0.1:{port}' in result.stderr
    assert not (workspace / STATE / 'runtime.json').exists()
    Workspace.open(str(workspace)).close()


@needs_service
def test_serve_refuses_a_runtime_file_that_stays_open(tmp_path, monkeypatch, capsys):
    # The state directory could be made private, its files cannot (a mount whose file and directory masks differ).
    import uvicorn

    from eeglayoutlab.cli import main as cli

    monkeypatch.setattr(uvicorn.Server, 'run', lambda *args, **kwargs: pytest.fail('the service started'))
    fchmod = os.fchmod
    monkeypatch.setattr(os, 'fchmod', lambda fd, mode: fchmod(fd, 0o644 if mode == 0o600 else mode))
    assert cli.main(['serve', str(tmp_path / 'w'), '--root', str(tmp_path), '--no-browser']) == 1
    assert f'{tmp_path / "w" / STATE / "runtime.json"} cannot be made private' in capsys.readouterr().err
    monkeypatch.undo()
    assert sorted(os.listdir(tmp_path / 'w' / STATE)) == ['.gitignore', 'lock']
    Workspace.open(str(tmp_path / 'w')).close()


@needs_service
@pytest.mark.parametrize('args, message', [
    (['--port', '70000'], 'invalid port'),
    (['--root', 'relative/missing'], 'does not exist'),
])
def test_serve_rejects_bad_arguments(tmp_path, args, message):
    result = subprocess.run(command(str(tmp_path / 'w'), *args, '--no-browser'), cwd=tmp_path, env=environment(),
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    assert result.returncode == 2 and message in result.stderr


# --- The installed form (design 0002, changes 1, 2 and 4; phase 3 slice 2) ----------------------------------------

@needs_service
def test_serve_in_the_installed_form_needs_no_root(tmp_path):
    # installed_support's prefix: sys.prefix is P and the package is P's copy, so R and the interface are found as an
    # installed eeglayoutlab finds them, with no --root, no --static and no EEG_* variable.
    import httpx

    prefix = fake_prefix(tmp_path / 'P', public=())
    workspace = tmp_path / 'workspace'
    process = prefix.popen(MAIN, 'serve', str(workspace), '--no-browser')
    try:
        runtime = wait_for_runtime(workspace, process)
        assert runtime['root'] == os.path.realpath(prefix.root) and runtime['pid'] == process.pid
        with httpx.Client(base_url=f'http://127.0.0.1:{runtime["port"]}', timeout=10) as client:
            assert client.get(f'/open?token={runtime["token"]}').status_code == 303
            health = client.get('/api/local-compute/health')
            assert health.status_code == 200 and health.headers['x-eeg-api-version'] == '1'
            assert health.json()['local_only'] is True
            assert client.get('/').text == '<!doctype html><title>EEG Layout Lab</title>'
            assert client.get('/design').text == '<!doctype html><title>design</title>'
        code, out, err = stop(process, signal.SIGTERM)
        assert code == 0, err
        assert 'The interface is not built' not in out
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    # Without its interface, the installed package says that the package is incomplete.
    shutil.rmtree(prefix.root / 'webapp/dist/client')
    process = prefix.popen(MAIN, 'serve', str(workspace), '--no-browser')
    try:
        wait_for_runtime(workspace, process, previous=runtime['token'])
        code, out, err = stop(process, signal.SIGTERM)
        assert code == 0, err
        assert (f'The interface is not built ({os.path.realpath(prefix.root)}/webapp/dist/client); it is part of the '
                'eeglayoutlab package, so install the package again.') in out
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


@needs_service
@needs_non_root
def test_serve_refuses_a_read_only_root_and_writes_nothing(tmp_path):
    # 0002, decision 3: before a workspace is chosen or opened, also with --cache-only. The installed form says how
    # to get a writable environment; a checkout's root gets the generic remedy.
    prefix = fake_prefix(tmp_path / 'P', public=())
    real = os.path.realpath(prefix.root)
    workspace = tmp_path / 'workspace'
    before = tree_state(prefix.root)
    with read_only(prefix.root):
        for args in ([str(workspace)], [str(workspace), '--cache-only'], []):
            result = prefix.run(MAIN, 'serve', *args, '--no-browser', cwd=tmp_path)
            assert result.returncode == 2, result.stderr
            assert result.stderr.startswith(f'eeglayoutlab: {real} is not writable. The installed application '), \
                result.stderr
            assert 'create a user environment' in result.stderr and result.stdout == ''
    assert tree_state(prefix.root) == before
    assert not workspace.exists() and not (tmp_path / MARKER).exists() and not (tmp_path / STATE).exists()
    root = tmp_path / 'checkout'
    (root / 'results/v2').mkdir(parents=True)
    for blocked in (root / 'results/v2', root):
        with read_only(blocked):
            result = subprocess.run(command(str(workspace), '--root', str(root), '--no-browser'), cwd=tmp_path,
                                    env=environment(), stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                    timeout=60)
        assert result.returncode == 2, result.stderr
        assert result.stderr == (f'eeglayoutlab: {blocked} is not writable. Records and data are written under the '
                                 'scientific root; use a root you can write (--root or EEG_REPOSITORY_ROOT).\n')
        assert not workspace.exists()


# A stop that comes while serve starts: the handlers are installed before the runtime file is written, so a SIGTERM
# right after the write is noted, serve exits without serving and the file is gone. Installed after the write (slice
# 2), the signal's default action killed the process (-15) and left the file behind.
STOP_AFTER_WRITE = """
import os, signal, sys
from eeglayoutlab.cli import main as cli
from eeglayoutlab.server.workspace import Workspace
original = Workspace.write_runtime
def write_then_stop(self, *args, **kwargs):
    original(self, *args, **kwargs)
    os.kill(os.getpid(), signal.SIGTERM)
Workspace.write_runtime = write_then_stop
sys.exit(cli.main(sys.argv[1:]))
"""


@needs_service
def test_a_stop_right_after_the_runtime_file_is_written_leaves_no_runtime_file(tmp_path):
    from .service_support import synthetic_root

    root = synthetic_root(tmp_path / 'root')
    workspace = tmp_path / 'workspace'
    result = subprocess.run([sys.executable, '-c', STOP_AFTER_WRITE, 'serve', str(workspace), '--root', str(root),
                             '--no-browser'], cwd=tmp_path, env=environment(), stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert 'EEG Layout Lab:' not in result.stdout
    assert not (workspace / STATE / 'runtime.json').exists()
    Workspace.open(str(workspace)).close()


# A stop after the address is printed but before the compute services exist: SIGTERM as uvicorn starts (the services'
# loop does not run yet) or while the services are built (it runs, the queue does not exist yet).
STOP_WHILE_STARTING = """
import os, signal, sys
import uvicorn
from eeglayoutlab.cli import main as cli
from eeglayoutlab.server.routes.compute import ComputeHost
owner, name = (uvicorn.Server, 'run') if sys.argv.pop(1) == 'run' else (ComputeHost, '_build')
original = getattr(owner, name)
def stopped(self, *args, **kwargs):
    os.kill(os.getpid(), signal.SIGTERM)
    return original(self, *args, **kwargs)
setattr(owner, name, stopped)
sys.exit(cli.main(sys.argv[1:]))
"""


@needs_service
@pytest.mark.parametrize('where', ['run', 'build'])
def test_a_stop_before_the_compute_services_exist_dispatches_nothing(tmp_path, where):
    """The first signal reaches the compute services even when they do not exist yet: they stop as soon as they are
    built, so the task an earlier run left queued is neither recovered nor launched, and stays queued."""
    from .compute_support import REQUESTS, compute_root, key_of

    root = tmp_path / 'root'
    compute_root(root)
    workspace = tmp_path / 'workspace'
    Workspace.open(str(workspace)).close()
    task = {'id': '11111111-1111-4111-8111-111111111111', 'sequence': 1, 'kind': 'local-compute',
            'key': key_of(root, REQUESTS['hold']), 'request': REQUESTS['hold'], 'status': 'queued',
            'created_at': '2026-11-23T08:00:00.000Z', 'progress': 0, 'cached': False, 'catalog': {}}
    queue = workspace / STATE / 'queue.json'
    queue.write_text(jsjson.stringify({'schema': 'eeglayoutlab-queue/1', 'sequence': 1, 'tasks': [task]}),
                     encoding='utf-8')
    env = {**environment(), 'EEG_COMPUTE_PYTHON': sys.executable}
    result = subprocess.run([sys.executable, '-c', STOP_WHILE_STARTING, where, 'serve', str(workspace), '--root',
                             str(root), '--no-browser'], cwd=tmp_path, env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert 'EEG Layout Lab:' in result.stdout and 'Traceback' not in result.stderr, result.stderr
    assert jsjson.parse(queue.read_text(encoding='utf-8'))['tasks'] == [task]
    assert not (root / 'results/v2/local_app_jobs').exists()
    assert not (root / 'results/v2/.eeglayoutlab-execution.lock').exists()
    assert not (workspace / STATE / 'runtime.json').exists()


# The last write of the queue at shutdown fails (a full disk).
FAILED_LAST_WRITE = """
import errno, sys
from eeglayoutlab.cli import main as cli
from eeglayoutlab.jobs.queue import WorkspaceQueue
dispose = WorkspaceQueue.dispose
def full():
    raise OSError(errno.ENOSPC, 'No space left on device')
def dispose_on_a_full_disk(self):
    self._save = full
    dispose(self)
WorkspaceQueue.dispose = dispose_on_a_full_disk
sys.exit(cli.main(sys.argv[1:]))
"""


@needs_service
def test_serve_exits_1_when_the_last_write_of_the_queue_fails(tmp_path):
    """Node's host exits 1 when its ``dispose`` throws (start.mjs: ``process.exitCode = 1``), as it does when its
    last write of the queue fails; so does ``serve``, after a full shutdown. The queue logs the failure as Node's
    ``failClosed`` does (``computation queue stopped``, with its traceback), then one last line names the file. The
    signal is sent once a request has been answered, so the services (built in the lifespan, before uvicorn
    answers) exist: a stop before that builds nothing and exits 0."""
    import httpx

    from .service_support import synthetic_root

    root = synthetic_root(tmp_path / 'root')
    workspace = tmp_path / 'workspace'
    process = subprocess.Popen([sys.executable, '-c', FAILED_LAST_WRITE, 'serve', str(workspace), '--root', str(root),
                                '--no-browser'], cwd=tmp_path, env=environment(), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        runtime = wait_for_runtime(workspace, process)
        with httpx.Client(base_url=f'http://127.0.0.1:{runtime["port"]}', timeout=10) as client:
            assert client.get(f'/open?token={runtime["token"]}').status_code == 303
            assert client.get('/api/community/status').status_code == 200
        code, _, err = stop(process, signal.SIGTERM)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    queue = workspace / STATE / 'queue.json'
    assert code == 1, err
    last = (f'eeglayoutlab: Cannot write the workspace queue {queue} at shutdown: No space left on device. The next '
            'start applies its restart rules to the file as it was.')
    assert err.splitlines()[-1] == last and err.count(str(queue)) == 1, err
    assert ' ERROR eeglayoutlab.jobs.queue: computation queue stopped\n' in err.split(last)[0], err
    assert not (workspace / STATE / 'runtime.json').exists()
    Workspace.open(str(workspace)).close()


def serve_and_get(tmp_path: Path, workspace: Path, root: Path, paths: list[str], *flags: str) -> tuple[list, str]:
    """Runs ``serve`` with ``flags``, opens a session and GETs ``paths``; returns their JSON bodies and stdout."""
    import httpx

    process = subprocess.Popen(command(str(workspace), '--root', str(root), '--no-browser', *flags), cwd=tmp_path,
                               env=environment(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        runtime = wait_for_runtime(workspace, process)
        with httpx.Client(base_url=f'http://127.0.0.1:{runtime["port"]}', timeout=10) as client:
            assert client.get(f'/open?token={runtime["token"]}').status_code == 303
            bodies = []
            for path in paths:
                response = client.get(path)
                assert response.status_code == 200, response.text
                bodies.append(jsjson.parse(response.text))
        code, out, err = stop(process, signal.SIGTERM)
        assert code == 0, err
        return bodies, out
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


@needs_service
def test_serve_cache_only_reports_maintenance(tmp_path):
    from .service_support import synthetic_root

    root = synthetic_root(tmp_path / 'root')
    workspace = tmp_path / 'workspace'
    (health, status), out = serve_and_get(tmp_path, workspace, root,
                                          ['/api/local-compute/health', '/api/community/status'], '--cache-only')
    assert (health['maintenance'], health['drained'], health['active_job']) == (True, True, None)
    assert (status['maintenance'], status['drained'], status['available']) == (True, True, True)
    assert 'Cache only: stored results are served; new computations are refused.' in out
    assert jsjson.parse((workspace / STATE / 'queue.json').read_text(encoding='utf-8'))['tasks'] == []
    (health,), out = serve_and_get(tmp_path, workspace, root, ['/api/local-compute/health'])
    assert (health['maintenance'], health['drained']) == (False, False) and 'Cache only' not in out
    assert not (root / 'results/v2/.eeglayoutlab-execution.lock').exists()


@needs_service
def test_serve_clear_interrupted_resolves_an_unconfirmed_spawn(tmp_path):
    from .service_support import synthetic_root

    root = synthetic_root(tmp_path / 'root')
    workspace = tmp_path / 'workspace'
    Workspace.open(str(workspace)).close()
    created = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
    task = {'id': '11111111-1111-4111-8111-111111111111', 'sequence': 1, 'kind': 'local-compute', 'key': 'a' * 64,
            'request': {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface'}, 'status': 'queued',
            'created_at': created, 'progress': 0, 'cached': False, 'catalog': {}, 'starting': True}
    queue = workspace / STATE / 'queue.json'
    queue.write_text(jsjson.stringify({'schema': 'eeglayoutlab-queue/1', 'sequence': 1, 'tasks': [task]}),
                     encoding='utf-8')
    (status,), _ = serve_and_get(tmp_path, workspace, root, ['/api/community/status'])
    assert (status['recovery_blocked'], status['queued_tasks']) == (True, 1)
    assert jsjson.parse(queue.read_text(encoding='utf-8'))['tasks'][0]['starting'] is True
    (status,), _ = serve_and_get(tmp_path, workspace, root, ['/api/community/status'], '--clear-interrupted')
    assert status['recovery_blocked'] is False
    assert 'starting' not in jsjson.parse(queue.read_text(encoding='utf-8'))['tasks'][0]


@needs_service
@pytest.mark.parametrize('gap', [0.01, 0.05])
def test_ctrl_c_twice_still_stops_the_running_worker_and_writes_its_records(tmp_path, gap):
    """uvicorn takes a second SIGINT as a forced exit, which skips the lifespan's shutdown; ``serve`` passes every
    signal on as SIGTERM, and the first one stops the running worker at once, as Node's dispose does. So when
    ``serve`` exits the worker's group is gone and its ``job.json`` is written."""
    import httpx

    from eeglayoutlab.jobs.queue import group_alive

    from .compute_support import REQUESTS, compute_root

    root = tmp_path / 'root'
    compute_root(root)
    workspace = tmp_path / 'workspace'
    env = {**environment(), 'EEG_COMPUTE_PYTHON': sys.executable}
    process = subprocess.Popen(command(str(workspace), '--root', str(root), '--no-browser'), cwd=tmp_path, env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    queue = workspace / STATE / 'queue.json'
    pid = None
    try:
        runtime = wait_for_runtime(workspace, process)
        with httpx.Client(base_url=f'http://127.0.0.1:{runtime["port"]}', timeout=30) as client:
            assert client.get(f'/open?token={runtime["token"]}').status_code == 303
            token = client.get('/api/local-compute/health').json()['token']
            job = client.post('/api/local-compute/jobs', content=jsjson.stringify(REQUESTS['hold']),
                              headers={'content-type': 'application/json', 'x-eeg-compute-token': token}).json()['job']
            deadline = time.monotonic() + 60
            while not (job['status'] == 'running' and job['progress'] > 0 and pid):
                assert time.monotonic() < deadline, job
                time.sleep(0.05)
                job = client.get(f'/api/local-compute/jobs/{job["id"]}').json()['job']
                task = jsjson.parse(queue.read_text(encoding='utf-8'))['tasks'][-1]
                pid = int(task['worker_pid']) if 'worker_pid' in task else None
        assert group_alive(pid)
        process.send_signal(signal.SIGINT)
        time.sleep(gap)
        process.send_signal(signal.SIGINT)
        _, err = process.communicate(timeout=60)
        assert process.returncode == 0, err
        assert 'Traceback' not in err and 'CancelledError' not in err, err
        assert not group_alive(pid)
        [record] = (root / 'results/v2/local_app_jobs').glob('*/*/job.json')
        stored = jsjson.parse(record.read_text(encoding='utf-8'))
        assert (stored['id'], stored['status'], stored['message']) == (task['backend_id'], 'cancelled', '任务已停止')
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
        if pid and group_alive(pid):
            os.killpg(pid, signal.SIGKILL)


@needs_service
def test_serve_refuses_a_corrupt_queue_file_and_keeps_it(tmp_path):
    from .service_support import synthetic_root

    root = synthetic_root(tmp_path / 'root')
    workspace = tmp_path / 'workspace'
    Workspace.open(str(workspace)).close()
    queue = workspace / STATE / 'queue.json'
    queue.write_bytes(b'{"schema":"eeglayoutlab-queue/1","sequence":')
    result = subprocess.run(command(str(workspace), '--root', str(root), '--no-browser'), cwd=tmp_path,
                            env=environment(), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    assert result.returncode == 1, result.stderr
    assert f'eeglayoutlab: The workspace queue {queue} cannot be read' in result.stderr
    assert result.stderr.count('cannot be read') == 1 and 'Traceback' not in result.stderr
    assert queue.read_bytes() == b'{"schema":"eeglayoutlab-queue/1","sequence":'
    assert not (workspace / STATE / 'runtime.json').exists()
    Workspace.open(str(workspace)).close()


class CommandLineBrowser:
    """A launcher that would put the URL on a command line (``xdg-open URL``, ``$BROWSER URL``)."""


def fake_browser(monkeypatch, launcher: object) -> list[str]:
    from eeglayoutlab.cli import main as cli

    opened: list[str] = []
    monkeypatch.setattr(cli.webbrowser, 'get', lambda using=None: launcher)
    monkeypatch.setattr(cli.webbrowser, 'open', lambda url, *args, **kwargs: opened.append(url) or True)
    return opened


def test_the_browser_gets_the_open_page_not_the_launch_url(opened, monkeypatch):
    from eeglayoutlab.cli import main as cli

    url = open_url(opened.write_runtime(41234, 'f' * 64, '/root'))
    launched = fake_browser(monkeypatch, CommandLineBrowser())
    cli._open_browser(url, opened.write_open_page)
    page = Path(opened.path) / STATE / 'open.html'
    assert launched == [page.as_uri()] and 'f' * 64 not in launched[0]
    assert url in page.read_text(encoding='utf-8') and mode(page) == 0o600


@pytest.mark.skipif(sys.platform != 'darwin', reason="macOS's launcher")
def test_macos_launcher_gets_the_url_on_standard_input(opened, monkeypatch):
    import webbrowser

    from eeglayoutlab.cli import main as cli

    url = open_url(opened.write_runtime(41234, 'f' * 64, '/root'))
    launched = fake_browser(monkeypatch, webbrowser.MacOSXOSAScript('default'))
    cli._open_browser(url, opened.write_open_page)
    assert launched == [url] and not (Path(opened.path) / STATE / 'open.html').exists()


def mac_launcher() -> object:
    import webbrowser

    if not hasattr(webbrowser, 'MacOSXOSAScript'):
        pytest.skip("macOS's launcher")
    return webbrowser.MacOSXOSAScript('default')


@pytest.mark.parametrize('launcher', [CommandLineBrowser, mac_launcher])
def test_a_service_that_is_stopping_opens_no_browser_and_leaves_no_open_page(opened, monkeypatch, launcher):
    # SIGINT or SIGTERM arrives while webbrowser looks for a browser (on Linux it runs xdg-settings first): the stop
    # handler removes the runtime file, then the server's should_exit is set. The browser thread then writes no
    # open page, which nothing would remove, and starts no browser.
    from types import SimpleNamespace

    from eeglayoutlab.cli import main as cli

    runtime = opened.write_runtime(41234, 'f' * 64, '/root')
    server = SimpleNamespace(started=True, should_exit=False)
    browser = launcher()

    def signalled(using=None):
        opened.remove_runtime()
        server.should_exit = True
        return browser

    launched = fake_browser(monkeypatch, browser)
    monkeypatch.setattr(cli.webbrowser, 'get', signalled)
    cli._open_when_started(server, open_url(runtime), opened.write_open_page)
    assert launched == [] and not (Path(opened.path) / STATE / 'open.html').exists()


@pytest.mark.parametrize('macos_launchers', [True, False], ids=['launcher-classes', 'no-launcher-classes'])
@pytest.mark.parametrize('stop', [True, False], ids=['stop-during-lookup', 'no-stop'])
def test_the_browser_lookup_runs_before_the_open_page_is_written(opened, monkeypatch, macos_launchers, stop):
    # webbrowser looks for the browsers on its first get() or open() (register_standard_browsers; on Linux it runs
    # xdg-settings). The lookup must come before the open page is written, also where webbrowser has no macOS
    # launcher classes (Linux): a stop during it then leaves no page and starts no browser. This runs the standard
    # library's get() and open() with only the lookup and the launcher replaced.
    import webbrowser
    from types import SimpleNamespace

    from eeglayoutlab.cli import main as cli

    runtime = opened.write_runtime(41234, 'f' * 64, '/root')
    server = SimpleNamespace(started=True, should_exit=False)
    launched: list[str] = []

    class Recording(webbrowser.BaseBrowser):
        def open(self, url, new=0, autoraise=True):
            launched.append(url)
            return True

    def lookup():
        if stop:
            opened.remove_runtime()
            server.should_exit = True
        webbrowser._tryorder = []
        webbrowser.register('recording', None, Recording('recording'), preferred=True)

    monkeypatch.setattr(webbrowser, '_tryorder', None)
    monkeypatch.setattr(webbrowser, '_browsers', {})
    monkeypatch.setattr(webbrowser, 'register_standard_browsers', lookup)
    if not macos_launchers:
        for name in ('MacOSXOSAScript', 'MacOSX'):
            monkeypatch.delattr(webbrowser, name, raising=False)
    cli._open_when_started(server, open_url(runtime), opened.write_open_page)
    page = Path(opened.path) / STATE / 'open.html'
    if stop:
        assert launched == [] and not page.exists()
    else:
        assert launched == [page.as_uri()] and open_url(runtime) in page.read_text(encoding='utf-8')


def test_no_open_page_without_a_browser(opened, monkeypatch, capsys):
    import webbrowser

    from eeglayoutlab.cli import main as cli

    def missing(using=None):
        raise webbrowser.Error('could not locate runnable browser')

    monkeypatch.setattr(cli.webbrowser, 'get', missing)
    monkeypatch.setattr(cli.webbrowser, 'open', lambda *args, **kwargs: pytest.fail('webbrowser.open was called'))
    cli._open_browser(open_url(opened.write_runtime(41234, 'f' * 64, '/root')), opened.write_open_page)
    assert not (Path(opened.path) / STATE / 'open.html').exists()
    assert 'Open the address above in a browser.' in capsys.readouterr().out


@pytest.mark.parametrize('browser', [True, False])
def test_a_second_serve_opens_or_prints_the_running_instance(tmp_path, monkeypatch, capsys, browser):
    from eeglayoutlab.cli import main as cli

    runtime = {'schema': RUNTIME_SCHEMA, 'pid': os.getpid(), 'port': 41234, 'token': 'e' * 64}
    Workspace.open(str(tmp_path / 'w')).close()

    def in_use(path, wait=0):
        raise WorkspaceInUse(path, runtime)

    monkeypatch.setattr(cli.Workspace, 'open', in_use)
    opened = fake_browser(monkeypatch, CommandLineBrowser())
    monkeypatch.setattr(cli.importlib.util, 'find_spec', lambda name: object())
    args = [str(tmp_path / 'w'), '--root', str(tmp_path)] + ([] if browser else ['--no-browser'])
    assert cli.main(['serve', *args]) == 0
    assert open_url(runtime) in capsys.readouterr().out
    page = tmp_path / 'w' / STATE / 'open.html'
    assert opened == ([page.as_uri()] if browser else [])
    assert not browser or open_url(runtime) in page.read_text(encoding='utf-8')


def test_a_locked_workspace_without_a_runtime_file_is_explained(tmp_path, monkeypatch, capsys):
    from eeglayoutlab.cli import main as cli

    def in_use(path, wait=0):
        raise WorkspaceInUse(path, None)

    monkeypatch.setattr(cli.Workspace, 'open', in_use)
    monkeypatch.setattr(cli.importlib.util, 'find_spec', lambda name: object())
    assert cli.main(['serve', str(tmp_path / 'w'), '--root', str(tmp_path), '--no-browser']) == 1
    assert 'runtime file is missing or not valid' in capsys.readouterr().err
