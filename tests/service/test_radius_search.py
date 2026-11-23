"""``schemas.radius_search.normalize_request`` is Node's ``normalizeRequest`` (phase 2 slice 3), messages included.

The variants are those of the schema parity corpus (``tests/schema_parity/formats/radius-search.mjs``), which
records Node's message for every rejected request. ``tests/test_schema_parity.py`` and
``tests/test_schema_service.py`` already compare acceptance and canonical bytes through the registry; here the
messages, which the Node host returns from ``POST /api/local-compute/jobs`` and writes into failed tasks.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

from schema_parity_support import FORMATS, body_text, needs_node, require

require('pydantic')

from eeglayoutlab.schemas import jsjson, radius_search  # noqa: E402
from eeglayoutlab.schemas.radius_search import normalize_request  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
VARIANTS = FORMATS.get('radius-search', [])
MESSAGES = {value for name, value in vars(radius_search).items() if name.isupper() and isinstance(value, str)}


def _outcome(value):
    try:
        return jsjson.stringify(normalize_request(value)), None
    except ValueError as error:
        return None, str(error)


@needs_node
@pytest.mark.parametrize('variant', [v for v in VARIANTS if v['parsed']], ids=lambda v: v['name'])
def test_normalize_request_gives_node_canonical_or_node_message(variant):
    value = jsjson.parse(body_text(variant))
    before = copy.deepcopy(value)
    assert _outcome(value) == (variant['canonical'], variant.get('error'))
    assert value == before


@needs_node
def test_the_variants_reach_every_node_message():
    assert {variant['error'] for variant in VARIANTS if 'error' in variant} == MESSAGES


@needs_node
def test_canonical_requests_normalize_to_themselves():
    # As check-api-contracts.mjs asserts for Node: the canonical request is a fixed point.
    for variant in VARIANTS:
        if variant['accepted']:
            assert _outcome(jsjson.parse(variant['canonical'])) == (variant['canonical'], None)


def test_python_values_follow_javascript_values():
    request = {'region_count': 2, 'radius_mm': 30, 'mode': 'preset', 'mask_codes': ('PL', 'PL')}
    assert normalize_request(request) == {'region_count': 2, 'radius_mm': 30, 'mode': 'preset', 'mask_codes': ['PL', 'PL']}
    assert _outcome({**request, 'region_count': True}) == (None, radius_search.REGION_COUNT)
    assert _outcome({**request, 'radius_mm': 10**400}) == (None, radius_search.RADIUS)
    assert _outcome({**request, 'mode': 'whole_surface', 'mask_codes': None}) == (None, radius_search.FREE_MASKS)
    assert _outcome({**request, 'noise_model': {'kind': 'spatial', 'rho': 0.5, 'length_mm': True}}) == \
        (None, radius_search.NOISE_UNSUPPORTED)
    assert _outcome({**request, 1: 2}) == (None, radius_search.UNKNOWN_FIELD)


def test_a_deeply_nested_value_is_rejected_without_a_traceback(monkeypatch):
    require('fastapi')
    require('httpx')
    from .service_support import loopback_client, make_app

    caught = []
    monkeypatch.setattr(sys, 'unraisablehook', caught.append)
    client = loopback_client(make_app(ROOT), csrf=True)
    deep = '{"a":' * 3000 + '1' + '}' * 3000
    for field, body in (('noise_model', '{"kind":' + deep + '}'), ('mask_codes', '[' + deep + ']'), ('data_prior', deep)):
        text = '{"region_count":1,"radius_mm":30,"mode":"preset","mask_codes":["PL"],"' + field + '":' + body + '}'
        response = client.post('/api/normalize/radius-search', content=text.encode(),
                               headers={'content-type': 'application/json'})
        assert response.status_code == 400 and response.json()['code'] == 'invalid_request'
        assert response.json()['error'].endswith(_outcome(jsjson.parse(text))[1])
    assert caught == []
