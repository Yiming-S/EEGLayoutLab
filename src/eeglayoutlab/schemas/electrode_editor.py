"""Electrode-editor request (``normalizeEditorRequest`` in webapp/server/electrode-editor-server.mjs).

The body of ``POST /api/electrode-editor/jobs`` and the ``request`` of every editor cache record. A preparation
names a parent layout of the library; an evaluation also carries the parent's digest, the fixed seed 2026 and the
64 stable slots of the parent's electrodes, each a bank index and whether that electrode is active, at least two
of them active.

``normalize_editor_request`` is a line-by-line port: it checks in Node's order and raises ``ValueError`` with
Node's message, which the Node host returns from the editor's job endpoint. ``ElectrodeEditorRequest`` describes the
canonical form for the OpenAPI document and accepts exactly what ``normalize_editor_request`` accepts. The canonical
form keeps Node's key order; Node rejects every other field, so nothing is dropped.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool

from . import jsjson
from .types import integer

__all__ = [
    'ElectrodeEditorRequest', 'ElectrodeEditorPreparation', 'ElectrodeEditorEvaluation', 'ElectrodeEditorSlot',
    'normalize_editor_request', 'canonical', 'ACTIONS', 'SLOT_COUNT', 'MAX_BANK_INDEX', 'SEED', 'MIN_ACTIVE',
]

ACTIONS = ('prepare', 'evaluate')
SLOT_COUNT = 64
MAX_BANK_INDEX = 1_000_000
SEED = 2026
MIN_ACTIVE = 2
_ID = re.compile('[a-f0-9]{64}')

# Node's messages, verbatim.
INVALID_REQUEST = 'Invalid editor request'
PREPARATION_FIELDS = 'Invalid preparation fields'
PROTOCOL = 'Invalid editor protocol'
SLOTS = 'Invalid stable electrode slots'
TOO_FEW_ACTIVE = 'At least two active electrodes are required'


# --- Node's rules ----------------------------------------------------------------

def _id(value: Any) -> bool:
    """``typeof value === 'string' && /^[a-f0-9]{64}$/.test(value)``: ``$`` is the end of the text, no newline."""
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _is_array(value: Any) -> bool:
    return isinstance(value, (list, tuple))


def _sorted_keys(value: dict) -> str:
    """``Object.keys(value).sort().join(',')``: UTF-16 code-unit order."""
    return ','.join(sorted((str(key) for key in value),
                           key=lambda key: key.encode('utf-16-be', errors='surrogatepass')))


def _bad_slot(slot: Any) -> bool:
    """A slot that is not ``{bank_index, enabled}`` with an integer index in [0, 1000000] and a boolean. ``!s`` and
    ``Object.keys`` of a number, a string or an array also fail the key test, so only an object can pass."""
    if not isinstance(slot, dict) or _sorted_keys(slot) != 'bank_index,enabled':
        return True
    index = slot.get('bank_index')
    return (not jsjson.is_integer(index) or not 0 <= jsjson.to_number(index) <= MAX_BANK_INDEX
            or not isinstance(slot.get('enabled'), bool))


def normalize_editor_request(raw: Any) -> dict[str, Any]:
    """``normalizeEditorRequest(raw)``: the canonical request; raises ``ValueError`` with Node's message where Node
    throws, checking in Node's order. ``raw`` is a ``jsjson.parse`` value or plain Python data (tuples count as
    arrays, ``bool`` is not a number); it is not changed."""
    # A value that is not an object has no action: `!raw`, or `raw.action` is undefined.
    if (not isinstance(raw, dict) or not (isinstance(raw.get('action'), str) and raw['action'] in ACTIONS)
            or not _id(raw.get('parent_id'))):
        raise ValueError(INVALID_REQUEST)
    if raw['action'] == 'prepare':
        if _sorted_keys(raw) != 'action,parent_id':
            raise ValueError(PREPARATION_FIELDS)
        return {'action': 'prepare', 'parent_id': raw['parent_id']}
    seed = raw.get('seed')
    if (_sorted_keys(raw) != 'action,parent_digest,parent_id,seed,slots' or not _id(raw.get('parent_digest'))
            or not (jsjson.is_number(seed) and jsjson.to_number(seed) == SEED)):
        raise ValueError(PROTOCOL)
    slots = raw.get('slots')
    if not _is_array(slots) or len(slots) != SLOT_COUNT or any(_bad_slot(slot) for slot in slots):
        raise ValueError(SLOTS)
    if sum(1 for slot in slots if slot['enabled']) < MIN_ACTIVE:
        raise ValueError(TOO_FEW_ACTIVE)
    return {'action': 'evaluate', 'parent_id': raw['parent_id'], 'parent_digest': raw['parent_digest'], 'seed': SEED,
            'slots': [{'bank_index': int(jsjson.to_number(slot['bank_index'])), 'enabled': slot['enabled']}
                      for slot in slots]}


# --- Schema --------------------------------------------------------------------

Identifier = Annotated[str, Field(strict=True, pattern='^[a-f0-9]{64}$')]
"""A lowercase SHA-256 hex digest: a library record id or a parent digest."""

_EXACT = ConfigDict(extra='forbid')


class ElectrodeEditorSlot(BaseModel):
    """One of the parent's 64 electrodes: the bank index of its position, which the worker checks against the
    slot's region, and whether it is active."""
    model_config = _EXACT
    bank_index: integer(ge=0, le=MAX_BANK_INDEX)
    enabled: StrictBool

    def canonical(self) -> dict[str, Any]:
        return {'bank_index': self.bank_index, 'enabled': self.enabled}


