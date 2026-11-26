"""Source-reception request (``normalizeReceptionRequest`` and ``normalizeSourceRequest`` in
webapp/contracts/source-reception.mjs).

The body of ``POST /api/source-reception/jobs`` and ``/lookup``, the request of a community task of kind
``source-reception``, and the ``request`` of every reception result. One format in two versions, told apart as Node
tells them: a request without ``mode`` is a v1 request (``source-reception/1``), whose sources lie near the anchor of
one of six regions; a request with ``mode`` is a v2 request (``source-reception/2``): one frozen generation source
(``single_source``), six generation sources within one region (``multi_source``) or one fixed source in each of one
to six regions (``cross_region``), optionally with the atlas definition ``dk40-six-roi-v1``.

``normalize_reception_request`` (both versions) and ``normalize_source_request`` (v1) are line-by-line ports: they
check in Node's order and raise ``ValueError`` with Node's message, which the Node host returns from the reception
endpoints. ``SourceReceptionRequest`` describes the canonical forms for the OpenAPI document and accepts exactly
what ``normalize_reception_request`` accepts. The canonical form keeps Node's key order: ``record_id``,
``brain_region``, ``waveform``, ``artifact_scale``, ``seed`` in v1; ``record_id``, ``waveform``,
``artifact_scale``, ``seed``, ``mode``, ``region_definition`` (when sent) and the mode's source field in v2, with
``brain_regions`` in the order of ``SOURCE_REGIONS``. Node rejects every other field, so nothing is dropped.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Discriminator, Field, Tag

from . import jsjson
from .types import integer

__all__ = [
    'SourceReceptionRequest', 'SourceReceptionV1', 'SingleSourceReception', 'MultiSourceReception',
    'CrossRegionReception', 'normalize_reception_request', 'normalize_source_request', 'canonical',
    'SOURCE_REGIONS', 'WAVEFORMS', 'ARTIFACT_SCALES', 'MODES', 'REGION_DEFINITION', 'MAX_SEED', 'MAX_SOURCE_INDEX',
    'MAX_CROSS_REGIONS',
]

# Node's SOURCE_REGIONS, compared by tests/test_schema_parity.py. Node's CROSS_REGIONS is the same list
# (check-cross-region-contract.mjs), and the order of the canonical brain_regions.
SOURCE_REGIONS = ('frontal', 'central', 'parietal', 'occipital', 'temporal_left', 'temporal_right')
WAVEFORMS = ('burst', 'rhythm')
ARTIFACT_SCALES = (0, 0.5, 1, 2, 4)
MODES = ('single_source', 'multi_source', 'cross_region')
REGION_DEFINITION = 'dk40-six-roi-v1'
MAX_SEED = 9999
MAX_SOURCE_INDEX = 255
MAX_CROSS_REGIONS = 6
V1_FIELDS = ('record_id', 'brain_region', 'waveform', 'artifact_scale', 'seed')
_ID = re.compile('[a-f0-9]{64}')

# Node's messages, verbatim.
INVALID_FIELDS = '源实验配置字段无效'
INVALID_CHOICE = '请选择已有完整布局、支持的源区与波形；种子范围0–9999'
UNSUPPORTED_DEFINITION = 'Unsupported source ROI definition'
INVALID_MODE = '源模式或字段无效'
INVALID_SOURCE_INDEX = '选择0–255中的一个冻结生成源'
INVALID_CROSS_REGIONS = '跨区域模式需要选择1–6个不同的源区域'


# --- Node's rules ----------------------------------------------------------------

def _utf16(key: str) -> bytes:
    return key.encode('utf-16-be', errors='surrogatepass')


def _sorted_keys(keys: Any) -> str:
    """``keys.sort().join(',')``: UTF-16 code-unit order."""
    return ','.join(sorted((str(key) for key in keys), key=_utf16))


def _is_array(value: Any) -> bool:
    return isinstance(value, (list, tuple))


def _in(value: Any, allowed: tuple[str, ...]) -> bool:
    """``allowed.includes(value)`` for a list of strings."""
    return isinstance(value, str) and value in allowed


def _scale(value: Any) -> int | float | None:
    """The entry of ``ARTIFACT_SCALES`` that ``SCALES.includes(value)`` finds (SameValueZero: -0 is 0, ``true`` is
    not 1), or None."""
    if not jsjson.is_number(value):
        return None
    number = jsjson.to_number(value)
    return next((scale for scale in ARTIFACT_SCALES if scale == number), None)


def _integer_in(value: Any, high: int) -> bool:
    """``Number.isInteger(value) && value >= 0 && value <= high``."""
    return jsjson.is_integer(value) and 0 <= jsjson.to_number(value) <= high


def normalize_source_request(raw: Any) -> dict[str, Any]:
    """``normalizeSourceRequest(raw)``: the canonical v1 request; raises ``ValueError`` with Node's message where
    Node throws. ``raw`` is a ``jsjson.parse`` value or plain Python data (tuples count as arrays, ``bool`` is not a
    number); it is not changed."""
    # `!x || Array.isArray(x) || typeof x !== 'object'`, then any key outside the five; missing keys pass here.
    if not isinstance(raw, dict) or any(str(key) not in V1_FIELDS for key in raw):
        raise ValueError(INVALID_FIELDS)
    record_id, scale, seed = raw.get('record_id'), _scale(raw.get('artifact_scale')), raw.get('seed')
    if (not (isinstance(record_id, str) and _ID.fullmatch(record_id)) or not _in(raw.get('brain_region'), SOURCE_REGIONS)
            or not _in(raw.get('waveform'), WAVEFORMS) or scale is None or not _integer_in(seed, MAX_SEED)):
        raise ValueError(INVALID_CHOICE)
    return {'record_id': record_id, 'brain_region': raw['brain_region'], 'waveform': raw['waveform'],
            'artifact_scale': scale, 'seed': int(jsjson.to_number(seed))}


def normalize_reception_request(raw: Any) -> dict[str, Any]:
    """``normalizeReceptionRequest(raw)``: the canonical request of either version; raises ``ValueError`` with
    Node's message where Node throws, checking in Node's order. A value without ``mode`` (``x?.mode === undefined``:
    not an object, or an object without the key) is a v1 request; any value of ``mode``, ``null`` included, makes
    it v2. ``raw`` is a ``jsjson.parse`` value or plain Python data; it is not changed."""
    if not isinstance(raw, dict) or 'mode' not in raw:
        return normalize_source_request(raw)
    definition = 'region_definition' in raw
    if definition and not (isinstance(raw['region_definition'], str) and raw['region_definition'] == REGION_DEFINITION):
        raise ValueError(UNSUPPORTED_DEFINITION)
    mode = raw['mode']
    single, cross = _in(mode, ('single_source',)), _in(mode, ('cross_region',))
    expected = _sorted_keys(['record_id', 'mode', 'source_index' if single else 'brain_regions' if cross else 'brain_region',
                             'waveform', 'artifact_scale', 'seed', *(['region_definition'] if definition else [])])
    if not _in(mode, MODES) or _sorted_keys(raw) != expected:
        raise ValueError(INVALID_MODE)
    common = normalize_source_request({
        'record_id': raw.get('record_id'), 'brain_region': 'frontal' if single or cross else raw.get('brain_region'),
        'waveform': raw.get('waveform'), 'artifact_scale': raw.get('artifact_scale'), 'seed': raw.get('seed'),
    })
    if single and not _integer_in(raw.get('source_index'), MAX_SOURCE_INDEX):
        raise ValueError(INVALID_SOURCE_INDEX)
    regions = raw.get('brain_regions')
    if cross and (not _is_array(regions) or not 1 <= len(regions) <= MAX_CROSS_REGIONS
                  or not all(_in(region, SOURCE_REGIONS) for region in regions) or len(set(regions)) != len(regions)):
        raise ValueError(INVALID_CROSS_REGIONS)
    out = {'record_id': common['record_id'], 'waveform': common['waveform'], 'artifact_scale': common['artifact_scale'],
           'seed': common['seed'], 'mode': mode}
    if definition:
        out['region_definition'] = REGION_DEFINITION
    if single:
        out['source_index'] = int(jsjson.to_number(raw['source_index']))
    elif cross:
        out['brain_regions'] = [region for region in SOURCE_REGIONS if region in regions]
    else:
        out['brain_region'] = common['brain_region']
    return out


# --- Schema --------------------------------------------------------------------

RecordId = Annotated[str, Field(strict=True, pattern='^[a-f0-9]{64}$',
                                description='The library record of the layout: a lowercase SHA-256 hex digest.')]
Region = Literal[SOURCE_REGIONS]  # type: ignore[valid-type]
Waveform = Literal[WAVEFORMS]  # type: ignore[valid-type]
ArtifactScale = Annotated[Literal[ARTIFACT_SCALES], Field(json_schema_extra={'type': 'number'})]  # type: ignore[valid-type]
Seed = integer(ge=0, le=MAX_SEED)

_EXACT = ConfigDict(extra='forbid')


def _absent_default(schema: dict[str, Any]) -> None:
    # Optional but not nullable: the canonical form leaves the field out instead of writing null.
    schema.pop('default', None)


class SourceReceptionV1(BaseModel):
    """A v1 request (no ``mode``): the six generation sources nearest to the region's fixed coordinate anchor."""
    model_config = _EXACT
    record_id: RecordId
    brain_region: Region
    waveform: Waveform
    artifact_scale: ArtifactScale
    seed: Seed

    def canonical(self) -> dict[str, Any]:
        return {'record_id': self.record_id, 'brain_region': self.brain_region, 'waveform': self.waveform,
                'artifact_scale': self.artifact_scale, 'seed': self.seed}


