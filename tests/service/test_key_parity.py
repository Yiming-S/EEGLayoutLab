"""Python request keys equal Node's on the same root (design 0001, phase 2 exit criterion 1; plan B1-B12).

For every synthetic root variant, interpreter configuration and request, ``eeglayoutlab.jobs`` must give the
configuration, identity text, admission text and key that Node's ``LocalComputeQueue`` and
``DesignEvaluationService`` give (tests/service/parity/identity.mjs), or fail the same way: by Node's code where
the error has one (system errors carry absolute paths in their messages), by name for a ``SyntaxError``, the
others by Node's message.

The radius identity (slice 3: ``identityFor`` of ``LocalComputeQueue``, the key of every radius record) is compared
the same way through tests/service/parity/library.mjs, on design roots with the radius code files added
(``radius_root``): each interpreter configuration, the radius-specific breaks (a code file linked out of the root,
which Node follows: plan B8) and every canonical request of the radius-search corpus. ``codeIdentity`` covers the
top-level ``src/compact_eeg/*.py`` only (check-project-structure.mjs:30).

The design-submission envelope (slice 5) is compared through tests/service/parity/annotations.mjs: Node's production
design-evaluation adapter (``designSubmission``, ``normalizeDesignRequest`` and the real context on the synthetic
base and full roots) and the same steps in Python give the same request text, key, names, source metadata and
worker input for bare requests and envelopes, so electrode names and source declarations never enter a key
(check-electrode-annotations.mjs:73, check-coordinate-review.mjs:122).

The electrode editor's context (slice 6: ``ElectrodeEditorService.context``, the key of every editor record) is
compared through tests/service/parity/editor_run.mjs (mode ``contexts``) on editor roots (tests/service/
editor_support.py ``editor_root``): a preparation and an evaluation of each kind of parent the library holds, on each
interpreter configuration of the base root and on variants where the parent's report, the surface admission, the
editor's code or the design inputs differ; the configuration, context members, identity, admission, parent record,
parent digest, key and worker input, or the refusal by Node's message.

With ``EEG_KEY_PARITY_ROOT=<checkout>`` the same comparisons also run on that real installation (marked
``data_bundle``; the radius identity also for every stored radius request, the editor's context for every parent the
editor offers and every stored editor request), and every stored design and editor cache and every batch
``request.json`` must re-derive its key. Nothing is written under that root.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

import pytest

from eeglayoutlab.jobs import identity as py_identity
from eeglayoutlab.jobs import nodepath
from eeglayoutlab.jobs import runtime as py_runtime
from eeglayoutlab.jobs.identity import request_key
from eeglayoutlab.schemas import jsjson
from eeglayoutlab.server.workspace import LOCAL_OWNER

from .key_parity_support import (
    BAD_UTF8_NAME, BANK, CONDA_META, CONFIGS, EDITOR_ACCEPTED, EDITOR_PARENTS, EDITOR_ROOT_CONFIGS, EDITOR_SOME,
    LINE_TERMINATOR_DIST_INFO, NATIVE, NATIVE_DIST_INFO, PRIOR, RADIUS_CODE_NAMES, RADIUS_KEY_REQUESTS,
    RADIUS_ROOT_CONFIGS, RADIUS_ROOTS, REQUESTS, ROOTS, SPATIAL, TABLE_DIR, Case, EditorCases, EnvelopeCases,
    PythonCases, all_requests, browser_submission, build_roots, canonical_requests, coordinate_sources, design_root,
    digest, editor_case_ids, editor_context_cases, envelope_outcome, needs_node, node_outcome, radius_cases,
    radius_corpus, radius_outcome, radius_root, require, run_annotations_node, run_editor_node, run_library_node,
    run_node, spec_case, synthetic_cases,
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


# --- The radius identity (slice 3) -------------------------------------------------------------------------------

RADIUS_CORPUS = radius_corpus()
RADIUS_CASE_IDS = [f'{name}/{config}/{request}' for name in RADIUS_ROOTS
                   for config in RADIUS_ROOT_CONFIGS.get(name, ('default',)) for request in RADIUS_KEY_REQUESTS]
RADIUS_CASE_IDS += [f'radius-base/default/{request}' for request in RADIUS_CORPUS]
RADIUS_WORKER = 'scripts/run_local_radius_compute.py'


@pytest.fixture(scope='session')
def radius_synthetic(tmp_path_factory):
    base = tmp_path_factory.mktemp('radius-parity')
    roots = {}
    for name, options in RADIUS_ROOTS.items():
        root = radius_root(base / 'roots' / name, **options)
        roots[name] = (root, os.path.realpath(root))
    cases = radius_cases(roots, RADIUS_CORPUS)
    node = run_library_node({'identities': cases}, base)
    return roots, {case['id']: case for case in cases}, {result['id']: result for result in node['identities']}, node


@needs_node
@pytest.mark.parametrize('case_id', RADIUS_CASE_IDS)
def test_radius_key_parity(case_id, radius_synthetic):
    _, cases, node, _ = radius_synthetic
    assert radius_outcome(cases[case_id]) == node_outcome(node[case_id])


def _code(result) -> dict:
    return jsjson.parse(result['identity'])['code']


@needs_node
def test_radius_variants_reach_their_branches(radius_synthetic):
    # Parity alone would also pass if a fixture missed its branch; these pin what each variant exercises.
    roots, _, result, output = radius_synthetic
    linux = output['platform'] != 'darwin'
    ok = lambda case_id: result[case_id]['ok'] and result[case_id]  # noqa: E731
    failed = lambda case_id: node_outcome(result[case_id])  # noqa: E731

    # The code files: the worker, its configuration and the two pointers, then the top-level *.py (a dot file too)
    # in UTF-16 code-unit order; nested workflows and other names never.
    whole = ok('radius-base/default/whole')
    code = list(_code(whole))
    assert code[:4] == [RADIUS_WORKER, 'configs/single_head_optimization.json', 'results/v2/current_multiregion_bank.json',
                        'results/v2/current_surface_admissibility.json']
    names = [path.removeprefix('src/compact_eeg/') for path in code[4:]]
    assert all(path.startswith('src/compact_eeg/') and '/' not in name for path, name in zip(code[4:], names))
    assert names == nodepath.js_sort(names) and names != sorted(names)
    assert {name for name in RADIUS_CODE_NAMES if name.endswith('.py')} <= set(names)
    assert not {'notes.txt', 'cache.pyc', 'module.py.bak'} & set(names)
    assert names.index('\U0001F600.py') < names.index('\uff5a.py')
    assert _code(whole)[RADIUS_WORKER] == digest('radius worker')
    assert jsjson.parse(whole['identity'])['version'] == 'local-radius-queue/1'
    assert jsjson.parse(whole['identity'])['threads'] == 2
    # The data-prior files only for a truthy data_prior, after the code files.
    assert list(_code(ok('radius-base/default/prior')))[-3:] == list(py_identity.DATA_PRIOR_FILES)
    assert list(_code(ok('radius-base/default/prior-empty-object')))[-3:] == list(py_identity.DATA_PRIOR_FILES)
    for name in ('prior-zero', 'prior-empty-string', 'spatial', 'empty', 'array', 'string'):
        assert ok(f'radius-base/default/{name}')['identity'] == whole['identity'], name
    assert ok('radius-no_prior/default/whole') and failed('radius-no_prior/default/prior')['code'] == 'ENOENT'
    # Requests differ only in their keys; a member read of null fails as in V8.
    assert len({ok(f'radius-base/default/{name}')['key'] for name in ('whole', 'preset', 'spatial', 'empty')}) == 4
    assert failed('radius-base/default/null')['message'] == "Cannot read properties of null (reading 'data_prior')"
    # A code file linked out of the root is followed (plan B8): its target's bytes, under its own name.
    assert _code(ok('radius-linked/default/whole'))['src/compact_eeg/linked.py'] == digest('outside code')
    for name, code_name in (('py_directory', 'EISDIR'), ('dangling_code', 'ENOENT'), ('no_src', 'ENOENT'),
                            ('no_worker', 'ENOENT')):
        assert failed(f'radius-{name}/default/whole')['code'] == code_name, name
    unreadable = f'{roots["radius-unreadable_code"][1]}/src/compact_eeg/b.py'
    if not os.access(unreadable, os.R_OK):
        assert failed('radius-unreadable_code/default/whole')['code'] == 'EACCES'
    # The compute interpreter: python || EEG_COMPUTE_PYTHON || the managed runtime || 'python3'.
    simnibs = roots['radius-simnibs'][0]
    for config, python in (('default', f'{simnibs}/{NATIVE}/bin/python'), ('explicit', '/explicit/python'),
                           ('env', '/env/python'), ('env-empty', f'{simnibs}/{NATIVE}/bin/python'),
                           ('explicit-empty', '/env/python')):
        assert ok(f'radius-simnibs/{config}/whole')['config']['python'] == python, config
    assert ok('radius-base/default/whole')['config']['python'] == 'python3'
    assert ok('radius-linux64/default/whole')['config']['python'].endswith('/.runtime/compute-linux-64/bin/python')
    assert ok('radius-dangling/default/whole')['config']['python'] == 'python3'
    # A linked root keeps its spelling; the same files give the same code digests.
    link, real = roots['radius-symlinked']
    assert link != real and ok('radius-symlinked/default/whole')['config']['repositoryRoot'] == link
    assert _code(ok('radius-symlinked/default/whole')) == _code(ok('radius-simnibs/default/whole'))
    # The interpreter fingerprint enters keys off macOS only.
    assert ('"runtime":' in whole['identity']) == linux
    assert RADIUS_CORPUS and all(result[f'radius-base/default/{name}']['ok'] for name in RADIUS_CORPUS)


def test_code_identity_covers_top_level_files_only(tmp_path):
    """check-project-structure.mjs:30 'checkout roots and independently scoped implementation identities are
    explicit': the checkout root and native interpreter, ``codeIdentity`` over the top-level ``src/compact_eeg``
    files only, and workflow lists that name files of this checkout under ``src/compact_eeg/workflows/``."""
    require('pydantic')  # jobs.radius imports the radius-search schema; the native runtime suite has no Pydantic
    from eeglayoutlab.jobs.radius import code_identity

    checkout = Path(__file__).resolve().parents[2]
    assert py_runtime.default_repository_root() == os.path.realpath(checkout)
    assert py_runtime.native_python_path(str(checkout)) == f'{checkout}/.runtime/simnibs-4.6.0/bin/python'
    for path in ('scripts/run_local_radius_compute.py', 'configs/single_head_optimization.json',
                 'results/v2/current_multiregion_bank.json', 'results/v2/current_surface_admissibility.json',
                 'src/compact_eeg/local_radius_compute.py', 'src/compact_eeg/workflows/other.py'):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text('{}', encoding='utf-8')
    identity = code_identity(str(tmp_path))
    assert 'src/compact_eeg/local_radius_compute.py' in identity
    assert not any('/workflows/' in path for path in identity)
    workflows = {*py_identity.DESIGN_WORKFLOW, *py_identity.RECEPTION_WORKFLOW, *py_identity.RECEPTION_V2_WORKFLOW,
                 *py_identity.EDITOR_WORKFLOW}
    for path in workflows:
        assert (checkout / path).read_text(encoding='utf-8')
        assert path.startswith('src/compact_eeg/workflows/')
    assert any(path.endswith('/electrode_editor.py') for path in py_identity.EDITOR_WORKFLOW)
    assert any(path.endswith('/source_reception.py') for path in py_identity.RECEPTION_WORKFLOW)


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


RADIUS_REAL_CONFIGS = ('default', 'explicit', 'env', 'env-empty')


@pytest.mark.data_bundle
@real_root
@needs_node
def test_real_root_radius_key_parity(tmp_path):
    """The radius identity on the installation: each configuration, and every stored radius request, whose key is
    its directory's exactly when the record is current (the library's ``compatible``)."""
    stored = {}
    directory = Path(REAL_ROOT) / 'results/v2/local_app_jobs'
    for entry in sorted(directory.iterdir()) if directory.is_dir() else ():
        cache = entry / 'cache.json'
        if KEY.fullmatch(entry.name) and cache.is_file():
            stored[entry.name] = jsjson.parse(cache.read_bytes().decode('utf-8', errors='replace'))['request']
    cases = [{'id': f'real/{config}/{name}', 'root': REAL_ROOT, **CONFIGS[config], 'request': request}
             for config in RADIUS_REAL_CONFIGS for name, request in RADIUS_KEY_REQUESTS.items()]
    cases += [{'id': f'real/default/stored-{key}', 'root': REAL_ROOT, 'request': request} for key, request in stored.items()]
    node = {result['id']: result for result in run_library_node({'identities': cases}, tmp_path)['identities']}
    for case in cases:
        assert radius_outcome(case) == node_outcome(node[case['id']]), case['id']
    assert stored and all(node[f'real/default/stored-{key}']['ok'] for key in stored)
    assert node['real/default/whole']['ok']


# --- The design submission envelope (slice 5) ---------------------------------------------------------------------

def _grid(z: Any) -> list:
    return [[(i % 8) * 6, (i // 8) * 6, z(i)] for i in range(64)]


SHARED_DESIGN = {'schema': 'eeg-electrode-design/1', 'coordinate_system': 'ernie_native_mm', 'unit': 'mm',
                 'name': 'Shared layout', 'xyz_mm': _grid(lambda i: 1e-14), 'region_indices': [i % 2 for i in range(64)]}
# check-coordinate-review.mjs:24-27: a name with a comma and quotes, the others CJK.
REVIEW_DESIGN = {'schema': 'eeg-electrode-design/1', 'coordinate_system': 'ernie_native_mm', 'unit': 'mm',
                 'name': 'Original scientific design name',
                 'xyz_mm': [[(i % 8) * 6 + 1.42e-14, (i // 8) * 6, -112.31415926535898] for i in range(64)],
                 'region_indices': [i % 2 for i in range(64)],
                 'electrode_names': [' Fp1, "left" ' if i == 0 else f'电极{i + 1}' for i in range(64)]}
ENVELOPE_OWNERS = ('a' * 64, LOCAL_OWNER)


def _names(prefix: str) -> list[str]:
    return [f'{prefix}{i + 1}' for i in range(64)]


def _envelope_raws() -> dict[str, tuple[str, Any]]:
    """Raw bodies by case id, each with its root: the scientific variants bare and named, the coordinate-review
    design bare, named and with every source declaration, and envelopes the adapter refuses."""
    a, b = {**SHARED_DESIGN, 'electrode_names': _names('A')}, {**SHARED_DESIGN, 'electrode_names': _names('B')}
    raws: dict[str, tuple[str, Any]] = {}
    variants = {'evaluate': ('base', {}), 'perturb': ('base', {'action': 'perturb'}),
                'robustness': ('base', {'robustness': 'standard/1'}), 'noise': ('base', {'noise_model': SPATIAL}),
                'prior': ('base', {'data_prior': PRIOR}), 'scenario': ('full', {'conductivity_scenario': 'skull_x2'}),
                'head': ('full', {'head_id': 'ixi002'})}
    for name, (root, options) in variants.items():
        options = dict(options)
        action = options.pop('action', 'evaluate')
        raws[f'{name}/bare'] = (root, browser_submission(SHARED_DESIGN, action, **options))
        raws[f'{name}/names-a'] = (root, browser_submission(a, action, **options))
        raws[f'{name}/names-b'] = (root, browser_submission(b, action, **options))
    raws['review/bare'] = ('base', browser_submission({k: v for k, v in REVIEW_DESIGN.items() if k != 'electrode_names'}))
    raws['review/named'] = ('base', browser_submission(REVIEW_DESIGN))
    for name, source in coordinate_sources().items():
        raws[f'review/sourced-{name}'] = ('base', browser_submission({**REVIEW_DESIGN, 'source_metadata': source}))
        unnamed = {k: v for k, v in REVIEW_DESIGN.items() if k != 'electrode_names'}
        raws[f'review/source-only-{name}'] = ('base', browser_submission({**unnamed, 'source_metadata': source}))
    v1 = coordinate_sources().get('v1', {})
    for name, source in {'path': {**v1, 'electrodes_file': '/private/input.tsv'},
                         'long-description': {**v1, 'coordinate_system_description': 'x' * 2049},
                         'head-frame': {**v1, 'coordinate_system': 'head'}, 'null': None}.items():
        envelope = browser_submission(REVIEW_DESIGN)
        raws[f'refused/source-{name}'] = ('base', {**envelope, 'source_metadata': source})
    named = browser_submission(a)
    raws['refused/names-63'] = ('base', {**named, 'electrode_names': _names('A')[1:]})
    raws['refused/extra-key'] = ('base', {**named, 'extra': 1})
    raws['refused/request-null'] = ('base', {**named, 'request': None})
    raws['refused/request-invalid'] = ('base', {**named, 'request': {**named['request'], 'seed': -1}})
    raws['refused/scenario-on-base'] = ('base', browser_submission(a, conductivity_scenario='skull_x2'))
    raws['refused/bare-invalid'] = ('base', {**named['request'], 'radius_mm': 4})
    return raws


ENVELOPE_RAWS = _envelope_raws()


@pytest.fixture(scope='session')
def envelope_synthetic(tmp_path_factory):
    require('pydantic')
    base = tmp_path_factory.mktemp('envelope-parity')
    roots = {name: design_root(base / 'roots' / name, **ROOTS[name]) for name in ('base', 'full')}
    cases = [{'id': case_id, 'root': roots[root], 'raw': raw} for case_id, (root, raw) in ENVELOPE_RAWS.items()]
    # One service per root, as the driver keeps one adapter per root and interpreter.
    adapters = EnvelopeCases()
    python = {case['id']: adapters.run(case) for case in cases}
    # Node's annotation identities of the same prepared values (the key and the canonical request from Python).
    identities = []
    for case_id, outcome in python.items():
        if case_id.startswith('review/') and outcome['ok'] and outcome['electrode_names'] is not None:
            prepared = _prepared(outcome)
            identities += [{'id': f'{case_id}/{owner}', 'owner': owner, 'prepared': jsjson.stringify(prepared),
                            'create': True} for owner in ENVELOPE_OWNERS]
    (base / 'node-root').mkdir()
    node = run_annotations_node({'root': str(base / 'node-root'), 'prepares': cases, 'identities': identities}, base)
    return {'cases': cases, 'python': python, 'node': node, 'identities': identities}


def _prepared(outcome: dict) -> dict:
    """The adapter's prepared value from a compared outcome (without ``ctx``, which annotations do not read)."""
    prepared = {'request': jsjson.parse(outcome['request']), 'key': outcome['key']}
    for name in ('electrode_names', 'source_metadata'):
        if outcome[name] is not None:
            prepared[name] = jsjson.parse(outcome[name])
    return prepared