def _at_least_two_active(schema: dict[str, Any]) -> None:
    # JSON Schema 2020-12 (OpenAPI 3.1): at least two items with enabled true.
    schema.update(contains={'type': 'object', 'properties': {'enabled': {'const': True}}, 'required': ['enabled']},
                  minContains=MIN_ACTIVE)


class ElectrodeEditorPreparation(BaseModel):
    """Load the parent layout's region data for editing."""
    model_config = _EXACT
    action: Literal['prepare']
    parent_id: Identifier

    def canonical(self) -> dict[str, Any]:
        return {'action': 'prepare', 'parent_id': self.parent_id}


class ElectrodeEditorEvaluation(BaseModel):
    """Score the edited layout: ``parent_digest`` is the SHA-256 of the parent record's ``JSON.stringify`` text,
    and the slots keep the parent's electrode order."""
    model_config = _EXACT
    action: Literal['evaluate']
    parent_id: Identifier
    parent_digest: Identifier
    seed: Literal[SEED]  # type: ignore[valid-type]
    slots: Annotated[list[ElectrodeEditorSlot], Field(min_length=SLOT_COUNT, max_length=SLOT_COUNT,
                                                       json_schema_extra=_at_least_two_active)]

    def canonical(self) -> dict[str, Any]:
        return {'action': 'evaluate', 'parent_id': self.parent_id, 'parent_digest': self.parent_digest,
                'seed': SEED, 'slots': [slot.canonical() for slot in self.slots]}


def _node_rules(value: Any) -> Any:
    # Node's rules decide and give the message; the tagged union then checks the canonical value it describes.
    if isinstance(value, (ElectrodeEditorPreparation, ElectrodeEditorEvaluation)):
        return value
    return normalize_editor_request(value)


ElectrodeEditorRequest = Annotated[
    Union[ElectrodeEditorPreparation, ElectrodeEditorEvaluation], Field(discriminator='action'),
    BeforeValidator(_node_rules),
]


def canonical(value: ElectrodeEditorPreparation | ElectrodeEditorEvaluation) -> dict[str, Any]:
    """The registry's canonical value of a validated request."""
    return value.canonical()
