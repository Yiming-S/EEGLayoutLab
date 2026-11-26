"""Electrode-name sidecar storage, queue attachment and HTTP transport tests (phase 2 slice 5).

Ports the six server/sidecar sites of ``check-electrode-annotations.mjs`` adapted to the single-owner local
workspace architecture (design 0001, decision 6).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import uuid

import pytest

from eeglayoutlab.jobs.annotations import ANNOTATION_LIMITS, AnnotationError, ElectrodeAnnotations
from eeglayoutlab.jobs.design import DesignEvaluationService, design_adapter
from eeglayoutlab.jobs.design_result import normalize_design_request
from eeglayoutlab.jobs.identity import request_key
from eeglayoutlab.jobs.queue import QueueError, WorkspaceQueue
from eeglayoutlab.schemas import jsjson

from .key_parity_support import require


def _base_design() -> dict[str, Any]:
    return {
        'schema': 'eeg-electrode-design/1',
        'coordinate_system': 'ernie_native_mm',
        'unit': 'mm',
        'name': 'Shared layout',
        'xyz_mm': [[(i % 8) * 6, (i // 8) * 6, 1e-14] for i in range(64)],
        'region_indices': [i % 2 for i in range(64)],
    }


def _names(prefix: str) -> list[str]:
    return [f'{prefix}{i + 1}' for i in range(64)]


def _submission(req: dict[str, Any], names: list[str]) -> dict[str, Any]:
    return {'schema': 'design-submission/1', 'request': req, 'electrode_names': names}


def _fixture(tmp_path: Path, *, cached: bool = True):
    root = tmp_path / 'root'
    ws = tmp_path / 'workspace'
    root.mkdir(parents=True, exist_ok=True)
    ws.mkdir(parents=True, exist_ok=True)

    design = _base_design()
    req = normalize_design_request({'action': 'evaluate', 'design': design, 'radius_mm': 6, 'seed': 42})
    identity = {'test_identity': 'frozen'}
    key = request_key(req, identity)
    result = {
        'schema': 'design-evaluation/1',
        'status': 'completed',
        'request': req,
        'forward_mode': 'cached_fem',
        'evaluated_xyz_mm': design['xyz_mm'],
        'nominal': {
            'field_relative': 1,
            'field_absolute': 0.9,
            'reference_field_absolute': 0.9,
            'sensitivity_tail': 1,
            'localization_relative': 1,
            'median_mm': 10,
            'p90_mm': 20,
            'reference_median_mm': 10,
            'reference_p90_mm': 20,
        },
        'projection_max_mm': 0,
        'trials': [],
        'provenance': {'candidate_count': 64, 'original': [1 / 3, -1e-18, 1.0000000000000002]},
    }
    cache = {
        'key': key,
        'identity': identity,
        'result': result,
        'result_sha256': jsjson.sha256_hex(result),
        'finished_at': '2026-11-25T12:00:00.000Z',
    }
    cache_dir = root / 'results/v2/design_evaluation_jobs' / key
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / 'cache.json'
    if cached:
        cache_path.write_bytes(jsjson.stringify(cache).encode('utf-8'))

    service = DesignEvaluationService(
        str(root),
        python='unused',
        context_override=lambda r: {'identity': identity, 'key': request_key(r, identity)},
        spawn_process=lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError('metadata test must not spawn')),
    )
    ws_ann_dir = str(ws / 'annotations' / 'electrode-names')
    annotations = ElectrodeAnnotations.local(ws_ann_dir, str(root))
    blocked = [False]

    def gate() -> None:
        if blocked[0]:
            raise QueueError('Resources unavailable.', 503)

    queue_dir = str(ws / '.eeglayoutlab' / 'queue')
    scheduler = WorkspaceQueue(
        queue_dir,
        {'design-evaluation': design_adapter(service)},
        root=str(root),
        annotations=annotations,
        poll_ms=None,
        before_new_work=gate,
    )
    return {
        'root': root,
        'ws': ws,
        'ws_ann_dir': ws_ann_dir,
        'queue_dir': queue_dir,
        'service': service,
        'annotations': annotations,
        'scheduler': scheduler,
        'req': req,
        'key': key,
        'cache': cache,
        'cache_path': cache_path,
        'set_blocked': lambda flag: blocked.__setitem__(0, flag),
    }


def test_shared_receipts_retain_variants_across_restart_without_scientific_file_changes(tmp_path):
    """check-electrode-annotations.mjs:62 'shared receipts retain owner-specific and same-owner variants across restart
    without scientific file changes' (owners dropped per R1)."""
    f = _fixture(tmp_path, cached=False)
    try:
        names_a, names_b = _names('A'), _names('B')
        first = f['scheduler'].submit('design-evaluation', _submission(f['req'], names_a))
        second = f['scheduler'].submit('design-evaluation', _submission(f['req'], names_b))
        assert first['job']['id'] == second['job']['id']
        assert first['job']['key'] == second['job']['key']
        aid = first['job']['annotation_id']
        bid = second['job']['annotation_id']
        assert aid != bid

        task = f['scheduler'].get_task(first['job']['id'], 'design-evaluation')
        assert f['scheduler'].view(task, include_result=False, annotation_id=aid)['electrode_annotation']['electrode_names'] == names_a
        assert f['scheduler'].view(task, include_result=False, annotation_id=bid)['electrode_annotation']['electrode_names'] == names_b

        f['scheduler'].dispose()
        restored = WorkspaceQueue(
            f['queue_dir'],
            {'design-evaluation': design_adapter(f['service'])},
            root=str(f['root']),
            annotations=ElectrodeAnnotations.local(f['ws_ann_dir'], str(f['root'])),
            poll_ms=None,
        )
        try:
            rtask = restored.get_task(first['job']['id'], 'design-evaluation')
            assert restored.view(rtask, include_result=False, annotation_id=aid)['electrode_annotation']['electrode_names'] == names_a
            assert restored.view(rtask, include_result=False, annotation_id=bid)['electrode_annotation']['electrode_names'] == names_b
            assert rtask['request'] == f['req']
            assert list((f['root'] / 'results/v2/design_evaluation_jobs' / f['key']).iterdir()) == []
        finally:
            restored.dispose()
    finally:
        f['scheduler'].dispose()
        f['service'].dispose()


