"""Python request keys equal Node's on the same root (design 0001, phase 2 exit criterion 1; plan B1-B12).

For every synthetic root variant, interpreter configuration and request, ``eeglayoutlab.jobs`` must give the
configuration, identity text, admission text and key that Node's ``LocalComputeQueue`` and
``DesignEvaluationService`` give (tests/service/parity/identity.mjs), or fail the same way: by Node's code where
the error has one (system errors carry absolute paths in their messages), by name for a ``SyntaxError``, the
others by Node's message.

With ``EEG_KEY_PARITY_ROOT=<checkout>`` the same comparison also runs on that real installation (marked
``data_bundle``), and every stored design and editor cache and every batch ``request.json`` must re-derive its key.
Nothing is written under that root.
"""
from __future__ import annotations

import os
from pathlib import Path
import re

import pytest

from eeglayoutlab.jobs import identity as py_identity
from eeglayoutlab.jobs import runtime as py_runtime
from eeglayoutlab.jobs.identity import request_key
from eeglayoutlab.schemas import jsjson

from .key_parity_support import (
    BAD_UTF8_NAME, BANK, CONDA_META, LINE_TERMINATOR_DIST_INFO, NATIVE, NATIVE_DIST_INFO, REQUESTS, TABLE_DIR, Case,
    PythonCases, all_requests, build_roots, canonical_requests, digest, needs_node, node_outcome, run_node, spec_case,
    synthetic_cases,
)

CASES = synthetic_cases()


@pytest.fixture(scope='session')
def synthetic(tmp_path_factory):
    base = tmp_path_factory.mktemp('key-parity')
    roots = build_roots(base / 'roots')
    requests = all_requests()
    specs = {case.id: spec_case(case, *roots[case.root], requests) for case in CASES}
    node = run_node(list(specs.values()), base)
    return roots, specs, node


@needs_node
@pytest.mark.parametrize('case', CASES, ids=lambda case: case.id)
def test_key_parity(case, synthetic):
    _, specs, node = synthetic
    assert PythonCases().run(specs[case.id]) == node_outcome(node['by_id'][case.id])


@needs_node
def test_node_constants_match(synthetic):
    constants = synthetic[2]['constants']
    assert constants == {
        'NATIVE_RUNTIME_RELATIVE': py_runtime.NATIVE_RUNTIME_RELATIVE,
        'TABLE_RUNTIME_RELATIVE': py_runtime.TABLE_RUNTIME_RELATIVE,
        'WORKFLOW_BASE': list(py_identity.WORKFLOW_BASE),
        'DESIGN_WORKFLOW': list(py_identity.DESIGN_WORKFLOW),
        'RECEPTION_WORKFLOW': list(py_identity.RECEPTION_WORKFLOW),
        'RECEPTION_V2_WORKFLOW': list(py_identity.RECEPTION_V2_WORKFLOW),
        'EDITOR_WORKFLOW': list(py_identity.EDITOR_WORKFLOW),
        'DATA_PRIOR_FILES': list(py_identity.DATA_PRIOR_FILES),
    }


def _digests(result):
    return list(jsjson.parse(result['identity'])['digests'])


