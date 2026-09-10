"""Regression checks for the original invisible region and exposure screening."""
import unittest
import importlib.util
import sys
import json
from pathlib import Path
import numpy as np
from scipy.spatial import ConvexHull, cKDTree
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from compact_eeg.surface_admissibility import load_admissibility, fibonacci_directions, exposure_counts


class SurfaceAdmissibilityTests(unittest.TestCase):
    def test_frozen_problem_region_and_controls(self):
        p = json.loads((ROOT / 'results/v2/current_multiregion_bank.json').read_text())
        g = np.load(ROOT / p['candidates'])
        mask, provenance = load_admissibility(ROOT)
        a = np.load(ROOT / provenance['surface_admissibility_path'])
        old = json.loads((ROOT / 'results/v2/historical_strict_area_budget_study.json').read_text())
        report = json.loads((ROOT / old['report']).read_text())
        row = next(r for r in report['conditions'] if r['condition']['id'] == 'r2_whole_scalp_free_union60')
        snapshot = next(f['final'] for f in row['finalists'] if f['objective'] == 'min_field_sensitivity20')
        ids = g['candidate_vertex_indices'][snapshot['candidate_bank_indices']][:32]
        self.assertFalse(mask[ids].any())
        self.assertTrue((a['exposure_counts'][:, ids] == 0).all())
        for name in ['left_near_ear_posterolateral_approx', 'right_near_ear_posterolateral_approx']:
            controls = g['surface_roi_masks'][:,list(g['roi_names']).index(name)]
            self.assertTrue(mask[controls].all())
            self.assertFalse(a['unstable_vertex_mask'][controls].any())
        h = np.load(ROOT / p['path'])
        _, ref = cKDTree(g['surface_vertices_m']*1000).query(h['reference_xyz_mm'])
        self.assertTrue(mask[ref].all())
        self.assertEqual(len(mask),len(g['surface_vertices_m']))
        with self.assertRaisesRegex(ValueError, 'geometry mismatch'):
            load_admissibility(ROOT, '0'*64)

    @unittest.skipUnless(importlib.util.find_spec('simnibs'), 'native CGAL runtime required')
    def test_closed_inner_surface_occluded_outer_surface_exposed(self):
        vertices = fibonacci_directions(80) * .1
        faces = ConvexHull(vertices).simplices.copy()
        for face in faces:
            tri = vertices[face]
            if np.dot(np.cross(tri[1]-tri[0],tri[2]-tri[0]),tri.mean(axis=0)) < 0:
                face[1],face[2]=face[2],face[1]
        inner=vertices*.5
        v=np.vstack([vertices,inner]); f=np.vstack([faces,faces+len(vertices)])
        counts=exposure_counts(v,f,fibonacci_directions(32))
        self.assertTrue((counts[:len(vertices)]>0).all())
        self.assertTrue((counts[len(vertices):]==0).all())

if __name__=='__main__': unittest.main()
