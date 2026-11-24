"""Read-only experiment packaging (``eeg-reproducibility-bundle/1``): Node's ``webapp/server/experiment-bundle.mjs``,
statement by statement. No rescoring, rekeying or invented history.

``experiment_bundle(root, record, python=...)`` packs a library record (``Library.get``) with the exact bytes of its
source file: the saved radius cache, the strict-area report, the radius optimization report the pointer
``results/v2/current_single_head_optimization.json`` names, or the saved coordinate evaluation. The source must
resolve (``realpath(3)``) under ``R/results/v2`` or ``R/webapp/public/data``; its SHA-256 is checked against the
record, and a coordinate evaluation is checked again in full (key, result checksum, request identity, the
evaluated coordinates and metrics the record shows). ``describe_search`` reads the saved search history.

For a radius cache whose snapshots lack coordinates, the frozen-bank coordinates come from
``scripts/export_history_coordinates.py``, run with the compute interpreter (``RuntimeConfig.python``, which the
route passes as Node passes ``queue.python``) as Node's ``execFile`` runs it: arguments converted with ``String``,
the service's environment plus three thread and bytecode settings, the service's working directory, 10 s and 1 MiB
of output per stream (counted after UTF-8 decoding, as Node counts). Any failure there only sets the coordinate
note.

The value returned is plain JSON data built member by member in Node's order, so ``jsjson.stringify`` writes the
bytes ``JSON.stringify`` writes; members Node leaves ``undefined`` are left out. Node's errors keep their messages
(V8's ``TypeError`` texts for member reads of ``null`` and calls of non-functions). The route turns every error into
Node's generic 500.

Known difference: after the timeout or an oversized output Node closes the outputs, sends ``SIGTERM`` and waits for
the child to exit, forever if it ignores the signal; here ``SIGKILL`` follows after ``KILL_GRACE_SECONDS``.
"""
from __future__ import annotations

import codecs
import errno
import hashlib
import math
import os
import re
import selectors
import signal
import socket
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Optional, Sequence

from ..schemas import jsjson
from . import nodefs, nodepath
from .design_result import normalize_design_request, validate_design_result
from .fingerprint import _EXECVP_SKIP
from .identity import UNDEFINED, JSTypeError, _js_string, _same, js_truthy, request_key, to_number
from .records import read_file, realpath
from .reception_records import _hash_json, _js_min, _spread

__all__ = ['BUNDLE_SCHEMA', 'HISTORY_SCRIPT', 'HISTORY_TIMEOUT_SECONDS', 'HISTORY_MAX_BUFFER', 'HISTORY_ENV',
           'KILL_GRACE_SECONDS', 'BundleError', 'ExecFileError', 'describe_search', 'experiment_bundle', 'exec_file',
           'deep_strict_equal', 'to_number']

BUNDLE_SCHEMA = 'eeg-reproducibility-bundle/1'
HISTORY_SCRIPT = 'scripts/export_history_coordinates.py'
RADIUS_POINTER = 'results/v2/current_single_head_optimization.json'
HISTORY_TIMEOUT_SECONDS = 10.0
HISTORY_MAX_BUFFER = 1024 * 1024
HISTORY_ENV = {'PYTHONDONTWRITEBYTECODE': '1', 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}
KILL_GRACE_SECONDS = 2.0
_READ_SIZE = 65536
_EXIT_POLL_SECONDS = 0.01  # how soon stdin closes after the child exits
_HEX64 = re.compile('[a-f0-9]{64}')

# Node's messages, verbatim.
CACHE_CHECKSUM = '坐标评价缓存校验失败'
COORDINATE_IDENTITY = '坐标评价记录身份不匹配'
COORDINATE_MISMATCH = '坐标评价来源与所选记录不匹配'
COORDINATE_SOURCE = '坐标评价来源路径或身份无效'
RADIUS_REPORT = '历史优化报告与导出身份不符'
NO_SOURCE = '原始记录未提供来源文件'
OUTSIDE = '来源文件不在实验目录内'
SOURCE_CHECKSUM = '原始文件校验失败'
RADIUS_CHECKSUM = '原始缓存校验失败'
COORDINATE_SCOPE = '固定坐标评价，不执行布局搜索；原始输入坐标与实际评价坐标分别保留。'
HISTORY_SCOPE = '保存的初始化及接受步骤；未记录的被拒绝提案不补造。'
COORDINATE_NOTE = ('固定坐标评价无布局搜索历史；输入坐标见 original_record.result.request.design.xyz_mm，'
                   '实际评价坐标见 record.layout.xyzMm。')
