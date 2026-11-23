"""Node's messages and orders that the read-only library reproduces (phase 2 slice 3), against Node itself.

- Unit level, one Node run (``MESSAGES_DRIVER``): ``normalizeDesignRequest``'s refusal of every request of the
  design-evaluation schema corpus (and of the request inside a submission envelope) and of hand-made requests
  that reach each check alone and in pairs, against ``design_result.normalize_design_request``; ``util.inspect``
  of strings and the ``ERR_INVALID_ARG_VALUE`` message of a path with a NUL byte (``nodefs``); the ``Received``
  part of ``ERR_INVALID_ARG_TYPE`` from ``path.join`` and ``path.resolve`` for parsed JSON values
  (``reception_records.received``, Node's hardened text; a Node before nodejs/node#65607 is compared with that
  release's text); every comparison V8's ``Array.prototype.sort`` makes, in order, and its result (``jssort``,
  with the insertion-sort limit measured on the running Node: ``library_support.node_generation``); what an object
  literal finds on Object.prototype (``familyNames[id]``); and ``createHash().update`` of strings with lone
  surrogates (``idFor``).
- End to end, Node's own queue against ``Library`` (``library_support.run_node``, Python sorting with the running
  Node's limit): stored design requests that Node refuses, strict-area pointers whose report is missing, not a
  string or holds a NUL byte, offline records whose identifiers carry lone surrogates or name Object.prototype
  members and a reference report whose conditions are a string, and lists of 3 to 12 records in which a record's
  ``finished_at`` is not a string at several positions (lists of 3 to 7 records that Node 26 sorts and older Node,
  like Python's own ``list.sort``, does not).
"""
from __future__ import annotations

import copy
import functools
import random
import subprocess
from pathlib import Path
from typing import Any

import pytest

from schema_parity_support import FORMATS, body_text, require

require('pydantic')

from eeglayoutlab.jobs import jssort, nodefs  # noqa: E402
from eeglayoutlab.jobs.design_result import DesignResultError, normalize_design_request  # noqa: E402
from eeglayoutlab.jobs.identity import UNDEFINED, JSTypeError, _js_string, js_truthy  # noqa: E402
from eeglayoutlab.jobs.library import Library, _newest_first  # noqa: E402
from eeglayoutlab.jobs.reception_records import received, summary  # noqa: E402
from eeglayoutlab.jobs.records import RecordStore  # noqa: E402
from eeglayoutlab.jobs.runtime import runtime_config  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402

from .key_parity_support import NODE_ENV, PRIOR, needs_node  # noqa: E402
from .library_support import (  # noqa: E402
    CURRENT_POINTER, GRID, ROOT, WEBAPP, area_report, balanced, code_tree, design_record, design_request,
    forward_inputs, node_generation, offline_datasets, offline_radius, python_entry, run_node, sha, sorting_as_node,
    write,
)
from .test_library import assert_same_entry  # noqa: E402

MESSAGES_DRIVER = r"""
// Node reference of tests/service/test_library_messages.py (its header documents the spec).
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { inspect } from 'node:util';

const [specPath, outPath] = process.argv.slice(2);
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
const load = file => import(pathToFileURL(`${spec.webapp}/${file}`).href);
const { normalizeDesignRequest } = await load('server/design-evaluation-server.mjs');
const { designSubmission } = await load('server/annotations/electrode-names.mjs');
const thrown = run => { try { run(); return null; } catch (error) { return String(error?.message ?? error); } };
const out = { node: process.versions.node, designs: [], inspect: [], nul: [], join: [], resolve: [], sorts: [] };
for (const text of spec.designs) {
  let value;
  try { value = JSON.parse(text); } catch { continue; }
  const candidates = [text];
  try {
    const inner = JSON.stringify(designSubmission(value).request);
    if (inner !== undefined && !candidates.includes(inner)) candidates.push(inner);
  } catch {}
  for (const candidate of candidates)
    out.designs.push([candidate, thrown(() => normalizeDesignRequest(JSON.parse(candidate)))]);
}
for (const text of spec.strings) {
  out.inspect.push(inspect(text));
  out.nul.push(text.includes('\u0000') ? thrown(() => readFileSync(text)) : null);
}
for (const text of spec.values) {
  const { value } = JSON.parse(text);
  out.join.push(thrown(() => path.join('/r', value)));
  out.resolve.push(thrown(() => path.resolve('/r', value)));
}
for (const { values, answers, throwAt } of spec.sorts) {
  const calls = [];
  const items = values.map((v, id) => ({ id, v }));
  let error = null;
  try {
    items.sort((a, b) => {
      calls.push([a.id, b.id]);
      if (throwAt !== null && calls.length - 1 === throwAt) throw new Error('stop');
      return answers ? answers[(calls.length - 1) % answers.length] : a.v - b.v;
    });
  } catch (e) { error = e.message; }
  out.sorts.push({ calls, order: items.map(item => item.id), error });
}
const names = Object.fromEntries(spec.familyNames);
const keys = [...Object.getOwnPropertyNames(Object.prototype), ...spec.familyKeys];
out.families = keys.map(key => {
  const value = names[key];
  return [key, value === undefined || value === null ? null : `${value}`];
});
out.ids = spec.ids.map(([dataset, id]) => createHash('sha256').update(`${dataset}:${id}`).digest('hex'));
writeFileSync(outPath, JSON.stringify(out));
process.exit(0);
"""


