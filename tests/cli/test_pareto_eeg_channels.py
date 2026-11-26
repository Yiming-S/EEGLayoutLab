"""Byte-parity tests for Phase 3 Slices 11 & 12: ``pareto``, ``eeg-summary``, ``prior`` and ``channels``."""
from __future__ import annotations

import json
import math
from pathlib import Path
import stat
import sys
from typing import Any

import pytest

from eeglayoutlab.core.channel_subset import channel_subsets, generator
from eeglayoutlab.core.pareto import (
    comparison_group, dominates, pareto_analysis, pareto_ranks,
    robustness_summary_from_block, summary_objectives,
)
from eeglayoutlab.figures.channel_subset import channel_subset_figure_svg
from eeglayoutlab.schemas import jsjson

from .cli_support import (
    ROOT, needs_node, run_node_cli, run_node_driver,
    run_python_cli_inproc, run_python_cli_subprocess, tree_bytes,
)

DRIVER = Path(__file__).resolve().parent / 'parity/channels_pareto.mjs'
FAKE_WORKER = Path(__file__).resolve().parent / 'fake_worker.py'

NAMES_16 = [
    'Fp1', 'Fp2', 'F7', 'F3', 'Fz', 'F4', 'F8',
    'T7', 'C3', 'Cz', 'C4', 'T8', 'P3', 'Pz', 'P4', 'O1',
]


