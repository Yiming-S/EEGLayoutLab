"""Guards for key equality (plan B11, B21, B7).

- B21: the service never writes hashed or stored JSON with Python's ``json`` (``1.0``, ``1e-07``, insertion-order
  integer keys, ``ensure_ascii``), so ``eeglayoutlab.jobs`` and ``eeglayoutlab.server`` do not import it.
- B11: phase 2 changes no identity input by accident. ``identity_inputs.json`` records the SHA-256 of every file
  in git whose bytes Node hashes into a request key; a deliberate science change updates it in the same commit:
  ``python tests/service/test_guards.py --write``.
- B7: key strings are built with ``nodepath``, never ``os.path``.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / 'src/eeglayoutlab'
MANIFEST = Path(__file__).with_name('identity_inputs.json')
# The OpenAPI document is a pretty-printed contract file (contracts/generated/openapi.json), never hashed into a
# key or stored as a record; JSON.stringify cannot indent it, so it keeps json.dumps.
JSON_ALLOWED = {'server/openapi.py'}


def _imports_json(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(alias.name == 'json' or alias.name.startswith('json.') for alias in node.names):
            lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and (
                node.module == 'json' or node.module.startswith('json.')):
            lines.append(node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == '__import__' and node.args \
                and isinstance(node.args[0], ast.Constant) and str(node.args[0].value).split('.')[0] == 'json':
            lines.append(node.lineno)
    return lines


def test_service_code_does_not_import_python_json():
    offenders = {}
    for directory in ('jobs', 'server', 'core', 'figures', 'cli'):
        for path in sorted((PACKAGE / directory).rglob('*.py')):
            relative = path.relative_to(PACKAGE).as_posix()
            lines = _imports_json(ast.parse(path.read_text(encoding='utf-8'), str(path)))
            if lines and relative not in JSON_ALLOWED:
                offenders[relative] = lines
    assert offenders == {}, 'use eeglayoutlab.schemas.jsjson for hashed or stored JSON'
    assert (PACKAGE / 'jobs/identity.py').is_file()


def test_the_json_guard_sees_every_import_form():
    for source in ('import json', 'import json.decoder', 'from json import dumps', 'from json.decoder import scanstring',
                   'import os, json as j', 'x = __import__("json")'):
        assert _imports_json(ast.parse(source)), source
    for source in ('from . import jsjson', 'from ..schemas import jsjson', 'import jsonschema', 'from .json import x'):
        assert not _imports_json(ast.parse(source)), source


def test_key_strings_are_not_built_with_os_path():
    # The identity module builds every key string; os.path, posixpath and pathlib spell paths differently from Node.
    banned = ('os.path', 'posixpath', 'pathlib')
    lines = []
    for node in ast.walk(ast.parse((PACKAGE / 'jobs/identity.py').read_text(encoding='utf-8'))):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and f'{node.value.id}.{node.attr}' in banned:
            lines.append(node.lineno)
        elif isinstance(node, ast.Import) and any(alias.name in banned for alias in node.names):
            lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and (node.module in banned or node.module == 'os' and
                                                   any(alias.name == 'path' for alias in node.names)):
            lines.append(node.lineno)
    assert lines == []


# --- Identity inputs (B11) --------------------------------------------------------------------------------------

def identity_inputs() -> list[str]:
    """Every file in git whose bytes enter a Node request key (rule 5 of the phase 2 plan):

    - radius ``codeIdentity``: the script, the configuration and every top-level ``src/compact_eeg/*.py`` (so a
      new module changes every radius key and fails here);
    - the workflow lists and ``DATA_PRIOR_FILES``;
    - the fixed code files of the design, editor and reception (v1 and v2 ``code``) identities;
    - the worker inputs under ``webapp/public/models`` and ``webapp/public/data`` (library records and ROI files).
    The pointers and data under ``results/`` are not in git, and CI has none.
    """
    from eeglayoutlab.jobs.identity import (
        DATA_PRIOR_FILES, DESIGN_WORKFLOW, EDITOR_WORKFLOW, RECEPTION_V2_WORKFLOW, RECEPTION_WORKFLOW,
    )
    paths = {'scripts/run_local_radius_compute.py', 'configs/single_head_optimization.json'}
    paths |= {f'src/compact_eeg/{entry.name}' for entry in (ROOT / 'src/compact_eeg').iterdir() if entry.name.endswith('.py')}
    paths |= {*DESIGN_WORKFLOW, *RECEPTION_WORKFLOW, *RECEPTION_V2_WORKFLOW, *EDITOR_WORKFLOW, *DATA_PRIOR_FILES}
    # webapp/server/runtime/scientific-context.mjs
    paths |= {'src/compact_eeg/surface_admissibility.py', 'scripts/design_evaluation.py', 'scripts/inspect_ernie_cortical_forward.py',
              'src/compact_eeg/cortical_fem.py', 'src/compact_eeg/layout_search_metrics.py', 'src/compact_eeg/noise_models.py',
              'src/compact_eeg/metrics.py', 'src/compact_eeg/prototype_localization.py', 'src/compact_eeg/inverse_pilot.py',
              'configs/ernie_fem_point_pilot.json', 'configs/conductivity_scenarios.json',
              'src/compact_eeg/workflows/design_robustness.py'}
    # webapp/server/electrode-editor-server.mjs, source-reception-server.mjs, reception-v2-support.mjs
    paths |= {'scripts/electrode_editor.py', 'scripts/source_reception.py', 'scripts/run_source_reception.py',
              'scripts/source_reception_v2.py', 'scripts/run_source_reception_v2.py', 'scripts/reception_forward_provider.py',
              'scripts/inspect_reception_runtime.py', 'src/compact_eeg/workflows/source_roi.py',
              'webapp/public/models/ernie/source-roi.json', 'webapp/public/models/ernie/source-roi-definition.json'}
    # runtime/identity-cache.mjs runs the snapshot inspector when it is readable (else inspect_reception_runtime.py):
    # its output, not its bytes, is numerical_runtime_sha256 in every reception v2 key (B15).
    paths |= {'scripts/inspect_reception_runtime_snapshot.py'}
    for directory in ('webapp/public/models', 'webapp/public/data'):
        paths |= {path.relative_to(ROOT).as_posix() for path in (ROOT / directory).rglob('*')
                  if path.is_file() and not path.name.startswith('.')}
    return sorted(paths)


def _sha256(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def manifest() -> dict[str, str]:
    return {path: _sha256(path) for path in identity_inputs()}


def test_identity_inputs_are_unchanged():
    recorded = json.loads(MANIFEST.read_text(encoding='utf-8'))
    assert sorted(recorded) == identity_inputs(), 'the set of identity inputs changed; see the module docstring'
    changed = sorted(path for path, sha in recorded.items() if _sha256(path) != sha)
    assert changed == [], 'these identity inputs changed bytes, which changes request keys; see the module docstring'


if __name__ == '__main__' and sys.argv[1:] == ['--write']:
    sys.path.insert(0, str(ROOT / 'src'))
    MANIFEST.write_text(json.dumps(manifest(), indent=2) + '\n', encoding='utf-8')
    print(f'wrote {MANIFEST.relative_to(ROOT)}')
