"""Electrode-editor service, result schema and B17 context parity tests (phase 2 slice 6).

Ports the two pending server sites of ``check-electrode-editor.mjs`` and verifies ``ElectrodeEditorService.context``
byte-for-byte against Node's ``ElectrodeEditorService`` (plan B17).
"""
from __future__ import annotations

import copy
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any

import pytest

from eeglayoutlab.jobs.editor import EDITOR_CACHE_SCHEMA, ElectrodeEditorService
from eeglayoutlab.jobs.editor_records import EditorResultError, validate_editor_result
from eeglayoutlab.jobs.identity import EDITOR_WORKFLOW
from eeglayoutlab.jobs.worker import ExecutionSlot
from eeglayoutlab.schemas import jsjson

from .key_parity_support import NODE_ENV, design_root, digest
from .test_worker import FakeChild

PARENT = 'a' * 64
DIGEST = 'b' * 64
XYZ = [[i * 5, 0, 0] for i in range(64)]
LABELS = [int(i >= 32) for i in range(64)]
METRICS = {
    'field_relative': 0.8,
    'field_absolute': 0.7,
    'sensitivity_tail': 0.4,
    'localization_relative': 0.3,
    'median_mm': 20,
    'p90_mm': 40,
    'conditional_global': 0.3,
}


def _slots() -> list[dict[str, Any]]:
    return [{'bank_index': i, 'enabled': True} for i in range(64)]


def _request(**overrides: Any) -> dict[str, Any]:
    return {
        'action': 'evaluate',
        'parent_id': PARENT,
        'parent_digest': DIGEST,
        'seed': 2026,
        'slots': _slots(),
        **overrides,
    }


