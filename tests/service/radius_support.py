"""The radius run path's test helpers (test_radius.py, tests/service/README.md).

``FakeChild`` and ``Spawner`` are check-local-compute.mjs's ``fakeSpawner()`` for ``jobs.worker``'s ``spawn`` hook:
no pid, signals recorded, the streams written by the test. ``PinnedClock`` and ``PinnedIds`` replace ``Date`` and
the job identifiers as ``parity/radius_run.mjs`` pins them in Node.

The parity of the run path: ``parity_cases`` builds the case roots and scripts, ``run_node`` runs Node's own
``LocalComputeQueue`` over them, and ``run_python`` runs ``RadiusJobs`` over the same steps (the module docstring of
``parity/radius_run.mjs`` defines them). Each root is built again at the same path for Python, so the bytes
written, messages with paths included, can be compared as they are.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable, Optional

from eeglayoutlab.jobs.integrity import BANK_POINTER
from eeglayoutlab.jobs.radius import MAX_OUTPUT_BYTES, WORKER_ENV, WORKER_SCRIPT, RadiusJobs, code_identity
from eeglayoutlab.jobs.worker import WorkerError
from eeglayoutlab.schemas import jsjson

from .key_parity_support import NODE_ENV
from .library_support import RADIUS_REQUESTS, code_tree, forward_inputs, radius_result, sha, write

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'tests/service/parity/radius_run.mjs'
SETTLE = 20.0  # seconds any wait may take under load before the test fails
REQUEST = {'region_count': 2, 'radius_mm': 35, 'mode': 'preset', 'mask_codes': ['PL', 'PR']}
OTHER = {**REQUEST, 'radius_mm': 40}
# 2026-11-23T08:00:00.000Z, then 1.5 s per `new Date()`.
CLOCK = {'start': 1795420800000, 'step': 1500}
TIMEOUT_CASE_MS = 2000


# --- Fakes -----------------------------------------------------------------------------------------------------

class FakeChild:
    """``fakeSpawner()``'s child: no pid, kills recorded, stdin collected, streams written by the test."""

    pid = None

    def __init__(self, worker: Any, executable: str, args: list, options: dict):
        self.worker, self.executable, self.args, self.options = worker, executable, args, options
        self.kills: list[str] = []
        self.inputs: list[bytes] = []

    def kill(self, name: str) -> None:
        self.kills.append(name)

    def end_input(self, data: bytes) -> None:
        self.inputs.append(data)

    def resume(self) -> None:
        pass

    def abandon(self) -> tuple:
        return None, None

    # child.stdout.write, child.stderr.write, child.emit('error'), child.stdin.emit('error'), child.emit('close')
    def stdout(self, data: bytes | str) -> None:
        self.worker.feed_stdout(data.encode() if isinstance(data, str) else data)

    def stderr(self, data: bytes | str) -> None:
        self.worker.feed_stderr(data.encode() if isinstance(data, str) else data)

    def error(self, message: str) -> None:
        self.worker.feed_error(WorkerError(message))

    def stdin_error(self, message: str, code: Optional[str] = None) -> None:
        self.worker.feed_stdin_error(WorkerError(message, code))

    def close(self, code: Optional[int] = None, signal: Optional[str] = None) -> None:
        self.worker.feed_close(code, signal)

    def complete(self, result: Any) -> None:
        """``complete(child, result)`` of check-local-compute.mjs."""
        self.stdout(jsjson.stringify({'type': 'result', 'result': result}) + '\n')
        self.close(0)


class Spawner:
    """``fakeSpawner()``: one ``FakeChild`` per spawn; ``throw`` makes every spawn raise (Node's throwing
    ``spawnProcess``)."""

    def __init__(self, throw: Optional[str] = None, children: Optional[list] = None):
        self.throw = throw
        self.children: list[FakeChild] = children if children is not None else []

    def __call__(self, worker: Any, executable: str, args: list, options: dict) -> FakeChild:
        if self.throw is not None:
            raise RuntimeError(self.throw)
        child = FakeChild(worker, executable, args, options)
        self.children.append(child)
        return child


class PinnedClock:
    """``Date.now()`` that is ``start + step * n`` at its n-th call."""

    def __init__(self, start: int, step: int):
        self.start, self.step, self.calls = start, step, 0

    def __call__(self) -> int:
        value = self.start + self.step * self.calls
        self.calls += 1
        return value


class PinnedIds:
    """Job identifiers ``00000000-0000-4000-8000-<n>`` from n = 1, as the Node driver pins them."""

    def __init__(self):
        self.count = 0

    def __call__(self) -> str:
        self.count += 1
        return f'00000000-0000-4000-8000-{self.count:012d}'


