"""The design-evaluation identity and request key: Node's ``runtime/scientific-context.mjs``, statement by statement.

``request_key(request, identity)`` is ``sha256(JSON.stringify({request, identity}))``. ``design_context`` returns
the identity, the surface-admission pointer and that key for a request, with the bytes Node's
``DesignEvaluationService.context`` gives on the same root with the same interpreter string. The identity is a
plain dict built in Node's member order, so ``jsjson.stringify`` writes Node's text.

Rules that keep the keys equal (design 0001 phase 2 plan, section 4):

- raw pointer strings (``p.path``, ``config.mesh_path``, ``manifest.source_inputs`` ...) are digest keys
  verbatim; the paths Node builds use ``nodepath`` (B7);
- pointers are read at ``nodepath.join(root, x)`` without a containment check, and digests go through
  ``InputIntegrity`` (B8), all files at once as Node's ``Promise.all`` (``InputIntegrity.digest_all``);
- failures carry Node's code (``ENOENT``, ``EISDIR``, ``ERR_INVALID_ARG_TYPE`` ...) or message: only a missing
  optional pointer (``ENOENT``) is tolerated, and a pointer that is a directory or not JSON fails as in Node;
- only the JavaScript truthiness of ``conductivity_scenario``, ``head_id``, ``robustness`` and ``data_prior``
  is read, and the names are checked with ``re.fullmatch`` (JavaScript's ``$`` is the end of the text) (B12);
- the managed-runtime rows are added only when ``python`` is exactly ``nodepath.join(root, runtime, 'bin/python')``,
  and directory listings are filtered and sorted as Node's (B6);
- ``python`` is ``RuntimeConfig.native_python``, never the service's own interpreter (B5).
"""
from __future__ import annotations

import math
import re
from typing import Any, NamedTuple

from ..schemas import jsjson
from . import nodefs, nodepath
from .fingerprint import runtime_identity
from .runtime import NATIVE_RUNTIME_RELATIVE, TABLE_RUNTIME_RELATIVE

__all__ = [
    'WORKFLOW_BASE', 'DESIGN_WORKFLOW', 'RECEPTION_WORKFLOW', 'RECEPTION_V2_WORKFLOW', 'EDITOR_WORKFLOW',
    'DATA_PRIOR_FILES', 'DESIGN_CACHE_SCHEMA', 'IdentityError', 'JSTypeError', 'DesignContext', 'js_truthy',
    'request_key',
    'design_context',
]

# webapp/server/project-paths.mjs:16-38. Actual implementations must be fingerprinted, not just legacy CLI shims.
_WORKFLOWS = 'src/compact_eeg/workflows/'
WORKFLOW_BASE = (_WORKFLOWS + '__init__.py', _WORKFLOWS + 'paths.py')
DESIGN_WORKFLOW = (
    *WORKFLOW_BASE,
    _WORKFLOWS + 'design_evaluation.py',
    _WORKFLOWS + 'head_model.py',
    _WORKFLOWS + 'reception_forward_provider.py',
    _WORKFLOWS + 'shared_native_forward.py',
    _WORKFLOWS + 'scalp_node_table.py',
    _WORKFLOWS + 'head_package.py',
)
RECEPTION_WORKFLOW = (_WORKFLOWS + '__init__.py', _WORKFLOWS + 'source_reception.py')
RECEPTION_V2_WORKFLOW = (
    *WORKFLOW_BASE,
    _WORKFLOWS + 'source_reception.py',
    _WORKFLOWS + 'source_reception_v2.py',
    _WORKFLOWS + 'reception_forward_provider.py',
    _WORKFLOWS + 'shared_native_forward.py',
)
EDITOR_WORKFLOW = (_WORKFLOWS + 'electrode_editor.py',)
# webapp/contracts/scientific-options.mjs:110
DATA_PRIOR_FILES = (
    'src/compact_eeg/workflows/data_prior.py',
    'src/compact_eeg/workflows/eeg_recording.py',
    'webapp/public/models/ernie/source-roi.json',
)

