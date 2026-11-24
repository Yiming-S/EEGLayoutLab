"""The design-evaluation run path's test helpers (test_design.py, tests/service/README.md).

``REQUEST``, ``baseline_result`` and ``perturbation`` are check-design-decision.mjs's fixtures, ``robust_result``
check-design-robustness.mjs's; ``Fixture`` is check-design-decision.mjs's ``fixture()``: a service whose context is
the stub ``{identity: {version}, key}`` and whose children are ``radius_support.FakeChild``. ``FAKE_WORKER`` is a
stand-in for ``scripts/design_evaluation.py`` that answers any canonical request with a result its validator accepts
(the design's ``name`` picks another behaviour: ``fail``, ``hold``, ``stale``).

The parity of the run path: ``parity_cases`` builds the case roots (``key_parity_support.design_root``, so the
context is the scientific one on both sides) and scripts, ``run_node`` runs Node's own ``DesignEvaluationService``
over them (``parity/design_run.mjs``) and ``run_python`` runs ``DesignJobs`` over the same steps. Each root is built
again at the same path for Python, so the bytes written, messages with paths included, can be compared as they are.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Callable, Optional

from eeglayoutlab.jobs.design import MAX_OUTPUT_BYTES, WORKER_ENV, WORKER_SCRIPT, DesignJobs
from eeglayoutlab.jobs.records import node_message
from eeglayoutlab.jobs.runtime import runtime_config
from eeglayoutlab.schemas import jsjson

from .key_parity_support import NODE_ENV, PRIOR, SPATIAL, design_root, digest
from .library_support import robustness_block
from .radius_support import FakeChild, PinnedClock, PinnedIds, Spawner, b64, line, until

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'tests/service/parity/design_run.mjs'
SETTLE = 20.0
HOLD = 120  # seconds a held fake worker waits; it is always stopped before that
# 2026-11-23T08:00:00.000Z, then 1.5 s per `new Date()`.
CLOCK = {'start': 1795420800000, 'step': 1500}
TIMEOUT_CASE_MS = 2000
ADMISSION_POINTER = 'results/v2/current_surface_admissibility.json'
# design_root's admission pointer: what a result's provenance must record.
ADMISSION = {'surface_admissibility_sha256': digest('mask'), 'surface_admissibility_version': 'native-external-exposure/1'}

# --- check-design-decision.mjs and check-design-robustness.mjs ------------------------------------------------------

DESIGN = {'schema': 'eeg-electrode-design/1', 'coordinate_system': 'ernie_native_mm', 'unit': 'mm', 'name': 'test',
          'xyz_mm': [[(i % 8) * 6, (i // 8) * 6, 0] for i in range(64)],
          'region_indices': [int(i >= 32) for i in range(64)]}
REQUEST = {'action': 'evaluate', 'design': DESIGN, 'radius_mm': 6, 'seed': 42}
OTHER = {**REQUEST, 'seed': 43}
SEVEN = {**REQUEST, 'seed': 7}
PERTURB = {**REQUEST, 'action': 'perturb'}
ROBUST = {**REQUEST, 'robustness': 'standard/1'}
NOMINAL = {'field_relative': 1, 'field_absolute': 0.9, 'reference_field_absolute': 0.9, 'sensitivity_tail': 1,
           'localization_relative': 1, 'median_mm': 10, 'p90_mm': 20, 'reference_median_mm': 10, 'reference_p90_mm': 20}


def canonical(raw: Any) -> dict:
    """``normalizeDesignRequest(raw)`` (the phase 1 schema; Pydantic)."""
    from eeglayoutlab.jobs.design_result import normalize_design_request

    return normalize_design_request(raw)


def baseline_result(request: Any = REQUEST, **members: Any) -> dict:
    """``baselineResult()`` of check-design-decision.mjs, for ``request``, with members replaced or added."""
    return {'schema': 'design-evaluation/1', 'status': 'completed', 'request': request, 'forward_mode': 'cached_fem',
            'nominal': dict(NOMINAL), 'projection_max_mm': 0, 'evaluated_xyz_mm': DESIGN['xyz_mm'],
            'provenance': {'candidate_count': 64}, 'trials': [], **members}


def perturbation(position: int, **members: Any) -> dict:
    """Trial ``position`` of check-design-decision.mjs:330's perturbation result, with members replaced."""
    return {'index': position, 'status': 'completed', 'xyz_mm': DESIGN['xyz_mm'], 'requested_xyz_mm': DESIGN['xyz_mm'],
            'region_indices': DESIGN['region_indices'], 'actual_max_mm': 0, 'actual_mean_mm': 0,
            'candidate_bank_indices': list(range(64)), 'unchanged_fraction': 1, 'minimum_chord_distance_mm': 6,
            'target_error_max_mm': 0, 'field_relative': 1, 'fixed_estimator_field_relative': 1, **members}


