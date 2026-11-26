"""The electrode editor's run path: Node's ``ElectrodeEditorService`` (``electrode-editor-server.mjs:41-108``),
statement by statement, as a subclass of slice 5's ``DesignJobs``, as Node's class extends
``DesignEvaluationService``.

An editor request (``schemas.electrode_editor.normalize_editor_request``) names a parent layout of the library
(``prepare``), or also carries the parent's digest and 64 stable slots (``evaluate``). Its context starts from the
parent's full library record (``jobs.library.Library.get``, Node's record bytes: B13) and from the design context
of the same request (slice 1), and its identity is the design identity with ``schema`` overwritten in its first
position, then ``parent_digest``, ``editor_sha256`` (``scripts/electrode_editor.py``) and
``editor_implementation_sha256`` (``EDITOR_WORKFLOW``) appended (B17). The key is
``sha256(JSON.stringify({request, identity}))``. Records go to ``R/results/v2/electrode_editor_jobs/<key>/``, as the
coordinate evaluation's do: ``<uuid>/request.json``, ``<uuid>/job.json`` (the view, with ``parent_digest``, and
``stderr``) and ``cache.json`` for a completed result, published once (B16).

The worker is ``<native interpreter> -u R/scripts/electrode_editor.py`` with ``{request, parent}`` on stdin, one
thread (B10), 600 s and 4 MiB of output, as ``DesignJobs`` runs its script; every other member (lookup, submit,
close, finish, cancel, dispose and the Python additions) is ``DesignJobs``'s. ``records()`` and ``parents()`` are
slice 3's ``editor_records``; ``handle()`` is HTTP (the routes).

The context is computed in three steps off the event loop, each in a worker thread under the identity lock of
``jobs.kinds`` (one identity at a time across kinds): the parent (``Library.get``, its checks and digest), the
design context (``DesignJobs.context``), then the parent's geometry and the editor's digests. Node runs the same
statements in this order, so a request that fails several checks fails with Node's message.
"""
from __future__ import annotations

from typing import Any, Optional

from ..schemas import jsjson
from ..schemas.electrode_editor import normalize_editor_request
from . import nodefs, nodepath
from .design import DesignJob, DesignJobError, DesignJobs
from .editor_records import parents, records, validate_editor_result
from .identity import EDITOR_WORKFLOW, UNDEFINED, _member, _path, _same, js_truthy, request_key
from .reception_records import _spread

__all__ = ['EditorJobs', 'EditorContextError', 'editor_jobs', 'WORKER_SCRIPT', 'EDITOR_CACHE_SCHEMA', 'NOT_A_PARENT',
           'NOT_INDEPENDENT', 'PARENT_CHANGED', 'REPORT_MISMATCH', 'GEOMETRY_DIFFERS']

WORKER_SCRIPT = 'scripts/electrode_editor.py'
EDITOR_CACHE_SCHEMA = 'electrode-editor-cache/1'
# Node's messages, verbatim, in the order its context checks them.
NOT_A_PARENT = 'Choose a completed layout with saved region boundaries'
NOT_INDEPENDENT = ('The electrode editor scores with independent noise; choose a layout searched under independent '
                   'noise')
PARENT_CHANGED = 'Parent changed; reload the layout before editing'
REPORT_MISMATCH = 'Parent report identity mismatch'
GEOMETRY_DIFFERS = 'Parent region geometry or surface-admission identity differs'


class EditorContextError(DesignJobError):
    """A parent the editor refuses (Node's plain ``Error``); the message is Node's, verbatim. A ``DesignJobError``,
    so the routes answer it as Node's ``publicFailure`` does (400 with the message)."""


def _nullish(value: Any) -> bool:
    return value is None or value is UNDEFINED


def _opt(value: Any, key: str) -> Any:
    """``value?.key``."""
    return UNDEFINED if _nullish(value) else _member(value, key)


def _defined(*members: tuple[str, Any]) -> dict:
    """An object literal as ``JSON.stringify`` writes it: ``undefined`` members are left out."""
    return {key: value for key, value in members if value is not UNDEFINED}