HISTORY_NOTE = '原前向库坐标未载入；原始点位索引仍保留在实验包中。'
COORDINATE_REPRODUCTION = '固定坐标评价的原始输入、实际评价坐标与保存指标归档；不包含布局搜索历史。运行需要对应代码版本、头模和前向矩阵。'
REPRODUCTION = '原始输入与轨迹归档；运行需要对应代码版本、头模和前向矩阵。'
SNAPSHOT_LABELS = ('初始化', '优化后')
ENTRYPOINTS = {'cache': 'scripts/run_local_radius_compute.py', 'strict_area': 'scripts/run_area_budget_study.py',
               'design_evaluation': 'scripts/design_evaluation.py'}
OTHER_ENTRYPOINT = 'see original_record provenance and run manifest'


class BundleError(ValueError):
    """A record or source file Node refuses to package; the message is Node's, verbatim."""


class ExecFileError(RuntimeError):
    """A failed ``execFile``: a non-zero exit, a signal, the timeout or an output beyond the buffer."""


# --- JavaScript values ------------------------------------------------------------------------------------------

def _nullish(value: Any) -> bool:
    return value is None or value is UNDEFINED


def _units(text: str) -> bytes:
    return text.encode('utf-16-le', errors='surrogatepass')


def _get(value: Any, key: str) -> Any:
    """``value.key`` on a parsed JSON value: an array's or a string's ``length`` and indices, ``UNDEFINED`` for any
    other member of a primitive; ``null`` and ``undefined`` throw V8's ``TypeError``."""
    if _nullish(value):
        raise JSTypeError(f"Cannot read properties of {'null' if value is None else 'undefined'} (reading '{key}')")
    if isinstance(value, dict):
        return value.get(key, UNDEFINED)
    if isinstance(value, (list, str)):
        size = len(value) if isinstance(value, list) else len(_units(value)) // 2
        if key == 'length':
            return size
        if jsjson.is_array_index(key) and int(key) < size:
            if isinstance(value, list):
                return value[int(key)]
            return _units(value)[2 * int(key):2 * int(key) + 2].decode('utf-16-le', errors='surrogatepass')
    return UNDEFINED


def _opt(value: Any, key: str) -> Any:
    """``value?.key``."""
    return UNDEFINED if _nullish(value) else _get(value, key)


def _coalesce(value: Any, fallback: Callable[[], Any]) -> Any:
    """``value ?? fallback()``, the right side evaluated only when needed."""
    return fallback() if _nullish(value) else value


def _defined(value: dict) -> dict:
    """The members ``JSON.stringify`` writes."""
    return {key: item for key, item in value.items() if item is not UNDEFINED}


def _finite(value: Any) -> bool:
    """``Number.isFinite(value)``."""
    return jsjson.is_number(value) and math.isfinite(jsjson.to_number(value))


def _find(items: Any, expression: str, test: Callable[[Any], bool]) -> Any:
    """``items?.find(test)`` (``expression`` is the callee as V8 names it)."""
    if _nullish(items):
        return UNDEFINED
    if not isinstance(items, list):
        raise JSTypeError(f'{expression} is not a function')
    for item in items:
        if test(item):
            return item
    return UNDEFINED


def _same_value(a: float, b: float) -> bool:
    """``Object.is`` of two numbers."""
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    if a == 0 and b == 0:
        return math.copysign(1, a) == math.copysign(1, b)
    return a == b


def deep_strict_equal(a: Any, b: Any) -> bool:
    """``util.isDeepStrictEqual(a, b)`` for parsed JSON values: primitives by ``Object.is`` (``-0`` is not ``0``),
    arrays item by item, objects by their set of keys (in any order) and values; an array is never an object."""
    stack = [(a, b)]
    while stack:
        x, y = stack.pop()
        if x is y:
            continue
        if isinstance(x, bool) or isinstance(y, bool) or _nullish(x) or _nullish(y):
            return False  # not the same object, so not the same primitive
        if jsjson.is_number(x) or jsjson.is_number(y):
            if not (jsjson.is_number(x) and jsjson.is_number(y)
                    and _same_value(jsjson.to_number(x), jsjson.to_number(y))):
                return False
        elif isinstance(x, str) or isinstance(y, str):
            if not (isinstance(x, str) and isinstance(y, str) and x == y):
                return False
        elif isinstance(x, list) and isinstance(y, list):
            if len(x) != len(y):
                return False
            stack.extend(zip(x, y))
        elif isinstance(x, dict) and isinstance(y, dict):
            if x.keys() != y.keys():
                return False
            stack.extend((x[key], y[key]) for key in x)
        else:
            return False
    return True