class _V2(BaseModel):
    model_config = _EXACT
    record_id: RecordId
    waveform: Waveform
    artifact_scale: ArtifactScale
    seed: Seed

    def _common(self, mode: str) -> dict[str, Any]:
        out: dict[str, Any] = {'record_id': self.record_id, 'waveform': self.waveform,
                               'artifact_scale': self.artifact_scale, 'seed': self.seed, 'mode': mode}
        if self.region_definition is not None:  # type: ignore[attr-defined]
            out['region_definition'] = REGION_DEFINITION
        return out


def _definition() -> Any:
    return Field(default=None, json_schema_extra=_absent_default,
                 description='The source ROI atlas, kept in the identity when sent.')


class SingleSourceReception(_V2):
    """One frozen generation source, by its index."""
    mode: Literal['single_source']
    region_definition: Literal[REGION_DEFINITION] = _definition()  # type: ignore[valid-type]
    source_index: integer(ge=0, le=MAX_SOURCE_INDEX)  # type: ignore[valid-type]

    def canonical(self) -> dict[str, Any]:
        return {**self._common('single_source'), 'source_index': self.source_index}


class MultiSourceReception(_V2):
    """Six generation sources within one region."""
    mode: Literal['multi_source']
    region_definition: Literal[REGION_DEFINITION] = _definition()  # type: ignore[valid-type]
    brain_region: Region

    def canonical(self) -> dict[str, Any]:
        return {**self._common('multi_source'), 'brain_region': self.brain_region}