@needs_node
@pytest.mark.parametrize('case_id', list(ENVELOPE_RAWS))
def test_envelope_prepare_parity(case_id, envelope_synthetic):
    """The production adapter's ``prepare`` of each body on the same root: request text, key, identity, names,
    source metadata and worker input, or the same refusal (message and status)."""
    assert envelope_synthetic['python'][case_id] == envelope_outcome(envelope_synthetic['node']['prepares'][case_id])


@needs_node
def test_envelope_names_never_enter_the_request_worker_input_or_key(envelope_synthetic):
    """check-electrode-annotations.mjs:73 'production adapter normalization excludes A/B names from request, worker
    input and scientific key', on synthetic roots with Node's real context: a bare request and two envelopes with
    other names give one request text, one worker input and one key, in both hosts."""
    groups = {case_id.split('/')[0] for case_id in ENVELOPE_RAWS if case_id.endswith('/names-a')}
    assert groups == {'evaluate', 'perturb', 'robustness', 'noise', 'prior', 'scenario', 'head'}
    node = {case_id: envelope_outcome(result) for case_id, result in envelope_synthetic['node']['prepares'].items()}
    for host, outcomes in (('python', envelope_synthetic['python']), ('node', node)):
        keys = set()
        for group in groups:
            bare, *named = (outcomes[f'{group}/{name}'] for name in ('bare', 'names-a', 'names-b'))
            assert bare['ok'] and all(item['ok'] for item in named), (host, group)
            for item in named:
                assert (item['request'], item['key'], item['worker_input']) == (bare['request'], bare['key'],
                                                                                bare['request']), (host, group)
                assert item['keys'] == ['request', 'key', 'ctx', 'electrode_names'], (host, group)
                assert 'electrode_names' not in item['request'] and 'A1' not in item['request'], (host, group)
            assert bare['keys'] == ['request', 'key', 'ctx'] and bare['electrode_names'] is None, (host, group)
            assert named[0]['electrode_names'] == jsjson.stringify(_names('A')), (host, group)
            assert named[1]['electrode_names'] == jsjson.stringify(_names('B')), (host, group)
            keys.add(bare['key'])
        assert len(keys) == len(groups), host  # the scientific options do reach the key


