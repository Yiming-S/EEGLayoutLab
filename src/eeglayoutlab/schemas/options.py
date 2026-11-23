"""Optional scientific model choices (webapp/contracts/scientific-options.mjs).

Defaults normalize to ``None`` and are left out of canonical requests, so a
default request keeps its original cache key.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator

from . import jsjson
from .types import JsNumber, empty_as_absent, js_integer, js_integer_or_none, number

_EXACT = ConfigDict(extra='forbid')


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
    length_mm: Annotated[Literal[10, 20, 40], BeforeValidator(js_integer)]

    def canonical(self) -> dict[str, Any]:
        return {'kind': 'spatial', 'rho': 0.5, 'length_mm': self.length_mm}


class BrainBackgroundNoise(BaseModel):
    """Design evaluation only; the radius search rejects it."""
    model_config = _EXACT
    kind: Literal['brain_background']
    fraction: Half

    def canonical(self) -> dict[str, Any]:
        return {'kind': 'brain_background', 'fraction': 0.5}


NoiseModel = Annotated[Union[IidNoise, SpatialNoise, BrainBackgroundNoise], Field(discriminator='kind')]

ConductivityScenario = Annotated[Literal['skull_x0.5', 'skull_x2'] | None, BeforeValidator(empty_as_absent)]

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
    length_mm: Annotated[Literal[5, 10, 15, 20, 30, 40] | None, BeforeValidator(js_integer_or_none)]

    @model_validator(mode='after')
    def _length_matches_rho(self) -> DataPrior:
        if (self.rho == 0) != (self.length_mm is None):
            raise ValueError('length_mm must be null exactly when rho is 0')
        return self

    def canonical(self) -> dict[str, Any]:
        return {'region_gain': list(self.region_gain), 'rho': self.rho, 'length_mm': self.length_mm}