ROBUST_NOMINAL = {'field_relative': 0.9, 'field_absolute': 0.81, 'reference_field_absolute': 0.9,
                  'sensitivity_tail': 0.8, 'localization_relative': 0.7, 'median_mm': 5, 'p90_mm': 12,
                  'reference_median_mm': 4, 'reference_p90_mm': 10}


def robust_result(request: dict, robustness: Optional[dict] = None) -> dict:
    """``result(req, robustness)`` of check-design-robustness.mjs."""
    result = {'schema': 'design-evaluation/1', 'status': 'completed', 'request': request,
              'forward_mode': 'scalp_node_table', 'nominal': dict(ROBUST_NOMINAL), 'projection_max_mm': 0,
              'evaluated_xyz_mm': DESIGN['xyz_mm'], 'trials': [], 'provenance': {'candidate_count': 100}}
    if robustness:
        result['robustness'] = robustness
    return result


def _stats(median: float, count: int) -> dict:
    """``stats(median, count)`` of robustness-fixture.mjs."""
    return {'median': median, 'p10': median - 1e-3, 'minimum': median - 2e-3, 'count': count}


def _pop(block: dict) -> None:
    block['dropout']['single']['candidate'].pop()


def _p10(block: dict) -> None:
    block['dropout']['random'][1]['candidate']['p10'] = block['dropout']['random'][1]['candidate']['median'] + .01


def _log_sd(block: dict) -> None:
    block['impedance'][0]['log_sd'] = 2


def _rejected(block: dict) -> None:
    block['replacement']['levels'][0]['candidate']['rejected'] = 0


def _fixed(block: dict) -> None:
    block['replacement']['levels'][1]['reference']['fixed_estimator'] = _stats(.9, 16)


def _count(block: dict) -> None:
    block['replacement']['levels'][0]['candidate']['fixed_estimator']['count'] = 16


def _nan(block: dict) -> None:
    block['dropout']['random'][0]['reference']['median'] = float('nan')


def _unavailable(block: dict) -> None:
    block['replacement'] = {'status': 'unavailable'}


# check-design-robustness.mjs:41-50, in order.
CORRUPTIONS: tuple[Callable[[dict], None], ...] = (_pop, _p10, _log_sd, _rejected, _fixed, _count, _nan, _unavailable)


class Fixture:
    """``fixture()`` of check-design-decision.mjs: a context stub ``{identity: {version}, key: sha256({request,
    version})}`` whose ``change()`` bumps the version, and fake children that record their kills."""

    def __init__(self, root: Path, **options: Any):
        self.version = 1
        self.children: list[FakeChild] = []
        options.setdefault('timeout_ms', 3000)
        self.service = DesignJobs(str(root), 'python3', context=self.context, spawn=Spawner(children=self.children),
                                  **options)

    def context(self, request: Any) -> dict:
        return {'identity': {'version': self.version},
                'key': jsjson.sha256_hex({'request': request, 'version': self.version})}

    def change(self) -> None:
        self.version += 1


async def done(service: DesignJobs) -> None:
    """``done(service)``: until no job is active."""
    await until(lambda: service.active is None, SETTLE)


# --- A stand-in worker ---------------------------------------------------------------------------------------------

FAKE_WORKER = r'''import json
import math
import os
import sys
import time

request = json.loads(sys.stdin.read())
design = request['design']
with open(os.path.join(os.getcwd(), %(admission)r), encoding='utf-8') as handle:
    admission = json.load(handle)
mode = design['name']
print(json.dumps({'type': 'progress', 'progress': 0.25, 'message': '评价名义坐标'}), flush=True)
if mode == 'fail':
    print(json.dumps({'type': 'error', 'message': '评价失败'}), flush=True)
    sys.stderr.write('Traceback: boom\n')
    sys.exit(1)
if mode == 'hold':
    time.sleep(%(hold)d)
xyz = design['xyz_mm']
chord = min(math.hypot(*(a - b for a, b in zip(p, q))) for i, p in enumerate(xyz) for q in xyz[i + 1:])
trials = [{'index': i, 'status': 'completed', 'xyz_mm': xyz, 'requested_xyz_mm': xyz,
           'region_indices': design['region_indices'], 'actual_max_mm': 0, 'actual_mean_mm': 0,
           'candidate_bank_indices': list(range(64)), 'unchanged_fraction': 1, 'minimum_chord_distance_mm': chord,
           'target_error_max_mm': 0, 'field_relative': 1, 'fixed_estimator_field_relative': 1}
          for i in range(4 if request['action'] == 'perturb' else 0)]
result = {'schema': 'design-evaluation/1', 'status': 'completed',
          'request': dict(request, seed=request['seed'] + 1) if mode == 'stale' else request,
          'forward_mode': 'head_scalp_node_table' if request.get('head_id') else 'scalp_node_table',
          'nominal': json.loads(%(nominal)r), 'projection_max_mm': 0, 'evaluated_xyz_mm': xyz,
          'provenance': {'candidate_count': 64, 'surface_admissibility_sha256': admission['sha256'],
                         'surface_admissibility_version': admission['schema_version']},
          'trials': trials}
if request.get('robustness'):
    result['robustness'] = json.loads(%(robustness)r)
print(json.dumps({'type': 'progress', 'progress': 0.75, 'message': '写入评价结果'}), flush=True)
sys.stderr.write('worker stderr\n')
print(json.dumps({'type': 'result', 'result': result}, ensure_ascii=False), flush=True)
''' % {'admission': ADMISSION_POINTER, 'hold': HOLD, 'nominal': jsjson.stringify(NOMINAL),
       'robustness': jsjson.stringify(robustness_block())}


