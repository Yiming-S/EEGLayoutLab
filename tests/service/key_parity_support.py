"""Shared setup for the key parity tests (tests/service/README.md).

``design_root`` builds a synthetic scientific root, a Python port of ``designContextRoot`` in
``webapp/scripts/helpers/robustness-fixture.mjs`` with a switch for each variant in ``ROOTS``. ``synthetic_cases``
crosses the roots with interpreter configurations (``CONFIGS``) and requests (``REQUESTS`` and the canonical design
requests of the schema parity corpus); ``run_node`` runs the Node driver ``tests/service/parity/identity.mjs`` once
over a list of cases and ``PythonCases`` computes the same cases with ``eeglayoutlab.jobs``.

Like tests/schema_parity_support.py: without Node, or without Pydantic (the service extra, so the native runtime
suite runs unchanged), the parity tests are skipped; with ``EEG_REQUIRE_SCHEMA_PARITY=1`` (set in CI) a missing
dependency is an error instead.
"""
from __future__ import annotations

from dataclasses import dataclass
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Optional
import unicodedata

import pytest

from eeglayoutlab.jobs.identity import IdentityError, JSTypeError, design_context
from eeglayoutlab.jobs.integrity import InputIntegrity
from eeglayoutlab.jobs.runtime import runtime_config
from eeglayoutlab.schemas import jsjson
from schema_parity_support import CORPUS, REQUIRED, require  # noqa: F401 - re-exported

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'tests/service/parity/identity.mjs'


def _node_available() -> bool:
    if not REQUIRED and importlib.util.find_spec('pydantic') is None:
        return False
    if shutil.which('node') is None:
        if REQUIRED:
            raise RuntimeError('EEG_REQUIRE_SCHEMA_PARITY=1 but Node is not on PATH')
        return False
    return True


NODE = _node_available()
needs_node = pytest.mark.skipif(not NODE, reason='Node (and the service extra) are required to run the Node reference')


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


# --- Synthetic roots -------------------------------------------------------------------------------------------

BANK = 'results/v2/bank/runs/r/batches/b/bank.npz'
TABLE_DIR = 'results/v2/scalp_node_table/' + 't' * 64
SCENARIOS = ('skull_x2', 'skull_x0.5')
HEADS = ('ixi002', 'a', 'a_b-c', 'a' * 40)
NATIVE = '.runtime/simnibs-4.6.0'
TABLE_RUNTIME = '.runtime/compute-linux-64'
SITE = 'lib/python3.11/site-packages'
# Code-unit order differs from code-point order for the last two: U+1F600 is D83D DE00 in UTF-16, before U+FF5A.
CONDA_META = ('b.json', 'a.json', 'Z.json', '\u00e4.json', '\uff5a.json', '\U0001F600.json', 'history', 'notes.json.bak')
# JavaScript's '.' does not match a line terminator (\n, \r, U+2028, U+2029) and its '$' is only the end of the
# text, so the names that contain one, or end in '\n', never match the dist-info rules; Python's '.' and '$' would.
LINE_TERMINATOR_DIST_INFO = ('numpy-a\nb.dist-info', 'numpy-a\rb.dist-info', 'numpy-a\u2028b.dist-info',
                             'scipy-a\u2029b.dist-info', 'numpy-1.dist-info\n')
NATIVE_DIST_INFO = ('simnibs-4.6.0.dist-info', 'cortech-0.1.dist-info', 'numpy-2.3.0.dist-info', 'scipy-1.17.1.dist-info',
                    'numpy-.dist-info', 'numba-0.60.0.dist-info', 'numpyx-1.0.dist-info', 'Numpy-1.0.dist-info',
                    'numpy-2.3.0.dist-info.bak', 'simnibs.dist-info', *LINE_TERMINATOR_DIST_INFO)
TABLE_DIST_INFO = ('cortech-0.1.dist-info', 'llvmlite-0.43.0.dist-info', 'nibabel-5.3.2.dist-info', 'numba-0.60.0.dist-info',
                   'numpy-2.3.0.dist-info', 'scipy-1.17.1.dist-info', 'simnibs-4.6.0.dist-info', 'matplotlib-3.10.8.dist-info',
                   *LINE_TERMINATOR_DIST_INFO)

