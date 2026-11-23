"""Synthetic roots, stand-in interpreters and the Node reference for test_bundle.py (tests/service/README.md).

- ``bundle_root`` extends library_support's base root with what the bundles read: the radius optimization report
  behind ``results/v2/current_single_head_optimization.json`` (every way a record finds, or misses, its saved
  search), strict-area reports with saved initial states, traces and counters, and radius caches whose saved
  search names frozen-bank indices without coordinates (the export subprocess).
- ``cases_root`` holds hand-written records and source files for the paths a library record never takes:
  sources outside the experiment directories, checksums, member reads of ``null``, JavaScript coercions.
- ``fake_interpreters`` writes stand-ins for the compute interpreter: ``/bin/sh`` wrappers around one Python script
  whose mode prints its arguments and environment, coordinates from the indices, output at and beyond 1 MiB
  (counted after UTF-8 decoding), invalid UTF-8, text that is not JSON, or exits, kills itself or hangs.
- ``coordinate_fixture`` ports ``fixture`` of webapp/scripts/check-coordinate-bundles.mjs.

``run_node`` runs ``BUNDLE_DRIVER`` (Node's own ``LocalComputeQueue`` and ``experimentBundle``) once, with one
thread-pool worker and a queue directory that is never created; ``python_side`` computes the same cases with
``eeglayoutlab.jobs``. A bundle is compared as its text with ``original_record`` replaced by the SHA-256 of that
member's text, plus that digest (computed once per source file: the original report is 33 MB on a real root).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Callable, Optional

from eeglayoutlab.schemas import jsjson

from .key_parity_support import NODE_ENV
from .library_support import (
    DESIGN_IDENTITY, GRID, attempt, balanced, grid, library_root, offline_datasets, offline_radius,
    area_report, radius_result, sha, write, write_cache,
)

ROOT = Path(__file__).resolve().parents[2]
WEBAPP = ROOT / 'webapp'
RADIUS_POINTER = 'results/v2/current_single_head_optimization.json'
RADIUS_REPORT = 'results/v2/campaigns/radius/optimization_report.json'
STRICT_POINTER = 'results/v2/current_strict_area_budget_study.json'
MARKER = 'EEG_BUNDLE_MARKER'
UNDEFINED_VALUE = object()  # a member left out of a hand-written record

# --- Stand-in interpreters ---------------------------------------------------------------------------------------

FAKE = r'''
import json, os, signal, stat, sys, time
mode, args = sys.argv[1], sys.argv[2:]
out, err = sys.stdout.buffer, sys.stderr.buffer
MAX = 1024 * 1024


def padded(payload, size):
    return payload + b' ' * (size - len(payload))


def indices():
    return json.loads(args[args.index('--indices') + 1])


if mode == 'echo':
    names = ('PYTHONDONTWRITEBYTECODE', 'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'EEG_BUNDLE_MARKER')
    seen = {'argv': args, 'env': {name: os.environ.get(name) for name in names}, 'cwd': os.getcwd()}
    kinds = {fd: 'socket' if stat.S_ISSOCK(mode) else 'fifo' if stat.S_ISFIFO(mode) else 'other'
             for fd, mode in ((fd, os.fstat(fd).st_mode) for fd in (0, 1, 2))}
    out.write(json.dumps({'xyz_mm': [seen, {'stdio': [kinds[0], kinds[1], kinds[2]]}]}).encode())
elif mode == 'coords':
    out.write(json.dumps({'xyz_mm': [[[i * 0.5, -i, i / 1000] for i in group] for group in indices()]}).encode())
elif mode == 'chunked':
    for part in (b'{"xyz_mm":["\xe2\x82', b'\xac", ', b'"x"]}'):
        out.write(part)
        out.flush()
        time.sleep(0.05)
elif mode == 'exit':
    out.write(b'{"xyz_mm":[1,2]}')
    err.write(b'failed')
    sys.exit(3)
elif mode == 'signal':
    out.write(b'{"xyz_mm":[1,2]}')
    out.flush()
    os.kill(os.getpid(), signal.SIGTERM)
elif mode == 'exact':
    out.write(padded(b'{"xyz_mm":[[1,2,3],[4,5,6]]}', MAX))
elif mode == 'over':
    out.write(padded(b'{"xyz_mm":[[1,2,3],[4,5,6]]}', MAX + 1))
elif mode == 'replaced':
    out.write(b'{"xyz_mm":["\xff\xfe","\xc3"]}')
elif mode == 'replaced-exact':  # three bytes become three U+FFFD: six bytes more once decoded
    out.write(padded(b'{"xyz_mm":["\xff\xfe","\xc3"]}', MAX - 6))
elif mode == 'replaced-over':
    out.write(padded(b'{"xyz_mm":["\xff\xfe","\xc3"]}', MAX - 5))
elif mode == 'stderr-exact':
    err.write(b'e' * MAX)
    out.write(b'{"xyz_mm":[7,8]}')
elif mode == 'stderr-over':
    err.write(b'e' * (MAX + 1))
    out.write(b'{"xyz_mm":[7,8]}')
elif mode == 'text':
    out.write(b'not json')
elif mode == 'bom':
    out.write(b'\xef\xbb\xbf{"xyz_mm":[1,2]}')
elif mode == 'tail':
    out.write(b'{"xyz_mm":[1,2]}\xe2\x82')
elif mode == 'literals':
    out.write(b'{"xyz_mm":[1e400,-0]} \n')
elif mode == 'short':
    out.write(b'{"xyz_mm":[[[1,2,3]]]}')
elif mode == 'string':
    out.write(json.dumps({'xyz_mm': 'a\U0001F600'}).encode())
elif mode == 'object':
    out.write(b'{"xyz_mm":{"1":"b","0":"a"}}')
elif mode == 'number':
    out.write(b'{"xyz_mm":5}')
elif mode == 'missing-member':
    out.write(b'{"other":1}')
elif mode == 'null':
    out.write(b'null')
elif mode == 'sleep':
    time.sleep(60)
elif mode == 'stubborn':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    out.write(b'{"xyz_mm":[1,2]}')
    out.flush()
    time.sleep(60)
elif mode == 'stdin':
    sys.stdin.buffer.read()
    out.write(b'{"xyz_mm":[1,2]}')
'''

# The modes both hosts run in the parity test (the hanging ones are Python-only, with a short timeout).
PARITY_MODES = ('echo', 'coords', 'chunked', 'exit', 'signal', 'exact', 'over', 'replaced', 'replaced-exact',
                'replaced-over', 'stderr-exact', 'stderr-over', 'text', 'bom', 'tail', 'literals', 'short', 'string',
                'object', 'number', 'missing-member', 'null')
HANGING_MODES = ('sleep', 'stubborn', 'stdin')


def fake_interpreters(directory: Path) -> dict[str, str]:
    """A ``/bin/sh`` wrapper per mode, plus a missing interpreter and one that cannot be executed."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / 'fake.py'
    script.write_text(FAKE, encoding='utf-8')
    paths = {}
    for mode in PARITY_MODES + HANGING_MODES:
        wrapper = directory / f'python-{mode}'
        wrapper.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -I {shlex.quote(str(script))} '
                           f'{shlex.quote(mode)} "$@"\n', encoding='utf-8')
        wrapper.chmod(0o755)
        paths[mode] = str(wrapper)
    paths['missing'] = str(directory / 'no-such-python')
    plain = directory / 'not-executable'
    plain.write_text('#!/bin/sh\necho "{}"\n', encoding='utf-8')
    plain.chmod(0o644)
    paths['not-executable'] = str(plain)
    return paths


