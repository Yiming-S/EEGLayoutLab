"""The reception runtime digest (plan B15): ``jobs.runtime_digest``, Node's ``runtime/identity-cache.mjs``.

- Ports of the 13 sites of webapp/scripts/check-runtime-identity-cache.mjs on ``RuntimeIdentityCache`` with that
  file's injected inspectors (``runtime_digest_support.Fixture``).
- Then what Python adds: Node's constants, the asynchronous and synchronous calls sharing one inspection, a caller
  that stops waiting, ``close`` (also of an inspector spawned after it), the service's environment read as Node
  reads ``process.env``, Node's settings over the service's and the memo key of the merged environment, an inspector
  that closes its outputs and runs on, and the error classes the queue tells refusals from internal faults by.
- Parity: ``parity/runtime_digest.mjs`` runs Node's ``createRuntimeIdentityCache`` with its own inspector runner on
  case directories with a stub inspector script (``runtime_digest_support.parity_cases``): fixed outputs, failures,
  the timeout (also of an inspector that closes its outputs and runs on), outputs at and over the bound, missing and
  unreadable scripts, legacy output without ``watch``, malformed results, changed stamps, the launcher chain and PATH
  search, environments (``PYTHONPATH`` and Node's settings among them), the entry budget and simultaneous reads.
  Digests, inspector runs and errors must equal Node's.
- ``native_runtime``: the real inspector of ``EEG_KEY_PARITY_ROOT`` (read only), through Node and Python, with and
  without ``PYTHONPATH`` in the environment.
"""
from __future__ import annotations

import asyncio
import copy
import errno
import os
from pathlib import Path
import re
import sys
import threading
import time

import pytest

from eeglayoutlab.jobs import queue, runtime_digest
from eeglayoutlab.jobs.runtime import native_python_path
from eeglayoutlab.jobs.runtime_digest import (DIGEST_SCHEMA, InspectorError, MaxBufferError, RuntimeDigestError,
                                              RuntimeIdentityCache, _valid_watch)
from eeglayoutlab.jobs.worker import WorkerError
from eeglayoutlab.schemas import jsjson

from .key_parity_support import needs_node
from .runtime_digest_support import (Fixture, ROOT, apply, build, environment, hash_text, mode, observation,
                                     parity_cases, python_case, run, run_driver, stub_root)

NODE_SOURCE = ROOT / 'webapp/server/runtime/identity-cache.mjs'
# The parity's timeout case waits this long on each host instead of 15 s (the constant itself is checked below).
TIMEOUT_MS = 5000
# Parity cases whose runs depend on permissions, which the superuser does not have refused.
PERMISSIONS = ('snapshot-unreadable', 'unreadable-entry', 'fail-closed')


# --- Ports of check-runtime-identity-cache.mjs ------------------------------------------------------------------

def test_warm_runtime_checks_preserve_digest_with_no_new_inspector_and_isolate_returned_values(tmp_path):
    f = Fixture(tmp_path)
    first = f.read()
    expected = copy.deepcopy(first)
    first['sha256'] = '0' * 64
    assert f.read() == expected
    assert f.calls == 1


def test_same_size_writes_invalidate_even_when_mtime_is_restored(tmp_path):
    f = Fixture(tmp_path)
    before = f.read()
    info = os.stat(f.file)
    f.file.write_text('version2', encoding='utf-8')
    os.utime(f.file, ns=(info.st_atime_ns, info.st_mtime_ns))
    assert f.read()['sha256'] != before['sha256']
    assert f.calls == 2


@pytest.mark.parametrize('mutation', ['add', 'delete', 'replace'])
def test_numerical_discovery_invalidates_the_cached_inspection(tmp_path, mutation):
    f = Fixture(tmp_path)
    sibling = f.folder / 'other.py'
    sibling.write_text('other', encoding='utf-8')
    expected = f.read()
    if mutation == 'add':
        (f.folder / 'added.py').write_text('new numerical module', encoding='utf-8')
    if mutation == 'delete':
        sibling.unlink()
    if mutation == 'replace':
        f.folder.rename(f'{f.folder}-old')
        f.folder.mkdir()
        f.file.write_text('version1', encoding='utf-8')
    assert f.read() == expected
    assert f.calls == 2