# One broken input each. The scenario and head breaks change SCENARIOS[0] and HEADS[0].
BREAKS = (
    'no_pointer', 'no_source', 'escape', 'escape_prefix', 'report_absolute',
    # the identity checks after the digests
    'bank_sha', 'candidate_sha', 'admission_sha', 'admission_geometry', 'table_sha', 'scenario_sha', 'head_sha',
    # optional pointers: only ENOENT is tolerated
    'table_dir', 'scenario_dir', 'head_dir', 'table_corrupt', 'scenario_corrupt', 'head_corrupt',
    # pointer files read as Node reads them: a BOM is not JSON
    'admission_bom',
    # pointer values Node's code trips over, or skips when they are falsy
    'admission_null', 'table_array', 'table_string', 'table_object', 'table_false', 'table_zero', 'table_empty',
    'table_null', 'scenario_false', 'scenario_null', 'head_zero', 'head_null', 'mesh_null', 'mesh_nul', 'no_mesh_path',
    'no_source_inputs', 'no_init', 'dir_init',
    # an input that cannot be opened (mode 000; not for a user who can read anything)
    'unreadable_sources',
)
# Two breaks in different stages. Synchronous argument errors always settle before any I/O (a path that is not
# a string before one with a NUL byte) and the identity checks run one after another once every digest is in.
# Between the file stages (real paths, opens, reads: a directory opens and fails at its first read) the order is
# fixed only with one thread-pool worker, which the driver uses (NODE_ENV).
COMBINED = (
    'no_init+no_mesh_path', 'mesh_nul+no_init', 'mesh_nul+no_source_inputs', 'dir_init+no_source',
    'dir_init+unreadable_sources',
    'bank_sha+candidate_sha', 'candidate_sha+admission_sha', 'admission_sha+table_sha', 'table_sha+scenario_sha',
    'scenario_sha+head_sha',
)
# A name that is not UTF-8, which Node reads back as U+FFFD; macOS refuses to create it (EILSEQ).
BAD_UTF8_NAME = b'\xff.json'


def _write(root: Path, path: str, body: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding='utf-8')


def _runtime_tree(root: Path, runtime: str, dist_info: tuple[str, ...], simnibs: bool, link: bool) -> None:
    # A non-executable interpreter: the Linux fingerprint fails the same way (EACCES) for Node and Python.
    if link:
        _write(root, f'{runtime}/bin/python3.11', 'interpreter')
        (root / runtime / 'bin/python').symlink_to('python3.11')
    else:
        _write(root, f'{runtime}/bin/python', 'interpreter')
    for name in CONDA_META:
        _write(root, f'{runtime}/conda-meta/{name}', f'record {name}')
    for name in dist_info:
        _write(root, f'{runtime}/{SITE}/{name}/METADATA', f'metadata {name}')
    if simnibs:
        _write(root, f'{runtime}/{SITE}/simnibs/simulation/fem.py', 'fem')
        _write(root, f'{runtime}/{SITE}/simnibs/mesh_tools/mesh_io.py', 'mesh io')


