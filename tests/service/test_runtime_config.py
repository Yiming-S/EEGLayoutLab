"""Root and interpreter strings (plan B4, B5): ports of webapp/scripts/check-runtime-storage.mjs ('explicit runtime
roots preserve interpreter precedence ...', 'the Linux table runtime is selected only when the SimNIBS runtime is
absent') and the interpreter part of check-service-storage.mjs ('native services preserve managed interpreter
precedence over radius overrides')."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from eeglayoutlab.jobs import nodepath
from eeglayoutlab.jobs import runtime as runtime_module
from eeglayoutlab.jobs.runtime import (
    default_repository_root, managed_python, repository_root, runtime_config,
)
from eeglayoutlab.schemas import jsjson

from .installed_support import (
    DISTRIBUTION, ROOT_TREES, SITE, VERSION, environment, fake_prefix, links_in, needs_non_root, read_only, tree_state,
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


# --- The installed form (design 0002, changes 1 and 2; phase 3 slice 2) ------------------------------------------
# No Node counterpart: the Node host is not shipped in the installed form. The functions take the prefix and the
# package file, so a layout under tmp_path stands in for a conda prefix P in process; the subprocess cases below run
# the default call path on installed_support's fake prefix.

def _installed(base: Path, name: str = 'P') -> tuple[str, str, str]:
    """(P, the package's runtime.py inside P, R) of a minimal installed form under ``base``."""
    prefix = base / name
    (prefix / 'share/eeglayoutlab/root/src/compact_eeg').mkdir(parents=True)
    package = prefix / 'lib/python3.11/site-packages/eeglayoutlab/jobs/runtime.py'
    package.parent.mkdir(parents=True)
    package.write_text('', encoding='utf-8')
    (prefix / 'bin').mkdir()
    (prefix / 'bin/python3.11').write_text('fixture', encoding='utf-8')
    (prefix / 'bin/python').symlink_to('python3.11')
    return str(prefix), str(package), str(prefix / 'share/eeglayoutlab/root')


def test_installed_defaults_follow_the_order_of_precedence(tmp_path):
    prefix, package, root = _installed(tmp_path)
    where = {'prefix': prefix, 'package_file': package}
    assert runtime_module.checkout_root(package) is None
    assert runtime_module.installed_root(prefix) == root
    assert default_repository_root(**where) == root
    assert repository_root(env={}, **where) == root
    environment = f'{prefix}/bin/python'
    config = runtime_config(root, env={}, **where)
    assert (config.repository_root, config.python, config.native_python) == (root, environment, environment)
    # python || EEG_COMPUTE_PYTHON || managed || P/bin/python || 'python3'; the native one follows.
    assert runtime_config(root, env={'EEG_COMPUTE_PYTHON': '/env/python'}, **where).native_python == '/env/python'
    assert runtime_config(root, '/explicit/python', env={'EEG_COMPUTE_PYTHON': '/env/python'}, **where).python == \
        '/explicit/python'
    table = nodepath.join(root, '.runtime/compute-linux-64/bin/python')
    _fixture(table)
    config = runtime_config(root, env={}, **where)
    assert (config.python, config.native_python) == (table, table)
    assert runtime_config(root, '/explicit/python', env={}, **where).native_python == table
    native = nodepath.join(root, '.runtime/simnibs-4.6.0/bin/python')
    _fixture(native)
    assert runtime_config(root, env={'EEG_COMPUTE_PYTHON': '/env/python'}, **where).native_python == native
    os.remove(native)
    os.remove(table)
    # An environment without its interpreter (a dangling bin/python) falls through to python3.
    os.remove(f'{prefix}/bin/python3.11')
    assert runtime_config(root, env={}, **where).python == 'python3'


def test_installed_defaults_are_spelled_with_the_real_path_of_a_linked_prefix(tmp_path):
    prefix, package, root = _installed(tmp_path / 'real')
    (tmp_path / 'link').symlink_to(tmp_path / 'real')
    linked_prefix, linked_package = prefix.replace('/real/', '/link/'), package.replace('/real/', '/link/')
    where = {'prefix': linked_prefix, 'package_file': linked_package}
    assert default_repository_root(**where) == root
    assert runtime_config(root, env={}, **where).python == f'{prefix}/bin/python'
    # An explicit root through the link is kept as spelled (never resolved), but it is the installed root.
    linked_root = root.replace('/real/', '/link/')
    assert repository_root(linked_root, env={}, **where) == linked_root
    config = runtime_config(linked_root, env={}, **where)
    assert (config.repository_root, config.python) == (linked_root, f'{prefix}/bin/python')


def test_a_prefix_root_without_compact_eeg_is_no_root(tmp_path):
    prefix, package, root = _installed(tmp_path)
    os.rmdir(f'{root}/src/compact_eeg')
    where = {'prefix': prefix, 'package_file': package}
    assert runtime_module.installed_root(prefix) is None and default_repository_root(**where) is None
    with pytest.raises(ValueError, match='^A repository root is required.$'):
        repository_root(env={}, **where)
    assert runtime_config(root, env={}, **where).python == 'python3'


def test_a_checkout_wins_over_an_installed_root_in_its_prefix(tmp_path):
    # This package lies in a checkout: its root and the checkout's interpreter rule hold, whatever the prefix holds.
    prefix, _, root = _installed(tmp_path)
    assert runtime_module.installed_root(prefix) == root
    assert default_repository_root(prefix=prefix) == str(PACKAGE_CHECKOUT)
    assert repository_root(env={}, prefix=prefix) == str(PACKAGE_CHECKOUT)
    assert runtime_config(root, env={}, prefix=prefix).python == 'python3'
    assert not runtime_module.installed_form(root, prefix=prefix)


def test_explicit_roots_and_interpreters_win_over_the_installed_defaults(tmp_path):
    prefix, package, root = _installed(tmp_path)
    where = {'prefix': prefix, 'package_file': package}
    other = tmp_path / 'other'
    other.mkdir()
    assert repository_root(str(other), env={}, **where) == str(other)
    assert repository_root(env={'EEG_REPOSITORY_ROOT': str(other)}, **where) == str(other)
    # Another R keeps the checkout's rule: python3, not the environment's interpreter.
    assert runtime_config(str(other), env={}, **where).python == 'python3'
    # Empty strings fall through as with JavaScript's ||.
    assert repository_root('', env={'EEG_REPOSITORY_ROOT': ''}, **where) == root
    assert runtime_config(root, '', env={'EEG_COMPUTE_PYTHON': ''}, **where).python == f'{prefix}/bin/python'


INSTALLED_PROBE = """
import os
from eeglayoutlab.jobs import runtime
from eeglayoutlab.schemas import jsjson
root = runtime.repository_root()
config = runtime.runtime_config(root)
print(jsjson.stringify({'file': runtime.__file__, 'default': runtime.default_repository_root(), 'root': root,
                        'python': config.python, 'native': config.native_python,
                        'installed': runtime.installed_form(root)}))
"""


def _probe(installed, **kwargs) -> dict:
    result = installed.run(INSTALLED_PROBE, **kwargs)
    assert result.returncode == 0, result.stderr
    return jsjson.parse(result.stdout)


def test_the_installed_default_call_path(tmp_path):
    # A fresh interpreter whose sys.prefix is P imports the copy of the package in P's site-packages, as an
    # installed eeglayoutlab does, and calls everything with its defaults.
    prefix = fake_prefix(tmp_path / 'P', public=())
    real = os.path.realpath(prefix.path)
    found = _probe(prefix)
    assert found['file'] == f'{prefix.site}/eeglayoutlab/jobs/runtime.py'
    assert found == {**found, 'default': f'{real}/share/eeglayoutlab/root', 'root': f'{real}/share/eeglayoutlab/root',
                     'python': f'{real}/bin/python', 'native': f'{real}/bin/python', 'installed': True}
    # Through a linked prefix the strings are those of its real path.
    (tmp_path / 'link').symlink_to(tmp_path / 'P')
    linked = _probe(prefix, prefix=tmp_path / 'link')
    assert linked == {**found, 'file': f'{tmp_path}/link/{SITE}/eeglayoutlab/jobs/runtime.py'}
    # The overrides win in the installed form too.
    other = tmp_path / 'other'
    other.mkdir()
    assert _probe(prefix, env=environment(EEG_REPOSITORY_ROOT=str(other))) == {
        **found, 'root': str(other), 'python': 'python3', 'native': 'python3', 'installed': False}
    assert _probe(prefix, env=environment(EEG_COMPUTE_PYTHON='/env/python')) == {
        **found, 'python': '/env/python', 'native': '/env/python'}
    # A managed runtime in R wins over the environment's interpreter.
    table = prefix.root / '.runtime/compute-linux-64/bin/python'
    _fixture(str(table))
    assert _probe(prefix) == {**found, 'python': f'{real}/share/eeglayoutlab/root/.runtime/compute-linux-64/bin/python',
                              'native': f'{real}/share/eeglayoutlab/root/.runtime/compute-linux-64/bin/python'}


def test_the_fake_prefix_has_the_layout_of_design_0002(tmp_path):
    prefix = fake_prefix(tmp_path / 'P')
    # R holds real files only; the one link of P is bin/python, to a file inside P.
    assert links_in(prefix.root) == [] and links_in(prefix.site) == []
    assert links_in(prefix.path) == ['bin/python'] and os.readlink(prefix.python) == 'python3.11'
    assert os.path.realpath(prefix.python).startswith(os.path.realpath(prefix.path) + '/')
    for tree in ROOT_TREES:
        assert (prefix.root / tree).is_dir()
    assert not (prefix.root / 'examples/outputs').exists() and not list(prefix.root.rglob('__pycache__'))
    assert (prefix.root / 'data/SOURCES.md').read_bytes() == (CHECKOUT / 'data/SOURCES.md').read_bytes()
    assert not (prefix.site / 'compact_eeg').exists() and (prefix.site / 'eeglayoutlab/jobs/runtime.py').is_file()
    metadata = (prefix.site / f'compact_eeg-{VERSION}.dist-info/METADATA').read_text(encoding='utf-8')
    assert f'Name: {DISTRIBUTION}\n' in metadata and f'Version: {VERSION}\n' in metadata
    assert sorted(path.name for path in prefix.site.glob('*-info')) == [
        f'compact_eeg-{VERSION}.dist-info', 'cortech-0.1.dist-info', 'llvmlite-0.46.0-py3.11.egg-info',
        'nibabel-5.3.3.dist-info', 'numba-0.64.0.dist-info', 'numpy-2.3.0.dist-info', 'scipy-1.17.1.dist-info']
    assert SITE == 'lib/python3.11/site-packages'
    records = sorted(path.name for path in prefix.conda_meta.iterdir())
    assert 'history' in records and f'eeglayoutlab-{VERSION}-pyh4616a5c_0.json' in records
    assert all(name.endswith('.json') for name in records if name != 'history')
    # bin/python runs this interpreter.
    result = subprocess.run([str(prefix.python), '-c', 'import sys; print(sys.version_info[:2])'], capture_output=True,
                            text=True, timeout=60)
    assert result.returncode == 0 and result.stdout.strip() == str(tuple(sys.version_info[:2]))


def test_the_fake_prefix_imports_neither_package_from_a_checkout(tmp_path):
    # An editable install (CI's pip install -e) appends a checkout's src to sys.path through a .pth file, after
    # site-packages; so does bootstrap_runtime.py in a managed runtime. Here that entry is appended before the prelude.
    prefix = fake_prefix(tmp_path / 'P', public=())
    probe = ('import importlib.util\nimport eeglayoutlab\n'
             'print(importlib.util.find_spec("compact_eeg"), eeglayoutlab.__file__)\n')
    editable = prefix.command(probe)
    code = editable.index('-c') + 1
    editable[code] = f'import sys\nsys.path.append({str(CHECKOUT / "src")!r})\n' + editable[code]
    for command in (prefix.command(probe), editable):
        result = subprocess.run(command, cwd=tmp_path, env=environment(), stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        assert result.stdout == f'None {prefix.site}/eeglayoutlab/__init__.py\n'


# --- A read-only R (0002, decision 3) ----------------------------------------------------------------------------

def test_read_only_puts_back_the_mode_each_directory_had(tmp_path):
    # Under umask 002 (an ordinary user on Ubuntu or Fedora) a new directory is 0775; tree_state compares modes.
    first, second = tmp_path / 'first', tmp_path / 'second'
    for path, mode in ((first, 0o775), (second, 0o700)):
        path.mkdir()
        path.chmod(mode)
    before = tree_state(tmp_path)
    with read_only(first, second, first):
        assert stat.S_IMODE(first.stat().st_mode) == stat.S_IMODE(second.stat().st_mode) == 0o555
    assert tree_state(tmp_path) == before


@needs_non_root
def test_a_read_only_root_is_reported_without_writing(tmp_path):
    prefix, package, root = _installed(tmp_path)
    where = {'prefix': prefix, 'package_file': package}
    assert runtime_module.unwritable_root(root, **where) is None
    before = tree_state(Path(root))
    with read_only(Path(root)):
        message = runtime_module.unwritable_root(root, **where)
        assert message.startswith(f'{root} is not writable. ') and 'create a user environment' in message
        # The same directory outside the installed form gets the generic remedy.
        message = runtime_module.unwritable_root(root, prefix=prefix)
        assert message.startswith(f'{root} is not writable. ') and '--root or EEG_REPOSITORY_ROOT' in message
    assert tree_state(Path(root)) == before
    # Below R: the deepest of results/v2 and results that exists.
    (Path(root) / 'results/v2').mkdir(parents=True)
    with read_only(Path(root) / 'results'):
        assert runtime_module.unwritable_root(root, **where) is None
    with read_only(Path(root) / 'results/v2'):
        assert runtime_module.unwritable_root(root, **where).startswith(f'{root}/results/v2 is not writable. ')
    os.rmdir(Path(root) / 'results/v2')
    with read_only(Path(root) / 'results'):
        assert runtime_module.unwritable_root(root, **where).startswith(f'{root}/results is not writable. ')