DESIGN_CACHE_SCHEMA = 'design-evaluation-cache/1'
_BANK_POINTER = 'results/v2/current_multiregion_bank.json'
_ADMISSION_POINTER = 'results/v2/current_surface_admissibility.json'
_TABLE_POINTER = 'results/v2/current_scalp_node_table.json'
_HEAD_PACKAGE_FILES = ('package.json', 'scalp.npz', 'admissibility.npz', 'sources.npz', 'mapping.npz', 'table.json')
# JavaScript's "." matches anything but a line terminator; its "$" (without the m flag) is the end of the text.
_JS_DOT = '[^\n\r\u2028\u2029]'
_SCENARIO_NAME = re.compile('[a-z0-9]+(?:[_.][a-z0-9]+)*')
_HEAD_ID = re.compile('[a-z0-9]+(?:[_-][a-z0-9]+)*')
_NATIVE_DIST_INFO = re.compile(f'(simnibs|cortech|numpy|scipy)-{_JS_DOT}*\\.dist-info')
_TABLE_DIST_INFO = re.compile(f'(cortech|llvmlite|nibabel|numba|numpy|scipy)-{_JS_DOT}*\\.dist-info')


class IdentityError(ValueError):
    """A scientific identity that cannot be formed; the message is Node's, verbatim."""


class JSTypeError(TypeError):
    """The ``TypeError`` V8 throws for the same input (a member of ``null``, an object without a string form);
    the message is V8's, verbatim."""


class DesignContext(NamedTuple):
    identity: dict
    admission: Any
    key: str


class _Undefined:
    """JavaScript ``undefined``: a member that is absent, which is not ``null``."""

    def __repr__(self) -> str:
        return 'undefined'


UNDEFINED = _Undefined()


def js_truthy(value: Any) -> bool:
    """JavaScript truthiness: ``{}`` and ``[]`` are true; only ``undefined``, ``null``, ``false``, ``0``, ``NaN``
    and ``''`` are false (Python's ``bool({})`` is ``False``)."""
    if value is None or value is UNDEFINED or value is False:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0 and not math.isnan(value)
    if isinstance(value, str):
        return value != ''
    return True