def worker_root(directory: Path) -> Path:
    """A design root whose ``scripts/design_evaluation.py`` is ``FAKE_WORKER``."""
    root = Path(design_root(directory))
    (root / WORKER_SCRIPT).write_text(FAKE_WORKER, encoding='utf-8')
    return root


# --- The parity cases ----------------------------------------------------------------------------------------------

def run_result(raw: Any = REQUEST, **members: Any) -> dict:
    """A result the validator accepts for ``raw`` on a design root: the baseline for its canonical request, with the
    admission of the root and, for a perturbation, four unchanged trials."""
    request = canonical(raw)
    trials = [perturbation(i) for i in range(4)] if request['action'] == 'perturb' else []
    return baseline_result(request, provenance={'candidate_count': 64, **ADMISSION}, trials=trials, **members)


def result_line(result: Any) -> list:
    return ['stdout', b64(line({'type': 'result', 'result': result}))]


def odd_result_line(result: dict) -> list:
    """The result with a member whose JSON text V8 reads and writes in its own way (array-index keys first, ``-0``,
    big and tiny numbers, a lone surrogate, escapes), as the last line without a newline: the cache bytes and the
    checksum must still be Node's (B14)."""
    text = jsjson.stringify({'type': 'result', 'result': result})
    extra = ('"extra":{"__proto__":{"x":1},"2":"b","1":"a","big":123456789012345678901234567890,"zero":-0,'
             '"one":1.0,"small":1e-7,"tiny":5e-324,"lone":"\\ud800","escaped":"\\u2028\\/\\u0007"}')
    return ['stdout', b64(text[:-2] + ',' + extra + '}}')]


def _progress_lines() -> list[str]:
    """Progress events whose members ``Number`` and ``String`` convert, logs and odd JSON, as chunks."""
    chunks = [
        line({'type': 'progress', 'progress': '0.125', 'message': ''}),
        line({'type': 'progress', 'progress': [0.25], 'message': {'a': 1}}),
        b'{"type":"progress","progress":-1e400,"message":1e400}\n',
        line({'type': 'progress', 'progress': None, 'message': False}),
        line({'type': 'progress', 'progress': 0.5}),
        b'\n   \t\nnot json\n[1,2]\n"text"\n',
        b'{"type":"progress","progress":0.75,"type":"other"}\n',
        line({'type': 'result', 'result': {'schema': 'early'}}),
        line({'type': 'error', 'message': ['a', ['b']]}),
        b'\xff\xfe{"type":"x"}\n',
        line({'type': 'progress', 'progress': 0.4, 'message': ['几', '何']}),
    ]
    # A progress line cut inside a three-byte character, and one cut between its members.
    split = line({'type': 'progress', 'progress': 0.6, 'message': '真实检查'})
    cut = split.index('真'.encode()) + 1
    chunks += [split[:cut], split[cut:], b'{"type":"progress","progress":" 0x10 "', b',"message":"optimize"}\n']
    return [b64(chunk) for chunk in chunks]


def _stderr_chunks() -> list[str]:
    # The 16,000-unit tail starts inside the surrogate pair: a lone low surrogate, which JSON.stringify escapes.
    text = ('警告：' * 100 + '\U0001F600' + 'e' * 15999).encode('utf-8')
    cut = text.index('\U0001F600'.encode()) + 2
    return [b64('warning: 中文\n'.encode()[:11]), b64('warning: 中文\n'.encode()[11:]), b64(text[:cut]), b64(text[cut:])]


def _round(raw: Any, result: Any, close: tuple = (0, None)) -> list:
    """One job: submit, the result line (``None``: no result event), the close, then its final view."""
    steps: list = [['submit', raw]]
    if result is not None:
        steps.append(result_line(result))
    return steps + [['close', *close], ['settle'], ['view']]


