"""Phase 0c: the FastAPI spike endpoint returns Node's canonical bytes over HTTP."""
import base64
import json
from pathlib import Path

import pytest

pytest.importorskip('fastapi')
pytest.importorskip('httpx')

from fastapi.testclient import TestClient  # noqa: E402

from eeglayoutlab.schemas import jsjson  # noqa: E402
from eeglayoutlab.server.spike import app, openapi_document  # noqa: E402
from test_schema_design_parity import CORPUS, SUBMISSIONS, VARIANTS, needs_node  # noqa: E402

PATH = '/api/spike/design-evaluation/normalize'
client = TestClient(app)


def post(body: bytes):
    return client.post(PATH, content=body, headers={'content-type': 'application/json'})


@needs_node
@pytest.mark.parametrize('variant', VARIANTS + SUBMISSIONS, ids=lambda variant: variant['name'])
def test_http_parity(variant):
    body = base64.b64decode(variant['bytes']) if 'bytes' in variant else variant['text'].encode('utf-8', 'surrogatepass')
    response = post(body)
    if not variant['accepted']:
        assert response.status_code == 400
        assert response.json()['code'] == 'invalid_request'
        return
    assert response.status_code == 200
    out = json.loads(response.content)
    request = jsjson.stringify(out['request'])
    canonical = json.loads(variant['canonical'])
    assert request == (jsjson.stringify(canonical['request']) if variant in SUBMISSIONS else variant['canonical'])
    # The response bytes are written with JSON.stringify semantics, so the hash is Node's request hash.
    assert response.content.decode('utf-8').startswith('{"request":' + request + ',"request_sha256":')
    assert out['request_sha256'] == jsjson.sha256_hex(out['request'])


def test_openapi_documents_the_request_body():
    document = openapi_document()
    body = document['paths'][PATH]['post']['requestBody']['content']['application/json']['schema']
    assert {'$ref': '#/components/schemas/DesignEvaluationRequest'} in body['oneOf']
    assert document['components']['schemas']['SpatialNoise']['properties']['rho']['const'] == 0.5


def test_committed_openapi_document_is_current():
    # tests/schema_parity/generated/openapi.d.ts comes from this file:
    # openapi-typescript 7.13 openapi.json --default-non-nullable false (request fields with defaults stay optional).
    committed = json.loads((Path(__file__).parent / 'schema_parity/generated/openapi.json').read_text(encoding='utf-8'))
    assert committed == openapi_document()
