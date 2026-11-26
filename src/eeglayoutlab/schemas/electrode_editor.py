"""Electrode-editor request format (``normalizeEditorRequest`` in webapp/server/electrode-editor-server.mjs).

The body of ``POST /api/electrode-editor/jobs`` and ``/lookup``, and the ``request`` of every stored editor
record. Supports two actions:
- ``prepare``: ``{action: 'prepare', parent_id}``
- ``evaluate``: ``{action: 'evaluate', parent_id, parent_digest, seed: 2026, slots}`` (64 stable slots, at least
  2 enabled, bank indices in ``[0, 1_000_000]``).
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from . import jsjson

try:
    from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, model_validator
    from .types import integer, js_integer
    _HAS_PYDANTIC = True
except ModuleNotFoundError:  # Allows pure normalize_editor_request in runtimes without [service] extras.
    _HAS_PYDANTIC = False

__all__ = [
    'ElectrodeSlot', 'PrepareEditorRequest', 'EvaluateEditorRequest', 'ElectrodeEditorRequest',
    'normalize_editor_request', 'canonical', 'EDITOR_SEED', 'MAX_BANK_INDEX',
]

EDITOR_SEED = 2026
MAX_BANK_INDEX = 1000000
_HEX64 = re.compile(r'[a-f0-9]{64}')

INVALID_REQUEST = 'Invalid editor request'
INVALID_PREPARE = 'Invalid preparation fields'
INVALID_PROTOCOL = 'Invalid editor protocol'
INVALID_SLOTS = 'Invalid stable electrode slots'
MIN_ACTIVE = 'At least two active electrodes are required'


def _id(value: Any) -> bool:
    """``typeof value === 'string' && /^[a-f0-9]{64}$/.test(value)``."""
    return isinstance(value, str) and bool(_HEX64.fullmatch(value))


def _sorted_keys(value: dict[str, Any]) -> str:
    """``Object.keys(value).sort().join(',')`` in UTF-16 code-unit order."""
    return ','.join(sorted((str(key) for key in value),
                           key=lambda key: key.encode('utf-16-be', errors='surrogatepass')))


def _valid_slot(slot: Any) -> bool:
    if not isinstance(slot, dict) or _sorted_keys(slot) != 'bank_index,enabled':
        return False
    bank = slot.get('bank_index')
    enabled = slot.get('enabled')
    if not jsjson.is_integer(bank) or type(enabled) is not bool:
        return False
    idx = int(jsjson.to_number(bank))
    return 0 <= idx <= MAX_BANK_INDEX


def normalize_editor_request(raw: Any) -> dict[str, Any]:
    """``normalizeEditorRequest(raw)`` (webapp/server/electrode-editor-server.mjs): checks in Node's exact order
    and raises ``ValueError`` with Node's verbatim message."""
    if not isinstance(raw, dict) or raw.get('action') not in ('prepare', 'evaluate') or not _id(raw.get('parent_id')):
        raise ValueError(INVALID_REQUEST)
    if raw['action'] == 'prepare':
        if _sorted_keys(raw) != 'action,parent_id':
            raise ValueError(INVALID_PREPARE)
        return {'action': 'prepare', 'parent_id': raw['parent_id']}
    seed = raw.get('seed')
    if (_sorted_keys(raw) != 'action,parent_digest,parent_id,seed,slots'
            or not _id(raw.get('parent_digest'))
            or not (jsjson.is_number(seed) and jsjson.to_number(seed) == EDITOR_SEED)):
        raise ValueError(INVALID_PROTOCOL)
    slots = raw.get('slots')
    if not isinstance(slots, (list, tuple)) or len(slots) != 64 or any(not _valid_slot(s) for s in slots):
        raise ValueError(INVALID_SLOTS)
    if sum(1 for s in slots if s['enabled']) < 2:
        raise ValueError(MIN_ACTIVE)
    return {
        'action': 'evaluate',
        'parent_id': raw['parent_id'],
        'parent_digest': raw['parent_digest'],
        'seed': EDITOR_SEED,
        'slots': [{'bank_index': int(jsjson.to_number(s['bank_index'])), 'enabled': s['enabled']} for s in slots],
    }


if _HAS_PYDANTIC:
    def _hex_id(value: str) -> str:
        if not _HEX64.fullmatch(value):
            raise ValueError('must be 64 lowercase hexadecimal digits')
        return value

    HexId = Annotated[str, Field(strict=True, json_schema_extra={'pattern': '^[0-9a-f]{64}$'}), AfterValidator(_hex_id)]

    class ElectrodeSlot(BaseModel):
        """One of the 64 fixed electrode slots of a parent layout."""
        model_config = ConfigDict(extra='forbid')
        bank_index: integer(ge=0, le=MAX_BANK_INDEX)
        enabled: Annotated[bool, Field(strict=True)]

    class PrepareEditorRequest(BaseModel):
        """Load the candidate bank indices inside each region patch of a saved 64-electrode layout."""
        model_config = ConfigDict(extra='forbid')
        action: Literal['prepare']
        parent_id: HexId

        @model_validator(mode='before')
        @classmethod
        def _node_rules(cls, data: Any) -> Any:
            return data if isinstance(data, cls) else normalize_editor_request(data)

        def canonical(self) -> dict[str, Any]:
            return {'action': 'prepare', 'parent_id': self.parent_id}

    class EvaluateEditorRequest(BaseModel):
        """Evaluate an edited subset or within-patch relocation of a parent layout's 64 electrode slots."""
        model_config = ConfigDict(extra='forbid')
        action: Literal['evaluate']
        parent_id: HexId
        parent_digest: HexId
        seed: Annotated[Literal[2026], BeforeValidator(js_integer)]
        slots: Annotated[list[ElectrodeSlot], Field(min_length=64, max_length=64)]

        @model_validator(mode='before')
        @classmethod
        def _node_rules(cls, data: Any) -> Any:
            return data if isinstance(data, cls) else normalize_editor_request(data)

        def canonical(self) -> dict[str, Any]:
            return {
                'action': 'evaluate',
                'parent_id': self.parent_id,
                'parent_digest': self.parent_digest,
                'seed': EDITOR_SEED,
                'slots': [{'bank_index': slot.bank_index, 'enabled': slot.enabled} for slot in self.slots],
            }

    def _before_editor_union(value: Any) -> Any:
        if isinstance(value, (PrepareEditorRequest, EvaluateEditorRequest)):
            return value
        return normalize_editor_request(value)

    ElectrodeEditorRequest = Annotated[
        Union[PrepareEditorRequest, EvaluateEditorRequest],
        Field(discriminator='action'),
        BeforeValidator(_before_editor_union),
    ]

    _ADAPTER: TypeAdapter = TypeAdapter(ElectrodeEditorRequest)

    def canonical(value: PrepareEditorRequest | EvaluateEditorRequest) -> dict[str, Any]:
        """The registry's canonical value of a validated editor request."""
        return value.canonical()
else:
    ElectrodeSlot = PrepareEditorRequest = EvaluateEditorRequest = ElectrodeEditorRequest = None  # type: ignore[assignment,misc]

    def canonical(value: Any) -> dict[str, Any]:
        return normalize_editor_request(value)