def _result(req: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    enabled_indices = [i for i, s in enumerate(req['slots']) if s['enabled']]
    n = len(enabled_indices)
    return {
        'schema': 'electrode-editor/1',
        'status': 'completed',
        'request': req,
        'electrode_count': n,
        'active_slots': enabled_indices,
        'evaluated_xyz_mm': [XYZ[i] for i in enabled_indices],
        'region_indices': [LABELS[i] for i in enabled_indices],
        'minimum_distance_mm': 5,
        'baseline': copy.deepcopy(METRICS),
        'parent_metrics': copy.deepcopy(METRICS),
        'edited_metrics': copy.deepcopy(METRICS),
        **overrides,
    }


def _wait_idle(service: ElectrodeEditorService, timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if service.active is None:
            return
        time.sleep(0.01)
    raise AssertionError('editor job did not finish')


def test_result_schema_rejects_stale_requests_malformed_geometry_and_fabricated_combined_score():
    """check-electrode-editor.mjs:46 'result schema rejects stale requests, malformed geometry and fabricated
    combined score'."""
    req = _request()
    validate_editor_result(_result(req), req)

    for patch in (
        {'request': {**req, 'parent_digest': 'c' * 64}},
        {'electrode_count': 63},
        {'minimum_distance_mm': 0},
        {'active_slots': [1] * 64},
        {'edited_metrics': {**METRICS, 'conditional_global': 0.8}},
    ):
        with pytest.raises(EditorResultError):
            validate_editor_result({**_result(req), **patch}, req)

    prep_req = {'action': 'prepare', 'parent_id': PARENT}
    prep_ok = {
        'schema': 'electrode-editor/1',
        'status': 'completed',
        'request': prep_req,
        'parent': {'id': PARENT, 'region_count': 2},
        'original_indices': list(range(64)),
        'regions': [
            {'bank_indices': list(range(r * 32, (r + 1) * 32)), 'xyz_mm': XYZ[r * 32:(r + 1) * 32]}
            for r in (0, 1)
        ],
    }
    validate_editor_result(prep_ok, prep_req)
    with pytest.raises(EditorResultError, match='Invalid editor region data'):
        validate_editor_result({**prep_ok, 'regions': prep_ok['regions'][:1]}, prep_req)


def test_editor_shares_capacity_caches_completed_results_and_retains_capacity_while_cancelling(tmp_path):
    """check-electrode-editor.mjs:67 'editor shares capacity, caches completed results and retains capacity while
    cancelling'."""
    slot = ExecutionSlot()
    children: list[FakeChild] = []

    def spawn(*_args: Any, **_kwargs: Any) -> FakeChild:
        child = FakeChild(pid=7100 + len(children))
        children.append(child)
        return child

    class _DummyLibrary:
        def get(self, _pid: str) -> Any:
            return None

    service = ElectrodeEditorService(
        str(tmp_path),
        python='python',
        library=_DummyLibrary(),  # type: ignore[arg-type]
        execution_slot=slot,
        spawn_process=spawn,
        context_override=lambda r: {
            'identity': {'schema': 'test'},
            'key': jsjson.sha256_hex({'request': r, 'identity': {'schema': 'test'}}),
            'parent': {'id': PARENT},
            'parent_digest': DIGEST,
        },
    )
    release_other = None
    try:
        release_design = slot.acquire('existing')
        assert release_design is not None
        assert service.submit(_request())['busy'] is True
        assert len(children) == 0
        release_design()

        first = service.submit(_request())
        assert len(children) == 1
        assert first['job']['parent_digest'] == DIGEST
        assert jsjson.parse(children[0].stdin_payloads[0]) == {'request': _request(), 'parent': {'id': PARENT}}

        children[0].emit_stdout(jsjson.stringify({'type': 'result', 'result': _result(_request())}) + '\n')
        children[0].close(0, None)
        _wait_idle(service)
        assert service.jobs[first['job']['id']].status == 'completed'

        release_other = slot.acquire('other')
        assert release_other is not None
        cached = service.submit(_request())
        assert cached['job']['cached'] is True
        assert cached['job']['parent_digest'] == DIGEST
        assert len(children) == 1
        release_other()
        release_other = None

        nxt = _request()
        nxt['slots'][0]['enabled'] = False
        second = service.submit(nxt)
        service.cancel(second['job']['id'])
        assert service.active is not None
        assert slot.busy is True
        children[1].close(0, None)
        _wait_idle(service)
        assert service.jobs[second['job']['id']].status == 'cancelled'
        assert service.jobs[second['job']['id']].result is None

        cache_path = service.store.path(service.record_kind, first['job']['key'], 'cache.json')
        stored = jsjson.parse(Path(cache_path).read_text(encoding='utf-8'))
        assert list(stored.keys()) == ['key', 'identity', 'result', 'result_sha256', 'finished_at']
        assert stored['result']['electrode_count'] == 64
    finally:
        if release_other is not None:
            release_other()
        service.dispose()


def test_editor_context_b17_key_order_and_node_parity(tmp_path):
    """Verifies B17 identity field order (schema overwritten first, editor fields appended) and exact key parity
    against Node's ElectrodeEditorService.context on synthetic roots."""
    root = design_root(tmp_path / 'root')
    tree = Path(root)
    (tree / 'scripts/electrode_editor.py').write_text('editor script', encoding='utf-8')
    for rel in EDITOR_WORKFLOW:
        p = tree / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f'workflow {rel}', encoding='utf-8')

    parent_req = {'region_count': 2, 'radius_mm': 35, 'mode': 'whole_surface'}
    parent_result = {
        'status': 'completed',
        'request': parent_req,
        'layout': {
            'id': 'cand-01',
            'xyzMm': XYZ,
            'referenceXyzMm': XYZ,
            'regionIndices': LABELS,
            'regionPatchVertexIndices': [[0, 1, 2], [3, 4, 5]],
            'regionAreasCm2': [12.5, 13.0],
        },
        'geometry': {'union_connected_component_count': 2, 'common_graph_radius_mm': 35, 'union_area_cm2': 25.5},
        'metrics': {
            'field_relative': 0.8,
            'sensitivity_tail': 0.4,
            'localization_relative': 0.3,
            'conditional_global': 0.3,
        },
        'provenance': {
            'geometry_sha256': digest('candidates'),
            'surface_admissibility_sha256': digest('mask'),
            'surface_admissibility_version': 'native-external-exposure/1',
        },
    }
    # Write radius worker & config so Library can read the radius cache record cleanly.
    (tree / 'scripts/run_local_radius_compute.py').write_text('radius worker', encoding='utf-8')
    (tree / 'configs/single_head_optimization.json').write_text('{"restarts":2}', encoding='utf-8')

    service = ElectrodeEditorService(root)
    try:
        _, parent_id = service.library.radius.identity_for(parent_req)
        cache_dir = tree / 'results/v2/local_app_jobs' / parent_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / 'cache.json').write_bytes(jsjson.stringify({
            'key': parent_id,
            'request': parent_req,
            'result': parent_result,
            'result_sha256': jsjson.sha256_hex(parent_result),
            'finished_at': '2026-11-25T10:00:00.000Z',
        }).encode('utf-8'))

        prep_req = {'action': 'prepare', 'parent_id': parent_id}
        prep_ctx = service.context(prep_req)
        assert list(prep_ctx['identity'].keys())[0] == 'schema'
        assert prep_ctx['identity']['schema'] == EDITOR_CACHE_SCHEMA
        assert list(prep_ctx['identity'].keys())[-3:] == [
            'parent_digest', 'editor_sha256', 'editor_implementation_sha256',
        ]

        eval_req = {
            'action': 'evaluate',
            'parent_id': parent_id,
            'parent_digest': prep_ctx['parent_digest'],
            'seed': 2026,
            'slots': _slots(),
        }
        eval_ctx = service.context(eval_req)

        # Reject stale parent_digest, missing parent, and correlated-noise parent.
        with pytest.raises(ValueError, match='Parent changed'):
            service.context({**eval_req, 'parent_digest': '0' * 64})
        with pytest.raises(ValueError, match='Choose a completed layout'):
            service.context({'action': 'prepare', 'parent_id': 'f' * 64})

        if shutil.which('node') is not None:
            checkout = Path(__file__).resolve().parents[2]
            editor_mod = str(checkout / 'webapp/server/electrode-editor-server.mjs')
            compute_mod = str(checkout / 'webapp/server/local-compute-server.mjs')
            node_queue_dir = str(tmp_path / 'node_queue')
            script = (
                f"import {{ LocalComputeQueue }} from {jsjson.stringify(compute_mod)};\n"
                f"import {{ ElectrodeEditorService }} from {jsjson.stringify(editor_mod)};\n"
                f"const q = new LocalComputeQueue({{ repositoryRoot: {jsjson.stringify(root)}, queueDirectory: {jsjson.stringify(node_queue_dir)} }});\n"
                "const ed = new ElectrodeEditorService(q);\n"
                f"const prep = await ed.context({jsjson.stringify(prep_req)});\n"
                f"const ev = await ed.context({jsjson.stringify(eval_req)});\n"
                "console.log(JSON.stringify({\n"
                "  prep_key: prep.key, prep_identity: JSON.stringify(prep.identity),\n"
                "  eval_key: ev.key, eval_identity: JSON.stringify(ev.identity),\n"
                "}));\n"
            )
            proc = subprocess.run(
                ['node', '--input-type=module', '-e', script],
                check=True, capture_output=True, text=True, env=NODE_ENV,
            )
            node_out = jsjson.parse(proc.stdout.strip())
            assert prep_ctx['key'] == node_out['prep_key']
            assert jsjson.stringify(prep_ctx['identity']) == node_out['prep_identity']
            assert eval_ctx['key'] == node_out['eval_key']
            assert jsjson.stringify(eval_ctx['identity']) == node_out['eval_identity']
    finally:
        service.dispose()
