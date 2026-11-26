"""Helpers for test_runtime_digest.py (``jobs.runtime_digest``, plan B15).

- ``Fixture`` is the fixture of webapp/scripts/check-runtime-identity-cache.mjs: a root with ``package/numerical.py``
  and an injected ``inspect`` that hashes the file (and ``CHOICE`` of the environment) and observes the folder and
  the file, counting its calls.
- ``STUB`` is a stand-in for the inspector scripts, run by a real interpreter: what it prints, writes to stderr,
  how it exits and what it observes come from ``R/stub/mode.json`` (``MODE``). Each run appends a line to
  ``<case>/inspections.log``, so both hosts count the inspector runs of their own memo.
- ``CASES`` are the parity cases: steps run in order on a case directory (``<case>``, with the root at
  ``<case>/R``), by ``parity/runtime_digest.mjs`` on Node's ``createRuntimeIdentityCache`` and by ``python_case``
  on ``RuntimeIdentityCache``. ``build`` lays out a case before either host runs it.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Optional

from eeglayoutlab.jobs import records
from eeglayoutlab.jobs.runtime_digest import DIGEST_SCHEMA, INSPECT_ENV, RuntimeIdentityCache
from eeglayoutlab.schemas import jsjson

from .key_parity_support import NODE_ENV

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'tests/service/parity/runtime_digest.mjs'
WATCH_SCHEMA = 'reception-runtime-watch/1'
EIGHT_MIB = 8 * 1024 * 1024


def hash_text(text: str | bytes) -> str:
    return hashlib.sha256(text.encode('utf-8') if isinstance(text, str) else text).hexdigest()


def stamp(path: str | Path, full: bool = True) -> str:
    info = os.lstat(path)
    values = [info.st_dev, info.st_ino, info.st_mode]
    if full:
        values += [info.st_size, info.st_mtime_ns, info.st_ctime_ns]
    return ':'.join(str(value) for value in values)


def observation(paths: list[str | Path]) -> dict:
    """``observation(paths)`` of the Node test: full stamps of each path."""
    return {'schema': WATCH_SCHEMA, 'entries': [[str(path), True, stamp(path)] for path in paths]}


def run(coroutine):
    return asyncio.run(coroutine)


class Fixture:
    """``fixture(t, options)`` of check-runtime-identity-cache.mjs."""

    def __init__(self, directory: Path, **options: Any):
        self.root = directory / 'eeg-runtime-watch'
        self.folder = self.root / 'package'
        self.folder.mkdir(parents=True)
        self.file = self.folder / 'numerical.py'
        self.file.write_text('version1', encoding='utf-8')
        self.calls = 0
        self.failure: Optional[BaseException] = None
        self.after_snapshot: Optional[Callable[[], None]] = None
        self.cache = RuntimeIdentityCache(inspect=self.inspect, **options)
        self.args = {'root': str(self.root), 'python': sys.executable, 'env': {}}

    def inspect(self, python: str, root: str, env: dict) -> dict:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        value = hash_text(self.file.read_text(encoding='utf-8') + (env.get('CHOICE') or ''))
        watch = observation([self.folder, self.file])
        if self.after_snapshot is not None:
            self.after_snapshot()
        return {'schema': DIGEST_SCHEMA, 'sha256': value, 'watch': watch}

    async def aread(self, **overrides: Any) -> dict:
        return await self.cache(**{**self.args, **overrides})

    def read(self, **overrides: Any) -> dict:
        return run(self.aread(**overrides))


# --- The stub inspector -----------------------------------------------------------------------------------------

STUB = '''\
"""Stub inspector (tests/service/runtime_digest_support.py): behaviour from stub/mode.json of its root."""
import hashlib, json, os, signal, sys, time

root = os.path.dirname(os.path.dirname(sys.argv[0]))
with open(os.path.join(root, '..', 'inspections.log'), 'a', encoding='utf-8') as log:
    log.write(os.path.basename(sys.argv[0]) + '\\n')
with open(os.path.join(root, 'stub', 'mode.json'), encoding='utf-8') as source:
    mode = json.load(source)


def stamp(path, full):
    try:
        info = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    values = [info.st_dev, info.st_ino, info.st_mode]
    if full:
        values += [info.st_size, info.st_mtime_ns, info.st_ctime_ns]
    return ':'.join(str(value) for value in values)


def fill(value):
    if isinstance(value, str):
        return value.replace('<root>', root)
    if isinstance(value, list):
        return [fill(item) for item in value]
    if isinstance(value, dict):
        return {key: fill(item) for key, item in value.items()}
    return value


if mode.get('stderr'):
    sys.stderr.write(mode['stderr'])
    sys.stderr.flush()
if mode.get('stderr_ff'):
    sys.stderr.buffer.write(b'\\xff' * mode['stderr_ff'])
    sys.stderr.flush()
if mode.get('close_outputs'):  # both outputs end, the process runs on
    os.close(1)
    os.close(2)
if mode.get('sleep'):
    time.sleep(mode['sleep'])
if 'raw' in mode:
    output = mode['raw'].encode('utf-8')
elif mode.get('flood'):
    output = b'x' * mode['flood']
else:
    parts = []
    for name in mode.get('hash', []):
        with open(os.path.join(root, name), encoding='utf-8') as source:
            parts.append(source.read())
    parts += [os.environ.get(name, '') for name in mode.get('env', [])]
    result = {'schema': 'reception-runtime-digest/1', 'sha256': hashlib.sha256('\\0'.join(parts).encode()).hexdigest()}
    if not mode.get('legacy'):
        entries = [[root + '/' + name, full, stamp(root + '/' + name, full)] for name, full in mode.get('watch', [])]
        result['watch'] = {'schema': 'reception-runtime-watch/1', 'entries': entries + fill(mode.get('extra', []))}
    result.update(fill(mode.get('override', {})))
    for action in mode.get('after', []):
        path = os.path.join(root, action[1])
        if action[0] == 'append':
            with open(path, 'a', encoding='utf-8') as target:
                target.write('x')
        elif action[0] == 'relink':
            os.remove(path)
            os.symlink(fill(action[2]), path)
    output = json.dumps(result).encode('utf-8')
    if mode.get('pad_to'):
        output += b' ' * (mode['pad_to'] - len(output))
sys.stdout.buffer.write(output)
sys.stdout.flush()
if mode.get('kill'):
    os.kill(os.getpid(), mode['kill'])
    time.sleep(10)
sys.exit(mode.get('exit', 0))
'''

MODE = {'hash': ['stub/numerical.txt'], 'env': ['CHOICE', 'PYTHONPATH'],
        'watch': [['stub/numerical.txt', True], ['stub', True]]}
SNAPSHOT = 'R/scripts/inspect_reception_runtime_snapshot.py'
LEGACY = 'R/scripts/inspect_reception_runtime.py'


def mode(**changes: Any) -> list:
    """The step that writes ``R/stub/mode.json``: ``MODE`` with ``changes`` (``None`` removes a member)."""
    value = {**MODE, **changes}
    return ['write', 'R/stub/mode.json', json.dumps({key: item for key, item in value.items() if item is not None})]


def stub_root(case: Path) -> None:
    """``<case>/R``: both inspector scripts (the stub), ``stub/mode.json`` (``MODE``) and ``stub/numerical.txt``."""
    for name in (SNAPSHOT, LEGACY):
        (case / name).parent.mkdir(parents=True, exist_ok=True)
        (case / name).write_text(STUB, encoding='utf-8')
    (case / 'R/stub').mkdir()
    (case / 'R/stub/numerical.txt').write_text('version1', encoding='utf-8')
    apply(case, mode(), sys.executable)


# --- Steps ------------------------------------------------------------------------------------------------------

def fill(value: Any, case: str, python: str) -> Any:
    """``<case>`` and ``<python>`` in every string of a step."""
    if isinstance(value, str):
        return value.replace('<case>', case).replace('<python>', python)
    if isinstance(value, list):
        return [fill(item, case, python) for item in value]
    if isinstance(value, dict):
        return {key: fill(item, case, python) for key, item in value.items()}
    return value


def plain(value: Any, case: str) -> Any:
    """The case directory as ``<case>`` in every string of a result."""
    if isinstance(value, str):
        return value.replace(case, '<case>')
    if isinstance(value, list):
        return [plain(item, case) for item in value]
    if isinstance(value, dict):
        return {key: plain(item, case) for key, item in value.items()}
    return value


def _at(case: Path, path: str) -> str:
    return path if path.startswith('/') else f'{case}/{path}'


def apply(case: Path, step: list, python: str) -> None:
    """One file step, as the driver's ``ops`` run it with ``fs/promises``."""
    op, *args = fill(step, str(case), python)
    if op == 'write':
        fd = os.open(_at(case, args[0]), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, args[2] if len(args) > 2 else 0o666)
        try:
            os.write(fd, args[1].encode('utf-8'))
        finally:
            os.close(fd)
    elif op == 'symlink':
        os.symlink(args[0], _at(case, args[1]))
    elif op == 'unlink':
        os.unlink(_at(case, args[0]))
    elif op == 'chmod':
        os.chmod(_at(case, args[0]), args[1])
    elif op == 'mkdir':
        os.makedirs(_at(case, args[0]), exist_ok=True)
    elif op == 'rename':
        os.rename(_at(case, args[0]), _at(case, args[1]))
    else:
        raise ValueError(f'unknown step {op}')


