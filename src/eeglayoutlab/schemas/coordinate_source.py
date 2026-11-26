"""``electrode-coordinate-source/1``, ``/2`` and ``/3`` (webapp/contracts/coordinate-source.mjs).

Where imported coordinates came from: the input files, their frame and, for converted inputs,
the mapping that produced the Ernie coordinates. It never enters a scientific request or cache
key, but it enters the identity of an electrode-name annotation, so its canonical value must
equal Node's byte for byte. Node returns shallow copies of the input, so the canonical value
keeps the input's key order, not the field order of these models.
"""
from __future__ import annotations

import copy
import re
from typing import Annotated, Any, ClassVar, Literal, Optional, Union

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, PrivateAttr, TypeAdapter, model_validator

from . import jsjson
from .types import integer, js_integer, known_tag, number

__all__ = [
    'CoordinateSource', 'CoordinateSourceV1', 'CoordinateSourceV2', 'CoordinateSourceV3',
    'MniConversion', 'LabelConversion', 'HeadRegistration', 'FileRegionAssignment', 'BalancedRegionAssignment',
    'canonical', 'normalize_coordinate_source', 'JS_TRIM', 'utf16_length',
    'MNI_COORDINATE_SYSTEMS', 'LABEL_CAP', 'MNI_IMPORT_LIMIT_MM', 'HEAD_REGISTRATION_METHOD',
    'HEAD_REGISTRATION_LIMIT_MM', 'MONTAGE_FORMATS',
]

# BIDS template coordinate systems accepted as MNI input. All are mapped with the SimNIBS MNI152NLin6Asym warp.
MNI_COORDINATE_SYSTEMS = (
    'MNI152NLin6Asym', 'MNI152NLin6Sym', 'MNI152Lin', 'MNI152NLin2009aAsym', 'MNI152NLin2009aSym',
    'MNI152NLin2009bAsym', 'MNI152NLin2009bSym', 'MNI152NLin2009cAsym', 'MNI152NLin2009cSym', 'MNI305',
    'MNIColin27', 'IXI549Space', 'ICBM452AirSpace', 'ICBM452Warp5Space',
)
LABEL_CAP = 'EEG10-20_extended_SPM12'
MNI_IMPORT_LIMIT_MM = 10
# Head-frame coordinates registered onto Ernie's scalp by their landmarks (webapp/lib/head-registration.ts).
HEAD_REGISTRATION_METHOD = 'head-landmarks-surface/1'
HEAD_REGISTRATION_LIMIT_MM = 10
MONTAGE_FORMATS = ('mne-elc/1', 'eeglab-sfp/1')

_COMMON = ('schema', 'format', 'electrodes_file', 'coordsystem_file', 'coordinate_system', 'unit',
           'coordinate_system_description', 'region_index_base', 'region_description')
_CONVERSION = ('method', 'mapping_id', 'input_coordinate_system', 'input_unit', 'max_surface_distance_mm')
_HEAD_CONVERSION = ('method', 'mapping_id', 'input_coordinate_system', 'input_unit', 'landmark_source', 'scale',
                    'rotation_deg', 'max_landmark_residual_mm', 'max_surface_distance_mm', 'iterations')

# --- JavaScript text rules ----------------------------------------------------

# String.prototype.trim's characters, defined in jsjson so that code without Pydantic can use them.
JS_TRIM = jsjson.JS_TRIM


def utf16_length(text: str) -> int:
    """``text.length``: UTF-16 code units, so an emoji counts twice and a lone surrogate once."""
    return len(text.encode('utf-16-le', errors='surrogatepass')) // 2


def _text(max_units: int, multiline: bool) -> Any:
    """``text(value, max, multiline)``: a string of at most ``max_units`` UTF-16 units that is not blank after JS
    ``trim`` and has no control character (tab, LF and CR are allowed in multiline text) or DEL."""
    allowed = {9, 10, 13} if multiline else set()

    def check(value: str) -> str:
        if (utf16_length(value) > max_units or all(c in JS_TRIM for c in value)
                or any((ord(c) < 32 and ord(c) not in allowed) or ord(c) == 127 for c in value)):
            raise ValueError(f'must be non-blank text of at most {max_units} UTF-16 units without control characters')
        return value

    # Pydantic's own max_length would reject lone surrogates, which Node accepts; the bound is for the schema only.
    return Annotated[str, Field(strict=True, json_schema_extra={'minLength': 1, 'maxLength': max_units}), AfterValidator(check)]


