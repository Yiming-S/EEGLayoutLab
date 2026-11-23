"""Design-evaluation request (``normalizeDesignRequest`` in webapp/server/design-evaluation-server.mjs).

``DesignEvaluationRequest`` validates what Node accepts; ``canonical()`` builds
the object Node returns, in Node's key order, and ``canonical_json()`` its
``JSON.stringify`` text, from which Node derives the cache key.
"""
from __future__ import annotations

from itertools import combinations
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from . import jsjson
from .options import ConductivityScenario, DataPrior, HeadId, IidNoise, NoiseModel, Robustness
from .types import JsInteger, integer, js_integer, number

DEFAULT_DESIGN_NAME = '导入布局'
ELECTRODES = 64
MIN_SPACING_MM = 4 - 1e-7


def _design_name(value: Any) -> str:
    # Any non-string name means the default; strings keep their first 100 UTF-16 units.
    return jsjson.slice_utf16(value, 100) if isinstance(value, str) else DEFAULT_DESIGN_NAME


Coordinate = number(ge=-500, le=500)
Point = tuple[Coordinate, Coordinate, Coordinate]


class ElectrodeDesign(BaseModel):
    """``eeg-electrode-design/1`` in Ernie native millimetres. Other design fields are dropped."""
    model_config = ConfigDict(extra='ignore')
    schema_: Literal['eeg-electrode-design/1'] = Field(alias='schema')
    coordinate_system: Literal['ernie_native_mm']
    unit: Literal['mm']
    name: Annotated[str, BeforeValidator(_design_name)] = DEFAULT_DESIGN_NAME
    xyz_mm: Annotated[list[Point], Field(min_length=ELECTRODES, max_length=ELECTRODES)]
    region_indices: Annotated[list[JsInteger], Field(min_length=ELECTRODES, max_length=ELECTRODES)]

    @model_validator(mode='after')
    def _geometry(self) -> ElectrodeDesign:
        # Tuple equality treats -0 and 0 as equal, like Node's p.join(',').
        if len(set(self.xyz_mm)) != ELECTRODES:
            raise ValueError('需要64个互异的有限坐标')
        regions = len(set(self.region_indices))
        if regions not in (1, 2, 3, 4, 6) or any(not 0 <= v < regions for v in self.region_indices):
            raise ValueError('区域编号错误')
        counts = sorted((self.region_indices.count(i) for i in range(regions)), reverse=True)
        if counts != [ELECTRODES // regions + int(i < ELECTRODES % regions) for i in range(regions)]:
            raise ValueError('区域分配须均衡，总数64')
        for p, q in combinations(self.xyz_mm, 2):
            if jsjson.hypot(*(a - b for a, b in zip(p, q))) < MIN_SPACING_MM:
                raise ValueError('最小直线点距需达到4 mm')
        return self

    def canonical(self) -> dict[str, Any]:
        return {
            'schema': self.schema_,
            'coordinate_system': self.coordinate_system,
            'unit': self.unit,
            'name': self.name,
            'xyz_mm': [list(p) for p in self.xyz_mm],
            'region_indices': list(self.region_indices),
        }


class DesignEvaluationRequest(BaseModel):
    """Body of ``POST /api/design-evaluation/jobs``. Unknown top-level fields are rejected."""
    model_config = ConfigDict(extra='forbid')
    action: Literal['evaluate', 'perturb']
    design: ElectrodeDesign
    radius_mm: Annotated[Literal[3, 6, 10], BeforeValidator(js_integer)]
    seed: integer(ge=0, le=9999)
    noise_model: NoiseModel | None = None
    conductivity_scenario: ConductivityScenario = None
    head_id: HeadId = None
    robustness: Robustness = None
    data_prior: DataPrior | None = None

    @property
    def effective_noise_model(self):
        return None if isinstance(self.noise_model, IidNoise) else self.noise_model

    @model_validator(mode='after')
    def _combinations(self) -> DesignEvaluationRequest:
        evaluate = self.action == 'evaluate'
        if self.conductivity_scenario and not evaluate:
            raise ValueError('电导率情景只用于坐标评价，不用于网格偏移')
        if self.head_id and (not evaluate or self.conductivity_scenario):
            raise ValueError('其他头模只用于坐标评价，且不与电导率情景同时使用')
        if self.robustness and (not evaluate or self.conductivity_scenario or self.head_id):
            raise ValueError('稳健性评价只用于Ernie名义头模上的坐标评价')
        if self.data_prior and (self.effective_noise_model or self.head_id):
            raise ValueError('数据先验已包含噪声结构，且只定义在Ernie头模上')
        return self

    def canonical(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            'action': self.action,
            'design': self.design.canonical(),
            'radius_mm': self.radius_mm,
            'seed': self.seed,
        }
        if self.effective_noise_model:
            out['noise_model'] = self.effective_noise_model.canonical()
        if self.conductivity_scenario:
            out['conductivity_scenario'] = self.conductivity_scenario
        if self.head_id:
            out['head_id'] = self.head_id
        if self.robustness:
            out['robustness'] = self.robustness
        if self.data_prior:
            out['data_prior'] = self.data_prior.canonical()
        return out


def normalize_design_request(raw: Any) -> dict[str, Any]:
    """Python counterpart of ``normalizeDesignRequest``; raises ``pydantic.ValidationError`` (a ValueError)."""
    return DesignEvaluationRequest.model_validate(raw).canonical()


def canonical_json(raw: Any) -> str:
    """``JSON.stringify(normalizeDesignRequest(raw))``."""
    return jsjson.stringify(normalize_design_request(raw))


def canonical_json_from_text(text: str) -> str:
    """``JSON.stringify(normalizeDesignRequest(JSON.parse(text)))``."""
    return canonical_json(jsjson.parse(text))