def _set_size(values: list) -> int:
    """``new Set(values).size`` (SameValueZero: ``-0`` is ``0``, objects by identity)."""
    seen = set()
    for value in values:
        if isinstance(value, bool):
            item: Any = ('boolean', value)
        elif jsjson.is_number(value):
            number = jsjson.to_number(value)
            item = ('number', 'NaN' if math.isnan(number) else number)
        elif isinstance(value, str):
            item = ('string', value)
        elif value is None:
            item = ('null',)
        else:
            item = ('object', id(value))
        seen.add(item)
    return len(seen)


def _items(values: list) -> list:
    """An array of possibly ``undefined`` items as ``JSON.stringify`` writes it (``undefined`` is ``null``)."""
    return [None if value is UNDEFINED else value for value in values]


# --- describeSearch ---------------------------------------------------------------------------------------------

def _score(s: Any) -> Any:
    """``value(s)``: the saved objective score of a search state, else the minimum of field and tail, else null."""
    if _nullish(s):
        return None
    for key in ('objective_score', 'objective'):
        value = _get(s, key)
        if jsjson.is_number(value):
            return value
    field, tail = _get(s, 'field20'), _get(s, 'sensitivity_tail')
    if jsjson.is_number(field) and jsjson.is_number(tail):
        return _js_min(field, tail)
    return None


def _length(value: Any) -> Any:
    """``value?.length``."""
    return _opt(value, 'length')


def describe_search(record: Any, raw: Any) -> dict:
    """``describeSearch(record, raw)``: the saved search of a record's source (initialization, accepted moves and
    counters), never reconstructed; a coordinate evaluation has none."""
    dataset = _get(record, 'dataset_id')
    if _same(dataset, 'design_evaluation'):
        return _defined({
            'configuration': _get(_get(raw, 'result'), 'request'),
            'objective': None,
            'initial': None,
            'final': None,
            'trace': [],
            'curve': [],
            'counters': {'scored_layouts': None, 'coordinate_proposals': None, 'geometry_attempts': None},
            'original_counters': None,
            'history_status': 'not_applicable_coordinate_evaluation',
            'history_scope': COORDINATE_SCOPE,
            'global_optimum_certified': False,
        })
    d: Any = None
    configuration = _get(record, 'request')
    if _same(dataset, 'cache'):
        d = _opt(_get(raw, 'result'), 'diagnostics')
    if _same(dataset, 'offline_radius'):
        entry = _find(_get(raw, 'conditions'), 'raw.conditions?.find',
                      lambda c: _same(_get(_get(c, 'condition'), 'id'),
                                      _get(_get(record, 'provenance'), 'condition_id')))
        finalist = _find(_opt(entry, 'finalists'), 'entry?.finalists?.find',
                         lambda f: _same(_opt(_get(f, 'evaluation'), 'id'), _opt(_get(record, 'layout'), 'id'))
                         and _same(_get(f, 'objective'), _get(_get(record, 'provenance'), 'objective')))
        d = _opt(finalist, 'search')
        configuration = _defined({**_spread(_get(raw, 'config')), 'condition': _opt(entry, 'condition')})
    if isinstance(dataset, str) and dataset in ('strict_area', 'historical_area'):
        entry = _find(_get(raw, 'conditions'), 'raw.conditions?.find',
                      lambda c: _same(_get(_get(c, 'condition'), 'id'),
                                      _get(_get(record, 'provenance'), 'condition_id')))
        configuration = _defined({**_spread(_get(raw, 'config')), 'condition': _opt(entry, 'condition')})
        finalist = _find(_opt(entry, 'finalists'), 'entry?.finalists?.find',
                         lambda f: _same(_get(f, 'objective'), _get(_get(record, 'provenance'), 'objective')))
        d = ({**_spread(finalist), 'attempts': _get(entry, 'attempts'), 'evaluated': _get(entry, 'counts')}
             if js_truthy(finalist) else finalist)
    initial = _coalesce(_opt(d, 'initial'), lambda: None)
    final = _coalesce(_opt(d, 'final'), lambda: None)
    objective = _coalesce(_get(_get(record, 'provenance'), 'objective'), lambda: 'min(field20,sensitivity_tail)')
    trace = _coalesce(_opt(d, 'trace'), lambda: [])
    curve = [{'step': 0, 'value': _score(initial)}] if js_truthy(initial) and _score(initial) is not None else []
    if not isinstance(trace, list):
        raise JSTypeError('trace.entries is not a function or its return value is not iterable')
    for i, move in enumerate(trace):
        after = _coalesce(_get(move, 'after'), lambda: _get(move, 'objective_after'))
        if _finite(after):
            curve.append({'step': i + 1, 'value': after})
    return _defined({
        'configuration': configuration,
        'objective': objective,
        'initial': initial,
        'final': final,
        'trace': trace,
        'curve': curve,
        'counters': {
            'scored_layouts': _coalesce(_opt(d, 'scored_layouts'),
                                        lambda: _coalesce(_opt(_opt(d, 'evaluated'), 'field_scores'), lambda: None)),
            'coordinate_proposals': _coalesce(
                _opt(d, 'coordinate_proposals'),
                lambda: _coalesce(_opt(_opt(d, 'evaluated'), 'coordinate_proposals'), lambda: None)),
            'geometry_attempts': _coalesce(_length(_opt(d, 'attempts')),
                                           lambda: _coalesce(_length(_opt(d, 'center_attempts')), lambda: None)),
        },
        'original_counters': _coalesce(_opt(d, 'evaluated_counts'), lambda: _coalesce(_opt(d, 'evaluated'),
                                                                                       lambda: None)),
        'history_status': 'recorded_accepted_moves' if js_truthy(d) else 'not_available_in_loaded_record',
        'history_scope': HISTORY_SCOPE,
        'global_optimum_certified': False,
    })