def design_root(directory: Path, *, table: bool = False, scenarios: tuple[str, ...] = (), heads: tuple[str, ...] = (),
                runtime: Optional[str] = None, odd_pointers: bool = False, symlinked: bool = False,
                broken: Optional[str] = None, spelling: Optional[str] = None, lexical: bool = False,
                bad_utf8: bool = False, odd_bytes: bool = False) -> str:
    """A scientific root with placeholder files for every input of a design-evaluation context identity.

    The base tree is ``designContextRoot``'s. ``table`` adds the nominal scalp-node table, ``scenarios`` and
    ``heads`` their pointers and tables (as check-design-decision.mjs builds them), ``runtime`` a fake
    ``simnibs`` (SimNIBS), ``compute-linux-64`` (table runtime), ``both`` or ``dangling`` (a broken
    ``bin/python`` link) tree, ``odd_pointers`` raw pointer strings that are not normalized, ``symlinked`` returns
    a symbolic link to the tree instead of the tree, and ``broken`` breaks one thing (``BREAKS``) or two
    (``'a+b'``, ``COMBINED``).

    The others are about how Node resolves real paths (``eeglayoutlab.jobs.nodefs``). ``spelling`` returns the
    root in another letter case (``upper-root``) or Unicode normalization (``nfd-root``, the tree being named
    ``trée`` in NFC), or keeps it and links ``data/sources.npz`` to a target that spells the root that way
    (``upper-link``, ``nfd-link``); on a case- and normalization-insensitive volume (macOS) the spelled path is the
    same file, elsewhere it does not exist. ``lexical`` returns a link whose target has ``..`` after a symbolic
    link: the kernel reaches the tree, ``fs.realpathSync`` a decoy copy whose ``paths.py`` differs.
    ``bad_utf8`` adds a conda record named ``BAD_UTF8_NAME`` where the file system allows it. ``odd_bytes``
    puts bytes that are not UTF-8 in a string of the admission pointer (Node reads them as U+FFFD) and makes
    ``source_inputs`` the escape of a lone surrogate, which Node opens as the file named U+FFFD.
    Returns the root string to configure.
    """
    names = set(broken.split('+')) if broken else set()
    assert names <= set(BREAKS)
    assert spelling in (None, 'upper-root', 'nfd-root', 'upper-link', 'nfd-link')
    directory.mkdir(parents=True, exist_ok=True)
    root = directory / ('tr\u00e9e' if spelling in ('nfd-root', 'nfd-link') else 'tree')
    root.mkdir()
    pointer = {'path': BANK, 'candidates': 'data/candidates.npz', 'report': 'data/report.json', 'sha256': digest('bank')}
    config = {'mesh_path': 'data/head.msh', 'external_node_mapping_path': 'data/scalp/mapping.npy'}
    manifest = {'source_inputs': 'data/sources.npz'}
    admission = {'path': 'data/admission.npz', 'sha256': digest('mask'), 'geometry_sha256': digest('candidates'),
                 'schema_version': 'native-external-exposure/1'}
    report = {'candidate_sha256': digest('candidates')}
    if odd_pointers:
        # Raw strings are digest keys verbatim; join and dirname normalize only the paths Node builds from them.
        pointer['path'] = './results//v2/bank/runs/r/batches/b/bank.npz'
        pointer['candidates'] = str(root / 'data/candidates.npz')  # absolute: InputIntegrity resolves it as is
        manifest['source_inputs'] = 'data/x/../sources.npz'
        config['mesh_path'] = 'data/head.msh/'
        config['external_node_mapping_path'] = 'data//scalp/./mapping.npy'
    if 'report_absolute' in names:
        # Digested through resolve (absolute wins), but read through join(root, ...): the read fails.
        pointer['report'] = str(root / 'data/report.json')
    if 'bank_sha' in names:
        pointer['sha256'] = digest('another bank')
    if 'candidate_sha' in names:
        report['candidate_sha256'] = digest('other candidates')
    if 'admission_sha' in names:
        admission['sha256'] = digest('another mask')
    if 'admission_geometry' in names:
        # The mask file is intact, but it was screened for other candidates.
        admission['geometry_sha256'] = digest('old candidates')
    if 'mesh_null' in names:
        config['mesh_path'] = None
    if 'mesh_nul' in names:
        config['mesh_path'] = 'data/head.msh\0'
    if 'no_mesh_path' in names:
        del config['mesh_path']
    if 'no_source_inputs' in names:
        del manifest['source_inputs']
    if odd_bytes:
        admission['note'] = 'NOT-UTF-8'
        manifest['source_inputs'] = 'data/\ud800.npz'
    files = {
        'results/v2/current_multiregion_bank.json': jsjson.stringify(pointer),
        'results/v2/current_surface_admissibility.json': jsjson.stringify(admission),
        'data/admission.npz': 'mask', BANK: 'bank', 'data/candidates.npz': 'candidates',
        'data/report.json': jsjson.stringify(report),
        'results/v2/bank/runs/r/run_manifest.json': jsjson.stringify(manifest),
        'configs/ernie_fem_point_pilot.json': jsjson.stringify(config),
        'data/head.msh': 'mesh', 'data/scalp/mapping.npy': 'mapping', 'data/scalp/external_scalp_vertices_m.npy': 'vertices',
        'data/scalp/external_scalp_triangles.npy': 'triangles', 'data/sources.npz': 'sources',
        'webapp/public/models/ernie/source-roi.json': 'atlas',
    }
    for name in ('__init__', 'paths', 'design_evaluation', 'head_model', 'reception_forward_provider', 'shared_native_forward',
                 'scalp_node_table', 'head_package', 'design_robustness', 'data_prior', 'eeg_recording'):
        files[f'src/compact_eeg/workflows/{name}.py'] = 'code'
    for path in ('scripts/design_evaluation.py', 'scripts/inspect_ernie_cortical_forward.py', 'src/compact_eeg/cortical_fem.py',
                 'src/compact_eeg/surface_admissibility.py', 'src/compact_eeg/layout_search_metrics.py', 'src/compact_eeg/noise_models.py',
                 'src/compact_eeg/metrics.py', 'src/compact_eeg/prototype_localization.py', 'src/compact_eeg/inverse_pilot.py'):
        files[path] = 'code'
    if table or scenarios or heads:
        files[f'{TABLE_DIR}/manifest.json'] = 'manifest'
        files[f'{TABLE_DIR}/index.npz'] = 'index'
        files[f'{TABLE_DIR}/rows.npy'] = 'rows'
        files['results/v2/current_scalp_node_table.json'] = jsjson.stringify({
            'schema': 'scalp-node-superposition/1', 'table_id': 't' * 64, 'manifest_path': f'{TABLE_DIR}/manifest.json',
            'manifest_sha256': digest('another manifest' if 'table_sha' in names else 'manifest')})
    if scenarios:
        files['configs/conductivity_scenarios.json'] = 'scenarios'
    for name in scenarios:
        scenario_dir = f'results/v2/scalp_node_table_scenarios/{name}/' + 's' * 64
        for part in ('manifest.json', 'index.npz', 'rows.npy'):
            files[f'{scenario_dir}/{part}'] = f'scenario {name} {part}'
        wrong = 'scenario_sha' in names and name == SCENARIOS[0]
        files[f'results/v2/scalp_node_table_scenarios/{name}/current.json'] = jsjson.stringify({
            'schema': 'scalp-node-superposition/1', 'table_id': 's' * 64, 'manifest_path': f'{scenario_dir}/manifest.json',
            'manifest_sha256': digest('changed' if wrong else f'scenario {name} manifest.json')})
    for head_id in heads:
        head = f'results/v2/heads/{head_id}'
        head_table = f'{head}/table/' + 'h' * 64
        for name in ('package.json', 'scalp.npz', 'admissibility.npz', 'sources.npz', 'mapping.npz'):
            files[f'{head}/{name}'] = f'{head_id} {name}'
        for part in ('manifest.json', 'index.npz', 'rows.npy'):
            files[f'{head_table}/{part}'] = f'head {head_id} {part}'
        wrong = 'head_sha' in names and head_id == HEADS[0]
        files[f'{head}/table.json'] = jsjson.stringify({
            'schema': 'scalp-node-superposition/1', 'table_id': 'h' * 64, 'manifest_path': f'{head_table}/manifest.json',
            'manifest_sha256': digest('changed' if wrong else f'head {head_id} manifest.json')})
    table_pointer = 'results/v2/current_scalp_node_table.json'
    scenario_pointer = f'results/v2/scalp_node_table_scenarios/{SCENARIOS[0]}/current.json'
    head_pointer = f'results/v2/heads/{HEADS[0]}/table.json'
    admission_pointer = 'results/v2/current_surface_admissibility.json'
    corrupt = '{"schema":"scalp-node-superposition/1","manifest_path":'  # a pointer cut short while written
    for name, path, body in (('table_corrupt', table_pointer, corrupt), ('scenario_corrupt', scenario_pointer, corrupt),
                             ('head_corrupt', head_pointer, corrupt), ('table_array', table_pointer, '[]'),
                             ('table_string', table_pointer, '"x"'), ('table_object', table_pointer, '{}'),
                             ('table_false', table_pointer, 'false'), ('table_zero', table_pointer, '0'),
                             ('table_empty', table_pointer, '""'), ('table_null', table_pointer, 'null'),
                             ('scenario_false', scenario_pointer, 'false'), ('scenario_null', scenario_pointer, 'null'),
                             ('head_zero', head_pointer, '0'), ('head_null', head_pointer, 'null'),
                             ('admission_null', admission_pointer, 'null'),
                             ('admission_bom', admission_pointer, '\ufeff' + files[admission_pointer])):
        if name in names:
            files[path] = body
    for path, body in files.items():
        _write(root, path, body)
    if odd_bytes:
        text = (root / admission_pointer).read_bytes()
        (root / admission_pointer).write_bytes(text.replace(b'NOT-UTF-8', b'a\xffb\xed\xa0\x80c\xc3'))
        _write(root, 'data/\ufffd.npz', 'sources')
        (root / 'data/sources.npz').unlink()
    if 'unreadable_sources' in names:
        (root / 'data/sources.npz').chmod(0)
    for name, path in (('table_dir', table_pointer), ('scenario_dir', scenario_pointer), ('head_dir', head_pointer),
                       ('dir_init', 'src/compact_eeg/workflows/__init__.py')):
        if name in names:
            (root / path).unlink()
            (root / path).mkdir()
    if 'no_pointer' in names:
        (root / 'results/v2/current_multiregion_bank.json').unlink()
    if 'no_source' in names:
        (root / 'data/sources.npz').unlink()
    if 'no_init' in names:
        (root / 'src/compact_eeg/workflows/__init__.py').unlink()
    # A link out of the project; for escape_prefix its target shares the root's string prefix (tree-outside).
    for name, outside in (('escape', directory / 'outside-sources.npz'),
                          ('escape_prefix', directory / f'{root.name}-outside/sources.npz')):
        if name in names:
            outside.parent.mkdir(exist_ok=True)
            outside.write_text('sources', encoding='utf-8')
            (root / 'data/sources.npz').unlink()
            (root / 'data/sources.npz').symlink_to(outside)
    if spelling in ('upper-link', 'nfd-link'):
        # An absolute link inside the project whose target spells the root differently.
        (root / 'data/real-sources.npz').write_text('sources', encoding='utf-8')
        (root / 'data/sources.npz').unlink()
        spelled = str(directory / root.name.upper()) if spelling == 'upper-link' else unicodedata.normalize('NFD', str(root))
        (root / 'data/sources.npz').symlink_to(spelled + '/data/real-sources.npz')
    if runtime in ('simnibs', 'both'):
        _runtime_tree(root, NATIVE, NATIVE_DIST_INFO, simnibs=True, link=True)
    if runtime in ('compute-linux-64', 'both'):
        _runtime_tree(root, TABLE_RUNTIME, TABLE_DIST_INFO, simnibs=False, link=False)
    if runtime == 'dangling':
        (root / NATIVE / 'bin').mkdir(parents=True)
        (root / NATIVE / 'bin/python').symlink_to('python3.11')
    if runtime is not None and runtime not in ('simnibs', 'both', 'compute-linux-64', 'dangling'):
        raise ValueError(runtime)
    # A second spelling of the managed interpreter, through a link in the tree.
    if runtime in ('simnibs', 'both'):
        (root / 'py-link').symlink_to(f'{NATIVE}/bin/python')
    if bad_utf8:
        try:
            descriptor = os.open(os.fsencode(root / NATIVE / 'conda-meta') + b'/' + BAD_UTF8_NAME,
                                 os.O_WRONLY | os.O_CREAT, 0o644)
        except OSError:
            pass  # EILSEQ on macOS
        else:
            os.write(descriptor, b'record')
            os.close(descriptor)
    if symlinked:
        link = directory / 'link'
        link.symlink_to(root)
        return str(link)
    if lexical:
        # link -> alias/../real, alias -> deep/b: the kernel reads deep/real (the tree), realpathSync real (a decoy).
        decoy = directory / 'decoy'
        shutil.copytree(root, decoy, symlinks=True)
        (decoy / 'src/compact_eeg/workflows/paths.py').write_text('decoy code', encoding='utf-8')
        (directory / 'deep/b').mkdir(parents=True)
        (directory / 'deep/real').symlink_to(root)
        (directory / 'alias').symlink_to(directory / 'deep/b')
        (directory / 'real').symlink_to(decoy)
        (directory / 'link').symlink_to('alias/../real')
        return str(directory / 'link')
    if spelling == 'upper-root':
        return str(directory / root.name.upper())
    if spelling == 'nfd-root':
        return unicodedata.normalize('NFD', str(root))
    return str(root)