class CrossRegionReception(_V2):
    """One fixed source in each of one to six regions, each listed once and in the order of the region list."""
    mode: Literal['cross_region']
    region_definition: Literal[REGION_DEFINITION] = _definition()  # type: ignore[valid-type]
    brain_regions: Annotated[list[Region], Field(min_length=1, max_length=MAX_CROSS_REGIONS,
                                                 json_schema_extra={'uniqueItems': True})]

    def canonical(self) -> dict[str, Any]:
        return {**self._common('cross_region'), 'brain_regions': list(self.brain_regions)}


_MODELS = (SourceReceptionV1, SingleSourceReception, MultiSourceReception, CrossRegionReception)


def _version(value: Any) -> str:
    # Node tells the versions apart by whether mode is present; Node's rules have run, so a dict is canonical.
    if isinstance(value, dict):
        return value.get('mode', 'v1')
    return 'v1' if isinstance(value, SourceReceptionV1) else value.mode


def _node_rules(value: Any) -> Any:
    # Node's rules decide and give the message; the tagged union then checks the canonical value it describes.
    if isinstance(value, _MODELS):
        return value
    return normalize_reception_request(value)


SourceReceptionRequest = Annotated[
    Union[Annotated[SourceReceptionV1, Tag('v1')], Annotated[SingleSourceReception, Tag('single_source')],
          Annotated[MultiSourceReception, Tag('multi_source')], Annotated[CrossRegionReception, Tag('cross_region')]],
    Discriminator(_version), BeforeValidator(_node_rules),
]


def canonical(value: SourceReceptionV1 | SingleSourceReception | MultiSourceReception | CrossRegionReception
              ) -> dict[str, Any]:
    """The registry's canonical value of a validated request."""
    return value.canonical()