def test_sidecar_integrity_paths_crashed_temporaries_private_output_and_storage_limits(tmp_path):
    """check-electrode-annotations.mjs:78 'sidecar integrity, paths, crashed temporaries, private output and storage
    limits are enforced'."""
    f = _fixture(tmp_path)
    try:
        adapter = f['scheduler'].adapters['design-evaluation']
        names_a, names_b = _names('A'), _names('B')
        prepared = adapter['prepare'](_submission(f['req'], names_a))
        owner = 'a' * 64
        first = f['annotations'].create(prepared, owner)
        assert owner not in jsjson.stringify(first)

        directory = Path(f['annotations'].write_directory())
        assert (directory.stat().st_mode & 0o777) == 0o700
        (directory / f'.{uuid.uuid4()}.tmp').write_text('interrupted', encoding='utf-8')
        second = f['annotations'].create({**prepared, 'electrode_names': names_b}, owner)
        assert second['record_id'] == f['key']
        assert len(f['annotations'].list()) == 2

        limited = ElectrodeAnnotations.local(
            f['ws_ann_dir'], str(f['root']), limits={**ANNOTATION_LIMITS, 'files': 3},
        )
        with pytest.raises(AnnotationError) as exc_limit:
            limited.create({**prepared, 'electrode_names': _names('C')}, owner)
        assert exc_limit.value.status == 507

        with pytest.raises(AnnotationError) as exc_traverse:
            f['annotations'].read('../outside', f['key'])
        assert exc_traverse.value.status == 404

        ann_path = directory / f"{first['id']}.json"
        assert (ann_path.stat().st_mode & 0o777) == 0o600
        original = ann_path.read_text(encoding='utf-8')
        ann_path.write_text(original.replace('A1', 'changed'), encoding='utf-8')
        with pytest.raises(AnnotationError) as exc_corrupt:
            f['annotations'].read(first['id'], f['key'])
        assert exc_corrupt.value.status == 409

        ann_path.unlink()
        os.symlink(f['cache_path'], ann_path)
        with pytest.raises(AnnotationError) as exc_link:
            f['annotations'].read(first['id'], f['key'])
        assert exc_link.value.status == 409
    finally:
        f['scheduler'].dispose()
        f['service'].dispose()


