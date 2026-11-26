"""A fake conda prefix in the installed form of design 0002 (phase 3, slice 2; slices 3, 7 and 8 reuse it).

``fake_prefix(path)`` lays out, under ``path`` (P)::

    P/bin/python -> python3.11                          a link to a file inside P: a shell script that runs ``interpreter``
    P/lib/pythonX.Y/site-packages/eeglayoutlab/         a copy of this checkout's src/eeglayoutlab
    P/lib/pythonX.Y/site-packages/compact_eeg-V.dist-info/METADATA       Name: compact-eeg (pyproject.toml)
    P/lib/pythonX.Y/site-packages/<dist>-V.dist-info/METADATA            cortech, nibabel, numba, numpy, scipy
    P/lib/pythonX.Y/site-packages/llvmlite-0.46.0-pyX.Y.egg-info/PKG-INFO
    P/conda-meta/<name>-<version>-<build>.json          records with ``depends``: the numerical closure, eeglayoutlab's
                                                        own record and service-only packages
    P/conda-meta/history                                not JSON
    P/share/eeglayoutlab/root/                          R: real copies (never links) of the files build.sh copies

X.Y is the running interpreter's version, as slice 3 reads the site-packages path from it (3.11 in both tiers). R
holds ``src/compact_eeg``, ``scripts``, ``configs``, ``examples`` (without ``outputs``), the three ``data`` files, the
worker inputs of ``webapp/public`` (all of it with ``public=True``) and a built interface at ``webapp/dist/client``:
a small stand-in, or a copy of ``interface``. Model data is not there; ``data compose`` places it.

A subprocess that sets ``sys.prefix`` and puts P's site-packages first on ``sys.path`` before it imports
``eeglayoutlab`` runs the installed package (``FakePrefix.command``, ``run`` and ``popen``). ``-I`` drops
``PYTHONPATH`` and the current directory, but not the ``.pth`` files of this interpreter's site-packages, and an
editable install (CI's ``pip install -e``, or ``scripts/bootstrap_runtime.py``'s into a managed runtime, which may
be another checkout's) puts a checkout's ``src`` on ``sys.path`` through one. So the prelude first drops every
entry that holds ``compact_eeg`` or ``eeglayoutlab``: neither is importable from a checkout there, and
``compact_eeg`` is in R only, as in 0002. This interpreter's site-packages stays after P's with what is installed in
it: the service extra, and an editable install's ``compact_eeg-V.dist-info``, which ``importlib.metadata`` finds
only after P's. A regular (not editable) install of the package into this interpreter is not supported: the prelude
would drop its site-packages.
"""
from __future__ import annotations

from dataclasses import dataclass
import contextlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tomllib
from typing import Iterable, Iterator, Optional, Sequence, Union

import pytest

ROOT = Path(__file__).resolve().parents[2]
PYTHON_VERSION = f'{sys.version_info.major}.{sys.version_info.minor}'
SITE = f'lib/python{PYTHON_VERSION}/site-packages'
INSTALLED_ROOT = 'share/eeglayoutlab/root'
VERSION = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
DISTRIBUTION = 'compact-eeg'

# build.sh, step 3: the checkout's files at their relative paths.
ROOT_TREES = ('src/compact_eeg', 'scripts', 'configs', 'examples')
DATA_FILES = ('data/manifest.json', 'data/SOURCES.md', 'data/README.md')
# The worker inputs in the interface tree (0002, "What R holds today").
WORKER_INPUTS = ('webapp/public/models/ernie/source-roi.json', 'webapp/public/models/ernie/source-roi-definition.json',
                 'webapp/public/data/ernie-mni-mapping.json', 'webapp/public/data/single_head_optimization.json')
IGNORED = shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store')