def _invalid_results() -> list:
    """Results validateDesignResult refuses, one per check, the trial members ToNumber converts and the eight
    robustness corruptions, as rounds."""
    base = run_result()
    shifted = [[x + 3, y, z] for x, y, z in DESIGN['xyz_mm']]
    crowded = [list(p) for p in DESIGN['xyz_mm']]
    crowded[0][0] += 1.5
    crowded[1][0] -= 1.5
    rounds: list = [
        _round(REQUEST, None),  # no result event
        _round(REQUEST, None)[:1] + [['stdout', b64(line({'type': 'result', 'result': None}))], ['close', 0, None],
                                      ['settle'], ['view']],
        _round(REQUEST, baseline_result(canonical(REQUEST))),  # no surface-admission provenance
        _round(REQUEST, {**base, 'provenance': {**base['provenance'], 'surface_admissibility_version': 'other/1'}}),
        _round(REQUEST, {**base, 'request': canonical({**REQUEST, 'seed': 9})}),
        _round(REQUEST, {**base, 'forward_mode': 'head_scalp_node_table'}),
        _round(REQUEST, {**base, 'forward_mode': 'unknown'}),
        _round(REQUEST, {**base, 'schema': 'design-evaluation/2'}),
        _round(REQUEST, {**base, 'status': 'failed'}),
        _round(REQUEST, {**base, 'nominal': None}),
        _round(REQUEST, {**base, 'nominal': {**NOMINAL, 'p90_mm': None}}),
        _round(REQUEST, {**base, 'nominal': {**NOMINAL, 'sensitivity_tail': 'x'}}),
        _round(REQUEST, {**base, 'nominal': {**NOMINAL, 'p90_mm': 5}}),
        _round(REQUEST, {**base, 'evaluated_xyz_mm': shifted}),
        _round(REQUEST, {**base, 'projection_max_mm': 1}),
        _round(REQUEST, {**base, 'evaluated_xyz_mm': crowded, 'projection_max_mm': 1.5}),
        _round(REQUEST, {**base, 'trials': [perturbation(0)]}),
        _round(PERTURB, {**run_result(PERTURB), 'trials': [None, None, None, None]}),  # V8's TypeError
        _round(PERTURB, {**run_result(PERTURB), 'trials': [perturbation(0, xyz_mm=[]), *run_result(PERTURB)['trials'][1:]]}),
        _round(PERTURB, {**run_result(PERTURB), 'trials': [perturbation(0, actual_max_mm=5), *run_result(PERTURB)['trials'][1:]]}),
        _round(PERTURB, {**run_result(PERTURB), 'trials': [perturbation(0, index=1), *run_result(PERTURB)['trials'][1:]]}),
        _round(PERTURB, {**run_result(PERTURB), 'trials': [perturbation(0, field_relative=None), *run_result(PERTURB)['trials'][1:]]}),
        _round(PERTURB, {**run_result(PERTURB), 'trials': [perturbation(0, status='geometry_rejected'), *run_result(PERTURB)['trials'][1:]]}),
        # The geometry checks subtract actual_max_mm and unchanged_fraction before testing that they are numbers:
        # JavaScript's ToNumber converts strings and arrays, and an object with its own toString throws.
        *(_round(PERTURB, {**run_result(PERTURB), 'trials': [perturbation(0, **{member: value}),
                                                             *run_result(PERTURB)['trials'][1:]]})
          for member, value in (('actual_max_mm', '5'), ('actual_max_mm', [5]), ('actual_max_mm', ' 0x10 '),
                                ('actual_max_mm', '0'), ('actual_max_mm', {'toString': 1}),
                                ('unchanged_fraction', [0.5]), ('unchanged_fraction', ''),
                                ('unchanged_fraction', [None]), ('unchanged_fraction', {'toString': 'x'}))),
        _round(ROBUST, run_result(ROBUST)),  # the block is missing
        _round(REQUEST, run_result(REQUEST, robustness=robustness_block())),  # a block nobody asked for
    ]
    for corrupt in CORRUPTIONS:
        block = robustness_block()
        corrupt(block)
        if corrupt is _nan:  # NaN has no JSON text: the worker would write null, which fails as NaN does
            block['dropout']['random'][0]['reference']['median'] = None
        rounds.append(_round(ROBUST, run_result(ROBUST, robustness=block)))
    return [step for steps in rounds for step in steps]


