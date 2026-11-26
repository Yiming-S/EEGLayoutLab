"""Byte-parity tests for ``evaluate``, ``search`` and ``study`` against ``webapp/scripts/eeglayoutlab.mjs``
(phase 3 slice 6; U8, U10, U11).
"""
from __future__ import annotations

from pathlib import Path
import sys
from unittest import mock

import pytest

from schema_parity_support import require

require('pydantic')

from eeglayoutlab.cli import run as cli_run  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402
from service.key_parity_support import HEADS, PRIOR, SCENARIOS, SPATIAL, design_root, radius_root  # noqa: E402

from .cli_support import (  # noqa: E402
    ROOT, needs_node, run_node_cli, run_python_cli_inproc, tree_bytes,
)

FAKE_WORKER = ROOT / 'tests/cli/fake_worker.py'


def _make_fake_python(tmp_path: Path, name: str = 'fake-python') -> Path:
    wrapper = tmp_path / name
    wrapper.write_text(
        f'#!/bin/sh\n'
        f'# drop -u ($1), pass target worker script ($2) to fake_worker.py\n'
        f'shift\n'
        f'exec "{sys.executable}" -u "{FAKE_WORKER}" "$@"\n',
        encoding='utf-8',
    )
    wrapper.chmod(0o755)
    return wrapper


