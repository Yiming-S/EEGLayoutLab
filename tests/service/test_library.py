"""The read-only local data library (``eeglayoutlab.jobs.library``) equals Node's ``LocalDataLibrary`` (phase 2
slice 3), and ports webapp/scripts/check-local-data-library.mjs.

- Parity: on synthetic roots (tests/service/library_support.py) Node's own queue and the Python library give the
  same ``list()`` document (records compared as a set, ``finished_at`` order separately: Node sorts labels with
  ``localeCompare``), the same ``get(id)`` text for every listed id and every record directory, the same
  ``identityFor`` of each radius request, and the same annotation reads and listings of Node's directory (Node's
  ``list(owner)`` of every owner against the owner-agnostic ``list()``). Failures compare by Node's code where the
  error has one, else by message.
- The ports of check-local-data-library.mjs use the fixture of that file: a queue with an empty code identity (no
  runtime member, no input check) and one stored ``no_layout`` record. The lookup and submit halves of those tests
  need the queue of slice 4; here their read side (``RadiusCache.read_cache``, the key, the request format).
- With ``EEG_KEY_PARITY_ROOT`` (marked ``data_bundle``) the checks of the dataTests run on that installation, and
  the parity comparison as well. Nothing is written under any root.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest

from schema_parity_support import require

require('pydantic')

from eeglayoutlab.jobs.annotations import AnnotationError, ElectrodeAnnotations  # noqa: E402
from eeglayoutlab.jobs.identity import IdentityError  # noqa: E402
from eeglayoutlab.jobs.integrity import InputIntegrity  # noqa: E402
from eeglayoutlab.jobs.library import (  # noqa: E402
    DATASETS, INPUT_WARNING, Library, LibraryError, area_records, validate_saved_record,
)
from eeglayoutlab.jobs.radius import RadiusCache, normalize_request  # noqa: E402
from eeglayoutlab.jobs.runtime import runtime_config  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402

from .key_parity_support import needs_node  # noqa: E402
from .library_support import (  # noqa: E402
    BROKEN, NODE_ANNOTATIONS, RADIUS_REQUESTS, annotation, annotations, broken_offline, code_tree, finished_order,
    forward_inputs, library_root, node_failure, python_entry, records_by_text, run_node, sha, write_annotation,
    write_cache,
)

REQUEST = {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface'}
NO_LAYOUT = {'status': 'no_layout', 'request': REQUEST, 'layout': None, 'metrics': None}
FINISHED = '2026-09-08T12:00:00Z'


def cached_fixture(tmp_path: Path):
    """``cachedFixture()``: a root with one stored ``no_layout`` record under an empty code identity."""
    root = tmp_path / 'eeg-library-test'
    root.mkdir()
    radius = RadiusCache(str(root), 'python3', get_identity=lambda: {})
    library = Library(str(root), runtime_config(str(root)), radius=radius)
    key = radius.identity_for(REQUEST)[1]
    file = write_cache(root, key, REQUEST, NO_LAYOUT, FINISHED)
    return library, radius, file, key


def snapshot(root: Path) -> dict:
    """Every path under ``root`` with its type, size and modification time (links not followed)."""
    state = {}
    for directory, names, files in os.walk(root):
        for name in names + files:
            info = os.lstat(os.path.join(directory, name))
            state[os.path.join(directory, name)] = (info.st_mode, info.st_size, info.st_mtime_ns)
    return state


# --- check-local-data-library.mjs ----------------------------------------------------------------------------------

def test_existing_cache_has_history_after_restart(tmp_path):
    """:83, without the lookup (slice 4): a stored record lists as compatible; it answers its own request only."""
    library, radius, _, key = cached_fixture(tmp_path)
    listed = library.list()
    row = next(row for row in listed['records'] if row['id'] == key)
    assert row['compatible'] is True and row['status'] == 'no_layout' and row['metrics'] is None
    assert row['label'] == '1区 · 全头 · 半径≤15 mm' and row['finished_at'] == FINISHED
    assert jsjson.stringify(row) == jsjson.stringify({
        'id': key, 'dataset_id': 'cache', 'status': 'no_layout', 'label': '1区 · 全头 · 半径≤15 mm',
        'region_count': 1, 'radius_cap_mm': 15, 'mode': 'whole_surface', 'spacing_mm': 4, 'compatible': True,
        'request': REQUEST, 'finished_at': FINISHED, 'metrics': None, 'geometry': None})
    assert radius.read_cache(key, normalize_request(REQUEST))['result'] == NO_LAYOUT
    other = normalize_request({**REQUEST, 'radius_mm': 20})
    assert radius.read_cache(radius.identity_for(other)[1], other) is None
    assert radius.read_cache(key, other) is None


def test_historical_algorithm_data_stays_readable_but_cannot_resume(tmp_path):
    """:93: after a code change the record still opens, with its parameters, but is not a current result."""
    library, radius, _, key = cached_fixture(tmp_path)
    radius.get_identity = lambda: {'changed': True}
    record = library.get(key)
    assert record['compatible'] is False and record['request'] == REQUEST
    assert record['provenance']['file'] == f'results/v2/local_app_jobs/{key}/cache.json'
    assert radius.identity_for(REQUEST)[1] != key  # the lookup of slice 4 misses


def test_cached_result_is_served_without_touching_the_store(tmp_path):
    """:102, read side: serving a stored result needs no queue state and changes nothing on disk (the busy queue
    of the Node test is slice 4)."""
    library, radius, file, key = cached_fixture(tmp_path)
    before = snapshot(tmp_path)
    assert radius.read_cache(key, REQUEST)['finished_at'] == FINISHED
    assert library.get(key)['compatible'] is True
    assert library.list()['records'][0]['id'] == key
    assert snapshot(tmp_path) == before


def test_invalid_checksum_and_malformed_records_are_misses(tmp_path):
    """:111: a record whose result no longer matches its checksum, or that is not JSON, is never a hit."""
    library, radius, file, key = cached_fixture(tmp_path)
    cache = jsjson.parse(file.read_text(encoding='utf-8'))
    cache['result']['status'] = 'completed'
    file.write_text(jsjson.stringify(cache), encoding='utf-8')
    assert radius.read_cache(key, REQUEST) is None
    listed = library.list()
    assert listed['records'] == []
    assert listed['warnings'][-1] == '一条计算缓存未载入：缓存完整性校验未通过'
    file.write_text('{broken', encoding='utf-8')
    assert radius.read_cache(key, REQUEST) is None
    assert library.list()['records'] == [] and library.get(key) is None


def test_lookup_bodies_hit_miss_or_are_refused_before_any_read(tmp_path):
    """:121, without the endpoint (slice 4): the stored request reads its record, another radius reads nothing,
    and a body with an extra field is refused by the request format, before any key or file."""
    _, radius, _, key = cached_fixture(tmp_path)
    for body, hit in ((REQUEST, True), ({**REQUEST, 'radius_mm': 20}, False)):
        request = normalize_request(body)
        assert (radius.read_cache(radius.identity_for(request)[1], request) is not None) is hit
    with pytest.raises(ValueError):
        normalize_request({**REQUEST, 'AR': 0.9})


def test_input_byte_changes_invalidate_memoized_sha(tmp_path):
    """:134."""
    file = tmp_path / 'bank.npz'
    file.write_bytes(b'abc')
    inputs = InputIntegrity(str(tmp_path))
    first = inputs.digest('bank.npz')
    assert first == sha('abc')
    assert inputs.digest('bank.npz') == first
    file.write_bytes(b'xyz')
    assert inputs.digest('bank.npz') != first
    with pytest.raises((OSError, IdentityError)):
        inputs.digest('../../etc/passwd')


def test_failed_input_identity_blocks_cached_reuse(tmp_path):
    """:144, read side: a record whose forward inputs changed is not compatible, with Node's warning."""
    library, radius, _, key = cached_fixture(tmp_path)

    def changed(result):
        raise IdentityError('changed input')

    radius.verify_inputs = changed
    listed = library.list()
    assert listed['records'][0]['compatible'] is False
    assert listed['warnings'][-1] == INPUT_WARNING
    assert library.get(key)['compatible'] is False