# --- The bundle root ---------------------------------------------------------------------------------------------

def _meters(shift: float) -> list:
    return [[(x + shift) / 1000, y / 1000, 0.5e-3 * k] for k, (x, y, _) in enumerate(GRID)]


def radius_report(data: dict) -> dict:
    """The optimization report behind the early radius experiments: per condition of ``data``, the saved search of
    its finalists, matched by evaluation id and objective."""
    conditions = []
    for index, c in enumerate(data['conditions']):
        if index == 4:
            continue  # a condition the report does not have: no entry, no condition in the configuration
        finalists = []
        for k, v in enumerate(c['variants']):
            search: dict[str, Any] = {'evaluated_counts': {'coordinate_candidates_scored': 2048 + index},
                                      'center_attempts': list(range(index + k))}
            if index == 0:
                search.update(initial={'xyz_m': _meters(k), 'region_indices': v['region_indices'],
                                       'objective_score': 0.5 + k, 'field20': 0.1, 'sensitivity_tail': 0.05},
                              final={'xyz_m': _meters(k + 1), 'region_indices64': v['region_indices'],
                                     'objective_score': 0.75 + k},
                              trace=[{'objective_after': 0.6}, {'after': None, 'objective_after': 0.7},
                                     {'after': 'x'}, {'objective_before': 0.1}, 7, 'move', {'objective_after': 0.75}])
            elif index == 1:
                search.update(initial={'xyz_mm': v['xyz_mm'], 'objective': 0.25, 'field20': 0.3},
                              final={'xyz_mm': v['xyz_mm'], 'field20': 0.4, 'sensitivity_tail': 0.35},
                              trace=[{'after': 0.3}, {'after': 0.35}])
            elif index == 2:
                search.update(initial={'field20': 0.2, 'sensitivity_tail': 0.1}, trace=[])
            evaluation = {'id': v['id'] if index != 3 or k == 0 else 'another-layout'}
            finalist: dict[str, Any] = {'evaluation': evaluation, 'objective': v['objective']}
            if index != 3:
                finalist['search'] = search
            finalists.append(finalist)
        conditions.append({'condition': {'id': c['id'], 'R': c['R'], 'radius_mm': c['radius_mm']}, 'search': {},
                           'finalists': finalists})
    return {'schema_version': 'fixture-radius-report/1',
            'config': {'condition': 'replaced by the entry', 'search': {'restarts': 2}, '7': 'index key'},
            'conditions': conditions}