# --- Design requests -----------------------------------------------------------------------------------------------

SPATIAL_OK = {'kind': 'spatial', 'rho': 0.5, 'length_mm': 20}
BRAIN_OK = {'kind': 'brain_background', 'fraction': 0.5}
PRIOR_OK = {'region_gain': [1, 1.5, 0.25, 2.75, 1000, 0.001, 12.34], 'rho': 0.3, 'length_mm': 20}


DESIGN_MESSAGES = (
    '设计评价字段错误', '噪声模型格式无效', '不支持的噪声模型', '不支持的电导率情景', '电导率情景只用于坐标评价，不用于网格偏移',
    '头模编号无效', '其他头模只用于坐标评价，不用于网格偏移', '电导率情景只定义在Ernie头模上', '不支持的稳健性协议',
    '稳健性评价只用于坐标评价，不用于网格偏移', '稳健性评价只定义在Ernie名义头模上，不与电导率情景或其他头模同时使用', '数据先验格式无效',
    '数据先验的区域增益须为7个保留4位有效数字的正数', '数据先验的噪声相关比例无效', '数据先验的噪声相关长度无效',
    '数据先验已包含噪声结构，不能同时选择噪声模型', '数据先验只定义在Ernie头模上', '需要已配准的Ernie原生毫米坐标', '需要64个互异的有限坐标',
    '需要64个区域标签', '区域编号错误', '区域分配须均衡，总数64', '最小直线点距需达到4 mm', '计算动作、偏移或种子无效',
)


def _request(top: Any = None, design: Any = None, drop: tuple = (), drop_design: tuple = ()) -> dict:
    value: dict[str, Any] = {'action': 'evaluate', 'radius_mm': 3, 'seed': 2026, 'design': {
        'schema': 'eeg-electrode-design/1', 'coordinate_system': 'ernie_native_mm', 'unit': 'mm', 'name': 'n',
        'xyz_mm': [list(point) for point in GRID], 'region_indices': balanced(2)}}
    value['design'].update(design or {})
    value.update(top or {})
    for key in drop:
        value.pop(key)
    for key in drop_design:
        value['design'].pop(key)
    return value


def _points(changes: dict) -> list:
    points = [list(point) for point in GRID]
    for index, point in changes.items():
        points[index] = point
    return points