def test_lookup_misses_do_not_create_metadata_and_bare_cached_reads_stay_available(tmp_path):
    """check-electrode-annotations.mjs:94 'lookup misses do not create metadata, blocked writes fail before receipts,
    bare cached reads stay available'."""
    f = _fixture(tmp_path, cached=False)
    try:
        envelope = _submission(f['req'], _names('A'))
        assert f['scheduler'].submit('design-evaluation', envelope, lookup_only=True) == {'hit': False}
        assert f['annotations'].write_directory() is None
        assert len(f['scheduler'].tasks) == 0

        f['set_blocked'](True)
        with pytest.raises(QueueError) as exc_blocked:
            f['scheduler'].submit('design-evaluation', envelope)
        assert exc_blocked.value.status == 503
        assert f['annotations'].write_directory() is None
        assert len(f['scheduler'].tasks) == 0

        f['cache_path'].write_bytes(jsjson.stringify(f['cache']).encode('utf-8'))
        assert f['scheduler'].submit('design-evaluation', f['req'], lookup_only=True)['hit'] is True
        with pytest.raises(QueueError) as exc_lookup_blocked:
            f['scheduler'].submit('design-evaluation', envelope, lookup_only=True)
        assert exc_lookup_blocked.value.status == 503
        assert f['annotations'].write_directory() is None
        assert len(f['scheduler'].tasks) == 1

        f['set_blocked'](False)
        saved = f['scheduler'].submit('design-evaluation', envelope, lookup_only=True)
        f['set_blocked'](True)
        retry = f['scheduler'].submit('design-evaluation', envelope, lookup_only=True)
        assert retry['job']['annotation_id'] == saved['job']['annotation_id']
    finally:
        f['scheduler'].dispose()
        f['service'].dispose()


def test_per_receipt_metadata_bound_rejects_new_variants_without_creating_files(tmp_path):
    """check-electrode-annotations.mjs:112 'per-owner and per-receipt metadata bounds reject new variants without
    creating files' (per-receipt 100-variant bound; per-owner bound dropped per R1)."""
    f = _fixture(tmp_path)
    try:
        first = f['scheduler'].submit('design-evaluation', _submission(f['req'], _names('A')))
        aid = first['job']['annotation_id']
        task = f['scheduler'].get_task(first['job']['id'], 'design-evaluation')
        task['annotation_refs'] = {'local': [aid] * 100}

        with pytest.raises(QueueError) as exc_bound:
            f['scheduler'].submit('design-evaluation', _submission(f['req'], _names('B')))
        assert exc_bound.value.status == 413
        assert len(f['annotations'].list()) == 1
    finally:
        f['scheduler'].dispose()
        f['service'].dispose()


