"""Phase 0c spike: the design-evaluation schema behind FastAPI. Not wired into the interface.

Run: ``uvicorn eeglayoutlab.server.spike:app``. Write the OpenAPI document:
``python -m eeglayoutlab.server.spike openapi.json``.
"""
from __future__ import annotations

import json
import sys
from typing import Annotated, Any, Callable

from fastapi import Body, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException
from pydantic import BaseModel

from ..schemas import jsjson
from ..schemas.design_evaluation import DesignEvaluationRequest
from ..schemas.submission import DesignEvaluationBody, DesignSubmission, ElectrodeNames, canonical_submission


class JavaScriptJsonRequest(Request):
    """Parses the body as Node does: UTF-8 with replacement, then JSON.parse (no NaN, every number a double)."""

    async def json(self) -> Any:
        if not hasattr(self, '_json'):
            self._json = jsjson.parse(jsjson.decode_body(await self.body()))
        return self._json


class JavaScriptJsonRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()

        async def route(request: Request) -> Response:
            return await handler(JavaScriptJsonRequest(request.scope, request.receive))

        return route


class NormalizedDesignRequest(BaseModel):
    """Documentation of the response; the body itself is written with JSON.stringify semantics."""
    request: DesignEvaluationRequest
    request_sha256: str
    electrode_names: ElectrodeNames | None = None


app = FastAPI(title='EEGLayoutLab schema spike', version='0.0.0')
app.router.route_class = JavaScriptJsonRoute


@app.exception_handler(RequestValidationError)
async def invalid_request(_: Request, error: RequestValidationError) -> JSONResponse:
    # Node answers 400 with an `error` string; the stable code comes from contracts/api-formats.md.
    message = '; '.join(str(item.get('msg', '')) for item in error.errors())[:500]
    return JSONResponse({'error': message, 'code': 'invalid_request'}, status_code=400)


@app.exception_handler(HTTPException)
async def http_error(_: Request, error: HTTPException) -> JSONResponse:
    # FastAPI reports a body that JSON.parse would refuse (e.g. NaN) as a 400 HTTPException.
    code = 'invalid_request' if error.status_code == 400 else 'not_found' if error.status_code == 404 else 'internal_error'
    return JSONResponse({'error': str(error.detail), 'code': code}, status_code=error.status_code)


@app.post('/api/spike/design-evaluation/normalize', responses={200: {'model': NormalizedDesignRequest}}, response_class=Response)
async def normalize_design_evaluation(body: Annotated[DesignEvaluationBody, Body()]) -> Response:
    canonical = canonical_submission(body)
    out = {'request': canonical['request'], 'request_sha256': jsjson.sha256_hex(canonical['request'])}
    if isinstance(body, DesignSubmission):
        out['electrode_names'] = canonical['electrode_names']
    return Response(jsjson.stringify(out).encode('utf-8'), media_type='application/json')


def openapi_document() -> dict[str, Any]:
    return app.openapi()


if __name__ == '__main__':
    text = json.dumps(openapi_document(), ensure_ascii=False, indent=2) + '\n'
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'w', encoding='utf-8') as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