# --- validateCoordinateSource -----------------------------------------------------------------------------------

def _validate_coordinate_source(record: Any, raw: Any) -> None:
    """``validateCoordinateSource(record, raw)``: the saved evaluation still is the one the record shows."""
    result = _get(raw, 'result')
    if not _same(_get(raw, 'key'), _get(record, 'id')) or not _same(_get(raw, 'result_sha256'), _hash_json(result)):
        raise BundleError(CACHE_CHECKSUM)
    raw_request = _opt(result, 'request')
    request = normalize_design_request(None if raw_request is UNDEFINED else raw_request)
    identity = _get(raw, 'identity')
    if not isinstance(identity, dict) or not _same(request_key(request, identity), _get(record, 'id')):
        raise BundleError(COORDINATE_IDENTITY)
    validate_design_result(result, request)
    nominal = result['nominal']
    scores = [_get(nominal, key) for key in ('field_relative', 'sensitivity_tail', 'localization_relative')]
    metrics = {**_spread(nominal),
               'conditional_global': None if any(_nullish(value) for value in scores) else _js_min(*scores)}
    design = request['design']
    # Node's normalized request shares the stored arrays (a -0 stays -0); the schema's canonical form has integers.
    regions = raw_request['design']['region_indices']
    layout = _get(record, 'layout')
    if (not _same(request['action'], 'evaluate') or not _same(_get(record, 'status'), 'completed')
            or not _same(_get(record, 'label'), design['name'])
            or not _same(_get(record, 'region_count'), _set_size(regions))
            or not _same(_opt(layout, 'id'), _get(record, 'id'))
            or not deep_strict_equal(_opt(layout, 'xyzMm'), _get(result, 'evaluated_xyz_mm'))
            or not deep_strict_equal(_opt(layout, 'regionIndices'), regions)
            or not deep_strict_equal(_get(record, 'metrics'), metrics)
            or not _same(_get(_get(record, 'provenance'), 'forward_mode'), _get(result, 'forward_mode'))):
        raise BundleError(COORDINATE_MISMATCH)


# --- experimentBundle -------------------------------------------------------------------------------------------

def _meters(value: Any) -> Any:
    """``s.xyz_m?.map((p) => p.map((v) => v * 1000))``."""
    if _nullish(value):
        return UNDEFINED
    if not isinstance(value, list):
        raise JSTypeError('s.xyz_m?.map is not a function')
    points = []
    for p in value:
        if _nullish(p):
            raise JSTypeError(f"Cannot read properties of {'null' if p is None else 'undefined'} (reading 'map')")
        if not isinstance(p, list):
            raise JSTypeError('p.map is not a function')
        points.append([to_number(v) * 1000.0 for v in p])
    return points