def describe(error: BaseException, case: str) -> dict:
    """A failure as the driver records Node's: a ``SyntaxError`` by name, others by name, message and code."""
    if isinstance(error, jsjson.JSONSyntaxError):
        return {'name': 'SyntaxError'}
    name = getattr(error, 'name', None)
    if not isinstance(name, str):
        name = 'TypeError' if isinstance(error, TypeError) else 'Error'
    return {'name': name, 'message': plain(records.node_message(error), case), 'code': getattr(error, 'code', None),
            'signal': getattr(error, 'signal', None), 'killed': getattr(error, 'killed', None)}


def runs(case: Path) -> int:
    try:
        return len([line for line in (case / 'inspections.log').read_text(encoding='utf-8').split('\n') if line])
    except FileNotFoundError:
        return 0


def environment(spec: Optional[dict]) -> Optional[dict]:
    if spec is None:
        return None
    from eeglayoutlab.jobs.runtime_digest import process_env
    value = {} if spec.get('base') == 'empty' else process_env()
    for name in spec.get('unset', []):
        value.pop(name, None)
    value.update(spec.get('set', {}))
    return value


async def python_case(case: dict, python: str) -> dict:
    """One case on ``RuntimeIdentityCache``, recorded as the driver records it."""
    directory = Path(case['dir'])
    out: dict = {'id': case['id'], 'steps': []}
    try:
        cache = RuntimeIdentityCache(**({'max_entries': case['maxEntries']} if 'maxEntries' in case else {}))
    except Exception as error:
        out['create'] = describe(error, case['dir'])
        return out
    try:
        for step in case['steps']:
            if step[0] != 'read':
                apply(directory, step, python)
                continue
            options = fill(step[1] if len(step) > 1 else {}, case['dir'], python)

            async def call() -> dict:
                try:
                    value = await cache(options.get('python', python), options.get('root', f"{case['dir']}/R"),
                                        environment(options.get('env')))
                    return {'ok': True, 'value': value}
                except Exception as error:
                    return {'ok': False, 'error': describe(error, case['dir'])}
            outcomes = await asyncio.gather(*(call() for _ in range(options.get('parallel', 1))))
            out['steps'].append({'outcomes': plain(list(outcomes), case['dir']), 'runs': runs(directory)})
    finally:
        cache.close()
    return out