async def until(check: Callable[[], bool], limit: float = SETTLE) -> None:
    deadline = time.monotonic() + limit
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError('the radius run did not settle')
        await asyncio.sleep(0.005)


def make_jobs(root: Path, spawn: Any, **options: Any) -> RadiusJobs:
    """``makeQueue()`` of check-local-compute.mjs: a fixed (empty) code identity unless one is given."""
    options.setdefault('get_identity', lambda: {})
    options.setdefault('timeout_ms', 3000)
    return RadiusJobs(str(root), 'python3', spawn=spawn, **options)


# --- Scripts ---------------------------------------------------------------------------------------------------

def b64(data: bytes | str) -> str:
    return base64.b64encode(data.encode('utf-8') if isinstance(data, str) else data).decode('ascii')


def line(value: Any) -> bytes:
    return (jsjson.stringify(value) + '\n').encode('utf-8')


def result_for(config: dict = REQUEST, **members: Any) -> dict:
    """``resultFor(config)`` of check-local-compute.mjs, with extra members (``provenance``)."""
    xyz = [[i * 5.0, 0.0, 0.0] for i in range(64)]
    regions = config['region_count']
    return {'status': 'completed', 'request': config,
            'layout': {'id': 'fixture', 'xyzMm': xyz, 'referenceXyzMm': xyz,
                       'regionIndices': [min(regions - 1, i * regions // 64) for i in range(64)]},
            'geometry': {'union_connected_component_count': regions, 'common_graph_radius_mm': config['radius_mm'],
                         'union_area_cm2': 30},
            'metrics': {'field_relative': 0.8, 'sensitivity_tail': 0.3, 'localization_relative': 0.5,
                        'conditional_global': 0.3},
            **members}


def bare_root(root: Path) -> None:
    """A root with the radius worker and the bank pointer (health ``available``); the code identity is fixed."""
    write(root, WORKER_SCRIPT, 'worker')
    write(root, BANK_POINTER, '{}')


def code_root(root: Path) -> dict:
    """A root with the radius code, the data-prior files and the forward inputs; returns the provenance its
    results carry (``InputIntegrity.verify`` accepts it, ``code_sha256`` is the code identity)."""
    code_tree(root)
    provenance = forward_inputs(root)
    return {**provenance, 'code_sha256': code_identity(str(root))}


BUILDERS: dict[str, Callable[[Path], Any]] = {'bare': bare_root, 'code': code_root}
CODE = {WORKER_SCRIPT: sha('worker'), 'src/compact_eeg/a.py': sha('a.py')}


def _progress_lines() -> list[str]:
    """Progress events whose members ``Number``, ``String`` and ``||`` convert, logs and odd JSON, as chunks."""
    long_log = 'x' * 1999 + '\U0001F600' + 'tail'  # the 2,000-unit cut leaves a lone high surrogate
    chunks = [
        line({'type': 'progress', 'progress': '0.125', 'stage': 0, 'message': ''}),
        line({'type': 'progress', 'progress': [0.25], 'stage': ['geo', ['metry']], 'message': {'a': 1}}),
        b'{"type":"progress","progress":-1e400,"stage":1e21,"message":1e400}\n',
        line({'type': 'progress', 'progress': None, 'stage': True, 'message': False}),
        line({'type': 'progress', 'progress': ' 0x10 ', 'stage': '加载', 'message': '载入头模'}),
        b'\n   \t\nnot json\n[1,2]\n"text"\n',
        b'{"type":"progress","progress":0.75,"type":"other"}\n',
        b'{"__proto__":{"x":1},"type":"note","2":"b","1":"a","big":123456789012345678901234567890,'
        b'"zero":-0,"one":1.0,"small":1e-7,"lone":"\\ud800"}\n',
        (long_log + '\n').encode('utf-8'),
        b'\xff\xfe{"type":"x"}\n',
    ]
    # A progress line cut inside a three-byte character, and one cut between its members.
    split = line({'type': 'progress', 'progress': 0.5, 'stage': 'geometry', 'message': '真实检查'})
    cut = split.index('真'.encode()) + 1
    chunks += [split[:cut], split[cut:], b'{"type":"progress","progress":0.6', b',"stage":"optimize"}\n']
    return [b64(chunk) for chunk in chunks]


def _stderr_chunks() -> list[str]:
    # The 16,000-unit tail starts inside the surrogate pair: a lone low surrogate, which JSON.stringify escapes.
    text = ('警告：' * 100 + '\U0001F600' + 'e' * 15999).encode('utf-8')
    cut = text.index('\U0001F600'.encode()) + 2
    return [b64('warning: 中文\n'.encode()[:11]), b64('warning: 中文\n'.encode()[11:]), b64(text[:cut]), b64(text[cut:])]


def parity_cases(base: Path) -> list[dict]:
    """The cases of the run-path parity; each root is ``base/<id>/root``, built for the Node run."""
    cases: list[dict] = []

    def case(id: str, steps: list, *, root: str = 'bare', identity: Any = CODE, timeout_ms: int = 3000,
             throw: Optional[str] = None) -> None:
        cases.append({'id': id, 'build': root, 'root': str(base / id / 'root'), 'python': 'python3',
                      'timeoutMs': timeout_ms, 'identity': identity, 'throw': throw, 'clock': CLOCK, 'steps': steps})

    def result_line(result: Any) -> list:
        return ['stdout', b64(line({'type': 'result', 'result': result}))]

    worker_code = {'code_sha256': {WORKER_SCRIPT: sha('worker')}}
    case('completed', [
        ['health'], ['submit', REQUEST], ['submit', REQUEST], ['submit', OTHER], ['health'], ['pid'],
        # A view after every chunk: progress, stage and message as each event leaves them.
        *(step for chunk in _progress_lines() for step in (['stdout', chunk], ['view'])),
        *(['stderr', chunk] for chunk in _stderr_chunks()),
        # The last line has no newline: it counts at the close.
        ['stdout', b64(jsjson.stringify({'type': 'result', 'result': result_for(provenance=worker_code)}))],
        ['close', 0, None], ['view'], ['settle'], ['view'], ['health'],
        ['submit', REQUEST], ['lookup', REQUEST], ['lookup', OTHER], ['lookup', {'radius_mm': 35}],
        ['restart', {}], ['lookup', {**REQUEST, 'mask_codes': ['PL', 'PR']}], ['submit', REQUEST], ['view'],
        ['restart', {'identity': {'version': 'changed'}, 'throw': 'expected new calculation'}],
        ['submit', REQUEST], ['settle'], ['view'],
    ])
    case('no-layout', [
        ['submit', REQUEST], result_line({'status': 'no_layout', 'request': REQUEST, 'layout': None, 'metrics': None}),
        ['close', 0, None], ['settle'], ['view'], ['health'], ['submit', REQUEST],
        ['restart', {}], ['submit', REQUEST],
    ])
    case('worker-failure', [
        ['submit', REQUEST], ['stderr', b64('Traceback (most recent call last):\n  ValueError: 失败\n')],
        ['stdout', b64(line({'type': 'error', 'code': 'compute_error', 'message': '失败'}))],
        ['close', 1, None], ['settle'], ['view'],
        ['submit', REQUEST], ['error', 'spawn python3 EACCES'], ['error', 'spawn python3 ENOENT'],
        ['close', -2, None], ['settle'], ['view'],
        ['submit', REQUEST], result_line(result_for()), ['close', 1, None], ['settle'], ['view'],
        ['submit', REQUEST], result_line({**result_for(), 'status': 'failed'}), ['close', 0, None], ['settle'],
        ['view'],
        ['submit', REQUEST], ['stdout', b64(line({'type': 'result'}))], ['close', 0, None], ['settle'], ['view'],
    ])
    case('spawn-throws', [['submit', REQUEST], ['view'], ['settle'], ['view']], throw='spawn EINVAL')
    case('invalid-result', [
        ['submit', REQUEST], result_line(result_for(OTHER)), ['close', 0, None], ['settle'], ['view'],
        ['submit', REQUEST], result_line({**result_for(), 'layout': None}), ['close', 0, None], ['settle'],
        ['view'],
        ['submit', REQUEST], result_line({**result_for(), 'request': {'command': 'bad'}}), ['close', 0, None],
        ['settle'], ['view'],
        ['submit', REQUEST], result_line(result_for(provenance={'code_sha256': {WORKER_SCRIPT: sha('old')}})),
        ['close', 0, None], ['settle'], ['view'],
        ['submit', REQUEST], result_line(result_for(provenance={'code_sha256': {'__proto__': 'x'}})),
        ['close', 0, None], ['settle'], ['view'],
        ['submit', REQUEST], result_line(result_for(provenance={'code_sha256': 'ab'})), ['close', 0, None],
        ['settle'], ['view'],
        ['submit', REQUEST], result_line(result_for(provenance={'code_sha256': [CODE[WORKER_SCRIPT]]})),
        ['close', 0, None], ['settle'], ['view'],
        ['submit', REQUEST], result_line(result_for(provenance={'code_sha256': 7})), ['close', 0, None],
        ['settle'], ['view'],
    ])
    # The progress line must arrive before the timer fires: Python arms it a few loop iterations before submit
    # returns (Node within the same turn), so the limit is far above any stall of the loop under load.
    case('timeout', [
        ['submit', REQUEST], ['stdout', b64(line({'type': 'progress', 'progress': 0.4, 'stage': 'geometry'}))],
        ['wait_kill'], ['view'], ['stdout', b64(line({'type': 'progress', 'progress': 0.9, 'stage': 'late'}))],
        ['close', None, 'SIGTERM'], ['settle'], ['view'],
    ], timeout_ms=TIMEOUT_CASE_MS)
    case('cancel', [
        ['submit', REQUEST], ['stdout', b64(line({'type': 'progress', 'progress': 0.3}))], ['cancel', None],
        ['cancel', None], ['view'], ['submit', OTHER], ['health'],
        ['stdout', b64(line({'type': 'progress', 'progress': 0.8, 'stage': 'late'}))], result_line(result_for()),
        ['close', None, 'SIGTERM'], ['settle'], ['view'], ['cancel', None],
        ['cancel_id', '00000000-0000-4000-8000-000000000099'], ['cancel_id', 'not an id'],
        ['submit', REQUEST], ['cancel', 'shutdown'], ['view'], ['close', 0, None], ['settle'], ['view'],
    ])
    case('input-error', [
        ['submit', REQUEST], ['stdin_error', 'write EPIPE', 'EPIPE'], ['view'], ['close', None, 'SIGTERM'],
        ['settle'], ['view'],
    ])
    case('output-limit', [
        ['submit', REQUEST], ['stdout', b64(line({'type': 'progress', 'progress': 0.2}))],
        ['stdout_fill', MAX_OUTPUT_BYTES + 1], ['view'], ['close', None, 'SIGTERM'], ['settle'], ['view'],
    ])
    case('dispose', [
        ['submit', REQUEST], ['dispose'], ['view'], ['submit', OTHER], ['close', None, 'SIGTERM'], ['settle'],
        ['view'],
    ])
    case('store-failure', [
        ['submit', REQUEST], ['rm_batch'], result_line(result_for()), ['close', 0, None], ['settle'], ['view'],
        ['submit', REQUEST], ['block_cache'], result_line(result_for()), ['close', 0, None], ['settle'], ['view'],
        ['lookup', REQUEST],
    ])
    case('normalized-requests', [
        ['submit', {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface', 'mask_codes': []}], ['view'],
        ['submit', {**REQUEST, 'AR': 0.9}], ['lookup', None],
        result_line({'status': 'no_layout', 'request': {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface'},
                     'layout': None}),
        ['close', 0, None], ['settle'], ['view'],
    ])
    # Node's own identity, runtime and input check on a root with the code and the forward inputs.
    case('code-root', [
        ['health'], ['submit', RADIUS_REQUESTS['prior']], ['stdout', 'PROVENANCE'], ['close', 0, None],
        ['settle'], ['view'], ['restart', {}], ['submit', RADIUS_REQUESTS['prior']], ['view'],
        ['submit', REQUEST], result_line(result_for()), ['close', 0, None], ['settle'], ['submit', REQUEST],
        ['lookup', REQUEST],
    ], root='code', identity=None)
    return cases


def build(case: dict) -> None:
    """Builds the case's root (again, at the same path, for the second run) and fills in its provenance."""
    root = Path(case['root'])
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    provenance = BUILDERS[case['build']](root)
    for step in case['steps']:
        if step == ['stdout', 'PROVENANCE']:
            step[1] = b64(line({'type': 'result', 'result': radius_result(
                RADIUS_REQUESTS['prior'], provenance)}))


# --- Runs ------------------------------------------------------------------------------------------------------

def _message(error: BaseException) -> str:
    message = getattr(error, 'message', None)
    return message if isinstance(message, str) else str(error)


async def run_case(item: dict) -> dict:
    """The Python side of one case: ``RadiusJobs`` driven by the steps the Node driver runs."""
    clock, ids = PinnedClock(**item['clock']), PinnedIds()
    records: list[list[str]] = []
    children: list[FakeChild] = []

    def make(options: dict) -> RadiusJobs:
        identity = options['identity'] if 'identity' in options else item['identity']
        thrown = options['throw'] if 'throw' in options else item['throw']
        return RadiusJobs(item['root'], item['python'], timeout_ms=item['timeoutMs'],
                          spawn=Spawner(thrown, children),
                          get_identity=(lambda: identity) if identity is not None else None,
                          clock=clock, random_uuid=ids)

    jobs, current = make({}), None

    async def record(kind: str, run: Callable[[], Any]) -> Any:
        try:
            value = run()
            if asyncio.iscoroutine(value):
                value = await value
            records.append([kind, jsjson.stringify(value)])
            return value
        except Exception as error:  # noqa: BLE001 - recorded as Node records a throw
            records.append([kind, jsjson.stringify({'error': _message(error)})])
            return None

    for kind, *args in item['steps']:
        child = children[-1] if children else None
        if kind == 'submit':
            value = await record(kind, lambda: jobs.submit(args[0]))
            if isinstance(value, dict) and 'job' in value:
                current = value['job']['id']
        elif kind == 'lookup':
            await record(kind, lambda: jobs.lookup(args[0]))
        elif kind == 'view':
            await record(kind, lambda: jobs.view(jobs.jobs[current]))
        elif kind == 'health':
            await record(kind, lambda: {k: v for k, v in jobs.health().items() if k != 'token'})
        elif kind == 'pid':
            await record(kind, jobs.active_pid)
        elif kind == 'cancel':
            await record(kind, lambda: jobs.cancel(current) if args[0] is None else jobs.cancel(current, args[0]))
        elif kind == 'cancel_id':
            await record(kind, lambda: jobs.cancel(args[0]))
        elif kind == 'dispose':
            jobs.dispose()
        elif kind == 'restart':
            jobs.dispose()
            jobs = make(args[0])
        elif kind == 'stdout':
            child.stdout(base64.b64decode(args[0]))
        elif kind == 'stdout_fill':
            child.stdout(b' ' * args[0])
        elif kind == 'stderr':
            child.stderr(base64.b64decode(args[0]))
        elif kind == 'error':
            child.error(args[0])
        elif kind == 'stdin_error':
            child.stdin_error(args[0], args[1])
        elif kind == 'close':
            child.close(args[0], args[1])
        elif kind == 'wait_kill':
            await until(lambda: bool(children[-1].kills))
        elif kind == 'settle':
            await until(lambda: jobs.active is None)
        elif kind == 'rm_batch':
            shutil.rmtree(jobs.jobs[current].batch)
        elif kind == 'block_cache':
            os.mkdir(os.path.join(os.path.dirname(jobs.jobs[current].batch), 'cache.json'))
        else:
            raise ValueError(f'unknown step {kind}')
    await until(lambda: jobs.active is None)
    jobs.dispose()
    return {
        'id': item['id'], 'records': records, 'clock': clock.calls, 'ids': ids.count,
        'children': [{
            'executable': c.executable, 'args': c.args, 'cwd': c.options['cwd'], 'stdio': c.options['stdio'],
            'detached': c.options['detached'], 'shell': c.options['shell'],
            'env': {name: c.options['env'].get(name) for name in WORKER_ENV},
            'inherits': all(name in WORKER_ENV or c.options['env'].get(name) == value
                            for name, value in os.environ.items()),
            'input': b64(b''.join(c.inputs)), 'kills': c.kills,
        } for c in children],
    }


def run_python(case: dict) -> dict:
    return asyncio.run(run_case(case))


def run_node(cases: list[dict], scratch: Path) -> dict:
    spec_path, out_path = scratch / 'radius-run-spec.json', scratch / 'radius-run-node.json'
    spec = {'queueDirectory': str(scratch / 'node-queue'),
            'cases': [{k: v for k, v in case.items() if k != 'build'} for case in cases]}
    spec_path.write_text(jsjson.stringify(spec), encoding='utf-8')
    subprocess.run(['node', str(DRIVER), str(spec_path), str(out_path)], check=True, cwd=ROOT, env=NODE_ENV,
                   timeout=600)
    return json.loads(out_path.read_text(encoding='utf-8'))


def record_tree(root: Path) -> dict[str, Any]:
    """Every directory (``None``) and file (its bytes) under ``results/v2/local_app_jobs``, by relative path."""
    base = root / 'results/v2/local_app_jobs'
    tree: dict[str, Any] = {}
    for directory, names, files in os.walk(base):
        for name in names:
            tree[os.path.relpath(os.path.join(directory, name), base)] = None
        for name in files:
            path = os.path.join(directory, name)
            tree[os.path.relpath(path, base)] = Path(path).read_bytes()
    return tree