# The numerical packages the recipe pins, with the METADATA (PKG-INFO for llvmlite) slice 3 hashes.
DIST_INFO = (('cortech', '0.1'), ('nibabel', '5.3.3'), ('numba', '0.64.0'), ('numpy', '2.3.0'), ('scipy', '1.17.1'))
EGG_INFO = (('llvmlite', '0.46.0'),)
# conda-meta records as (name, version, build, depends), after the 2026-11-23 osx-arm64 environment: the numerical
# closure and its dependencies, eeglayoutlab's own record, and packages outside the closure.
CLOSURE_RECORDS = (
    ('python', '3.11.18', 'hd05a0c4_0_cpython', ['libffi >=3.7.0,<3.8.0a0', 'libzlib >=1.3.2,<2.0a0', 'tzdata', 'pip']),
    ('python_abi', '3.11', '9_cp311', []),
    ('libffi', '3.7.0', 'h47dc5ef_1', []),
    ('libzlib', '1.3.2', 'h8088a28_3', []),
    ('tzdata', '2026e', 'h5d301ff_0', []),
    ('pip', '26.2.2', 'pyh8b19718_2', ['python >=3.10,<3.14.0a0', 'setuptools', 'wheel']),
    ('setuptools', '84.2.1', 'pyhe730653_0', ['python >=3.10']),
    ('wheel', '0.48.0', 'pyhd8ed1ab_0', ['packaging >=24.0', 'python >=3.10']),
    ('packaging', '26.3', 'pyhc364b38_0', ['python >=3.10']),
    ('numpy', '2.3.0', 'py311h4379d9d_0', ['libblas >=3.9.0,<4.0a0', 'libcblas >=3.9.0,<4.0a0', 'libcxx >=18',
                                           'liblapack >=3.9.0,<4.0a0', 'python >=3.11,<3.12.0a0',
                                           'python_abi 3.11.* *_cp311']),
    ('scipy', '1.17.1', 'py311h9a58382_1', ['libblas >=3.9.0,<4.0a0', 'libcblas >=3.9.0,<4.0a0', 'libcxx >=19',
                                            'liblapack >=3.9.0,<4.0a0', 'numpy >=1.25.2', 'python >=3.11,<3.12.0a0',
                                            'python_abi 3.11.* *_cp311']),
    ('numba', '0.64.0', 'py311h7b83a5e_0', ['llvm-openmp >=19', 'llvmlite >=0.46.0,<0.47.0a0', 'numpy >=1.24,<2.4',
                                            'python >=3.11,<3.12.0a0', 'python_abi 3.11.* *_cp311']),
    ('llvmlite', '0.46.0', 'py311h27de090_0', ['libcxx >=19', 'libzlib >=1.3.1,<2.0a0', 'python >=3.11,<3.12.0a0',
                                               'python_abi 3.11.* *_cp311']),
    ('nibabel', '5.3.3', 'pyhcf101f3_0', ['numpy >=1.25', 'packaging >=20', 'python >=3.10']),
    ('cortech', '0.1', 'np2py311h8e939d8_0', ['python', 'nibabel', 'numba', 'scipy', 'libcxx >=21',
                                              'python_abi 3.11.* *_cp311', 'numpy >=1.23,<3']),
    ('libblas', '3.11.0', '12_h51639a9_openblas', ['libopenblas >=0.3.34,<1.0a0']),
    ('libcblas', '3.11.0', '12_hb0561ab_openblas', ['libblas 3.11.0 12_h51639a9_openblas']),
    ('liblapack', '3.11.0', '12_hd9741b5_openblas', ['libblas 3.11.0 12_h51639a9_openblas']),
    ('libopenblas', '0.3.34', 'openmp_h5e6e99c_1', ['llvm-openmp >=21.1.8']),
    ('llvm-openmp', '23.1.6', 'hdb3d66b_0', []),
    ('libcxx', '23.1.6', 'hc645fd0_0', []),
)
OTHER_RECORDS = (
    ('eeglayoutlab', VERSION, 'pyh4616a5c_0', ['python >=3.11,<3.12', 'numpy 2.3.0', 'scipy 1.17.1', 'numba 0.64.0',
                                               'llvmlite 0.46.0', 'nibabel 5.3.3', 'cortech 0.1',
                                               'libblas * *openblas', 'libopenblas 0.3.34',
                                               'matplotlib-base 3.10.8', 'fastapi-core 0.165.0', 'uvicorn 0.54.0']),
    ('matplotlib-base', '3.10.8', 'py311h29553df_0', ['numpy >=1.23', 'python >=3.11,<3.12.0a0']),
    ('fastapi-core', '0.165.0', 'pyh5ded981_0', ['python >=3.10', 'starlette >=0.40.0']),
    ('starlette', '1.10.0', 'pyh5ded981_0', ['python >=3.10']),
    ('uvicorn', '0.54.0', 'pyh53cf698_0', ['h11 >=0.8', 'python >=3.10']),
    ('h11', '0.16.0', 'pyhcf101f3_1', ['python >=3.10']),
)
HISTORY = ('==> 2026-11-23 18:12:00 <==\n# cmd: conda create -p P -c conda-forge eeglayoutlab\n'
           '# conda version: 25.5.1\n+conda-forge/noarch::eeglayoutlab-0.2.0-pyh4616a5c_0\n')