def run_driver(cases: list[dict], python: str, scratch: Path, inspect_timeout_ms: Optional[int] = None) -> dict:
    """``parity/runtime_digest.mjs`` over ``cases``; its output with the cases by id."""
    spec = {'python': python, 'cases': cases}
    if inspect_timeout_ms is not None:
        spec['inspectTimeoutMs'] = inspect_timeout_ms
    spec_path, out_path = scratch / 'runtime-digest-spec.json', scratch / 'runtime-digest-node.json'
    spec_path.write_text(jsjson.stringify(spec), encoding='utf-8')
    subprocess.run(['node', str(DRIVER), str(spec_path), str(out_path)], check=True, cwd=ROOT, env=NODE_ENV,
                   timeout=900)
    output = json.loads(out_path.read_text(encoding='utf-8'))
    output['by_id'] = {case['id']: case for case in output['cases']}
    return output


# --- The parity cases -------------------------------------------------------------------------------------------

READ = ['read']
FRESH = ['write', 'R/stub/numerical.txt', 'version2']


def _read(**options: Any) -> list:
    return ['read', options]


def _path(*directories: str) -> dict:
    return {'base': 'empty', 'set': {'PATH': ':'.join(directories)}}


def _results() -> list:
    """Inspector results Node refuses or accepts: each read inspects anew (a refusal is never cached)."""
    bad = [
        {'override': {'schema': 'wrong'}}, {'override': {'schema': None}}, {'raw': '{"sha256": "' + 'a' * 64 + '"}'},
        {'override': {'sha256': 'A' * 64}}, {'override': {'sha256': 'a' * 63}}, {'override': {'sha256': 7}},
        {'override': {'sha256': None}}, {'override': {'sha256': 'a' * 64 + '\n'}}, {'override': {'sha256': {}}},
        {'override': {'sha256': {'toString': 'a' * 64}}}, {'override': {'sha256': [['a' * 32, 'b' * 31]]}},
        {'raw': 'null'}, {'raw': '[]'}, {'raw': '"' + 'a' * 64 + '"'}, {'raw': '7'},
        {'override': {'watch': None}}, {'override': {'watch': {}}}, {'override': {'watch': 1}},
        {'override': {'watch': {'schema': 'wrong', 'entries': [['/', False, None]]}}},
        {'override': {'watch': {'schema': WATCH_SCHEMA, 'entries': []}}},
        {'override': {'watch': {'schema': WATCH_SCHEMA, 'entries': {}}}},
        {'override': {'watch': {'schema': WATCH_SCHEMA, 'entries': [['/', False]]}}},
        {'override': {'watch': {'schema': WATCH_SCHEMA, 'entries': [['relative', False, None]]}}},
        {'override': {'watch': {'schema': WATCH_SCHEMA, 'entries': [['/', False, None], ['/', True, None]]}}},
        {'override': {'watch': {'schema': WATCH_SCHEMA, 'entries': [['/', 0, None]]}}},
        {'override': {'watch': {'schema': WATCH_SCHEMA, 'entries': [['/', False, 7]]}}},
        # JavaScript's \d is ASCII and its $ ends the input.
        {'override': {'watch': {'schema': WATCH_SCHEMA, 'entries': [['/', False, '١:2:3']]}}},
        {'override': {'watch': {'schema': WATCH_SCHEMA, 'entries': [['/', False, '1:2:3\n']]}}},
        {'override': {'watch': {'schema': WATCH_SCHEMA, 'entries': [['/', False, '1:2']]}}},
        {'override': {'watch': {'schema': WATCH_SCHEMA, 'entries': [['/', False, '1:2:3:4']]}}},
        {'override': {'watch': {'schema': WATCH_SCHEMA, 'entries': [['/', False, '-1:2:3']]}}},
        # Well formed but stale: changed during the inspection.
        {'override': {'watch': {'schema': WATCH_SCHEMA, 'entries': [['/', True, '1:2:3:4:-5:-6']]}}},
        {'override': {'watch': {'schema': WATCH_SCHEMA, 'entries': [['<root>/stub', False, '1:2:3']]}}},
        {'raw': 'not json'}, {'raw': ''}, {'raw': '﻿{}'},
    ]
    steps: list = []
    for changes in bad:
        steps += [mode(**changes), READ]
    # Accepted: String(['<64 hex>']) passes the test, and the array is the digest; extra members are ignored.
    # A cached result is reused until a watched file changes: FRESH makes the next read inspect again.
    steps += [mode(override={'sha256': ['a' * 64]}), READ, READ]
    steps += [mode(override={'extra': True}), FRESH, READ, READ]
    steps += [mode(raw='\n {"schema":"reception-runtime-digest/1","sha256":"' + 'b' * 64 + '"} \n'), FRESH, READ]
    return steps