def _design_payload(named: bool = False) -> dict:
    grid = [[(i % 8) * 6.0, (i // 8) * 6.0, 20.0] for i in range(64)]
    out = {
        'schema': 'eeg-electrode-design/1',
        'coordinate_system': 'ernie_native_mm',
        'unit': 'mm',
        'name': 'grid-test',
        'xyz_mm': grid,
        'region_indices': [int(i >= 32) for i in range(64)],
    }
    if named:
        out['electrode_names'] = [f'Ch{i + 1}' for i in range(64)]
        out['source_metadata'] = {
            'schema': 'electrode-coordinate-source/1',
            'format': 'bids-electrodes/1',
            'electrodes_file': 'electrodes.tsv',
            'coordsystem_file': 'coordsystem.json',
            'coordinate_system': 'ernie_native_mm',
            'unit': 'mm',
            'coordinate_system_description': 'Ernie native frame in mm.',
            'region_index_base': 0,
            'region_description': 'Two regions.',
        }
    return out


def _prior_document() -> dict:
    return {
        'schema': 'eeg-data-prior/1',
        'id': 'prior-test-01',
        'regions': ['frontal', 'central', 'parietal', 'occipital', 'temporal_left', 'temporal_right', 'other'],
        'channels': [f'Ch{i + 1}' for i in range(64)],
        'fit': {'summaries': 3},
        'request': PRIOR,
    }


def _assert_cli_parity(
    args_factory,
    tmp_path: Path,
    capsys,
    *,
    mode: str = 'ok',
    expected_code: int = 0,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, bytes], dict[str, bytes]]:
    py_out = tmp_path / f'py-{mode}-{expected_code}'
    node_out = tmp_path / f'node-{mode}-{expected_code}'
    monkeypatch.setenv('EEG_FAKE_WORKER_MODE', mode)

    py_code, py_stdout, _ = run_python_cli_inproc(args_factory(py_out), capsys)
    node_res = run_node_cli(args_factory(node_out), env={'EEG_FAKE_WORKER_MODE': mode})

    assert py_code == expected_code and node_res.returncode == expected_code, (py_code, node_res.returncode, node_res.stderr)
    assert py_stdout == node_res.stdout
    py_files = tree_bytes(py_out)
    node_files = tree_bytes(node_out)
    assert py_files == node_files
    return py_files, node_files


@needs_node
def test_evaluate_byte_parity_across_options_envelopes_priors_and_failures(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = design_root(tmp_path / 'root', table=True, scenarios=SCENARIOS, heads=HEADS)
    fake_py = _make_fake_python(tmp_path)

    bare_design = tmp_path / 'bare-design.json'
    bare_design.write_text(jsjson.stringify(_design_payload(named=False)), encoding='utf-8')

    named_design = tmp_path / 'named-design.json'
    named_design.write_text(jsjson.stringify(_design_payload(named=True)), encoding='utf-8')

    prior_path = tmp_path / 'prior.json'
    prior_path.write_text(jsjson.stringify(_prior_document()), encoding='utf-8')

    # 1. --design with electrode_names + source_metadata + robustness + spatial noise / conductivity / head / data-prior
    for tag, extra in (
        ('named-robust', ['--design', str(named_design), '--radius', '6', '--seed', '42', '--robustness', 'standard/1']),
        ('perturb-spatial', ['--design', str(bare_design), '--action', 'perturb', '--radius', '10', '--seed', '7', '--noise', 'spatial_20']),
        ('scenario', ['--design', str(bare_design), '--conductivity', 'skull_x2']),
        ('head', ['--design', str(bare_design), '--head', 'ixi002']),
        ('prior', ['--design', str(named_design), '--data-prior', str(prior_path)]),
    ):
        _assert_cli_parity(
            lambda out, ex=extra: ['evaluate', *ex, '--root', root, '--python', str(fake_py), '--out-dir', str(out)],
            tmp_path / tag,
            capsys,
            monkeypatch=monkeypatch,
        )

    # 2. Failure modes: error event, stderr-only, silent exit, invalid result -> writes request.error.json & exits 1
    for mode in ('error_event', 'stderr_only', 'silent_exit', 'invalid_result'):
        _assert_cli_parity(
            lambda out: [
                'evaluate', '--design', str(bare_design), '--root', root,
                '--python', str(fake_py), '--out-dir', str(out),
            ],
            tmp_path / f'fail-{mode}',
            capsys,
            mode=mode,
            expected_code=1,
            monkeypatch=monkeypatch,
        )

    # 3. Input mutated during worker run -> 'inputs or code changed during the calculation' in both CLIs
    root_py = design_root(tmp_path / 'mut-py', table=True)
    root_node = design_root(tmp_path / 'mut-node', table=True)
    monkeypatch.setenv('EEG_FAKE_WORKER_MODE', 'mutate_input_during_run')
    py_mut_out, node_mut_out = tmp_path / 'mut-py-out', tmp_path / 'mut-node-out'
    p_code, _, _ = run_python_cli_inproc(
        ['evaluate', '--design', str(bare_design), '--root', root_py, '--python', str(fake_py), '--out-dir', str(py_mut_out)],
        capsys,
    )
    n_res = run_node_cli(
        ['evaluate', '--design', str(bare_design), '--root', root_node, '--python', str(fake_py), '--out-dir', str(node_mut_out)],
        env={'EEG_FAKE_WORKER_MODE': 'mutate_input_during_run'},
    )
    assert p_code == 1 and n_res.returncode == 1
    assert tree_bytes(py_mut_out) == tree_bytes(node_mut_out)
    assert b'inputs or code changed during the calculation' in tree_bytes(py_mut_out)['request.error.json']

    # Verify zero service queue/workspace/job records were written under root!
    assert not (Path(root) / 'results/v2/design_evaluation_jobs').exists()
    assert not (Path(root) / 'results/web-service').exists()


@needs_node
def test_search_byte_parity_and_off_darwin_runtime_member(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = radius_root(tmp_path / 'rad-root', table=True)
    fake_py = _make_fake_python(tmp_path)

    req1 = tmp_path / 'whole.json'
    req1.write_text(jsjson.stringify({'region_count': 2, 'radius_mm': 30, 'mode': 'whole_surface'}), encoding='utf-8')

    req2 = tmp_path / 'spatial.json'
    req2.write_text(
        jsjson.stringify({'region_count': 3, 'radius_mm': 25, 'mode': 'low_hair', 'noise_model': SPATIAL}),
        encoding='utf-8',
    )

    prior_path = tmp_path / 'prior.json'
    prior_path.write_text(jsjson.stringify(_prior_document()), encoding='utf-8')

    # Batch search + data prior + no_layout + code-digest mismatch
    _assert_cli_parity(
        lambda out: ['search', str(req1), str(req2), '--root', root, '--python', str(fake_py), '--out-dir', str(out)],
        tmp_path / 'batch',
        capsys,
        monkeypatch=monkeypatch,
    )
    _assert_cli_parity(
        lambda out: [
            'search', str(req1), '--data-prior', str(prior_path),
            '--root', root, '--python', str(fake_py), '--out-dir', str(out),
        ],
        tmp_path / 'prior',
        capsys,
        monkeypatch=monkeypatch,
    )
    _assert_cli_parity(
        lambda out: ['search', str(req1), '--root', root, '--python', str(fake_py), '--out-dir', str(out)],
        tmp_path / 'no-layout',
        capsys,
        mode='no_layout',
        monkeypatch=monkeypatch,
    )
    files_bad, _ = _assert_cli_parity(
        lambda out: ['search', str(req1), '--root', root, '--python', str(fake_py), '--out-dir', str(out)],
        tmp_path / 'bad-digest',
        capsys,
        mode='bad_code_digest',
        expected_code=1,
        monkeypatch=monkeypatch,
    )
    assert b'scientific code changed during the search' in files_bad['whole.error.json']
    assert not (Path(root) / 'results/v2/local_app_jobs').exists()

    # Off-darwin runtime member check (Slice 6 unit check with injected runtime_identity)
    monkeypatch.setenv('EEG_FAKE_WORKER_MODE', 'ok')
    fake_runtime = {'platform': 'linux', 'arch': 'x64', 'python_sha256': 'a' * 64}
    env = cli_run.build_environment('search', {'root': root, 'python': str(fake_py)})
    with mock.patch.object(cli_run, 'runtime_identity', return_value=fake_runtime):
        run_rec = cli_run.search_one(env, {'region_count': 2, 'radius_mm': 30, 'mode': 'whole_surface'})
    assert run_rec['identity']['runtime'] == fake_runtime


@needs_node
def test_study_byte_parity_across_noise_seeds_displacements_heads_and_partial_failure(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = design_root(tmp_path / 'study-root', table=True, heads=HEADS)
    fake_py = _make_fake_python(tmp_path)
    design = _design_payload(named=True)

    seeds_study = tmp_path / 'seeds.json'
    seeds_study.write_text(
        jsjson.stringify({
            'protocol': 'noise_seeds',
            'title': 'Three noise seeds',
            'design': design,
            'cases': [{'seed': 41, 'radius_mm': 6}, {'seed': 42, 'radius_mm': 6}, {'seed': 43, 'radius_mm': 6}],
        }),
        encoding='utf-8',
    )

    disp_study = tmp_path / 'disp.json'
    disp_study.write_text(
        jsjson.stringify({
            'protocol': 'grid_displacements',
            'title': 'Grid displacements',
            'design': design,
            'cases': [{'seed': 10, 'radius_mm': 3}, {'seed': 11, 'radius_mm': 6}],
        }),
        encoding='utf-8',
    )

    heads_study = tmp_path / 'heads.json'
    heads_study.write_text(
        jsjson.stringify({
            'protocol': 'heads',
            'title': 'Cross-head study',
            'design': design,
            'cases': [{'head_id': HEADS[0], 'seed': 42, 'radius_mm': 6}, {'head_id': HEADS[1], 'seed': 42, 'radius_mm': 6}],
        }),
        encoding='utf-8',
    )

    for tag, path in (('seeds', seeds_study), ('disp', disp_study), ('heads', heads_study)):
        _assert_cli_parity(
            lambda out, p=path: ['study', str(p), '--root', root, '--python', str(fake_py), '--out-dir', str(out)],
            tmp_path / tag,
            capsys,
            monkeypatch=monkeypatch,
        )

    # Partial failure (seed 43 fails -> exit code 1, cases/01 and cases/02 written, study.json records failed_cases=1)
    py_files, _ = _assert_cli_parity(
        lambda out: ['study', str(seeds_study), '--root', root, '--python', str(fake_py), '--out-dir', str(out)],
        tmp_path / 'partial-fail',
        capsys,
        mode='fail_case_seed_43',
        expected_code=1,
        monkeypatch=monkeypatch,
    )
    assert sorted(py_files) == ['cases/01.result.json', 'cases/02.result.json', 'study.json']
    parsed = jsjson.parse(py_files['study.json'].decode('utf-8'))
    assert parsed['aggregation']['completed_cases'] == 2 and parsed['aggregation']['failed_cases'] == 1