def test_library_only_returns_allowlisted_opaque_ids(tmp_path):
    """:151."""
    library, *_ = cached_fixture(tmp_path)
    for id in ('../cache.json', '/etc/passwd', 'a' * 64, 'A' * 64, '', None, 5, ['a' * 64]):
        assert library.get(id) is None


# --- Python behaviour -------------------------------------------------------------------------------------------

def test_list_orders_by_finished_at_then_label_code_units(tmp_path):
    library, radius, _, key = cached_fixture(tmp_path)
    root = tmp_path / 'eeg-library-test'
    for request, finished in (({**REQUEST, 'radius_mm': 20}, None), ({**REQUEST, 'radius_mm': 25}, FINISHED),
                              ({**REQUEST, 'mode': 'low_hair'}, '2026-09-09T00:00:00Z')):
        write_cache(root, radius.identity_for(request)[1], request, {**NO_LAYOUT, 'request': request}, finished)
    labels = [(row.get('finished_at'), row['label']) for row in library.list()['records']]
    assert labels == [('2026-09-09T00:00:00Z', '1区 · 低毛发代理 · 半径≤15 mm'), (FINISHED, '1区 · 全头 · 半径≤15 mm'),
                      (FINISHED, '1区 · 全头 · 半径≤25 mm'), (None, '1区 · 全头 · 半径≤20 mm')]


