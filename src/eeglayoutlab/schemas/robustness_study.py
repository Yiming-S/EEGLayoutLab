"""Robustness-study request (``normalizeStudyInput`` in webapp/server/studies/protocol.mjs).

The body of ``POST /api/robustness-studies``: one design evaluated in 1 to 12 explicit cases of one protocol.
``noise_seeds`` repeats the evaluation with distinct seeds at one radius (a conductivity scenario may apply to
every case), ``grid_displacements`` runs perturbation trials for distinct seed/radius pairs, and ``heads``
evaluates one head package per case with one shared seed and radius. A title (not blank, at most 200 UTF-16 units;
default ``Robustness study``), notes (at most 2000 units) and one noise model for every case are optional. The
design's ``electrode_names`` and ``source_metadata`` are presentation metadata, kept outside every request.

``eeglayoutlab.jobs.studies.normalize_study_input`` is the line-by-line port: it checks in Node's order, raises
``StudyError`` (a ``ValueError``) with Node's message, which the Node host returns from the study endpoint, and
returns Node's normalized study, the canonical value of this format. ``RobustnessStudyInput`` describes the
canonical input for the OpenAPI document: the trimmed title, the notes, the design and cases as normalized, and the
noise model and scenario when they are not the defaults; electrode names that Node fills in for a source without
names are left out. It accepts exactly what ``normalize_study_input`` accepts: Node's rules decide and give the
message, then the canonical input is validated against the model of its protocol. Normalizing a canonical input
gives the same normalized study.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import (AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, PrivateAttr, StringConstraints,
                      WrapValidator)

from . import coordinate_source, jsjson
from .coordinate_source import CoordinateSource
from .design_evaluation import ElectrodeDesign
from .options import ConductivityScenario, NoiseModel
from .submission import ElectrodeNames
from .types import integer, js_integer

__all__ = [
    'RobustnessStudyInput', 'NoiseSeedStudy', 'GridDisplacementStudy', 'CrossHeadStudy', 'StudyDesign', 'StudyCase',
    'HeadStudyCase', 'canonical', 'canonical_input',
]

_EXACT = ConfigDict(extra='forbid')
MAX_CASES = 12
TITLE_UNITS = 200
NOTES_UNITS = 2000
DEFAULT_TITLE = 'Robustness study'


def _absent_default(schema: dict[str, Any]) -> None:
    # Optional but not nullable: the canonical input leaves the field out instead of writing null.
    schema.pop('default', None)


def _units(text: str) -> int:
    return len(text.encode('utf-16-le', errors='surrogatepass')) // 2


def _title(value: str) -> str:
    if not jsjson.js_trim(value) or _units(value) > TITLE_UNITS:
        raise ValueError('a study title is not blank and has at most 200 UTF-16 units')
    return value


def _notes(value: str) -> str:
    if _units(value) > NOTES_UNITS:
        raise ValueError('study notes have at most 2000 UTF-16 units')
    return value


# Lengths are UTF-16 units, checked by the validators; the bounds are kept for the schema only (see submission.py).
StudyTitle = Annotated[str, Field(strict=True, json_schema_extra={'minLength': 1, 'maxLength': TITLE_UNITS}),
                       AfterValidator(_title)]
StudyNotes = Annotated[str, Field(strict=True, json_schema_extra={'maxLength': NOTES_UNITS}), AfterValidator(_notes)]
Radius = Annotated[Literal[3, 6, 10], BeforeValidator(js_integer)]
Seed = integer(ge=0, le=9999)
HeadPackage = Annotated[str, StringConstraints(strict=True, max_length=40, pattern=r'^[a-z0-9]+(?:[_-][a-z0-9]+)*$')]


def _metadata_absent_defaults(schema: dict[str, Any]) -> None:
    # As _absent_default, at the model: ElectrodeNames carries a dict json_schema_extra, which a field's callable one
    # cannot be composed with.
    for name in ('electrode_names', 'source_metadata'):
        schema['properties'][name].pop('default', None)


class StudyDesign(ElectrodeDesign):
    """The design of every case (``eeg-electrode-design/1``), with presentation metadata that never enters a
    request: 64 electrode names and the coordinate source of an imported layout. Other design fields are dropped."""
    model_config = ConfigDict(json_schema_extra=_metadata_absent_defaults)
    electrode_names: ElectrodeNames = None
    source_metadata: CoordinateSource = None

    def input_value(self) -> dict[str, Any]:
        out = self.canonical()
        if self.electrode_names is not None:
            out['electrode_names'] = list(self.electrode_names)
        if self.source_metadata is not None:
            out['source_metadata'] = coordinate_source.canonical(self.source_metadata)
        return out


class StudyCase(BaseModel):
    """A case of a noise-seed or grid-displacement study."""
    model_config = _EXACT
    seed: Seed
    radius_mm: Radius

    def input_value(self) -> dict[str, Any]:
        return {'seed': self.seed, 'radius_mm': self.radius_mm}


class HeadStudyCase(BaseModel):
    """A case of a cross-head study: one head package of the design-evaluation catalog."""
    model_config = _EXACT
    head_id: HeadPackage
    seed: Seed
    radius_mm: Radius

    def input_value(self) -> dict[str, Any]:
        return {'head_id': self.head_id, 'seed': self.seed, 'radius_mm': self.radius_mm}


class _Study(BaseModel):
    model_config = _EXACT
    protocol: str
    title: StudyTitle = DEFAULT_TITLE
    notes: StudyNotes = ''
    design: StudyDesign
    cases: list[Any]
    noise_model: NoiseModel = Field(default=None, json_schema_extra=_absent_default)
    _normalized: Optional[dict] = PrivateAttr(default=None)

    def input_value(self) -> dict[str, Any]:
        """The input as a value ``normalize_study_input`` takes, in the canonical key order."""
        out: dict[str, Any] = {'protocol': self.protocol, 'title': self.title, 'notes': self.notes,
                               'design': self.design.input_value(),
                               'cases': [case.input_value() for case in self.cases]}
        if self.noise_model is not None:
            out['noise_model'] = self.noise_model.model_dump()
        scenario = getattr(self, 'conductivity_scenario', None)
        if scenario is not None:
            out['conductivity_scenario'] = scenario
        return out


class NoiseSeedStudy(_Study):
    """Distinct seeds at one radius: the spread of nominal metrics over noise draws on Ernie, optionally under
    one data-generating conductivity scenario."""
    protocol: Literal['noise_seeds']
    cases: Annotated[list[StudyCase], Field(min_length=1, max_length=MAX_CASES)]
    conductivity_scenario: ConductivityScenario = None


class GridDisplacementStudy(_Study):
    """Distinct seed/radius pairs of perturbation trials on Ernie."""
    protocol: Literal['grid_displacements']
    cases: Annotated[list[StudyCase], Field(min_length=1, max_length=MAX_CASES)]


class CrossHeadStudy(_Study):
    """One case per head package, each listed once, with one seed and one radius for every case."""
    protocol: Literal['heads']
    cases: Annotated[list[HeadStudyCase], Field(min_length=1, max_length=MAX_CASES)]


_MODELS = {'noise_seeds': NoiseSeedStudy, 'grid_displacements': GridDisplacementStudy, 'heads': CrossHeadStudy}


def canonical_input(normalized: dict[str, Any]) -> dict[str, Any]:
    """The canonical input of a normalized study: what the model of its protocol validates, and an input that
    ``normalize_study_input`` normalizes to ``normalized`` again."""
    annotation = normalized['annotation']
    design = dict(normalized['design'])
    # Node fills in E1..E64 after the source when only a source is sent; sending them would reorder the annotation.
    if 'electrode_names' in annotation and list(annotation)[0] == 'electrode_names':
        design['electrode_names'] = annotation['electrode_names']
    if 'source_metadata' in annotation:
        design['source_metadata'] = annotation['source_metadata']
    out: dict[str, Any] = {
        'protocol': normalized['protocol'], 'title': normalized['title'], 'notes': normalized['notes'],
        'design': design,
        'cases': [{**({'head_id': request['head_id']} if 'head_id' in request else {}),
                   'seed': request['seed'], 'radius_mm': request['radius_mm']} for request in normalized['requests']],
    }
    for key in ('noise_model', 'conductivity_scenario'):
        if key in normalized:
            out[key] = normalized[key]
    return out


def _node_rules(value: Any, handler: Any) -> Any:
    # Node's rules decide and give the message; the model of the protocol then checks the canonical input.
    if isinstance(value, _Study):
        return value
    from ..jobs.studies import normalize_study_input
    normalized = normalize_study_input(value)
    model = handler(canonical_input(normalized))
    model._normalized = normalized
    return model


RobustnessStudyInput = Annotated[
    Union[NoiseSeedStudy, GridDisplacementStudy, CrossHeadStudy], Field(discriminator='protocol'),
    WrapValidator(_node_rules),
]


def canonical(value: NoiseSeedStudy | GridDisplacementStudy | CrossHeadStudy) -> dict[str, Any]:
    """The registry's canonical value of a validated study: Node's normalized study."""
    if value._normalized is None:
        from ..jobs.studies import normalize_study_input
        value._normalized = normalize_study_input(value.input_value())
    return value._normalized
