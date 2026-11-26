"""Package test: design 0002's installed root, interpreter, environment identity rows, data install/verify and CLI."""
import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

prefix_real = pathlib.Path(os.path.realpath(sys.prefix))
root = pathlib.Path(sys.prefix) / 'share/eeglayoutlab/root'
root_real = pathlib.Path(os.path.realpath(root))

for relative in (
    'src/compact_eeg/metrics.py',
    'src/compact_eeg/workflows/paths.py',
    'scripts/design_evaluation.py',
    'scripts/run_local_radius_compute.py',
    'configs/ernie_fem_point_pilot.json',
    'data/manifest.json',
    'data/packages.json',
    'data/SOURCES.md',
    'webapp/public/models/ernie/source-roi.json',
    'webapp/public/data/ernie-mni-mapping.json',
    'webapp/dist/client/index.html',
    'examples/expected.json',
):
    assert (root / relative).is_file(), f'missing {relative}'
assert not list(root.rglob('__pycache__')), 'bytecode in the root tree'

# compact_eeg exists once, in the root tree, so the code that runs is the code that is hashed.
assert importlib.util.find_spec('compact_eeg') is None, 'compact_eeg is importable from site-packages'

from eeglayoutlab.data.index import load_index  # noqa: E402
from eeglayoutlab.data.store import code_version  # noqa: E402
from eeglayoutlab.jobs.identity import _environment_rows  # noqa: E402
from eeglayoutlab.jobs.runtime import default_repository_root, installed_environment, runtime_config  # noqa: E402

expected_version = os.environ.get('EEG_PACKAGE_VERSION', '0.2.0')
assert code_version() == expected_version, f'{code_version()} != {expected_version}'
pkg_index = load_index(root / 'data/packages.json')
assert len(pkg_index.entries) >= 2 and 'base' in pkg_index.by_name

# Design 0002: default root, worker interpreter and environment identity rows without --root or EEG_COMPUTE_PYTHON.
clean_env = {k: v for k, v in os.environ.items() if k not in ('EEG_REPOSITORY_ROOT', 'EEG_COMPUTE_PYTHON')}
assert pathlib.Path(default_repository_root()) == root_real
cfg = runtime_config(str(root_real), env=clean_env)
expected_py = str(prefix_real / 'bin/python')
assert cfg.python == expected_py, f'{cfg.python} != {expected_py}'
assert cfg.native_python == expected_py, f'{cfg.native_python} != {expected_py}'
assert installed_environment(str(root_real)) == str(prefix_real)

rows = _environment_rows(str(prefix_real), expected_py)
assert rows[0] == 'environment:bin/python', rows[:3]
for required_pkg in ('cortech', 'nibabel', 'numba', 'numpy', 'scipy', 'llvmlite'):
    assert any(required_pkg in row and ('METADATA' in row or 'PKG-INFO' in row) for row in rows), (
        f'missing metadata row for {required_pkg} in {rows}'
    )

# The workers put R/src first on sys.path and find R from their own location.
probe = (
    'import sys, pathlib; sys.path.insert(0, sys.argv[1]); '
    'import compact_eeg.metrics, compact_eeg.workflows.paths as p; '
    'assert p.PROJECT_ROOT == pathlib.Path(sys.argv[2]).resolve(), p.PROJECT_ROOT'
)
subprocess.run([sys.executable, '-c', probe, str(root / 'src'), str(root)], check=True)

eeg_bin = str(pathlib.Path(sys.prefix) / 'bin/eeglayoutlab')
if not os.path.isfile(eeg_bin):
    eeg_bin = 'eeglayoutlab'

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = pathlib.Path(tmp)
    data_dir = tmp_path / 'data-store'
    environment = {**clean_env, 'EEGLAYOUTLAB_DATA_DIR': str(data_dir)}

    listed = subprocess.run([eeg_bin, 'data', 'list'], env=environment, check=True,
                            capture_output=True, text=True).stdout
    assert 'No packages are installed.' in listed, listed

    # No --root needed in the installed form: compose finds R automatically.
    composed = subprocess.run([eeg_bin, 'data', 'compose', '--dry-run'], env=environment, check=True,
                              capture_output=True, text=True).stdout
    assert 'No packages are installed' in composed, composed

    # Build a synthetic fixture package, install it with --no-compose, and verify SHA-256 integrity.
    sci = tmp_path / 'fixture-science'
    (sci / 'results/v2').mkdir(parents=True)
    src_bytes = (root / 'data/SOURCES.md').read_bytes()
    (sci / 'data').mkdir(parents=True)
    (sci / 'data/SOURCES.md').write_bytes(src_bytes)
    (sci / 'data/manifest.json').write_text(json.dumps({
        'schema_version': 'eeglayoutlab-data-bundle/1',
        'bundle_id': 'pkg-test',
        'files': [{
            'path': 'data/SOURCES.md',
            'size_bytes': len(src_bytes),
            'sha256': hashlib.sha256(src_bytes).hexdigest(),
        }],
    }), encoding='utf-8')
    built = tmp_path / 'built-pkgs'
    subprocess.run(
        [eeg_bin, 'data', 'build', '--root', str(sci), '--out', str(built), '--only', 'base', '--archive', 'base'],
        env=environment, check=True, capture_output=True, text=True,
    )
    subprocess.run(
        [eeg_bin, 'data', 'install', str(built / 'base-1.0.0.json'), '--no-compose', '--any-code-version'],
        env=environment, check=True, capture_output=True, text=True,
    )
    verified = subprocess.run(
        [eeg_bin, 'data', 'verify', 'base'],
        env=environment, check=True, capture_output=True, text=True,
    ).stdout
    assert 'base-1.0.0: intact' in verified, verified

    # Pure-Python coordinate design & SVG export work in the installed environment without Node or model data.
    design_out = tmp_path / 'std64.json'
    svg_dir = tmp_path / 'svg-out'
    subprocess.run(
        [eeg_bin, 'design', str(root / 'examples/01-standard64/standard64-labels.tsv'),
         '--name', 'standard64', '--out', str(design_out)],
        env=environment, check=True, capture_output=True, text=True,
    )
    subprocess.run(
        [eeg_bin, 'export', str(design_out), '--format', 'svg', '--out-dir', str(svg_dir)],
        env=environment, check=True, capture_output=True, text=True,
    )
    assert (svg_dir / 'layout.svg').is_file()

print('layout, default root, interpreter, environment rows, data verify and CLI verified as in design 0002')
