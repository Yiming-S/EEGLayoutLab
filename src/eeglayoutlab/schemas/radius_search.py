"""Radius-search request (``normalizeRequest`` in webapp/server/local-compute-server.mjs).

The body of ``POST /api/local-compute/jobs`` and ``/lookup``, and the ``request`` of every radius cache record.
``normalize_request`` is a line-by-line port: it checks in Node's order and raises ``ValueError`` with Node's
message, which the Node host returns to the interface and writes into failed tasks. ``RadiusSearchRequest``
describes the canonical form for the OpenAPI document and accepts exactly what ``normalize_request`` accepts.

The canonical form keeps Node's key order: ``region_count``, ``radius_mm``, ``mode``, ``mask_codes`` (preset mode
only), ``noise_model`` and ``data_prior`` (only when not the default). A free mode drops an empty ``mask_codes``, and
the independent noise model is dropped, so default requests keep their original cache keys.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from . import jsjson
from .options import DATA_PRIOR_LENGTHS_MM, SPATIAL_NOISE_LENGTHS_MM, DataPrior, SpatialNoise
from .types import js_integer

__all__ = [
    'RadiusSearchRequest', 'normalize_request', 'canonical', 'MASK_CODES', 'REGION_COUNTS', 'RADII_MM', 'MODES',
]

# Node's MASK_CODES (local-compute-server.mjs), compared by tests/test_schema_parity.py.
MASK_CODES = ('PL', 'PR', 'AL', 'AR', 'FL', 'FM', 'FR', 'OL', 'OR')
REGION_COUNTS = (1, 2, 3, 4, 6)
# 15-80 mm in steps of 5.
RADII_MM = tuple(range(15, 81, 5))
MODES = ('whole_surface', 'low_hair', 'preset')
FIELDS = ('region_count', 'radius_mm', 'mode', 'mask_codes', 'noise_model', 'data_prior')

# Node's messages, verbatim.
NOT_OBJECT = '配置必须是JSON对象'
UNKNOWN_FIELD = '配置含未支持字段'
NOISE_FORMAT = '噪声模型格式无效'
NOISE_BRAIN_BACKGROUND = '脑背景噪声只用于定位评价，布局搜索不支持'
NOISE_UNSUPPORTED = '不支持的噪声模型'
PRIOR_FORMAT = '数据先验格式无效'
PRIOR_GAINS = '数据先验的区域增益须为7个保留4位有效数字的正数'
PRIOR_RHO = '数据先验的噪声相关比例无效'
PRIOR_LENGTH = '数据先验的噪声相关长度无效'
PRIOR_WITH_NOISE = '数据先验已包含噪声结构，不能同时选择噪声模型'
REGION_COUNT = '区域数只支持1、2、3、4、6'
RADIUS = '半径须为15–80 mm，步长5 mm'
MODE = '不支持的区域模式'
PRESET_MASKS = '该组合的细分解剖掩膜尚未建立；请选择已支持的耳后、耳周、前额或眶周代理区域'
FREE_MASKS = '自由中心模式不接受指定掩膜'


# --- Node's rules ----------------------------------------------------------------

def _is_object(value: Any) -> bool:
    """``value && typeof value === 'object' && !Array.isArray(value)``."""
    return isinstance(value, dict)


def _is_array(value: Any) -> bool:
    return isinstance(value, (list, tuple))


def _sorted_keys(value: dict) -> str:
    """``Object.keys(value).sort().join(',')``: UTF-16 code-unit order."""
    return ','.join(sorted((str(key) for key in value),
                           key=lambda key: key.encode('utf-16-be', errors='surrogatepass')))


def _number_in(value: Any, allowed: tuple[int, ...]) -> bool:
    """``allowed.includes(value)`` for a list of numbers (SameValueZero; ``true`` is not 1)."""
    return jsjson.is_number(value) and jsjson.to_number(value) in allowed


def _four_digits(value: Any) -> bool:
    """``fourDigits`` (scientific-options.mjs): a finite number in [1e-3, 1e3] with at most 4 significant digits."""
    if not jsjson.is_number(value):
        return False
    number = jsjson.to_number(value)
    return 1e-3 <= number <= 1e3 and jsjson.equals_to_precision(number, 4)


def _noise_model(value: Any) -> dict[str, Any] | None:
    """``normalizeNoiseModel(value, {allowBrainBackground: false})``: the spatial preset, or ``None`` for
    independent noise."""
    if value is None:
        return None
    if not _is_object(value):
        raise ValueError(NOISE_FORMAT)
    keys, kind = _sorted_keys(value), value.get('kind')
    if kind == 'iid' and keys == 'kind':
        return None
    if (kind == 'spatial' and keys == 'kind,length_mm,rho' and _number_in(value.get('rho'), (0.5,))
            and _number_in(value.get('length_mm'), SPATIAL_NOISE_LENGTHS_MM)):
        return {'kind': 'spatial', 'rho': 0.5, 'length_mm': int(jsjson.to_number(value['length_mm']))}
    if kind == 'brain_background' and keys == 'fraction,kind' and _number_in(value.get('fraction'), (0.5,)):
        raise ValueError(NOISE_BRAIN_BACKGROUND)
    raise ValueError(NOISE_UNSUPPORTED)


def _data_prior(value: Any, noise_model: dict[str, Any] | None) -> dict[str, Any] | None:
    """``normalizeDataPrior(value, {noiseModel})`` (scientific-options.mjs), rejected, never rounded."""
    if value is None:
        return None
    if not _is_object(value) or _sorted_keys(value) != 'length_mm,region_gain,rho':
        raise ValueError(PRIOR_FORMAT)
    # The joined names also match {"length_mm,region_gain": ..., "rho": ...}, which has no region_gain.
    gains, rho, length = value.get('region_gain'), value.get('rho'), value.get('length_mm')
    if not _is_array(gains) or len(gains) != 7 or not all(_four_digits(gain) for gain in gains):
        raise ValueError(PRIOR_GAINS)
    if not jsjson.is_number(rho):
        raise ValueError(PRIOR_RHO)
    rho = jsjson.to_number(rho)
    if not 0 <= rho <= 0.95 or jsjson.round_half_up(rho * 100) / 100 != rho:
        raise ValueError(PRIOR_RHO)
    if (length is not None) if rho == 0 else not _number_in(length, DATA_PRIOR_LENGTHS_MM):
        raise ValueError(PRIOR_LENGTH)
    if noise_model:
        raise ValueError(PRIOR_WITH_NOISE)
    return {'region_gain': [jsjson.to_number(gain) for gain in gains], 'rho': rho,
            'length_mm': None if length is None else int(jsjson.to_number(length))}


def normalize_request(value: Any) -> dict[str, Any]:
    """``normalizeRequest(value)``: the canonical request; raises ``ValueError`` with Node's message where Node
    throws, checking in Node's order. ``value`` is a ``jsjson.parse`` value or plain Python data (tuples count as
    arrays, ``bool`` is not a number); it is not changed."""
    if not _is_object(value):
        raise ValueError(NOT_OBJECT)
    if any(key not in FIELDS for key in value):
        raise ValueError(UNKNOWN_FIELD)
    noise_model = _noise_model(value.get('noise_model'))
    prior = _data_prior(value.get('data_prior'), noise_model)
    noise = {**({'noise_model': noise_model} if noise_model else {}), **({'data_prior': prior} if prior else {})}
    region_count, radius_mm, mode = value.get('region_count'), value.get('radius_mm'), value.get('mode')
    if not _number_in(region_count, REGION_COUNTS):
        raise ValueError(REGION_COUNT)
    if not jsjson.is_integer(radius_mm) or jsjson.to_number(radius_mm) not in RADII_MM:
        raise ValueError(RADIUS)
    if not (isinstance(mode, str) and mode in MODES):
        raise ValueError(MODE)
    region_count, radius_mm = int(jsjson.to_number(region_count)), int(jsjson.to_number(radius_mm))
    masks = value.get('mask_codes')
    if mode == 'preset':
        if (not _is_array(masks) or len(masks) != region_count
                or any(not (isinstance(code, str) and code in MASK_CODES) for code in masks)):
            raise ValueError(PRESET_MASKS)
        return {'region_count': region_count, 'radius_mm': radius_mm, 'mode': mode, 'mask_codes': list(masks), **noise}
    # Absent and [] are accepted; null is not.
    if 'mask_codes' in value and (not _is_array(masks) or len(masks)):
        raise ValueError(FREE_MASKS)
    return {'region_count': region_count, 'radius_mm': radius_mm, 'mode': mode, **noise}


# --- Schema --------------------------------------------------------------------

def _absent_default(schema: dict[str, Any]) -> None:
    # Optional but not nullable: the canonical form leaves the field out instead of writing null.
    schema.pop('default', None)


class RadiusSearchRequest(BaseModel):
    """Body of ``POST /api/local-compute/jobs`` and ``/lookup`` in its canonical form: a free mode has no
    ``mask_codes``, and the independent noise model is left out. In preset mode ``mask_codes`` lists exactly
    ``region_count`` sites, repeats allowed, in order."""
    model_config = ConfigDict(extra='forbid')
    region_count: Annotated[Literal[REGION_COUNTS], BeforeValidator(js_integer)]  # type: ignore[valid-type]
    radius_mm: Annotated[Literal[RADII_MM], BeforeValidator(js_integer)]  # type: ignore[valid-type]
    mode: Literal[MODES]  # type: ignore[valid-type]
    mask_codes: Annotated[list[Literal[MASK_CODES]], Field(min_length=1, max_length=max(REGION_COUNTS))] = Field(  # type: ignore[valid-type]
        default=None, json_schema_extra=_absent_default)
    noise_model: SpatialNoise = Field(default=None, json_schema_extra=_absent_default)
    data_prior: DataPrior = Field(default=None, json_schema_extra=_absent_default)

    @model_validator(mode='before')
    @classmethod
    def _node_rules(cls, data: Any) -> Any:
        # Node's rules decide; the fields then check the canonical value, which the schema describes.
        return data if isinstance(data, cls) else normalize_request(data)

    def canonical(self) -> dict[str, Any]:
        out: dict[str, Any] = {'region_count': self.region_count, 'radius_mm': self.radius_mm, 'mode': self.mode}
        if self.mask_codes is not None:
            out['mask_codes'] = list(self.mask_codes)
        if self.noise_model is not None:
            out['noise_model'] = self.noise_model.canonical()
        if self.data_prior is not None:
            out['data_prior'] = self.data_prior.canonical()
        return out


def canonical(value: RadiusSearchRequest) -> dict[str, Any]:
    """The registry's canonical value of a validated request."""
    return value.canonical()