def parity_cases(base: Path) -> list[dict]:
    """The cases of the run-path parity; each root is ``base/<id>/tree``, built for the Node run."""
    cases: list[dict] = []

    def case(id: str, steps: list, *, timeout_ms: int = 3000, throw: Optional[str] = None,
             runtime: Optional[str] = None, odd_bytes: bool = False) -> None:
        cases.append({'id': id, 'directory': str(base / id), 'root': str(base / id / 'tree'), 'python': 'python3',
                      'runtime': runtime, 'odd_bytes': odd_bytes, 'timeoutMs': timeout_ms, 'throw': throw,
                      'clock': CLOCK, 'steps': steps})

    done = run_result()
    case('done', [
        ['submit', REQUEST], ['view'], ['pid'], ['jobs'], ['submit', REQUEST], ['submit', OTHER],
        # A view after every chunk: progress and message as each event leaves them.
        *(step for chunk in _progress_lines() for step in (['stdout', chunk], ['view'])),
        *(['stderr', chunk] for chunk in _stderr_chunks()),
        odd_result_line(done), ['close', 0, None], ['view'], ['settle'], ['view'], ['jobs'],
        ['submit', REQUEST], ['view'], ['jobs'], ['lookup', REQUEST], ['lookup', OTHER], ['lookup', {}],
        ['lookup', {**REQUEST, 'seed': -1}], ['submit', {**REQUEST, 'design': {**DESIGN, 'unit': 'm'}}], ['jobs'],
        ['restart', {}], ['lookup', REQUEST], ['submit', REQUEST], ['jobs'],
        ['restart', {'throw': 'expected new calculation'}], ['change', WORKER_SCRIPT, 'changed code'],
        ['lookup', REQUEST], ['submit', REQUEST], ['settle'], ['view'],
    ])
    # Other options and the canonical request: an odd spelling is normalized before the key, the stdin and the
    # records; the worker echoes the canonical request.
    spelled = {**REQUEST, 'seed': 42.0, 'radius_mm': 6.0, 'noise_model': {'kind': 'iid'}, 'robustness': None,
               'design': {**DESIGN, 'name': 'x' * 120}}
    prior = {**REQUEST, 'data_prior': PRIOR}
    spatial = {**REQUEST, 'noise_model': SPATIAL}
    case('options', [
        *_round(PERTURB, run_result(PERTURB)), *_round(ROBUST, run_result(ROBUST, robustness=robustness_block())),
        *_round({**ROBUST, 'seed': 7}, run_result({**ROBUST, 'seed': 7}, robustness=robustness_block(table=False))),
        *_round(prior, run_result(prior)), *_round(spatial, run_result(spatial)),
        *_round(spelled, run_result(spelled)), ['lookup', spelled], ['lookup', REQUEST],
        *_round({**REQUEST, 'design': {k: v for k, v in DESIGN.items() if k != 'name'}},
                run_result({**REQUEST, 'design': {k: v for k, v in DESIGN.items() if k != 'name'}})),
    ])
    case('worker-failure', [
        ['submit', REQUEST], ['stderr', b64('Traceback (most recent call last):\n  ValueError: 失败\n')],
        ['stdout', b64(line({'type': 'error', 'code': 'compute_error', 'message': '失败'}))],
        ['close', 1, None], ['view'], ['settle'], ['view'],
        ['submit', REQUEST], ['error', 'spawn python3 EACCES'], ['error', 'spawn python3 ENOENT'],
        ['close', -2, None], ['settle'], ['view'],
        *_round(REQUEST, run_result(), (1, None)),
        *_round(REQUEST, None, (1, None)),
        ['submit', REQUEST], ['stdout', b64(line({'type': 'error'}))], ['close', None, 'SIGKILL'], ['settle'],
        ['view'],
        ['submit', REQUEST], ['stdout', b64(line({'type': 'error', 'message': ''}))], ['close', 2, None], ['settle'],
        ['view'],
        ['submit', REQUEST], ['stdout', b64(line({'type': 'error', 'message': 7}))], ['error', 'later'],
        ['close', 3, None], ['settle'], ['view'],
    ])
    case('spawn-throws', [['submit', REQUEST], ['view'], ['settle'], ['view'], ['submit', REQUEST], ['jobs']],
         throw='spawn EINVAL')
    case('invalid-result', _invalid_results())
    admission = jsjson.stringify({'path': 'data/admission.npz', 'sha256': digest('another mask'),
                                  'geometry_sha256': digest('candidates'),
                                  'schema_version': 'native-external-exposure/1'}) + '\n'
    case('identity-changed', [
        ['submit', REQUEST], ['change', WORKER_SCRIPT, 'changed code'], result_line(done), ['close', 0, None],
        ['view'], ['settle'], ['view'],
        # A result the validator refuses fails as such, before the context is computed again.
        ['submit', REQUEST], ['change', WORKER_SCRIPT, 'changed again'],
        result_line({**done, 'request': canonical(OTHER)}), ['close', 0, None], ['view'], ['settle'],
        ['submit', REQUEST], result_line(done), ['close', 0, None], ['settle'], ['view'], ['lookup', REQUEST],
        # The context cannot be formed any more: its own message.
        ['submit', OTHER], ['change', ADMISSION_POINTER, admission], result_line(run_result(OTHER)),
        ['close', 0, None], ['settle'], ['view'], ['lookup', REQUEST],
    ])
    # An input removed, replaced by a directory or made unreadable while the worker runs: the context computed at
    # the close fails with Node's system error (its syscall and path), and so does the next submit's.
    code, pointer, config = 'src/compact_eeg/metrics.py', 'results/v2/current_multiregion_bank.json', \
        'configs/ernie_fem_point_pilot.json'

    def broken(breaks: list, restores: list, raw: Any = REQUEST) -> list:
        return [['submit', raw], *breaks, result_line(run_result(raw)), ['close', 0, None], ['settle'], ['view'],
                ['submit', raw], *restores]

    failures = [step for path in (code, pointer, config) for step in broken(
        [['move', path, 'moved']], [['move', 'moved', path]])]
    failures += [step for path in (code, pointer) for step in broken(
        [['move', path, 'moved'], ['mkdir', path]], [['rmdir', path], ['move', 'moved', path]])]
    if os.geteuid() != 0:  # the superuser reads a file of mode 000
        failures += [step for path in (code, pointer) for step in broken(
            [['chmod', path, 0]], [['chmod', path, 0o644]])]
    case('context-failure', [*failures, *_round(REQUEST, done), ['lookup', REQUEST]])
    # The source input that the manifest names with a lone surrogate (the file named U+FFFD) moved away: Node's
    # message names the path as the system received it, with U+FFFD.
    sources = 'data/\ufffd.npz'
    case('odd-bytes', [*broken([['move', sources, 'moved']], [['move', 'moved', sources]]), *_round(REQUEST, done)],
         odd_bytes=True)
    case('timeout', [
        ['submit', REQUEST], ['stdout', b64(line({'type': 'progress', 'progress': 0.4, 'message': '几何'}))],
        ['wait_kill'], ['view'], ['stdout', b64(line({'type': 'progress', 'progress': 0.9, 'message': 'late'}))],
        result_line(done), ['close', None, 'SIGTERM'], ['settle'], ['view'],
    ], timeout_ms=TIMEOUT_CASE_MS)
    # 2.5 minutes: Math.round gives 3 where Python's round gives 2.
    case('timeout-minutes', [
        ['submit', REQUEST], ['stop', 'timeout'], ['stop', 'user'], ['view'], ['close', 0, None], ['settle'],
        ['view'],
    ], timeout_ms=150000)
    case('cancel', [
        ['submit', REQUEST], ['stdout', b64(line({'type': 'progress', 'progress': 0.3, 'message': '计算'}))],
        ['cancel', None], ['cancel', None], ['view'], ['submit', OTHER],
        ['stdout', b64(line({'type': 'progress', 'progress': 0.8, 'message': 'late'}))], result_line(done),
        ['close', None, 'SIGTERM'], ['settle'], ['view'], ['cancel', None],
        ['cancel_id', '00000000-0000-4000-8000-000000000099'], ['cancel_id', 'not an id'],
        ['submit', REQUEST], ['cancel', 'shutdown'], ['view'], ['close', 0, None], ['settle'], ['view'],
        ['lookup', REQUEST],
    ])
    case('input-error', [
        ['submit', REQUEST], ['stdin_error', 'write EPIPE', 'EPIPE'], ['view'], result_line(done),
        ['close', None, 'SIGTERM'], ['settle'], ['view'],
    ])
    started = line({'type': 'progress', 'progress': 0.2, 'message': '开始'})
    case('output-limit', [
        # 4 MiB of output in all is allowed, one byte more stops the worker.
        ['submit', REQUEST], ['stdout', b64(started)], ['stdout_fill', MAX_OUTPUT_BYTES - len(started)], ['view'],
        ['stdout_fill', 1], ['view'], ['close', None, 'SIGTERM'], ['settle'], ['view'],
    ])
    case('dispose', [
        ['submit', REQUEST], ['dispose'], ['view'], ['submit', OTHER], ['submit', {}], ['lookup', OTHER],
        ['close', None, 'SIGTERM'],
        ['settle'], ['view'], ['submit', REQUEST],
    ])
    case('store-failure', [
        ['submit', REQUEST], ['rm_batch'], result_line(done), ['close', 0, None], ['settle'], ['view'],
        ['lookup', REQUEST], ['submit', REQUEST],
        ['submit', OTHER], ['block_cache'], result_line(run_result(OTHER)), ['close', 0, None], ['settle'],
        ['view'], ['lookup', OTHER],
        ['submit', PERTURB], ['rm_batch'], ['cancel', None], ['close', None, 'SIGTERM'], ['settle'], ['view'],
    ])
    case('publish-once', [
        # Another workspace published a valid result first: Python keeps it (B16), Node replaces it.
        ['submit', REQUEST], ['write_cache', 'valid', done], result_line(done), ['close', 0, None], ['settle'],
        ['view'], ['lookup', REQUEST], ['submit', REQUEST],
        # Files that are not a valid result for the job are replaced on both hosts.
        ['submit', OTHER], ['write_cache', 'text', 'not json'], result_line(run_result(OTHER)), ['close', 0, None],
        ['settle'], ['view'], ['lookup', OTHER],
        ['submit', PERTURB], ['write_cache', 'valid', done], ['lookup', PERTURB], ['submit', PERTURB],
        result_line(run_result(PERTURB)), ['close', 0, None], ['settle'], ['view'], ['lookup', PERTURB],
        ['submit', SEVEN], ['write_cache', 'tampered', run_result(SEVEN)], ['lookup', SEVEN], ['submit', SEVEN],
        result_line(run_result(SEVEN)), ['close', 0, None], ['settle'], ['view'], ['lookup', SEVEN],
        ['submit', ROBUST], ['write_cache', 'text', '{"key":"0","result":1}'],
        result_line(run_result(ROBUST, robustness=robustness_block())), ['close', 0, None], ['settle'], ['view'],
    ])
    # A cache.json that cannot be read is an error, not a miss (the superuser reads it: a hit on both hosts).
    case('unreadable', [
        *_round(REQUEST, done), ['deny_cache'], ['lookup', REQUEST], ['submit', REQUEST], ['view'], ['jobs'],
        ['allow_cache'], ['lookup', REQUEST], ['submit', REQUEST],
    ])
    case('busy', [
        ['submit_pair', REQUEST, OTHER], ['pause'], ['submit', OTHER], ['submit', REQUEST], ['resume'],
        ['submit', OTHER], result_line(done), ['close', 0, None], ['settle'],
        ['acquire'], ['submit', REQUEST], ['submit', OTHER], ['lookup', OTHER], ['release'], ['pause'],
        ['submit', OTHER], ['resume'], ['submit', OTHER], ['view'], ['close', 1, None], ['settle'], ['view'],
    ])
    case('remember', [
        ['submit', REQUEST], result_line(done), ['close', 0, None], ['settle'],
        *(['submit', REQUEST] for _ in range(22)), ['jobs'],
        ['submit', OTHER], *(['submit', REQUEST] for _ in range(21)), ['jobs'], ['close', 1, None], ['settle'],
        ['submit', REQUEST], ['jobs'],
    ])
    if sys.platform == 'darwin':
        # The managed interpreter is the worker's executable and enters the identity (no fingerprint on macOS); its
        # conda records gone, the listing fails (scandir).
        metadata = '.runtime/simnibs-4.6.0/conda-meta'
        case('managed', [*_round(REQUEST, run_result()), ['lookup', REQUEST],
                         *broken([['move', metadata, 'moved']], [['move', 'moved', metadata]], OTHER)],
             runtime='simnibs')
    return cases