def _snapshot(s: Any, i: int, record: Any) -> Optional[dict]:
    if not js_truthy(s):
        return None
    return _defined({
        'label': SNAPSHOT_LABELS[i],
        'xyzMm': _coalesce(_get(s, 'xyz_mm'), lambda: _coalesce(_meters(_get(s, 'xyz_m')), lambda: None)),
        'regionIndices': _coalesce(_get(s, 'region_indices'), lambda: _get(s, 'region_indices64')),
        'referenceXyzMm': _opt(_get(record, 'layout'), 'referenceXyzMm'),
    })


def _history_coordinates(root: Any, record: Any, search: dict, snapshots: list, python: Any,
                         execute: Callable[..., str]) -> None:
    """The ``try`` block of ``experimentBundle``: frozen-bank coordinates of the two snapshots."""
    indices = [_get(s, 'candidate_bank_indices') for s in (search['initial'], search['final'])]
    stdout = execute(python, [
        nodepath.resolve(root, HISTORY_SCRIPT),
        '--repository-root',
        root,
        '--bank-sha256',
        _get(_get(record, 'provenance'), 'bank_sha256'),
        '--indices',
        jsjson.stringify(_items(indices)),
    ], timeout=HISTORY_TIMEOUT_SECONDS, max_buffer=HISTORY_MAX_BUFFER, env={**os.environ, **HISTORY_ENV})
    coordinates = jsjson.parse(stdout)
    for i, s in enumerate(snapshots):
        if s is not None:
            value = _get(_get(coordinates, 'xyz_mm'), str(i))
            if value is UNDEFINED:
                s.pop('xyzMm', None)  # Node assigns undefined, which JSON.stringify leaves out
            else:
                s['xyzMm'] = value


def experiment_bundle(root: str, record: Any, python: Any = None, *,
                      execute: Optional[Callable[..., str]] = None) -> dict:
    """``await experimentBundle(root, record, {python})``: the reproducibility bundle of a library record.

    ``root`` is the library's root (``Library.root``), ``python`` the compute interpreter (``RuntimeConfig.python``;
    without it no coordinates are exported). ``execute`` replaces ``exec_file`` in tests. Raises ``BundleError``
    with Node's messages, Node's system errors (``records.node_message`` writes them) for a missing or unreadable
    source, and the errors of the design result checks; never writes.
    """
    provenance = _get(record, 'provenance')
    relative = _opt(provenance, 'file')
    expected = _opt(provenance, 'sha256')
    dataset = _get(record, 'dataset_id')
    design = _same(dataset, 'design_evaluation')
    if design:
        relative = _opt(_opt(_get(record, 'provenance'), 'design_result'), 'path')
        expected = _opt(_opt(_get(record, 'provenance'), 'design_result'), 'sha256')
        if (not _HEX64.fullmatch(_js_string(_get(record, 'id')))
                or not _same(relative, f"results/v2/design_evaluation_jobs/{_js_string(_get(record, 'id'))}/cache.json")
                or not _HEX64.fullmatch(_js_string(_coalesce(expected, lambda: '')))):
            raise BundleError(COORDINATE_SOURCE)
    if _same(dataset, 'offline_radius'):
        pointer = jsjson.parse(nodefs.decode(read_file(nodepath.resolve(root, RADIUS_POINTER))))
        expected = _opt(_get(_get(record, 'provenance'), 'original'), 'report_sha256')
        if not js_truthy(expected) or not _same(_get(pointer, 'sha256'), expected):
            raise BundleError(RADIUS_REPORT)
        relative = _get(pointer, 'report')
    if not isinstance(relative, str):
        raise BundleError(NO_SOURCE)
    path = realpath(nodepath.resolve(root, relative))
    if (not path.startswith(nodepath.resolve(root, 'results/v2') + '/')
            and not path.startswith(nodepath.resolve(root, 'webapp/public/data') + '/')):
        raise BundleError(OUTSIDE)
    data = read_file(path)
    digest = hashlib.sha256(data).hexdigest()
    if js_truthy(expected) and not _same(digest, expected):
        raise BundleError(SOURCE_CHECKSUM)
    raw = jsjson.parse(nodefs.decode(data))
    if design:
        _validate_coordinate_source(record, raw)
    if _same(dataset, 'cache') and (not _same(_get(raw, 'key'), _get(record, 'id'))
                                    or not _same(_get(raw, 'result_sha256'), _hash_json(_get(raw, 'result')))):
        raise BundleError(RADIUS_CHECKSUM)
    search = describe_search(record, raw)
    snapshots = [_snapshot(s, i, record) for i, s in enumerate((search['initial'], search['final']))]
    note = COORDINATE_NOTE if design else None
    if (js_truthy(python) and _same(dataset, 'cache') and js_truthy(search['initial'])
            and any(s is not None and not js_truthy(s.get('xyzMm', UNDEFINED)) for s in snapshots)):
        try:
            _history_coordinates(root, record, search, snapshots, python, execute or exec_file)
        except Exception:  # noqa: BLE001 - Node's bare catch: only the note changes
            note = HISTORY_NOTE
    request = _get(_get(raw, 'result'), 'request') if design else _get(record, 'request')
    identity = _coalesce(_get(raw, 'identity'), lambda: _coalesce(_get(raw, 'provenance'),
                                                                  lambda: _get(record, 'provenance')))
    return _defined({
        'schema': BUNDLE_SCHEMA,
        'record_id': _get(record, 'id'),
        'record': record,
        'source': {'path': relative, 'sha256': digest},
        'search': search,
        'snapshots': snapshots,
        'coordinate_note': note,
        'original_record': raw,
        'reproduction': _defined({
            'scope': COORDINATE_REPRODUCTION if design else REPRODUCTION,
            'request': request,
            'identity': identity,
            'entrypoint': ENTRYPOINTS.get(dataset, OTHER_ENTRYPOINT) if isinstance(dataset, str) else OTHER_ENTRYPOINT,
            'metrics_recomputed': False,
            'ar_changes_recompute': False,
        }),
    })


