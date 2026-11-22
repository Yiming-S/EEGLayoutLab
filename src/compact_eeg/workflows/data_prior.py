"""Data-derived source prior and electrode-noise structure (``eeg-data-prior/1``).

Recorded covariances (``eeg-covariance-summary/1``, average reference) are modelled at the
recorded channels' Ernie cap positions as

    C ~ P [ sum_r a_r H_r diag(w_r) H_r' + c G_L + diag(d) ] P,

with H the scalp-node-table fields of the 4096 dictionary sources, w their cortical-area
weights, r the six atlas ROIs plus the unassigned sources ('other'), G_L the Gaussian
correlation exp(-d^2 / 2L^2) between electrodes, d one nonnegative noise variance per channel
and P the average-reference projector. The per-channel variances absorb contact noise and
local artifacts, which differ several-fold between channels of real recordings, so the region
coefficients follow the shared (between-channel) covariance structure.

For each L on a fixed grid (and without the correlated term) the coefficients minimise the
Frobenius residual of the trace-normalised covariance: first one common signal scale s0 (the
area prior), then one coefficient per region bounded to [0.1, 10] s0, so a region the montage
barely sees is neither removed nor allowed to dominate. The L with the smallest regional residual
is the fit. Region gains are a_r divided by their area-weighted mean. The noise becomes the
evaluation's unit-diagonal model ``(1-rho) I + rho G_L`` with rho = c / (c + mean d).

Region gains from a few dozen channels are noisy, so they are shrunk toward the area prior,
g_t = 1 + t (g - 1), with t chosen by leave-one-out over the summaries (three or more): each one is
held out in turn, the prior is fitted to the others, and for every t on a fixed grid the region
pattern and L are kept while the signal scale, the correlated noise and the per-channel noise
are refitted to the held-out covariance. The t with the smallest mean held-out residual is used;
t = 0 means the data do not support regional differences and the prior keeps the area weights
(with the area prior's own best L). With fewer summaries t = 1 and the fit is flagged as not
cross-validated.

Evaluation and search use a fitted prior through the compact request field ``data_prior``:
dictionary and generation-source weights are multiplied by their region's gain, and the noise
becomes the fitted Gaussian correlation. The reference-calibrated 20 dB noise level is kept, so
scores remain reference-normalized; the data's own signal-to-noise ratio is reported only.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.optimize import lsq_linear
from scipy.spatial.distance import cdist

from .eeg_recording import check_summary

PRIOR_SCHEMA = 'eeg-data-prior/1'
ATLAS_PATH = 'webapp/public/models/ernie/source-roi.json'
ATLAS_ID = 'dk40-six-roi-v1'
REGIONS = ('frontal', 'central', 'parietal', 'occipital', 'temporal_left', 'temporal_right', 'other')
# Longer correlations are smooth enough to compete with the brain signal itself, which makes the split unidentifiable.
LENGTH_GRID_MM = (5, 10, 15, 20, 30, 40)
MAXIMUM_RHO = .95
GAIN_BOUNDS = (.1, 10.)
SHRINKAGE_GRID = (0., .25, .5, .75, 1.)
MINIMUM_CHANNELS = 16
CHANNEL_PRESENCE = .9


def atlas_groups(root, data):
    """Region index (REGIONS order) of every dictionary and generation source of the frozen bank."""
    atlas = json.loads((Path(root) / ATLAS_PATH).read_text())
    dictionary = np.asarray(atlas.get('dictionary_roi_indices'))
    generation = atlas.get('generation_sources', [])
    if atlas.get('definition_id') != ATLAS_ID or dictionary.shape != (len(data['source_xyz_mm']),) \
            or len(generation) != len(data['generation_xyz_mm']) or not set(np.unique(dictionary)) <= set(range(7)):
        raise ValueError('源区域图谱与前向库不一致')
    if not np.allclose([s['xyz_mm'] for s in generation], data['generation_xyz_mm'], rtol=0, atol=1e-6):
        raise ValueError('源区域图谱的生成源坐标与前向库不一致')
    # Atlas indices: 0 unassigned, 1..6 the ROIs; REGIONS puts 'other' last.
    dictionary_group = np.where(dictionary == 0, 6, dictionary - 1)
    generation_group = np.array([6 if s['roi_id'] is None else REGIONS.index(s['roi_id']) for s in generation])
    return dictionary_group, generation_group


def canonical(value):
    """The validated request form, or ValueError."""
    if not isinstance(value, dict) or set(value) != {'region_gain', 'rho', 'length_mm'}:
        raise ValueError('data_prior须含region_gain、rho和length_mm')
    gains, rho, length = value['region_gain'], value['rho'], value['length_mm']
    if not isinstance(gains, list) or len(gains) != len(REGIONS) or any(type(g) not in (int, float) or not np.isfinite(g)
                                                                         or not 1e-3 <= g <= 1e3 or float(f'{g:.4g}') != g for g in gains):
        raise ValueError('region_gain须为7个保留4位有效数字、介于0.001和1000之间的数')
    if type(rho) not in (int, float) or not 0 <= rho <= MAXIMUM_RHO or round(rho, 2) != rho:
        raise ValueError(f'rho须为0到{MAXIMUM_RHO}之间、保留两位小数的数')
    if (rho == 0 and length is not None) or (rho > 0 and (type(length) is not int or length not in LENGTH_GRID_MM)):
        raise ValueError(f'rho为0时length_mm为null，否则须为{LENGTH_GRID_MM}之一')
    return {'region_gain': [float(g) for g in gains], 'rho': float(rho), 'length_mm': length}


def prior_id(value):
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]


def noise_model(value):
    """Internal spatial model for the localization covariance, or None for independent noise."""
    return None if value['rho'] == 0 else {'kind': 'spatial', 'rho': value['rho'], 'length_mm': value['length_mm']}


def kernel(value):
    return None if value['rho'] == 0 else (value['rho'], value['length_mm'])


def apply(root, data, value, weights=None, generation_weights=None):
    """Prior-weighted dictionary and generation-source weights for a validated request value."""
    value = canonical(value)
    dictionary_group, generation_group = atlas_groups(root, data)
    gains = np.asarray(value['region_gain'])
    weights = data['source_area_weights'] if weights is None else weights
    generation_weights = data['generation_area_weights'] if generation_weights is None else generation_weights
    return np.asarray(weights) * gains[dictionary_group], np.asarray(generation_weights) * gains[generation_group]


def describe(value):
    value = canonical(value)
    return {'kind': 'data_prior', 'id': prior_id(value), 'regions': list(REGIONS), 'region_gain': value['region_gain'],
            'noise': 'independent' if value['rho'] == 0 else {'kind': 'spatial_gaussian_correlation', 'rho': value['rho'], 'length_mm': value['length_mm']},
            'applies_to': ['field', 'sensitivity', 'localization', 'search'],
            'noise_level': 'reference-calibrated 20 dB, as in the default protocol'}


def _vec(matrix):
    rows, cols = np.triu_indices(len(matrix))
    return matrix[rows, cols] * np.where(rows == cols, 1., np.sqrt(2.))


def channel_fields(root, xyz_mm):
    """Dictionary-source fields at cap positions; channels off the scalp-node table are reported, not used."""
    from . import scalp_node_table
    from .design_evaluation import ernie_scalp, load_bank
    if not scalp_node_table.available(root):
        raise ValueError('拟合数据先验需要预计算头皮节点表，本安装没有。')
    data, pointer, _ = load_bank(root)
    vertices, faces, _ = ernie_scalp(root, data)
    table = scalp_node_table.load(root)
    projection = scalp_node_table.project(vertices, faces, np.asarray(xyz_mm, dtype=float))
    rows, w = projection['vertex_rows'].copy(), projection['barycentric_weights']
    negligible = w < 1e-12
    rows[negligible] = np.repeat(rows[np.arange(len(rows)), w.argmax(axis=1)][:, None], 3, axis=1)[negligible]
    inside = np.isin(rows, table.vertex_indices).all(axis=1)
    n = int(data['dictionary_source_count'])
    field = table.superpose(rows[inside], w[inside])[:, :n]
    return data, pointer, table, field, inside, projection['distances_mm']


class Model:
    """Region, correlated-noise and per-channel-noise design matrices at one channel set."""

    def __init__(self, field, xyz_mm, weights, groups):
        c = len(field)
        self.size = c
        self.centring = np.eye(c) - 1. / c
        self.distance = cdist(xyz_mm, xyz_mm)
        weights = np.asarray(weights, dtype=float) / np.sum(weights)
        blocks = [self.centring @ (field[:, groups == r] * weights[groups == r]) @ field[:, groups == r].T @ self.centring
                  for r in range(len(REGIONS))]
        scale = sum(np.trace(b) for b in blocks)
        self.blocks = [b / scale for b in blocks]
        self.traces = np.array([np.trace(b) for b in self.blocks])
        self.area = np.array([weights[groups == r].sum() for r in range(len(REGIONS))])
        self.regions = np.stack([_vec(b) for b in self.blocks], axis=1)
        self.channel = np.stack([_vec(np.outer(self.centring[i], self.centring[i])) for i in range(c)], axis=1)

    def correlated(self, length):
        return self.centring @ np.exp(-self.distance ** 2 / (2. * length * length)) @ self.centring

    def _solve(self, signal, length, target, signal_bounds=None):
        """Nonnegative signal, correlated and per-channel noise coefficients; returns (x, relative residual)."""
        columns = [signal] + ([_vec(self.correlated(length))[:, None]] if length else []) + [self.channel]
        matrix = np.column_stack(columns)
        k = signal.shape[1]
        low = [0.] * matrix.shape[1]
        high = [np.inf] * matrix.shape[1]
        if signal_bounds is not None:
            low[:k], high[:k] = signal_bounds
        x = lsq_linear(matrix, target, bounds=(low, high), method='bvls').x if signal_bounds is not None \
            else lsq_linear(matrix, target, bounds=(0., np.inf), method='bvls').x
        return x, np.linalg.norm(matrix @ x - target) / np.linalg.norm(target)

    def _parts(self, x, k, length):
        correlated = x[k] if length else 0.
        channel = x[k + (1 if length else 0):]
        return correlated, channel

    def fit(self, covariance):
        """Best regional and best area-prior fits of one covariance."""
        target = _vec(covariance / np.trace(covariance))
        best, uniform = None, None
        for length in (None, *LENGTH_GRID_MM):
            x, residual = self._solve(self.regions.sum(axis=1)[:, None], length, target)
            if uniform is None or residual < uniform['residual']:
                correlated, channel = self._parts(x, 1, length)
                uniform = {'scale': x[0], 'correlated': correlated, 'channel': channel, 'length_mm': length, 'residual': residual}
            if x[0] <= 1e-9:
                continue
            low, high = GAIN_BOUNDS
            k = len(REGIONS)
            x, residual = self._solve(self.regions, length, target, ([low * x[0]] * k, [high * x[0]] * k))
            if best is None or residual < best['residual']:
                correlated, channel = self._parts(x, k, length)
                best = {'coefficients': x[:k], 'correlated': correlated, 'channel': channel, 'length_mm': length, 'residual': residual}
        if best is None:
            raise ValueError('数据协方差无法由皮层源模型解释（信号系数为0）')
        for fit in (best, uniform):
            # Unit-diagonal equivalent of c G_L + diag(d): its correlated fraction at mean channel noise.
            total = fit['correlated'] + fit['channel'].mean()
            fit['rho'] = float(min(MAXIMUM_RHO, round(float(fit['correlated'] / total), 2))) if total > 0 and fit['length_mm'] else 0.
            if fit['rho'] == 0:
                fit['length_mm'] = None
        signal = float(best['coefficients'] @ self.traces)
        noise = float(best['correlated'] * (np.trace(self.correlated(best['length_mm'])) if best['length_mm'] else 0)
                      + self.channel_trace(best['channel']))
        gains = best['coefficients'] / (best['coefficients'] @ self.area / self.area.sum())
        return {**best, 'gains': gains, 'snr_db': 10 * np.log10(signal / noise) if noise > 0 else None, 'uniform': uniform}

    def channel_trace(self, channel):
        return float(np.sum(channel * np.diag(self.centring)))

    def refit(self, covariance, gains, length):
        """Region pattern and L fixed; signal scale, correlated and per-channel noise refitted.

        Returns (model covariance at the target's unit-trace scale, per-channel noise variances, relative residual)."""
        target = _vec(covariance / np.trace(covariance))
        pattern = sum(g * b for g, b in zip(gains, self.blocks))
        x, residual = self._solve(_vec(pattern)[:, None], length, target)
        correlated, channel = self._parts(x, 1, length)
        fitted = x[0] * pattern + (correlated * self.correlated(length) if length else 0.) + self.centring @ np.diag(channel) @ self.centring
        return fitted, channel, residual

    def held_out_residual(self, covariance, gains, length):
        return self.refit(covariance, gains, length)[2]


def _restrict(summary, names):
    index = [summary['channels'].index(n) for n in names]
    covariance = np.asarray(summary['covariance'], dtype=float)[np.ix_(index, index)]
    centring = np.eye(len(index)) - 1. / len(index)
    # Re-referencing to the average of a channel subset is exact for average-referenced data.
    return centring @ covariance @ centring


def _round(value, digits=6):
    return float(f'{value:.{digits}g}')


def _quantiles(values):
    return {'p10': _round(np.quantile(values, .1), 4), 'median': _round(np.median(values), 4), 'p90': _round(np.quantile(values, .9), 4)}


def fit(summaries, root, progress=lambda *a: None):
    """eeg-data-prior/1 from one or more covariance summaries of one band (channels present in 90% of them)."""
    if not summaries:
        raise ValueError('至少需要一个协方差摘要')
    for summary in summaries:
        check_summary(summary, root)
    bands = {tuple(s['processing']['band_hz']) for s in summaries}
    if len(bands) != 1:
        raise ValueError('所有摘要须使用同一频带')
    # A channel excluded as bad in a few recordings should not be lost for all of them: keep channels
    # present in at least CHANNEL_PRESENCE of the summaries and leave out the summaries missing one.
    counts, order, position = Counter(), [], {}
    for s in summaries:
        for name, point in zip(s['channels'], s['xyz_mm']):
            counts[name] += 1
            if name not in position:
                order.append(name)
                position[name] = point
    shared = [n for n in order if counts[n] >= CHANNEL_PRESENCE * len(summaries)]
    excluded = [s['label'] for s in summaries if not all(n in s['channels'] for n in shared)]
    summaries = [s for s in summaries if all(n in s['channels'] for n in shared)]
    if not summaries:
        # Every channel can be in 90% of the summaries while each summary misses a different one.
        raise ValueError(f'没有一份摘要包含全部{len(shared)}个共同通道，请去掉缺通道较多的摘要后重试')
    if len(shared) < MINIMUM_CHANNELS:
        raise ValueError(f'各摘要共同的通道少于{MINIMUM_CHANNELS}个（{len(shared)}个）')
    xyz = np.array([position[n] for n in shared])
    progress(.1, '读取头皮节点表，计算记录通道处的前向场')
    data, pointer, table, field, inside, distances = channel_fields(root, xyz)
    names = [n for n, keep in zip(shared, inside) if keep]
    outside = [n for n, keep in zip(shared, inside) if not keep]
    if len(names) < MINIMUM_CHANNELS:
        raise ValueError(f'共同且位于头皮节点表内的通道少于{MINIMUM_CHANNELS}个（{len(names)}个）')
    dictionary_group, _ = atlas_groups(root, data)
    model = Model(field, xyz[inside], data['source_area_weights'], dictionary_group)
    normalized = [c / np.trace(c) for c in (_restrict(s, names) for s in summaries)]
    progress(.3, '拟合区域源功率与噪声结构')
    pooled = model.fit(np.mean(normalized, axis=0))
    per_summary = []
    for k, (s, c) in enumerate(zip(summaries, normalized)):
        progress(.3 + .3 * k / len(summaries), f'逐个摘要拟合 {k + 1}/{len(summaries)}')
        try:
            one = model.fit(c)
        except ValueError as error:
            per_summary.append({'label': s['label'], 'error': str(error)})
            continue
        per_summary.append({'label': s['label'], 'region_gain': [_round(g, 4) for g in one['gains']], 'rho': one['rho'],
                            'length_mm': one['length_mm'], 'relative_residual': _round(one['residual']),
                            'uniform_relative_residual': _round(one['uniform']['residual']),
                            'snr_db': None if one['snr_db'] is None else _round(one['snr_db'], 4)})
    held_out, shrinkage = None, 1.
    if len(summaries) >= 3:
        residuals = np.zeros((len(SHRINKAGE_GRID), len(summaries)))
        for k, c in enumerate(normalized):
            progress(.6 + .35 * k / len(summaries), f'留出检验 {k + 1}/{len(summaries)}')
            train = model.fit(np.mean([x for i, x in enumerate(normalized) if i != k], axis=0))
            for j, t in enumerate(SHRINKAGE_GRID):
                length = train['length_mm'] if t > 0 else train['uniform']['length_mm']
                residuals[j, k] = model.held_out_residual(c, 1 + t * (train['gains'] - 1), length)
        best = int(np.argmin(residuals.mean(axis=1)))
        shrinkage = SHRINKAGE_GRID[best]
        held_out = {'summaries': len(summaries), 'shrinkage_grid': list(SHRINKAGE_GRID),
                    'mean_relative_residual': [_round(v) for v in residuals.mean(axis=1)],
                    'selected_shrinkage': shrinkage,
                    'prior_relative_residual_median': _round(np.median(residuals[best])),
                    'uniform_relative_residual_median': _round(np.median(residuals[0])),
                    'prior_better_count': int(np.sum(residuals[best] < residuals[0] - 1e-12)),
                    'refit_on_held_out': 'region pattern and L fixed; signal scale, correlated and per-channel noise refitted'}
    noise_fit = pooled if shrinkage > 0 else pooled['uniform']
    gains = 1 + shrinkage * (pooled['gains'] - 1)
    request = canonical({'region_gain': [_round(g, 4) for g in gains], 'rho': noise_fit['rho'], 'length_mm': noise_fit['length_mm']})
    uniform = pooled['uniform']
    mean = np.mean(normalized, axis=0)
    fitted, channel, residual = model.refit(mean, np.array(request['region_gain']), request['length_mm'])
    uniform_model = model.refit(mean, np.ones(len(REGIONS)), uniform['length_mm'])[0]
    share = channel * np.diag(model.centring) / np.diag(fitted)
    sd = np.sqrt(np.maximum(channel, 0))
    progress(.97, '写出数据先验')
    return {
        'schema': PRIOR_SCHEMA, 'id': prior_id(request), 'request': request, 'regions': list(REGIONS), 'atlas': ATLAS_ID,
        'fit': {'relative_residual': _round(residual), 'regional_relative_residual': _round(pooled['residual']),
                'uniform_relative_residual': _round(uniform['residual']),
                'uniform_noise': {'rho': uniform['rho'], 'length_mm': uniform['length_mm']},
                'data_snr_db': None if pooled['snr_db'] is None else _round(pooled['snr_db'], 4),
                'channel_noise': {'variance_share': _quantiles(share),
                                  'sd_ratio_to_median': _quantiles(sd / np.median(sd)) if np.median(sd) > 0 else None},
                'fitted_region_gain': [_round(g, 4) for g in pooled['gains']], 'shrinkage': shrinkage,
                'cross_validated': held_out is not None,
                'gain_bounds_relative_to_area_prior_scale': list(GAIN_BOUNDS), 'held_out': held_out, 'per_summary': per_summary},
        'channels': names, 'channels_outside_table': outside, 'summaries_excluded': excluded,
        'channel_rule': f'channels present in at least {CHANNEL_PRESENCE:.0%} of the summaries; summaries missing one are left out',
        'projection_distance_mm_max': _round(float(np.max(distances[inside]))),
        'inputs': [{'label': s['label'], 'file': s['source']['file'], 'sha256': s['source']['sha256'], 'channels': len(s['channels']),
                    'epochs_used': s['epochs']['used']} for s in summaries],
        'band_hz': list(bands.pop()),
        'channel_model': {'description': 'trace-normalised average-reference model covariances at `channels`',
                          'data_prior': [[_round(v) for v in row] for row in fitted / np.trace(fitted)],
                          'area_prior': [[_round(v) for v in row] for row in uniform_model / np.trace(uniform_model)]},
        'provenance': {'bank_sha256': pointer['sha256'], 'scalp_node_table': table.table_id, 'region_definition': ATLAS_ID,
                       'length_grid_mm': list(LENGTH_GRID_MM), 'norm': 'Frobenius, trace-normalised average-reference covariance'},
    }


__all__ = ['PRIOR_SCHEMA', 'REGIONS', 'LENGTH_GRID_MM', 'atlas_groups', 'canonical', 'prior_id', 'noise_model', 'kernel',
           'apply', 'describe', 'Model', 'fit']