def _make_fake_python(tmp_path: Path) -> Path:
    wrapper = tmp_path / 'fake-python'
    wrapper.write_text(
        f'#!/bin/sh\nif [ "$1" = "-u" ]; then shift; fi\nexec "{sys.executable}" "{FAKE_WORKER}" "$@"\n',
        encoding='utf-8',
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return wrapper


def _synthetic_cli_root(root: Path) -> Path:
    (root / 'configs').mkdir(parents=True, exist_ok=True)
    (root / 'src/compact_eeg').mkdir(parents=True, exist_ok=True)
    (root / 'scripts').mkdir(parents=True, exist_ok=True)
    (root / 'scripts/eeg_data.py').write_text('# stub worker path\n', encoding='utf-8')
    return root


def _spd_covariance(seed: int, n: int = len(NAMES_16), factors: int = 4) -> list[list[float]]:
    rng = generator(seed)

    def normal() -> float:
        return math.sqrt(-2.0 * math.log(1.0 - rng())) * math.cos(2.0 * math.pi * rng())

    f_mat = [[normal() for _ in range(factors)] for _ in range(n)]
    out: list[list[float]] = []
    for i in range(n):
        row: list[float] = []
        for j in range(n):
            s = 0.0
            for k in range(factors):
                s += f_mat[i][k] * f_mat[j][k]
            if i == j:
                s += 0.05 + 0.1 * rng()
            row.append(s)
        out.append(row)
    return out


def _summary(
    label: str,
    cov: list[list[float]],
    names: list[str] = NAMES_16,
    band: list[int] | None = None,
    rec_sha: str | None = None,
) -> dict[str, Any]:
    src: dict[str, Any] = {
        'file': f'{label}.edf',
        'sha256': label.encode('utf-8').hex().ljust(64, '0')[:64],
    }
    if rec_sha is not None:
        src['recording_sha256'] = rec_sha
    return {
        'schema': 'eeg-covariance-summary/1',
        'label': label,
        'channels': list(names),
        'covariance': cov,
        'processing': {'band_hz': band or [1, 40]},
        'source': src,
    }


def _svg_text_for(report: dict[str, Any]) -> dict[str, Any]:
    held_out = len(report['test']) > 0
    standard = report['standard_10_20']
    b0 = jsjson.number_to_string(float(report['band_hz'][0]))
    b1 = jsjson.number_to_string(float(report['band_hz'][1]))
    return {
        'title': 'Reconstruction error of channel subsets',
        'subtitle': ' · '.join([
            'Mean held-out error' if held_out else 'Training error',
            f"{len(report['universe'])} shared channels",
            f'{b0}–{b1} Hz',
        ]),
        'xLabel': 'Channels in the subset',
        'yLabel': 'Unexplained variance (lower is better)',
        'names': {
            'data': 'Greedy on the data',
            'data_prior': 'Greedy on the data-prior model',
            'area_prior': 'Greedy on the area-prior model',
            'random': 'Random subsets, median and P10–P90',
            'standard': f"10-20 system ({standard['count']})" if standard else '',
        },
        'channels': lambda count: f'{count} channels',
        'caption': [
            'Error is the unexplained variance fraction of the average-referenced shared channels. '
            'Each subset is recorded against one of its own channels; the reconstructor is fitted on '
            'the training summaries.',
            (
                "Curves are the mean held-out error; the band is the P10–P90 of the random subsets' "
                'mean held-out error over draws. The data-greedy curve includes the size of the 10-20 subset.'
                if held_out
                else 'Without held-out summaries the curves are training errors, optimistic for greedy '
                "selection on the data; the band is the P10–P90 of the random subsets' training error."
            ),
        ],
    }


@needs_node
def test_mulberry32_pareto_and_channel_subsets_match_node_byte_for_byte(tmp_path: Path) -> None:
    train_a = _summary('s1', _spd_covariance(101))
    train_b = _summary('s2', _spd_covariance(102))
    train_partial = _summary('s3', [r[1:] for r in _spd_covariance(103)[1:]], NAMES_16[1:])
    held_a = _summary('h1', _spd_covariance(104))
    held_b = _summary('h2', _spd_covariance(105))
    held_skip = _summary('h3', [r[:-1] for r in _spd_covariance(106)[:-1]], NAMES_16[:-1])

    prior_doc = {
        'schema': 'eeg-data-prior/1',
        'id': '0123456789abcdef',
        'channels': NAMES_16[:15],
        'band_hz': [1, 40],
        'channel_model': {
            'data_prior': [r[:15] for r in _spd_covariance(201)[:15]],
            'area_prior': [r[:15] for r in _spd_covariance(202)[:15]],
        },
    }

    subset_cases = [
        # Training + held-out + prior + multiple counts
        {'options': {'training': [train_a, train_b], 'test': [held_a, held_b, held_skip], 'prior': prior_doc, 'counts': [4, 2, 8], 'draws': 60, 'seed': 7}},
        # Training only (no held-out, single count -> range line in SVG)
        {'options': {'training': [train_a, train_b], 'counts': [5], 'draws': 40, 'seed': 42}},
        # 90% channel presence with skipped training summary
        {'options': {'training': [_summary(f't{i}', _spd_covariance(300 + i)) for i in range(9)] + [train_partial], 'draws': 25, 'seed': 3}},
        # Invalid recording overlap error message
        {'options': {'training': [train_a], 'test': [train_a], 'counts': [3], 'draws': 10}},
        # Invalid band mismatch
        {'options': {'training': [train_a], 'test': [_summary('bad', _spd_covariance(9), NAMES_16, [8, 30])]}},
        # Invalid count out of range
        {'options': {'training': [train_a], 'counts': [16]}},
    ]

    pareto_items = [
        {'item': 'a', 'values': {'field': 0.9, 'sensitivity': 0.8, 'localization': 0.7, 'p90': 10.0}},
        {'item': 'b', 'values': {'field': 0.8, 'sensitivity': 0.85, 'localization': 0.75, 'p90': 8.5}},
        {'item': 'c', 'values': {'field': 0.7, 'sensitivity': 0.6, 'localization': 0.5, 'p90': 12.0}},
        {'item': 'd', 'values': {'field': 0.95, 'sensitivity': 0.9, 'localization': None, 'p90': None}},
        # Exact tie on rank + tie within 1e-13
        {'item': 'e', 'values': {'field': 0.9, 'sensitivity': 0.8 - 1e-13, 'localization': 0.7, 'p90': 10.0}},
    ]
    pareto_cases = [
        {'items': pareto_items, 'objectives': ['field', 'p90']},
        {'items': pareto_items, 'objectives': ['field', 'sensitivity', 'localization']},
        {'items': pareto_items, 'objectives': ['p90']},
        {'items': pareto_items, 'objectives': []},
        {'items': pareto_items, 'objectives': ['field', 'field']},
    ]

    group_cases = [
        {'dataset_id': 'offline_radius', 'status': 'completed', 'compatible': True, 'request': None},
        {'dataset_id': 'cache', 'status': 'completed', 'compatible': False, 'request': None},
        {'dataset_id': 'design_evaluation', 'status': 'completed', 'compatible': True, 'request': None},
        {'dataset_id': 'strict_area', 'status': 'completed', 'compatible': True, 'request': None, 'evaluation_condition': {'head_id': 'ixi002'}},
        {'dataset_id': 'cache', 'status': 'completed', 'compatible': True, 'request': {'data_prior': {'rho': 0.0, 'length_mm': None, 'region_gain': [1] * 7}}},
    ]

    rob_block = {
        'protocol': 'standard/1',
        'dropout': {'random': [{'removed': 4, 'candidate': {'median': 0.91}, 'reference': {'median': 0.95}}]},
        'impedance': [{'log_sd': 1, 'candidate': {'median': 0.89}, 'reference': {'median': 0.94}}],
        'replacement': {
            'status': 'completed',
            'levels': [{
                'rms_mm': 10,
                'candidate': {'fixed_estimator': {'median': 0.82}, 'redigitized': {'median': 0.88}},
                'reference': {'fixed_estimator': {'median': 0.90}, 'redigitized': {'median': 0.93}},
            }],
        },
    }
    summary_obj_cases = [
        {
            'metrics': {'field_relative': 0.9, 'sensitivity_tail': 0.8, 'localization_relative': 0.7, 'p90_mm': 11.2},
            'geometry': {'union_area_cm2': 32.5},
            'robustness': robustness_summary_from_block(rob_block),
        },
        {'metrics': {'field_relative': 0.85}, 'geometry': None},
    ]

    spec = {
        'prngSeeds': [0, 1, 42, 2147483647, 4294967295],
        'prngCount': 500,
        'paretoCases': pareto_cases,
        'groupCases': group_cases,
        'summaryObjCases': summary_obj_cases,
        'dominatesCases': [
            [[1.0, 1.0], [1.0, 1.0 - 1e-13], ['max', 'max']],
            [[1.0, 1.0], [1.0, 1.0 - 1e-11], ['max', 'max']],
            [[1.0, 8.0], [1.0, 10.0], ['max', 'min']],
        ],
        'rankCases': [
            [[[1, 1], [2, 0], [0, 2], [0.5, 0.5], [1, 1], [0, 0], [0.4, 0.4]], ['max', 'max']],
            [[[1, 10], [1, 5], [2, 5]], ['max', 'min']],
        ],
        'subsetCases': subset_cases,
    }
    node_out = run_node_driver(DRIVER, spec, tmp_path)

    for seed in spec['prngSeeds']:
        rng = generator(seed)
        py_draws = [rng() for _ in range(spec['prngCount'])]
        assert py_draws == node_out['prngDraws'][str(seed)]

    for idx, tc in enumerate(pareto_cases):
        expected = node_out['paretoResults'][idx]
        if expected['ok']:
            py_res = pareto_analysis(tc['items'], tc['objectives'])
            assert jsjson.stringify(py_res, indent=2) == expected['json']
        else:
            with pytest.raises(ValueError) as exc_info:
                pareto_analysis(tc['items'], tc['objectives'])
            assert str(exc_info.value) == expected['error']

    assert [comparison_group(r) for r in group_cases] == node_out['groupResults']
    assert [jsjson.stringify(summary_objectives(r)) for r in summary_obj_cases] == node_out['summaryObjResults']
    assert [dominates(a, b, d) for a, b, d in spec['dominatesCases']] == node_out['dominatesResults']
    assert [pareto_ranks(pts, d) for pts, d in spec['rankCases']] == node_out['rankResults']

    for idx, tc in enumerate(subset_cases):
        expected = node_out['subsetResults'][idx]
        opts = tc['options']
        if expected['ok']:
            py_rep = channel_subsets(
                training=opts['training'],
                test=opts.get('test'),
                prior=opts.get('prior'),
                counts=opts.get('counts'),
                draws=opts.get('draws'),
                seed=opts.get('seed'),
            )
            assert jsjson.stringify(py_rep, indent=2) == expected['json']
            py_svg = channel_subset_figure_svg(py_rep, _svg_text_for(py_rep))
            assert py_svg == expected['svg']
        else:
            with pytest.raises(ValueError) as exc_info:
                channel_subsets(
                    training=opts['training'],
                    test=opts.get('test'),
                    prior=opts.get('prior'),
                    counts=opts.get('counts'),
                    draws=opts.get('draws'),
                    seed=opts.get('seed'),
                )
            assert str(exc_info.value) == expected['error']


@needs_node
def test_the_pareto_command_ranks_result_files_of_one_condition(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ported CLI site from ``check-pareto.mjs``: written JSON, stdout TSV and exit codes match Node."""
    def design(name: str) -> dict[str, Any]:
        return {
            'schema': 'eeg-electrode-design/1',
            'coordinate_system': 'ernie_native_mm',
            'unit': 'mm',
            'name': name,
            'xyz_mm': [],
            'region_indices': [],
        }

    def evaluation(name: str, field: float, loc: float, **extra: Any) -> dict[str, Any]:
        return {
            'schema': 'eeglayoutlab-cli-run/1',
            'service': 'design-evaluation',
            'request': {'action': 'evaluate', 'design': design(name), 'radius_mm': 6, 'seed': 42, **extra},
            'result': {'nominal': {'field_relative': field, 'sensitivity_tail': 0.8, 'localization_relative': loc, 'p90_mm': 10}},
        }

    records = {
        'a': evaluation('a', 0.9, 0.5),
        'b': evaluation('b', 0.8, 0.7),
        'c': evaluation('c', 0.7, 0.4),
        'search': {
            'schema': 'eeglayoutlab-cli-run/1',
            'service': 'radius-search',
            'request': {'region_count': 2, 'radius_mm': 30, 'mode': 'whole_surface'},
            'result': {
                'status': 'completed',
                'metrics': {'field_relative': 0.95, 'sensitivity_tail': 0.5, 'localization_relative': 0.6, 'p90_mm': 9},
                'geometry': {'union_area_cm2': 40},
            },
        },
        'spatial': evaluation('s', 0.99, 0.99, noise_model={'kind': 'spatial', 'rho': 0.5, 'length_mm': 20}),
    }
    files: list[str] = []
    for name, val in records.items():
        p = tmp_path / f'{name}.json'
        p.write_text(json.dumps(val), encoding='utf-8')
        files.append(str(p))

    for objs in ('field,localization', 'field,area', None):
        node_out = tmp_path / f"node-{objs or 'default'}.json"
        py_out = tmp_path / f"py-{objs or 'default'}.json"
        extra = ['--objectives', objs] if objs else []
        n_res = run_node_cli(['pareto', *files[:4], *extra, '--out', str(node_out)])
        p_code, p_stdout, p_stderr = run_python_cli_inproc(['pareto', *files[:4], *extra, '--out', str(py_out)], capsys)
        assert n_res.returncode == p_code == 0, p_stderr
        assert p_stdout == n_res.stdout
        assert py_out.read_bytes() == node_out.read_bytes()

    # Refusal parity: mixed condition, unknown objective, single input file.
    for bad_args in (
        ['pareto', files[0], files[4], '--out', str(tmp_path / 'bad.json')],
        ['pareto', files[0], files[1], '--objectives', 'speed', '--out', str(tmp_path / 'bad.json')],
        ['pareto', files[0], '--out', str(tmp_path / 'bad.json')],
    ):
        n_bad = run_node_cli(bad_args)
        p_code, _, p_err = run_python_cli_inproc(bad_args, capsys)
        assert n_bad.returncode == p_code == 2
        assert p_err == n_bad.stderr


@needs_node
def test_the_channels_command_writes_the_report_from_summary_files_and_directories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ported CLI site from ``check-channel-subset.mjs``: report JSON, SVG, stdout table and refusals match Node."""
    held_dir = tmp_path / 'held'
    held_dir.mkdir()
    (tmp_path / 'a.json').write_text(json.dumps(_summary('a', _spd_covariance(11))), encoding='utf-8')
    (held_dir / 'b.json').write_text(json.dumps(_summary('b', _spd_covariance(12))), encoding='utf-8')
    (held_dir / 'notes.json').write_text(json.dumps({'schema': 'other'}), encoding='utf-8')

    node_out, node_fig = tmp_path / 'node/subset.json', tmp_path / 'node/figures/subset.svg'
    py_out, py_fig = tmp_path / 'py/subset.json', tmp_path / 'py/figures/subset.svg'

    n_res = run_node_cli([
        'channels', str(tmp_path / 'a.json'), '--test', str(held_dir),
        '--counts', '3,5', '--draws', '20', '--figure', str(node_fig), '--out', str(node_out),
    ])
    p_code, p_stdout, p_stderr = run_python_cli_inproc([
        'channels', str(tmp_path / 'a.json'), '--test', str(held_dir),
        '--counts', '3,5', '--draws', '20', '--figure', str(py_fig), '--out', str(py_out),
    ], capsys)
    assert n_res.returncode == p_code == 0, p_stderr
    assert p_stdout == n_res.stdout
    assert py_out.read_bytes() == node_out.read_bytes()
    assert py_fig.read_bytes() == node_fig.read_bytes()

    saved_bytes = py_out.read_bytes()
    for bad_args in (
        ['channels', str(tmp_path / 'a.json'), '--counts', '40', '--out', str(py_out)],
        ['channels', str(tmp_path / 'a.json'), '--test', str(tmp_path / 'a.json'), '--out', str(py_out)],
    ):
        n_bad = run_node_cli(bad_args)
        b_code, _, b_err = run_python_cli_inproc(bad_args, capsys)
        assert n_bad.returncode == b_code == 2
        assert b_err == n_bad.stderr
    assert py_out.read_bytes() == saved_bytes

    # Case-insensitive eeg-summary name clash refused before checking environment or reading recordings.
    clash_args = ['eeg-summary', str(tmp_path / 'x/Rec.edf'), str(tmp_path / 'y/rec.EDF'), '--out-dir', str(tmp_path)]
    n_clash = run_node_cli(clash_args)
    c_code, _, c_err = run_python_cli_inproc(clash_args, capsys)
    assert n_clash.returncode == c_code == 2
    assert c_err == n_clash.stderr


@needs_node
def test_eeg_summary_and_prior_commands_match_node_on_fake_worker_and_real_edf(tmp_path: Path) -> None:
    fake_py = _make_fake_python(tmp_path)
    root = _synthetic_cli_root(tmp_path / 'root')
    rec1 = tmp_path / 'sub01.edf'
    rec2 = tmp_path / 'rec2.edf'
    rec3 = tmp_path / 'sub03.bdf'
    for p in (rec1, rec2, rec3):
        p.write_bytes(b'placeholder')

    # 1. Batch eeg-summary success
    node_sum_dir = tmp_path / 'node-sum'
    py_sum_dir = tmp_path / 'py-sum'
    common = ['--root', str(root), '--python', str(fake_py), '--band', '2,35', '--epoch', '2']
    n_sum = run_node_cli(['eeg-summary', str(rec1), str(rec2), str(rec3), *common, '--out-dir', str(node_sum_dir)])
    p_sum = run_python_cli_subprocess(['eeg-summary', str(rec1), str(rec2), str(rec3), *common, '--out-dir', str(py_sum_dir)])
    assert n_sum.returncode == p_sum.returncode == 0, p_sum.stderr
    assert n_sum.stdout == p_sum.stdout == ''
    assert tree_bytes(py_sum_dir) == tree_bytes(node_sum_dir)

    # 2. Batch eeg-summary partial failure exits 1 and keeps valid summaries
    env_fail = {'EEG_FAKE_WORKER_MODE': 'fail_second_recording'}
    node_fail_dir = tmp_path / 'node-fail'
    py_fail_dir = tmp_path / 'py-fail'
    n_f = run_node_cli(['eeg-summary', str(rec1), str(rec2), *common, '--out-dir', str(node_fail_dir)], env=env_fail)
    p_f = run_python_cli_subprocess(['eeg-summary', str(rec1), str(rec2), *common, '--out-dir', str(py_fail_dir)], env=env_fail)
    assert n_f.returncode == p_f.returncode == 1
    assert tree_bytes(py_fail_dir) == tree_bytes(node_fail_dir)
    assert set(tree_bytes(py_fail_dir)) == {'sub01.summary.json'}

    # 3. prior from directory (>= 3 summaries with held-out line, and < 3 summaries with independent noise)
    for mode, srcs, tag in (
        ('ok', [str(py_sum_dir)], 'corr3'),
        ('prior_independent', [str(py_sum_dir / 'sub01.summary.json'), str(py_sum_dir / 'rec2.summary.json')], 'indep2'),
    ):
        env_m = {'EEG_FAKE_WORKER_MODE': mode}
        n_prior_out = tmp_path / f'node-prior-{tag}.json'
        p_prior_out = tmp_path / f'py-prior-{tag}.json'
        n_p = run_node_cli(['prior', *srcs, '--root', str(root), '--python', str(fake_py), '--out', str(n_prior_out)], env=env_m)
        p_p = run_python_cli_subprocess(['prior', *srcs, '--root', str(root), '--python', str(fake_py), '--out', str(p_prior_out)], env=env_m)
        assert n_p.returncode == p_p.returncode == 0, p_p.stderr
        assert p_p.stdout == n_p.stdout
        assert p_prior_out.read_bytes() == n_prior_out.read_bytes()

    # 4. Real scripts/eeg_data.py run on a synthetic 30-second EDF file (byte-equal summary JSON!)
    from tests.test_eeg_recording import LABELS, signals, write_edf
    real_edf = tmp_path / 'real_synth.edf'
    write_edf(real_edf, LABELS, signals(seconds=30, seed=11))
    node_real_dir = tmp_path / 'node-real-edf'
    py_real_dir = tmp_path / 'py-real-edf'
    real_args = ['--root', str(ROOT), '--python', sys.executable, '--label', 'synth-subject']
    n_real = run_node_cli(['eeg-summary', str(real_edf), *real_args, '--out-dir', str(node_real_dir)])
    p_real = run_python_cli_subprocess(['eeg-summary', str(real_edf), *real_args, '--out-dir', str(py_real_dir)])
    assert n_real.returncode == p_real.returncode == 0, p_real.stderr
    assert tree_bytes(py_real_dir) == tree_bytes(node_real_dir)