def test_records_reload_when_their_file_changes(tmp_path):
    library, radius, file, key = cached_fixture(tmp_path)
    assert library.list()['records'][0]['finished_at'] == FINISHED
    write_cache(tmp_path / 'eeg-library-test', key, REQUEST, NO_LAYOUT, '2026-12-31T00:00:00.000Z')
    assert library.list()['records'][0]['finished_at'] == '2026-12-31T00:00:00.000Z'
    file.unlink()
    assert library.list()['records'] == [] and library.get(key) is None


def test_a_root_without_radius_code_fails_like_node(tmp_path):
    """Node reads the code identity on every refresh; without ``src/compact_eeg`` the listing rejects."""
    root = tmp_path / 'empty'
    root.mkdir()
    library = Library(str(root), runtime_config(str(root)))
    with pytest.raises(FileNotFoundError):
        library.list()
    code_tree(root)
    with pytest.raises(FileNotFoundError):
        library.list()  # the bank pointer is a code file
    forward_inputs(root)
    listed = library.list()
    assert listed['records'] == []
    assert listed['warnings'] == [f"{dataset['label']}：数据未提供" for dataset in reversed(DATASETS[2:])]
    assert [dataset['count'] for dataset in listed['datasets']] == [0] * 5


def test_validate_saved_record_messages():
    record = {'status': 'completed', 'region_count': 2, 'dataset_id': 'strict_area',
              'layout': {'xyzMm': [[i * 5.0, 0.0, 0.0] for i in range(64)],
                         'referenceXyzMm': [[i * 5.0, 1.0, 0.0] for i in range(64)],
                         'regionIndices': [i % 2 for i in range(64)]},
              'metrics': {'field_relative': 0.8, 'sensitivity_tail': 0.3, 'localization_relative': 0.5,
                          'conditional_global': 0.3},
              'geometry': {'union_connected_component_count': 2}}
    assert validate_saved_record(record) is record

    def fails(change, message):
        copy_ = copy.deepcopy(record)
        change(copy_)
        with pytest.raises(LibraryError, match=f'^{message}$'):
            validate_saved_record(copy_)

    fails(lambda r: r.update(status='failed'), '无效记录状态')
    fails(lambda r: r.update(status='no_layout'), '缺失布局带有分数')
    fails(lambda r: r['layout']['xyzMm'].__setitem__(1, [0.0, 0.0, 0.0]), '记录坐标与区域标签无效')
    fails(lambda r: r['layout'].__setitem__('regionIndices', [0] * 64), '记录坐标与区域标签无效')
    fails(lambda r: r['metrics'].update(field_relative='0.8'), '无效保留率')
    fails(lambda r: r['metrics'].update(conditional_global=0.31), '保留率最小值不一致')
    fails(lambda r: r['geometry'].update(union_connected_component_count=1), '面积实验连通数不符')
    fails(lambda r: r['layout'].update(regionPatchVertexIndices=[[1, 2], [3, 52410]], regionAreasCm2=[1, 2]),
          '保存的区域面片或面积无效')
    fails(lambda r: r.update(provenance={'surface_status': 'external_exposure_screened'}), '新版面积记录缺少原生区域面片')
    assert validate_saved_record({**record, 'metrics': {**record['metrics'], 'sensitivity_tail': None,
                                                        'conditional_global': None}})