def area_with_history(report: dict) -> dict:
    """An area report whose frozen finalists keep their saved search, in a different shape per condition."""
    for n, entry in enumerate(report['conditions']):
        if not entry['finalists']:
            continue
        entry['attempts'] = [{'trial': k} for k in range(n % 4)]
        if n % 3:
            entry['counts'] = {'coordinate_proposals': 1536 + n, 'field_scores': 143 + n, 'geometry_trials': n}
        f = entry['finalists'][1]
        kind = n % 5
        if kind == 0:
            f.update(initial={'xyz_mm': grid(n + 0.5), 'region_indices': balanced(entry['condition']['region_count']),
                              'field20': 0.25, 'sensitivity_tail': 0.125},
                     trace=[{'after': 0.2 + k * 1e-3, 'before': 0.2} for k in range(n % 7)])
        elif kind == 1:
            f.update(initial={'objective_score': 0.3, 'region_indices64': [0] * 64},
                     final={**f['final'], 'xyz_m': _meters(n)}, trace=[{'objective_after': 0.31}])
        elif kind == 3:
            f.update(initial={}, trace=[])
        elif kind == 4:
            f.update(initial={'region_indices': None, 'region_indices64': balanced(2), 'objective': 0.9})
    return report


HISTORY_REQUESTS = {
    'history': {'region_count': 2, 'radius_mm': 30, 'mode': 'low_hair'},
    'history-partial': {'region_count': 2, 'radius_mm': 45, 'mode': 'low_hair'},
    'history-no-final': {'region_count': 2, 'radius_mm': 50, 'mode': 'low_hair'},
    'history-coordinates': {'region_count': 2, 'radius_mm': 55, 'mode': 'low_hair'},
}


def bank_indices(shift: int) -> list[int]:
    return [(k * 7 + shift) % 500 for k in range(64)]


def diagnostics(name: str) -> dict:
    """The saved search of a radius worker result: frozen-bank indices, without coordinates unless named so."""
    initial: dict[str, Any] = {'candidate_bank_indices': bank_indices(0), 'field20': 0.4, 'sensitivity_tail': 0.2,
                               'objective': 0.2, 'region_indices': balanced(2)}
    final: dict[str, Any] = {'candidate_bank_indices': bank_indices(3), 'field20': 0.45, 'sensitivity_tail': 0.25,
                             'objective': 0.25, 'region_indices': balanced(2)}
    if name in ('history-partial', 'history-coordinates'):
        initial['xyz_mm'] = grid(1.0)
    if name == 'history-coordinates':
        final['xyz_mm'] = grid(2.0)
    d: dict[str, Any] = {'initial': initial, 'trace': [{'before': 0.2, 'after': 0.22}, {'after': 0.25}],
                         'scored_layouts': 12, 'coordinate_proposals': 34, 'attempts': [{}, {}, {}]}
    if name != 'history-no-final':
        d['final'] = final
    return d


def bundle_root(root: Path, python: str) -> dict:
    """The base root of library_support with the bundles' sources; returns the record keys by name."""
    from eeglayoutlab.jobs.radius import RadiusCache

    keys = library_root(root, python)
    data = offline_radius()
    report = write(root, RADIUS_REPORT, radius_report(data))
    data['provenance'] = {'source': 'fixture', 'report_sha256': sha(report)}
    offline_datasets(root, radius=data, current=area_with_history(area_report()))
    write(root, RADIUS_POINTER, {'report': RADIUS_REPORT, 'sha256': sha(report)})
    radius = RadiusCache(str(root), python)
    for index, (name, request) in enumerate(HISTORY_REQUESTS.items()):
        key = radius.identity_for(request)[1]
        result = radius_result(request, keys['provenance'])
        result['diagnostics'] = diagnostics(name)
        write_cache(root, key, request, result, f'2026-09-2{index}T12:00:00Z')
        keys['radius'][name] = key
    return keys


# --- Hand-written records ----------------------------------------------------------------------------------------

def cases_root(root: Path) -> None:
    """A root with the pointer files the hand-written cases need, and a link out of the experiment directory."""
    root.mkdir(parents=True)
    report = write(root, 'results/v2/cases/radius-report.json', {'config': ['a', 'b'], 'conditions': []})
    write(root, RADIUS_POINTER, {'report': 'results/v2/cases/radius-report.json', 'sha256': sha(report)})
    write(root, 'outside/raw.json', {'key': 'x'})
    write(root, 'webapp/public/data/raw.json', {'config': 'cd', 'conditions': [None]})
    (root / 'results/v2/cases').mkdir(parents=True, exist_ok=True)
    (root / 'results/v2/cases/escape.json').symlink_to(root / 'outside/raw.json')
    (root / 'results/v2/cases/public.json').symlink_to(root / 'webapp/public/data/raw.json')
    (root / 'results/v2/cases/directory.json').mkdir()