def hand_designs() -> list[Any]:
    """Requests that reach each of ``normalizeDesignRequest``'s checks, alone and with a later one."""
    values: list[Any] = [None, [], 5, 'x', {}, _request()]
    values += [_request(drop=(key,)) for key in ('action', 'design', 'radius_mm', 'seed')]
    values += [_request({key: 1}) for key in ('x', '__proto__', 'constructor', 'toString', 'schema')]
    for model in (None, 0, '', 'x', [], {}, {'kind': 'iid'}, {'kind': 'iid', 'x': 1}, SPATIAL_OK,
                  {**SPATIAL_OK, 'length_mm': 30}, {**SPATIAL_OK, 'rho': 0.4}, {**SPATIAL_OK, 'length_mm': True},
                  {'kind': 'spatial', 'length_mm,rho': 0.5}, {'kind': 'spatial', 'length_mm,rho': 0.5, 'x': 1},
                  BRAIN_OK, {**BRAIN_OK, 'fraction': 0.4}):
        values.append(_request({'noise_model': model}))
    for scenario in (None, '', 0, False, 'skull_x3', 'skull_x2', 'skull_x0.5', ['skull_x2']):
        values.append(_request({'conductivity_scenario': scenario}))
        values.append(_request({'conductivity_scenario': scenario, 'action': 'perturb'}))
    for head in (None, '', 'IXI002', 'ixi002', 'a' * 40, 'a' * 41, 'ixi002\n', 'ixi__002', '-ixi', 5, True):
        values.append(_request({'head_id': head}))
    values += [_request({'head_id': 'ixi002', 'action': 'perturb'}),
               _request({'head_id': 'ixi002', 'conductivity_scenario': 'skull_x2'}),
               _request({'head_id': 'ixi002', 'conductivity_scenario': 'skull_x3'})]
    for robustness in (None, '', False, 0, True, 'standard/2', 'standard/1'):
        values.append(_request({'robustness': robustness}))
    values += [_request({'robustness': 'standard/1', 'action': 'perturb'}),
               _request({'robustness': 'standard/1', 'conductivity_scenario': 'skull_x2'}),
               _request({'robustness': 'standard/1', 'head_id': 'ixi002'}),
               _request({'robustness': 'standard/2', 'head_id': 'IXI'})]
    gains = PRIOR_OK['region_gain']
    for prior in (None, 0, [], {}, PRIOR_OK, {**PRIOR_OK, 'x': 1}, {**PRIOR_OK, 'region_gain': gains[:6]},
                  {**PRIOR_OK, 'region_gain': [0.0001, *gains[1:]]}, {**PRIOR_OK, 'region_gain': [1.2345, *gains[1:]]},
                  {**PRIOR_OK, 'region_gain': [True, *gains[1:]]}, {**PRIOR_OK, 'region_gain': [1001, *gains[1:]]},
                  {**PRIOR_OK, 'rho': 0.96}, {**PRIOR_OK, 'rho': 0.333}, {**PRIOR_OK, 'rho': '0.3'},
                  {**PRIOR_OK, 'rho': -0.01}, {**PRIOR_OK, 'rho': 0}, {**PRIOR_OK, 'rho': 0, 'length_mm': None},
                  {**PRIOR_OK, 'length_mm': 25}, {**PRIOR_OK, 'length_mm': None},
                  {'length_mm,region_gain': 1, 'rho': 0.3}):
        values.append(_request({'data_prior': prior}))
    values += [_request({'data_prior': PRIOR_OK, 'noise_model': SPATIAL_OK}),
               _request({'data_prior': PRIOR_OK, 'noise_model': BRAIN_OK}),
               _request({'data_prior': PRIOR_OK, 'noise_model': {'kind': 'iid'}}),
               _request({'data_prior': PRIOR_OK, 'head_id': 'ixi002'}),
               _request({'data_prior': {**PRIOR_OK, 'rho': 2}, 'noise_model': 'x'}),
               _request({'data_prior': PRIOR_OK, 'conductivity_scenario': 'skull_x2'})]
    for design in (None, 'x', [], {}):
        values.append(_request({'design': design}))
    values += [_request(design={'unit': 'cm'}), _request(design={'schema': 'x'}),
               _request(design={'coordinate_system': 'mni'}), _request(drop_design=('unit',))]
    near = [GRID[0][0] + 3, GRID[0][1], GRID[0][2]]
    for xyz in ('x', [list(p) for p in GRID[:63]], _points({5: [1, 2]}), _points({5: [1, 2, 'a']}),
                _points({5: [501, 0, 0]}), _points({5: [-500, 0, 0]}), _points({5: [[1], 2, 3]}),
                _points({1: list(GRID[0])}), _points({1: near}), _points({1: [GRID[0][0] + 4, 0, 0]}),
                _points({1: [GRID[0][0] + 4 - 1e-8, 0, 0]}), _points({1: [GRID[0][0] + 4 - 1e-6, 0, 0]}),
                _points({0: [-0.0, 0, 0], 8: [0.0, 6.0, 0]})):
        values.append(_request(design={'xyz_mm': xyz}))
    for regions in ('x', balanced(2)[:63], [5] + balanced(2)[1:], [i % 5 for i in range(64)], [1.5] + balanced(2)[1:],
                    [-1] + balanced(2)[1:], [True] + balanced(2)[1:], [int(i >= 40) for i in range(64)], [0] * 64,
                    balanced(3), balanced(6), [str(v) for v in balanced(2)], [-0.0] + balanced(2)[1:]):
        values.append(_request(design={'region_indices': regions}))
    for top in ({'action': 'x'}, {'action': None}, {'radius_mm': 7}, {'radius_mm': '3'}, {'radius_mm': True},
                {'radius_mm': 10}, {'seed': -1}, {'seed': 1.5}, {'seed': 10000}, {'seed': 9999}, {'seed': '1'},
                {'seed': True}, {'action': 'perturb'}):
        values.append(_request(top))
    values += [_request({'radius_mm': 7}, {'unit': 'cm'}), _request({'noise_model': 'x', 'conductivity_scenario': 'y'}),
               _request({'seed': -1}, {'region_indices': [5] * 64}), _request({'noise_model': 'x'}, {'xyz_mm': 'x'}),
               _request({'head_id': 'IXI', 'robustness': 'x'}), _request({'robustness': 'x', 'data_prior': {}}),
               _request({'radius_mm': 7}, {'xyz_mm': _points({1: near})})]
    return values