class EditorJobs(DesignJobs):
    """Node's ``ElectrodeEditorService`` on one root: ``DesignJobs`` with the editor's request, result check,
    context, worker input and view.

    ``library`` is the root's ``jobs.library.Library`` (Node's ``queue.library``), or a function that returns it,
    called when a context first needs it; its ``get`` may also be a coroutine function. Every other argument is
    ``DesignJobs``'s: ``root``, the native interpreter ``python`` (which runs the worker and enters the identity),
    ``context`` (Node's ``context`` option, which replaces the design context the editor's builds on), ``spawn``,
    ``timeout_ms``, ``store``, ``execution_slot`` (shared with the coordinate evaluation, as Node's
    ``executionSlotFor(queue)``), ``inputs``, ``clock`` and ``random_uuid``.
    """

    record_kind = 'editor'
    script_name = WORKER_SCRIPT

    def __init__(self, root: str, python: str, library: Any = None, **options: Any):
        super().__init__(root, python, **options)
        self._library = library

    @property
    def library(self) -> Any:
        """``this.queue.library``."""
        library = self._library
        if callable(library) and not hasattr(library, 'get'):
            library = self._library = library()
        return library

    # --- Node's overrides -----------------------------------------------------------------------------------------

    def normalize(self, raw: Any) -> dict:
        """``normalizeEditorRequest(raw)``: raises ``ValueError`` with Node's message."""
        return normalize_editor_request(raw)

    def validate(self, result: Any, request: Any, admission: Any = UNDEFINED) -> None:
        """``validateEditorResult(result, request)``; ``admission`` is ignored, as Node drops the extra argument."""
        validate_editor_result(result, request)

    async def context(self, request: Any) -> dict:
        """``await context(request)``: ``{identity, admission, key, parent, parent_digest}``. Raises
        ``EditorContextError`` with Node's message for a parent the editor refuses, and what the library, the
        design context or a digest raises."""
        from .kinds import call  # here: jobs.kinds builds the adapters of this module

        parent = await call(self._get_parent, _member(request, 'parent_id'))
        parent_digest = await call(self._parent_digest, request, parent)
        base = await super().context(request)
        return await call(self._editor_context, request, base, parent, parent_digest)

    def worker_input(self, job: DesignJob) -> Any:
        """``workerInput(j)``: ``{request, parent}``."""
        return _defined(('request', job.request), ('parent', _member(job.ctx, 'parent')))

    def view(self, job: DesignJob) -> dict:
        """``view(j)``: the coordinate evaluation's view with ``parent_digest``, the context's or, for a job without
        one (a cached job of ``submit``), the digest of the result's ``parent`` (a preparation echoes it), else the
        result request's (an evaluation's)."""
        digest = _opt(job.ctx, 'parent_digest')
        if _nullish(digest):
            result = None if job.result is UNDEFINED else job.result
            parent = _opt(result, 'parent')
            digest = jsjson.sha256_hex(parent) if js_truthy(parent) else _opt(_opt(result, 'request'), 'parent_digest')
        return _defined(*super().view(job).items(), ('parent_digest', digest))

    def records(self) -> list[dict]:
        """``await records()``: the saved evaluations as editor drafts (``editor_records.records``)."""
        return records(self.store)

    def parents(self) -> list[dict]:
        """``await parents()``: the library layouts the editor can start from (``editor_records.parents``)."""
        return parents(self.library)

    # --- The context, step by step --------------------------------------------------------------------------------

    def _get_parent(self, parent_id: Any) -> Any:
        """``await this.queue.library.get(parent_id)``; a coroutine is awaited by ``kinds.call``."""
        return self.library.get(parent_id)

    @staticmethod
    def _parent_digest(request: Any, parent: Any) -> str:
        """The checks of the parent record, then its digest, ``sha256(JSON.stringify(parent))``."""
        if (not _same(_opt(parent, 'status'), 'completed')
                or not js_truthy(_opt(_member(parent, 'layout'), 'regionPatchVertexIndices'))):
            raise EditorContextError(NOT_A_PARENT)
        if js_truthy(_opt(_member(parent, 'request'), 'noise_model')):
            raise EditorContextError(NOT_INDEPENDENT)
        parent_digest = jsjson.sha256_hex(parent)
        if (_same(_member(request, 'action'), 'evaluate')
                and not _same(_member(request, 'parent_digest'), parent_digest)):
            raise EditorContextError(PARENT_CHANGED)
        return parent_digest

    def _editor_context(self, request: Any, base: Any, parent: Any, parent_digest: str) -> dict:
        """The parent's region geometry and surface admission against the design context's, then the identity
        (B17: the design identity copied, ``schema`` overwritten in place, three members appended) and the key."""
        geometry = _member(_member(parent, 'provenance'), 'geometry_sha256')
        if _same(_member(parent, 'dataset_id'), 'strict_area'):
            report = _member(_member(parent, 'provenance'), 'file')
            if not _same(self.inputs.digest(_path(report)), _member(_member(parent, 'provenance'), 'sha256')):
                raise EditorContextError(REPORT_MISMATCH)
            data = jsjson.parse(nodefs.decode(nodefs.read_file(nodepath.join(self.root, _path(report)))))
            geometry = _opt(_member(data, 'identity'), 'geometry_sha256')
        admission = _member(base, 'admission')
        if (not _same(geometry, _member(admission, 'geometry_sha256'))
                or not _same(_member(_member(parent, 'provenance'), 'surface_admissibility_sha256'),
                             _member(admission, 'sha256'))):
            raise EditorContextError(GEOMETRY_DIFFERS)
        identity = {**_spread(_member(base, 'identity')), 'schema': EDITOR_CACHE_SCHEMA, 'parent_digest': parent_digest}
        identity['editor_sha256'] = self.inputs.digest(self.script_name)
        identity['editor_implementation_sha256'] = self.inputs.digest_all(EDITOR_WORKFLOW)
        return {**_spread(base), 'parent': parent, 'parent_digest': parent_digest, 'identity': identity,
                'key': request_key(request, identity)}


def editor_jobs(runtime: Any, library: Optional[Any] = None, **options: Any) -> EditorJobs:
    """Node's ``new ElectrodeEditorService(queue)`` for a ``RuntimeConfig``: its root and native interpreter, and the
    library of that root (``jobs.library.Library``, built here unless given)."""
    if library is None:
        from .library import Library
        library = Library(runtime.repository_root, runtime)
    return EditorJobs(runtime.repository_root, runtime.native_python, library, **options)