def test_missing_dependencies_fail_closed_and_repaired_inputs_retry(tmp_path):
    f = Fixture(tmp_path)
    first = f.read()
    f.file.unlink()
    with pytest.raises(OSError) as caught:
        f.read()
    assert caught.value.errno == errno.ENOENT
    f.file.write_text('version1', encoding='utf-8')
    assert f.read() == first
    assert f.calls == 3


def test_simultaneous_cold_and_warm_queries_share_a_single_inspection_check(tmp_path):
    f = Fixture(tmp_path)

    async def burst() -> list[dict]:
        return list(await asyncio.gather(*(f.aread() for _ in range(12))))
    cold = run(burst())
    assert all(result['sha256'] == cold[0]['sha256'] for result in cold)
    assert f.calls == 1
    run(burst())
    assert f.calls == 1
    f.file.write_text('version2', encoding='utf-8')
    run(burst())
    assert f.calls == 2


def test_failed_inspection_is_not_reused_and_observations_changed_during_inspection_are_rejected(tmp_path):
    f = Fixture(tmp_path)
    f.failure = RuntimeDigestError('incomplete runtime')
    with pytest.raises(RuntimeDigestError, match='incomplete runtime'):
        f.read()
    f.failure = None
    f.after_snapshot = lambda: f.file.write_text('version2', encoding='utf-8')
    with pytest.raises(RuntimeDigestError, match='检查期间'):
        f.read()
    f.after_snapshot = None
    assert f.read()['sha256'] == hash_text('version2')
    assert f.calls == 3


def test_environment_keys_and_bounded_least_recently_used_entries_stay_independent(tmp_path):
    f = Fixture(tmp_path, max_entries=2)
    a, b, c = ({'env': {'CHOICE': choice}} for choice in 'abc')
    first = f.read(**a)
    assert f.read(**b)['sha256'] != first['sha256']
    assert f.read(**a) == first
    f.read(**c)
    assert f.calls == 3
    f.read(**a)
    assert f.calls == 3
    f.read(**b)
    assert f.calls == 4


def test_launcher_symlink_and_an_earlier_path_executable_invalidate_the_current_digest(tmp_path):
    f = Fixture(tmp_path)
    first, second = f.root / 'first', f.root / 'second'
    first.mkdir()
    second.mkdir()
    (second / 'python').symlink_to(sys.executable)
    args = {'python': 'python', 'env': {'PATH': f'{first}:{second}'}}
    f.read(**args)
    f.read(**args)
    assert f.calls == 1
    (first / 'python').symlink_to(sys.executable)
    f.read(**args)
    assert f.calls == 2
    (first / 'python').unlink()
    (first / 'python').write_text('different executable', encoding='utf-8')
    f.read(**args)
    assert f.calls == 3


