"""Installed environment identity rows (design 0002, change 3; phase 3, slice 3).

Tests both in process (via ``prefix`` and ``package_file`` parameters) and in subprocesses running the installed
package from ``installed_support.fake_prefix``:

- checkout identities and keys remain byte-identical even while a fake prefix exists;
- ``InputIntegrity`` refuses ``environment:`` rows without an ``environment`` base, resolves only ``environment:``
  rows against the real path of P when given, and refuses links leaving P;
- ``_environment_rows`` emits ``environment:bin/python``, ``environment:conda-meta/<name>.json`` for the numerical
  closure only (U16, sorted with ``nodepath.js_sort``), and ``METADATA`` / ``llvmlite`` ``PKG-INFO`` under the
  running interpreter's ``lib/pythonX.Y/site-packages``;
- environment rows enter D only when in the installed form and ``python`` is ``<real P>/bin/python`` (not with
  ``EEG_COMPUTE_PYTHON``, an explicit interpreter, a managed runtime, or another R), and are present on darwin
  even though ``runtime`` fingerprint is ``None``;
- changing ``numpy`` ``METADATA`` or a closure ``conda-meta`` record changes D, E, V2 and St keys, while changing
  or adding records outside the closure (``eeglayoutlab``'s own record or service-only packages) leaves all four
  keys unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys

import pytest

from eeglayoutlab.jobs import nodefs, nodepath
from eeglayoutlab.jobs.identity import IdentityError, _environment_rows, design_context
from eeglayoutlab.jobs.integrity import InputIntegrity
from eeglayoutlab.jobs.runtime import installed_environment, runtime_config
from eeglayoutlab.schemas import jsjson

from .installed_support import (
    CLOSURE_RECORDS, DIST_INFO, EGG_INFO, OTHER_RECORDS, PYTHON_VERSION, SITE, VERSION,
    environment, fake_prefix, record_name,
)
from .key_parity_support import design_root, digest

DESIGN = {
    'schema': 'eeg-electrode-design/1',
    'coordinate_system': 'ernie_native_mm',
    'unit': 'mm',
    'name': 'installed-test',
    'xyz_mm': [[(i % 8) * 6, (i // 8) * 6, 0] for i in range(64)],
    'region_indices': [int(i >= 32) for i in range(64)],
}
REQUEST = {'action': 'evaluate', 'design': DESIGN, 'radius_mm': 6, 'seed': 42}


def _seed_scientific_pointers(target_root: Path, scratch: Path) -> None:
    """Copies synthetic forward/bank/table pointers from ``design_root`` into an installed root R without touching
    the real ``src/compact_eeg`` and ``scripts`` files copied by ``fake_prefix``."""
    synthetic = Path(design_root(scratch / 'synthetic', table=True))
    for rel in (
        'results/v2/current_multiregion_bank.json',
        'results/v2/current_surface_admissibility.json',
        'results/v2/current_scalp_node_table.json',
        'results/v2/bank',
        'results/v2/scalp_node_table',
        'data/admission.npz',
        'data/candidates.npz',
        'data/report.json',
        'data/head.msh',
        'data/sources.npz',
        'data/scalp',
        'configs/ernie_fem_point_pilot.json',
    ):
        src = synthetic / rel
        dst = target_root / rel
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)


def _expected_environment_rows(version: str = PYTHON_VERSION) -> list[str]:
    site = f'lib/python{version}/site-packages'
    closure_files = nodepath.js_sort(record_name(name, ver, build) for name, ver, build, _ in CLOSURE_RECORDS)
    dist_rows = [
        f'environment:{site}/{name}-{ver}.dist-info/METADATA'
        for name, ver in sorted(DIST_INFO, key=lambda item: item[0])
    ]
    egg_rows = [
        f'environment:{site}/{name}-{ver}-py{version}.egg-info/PKG-INFO'
        for name, ver in EGG_INFO
    ]
    return ['environment:bin/python', *(f'environment:conda-meta/{f}' for f in closure_files), *dist_rows, *egg_rows]


def test_environment_rows_order_closure_filter_and_interpreter_version(tmp_path):
    prefix = fake_prefix(tmp_path / 'P', public=())
    rows = _environment_rows(str(prefix.path))
    assert rows == _expected_environment_rows()
    # None of OTHER_RECORDS (eeglayoutlab, matplotlib-base, fastapi-core, starlette, uvicorn, h11) or history enters.
    for name, ver, build, _ in OTHER_RECORDS:
        assert f'environment:conda-meta/{record_name(name, ver, build)}' not in rows
    assert 'environment:conda-meta/history' not in rows
    assert f'environment:{SITE}/compact_eeg-{VERSION}.dist-info/METADATA' not in rows

    # Site-packages path follows the running interpreter's X.Y version, not a literal python3.11.
    alt_site = prefix.path / 'lib/python3.13/site-packages'
    shutil.copytree(prefix.site, alt_site)
    shutil.move(alt_site / 'llvmlite-0.46.0-py3.11.egg-info', alt_site / 'llvmlite-0.46.0-py3.13.egg-info')
    rows_313 = _environment_rows(str(prefix.path), python_version='3.13')
    assert rows_313 == _expected_environment_rows('3.13')


def test_checkout_identity_and_integrity_are_unchanged_while_a_fake_prefix_exists(tmp_path):
    root = design_root(tmp_path / 'checkout', table=True)
    # Capture checkout identity & key before any fake prefix exists.
    cfg_before = runtime_config(root, env={})
    ctx_before = design_context(cfg_before.repository_root, cfg_before.native_python,
                                InputIntegrity(cfg_before.repository_root), REQUEST)
    text_before = jsjson.stringify(ctx_before.identity)

    prefix = fake_prefix(tmp_path / 'P')
    # Even when passing prefix=P, a package inside a checkout produces no environment base and byte-identical D.
    assert installed_environment(root, prefix=str(prefix.path)) is None
    assert installed_environment(str(prefix.root), prefix=str(prefix.path)) is None
    cfg_after = runtime_config(root, env={}, prefix=str(prefix.path))
    inputs_after = InputIntegrity(cfg_after.repository_root)
    ctx_after = design_context(cfg_after.repository_root, cfg_after.native_python, inputs_after, REQUEST,
                               prefix=str(prefix.path))
    assert jsjson.stringify(ctx_after.identity) == text_before
    assert ctx_after.key == ctx_before.key
    assert not any(key.startswith('environment:') for key in ctx_after.identity['digests'])

    # Without an environment base, InputIntegrity refuses any environment: row.
    with pytest.raises(IdentityError, match='^输入文件超出本项目$'):
        inputs_after.digest('environment:bin/python')


def test_installed_integrity_containment_and_override_precedence(tmp_path):
    prefix = fake_prefix(tmp_path / 'real/P')
    _seed_scientific_pointers(prefix.root, tmp_path)
    pkg = str(prefix.site / 'eeglayoutlab/jobs/runtime.py')
    where = {'prefix': str(prefix.path), 'package_file': pkg}

    env_base = installed_environment(str(prefix.root), **where)
    assert env_base == os.path.realpath(prefix.path)
    cfg = runtime_config(str(prefix.root), env={}, **where)
    inputs = InputIntegrity(cfg.repository_root, env_base)
    ctx = design_context(cfg.repository_root, cfg.native_python, inputs, REQUEST, **where)

    env_rows = [k for k in ctx.identity['digests'] if k.startswith('environment:')]
    assert env_rows == _expected_environment_rows()
    if sys.platform == 'darwin':
        assert 'runtime' not in ctx.identity

    # Through a linked prefix spelling, keys and rows match the real prefix identically.
    (tmp_path / 'linked-P').symlink_to(prefix.path)
    linked_where = {
        'prefix': str(tmp_path / 'linked-P'),
        'package_file': str(tmp_path / 'linked-P' / SITE / 'eeglayoutlab/jobs/runtime.py'),
    }
    linked_cfg = runtime_config(str(tmp_path / 'linked-P/share/eeglayoutlab/root'), env={}, **linked_where)
    linked_inputs = InputIntegrity(linked_cfg.repository_root,
                                   installed_environment(linked_cfg.repository_root, **linked_where))
    linked_ctx = design_context(linked_cfg.repository_root, linked_cfg.native_python, linked_inputs, REQUEST,
                                **linked_where)
    assert linked_ctx.key == ctx.key

    # EEG_COMPUTE_PYTHON or explicit python: no environment rows.
    for override_cfg in (
        runtime_config(str(prefix.root), env={'EEG_COMPUTE_PYTHON': '/custom/python'}, **where),
        runtime_config(str(prefix.root), python='/explicit/python', env={}, **where),
    ):
        override_ctx = design_context(override_cfg.repository_root, override_cfg.native_python, inputs, REQUEST,
                                      **where)
        assert not any(k.startswith('environment:') for k in override_ctx.identity['digests'])

    # Another root (--root /other): installed_environment is None and no environment rows enter.
    other_root = design_root(tmp_path / 'other', table=True)
    assert installed_environment(other_root, **where) is None
    other_cfg = runtime_config(other_root, env={}, **where)
    other_ctx = design_context(other_cfg.repository_root, other_cfg.native_python,
                               InputIntegrity(other_cfg.repository_root), REQUEST, **where)
    assert not any(k.startswith('environment:') for k in other_ctx.identity['digests'])

    # Non-prefixed rows still cannot escape R into P, and environment: rows cannot escape P via '..' or symlink.
    with pytest.raises(IdentityError, match='^输入文件超出本项目$'):
        inputs.digest('../../../conda-meta/history')
    (tmp_path / 'real/outside').write_text('outside\n', encoding='utf-8')
    with pytest.raises(IdentityError, match='^输入文件超出本项目$'):
        inputs.digest('environment:../outside')

    outside = tmp_path / 'outside-metadata'
    outside.write_text('outside\n', encoding='utf-8')
    numpy_meta = prefix.site / 'numpy-2.3.0.dist-info/METADATA'
    backup = numpy_meta.read_text(encoding='utf-8')
    numpy_meta.unlink()
    numpy_meta.symlink_to(outside)
    try:
        fresh_inputs = InputIntegrity(cfg.repository_root, env_base)
        with pytest.raises(IdentityError, match='^输入文件超出本项目$'):
            design_context(cfg.repository_root, cfg.native_python, fresh_inputs, REQUEST, **where)
    finally:
        numpy_meta.unlink()
        numpy_meta.write_text(backup, encoding='utf-8')


SUBPROCESS_KEYS_PROBE = """
import asyncio, os, sys
from pathlib import Path
from eeglayoutlab.jobs import runtime
from eeglayoutlab.jobs.design import DesignJobs
from eeglayoutlab.jobs.editor import EditorJobs
from eeglayoutlab.jobs.reception import ReceptionJobs
from eeglayoutlab.jobs.kinds import community_adapters
from eeglayoutlab.jobs.library import Library
from eeglayoutlab.jobs.queue import WorkspaceQueue
from eeglayoutlab.jobs.radius import RadiusJobs
from eeglayoutlab.jobs.slot import ExecutionSlot, InstallationLock
from eeglayoutlab.server.workspace_studies import RobustnessStudyService, StudyStore
from eeglayoutlab.schemas import jsjson