def _broken_options(broken: str) -> dict:
    names = broken.split('+')
    if any(name.startswith(('scenario_', 'head_')) for name in names):
        return {'broken': broken, 'table': True, 'scenarios': SCENARIOS, 'heads': HEADS}
    return {'broken': broken, 'table': any(name.startswith('table_') for name in names)}


# --- Cases -------------------------------------------------------------------------------------------------------

ROOTS: dict[str, dict] = {
    'base': {},
    'table': {'table': True},
    'full': {'table': True, 'scenarios': SCENARIOS, 'heads': HEADS},
    'simnibs': {'runtime': 'simnibs'},
    'linux64': {'runtime': 'compute-linux-64'},
    'both': {'runtime': 'both', 'table': True},
    'dangling': {'runtime': 'dangling'},
    'odd': {'odd_pointers': True, 'table': True},
    'symlinked': {'runtime': 'simnibs', 'symlinked': True},
    'lexical': {'lexical': True},
    'upper-root': {'spelling': 'upper-root'},
    'nfd-root': {'spelling': 'nfd-root'},
    'upper-link': {'spelling': 'upper-link'},
    'nfd-link': {'spelling': 'nfd-link'},
    'bad-utf8': {'runtime': 'simnibs', 'bad_utf8': True},
    'odd-bytes': {'odd_bytes': True},
    **{f'broken-{name}': _broken_options(name) for name in (*BREAKS, *COMBINED)},
}

