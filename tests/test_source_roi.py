"""Atlas membership, scientific invariants and all 63 regional combinations."""
from copy import deepcopy
from itertools import combinations
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_array_equal, assert_allclose

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import source_reception_v2 as sr

roi = sr.source_roi


def data():
    manifest = json.loads((ROOT / roi.ATLAS_PATH).read_text())
    rng = np.random.default_rng(271828)
    n = 80
    inputs = {
        "dictionary_count": n, "area_weights": np.ones(n) / n,
        "generation_xyz_mm": np.asarray([s["xyz_mm"] for s in manifest["generation_sources"]]),
        "generation_normals": np.asarray([s["normal"] for s in manifest["generation_sources"]]),
        "generation_area_weights": np.ones(256) / 256,
        "baseline_h": rng.normal(size=(64, n + 256)) * 100,
        "candidate_h": rng.normal(size=(64, n + 256)) * 60,
        "baseline_xyz_mm": rng.normal(size=(64, 3)) * 40,
        "candidate_xyz_mm": rng.normal(size=(64, 3)) * 25,
    }
    inputs["source_atlas"] = roi.load_atlas(ROOT, inputs, manifest["source_inputs_sha256"])
    return inputs


def request(mode="cross_region", **extra):
    return sr.validate_request({"record_id": "a" * 64, "mode": mode,
        "region_definition": roi.DEFINITION_ID, "waveform": "burst", "seed": 2026,
        "artifact_scale": 1, **({"brain_regions":list(roi.REGIONS)} if mode == "cross_region" else {}), **extra})