def build(case: dict) -> None:
    """Builds the case's root (again, at the same path, for the second run; Node's is ``root.node`` by then)."""
    if Path(case['root']).exists():
        shutil.rmtree(case['root'])
    root = design_root(Path(case['directory']), runtime=case['runtime'], odd_bytes=case['odd_bytes'])
    assert root == case['root']


# --- Runs ----------------------------------------------------------------------------------------------------------

def _message(error: BaseException) -> str:
    """Node's ``error.message``: a system error as Node writes it (``records.node_message``)."""
    message = getattr(error, 'message', None)
    return message if isinstance(message, str) else node_message(error)


async def run_case(item: dict) -> dict:
    """The Python side of one case: ``DesignJobs`` driven by the steps the Node driver runs."""
    clock, ids = PinnedClock(**item['clock']), PinnedIds()
    records: list[list[str]] = []
    children: list[FakeChild] = []

    def make(options: dict) -> DesignJobs:
        thrown = options['throw'] if 'throw' in options else item['throw']
        runtime = runtime_config(item['root'], item['python'])
        return DesignJobs(runtime.repository_root, runtime.native_python, timeout_ms=item['timeoutMs'],
                          spawn=Spawner(thrown, children), clock=clock, random_uuid=ids)

    jobs, current, release = make({}), None, None

    async def record(kind: str, run: Callable[[], Any]) -> Any:
        try:
            value = run()
            if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
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
        elif kind == 'submit_pair':
            first = asyncio.ensure_future(jobs.submit(args[0]))
            second = asyncio.ensure_future(jobs.submit(args[1]))
            value = await record(kind, lambda: first)
            await record(kind, lambda: second)
            if isinstance(value, dict) and 'job' in value:
                current = value['job']['id']
        elif kind == 'lookup':
            await record(kind, lambda: jobs.lookup(args[0]))
        elif kind == 'view':
            await record(kind, lambda: jobs.view(jobs.jobs[current]))
        elif kind == 'jobs':
            await record(kind, lambda: list(jobs.jobs))
        elif kind == 'pid':
            await record(kind, jobs.active_pid)
        elif kind == 'cancel':
            await record(kind, lambda: jobs.cancel(current) if args[0] is None else jobs.cancel(current, args[0]))
        elif kind == 'cancel_id':
            await record(kind, lambda: jobs.cancel(args[0]))
        elif kind == 'stop':
            await record(kind, lambda: jobs.jobs[current].worker.stop(args[0]))
        elif kind == 'dispose':
            jobs.dispose()
        elif kind == 'restart':
            jobs.dispose()
            jobs = make(args[0])
        elif kind == 'acquire':
            def acquire() -> bool:
                nonlocal release
                release = jobs.execution_slot.acquire('other')
                return release is not None
            await record(kind, acquire)
        elif kind == 'release':
            if release is not None:
                release()
            release = None
        elif kind == 'pause':
            jobs.execution_slot.pause()
        elif kind == 'resume':
            jobs.execution_slot.resume()
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
            await until(lambda: bool(children[-1].kills), SETTLE)
        elif kind == 'settle':
            await until(lambda: jobs.active is None, SETTLE)
        elif kind == 'rm_batch':
            shutil.rmtree(jobs.jobs[current].batch)
        elif kind == 'block_cache':
            os.mkdir(os.path.join(jobs.jobs[current].directory, 'cache.json'))
        elif kind == 'write_cache':
            job = jobs.jobs[current]
            body = args[1] if args[0] == 'text' else jsjson.stringify({
                'key': job.key, 'identity': job.ctx['identity'], 'result': args[1],
                'result_sha256': jsjson.sha256_hex(args[1] if args[0] == 'valid' else 'tampered'),
                'finished_at': '2026-01-01T00:00:00.000Z'})
            Path(job.directory, 'cache.json').write_bytes(body.encode('utf-8'))
        elif kind in ('deny_cache', 'allow_cache'):
            os.chmod(os.path.join(jobs.jobs[current].directory, 'cache.json'), 0 if kind == 'deny_cache' else 0o600)
        elif kind == 'change':
            Path(item['root'], args[0]).write_bytes(args[1].encode('utf-8'))
        elif kind == 'move':
            os.rename(os.path.join(item['root'], args[0]), os.path.join(item['root'], args[1]))
        elif kind == 'mkdir':
            os.mkdir(os.path.join(item['root'], args[0]))
        elif kind == 'rmdir':
            os.rmdir(os.path.join(item['root'], args[0]))
        elif kind == 'chmod':
            os.chmod(os.path.join(item['root'], args[0]), args[1])
        else:
            raise ValueError(f'unknown step {kind}')
    await until(lambda: jobs.active is None, SETTLE)
    jobs.dispose()
    if release is not None:
        release()
    return {
        'id': item['id'], 'records': records, 'clock': clock.calls, 'ids': ids.count,
        'children': [{
            'executable': c.executable, 'args': c.args, 'cwd': c.options['cwd'], 'stdio': c.options['stdio'],
            'detached': c.options['detached'], 'shell': c.options['shell'],
            'env': {name: c.options['env'].get(name) for name in WORKER_ENV},
            'inherits': all(name in WORKER_ENV or c.options['env'].get(name) == value
                            for name, value in os.environ.items()),
            'added': sorted(name for name in c.options['env'] if name not in os.environ and name not in WORKER_ENV),
            'input': b64(b''.join(c.inputs)), 'kills': c.kills,
        } for c in children],
    }