def test_workspace_annotations_come_first_and_ignore_the_owner(tmp_path):
    root, workspace = tmp_path / 'root', tmp_path / 'W/annotations/electrode-names'
    record_id = sha('record')
    node_dir = root / NODE_ANNOTATIONS
    shared = annotation('browser-a', record_id)
    own = annotation('local', record_id, [f'W{i}' for i in range(64)])
    write_annotation(node_dir, shared)
    write_annotation(node_dir, annotation('browser-b', sha('other')))
    write_annotation(workspace, own)
    write_annotation(workspace, shared)
    store = ElectrodeAnnotations.local(str(workspace), str(root))
    assert store.read(own['id'], record_id)['electrode_names'][0] == 'W0'
    assert store.read(shared['id'], record_id)['id'] == shared['id']
    assert 'owner' not in store.read(shared['id'], record_id)
    with pytest.raises(AnnotationError) as caught:
        store.read(shared['id'], sha('other'))
    assert caught.value.status == 404
    assert sorted(value['id'] for value in store.list()) == sorted(
        [own['id'], shared['id'], annotation('browser-b', sha('other'))['id']])
    library = Library(str(root), runtime_config(str(root)), str(workspace))
    assert library.annotations.read(own['id'], record_id)['record_id'] == record_id


def test_a_linked_annotation_directory_is_unavailable(tmp_path):
    root, target = tmp_path / 'root', tmp_path / 'elsewhere'
    target.mkdir()
    (root / 'results/v2/design_evaluation_jobs').mkdir(parents=True)
    (root / NODE_ANNOTATIONS).symlink_to(target)
    store = ElectrodeAnnotations.local(None, str(root))
    with pytest.raises(AnnotationError) as caught:
        store.list()
    assert (caught.value.status, str(caught.value)) == (409, 'Electrode name storage is unavailable.')
    missing = ElectrodeAnnotations.local(str(tmp_path / 'W/annotations/electrode-names'), str(tmp_path / 'none'))
    assert missing.list() == []


# --- Parity with Node -------------------------------------------------------------------------------------------

EXTRA_IDS = ['a' * 64, 'A' * 64, '../cache.json', '/etc/passwd']


def _item(id: str, root: Path, keys: dict, annotation_reads: list, owners: list) -> dict:
    ids = [*EXTRA_IDS, *keys.get('radius', {}).values(), *keys.get('design', {}).values()]
    item = {'id': id, 'root': str(root), 'ids': ids,
            'requests': {**RADIUS_REQUESTS, 'empty': {}, 'null': None}}
    if annotation_reads or owners:
        item['annotations'] = {'reads': annotation_reads, 'owners': owners}
    return item


@pytest.fixture(scope='session')
def parity(tmp_path_factory):
    base = tmp_path_factory.mktemp('library-parity')
    python = runtime_config(str(base)).python
    items = []
    keys = library_root(base / 'base', python)
    record = keys['design']['default']
    good = annotations(base / 'base', record)
    reads = [[good['first']['id'], 'browser-a', record], [good['second']['id'], 'browser-b', record],
             [good['first']['id'], 'browser-a', sha('other')], [sha('none'), 'browser-a', record]]
    items.append(_item('base', base / 'base', keys, reads, ['browser-a', 'browser-b', 'nobody']))
    (base / 'symlinked').symlink_to(base / 'base')
    items.append(_item('symlinked', base / 'symlinked', keys, reads, ['browser-a', 'browser-b']))
    (base / 'outside.py').write_text('outside the root', encoding='utf-8')
    linked = library_root(base / 'linked-code', python, linked=base / 'outside.py')
    items.append(_item('linked-code', base / 'linked-code', linked, [], []))
    (base / 'bare').mkdir()
    items.append(_item('bare', base / 'bare', {}, [], []))
    (base / 'minimal').mkdir()
    code_tree(base / 'minimal')
    forward_inputs(base / 'minimal')
    items.append(_item('minimal', base / 'minimal', {}, [], []))
    for kind in BROKEN:
        broken_offline(base / f'broken-{kind}', kind)
        items.append(_item(f'broken-{kind}', base / f'broken-{kind}', {}, [], []))
    bad = annotations(base / 'broken-paths', record, broken=True)
    items[-len(BROKEN)]['annotations'] = {
        'reads': [[bad['tampered']['id'], 'browser-a', record], [bad['invalid']['id'], 'browser-c', record]],
        'owners': ['browser-a']}
    before = snapshot(base)
    node = run_node(items, tmp_path_factory.mktemp('library-node'))
    python_entries = {item['id']: python_entry(item) for item in items}
    assert snapshot(base) == before
    return {item['id']: item for item in items}, node, python_entries