def raw_cache(result: Any, key: str) -> dict:
    return {'key': key, 'result': result, 'result_sha256': jsjson.sha256_hex(result)}


def record_cases(root: Path, pythons: dict[str, str]) -> list[dict]:
    """Hand-written records with their source files under ``root`` (``cases_root``)."""
    cases: list[dict] = []

    def case(name: str, record: Any, raw: Any = None, *, python: Optional[str] = None, text: Optional[str] = None,
             file: Optional[str] = None) -> None:
        relative = file or f'results/v2/cases/{name}.json'
        if text is not None or raw is not None:
            write(root, relative, text if text is not None else raw)
        if isinstance(record, dict) and isinstance(record.get('provenance'), dict) and file is None:
            record['provenance'].setdefault('file', relative)
        cases.append({'name': name, 'root': str(root), 'record': jsjson.stringify(record), 'python': python})

    def cache(name: str, d: Any, *, python: Optional[str] = None, provenance: Optional[dict] = None,
              record: Optional[dict] = None) -> None:
        id = sha(name)
        body = {'id': id, 'dataset_id': 'cache', 'request': {'region_count': 2}, 'layout': {'referenceXyzMm': GRID},
                'provenance': {'bank_sha256': sha('bank'), **(provenance or {})}, **(record or {})}
        case(name, body, raw_cache({'diagnostics': d}, id), python=python)

    history = diagnostics('history')
    # The export subprocess with every stand-in (``pythons``: mode -> path), and the arguments Node converts with
    # String() (a NUL byte cuts a converted value; it is refused in a string).
    for mode, python in pythons.items():
        cache(f'python-{mode}', history, python=python)
    for name, value in (('undefined', UNDEFINED_VALUE), ('null', None), ('number', 5), ('array', [sha('bank'), 'x']),
                        ('nested', [[sha('bank')], []]), ('object', {'a': 1}), ('to-string', {'toString': 'x'}),
                        ('nul', 'a\u0000b'), ('array-nul', ['a\u0000b']), ('surrogate', '\ud800')):
        provenance = {} if value is UNDEFINED_VALUE else {'bank_sha256': value}
        cache(f'bank-{name}', history, python=pythons['echo'], record={'provenance': provenance})
    cache('python-empty', history, python='')
    cache('python-number', history, python=5)  # type: ignore[arg-type]
    cache('python-nul', history, python='python\u0000')
    cache('python-relative', history, python='no-such-interpreter-on-path')
    # Which snapshots ask for coordinates.
    cache('final-null', {**history, 'final': None}, python=pythons['coords'])
    cache('final-false', {**history, 'final': False}, python=pythons['echo'])
    cache('initial-zero', {**history, 'initial': 0}, python=pythons['echo'])
    cache('initial-string', {**history, 'initial': 'state'}, python=pythons['echo'])
    cache('falsy-xyz', {**history, 'initial': {**history['initial'], 'xyz_mm': 0}}, python=pythons['coords'])
    cache('empty-xyz', {**history, 'initial': {**history['initial'], 'xyz_mm': []},
                        'final': {**history['final'], 'xyz_mm': ''}}, python=pythons['coords'])
    coerced = [[0.001, '2', None], [True, [3], {}], ['0x10', ' 1e3 ', '', '\u00a0', 'abc', '-0', '.5e1']]
    cache('xyz-m', {**history, 'initial': {'xyz_m': coerced, 'region_indices': None, 'region_indices64': None},
                    'final': {'xyz_m': [], 'region_indices64': [1]}})
    cache('xyz-m-number', {**history, 'initial': {'xyz_m': 5}})
    cache('xyz-m-null-point', {**history, 'initial': {'xyz_m': [None]}})
    cache('xyz-m-string-point', {**history, 'initial': {'xyz_m': ['abc']}})
    cache('xyz-m-to-string', {**history, 'initial': {'xyz_m': [[{'toString': 1}]]}})
    cache('xyz-m-value-of', {**history, 'initial': {'xyz_m': [[{'valueOf': 1}, [[]], [1, 2]]]}})
    cache('xyz-m-null', {**history, 'initial': {'xyz_m': None, 'xyz_mm': None}}, python=pythons['coords'])
    # The saved search: scores, traces and counters.
    cache('scores', {'initial': {'field20': -0.0, 'sensitivity_tail': 0.0}, 'final': {'objective_score': '1'},
                     'trace': [{'after': 1}, {'objective_after': 2}, {'after': None, 'objective_after': 3},
                               {'after': 'x'}, 5, 'str', [], {'after': True}, {'after': {'a': 1}}],
                     'attempts': 'abcd', 'evaluated': {'field_scores': 3, 'coordinate_proposals': None},
                     'evaluated_counts': None, 'center_attempts': [1]})
    cache('scores-objective', {'initial': {'objective_score': None, 'objective': 0.5}, 'attempts': {'length': 7},
                               'scored_layouts': 0, 'coordinate_proposals': False})
    cache('scores-none', {'initial': {'field20': 0.5}, 'attempts': 3, 'center_attempts': 'xy'})
    cache('trace-object', {'trace': {'entries': 1}})
    cache('trace-string', {'trace': 'abc'})
    cache('trace-null-move', {'trace': [{'after': 1}, None]})
    cache('diagnostics-string', 'text')
    cache('diagnostics-false', False)
    cache('diagnostics-missing', None)
    text = ('{"key":"%s","result":{"diagnostics":{"initial":{"objective_score":1e400},'
            '"trace":[{"after":1e400},{"after":-0}]}},' % sha('infinite'))
    result_text = '{"diagnostics":{"initial":{"objective_score":1e400},"trace":[{"after":1e400},{"after":-0}]}}'
    infinite = {'id': sha('infinite'), 'dataset_id': 'cache', 'provenance': {}}
    case('infinite', infinite, text=text + '"result_sha256":"%s"}' % sha(jsjson.stringify(jsjson.parse(result_text))))
    # Radius cache checks.
    cache('key-mismatch', history, record={'id': sha('another')})
    case('result-missing', {'id': sha('result-missing'), 'dataset_id': 'cache', 'provenance': {}},
         {'key': sha('result-missing')})
    case('raw-null', {'id': sha('raw-null'), 'dataset_id': 'cache', 'provenance': {}}, text='null')
    case('raw-string', {'id': sha('raw-string'), 'dataset_id': 'cache', 'provenance': {}}, text='"text"')
    case('not-json', {'id': sha('not-json'), 'dataset_id': 'cache', 'provenance': {}}, text='{broken')
    case('bom', {'id': sha('bom'), 'dataset_id': 'cache', 'provenance': {}}, text='\ufeff{}')
    # Source paths and checksums.
    good = raw_cache({'diagnostics': history}, sha('paths'))
    for name, provenance in (('no-file', {'file': None}), ('number-file', {'file': 5}),
                             ('escape', {'file': 'results/v2/cases/escape.json'}),
                             ('public', {'file': 'results/v2/cases/public.json'}),
                             ('outside', {'file': 'outside/raw.json'}), ('absolute', {'file': '/etc/hosts'}),
                             ('parent', {'file': 'results/v2/../outside/raw.json'}),
                             ('missing-file', {'file': 'results/v2/cases/none.json'}),
                             ('directory', {'file': 'results/v2/cases/directory.json'}),
                             ('webapp-data', {'file': 'webapp/public/data/raw.json'}),
                             ('sha-match', {'sha256': sha(jsjson.stringify(good))}),
                             ('sha-mismatch', {'sha256': sha('other')}), ('sha-zero', {'sha256': 0}),
                             ('sha-empty', {'sha256': ''})):
        body = {'id': sha('paths'), 'dataset_id': 'strict_area', 'provenance': dict(provenance)}
        if 'file' not in provenance:
            case(name, body, good)
        else:
            case(name, body, file=provenance['file'] if isinstance(provenance['file'], str) else 'unused')
    case('no-provenance', {'id': sha('x'), 'dataset_id': 'strict_area'})
    case('record-null', None)
    # The strict-area search over unusual reports.
    area = {'config': {'spacing_mm': 4, 'condition': 'shadowed'},
            'conditions': [{'condition': {'id': 'a'}, 'finalists': [{'objective': 'min'}],
                            'attempts': None, 'counts': {'field_scores': 1}},
                           {'condition': {'id': 'b'}, 'finalists': ['min', {'objective': 'other'}], 'attempts': 'xyz'},
                           {'condition': {'id': 'c'}, 'finalists': {'find': 1}},
                           {'condition': {'id': 'd'}, 'finalists': [None]},
                           {'condition': {'id': 'e'}, 'finalists': [0, {'objective': 'min', 'initial': False}]}]}
    for name, condition, objective in (('area-a', 'a', 'min'), ('area-b', 'b', 'missing'), ('area-c', 'c', 'min'),
                                       ('area-d', 'd', 'min'), ('area-e', 'e', 'min'), ('area-none', 'z', 'min'),
                                       ('area-b-string', 'b', UNDEFINED_VALUE)):
        provenance = {'condition_id': condition}
        if objective is not UNDEFINED_VALUE:
            provenance['objective'] = objective
        case(name, {'id': sha(name), 'dataset_id': 'historical_area', 'provenance': provenance}, area)
    for name, raw in (('area-config-string', {'config': 'ab', 'conditions': []}),
                      ('area-config-array', {'config': [1, 2], 'conditions': None}),
                      ('area-conditions-object', {'conditions': {'find': 1}}),
                      ('area-conditions-string', {'conditions': 'abc'}),
                      ('area-condition-missing', {'conditions': [{}]}),
                      ('area-entry-null', {'conditions': [None]}),
                      ('area-raw-null', None)):
        case(name, {'id': sha(name), 'dataset_id': 'strict_area', 'provenance': {'condition_id': 'a'}},
             raw, text='null' if raw is None else None)
    case('area-no-provenance-conditions', {'id': sha('p'), 'dataset_id': 'strict_area',
                                           'provenance': {'file': 'results/v2/cases/area-a.json'}})
    # The early radius experiments: the pointer, its digest and the report.
    report_sha = sha(jsjson.stringify({'config': ['a', 'b'], 'conditions': []}))
    for name, provenance in (('radius-ok', {'original': {'report_sha256': report_sha}, 'condition_id': 'c'}),
                             ('radius-sha', {'original': {'report_sha256': sha('another')}}),
                             ('radius-no-original', {}), ('radius-falsy', {'original': {'report_sha256': ''}})):
        case(name, {'id': sha(name), 'dataset_id': 'offline_radius', 'request': None, 'layout': {'id': 'v'},
                    'provenance': {'file': 'ignored', **provenance}})
    case('radius-no-provenance', {'id': sha('r'), 'dataset_id': 'offline_radius'})
    # Other datasets.
    case('other-dataset', {'id': sha('other'), 'dataset_id': 'something', 'provenance': {'objective': 'o'}},
         {'provenance': {'p': 1}})
    case('other-dataset-null', {'id': sha('other-null'), 'dataset_id': 'something', 'provenance': {}}, text='null')
    case('no-id', {'dataset_id': 'strict_area', 'provenance': {'condition_id': 'a', 'objective': 'min'}},
         raw=area)
    return cases


