"""Session robustness of a fixed 64-electrode layout (protocol ``standard/1``).

Three perturbations that occur between recording sessions, each scored as LMMSE
field retention relative to the nominal standard64 reference at 20 dB, the same
normalizer as ``field_relative``:

* Electrode dropout. Bad channels are removed and the remaining electrodes are
  re-referenced to their own average; the estimator is retrained on them. Every
  single electrode is removed in turn (64 cases), and 32 seeded random subsets of
  2, 4 and 8 electrodes are removed.
* Unequal electrode noise (impedance). The nominal noise is the floor of a good
  contact; a poorer contact multiplies the noise standard deviation by
  ``max(1, exp(s z_i))``, ``z_i ~ N(0, 1)``, so half the electrodes keep the
  nominal noise; ``s = 0.5`` and ``1.0``, 32 draws each. Channel noise levels can
  be measured, so the estimator knows them. (A lognormal factor without the floor
  makes some contacts quieter than a good one, and highly redundant layouts
  would then gain from unequal noise.)
* Cap re-placement. The whole cap is rotated about the head centre (centre of
  the sphere fitted to standard64) around a uniformly random axis, by the angle
  that moves standard64 by 5 or 10 mm RMS, plus independent 2 mm (per axis)
  electrode jitter, then projected onto the scalp; 16 trials per level. Fields
  come from the published scalp-node table. ``fixed_estimator`` keeps the
  estimator of the nominal positions (positions not re-measured);
  ``redigitized`` retrains it on the new positions.

The standard64 reference receives the same draws, paired by list position and
rotation, and is reported beside the layout. Its scores use the same nominal
reference normalizer, so 1 means "as good as the unperturbed reference".
"""
from __future__ import annotations

import numpy as np
from scipy.linalg import cho_factor, cho_solve

PROTOCOL = 'standard/1'
SNR_DB = 20
DROPOUT_COUNTS = (2, 4, 8)
DROPOUT_DRAWS = 32
IMPEDANCE_LOG_SD = (0.5, 1.0)
IMPEDANCE_DRAWS = 32
REPLACEMENT_RMS_MM = (5, 10)
REPLACEMENT_JITTER_MM = 2.0
REPLACEMENT_TRIALS = 16
# Streams of one request seed; fixed so adding a stream never changes another.
_STREAM = {'dropout': 1, 'impedance': 2, 'replacement': 3}


def validate(value, request):
    if value != PROTOCOL:
        raise ValueError(f'robustness must be "{PROTOCOL}"')
    if request.get('action') != 'evaluate' or 'head_id' in request or 'conductivity_scenario' in request:
        raise ValueError('robustness applies to the evaluate action on the Ernie head, without a conductivity scenario')


def subset_relative(engine, positions, variance=None):
    """Field retention of the engine's layout restricted to ``positions``.

    ``engine`` is a LayoutSearchMetrics whose bank is exactly the 64 layout
    electrodes. ``variance`` optionally scales each electrode's noise variance.
    With all 64 positions and no scaling this is ``make_state(...).field_relative``.
    """
    s = np.asarray(positions, dtype=np.int64)
    _, noise = engine._noise(SNR_DB)
    covariance = engine._covariance[np.ix_(s, s)]
    correlation = engine._noise_matrix(s)
    if variance is not None:
        root = np.sqrt(np.asarray(variance, float)[s])
        correlation = correlation * root[:, None] * root[None, :]
    covariance = .5 * (covariance + covariance.T) + noise * correlation
    inverse = cho_solve(cho_factor(covariance, lower=True, check_finite=False), np.eye(len(s)), check_finite=False)
    inverse = .5 * (inverse + inverse.T)
    cross = engine._cross[:, s]
    inverse_one = inverse.sum(axis=1)
    projected_one = cross @ inverse_one
    absolute = (np.sum((cross @ inverse) * cross) - np.dot(projected_one, projected_one) / inverse_one.sum()) / engine._target_energy
    if not np.isfinite(absolute) or not -1e-9 <= absolute <= 1 + 1e-9:
        raise FloatingPointError('subset explained energy outside numerical bounds')
    return float(absolute / engine._baseline(SNR_DB))


def stats(values):
    values = np.asarray([v for v in values if v is not None], float)
    if not len(values):
        return None
    median, p10 = np.quantile(values, [.5, .1])
    return {'median': float(median), 'p10': float(p10), 'minimum': float(values.min()), 'count': int(len(values))}


def dropout(candidate, reference, seed):
    single = [subset_relative(candidate, np.delete(np.arange(64), i)) for i in range(64)]
    single_reference = [subset_relative(reference, np.delete(np.arange(64), i)) for i in range(64)]
    rng = np.random.default_rng(np.random.SeedSequence([seed, _STREAM['dropout']]))
    levels = []
    for count in DROPOUT_COUNTS:
        kept = [np.sort(rng.permutation(64)[count:]) for _ in range(DROPOUT_DRAWS)]
        levels.append({'removed': count, 'draws': DROPOUT_DRAWS,
                       'candidate': stats(subset_relative(candidate, k) for k in kept),
                       'reference': stats(subset_relative(reference, k) for k in kept)})
    return {'single': {'candidate': single, 'reference': stats(single_reference)}, 'random': levels}


def impedance(candidate, reference, seed):
    rng = np.random.default_rng(np.random.SeedSequence([seed, _STREAM['impedance']]))
    levels, everything = [], np.arange(64)
    for log_sd in IMPEDANCE_LOG_SD:
        draws = [np.maximum(1., np.exp(2 * log_sd * rng.standard_normal(64))) for _ in range(IMPEDANCE_DRAWS)]
        levels.append({'log_sd': log_sd, 'draws': IMPEDANCE_DRAWS,
                       'candidate': stats(subset_relative(candidate, everything, v) for v in draws),
                       'reference': stats(subset_relative(reference, everything, v) for v in draws)})
    return levels


