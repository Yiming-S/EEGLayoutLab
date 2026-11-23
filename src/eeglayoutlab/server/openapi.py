"""The OpenAPI document, built from the request format registry.

The interface's TypeScript types are generated from this document (``contracts/generated/``), so it is
built explicitly: each request body is a named component, and the errors are the service's
``{error, code}`` answers, not FastAPI's 422 validation responses.

Write it with ``python -m eeglayoutlab.server.openapi contracts/generated/openapi.json``.
"""
from __future__ import annotations

from functools import lru_cache
import json
import sys
from typing import Any

from pydantic import TypeAdapter

from .. import API_VERSION
from ..schemas.registry import REQUEST_FORMATS

REF = '#/components/schemas/{model}'
ERROR_SCHEMA = {
    'type': 'object',
    'title': 'ErrorResponse',
    'properties': {
        'error': {'type': 'string', 'description': 'Message for people; not stable.'},
        'code': {'type': 'string', 'description': 'Stable code, listed in contracts/api-formats.md.'},
    },
    'required': ['error', 'code'],
}
NORMALIZED_SCHEMA = {
    'type': 'object',
    'title': 'NormalizedRequest',
    'properties': {
        'canonical': {'description': "The request as Node's normalizer returns it."},
        'canonical_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$',
                             'description': 'SHA-256 of JSON.stringify(canonical).'},
    },
    'required': ['canonical', 'canonical_sha256'],
}
ERRORS = {
    '400': 'The body is not valid JSON or not a valid request.',
    '413': 'The body is larger than 65,536 bytes.',
    '415': 'The content type is not application/json.',
}


def _ref(name: str) -> dict[str, str]:
    return {'$ref': REF.format(model=name)}


@lru_cache(maxsize=1)
def _document() -> str:
    formats = list(REQUEST_FORMATS.values())
    keyed, definitions = TypeAdapter.json_schemas(
        [(format.name, 'validation', format.adapter) for format in formats], ref_template=REF)
    components: dict[str, Any] = dict(definitions.get('$defs', {}))
    for format in formats:
        schema = keyed[(format.name, 'validation')]
        if schema != _ref(format.schema_name):
            if format.schema_name in components:
                raise ValueError(f'schema name {format.schema_name} is used twice')
            components[format.schema_name] = schema
    components['ErrorResponse'] = ERROR_SCHEMA
    components['NormalizedRequest'] = NORMALIZED_SCHEMA
    paths = {
        f'/api/normalize/{format.name}': {
            'post': {
                'operationId': 'normalize_' + format.name.replace('-', '_'),
                'summary': f'Validate a {format.name} request and return its canonical form',
                'description': f'Diagnostic endpoint. Reproduces {format.node}.',
                'requestBody': {'required': True, 'content': {'application/json': {'schema': _ref(format.schema_name)}}},
                'responses': {
                    '200': {'description': 'The canonical request.',
                            'content': {'application/json': {'schema': _ref('NormalizedRequest')}}},
                    **{status: {'description': text, 'content': {'application/json': {'schema': _ref('ErrorResponse')}}}
                       for status, text in ERRORS.items()},
                },
            },
        }
        for format in formats
    }
    document = {
        'openapi': '3.1.0',
        'info': {'title': 'EEGLayoutLab', 'version': API_VERSION,
                 'description': 'Local service API. Request formats are defined in eeglayoutlab.schemas. The schemas '
                                'describe the canonical form of each request; the service also accepts the spellings '
                                'the Node host accepts for default values (contracts/README.md).'},
        'paths': paths,
        'components': {'schemas': dict(sorted(components.items()))},
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + '\n'


def openapi_document() -> dict[str, Any]:
    """A fresh copy of the document."""
    return json.loads(_document())


def openapi_text() -> str:
    """The document as committed in ``contracts/generated/openapi.json``."""
    return _document()


if __name__ == '__main__':
    if len(sys.argv) > 2:
        raise SystemExit('usage: python -m eeglayoutlab.server.openapi [output.json]')
    if len(sys.argv) == 2:
        with open(sys.argv[1], 'w', encoding='utf-8') as handle:
            handle.write(openapi_text())
    else:
        sys.stdout.write(openapi_text())
