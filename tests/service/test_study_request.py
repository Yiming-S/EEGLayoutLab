"""``jobs.studies.normalize_study_input`` is Node's ``normalizeStudyInput`` (phase 2 slice 8), messages included.

The variants are those of the schema parity corpus (``tests/schema_parity/formats/robustness-study.mjs``), which
records Node's message for every rejected study. ``tests/test_schema_parity.py`` and ``tests/test_schema_service.py``
already compare acceptance and the normalized study's bytes through the registry; here the messages, which the
Node host returns from ``POST /api/robustness-studies``, the status, the canonical input of
``schemas.robustness_study`` and Python values.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

from schema_parity_support import FORMATS, body_text, needs_node, require

require('pydantic')

from eeglayoutlab.jobs import studies  # noqa: E402
from eeglayoutlab.jobs.identity import UNDEFINED  # noqa: E402
from eeglayoutlab.jobs.studies import StudyError, normalize_study_input  # noqa: E402
from eeglayoutlab.schemas import jsjson, robustness_study  # noqa: E402
from eeglayoutlab.schemas.registry import REQUEST_FORMATS  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
VARIANTS = FORMATS.get('robustness-study', [])
FORMAT = REQUEST_FORMATS['robustness-study']
# Node's own messages; every other message a variant reaches is one of normalizeDesignRequest, electrodeNames or
# validateCoordinateSource, which the study passes on.
MESSAGES = {studies.CASES, studies.TITLE, studies.HEAD_SCENARIO, studies.HEAD_CASE_FIELDS, studies.CASE_FIELDS,
            studies.HEAD_PACKAGE, studies.HEAD_REPEATED, studies.HEAD_SEED, studies.PAIR_REPEATED, studies.RADIUS_FIXED}
PASSED_ON = {'设计评价字段错误', '需要已配准的Ernie原生毫米坐标', '需要64个互异的有限坐标', '需要64个区域标签', '区域编号错误',
             '区域分配须均衡，总数64', '最小直线点距需达到4 mm', '计算动作、偏移或种子无效', '噪声模型格式无效', '不支持的噪声模型',
             '不支持的电导率情景', '电导率情景只用于坐标评价，不用于网格偏移', '头模编号无效',
             '需要64个不重复的电极名称，每个名称最多128个字符且不含控制字符。', '坐标来源说明格式无效'}
DESIGN = {'schema': 'eeg-electrode-design/1', 'coordinate_system': 'ernie_native_mm', 'unit': 'mm', 'name': 'Original',
          'xyz_mm': [[(i % 8) * 6, (i // 8) * 6, 0] for i in range(64)], 'region_indices': [i % 2 for i in range(64)]}
NAMES = [f'Channel {i + 1}' for i in range(64)]


def _outcome(value):
    try:
        return jsjson.stringify(normalize_study_input(value)), None
    except StudyError as error:
        assert error.status == 400 and error.study_safe and error.message == str(error)
        return None, str(error)


def _study(**overrides):
    return {'protocol': 'noise_seeds', 'design': DESIGN, 'cases': [{'seed': 42, 'radius_mm': 6}, {'seed': 43, 'radius_mm': 6}],
            **overrides}


@needs_node
@pytest.mark.parametrize('variant', [v for v in VARIANTS if v['parsed']], ids=lambda v: v['name'])
def test_normalize_study_input_gives_node_study_or_node_message(variant):
    value = jsjson.parse(body_text(variant))
    before = copy.deepcopy(value)
    assert _outcome(value) == (variant['canonical'], variant.get('error'))
    assert value == before


@needs_node
def test_the_variants_reach_every_node_message():
    errors = {variant['error'] for variant in VARIANTS if 'error' in variant}
    assert MESSAGES <= errors and errors - MESSAGES <= PASSED_ON


@needs_node
def test_the_variants_cover_every_protocol_and_every_option():
    accepted = [jsjson.parse(v['canonical']) for v in VARIANTS if v['accepted']]
    assert {study['protocol'] for study in accepted} == set(studies.STUDY_PROTOCOLS)
    assert {len(study['requests']) for study in accepted} == set(range(1, 13))
    assert {study['noise_model']['kind'] for study in accepted if 'noise_model' in study} == {'spatial', 'brain_background'}
    assert {study['conductivity_scenario'] for study in accepted if 'conductivity_scenario' in study} == {'skull_x2', 'skull_x0.5'}
    assert {tuple(study['annotation']) for study in accepted} == {(), ('electrode_names',),
                                                                  ('electrode_names', 'source_metadata'),
                                                                  ('source_metadata', 'electrode_names')}


@needs_node
def test_canonical_inputs_normalize_to_the_same_study():
    # The canonical input the model validates is itself a study body that normalizes to the same study.
    for variant in VARIANTS:
        if variant['accepted']:
            normalized = jsjson.parse(variant['canonical'])
            canonical_input = robustness_study.canonical_input(normalized)
            assert _outcome(canonical_input) == (variant['canonical'], None)
            model = FORMAT.adapter.validate_python(canonical_input)
            assert jsjson.stringify(model.input_value()) == jsjson.stringify(canonical_input)
            # A model validated without Node's rules normalizes its own input to the same study.
            bare = type(model).model_validate(canonical_input)
            assert jsjson.stringify(robustness_study.canonical(bare)) == variant['canonical']


def test_the_registry_gives_the_normalized_study_and_node_message():
    normalized = FORMAT.normalize(_study())
    assert jsjson.stringify(normalized) == jsjson.stringify(normalize_study_input(_study()))
    with pytest.raises(ValueError, match=studies.PAIR_REPEATED):
        FORMAT.normalize(_study(cases=[{'seed': 1, 'radius_mm': 6}] * 2))
    model = FORMAT.adapter.validate_python(_study(title=' T '))
    assert FORMAT.adapter.validate_python(model) is model and model.title == 'T'


def test_the_normalized_study_keeps_node_order_and_requests():
    names_and_source = DESIGN | {'source_metadata': None}
    assert _outcome(_study(design=names_and_source)) == (None, studies.SOURCE)
    study = normalize_study_input(_study(title=' 　Title\t', noise_model={'length_mm': 20, 'rho': 0.5, 'kind': 'spatial'},
                                         conductivity_scenario='skull_x2', design=DESIGN | {'electrode_names': NAMES}))
    assert list(study) == ['protocol', 'title', 'notes', 'design', 'noise_model', 'conductivity_scenario', 'annotation', 'requests']
    assert study['title'] == 'Title' and study['notes'] == ''
    assert list(study['noise_model']) == ['kind', 'rho', 'length_mm']
    assert study['annotation'] == {'electrode_names': NAMES}
    assert [list(request) for request in study['requests']] == [
        ['action', 'design', 'radius_mm', 'seed', 'noise_model', 'conductivity_scenario']] * 2
    assert study['design'] is study['requests'][0]['design'] and 'electrode_names' not in study['design']


def test_python_values_follow_javascript_values():
    # -0 and 0 are one seed in a cross-head study and repeat a seed/radius pair (`${-0}` is "0").
    heads = [{'head_id': 'ixi002', 'seed': 0, 'radius_mm': 6}, {'head_id': 'ixi012', 'seed': -0.0, 'radius_mm': 6.0}]
    assert _outcome(_study(protocol='heads', cases=heads))[1] is None
    assert _outcome(_study(cases=[{'seed': 0, 'radius_mm': 6}, {'seed': -0.0, 'radius_mm': 6}])) == (None, studies.PAIR_REPEATED)
    assert _outcome(_study(cases=[{'seed': 42, 'radius_mm': 6}, {'seed': 42.0, 'radius_mm': 6.0}])) == (None, studies.PAIR_REPEATED)
    for bad in (True, 10**400, float('inf'), float('nan'), '42', 2.5):
        assert _outcome(_study(cases=[{'seed': bad, 'radius_mm': 6}])) == (None, '计算动作、偏移或种子无效')
    # null, undefined and an absent title or notes mean the default; tuples count as arrays.
    for value in (None, UNDEFINED):
        assert jsjson.parse(_outcome(_study(title=value, notes=value))[0])['title'] == 'Robustness study'
    assert _outcome(_study(cases=({'seed': 1, 'radius_mm': 6},)))[1] is None
    for falsy in (None, False, 0, '', [], ()):
        assert _outcome(falsy) == (None, studies.CASES)
    assert _outcome({**_study(), 1: 2}) == (None, studies.CASES)
    assert _outcome(_study(cases=[{'radius_mm': 6, 1: 2}])) == (None, studies.CASE_FIELDS)
    # The title's length is in UTF-16 units and counts the spaces trimmed off.
    assert _outcome(_study(title='\U0001F600' * 100))[1] is None
    assert _outcome(_study(title='a' * 199 + '\U0001F600')) == (None, studies.TITLE)
    assert _outcome(_study(title=' ' + 'a' * 200)) == (None, studies.TITLE)
    assert _outcome(_study(title='\ud800'))[1] is None


def test_normalization_does_not_change_its_input():
    value = _study(design=DESIGN | {'electrode_names': NAMES}, noise_model={'kind': 'iid'})
    before = copy.deepcopy(value)
    study = normalize_study_input(value)
    assert value == before and list(value) == list(before)
    assert study['annotation']['electrode_names'] is not NAMES and study['design']['xyz_mm'] is not DESIGN['xyz_mm']


def test_a_deeply_nested_value_is_rejected_without_a_traceback(monkeypatch):
    require('fastapi')
    require('httpx')
    from .service_support import loopback_client, make_app

    caught = []
    monkeypatch.setattr(sys, 'unraisablehook', caught.append)
    client = loopback_client(make_app(ROOT), csrf=True)
    deep = '{"a":' * 3000 + '1' + '}' * 3000
    text = jsjson.stringify(_study(title='T'))
    bodies = [
        text.replace('"noise_seeds"', deep),
        text.replace('"seed":42', '"seed":' + deep),
        text.replace('"title":"T"', '"title":' + deep),
        text.replace('"title":"T"', '"title":"T","extra":' + deep),
        text.replace('"title":"T"', '"title":"T","noise_model":' + deep),
        text.replace('"title":"T"', '"title":"T","conductivity_scenario":' + deep),
        text.replace('"unit":"mm"', '"unit":"mm","electrode_names":' + deep),
        text.replace('"unit":"mm"', '"unit":"mm","source_metadata":' + deep),
        text.replace('[{"seed":42', '[' + deep + ',{"seed":42'),
    ]
    for body in bodies:
        response = client.post('/api/normalize/robustness-study', content=body.encode(),
                               headers={'content-type': 'application/json'})
        assert response.status_code == 400 and response.json()['code'] == 'invalid_request'
        assert response.json()['error'].endswith(_outcome(jsjson.parse(body))[1])
    # Unknown design fields are dropped, at any depth.
    response = client.post('/api/normalize/robustness-study', headers={'content-type': 'application/json'},
                           content=text.replace('"unit":"mm"', '"unit":"mm","extra":' + deep).encode())
    assert response.status_code == 200 and response.json()['canonical'] == jsjson.parse(_outcome(_study(title='T'))[0])
    assert caught == []