def head_centre(points):
    """Least-squares sphere centre: |p|^2 = 2 c.p + (r^2 - |c|^2)."""
    points = np.asarray(points, float)
    design = np.hstack([2 * points, np.ones((len(points), 1))])
    solution = np.linalg.lstsq(design, np.sum(points * points, axis=1), rcond=None)[0]
    return solution[:3]


def rotation(axis, angle):
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(angle) * k + (1 - np.cos(angle)) * (k @ k)


def angle_for_rms(points, centre, axis, rms_mm):
    """Rotation angle about ``axis`` through ``centre`` moving ``points`` by ``rms_mm`` RMS."""
    q = np.asarray(points, float) - centre
    perpendicular = q - np.outer(q @ axis, axis)
    radius = np.sqrt(np.mean(np.sum(perpendicular * perpendicular, axis=1)))
    return 2 * np.arcsin(min(1., rms_mm / (2 * radius)))


def replacement(context, seed):
    """Cap re-placement trials; ``context`` holds the evaluated fields and the table."""
    from . import scalp_node_table
    from .design_evaluation import fixed_estimator_retention
    from compact_eeg import noise_models
    from compact_eeg.layout_search_metrics import LayoutSearchMetrics
    root, data, kernel = context['root'], context['data'], context['kernel']
    if not scalp_node_table.available(root):
        return {'status': 'unavailable', 'reason': '重新佩戴试验需要预计算头皮节点表，本安装没有。'}
    table = scalp_node_table.load(root)
    vertices, faces = context['scalp']
    n, weights, hb = context['n'], context['weights'], context['hb']
    nominal = {'candidate': (context['h'], context['xyz']), 'reference': (hb, context['reference_xyz'])}
    centre = head_centre(context['reference_xyz'])
    eligible = data['_eligible_surface']
    rng = np.random.default_rng(np.random.SeedSequence([seed, _STREAM['replacement']]))

    def correlation(points):
        return None if kernel is None else noise_models.spatial_correlation(points, *kernel)

    def fields(points, strict):
        projection = scalp_node_table.project(vertices, faces, points)
        rows, w = projection['vertex_rows'].copy(), projection['barycentric_weights']
        negligible = w < 1e-12
        rows[negligible] = np.repeat(rows[np.arange(len(rows)), w.argmax(axis=1)][:, None], 3, axis=1)[negligible]
        # Layout electrodes need all three face vertices admissible, as for new coordinates; the reference is exempt.
        if strict and not eligible[projection['vertex_rows']].all():
            return None
        if not np.isin(rows, table.vertex_indices).all():
            return None
        field = table.superpose(rows, w)
        return field[:, :n], projection['projected_mm']

    levels = []
    for rms in REPLACEMENT_RMS_MM:
        outcome = {name: {'fixed': [], 'redigitized': [], 'moved': [], 'rejected': 0} for name in nominal}
        angles = []
        for _ in range(REPLACEMENT_TRIALS):
            axis = rng.standard_normal(3)
            axis /= np.linalg.norm(axis)
            angle = angle_for_rms(context['reference_xyz'], centre, axis, rms)
            turn = rotation(axis, angle)
            jitter = rng.normal(scale=REPLACEMENT_JITTER_MM, size=(64, 3))
            angles.append(np.degrees(angle))
            for name, (field, points) in nominal.items():
                moved = (points - centre) @ turn.T + centre + jitter
                observed = fields(moved, strict=name == 'candidate')
                if observed is None:
                    outcome[name]['rejected'] += 1
                    continue
                changed, actual = observed
                noise = None if kernel is None else {'nominal': correlation(points), 'observed': correlation(actual),
                                                     'reference': correlation(context['reference_xyz'])}
                outcome[name]['fixed'].append(fixed_estimator_retention(field, changed, hb, weights, snr_db=SNR_DB, noise=noise))
                engine = LayoutSearchMetrics(changed, hb, weights, noise_kernel=None if kernel is None
                                             else (actual, context['reference_xyz'], *kernel))
                outcome[name]['redigitized'].append(engine.make_state(np.arange(64), snr_db=SNR_DB).field_relative)
                outcome[name]['moved'].append(float(np.sqrt(np.mean(np.sum((actual - points) ** 2, axis=1)))))
        levels.append({'rms_mm': rms, 'trials': REPLACEMENT_TRIALS, 'rotation_deg': float(np.median(angles)),
                       **{name: {'completed': len(o['fixed']), 'rejected': o['rejected'], 'fixed_estimator': stats(o['fixed']),
                                 'redigitized': stats(o['redigitized']),
                                 'displacement_rms_mm': float(np.median(o['moved'])) if o['moved'] else None}
                          for name, o in outcome.items()}})
    return {'status': 'completed', 'centre_mm': centre.tolist(), 'jitter_mm': REPLACEMENT_JITTER_MM,
            'table_id': table.table_id, 'levels': levels}


def evaluate(context, seed, progress=lambda *args: None):
    """The ``robustness`` result block for one evaluated layout."""
    candidate, reference = context['engine'], context['reference_engine']
    progress(.9, '稳健性：电极脱落')
    block = {'protocol': PROTOCOL, 'snr_db': SNR_DB, 'dropout': dropout(candidate, reference, seed)}
    progress(.93, '稳健性：电极噪声不均')
    block['impedance'] = impedance(candidate, reference, seed)
    progress(.95, '稳健性：重新佩戴')
    block['replacement'] = replacement(context, seed)
    return block
