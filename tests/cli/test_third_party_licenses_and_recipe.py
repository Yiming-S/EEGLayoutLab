"""Tests for Phase 3 Slice 9: ``webapp/scripts/third-party-licenses.mjs``, ``recipe.yaml`` and ``run_test.py``."""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import stat
import subprocess
import sys

from service.installed_support import fake_prefix

from .cli_support import NODE, ROOT, needs_node

LICENSE_SCRIPT = ROOT / 'webapp/scripts/third-party-licenses.mjs'
RECIPE_DIR = ROOT / 'packaging/conda-forge/eeglayoutlab'


@needs_node
def test_third_party_web_licenses_script_includes_runtime_closure_and_excludes_build_only(tmp_path: Path) -> None:
    assert NODE is not None
    out_a = tmp_path / 'THIRD_PARTY_WEB_LICENSES_A.txt'
    out_b = tmp_path / 'THIRD_PARTY_WEB_LICENSES_B.txt'
    res_a = subprocess.run([NODE, str(LICENSE_SCRIPT), '--out', str(out_a)], cwd=ROOT,
                           check=True, capture_output=True, text=True)
    subprocess.run([NODE, str(LICENSE_SCRIPT), '--out', str(out_b)], cwd=ROOT,
                   check=True, capture_output=True, text=True)
    assert out_a.read_bytes() == out_b.read_bytes(), 'license output must be deterministic'
    text = out_a.read_text(encoding='utf-8')
    assert 'wrote ' in res_a.stdout

    # Must include core bundled client packages and their license texts
    for expected_pkg in (
        '- react@',
        '- react-dom@',
        '- @base-ui/react@',
        '- three@',
        '- recharts@',
        '- lucide-react@',
        '- clsx@',
        '- tailwind-merge@',
        '- vinext@',
    ):
        assert expected_pkg in text, f'missing {expected_pkg}'

    # Must exclude build-only native/CLI/type packages (LGPL sharp-libvips, CC-BY caniuse-lite, dev toolchains)
    for forbidden in (
        '- @img/sharp',
        '- caniuse-lite@',
        '- playwright@',
        '- oxlint@',
        '- typescript@',
        '- @types/',
        '- @vercel/og@',
        '- satori@',
    ):
        assert forbidden not in text, f'unexpected build-only package {forbidden} in bundled web licenses'


def test_conda_recipe_yaml_and_run_test_pass_in_installed_prefix(tmp_path: Path) -> None:
    recipe_text = (RECIPE_DIR / 'recipe.yaml').read_text(encoding='utf-8')
    assert 'nodejs >=22.18' in recipe_text
    assert 'THIRD_PARTY_WEB_LICENSES.txt' in recipe_text
    assert 'EEG_PACKAGE_VERSION=${{ version }} python run_test.py' in recipe_text
    assert 'pytest tests/test_iid_pin.py -q' in recipe_text

    # Build an installed-layout prefix (0002) and run the real packaging/conda-forge/eeglayoutlab/run_test.py!
    prefix = fake_prefix(
        tmp_path / 'P',
        public=(
            'webapp/public/models/ernie/source-roi.json',
            'webapp/public/data/ernie-mni-mapping.json',
        ),
    )
    # Copy remaining files that build.sh places in $PREFIX/share/eeglayoutlab/root
    shutil.copytree(ROOT / 'examples', prefix.root / 'examples', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('outputs', '__pycache__', '*.pyc', '.DS_Store'))
    (prefix.root / 'data/manifest.json').write_bytes((ROOT / 'data/manifest.json').read_bytes())
    (prefix.root / 'data/SOURCES.md').write_bytes((ROOT / 'data/SOURCES.md').read_bytes())
    (prefix.root / 'webapp/dist/client').mkdir(parents=True, exist_ok=True)
    (prefix.root / 'webapp/dist/client/index.html').write_text('<!doctype html><title>EEG</title>\n', encoding='utf-8')

    # Entry-point script $PREFIX/bin/eeglayoutlab matching recipe.yaml's entry_points
    eeg_bin = prefix.path / 'bin/eeglayoutlab'
    boot = (
        'import os, sys; '
        f'sys.prefix = sys.exec_prefix = {str(prefix.path)!r}; '
        "sys.path[:] = [e for e in sys.path if not any(os.path.isdir(os.path.join(e, n)) for n in ('compact_eeg', 'eeglayoutlab'))]; "
        f'sys.path.insert(0, {str(prefix.site)!r}); '
        'from eeglayoutlab.cli.main import main; '
        'sys.exit(main(sys.argv[1:]))'
    )
    eeg_bin.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" -I -B -c {boot!r} "$@"\n',
        encoding='utf-8',
    )
    eeg_bin.chmod(eeg_bin.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    run_test_code = (RECIPE_DIR / 'run_test.py').read_text(encoding='utf-8')
    clean_env = {
        k: v for k, v in os.environ.items()
        if k not in ('EEG_REPOSITORY_ROOT', 'EEG_COMPUTE_PYTHON', 'PYTHONPATH')
    }
    clean_env['EEG_PACKAGE_VERSION'] = '0.2.0'
    clean_env['PATH'] = f"{prefix.path / 'bin'}:{clean_env.get('PATH', '')}"

    res = prefix.run(run_test_code, env=clean_env)
    assert res.returncode == 0, f'stdout:\n{res.stdout}\nstderr:\n{res.stderr}'
    assert 'layout, default root, interpreter, environment rows, data verify and CLI verified' in res.stdout
