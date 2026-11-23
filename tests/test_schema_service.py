"""The service's transport and diagnostic endpoints answer as the Node host does (design 0001, decision 6)."""
import copy
import hashlib
import json
import sys

import pytest

from schema_parity_support import CASES, FORMATS, ROOT, body_bytes, case_id, needs_node, require

require('fastapi')
require('httpx')

from fastapi.testclient import TestClient  # noqa: E402

from eeglayoutlab.schemas.registry import REQUEST_FORMATS  # noqa: E402
from eeglayoutlab.server.app import MAX_BODY_BYTES, create_app  # noqa: E402
from eeglayoutlab.server.openapi import openapi_document, openapi_text  # noqa: E402

client = TestClient(create_app(), raise_server_exceptions=False)
JSON = {'content-type': 'application/json'}


def post(format_name, body, headers=JSON):
    return client.post(f'/api/normalize/{format_name}', content=body, headers=headers)


def assert_transport_headers(response):
    assert response.headers['content-type'] == 'application/json; charset=utf-8'
    assert response.headers['x-eeg-api-version'] == '1'
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['cross-origin-resource-policy'] == 'same-origin'


def assert_error(response, status, code, message=None):
    assert response.status_code == status
    assert list(response.json()) == ['error', 'code'] and response.json()['code'] == code
    if message is not None:
        assert response.json()['error'] == message
    assert_transport_headers(response)


@needs_node
@pytest.mark.parametrize('case', CASES, ids=case_id)
def test_http_parity(case):
    format_name, variant = case
    response = post(format_name, body_bytes(variant))
    if not variant['accepted']:
        assert_error(response, 400, 'invalid_request')
        return
    assert response.status_code == 200
    assert_transport_headers(response)
    canonical = variant['canonical']
    # The body is written with JSON.stringify semantics, so its bytes contain Node's canonical bytes.
    digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    assert response.content.decode('utf-8') == '{"canonical":' + canonical + ',"canonical_sha256":"' + digest + '"}'


@pytest.mark.parametrize('content_type', [None, 'text/plain', 'Application/JSON', 'json'])
def test_a_body_that_is_not_declared_json_is_rejected_first(content_type):
    headers = {} if content_type is None else {'content-type': content_type}
    # 415 comes before the size check, as in Node.
    assert_error(post('design-evaluation', b'x' * (MAX_BODY_BYTES + 1), headers), 415, 'unsupported_media_type', 'JSON required')


@pytest.mark.parametrize('content_type', ['application/json', 'application/json; charset=utf-8', 'application/jsonx'])
def test_content_type_only_needs_the_json_prefix(content_type):
    assert_error(post('design-evaluation', b'{}', {'content-type': content_type}), 400, 'invalid_request')


def test_body_size_limit_counts_the_bytes_received():
    padding = lambda n: b'{"a":"' + b'x' * (n - 8) + b'"}'  # noqa: E731
    assert len(padding(MAX_BODY_BYTES)) == MAX_BODY_BYTES
    assert_error(post('design-evaluation', padding(MAX_BODY_BYTES)), 400, 'invalid_request')
    assert_error(post('design-evaluation', padding(MAX_BODY_BYTES + 1)), 413, 'request_too_large', '配置过大')
    # An invalid byte becomes a three-byte U+FFFD when decoded; the limit applies before that, as in Node.
    assert_error(post('design-evaluation', padding(MAX_BODY_BYTES - 1)[:-3] + b'\xff"}'), 400, 'invalid_request')


@needs_node
def test_a_body_at_the_limit_with_an_invalid_byte_in_a_dropped_field_is_accepted():
    variant = next(variant for variant in FORMATS['design-evaluation'] if variant['name'] == 'base')
    request = json.loads(variant['text'])
    request['design']['extra'] = ''
    text = json.dumps(request, separators=(',', ':')).encode()
    body = text.replace(b'"extra":""', b'"extra":"' + b'x' * (MAX_BODY_BYTES - len(text) - 1) + b'\xff"')
    assert len(body) == MAX_BODY_BYTES
    response = post('design-evaluation', body)
    assert response.status_code == 200 and response.json()['canonical'] == json.loads(variant['canonical'])


@pytest.mark.parametrize('body', [b'', b'NaN', b'{"a":1}x', b'\xef\xbb\xbf{}', b'[' * 30000])
def test_bodies_json_parse_rejects_are_invalid(body):
    assert_error(post('coordinate-source', body), 400, 'invalid_request')


def test_deeply_nested_json_is_parsed_not_a_server_error():
    assert_error(post('coordinate-source', b'[' * 30000 + b']' * 30000), 400, 'invalid_request')


