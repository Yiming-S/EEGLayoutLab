"""Deterministic algebra, coordinate contract and finite-bank perturbation tests."""
import sys
from pathlib import Path
import unittest
import json
from unittest.mock import patch
import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from compact_eeg.workflows import design_evaluation as de


def request():
    return {'action': 'perturb', 'radius_mm': 6, 'seed': 42, 'design': {
        'schema': 'eeg-electrode-design/1', 'coordinate_system': 'ernie_native_mm', 'unit': 'mm', 'name': 'fixture',
        'xyz_mm': [[float(i % 8 * 6), float(i // 8 * 6), 0.] for i in range(64)], 'region_indices': [0] * 32 + [1] * 32}}


class DesignEvaluationTests(unittest.TestCase):
    def test_displacement_excludes_forbidden_rows_without_renumbering(self):
        xyz = np.asarray(request()['design']['xyz_mm']); labels = np.array([0]*32+[1]*32)
        bank = np.vstack([xyz, xyz+[0,0,1]])
        allowed = np.array([False]*64+[True]*64)
        ids, _ = de.displaced_indices(xyz, labels, bank, 3, np.random.default_rng(42), allowed)
        self.assertTrue(np.all(ids>=64)); self.assertEqual(len(set(ids)),64)

    def test_legacy_cavity_layout_rejected_before_native_solver(self):
        pointer = json.loads((ROOT/'results/v2/historical_strict_area_budget_study.json').read_text())
        report = json.loads((ROOT/pointer['report']).read_text())
        c = next(c for c in report['conditions'] if c['condition']['id']=='r2_whole_scalp_free_union60')
        s = next(f['final'] for f in c['finalists'] if f['objective']=='min_field_sensitivity20')
        r = request(); r['action']='evaluate'; r['design']['xyz_mm']=s['xyz_mm']; r['design']['region_indices']=s['region_indices']
        with patch.object(de,'native_field',side_effect=AssertionError('must not invoke solver')):
            with self.assertRaisesRegex(ValueError,'外部表面筛选'): de.evaluate(r)

    def test_valid_contract(self):
        self.assertEqual(de.validate_request(request()), request())

    def test_invalid_configuration(self):
        for key, value in [('action', 'search'), ('seed', True), ('seed', -1), ('radius_mm', 4), ('radius_mm', True)]:
            with self.subTest(key=key), self.assertRaises(ValueError): de.validate_request({**request(), key: value})

    def test_coordinate_frames_and_spacing(self):
        for key, val in [('coordinate_system', 'mni'), ('unit', 'm'), ('xyz_mm', [[0, 0, 0]] * 64), ('region_indices', [0] * 31 + [1] * 33)]:
            r = request(); r['design'][key] = val
            with self.subTest(key=key), self.assertRaises(ValueError): de.validate_request(r)
        r = request(); r['design']['xyz_mm'][1] = [1, 0, 0]
        with self.assertRaises(ValueError): de.validate_request(r)

    def test_no_change_frozen_estimator_equals_oracle(self):
        rng = np.random.default_rng(31)
        h, b = rng.normal(size=(2, 64, 100)); w = rng.uniform(.1, 1, 100)
        engine = de.LayoutSearchMetrics(h, b, w)
        expected = engine.make_state(np.arange(64)).field_relative
        self.assertAlmostEqual(de.fixed_estimator_retention(h, h, b, w), expected, places=11)
        self.assertAlmostEqual(de.fixed_estimator_retention(b, b, b, w), 1, places=11)

    def test_known_displaced_estimator_bounds_frozen_estimator(self):
        rng = np.random.default_rng(3); h, moved, b = rng.normal(size=(3, 64, 90)); w = np.ones(90)
        oracle = de.LayoutSearchMetrics(moved, b, w).make_state(np.arange(64)).field_relative
        frozen = de.fixed_estimator_retention(h, moved, b, w)
        self.assertLessEqual(frozen, oracle + 1e-11)
        self.assertLess(frozen, 0)  # Negative explanation is preserved, never clipped.

    def test_gauge_invariance(self):
        rng = np.random.default_rng(20); h, moved, b = rng.normal(size=(3, 64, 70)); w = np.ones(70)
        original = de.fixed_estimator_retention(h, moved, b, w)
        result = de.fixed_estimator_retention(h + 10, moved - 4, b + 12, w)
        self.assertAlmostEqual(result, original, places=11)

    def test_zero_offset_preserves_exact_layout(self):
        r = request(); xyz = np.array(r['design']['xyz_mm']); labels = np.array(r['design']['region_indices'])
        ids, t = de.displaced_indices(xyz, labels, xyz, 0, np.random.default_rng(1))
        assert_array_equal(ids, np.arange(64)); self.assertEqual(t['unchanged_fraction'], 1)
        self.assertEqual(t['actual_max_mm'], 0)

    def test_displacement_distinct_bounded_and_reproducible(self):
        r = request(); xyz = np.array(r['design']['xyz_mm']); labels = np.array(r['design']['region_indices'])
        bank = np.vstack([xyz, xyz + [0, 0, 5]])
        a, t = de.displaced_indices(xyz, labels, bank, 6, np.random.default_rng(3))
        b, s = de.displaced_indices(xyz, labels, bank, 6, np.random.default_rng(3))
        assert_array_equal(a, b); self.assertEqual(t, s); self.assertEqual(len(set(a)), 64)
        self.assertLessEqual(t['actual_max_mm'], 6 + 1e-7)
        assert_allclose(np.array(t['xyz_mm']), bank[a])


if __name__ == '__main__': unittest.main()