def coordinate_cases(root: Path, record: dict) -> list[dict]:
    """A saved coordinate evaluation of ``root`` (``record`` as the library gives it) with its record edited."""
    cases = []

    def case(name: str, change: Callable[[dict], None]) -> None:
        edited = json.loads(json.dumps(record))
        change(edited)
        cases.append({'name': name, 'root': str(root), 'record': jsjson.stringify(edited), 'python': None})

    def setter(path: tuple, value: Any) -> Callable[[dict], None]:
        def change(target: dict) -> None:
            for key in path[:-1]:
                target = target[key]
            if value is _DELETE:
                del target[path[-1]]
            else:
                target[path[-1]] = value
        return change

    case('coordinate-ok', lambda r: None)
    for name, path, value in (
            ('coordinate-path', ('provenance', 'design_result', 'path'), 'results/v2/reference.json'),
            ('coordinate-path-missing', ('provenance', 'design_result', 'path'), _DELETE),
            ('coordinate-sha-missing', ('provenance', 'design_result', 'sha256'), _DELETE),
            ('coordinate-sha-upper', ('provenance', 'design_result', 'sha256'),
             record['provenance']['design_result']['sha256'].upper()),
            ('coordinate-sha-other', ('provenance', 'design_result', 'sha256'), sha('other')),
            ('coordinate-id-array', ('id',), [record['id']]),
            ('coordinate-id-upper', ('id',), record['id'].upper()),
            ('coordinate-label', ('label',), 'another record'),
            ('coordinate-status', ('status',), 'no_layout'),
            ('coordinate-count', ('region_count',), 3),
            ('coordinate-layout-id', ('layout', 'id'), sha('x')),
            ('coordinate-layout-missing', ('layout',), _DELETE),
            ('coordinate-regions', ('layout', 'regionIndices', 0), 1),
            ('coordinate-xyz', ('layout', 'xyzMm', 0, 2), 1.0000001),
            ('coordinate-metric', ('metrics', 'conditional_global'), 0.99),
            ('coordinate-metric-extra', ('metrics', 'extra'), 1),
            ('coordinate-metric-missing', ('metrics', 'median_mm'), _DELETE),
            ('coordinate-forward-mode', ('provenance', 'forward_mode'), 'cached_fem'),
            ('coordinate-provenance', ('provenance',), _DELETE),
    ):
        case(name, setter(path, value))
    case('coordinate-metric-order', lambda r: r.update(metrics=dict(reversed(list(r['metrics'].items())))))
    return cases