def test_http_annotations_require_policy_and_token_and_serve_annotation_id_on_jobs_library_and_bundles(tmp_path):
    """check-electrode-annotations.mjs:124 'HTTP annotations require policy/token and owner; snapshots and delivery
    preserve each variant after sidecars disappear' (policy, token and annotation_id reads; owner/sharing dropped per
    R1/R5)."""
    require('fastapi')
    require('httpx')
    from .service_support import TOKENS, loopback_client, make_app, static_export, synthetic_root

    root = synthetic_root(tmp_path / 'root')
    static = static_export(tmp_path / 'static')
    ws = tmp_path / 'ws'
    ws.mkdir()

    design = _base_design()
    req = normalize_design_request({'action': 'evaluate', 'design': design, 'radius_mm': 6, 'seed': 42})
    svc_probe = DesignEvaluationService(str(root))
    ctx = svc_probe.context(req)
    key = ctx['key']
    svc_probe.dispose()

    result = {
        'schema': 'design-evaluation/1',
        'status': 'completed',
        'request': req,
        'forward_mode': 'cached_fem',
        'evaluated_xyz_mm': design['xyz_mm'],
        'nominal': {
            'field_relative': 1,
            'field_absolute': 0.9,
            'reference_field_absolute': 0.9,
            'sensitivity_tail': 1,
            'localization_relative': 1,
            'median_mm': 10,
            'p90_mm': 20,
            'reference_median_mm': 10,
            'reference_p90_mm': 20,
        },
        'projection_max_mm': 0,
        'trials': [],
        'provenance': {
            'candidate_count': 64,
            'surface_admissibility_sha256': ctx['admission']['sha256'],
            'surface_admissibility_version': ctx['admission']['schema_version'],
        },
    }
    cache = {
        'key': key,
        'identity': ctx['identity'],
        'result': result,
        'result_sha256': jsjson.sha256_hex(result),
        'finished_at': '2026-11-25T12:00:00.000Z',
    }
    cache_path = Path(root) / 'results/v2/design_evaluation_jobs' / key / 'cache.json'
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    before_bytes = jsjson.stringify(cache).encode('utf-8')
    cache_path.write_bytes(before_bytes)

    app = make_app(root, static, workspace=ws)
    client = loopback_client(app)
    try:
        names_a, names_b = _names('A'), _names('B')
        body_a = jsjson.stringify(_submission(req, names_a)).encode('utf-8')
        body_b = jsjson.stringify(_submission(req, names_b)).encode('utf-8')
        headers = {'content-type': 'application/json', 'x-eeg-compute-token': TOKENS.csrf}

        assert client.post('/api/design-evaluation/lookup', content=body_a,
                           headers={'content-type': 'application/json'}).status_code == 403
        assert client.post('/api/design-evaluation/lookup', content=body_a,
                           headers={**headers, 'origin': 'https://foreign.test'}).status_code == 403

        first = client.post('/api/design-evaluation/lookup', content=body_a, headers=headers)
        second = client.post('/api/design-evaluation/lookup', content=body_b, headers=headers)
        assert first.status_code == 200 and second.status_code == 200
        aid = first.json()['job']['annotation_id']
        bid = second.json()['job']['annotation_id']
        assert aid != bid and first.json()['job']['key'] == second.json()['job']['key'] == key

        job_id = first.json()['job']['id']
        old = client.get(f'/api/design-evaluation/jobs/{job_id}?annotation_id={aid}')
        assert old.status_code == 200
        assert old.json()['job']['electrode_annotation']['electrode_names'] == names_a
        assert client.get(f'/api/design-evaluation/jobs/{job_id}?annotation_id={aid}&extra=1').status_code == 400

        rec = client.get(f'/api/local-compute/library/{key}?annotation_id={aid}')
        assert rec.status_code == 200
        assert rec.json()['record']['electrode_annotation']['electrode_names'] == names_a
        assert 'electrode_annotation' not in client.get(f'/api/local-compute/library/{key}').json()['record']

        bundle = client.get(f'/api/local-compute/library/{key}/bundle?annotation_id={aid}')
        assert bundle.status_code == 200
        assert bundle.json()['original_record'] == cache
        assert bundle.json()['electrode_annotation']['electrode_names'] == names_a
        assert cache_path.read_bytes() == before_bytes
    finally:
        app.close()