workspace = Path(sys.argv[1])
workspace.mkdir(parents=True, exist_ok=True)
root = runtime.repository_root()
cfg = runtime.runtime_config(root)

design_req = {
    'action': 'evaluate',
    'design': {
        'schema': 'eeg-electrode-design/1',
        'coordinate_system': 'ernie_native_mm',
        'unit': 'mm',
        'name': 'probe',
        'xyz_mm': [[(i % 8) * 6, (i // 8) * 6, 0] for i in range(64)],
        'region_indices': [int(i >= 32) for i in range(64)],
    },
    'radius_mm': 6,
    'seed': 42,
}

parent_id = 'b' * 64
parent_record = {
    'id': parent_id,
    'dataset_id': 'cache',
    'compatible': True,
    'status': 'completed',
    'request': {'region_count': 2, 'radius_mm': 35, 'mode': 'whole_surface'},
    'layout': {
        'xyzMm': [[(i % 8) * 6.0, (i // 8) * 6.0, 0.0] for i in range(64)],
        'regionIndices': [int(i >= 32) for i in range(64)],
        'referenceXyzMm': [[(i % 8) * 7.0, (i // 8) * 7.0, 1.0] for i in range(64)],
        'regionPatchVertexIndices': [[0, 1], [2, 3]],
    },
    'provenance': {
        'geometry_sha256': sys.argv[2],
        'surface_admissibility_sha256': sys.argv[3],
    },
}

class FakeLib:
    def get(self, rec_id):
        return parent_record if rec_id == parent_id else None

async def run():
    slot = ExecutionSlot(InstallationLock(root, str(workspace / 'exec.lock')))
    radius = RadiusJobs(root, cfg.python, execution_slot=slot)
    design = DesignJobs(root, cfg.native_python, execution_slot=slot, store=radius.store)
    editor = EditorJobs(root, cfg.native_python, FakeLib(), execution_slot=slot, store=radius.store)
    async def fake_runtime(_py, _rt):
        return {'schema': 'reception-runtime-digest/1', 'sha256': 'c' * 64}
    reception = ReceptionJobs(root, cfg.native_python, FakeLib(), compute_python=cfg.python,
                              execution_slot=slot, store=radius.store, runtime=fake_runtime)

    d_ctx = await design.context(design_req)
    e_ctx = await editor.context({'action': 'prepare', 'parent_id': parent_id})
    v2_ctx = await reception.context({
        'record_id': parent_id, 'mode': 'single_source', 'source_index': 0,
        'waveform': 'burst', 'artifact_scale': 1, 'seed': 7,
    })

    queue = WorkspaceQueue(str(workspace / '.eeglayoutlab'),
                           community_adapters(radius, design, editor, reception),
                           slot=slot, cache_only=True)
    await queue.start()
    study_service = RobustnessStudyService(queue, root, store=StudyStore(str(workspace / 'studies')))
    created = await study_service.create({
        'protocol': 'noise_seeds',
        'title': 'Installed identity check',
        'design': design_req['design'],
        'cases': [{'seed': 42, 'radius_mm': 6}],
    })
    # Bind case identity via design adapter prepare (as study start binds identities).
    st_prepared = await queue.adapters['design-evaluation'].prepare(created['study']['cases'][0]['request'])
    await study_service.aclose()
    await reception.aclose()
    await queue.close()

    rad_identity, rad_key = radius.identity_for({'region_count': 2, 'radius_mm': 35, 'mode': 'whole_surface'})
    return {
        'd_key': d_ctx['key'],
        'e_key': e_ctx['key'],
        'v2_key': v2_ctx['key'],
        'st_key': st_prepared['key'],
        'rad_key': rad_key,
        'env_rows': [k for k in d_ctx['identity']['digests'] if k.startswith('environment:')],
        'e_has_env': any(k.startswith('environment:') for k in e_ctx['identity']['digests']),
        'v2_has_env': any(k.startswith('environment:') for k in v2_ctx['identity']['forward']['digests']),
    }

print(jsjson.stringify(asyncio.run(run())))
"""


def test_installed_d_e_v2_and_st_keys_track_numerical_closure_only(tmp_path):
    pytest.importorskip('pydantic')
    prefix = fake_prefix(tmp_path / 'P')
    _seed_scientific_pointers(prefix.root, tmp_path)
    geom_sha = digest('candidates')
    adm_sha = digest('mask')

    def probe(tag: str) -> dict:
        res = prefix.run(SUBPROCESS_KEYS_PROBE, str(tmp_path / f'ws-{tag}'), geom_sha, adm_sha)
        assert res.returncode == 0, res.stderr
        return jsjson.parse(res.stdout)

    base = probe('base')
    assert base['env_rows'] == _expected_environment_rows()
    assert base['e_has_env'] is True and base['v2_has_env'] is True

    # 1. Changing eeglayoutlab's own conda-meta record or adding an unrelated package does NOT change any key.
    own_rec = prefix.conda_meta / record_name('eeglayoutlab', VERSION, 'pyh4616a5c_0')
    own_rec.write_text(own_rec.read_text(encoding='utf-8').replace('"build_number": 0', '"build_number": 9'),
                       encoding='utf-8')
    (prefix.conda_meta / 'rich-13.9.0-pyhd8ed1ab_0.json').write_text(
        '{"name": "rich", "version": "13.9.0", "build": "pyhd8ed1ab_0", "depends": ["python >=3.11"]}\n',
        encoding='utf-8',
    )
    after_unrelated = probe('unrelated')
    for k in ('d_key', 'e_key', 'v2_key', 'st_key', 'rad_key'):
        assert after_unrelated[k] == base[k], k

    # 2. Changing numpy METADATA changes D, E, V2 and St keys, while Rad stays unchanged.
    numpy_meta = prefix.site / 'numpy-2.3.0.dist-info/METADATA'
    numpy_meta.write_text(numpy_meta.read_text(encoding='utf-8') + 'X-Test: modified\n', encoding='utf-8')
    after_numpy = probe('numpy')
    for k in ('d_key', 'e_key', 'v2_key', 'st_key'):
        assert after_numpy[k] != base[k], k
    assert after_numpy['rad_key'] == base['rad_key']

    # 3. Changing a closure conda-meta record (libopenblas, reached transitively through numpy -> libblas) also
    # changes D, E, V2 and St keys.
    openblas_rec = prefix.conda_meta / record_name('libopenblas', '0.3.34', 'openmp_h5e6e99c_1')
    openblas_rec.write_text(openblas_rec.read_text(encoding='utf-8').replace('"build_number": 1', '"build_number": 2'),
                            encoding='utf-8')
    after_closure = probe('closure')
    for k in ('d_key', 'e_key', 'v2_key', 'st_key'):
        assert after_closure[k] != after_numpy[k], k
    assert after_closure['rad_key'] == base['rad_key']