def _write(path: Path, text: str, mode: int) -> None:
    """``writeFile(path, text, {mode})``: the mode applies when the file is created."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(fd, text.encode('utf-8'))
    finally:
        os.close(fd)


@pytest.mark.parametrize('change', ['missing target', 'nonexecutable target', 'intermediate link'])
def test_an_earlier_path_symlink_becoming_executable_invalidates_the_digest(tmp_path, change):
    f = Fixture(tmp_path)
    first, second, external = f.root / 'first', f.root / 'second', f.root / 'external'
    for directory in (first, second, external):
        directory.mkdir()
    preferred, fallback, target = first / 'python', second / 'python', external / 'preferred-python'
    _write(fallback, 'fallback runtime', 0o755)
    if change == 'intermediate link':
        (external / 'intermediate').symlink_to('preferred-python')
        preferred.symlink_to('../external/intermediate')
    else:
        preferred.symlink_to(target)
    if change == 'nonexecutable target':
        _write(target, 'preferred runtime', 0o644)
    inspections = 0

    def inspect(python: str, root: str, env: dict) -> dict:
        nonlocal inspections
        inspections += 1
        executable = preferred if os.access(preferred, os.X_OK) else fallback  # the search goes on to the fallback
        return {'schema': DIGEST_SCHEMA, 'sha256': hash_text(executable.read_bytes()),
                'watch': observation([executable])}
    cache = RuntimeIdentityCache(inspect=inspect)
    args = {**f.args, 'python': 'python', 'env': {'PATH': f'{first}:{second}'}}
    initial = run(cache(**args))
    assert initial['sha256'] == hash_text('fallback runtime')
    assert run(cache(**args)) == initial
    assert inspections == 1
    if change == 'nonexecutable target':
        target.chmod(0o755)
    else:
        _write(target, 'preferred runtime', 0o755)
    updated = run(cache(**args))
    assert updated['sha256'] == hash_text('preferred runtime')
    assert inspections == 2
    assert run(cache(**args)) == updated
    assert inspections == 2


@pytest.mark.parametrize('invocation', ['PATH entry', 'absolute executable', 'relative executable'])
def test_symlink_traversal_retains_operating_system_path_semantics(tmp_path, invocation):
    f = Fixture(tmp_path)
    physical, branch = f.root / 'physical', f.root / 'branch'
    (physical / 'nested').mkdir(parents=True)
    (physical / 'bin').mkdir()
    branch.mkdir()
    (branch / 'link').symlink_to(physical / 'nested')
    actual, fallback = physical / 'bin/python', f.root / 'fallback'
    fallback.mkdir()
    _write(fallback / 'python', 'fallback runtime', 0o755)
    lexical = f'{branch}/link/../bin/python'
    if invocation == 'PATH entry':
        args = {**f.args, 'python': 'python', 'env': {'PATH': f'{branch}/link/../bin:{fallback}'}}
    else:
        args = {**f.args, 'python': lexical if invocation == 'absolute executable' else 'branch/link/../bin/python'}
        _write(actual, 'version1', 0o755)
    inspections = 0

    def inspect(python: str, root: str, env: dict) -> dict:
        nonlocal inspections
        inspections += 1
        executable = lexical if os.access(lexical, os.X_OK) else str(fallback / 'python')
        return {'schema': DIGEST_SCHEMA, 'sha256': hash_text(Path(executable).read_bytes()),
                'watch': observation([f.file])}
    cache = RuntimeIdentityCache(inspect=inspect)
    initial = run(cache(**args))
    assert run(cache(**args)) == initial
    assert inspections == 1
    _write(actual, 'version2', 0o755)
    assert run(cache(**args))['sha256'] == hash_text('version2')
    assert inspections == 2


def test_legacy_digest_only_inspectors_are_accepted_but_not_cached(tmp_path):
    f = Fixture(tmp_path)
    calls = 0

    def inspect(python: str, root: str, env: dict) -> dict:
        nonlocal calls
        calls += 1
        return {'schema': DIGEST_SCHEMA, 'sha256': hash_text('legacy')}
    cache = RuntimeIdentityCache(inspect=inspect)
    run(cache(**f.args))
    run(cache(**f.args))
    assert calls == 2


def test_an_implicit_platform_executable_search_path_is_inspected_each_time(tmp_path):
    f = Fixture(tmp_path)
    args = {'python': 'python3', 'env': {}}
    f.read(**args)
    f.read(**args)
    assert f.calls == 2


def test_zero_entry_budget_disables_retention_malformed_runtime_output_fails(tmp_path):
    f = Fixture(tmp_path, max_entries=0)
    f.read()
    f.read()
    assert f.calls == 2
    for result in ({'schema': 'wrong', 'sha256': hash_text('x')}, {'schema': DIGEST_SCHEMA, 'sha256': 'bad'},
                   {'schema': DIGEST_SCHEMA, 'sha256': hash_text('x'), 'watch': {}}):
        cache = RuntimeIdentityCache(inspect=lambda python, root, env, result=result: result)
        with pytest.raises(RuntimeDigestError):
            run(cache(**f.args))


# --- What Python adds -------------------------------------------------------------------------------------------

def _constant(pattern: str) -> str:
    match = re.search(pattern, NODE_SOURCE.read_text(encoding='utf-8'))
    assert match, f'{pattern} moved in identity-cache.mjs'
    return match.group(1)


def test_constants_are_nodes():
    assert _constant(r"const digestSchema = '([^']+)'") == runtime_digest.DIGEST_SCHEMA
    assert _constant(r"const watchSchema = '([^']+)'") == runtime_digest.WATCH_SCHEMA
    assert _constant(r"let script = join\(root, '([^']+)'\)") == runtime_digest.SNAPSHOT_SCRIPT
    assert _constant(r"(?<!let )script = join\(root, '([^']+)'\)") == runtime_digest.LEGACY_SCRIPT
    settings = dict(re.findall(r"(\w+): '(\d)'", _constant(r'env = \{ \.\.\.env, ([^}]+) \}')))
    assert settings == runtime_digest.INSPECT_ENV and list(settings) == list(runtime_digest.INSPECT_ENV)
    assert int(_constant(r'timeout: (\d+),')) == runtime_digest.INSPECT_TIMEOUT_SECONDS * 1000
    assert _constant(r'maxBuffer: ([\d *]+) \}') == '8 * 1024 * 1024'
    assert runtime_digest.INSPECT_MAX_BUFFER == 8 * 1024 * 1024
    assert int(_constant(r'maxEntries = (\d+)')) == runtime_digest.MAX_ENTRIES
    assert int(_constant(r'watch\.entries\.length > (\d+)')) == runtime_digest.WATCH_LIMIT
    assert int(_constant(r'expanded\.size > (\d+)')) == runtime_digest.LAUNCHER_LIMIT
    assert _constant(r"new Error\('(接收[^']+)'\)") == runtime_digest.INVALID_DIGEST
    assert _constant(r"new Error\('(数值[^']+)'\)") == runtime_digest.CHANGED_DURING_INSPECTION
    assert _constant(r"new Error\('(Python launcher[^']+)'\)") == runtime_digest.LAUNCHER_CHAIN_TOO_LARGE
    assert _constant(r"new Error\('(Invalid runtime[^']+)'\)") == runtime_digest.INVALID_LIMIT
    source = NODE_SOURCE.read_text(encoding='utf-8')
    assert f"/^{runtime_digest._STAMP.pattern.replace('[0-9]', chr(92) + 'd')}$/.test(item[2])" in source
    assert f'/^{runtime_digest._HEX64.pattern}$/.test(result.sha256)' in source


def test_max_entries_follow_number_is_integer():
    for value in (0, 4, 4.0, 2 ** 53):
        RuntimeIdentityCache(max_entries=value)
    for value in (-1, 1.5, float('inf'), float('nan'), True, '4', None):
        with pytest.raises(RuntimeDigestError, match='Invalid runtime cache limit'):
            RuntimeIdentityCache(max_entries=value)


def test_watch_bounds_and_javascript_patterns():
    entry = ['/', False, '1:2:3']
    assert _valid_watch({'schema': 'reception-runtime-watch/1', 'entries': [entry]})
    many = [[f'/{index}', False, None] for index in range(100000)]
    assert _valid_watch({'schema': 'reception-runtime-watch/1', 'entries': many})
    assert not _valid_watch({'schema': 'reception-runtime-watch/1', 'entries': [*many, ['/x', False, None]]})
    for stamp in ('١:2:3', '1:2:3\n', '1:2:3:4:5', '1:2:3:4:5:6:7', '1:2:3:-4:5:6', ' 1:2:3'):
        assert not _valid_watch({'schema': 'reception-runtime-watch/1', 'entries': [['/', False, stamp]]}), stamp
    assert _valid_watch({'schema': 'reception-runtime-watch/1', 'entries': [['/', True, '1:2:3:4:-5:-6']]})
    assert not _valid_watch({'schema': 'reception-runtime-watch/1', 'entries': [['/', 1.0, None]]})


class Held:
    """An injected inspector that waits for ``release`` (so calls can join it) and counts its runs."""

    def __init__(self, sha256: str = 'a' * 64):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.sha256 = sha256

    def __call__(self, python: str, root: str, env: dict) -> dict:
        self.calls += 1
        self.started.set()
        assert self.release.wait(60)
        return {'schema': DIGEST_SCHEMA, 'sha256': self.sha256,
                'watch': {'schema': 'reception-runtime-watch/1', 'entries': [[root, False, _stamp(root)]]}}


def _stamp(path: str) -> str:
    info = os.lstat(path)
    return f'{info.st_dev}:{info.st_ino}:{info.st_mode}'


def test_asynchronous_and_synchronous_calls_share_the_memo_and_the_inspection_in_flight(tmp_path):
    held = Held()
    cache = RuntimeIdentityCache(inspect=held)
    args = (sys.executable, str(tmp_path), {})
    results: list = []

    async def scenario() -> None:
        first = asyncio.ensure_future(cache(*args))
        await asyncio.to_thread(held.started.wait, 60)
        joiner = threading.Thread(target=lambda: results.append(cache.read_sync(*args)))
        joiner.start()
        await asyncio.sleep(0.2)
        held.release.set()
        results.append(await first)
        await asyncio.to_thread(joiner.join, 60)
    run(scenario())
    assert results == [{'schema': DIGEST_SCHEMA, 'sha256': 'a' * 64}] * 2 and results[0] is not results[1]
    assert held.calls == 1
    assert cache.read_sync(*args) == results[0] and held.calls == 1


def test_a_caller_that_stops_waiting_leaves_the_inspection_to_the_others(tmp_path):
    held = Held()
    cache = RuntimeIdentityCache(inspect=held)
    args = (sys.executable, str(tmp_path), {})

    async def scenario() -> dict:
        impatient = asyncio.ensure_future(cache(*args))
        await asyncio.to_thread(held.started.wait, 60)
        patient = asyncio.ensure_future(cache(*args))
        await asyncio.sleep(0.1)
        impatient.cancel()
        await asyncio.sleep(0.1)
        held.release.set()
        return await patient
    assert run(scenario()) == {'schema': DIGEST_SCHEMA, 'sha256': 'a' * 64}
    assert cache.read_sync(*args)['sha256'] == 'a' * 64 and held.calls == 1  # the result was kept


def test_keys_of_other_interpreters_and_roots_do_not_wait_for_each_other(tmp_path):
    held = Held()
    cache = RuntimeIdentityCache(inspect=lambda python, root, env: held(python, root, env) if root.endswith('slow')
                                 else {'schema': DIGEST_SCHEMA, 'sha256': 'b' * 64})
    (tmp_path / 'slow').mkdir()

    async def scenario() -> dict:
        slow = asyncio.ensure_future(cache(sys.executable, str(tmp_path / 'slow'), {}))
        await asyncio.to_thread(held.started.wait, 60)
        try:
            return await asyncio.wait_for(cache(sys.executable, str(tmp_path), {}), 30)
        finally:
            held.release.set()
            await slow
    assert run(scenario())['sha256'] == 'b' * 64


def test_close_kills_the_inspectors_still_running(tmp_path):
    stub_root(tmp_path / 'case')
    apply(tmp_path / 'case', mode(sleep=60), sys.executable)
    cache = RuntimeIdentityCache()

    async def scenario() -> BaseException:
        call = asyncio.ensure_future(cache(sys.executable, str(tmp_path / 'case/R')))
        deadline = time.monotonic() + 30
        while (not (tmp_path / 'case/inspections.log').exists() or not cache._processes) \
                and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        cache.close()
        try:
            await asyncio.wait_for(call, 30)
        except BaseException as error:  # noqa: BLE001 - the failure is the result
            return error
        raise AssertionError('the inspector was not stopped')
    started = time.monotonic()
    error = run(scenario())
    assert isinstance(error, InspectorError) and error.signal == 'SIGKILL' and error.code is None
    assert time.monotonic() - started < 30


def test_close_also_kills_an_inspector_spawned_after_it(tmp_path, monkeypatch):
    # A call still taking its stamps when the service closes spawns its inspector afterwards: it is killed at once,
    # not left to the 15 s timeout (whose SIGTERM would be the failure without the closed state).
    stub_root(tmp_path / 'case')
    apply(tmp_path / 'case', mode(sleep=60), sys.executable)
    stamping, release = threading.Event(), threading.Event()
    launcher_watch = runtime_digest._launcher_watch

    def held(*args):
        stamping.set()
        assert release.wait(60)
        return launcher_watch(*args)
    monkeypatch.setattr(runtime_digest, '_launcher_watch', held)
    cache = RuntimeIdentityCache()

    async def scenario() -> BaseException:
        call = asyncio.ensure_future(cache(sys.executable, str(tmp_path / 'case/R')))
        assert await asyncio.to_thread(stamping.wait, 60)
        cache.close()
        release.set()
        try:
            await asyncio.wait_for(call, 60)
        except BaseException as error:  # noqa: BLE001 - the failure is the result
            return error
        raise AssertionError('the inspector ran after the close')
    try:
        error = run(scenario())
    finally:
        release.set()
        cache.close()
    assert isinstance(error, InspectorError) and error.signal == 'SIGKILL' and error.code is None
    assert not cache._processes


def test_the_service_environment_is_read_as_node_reads_process_env(tmp_path, monkeypatch):
    # Node decodes the environment as UTF-8 (invalid bytes as U+FFFD) and passes that text on; the stub hashes what
    # it receives.
    case = tmp_path / 'case'
    stub_root(case)
    apply(case, mode(env=['EEG_RAW'], legacy=True), sys.executable)
    monkeypatch.setitem(os.environb, b'EEG_RAW', b'a\xffb')
    assert runtime_digest.process_env()['EEG_RAW'] == 'a�b'
    value = run(RuntimeIdentityCache()(sys.executable, str(case / 'R')))
    assert value['sha256'] == hash_text('version1\0a�b')


def test_nodes_settings_override_the_services_and_the_memo_keys_the_merged_environment(tmp_path):
    """identity-cache.mjs:94, ``env = {...env, PYTHONDONTWRITEBYTECODE: '1', OMP_NUM_THREADS: '1', ...}``: the
    inspector gets the five settings over the service's own values of those names (a real child hashes what it
    got), and the memo key is taken of that merged environment, so environments that differ only there share one
    inspection."""
    settings = runtime_digest.INSPECT_ENV
    f = Fixture(tmp_path)
    seen: list[dict] = []
    f.cache = RuntimeIdentityCache(inspect=lambda python, root, env: seen.append(dict(env)) or f.inspect(python, root,
                                                                                                         env))
    service = {'CHOICE': 'a', **{name: '8' for name in settings}}
    first = f.read(env=service)
    assert seen == [{'CHOICE': 'a', **settings}]
    assert f.read(env={**service, 'OMP_NUM_THREADS': '4', 'PYTHONDONTWRITEBYTECODE': ''}) == first
    assert f.read(env={'CHOICE': 'a'}) == first and len(seen) == f.calls == 1
    case = tmp_path / 'case'
    stub_root(case)
    apply(case, mode(env=list(settings), legacy=True), sys.executable)
    value = run(RuntimeIdentityCache()(sys.executable, str(case / 'R'), {name: '8' for name in settings}))
    assert value['sha256'] == hash_text('\0'.join(['version1', *settings.values()]))


def test_an_inspector_that_closes_its_outputs_and_runs_on_fails_at_the_timeout(tmp_path, monkeypatch):
    """execFile's timer, not the end of the outputs, ends the call: SIGTERM at the deadline (here 1 s) and
    ``Command failed`` with what stderr held, killed by that signal, as Node fails (the parity's ``outputs-closed``
    case). Waiting for the process instead would wait as long as it runs."""
    monkeypatch.setattr(runtime_digest, 'INSPECT_TIMEOUT_SECONDS', 1.0)
    stub_root(tmp_path / 'case')
    apply(tmp_path / 'case', mode(stderr='started\n', close_outputs=True, sleep=60), sys.executable)
    cache = RuntimeIdentityCache()
    started = time.monotonic()
    try:
        with pytest.raises(InspectorError) as caught:
            run(asyncio.wait_for(cache(sys.executable, str(tmp_path / 'case/R')), 15))
    finally:
        cache.close()
    script = f'{tmp_path}/case/R/{runtime_digest.SNAPSHOT_SCRIPT}'
    assert (caught.value.message, caught.value.signal, caught.value.killed, caught.value.code) == \
        (f'Command failed: {sys.executable} {script}\nstarted\n', 'SIGTERM', True, None)
    assert time.monotonic() - started < 10


def test_errors_keep_nodes_classes_for_the_queue():
    refusals = [RuntimeDigestError(runtime_digest.INVALID_DIGEST),
                InspectorError('Command failed: python x\nboom\n', code=1, killed=False, signal=None, cmd='python x'),
                InspectorError('Command failed: python x\n', code=None, killed=True, signal='SIGTERM', cmd='python x')]
    for error in refusals:
        assert not queue.internal_fault(error) and queue.public_message(error) == error.message
    for error in (MaxBufferError('stdout'), WorkerError('spawn python ENOENT', 'ENOENT'),
                  OSError(errno.EACCES, 'denied')):
        if isinstance(error, OSError):
            error.code = 'EACCES'
        assert queue.internal_fault(error) and queue.public_message(error) == queue.INTERNAL_MESSAGE
    assert queue.public_message(jsjson.JSONSyntaxError('x')) == queue.NOT_JSON


# --- Parity with Node -------------------------------------------------------------------------------------------

@pytest.fixture(scope='module')
def parity(tmp_path_factory):
    """Both hosts over the parity cases, each on its own copy of the case directories (same name lengths)."""
    scratch = tmp_path_factory.mktemp('runtime-digest')
    cases = parity_cases()
    python = sys.executable
    node = run_driver(build(scratch / 'n', cases, python), python, scratch, inspect_timeout_ms=TIMEOUT_MS)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runtime_digest, 'INSPECT_TIMEOUT_SECONDS', TIMEOUT_MS / 1000)
        ours = {case['id']: run(python_case(case, python)) for case in build(scratch / 'p', cases, python)}
    return cases, node, ours


@needs_node
def test_stub_inspectors_match_node(parity):
    cases, node, ours = parity
    assert set(node['by_id']) == set(ours) == {case['id'] for case in cases}
    differences = {key: {'python': ours[key], 'node': node['by_id'][key]}
                   for key in ours if ours[key] != node['by_id'][key]}
    assert differences == {}


@needs_node
def test_parity_cases_reach_their_branches(parity):
    cases, node, _ = parity
    assert node['scaled'] >= 2  # the timeout cases ran with the shorter timer
    by_id = node['by_id']
    for case in cases:
        if 'expect' in case and not (os.geteuid() == 0 and case['id'] in PERMISSIONS):
            assert [step['runs'] for step in by_id[case['id']]['steps']] == case['expect'], case['id']

    def error(case: str, index: int = 0) -> dict:
        outcome = by_id[case]['steps'][index]['outcomes'][0]
        assert not outcome['ok'], (case, index)
        return outcome['error']
    script = '<case>/R/scripts/inspect_reception_runtime_snapshot.py'
    assert error('timeout') == error('outputs-closed') == {
        'name': 'Error', 'message': f'Command failed: {sys.executable} {script}\nstarted\n', 'code': None,
        'signal': 'SIGTERM', 'killed': True}
    assert error('exit')['message'] == f'Command failed: {sys.executable} {script}\nbroken runtime\n'
    assert error('exit')['code'] == 3 and error('signal')['signal'] == 'SIGKILL'
    for case, stream in (('stdout-flood', 'stdout'), ('stdout-over-the-bound', 'stdout'),
                         ('stderr-decoded-over-the-bound', 'stderr')):
        assert error(case) == {'name': 'RangeError', 'message': f'{stream} maxBuffer length exceeded',
                               'code': 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER', 'signal': None, 'killed': None}
    for case in ('stdout-exactly-at-the-bound', 'stderr-decoded-at-the-bound', 'fallback', 'relative-python',
                 'relative-path-entry'):
        assert by_id[case]['steps'][0]['outcomes'][0]['ok'], case
    if os.geteuid() != 0:
        assert error('snapshot-unreadable')['message'] == f"EACCES: permission denied, access '{script}'"
        assert error('unreadable-entry')['message'] == "EACCES: permission denied, lstat '<case>/R/locked/missing'"
        assert error('fail-closed', 1) == error('unreadable-entry')
    assert error('scripts-not-a-directory')['code'] == 'ENOTDIR'
    assert error('no-path')['message'] == 'spawn eeg-missing-python ENOENT'
    assert error('missing-python')['message'] == 'spawn <case>/missing/python ENOENT'
    assert error('nonexecutable-python')['code'] == error('directory-python')['code'] == 'EACCES'
    assert error('nul-in-entry')['code'] == error('nul-in-environment')['code'] == 'ERR_INVALID_ARG_VALUE'
    assert error('launcher-chain-too-large')['message'] == 'Python launcher link chain is too large'
    assert error('changed-during-inspection')['message'] == error('launcher-changed-during-inspection')['message'] \
        == '数值运行环境在检查期间发生变化'
    assert by_id['negative-entries']['create']['message'] == 'Invalid runtime cache limit'
    results = [step['outcomes'][0] for step in by_id['results']['steps']]
    assert {outcome['error']['message'] for outcome in results if not outcome['ok'] and 'message' in outcome['error']} \
        >= {'接收数值环境身份无效', '数值运行环境在检查期间发生变化', 'Cannot convert object to primitive value'}
    assert sum(not outcome['ok'] and outcome['error'] == {'name': 'SyntaxError'} for outcome in results) == 3
    assert {'schema': DIGEST_SCHEMA, 'sha256': ['a' * 64]} in [outcome.get('value') for outcome in results]
    pythonpath = [step['outcomes'][0]['value']['sha256'] for step in by_id['pythonpath']['steps']]
    assert pythonpath[0] == pythonpath[2] != pythonpath[1] == pythonpath[3]


# --- The real inspector -----------------------------------------------------------------------------------------

def _shadow_cortech(directory: Path) -> str:
    """A ``PYTHONPATH`` entry whose ``cortech`` (package and distribution) comes before the runtime's own, so the
    inspector's identity, and with it the digest, changes."""
    (directory / 'cortech').mkdir(parents=True)
    (directory / 'cortech/__init__.py').write_text('"""A package that shadows the runtime\'s cortech."""\n')
    info = directory / 'cortech-0.0.dist-info'
    info.mkdir()
    (info / 'METADATA').write_text('Metadata-Version: 2.1\nName: cortech\nVersion: 0.0\n')
    (info / 'RECORD').write_text('cortech/__init__.py,,\ncortech-0.0.dist-info/METADATA,,\n'
                                 'cortech-0.0.dist-info/RECORD,,\n')
    return str(directory)


