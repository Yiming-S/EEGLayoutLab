"""Tests for ``eeglayoutlab examples run`` in both checkout and installed forms (phase 3 slice 7; U14)."""
from __future__ import annotations

from pathlib import Path
import shutil
import sys

import pytest

from schema_parity_support import require

require('pydantic')

from eeglayoutlab.schemas import jsjson  # noqa: E402
from service.installed_support import MAIN, environment, fake_prefix  # noqa: E402
from service.key_parity_support import radius_root  # noqa: E402

from .cli_support import ROOT, run_python_cli_inproc  # noqa: E402

FAKE_WORKER = ROOT / 'tests/cli/fake_worker.py'


def _make_fake_python(tmp_path: Path) -> Path:
    wrapper = tmp_path / 'fake-python'
    wrapper.write_text(
        f'#!/bin/sh\n'
        f'shift\n'
        f'exec "{sys.executable}" -u "{FAKE_WORKER}" "$@"\n',
        encoding='utf-8',
    )
    wrapper.chmod(0o755)
    return wrapper


def _examples_root(tmp_path: Path, *, with_heads: bool = True) -> Path:
    heads = ()
    if with_heads:
        heads_spec = jsjson.parse((ROOT / 'examples/03-cross-head/heads.json').read_text(encoding='utf-8'))
        heads = tuple(entry['head_id'] for entry in heads_spec['cases'])
    root = Path(radius_root(tmp_path / 'ex-root', table=True, heads=heads))
    shutil.copytree(ROOT / 'examples', root / 'examples', ignore=shutil.ignore_patterns('outputs'))
    # Copy Ernie mapping JSON used by design & export (U13).
    mapping_dst = root / 'webapp/public/data/ernie-mni-mapping.json'
    mapping_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'webapp/public/data/ernie-mni-mapping.json', mapping_dst)
    return root


def test_examples_run_matches_expected_handles_skip_missing_heads_drift_and_update(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_py = _make_fake_python(tmp_path)
    full_root = _examples_root(tmp_path / 'full', with_heads=True)
    out_all = tmp_path / 'out-all'

    # 1. All 3 examples match expected.json within 1e-6 -> exit 0
    monkeypatch.setenv('EEG_FAKE_WORKER_MODE', 'examples_expected')
    code, out, _ = run_python_cli_inproc(
        ['examples', 'run', '--root', str(full_root), '--out-dir', str(out_all), '--python', str(fake_py)],
        capsys,
    )
    assert code == 0, out
    assert 'All scores of 3 of 3 examples match expected.json within 0.000001.' in out
    assert (out_all / '01-standard64/files/layout.svg').is_file()
    assert (out_all / '02-compact-search/files/layout.svg').is_file()
    assert (out_all / '03-cross-head/study.json').is_file()

    # 2. Score drift > 1e-6 -> exit 1 with differences reported
    monkeypatch.setenv('EEG_FAKE_WORKER_MODE', 'examples_drift')
    code, out, _ = run_python_cli_inproc(
        ['examples', 'run', '--root', str(full_root), '--out-dir', str(tmp_path / 'out-drift'), '--python', str(fake_py)],
        capsys,
    )
    assert code == 1 and 'differences:' in out

    # 3. Missing head packages: fails without --skip-cross-head, succeeds with --skip-cross-head
    no_heads_root = _examples_root(tmp_path / 'no-heads', with_heads=False)
    monkeypatch.setenv('EEG_FAKE_WORKER_MODE', 'examples_expected')
    code, out, _ = run_python_cli_inproc(
        ['examples', 'run', '--root', str(no_heads_root), '--out-dir', str(tmp_path / 'out-missing'), '--python', str(fake_py)],
        capsys,
    )
    assert code == 1
    assert 'head packages without a published table: ernie_xh' in out
    assert '03-cross-head: not run' in out

    code, out, _ = run_python_cli_inproc(
        [
            'examples', 'run', '--root', str(no_heads_root), '--out-dir', str(tmp_path / 'out-skip'),
            '--skip-cross-head', '--python', str(fake_py),
        ],
        capsys,
    )
    assert code == 0
    assert 'All scores of 2 of 3 examples match expected.json within 0.000001. Not compared: 03-cross-head.' in out

    # 4. --update-expected refuses when --skip-cross-head leaves out an example, writes expected.json when all 3 run
    code, _, err = run_python_cli_inproc(
        [
            'examples', 'run', '--root', str(full_root), '--out-dir', str(tmp_path / 'out-upd-skip'),
            '--skip-cross-head', '--update-expected', '--python', str(fake_py),
        ],
        capsys,
    )
    assert code == 1 and '--update-expected needs every example' in err

    monkeypatch.setenv('EEG_FAKE_WORKER_MODE', 'examples_drift')
    code, out, _ = run_python_cli_inproc(
        [
            'examples', 'run', '--root', str(full_root), '--out-dir', str(tmp_path / 'out-upd'),
            '--update-expected', '--python', str(fake_py),
        ],
        capsys,
    )
    assert code == 0 and f'wrote {full_root / "examples/expected.json"}' in out


def test_examples_run_in_installed_form_uses_cwd_default_and_refuses_root_or_update(tmp_path: Path) -> None:
    fake_py = _make_fake_python(tmp_path)
    prefix = fake_prefix(tmp_path / 'P')
    # Lay synthetic data pointers/tables into P/share/eeglayoutlab/root so examples 1 & 2 run end-to-end!
    synth = _examples_root(tmp_path / 'synth', with_heads=False)
    for rel in ('results', 'configs/ernie_fem_point_pilot.json', 'configs/single_head_optimization.json',
                'data/admission.npz', 'data/candidates.npz', 'data/report.json',
                'data/head.msh', 'data/scalp', 'data/sources.npz'):
        src, dst = synth / rel, prefix.root / rel
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)

    work_cwd = tmp_path / 'user-cwd'
    work_cwd.mkdir()
    env = environment(EEG_FAKE_WORKER_MODE='examples_expected')

    # Refuses --update-expected in installed form (exit 2)
    res_upd = prefix.run(MAIN, 'examples', 'run', '--update-expected', cwd=work_cwd, env=env)
    assert res_upd.returncode == 2 and 'only available in a source checkout' in res_upd.stderr

    # Refuses --out-dir inside installed R (exit 2)
    res_inside = prefix.run(
        MAIN, 'examples', 'run', '--out-dir', str(prefix.root / 'examples/outputs'), cwd=work_cwd, env=env
    )
    assert res_inside.returncode == 2 and 'inside the installed scientific root' in res_inside.stderr

    # Default --out-dir in installed form writes to <cwd>/eeglayoutlab-examples and leaves R untouched!
    res_ok = prefix.run(
        MAIN, 'examples', 'run', '--skip-cross-head', '--python', str(fake_py), cwd=work_cwd, env=env
    )
    assert res_ok.returncode == 0, res_ok.stderr + '\n' + res_ok.stdout
    assert (work_cwd / 'eeglayoutlab-examples/01-standard64/request.result.json').is_file()
    assert (work_cwd / 'eeglayoutlab-examples/02-compact-search/request.result.json').is_file()
    assert not (prefix.root / 'examples/outputs').exists()
