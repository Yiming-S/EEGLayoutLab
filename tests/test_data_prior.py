"""Data-prior fit on synthetic fields: recovery, cross-validated shrinkage, request form and weights."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from compact_eeg.workflows import data_prior as dp
from compact_eeg.workflows import eeg_recording as er

POSITIONS = json.loads((ROOT / er.MAPPING_PATH).read_text())['labels']['positions_mm']
NAMES = [p[0] for p in POSITIONS[:85:3]]
XYZ = np.array([p[1:] for p in POSITIONS[:85:3]], dtype=float)


def synthetic(seed=0, sources=700):
    rng = np.random.default_rng(seed)
    field = rng.normal(size=(len(NAMES), sources))
    groups = np.arange(sources) % len(dp.REGIONS)
    weights = rng.uniform(.5, 1.5, sources)
    return field, groups, weights


def covariance(model, gains, correlated=.2, length=20, channel=None, scale=1.):
    channel = np.full(model.size, .02) if channel is None else channel
    signal = sum(g * b for g, b in zip(gains, model.blocks))
    return scale * signal + correlated * model.correlated(length) + model.centring @ np.diag(channel) @ model.centring


def test_an_exact_model_covariance_is_recovered():
    field, groups, weights = synthetic()
    model = dp.Model(field, XYZ, weights, groups)
    true = np.array([2., 1., .5, 1.5, .8, .8, .3])
    channel = np.random.default_rng(1).uniform(.01, .05, model.size)
    fit = model.fit(covariance(model, true, channel=channel))
    expected = true / (true @ model.area / model.area.sum())
    assert fit['residual'] < 1e-6
    assert np.allclose(fit['gains'], expected, rtol=1e-4)
    assert fit['length_mm'] == 20 and fit['rho'] == round(.2 / (.2 + channel.mean()), 2)
    # The area prior cannot represent unequal regions.
    assert fit['uniform']['residual'] > 10 * fit['residual']


def test_gains_are_bounded_relative_to_the_area_prior_scale():
    field, groups, weights = synthetic(seed=2)
    model = dp.Model(field, XYZ, weights, groups)
    fit = model.fit(covariance(model, [50., 1, 1, 1, 1, 1, .001], correlated=0))
    ratio = fit['coefficients'] / fit['uniform']['scale']
    assert ratio.max() <= dp.GAIN_BOUNDS[1] + 1e-9 and ratio.min() >= dp.GAIN_BOUNDS[0] - 1e-9


def summaries_from(model, gains_list, rng):
    out = []
    for i, gains in enumerate(gains_list):
        c = covariance(model, gains, channel=rng.uniform(.01, .06, model.size), scale=rng.uniform(.5, 2))
        c = c + model.centring @ np.diag(rng.uniform(0, .01, model.size)) @ model.centring
        out.append({'schema': er.SUMMARY_SCHEMA, 'label': f's{i}', 'mapping_id': er.cap_lookup(ROOT)[2], 'channels': NAMES,
                    'xyz_mm': XYZ.tolist(), 'covariance': c.tolist(), 'processing': {'band_hz': [8., 30.]},
                    'source': {'file': f's{i}.edf', 'sha256': '0' * 64}, 'epochs': {'used': 100}})
    return out


@pytest.fixture
def fake_fields(monkeypatch):
    field, groups, weights = synthetic(seed=4)
    data = {'source_area_weights': weights, 'dictionary_source_count': field.shape[1]}
    table = type('Table', (), {'table_id': 'synthetic'})()
    monkeypatch.setattr(dp, 'channel_fields', lambda root, xyz: (data, {'sha256': 'b' * 64}, table, field, np.ones(len(xyz), bool), np.zeros(len(xyz))))
    monkeypatch.setattr(dp, 'atlas_groups', lambda root, data: (groups, None))
    return dp.Model(field, XYZ, weights, groups)


def test_shared_regional_structure_survives_cross_validation(fake_fields):
    rng = np.random.default_rng(5)
    true = np.array([3., 1., .4, 2., .7, .7, .3])
    summaries = summaries_from(fake_fields, [true * rng.uniform(.9, 1.1, 7) for _ in range(5)], rng)
    summaries[0]['source']['recording_sha256'] = 'a' * 64
    prior = dp.fit(summaries, ROOT)
    held = prior['fit']['held_out']
    assert prior['fit']['cross_validated'] and held['selected_shrinkage'] == 1. and held['prior_better_count'] == 5
    expected = true / (true @ fake_fields.area / fake_fields.area.sum())
    assert np.allclose(prior['request']['region_gain'], expected, rtol=.1)
    assert prior['request']['length_mm'] == 20 and prior['id'] == dp.prior_id(prior['request'])
    assert np.isclose(np.trace(np.array(prior['channel_model']['data_prior'])), 1, atol=1e-5)
    assert len(prior['fit']['per_summary']) == 5
    assert prior['inputs'][0]['recording_sha256'] == 'a' * 64
    assert prior['inputs'][0]['sha256'] == '0' * 64
    assert 'recording_sha256' not in prior['inputs'][1]


def test_unshared_regional_structure_is_shrunk_toward_the_area_prior(fake_fields):
    rng = np.random.default_rng(6)
    gains = [np.exp(rng.normal(scale=1.2, size=7)) for _ in range(6)]
    prior = dp.fit(summaries_from(fake_fields, gains, rng), ROOT)
    assert prior['fit']['held_out']['selected_shrinkage'] < 1.
    single = dp.fit(summaries_from(fake_fields, gains[:2], rng), ROOT)
    assert single['fit']['cross_validated'] is False and single['fit']['shrinkage'] == 1.


def test_fit_rejects_mixed_bands_and_too_few_channels(fake_fields):
    rng = np.random.default_rng(7)
    a, b = summaries_from(fake_fields, [np.ones(7), np.ones(7)], rng)
    b['processing']['band_hz'] = [1., 40.]
    with pytest.raises(ValueError, match='频带'):
        dp.fit([a, b], ROOT)
    small = {**a, 'channels': NAMES[:10], 'xyz_mm': XYZ[:10].tolist(),
             'covariance': (np.eye(10) - 1 / 10).tolist()}
    with pytest.raises(ValueError, match='少于'):
        dp.fit([small], ROOT)
    # Each summary misses a different channel: every channel is in 90% of them, but no summary has all.
    gapped = []
    for k in range(10):
        keep = [i for i in range(len(NAMES)) if i != k]
        c = np.asarray(a['covariance'])[np.ix_(keep, keep)]
        c = c - c.mean(axis=0) - c.mean(axis=1)[:, None] + c.mean()
        gapped.append({**a, 'label': f'g{k}', 'channels': [NAMES[i] for i in keep], 'xyz_mm': XYZ[keep].tolist(), 'covariance': c.tolist()})
    with pytest.raises(ValueError, match='没有一份摘要包含全部'):
        dp.fit(gapped, ROOT)


def test_request_form():
    value = {'region_gain': [1.5, 1., .75, 2., 1., 1., .3], 'rho': .25, 'length_mm': 20}
    assert dp.canonical(value) == value
    assert dp.kernel(value) == (.25, 20) and dp.noise_model(value)['rho'] == .25
    assert dp.kernel({**value, 'rho': 0., 'length_mm': None}) is None
    for change in ({'region_gain': [1.] * 6}, {'region_gain': [1.23456] + [1.] * 6}, {'region_gain': [0.] + [1.] * 6},
                   {'rho': .255}, {'rho': .99}, {'rho': 0., 'length_mm': 20}, {'length_mm': 25}, {'length_mm': None}):
        with pytest.raises(ValueError):
            dp.canonical({**value, **change})
    with pytest.raises(ValueError):
        dp.canonical({**value, 'extra': 1})
    assert dp.prior_id(value) != dp.prior_id({**value, 'rho': .3})


def test_prior_weights_follow_the_atlas_regions():
    atlas = json.loads((ROOT / dp.ATLAS_PATH).read_text())
    data = {'source_xyz_mm': np.zeros((len(atlas['dictionary_roi_indices']), 3)),
            'generation_xyz_mm': np.array([s['xyz_mm'] for s in atlas['generation_sources']]),
            'source_area_weights': np.ones(len(atlas['dictionary_roi_indices'])), 'generation_area_weights': np.ones(len(atlas['generation_sources']))}
    gains = [2., 3., 4., 5., 6., 7., .5]
    weights, generation = dp.apply(ROOT, data, {'region_gain': gains, 'rho': 0., 'length_mm': None})
    roi = np.asarray(atlas['dictionary_roi_indices'])
    assert np.all(weights[roi == 0] == .5) and np.all(weights[roi == 4] == 5.)
    names = [s['roi_id'] for s in atlas['generation_sources']]
    assert generation[names.index('temporal_right')] == 7. and generation[names.index(None)] == .5
    with pytest.raises(ValueError, match='图谱'):
        dp.atlas_groups(ROOT, {**data, 'generation_xyz_mm': data['generation_xyz_mm'] + 1})


def test_requests_carry_a_prior_instead_of_a_noise_model():
    from compact_eeg.local_radius_compute import search_seed, validate_request as radius_request
    from compact_eeg.workflows import design_evaluation as de
    prior = {'region_gain': [1.037, 2.829, .09946, 1.344, .4122, 1.072, .09946], 'rho': .2, 'length_mm': 20}
    spatial = {'kind': 'spatial', 'rho': .5, 'length_mm': 20}
    base = radius_request({'region_count': 2, 'radius_mm': 30, 'mode': 'whole_surface'})
    assert radius_request({**base, 'data_prior': prior})['data_prior'] == prior
    # The prior changes the scores, not the candidate search itself.
    assert search_seed(radius_request({**base, 'data_prior': prior})) == search_seed(base)
    design = {'action': 'evaluate', 'radius_mm': 6, 'seed': 42, 'design': {
        'schema': 'eeg-electrode-design/1', 'coordinate_system': 'ernie_native_mm', 'unit': 'mm', 'name': 'fixture',
        'xyz_mm': [[float(i % 8 * 6), float(i // 8 * 6), 0.] for i in range(64)], 'region_indices': [0] * 32 + [1] * 32}}
    assert de.validate_request({**design, 'data_prior': prior})['data_prior'] == prior
    for bad in ({'data_prior': prior, 'noise_model': spatial}, {'data_prior': {**prior, 'rho': .255}}, {'data_prior': prior, 'head_id': 'ixi002'}):
        with pytest.raises(ValueError):
            de.validate_request({**design, **bad})
    for bad in ({'data_prior': prior, 'noise_model': spatial}, {'data_prior': {**prior, 'length_mm': 25}}):
        with pytest.raises(ValueError):
            radius_request({**base, **bad})