# Interpreter configurations: the queue's explicit python, EEG_COMPUTE_PYTHON, or a direct scientificContext call
# with a given interpreter string. In `direct`, '{root}' is replaced by the configured root string.
CONFIGS: dict[str, dict] = {
    'default': {},
    'explicit': {'python': '/explicit/python'},
    'env': {'env': {'EEG_COMPUTE_PYTHON': '/env/python'}},
    'env-empty': {'env': {'EEG_COMPUTE_PYTHON': ''}},
    'explicit-empty': {'python': '', 'env': {'EEG_COMPUTE_PYTHON': '/env/python'}},
    'direct-exact': {'direct': '{root}/.runtime/simnibs-4.6.0/bin/python'},
    'direct-dot': {'direct': '{root}/./.runtime/simnibs-4.6.0/bin/python'},
    'direct-dotdot': {'direct': '{root}/.runtime/simnibs-4.6.0/bin/../bin/python'},
    'direct-link': {'direct': '{root}/py-link'},
    'direct-realpath': {'direct': '{real}/.runtime/simnibs-4.6.0/bin/python'},
    'direct-table': {'direct': '{root}/.runtime/compute-linux-64/bin/python'},
}

ROOT_CONFIGS: dict[str, tuple[str, ...]] = {
    'base': ('default', 'explicit', 'env', 'env-empty', 'explicit-empty'),
    'simnibs': ('default', 'explicit', 'env', 'env-empty', 'explicit-empty', 'direct-exact', 'direct-dot', 'direct-dotdot', 'direct-link'),
    'linux64': ('default', 'env', 'explicit'),
    'both': ('default', 'direct-table'),
    'symlinked': ('default', 'direct-realpath'),
    'dangling': ('default', 'env'),
}