@pytest.mark.native_runtime
@needs_node
def test_the_real_inspector_gives_nodes_digest(tmp_path, capsys):
    root = os.environ.get('EEG_KEY_PARITY_ROOT')
    if not root or not os.path.exists(native_python_path(root)):
        pytest.skip('EEG_KEY_PARITY_ROOT with the native runtime is required to run the real inspector')
    python = native_python_path(root)
    leak = _shadow_cortech(tmp_path / 'leak')
    base = {'base': 'process', 'unset': ['PYTHONPATH']}
    shadowed = {'base': 'process', 'set': {'PYTHONPATH': leak}}
    reads = [['read', {'root': root, 'env': env}] for env in (base, base, shadowed, shadowed)]
    case = {'id': 'real', 'dir': str(tmp_path / 'case'), 'steps': reads}
    node = run_driver([case], python, tmp_path)['by_id']['real']
    inspections = 0

    def inspect(python: str, root: str, env: dict):
        nonlocal inspections
        inspections += 1
        return runtime_digest.run_inspector(python, root, env)
    cache = RuntimeIdentityCache(inspect=inspect)
    ours = [run(cache(python, root, environment(env))) for env in (base, base, shadowed, shadowed)]
    values = [step['outcomes'][0] for step in node['steps']]
    assert all(outcome['ok'] for outcome in values), values
    assert [outcome['value'] for outcome in values] == ours
    assert ours[0] == ours[1] != ours[2] == ours[3]
    assert inspections == 2  # each environment inspected once, then reused
    with capsys.disabled():
        print(f"\nnumerical_runtime_sha256 {ours[0]['sha256']}; with a shadowing PYTHONPATH {ours[2]['sha256']}")