# Runs the given code in the installed form: sys.argv is ['-c', P, site, *args] until the prelude removes P and site.
# Entries that hold either package (an editable install's src) go first; then P's site-packages leads.
PRELUDE = ('import os, sys\nsys.prefix = sys.argv[1]\n'
           "sys.path[:] = [entry for entry in sys.path if not any(os.path.isdir(os.path.join(entry, name))\n"
           "                                                      for name in ('compact_eeg', 'eeglayoutlab'))]\n"
           'sys.path.insert(0, sys.argv[2])\ndel sys.argv[1:3]\n')
# The command line's entry point (recipe.yaml: eeglayoutlab = eeglayoutlab.cli.main:main).
MAIN = 'from eeglayoutlab.cli.main import main\nsys.exit(main(sys.argv[1:]))\n'

needs_non_root = pytest.mark.skipif(hasattr(os, 'geteuid') and os.geteuid() == 0,
                                    reason='the superuser writes through any mode')


def record_name(name: str, version: str, build: str) -> str:
    return f'{name}-{version}-{build}.json'


def _record(name: str, version: str, build: str, depends: list[str]) -> str:
    subdir = 'noarch' if build.startswith('pyh') else 'osx-arm64'
    tail = build.rsplit('_', 1)[-1]
    value = {'build': build, 'build_number': int(tail) if tail.isdigit() else 0,
             'channel': f'https://conda.anaconda.org/conda-forge/{subdir}', 'depends': depends,
             'fn': record_name(name, version, build)[:-5] + '.conda', 'name': name, 'subdir': subdir,
             'version': version}
    return json.dumps(value, indent=2) + '\n'


def _metadata(name: str, version: str) -> str:
    return f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\nSummary: fixture of {name}\n'


def _copy_tree(source: Path, target: Path) -> None:
    # copytree follows symbolic links by default: every file in R is a real file, as 0002 requires.
    shutil.copytree(source, target, ignore=IGNORED, symlinks=False)


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _stand_in_interface(target: Path) -> None:
    """A built interface as ``npm run build`` lays it out, small: the home page, one page and a script."""
    for name, text in (('index.html', '<!doctype html><title>EEG Layout Lab</title>'),
                       ('design.html', '<!doctype html><title>design</title>'),
                       ('404.html', '<!doctype html><title>not found</title>'),
                       ('_next/static/chunks/app.js', 'console.log(1);')):
        (target / name).parent.mkdir(parents=True, exist_ok=True)
        (target / name).write_text(text, encoding='utf-8')


