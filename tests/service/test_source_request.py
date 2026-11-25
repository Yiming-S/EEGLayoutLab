"""``schemas.source_reception.normalize_reception_request`` is Node's ``normalizeReceptionRequest``, with
``normalizeSourceRequest`` for requests without ``mode`` (phase 2 slice 7), messages included.

The variants are those of the schema parity corpus (``tests/schema_parity/formats/source-reception.mjs``), which
records Node's message for every rejected request. ``tests/test_schema_parity.py`` and
``tests/test_schema_service.py`` already compare acceptance and canonical bytes through the registry; here the
messages, which the Node host returns from ``POST /api/source-reception/jobs`` and ``/lookup``.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

from schema_parity_support import FORMATS, body_text, needs_node, require

require('pydantic')

from eeglayoutlab.schemas import jsjson, source_reception as source  # noqa: E402
from eeglayoutlab.schemas.source_reception import normalize_reception_request, normalize_source_request  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
VARIANTS = FORMATS.get('source-reception', [])
MESSAGES = {source.INVALID_FIELDS, source.INVALID_CHOICE, source.UNSUPPORTED_DEFINITION, source.INVALID_MODE,
            source.INVALID_SOURCE_INDEX, source.INVALID_CROSS_REGIONS}
RECORD = 'a' * 64
V1 = {'record_id': RECORD, 'brain_region': 'frontal', 'waveform': 'burst', 'artifact_scale': 1, 'seed': 2026}
COMMON = {'record_id': RECORD, 'waveform': 'burst', 'artifact_scale': 1, 'seed': 2026}


def _outcome(value, normalize=normalize_reception_request):
    try:
        return jsjson.stringify(normalize(value)), None
    except ValueError as error:
        return None, str(error)


def _single(**overrides):
    return {**COMMON, 'mode': 'single_source', 'source_index': 2, **overrides}


def _cross(regions, **overrides):
    return {**COMMON, 'mode': 'cross_region', 'brain_regions': regions, **overrides}


@needs_node
@pytest.mark.parametrize('variant', [v for v in VARIANTS if v['parsed']], ids=lambda v: v['name'])
def test_normalize_reception_request_gives_node_canonical_or_node_message(variant):
    value = jsjson.parse(body_text(variant))
    before = copy.deepcopy(value)
    assert _outcome(value) == (variant['canonical'], variant.get('error'))
    assert value == before


@needs_node
def test_the_variants_reach_every_node_message():
    assert {variant['error'] for variant in VARIANTS if 'error' in variant} == MESSAGES


@needs_node
def test_the_variants_cover_both_versions_and_every_mode():
    accepted = [jsjson.parse(v['canonical']) for v in VARIANTS if v['accepted']]
    assert {request.get('mode', 'v1') for request in accepted} == {'v1', *source.MODES}
    assert {request['mode'] for request in accepted if 'region_definition' in request} == set(source.MODES)
    assert {region for request in accepted for region in request.get('brain_regions', [])} == set(source.SOURCE_REGIONS)


@needs_node
def test_canonical_requests_normalize_to_themselves():
    for variant in VARIANTS:
        if variant['accepted']:
            assert _outcome(jsjson.parse(variant['canonical'])) == (variant['canonical'], None)


@needs_node
def test_values_without_mode_take_the_v1_path():
    # normalizeReceptionRequest hands every value whose mode is undefined to normalizeSourceRequest.
    for variant in VARIANTS:
        if variant['parsed']:
            value = jsjson.parse(body_text(variant))
            if not (isinstance(value, dict) and 'mode' in value):
                assert _outcome(value, normalize_source_request) == (variant['canonical'], variant.get('error'))


def test_python_values_follow_javascript_values():
    assert _outcome(V1) == (jsjson.stringify(V1), None)
    # -0 is one of the scales (SameValueZero) and a valid seed; both are written 0, as JSON.stringify writes -0.
    assert _outcome({**V1, 'artifact_scale': -0.0, 'seed': -0.0})[0] == jsjson.stringify({**V1, 'artifact_scale': 0, 'seed': 0})
    assert _outcome({**V1, 'artifact_scale': 0.5, 'seed': 9999.0})[0] == jsjson.stringify({**V1, 'artifact_scale': 0.5, 'seed': 9999})
    for bad in ({'artifact_scale': True}, {'artifact_scale': 1j}, {'artifact_scale': float('nan')}, {'seed': True},
                {'seed': 10**400}, {'seed': float('inf')}, {'record_id': RECORD + '\n'}, {'brain_region': ('frontal',)}):
        assert _outcome({**V1, **bad}) == (None, source.INVALID_CHOICE)
    for falsy in (None, False, 0, 0.0, '', [], ()):
        assert _outcome(falsy) == (None, source.INVALID_FIELDS)
    assert _outcome({**V1, 1: 2}) == (None, source.INVALID_FIELDS)
    # Any value of mode, None (null) included, makes the request v2.
    assert _outcome({**V1, 'mode': None}) == (None, source.INVALID_MODE)
    assert _outcome({**V1, 'mode': ['single_source']}) == (None, source.INVALID_MODE)
    assert _outcome(_single(source_index=255.0))[0].endswith('"source_index":255}')
    for bad in (True, 256, -1, 0.5, 10**400, float('nan'), '2'):
        assert _outcome(_single(source_index=bad)) == (None, source.INVALID_SOURCE_INDEX)
    regions = ('temporal_right', 'frontal')
    assert _outcome(_cross(regions))[0].endswith('"brain_regions":["frontal","temporal_right"]}')
    for bad in ([['frontal']], [{'frontal': 1}], ['frontal', 'frontal'], [], list(source.SOURCE_REGIONS) + ['frontal'], 'frontal'):
        assert _outcome(_cross(bad)) == (None, source.INVALID_CROSS_REGIONS)
    assert _outcome(_cross(['frontal'], region_definition=None)) == (None, source.UNSUPPORTED_DEFINITION)
    assert _outcome(_cross(['frontal'], mode='other', region_definition=0)) == (None, source.UNSUPPORTED_DEFINITION)


def test_normalization_does_not_change_its_input():
    request = _cross(['occipital', 'frontal'], region_definition=source.REGION_DEFINITION)
    before = copy.deepcopy(request)
    assert normalize_reception_request(request)['brain_regions'] == ['frontal', 'occipital']
    assert request == before and list(request) == list(before)


def test_a_deeply_nested_value_is_rejected_without_a_traceback(monkeypatch):
    require('fastapi')
    require('httpx')
    from .service_support import loopback_client, make_app

    caught = []
    monkeypatch.setattr(sys, 'unraisablehook', caught.append)
    client = loopback_client(make_app(ROOT), csrf=True)
    deep = '{"a":' * 3000 + '1' + '}' * 3000
    single = jsjson.stringify(_single())
    bodies = [
        single.replace('"single_source"', deep),
        single.replace('"source_index":2', '"source_index":' + deep),
        single.replace('"seed":2026', '"seed":' + deep),
        single.replace('"seed":2026', '"seed":2026,"extra":' + deep),
        single.replace('"seed":2026', '"seed":2026,"region_definition":' + deep),
        jsjson.stringify(V1).replace('"frontal"', deep),
        jsjson.stringify(_cross(['frontal'])).replace('["frontal"]', '[' + deep + ']'),
    ]
    for body in bodies:
        response = client.post('/api/normalize/source-reception', content=body.encode(),
                               headers={'content-type': 'application/json'})
        assert response.status_code == 400 and response.json()['code'] == 'invalid_request'
        assert response.json()['error'].endswith(_outcome(jsjson.parse(body))[1])
    assert caught == []