class SourceRoiTests(unittest.TestCase):
    def test_public_atlas_has_nonoverlapping_true_parent_label_membership(self):
        inputs = data()
        atlas = inputs["source_atlas"]
        self.assertEqual(atlas["generation_counts"], dict(zip(roi.REGIONS, [70, 34, 56, 33, 20, 18])))
        self.assertEqual(atlas["unassigned_generation_count"], 25)
        self.assertTrue(all(item["labels_reproduced_exactly"] for item in atlas["validation"]))
        self.assertTrue(all(item["geometry_matches_frozen_sources"] for item in atlas["validation"]))
        for source in atlas["generation_sources"]:
            if source["roi_id"] == "temporal_left": self.assertEqual(source["hemisphere"], "lh")
            if source["roi_id"] == "temporal_right": self.assertEqual(source["hemisphere"], "rh")
            if source["mixed_roi_boundary"]: self.assertIsNone(source["roi_id"])

    def test_all_63_subsets_retain_same_in_roi_representatives_and_normalized_power(self):
        inputs = data()
        assignment = {row["source_region"]:row["generation_source_index"] for row in roi.representatives(inputs["source_atlas"], inputs["generation_xyz_mm"])}
        count = 0
        for k in range(1, 7):
            for regions in combinations(roi.REGIONS, k):
                count += 1
                ids, weights, source = roi.select_sources(inputs, request(brain_regions=list(reversed(regions))))
                assert_array_equal(ids, [assignment[r] for r in regions])
                assert_array_equal(weights, np.full(k, 1/k))
                self.assertEqual(source["source_regions"], list(regions))
                self.assertEqual(len(set(ids)), k)
        self.assertEqual(count, 63)

    def test_local_six_never_cross_region_or_use_unassigned_sources(self):
        inputs = data()
        for region in roi.REGIONS:
            ids, weights, source = roi.select_sources(inputs, request("multi_source", brain_region=region))
            self.assertEqual(len(ids), 6)
            self.assertEqual(len(set(ids)), 6)
            self.assertEqual(source["source_regions"], [region] * 6)
            self.assertAlmostEqual(weights.sum(), 1.)
        empty = deepcopy(inputs["source_atlas"])
        for s in empty["generation_sources"]: s["roi_id"] = None
        with self.assertRaisesRegex(ValueError, "fewer than"):
            roi.region_indices(empty, inputs["generation_xyz_mm"], "frontal", 1)

    def test_request_version_explicit_and_legacy_kept_separate(self):
        req = request()
        self.assertEqual(sr.validate_request(req), req)
        with self.assertRaises(ValueError): sr.validate_request({**req, "region_definition":"unknown"})
        old = {k:v for k,v in req.items() if k != "region_definition"}
        self.assertNotEqual(req, sr.validate_request(old))

    def test_atlas_and_source_corruption_rejected(self):
        inputs = data()
        sha = inputs["source_atlas"]["source_inputs_sha256"]
        with self.assertRaises(ValueError): roi.load_atlas(ROOT, inputs, "0" * 64)
        bad = deepcopy(inputs)
        bad["generation_xyz_mm"][0, 0] += .01
        with self.assertRaises(ValueError): roi.load_atlas(ROOT, bad, sha)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / roi.ATLAS_PATH).parent.mkdir(parents=True)
            (root / roi.DEFINITION_PATH).write_bytes((ROOT / roi.DEFINITION_PATH).read_bytes())
            atlas = json.loads((ROOT / roi.ATLAS_PATH).read_text())
            assigned = next(s for s in atlas["generation_sources"] if s["roi_id"])
            assigned["parent_atlas_labels"] = [35, 35, 35]  # insula cannot inherit a frontal or other ROI
            (root / roi.ATLAS_PATH).write_text(json.dumps(atlas))
            with self.assertRaises(ValueError): roi.load_atlas(root, inputs, sha)

    def test_single_source_same_numbers_with_or_without_atlas_and_other_sources_retained(self):
        inputs = data()
        index = next(s["id"] for s in inputs["source_atlas"]["generation_sources"] if s["roi_id"] is None)
        req = request("single_source", source_index=index)
        new = sr.simulate(inputs, req)
        old = sr.simulate(inputs, {k:v for k,v in req.items() if k != "region_definition"})
        for field in ("waveforms", "conditions", "strength_curve", "events", "metrics"):
            self.assertEqual(new[field], old[field], field)
        self.assertEqual(new["source"]["source_regions"], [None])
        self.assertNotIn("cross_region_source_count", new["protocol"])

    def test_new_local_and_cross_fields_use_original_H_columns_and_never_refit_on_test_sources(self):
        inputs = data()
        before = {key:inputs[key].copy() for key in ("baseline_h", "candidate_h", "area_weights", "generation_xyz_mm", "generation_normals")}
        original = sr.legacy.fit_decoders
        captured = []
        def capture(b,x,w):
            captured.append((b.copy(),x.copy(),w.copy()))
            return original(b,x,w)
        for req in (request(), request("multi_source", brain_region="central")):
            with patch.object(sr.legacy, "fit_decoders", capture): result = sr.simulate(inputs, req)
            ids, weights, _ = roi.select_sources(inputs, req)
            latent = sr.legacy.generate_latents(2026, "burst", weights)
            for side in ("baseline", "candidate"):
                expected = sr.legacy.average_reference(inputs[side + "_h"][:, inputs["dictionary_count"] + ids] @ latent["source_am"])
                assert_array_equal(result["waveforms"][side]["brain_uv"], sr.legacy.preview(expected, 1e6))
            assert_array_equal(result["source"]["normals_mri"], inputs["generation_normals"][ids])
            assert_allclose(np.mean(latent["source_am"] ** 2, axis=1).sum(), sr.legacy.SOURCE_MOMENT_AM ** 2, rtol=1e-12)
        for b,x,w in captured:
            assert_array_equal(b, inputs["baseline_h"][:, :inputs["dictionary_count"]])
            assert_array_equal(x, inputs["candidate_h"][:, :inputs["dictionary_count"]])
            assert_array_equal(w, inputs["area_weights"])
        for key, values in before.items(): assert_array_equal(inputs[key], values)


if __name__ == "__main__": unittest.main()