@needs_node
def test_source_metadata_cannot_change_normalization_context_or_annotation_ids(envelope_synthetic, tmp_path):
    """check-coordinate-review.mjs:122 'source metadata remains bounded and cannot change scientific normalization,
    context identity or legacy annotation IDs': every source declaration leaves the request and key of the bare
    request; the annotation of the named submission keeps its id (no source_metadata), the sourced one gets another
    and reads back with its declaration; ids equal Node's for the same owner; invalid declarations are refused."""
    from eeglayoutlab.jobs.annotations import (
        SOURCE, WORKSPACE_ANNOTATIONS, ElectrodeAnnotations, validate_electrode_annotation,
    )

    python, node = envelope_synthetic['python'], envelope_synthetic['node']
    sources = coordinate_sources()
    assert set(sources) == {'v1', 'v2Mni', 'v2Labels', 'v3Native', 'v3Mni', 'v3BidsHead', 'v3Labels', 'v3Elc', 'v3Sfp',
                            'v3SfpNative'}
    bare, named = python['review/bare'], python['review/named']
    for name, source in sources.items():
        for case_id in (f'review/sourced-{name}', f'review/source-only-{name}'):
            sourced = python[case_id]
            assert (sourced['request'], sourced['key']) == (bare['request'], bare['key']), case_id
            assert 'source_metadata' not in sourced['request'] and 'coordinate_system_description' not in sourced['request']
            assert sourced['source_metadata'] == jsjson.stringify(source)
        assert python[f'review/source-only-{name}']['electrode_names'] == jsjson.stringify([f'E{i + 1}' for i in range(64)])
    for name in ('path', 'long-description', 'head-frame', 'null'):
        assert python[f'refused/source-{name}'] == {'ok': False, 'message': SOURCE, 'status': None, 'safe': False}

    workspace = tmp_path / 'W'
    workspace.mkdir()
    for owner in ENVELOPE_OWNERS:
        annotations = ElectrodeAnnotations([(str(workspace), WORKSPACE_ANNOTATIONS)], owner=owner, writable=True)
        old = annotations.create(_prepared(named))
        for name, source in sources.items():
            current = annotations.create(_prepared(python[f'review/sourced-{name}']))
            assert 'source_metadata' not in old and current['source_metadata'] == source and current['id'] != old['id']
            assert validate_electrode_annotation(current, bare['key']) is current
            reread = ElectrodeAnnotations([(str(workspace), WORKSPACE_ANNOTATIONS)]).read(current['id'], bare['key'])
            assert reread == current
            assert node['identities'][f'review/sourced-{name}/{owner}']['create']['value'] == jsjson.stringify(current)
        assert annotations.create(_prepared(named))['id'] == old['id']
        assert validate_electrode_annotation(old, bare['key']) is old
        assert node['identities'][f'review/named/{owner}']['create']['value'] == jsjson.stringify(old)


