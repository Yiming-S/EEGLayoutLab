"""The read-only library and catalogs (phase 2 slice 3): the library routes of Node's ``computeMiddleware``
(local-compute-server.mjs, lines 306-357) and the catalog reads of the editor and design services.

- ``GET /api/local-compute/library``: ``Library.list()`` (``{schema, local_only, records, warnings, datasets,
  retention}``) followed by ``electrode_annotations``;
- ``GET /api/local-compute/library/<64 hex>[?annotation_id=<64 hex>]``: ``{record}``, the record carrying the
  annotation as ``electrode_annotation`` when one is asked for; 404 ``记录不存在或完整性校验未通过``;
- ``GET /api/local-compute/library/<64 hex>/bundle[?annotation_id=...]``: the reproducibility bundle
  (``jobs.bundle.experiment_bundle`` with the compute interpreter, as Node passes ``queue.python``), the annotation
  added to the bundle and to its record; 404 ``记录不存在``;
- ``GET /api/electrode-editor/records`` and ``/parents``, ``GET /api/source-reception/layouts`` and
  ``GET /api/design-evaluation/heads``.

Each body is Node's text on the same root, without the public service's visibility machinery: no ``visibility``
member on records, no ``library_scope``, and every record is listed and readable. Electrode-name annotations are
read without regard to their owner, from ``W/annotations/electrode-names/`` first, then Node's
``R/results/v2/design_evaluation_jobs/electrode_annotations/`` (``jobs.annotations``). Warnings keep the server
paths that Node's ``redactPaths`` replaces (path redaction is not carried over, phase 2 plan).

Errors follow Node's catch block for these routes, not the generic 500 of the others: an annotation error keeps its
status and message (Node's ``annotationSafe``: the query, a missing or foreign annotation, storage that needs
inspection), and any other failure, a library that cannot be read among them, is a 500 with ``计算记录无法读取``.
The annotation query is checked only for a record that exists and, for a bundle, after the bundle is built, as in
Node. An identifier other than 64 lowercase hex digits is an unknown path (Node's 404 for the prefix).

The library, its radius identity and the head digests are built on first use and kept for the process (Node builds
them with the service), so a root that cannot be read answers 500 instead of stopping the service. The modules of
``eeglayoutlab.jobs`` are imported then too: ``eeglayoutlab serve`` writes its runtime file before it builds the
application, so building it stays short. The routes run in the worker threads; ``Library`` serializes its own calls.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import TYPE_CHECKING, Any, Callable, Optional
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request, Response

from ..app import error_response, json_response, node_fallback, raw_path

if TYPE_CHECKING:
    from ...jobs.integrity import InputIntegrity
    from ...jobs.library import Library
    from ...jobs.runtime import RuntimeConfig
    from ..app import ServiceConfig

LOG = logging.getLogger('eeglayoutlab.server')

ANNOTATION_QUERY = 'annotation_id'
# Node's messages (local-compute-server.mjs), which the interface may show.
INVALID_QUERY = 'Invalid electrode name annotation query.'
NO_RECORD = '记录不存在或完整性校验未通过'
NO_BUNDLE_RECORD = '记录不存在'
UNREADABLE = '计算记录无法读取'
# The record identifier of Node's route patterns.
KEY = re.compile('[a-f0-9]{64}')


def annotation_query(query: bytes) -> Optional[str]:
    """``readAnnotation``'s query rules on the raw query string: ``None`` without an ``annotation_id`` (other names
    are then ignored); its value when it is the only name and given once; otherwise ``AnnotationError`` 400.

    The query is parsed as ``URLSearchParams`` parses it (``application/x-www-form-urlencoded``: ``&``-separated,
    empty pieces skipped, ``+`` a space, percent escapes decoded as UTF-8 with replacement)."""
    from ...jobs.annotations import AnnotationError

    pairs = parse_qsl(query.decode('latin-1'), keep_blank_values=True)
    names = [name for name, _ in pairs]
    if ANNOTATION_QUERY not in names:
        return None
    if len(names) != 1:
        raise AnnotationError(INVALID_QUERY, 400)
    return pairs[0][1]


class LibraryRoutes:
    """The library of one service process and the answers of its routes."""

    def __init__(self, config: 'ServiceConfig'):
        self.config = config
        self._lock = threading.Lock()
        self._runtime: Optional[RuntimeConfig] = config.runtime
        self._library: Optional[Library] = None
        self._inputs: Optional[InputIntegrity] = None

    # --- What Node builds with the service ------------------------------------------------------------------

    def runtime(self) -> 'RuntimeConfig':
        """``runtimeConfig`` of the root: ``python`` is ``computePython``, the radius and bundle interpreter."""
        from ...jobs.runtime import runtime_config

        with self._lock:
            if self._runtime is None:
                self._runtime = runtime_config(self.config.root)
            return self._runtime

    def library(self) -> 'Library':
        from ...jobs import nodepath
        from ...jobs.annotations import WORKSPACE_ANNOTATIONS
        from ...jobs.library import Library

        runtime = self.runtime()
        with self._lock:
            if self._library is None:
                annotations = nodepath.join(self.config.user.workspace, *WORKSPACE_ANNOTATIONS)
                self._library = Library(runtime.repository_root, runtime, annotations)
            return self._library

    def inputs(self) -> 'InputIntegrity':
        """The service's ``InputIntegrity`` (the design service's in Node), whose digests the head listing checks."""
        from ...jobs.integrity import InputIntegrity

        runtime = self.runtime()
        with self._lock:
            if self._inputs is None:
                self._inputs = InputIntegrity(runtime.repository_root)
            return self._inputs

    # --- Answers --------------------------------------------------------------------------------------------

    def answer(self, request: Request, build: Callable[[], Response]) -> Response:
        """Node's catch block: annotation errors (``annotation_safe``, Node's ``annotationSafe``) keep their status
        and message, anything else is a 500."""
        try:
            return build()
        except Exception as error:  # noqa: BLE001 - Node answers every other failure this way
            if getattr(error, 'annotation_safe', False):
                return error_response(error.status, error.message)  # type: ignore[attr-defined]
            LOG.exception('library request failed: %s %s', request.method, raw_path(request.scope))
            return error_response(500, UNREADABLE)

    def annotation(self, request: Request, record_id: Any) -> Optional[dict]:
        """``readAnnotation(req, ..., recordId)``: the annotation the query names, or ``None`` without one."""
        annotation_id = annotation_query(request.scope.get('query_string', b''))
        if annotation_id is None:
            return None
        return self.library().annotations.read(annotation_id, record_id)

    def listing(self) -> Response:
        library = self.library()
        listed = library.list()
        listed['electrode_annotations'] = library.annotations.list()
        return json_response(200, listed)

    def record(self, request: Request, id: str) -> Response:
        record = self.library().get(id)
        if record is None:
            return error_response(404, NO_RECORD)
        annotation = self.annotation(request, record.get('id'))
        if annotation is not None:
            record = {**record, 'electrode_annotation': annotation}
        return json_response(200, {'record': record})

    def bundle(self, request: Request, id: str) -> Response:
        from ...jobs.bundle import experiment_bundle

        library = self.library()
        record = library.get(id)
        if record is None:
            return error_response(404, NO_BUNDLE_RECORD)
        bundle = experiment_bundle(library.root, record, self.runtime().python)
        annotation = self.annotation(request, record.get('id'))
        if annotation is not None:
            # {...bundle, electrode_annotation, record: {...bundle.record, electrode_annotation}}: the record keeps
            # its place, the annotation comes last in both.
            bundle = {**bundle, 'electrode_annotation': annotation,
                      'record': {**bundle['record'], 'electrode_annotation': annotation}}
        return json_response(200, bundle)

    def editor_records(self) -> Response:
        from ...jobs.editor_records import records

        return json_response(200, {'records': records(self.library().store)})

    def editor_parents(self) -> Response:
        from ...jobs.editor_records import parents

        return json_response(200, {'records': parents(self.library())})

    def layouts(self) -> Response:
        from ...jobs.reception_records import reception_layouts

        return json_response(200, reception_layouts(self.library()))

    def heads(self) -> Response:
        from ...jobs.design_heads import heads

        return json_response(200, {'heads': heads(self.runtime().repository_root, self.inputs())})


def add_routes(app: FastAPI, config: 'ServiceConfig') -> LibraryRoutes:
    routes = LibraryRoutes(config)

    # The identifier is read from the path parameters rather than declared as a parameter: FastAPI's validation of
    # a declared one costs some 40 ms when the application is built, before serve installs its signal handlers.
    def keyed(answer: Callable[[Request, str], Response]) -> Callable[[Request], Response]:
        def endpoint(request: Request) -> Response:
            id = request.path_params['id']
            if not KEY.fullmatch(id):
                # Node's pattern is [a-f0-9]{64}; anything else under the prefix is an unknown path.
                return error_response(404, node_fallback(raw_path(request.scope)) or 'Not Found')
            return routes.answer(request, lambda: answer(request, id))
        return endpoint

    def plain(answer: Callable[[], Response]) -> Callable[[Request], Response]:
        def endpoint(request: Request) -> Response:
            return routes.answer(request, answer)
        return endpoint

    for path, name, endpoint in (
        ('/api/local-compute/library', 'library', plain(routes.listing)),
        ('/api/local-compute/library/{id}', 'library_record', keyed(routes.record)),
        ('/api/local-compute/library/{id}/bundle', 'library_bundle', keyed(routes.bundle)),
        ('/api/electrode-editor/records', 'editor_records', plain(routes.editor_records)),
        ('/api/electrode-editor/parents', 'editor_parents', plain(routes.editor_parents)),
        ('/api/source-reception/layouts', 'reception_layouts', plain(routes.layouts)),
        ('/api/design-evaluation/heads', 'design_heads', plain(routes.heads)),
    ):
        # Plain functions: FastAPI runs them in its worker threads, since every answer reads files.
        app.add_api_route(path, endpoint, methods=['GET'], include_in_schema=False, name=name)
    return routes