@needs_node
def test_variants_reach_their_branches(synthetic):
    # Parity alone would also pass if a fixture missed its branch; these pin what each variant exercises.
    roots, _, node = synthetic
    result = node['by_id']
    linux = node['platform'] != 'darwin'
    ok = lambda case_id: result[case_id]['ok'] and result[case_id]  # noqa: E731

    # Managed-runtime rows: the interpreter, conda records in code-unit order, matching dist-info, two sources.
    native = ok('simnibs/default/empty')
    site = f'{NATIVE}/lib/python3.11/site-packages'
    meta = sorted((n for n in CONDA_META if n.endswith('.json')), key=lambda n: n.encode('utf-16-be'))
    assert meta[-2:] == ['\U0001F600.json', '\uff5a.json']
    matching = sorted(n for n in NATIVE_DIST_INFO
                      if re.fullmatch('(simnibs|cortech|numpy|scipy)-[^\n\r\u2028\u2029]*\\.dist-info', n))
    assert not set(LINE_TERMINATOR_DIST_INFO) & set(matching)
    assert [p for p in _digests(native) if p.startswith('.runtime/')] == [
        f'{NATIVE}/bin/python', *(f'{NATIVE}/conda-meta/{n}' for n in meta), *(f'{site}/{n}/METADATA' for n in matching),
        f'{site}/simnibs/simulation/fem.py', f'{site}/simnibs/mesh_tools/mesh_io.py']
    simnibs_root = roots['simnibs'][0]
    assert native['config'] == {'repositoryRoot': simnibs_root, 'python': f'{simnibs_root}/{NATIVE}/bin/python',
                                'nativePython': f'{simnibs_root}/{NATIVE}/bin/python'}
    # A radius override never reaches the native workflows while a managed runtime exists.
    assert ok('simnibs/explicit/empty')['config']['python'] == '/explicit/python'
    assert ok('simnibs/explicit/empty')['identity'] == native['identity']
    # Another spelling of the same interpreter leaves the rows out; the exact string keeps them.
    for config in ('direct-dot', 'direct-dotdot', 'direct-link'):
        spelled = ok(f'simnibs/{config}/empty')
        assert not any(p.startswith('.runtime/') for p in _digests(spelled))
        assert jsjson.parse(spelled['identity'])['python'] != native['config']['nativePython']
    assert ok('simnibs/direct-exact/empty')['identity'] == native['identity']
    # Table runtime rows, SimNIBS precedence, and the table branch reached by its exact string.
    assert any(p.startswith('.runtime/compute-linux-64/conda-meta/') for p in _digests(ok('linux64/default/empty')))
    assert not any('compute-linux-64' in p for p in _digests(ok('both/default/empty')))
    assert any('compute-linux-64' in p for p in _digests(ok('both/direct-table/empty')))
    assert ok('dangling/default/empty')['config']['nativePython'] == 'python3'
    # Interpreter precedence with JavaScript's || (an empty string falls through).
    assert ok('base/default/empty')['config']['nativePython'] == 'python3'
    assert ok('base/env/empty')['config']['nativePython'] == '/env/python'
    assert ok('base/env-empty/empty')['config']['nativePython'] == 'python3'
    assert ok('base/explicit-empty/empty')['config']['nativePython'] == '/env/python'
    # The symlinked root keeps its spelling in identity.python; containment uses the real path.
    link, real = roots['symlinked']
    assert link != real and jsjson.parse(ok('symlinked/default/empty')['identity'])['python'] == f'{link}/{NATIVE}/bin/python'
    assert not any(p.startswith('.runtime/') for p in _digests(ok('symlinked/direct-realpath/empty')))
    # Raw pointer strings stay raw; built paths are normalized.
    odd = _digests(ok('odd/default/empty'))
    for raw in ('./results//v2/bank/runs/r/batches/b/bank.npz', f'{roots["odd"][1]}/data/candidates.npz',
                'data/x/../sources.npz', 'data/head.msh/', 'data//scalp/./mapping.npy',
                'results/v2/bank/runs/r/run_manifest.json', 'data/scalp/external_scalp_vertices_m.npy'):
        assert raw in odd
    assert BANK not in odd and f'{TABLE_DIR}/index.npz' in odd
    # Optional rows only for truthy options, in Node's order.
    assert _digests(ok('base/default/robustness+data_prior'))[-4:] == [
        'src/compact_eeg/workflows/design_robustness.py', *py_identity.DATA_PRIOR_FILES]
    assert 'src/compact_eeg/workflows/design_robustness.py' in _digests(ok('base/default/robustness-object'))
    assert _digests(ok('base/default/data_prior-zero')) == _digests(ok('base/default/evaluate'))
    assert _digests(ok('full/default/head-array')) == _digests(ok('full/default/head'))
    assert _digests(ok('full/default/head-deep-array')) == _digests(ok('full/default/head'))  # 1000 levels deep
    # Failures: one broken thing each, then two whose order Node fixes (the first error in Node's order wins).
    mismatch = {'message': '外部表面筛选文件身份不匹配'}
    for case_id, error in {
        'broken-no_pointer/default/empty': {'code': 'ENOENT'}, 'broken-no_source/default/empty': {'code': 'ENOENT'},
        'broken-report_absolute/default/empty': {'code': 'ENOENT'},
        'broken-escape/default/empty': {'message': '输入文件超出本项目'},
        'broken-escape_prefix/default/empty': {'message': '输入文件超出本项目'},
        'broken-bank_sha/default/empty': {'message': '前向库身份不匹配'},
        'broken-candidate_sha/default/empty': {'message': '候选坐标身份不匹配'},
        'broken-admission_sha/default/empty': mismatch, 'broken-admission_geometry/default/empty': mismatch,
        'broken-table_sha/default/empty': {'message': '预计算头皮节点表身份不匹配'},
        'broken-scenario_sha/default/scenario': {'message': '电导率情景头皮节点表身份不匹配'},
        'broken-head_sha/default/head': {'message': '头模头皮节点表身份不匹配'},
        # Only a missing optional pointer is tolerated.
        'broken-table_dir/default/empty': {'code': 'EISDIR'}, 'broken-scenario_dir/default/scenario': {'code': 'EISDIR'},
        'broken-head_dir/default/head': {'code': 'EISDIR'}, 'broken-table_corrupt/default/empty': {'name': 'SyntaxError'},
        'broken-scenario_corrupt/default/scenario': {'name': 'SyntaxError'},
        'broken-head_corrupt/default/head': {'name': 'SyntaxError'},
        'broken-admission_null/default/empty': {'message': "Cannot read properties of null (reading 'path')"},
        'broken-table_array/default/empty': {'code': 'ERR_INVALID_ARG_TYPE'},
        'broken-table_string/default/empty': {'code': 'ERR_INVALID_ARG_TYPE'},
        'broken-table_object/default/empty': {'code': 'ERR_INVALID_ARG_TYPE'},
        'broken-mesh_null/default/empty': {'code': 'ERR_INVALID_ARG_TYPE'},
        'broken-no_mesh_path/default/empty': {'code': 'ERR_INVALID_ARG_TYPE'},
        'broken-no_source_inputs/default/empty': {'code': 'ERR_INVALID_ARG_TYPE'},
        'broken-mesh_nul/default/empty': {'code': 'ERR_INVALID_ARG_VALUE'},
        'broken-no_init/default/empty': {'code': 'ENOENT'}, 'broken-dir_init/default/empty': {'code': 'EISDIR'},
        'broken-admission_bom/default/empty': {'name': 'SyntaxError'},
        'broken-scenario_false/default/scenario': {'code': 'ERR_INVALID_ARG_TYPE'},
        'broken-scenario_null/default/scenario': {'message': "Cannot read properties of null (reading 'manifest_path')"},
        'broken-head_zero/default/head': {'code': 'ERR_INVALID_ARG_TYPE'},
        'broken-head_null/default/head': {'message': "Cannot read properties of null (reading 'manifest_path')"},
        'broken-no_init+no_mesh_path/default/empty': {'code': 'ERR_INVALID_ARG_TYPE'},
        'broken-mesh_nul+no_init/default/empty': {'code': 'ERR_INVALID_ARG_VALUE'},
        'broken-mesh_nul+no_source_inputs/default/empty': {'code': 'ERR_INVALID_ARG_TYPE'},
        'broken-dir_init+no_source/default/empty': {'code': 'ENOENT'},
        'broken-bank_sha+candidate_sha/default/empty': {'message': '前向库身份不匹配'},
        'broken-candidate_sha+admission_sha/default/empty': {'message': '候选坐标身份不匹配'},
        'broken-admission_sha+table_sha/default/empty': mismatch,
        'broken-table_sha+scenario_sha/default/scenario': {'message': '预计算头皮节点表身份不匹配'},
        'broken-scenario_sha+head_sha/default/scenario+head': {'message': '电导率情景头皮节点表身份不匹配'},
    }.items():
        outcome = node_outcome(result[case_id])
        assert not outcome['ok'] and {k: outcome.get(k) for k in error} == error, case_id
    # An input that cannot be opened fails before an earlier directory that opens and fails when read, in Node's
    # order with one thread-pool worker (not checked for a user who can read any file).
    unreadable = f'{roots["broken-unreadable_sources"][1]}/data/sources.npz'
    if not os.access(unreadable, os.R_OK):
        for case_id in ('broken-unreadable_sources/default/empty', 'broken-dir_init+unreadable_sources/default/empty'):
            assert node_outcome(result[case_id]).get('code') == 'EACCES', case_id
    # A falsy nominal table pointer is skipped like a missing one.
    for name in ('table_false', 'table_zero', 'table_empty', 'table_null'):
        assert ok(f'broken-{name}/default/empty')['identity'] == ok('base/default/empty')['identity'], name
    # Bytes that are not UTF-8 are read as U+FFFD; a lone surrogate in a path opens the file named U+FFFD.
    odd_bytes = ok('odd-bytes/default/empty')
    assert jsjson.parse(odd_bytes['admission'])['note'] == 'a\ufffdb\ufffd\ufffd\ufffdc\ufffd'
    assert jsjson.parse(odd_bytes['identity'])['digests']['data/\ud800.npz'] == digest('sources')
    for case_id, message in {
        'base/default/scenario': '电导率情景评价需要名义头皮节点表，用于核对同一电极采样。',
        'broken-table_null/default/scenario': '电导率情景评价需要名义头皮节点表，用于核对同一电极采样。',
        'table/default/scenario': '该电导率情景的头皮节点表尚未预计算',
        'table/default/scenario-number': '该电导率情景的头皮节点表尚未预计算',
        'table/default/head': '该头模或其头皮节点表尚未预计算',
        'full/default/bad-scenario': '电导率情景名称无效', 'full/default/bad-scenario-newline': '电导率情景名称无效',
        'full/default/bad-scenario-dash': '电导率情景名称无效', 'full/default/scenario-object': '电导率情景名称无效',
        'full/default/bad-head': '头模编号无效', 'full/default/bad-head-newline': '头模编号无效',
        'full/default/bad-head-dot': '头模编号无效', 'full/default/head-empty-array-first': '头模编号无效',
        'full/default/scenario-tostring': 'Cannot convert object to primitive value',
        'full/default/head-tostring': 'Cannot convert object to primitive value',
    }.items():
        assert result[case_id] == {**result[case_id], 'ok': False, 'message': message, 'code': None}, case_id
    assert ok('full/default/scenario+head')
    # Real paths (nodefs): InputIntegrity's root comes from realpathSync (link targets lexically, the spelling
    # kept), each input from realpath(3) (physically; on macOS in the on-disk case and normalization).
    lexical = jsjson.parse(ok('lexical/default/empty')['identity'])['digests']
    assert lexical['src/compact_eeg/workflows/paths.py'] == digest('decoy code')
    assert lexical['src/compact_eeg/workflows/head_model.py'] == digest('code')
    insensitive = {name: os.path.exists(roots[name][0]) for name in ('upper-root', 'nfd-root')}
    for name, spelled in insensitive.items():
        # A root spelled differently from the disk refuses every input; elsewhere it does not exist.
        expected = {'message': '输入文件超出本项目'} if spelled else {'code': 'ENOENT'}
        outcome = node_outcome(result[f'{name}/default/empty'])
        assert {k: outcome.get(k) for k in expected} == expected, name
    for name, spelled in (('upper-link', insensitive['upper-root']), ('nfd-link', insensitive['nfd-root'])):
        # A link whose target spells the root differently stays inside it: the same digests as the base root.
        if spelled:
            assert ok(f'{name}/default/empty')['identity'] == ok('base/default/empty')['identity'], name
        else:
            assert node_outcome(result[f'{name}/default/empty'])['code'] == 'ENOENT', name
    # A conda record whose name is not UTF-8 is listed as U+FFFD and cannot be opened (Linux; macOS refuses it).
    if os.path.exists(os.fsencode(roots['bad-utf8'][0]) + f'/{NATIVE}/conda-meta/'.encode() + BAD_UTF8_NAME):
        assert node_outcome(result['bad-utf8/default/empty'])['code'] == 'ENOENT'
    else:
        assert ok('bad-utf8/default/empty')['identity'] == ok('simnibs/default/empty')['identity'].replace(
            roots['simnibs'][0], roots['bad-utf8'][0])
    # Every canonical request of the phase 1 corpus has its tables on the full root.
    assert canonical_requests() and all(result[f'full/default/{name}']['ok'] for name in canonical_requests())
    # The interpreter fingerprint enters keys off macOS only; a fake interpreter gives {python: null}.
    assert ('"runtime":' in ok('base/default/empty')['identity']) == linux
    assert ('"runtime":{"python":null}' in native['identity']) == linux