# --- The electrode editor's context (slice 6) ----------------------------------------------------------------------

EDITOR_CASE_IDS = editor_case_ids()
EDITOR_MESSAGES = {
    'record': 'Choose a completed layout with saved region boundaries',
    'noise': 'The electrode editor scores with independent noise; choose a layout searched under independent noise',
    'digest': 'Parent changed; reload the layout before editing',
    'geometry': 'Parent region geometry or surface-admission identity differs',
}


@pytest.fixture(scope='session')
def editor_synthetic(tmp_path_factory):
    require('pydantic')  # the library and the design context
    from .editor_support import build_editor_roots

    base = tmp_path_factory.mktemp('editor-parity')
    roots = build_editor_roots(base / 'roots')
    cases = editor_context_cases(roots)
    node = run_editor_node(cases, base)
    return roots, {case['id']: case for case in cases}, node, base


@needs_node
@pytest.mark.parametrize('case_id', EDITOR_CASE_IDS)
def test_editor_context_parity(case_id, editor_synthetic):
    _, cases, node, base = editor_synthetic
    assert EditorCases(base).run(cases[case_id]) == node_outcome(node['by_id'][case_id])


@needs_node
def test_editor_variants_reach_their_branches(editor_synthetic):
    # Parity alone would also pass if a fixture missed its branch; these pin what each variant exercises.
    from eeglayoutlab.jobs.integrity import InputIntegrity

    from .editor_support import EDITOR_CODE

    roots, cases, node, _ = editor_synthetic
    result = node['by_id']
    ok = lambda case_id: result[case_id]['ok'] and result[case_id]  # noqa: E731
    message = lambda case_id: node_outcome(result[case_id]).get('message')  # noqa: E731
    code = lambda case_id: node_outcome(result[case_id]).get('code')  # noqa: E731

    # Every kind of parent on the base root, in Node's order of checks.
    for config in EDITOR_ROOT_CONFIGS['editor-base']:
        for parent in EDITOR_ACCEPTED:
            assert ok(f'editor-base/{config}/prepare-{parent}') and ok(f'editor-base/{config}/evaluate-{parent}')
        for parent in ('historical', 'offline', 'design', 'strict-no-layout', 'cache-unpatched', 'cache-zero-patches',
                       'cache-no-layout', 'missing'):
            for kind in ('prepare', 'evaluate'):
                assert message(f'editor-base/{config}/{kind}-{parent}') == EDITOR_MESSAGES['record'], parent
        assert message(f'editor-base/{config}/evaluate-cache-spatial') == EDITOR_MESSAGES['noise']
        for parent in ('cache-geometry', 'cache-admission'):
            assert message(f'editor-base/{config}/evaluate-{parent}') == EDITOR_MESSAGES['geometry']
        assert message(f'editor-base/{config}/stale-cache') == EDITOR_MESSAGES['digest']
    assert set(EDITOR_PARENTS) == {*EDITOR_ACCEPTED, 'historical', 'offline', 'design', 'strict-no-layout',
                                   'cache-unpatched', 'cache-zero-patches', 'cache-no-layout', 'missing',
                                   'cache-spatial', 'cache-geometry', 'cache-admission'}

    # B17: the design identity, ``schema`` overwritten in place, three members appended; the context's members.
    prepared = ok('editor-base/default/prepare-cache')
    evaluated = ok('editor-base/default/evaluate-cache')
    assert prepared['keys'] == ['identity', 'admission', 'key', 'parent', 'parent_digest']
    identity = jsjson.parse(prepared['identity'])
    base = roots['editor-base']
    request = cases['editor-base/default/prepare-cache']['request']
    design = py_identity.design_context(base['root'], prepared['config']['nativePython'],
                                        InputIntegrity(base['root']), request)
    assert list(identity) == [*design.identity, 'parent_digest', 'editor_sha256', 'editor_implementation_sha256']
    assert identity == {**design.identity, 'schema': 'electrode-editor-cache/1',
                        'parent_digest': digest(prepared['parent']), 'editor_sha256': digest('editor worker'),
                        'editor_implementation_sha256': {EDITOR_CODE: digest('editor code')}}
    assert prepared['key'] == request_key(request, identity)
    assert prepared['parent_digest'] == evaluated['parent_digest'] == digest(prepared['parent'])
    assert evaluated['identity'] == prepared['identity'] and evaluated['key'] != prepared['key']
    assert prepared['worker_input'] == f'{{"request":{jsjson.stringify(request)},"parent":{prepared["parent"]}}}'
    # The strict-area parent's geometry is its report's, a radius cache's its provenance's.
    assert 'geometry_sha256' not in jsjson.parse(ok('editor-base/default/prepare-strict')['parent'])['provenance']
    assert jsjson.parse(prepared['parent'])['provenance']['geometry_sha256'] == digest('candidates')

    # The interpreter enters the design identity; the library's compatibility enters the parent's digest.
    keys = {config: ok(f'editor-base/{config}/prepare-strict')['key'] for config in EDITOR_ROOT_CONFIGS['editor-base']}
    assert len(set(keys.values())) == 3 and keys['default'] == keys['env-empty']
    assert ok('editor-simnibs/default/prepare-cache')['config']['nativePython'].endswith(f'/{NATIVE}/bin/python')
    # A linked root keeps its spelling: the report's real path is not under it, so the library refuses the
    # strict-area dataset (Node's 报告路径或身份无效) and the editor its layouts; the radius caches stay parents.
    link = roots['editor-symlinked']['root']
    linked = ok('editor-symlinked/default/prepare-cache')['config']['repositoryRoot']
    assert linked == link != roots['editor-symlinked']['tree']
    assert message('editor-symlinked/default/prepare-strict') == EDITOR_MESSAGES['record']
    assert ok('editor-table/default/prepare-cache')['identity'] != prepared['identity']

    # Variants: the report's geometry, the admission, the editor's code, the design inputs, no library.
    assert message('editor-no-geometry/default/prepare-strict') == EDITOR_MESSAGES['geometry']
    assert ok('editor-no-geometry/default/prepare-cache')
    for parent in ('strict', 'cache', 'cache-other-code'):
        assert message(f'editor-other-admission/default/prepare-{parent}') == EDITOR_MESSAGES['geometry']
    for name, error in (('no-script', 'ENOENT'), ('no-code', 'ENOENT'), ('code-dir', 'EISDIR')):
        assert code(f'editor-{name}/default/prepare-cache') == error, name
        assert message(f'editor-{name}/default/prepare-missing') == EDITOR_MESSAGES['record'], name
    broken = node_outcome(result['editor-broken-bank/default/prepare-cache'])
    assert not broken['ok'] and broken.get('message') not in EDITOR_MESSAGES.values()
    assert message('editor-broken-bank/default/prepare-missing') == EDITOR_MESSAGES['record']
    assert message('editor-broken-bank/default/evaluate-cache-spatial') == EDITOR_MESSAGES['noise']
    for parent in EDITOR_SOME:
        assert message(f'editor-no-library/default/prepare-{parent}') == EDITOR_MESSAGES['record'], parent

    # Values the routes never pass: read as V8 reads them.
    assert message('editor-base/default/odd-null') == "Cannot read properties of null (reading 'parent_id')"
    assert message('editor-base/default/odd-empty') == EDITOR_MESSAGES['record']
    assert message('editor-base/default/odd-no-digest') == EDITOR_MESSAGES['digest']
    assert ok('editor-base/default/odd-no-action')['identity'] == prepared['identity']
    odd = ok('editor-base/default/odd-index-keys')
    assert odd['worker_input'].startswith('{"request":{"1":["a",{"1":"a","2":"b"}],"2":"b","parent_id":')
    assert len({ok(f'editor-base/default/{name}')['key'] for name in ('odd-no-action', 'odd-index-keys',
                                                                       'prepare-cache')}) == 3