class _Delete:
    pass


_DELETE = _Delete()


DESCRIBE = [
    ({'dataset_id': 'offline_radius', 'provenance': {}, 'request': None}, {}),
    ({'dataset_id': 'offline_radius', 'provenance': {'condition_id': 'c'}, 'layout': {'id': 'v'}},
     {'config': 'xy',
      'conditions': [{'condition': {'id': 'c'}, 'finalists': [{'evaluation': None, 'objective': None}]}]}),
    ({'dataset_id': 'offline_radius', 'provenance': {'condition_id': 'c', 'objective': 'o'}, 'layout': {'id': 'v'}},
     {'conditions': [{'condition': {'id': 'c'}, 'finalists': [{'evaluation': {'id': 'v'}, 'objective': 'o',
                                                              'search': 'text'}]}]}),
    ({'dataset_id': 'offline_radius', 'provenance': {'condition_id': 'c'}},
     {'conditions': [{'condition': {'id': 'c'}, 'finalists': 'abc'}]}),
    ({'dataset_id': 'offline_radius', 'provenance': {'condition_id': 'c'}},
     {'conditions': [{'condition': {'id': 'c'}, 'finalists': [None]}]}),
    ({'dataset_id': 'offline_radius'}, {'conditions': [{'condition': {'id': 'c'}}]}),
    ({'dataset_id': 'offline_radius'}, {'conditions': []}),
    ({'dataset_id': 'offline_radius', 'provenance': {}}, None),
    ({'dataset_id': 'design_evaluation'}, {'result': {'request': {'a': 1}}}),
    ({'dataset_id': 'design_evaluation'}, {'result': {}}),
    ({'dataset_id': 'design_evaluation'}, {}),
    ({'dataset_id': 'cache', 'provenance': {'objective': None}, 'request': {'x': 1}}, {'result': None}),
    ({'dataset_id': 'cache', 'provenance': {}}, {'result': {'diagnostics': {'initial': [1], 'final': 'f'}}}),
    ({'dataset_id': 'cache', 'provenance': {}}, 'text'),
    ({'dataset_id': 'cache'}, {}),
    ({'dataset_id': ['cache'], 'provenance': {}}, {}),
    ({'dataset_id': 'strict_area', 'provenance': {'condition_id': None}}, {'conditions': [{'condition': {'id': None},
                                                                                           'finalists': []}]}),
    ({'provenance': {}}, None),
    (None, {}),
]