def parity_cases() -> list[dict]:
    """``{id, steps, expect?, setup?, maxEntries?}``; ``expect`` is the run count after each read of Node's run."""
    launcher = [['mkdir', 'bin'], ['symlink', '<python>', 'bin/python']]
    many = ':'.join(f'<case>/d{index}' for index in range(5001))
    return [
        {'id': 'cached', 'steps': [READ, READ, FRESH, READ, READ], 'expect': [1, 1, 2, 2]},
        {'id': 'same-size', 'steps': [READ, ['write', 'R/stub/numerical.txt', 'version1'], READ], 'expect': [1, 2]},
        {'id': 'discovery', 'steps': [READ, ['write', 'R/stub/added.py', 'x'], READ, READ], 'expect': [1, 2, 2]},
        {'id': 'legacy', 'steps': [mode(legacy=True), READ, READ], 'expect': [1, 2]},
        {'id': 'fallback', 'steps': [['unlink', SNAPSHOT], READ, READ, FRESH, READ], 'expect': [1, 1, 2]},
        {'id': 'fallback-dangling-link',
         'steps': [['unlink', SNAPSHOT], ['symlink', 'missing.py', SNAPSHOT], READ, READ], 'expect': [1, 1]},
        {'id': 'snapshot-unreadable', 'steps': [['chmod', SNAPSHOT, 0], READ, ['chmod', SNAPSHOT, 0o644], READ]},
        {'id': 'snapshot-directory', 'steps': [['unlink', SNAPSHOT], ['mkdir', SNAPSHOT], READ], 'expect': [0]},
        {'id': 'no-scripts', 'steps': [['unlink', SNAPSHOT], ['unlink', LEGACY], READ, READ], 'expect': [0, 0]},
        {'id': 'scripts-not-a-directory', 'setup': [['rename', 'R/scripts', 'R/held'], ['write', 'R/scripts', '']],
         'steps': [READ], 'expect': [0]},
        {'id': 'exit', 'steps': [mode(stderr='broken runtime\n', exit=3), READ, READ], 'expect': [1, 2]},
        {'id': 'exit-after-output', 'steps': [mode(exit=1), READ], 'expect': [1]},
        {'id': 'signal', 'steps': [mode(stderr='dying\n', kill=9), READ], 'expect': [1]},
        {'id': 'results', 'steps': _results()},
        {'id': 'missing-entry', 'steps': [mode(extra=[['<root>/later', True, None], ['/\ud800x', False, None]]),
                                          READ, READ, ['write', 'R/later', ''], READ], 'expect': [1, 1, 2]},
        {'id': 'nul-in-entry', 'steps': [mode(extra=[['/a\u0000b', True, None]]), READ]},
        {'id': 'unreadable-entry', 'setup': [['mkdir', 'R/locked']],
         'steps': [mode(extra=[['<root>/locked/missing', True, None]]), ['chmod', 'R/locked', 0], READ,
                   ['chmod', 'R/locked', 0o755], READ, READ], 'expect': [1, 2, 2]},
        # A stamp that cannot be taken fails a cached entry's check (no new inspection), even after a difference.
        {'id': 'fail-closed', 'setup': [['mkdir', 'R/locked']],
         'steps': [mode(extra=[['<root>/locked/missing', True, None]]), READ, FRESH, ['chmod', 'R/locked', 0], READ,
                   ['chmod', 'R/locked', 0o755], READ], 'expect': [1, 1, 2]},
        {'id': 'changed-during-inspection',
         'steps': [mode(after=[['append', 'stub/numerical.txt']]), READ, mode(), READ, READ], 'expect': [1, 2, 2]},
        {'id': 'launcher-changed-during-inspection', 'setup': launcher,
         'steps': [mode(after=[['relink', '../bin/python', '<python>']]), _read(python='<case>/bin/python'),
                   mode(), _read(python='<case>/bin/python'), _read(python='<case>/bin/python')],
         'expect': [1, 2, 2]},
        {'id': 'launcher-link', 'setup': launcher,
         'steps': [_read(python='<case>/bin/python'), _read(python='<case>/bin/python'), ['unlink', 'bin/python'],
                   ['symlink', '<python>', 'bin/python'], _read(python='<case>/bin/python'),
                   ['unlink', 'bin/python'], ['mkdir', 'other'], ['symlink', '<python>', 'other/python'],
                   ['symlink', '../other/python', 'bin/python'], _read(python='<case>/bin/python'),
                   _read(python='<case>/bin/python')],
         'expect': [1, 1, 2, 3, 3]},
        # bin/python -> ../lib/python resolves through the directory link bin, not lexically to <case>/lib/python.
        {'id': 'launcher-link-through-a-directory-link',
         'setup': [['mkdir', 'real/sub/bin'], ['mkdir', 'real/sub/lib'], ['symlink', '<python>', 'real/sub/lib/python'],
                   ['symlink', '../lib/python', 'real/sub/bin/python'], ['symlink', '<case>/real/sub/bin', 'bin']],
         'steps': [_read(python='<case>/bin/python'), _read(python='<case>/bin/python'),
                   ['symlink', '<python>', 'real/sub/lib/python3'], ['unlink', 'real/sub/lib/python'],
                   ['symlink', 'python3', 'real/sub/lib/python'],
                   _read(python='<case>/bin/python'), _read(python='<case>/bin/python')],
         'expect': [1, 1, 2, 2]},
        {'id': 'path-search',
         'setup': [['mkdir', 'first'], ['mkdir', 'second'], ['symlink', '<python>', 'second/python']],
         'steps': [_read(python='python', env=_path('<case>/first', '<case>/second'))] * 2
         + [['symlink', '<python>', 'first/python'], _read(python='python', env=_path('<case>/first', '<case>/second')),
            ['unlink', 'first/python'], ['write', 'first/python', 'different executable', 0o644],
            _read(python='python', env=_path('<case>/first', '<case>/second')),
            _read(python='python', env=_path('<case>/first', '<case>/second'))],
         'expect': [1, 1, 2, 3, 3]},
        {'id': 'relative-python', 'setup': [['mkdir', 'R/bin'], ['symlink', '<python>', 'R/bin/python']],
         'steps': [_read(python='bin/python'), _read(python='bin/python')], 'expect': [1, 1]},
        {'id': 'relative-path-entry', 'setup': [['mkdir', 'R/bin'], ['symlink', '<python>', 'R/bin/python']],
         'steps': [_read(python='python', env=_path('bin')), _read(python='python', env=_path('bin'))],
         'expect': [1, 1]},
        {'id': 'empty-path-entry', 'setup': [['mkdir', 'second'], ['symlink', '<python>', 'second/python']],
         'steps': [_read(python='python', env=_path('', '<case>/second')),
                   _read(python='python', env=_path('', '<case>/second')),
                   ['symlink', '<python>', 'R/python'], _read(python='python', env=_path('', '<case>/second'))],
         'expect': [1, 1, 2]},
        {'id': 'no-path', 'steps': [_read(python='eeg-missing-python', env={'base': 'empty'})] * 2,
         'expect': [0, 0]},
        {'id': 'missing-python', 'steps': [_read(python='<case>/missing/python')], 'expect': [0]},
        {'id': 'directory-python', 'setup': [['mkdir', 'bin/python']], 'steps': [_read(python='<case>/bin/python')]},
        {'id': 'nonexecutable-python', 'setup': [['mkdir', 'bin'], ['write', 'bin/python', 'x', 0o644]],
         'steps': [_read(python='<case>/bin/python')], 'expect': [0]},
        {'id': 'no-shebang-python',
         'setup': [['mkdir', 'bin'], ['write', 'bin/python', 'printf \'{"schema":"reception-runtime-digest/1",'
                                     '"sha256":"%s"}\' ' + 'c' * 64 + '\n', 0o755]],
         'steps': [_read(python='<case>/bin/python'), _read(python='<case>/bin/python')]},
        {'id': 'timeout', 'steps': [mode(stderr='started\n', sleep=60), READ], 'expect': [1]},
        # The deadline, not the end of the outputs, decides: an inspector that closes both and runs on is stopped.
        {'id': 'outputs-closed', 'steps': [mode(stderr='started\n', close_outputs=True, sleep=60), READ],
         'expect': [1]},
        {'id': 'stdout-flood', 'steps': [mode(flood=EIGHT_MIB + 1), READ], 'expect': [1]},
        {'id': 'stdout-exactly-at-the-bound', 'steps': [mode(pad_to=EIGHT_MIB), READ], 'expect': [1]},
        {'id': 'stdout-over-the-bound', 'steps': [mode(pad_to=EIGHT_MIB + 1), READ], 'expect': [1]},
        # Invalid bytes count as U+FFFD, three bytes each after decoding: 2,796,203 of them pass 8 MiB.
        {'id': 'stderr-decoded-over-the-bound', 'steps': [mode(stderr_ff=2796203), READ], 'expect': [1]},
        {'id': 'stderr-decoded-at-the-bound', 'steps': [mode(stderr_ff=2796202), READ], 'expect': [1]},
        {'id': 'environments', 'steps': [
            *[_read(env={'base': 'process', 'set': {'CHOICE': str(n)}}) for n in (1, 2, 3, 4, 1, 5, 2, 1, 3)]],
         'expect': [1, 2, 3, 4, 4, 5, 6, 6, 7]},
        {'id': 'pythonpath', 'steps': [
            _read(env={'base': 'process', 'unset': ['PYTHONPATH']}),
            _read(env={'base': 'process', 'set': {'PYTHONPATH': '/eeg-runtime-digest/leak'}}),
            _read(env={'base': 'process', 'unset': ['PYTHONPATH']}),
            _read(env={'base': 'process', 'set': {'PYTHONPATH': '/eeg-runtime-digest/leak'}})], 'expect': [1, 2, 2, 2]},
        {'id': 'nul-in-environment', 'steps': [_read(env={'base': 'process', 'set': {'EEG_X': 'a\u0000b'}})],
         'expect': [0]},
        # Node's settings override the service's own values of those names, and the key is the merged environment's.
        {'id': 'inspector-settings', 'steps': [
            mode(env=list(INSPECT_ENV)), _read(env={'base': 'process', 'set': {name: '8' for name in INSPECT_ENV}}),
            _read(env={'base': 'process', 'set': {'OMP_NUM_THREADS': '4', 'PYTHONDONTWRITEBYTECODE': ''}}),
            _read(env={'base': 'process', 'unset': list(INSPECT_ENV)})], 'expect': [1, 1, 1]},
        {'id': 'zero-entries', 'maxEntries': 0, 'steps': [READ, READ], 'expect': [1, 2]},
        {'id': 'one-entry', 'maxEntries': 1.0,
         'steps': [_read(env={'base': 'process', 'set': {'CHOICE': choice}}) for choice in 'aaba'], 'expect': [1, 1, 2, 3]},
        {'id': 'negative-entries', 'maxEntries': -1, 'steps': []},
        {'id': 'fractional-entries', 'maxEntries': 1.5, 'steps': []},
        {'id': 'parallel', 'steps': [_read(parallel=12), _read(parallel=12), FRESH, _read(parallel=12)],
         'expect': [1, 1, 2]},
        {'id': 'launcher-chain-too-large',
         'steps': [_read(python='python', env={'base': 'empty', 'set': {'PATH': many}})], 'expect': [0]},
    ]


def build(directory: Path, cases: list[dict], python: str) -> list[dict]:
    """Lays out each case under ``directory`` and returns the cases with their ``dir``."""
    built = []
    for case in cases:
        path = directory / case['id']
        path.mkdir(parents=True)
        stub_root(path)
        for step in case.get('setup', []):
            apply(path, step, python)
        built.append({key: value for key, value in {**case, 'dir': str(path)}.items()
                      if key not in ('setup', 'expect')})
    return built