# --- Strings, values and sorts --------------------------------------------------------------------------------------

def strings() -> list[str]:
    rng = random.Random(3)
    alphabet = ['a', 'Z', '0', ' ', "'", '"', '`', '$', '{', '}', '${', '\\', '\n', '\t', '\r', '\x0b', '\x08', '\x0c',
                '\x00', '\x1f', '\x7f', '\x85', '\x9f', '\xa0', 'é', '中', '\U0001F600', '\ud800', '\udc00', '/']
    texts = ["it's", 'a"b', 'a\'b"c', 'a\'b"c`d', 'a\'b"c${d', '', 'x' * 130, 'line\n' * 40, '\x00' + 'y' * 200]
    for n in (1, 2, 5, 16, 17, 60, 75, 76, 77, 78, 100, 123, 124, 125, 126, 200, 10001):
        texts += [''.join(rng.choice(alphabet) for _ in range(n)) for _ in range(6)]
    texts += ['/tmp/root/' + text + '\x00' for text in texts[:60]]
    return texts


VALUES = ['{}', '{"value":null}', '{"value":true}', '{"value":false}', '{"value":0}', '{"value":-0}',
          '{"value":5}', '{"value":1.5}', '{"value":1e21}', '{"value":-1e-7}', '{"value":[]}', '{"value":["a"]}',
          '{"value":{}}', '{"value":{"constructor":5}}', '{"value":{"constructor":"s"}}',
          '{"value":{"constructor":true}}',
          '{"value":{"constructor":0}}', '{"value":{"constructor":""}}', '{"value":{"constructor":null}}',
          '{"value":{"constructor":{}}}', '{"value":{"constructor":[]}}', '{"value":{"constructor":[1]}}',
          '{"value":{"constructor":{"name":"X"}}}', '{"value":{"constructor":{"name":5}}}',
          '{"value":{"constructor":{"name":null}}}', '{"value":{"constructor":{"name":""}}}',
          '{"value":{"constructor":{"name":["X"]}}}', '{"value":{"name":"X"}}']


