"""Optional scientific model choices (webapp/contracts/scientific-options.mjs).

Defaults normalize to ``None`` and are left out of canonical requests, so a
default request keeps its original cache key.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator

from . import jsjson
from .types import JsNumber, empty_as_absent, js_integer, js_integer_or_none, known_tag, number

_EXACT = ConfigDict(extra='forbid')

# Node's lists in scientific-options.mjs; tests/test_schema_parity.py compares them.
CONDUCTIVITY_SCENARIOS = ('skull_x0.5', 'skull_x2')
SPATIAL_NOISE_LENGTHS_MM = (10, 20, 40)
DATA_PRIOR_LENGTHS_MM = (5, 10, 15, 20, 30, 40)


def _half(value: float) -> float:
    if value != 0.5:
        raise ValueError('must be 0.5')
    return value


Half = Annotated[JsNumber, AfterValidator(_half), Field(json_schema_extra={'const': 0.5})]


class IidNoise(BaseModel):
    """Accepted for the production model and dropped from canonical output."""
    model_config = _EXACT
    kind: Literal['iid']


class SpatialNoise(BaseModel):
    model_config = _EXACT
    kind: Literal['spatial']
    rho: Half
    length_mm: Annotated[Literal[SPATIAL_NOISE_LENGTHS_MM], BeforeValidator(js_integer)]  # type: ignore[valid-type]

    def canonical(self) -> dict[str, Any]:
        return {'kind': 'spatial', 'rho': 0.5, 'length_mm': self.length_mm}


class BrainBackgroundNoise(BaseModel):
    """Design evaluation only; the radius search rejects it."""
    model_config = _EXACT
    kind: Literal['brain_background']
    fraction: Half

    def canonical(self) -> dict[str, Any]:
        return {'kind': 'brain_background', 'fraction': 0.5}


NoiseModel = Annotated[Union[IidNoise, SpatialNoise, BrainBackgroundNoise], Field(discriminator='kind'),
                       known_tag('kind', ('iid', 'spatial', 'brain_background'))]

ConductivityScenario = Annotated[Literal[CONDUCTIVITY_SCENARIOS] | None, BeforeValidator(empty_as_absent)]  # type: ignore[valid-type]

HeadId = Annotated[
    Annotated[str, StringConstraints(strict=True, max_length=40, pattern=r'^[a-z0-9]+(?:[_-][a-z0-9]+)*$')] | None,
    BeforeValidator(empty_as_absent),
]


def _robustness_absent(value: Any) -> Any:
    # `false` means off, but `0` does not: Python's 0 == False must not leak in.
    return None if value is None or value is False or (isinstance(value, str) and value == '') else value


Robustness = Annotated[Literal['standard/1'] | None, BeforeValidator(_robustness_absent)]


def _four_significant_digits(value: float) -> float:
    if not jsjson.equals_to_precision(value, 4):
        raise ValueError('must have at most 4 significant digits')
    return value


def _two_decimals(value: float) -> float:
    if jsjson.round_half_up(value * 100) / 100 != value:
        raise ValueError('must have at most 2 decimals')
    return value


RegionGain = Annotated[number(ge=1e-3, le=1e3), AfterValidator(_four_significant_digits)]


class DataPrior(BaseModel):
    """The ``request`` value of an ``eeg-data-prior/1`` file; rejected, never rounded."""
    model_config = _EXACT
    # frontal, central, parietal, occipital, temporal_left, temporal_right, other (dk40-six-roi-v1)
    region_gain: Annotated[list[RegionGain], Field(min_length=7, max_length=7)]
    rho: Annotated[number(ge=0, le=0.95), AfterValidator(_two_decimals)]
    # Required but nullable: null exactly when rho is 0.
    length_mm: Annotated[Literal[DATA_PRIOR_LENGTHS_MM] | None, BeforeValidator(js_integer_or_none)]  # type: ignore[valid-type]

    @model_validator(mode='after')
    def _length_matches_rho(self) -> DataPrior:
        if (self.rho == 0) != (self.length_mm is None):
            raise ValueError('length_mm must be null exactly when rho is 0')
        return self

    def canonical(self) -> dict[str, Any]:
        return {'region_gain': list(self.region_gain), 'rho': self.rho, 'length_mm': self.length_mm}


DATA_PRIOR_SCHEMA = 'eeg-data-prior/1'
DATA_PRIOR_REGIONS = ('frontal', 'central', 'parietal', 'occipital', 'temporal_left', 'temporal_right', 'other')


def _js_truthy(value: Any) -> bool:
    if value is None or value is False or value == '':
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0 and value == value
    return True


def normalize_data_prior_value(value: Any) -> dict[str, Any] | None:
    """``normalizeDataPrior(value)`` with Node's verbatim Chinese messages."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('数据先验格式无效')
    keys = ','.join(sorted(value, key=lambda key: key.encode('utf-16-be', errors='surrogatepass')))
    if keys != 'length_mm,region_gain,rho':
        raise ValueError('数据先验格式无效')
    gains = value.get('region_gain')
    rho = value.get('rho')
    length = value.get('length_mm')
    if (
        not isinstance(gains, list)
        or len(gains) != len(DATA_PRIOR_REGIONS)
        or not all(
            jsjson.is_number(g) and 1e-3 <= jsjson.to_number(g) <= 1e3 and jsjson.equals_to_precision(jsjson.to_number(g), 4)
            for g in gains
        )
    ):
        raise ValueError('数据先验的区域增益须为7个保留4位有效数字的正数')
    if not jsjson.is_number(rho):
        raise ValueError('数据先验的噪声相关比例无效')
    rho_num = jsjson.to_number(rho)
    if not (0.0 <= rho_num <= 0.95) or jsjson.round_half_up(rho_num * 100.0) / 100.0 != rho_num:
        raise ValueError('数据先验的噪声相关比例无效')
    if (length is not None) if rho_num == 0.0 else not (jsjson.is_number(length) and jsjson.to_number(length) in DATA_PRIOR_LENGTHS_MM):
        raise ValueError('数据先验的噪声相关长度无效')
    return {
        'region_gain': [jsjson.to_number(g) for g in gains],
        'rho': rho_num,
        'length_mm': None if length is None else int(jsjson.to_number(length)),
    }


def data_prior_from_file(document: Any) -> dict[str, Any] | None:
    """``dataPriorFromFile(document)`` from ``webapp/contracts/scientific-options.mjs``."""
    if (
        not isinstance(document, dict)
        or document.get('schema') != DATA_PRIOR_SCHEMA
        or not isinstance(document.get('regions'), list)
        or jsjson.stringify(document['regions']) != jsjson.stringify(list(DATA_PRIOR_REGIONS))
        or not _js_truthy(document.get('fit'))
        or not isinstance(document.get('channels'), list)
    ):
        raise ValueError('不是eeg-data-prior/1数据先验文件')
    return normalize_data_prior_value(document.get('request'))