ROOT_IDS = ['base', 'symlinked', 'linked-code', 'bare', 'minimal', *(f'broken-{kind}' for kind in BROKEN)]


def assert_same_entry(item: dict, node: dict, python: dict) -> None:
    assert (python['root'], python['python']) == (node['root'], node['python'])
    if node['list']['ok']:
        assert python['list']['ok'], python['list']
        assert records_by_text(python['list']['value']) == records_by_text(node['list']['value'])
        assert finished_order(python['list']['value']) == finished_order(node['list']['value'])
    else:
        assert python['list'] == node_failure(node['list'])
    assert set(python['get']) == set(node['get'])
    for id, result in node['get'].items():
        assert python['get'][id] == node_failure(result), id
    for name, result in node['identity'].items():
        assert python['identity'][name] == node_failure(result), name
    if 'annotations' in item:
        reads = node['annotations']['reads']
        assert python['annotations']['reads'] == [node_failure(result) for result in reads]
        lists = [node_failure(result) for result in node['annotations']['lists']]
        if all(result['ok'] for result in lists):
            assert python['annotations']['list']['ok']
            texts = sorted(text for result in lists for text in result['value'])
            assert sorted(python['annotations']['list']['value']) == texts
        else:
            assert python['annotations']['list'] == next(result for result in lists if not result['ok'])


@needs_node
@pytest.mark.parametrize('root', ROOT_IDS)
def test_library_parity(root, parity):
    items, node, python = parity
    assert_same_entry(items[root], node[root], python[root])


@needs_node
def test_library_parity_covers_each_record_kind(parity):
    """The synthetic roots reach what the comparison is for: every dataset, both ``compatible`` values, each
    evaluation condition, robustness, Node's warnings, and the area rejection of a linked root."""
    items, node, _ = parity
    listed = jsjson.parse(node['base']['list']['value'])
    counts = {dataset['id']: dataset['count'] for dataset in listed['datasets']}
    assert counts == {'design_evaluation': 6, 'cache': 9, 'strict_area': 30, 'historical_area': 30,
                      'offline_radius': 10}
    cache = {row['id']: row['compatible'] for row in listed['records'] if row['dataset_id'] == 'cache'}
    assert sorted(cache.values()) == [False] * 3 + [True] * 6
    conditions = [row.get('evaluation_condition') for row in listed['records']
                  if row['dataset_id'] == 'design_evaluation']
    assert sorted(next(iter(c)) for c in conditions if c) == [
        'conductivity_scenario', 'data_prior', 'head_id', 'noise_model']
    assert any('robustness' in row for row in listed['records'])
    assert INPUT_WARNING in listed['warnings'] and '一条坐标评价记录未载入：设计记录身份校验失败' in listed['warnings']
    unreadable = any(warning.startswith('一条计算缓存未载入：EACCES') for warning in listed['warnings'])
    assert unreadable == (os.geteuid() != 0)
    linked = jsjson.parse(node['symlinked']['list']['value'])
    assert [w for w in linked['warnings'] if '报告路径或身份无效' in w] == [
        '历史面积实验 · 原坐标范围：报告路径或身份无效', '外部曝光筛选 · 30面积布局：报告路径或身份无效']
    assert node['bare']['list']['code'] == 'ENOENT'
    broken = [w for kind in BROKEN for w in jsjson.parse(node[f'broken-{kind}']['list']['value'])['warnings']]
    assert len(broken) == 3 * len(BROKEN)


# --- The real installation (EEG_KEY_PARITY_ROOT) ----------------------------------------------------------------

REAL_ROOT = os.environ.get('EEG_KEY_PARITY_ROOT')
real_root = pytest.mark.skipif(not REAL_ROOT, reason='set EEG_KEY_PARITY_ROOT to a checkout with results/v2')


@pytest.fixture(scope='module')
def real_library():
    return Library(REAL_ROOT, runtime_config(REAL_ROOT))


def _read_json(path: Path):
    return jsjson.parse(path.read_bytes().decode('utf-8'))