@dataclass(frozen=True)
class FakePrefix:
    path: Path
    """P as it was created (no link in it unless the caller put one there)."""
    version: str

    @property
    def site(self) -> Path:
        return self.path / SITE

    @property
    def root(self) -> Path:
        return self.path / INSTALLED_ROOT

    @property
    def python(self) -> Path:
        return self.path / 'bin/python'

    @property
    def conda_meta(self) -> Path:
        return self.path / 'conda-meta'

    def command(self, code: str, *args: str, prefix: Optional[Union[str, Path]] = None) -> list[str]:
        """This interpreter running ``code`` with ``sys.prefix`` set to ``prefix`` (default P) and its
        site-packages first on ``sys.path``; ``code`` sees ``sys.argv == ['-c', *args]``."""
        spelled = Path(prefix) if prefix is not None else self.path
        return [sys.executable, '-I', '-B', '-c', PRELUDE + code, str(spelled), str(spelled / SITE), *map(str, args)]

    def run(self, code: str, *args: str, prefix: Optional[Union[str, Path]] = None, cwd: Optional[Path] = None,
            env: Optional[dict[str, str]] = None, timeout: float = 120) -> subprocess.CompletedProcess:
        return subprocess.run(self.command(code, *args, prefix=prefix), cwd=cwd or self.path.parent,
                              env=env if env is not None else environment(), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=timeout)

    def popen(self, code: str, *args: str, prefix: Optional[Union[str, Path]] = None, cwd: Optional[Path] = None,
              env: Optional[dict[str, str]] = None) -> subprocess.Popen:
        return subprocess.Popen(self.command(code, *args, prefix=prefix), cwd=cwd or self.path.parent,
                                env=env if env is not None else environment(), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def environment(**extra: str) -> dict[str, str]:
    """This process's environment without ``EEG_*`` (the root and interpreter overrides) and ``PYTHON*``."""
    env = {name: value for name, value in os.environ.items() if not name.startswith(('EEG_', 'PYTHON'))}
    env.update(extra)
    return env


def fake_prefix(path: Path, *, version: str = VERSION, public: Union[bool, Sequence[str]] = WORKER_INPUTS,
                interface: Optional[Path] = None, interpreter: Optional[str] = sys.executable,
                records: Iterable[tuple[str, str, str, list[str]]] = CLOSURE_RECORDS + OTHER_RECORDS) -> FakePrefix:
    """Builds the installed form under ``path`` (see the module docstring) and returns it.

    ``public``: ``True`` copies all of ``webapp/public``, a sequence of root-relative paths only those files.
    ``interface``: a built interface to copy to ``R/webapp/dist/client`` (default: a small stand-in).
    ``interpreter``: what ``P/bin/python`` runs; ``None`` writes a file that is not executable.
    """
    prefix = FakePrefix(path, version)
    site = prefix.site
    # The package, without compact_eeg, and its distribution's metadata.
    _copy_tree(ROOT / 'src/eeglayoutlab', site / 'eeglayoutlab')
    dist_info = site / f'compact_eeg-{version}.dist-info'
    dist_info.mkdir()
    (dist_info / 'METADATA').write_text(_metadata(DISTRIBUTION, version), encoding='utf-8')
    (dist_info / 'top_level.txt').write_text('eeglayoutlab\n', encoding='utf-8')
    for name, dist_version in DIST_INFO:
        (site / f'{name}-{dist_version}.dist-info').mkdir()
        (site / f'{name}-{dist_version}.dist-info/METADATA').write_text(_metadata(name, dist_version), 'utf-8')
    for name, dist_version in EGG_INFO:
        egg = site / f'{name}-{dist_version}-py{PYTHON_VERSION}.egg-info'
        egg.mkdir()
        (egg / 'PKG-INFO').write_text(_metadata(name, dist_version), encoding='utf-8')
    # The interpreter: bin/python links to a file inside P.
    (path / 'bin').mkdir(parents=True)
    target = path / f'bin/python{PYTHON_VERSION}'
    if interpreter is None:
        target.write_text('fixture interpreter\n', encoding='utf-8')
    else:
        target.write_text(f'#!/bin/sh\nexec {_shell_quote(interpreter)} "$@"\n', encoding='utf-8')
        target.chmod(0o755)
    (path / 'bin/python').symlink_to(target.name)
    # conda-meta: one JSON record per package and a history that is not JSON.
    prefix.conda_meta.mkdir()
    for name, record_version, build, depends in records:
        (prefix.conda_meta / record_name(name, record_version, build)).write_text(
            _record(name, record_version, build, list(depends)), encoding='utf-8')
    (prefix.conda_meta / 'history').write_text(HISTORY, encoding='utf-8')
    # R: real copies of the checkout's files at their relative paths.
    root = prefix.root
    for tree in ROOT_TREES:
        _copy_tree(ROOT / tree, root / tree)
    shutil.rmtree(root / 'examples/outputs', ignore_errors=True)
    for name in DATA_FILES:
        _copy_file(ROOT / name, root / name)
    if public is True:
        _copy_tree(ROOT / 'webapp/public', root / 'webapp/public')
    elif public:
        for name in public:
            _copy_file(ROOT / name, root / name)
    client = root / 'webapp/dist/client'
    if interface is not None:
        _copy_tree(interface, client)
    else:
        _stand_in_interface(client)
    return prefix


def _shell_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def links_in(path: Path) -> list[str]:
    """Every symbolic link under ``path``, relative to it."""
    return sorted(str(item.relative_to(path)) for item in path.rglob('*') if item.is_symlink())


@contextlib.contextmanager
def read_only(*paths: Path) -> Iterator[None]:
    """Each directory at mode 0555 for the duration, then at the mode it had before, whatever the umask made it (so
    tmp_path can be removed and ``tree_state`` compares equal)."""
    modes = [(path, stat.S_IMODE(path.stat().st_mode)) for path in paths]
    try:
        for path, _ in modes:
            path.chmod(0o555)
        yield
    finally:
        # In reverse, so a directory named twice gets its first mode back.
        for path, mode in reversed(modes):
            path.chmod(mode)


def tree_state(path: Path) -> dict[str, tuple]:
    """Each entry under ``path`` (itself included) with its type, size, mode and modification time, to show that
    nothing was written."""
    state = {}
    for item in [path, *path.rglob('*')]:
        info = item.lstat()
        state[str(item.relative_to(path))] = (stat.S_IFMT(info.st_mode), info.st_size, stat.S_IMODE(info.st_mode),
                                              info.st_mtime_ns)
    return state