@needs_node
def test_a_deeply_nested_type_tag_is_rejected_without_a_traceback(monkeypatch):
    # Pydantic repeats a wrong tag in its message; for a value deeper than the recursion limit that fails and
    # prints a traceback for every request. The tags are checked first (schemas.types.known_tag).
    caught = []
    monkeypatch.setattr(sys, 'unraisablehook', caught.append)
    deep = '{"a":' * 3000 + '1' + '}' * 3000

    def with_deep_tag(value, *path):
        value = copy.deepcopy(value)
        target = value
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = '__DEEP__'
        text = json.dumps(value)
        assert text.count('"__DEEP__"') == 1
        return text.replace('"__DEEP__"', deep)

    accepted = lambda name: [json.loads(v['canonical']) for v in FORMATS[name] if v['accepted']]  # noqa: E731
    v2 = next(source for source in accepted('coordinate-source') if source['schema'].endswith('/2'))
    v3 = next(source for source in accepted('coordinate-source') if source['schema'].endswith('/3') and source['conversion'])
    envelope = next(body for body in accepted('design-evaluation') if 'source_metadata' in body)
    request = envelope['request']
    bodies = [
        ('coordinate-source', with_deep_tag(v3, 'schema'), 'schema'),
        ('coordinate-source', with_deep_tag(v2, 'conversion', 'method'), 'method'),
        ('coordinate-source', with_deep_tag(v3, 'conversion', 'method'), 'method'),
        ('coordinate-source', with_deep_tag(v3, 'region_assignment', 'method'), 'method'),
        ('design-evaluation', with_deep_tag({**request, 'noise_model': {'kind': 'iid'}}, 'noise_model', 'kind'), 'kind'),
        ('design-evaluation', with_deep_tag({'schema': 'design-submission/1', **envelope}, 'source_metadata', 'schema'), 'schema'),
    ]
    for format_name, body, tag in bodies:
        response = post(format_name, body.encode())
        assert_error(response, 400, 'invalid_request')
        assert f'{tag} must be one of' in response.json()['error']
    assert caught == []


def test_unknown_paths_and_methods_answer_in_the_error_format():
    assert_error(client.get('/api/normalize/unknown'), 404, 'not_found')
    assert_error(client.post('/api/normalize/unknown', content=b'{}', headers=JSON), 404, 'not_found')
    assert_error(client.get('/api/normalize/design-evaluation'), 405, 'method_not_allowed')
    # Node matches the path as received: no trailing-slash redirect and no percent-decoded alias.
    for path in ('/api/normalize/design-evaluation/', '/api/normalize/coordinate%2Dsource', '/api/openapi.json/'):
        response = client.request('POST' if 'normalize' in path else 'GET', path, content=b'{}', headers=JSON,
                                  follow_redirects=False)
        assert_error(response, 404, 'not_found')


def test_validation_errors_name_the_field_and_stay_short():
    response = post('design-evaluation', json.dumps({'action': 'evaluate', 'design': None, 'radius_mm': 3, 'seed': 1}).encode())
    assert_error(response, 400, 'invalid_request')
    assert len(response.json()['error']) <= 500


def test_openapi_lists_every_format_without_framework_validation_errors():
    document = openapi_document()
    assert document['openapi'] == '3.1.0' and document['info']['version'] == '1'
    text = json.dumps(document)
    assert '"422"' not in text and 'HTTPValidationError' not in text
    for format in REQUEST_FORMATS.values():
        operation = document['paths'][f'/api/normalize/{format.name}']['post']
        assert operation['requestBody']['content']['application/json']['schema'] == {'$ref': f'#/components/schemas/{format.schema_name}'}
        assert format.schema_name in document['components']['schemas']
        assert sorted(operation['responses']) == ['200', '400', '413', '415']
    assert document['components']['schemas']['SpatialNoise']['properties']['rho']['const'] == 0.5
    response = client.get('/api/openapi.json')
    assert response.status_code == 200 and response.text == openapi_text()
    assert_transport_headers(response)


def test_committed_openapi_document_is_current():
    # Regenerate with: python -m eeglayoutlab.server.openapi contracts/generated/openapi.json
    # then, in webapp/: npm run generate:api-types
    assert (ROOT / 'contracts/generated/openapi.json').read_text(encoding='utf-8') == openapi_text()


def test_interactive_documentation_pages_are_not_served():
    for path in ('/docs', '/redoc', '/openapi.json'):
        assert_error(client.get(path), 404, 'not_found')