@pytest.mark.data_bundle
@real_root
def test_all_offline_layouts_load_read_only_with_original_metric_values(real_library):
    """:29 (designLink stays in Node)."""
    root = Path(REAL_ROOT)
    library = real_library.list()
    assert library['warnings'] == []
    counts = {dataset['id']: dataset['count'] for dataset in library['datasets']}
    assert (counts['offline_radius'], counts['strict_area']) == (342, 30)
    radius = _read_json(root / 'webapp/public/data/single_head_optimization.json')
    pointer = _read_json(root / 'results/v2/current_strict_area_budget_study.json')
    data = (root / pointer['report']).read_bytes()
    assert sha(data) == pointer['sha256']
    area = jsjson.parse(data.decode('utf-8'))
    historical = _read_json(root / _read_json(root / 'results/v2/historical_strict_area_budget_study.json')['report'])
    for row in library['records']:
        if row['dataset_id'] not in ('offline_radius', 'strict_area', 'historical_area'):
            continue
        record = real_library.get(row['id'])
        validate_saved_record(record)
        assert record['compatible'] is False and record['request'] is None
        if row['dataset_id'] == 'offline_radius':
            c = next(c for c in radius['conditions'] if c['id'] == record['provenance']['condition_id'])
            v = next(v for v in c['variants'] if v['id'] == record['layout']['id'])
            assert record['layout']['xyzMm'] == v['xyz_mm'] and record['layout']['regionIndices'] == v['region_indices']
            assert record['metrics']['conditional_global'] == next(
                m for m in v['conditions'] if m['snr_db'] == 20)['conditional_global']
        else:
            original = historical if row['dataset_id'] == 'historical_area' else area
            c = next(c for c in original['conditions'] if c['condition']['id'] == record['provenance']['condition_id'])
            f = next(f for f in c['finalists'] if f['objective'] == 'min_field_sensitivity20')
            assert record['layout']['xyzMm'] == f['final']['xyz_mm']
            assert record['layout']['regionIndices'] == f['final']['region_indices']
            assert record['metrics']['field_relative'] == f['evaluation']['field20']
            assert record['metrics']['reference_median_mm'] == original['baseline']['localization']['median_error_mm']
            assert record['provenance']['reevaluation_512_sources'] is False


@pytest.mark.data_bundle
@real_root
def test_coordinate_evaluations_reopen_their_original_evaluated_coordinates(real_library):
    """:65."""
    library = real_library.list()
    summaries = [row for row in library['records'] if row['dataset_id'] == 'design_evaluation']
    assert next(d for d in library['datasets'] if d['id'] == 'design_evaluation')['count'] == len(summaries)
    for summary in summaries:
        record = real_library.get(summary['id'])
        cache = _read_json(Path(REAL_ROOT) / 'results/v2/design_evaluation_jobs' / summary['id'] / 'cache.json')
        assert cache['result']['request']['action'] == 'evaluate'
        assert record['label'] == cache['result']['request']['design']['name']
        assert record['layout']['xyzMm'] == cache['result']['evaluated_xyz_mm']
        assert record['layout']['regionIndices'] == cache['result']['request']['design']['region_indices']
        assert record['metrics']['field_relative'] == cache['result']['nominal']['field_relative']
        assert len(record['layout']['xyzMm']) == 64


@pytest.mark.data_bundle
@real_root
def test_area_importer_rejects_changed_scientific_protocols():
    """:158."""
    root = Path(REAL_ROOT)
    report = _read_json(root / _read_json(root / 'results/v2/current_strict_area_budget_study.json')['report'])
    changes = (lambda r: r.update(schema_version='new-version'),
               lambda r: r['config'].update(spacing_mm=2),
               lambda r: r['config']['evaluation'].update(snr_db=10),
               lambda r: r['baseline']['localization'].update(generation_source_count=512))
    assert len(area_records(report, {'file': 'x', 'sha256': 'y'})) == 30
    for change in changes:
        changed = copy.deepcopy(report)
        change(changed)
        with pytest.raises(LibraryError):
            area_records(changed, {})


@pytest.mark.data_bundle
@real_root
@needs_node
def test_real_root_library_parity(tmp_path):
    """Every record of the installation, as Node lists and gets it: the parent-digest inputs (plan B13)."""
    before = snapshot(Path(REAL_ROOT) / 'results/v2')
    item = {'id': 'real', 'root': REAL_ROOT, 'ids': EXTRA_IDS, 'requests': dict(RADIUS_REQUESTS)}
    node = run_node([item], tmp_path)['real']
    python = python_entry(item)
    assert_same_entry(item, node, python)
    assert len(node['get']) > 400
    assert snapshot(Path(REAL_ROOT) / 'results/v2') == before