_GRID = [[(i % 8) * 6.0, (i // 8) * 6.0, 0.0] for i in range(64)]
_DESIGN = {'schema': 'eeg-electrode-design/1', 'coordinate_system': 'ernie_native_mm', 'unit': 'mm', 'name': 'test',
           'xyz_mm': _GRID, 'region_indices': [float(i >= 32) for i in range(64)]}
EVALUATE = {'action': 'evaluate', 'design': _DESIGN, 'radius_mm': 6.0, 'seed': 42.0}
PRIOR = {'region_gain': [1.037, 2.829, 0.09946, 1.344, 0.4122, 1.072, 0.09946], 'rho': 0.2, 'length_mm': 20.0}
SPATIAL = {'kind': 'spatial', 'rho': 0.5, 'length_mm': 20.0}

def _nested(value: Any, depth: int) -> Any:
    for _ in range(depth):
        value = [value]
    return value


# Each option alone and the combinations that reach several rows, the reception v2 `forward` context ({}), and
# requests the normalizer would refuse, for the truthiness and name rules of scientificContext itself.
REQUESTS: dict[str, Any] = {
    'empty': {},
    'evaluate': EVALUATE,
    'perturb': {**EVALUATE, 'action': 'perturb'},
    'robustness': {**EVALUATE, 'robustness': 'standard/1'},
    'data_prior': {**EVALUATE, 'data_prior': PRIOR},
    'noise_model': {**EVALUATE, 'noise_model': SPATIAL},
    'scenario': {**EVALUATE, 'conductivity_scenario': 'skull_x2'},
    'scenario-x0.5': {**EVALUATE, 'conductivity_scenario': 'skull_x0.5'},
    'head': {**EVALUATE, 'head_id': 'ixi002'},
    'scenario+data_prior': {**EVALUATE, 'conductivity_scenario': 'skull_x2', 'data_prior': PRIOR},
    'scenario+head': {**EVALUATE, 'conductivity_scenario': 'skull_x2', 'head_id': 'ixi002'},
    'robustness+data_prior': {**EVALUATE, 'robustness': 'standard/1', 'data_prior': PRIOR},
    'forward_mode': {**EVALUATE, 'forward_mode': 'scalp_node_table'},
    'bad-scenario': {**EVALUATE, 'conductivity_scenario': 'Skull_x2'},
    'bad-scenario-newline': {**EVALUATE, 'conductivity_scenario': 'skull_x2\n'},
    'bad-head': {**EVALUATE, 'head_id': 'IXI002'},
    'bad-head-newline': {**EVALUATE, 'head_id': 'ixi002\n'},
    'bad-head-dot': {**EVALUATE, 'head_id': 'ixi.002'},
    'bad-scenario-dash': {**EVALUATE, 'conductivity_scenario': 'skull-x2'},
    'scenario-object': {**EVALUATE, 'conductivity_scenario': {}},
    'scenario-tostring': {**EVALUATE, 'conductivity_scenario': {'toString': 1.0}},
    'head-tostring': {**EVALUATE, 'head_id': {'toString': 'ixi002'}},
    'head-array': {**EVALUATE, 'head_id': ['ixi002']},
    'head-deep-array': {**EVALUATE, 'head_id': _nested('ixi002', 1000)},
    'head-empty-array-first': {**EVALUATE, 'head_id': [[], 'ixi002']},  # String() gives ',ixi002'
    'scenario-number': {**EVALUATE, 'conductivity_scenario': 2.0},
    'robustness-object': {**EVALUATE, 'robustness': {}},
    'data_prior-zero': {**EVALUATE, 'data_prior': 0.0},
    'data_prior-empty-list': {**EVALUATE, 'data_prior': []},
    'scenario-empty': {**EVALUATE, 'conductivity_scenario': ''},
    'null': None,
}


def canonical_requests() -> dict[str, Any]:
    """Every accepted design-evaluation variant of the phase 1 corpus, as Node's canonical request."""
    if CORPUS is None:
        return {}
    return {f'canonical-{variant["name"]}': jsjson.parse(variant['canonical'])['request']
            for variant in CORPUS['formats']['design-evaluation']['variants'] if variant['accepted']}


@dataclass(frozen=True)
class Case:
    id: str
    root: str
    config: str
    request: str


def synthetic_cases() -> list[Case]:
    cases = []
    for root in ROOTS:
        for config in ROOT_CONFIGS.get(root, ('default',)):
            for request in REQUESTS:
                cases.append(Case(f'{root}/{config}/{request}', root, config, request))
    for root in ('base', 'full'):
        for request in canonical_requests():
            cases.append(Case(f'{root}/default/{request}', root, 'default', request))
    return cases


def all_requests() -> dict[str, Any]:
    return {**REQUESTS, **canonical_requests()}


def spec_case(case: Case, root: str, real: str, requests: dict[str, Any]) -> dict:
    """The driver's case: {id, root, python?, env?, direct?, request}."""
    config = CONFIGS[case.config]
    entry: dict[str, Any] = {'id': case.id, 'root': root}
    if 'python' in config:
        entry['python'] = config['python']
    if 'env' in config:
        entry['env'] = config['env']
    if 'direct' in config:
        entry['direct'] = {'python': config['direct'].replace('{root}', root).replace('{real}', real)}
    entry['request'] = requests[case.request]
    return entry


# One thread-pool worker: libuv then runs the queued file requests strictly in order, so when two inputs fail
# Node reports the same one every time (InputIntegrity.digest_all reproduces that order). With the default pool
# of 4, an input can reach its open or read before another finishes an earlier step, and such pairs come out
# either way (about 1-3% of runs for an unreadable file against a directory); keys never depend on it.
NODE_ENV = {**os.environ, 'UV_THREADPOOL_SIZE': '1'}


def run_node(cases: list[dict], scratch: Path, reuse: bool = False) -> dict:
    """Runs the Node driver once over every case; returns its output with the cases by id."""
    queue = scratch / 'node-queue'  # resolved by the constructors, never created
    spec_path, out_path = scratch / 'spec.json', scratch / 'node.json'
    spec_path.write_text(jsjson.stringify({'queueDirectory': str(queue), 'reuse': reuse, 'cases': cases}), encoding='utf-8')
    subprocess.run(['node', str(DRIVER), str(spec_path), str(out_path)], check=True, cwd=ROOT, env=NODE_ENV)
    output = json.loads(out_path.read_text(encoding='utf-8'))
    assert not queue.exists()
    output['by_id'] = {case['id']: case for case in output['cases']}
    return output


def _error(error: BaseException) -> dict:
    """A Python failure in the compared form: by Node's code, by ``SyntaxError`` for text that is not JSON (V8's
    messages are not reproduced), or by Node's message (``IdentityError``, ``JSTypeError``)."""
    code = getattr(error, 'code', None)
    if isinstance(code, str):  # ERR_INVALID_ARG_TYPE, ERR_INVALID_ARG_VALUE
        return {'code': code}
    if isinstance(error, OSError) and error.errno in errno.errorcode:
        return {'code': errno.errorcode[error.errno]}
    if isinstance(error, jsjson.JSONSyntaxError):
        return {'name': 'SyntaxError'}
    if isinstance(error, (IdentityError, JSTypeError)):
        return {'message': str(error)}
    return {'unexpected': f'{type(error).__name__}: {error}'}


def node_outcome(result: dict) -> dict:
    """A driver result in the compared form: errors with a code by code (system errors carry absolute paths),
    a ``SyntaxError`` by name, the others by message."""
    if result['ok']:
        return result
    outcome = {'id': result['id'], 'ok': False}
    if 'config' in result:
        outcome['config'] = result['config']
    if result['code']:
        outcome['code'] = result['code']
    elif result.get('name') == 'SyntaxError':
        outcome['name'] = 'SyntaxError'
    else:
        outcome['message'] = result['message']
    return outcome


class PythonCases:
    """``eeglayoutlab.jobs`` over driver cases. With ``reuse``, one InputIntegrity per root configuration."""

    def __init__(self, reuse: bool = False):
        self.reuse = reuse
        self._inputs: dict[str, InputIntegrity] = {}

    def run(self, case: dict) -> dict:
        outcome: dict[str, Any] = {'id': case['id'], 'ok': False}
        try:
            config = runtime_config(case['root'], case.get('python'), env=case.get('env', {}))
            if self.reuse and config.repository_root in self._inputs:
                inputs = self._inputs[config.repository_root]
            else:
                InputIntegrity(config.repository_root)  # the queue's own, as LocalComputeQueue builds one
                inputs = self._inputs[config.repository_root] = InputIntegrity(config.repository_root)
            outcome['config'] = {'repositoryRoot': config.repository_root, 'python': config.python,
                                 'nativePython': config.native_python}
            python = case['direct']['python'] if 'direct' in case else config.native_python
            context = design_context(config.repository_root, python, inputs, case['request'])
        except Exception as error:  # noqa: BLE001 - every failure is compared with Node's
            outcome.update(_error(error))
            return outcome
        return {'id': case['id'], 'ok': True, 'config': outcome['config'], 'identity': jsjson.stringify(context.identity),
                'admission': jsjson.stringify(context.admission), 'key': context.key}


def build_roots(base: Path) -> dict[str, tuple[str, str]]:
    """Every root in ROOTS under ``base``: name -> (configured root string, real path of the tree)."""
    roots = {}
    for name, options in ROOTS.items():
        root = design_root(base / name, **options)
        roots[name] = (root, os.path.realpath(root))
    return roots
