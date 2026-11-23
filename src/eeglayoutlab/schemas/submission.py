"""``design-submission/1`` envelope (webapp/server/annotations/electrode-names.mjs).

The interface wraps a design-evaluation request with presentation metadata.
The names never enter the request or its cache key.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Discriminator, Field, Tag

from .design_evaluation import DesignEvaluationRequest

# ECMAScript WhiteSpace and LineTerminator, which String.prototype.trim removes.
# Python's str.strip differs: it removes U+0085 and U+001C-U+001F but keeps U+FEFF.
JS_TRIM = frozenset('\t\n\v\f\r              '
                    '    　﻿')


def _utf16_length(text: str) -> int:
    return len(text.encode('utf-16-le', errors='surrogatepass')) // 2


def _electrode_name(value: str) -> str:
    if all(c in JS_TRIM for c in value) or _utf16_length(value) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('electrode names are non-blank, at most 128 UTF-16 units and free of control characters')
    return value


def _distinct(names: list[str]) -> list[str]:
    if len(set(names)) != len(names):
        raise ValueError('electrode names must be distinct')
    return names


# Length is checked in UTF-16 units by _electrode_name. Pydantic's own min/max_length would also convert the
# value to a Rust string, rejecting lone surrogates that Node accepts; the bounds are kept for the schema only.
ElectrodeName = Annotated[str, Field(strict=True, json_schema_extra={'minLength': 1, 'maxLength': 128}), AfterValidator(_electrode_name)]
ElectrodeNames = Annotated[list[ElectrodeName], Field(min_length=64, max_length=64, json_schema_extra={'uniqueItems': True}),
                           AfterValidator(_distinct)]


class DesignSubmission(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_: Literal['design-submission/1'] = Field(alias='schema')
    request: DesignEvaluationRequest
    electrode_names: ElectrodeNames
    # Not ported in the spike: Node checks it with validateCoordinateSource (webapp/contracts/coordinate-source.mjs).
    source_metadata: dict[str, Any] | None = None

    def canonical(self) -> dict[str, Any]:
        return {'request': self.request.canonical(), 'electrode_names': list(self.electrode_names)}


def _kind(value: Any) -> str:
    # Node treats anything whose schema is not exactly 'design-submission/1' as a bare request.
    if isinstance(value, dict):
        return 'submission' if value.get('schema') == 'design-submission/1' else 'request'
    return 'submission' if isinstance(value, DesignSubmission) else 'request'


DesignEvaluationBody = Annotated[
    Union[Annotated[DesignEvaluationRequest, Tag('request')], Annotated[DesignSubmission, Tag('submission')]],
    Discriminator(_kind),
]


def canonical_submission(body: DesignEvaluationRequest | DesignSubmission) -> dict[str, Any]:
    """What Node's ``designSubmission`` + ``normalizeDesignRequest`` keep: the request and, if sent, the names."""
    return body.canonical() if isinstance(body, DesignSubmission) else {'request': body.canonical()}
