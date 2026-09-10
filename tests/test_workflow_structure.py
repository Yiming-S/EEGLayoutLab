"""Compatibility and package boundaries; no head-model solve or artifact writes."""
import importlib
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))


@pytest.mark.parametrize('name', [
    'source_reception', 'source_reception_v2', 'reception_forward_provider',
    'design_evaluation', 'electrode_editor',
])
def test_legacy_import_is_the_same_implementation(name):
    package = importlib.import_module('compact_eeg.workflows.' + name)
    legacy = importlib.import_module(name)
    assert legacy is package
    assert Path(package.__file__).parent == ROOT / 'src/compact_eeg/workflows'
    for key, value in vars(package).items():
        if callable(value) and not key.startswith('__'):
            assert getattr(legacy, key) is value


def test_project_root_is_independent_of_working_directory(tmp_path):
    command = "import sys; sys.path.insert(0, sys.argv[1]); from compact_eeg.workflows.paths import PROJECT_ROOT; print(PROJECT_ROOT)"
    result = subprocess.run([sys.executable, '-B', '-c', command, str(ROOT / 'src')],
                            cwd=tmp_path, capture_output=True, text=True, check=True)
    assert Path(result.stdout.strip()) == ROOT


@pytest.mark.parametrize('name', ['design_evaluation', 'electrode_editor'])
def test_legacy_worker_cli_still_rejects_invalid_input_without_calculating(name):
    result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts' / (name + '.py'))],
                            input='{}', capture_output=True, text=True, timeout=20)
    assert result.returncode == 1
    assert '"type": "error"' in result.stdout
    assert 'Traceback' not in result.stderr


def test_workflows_do_not_import_legacy_script_modules():
    import ast
    names = {'source_reception', 'source_reception_v2', 'reception_forward_provider',
             'design_evaluation', 'electrode_editor', 'inspect_ernie_cortical_forward'}
    for path in (ROOT / 'src/compact_eeg/workflows').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert not names.intersection(alias.name for alias in node.names), path
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                assert node.module not in names, path
