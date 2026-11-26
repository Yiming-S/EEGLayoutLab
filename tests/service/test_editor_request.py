"""``schemas.electrode_editor.normalize_editor_request`` is Node's ``normalizeEditorRequest`` (phase 2 slice 6),
messages included.

The variants are those of the schema parity corpus (``tests/schema_parity/formats/electrode-editor.mjs``), which
records Node's message for every rejected request. ``tests/test_schema_parity.py`` and
``tests/test_schema_service.py`` already compare acceptance and canonical bytes through the registry; here the
messages, which the Node host returns from ``POST /api/electrode-editor/jobs``.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

from schema_parity_support import FORMATS, body_text, needs_node, require

require('pydantic')

from eeglayoutlab.schemas import electrode_editor as editor, jsjson  # noqa: E402
from eeglayoutlab.schemas.electrode_editor import normalize_editor_request  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
VARIANTS = FORMATS.get('electrode-editor', [])
MESSAGES = {editor.INVALID_REQUEST, editor.PREPARATION_FIELDS, editor.PROTOCOL, editor.SLOTS, editor.TOO_FEW_ACTIVE}
PARENT, DIGEST = 'a' * 64, 'b' * 64


def _outcome(value):
    try:
        return jsjson.stringify(normalize_editor_request(value)), None
    except ValueError as error:
        return None, str(error)


def _evaluate(**overrides):
    return {'action': 'evaluate', 'parent_id': PARENT, 'parent_digest': DIGEST, 'seed': 2026,
            'slots': [{'bank_index': i, 'enabled': True} for i in range(64)], **overrides}


@needs_node
@pytest.mark.parametrize('variant', [v for v in VARIANTS if v['parsed']], ids=lambda v: v['name'])
def test_normalize_editor_request_gives_node_canonical_or_node_message(variant):
    value = jsjson.parse(body_text(variant))
    before = copy.deepcopy(value)
    assert _outcome(value) == (variant['canonical'], variant.get('error'))
    assert value == before


@needs_node
def test_the_variants_reach_every_node_message():
    assert {variant['error'] for variant in VARIANTS if 'error' in variant} == MESSAGES


@needs_node
def test_canonical_requests_normalize_to_themselves():
    for variant in VARIANTS:
        if variant['accepted']:
            assert _outcome(jsjson.parse(variant['canonical'])) == (variant['canonical'], None)


def test_python_values_follow_javascript_values():
    slots = tuple({'bank_index': i, 'enabled': i > 0} for i in range(64))
    request = _evaluate(slots=slots)
    assert normalize_editor_request(request)['slots'] == [dict(slot) for slot in slots]
    assert _outcome({'action': 'prepare', 'parent_id': PARENT}) == (f'{{"action":"prepare","parent_id":"{PARENT}"}}', None)
    assert _outcome(_evaluate(seed=2026.0))[1] is None
    assert _outcome(_evaluate(seed=True)) == (None, editor.PROTOCOL)
    assert _outcome(_evaluate(seed=10**400)) == (None, editor.PROTOCOL)
    assert _outcome(_evaluate(seed=float('nan'))) == (None, editor.PROTOCOL)
    assert _outcome({'action': 'prepare', 'parent_id': PARENT + '\n'}) == (None, editor.INVALID_REQUEST)
    for bad in ({'bank_index': True, 'enabled': True}, {'bank_index': 10**400, 'enabled': True},
                {'bank_index': 1, 'enabled': 1}, {'bank_index': float('inf'), 'enabled': True}, ('bank_index', 'enabled')):
        assert _outcome(_evaluate(slots=[bad, *slots[1:]])) == (None, editor.SLOTS)
    for falsy in (None, False, 0, 0.0, ''):
        assert _outcome(falsy) == (None, editor.INVALID_REQUEST)
    assert _outcome({'action': 'prepare', 'parent_id': PARENT, 1: 2}) == (None, editor.PREPARATION_FIELDS)
    assert _outcome(_evaluate(slots=[{'bank_index': i, 'enabled': i == 5} for i in range(64)])) == (None, editor.TOO_FEW_ACTIVE)


def test_a_deeply_nested_value_is_rejected_without_a_traceback(monkeypatch):
    require('fastapi')
    require('httpx')
    from .service_support import loopback_client, make_app

    caught = []
    monkeypatch.setattr(sys, 'unraisablehook', caught.append)
    client = loopback_client(make_app(ROOT), csrf=True)
    deep = '{"a":' * 3000 + '1' + '}' * 3000
    slots = jsjson.stringify(_evaluate()['slots'])
    for body in ('{"action":' + deep + ',"parent_id":"' + PARENT + '"}',
                 '{"action":"prepare","parent_id":"' + PARENT + '","extra":' + deep + '}',
                 '{"action":"evaluate","parent_id":"' + PARENT + '","parent_digest":"' + DIGEST + '","seed":' + deep
                 + ',"slots":' + slots + '}',
                 '{"action":"evaluate","parent_id":"' + PARENT + '","parent_digest":"' + DIGEST + '","seed":2026,"slots":['
                 + deep + ']}',
                 '{"action":"evaluate","parent_id":"' + PARENT + '","parent_digest":"' + DIGEST + '","seed":2026,"slots":'
                 + slots.replace('"enabled":true', '"enabled":' + deep, 1) + '}'):
        response = client.post('/api/normalize/electrode-editor', content=body.encode(),
                               headers={'content-type': 'application/json'})
        assert response.status_code == 400 and response.json()['code'] == 'invalid_request'
        assert response.json()['error'].endswith(_outcome(jsjson.parse(body))[1])
    assert caught == []
