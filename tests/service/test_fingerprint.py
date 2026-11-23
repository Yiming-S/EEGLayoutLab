"""Interpreter identity off macOS (plan B9): port of webapp/scripts/check-abuse-limits.mjs 'cache keys carry the
interpreter identity off macOS only', plus the probe text and the real subprocess path: execFileSync's non-zero
exit, 30 s timeout, 1 MiB maxBuffer (the child is killed when it passes), ignored stderr and, off macOS,
execvp's /bin/sh for a file without a ``#!`` line, checked against Node's own module with fake interpreters."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

import pytest

from eeglayoutlab.jobs import fingerprint
from eeglayoutlab.jobs.fingerprint import PROBE, python_fingerprint, runtime_identity
from eeglayoutlab.schemas import jsjson

from .key_parity_support import needs_node

NODE_SOURCE = Path(__file__).resolve().parents[2] / 'webapp/server/runtime/python-fingerprint.mjs'
FAKE = ('/opt/fake/python-a', '/opt/fake/python-b')


@pytest.fixture
def fresh_memo():
    # The memo lives for the process, as Node's; forget the fake interpreters around each test.
    for name in FAKE:
        fingerprint._memo.pop(name, None)
    yield
    for name in FAKE:
        fingerprint._memo.pop(name, None)


def test_probe_is_nodes():
    block = re.search(r"const PROBE = \[\n(.*?)\n\]\.join\('\\n'\);", NODE_SOURCE.read_text(encoding='utf-8'), re.S)
    assert block, 'the PROBE array moved in python-fingerprint.mjs'
    lines = []
    for line in block.group(1).split('\n'):
        literal = line.strip().removesuffix(',')
        assert literal[0] == literal[-1] == "'" and '\\' not in literal and "'" not in literal[1:-1]
        lines.append(literal[1:-1])
    assert '\n'.join(lines) == PROBE


def test_cache_keys_carry_the_interpreter_identity_off_macos_only(fresh_memo):
    calls = []

    def run(python, args):
        calls.append((python, args))
        return 'noise\n{"machine": "x86_64", "numpy": "2.1.0", "python": "3.11.9", "scipy": "1.14.1", "system": "Linux"}\n'

    value = python_fingerprint('/opt/fake/python-a', run)
    assert value == {'machine': 'x86_64', 'numpy': '2.1.0', 'python': '3.11.9', 'scipy': '1.14.1', 'system': 'Linux'}
    assert list(value) == ['machine', 'numpy', 'python', 'scipy', 'system']
    python_fingerprint('/opt/fake/python-a', run)
    assert len(calls) == 1 and calls[0] == ('/opt/fake/python-a', ['-I', '-c', PROBE])

    def fail(python, args):
        raise OSError('missing')

    assert python_fingerprint('/opt/fake/python-b', fail) == {'python': None}
    assert runtime_identity('/opt/fake/python-a', 'darwin') is None
    assert runtime_identity('/opt/fake/python-a', 'linux') == value


@pytest.mark.parametrize('output', ['', 'noise', '{"python": "3.11.9"}\nnoise\n', '{"python": NaN}'])
def test_unparseable_probe_output_gives_a_null_python(output, fresh_memo):
    assert python_fingerprint('/opt/fake/python-a', lambda python, args: output) == {'python': None}


def test_last_line_after_javascript_trim(fresh_memo):
    # trim() removes U+FEFF and U+2028 but not U+0085; Python's strip() would differ on both.
    output = 'noise\r\n{"python": "3.11.9"}\r\n\u2028\ufeff'
    assert python_fingerprint('/opt/fake/python-a', lambda python, args: output) == {'python': '3.11.9'}


def test_real_interpreters(tmp_path):
    value = python_fingerprint(sys.executable)
    assert list(value) == ['machine', 'numpy', 'python', 'scipy', 'system']
    assert value['python'] == platform.python_version() and value['system'] == platform.system()
    fake = tmp_path / 'python'
    fake.write_text('not an interpreter', encoding='utf-8')  # not executable
    assert python_fingerprint(str(fake)) == {'python': None}
    assert python_fingerprint(str(tmp_path / 'missing')) == {'python': None}


# --- execFileSync's contract, with real processes ----------------------------------------------------------------

LINE = '{"machine": "x86_64", "numpy": "2.1.0", "python": "3.11.9", "scipy": "1.14.1", "system": "Linux"}'
PARSED = {'machine': 'x86_64', 'numpy': '2.1.0', 'python': '3.11.9', 'scipy': '1.14.1', 'system': 'Linux'}


def _fake(directory: Path, name: str, body: str, shebang: bool = True) -> str:
    path = directory / name
    path.write_text(('#!/bin/sh\n' if shebang else '') + body, encoding='utf-8')
    path.chmod(0o755)
    return str(path)


def _flood(total: int) -> str:
    """A probe whose output, ending in the JSON line, is ``total`` bytes long."""
    return f'head -c {total - len(LINE) - 2} /dev/zero | tr "\\000" x\nprintf "\\n%s\\n" \'{LINE}\'\n'


def _fakes(directory: Path) -> dict[str, tuple[str, object]]:
    """Fake interpreters and the fingerprint Node gives each (python-fingerprint.mjs with execFileSync)."""
    return {
        'ok': (_fake(directory, 'ok', f"echo noise >&2\nprintf '%s\\n' '{LINE}'\n"), PARSED),
        # execFileSync throws on a non-zero exit, even after a valid line.
        'exit-1': (_fake(directory, 'exit-1', f"printf '%s\\n' '{LINE}'\nexit 1\n"), {'python': None}),
        'signal': (_fake(directory, 'signal', f"printf '%s\\n' '{LINE}'\nkill -9 $$\n"), {'python': None}),
        # maxBuffer is 1 MiB: output of exactly 1 MiB is read, one byte more fails the call.
        'one-mib': (_fake(directory, 'one-mib', _flood(1024 * 1024)), PARSED),
        'over-one-mib': (_fake(directory, 'over-one-mib', _flood(1024 * 1024 + 1)), {'python': None}),
        # More than 1 MiB and then no end: the child is killed as soon as the limit is passed.
        'flood': (_fake(directory, 'flood', 'head -c 8388608 /dev/zero\nexec sleep 30\n'), {'python': None}),
        # stderr is ignored: a message after the probe line does not become the last line.
        'late-stderr': (_fake(directory, 'late-stderr', f"printf '%s\\n' '{LINE}'\necho late >&2\n"), PARSED),
        # No #! line: glibc's execvp (libuv off macOS) runs the file with /bin/sh; macOS's posix_spawn fails.
        'no-shebang': (_fake(directory, 'no-shebang', f"printf '%s\\n' '{LINE}'\n", shebang=False),
                       {'python': None} if sys.platform == 'darwin' else PARSED),
    }


def test_fake_interpreters_follow_exec_file_sync(tmp_path):
    for name, (python, expected) in _fakes(tmp_path).items():
        assert python_fingerprint(python) == expected, name


def test_a_hung_interpreter_times_out(tmp_path, monkeypatch):
    # Node kills the probe after 30 s and records {python: null}; the line printed after the sleep is never read.
    monkeypatch.setattr(fingerprint, '_TIMEOUT_SECONDS', 0.5)
    python = _fake(tmp_path, 'slow', f"sleep 5\nprintf '%s\\n' '{LINE}'\n")
    started = time.monotonic()
    assert python_fingerprint(python) == {'python': None}
    assert time.monotonic() - started < 4


def test_a_flooding_interpreter_is_killed_at_the_limit(tmp_path, monkeypatch):
    # execFileSync kills the probe as soon as its output passes 1 MiB, so an interpreter that floods its output
    # never fills the memory. The fake writes 64 MiB and then waits: reading on to the end would take until the
    # timeout (and hold all 64 MiB).
    monkeypatch.setattr(fingerprint, '_TIMEOUT_SECONDS', 4)
    python = _fake(tmp_path, 'flooding', 'head -c 67108864 /dev/zero\nexec sleep 30\n')
    started = time.monotonic()
    assert python_fingerprint(python) == {'python': None}
    assert time.monotonic() - started < 2


def test_a_file_without_a_shebang_runs_with_sh_off_macos(tmp_path):
    python = _fake(tmp_path, 'plain', f"printf '%s\\n' '{LINE}'\n", shebang=False)
    assert fingerprint._run(python, [], platform='linux').strip() == LINE
    with pytest.raises(OSError):
        fingerprint._run(python, [], platform='darwin')


def _path_fakes(base: Path) -> dict[str, Path]:
    """Four directories with an entry named ``fakepy``: no ``#!`` line (a), a ``#!`` line (b), a file without the
    x bit (c), a directory (d). Each executable prints the probe line with its own label."""
    dirs = {}
    for label in 'abcd':
        dirs[label] = base / label
        dirs[label].mkdir()
    for label, shebang in (('a', False), ('b', True)):
        _fake(dirs[label], 'fakepy', f"printf '%s\\n' '{{\"python\": \"{label}\"}}'\n", shebang=shebang)
    (dirs['c'] / 'fakepy').write_text('#!/bin/sh\necho c\n', encoding='utf-8')
    (dirs['d'] / 'fakepy').mkdir()
    return dirs


# PATH entries (from _path_fakes, '' for an empty entry) and what glibc's execvp runs for the bare name fakepy.
PATH_CASES = {
    'a:b': {'python': 'a'},  # the first file it can execute, through /bin/sh
    'b:a': {'python': 'b'},
    'c:a': {'python': 'a'},  # EACCES (no x bit) is skipped
    'd:a': {'python': 'a'},  # EACCES (a directory) is skipped
    'c:d': {'python': None},
    ':b': {'python': 'a'},  # an empty entry is the working directory (a)
}


def _path_value(dirs: dict[str, Path], spec: str) -> str:
    return ':'.join(str(dirs[label]) if label else '' for label in spec.split(':'))


def test_bare_names_are_searched_as_execvp_does_off_macos(tmp_path, monkeypatch):
    dirs = _path_fakes(tmp_path)
    monkeypatch.chdir(dirs['a'])
    for spec, expected in PATH_CASES.items():
        monkeypatch.setenv('PATH', _path_value(dirs, spec))
        try:
            output = fingerprint._run('fakepy', [], platform='linux')
            value = jsjson.parse(jsjson.js_trim(output).split('\n')[-1])
        except OSError:
            value = {'python': None}
        assert value == expected, spec


@needs_node
@pytest.mark.skipif(sys.platform == 'darwin', reason="Node spawns with posix_spawn on macOS, where keys carry no fingerprint")
def test_bare_names_match_node(tmp_path, monkeypatch):
    dirs = _path_fakes(tmp_path)
    node = shutil.which('node')
    script = ("import { pythonFingerprint } from " + json.dumps(NODE_SOURCE.as_uri()) + ";\n"
              "console.log(JSON.stringify(pythonFingerprint('fakepy')));")
    for spec, expected in PATH_CASES.items():
        path = _path_value(dirs, spec)
        output = subprocess.run([node, '--input-type=module', '-e', script], check=True, capture_output=True, text=True,
                                cwd=dirs['a'], env={**os.environ, 'PATH': path}).stdout
        assert json.loads(output) == expected, spec
        fingerprint._memo.pop('fakepy', None)
        monkeypatch.chdir(dirs['a'])
        monkeypatch.setenv('PATH', path)
        assert python_fingerprint('fakepy') == expected, spec
    fingerprint._memo.pop('fakepy', None)


@needs_node
def test_fake_interpreters_match_node(tmp_path):
    fakes = _fakes(tmp_path)
    script = ("import { pythonFingerprint } from " + json.dumps(NODE_SOURCE.as_uri()) + ";\n"
              "console.log(JSON.stringify(process.argv.slice(1).map((python) => pythonFingerprint(python))));")
    output = subprocess.run(['node', '--input-type=module', '-e', script, *(python for python, _ in fakes.values())],
                            check=True, capture_output=True, text=True).stdout
    node = dict(zip(fakes, json.loads(output)))
    assert node == {name: expected for name, (_, expected) in fakes.items()}
    assert {name: python_fingerprint(python) for name, (python, _) in fakes.items()} == node
