"""Electrode-editor execution service (``webapp/server/electrode-editor-server.mjs``, phase 2 slice 6).

Subclasses ``DesignEvaluationService`` for ``prepare`` and ``evaluate`` actions on saved 64-electrode layouts
with region patches:
- Validates parent eligibility, independent noise requirement, ``parent_digest``, and surface-admissibility /
  geometry SHA-256 against the active installation.
- Preserves Node's exact ``identity`` field order (plan B17: copy ``base.identity``, overwrite ``schema`` in
  first position with ``'electrode-editor-cache/1'``, and append ``parent_digest``, ``editor_sha256``,
  ``editor_implementation_sha256``).
- Shares ``RecordStore`` (``results/v2/electrode_editor_jobs``) and ``ExecutionSlot`` with the other compute
  services.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from ..schemas import jsjson
from ..schemas.electrode_editor import normalize_editor_request
from . import nodefs, nodepath
from .design import DesignEvaluationService, _DesignJob
from .editor_records import parents as list_editor_parents
from .editor_records import records as list_editor_records
from .editor_records import validate_editor_result
from .identity import EDITOR_WORKFLOW, UNDEFINED, js_truthy, request_key
from .library import Library
from .records import read_file

__all__ = ['EDITOR_CACHE_SCHEMA', 'ElectrodeEditorService', 'editor_adapter']

EDITOR_CACHE_SCHEMA = 'electrode-editor-cache/1'


class ElectrodeEditorService(DesignEvaluationService):
    """Port of ``ElectrodeEditorService`` (``webapp/server/electrode-editor-server.mjs``)."""

    record_kind = 'editor'
    script_name = 'scripts/electrode_editor.py'

    def __init__(
        self,
        repository_root: Optional[str] = None,
        *,
        library: Optional[Library] = None,
        **kwargs: Any,
    ):
        super().__init__(repository_root, **kwargs)
        self.library = library if library is not None else Library(self.root, self.runtime)

    def normalize(self, raw: Any) -> dict[str, Any]:
        return normalize_editor_request(raw)

    def validate(self, result: Any, request: dict[str, Any], admission: Any = UNDEFINED) -> None:
        validate_editor_result(result, request)

    def context(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.context_override is not None:
            return super().context(request)
        parent = self.library.get(request['parent_id'])
        layout = parent.get('layout') if isinstance(parent, dict) else None
        xyz = layout.get('xyzMm') if isinstance(layout, dict) else None
        if (not isinstance(parent, dict)
                or parent.get('status') != 'completed'
                or not js_truthy(layout.get('regionPatchVertexIndices') if isinstance(layout, dict) else None)
                or not (isinstance(xyz, list) and len(xyz) == 64)):
            raise ValueError('Choose a completed layout with saved region boundaries')
        parent_req = parent.get('request')
        if isinstance(parent_req, dict) and js_truthy(parent_req.get('noise_model')):
            raise ValueError(
                'The electrode editor scores with independent noise; choose a layout searched under independent noise'
            )
        parent_digest = jsjson.sha256_hex(parent)
        if request['action'] == 'evaluate' and request['parent_digest'] != parent_digest:
            raise ValueError('Parent changed; reload the layout before editing')
        base = super().context(request)
        prov = parent['provenance']
        geometry = prov.get('geometry_sha256')
        if parent.get('dataset_id') == 'strict_area':
            report = prov['file']
            if self.inputs.digest(report) != prov.get('sha256'):
                raise ValueError('Parent report identity mismatch')
            report_json = jsjson.parse(nodefs.decode(read_file(nodepath.join(self.root, report))))
            report_identity = report_json.get('identity') if isinstance(report_json, dict) else None
            geometry = report_identity.get('geometry_sha256') if isinstance(report_identity, dict) else None
        admission = base['admission']
        if (geometry != admission.get('geometry_sha256')
                or prov.get('surface_admissibility_sha256') != admission.get('sha256')):
            raise ValueError('Parent region geometry or surface-admission identity differs')
        # Plan B17: copy base.identity, overwrite schema in first position, append editor fields.
        identity = {
            **base['identity'],
            'schema': EDITOR_CACHE_SCHEMA,
            'parent_digest': parent_digest,
            'editor_sha256': self.inputs.digest(self.script_name),
            'editor_implementation_sha256': self.inputs.digest_all(list(EDITOR_WORKFLOW)),
        }
        return {
            **base,
            'parent': parent,
            'parent_digest': parent_digest,
            'identity': identity,
            'key': request_key(request, identity),
        }

    def worker_input(self, job: _DesignJob) -> Any:
        return {'request': job.request, 'parent': job.ctx.get('parent')}

    def view(self, job: _DesignJob) -> dict[str, Any]:
        out = super().view(job)
        parent_digest = job.ctx.get('parent_digest') if isinstance(job.ctx, dict) else None
        if parent_digest is None and isinstance(job.result, dict):
            if js_truthy(job.result.get('parent')):
                parent_digest = jsjson.sha256_hex(job.result['parent'])
            elif isinstance(job.result.get('request'), dict):
                parent_digest = job.result['request'].get('parent_digest')
        if parent_digest is not None:
            out['parent_digest'] = parent_digest
        return out

    def records(self) -> list[dict[str, Any]]:
        return list_editor_records(self.store)

    def parents(self) -> list[dict[str, Any]]:
        return list_editor_parents(self.library)


def editor_adapter(service: ElectrodeEditorService) -> dict[str, Callable[..., Any]]:
    """Adapter binding ``ElectrodeEditorService`` into ``WorkspaceQueue``."""
    def prepare(raw: Any) -> dict[str, Any]:
        request = service.normalize(raw)
        ctx = service.context(request)
        return {'request': request, 'key': ctx['key'], 'ctx': ctx}

    return {
        'prepare': prepare,
        'lookup': lambda p: service.lookup(p['request'], p['ctx']),
        'start': lambda r: service.submit(r),
        'get': lambda job_id: service.get(job_id),
        'busy': lambda: bool(service.busy),
        'pid': lambda: service.pid(),
        'cancel': lambda job_id: service.cancel(job_id),
    }
