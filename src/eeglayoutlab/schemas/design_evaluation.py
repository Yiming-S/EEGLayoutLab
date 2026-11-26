"""Design-evaluation request (``normalizeDesignRequest`` in webapp/server/design-evaluation-server.mjs).

``DesignEvaluationRequest`` validates what Node accepts; ``canonical()`` builds
the object Node returns, in Node's key order, and ``canonical_json()`` its
``JSON.stringify`` text, from which Node derives the cache key.
"""
from __future__ import annotations

from itertools import combinations
from typing import Annotated, Any, Literal

from . import jsjson

try:
    from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator
    from .options import ConductivityScenario, DataPrior, HeadId, IidNoise, NoiseModel, Robustness
    from .types import JsInteger, integer, js_integer, number
    _HAS_PYDANTIC = True
except ModuleNotFoundError:  # Allows pure normalize_design_request in runtimes without [service] extras.
    _HAS_PYDANTIC = False

DEFAULT_DESIGN_NAME = '导入布局'
ELECTRODES = 64
MIN_SPACING_MM = 4 - 1e-7


def _design_name(value: Any) -> str:
    # Any non-string name means the default; strings keep their first 100 UTF-16 units.
    return jsjson.slice_utf16(value, 100) if isinstance(value, str) else DEFAULT_DESIGN_NAME


def _clean_coord(v: Any) -> float:
    num = jsjson.to_number(v)
    return 0.0 if num == 0 else num


def _normalize_pure(raw: Any) -> dict[str, Any]:
    """Pure-Python counterpart of ``normalizeDesignRequest`` (webapp/server/design-evaluation-server.mjs)."""
    from ..jobs.design_result import _refuse

    _refuse(raw)
    d = raw['design']
    out: dict[str, Any] = {
        'action': raw['action'],
        'design': {
            'schema': d['schema'],
            'coordinate_system': d['coordinate_system'],
            'unit': d['unit'],
            'name': _design_name(d.get('name')),
            'xyz_mm': [[_clean_coord(v) for v in p] for p in d['xyz_mm']],
            'region_indices': [int(jsjson.to_number(v)) for v in d['region_indices']],
        },
        'radius_mm': int(jsjson.to_number(raw['radius_mm'])),
        'seed': int(jsjson.to_number(raw['seed'])),
    }
    nm = raw.get('noise_model')
    if isinstance(nm, dict) and nm.get('kind') != 'iid':
        if nm['kind'] == 'spatial':
            out['noise_model'] = {
                'kind': 'spatial',
                'rho': 0.5,
                'length_mm': int(jsjson.to_number(nm['length_mm'])),
            }
        elif nm['kind'] == 'brain_background':
            out['noise_model'] = {'kind': 'brain_background', 'fraction': 0.5}
    sc = raw.get('conductivity_scenario')
    if sc:
        out['conductivity_scenario'] = sc
    head = raw.get('head_id')
    if head:
        out['head_id'] = head
    rob = raw.get('robustness')
    if rob:
        out['robustness'] = rob
    dp = raw.get('data_prior')
    if isinstance(dp, dict):
        out['data_prior'] = {
            'region_gain': [_clean_coord(g) for g in dp['region_gain']],
            'rho': _clean_coord(dp['rho']),
            'length_mm': None if dp['length_mm'] is None else int(jsjson.to_number(dp['length_mm'])),
        }
    return out


if _HAS_PYDANTIC:
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
else:
    ElectrodeDesign = DesignEvaluationRequest = None  # type: ignore[assignment,misc]

    def normalize_design_request(raw: Any) -> dict[str, Any]:
        return _normalize_pure(raw)


def canonical_json(raw: Any) -> str:
    """``JSON.stringify(normalizeDesignRequest(raw))``."""
    return jsjson.stringify(normalize_design_request(raw))


def canonical_json_from_text(text: str) -> str:
    """``JSON.stringify(normalizeDesignRequest(JSON.parse(text)))``."""
    return canonical_json(jsjson.parse(text))
