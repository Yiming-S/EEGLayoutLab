"""Root and interpreter strings (plan B4, B5): ports of webapp/scripts/check-runtime-storage.mjs ('explicit runtime
roots preserve interpreter precedence ...', 'the Linux table runtime is selected only when the SimNIBS runtime is
absent') and the interpreter part of check-service-storage.mjs ('native services preserve managed interpreter
precedence over radius overrides')."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from eeglayoutlab.jobs import nodepath
from eeglayoutlab.jobs import runtime as runtime_module
from eeglayoutlab.jobs.runtime import (
    default_repository_root, managed_python, repository_root, runtime_config,
)

CHECKOUT = Path(__file__).resolve().parents[2]
# The checkout that holds the package under test (this one, unless the package is imported from elsewhere).
PACKAGE_CHECKOUT = Path(os.path.realpath(runtime_module.__file__)).parents[3]


def _fixture(path: str) -> None:
    os.makedirs(nodepath.dirname(path), exist_ok=True)
    Path(path).write_text('fixture', encoding='utf-8')


def test_explicit_runtime_roots_preserve_interpreter_precedence(tmp_path):
    # check-runtime-storage.mjs:9. Its queue-directory assertions are not ported: the workspace replaces Node's
    # queue directory (plan 2.2), so RuntimeConfig has none.
    root = str(tmp_path)
    assert runtime_config(root, env={}).python == 'python3'
    native = nodepath.join(root, '.runtime/simnibs-4.6.0/bin/python')
    _fixture(native)
    config = runtime_config(root, python='/explicit/python', env={})
    assert config.python == '/explicit/python'
    assert config.native_python == native


def test_linux_table_runtime_is_selected_only_without_simnibs(tmp_path):
    # check-runtime-storage.mjs:22
    root = str(tmp_path)
    table = nodepath.join(root, '.runtime/compute-linux-64/bin/python')
    native = nodepath.join(root, '.runtime/simnibs-4.6.0/bin/python')
    _fixture(table)
    assert runtime_config(root, env={}).python == table
    assert runtime_config(root, env={'EEG_COMPUTE_PYTHON': '/env/python'}).python == '/env/python'
    assert runtime_config(root, env={'EEG_COMPUTE_PYTHON': '/env/python'}).native_python == table
    _fixture(native)
    assert runtime_config(root, env={}).native_python == native


def test_native_services_use_the_managed_interpreter_over_radius_overrides(tmp_path):
    # check-service-storage.mjs:33: the queue keeps its explicit interpreter; the design, reception and editor
    # services (one RuntimeConfig.native_python here) use the managed one, also for a queue without a runtime
    # configuration (`new SourceReceptionService({root, python: '/fallback/python'})`).
    root = str(tmp_path)
    native = nodepath.join(root, '.runtime/simnibs-4.6.0/bin/python')
    _fixture(native)
    config = runtime_config(root, python='/explicit/python', env={})
    assert config.python == '/explicit/python'
    assert config.native_python == native
    assert runtime_config(root, python='/fallback/python', env={}).native_python == native


def test_interpreter_precedence_uses_javascript_or(tmp_path):
    root = str(tmp_path)
    assert runtime_config(root, python='', env={'EEG_COMPUTE_PYTHON': '/env/python'}).python == '/env/python'
    assert runtime_config(root, env={'EEG_COMPUTE_PYTHON': ''}).python == 'python3'
    assert runtime_config(root, python='/explicit/python', env={'EEG_COMPUTE_PYTHON': '/env/python'}).python == '/explicit/python'
    # Without a managed runtime the native interpreter is the compute one.
    assert runtime_config(root, python='/explicit/python', env={}).native_python == '/explicit/python'


def test_managed_runtime_must_exist_through_links(tmp_path):
    root = str(tmp_path)
    native = Path(nodepath.join(root, '.runtime/simnibs-4.6.0/bin/python'))
    native.parent.mkdir(parents=True)
    native.symlink_to('python3.11')  # dangling: existsSync follows links
    assert managed_python(root) is None
    assert runtime_config(root, env={}).native_python == 'python3'
    (native.parent / 'python3.11').write_text('fixture', encoding='utf-8')
    assert managed_python(root) == str(native)


def test_root_strings_are_normalized_never_resolved_through_links(tmp_path):
    (tmp_path / 'real').mkdir()
    (tmp_path / 'link').symlink_to(tmp_path / 'real')
    spelled = f'{tmp_path}//link/./x/..'
    assert runtime_config(spelled, env={}).repository_root == f'{tmp_path}/link'
    assert repository_root(spelled, env={}) == f'{tmp_path}/link'
    assert repository_root(env={'EEG_REPOSITORY_ROOT': f'{tmp_path}/link/'}) == f'{tmp_path}/link'
    # The explicit value wins over the environment, with JavaScript's ||.
    assert repository_root(f'{tmp_path}/real', env={'EEG_REPOSITORY_ROOT': f'{tmp_path}/link'}) == f'{tmp_path}/real'
    assert repository_root('', env={'EEG_REPOSITORY_ROOT': f'{tmp_path}/link'}) == f'{tmp_path}/link'


def test_root_errors_are_nodes(tmp_path):
    with pytest.raises(ValueError, match='^EEG_REPOSITORY_ROOT must be absolute.$'):
        repository_root('relative/root', env={})
    with pytest.raises(ValueError, match='^EEG_REPOSITORY_ROOT must be absolute.$'):
        repository_root(env={'EEG_REPOSITORY_ROOT': 'relative/root'})
    with pytest.raises(ValueError, match='^The scientific repository root does not exist.$'):
        repository_root(str(tmp_path / 'missing'), env={})
    for blank in ('', ' \u3000\ufeff'):
        with pytest.raises(ValueError, match='^A repository root is required.$'):
            runtime_config(blank, env={})


def test_default_root_is_the_real_path_of_this_checkout():
    # Node's default comes from import.meta.url, in which symbolic links are resolved.
    assert default_repository_root() == os.path.realpath(CHECKOUT)
    assert repository_root(env={}) == os.path.realpath(CHECKOUT)


def _default_root_through(source: str, cwd: Path) -> str:
    """``default_repository_root()`` in a fresh interpreter that imports this package from ``source``."""
    script = 'from eeglayoutlab.jobs.runtime import default_repository_root; print(default_repository_root())'
    environment = {**os.environ, 'PYTHONPATH': source}
    return subprocess.run([sys.executable, '-B', '-c', script], check=True, capture_output=True, text=True, cwd=cwd,
                          env=environment).stdout.strip()


def test_default_root_resolves_a_checkout_reached_through_a_link(tmp_path):
    # Under pytest the package is imported from the real checkout, so the test above cannot see a lost realpath.
    (tmp_path / 'link').symlink_to(PACKAGE_CHECKOUT)
    assert _default_root_through(f'{tmp_path}/link/src', tmp_path) == str(PACKAGE_CHECKOUT)


def test_default_root_resolves_link_targets_as_node_does(tmp_path):
    # Node resolves its main module with fs.realpathSync, which resolves `alias/..` in a link target lexically:
    # through link -> alias/../real the kernel imports this checkout (deep/real) but Node's real path is the decoy
    # (real). The decoy holds only the names realpathSync stats and the checkout test looks for.
    decoy = tmp_path / 'decoy'
    (decoy / 'src/eeglayoutlab/jobs').mkdir(parents=True)
    (decoy / 'src/eeglayoutlab/jobs/runtime.py').write_text('', encoding='utf-8')
    (decoy / 'src/compact_eeg').mkdir()
    (decoy / 'pyproject.toml').write_text('', encoding='utf-8')
    (tmp_path / 'deep/b').mkdir(parents=True)
    (tmp_path / 'deep/real').symlink_to(PACKAGE_CHECKOUT)
    (tmp_path / 'alias').symlink_to(tmp_path / 'deep/b')
    (tmp_path / 'real').symlink_to(decoy)
    (tmp_path / 'link').symlink_to('alias/../real')
    assert _default_root_through(f'{tmp_path}/link/src', tmp_path) == os.path.realpath(decoy)
