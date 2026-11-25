"""Every request format, defined once (design 0001, decision 4).

A format validates the value ``JSON.parse`` gives (``jsjson.parse``) and returns the value that Node's
normalizer returns, to be written with ``jsjson.stringify``. The service, the OpenAPI document and the
parity tests (``tests/schema_parity``) all read this table, so a format is added here and nowhere else.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Callable, Mapping

from pydantic import TypeAdapter

from . import coordinate_source, options, radius_search, submission


@dataclass(frozen=True)
class RequestFormat:
    name: str
    """URL segment and parity corpus key, for example ``design-evaluation``."""
    schema_name: str
    """Name of the body schema in the OpenAPI document and the generated TypeScript types."""
    body: Any
    """The validated type: a model or an annotated union."""
    canonical: Callable[[Any], dict[str, Any]]
    """Canonical value of a validated body, in Node's key order."""
    node: str
    """The Node code this format reproduces until the Node host is retired."""
    options: Mapping[str, tuple[Any, ...]] = field(default_factory=dict)
    """Lists of allowed values that have a Node counterpart; the parity tests compare the two."""

    @cached_property
    def adapter(self) -> TypeAdapter:
        return TypeAdapter(self.body)

    def normalize(self, value: Any) -> dict[str, Any]:
        """Validate a parsed body and return its canonical value; raises ``ValueError`` when Node would reject it."""
        return self.canonical(self.adapter.validate_python(value))


REQUEST_FORMATS: dict[str, RequestFormat] = {
    format.name: format
    for format in (
        RequestFormat(
            name='coordinate-source',
            schema_name='CoordinateSource',
            body=coordinate_source.CoordinateSource,
            canonical=coordinate_source.canonical,
            node='validateCoordinateSource (webapp/contracts/coordinate-source.mjs)',
            options={
                'mni_coordinate_systems': coordinate_source.MNI_COORDINATE_SYSTEMS,
                'montage_formats': coordinate_source.MONTAGE_FORMATS,
            },
        ),
        RequestFormat(
            name='design-evaluation',
            schema_name='DesignEvaluationBody',
            body=submission.DesignEvaluationBody,
            canonical=submission.canonical_submission,
            node='designSubmission + normalizeDesignRequest (webapp/server/annotations/electrode-names.mjs, '
                 'webapp/server/design-evaluation-server.mjs)',
            options={
                'conductivity_scenarios': options.CONDUCTIVITY_SCENARIOS,
                'spatial_noise_lengths_mm': options.SPATIAL_NOISE_LENGTHS_MM,
                'data_prior_lengths_mm': options.DATA_PRIOR_LENGTHS_MM,
            },
        ),
        RequestFormat(
            name='radius-search',
            schema_name='RadiusSearchRequest',
            body=radius_search.RadiusSearchRequest,
            canonical=radius_search.canonical,
            node='normalizeRequest (webapp/server/local-compute-server.mjs)',
            options={
                'mask_codes': radius_search.MASK_CODES,
                'spatial_noise_lengths_mm': options.SPATIAL_NOISE_LENGTHS_MM,
                'data_prior_lengths_mm': options.DATA_PRIOR_LENGTHS_MM,
                'electrode_counts': radius_search.ELECTRODE_COUNTS,
            },
        ),
    )
}