# The reference of 2026-11-23 (Node, the installation's default configuration): a preparation of this parent.
REFERENCE_PARENT = 'bb0d29ac477c29511e3d40985e5f6c9cc0d80c58a12716894fd677caa2752cf3'
REFERENCE = {'key': '57dabe43c3cc58137d5a296d665f125495db66eab760f3019a6ed5755758ea12',
             'parent_digest': '6485c7150479644ad536a5e3414c88c6a41811a502bcee20852697d04a978685',
             'identity_sha256': 'add0ef2a4af4e2557fe319810a4713260c207a32b25e98f846bedfa93cd6d1d7'}


@pytest.mark.data_bundle
@real_root
@needs_node
def test_real_root_editor_context_parity(tmp_path):
    """The editor's context on the installation (its default configuration, one queue and service as the server
    has): a preparation of every parent the editor offers and of the reference parent, and every stored editor
    request as stored. Python and Node agree on each. An offered parent is prepared or, once the region geometry or
    surface admission moved on, refused for that alone (``parents()`` does not check them, as in Node); which
    parents are refused, and which stored keys and reference values still hold today, is printed (inputs move on;
    an evaluation whose parent changed is refused)."""
    require('pydantic')
    from eeglayoutlab.jobs.editor_records import parents
    from eeglayoutlab.jobs.library import Library

    config = py_runtime.runtime_config(REAL_ROOT, env={})
    offered = [row['id'] for row in parents(Library(config.repository_root, config))]
    stored = {}
    directory = Path(REAL_ROOT) / 'results/v2/electrode_editor_jobs'
    for entry in sorted(directory.iterdir()) if directory.is_dir() else ():
        cache = entry / 'cache.json'
        if KEY.fullmatch(entry.name) and cache.is_file():
            stored[entry.name] = jsjson.parse(cache.read_bytes().decode('utf-8', errors='replace'))['result']['request']
    cases = [{'id': f'real/prepare-{id}', 'root': REAL_ROOT, 'request': {'action': 'prepare', 'parent_id': id}}
             for id in dict.fromkeys([REFERENCE_PARENT, *offered])]
    cases += [{'id': f'real/stored-{key}', 'root': REAL_ROOT, 'request': request} for key, request in stored.items()]
    node = run_editor_node(cases, tmp_path, reuse=True)['by_id']
    python = EditorCases(tmp_path, reuse=True)
    outcomes = {case['id']: python.run(case) for case in cases}
    for case in cases:
        assert outcomes[case['id']] == node_outcome(node[case['id']]), case['id']
    refused = [id for id in offered if not outcomes[f'real/prepare-{id}']['ok']]
    assert offered and all(outcomes[f'real/prepare-{id}'].get('message') == EDITOR_MESSAGES['geometry']
                           for id in refused)
    reference = outcomes[f'real/prepare-{REFERENCE_PARENT}']
    today = ({'key': reference['key'], 'parent_digest': reference['parent_digest'],
              'identity_sha256': digest(reference['identity'])} if reference['ok'] else reference)
    print(f'\neditor reference {REFERENCE_PARENT[:12]}: ' + ', '.join(
        f'{name} {"matches" if today.get(name) == value else "differs"}' for name, value in REFERENCE.items()))
    for key in stored:
        outcome = outcomes[f'real/stored-{key}']
        refusal = outcome.get('message') or outcome.get('code')
        state = ('key matches' if outcome['ok'] and outcome['key'] == key else
                 f'key differs ({outcome["key"][:12]})' if outcome['ok'] else f'refused: {refusal}')
        print(f'editor cache {key[:12]} {stored[key]["action"]}: {state}')
    print(f'editor parents prepared: {len(offered) - len(refused)} of {len(offered)}; refused for their geometry or '
          f'admission: {", ".join(id[:12] for id in refused) or "none"}')