def run_python(case: dict) -> dict:
    return asyncio.run(run_case(case))


def run_node(cases: list[dict], scratch: Path) -> dict:
    spec_path, out_path = scratch / 'design-run-spec.json', scratch / 'design-run-node.json'
    spec = {'queueDirectory': str(scratch / 'node-queue'),
            'cases': [{k: v for k, v in case.items() if k not in ('directory', 'runtime', 'odd_bytes')}
                      for case in cases]}
    spec_path.write_text(jsjson.stringify(spec), encoding='utf-8')
    subprocess.run(['node', str(DRIVER), str(spec_path), str(out_path)], check=True, cwd=ROOT, env=NODE_ENV,
                   timeout=600)
    return json.loads(out_path.read_text(encoding='utf-8'))


def record_tree(root: Path, kind: str = 'results/v2/design_evaluation_jobs') -> dict[str, Any]:
    """Every directory (``None``) and file (its bytes) under the record tree, by relative path."""
    base = root / kind
    tree: dict[str, Any] = {}
    for directory, names, files in os.walk(base):
        for name in names:
            tree[os.path.relpath(os.path.join(directory, name), base)] = None
        for name in files:
            path = os.path.join(directory, name)
            tree[os.path.relpath(path, base)] = Path(path).read_bytes()
    return tree