# --- coordinate_fixture: check-coordinate-bundles.mjs -------------------------------------------------------------

def coordinate_fixture(directory: Path, **extra: Any) -> dict:
    """``fixture(t, extra)``: a saved coordinate evaluation (serialization data only), its reference report and its
    library record; ``persist(value)`` rewrites the file and refreshes only the record's outer file digest."""
    from eeglayoutlab.jobs.identity import request_key
    from eeglayoutlab.jobs.reception_records import design_reception_record

    from .library_support import design_request

    directory.mkdir(parents=True)
    root = Path(os.path.realpath(directory))
    request = design_request('Coordinate serialization fixture', **extra)
    id = request_key(request, DESIGN_IDENTITY)
    result = {
        'schema': 'design-evaluation/1', 'status': 'completed', 'request': request,
        'forward_mode': 'head_scalp_node_table' if request.get('head_id') else 'direct_fem',
        'nominal': {'field_relative': 0.9 / 0.99, 'field_absolute': 0.9, 'reference_field_absolute': 0.99,
                    'sensitivity_tail': 0.4, 'localization_relative': 0.5, 'median_mm': 10, 'p90_mm': 20,
                    'reference_median_mm': 9, 'reference_p90_mm': 18},
        'projection_max_mm': 1, 'evaluated_xyz_mm': [[x, y, 1] for x, y, _ in GRID],
        'provenance': {'candidate_count': 64}, 'trials': [],
    }
    relative = f'results/v2/design_evaluation_jobs/{id}/cache.json'
    cache = jsjson.parse(jsjson.stringify({'key': id, 'identity': DESIGN_IDENTITY, 'result': result,
                                           'result_sha256': jsjson.sha256_hex(result),
                                           'finished_at': '2026-10-14T00:00:00Z'}))
    report = write(root, 'results/v2/reference.json', {'baseline': {'reference_xyz_mm': GRID}})
    write(root, STRICT_POINTER, {'report': 'results/v2/reference.json', 'sha256': sha(report)})
    file = root / relative
    write(root, relative, cache)
    record = design_reception_record(str(root), id, conditions=True)

    def persist(value: dict) -> None:
        data = write(root, relative, value)
        record['provenance']['design_result']['sha256'] = sha(data)

    return {'root': root, 'id': id, 'record': record, 'cache': cache, 'file': file, 'relative': relative,
            'persist': persist}


# --- Node reference ----------------------------------------------------------------------------------------------