# --- execFile ---------------------------------------------------------------------------------------------------

_LONE_SURROGATE = re.compile('[\ud800-\udfff]')


def _argument(value: Any) -> bytes:
    """One argument as Node's ``spawn`` passes it: a string with a NUL byte is refused (``ERR_INVALID_ARG_VALUE``);
    any other value is converted with ``ToString`` (``node::Utf8Value``) and cut at a NUL byte (C strings), and a
    conversion that throws gives an empty argument (the exception is dropped); lone surrogates become U+FFFD."""
    if isinstance(value, str):
        return nodefs.encode(value)
    try:
        text = _js_string(value)
    except JSTypeError:
        return b''
    return _LONE_SURROGATE.sub('\ufffd', text).encode('utf-8').split(b'\0', 1)[0]


def _exec_file(candidate: bytes, argv: list[bytes], options: dict) -> subprocess.Popen:
    """One ``execve`` of glibc's ``execvp``: a file without a ``#!`` line (``ENOEXEC``) runs with ``/bin/sh``."""
    try:
        return subprocess.Popen(argv, executable=candidate, **options)
    except OSError as error:
        if error.errno != errno.ENOEXEC:
            raise
    return subprocess.Popen([b'/bin/sh', candidate, *argv[1:]], **options)


def _spawn(argv: list[bytes], options: dict, platform: str) -> subprocess.Popen:
    """libuv's spawn (``jobs.fingerprint._spawn``, with the three streams given): Python's own search on macOS
    (``posix_spawn``), glibc's ``execvp`` elsewhere."""
    if platform == 'darwin':
        return subprocess.Popen(argv, **options)
    name = argv[0]
    if b'/' in name:
        return _exec_file(name, argv, options)
    if not name:
        raise OSError(errno.ENOENT, os.strerror(errno.ENOENT), name)
    denied = False
    path = (options.get('env') or os.environ).get('PATH', os.defpath)
    for directory in nodefs.encode(path).split(b':'):
        candidate = directory + b'/' + name if directory else b'./' + name
        try:
            return _exec_file(candidate, argv, options)
        except OSError as error:
            if error.errno not in _EXECVP_SKIP:
                raise
            denied = denied or error.errno == errno.EACCES
    number = errno.EACCES if denied else errno.ENOENT
    raise OSError(number, os.strerror(number), name)


def _stop(process: subprocess.Popen) -> None:
    """``child.kill('SIGTERM')``; ``SIGKILL`` after ``KILL_GRACE_SECONDS`` (Node would wait for the exit)."""
    if process.poll() is not None:
        return
    try:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    except ProcessLookupError:
        pass


