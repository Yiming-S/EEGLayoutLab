"""The radius search's identity, stored results, and execution service (``eeglayoutlab.jobs.radius``, slices 3–4).

Ports check-local-compute.mjs's result validation and RadiusService tests, check-local-data-library.mjs's HTTP lookup
test, and check-lab-workflow.mjs's 30 strict-area records check; checks ``validate_worker_result`` against Node's
``validateWorkerResult`` message by message.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess

import pytest

from eeglayoutlab.jobs.identity import DATA_PRIOR_FILES, request_key  # noqa: E402
from eeglayoutlab.jobs.radius import (  # noqa: E402
    CODE_FILES, RADIUS_IDENTITY_VERSION, RadiusCache, RadiusResultError, RadiusService, code_identity, radius_identity,
    validate_worker_result,
)
from eeglayoutlab.jobs.records import error_code  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402

from .key_parity_support import NODE_ENV, PRIOR, needs_node  # noqa: E402
from .library_support import (  # noqa: E402
    CODE_NAMES, WEBAPP, code_tree, forward_inputs, radius_result, sha, write, write_cache,
)

REQUEST = {'region_count': 2, 'radius_mm': 35, 'mode': 'preset', 'mask_codes': ['PL', 'PR']}


def result_for(config: dict = REQUEST) -> dict:
    """``resultFor(config)`` of check-local-compute.mjs (the reference coordinates are the same list)."""
    xyz = [[i * 5.0, 0.0, 0.0] for i in range(64)]
    regions = config['region_count']
    labels = [min(regions - 1, i * regions // 64) for i in range(64)]
    return {'status': 'completed', 'request': config,
            'layout': {'id': 'fixture', 'xyzMm': xyz, 'referenceXyzMm': xyz, 'regionIndices': labels},
            'geometry': {'union_connected_component_count': regions, 'common_graph_radius_mm': config['radius_mm'],
                         'union_area_cm2': 30},
            'metrics': {'field_relative': 0.8, 'sensitivity_tail': 0.3, 'localization_relative': 0.5,
                        'conditional_global': 0.3}}


def test_result_validation_rejects_stale_request_duplicated_points_wrong_components_and_false_g():
    """check-local-compute.mjs:61."""
    validate_worker_result(result_for(), REQUEST)
    with pytest.raises(RadiusResultError, match='^结果配置不一致$'):
        validate_worker_result(result_for({**REQUEST, 'radius_mm': 40}), REQUEST)
    duplicate = result_for()
    duplicate['layout']['xyzMm'][1] = duplicate['layout']['xyzMm'][0]
    with pytest.raises(RadiusResultError, match='^无效64点坐标$'):
        validate_worker_result(duplicate, REQUEST)
    merged = result_for()
    merged['geometry']['union_connected_component_count'] = 1
    with pytest.raises(RadiusResultError, match='^区域几何无效$'):
        validate_worker_result(merged, REQUEST)
    wrong = result_for()
    wrong['metrics']['conditional_global'] = 0.9
    with pytest.raises(RadiusResultError, match='^综合约束计算不一致$'):
        validate_worker_result(wrong, REQUEST)
    validate_worker_result({'status': 'no_layout', 'request': REQUEST, 'layout': None, 'metrics': None}, REQUEST)


def test_adaptive_cross_region_allocation_mode_normalizes_and_enforces_floor():
    """check-local-compute.mjs::adaptive cross-region allocation mode normalizes cleanly and enforces >= 4 per region."""
    from eeglayoutlab.schemas.radius_search import normalize_request
    adaptive_req = normalize_request({**REQUEST, 'allocation_mode': 'adaptive'})
    assert adaptive_req == {**REQUEST, 'allocation_mode': 'adaptive'}
    assert normalize_request({**REQUEST, 'allocation_mode': 'balanced'}) == REQUEST
    assert normalize_request({**REQUEST, 'allocation_mode': None}) == REQUEST
    with pytest.raises(ValueError, match='单区域'):
        normalize_request({'region_count': 1, 'radius_mm': 30, 'mode': 'whole_surface', 'allocation_mode': 'adaptive'})
    with pytest.raises(ValueError, match='配额模式无效'):
        normalize_request({**REQUEST, 'allocation_mode': 'invalid'})
    asymmetric = result_for(adaptive_req)
    asymmetric['layout']['regionIndices'] = [0 if i < 12 else 1 for i in range(64)]
    validate_worker_result(asymmetric, adaptive_req)
    with pytest.raises(RadiusResultError, match='^区域分配错误$'):
        validate_worker_result({**asymmetric, 'request': REQUEST}, REQUEST)
    below_floor = result_for(adaptive_req)
    below_floor['layout']['regionIndices'] = [0 if i < 3 else 1 for i in range(64)]
    with pytest.raises(RadiusResultError, match='^区域分配错误$'):
        validate_worker_result(below_floor, adaptive_req)
    comp_req = normalize_request({**adaptive_req, 'objective_mode': 'composite'})
    assert comp_req == {**adaptive_req, 'objective_mode': 'composite'}
    assert normalize_request({**REQUEST, 'objective_mode': 'min'}) == REQUEST
    assert normalize_request({**REQUEST, 'objective_mode': None}) == REQUEST
    with pytest.raises(ValueError, match='优化目标模式无效'):
        normalize_request({**REQUEST, 'objective_mode': 'invalid'})
    validate_worker_result({**asymmetric, 'request': comp_req}, comp_req)

    k16_req = normalize_request({**comp_req, 'electrode_count': 16})
    assert k16_req == {**comp_req, 'electrode_count': 16}
    assert normalize_request({**REQUEST, 'electrode_count': 64}) == REQUEST
    assert normalize_request({**REQUEST, 'electrode_count': None}) == REQUEST
    with pytest.raises(ValueError, match='电极总数只支持'):
        normalize_request({**REQUEST, 'electrode_count': 20})
    with pytest.raises(ValueError, match='至少为每区4导'):
        normalize_request({'region_count': 4, 'radius_mm': 30, 'mode': 'whole_surface',
                           'allocation_mode': 'adaptive', 'electrode_count': 12})
    with pytest.raises(ValueError, match='每区至少2导'):
        normalize_request({'region_count': 6, 'radius_mm': 30, 'mode': 'whole_surface', 'electrode_count': 8})
    k16_res = result_for(k16_req)
    k16_res['layout']['xyzMm'] = k16_res['layout']['xyzMm'][:16]
    k16_res['layout']['regionIndices'] = [0 if i < 6 else 1 for i in range(16)]
    validate_worker_result(k16_res, k16_req)
    with pytest.raises(RadiusResultError, match='^无效16点坐标$'):
        validate_worker_result({**k16_res, 'layout': {**k16_res['layout'], 'xyzMm': k16_res['layout']['xyzMm'][:15]}},
                               k16_req)


def _variant(change) -> dict:
    result = copy.deepcopy(result_for())
    change(result)
    return result


def _set(path: str, value):
    def change(result):
        *parents, last = path.split('.')
        target = result
        for part in parents:
            target = target[int(part)] if isinstance(target, list) else target[part]
        if isinstance(target, list):
            target[int(last)] = value
        else:
            target[last] = value
    return change


VALIDATOR_CASES = {
    'accepted': result_for(),
    'no-layout': {'status': 'no_layout', 'request': REQUEST, 'layout': None, 'metrics': None},
    'no-layout-scores': {'status': 'no_layout', 'request': REQUEST, 'layout': None, 'metrics': {}},
    'no-layout-undefined': {'status': 'no_layout', 'request': REQUEST},
    'failed': _variant(_set('status', 'failed')),
    'null': None,
    'request-unnormalized': _variant(_set('request', {**REQUEST, 'radius_mm': 35.0, 'mask_codes': ['PL', 'PR']})),
    'request-refused': _variant(_set('request', {**REQUEST, 'AR': 0.9})),
    'request-missing': _variant(lambda r: r.pop('request')),
    'layout-null': _variant(_set('layout', None)),
    'xyz-short': _variant(lambda r: r['layout'].update(xyzMm=r['layout']['xyzMm'][:63])),
    'xyz-string': _variant(_set('layout.xyzMm.3.0', '15')),
    'xyz-boolean': _variant(_set('layout.xyzMm.3.1', True)),
    'xyz-negative-zero': _variant(_set('layout.xyzMm.0.1', -0.0)),
    'reference-null': _variant(_set('layout.referenceXyzMm', None)),
    'labels-float': _variant(_set('layout.regionIndices.0', 0.5)),
    'labels-range': _variant(_set('layout.regionIndices.63', 2)),
    'labels-unbalanced': _variant(_set('layout.regionIndices.31', 1)),
    'geometry-null': _variant(_set('geometry', None)),
    'geometry-count-string': _variant(_set('geometry.union_connected_component_count', '2')),
    'radius-limit': _variant(_set('geometry.common_graph_radius_mm', 35 + 1e-7)),
    'radius-over': _variant(_set('geometry.common_graph_radius_mm', 35 + 2e-7)),
    'radius-zero': _variant(_set('geometry.common_graph_radius_mm', 0)),
    'area-negative': _variant(_set('geometry.union_area_cm2', -1)),
    'spacing': _variant(_set('layout.xyzMm.1', [3.99, 0.0, 0.0])),
    'spacing-limit': _variant(_set('layout.xyzMm.1', [4 - 1e-7, 0.0, 0.0])),
    'metrics-null': _variant(_set('metrics', None)),
    'metrics-string': _variant(_set('metrics.field_relative', '0.8')),
    'metrics-null-score': _variant(lambda r: r['metrics'].update(sensitivity_tail=None, conditional_global=None)),
    'metrics-null-score-g': _variant(_set('metrics.sensitivity_tail', None)),
    'metrics-missing-score': _variant(lambda r: r['metrics'].pop('localization_relative')),
    'g-tolerance': _variant(_set('metrics.conditional_global', 0.3 + 5e-11)),
    'g-outside': _variant(_set('metrics.conditional_global', 0.3 + 2e-10)),
}

VALIDATOR_DRIVER = r"""
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const [specPath, outPath] = process.argv.slice(2);
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
const { validateWorkerResult } = await import(pathToFileURL(`${spec.webapp}/server/local-compute-server.mjs`).href);
const out = {};
for (const [name, result] of Object.entries(spec.cases)) {
  try { validateWorkerResult(result, spec.request); out[name] = null; } catch (error) { out[name] = error.message; }
}
writeFileSync(outPath, JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_validator_messages_equal_node(tmp_path):
    driver, spec, out = tmp_path / 'validator.mjs', tmp_path / 'spec.json', tmp_path / 'out.json'
    driver.write_text(VALIDATOR_DRIVER, encoding='utf-8')
    spec.write_text(jsjson.stringify({'webapp': str(WEBAPP), 'request': REQUEST, 'cases': VALIDATOR_CASES}),
                    encoding='utf-8')
    subprocess.run(['node', str(driver), str(spec), str(out)], check=True, env=NODE_ENV)
    node = json.loads(out.read_text(encoding='utf-8'))
    python = {}
    for name, result in VALIDATOR_CASES.items():
        # Through the JSON text, as the worker's output and the stored records reach the validator.
        try:
            validate_worker_result(jsjson.parse(jsjson.stringify(result)), REQUEST)
            python[name] = None
        except ValueError as error:
            python[name] = str(error)
    assert python == node
    assert node['accepted'] is None and node['radius-limit'] is None and node['g-outside'] is not None


# --- Identity -----------------------------------------------------------------------------------------------------

def _code_root(tmp_path: Path) -> Path:
    root = tmp_path / 'root'
    root.mkdir()
    code_tree(root)
    forward_inputs(root)
    return root


def test_code_identity_lists_top_level_python_files_in_code_unit_order(tmp_path):
    root = _code_root(tmp_path)
    identity = code_identity(str(root))
    names = ['Z.py', 'a.py', 'b.py', 'ä.py', '\U0001F600.py', 'ｚ.py']
    assert list(identity) == [*CODE_FILES, *(f'src/compact_eeg/{name}' for name in names)]
    assert identity['src/compact_eeg/a.py'] == sha('a.py')
    assert identity['scripts/run_local_radius_compute.py'] == sha('worker')
    assert 'src/compact_eeg/notes.txt' not in identity and set(CODE_NAMES) - set(names) == {'notes.txt', 'cache.pyc'}


def test_code_identity_follows_links_and_fails_like_node(tmp_path):
    root = _code_root(tmp_path)
    outside = tmp_path / 'outside.py'
    outside.write_text('outside', encoding='utf-8')
    (root / 'src/compact_eeg/linked.py').symlink_to(outside)
    assert code_identity(str(root))['src/compact_eeg/linked.py'] == sha('outside')
    (root / 'src/compact_eeg/package.py').mkdir()
    with pytest.raises(OSError) as caught:
        code_identity(str(root))
    assert error_code(caught.value) == 'EISDIR'
    with pytest.raises(OSError) as caught:
        code_identity(str(tmp_path / 'missing'))
    assert error_code(caught.value) == 'ENOENT'


def test_radius_identity_adds_prior_files_and_runtime_only_when_present(tmp_path):
    root = _code_root(tmp_path)
    code = {'src/compact_eeg/a.py': sha('a.py')}
    plain = radius_identity(str(root), REQUEST, code, None)
    assert jsjson.stringify(plain) == jsjson.stringify(
        {'version': RADIUS_IDENTITY_VERSION, 'code': code, 'threads': 2})
    prior = radius_identity(str(root), {**REQUEST, 'data_prior': PRIOR}, code, {'python': 'x'})
    assert list(prior['code']) == [*code, *DATA_PRIOR_FILES]
    assert prior['code'][DATA_PRIOR_FILES[0]] == sha(DATA_PRIOR_FILES[0]) and prior['runtime'] == {'python': 'x'}
    assert 'runtime' not in radius_identity(str(root), REQUEST, code, '')
    cache = RadiusCache(str(root), 'python3', get_identity=lambda: code)
    identity, key = cache.identity_for(REQUEST)
    assert key == request_key(REQUEST, identity) == jsjson.sha256_hex({'request': REQUEST, 'identity': plain})


def test_read_cache_returns_the_canonical_request_or_a_miss(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    cache = RadiusCache(str(root), 'python3', get_identity=lambda: {})
    raw = {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface', 'mask_codes': []}
    canonical = {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface'}
    key = cache.identity_for(canonical)[1]
    result = radius_result(canonical, status='no_layout')
    write_cache(root, key, raw, result, '2026-01-01T00:00:00Z')
    stored = cache.read_cache(key)
    assert jsjson.stringify(stored['request']) == jsjson.stringify(canonical)
    assert stored['finished_at'] == '2026-01-01T00:00:00Z' and cache.read_cache(key, canonical) is not None
    assert cache.read_cache(key, {**canonical, 'radius_mm': 20}) is None
    write_cache(root, key, raw, {**result, 'metrics': {}}, None)
    assert cache.read_cache(key) is None  # no_layout with scores
    write(root, f'results/v2/local_app_jobs/{key}/cache.json', {'key': key, 'request': raw, 'result_sha256': sha('x')})
    assert cache.read_cache(key) is None  # no result
    write_cache(root, sha('other'), raw, result)
    other = root / f'results/v2/local_app_jobs/{sha("other")}'
    other.rename(root / f'results/v2/local_app_jobs/{sha("moved")}')
    assert cache.read_cache(sha('moved')) is None  # key mismatch
    if os.geteuid() != 0:
        path = root / f'results/v2/local_app_jobs/{key}/cache.json'
        path.chmod(0)
        with pytest.raises(PermissionError):
            cache.read_cache(key)


# --- RadiusService, HTTP lookup, and strict-area bundle checks (slice 4) ----------------------------------------

REAL_ROOT = os.environ.get('EEG_KEY_PARITY_ROOT')
real_root = pytest.mark.skipif(not REAL_ROOT, reason='set EEG_KEY_PARITY_ROOT to a checkout with results/v2')


@pytest.mark.data_bundle
@real_root
def test_all_30_actual_strict_area_records_have_one_entry_per_domain_area_r_and_preserved_metrics():
    """check-lab-workflow.mjs::all 30 actual strict-area records have exactly one entry per domain-area-R and
    preserved metrics."""
    from eeglayoutlab.jobs.library import Library
    from eeglayoutlab.jobs.runtime import runtime_config

    assert REAL_ROOT is not None
    data = Library(REAL_ROOT, runtime_config(REAL_ROOT)).list()
    strict_rows = [row for row in data['records'] if row['dataset_id'] == 'strict_area']
    assert len(strict_rows) == 30
    ids: set[str] = set()
    for domain in ('whole_scalp_free', 'low_hair_free'):
        for area in (60, 120, 180):
            rows = sorted(
                (r for r in strict_rows if r['mode'] == domain and r['area_cap_cm2'] == area),
                key=lambda r: r['region_count'],
            )
            assert [r['region_count'] for r in rows] == [1, 2, 3, 4, 6]
            for row in rows:
                ids.add(row['id'])
                assert row['geometry']['union_connected_component_count'] == row['region_count']
                metrics = row['metrics']
                assert metrics['conditional_global'] == min(
                    metrics['field_relative'], metrics['sensitivity_tail'], metrics['localization_relative'],
                )
                assert row['request'] is None
    assert len(ids) == 30


def test_queue_has_one_child_deduplicates_identical_in_flight_requests_and_records_progress(tmp_path):
    """check-local-compute.mjs::queue has one child, deduplicates identical in-flight requests and records progress."""
    from .test_worker import FakeChild

    root = _code_root(tmp_path)
    spawned: list[tuple[str, list[str], dict]] = []
    children: list[FakeChild] = []

    def spawn(exe: str, args: list[str], opts: dict) -> FakeChild:
        spawned.append((exe, args, opts))
        child = FakeChild(pid=9100 + len(children))
        children.append(child)
        return child

    service = RadiusService(str(root), python='python3', spawn_process=spawn, verify_inputs=lambda _: None)
    first = service.submit(REQUEST)
    assert len(children) == 1
    _, _, opts = spawned[0]
    assert opts['shell'] is False
    assert opts['env']['OPENBLAS_NUM_THREADS'] == '2'
    assert opts['env']['OMP_NUM_THREADS'] == '2'

    # Identical in-flight request deduplicates without spawning another child.
    dedup = service.submit({**REQUEST})
    assert dedup['job']['id'] == first['job']['id']
    assert len(children) == 1

    # Different request while busy reports busy with active_job.
    busy = service.submit({**REQUEST, 'radius_mm': 40})
    assert busy['busy'] is True
    assert busy['active_job']['id'] == first['job']['id']

    children[0].emit_stdout(
        jsjson.stringify({'type': 'progress', 'stage': 'searching', 'progress': 0.65, 'message': '正在搜索候选'}) + '\n'
    )
    mid = service.get(first['job']['id'])
    assert mid['progress'] == 0.65 and mid['stage'] == 'searching' and mid['message'] == '正在搜索候选'

    children[0].emit_stdout(jsjson.stringify({'type': 'result', 'result': result_for(REQUEST)}) + '\n')
    children[0].close(0, None)
    done = service.get(first['job']['id'])
    assert done['status'] == 'completed' and done['progress'] == 1
    assert done['cached'] is False and done['source'] == 'local_compute'


def test_disk_cache_survives_queue_restart_and_source_identity_invalidates_it(tmp_path):
    """check-local-compute.mjs::disk cache survives queue restart and source identity invalidates it."""
    from .test_worker import FakeChild

    root = _code_root(tmp_path)
    children: list[FakeChild] = []

    def spawn(*_) -> FakeChild:
        c = FakeChild(pid=9200 + len(children))
        children.append(c)
        return c

    first_service = RadiusService(str(root), python='python3', spawn_process=spawn, verify_inputs=lambda _: None)
    job = first_service.submit(REQUEST)['job']
    children[0].emit_stdout(jsjson.stringify({'type': 'result', 'result': result_for(REQUEST)}) + '\n')
    children[0].close(0, None)
    original_key = job['key']
    cache_file = root / f'results/v2/local_app_jobs/{original_key}/cache.json'
    original_bytes = cache_file.read_bytes()

    # Restart with unchanged code identity: lookup and submit hit disk cache without spawning.
    restarted = RadiusService(str(root), python='python3',
                              spawn_process=lambda *_: pytest.fail('must not spawn on cache hit'),
                              verify_inputs=lambda _: None)
    looked = restarted.lookup(REQUEST)
    assert looked['hit'] is True and looked['job']['cached'] is True and looked['job']['source'] == 'local_cache'
    replayed = restarted.submit(REQUEST)['job']
    assert replayed['cached'] is True and replayed['key'] == original_key
    assert cache_file.read_bytes() == original_bytes

    # Changing scientific source invalidates cache identity while keeping old cache untouched.
    (root / 'src/compact_eeg/a.py').write_text('updated_science = 2\n', encoding='utf-8')
    after_edit = RadiusService(str(root), python='python3', spawn_process=spawn, verify_inputs=lambda _: None)
    assert after_edit.lookup(REQUEST) == {'hit': False}
    new_job = after_edit.submit(REQUEST)['job']
    assert new_job['key'] != original_key
    assert len(children) == 2
    children[1].close(1, None)
    assert cache_file.read_bytes() == original_bytes


def test_lookup_http_endpoint_returns_a_miss_without_a_task_and_rejects_extra_query_fields(tmp_path):
    """check-local-data-library.mjs::lookup HTTP endpoint returns a miss without a task, and rejects extra query
    fields."""
    from .key_parity_support import require as req_pkg
    req_pkg('fastapi')
    req_pkg('httpx')
    from .service_support import loopback_client, make_app

    root = _code_root(tmp_path)
    (root / 'scripts').mkdir(parents=True, exist_ok=True)
    (root / 'scripts/run_local_radius_compute.py').write_text('worker', encoding='utf-8')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()

    app = make_app(root, workspace=workspace)
    try:
        client = loopback_client(app, csrf=True)
        miss = client.post('/api/local-compute/lookup', json=REQUEST)
        assert miss.status_code == 200 and miss.json() == {'hit': False}
        assert client.get('/api/community/status').json()['jobs'] == []
        assert not (root / 'results/v2/local_app_jobs').exists()

        bad_body = client.post('/api/local-compute/lookup', json={**REQUEST, 'AR': 0.9})
        assert bad_body.status_code == 400 and bad_body.json()['error'] == '配置含未支持字段'

        uid = '11111111-2222-3333-4444-555555555555'
        bad_query = client.get(f'/api/local-compute/jobs/{uid}?extra=1')
        assert bad_query.status_code == 400 and bad_query.json()['error'] == 'Unsupported task query.'
        bad_ann = client.get(f'/api/local-compute/jobs/{uid}?annotation_id=not-hex')
        assert bad_ann.status_code == 400 and bad_ann.json()['error'] == 'Invalid electrode name annotation.'

        # Populate a valid cache and verify lookup hits with cached=True and source='local_cache'.
        q = app.queue_routes.queue()
        radius = app.queue_routes._radius
        assert radius is not None
        _, key = radius.identity_for(REQUEST)
        write_cache(root, key, REQUEST, radius_result(REQUEST, status='no_layout'), '2026-10-01T00:00:00Z')
        hit = client.post('/api/local-compute/lookup', json=REQUEST)
        assert hit.status_code == 200
        payload = hit.json()
        assert payload['hit'] is True
        assert payload['job']['cached'] is True and payload['job']['source'] == 'local_cache'
        assert len(q.tasks) == 1
    finally:
        app.close()