# --- The real installation (EEG_KEY_PARITY_ROOT) ----------------------------------------------------------------

REAL_ROOT = os.environ.get('EEG_KEY_PARITY_ROOT')
real_root = pytest.mark.skipif(not REAL_ROOT, reason='set EEG_KEY_PARITY_ROOT to a checkout with results/v2 and .runtime')
REAL_CONFIGS = ('default', 'explicit', 'env', 'env-empty')
REAL_CASES = [Case(f'real/{config}/{request}', 'real', config, request) for config in REAL_CONFIGS for request in REQUESTS]
REAL_CASES += [Case(f'real/default/{request}', 'real', 'default', request) for request in canonical_requests()]
if not REAL_ROOT:
    REAL_CASES = REAL_CASES[:1]  # one skipped placeholder instead of one per case
RECORD_KINDS = ('local_app_jobs', 'design_evaluation_jobs', 'electrode_editor_jobs', 'source_reception_jobs',
                'source_reception_v2_jobs')
KEY = re.compile('[a-f0-9]{64}')


@pytest.fixture(scope='session')
def real(tmp_path_factory):
    root = REAL_ROOT
    requests = all_requests()
    specs = {case.id: spec_case(case, root, os.path.realpath(root), requests) for case in REAL_CASES}
    # One queue per configuration: hashing every input of the real installation again for each case is slow.
    node = run_node(list(specs.values()), tmp_path_factory.mktemp('key-parity-real'), reuse=True)
    return specs, node, PythonCases(reuse=True)