def _file_name(value: str) -> str:
    if '/' in value or '\\' in value or value in ('.', '..'):
        raise ValueError('must be a file name without a directory')
    return value


def _mapping_id(value: str) -> str:
    # fullmatch, because Python's `$` also matches before a trailing newline and JavaScript's does not.
    if not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('must be 64 lowercase hexadecimal digits')
    return value


def _zero(value: Any) -> Any:
    """``value === 0``: a JSON number equal to zero (``-0`` included); ``false`` is not a number."""
    if jsjson.is_number(value) and jsjson.to_number(value) == 0:
        return 0
    raise ValueError('must be 0')


Text64 = _text(64, multiline=False)
FileName = Annotated[_text(200, multiline=False), AfterValidator(_file_name),
                     Field(json_schema_extra={'pattern': r'^[^/\\]+$'})]
MappingId = Annotated[str, Field(strict=True, json_schema_extra={'pattern': '^[0-9a-f]{64}$'}), AfterValidator(_mapping_id)]
FrameDescription = _text(2048, multiline=True)
RegionDescription = _text(1024, multiline=True)
Zero = Annotated[Literal[0], BeforeValidator(_zero)]


def _node_key_list(keys: Any) -> str:
    """Node's ``keys`` check: names sorted by UTF-16 code units and joined with commas."""
    return ','.join(sorted(keys, key=lambda key: key.encode('utf-16-be', errors='surrogatepass')))


class _NodeObject(BaseModel):
    """An object with exactly ``KEYS``. The validated input is kept, because Node's value is a copy of it."""
    model_config = ConfigDict(extra='forbid')
    KEYS: ClassVar[tuple[str, ...]] = ()
    _input: dict[str, Any] = PrivateAttr(default_factory=dict)

    @model_validator(mode='wrap')
    @classmethod
    def _exact_keys(cls, data: Any, handler: Any) -> Any:
        if isinstance(data, cls):
            return data
        if isinstance(data, dict) and _node_key_list(data) != _node_key_list(cls.KEYS):
            raise ValueError(f'fields must be exactly {", ".join(cls.KEYS)}')
        model = handler(data)
        model._input = copy.deepcopy(data)
        return model


# --- conversions --------------------------------------------------------------

class MniConversion(_NodeObject):
    """MNI template coordinates mapped onto Ernie's scalp with the SimNIBS nonlinear warp."""
    KEYS: ClassVar[tuple[str, ...]] = _CONVERSION
    method: Literal['ernie-mni-scalp/1']
    mapping_id: MappingId
    input_coordinate_system: Literal[MNI_COORDINATE_SYSTEMS]  # type: ignore[valid-type]
    input_unit: Literal['mm']
    max_surface_distance_mm: number(ge=0, le=MNI_IMPORT_LIMIT_MM)


class LabelConversion(_NodeObject):
    """10-05 electrode names placed at the positions of the SimNIBS cap."""
    KEYS: ClassVar[tuple[str, ...]] = _CONVERSION
    method: Literal['cap-labels/1']
    mapping_id: MappingId
    input_coordinate_system: Literal['EEG10-20_extended_SPM12']
    input_unit: None
    max_surface_distance_mm: None


class HeadRegistration(_NodeObject):
    """Digitized head-frame coordinates registered onto Ernie's scalp by their landmarks."""
    KEYS: ClassVar[tuple[str, ...]] = _HEAD_CONVERSION
    method: Literal['head-landmarks-surface/1']
    mapping_id: MappingId
    input_coordinate_system: Text64
    input_unit: Literal['mm', 'cm', 'm']
    landmark_source: Literal['coordsystem', 'file']
    scale: number(ge=0.5, le=2)
    rotation_deg: number(ge=0, le=180)
    max_landmark_residual_mm: number(ge=0, le=1000)
    max_surface_distance_mm: number(ge=0, le=HEAD_REGISTRATION_LIMIT_MM)
    iterations: integer(ge=0, le=1000)


class FileRegionAssignment(_NodeObject):
    """The regions were read from the file."""
    KEYS: ClassVar[tuple[str, ...]] = ('method',)
    method: Literal['file']


class BalancedRegionAssignment(_NodeObject):
    """The regions were assigned on import, balanced in space."""
    KEYS: ClassVar[tuple[str, ...]] = ('method', 'region_count')
    method: Literal['balanced-spatial/1']
    region_count: Annotated[Literal[1, 2, 3, 4, 6], BeforeValidator(js_integer)]