BUNDLE_DRIVER = r"""
// Node reference of tests/service/bundle_support.py: library records through Node's own LocalComputeQueue (one per
// root, with a queue directory that is never created) and experimentBundle as the library route calls it, the same
// with hand-written records, and describeSearch.
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const [specPath, outPath] = process.argv.slice(2);
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
const load = path => import(pathToFileURL(`${spec.webapp}/${path}`).href);
const { LocalComputeQueue } = await load('server/local-compute-server.mjs');
const { experimentBundle, describeSearch } = await load('server/experiment-bundle.mjs');
const sha = text => createHash('sha256').update(text).digest('hex');
const failure = error => ({ ok: false, code: error?.code ?? null, name: error?.name ?? null,
  message: String(error?.message ?? error), status: error?.status ?? null });
async function attempt(run) {
  try { return { ok: true, value: await run() }; } catch (error) { return failure(error); }
}
const originals = new Map();
function packed(bundle) {
  const key = bundle.source.sha256;
  if (!originals.has(key)) originals.set(key, sha(JSON.stringify(bundle.original_record)));
  const original = originals.get(key);
  return { text: JSON.stringify({ ...bundle, original_record: original }), original };
}
const out = { library: {}, records: {}, describe: [] };
for (const item of spec.roots) {
  const queue = new LocalComputeQueue({ repositoryRoot: item.root, queueDirectory: spec.queueDirectory });
  out.library[item.id] = { root: queue.root, python: queue.python, bundles: {} };
  for (const [name, id, python] of item.cases) {
    out.library[item.id].bundles[name] = await attempt(async () => {
      const record = await queue.library.get(id);
      return record ? packed(await experimentBundle(queue.root, record, { python: python ?? queue.python })) : null;
    });
  }
  queue.dispose();
}
for (const item of spec.records ?? [])
  out.records[item.name] = await attempt(async () => packed(await experimentBundle(item.root, JSON.parse(item.record),
    item.python === null ? undefined : { python: item.python })));
for (const [record, raw] of spec.describe ?? [])
  out.describe.push(await attempt(() => JSON.stringify(describeSearch(JSON.parse(record), JSON.parse(raw)))));
writeFileSync(outPath, JSON.stringify(out));
process.exit(0);
"""


def run_node(spec: dict, scratch: Path) -> dict:
    """Runs ``BUNDLE_DRIVER`` once (``spec``: ``{roots: [{id, root, cases: [[name, id, python|null]]}], records:
    [{name, root, record, python}], describe: [[recordText, rawText]]}``), with ``MARKER`` set."""
    queue = scratch / 'node-queue'  # resolved by the queue, never created
    driver, spec_path, out_path = scratch / 'bundle.mjs', scratch / 'bundle-spec.json', scratch / 'bundle-node.json'
    driver.write_text(BUNDLE_DRIVER, encoding='utf-8')
    spec_path.write_text(jsjson.stringify({'webapp': str(WEBAPP), 'queueDirectory': str(queue), **spec}),
                         encoding='utf-8')
    subprocess.run(['node', str(driver), str(spec_path), str(out_path)], check=True, cwd=ROOT,
                   env={**NODE_ENV, MARKER: 'inherited'})
    assert not queue.exists()
    return json.loads(out_path.read_text(encoding='utf-8'))


# --- Python side -------------------------------------------------------------------------------------------------

class Packer:
    """``packed(bundle)`` of the driver: the original record's digest is computed once per source file."""

    def __init__(self) -> None:
        self.originals: dict[str, str] = {}

    def __call__(self, bundle: dict) -> dict:
        key = bundle['source']['sha256']
        if key not in self.originals:
            self.originals[key] = sha(jsjson.stringify(bundle['original_record']))
        original = self.originals[key]
        return {'text': jsjson.stringify({**bundle, 'original_record': original}), 'original': original}


def python_side(spec: dict) -> dict:
    """The driver's output computed with ``eeglayoutlab.jobs`` (run with ``MARKER`` set and the working directory
    at the repository, as the driver runs)."""
    from eeglayoutlab.jobs.bundle import describe_search, experiment_bundle
    from eeglayoutlab.jobs.library import Library
    from eeglayoutlab.jobs.runtime import runtime_config

    packed = Packer()
    out: dict[str, Any] = {'library': {}, 'records': {}, 'describe': []}
    for item in spec.get('roots', []):
        config = runtime_config(item['root'])
        library = Library(item['root'], config)
        entry = out['library'][item['id']] = {'root': library.root, 'python': config.python, 'bundles': {}}
        for name, id, python in item['cases']:
            def bundle(id: str = id, python: Optional[str] = python) -> Any:
                record = library.get(id)
                if record is None:
                    return None
                return packed(experiment_bundle(library.root, record, config.python if python is None else python))
            entry['bundles'][name] = attempt(bundle)
    for item in spec.get('records', []):
        out['records'][item['name']] = attempt(lambda item=item: packed(experiment_bundle(
            item['root'], jsjson.parse(item['record']), item['python'])))
    for record, raw in spec.get('describe', []):
        out['describe'].append(attempt(lambda record=record, raw=raw: jsjson.stringify(
            describe_search(jsjson.parse(record), jsjson.parse(raw)))))
    return out
