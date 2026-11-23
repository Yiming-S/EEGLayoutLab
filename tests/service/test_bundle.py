"""The experiment bundle (``eeglayoutlab.jobs.bundle``) equals Node's ``experimentBundle`` (phase 2 slice 3), and
ports webapp/scripts/check-coordinate-bundles.mjs and the bundle tests of check-source-upgrade.mjs.

- Parity (tests/service/bundle_support.py): Node's own queue and ``experimentBundle`` against the Python library
  and bundle, on a root with every kind of library record and saved search, on a link to it (every source then
  leaves the experiment directory), on hand-written records and sources, and for ``describeSearch`` alone. The
  frozen-bank coordinates come from stand-in interpreters run by both hosts: their arguments, environment, working
  directory and kind of streams, output at and beyond 1 MiB, invalid UTF-8, non-JSON text, exits and signals.
  Bundles compare as text (``original_record`` by the digest of its text); failures by Node's code, else by
  message.
- The ports of the Node tests use their fixtures (``coordinate_fixture``). Node's own bundle tests never run the
  export subprocess (they pass no interpreter), and neither do the ports.
- With ``EEG_KEY_PARITY_ROOT`` (marked ``data_bundle``) the dataTests run on that installation, and the parity
  comparison covers every record there, the export of the frozen-bank coordinates with the installation's own
  interpreter included. Nothing is written under any root.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time

import pytest

from schema_parity_support import require

require('pydantic')

from eeglayoutlab.jobs import bundle as bundle_module  # noqa: E402
from eeglayoutlab.jobs.bundle import (  # noqa: E402
    BundleError, ExecFileError, deep_strict_equal, describe_search, exec_file, experiment_bundle, to_number,
)
from eeglayoutlab.jobs.design_result import DesignResultError  # noqa: E402
from eeglayoutlab.jobs.identity import JSTypeError  # noqa: E402
from eeglayoutlab.jobs.library import Library, area_records, radius_records  # noqa: E402
from eeglayoutlab.jobs.reception_records import design_reception_record  # noqa: E402
from eeglayoutlab.jobs.runtime import runtime_config  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402

from .bundle_support import (  # noqa: E402
    DESCRIBE, HISTORY_REQUESTS, MARKER, PARITY_MODES, ROOT, bundle_root, cases_root, coordinate_cases,
    coordinate_fixture, fake_interpreters, python_side, record_cases, run_node,
)
from .key_parity_support import NODE_ENV, SPATIAL, needs_node  # noqa: E402
from .library_support import (  # noqa: E402
    GRID, code_tree, design_record, design_request, forward_inputs, node_failure, offline_datasets, sha,
)

NODE_SOURCE = ROOT / 'webapp/server/experiment-bundle.mjs'
NAN = float('nan')


def snapshot(root: Path) -> dict:
    """Every path under ``root`` with its type, size and modification time (links not followed)."""
    state = {}
    for directory, names, files in os.walk(root):
        for name in names + files:
            info = os.lstat(os.path.join(directory, name))
            state[os.path.join(directory, name)] = (info.st_mode, info.st_size, info.st_mtime_ns)
    return state


# --- check-coordinate-bundles.mjs ---------------------------------------------------------------------------------

def test_coordinate_bundle_preserves_input_and_evaluated_coordinates_separately(tmp_path):
    """:53."""
    fx = coordinate_fixture(tmp_path / 'root')
    before, record_before = fx['file'].read_bytes(), copy.deepcopy(fx['record'])
    bundle = experiment_bundle(str(fx['root']), fx['record'])
    cache = fx['cache']
    assert bundle['schema'] == 'eeg-reproducibility-bundle/1'
    assert bundle['record_id'] == fx['id']
    assert bundle['source'] == {'path': fx['relative'], 'sha256': sha(before)}
    assert bundle['original_record'] == cache
    assert bundle['record']['layout']['xyzMm'] == cache['result']['evaluated_xyz_mm']
    assert bundle['record']['layout']['xyzMm'] != cache['result']['request']['design']['xyz_mm']
    assert bundle['record']['metrics'] == {**cache['result']['nominal'], 'conditional_global': 0.4}
    assert bundle['reproduction']['request'] == cache['result']['request']
    assert bundle['reproduction']['identity'] == cache['identity']
    assert bundle['reproduction']['entrypoint'] == 'scripts/design_evaluation.py'
    assert bundle['reproduction']['metrics_recomputed'] is False
    search = bundle['search']
    assert search['history_status'] == 'not_applicable_coordinate_evaluation'
    assert (search['objective'], search['initial'], search['final']) == (None, None, None)
    assert search['trace'] == [] and search['curve'] == []
    assert bundle['snapshots'] == [None, None]
    assert re.search('输入坐标.*实际评价坐标', bundle['coordinate_note'])
    assert fx['record'] == record_before
    assert fx['file'].read_bytes() == before


def test_coordinate_bundle_of_a_library_record_starts_no_worker(tmp_path):
    """:80, without the HTTP layer (the library route belongs to the routes of slice 3): the record the library
    gives is packed with its source, and no interpreter is started even when one is configured."""
    fx = coordinate_fixture(tmp_path / 'root')

    class Stub:  # the Node test's library: get(key) gives the record of its own id only
        def get(self, key):
            return fx['record'] if key == fx['id'] else None

    record = Stub().get(fx['id'])

    def started(*args, **kwargs):
        pytest.fail('the coordinate bundle must not start a worker')

    bundle = experiment_bundle(str(fx['root']), record, 'python3', execute=started)
    assert bundle['record_id'] == fx['id'] and bundle['record'] == record
    assert bundle['original_record']['key'] == fx['id']
    assert bundle['search']['history_status'] == 'not_applicable_coordinate_evaluation'


_UNSET = object()


def _set(record: dict, key: str, value) -> None:
    """``record.provenance.design_result[key] = value``; ``_UNSET`` leaves the member out (``undefined``)."""
    target = record['provenance']['design_result']
    if value is _UNSET:
        target.pop(key, None)
    else:
        target[key] = value


def test_coordinate_exports_reject_missing_or_redirected_source_paths_and_changed_source_bytes(tmp_path):
    """:95."""
    fx = coordinate_fixture(tmp_path / 'root')
    root, record, original = str(fx['root']), fx['record'], copy.deepcopy(fx['record'])
    for path in ('results/v2/reference.json', '../cache.json', _UNSET, None):
        _set(record, 'path', path)
        with pytest.raises(BundleError, match='来源路径或身份无效'):
            experiment_bundle(root, record)
    record.update(copy.deepcopy(original))
    _set(record, 'sha256', _UNSET)
    with pytest.raises(BundleError, match='来源路径或身份无效'):
        experiment_bundle(root, record)
    record.update(copy.deepcopy(original))
    fx['file'].write_text(jsjson.stringify({'changed': True}), encoding='utf-8')
    with pytest.raises(BundleError, match='原始文件校验失败'):
        experiment_bundle(root, record)


def test_coordinate_source_symlinks_cannot_escape_the_experiment_directory(tmp_path):
    """:110."""
    fx = coordinate_fixture(tmp_path / 'root')
    outside = fx['root'] / 'outside-cache.json'
    outside.write_bytes(fx['file'].read_bytes())
    fx['file'].unlink()
    fx['file'].symlink_to(outside)
    with pytest.raises(BundleError, match='来源文件不在实验目录内'):
        experiment_bundle(str(fx['root']), fx['record'])


def test_coordinate_exports_verify_key_checksum_and_request_identity_after_validating_file_bytes(tmp_path):
    """:119."""
    fx = coordinate_fixture(tmp_path / 'root')

    def reseal(value: dict) -> None:
        value['result_sha256'] = jsjson.sha256_hex(value['result'])

    for change in (lambda v: v.update(key='f' * 64),
                   lambda v: v['result']['nominal'].update(field_relative=123),
                   lambda v: v.update(identity=None),
                   lambda v: v['identity'].update(threads=2),
                   lambda v: (v['result']['request'].update(seed=43), reseal(v))):
        invalid = copy.deepcopy(fx['cache'])
        change(invalid)
        fx['persist'](invalid)
        with pytest.raises(BundleError, match='缓存校验失败|记录身份不匹配'):
            experiment_bundle(str(fx['root']), fx['record'])


def test_coordinate_exports_reject_source_results_that_no_longer_match_displayed_coordinates_or_metrics(tmp_path):
    """:133."""
    fx = coordinate_fixture(tmp_path / 'root')
    root, record = str(fx['root']), fx['record']

    def lowered(value: dict) -> None:
        value['result']['evaluated_xyz_mm'] = [[x, y, 0.5] for x, y, _ in value['result']['evaluated_xyz_mm']]
        value['result']['projection_max_mm'] = 0.5

    for change in (lowered, lambda v: v['result']['nominal'].update(field_absolute=0.495, field_relative=0.5)):
        invalid = copy.deepcopy(fx['cache'])
        change(invalid)
        invalid['result_sha256'] = jsjson.sha256_hex(invalid['result'])
        fx['persist'](invalid)
        with pytest.raises(BundleError, match='来源与所选记录不匹配'):
            experiment_bundle(root, record)
    fx['persist'](fx['cache'])
    assert experiment_bundle(root, record)['record_id'] == fx['id']
    for change in (lambda r: r.update(label='another record'),
                   lambda r: r['layout']['regionIndices'].__setitem__(0, 1),
                   lambda r: r['metrics'].update(conditional_global=0.99)):
        invalid = copy.deepcopy(record)
        change(invalid)
        with pytest.raises(BundleError, match='来源与所选记录不匹配'):
            experiment_bundle(root, invalid)


def test_evaluations_under_other_conditions_are_library_records_with_their_conditions(tmp_path):
    """:163, the library half (``assertIndependentNoiseParent`` is reception v2: slice 7)."""
    for index, (extra, condition) in enumerate((
            ({'noise_model': SPATIAL}, {'noise_model': SPATIAL}),
            ({'conductivity_scenario': 'skull_x2'}, {'conductivity_scenario': 'skull_x2'}),
            ({'head_id': 'ixi002'}, {'head_id': 'ixi002'}))):
        fx = coordinate_fixture(tmp_path / f'root-{index}', **extra)
        assert fx['record']['evaluation_condition'] == condition
        assert design_reception_record(str(fx['root']), fx['id']) is None
        assert experiment_bundle(str(fx['root']), fx['record'])['record']['evaluation_condition'] == condition
    fx = coordinate_fixture(tmp_path / 'default')
    assert 'evaluation_condition' not in fx['record']
    assert design_reception_record(str(fx['root']), fx['id']) == fx['record']


# --- check-source-upgrade.mjs -------------------------------------------------------------------------------------

def test_missing_history_is_explicit_and_never_fabricates_zero_score_initial_state():
    """:121."""
    s = describe_search({'dataset_id': 'offline_radius', 'provenance': {}, 'request': None}, {})
    assert s['history_status'] == 'not_available_in_loaded_record'
    assert s['initial'] is None
    assert s['curve'] == []


def test_synthetic_completed_native_record_resolves_evaluated_coordinates_not_unprojected_inputs(tmp_path):
    """:143 (``designReceptionRecord``): the record hashes the exact saved bytes, whitespace included."""
    root = tmp_path / 'eeg-reception-record'
    id = 'a' * 64
    result = {
        'schema': 'design-evaluation/1', 'status': 'completed', 'forward_mode': 'direct_fem',
        'request': design_request('synthetic-test'),
        'nominal': {'field_relative': 1, 'field_absolute': 0.9, 'reference_field_absolute': 0.9, 'sensitivity_tail': 1,
                    'localization_relative': 1, 'median_mm': 10, 'p90_mm': 20, 'reference_median_mm': 10,
                    'reference_p90_mm': 20},
        'projection_max_mm': 1, 'evaluated_xyz_mm': [[x, y, 1] for x, y, _ in GRID],
        'provenance': {'candidate_count': 64}, 'trials': [],
    }
    jobs = root / 'results/v2/design_evaluation_jobs' / id
    jobs.mkdir(parents=True)
    report = jsjson.stringify({'baseline': {'reference_xyz_mm': GRID}})
    (root / 'results/v2/reference.json').write_text(report, encoding='utf-8')
    (root / 'results/v2/current_strict_area_budget_study.json').write_text(
        jsjson.stringify({'report': 'results/v2/reference.json', 'sha256': sha(report)}), encoding='utf-8')
    cache = jsjson.parse(jsjson.stringify({'key': id, 'result': result, 'result_sha256': jsjson.sha256_hex(result)}))
    saved = (json.dumps(cache, indent=2, ensure_ascii=False) + '\n').encode('utf-8')  # JSON.stringify(v, null, 2)
    (jobs / 'cache.json').write_bytes(saved)
    r = design_reception_record(str(root), id)
    assert r['layout']['xyzMm'] == result['evaluated_xyz_mm']
    assert r['layout']['xyzMm'] != GRID
    assert len(r['layout']['xyzMm']) == 64
    assert r['provenance']['forward_mode'] == 'direct_fem'
    assert r['provenance']['design_result'] == {'path': f'results/v2/design_evaluation_jobs/{id}/cache.json',
                                                'sha256': sha(saved)}
    invalid = copy.deepcopy(cache['result'])
    invalid['request']['design']['region_indices'] = [99] * 64
    (jobs / 'cache.json').write_text(jsjson.stringify({'key': id, 'result': invalid,
                                                       'result_sha256': jsjson.sha256_hex(invalid)}), encoding='utf-8')
    with pytest.raises(DesignResultError, match='区域编号错误'):
        design_reception_record(str(root), id)


# --- Python behaviour -------------------------------------------------------------------------------------------

def test_messages_are_nodes_verbatim():
    source = NODE_SOURCE.read_text(encoding='utf-8')
    texts = [value for name, value in vars(bundle_module).items() if isinstance(value, str) and not value.isascii()]
    texts += [*bundle_module.SNAPSHOT_LABELS, *bundle_module.ENTRYPOINTS.values(), bundle_module.OTHER_ENTRYPOINT,
              bundle_module.HISTORY_SCRIPT, bundle_module.RADIUS_POINTER, bundle_module.BUNDLE_SCHEMA]
    assert len(texts) > 20
    for text in texts:
        assert text in source, text
    for name, value in bundle_module.HISTORY_ENV.items():
        assert f"{name}: '{value}'" in source
    assert 'timeout: 10000' in source and 'maxBuffer: 1024 * 1024' in source


@pytest.mark.parametrize('value, expected', [
    (None, 0.0), (True, 1.0), (False, 0.0), (2.5, 2.5), ('', 0.0), (' 0x1F ', 31.0), ('0b11', 3.0), ('0o7', 7.0),
    ('-0x10', NAN), ('1_000', NAN), ('.5', 0.5), ('5.', 5.0), ('\u00a01\ufeff', 1.0), ('1n', NAN),
    ('-Infinity', float('-inf')), ('infinity', NAN), ('\u0663', NAN), ('1e', NAN), ('.', NAN), ([], 0.0), ([2], 2.0),
    (['3'], 3.0), ([1, 2], NAN), ([None], 0.0), ([[4]], 4.0), ({}, NAN), ({'valueOf': 2}, NAN),
])
def test_to_number_is_javascripts(value, expected):
    number = to_number(value)
    assert (number != number and expected != expected) or number == expected


def test_to_number_of_an_object_with_its_own_to_string_throws():
    with pytest.raises(JSTypeError, match='^Cannot convert object to primitive value$'):
        to_number({'toString': 1})


def test_deep_strict_equal_is_nodes():
    assert deep_strict_equal({'a': [1, 2.0], 'b': None}, {'b': None, 'a': [1.0, 2]})
    assert not deep_strict_equal({'a': 1}, {'a': 1, 'b': None})
    assert not deep_strict_equal(0.0, -0.0)
    assert deep_strict_equal(float('nan'), float('nan'))
    assert not deep_strict_equal([1], {'0': 1})
    assert not deep_strict_equal(1, True) and not deep_strict_equal('1', 1) and not deep_strict_equal(None, False)
    assert deep_strict_equal([[1, [2]]], [[1, [2]]]) and not deep_strict_equal([[1, [2]]], [[1, [3]]])


@pytest.fixture(scope='module')
def fakes(tmp_path_factory):
    return fake_interpreters(tmp_path_factory.mktemp('bundle-fakes'))


def test_exec_file_terminates_at_the_timeout(fakes):
    started = time.monotonic()
    with pytest.raises(ExecFileError, match='timed out'):
        exec_file(fakes['sleep'], [], timeout=0.5)
    assert time.monotonic() - started < 5


def test_exec_file_keeps_stdin_open_and_unwritten(fakes):
    """Node keeps the child's stdin open, unwritten, while the child runs: a child that reads it waits until the
    timeout."""
    with pytest.raises(ExecFileError, match='timed out'):
        exec_file(fakes['stdin'], [], timeout=0.5)


def test_exec_file_kills_a_child_that_ignores_sigterm(fakes, monkeypatch):
    monkeypatch.setattr(bundle_module, 'KILL_GRACE_SECONDS', 0.2)
    started = time.monotonic()
    with pytest.raises(ExecFileError, match='timed out'):
        exec_file(fakes['stubborn'], [], timeout=0.5)
    assert time.monotonic() - started < 5


def test_exec_file_reports_signals_exits_and_spawn_failures(fakes):
    with pytest.raises(ExecFileError, match=f'signal {signal.SIGTERM.value}'):
        exec_file(fakes['signal'], [])
    with pytest.raises(ExecFileError, match='exit code 3'):
        exec_file(fakes['exit'], [])
    with pytest.raises(FileNotFoundError):
        exec_file(fakes['missing'], [])
    with pytest.raises(PermissionError):
        exec_file(fakes['not-executable'], [])
    with pytest.raises(ValueError):
        exec_file(fakes['echo'], ['a\u0000b'])
    with pytest.raises(TypeError):
        exec_file(5, [])


def test_exec_file_converts_arguments_as_node_does(fakes, monkeypatch):
    monkeypatch.setenv(MARKER, 'set')
    output = jsjson.parse(exec_file(fakes['echo'], [None, 5, -0.0, 1e21, ['a', ['b']], {}, ['c\u0000d'], '\ud800x',
                                                    {'toString': 'x'}, ['a', {'toString': 1}], {'valueOf': 1}],
                                    env={**os.environ, 'OMP_NUM_THREADS': '4'}))
    seen = output['xyz_mm'][0]
    # A conversion that throws (an own ``toString`` member) passes an empty argument, as node::Utf8Value does.
    assert seen['argv'] == ['null', '5', '0', '1e+21', 'a,b', '[object Object]', 'c', '\ufffdx', '', '',
                            '[object Object]']
    assert (seen['env']['OMP_NUM_THREADS'], seen['env'][MARKER]) == ('4', 'set')
    assert seen['cwd'] == os.getcwd()
    assert output['xyz_mm'][1] == {'stdio': ['socket', 'socket', 'socket']}


# Children whose exit status decides at the timeout, as in Node's execFile (its timeout destroys both outputs and
# signals the child; the exit handler then resolves on 0): one that exits 0 at once while a process it started
# holds its stdout or only its stderr, the same with exit 3, one that handles SIGTERM with exit 0, the same writing
# to stdout or stderr in its handler (SIGPIPE), or waiting for a writer to stderr that blocks once nobody reads (its
# EPIPE ends it), and one killed; one that exits at once while a process it started reads its stdin (Node closes it
# at the exit); and one blocked writing past the buffer, which handles SIGTERM once the outputs are closed. /bin/sh
# runs each script (a freshly written executable can take long to start on macOS).
SLOW_WRITER = (f"{shlex.quote(sys.executable)} -I -c "
               "'import os, time\nwhile 1: os.write(2, bytes(1000)); time.sleep(0.002)'")
TIMEOUT_STUBS = {
    'held': ("printf '{\"held\":1}'\n( sleep 4 ) &\n", '{"held":1}'),
    'held-stderr': ("printf '{\"held\":2}'\n( exec >/dev/null; sleep 4 ) &\n", '{"held":2}'),
    'held-exit': ("printf '{\"held\":3}'\n( sleep 4 ) &\nexit 3\n", None),
    'trapped': ("trap 'exit 0' TERM\nprintf '{\"held\":4}'\nwhile :; do sleep 0.05; done\n", '{"held":4}'),
    'trapped-write': ("trap 'printf x; exit 0' TERM\nprintf '{\"held\":6}'\nwhile :; do sleep 0.05; done\n", None),
    'trapped-write-stderr': ("trap 'printf x >&2; exit 0' TERM\nprintf '{\"held\":7}'\n"
                             "while :; do sleep 0.05; done\n", None),
    'trapped-blocked': (f"trap 'exit 0' TERM\nprintf '{{\"held\":8}}'\nsleep 0.5\n{SLOW_WRITER}\n", '{"held":8}'),
    'killed': ("printf '{\"held\":5}'\nsleep 4\n", None),
    'held-stdin': ("exec 3<&0\nprintf '{\"held\":9'\n( cat <&3 >/dev/null; printf '}' ) &\nexit 0\n", '{"held":9}'),
    'over-trapped': ("trap 'exit 0' TERM\nhead -c 4000000 /dev/zero | tr '\\0' a\nwhile :; do sleep 0.05; done\n",
                     None),
}
EXEC_DRIVER = r"""
import { execFile } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { promisify } from 'node:util';
const [specPath, outPath] = process.argv.slice(2);
const run = promisify(execFile);
const out = {};
for (const [name, script] of Object.entries(JSON.parse(readFileSync(specPath, 'utf8')))) {
  try { out[name] = (await run('/bin/sh', [script], { timeout: 1000, maxBuffer: 1024 * 1024 })).stdout; }
  catch { out[name] = null; }
}
writeFileSync(outPath, JSON.stringify(out));
process.exit(0);
"""


@pytest.fixture(scope='module')
def timeout_stubs(tmp_path_factory):
    directory = tmp_path_factory.mktemp('timeout-stubs')
    scripts = {}
    for name, (body, _) in TIMEOUT_STUBS.items():
        (directory / name).write_text(body, encoding='utf-8')
        scripts[name] = str(directory / name)
    return scripts


def _at_timeout(script: str) -> object:
    try:
        return exec_file('/bin/sh', [script], timeout=1.0)
    except ExecFileError:
        return None


@pytest.mark.parametrize('name', list(TIMEOUT_STUBS))
def test_exec_file_lets_the_exit_status_decide_at_the_timeout(timeout_stubs, name, monkeypatch):
    """A child that exits 0 by the timeout (or on its SIGTERM) gives the output read until then; none of these
    children waits for SIGKILL."""
    monkeypatch.setattr(bundle_module, 'KILL_GRACE_SECONDS', 10.0)
    started = time.monotonic()
    assert _at_timeout(timeout_stubs[name]) == TIMEOUT_STUBS[name][1]
    assert time.monotonic() - started < 2.9


@needs_node
def test_exec_file_at_the_timeout_is_nodes(timeout_stubs, tmp_path):
    driver, spec, out = tmp_path / 'exec.mjs', tmp_path / 'spec.json', tmp_path / 'out.json'
    driver.write_text(EXEC_DRIVER, encoding='utf-8')
    spec.write_text(jsjson.stringify(timeout_stubs), encoding='utf-8')
    subprocess.run(['node', str(driver), str(spec), str(out)], check=True, cwd=ROOT, env=NODE_ENV)
    node = jsjson.parse(out.read_text(encoding='utf-8'))
    assert {name: _at_timeout(script) for name, script in timeout_stubs.items()} == node
    assert node == {name: expected for name, (_, expected) in TIMEOUT_STUBS.items()}


@pytest.mark.parametrize('mode, ok', [('exact', True), ('over', False), ('replaced-exact', True),
                                      ('replaced-over', False), ('stderr-exact', True), ('stderr-over', False)])
def test_exec_file_counts_decoded_output_against_the_buffer(fakes, mode, ok):
    if ok:
        jsjson.parse(exec_file(fakes[mode], []))
    else:
        with pytest.raises(ExecFileError, match='maxBuffer'):
            exec_file(fakes[mode], [])


# --- Parity with Node -------------------------------------------------------------------------------------------

EXTRA_IDS = ['a' * 64, 'A' * 64]


@pytest.fixture(scope='session')
def parity(tmp_path_factory):
    base = tmp_path_factory.mktemp('bundle-parity')
    python = runtime_config(str(base)).python
    pythons = fake_interpreters(base / 'fakes')
    parity_pythons = {mode: pythons[mode] for mode in (*PARITY_MODES, 'missing', 'not-executable')}
    keys = bundle_root(base / 'root', python)
    (base / 'linked').symlink_to(base / 'root')
    cases_root(base / 'cases')
    library = Library(str(base / 'root'), runtime_config(str(base / 'root')))
    ids = [row['id'] for row in library.list()['records']]
    ids += [id for id in (*keys['radius'].values(), *keys['design'].values(), *EXTRA_IDS) if id not in ids]
    cases = [[id, id, None] for id in ids]
    for name in HISTORY_REQUESTS:
        cases += [[f'{name}:{mode}', keys['radius'][name], pythons[mode]] for mode in ('echo', 'coords', 'exit')]
    cases += [[f'history:{mode}', keys['radius']['history'], python] for mode, python in parity_pythons.items()]
    spec = {
        'roots': [{'id': 'root', 'root': str(base / 'root'), 'cases': cases},
                  {'id': 'linked', 'root': str(base / 'linked'), 'cases': [[id, id, None] for id in ids]}],
        'records': [*record_cases(base / 'cases', parity_pythons),
                    *coordinate_cases(base / 'root', library.get(keys['design']['default']))],
        'describe': [[jsjson.stringify(record), jsjson.stringify(raw)] for record, raw in DESCRIBE],
    }
    before = snapshot(base)
    node = run_node(spec, tmp_path_factory.mktemp('bundle-node'))
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(MARKER, 'inherited')
        patch.chdir(ROOT)
        python_out = python_side(spec)
    assert snapshot(base) == before
    return spec, node, python_out, keys


def _differences(node: dict, python: dict) -> list:
    assert set(node) == set(python)
    return [(name, node_failure(result), python[name]) for name, result in node.items()
            if python[name] != node_failure(result)]


def _negative_zero(root: Path, name: str, old: str, new: str, change=None) -> str:
    """A saved evaluation whose file spells a zero as ``-0`` (``old`` replaced by ``new`` in its text); the
    checksum, over ``JSON.stringify`` of the parsed result, stays the same."""
    key = design_record(root, design_request(name), change=change)
    path = root / f'results/v2/design_evaluation_jobs/{key}/cache.json'
    text = path.read_text(encoding='utf-8')
    assert text.count(old) == 1
    path.write_text(text.replace(old, new), encoding='utf-8')
    return key


@pytest.fixture(scope='module')
def negative_zero(tmp_path_factory):
    """Saved evaluations with ``-0`` where Node keeps it: a region label (the record and the source check share
    the stored array) and a nominal score that ``Math.min`` makes the conditional global score."""
    root = tmp_path_factory.mktemp('negative-zero') / 'root'
    root.mkdir()
    code_tree(root)
    forward_inputs(root)
    offline_datasets(root)

    def zero_scores(cache: dict) -> None:
        cache['result']['nominal'].update(field_relative=0.0, field_absolute=0.0, sensitivity_tail=0.0)
        cache['result_sha256'] = jsjson.sha256_hex(cache['result'])

    keys = {'region': _negative_zero(root, 'negative zero region', '"region_indices":[0,', '"region_indices":[-0,'),
            'score': _negative_zero(root, 'negative zero score', '"sensitivity_tail":0,', '"sensitivity_tail":-0,',
                                    zero_scores)}
    spec = {'roots': [{'id': 'zero', 'root': str(root), 'cases': [[name, key, None] for name, key in keys.items()]}]}
    before = snapshot(root)
    node = run_node(spec, tmp_path_factory.mktemp('negative-zero-node'))
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(MARKER, 'inherited')
        patch.chdir(ROOT)
        python_out = python_side(spec)
    assert snapshot(root) == before
    return node['library']['zero']['bundles'], python_out['library']['zero']['bundles']


@needs_node
def test_negative_zero_sources_bundle_as_in_node(negative_zero):
    """``-0`` in a stored region label or a nominal score passes the source check as in Node (deepStrictEqual
    tells ``-0`` from ``0``)."""
    node, python = negative_zero
    assert all(result['ok'] and result['value'] is not None for result in node.values()), node
    assert _differences(node, python) == []
    record = _bundle(node['score'])['record']
    assert record['metrics']['conditional_global'] == 0 and record['metrics']['field_relative'] == 0


@needs_node
@pytest.mark.parametrize('root', ['root', 'linked'])
def test_library_bundle_parity(root, parity):
    _, node, python, _ = parity
    assert (python['library'][root]['root'], python['library'][root]['python']) == (
        node['library'][root]['root'], node['library'][root]['python'])
    assert _differences(node['library'][root]['bundles'], python['library'][root]['bundles']) == []


@needs_node
def test_record_bundle_parity(parity):
    _, node, python, _ = parity
    assert _differences(node['records'], python['records']) == []


@needs_node
def test_describe_search_parity(parity):
    _, node, python, _ = parity
    assert python['describe'] == [node_failure(result) for result in node['describe']]


def _bundle(result: dict) -> dict:
    assert result['ok'], result
    return jsjson.parse(result['value']['text'])


@needs_node
def test_parity_covers_each_source_and_export_outcome(parity):
    """The cases reach what the comparison is for: every dataset packed, the linked root refused, the export run
    with Node's arguments and environment, each failure of the export only setting the note, and errors of each
    kind."""
    spec, node, _, keys = parity
    bundles = node['library']['root']['bundles']
    packed = [_bundle(result) for result in bundles.values() if result['ok'] and result['value']]
    assert {b['record']['dataset_id'] for b in packed} == {'offline_radius', 'strict_area', 'historical_area', 'cache',
                                                           'design_evaluation'}
    statuses = {b['search']['history_status'] for b in packed}
    assert statuses == {'recorded_accepted_moves', 'not_available_in_loaded_record',
                        'not_applicable_coordinate_evaluation'}
    assert any(b['search']['curve'] and b['snapshots'][0] and b['snapshots'][0]['xyzMm'] for b in packed
               if b['record']['dataset_id'] == 'offline_radius')
    linked = node['library']['linked']['bundles'].values()
    assert all((result['ok'] and result['value'] is None) or result['message'] == '来源文件不在实验目录内'
               for result in linked)
    assert sum(not result['ok'] for result in linked) > 20
    echo = _bundle(bundles['history:echo'])
    seen = echo['snapshots'][0]['xyzMm']
    root = str(spec['roots'][0]['root'])
    assert seen['argv'] == [f'{root}/scripts/export_history_coordinates.py', '--repository-root', root, '--bank-sha256',
                            sha('bank'), '--indices', jsjson.stringify([b['candidate_bank_indices'] for b in (
                                echo['search']['initial'], echo['search']['final'])])]
    assert seen['env'] == {'PYTHONDONTWRITEBYTECODE': '1', 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1',
                           MARKER: 'inherited'}
    assert seen['cwd'] == str(ROOT) and echo['snapshots'][1]['xyzMm'] == {'stdio': ['socket', 'socket', 'socket']}
    assert echo['coordinate_note'] is None
    notes = {name.split(':')[1]: _bundle(result)['coordinate_note'] for name, result in bundles.items()
             if name.startswith('history:')}
    succeeded = {mode for mode, note in notes.items() if note is None}
    assert succeeded == {'echo', 'coords', 'chunked', 'exact', 'replaced', 'replaced-exact', 'stderr-exact',
                         'literals', 'short', 'string', 'object', 'number'}
    assert _bundle(bundles['history-coordinates:exit'])['coordinate_note'] is None  # coordinates saved: no export
    records = node['records']
    arguments = {name: _bundle(records[name])['snapshots'][0]['xyzMm']['argv'][4] for name in records
                 if name.startswith('bank-') and name != 'bank-nul'}
    assert arguments == {'bank-undefined': 'undefined', 'bank-null': 'null', 'bank-number': '5',
                         'bank-array': f"{sha('bank')},x", 'bank-nested': f"{sha('bank')},",
                         'bank-object': '[object Object]', 'bank-to-string': '', 'bank-array-nul': 'a',
                         'bank-surrogate': '\ufffd'}
    failures = {result['code'] or result['message'] for result in [*records.values(), *node['describe']]
                if not result['ok']}
    assert {'ENOENT', 'EISDIR', 'ERR_INVALID_ARG_TYPE', '来源文件不在实验目录内', '原始记录未提供来源文件',
            '原始文件校验失败', '原始缓存校验失败', '历史优化报告与导出身份不符', '坐标评价来源路径或身份无效',
            '坐标评价来源与所选记录不匹配', 'trace.entries is not a function or its return value is not iterable',
            'raw.conditions?.find is not a function', 'entry?.finalists?.find is not a function',
            's.xyz_m?.map is not a function', 'p.map is not a function', 'Cannot convert object to primitive value',
            "Cannot read properties of null (reading 'condition')"} <= failures
    assert any(result['name'] == 'SyntaxError' for result in records.values() if not result['ok'])
    assert _bundle(records['coordinate-metric-order'])['record_id'] == keys['design']['default']


# --- The real installation (EEG_KEY_PARITY_ROOT) ----------------------------------------------------------------

REAL_ROOT = os.environ.get('EEG_KEY_PARITY_ROOT')
real_root = pytest.mark.skipif(not REAL_ROOT, reason='set EEG_KEY_PARITY_ROOT to a checkout with results/v2')


def _read_json(path: Path):
    return jsjson.parse(path.read_bytes().decode('utf-8'))


@pytest.mark.data_bundle
@real_root
def test_real_area_bundle_preserves_original_bytes_identity_all_coordinates_and_stored_accepted_trace():
    """check-source-upgrade.mjs:96."""
    root = Path(REAL_ROOT)
    p = _read_json(root / 'results/v2/current_strict_area_budget_study.json')
    data = (root / p['report']).read_bytes()
    raw = jsjson.parse(data.decode('utf-8'))
    r = next(r for r in area_records(raw, {'file': p['report'], 'sha256': p['sha256']})
             if r['status'] == 'completed' and r['region_count'] == 2 and r['area_cap_cm2'] == 60)
    bundle = experiment_bundle(REAL_ROOT, r)
    assert bundle['source']['sha256'] == sha(data)
    assert bundle['record']['layout']['xyzMm'] == r['layout']['xyzMm']
    assert bundle['search']['initial'] and bundle['search']['final'] and bundle['search']['curve']
    assert bundle['original_record'] == raw
    final = bundle['search']['final']
    assert bundle['search']['curve'][-1]['value'] == min(final['field20'], final['sensitivity_tail'])


@pytest.mark.data_bundle
@real_root
def test_historical_field_objective_keeps_its_saved_trajectory_and_is_not_replaced_with_the_tail_minimum():
    """check-source-upgrade.mjs:130."""
    file = 'webapp/public/data/single_head_optimization.json'
    record = radius_records(_read_json(Path(REAL_ROOT) / file), {'file': file})[0]
    b = experiment_bundle(REAL_ROOT, record)
    search = b['search']
    assert len(search['trace']) > 0
    assert search['curve'][0]['value'] == search['initial']['objective_score']
    assert search['curve'][-1]['value'] == search['final']['objective_score']
    assert search['curve'][0]['value'] != min(search['initial']['field20'], search['initial']['sensitivity_tail'])


@pytest.mark.data_bundle
@real_root
@needs_node
def test_real_root_bundle_parity(tmp_path):
    """The bundle of every record of the installation, as the library route builds it in Node (the cache records
    export their frozen-bank coordinates with the installation's compute interpreter)."""
    watched = [Path(REAL_ROOT) / name for name in ('results/v2', 'webapp/public/data', 'scripts', 'src')]
    before = [snapshot(path) for path in watched]
    library = Library(REAL_ROOT, runtime_config(REAL_ROOT))
    ids = [row['id'] for row in library.list()['records']]
    spec = {'roots': [{'id': 'real', 'root': REAL_ROOT, 'cases': [[id, id, None] for id in ids]}]}
    node = run_node(spec, tmp_path)['library']['real']
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(ROOT)
        python = python_side(spec)['library']['real']
    assert (python['root'], python['python']) == (node['root'], node['python'])
    assert _differences(node['bundles'], python['bundles']) == []
    datasets: dict[str, int] = {}
    for result in node['bundles'].values():
        if result['ok']:
            dataset = _bundle(result)['record']['dataset_id']
            datasets[dataset] = datasets.get(dataset, 0) + 1
    assert (datasets['offline_radius'], datasets['strict_area'], datasets['historical_area']) == (342, 30, 30)
    # The cache records whose snapshots hold bank indices only (whatever their number on this installation): the
    # real export script ran in both hosts and gave every coordinate.
    attempted = []
    for id in ids:
        record = library.get(id)
        if record is not None and record['dataset_id'] == 'cache':
            calls = []

            def stub(*args, calls=calls, **kwargs):
                calls.append(args)
                raise RuntimeError('not run')

            experiment_bundle(library.root, record, 'python', execute=stub)
            if calls:
                attempted.append(id)
    exported = [id for id in attempted if node['bundles'][id]['ok'] and _bundle(node['bundles'][id])[
        'coordinate_note'] is None and all(isinstance(s and s.get('xyzMm'), list)
                                           for s in _bundle(node['bundles'][id])['snapshots'])]
    assert exported == attempted
    assert [before == after for before, after in zip(before, [snapshot(path) for path in watched])] == [True] * 4
