"""Variable-count regression without modifying the frozen fixed64 protocol."""
import sys
import unittest
from pathlib import Path
import numpy as np
from numpy.testing import assert_allclose

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import electrode_editor as ee
from compact_eeg.layout_search_metrics import LayoutSearchMetrics
from compact_eeg.prototype_localization import evaluate_grid_localization


class EditorTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(2026)
        self.h, self.b = rng.normal(size=(2, 64, 96))
        self.w = rng.uniform(.1, 1, 96)
        self.data = {'dictionary_source_count': 80, 'source_xyz_mm': rng.normal(size=(80,3))*30,
                     'generation_xyz_mm': rng.normal(size=(16,3))*30, 'generation_area_weights': np.ones(16)}

    def test_full64_matches_frozen_engine(self):
        m, sigma = ee.field_metrics(self.h, self.b, self.w)
        engine = LayoutSearchMetrics(self.h, self.b, self.w)
        expected = engine.make_state(np.arange(64))
        self.assertAlmostEqual(m['field_relative'], expected.field_relative, places=10)
        self.assertAlmostEqual(m['field_absolute'], expected.field_absolute, places=10)
        self.assertAlmostEqual(m['sensitivity_tail'], engine.sensitivity_tail(np.arange(64)), places=10)
        assert_allclose(sigma, np.sqrt(engine.reference_mean_contrast_signal_power_v2*.01), rtol=1e-12)

    def test_standard_identity(self):
        m, _ = ee.field_metrics(self.b, self.b, self.w)
        self.assertAlmostEqual(m['field_relative'], 1., places=12)
        self.assertAlmostEqual(m['sensitivity_tail'], 1., places=12)
        self.assertLess(m['field_absolute'], 1.)

    def test_nested_deletions_keep_fixed_noise_and_nonincreasing_field(self):
        previous, sigma = ee.field_metrics(self.h, self.b, self.w)
        for n in [63,56,32,16,3,2]:
            m, noise = ee.field_metrics(self.h[:n], self.b, self.w)
            self.assertEqual(noise, sigma)
            self.assertLessEqual(m['field_absolute'], previous['field_absolute']+1e-10)
            self.assertLessEqual(m['sensitivity_tail'], previous['sensitivity_tail']+1e-10)
            previous = m

    def test_reference_and_scale_invariance(self):
        a, sigma = ee.field_metrics(self.h[:40], self.b, self.w)
        b, _ = ee.field_metrics(self.h[:40]+7, self.b-9, self.w)
        c, noise = ee.field_metrics(self.h[:40]*3, self.b*3, self.w)
        for k in a: self.assertAlmostEqual(a[k], b[k], places=10); self.assertAlmostEqual(a[k], c[k], places=10)
        assert_allclose(noise, sigma*3)

    def test_localization_matches_old64_paired_stream(self):
        _, sigma = ee.field_metrics(self.h[:,:80], self.b[:,:80], self.w[:80])
        actual, reason = ee.localize(self.h, self.data, sigma, np.arange(64), 2026)
        old = evaluate_grid_localization(self.h[:,:80], self.h[:,80:], self.data['source_xyz_mm'], self.data['generation_xyz_mm'],
            source_moment_am=1e-8, physical_electrode_noise_std_v=sigma, noise_seed=2026,
            layout_id='design-evaluation-paired-stream', generation_source_weights=self.data['generation_area_weights']).report
        self.assertIsNone(reason)
        for key in actual: self.assertEqual(actual[key], old[key])

    def test_slot_reordering_preserves_paired_noise(self):
        _, sigma = ee.field_metrics(self.h, self.b, self.w)
        slots = np.arange(0,64,2); permutation = slots[::-1]
        a, _ = ee.localize(self.h[slots], self.data, sigma, slots, 2026)
        b, _ = ee.localize(self.h[permutation], self.data, sigma, permutation, 2026)
        self.assertEqual(a, b)

    def test_two_points_localization_unavailable(self):
        result, reason = ee.localize(self.h[:2], self.data, 1e-9, np.array([0,1]), 2026)
        self.assertIsNone(result); self.assertEqual(reason, 'single_contrast_unknown_amplitude')

    def test_zero_dictionary_column_localization_unavailable(self):
        h = self.h[:8].copy(); h[:,0] = 0
        result, reason = ee.localize(h, self.data, 1e-9, np.arange(8), 2026)
        self.assertIsNone(result); self.assertEqual(reason, 'zero_dictionary_column')

    def test_unbalanced_deletion_and_clear_region_keep_stable_slots(self):
        xyz = np.array([[i*5, 0., 0.] for i in range(64)])
        labels = np.array([0]*32+[1]*32); allowed = [np.arange(32), np.arange(32,64)]
        slots = [{'bank_index':i,'enabled':i>=32} for i in range(64)]
        active, chosen = ee.validate_slots(slots,np.arange(64),labels,allowed,xyz)
        self.assertEqual(active.tolist(), list(range(32,64))); self.assertEqual(chosen.tolist(), active.tolist())
        slots[32]['bank_index'] = 1
        with self.assertRaisesRegex(ValueError, 'region'): ee.validate_slots(slots,np.arange(64),labels,allowed,xyz)

    def test_restoring_conflicting_position_is_rejected(self):
        xyz = np.array([[i*5, 0., 0.] for i in range(64)])
        labels = np.zeros(64,dtype=int); allowed = [np.arange(64)]
        slots = [{'bank_index':i,'enabled':True} for i in range(64)]
        slots[0] = {'bank_index':1,'enabled':False}
        ee.validate_slots(slots,np.arange(64),labels,allowed,xyz)
        slots[0]['enabled'] = True
        with self.assertRaisesRegex(ValueError,'distinct'): ee.validate_slots(slots,np.arange(64),labels,allowed,xyz)


if __name__ == '__main__': unittest.main()