@pytest.mark.data_bundle
@real_root
@needs_node
@pytest.mark.parametrize('case', REAL_CASES, ids=lambda case: case.id)
def test_real_root_key_parity(case, real):
    specs, node, python = real
    assert python.run(specs[case.id]) == node_outcome(node['by_id'][case.id])


@pytest.mark.data_bundle
@real_root
def test_real_root_stored_records_rederive_their_keys():
    """Every stored cache round-trips byte for byte and re-derives ``result_sha256``; design and editor caches and
    every batch ``request.json`` with an identity re-derive the directory key."""
    checked = {'caches': 0, 'keys': 0}
    for kind in RECORD_KINDS:
        directory = Path(REAL_ROOT) / 'results/v2' / kind
        if not directory.is_dir():
            continue
        for entry in sorted(directory.iterdir()):
            if not KEY.fullmatch(entry.name) or not entry.is_dir():
                continue
            cache_path = entry / 'cache.json'
            if cache_path.is_file():
                raw = cache_path.read_bytes()
                cache = jsjson.parse(raw.decode('utf-8', errors='replace'))
                assert jsjson.stringify(cache).encode('utf-8') == raw, cache_path
                assert jsjson.sha256_hex(cache['result']) == cache['result_sha256'], cache_path
                assert cache['key'] == entry.name
                checked['caches'] += 1
                if kind in ('design_evaluation_jobs', 'electrode_editor_jobs'):
                    assert request_key(cache['result']['request'], cache['identity']) == entry.name, cache_path
                    checked['keys'] += 1
            for batch in sorted(entry.iterdir()):
                request_path = batch / 'request.json'
                if batch.is_dir() and request_path.is_file():
                    stored = jsjson.parse(request_path.read_bytes().decode('utf-8', errors='replace'))
                    if 'identity' in stored:
                        assert request_key(stored['request'], stored['identity']) == entry.name, request_path
                        checked['keys'] += 1
    assert checked['caches'] > 0 and checked['keys'] > 0