def _same(a: Any, b: Any) -> bool:
    """``a === b`` for parsed JSON values: no coercion, objects by identity."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if jsjson.is_number(a) and jsjson.is_number(b):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return a is b


def _member(value: Any, key: str) -> Any:
    """``value.key`` on parsed JSON: ``UNDEFINED`` for an absent member; ``null`` and ``undefined`` throw."""
    if value is None or value is UNDEFINED:
        raise JSTypeError(f"Cannot read properties of {'null' if value is None else 'undefined'} (reading '{key}')")
    if isinstance(value, dict):
        return value.get(key, UNDEFINED)
    return UNDEFINED


def _option(request: Any, key: str) -> Any:
    """``request?.key``."""
    if isinstance(request, dict):
        return request.get(key, UNDEFINED)
    return UNDEFINED


def _js_string(value: Any) -> str:
    """``String(value)`` for parsed JSON, as a template literal or ``RegExp.prototype.test`` converts it.

    An object converts through ``toString`` and then ``valueOf``. A parsed object with its own ``toString``
    member (a JSON value, never a function) skips it, and ``Object.prototype.valueOf`` returns the object, so V8
    throws; otherwise ``Object.prototype.toString`` gives ``[object Object]``.
    """
    if isinstance(value, str):
        return value
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if value is None:
        return 'null'
    if value is UNDEFINED:
        return 'undefined'
    if jsjson.is_number(value):
        number = jsjson.to_number(value)
        if math.isnan(number):
            return 'NaN'
        if math.isinf(number):
            return 'Infinity' if number > 0 else '-Infinity'
        return jsjson.number_to_string(number)
    if isinstance(value, (list, tuple)):
        return ','.join(_join_leaves(value))
    if isinstance(value, dict) and 'toString' in value:
        raise JSTypeError('Cannot convert object to primitive value')
    return '[object Object]'


_END = object()


def _join_leaves(value: list) -> list[str]:
    """The parts ``Array.prototype.join`` writes for ``value``, without recursion (V8 joins nested arrays thousands
    of levels deep). A nested array writes its own items, so the result is the leaves in order; an empty array is
    one empty part, and ``null`` and ``undefined`` are empty parts as well."""
    parts: list[str] = []
    stack = [iter(value)]
    while stack:
        item = next(stack[-1], _END)
        if item is _END:
            stack.pop()
        elif isinstance(item, (list, tuple)) and item:
            stack.append(iter(item))
        elif isinstance(item, (list, tuple)) or item is None or item is UNDEFINED:
            parts.append('')
        else:
            parts.append(_js_string(item))
    return parts



def _path(value: Any) -> Any:
    """A raw pointer member as Node passes it to ``path`` functions; ``undefined`` becomes ``None`` (a TypeError there)."""
    return None if value is UNDEFINED else value


def _read_json(root: str, relative: Any) -> Any:
    """``JSON.parse(await readFile(join(root, relative), 'utf8'))``: text that is not JSON raises
    ``jsjson.JSONSyntaxError`` where Node throws a ``SyntaxError``."""
    return jsjson.parse(nodefs.decode(nodefs.read_file(nodepath.join(root, _path(relative)))))


def request_key(request: Any, identity: Any) -> str:
    """``sha256(JSON.stringify({request, identity}))``, with ``request`` first."""
    return jsjson.sha256_hex({'request': request, 'identity': identity})


def _runtime_rows(root: str, runtime_root: str, python: str, dist_info: re.Pattern, simnibs: bool) -> list[str]:
    rows = [nodepath.relative(root, python)]
    metadata = nodepath.join(runtime_root, 'conda-meta')
    for name in nodepath.js_sort(n for n in nodefs.readdir(nodepath.join(root, metadata)) if n.endswith('.json')):
        rows.append(nodepath.join(metadata, name))
    site = nodepath.join(runtime_root, 'lib/python3.11/site-packages')
    for name in nodepath.js_sort(n for n in nodefs.readdir(nodepath.join(root, site)) if dist_info.fullmatch(n)):
        rows.append(nodepath.join(site, name, 'METADATA'))
    if simnibs:
        rows += [nodepath.join(site, 'simnibs/simulation/fem.py'), nodepath.join(site, 'simnibs/mesh_tools/mesh_io.py')]
    return rows


def design_context(root: str, python: str, inputs: Any, request: Any) -> DesignContext:
    """``scientificContext({root, python, inputs}, request)``: the shared frozen-model identity.

    ``root`` is the configured root string (``RuntimeConfig.repository_root``), ``python`` the native
    interpreter string (``RuntimeConfig.native_python``) and ``inputs`` an ``InputIntegrity`` of that root.
    Preserves Node's file order, so the serialized identity and key are Node's.
    """
    p = _read_json(root, _BANK_POINTER)
    admission = _read_json(root, _ADMISSION_POINTER)
    config = _read_json(root, 'configs/ernie_fem_point_pilot.json')
    files: list[Any] = [
        *DESIGN_WORKFLOW,
        _BANK_POINTER,
        _member(p, 'path'),
        _member(p, 'candidates'),
        _member(p, 'report'),
        _ADMISSION_POINTER, _member(admission, 'path'), 'src/compact_eeg/surface_admissibility.py',
        'scripts/design_evaluation.py',
        'scripts/inspect_ernie_cortical_forward.py',
        'src/compact_eeg/cortical_fem.py',
        'src/compact_eeg/layout_search_metrics.py',
        'src/compact_eeg/noise_models.py',
        'src/compact_eeg/metrics.py',
        'src/compact_eeg/prototype_localization.py',
        'src/compact_eeg/inverse_pilot.py',
        'configs/ernie_fem_point_pilot.json',
        _member(config, 'mesh_path'),
        _member(config, 'external_node_mapping_path'),
    ]
    manifest_path = nodepath.join(
        nodepath.dirname(nodepath.dirname(nodepath.dirname(_path(_member(p, 'path'))))),
        'run_manifest.json',
    )
    manifest = _read_json(root, manifest_path)
    scalp = nodepath.dirname(_path(_member(config, 'external_node_mapping_path')))
    files += [
        manifest_path,
        _member(manifest, 'source_inputs'),
        nodepath.join(scalp, 'external_scalp_vertices_m.npy'),
        nodepath.join(scalp, 'external_scalp_triangles.npy'),
    ]
    # A published scalp-node table replaces per-request FEM for new coordinates;
    # its pointer, manifest, index and full row bytes enter the identity.
    table: Any = None
    try:
        table = _read_json(root, _TABLE_POINTER)
    except FileNotFoundError:
        pass
    if js_truthy(table):
        directory = nodepath.dirname(_path(_member(table, 'manifest_path')))
        files += [_TABLE_POINTER, _member(table, 'manifest_path'),
                  nodepath.join(directory, 'index.npz'), nodepath.join(directory, 'rows.npy')]
    # A conductivity scenario adds its definition and its own published table.
    scenario_table: Any = None
    scenario = _option(request, 'conductivity_scenario')
    if js_truthy(scenario):
        if not _SCENARIO_NAME.fullmatch(_js_string(scenario)):
            raise IdentityError('电导率情景名称无效')
        # The worker checks scenario rows against the nominal table; without it, new coordinates would solve FEM
        # first and fail after.
        if not js_truthy(table):
            raise IdentityError('电导率情景评价需要名义头皮节点表，用于核对同一电极采样。')
        scenario_pointer = f'results/v2/scalp_node_table_scenarios/{_js_string(scenario)}/current.json'
        try:
            scenario_table = _read_json(root, scenario_pointer)
        except FileNotFoundError:
            raise IdentityError('该电导率情景的头皮节点表尚未预计算') from None
        directory = nodepath.dirname(_path(_member(scenario_table, 'manifest_path')))
        files += ['configs/conductivity_scenarios.json', scenario_pointer, _member(scenario_table, 'manifest_path'),
                  nodepath.join(directory, 'index.npz'), nodepath.join(directory, 'rows.npy')]
    # An additional head adds its package files and its own table only when requested.
    head_table: Any = None
    head_id = _option(request, 'head_id')
    if js_truthy(head_id):
        if not _HEAD_ID.fullmatch(_js_string(head_id)):
            raise IdentityError('头模编号无效')
        head = f'results/v2/heads/{_js_string(head_id)}'
        try:
            head_table = _read_json(root, nodepath.join(head, 'table.json'))
        except FileNotFoundError:
            raise IdentityError('该头模或其头皮节点表尚未预计算') from None
        directory = nodepath.dirname(_path(_member(head_table, 'manifest_path')))
        files += [f'{head}/{name}' for name in _HEAD_PACKAGE_FILES]
        files += [_member(head_table, 'manifest_path'),
                  nodepath.join(directory, 'index.npz'), nodepath.join(directory, 'rows.npy')]
    # The robustness module enters the identity only for requests that use it.
    if js_truthy(_option(request, 'robustness')):
        files.append('src/compact_eeg/workflows/design_robustness.py')
    if js_truthy(_option(request, 'data_prior')):
        files += DATA_PRIOR_FILES
    if python == nodepath.join(root, NATIVE_RUNTIME_RELATIVE, 'bin/python'):
        files += _runtime_rows(root, NATIVE_RUNTIME_RELATIVE, python, _NATIVE_DIST_INFO, simnibs=True)
    elif python == nodepath.join(root, TABLE_RUNTIME_RELATIVE, 'bin/python'):
        # The Linux table runtime has no SimNIBS; its conda records and the projection packages identify it.
        files += _runtime_rows(root, TABLE_RUNTIME_RELATIVE, python, _TABLE_DIST_INFO, simnibs=False)
    # Object.fromEntries(await Promise.all(...)): a repeated path keeps its first position.
    digests = inputs.digest_all([_path(path) for path in files])
    if not _same(digests[_member(p, 'path')], _member(p, 'sha256')):
        raise IdentityError('前向库身份不匹配')
    report = _read_json(root, _member(p, 'report'))
    if not _same(digests[_member(p, 'candidates')], _member(report, 'candidate_sha256')):
        raise IdentityError('候选坐标身份不匹配')
    if (not _same(digests[_member(admission, 'path')], _member(admission, 'sha256'))
            or not _same(_member(admission, 'geometry_sha256'), _member(report, 'candidate_sha256'))):
        raise IdentityError('外部表面筛选文件身份不匹配')
    if js_truthy(table) and not _same(digests[_member(table, 'manifest_path')], _member(table, 'manifest_sha256')):
        raise IdentityError('预计算头皮节点表身份不匹配')
    if (js_truthy(scenario_table)
            and not _same(digests[_member(scenario_table, 'manifest_path')], _member(scenario_table, 'manifest_sha256'))):
        raise IdentityError('电导率情景头皮节点表身份不匹配')
    if (js_truthy(head_table)
            and not _same(digests[_member(head_table, 'manifest_path')], _member(head_table, 'manifest_sha256'))):
        raise IdentityError('头模头皮节点表身份不匹配')
    runtime = runtime_identity(python)
    identity: dict[str, Any] = {
        'schema': DESIGN_CACHE_SCHEMA,
        'digests': digests,
        'python': python,
        'threads': 1,
    }
    if js_truthy(runtime):
        identity['runtime'] = runtime
    return DesignContext(identity=identity, admission=admission, key=request_key(request, identity))