def test_multibyte_electrode_names_survive_request_chunks_split_inside_every_utf8_character(tmp_path):
    """check-electrode-annotations.mjs:184 'multibyte electrode names survive request chunks split inside every UTF-8
    character'."""
    f = _fixture(tmp_path)
    try:
        labels = _names('电极🧠')
        payload_bytes = jsjson.stringify(_submission(f['req'], labels)).encode('utf-8')
        # Byte-by-byte reassembly (as ASGI read_json_body accumulates arbitrary stream chunks before UTF-8 decode).
        reassembled = bytearray()
        for idx in range(len(payload_bytes)):
            reassembled.extend(payload_bytes[idx:idx + 1])
        parsed = jsjson.parse(jsjson.decode_body(bytes(reassembled)))
        outcome = f['scheduler'].submit('design-evaluation', parsed, lookup_only=True)
        assert outcome['hit'] is True
        assert outcome['job']['electrode_annotation']['electrode_names'] == labels
    finally:
        f['scheduler'].dispose()
        f['service'].dispose()

    require('fastapi')
    from .service_support import PORT, TOKENS, make_app, session_cookie, static_export, synthetic_root
    import asyncio

    root = synthetic_root(tmp_path / 'http_root')
    static = static_export(tmp_path / 'http_static')
    ws = tmp_path / 'http_ws'
    ws.mkdir()

    design = _base_design()
    req = normalize_design_request({'action': 'evaluate', 'design': design, 'radius_mm': 6, 'seed': 42})
    probe = DesignEvaluationService(str(root))
    ctx = probe.context(req)
    probe.dispose()
    result = {
        'schema': 'design-evaluation/1',
        'status': 'completed',
        'request': req,
        'forward_mode': 'cached_fem',
        'evaluated_xyz_mm': design['xyz_mm'],
        'nominal': {
            'field_relative': 1,
            'field_absolute': 0.9,
            'reference_field_absolute': 0.9,
            'sensitivity_tail': 1,
            'localization_relative': 1,
            'median_mm': 10,
            'p90_mm': 20,
            'reference_median_mm': 10,
            'reference_p90_mm': 20,
        },
        'projection_max_mm': 0,
        'trials': [],
        'provenance': {
            'candidate_count': 64,
            'surface_admissibility_sha256': ctx['admission']['sha256'],
            'surface_admissibility_version': ctx['admission']['schema_version'],
        },
    }
    cache_file = Path(root) / 'results/v2/design_evaluation_jobs' / ctx['key'] / 'cache.json'
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(jsjson.stringify({
        'key': ctx['key'],
        'identity': ctx['identity'],
        'result': result,
        'result_sha256': jsjson.sha256_hex(result),
    }).encode('utf-8'))

    app = make_app(root, static, workspace=ws)
    raw = jsjson.stringify(_submission(req, _names('电极🧠'))).encode('utf-8')
    sent_chunks = [raw[i:i + 1] for i in range(len(raw))]
    messages: list[dict[str, Any]] = []

    async def send_one_byte_at_a_time() -> None:
        idx = 0

        async def receive() -> dict[str, Any]:
            nonlocal idx
            if idx < len(sent_chunks):
                chunk = sent_chunks[idx]
                idx += 1
                return {'type': 'http.request', 'body': chunk, 'more_body': idx < len(sent_chunks)}
            return {'type': 'http.request', 'body': b'', 'more_body': False}

        async def send(msg: dict[str, Any]) -> None:
            messages.append(msg)

        scope = {
            'type': 'http',
            'asgi': {'version': '3.0'},
            'http_version': '1.1',
            'method': 'POST',
            'scheme': 'http',
            'path': '/api/design-evaluation/lookup',
            'raw_path': b'/api/design-evaluation/lookup',
            'query_string': b'',
            'client': ('127.0.0.1', 51000),
            'headers': [
                (b'host', f'127.0.0.1:{PORT}'.encode('ascii')),
                (b'cookie', session_cookie().encode('ascii')),
                (b'content-type', b'application/json'),
                (b'x-eeg-compute-token', TOKENS.csrf.encode('ascii')),
            ],
        }
        await app(scope, receive, send)

    try:
        asyncio.run(send_one_byte_at_a_time())
        start = next(m for m in messages if m['type'] == 'http.response.start')
        body = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
        assert start['status'] == 200
        decoded = jsjson.parse(body.decode('utf-8'))
        assert decoded['job']['electrode_annotation']['electrode_names'] == _names('电极🧠')
    finally:
        app.close()
