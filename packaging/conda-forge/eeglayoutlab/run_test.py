"""Package test: the layout of design 0002 and the commands that work without model data."""
import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(sys.prefix) / 'share/eeglayoutlab/root'
for relative in ('src/compact_eeg/metrics.py', 'src/compact_eeg/workflows/paths.py', 'scripts/design_evaluation.py',
                 'scripts/run_local_radius_compute.py', 'configs/ernie_fem_point_pilot.json', 'data/manifest.json',
                 'data/SOURCES.md', 'webapp/public/models/ernie/source-roi.json', 'webapp/dist/client/index.html',
                 'examples/expected.json'):
    assert (root / relative).is_file(), f'missing {relative}'
assert not list(root.rglob('__pycache__')), 'bytecode in the root tree'

# compact_eeg exists once, in the root tree, so the code that runs is the code that is hashed.
assert importlib.util.find_spec('compact_eeg') is None, 'compact_eeg is importable from site-packages'

from eeglayoutlab.data.store import code_version  # noqa: E402
assert code_version() == '0.2.0', code_version()

# The workers put R/src first on sys.path and find R from their own location.
probe = ('import sys, pathlib; sys.path.insert(0, sys.argv[1]); '
         'import compact_eeg.metrics, compact_eeg.workflows.paths as p; '
         'assert p.PROJECT_ROOT == pathlib.Path(sys.argv[2]).resolve(), p.PROJECT_ROOT')
subprocess.run([sys.executable, '-c', probe, str(root / 'src'), str(root)], check=True)

with tempfile.TemporaryDirectory() as data:
    environment = dict(os.environ, EEGLAYOUTLAB_DATA_DIR=data)
    listed = subprocess.run(['eeglayoutlab', 'data', 'list'], env=environment, check=True, capture_output=True,
                            text=True).stdout
    assert 'No packages are installed.' in listed, listed
    composed = subprocess.run(['eeglayoutlab', 'data', 'compose', '--root', str(root), '--dry-run'], env=environment,
                              check=True, capture_output=True, text=True).stdout
    assert 'No packages are installed' in composed, composed
print('layout and commands as in design 0002')
