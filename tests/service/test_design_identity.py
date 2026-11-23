"""Design-evaluation identity rules without Node: ports of webapp/scripts/check-design-decision.mjs ('source, scalp
and manifest bytes all invalidate the real context identity'), check-data-prior.mjs ('the prior modules and atlas
enter the computation identity only for requests with a prior') and check-design-robustness.mjs ('the robustness
module enters the context identity only for requests that use it').

Each Node test builds `new DesignEvaluationService({root, python: 'python3'})`; here that is
`runtime_config(root, 'python3').native_python` with one InputIntegrity, so memos persist across file changes as in
the Node service.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from eeglayoutlab.jobs import nodefs
from eeglayoutlab.jobs.identity import DATA_PRIOR_FILES, IdentityError, design_context
from eeglayoutlab.jobs.integrity import InputIntegrity
from eeglayoutlab.jobs.runtime import runtime_config
from eeglayoutlab.schemas import jsjson

from .key_parity_support import design_root, digest

DESIGN = {
    'schema': 'eeg-electrode-design/1', 'coordinate_system': 'ernie_native_mm', 'unit': 'mm', 'name': 'test',
    'xyz_mm': [[(i % 8) * 6, (i // 8) * 6, 0] for i in range(64)],
    'region_indices': [int(i >= 32) for i in range(64)],
}
REQUEST = {'action': 'evaluate', 'design': DESIGN, 'radius_mm': 6, 'seed': 42}
PRIOR = {'region_gain': [1.037, 2.829, 0.09946, 1.344, 0.4122, 1.072, 0.09946], 'rho': 0.2, 'length_mm': 20}
ROBUST_REQUEST = {**REQUEST, 'robustness': 'standard/1'}


class Service:
    """``DesignEvaluationService({root, python: 'python3'})``: its ``context(request)``."""

    def __init__(self, root: str):
        self.config = runtime_config(root, 'python3', env={})
        self.inputs = InputIntegrity(self.config.repository_root)

    def context(self, request):
        return design_context(self.config.repository_root, self.config.native_python, self.inputs, request)


def _write(root: Path, path: str, body: str) -> None:
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(body, encoding='utf-8')


def test_source_scalp_and_manifest_bytes_all_invalidate_the_context_identity(tmp_path):
    # check-design-decision.mjs:367. Its first assertion (the reception service's nativeContext equals this
    # context) belongs to signal reception, ported in slice 7.
    root = Path(design_root(tmp_path))
    service = Service(str(root))
    previous = service.context(REQUEST).key
    for path in ('src/compact_eeg/workflows/design_evaluation.py', 'src/compact_eeg/workflows/head_model.py',
                 'src/compact_eeg/workflows/reception_forward_provider.py', 'src/compact_eeg/workflows/shared_native_forward.py',
                 'src/compact_eeg/workflows/scalp_node_table.py', 'src/compact_eeg/noise_models.py',
                 'src/compact_eeg/workflows/head_package.py', 'data/sources.npz', 'data/scalp/external_scalp_vertices_m.npy',
                 'data/scalp/external_scalp_triangles.npy'):
        _write(root, path, 'changed')
        current = service.context(REQUEST).key
        assert current != previous
        previous = current
    _write(root, 'data/admission.npz', 'changed mask')
    with pytest.raises(IdentityError, match='筛选'):
        service.context(REQUEST)
    _write(root, 'results/v2/current_surface_admissibility.json', jsjson.stringify({
        'path': 'data/admission.npz', 'sha256': digest('changed mask'), 'geometry_sha256': digest('candidates'),
        'schema_version': 'native-external-exposure/2'}))
    previous = service.context(REQUEST).key
    # A published scalp-node table enters the identity: pointer, manifest, index and row bytes.
    table_dir = 'results/v2/scalp_node_table/' + 't' * 64

    def table_pointer(manifest):
        return jsjson.stringify({'schema': 'scalp-node-superposition/1', 'table_id': 't' * 64,
                                 'manifest_path': table_dir + '/manifest.json', 'manifest_sha256': digest(manifest)})

    for name, body in (('manifest.json', 'manifest'), ('index.npz', 'index'), ('rows.npy', 'rows')):
        _write(root, f'{table_dir}/{name}', body)
    _write(root, 'results/v2/current_scalp_node_table.json', table_pointer('manifest'))
    current = service.context(REQUEST).key
    assert current != previous
    previous = current
    _write(root, f'{table_dir}/rows.npy', 'changed rows')
    current = service.context(REQUEST).key
    assert current != previous
    # A conductivity scenario adds its definition and its own table only when requested.
    _write(root, f'{table_dir}/manifest.json', 'manifest')
    _write(root, f'{table_dir}/rows.npy', 'rows')
    nominal_key = service.context(REQUEST).key
    scenario_request = {**REQUEST, 'conductivity_scenario': 'skull_x2'}
    with pytest.raises(IdentityError, match='尚未预计算'):
        service.context(scenario_request)
    # Without the nominal table the worker would solve FEM before rejecting a scenario.
    (root / 'results/v2/current_scalp_node_table.json').unlink()
    with pytest.raises(IdentityError, match='名义头皮节点表'):
        service.context(scenario_request)
    _write(root, 'results/v2/current_scalp_node_table.json', table_pointer('manifest'))
    scenario_dir = 'results/v2/scalp_node_table_scenarios/skull_x2/' + 's' * 64
    for name, body in (('manifest.json', 'scenario manifest'), ('index.npz', 'scenario index'), ('rows.npy', 'scenario rows')):
        _write(root, f'{scenario_dir}/{name}', body)
    _write(root, 'configs/conductivity_scenarios.json', 'scenarios')
    _write(root, 'results/v2/scalp_node_table_scenarios/skull_x2/current.json', jsjson.stringify({
        'schema': 'scalp-node-superposition/1', 'table_id': 's' * 64, 'manifest_path': scenario_dir + '/manifest.json',
        'manifest_sha256': digest('scenario manifest')}))
    assert service.context(REQUEST).key == nominal_key
    previous = service.context(scenario_request).key
    for path in ('configs/conductivity_scenarios.json', scenario_dir + '/rows.npy', scenario_dir + '/index.npz'):
        _write(root, path, 'changed')
        current = service.context(scenario_request).key
        assert current != previous
        previous = current
    assert service.context(REQUEST).key == nominal_key
    _write(root, f'{scenario_dir}/manifest.json', 'changed scenario manifest')
    with pytest.raises(IdentityError, match='电导率情景头皮节点表'):
        service.context(scenario_request)
    _write(root, f'{scenario_dir}/manifest.json', 'scenario manifest')
    # A head package adds its package files and its own table only when requested.
    head_request = {**REQUEST, 'head_id': 'ixi002'}
    with pytest.raises(IdentityError, match='尚未预计算'):
        service.context(head_request)
    head, head_table = 'results/v2/heads/ixi002', 'results/v2/heads/ixi002/table/' + 'h' * 64
    head_files = ('package.json', 'scalp.npz', 'admissibility.npz', 'sources.npz', 'mapping.npz')
    for name in head_files:
        _write(root, f'{head}/{name}', name)
    for name, body in (('manifest.json', 'head manifest'), ('index.npz', 'head index'), ('rows.npy', 'head rows')):
        _write(root, f'{head_table}/{name}', body)
    _write(root, f'{head}/table.json', jsjson.stringify({
        'schema': 'scalp-node-superposition/1', 'table_id': 'h' * 64, 'manifest_path': head_table + '/manifest.json',
        'manifest_sha256': digest('head manifest')}))
    assert service.context(REQUEST).key == nominal_key
    previous = service.context(head_request).key
    for path in (*(f'{head}/{name}' for name in head_files), head_table + '/rows.npy', head_table + '/index.npz'):
        _write(root, path, 'changed')
        current = service.context(head_request).key
        assert current != previous
        previous = current
    assert service.context(REQUEST).key == nominal_key
    _write(root, f'{head_table}/manifest.json', 'changed head manifest')
    with pytest.raises(IdentityError, match='头模头皮节点表'):
        service.context(head_request)
    _write(root, f'{table_dir}/manifest.json', 'changed manifest')
    with pytest.raises(IdentityError, match='头皮节点表'):
        service.context(REQUEST)


def test_prior_files_enter_the_identity_only_with_a_prior(tmp_path):
    # check-data-prior.mjs:98. Its last part (the radius queue adds the same files to its code identity) is the
    # radius identity, ported with it in slice 3.
    root = Path(design_root(tmp_path))
    service = Service(str(root))
    plain, with_prior = service.context(REQUEST), service.context({**REQUEST, 'data_prior': PRIOR})
    for path in DATA_PRIOR_FILES:
        assert path not in plain.identity['digests']
        assert path in with_prior.identity['digests']
    assert list(with_prior.identity['digests'])[-len(DATA_PRIOR_FILES):] == list(DATA_PRIOR_FILES)
    _write(root, 'src/compact_eeg/workflows/data_prior.py', 'changed')
    assert service.context(REQUEST).key == plain.key
    assert service.context({**REQUEST, 'data_prior': PRIOR}).key != with_prior.key


def test_robustness_module_enters_the_identity_only_for_robustness_requests(tmp_path):
    # check-design-robustness.mjs:80
    root = Path(design_root(tmp_path))
    service = Service(str(root))
    plain, robust = service.context(REQUEST), service.context(ROBUST_REQUEST)
    assert 'src/compact_eeg/workflows/design_robustness.py' not in plain.identity['digests']
    assert 'src/compact_eeg/workflows/design_robustness.py' in robust.identity['digests']
    _write(root, 'src/compact_eeg/workflows/design_robustness.py', 'changed')
    assert service.context(REQUEST).key == plain.key
    assert service.context(ROBUST_REQUEST).key != robust.key


def test_identity_members_and_key_formula(tmp_path):
    service = Service(design_root(tmp_path))
    context = service.context(REQUEST)
    assert list(context.identity)[:4] == ['schema', 'digests', 'python', 'threads']
    assert context.identity['schema'] == 'design-evaluation-cache/1' and context.identity['python'] == 'python3'
    assert context.identity['threads'] == 1
    assert context.key == jsjson.sha256_hex({'request': REQUEST, 'identity': context.identity})
    assert jsjson.parse(jsjson.stringify(context.admission))['schema_version'] == 'native-external-exposure/1'


def test_symlink_leaving_the_root_is_refused(tmp_path):
    root = Path(design_root(tmp_path, broken='escape'))
    with pytest.raises(IdentityError, match='^输入文件超出本项目$'):
        Service(str(root)).context(REQUEST)


def test_missing_inputs_raise_file_not_found(tmp_path):
    for broken in ('no_pointer', 'no_source'):
        root = design_root(tmp_path / broken, broken=broken)
        with pytest.raises(FileNotFoundError):
            Service(root).context(REQUEST)


def test_a_file_that_changes_while_it_is_hashed_is_refused(tmp_path, monkeypatch):
    # local-input-integrity.mjs:16: the stamp is taken again after reading, so bytes of a file rewritten during
    # the read (a concurrent publish) never enter a key or the memo.
    root = design_root(tmp_path)
    inputs = InputIntegrity(root)
    target = nodefs.realpath(f'{root}/data/sources.npz')
    real_stat, calls = nodefs.stat, []

    def stat(path):
        info = real_stat(path)
        if path != target:
            return info
        calls.append(path)
        if len(calls) != 2:
            return info
        return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino, st_size=info.st_size,
                               st_mtime_ns=info.st_mtime_ns + 1, st_ctime_ns=info.st_ctime_ns)

    monkeypatch.setattr(nodefs, 'stat', stat)
    with pytest.raises(IdentityError, match='^输入文件正在变化$'):
        inputs.digest('data/sources.npz')
    assert len(calls) == 2 and inputs._memo == {}
    assert inputs.digest('data/sources.npz') == digest('sources')
    assert list(inputs._memo) == [target]


def test_runtime_rows_name_files_as_node_lists_them(tmp_path, monkeypatch):
    # Node's readdir decodes a name that is not UTF-8 with U+FFFD (that row then fails with ENOENT); os.listdir
    # of a str would keep it as a surrogate escape that opens the file. macOS cannot create such a name, so the
    # listing is replaced; tests/service/test_key_parity.py runs the real file on Linux (the bad-utf8 root).
    root = design_root(tmp_path, runtime='simnibs')
    conda = f'{root}/.runtime/simnibs-4.6.0/conda-meta'
    real_listdir = os.listdir

    def listdir(path):
        names = real_listdir(path)
        if path == os.fsencode(conda):
            return [*names, b'\xff.json']
        return [*names, '\udcff.json'] if path == conda else names

    class Recorder:
        def digest_all(self, files):
            self.files = files
            raise LookupError('recorded')

    monkeypatch.setattr(os, 'listdir', listdir)
    recorder = Recorder()
    with pytest.raises(LookupError):
        design_context(root, f'{root}/.runtime/simnibs-4.6.0/bin/python', recorder, REQUEST)
    rows = [path for path in recorder.files if path.startswith('.runtime/simnibs-4.6.0/conda-meta/')]
    assert '.runtime/simnibs-4.6.0/conda-meta/\ufffd.json' in rows
    assert not any('\udcff' in path for path in rows)