def sorts() -> list[dict]:
    rng = random.Random(7)
    cases = []
    for n in (*range(0, 40), 63, 64, 65, 100, 128, 200, 411, 700):
        for kind in ('random', 'dups', 'sorted-ish', 'runs', 'answers', 'throw'):
            if kind == 'dups':
                values = [rng.randrange(5) for _ in range(n)]
            elif kind == 'sorted-ish':
                values = sorted(rng.random() for _ in range(n))
                for _ in range(n // 20):
                    values[rng.randrange(n)] = rng.random()
            elif kind == 'runs':
                values = []
                while len(values) < n:
                    k, start = rng.randrange(1, 90), rng.random() * 100
                    step = -1 if rng.random() < 0.5 else 1
                    values += [start + step * i * (0 if rng.random() < 0.2 else 1) for i in range(k)]
                values = values[:n]
            else:
                values = [rng.random() for _ in range(n)]
            answers = [rng.choice([-1, 0, 1]) for _ in range(97)] if kind == 'answers' else None
            throw = rng.randrange(max(1, n * 3)) if kind == 'throw' else None
            cases.append({'values': values, 'answers': answers, 'throwAt': throw})
    return cases


FAMILY_NAMES = {'bilateral_near_ear': '双侧耳后代理', 'left_ear_forehead': '左耳后＋前额'}
FAMILY_KEYS = ['bilateral_near_ear', 'unknown', 'name', 'length', 'prototype', '__proto__', 'constructor']
IDS = [['offline_radius', 'c\ud800:v'], ['strict_area', 'run\udc00:x:y'], ['strict_area', 'a\ud83d'],
       ['offline_radius', '\U0001F600:\udbff'], ['strict_area', 'plain'], ['x', '\udfff\ud800']]


@pytest.fixture(scope='module')
def node(tmp_path_factory):
    scratch = tmp_path_factory.mktemp('library-messages')
    designs = [body_text(variant) for variant in FORMATS.get('design-evaluation', [])]
    designs += [jsjson.stringify(value) for value in hand_designs()]
    spec = {'webapp': str(WEBAPP), 'designs': designs, 'strings': strings(), 'values': VALUES, 'sorts': sorts(),
            'familyNames': list(FAMILY_NAMES.items()), 'familyKeys': FAMILY_KEYS, 'ids': IDS}
    driver, spec_path, out_path = scratch / 'messages.mjs', scratch / 'spec.json', scratch / 'out.json'
    driver.write_text(MESSAGES_DRIVER, encoding='utf-8')
    spec_path.write_text(jsjson.stringify(spec), encoding='utf-8')
    subprocess.run(['node', str(driver), str(spec_path), str(out_path)], check=True, cwd=ROOT, env=NODE_ENV)
    return spec, jsjson.parse(out_path.read_text(encoding='utf-8'))


def _refusal(text: str) -> Any:
    try:
        normalize_design_request(jsjson.parse(text))
    except DesignResultError as error:
        return str(error)
    return None


@needs_node
def test_design_refusals_carry_nodes_messages(node):
    """A stored request ``normalizeDesignRequest`` refuses gives Node's message; one it accepts is accepted."""
    _, out = node
    found = [(text[:200], message, _refusal(text)) for text, message in out['designs'] if _refusal(text) != message]
    assert found == []
    # Every message of normalizeDesignRequest and of the option normalizers it calls, and acceptance.
    assert {message for _, message in out['designs']} == {None, *DESIGN_MESSAGES}


@needs_node
def test_inspect_and_nul_paths_are_nodes(node):
    """``util.inspect`` of a string (quotes, escapes, line splitting past 76 code units, the 10000-unit cut), and
    Node's ``ERR_INVALID_ARG_VALUE`` message for a path with a NUL byte, cut at 128 code units."""
    spec, out = node
    found = []
    for text, inspected, message in zip(spec['strings'], out['inspect'], out['nul'], strict=True):
        mine = None
        if '\x00' in text:
            with pytest.raises(nodefs.InvalidArgValueError) as error:
                nodefs.check_path(text)
            mine = str(error.value)
        if (nodefs.inspect_string(text), mine) != (inspected, message):
            found.append((text[:80], inspected[:200], nodefs.inspect_string(text)[:200], message, mine))
    assert found == []
    assert any(' +\n  ' in text for text in out['inspect']) and any(text.startswith('`') for text in out['inspect'])
    assert any(message and message.endswith('...') for message in out['nul'])


def _thrown(run) -> Any:
    try:
        run()
    except (TypeError, JSTypeError) as error:
        return str(error)
    return None


def _received_before_65607(value: Any) -> str:
    """``determineSpecificType`` of Node releases before nodejs/node#65607 (Node 26.5, 24.21): an object is named
    by any ``name`` member of its ``constructor``, and a truthy primitive ``constructor`` fails the ``'name' in``
    check with V8's ``TypeError``."""
    constructor = value.get('constructor', UNDEFINED) if isinstance(value, dict) else UNDEFINED
    if isinstance(constructor, dict) and 'name' in constructor:
        return f"an instance of {_js_string(constructor['name'])}"
    if js_truthy(constructor) and not isinstance(constructor, (dict, list)):
        raise JSTypeError(f"Cannot use 'in' operator to search for 'name' in {_js_string(constructor)}")
    return received(value)


@needs_node
def test_received_is_nodes(node):
    """The ``Received`` part of ``path.join``'s and ``path.resolve``'s ``ERR_INVALID_ARG_TYPE``: Node's hardened
    text, which the library's checks write; a Node before the hardening is compared with its own text."""
    from eeglayoutlab.jobs.library import PathArgumentError, _path_argument

    spec, out = node
    hardened = node_generation()['receivedHardened']
    named = received if hardened else _received_before_65607

    def check(name: str, value: Any) -> None:
        if not isinstance(value, str):
            raise TypeError(f'The "{name}" argument must be of type string. Received {named(value)}')

    def resolve(value: Any) -> None:
        if hardened:
            _path_argument(value, 1)  # the library's check of a pointer's report
        else:
            check('paths[1]', value)

    found = []
    values = [jsjson.parse(text).get('value', UNDEFINED) for text in spec['values']]
    for text, value, joined, resolved in zip(spec['values'], values, out['join'], out['resolve'], strict=True):
        mine = (_thrown(lambda: check('path', value)), _thrown(lambda: resolve(value)))
        if mine != (joined, resolved):
            found.append((text, (joined, resolved), mine))
    assert found == []
    assert PathArgumentError.code == 'ERR_INVALID_ARG_TYPE'
    assert any(message.endswith('[Object]') for message in out['join'])
    assert hardened != any("Cannot use 'in' operator" in message for message in out['join'])
    # The values tell the two releases apart.
    assert any(_thrown(lambda: received(value)) != _thrown(lambda: _received_before_65607(value)) for value in values)


@needs_node
def test_array_sort_compares_as_v8(node):
    """``jssort.array_sort`` calls the comparator with V8's arguments in V8's order, gives V8's order (for
    inconsistent comparators too) and rethrows where V8 does."""
    from eeglayoutlab.jobs import jssort

    spec, out = node
    limit = node_generation()['insertionLimit']
    found = []
    for case, theirs in zip(spec['sorts'], out['sorts'], strict=True):
        calls: list = []
        items = [{'id': i, 'v': v} for i, v in enumerate(case['values'])]

        def compare(a: dict, b: dict) -> float:
            calls.append([a['id'], b['id']])
            if case['throwAt'] is not None and len(calls) - 1 == case['throwAt']:
                raise RuntimeError('stop')
            return case['answers'][(len(calls) - 1) % len(case['answers'])] if case['answers'] else a['v'] - b['v']

        error, order = None, None
        try:
            order = [item['id'] for item in jssort.array_sort(items, compare, insertion_limit=limit)]
        except RuntimeError as stop:
            error = str(stop)
        if calls != theirs['calls'] or error != theirs['error'] or (error is None and order != theirs['order']):
            found.append((len(case['values']), case['answers'] is not None, case['throwAt']))
    assert found == []
    # The service follows Node 26 (V8 14.6); Node 24 (V8 13.6, measured) and older have no insertion-only path.
    major = int(out['node'].split('.')[0])
    if major >= 26:
        assert limit == jssort.INSERTION_LIMIT
    elif major <= 24:
        assert limit == 2


@needs_node
def test_object_prototype_names_and_lone_surrogate_ids(node):
    """``familyNames[id]`` finds Object.prototype's members (as a template literal writes them), and ``idFor``
    hashes a lone surrogate as U+FFFD, as ``hash.update`` encodes a string."""
    from eeglayoutlab.jobs.library import _family_name, _id_for

    spec, out = node
    assert [[key, _family_name(key)] for key, _ in out['families']] == out['families']
    assert {'constructor', 'toString', '__proto__', 'hasOwnProperty'} <= {key for key, _ in out['families']}
    assert [_id_for(dataset, id) for dataset, id in spec['ids']] == out['ids']


# --- End to end ------------------------------------------------------------------------------------------------------

def _minimal(root: Path) -> None:
    root.mkdir(parents=True)
    code_tree(root)
    forward_inputs(root)


def _refuse(change):
    def edit(cache: dict) -> None:
        stored = copy.deepcopy(cache['result']['request'])
        change(stored)
        cache['result']['request'] = stored
        cache['result_sha256'] = jsjson.sha256_hex(cache['result'])
    return edit


REFUSED = {
    'extra': lambda r: r.update(x=1),
    'radius': lambda r: r.update(radius_mm=7.0),
    'noise': lambda r: r.update(noise_model={'kind': 'spatial', 'rho': 0.5, 'length_mm': 30.0}),
    'head': lambda r: r.update(head_id='IXI002'),
    'scenario': lambda r: r.update(conductivity_scenario='skull_x3'),
    'robustness': lambda r: r.update(robustness='standard/2'),
    'prior': lambda r: r.update(data_prior={**PRIOR, 'length_mm': 25.0}),
    'unit': lambda r: r['design'].update(unit='cm'),
    'duplicate': lambda r: r['design']['xyz_mm'].__setitem__(1, list(r['design']['xyz_mm'][0])),
    'unbalanced': lambda r: r['design'].update(region_indices=[float(i >= 40) for i in range(64)]),
    'spacing': lambda r: r['design']['xyz_mm'].__setitem__(1, [3.0, 0.0, 0.0]),
    'labels': lambda r: r['design'].update(region_indices=r['design']['region_indices'][:63]),
    # Joined, these keys read 'kind,length_mm,rho' too; Node reads rho as undefined.
    'noise-joined': lambda r: r.update(noise_model={'kind': 'spatial', 'length_mm,rho': 0.5}),
}

POINTERS = {
    'no-report': {'sha256': sha('x')},
    'number': {'report': 5},
    'negative-zero': '{"report":-0}',
    'null': {'report': None},
    'true': {'report': True},
    'array': {'report': ['a']},
    'object': {'report': {}},
    'named': {'report': {'constructor': {'name': 'Report'}}},
    'unnamed': {'report': {'constructor': {}}},
    'falsy': {'report': {'constructor': 0}},
    'primitive': {'report': {'constructor': 5}},
    'nul-quote': {'report': "results/v2/campaigns/a\x00'b.json"},
    'nul-quotes': {'report': 'a\x00\'"b'},
    'nul-backtick': {'report': 'a\x00\'"`b${'},
    'nul-long': {'report': 'results/v2/campaigns/' + 'n' * 90 + '\x00\n' + 'tail\x85\ud800.json'},
}

# Design records only, ``finished_at`` distinct ISO texts but at the positions given (in the store's order).
FINISHED = {
    'first-number': (8, {0: 12345}),
    'last-number': (8, {7: 12345}),
    'middle-true': (10, {4: True}),
    'last-array': (10, {9: [3]}),
    'falsy': (9, {2: 0, 5: False, 6: None}),
    'several': (12, {3: 99999, 10: True}),
    'second-true': (11, {1: True}),
    'short-true': (3, {1: True, 2: 0}),
    'short-number': (5, {2: 12345}),
    'short-falsy': (7, {0: 0, 4: True}),
}
# Lists that Node 26 sorts by binary insertion alone, in this order of store positions; Node 24 and older (one run,
# then insertion, as CPython's list.sort) compare the record with a truthy non-string finished_at as b, and throw.
SHORT_LISTS = {'short-true': [1, 0, 2], 'short-number': [4, 0, 3, 1, 2], 'short-falsy': [4, 3, 6, 2, 1, 5, 0]}


def _finished_root(root: Path, count: int, bad: dict) -> None:
    _minimal(root)
    data = write(root, 'results/v2/reference.json', {'baseline': {'reference_xyz_mm': GRID}})
    write(root, CURRENT_POINTER, {'report': 'results/v2/reference.json', 'sha256': sha(data)})
    requests = {}
    for i in range(count):
        request = design_request(f'n{i}')
        requests[design_record(root, request)] = request
    days = random.Random(count).sample(range(1, 29), count)
    for position, key in enumerate(RecordStore(str(root)).keys('design')):
        value = bad.get(position, f'2026-10-{days[position]:02d}T00:00:00Z')
        design_record(root, requests[key], change=lambda cache, value=value: cache.__setitem__('finished_at', value))


@pytest.fixture(scope='module')
def roots(tmp_path_factory):
    base = tmp_path_factory.mktemp('library-message-roots')
    items = []

    def add(name: str) -> None:
        items.append({'id': name, 'root': str(base / name), 'ids': [], 'requests': {}})

    _minimal(base / 'refused')
    offline_datasets(base / 'refused')
    for name, change in REFUSED.items():
        design_record(base / 'refused', design_request(f'refused {name}'), change=_refuse(change))
    design_record(base / 'refused', design_request('accepted'))
    add('refused')
    for name, pointer in POINTERS.items():
        _minimal(base / f'pointer-{name}')
        offline_datasets(base / f'pointer-{name}', pointers={'current': pointer})
        design_record(base / f'pointer-{name}', design_request('pointer'))
        add(f'pointer-{name}')
    radius = offline_radius()
    radius['conditions'][0]['id'] = 'c\ud800'
    for index, family in enumerate(('__proto__', 'constructor', 'toString', 'hasOwnProperty'), start=1):
        radius['conditions'][index]['family_id'] = family
    current = area_report(run_id='run\udc00\U0001F600')
    current['baseline']['field_metrics']['conditions'] = 'abc'
    historical = area_report(False, 'historical-run')
    historical['baseline']['field_metrics']['conditions'] = ''
    _minimal(base / 'quirks')
    offline_datasets(base / 'quirks', radius=radius, current=current, historical=historical)
    add('quirks')
    for name, (count, bad) in FINISHED.items():
        _finished_root(base / f'finished-{name}', count, bad)
        add(f'finished-{name}')
    node_out = run_node(items, tmp_path_factory.mktemp('library-message-node'))
    with sorting_as_node():
        python = {item['id']: python_entry(item) for item in items}
    return {item['id']: item for item in items}, node_out, python


ROOT_IDS = ['refused', *(f'pointer-{name}' for name in POINTERS), 'quirks', *(f'finished-{name}' for name in FINISHED)]


@needs_node
@pytest.mark.parametrize('root', ROOT_IDS)
def test_library_messages_parity(root, roots, request):
    if root == 'pointer-primitive' and not node_generation()['receivedHardened']:
        request.applymarker(pytest.mark.xfail(strict=True, reason="this Node predates nodejs/node#65607: its 'in' "
                                                                  'check throws for a primitive constructor'))
    items, node_out, python = roots
    assert_same_entry(items[root], node_out[root], python[root])


def _warnings(entry: dict) -> list[str]:
    return jsjson.parse(entry['list']['value'])['warnings'] if entry['list']['ok'] else []


@needs_node
def test_library_message_roots_reach_each_case(roots):
    """Node's own answers show what the roots are for: each refusal as a warning, each pointer failure, the
    offline records under these identifiers, and lists that fail or not with a ``finished_at`` that is no string."""
    _, node_out, _ = roots
    refused = _warnings(node_out['refused'])
    # One warning per refusal; 'noise' and 'noise-joined' share Node's message.
    assert len([text for text in refused if text.startswith('一条坐标评价记录未载入：')]) == len(REFUSED) - 1
    assert '一条坐标评价记录未载入：不支持的噪声模型' in refused
    pointer = [text for name in POINTERS for text in _warnings(node_out[f'pointer-{name}'])]
    for part in ('Received type number (-0)', 'Received undefined', 'an instance of Report', 'Received [Object]',
                 'without null bytes. Received `', 'without null bytes. Received "', '...'):
        assert any(part in text for text in pointer), part
    hardened = node_generation()['receivedHardened']
    primitive = 'Received [Object]' if hardened else "Cannot use 'in' operator to search for 'name' in 5"
    assert any(text.endswith(primitive) for text in _warnings(node_out['pointer-primitive']))
    assert any(text.startswith('一条坐标评价记录未载入：The "path" argument') for text in pointer)
    quirks = jsjson.parse(node_out['quirks']['list']['value'])
    labels = [row['label'] for row in quirks['records'] if row['dataset_id'] == 'offline_radius']
    assert any('function Object() { [native code] }' in label for label in labels)
    assert any('[object Object]' in label for label in labels)
    assert any(row['dataset_id'] == 'strict_area' for row in quirks['records'])
    assert any('candidate_field_explained_energy' in text for text in quirks['warnings'])
    lists = [node_out[f'finished-{name}']['list'] for name in FINISHED]
    assert any(not result['ok'] and result['message'] == '(b.finished_at || "").localeCompare is not a function'
               for result in lists)
    assert any(result['ok'] and any(not isinstance(row.get('finished_at'), (str, type(None))) and row['finished_at']
                                    for row in jsjson.parse(result['value'])['records']) for result in lists)
    short = [node_out[f'finished-{name}']['list']['ok'] for name in SHORT_LISTS]
    assert short == [node_generation()['insertionLimit'] >= 7] * len(SHORT_LISTS)


@pytest.mark.parametrize('name', list(SHORT_LISTS))
def test_short_lists_sort_as_node_26(tmp_path, name):
    """``list()`` sorts 3 to 7 records as Node 26 does, by binary insertion alone; Python's own sort, like Node 24
    and older, throws on these records."""
    _finished_root(tmp_path / name, *FINISHED[name])
    root = str(tmp_path / name)
    keys = RecordStore(root).keys('design')
    library = Library(root, runtime_config(root))
    assert [row['id'] for row in library.list()['records']] == [keys[i] for i in SHORT_LISTS[name]]
    rows = [summary(row) for row in library.records.values()]
    for sort in (lambda: sorted(rows, key=functools.cmp_to_key(_newest_first)),
                 lambda: jssort.array_sort(rows, _newest_first, insertion_limit=2)):
        with pytest.raises(JSTypeError, match=r'^\(b\.finished_at \|\| ""\)\.localeCompare is not a function$'):
            sort()