def _kill(process: subprocess.Popen, outputs: list) -> None:
    """``execFile``'s ``kill()``: both outputs are destroyed (a child still writing them gets ``EPIPE``), then the
    child is signalled."""
    for end in outputs:
        end.close()
    _stop(process)


def _timed_out(process: subprocess.Popen, outputs: list) -> bool:
    """``kill()`` at the timeout, then the exit handler: whether the child exited with 0 all the same."""
    _kill(process, outputs)
    return process.returncode == 0


def exec_file(file: Any, args: Sequence[Any], *, timeout: float = HISTORY_TIMEOUT_SECONDS,
              max_buffer: int = HISTORY_MAX_BUFFER, env: Optional[Mapping[str, str]] = None,
              platform: str = sys.platform) -> str:
    """``(await promisify(execFile)(file, args, {timeout, maxBuffer, env})).stdout``: the child's standard output
    decoded as UTF-8 (invalid bytes become U+FFFD).

    The three streams are socket pairs, as libuv creates them for ``'pipe'``; stdin stays open and unwritten until
    the child exits, when Node destroys it (a process the child started that reads it then sees its end), and the
    working directory is this process's. The call fails, as Node's rejects, when the file cannot be spawned, on a non-zero
    exit or a signal, at the timeout, and as soon as either output passes ``max_buffer`` bytes counted after
    decoding (Node's ``Buffer.byteLength`` of the decoded chunks). At the timeout and past the buffer, as in Node's
    ``execFile``, both outputs are closed before the child gets ``SIGTERM`` (so it gets ``EPIPE`` if it writes
    again); at the timeout its exit status then decides: a child that exits with 0 (one that had already exited
    while a process it started still holds an output open, or one that handles ``SIGTERM`` without writing)
    succeeds with the output read until then.
    """
    if not isinstance(file, str):
        raise TypeError('The "file" argument must be of type string.')
    argv = [nodefs.encode(file), *(_argument(value) for value in args)]
    deadline = time.monotonic() + timeout
    pairs = [socket.socketpair() for _ in range(3)]
    try:
        process = _spawn(argv, {'stdin': pairs[0][1].fileno(), 'stdout': pairs[1][1].fileno(),
                                'stderr': pairs[2][1].fileno(), 'env': dict(env) if env is not None else None},
                         platform)
    except BaseException:
        for pair in pairs:
            for end in pair:
                end.close()
        raise
    for _, child in pairs:
        child.close()
    ours = [pair[0] for pair in pairs]
    stdin, outputs = ours[0], ours[1:]
    parts: list[str] = []
    try:
        streams = {ours[1].fileno(): ('stdout', codecs.getincrementaldecoder('utf-8')('replace'), [0]),
                   ours[2].fileno(): ('stderr', codecs.getincrementaldecoder('utf-8')('replace'), [0])}
        with selectors.DefaultSelector() as selector:
            for end in outputs:
                selector.register(end, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if _timed_out(process, outputs):
                        return ''.join(parts)
                    raise ExecFileError(f'Command failed: timed out after {timeout} s')
                if stdin.fileno() != -1:
                    if process.poll() is None:
                        remaining = min(remaining, _EXIT_POLL_SECONDS)
                    else:
                        stdin.close()
                for key, _ in selector.select(remaining):
                    name, decoder, size = streams[key.fd]
                    chunk = os.read(key.fd, _READ_SIZE)
                    text = decoder.decode(chunk, final=not chunk)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    size[0] += len(text.encode('utf-8'))
                    if size[0] > max_buffer:
                        raise ExecFileError(f'{name} maxBuffer length exceeded')
                    if name == 'stdout':
                        parts.append(text)
        try:
            returncode = process.wait(timeout=max(deadline - time.monotonic(), 0))
        except subprocess.TimeoutExpired:
            if _timed_out(process, outputs):
                return ''.join(parts)
            raise ExecFileError(f'Command failed: timed out after {timeout} s') from None
    except BaseException:
        _kill(process, outputs)
        raise
    finally:
        for end in ours:
            end.close()
    if returncode < 0:
        raise ExecFileError(f'Command failed: killed by signal {-returncode}')
    if returncode != 0:
        raise ExecFileError(f'Command failed: exit code {returncode}')
    return ''.join(parts)