ConversionV2 = Annotated[Union[MniConversion, LabelConversion], Field(discriminator='method'),
                         known_tag('method', ('ernie-mni-scalp/1', 'cap-labels/1'))]
ConversionV3 = Optional[Annotated[Union[MniConversion, LabelConversion, HeadRegistration], Field(discriminator='method'),
                                  known_tag('method', ('ernie-mni-scalp/1', 'cap-labels/1', HEAD_REGISTRATION_METHOD))]]
RegionAssignment = Annotated[Union[FileRegionAssignment, BalancedRegionAssignment], Field(discriminator='method'),
                             known_tag('method', ('file', 'balanced-spatial/1'))]


# --- sources -------------------------------------------------------------------

class _Source(_NodeObject):
    electrodes_file: FileName
    coordinate_system: Literal['ernie_native_mm']
    unit: Literal['mm']
    coordinate_system_description: FrameDescription
    region_index_base: Zero
    region_description: RegionDescription


class CoordinateSourceV1(_Source):
    """An Ernie-native coordinate file."""
    KEYS: ClassVar[tuple[str, ...]] = _COMMON
    schema_: Literal['electrode-coordinate-source/1'] = Field(alias='schema')
    format: Literal['bids-electrodes/1']
    coordsystem_file: FileName


class CoordinateSourceV2(_Source):
    """A converted input: an MNI coordinate file, or a list of 10-05 electrode names (no coordinate-system file)."""
    KEYS: ClassVar[tuple[str, ...]] = _COMMON + ('conversion',)
    schema_: Literal['electrode-coordinate-source/2'] = Field(alias='schema')
    format: Literal['bids-electrodes/1', 'electrode-labels/1']
    coordsystem_file: Optional[FileName]
    conversion: ConversionV2

    @model_validator(mode='after')
    def _format_rules(self) -> CoordinateSourceV2:
        labels = self.format == 'electrode-labels/1'
        if (self.coordsystem_file is None) != labels:
            raise ValueError('coordsystem_file is null exactly for electrode-labels/1')
        if isinstance(self.conversion, LabelConversion) != labels:
            raise ValueError('electrode-labels/1 uses cap-labels/1 and bids-electrodes/1 uses ernie-mni-scalp/1')
        return self


class CoordinateSourceV3(_Source):
    """`/2` plus montage files, head-frame registration and regions assigned on import; conversion is null for an
    Ernie-native input."""
    KEYS: ClassVar[tuple[str, ...]] = _COMMON + ('conversion', 'region_assignment')
    schema_: Literal['electrode-coordinate-source/3'] = Field(alias='schema')
    format: Literal[('bids-electrodes/1', 'electrode-labels/1') + MONTAGE_FORMATS]  # type: ignore[valid-type]
    coordsystem_file: Optional[FileName]
    conversion: ConversionV3
    region_assignment: RegionAssignment

    @model_validator(mode='after')
    def _format_rules(self) -> CoordinateSourceV3:
        montage = self.format in MONTAGE_FORMATS
        labels = self.format == 'electrode-labels/1'
        if (self.coordsystem_file is None) != (montage or labels):
            raise ValueError('coordsystem_file is null exactly for montage files and electrode-labels/1')
        if self.conversion is None or isinstance(self.conversion, HeadRegistration):
            if labels:
                raise ValueError('electrode-labels/1 needs the cap-labels/1 conversion')
        elif montage or isinstance(self.conversion, LabelConversion) != labels:
            raise ValueError('the conversion does not match the format')
        return self


CoordinateSource = Annotated[
    Union[CoordinateSourceV1, CoordinateSourceV2, CoordinateSourceV3], Field(discriminator='schema_'),
    known_tag('schema', ('electrode-coordinate-source/1', 'electrode-coordinate-source/2', 'electrode-coordinate-source/3')),
]

_ADAPTER: TypeAdapter = TypeAdapter(CoordinateSource)


def canonical(value: CoordinateSourceV1 | CoordinateSourceV2 | CoordinateSourceV3) -> dict[str, Any]:
    """``validateCoordinateSource``'s return value: a copy of the validated input, in its key order."""
    return copy.deepcopy(value._input)


def normalize_coordinate_source(raw: Any) -> dict[str, Any]:
    """``validateCoordinateSource(raw)``; raises ``ValueError`` where Node throws."""
    return canonical(_ADAPTER.validate_python(raw))
