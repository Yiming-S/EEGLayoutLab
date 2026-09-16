"""Additive single-source contracts; keep v1 numerics and cache files intact."""
from __future__ import annotations

import json
from itertools import combinations
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import source_reception_v2 as sr


def request(**changes):
    return {"record_id": "2" * 64, "mode": "single_source", "source_index": 17,
            "waveform": "burst", "artifact_scale": 1, "seed": 2026, **changes}


def cross_request(regions=None, **changes):
    return {"record_id": "2" * 64, "mode": "cross_region",
            "brain_regions": list(sr.CROSS_REGION_ORDER) if regions is None else regions,
            "waveform": "burst", "artifact_scale": 1, "seed": 2026, **changes}


def inputs(seed=510):
    rng = np.random.default_rng(seed)
    n = 80
    normals = rng.normal(size=(256, 3))
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    return {"baseline_h": rng.normal(size=(64, n + 256)) * 100,
            "candidate_h": rng.normal(size=(64, n + 256)) * 60,
            "dictionary_count": n, "area_weights": np.ones(n) / n,
            "baseline_xyz_mm": rng.normal(size=(64, 3)) * [45, 65, 35] + [0, 10, 30],
            "candidate_xyz_mm": rng.normal(size=(64, 3)) * [20, 10, 15] + [0, 75, 30],
            "generation_xyz_mm": rng.normal(size=(256, 3)) * [40, 60, 30],
            "generation_normals": normals, "generation_area_weights": np.ones(256) / 256}


class SourceReceptionV2Tests(unittest.TestCase):
    def test_request_discriminates_modes_and_rejects_direction_or_coordinates(self):
        self.assertEqual(sr.validate_request(request()), request())
        for change in ({"source_index": True}, {"source_index": -1}, {"source_index": 256},
                       {"source_index": 1.5}, {"source_index": "17"}, {"mode": "free_orientation"},
                       {"brain_region": "frontal"}, {"direction": [1, 0, 0]}, {"xyz_mm": [1, 2, 3]},
                       {"seed": True}, {"record_id": "invalid"}, {"ar": 90}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                sr.validate_request(request(**change))
        multi = {key: val for key, val in request().items() if key != "source_index"}
        multi.update(mode="multi_source", brain_region="frontal")
        self.assertEqual(sr.validate_request(multi), multi)
        with self.assertRaises(ValueError):
            sr.validate_request({**multi, "source_index": 17})

    def test_cross_region_request_canonicalizes_without_mutating_input(self):
        raw = cross_request(["temporal_right", "frontal", "parietal"])
        original = json.loads(json.dumps(raw))
        result = sr.validate_request(raw)
        self.assertEqual(result["brain_regions"], ["frontal", "parietal", "temporal_right"])
        self.assertEqual(raw, original)
        self.assertIsNot(result["brain_regions"], raw["brain_regions"])
        self.assertEqual(sr.validate_request(result), result)
        self.assertNotEqual(sr.ALGORITHM_VERSION, "source-reception-fixed-normal-v2")

    def test_cross_region_invalid_sets_and_extra_fields_are_rejected(self):
        invalid = ([], ["frontal", "frontal"], ["unknown"], [None], [True], [["frontal"]],
                   "frontal", None, 3, ("frontal",), list(sr.CROSS_REGION_ORDER) + ["frontal"])
        for regions in invalid:
            with self.subTest(regions=regions), self.assertRaises(ValueError):
                sr.validate_request(cross_request(regions=regions) if regions is not None else {**cross_request(), "brain_regions": None})
        for extra in ({"source_index": 2}, {"brain_region": "frontal"}, {"xyz_mm": [1, 2, 3]}, {"direction": [0, 0, 1]}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                sr.validate_request(cross_request(**extra))

    def test_all_63_cross_region_sets_have_unique_stable_representatives_and_equal_power(self):
        data = inputs()
        xyz, n = data["generation_xyz_mm"], data["dictionary_count"]
        mapping = {entry["source_region"]: entry["generation_source_index"] for entry in sr.cross_region_representatives(xyz)}
        self.assertEqual(len(set(mapping.values())), 6)
        total = 0
        for count in range(1, 7):
            for regions in combinations(sr.CROSS_REGION_ORDER, count):
                total += 1
                with self.subTest(regions=regions):
                    req = sr.validate_request(cross_request(list(reversed(regions))))
                    self.assertEqual(req["brain_regions"], list(regions))
                    ids, weights, source = sr.select_cross_region_sources(xyz, req["brain_regions"], n)
                    assert_array_equal(ids, [mapping[region] for region in regions])
                    self.assertEqual(len(set(ids)), count)
                    self.assertEqual(source["source_regions"], list(regions))
                    self.assertEqual(source["bank_source_indices"], (n + ids).tolist())
                    assert_array_equal(source["xyz_mm"], xyz[ids])
                    assert_array_equal(source["anchor_xyz_mm"], [sr.legacy.REGION_ANCHORS_MM[r] for r in regions])
                    assert_array_equal(weights, np.full(count, 1 / count))
                    self.assertAlmostEqual(float(weights.sum()), 1)
                    self.assertEqual(source["source_power_weights"], weights.tolist())
                    latents = sr.legacy.generate_latents(2026, "burst", weights)
                    energy = np.mean(latents["source_am"] ** 2, axis=1)
                    assert_allclose(energy, np.full(count, sr.legacy.SOURCE_MOMENT_AM ** 2 / count), rtol=2e-14, atol=0)
                    self.assertAlmostEqual(float(energy.sum()), sr.legacy.SOURCE_MOMENT_AM ** 2, delta=1e-28)
        self.assertEqual(total, 63)

    def test_cross_region_collision_and_distance_tie_mapping_is_deterministic(self):
        # Deliberately colliding synthetic inputs make the assignment rule observable.
        xyz = np.zeros((256, 3))
        a = sr.cross_region_representatives(xyz)
        self.assertEqual([row["generation_source_index"] for row in a], list(range(6)))
        for region, expected in zip(sr.CROSS_REGION_ORDER, range(6), strict=True):
            ids, _, _ = sr.select_cross_region_sources(xyz, [region], 80)
            self.assertEqual(ids.tolist(), [expected])
        self.assertEqual(a, sr.cross_region_representatives(xyz.copy()))
        for bad in (np.zeros((5, 3)), np.full((256, 3), np.nan)):
            with self.assertRaises(ValueError):
                sr.cross_region_representatives(bad)

    def test_cross_region_forward_projection_and_contract_for_one_three_and_six_regions(self):
        data = inputs()
        for regions in (["frontal"], ["occipital", "frontal", "central"], list(sr.CROSS_REGION_ORDER)):
            req = cross_request(regions)
            result = sr.simulate(data, req)
            ids = np.asarray(result["source"]["generation_source_indices"])
            count = len(regions)
            latent = sr.legacy.generate_latents(2026, "burst", np.full(count, 1 / count))
            for side, matrix in (("baseline", data["baseline_h"]), ("candidate", data["candidate_h"])):
                expected = sr.legacy.average_reference(matrix[:, data["dictionary_count"] + ids] @ latent["source_am"])
                assert_array_equal(result["waveforms"][side]["brain_uv"], sr.legacy.preview(expected, 1e6))
            assert_array_equal(result["waveforms"]["source_nam"], sr.legacy.preview(latent["source_am"], 1e9))
            assert_array_equal(result["source"]["normals_mri"], data["generation_normals"][ids])
            self.assertEqual(result["schema_version"], "source-reception/2")
            self.assertEqual(result["source"]["patch_count"], count)
            self.assertEqual(result["protocol"]["cross_region_source_count"], count)
            self.assertEqual(result["protocol"]["experiment_mode"], "cross_region")
            self.assertEqual(np.asarray(result["waveforms"]["source_nam"]).shape, (count, 400))
            self.assertEqual(result["protocol"]["sample_rate_hz"], 200)
            self.assertEqual(result["protocol"]["duration_s"], 20)
            self.assertEqual(len(result["conditions"]), 4)
            self.assertEqual(len(result["strength_curve"]), 16)
            self.assertEqual(result["request"], sr.validate_request(req))
            self.assertIn("not an anatomical atlas", result["source"]["selection_method"])
            json.dumps(result, allow_nan=False)

    def test_cross_region_canonical_order_does_not_change_simulation(self):
        data = inputs()
        a = sr.simulate(data, cross_request(["occipital", "frontal"]))
        b = sr.simulate(data, cross_request(["frontal", "occipital"]))
        self.assertEqual(a, b)

    def test_one_cross_region_source_matches_its_explicit_single_source(self):
        data = inputs()
        cross = sr.simulate(data, cross_request(["occipital"]))
        index = cross["source"]["generation_source_indices"][0]
        single = sr.simulate(data, request(source_index=index))
        for key in ("conditions", "strength_curve", "waveforms", "events", "metrics"):
            self.assertEqual(cross[key], single[key], key)

    def test_cross_region_selection_preserves_full_prior_and_common_noise(self):
        data, captured = inputs(), []
        original = sr.legacy.fit_decoders
        def capture(b, x, w):
            captured.append((b.copy(), x.copy(), w.copy()))
            return original(b, x, w)
        with patch.object(sr.legacy, "fit_decoders", capture):
            a = sr.simulate(data, cross_request(["frontal"]))
            b = sr.simulate(data, cross_request())
        n = data["dictionary_count"]
        for baseline, candidate, weights in captured:
            assert_array_equal(baseline, data["baseline_h"][:, :n])
            assert_array_equal(candidate, data["candidate_h"][:, :n])
            assert_array_equal(weights, data["area_weights"])
        self.assertEqual(a["protocol"]["physical_electrode_noise_std_uv"], b["protocol"]["physical_electrode_noise_std_uv"])
        for side in ("baseline", "candidate"):
            self.assertEqual(a["waveforms"][side]["noise_uv"], b["waveforms"][side]["noise_uv"])

    def test_cross_region_preview_and_interference_strength_do_not_refit(self):
        data = inputs()
        a = sr.simulate(data, cross_request())
        with patch.object(sr.legacy, "preview", lambda *args: [999]):
            b = sr.simulate(data, cross_request())
        self.assertEqual(a["conditions"], b["conditions"])
        self.assertEqual(a["strength_curve"], b["strength_curve"])
        c = sr.simulate(data, cross_request(artifact_scale=4))
        self.assertEqual(a["strength_curve"], c["strength_curve"])
        for side in ("baseline", "candidate"):
            self.assertEqual(a["waveforms"][side]["brain_uv"], c["waveforms"][side]["brain_uv"])
            self.assertEqual(a["waveforms"][side]["noise_uv"], c["waveforms"][side]["noise_uv"])

    def test_source_index_is_exact_and_normal_is_original(self):
        data = inputs()
        r = sr.simulate(data, request())
        self.assertEqual(r["source"]["generation_source_indices"], [17])
        self.assertEqual(r["source"]["bank_source_indices"], [data["dictionary_count"] + 17])
        assert_array_equal(r["source"]["xyz_mm"], data["generation_xyz_mm"][[17]])
        assert_array_equal(r["source"]["normals_mri"], data["generation_normals"][[17]])
        self.assertEqual(r["source"]["orientation_mode"], "fixed_cortical_normal")
        self.assertFalse(r["protocol"]["free_orientation_supported"])

    def test_selected_source_does_not_condition_decoder_prior(self):
        data, captured = inputs(), []
        original = sr.legacy.fit_decoders
        def capture(b, x, w):
            captured.append((b.copy(), x.copy(), w.copy()))
            return original(b, x, w)
        with patch.object(sr.legacy, "fit_decoders", capture):
            sr.simulate(data, request(source_index=255))
        n = data["dictionary_count"]
        assert_array_equal(captured[0][0], data["baseline_h"][:, :n])
        assert_array_equal(captured[0][1], data["candidate_h"][:, :n])
        assert_array_equal(captured[0][2], data["area_weights"])

    def test_single_source_field_matches_direct_fixed_normal_projection(self):
        data = inputs()
        r = sr.simulate(data, request())
        latent = sr.legacy.generate_latents(2026, "burst", np.ones(1))
        column = data["dictionary_count"] + 17
        for side, matrix in (("baseline", data["baseline_h"]), ("candidate", data["candidate_h"])):
            expected = sr.legacy.average_reference(matrix[:, column:column + 1] @ latent["source_am"])
            assert_array_equal(r["waveforms"][side]["brain_uv"], sr.legacy.preview(expected, 1e6))
        assert_array_equal(r["waveforms"]["source_nam"], sr.legacy.preview(latent["source_am"], 1e9))
        self.assertAlmostEqual(float(np.mean(latent["source_am"] ** 2)), 1e-16, delta=1e-28)

    def test_single_source_keeps_shared_noise_and_strict_full_rate_contract(self):
        data = inputs()
        a = sr.simulate(data, request())
        b = sr.simulate(data, request(source_index=0))
        self.assertEqual(a["protocol"]["physical_electrode_noise_std_uv"], b["protocol"]["physical_electrode_noise_std_uv"])
        for side in ("baseline", "candidate"):
            self.assertEqual(a["waveforms"][side]["noise_uv"], b["waveforms"][side]["noise_uv"])
        self.assertEqual(a["schema_version"], "source-reception/2")
        self.assertEqual(a["protocol"]["sample_rate_hz"], 200)
        self.assertEqual(a["protocol"]["duration_s"], 20)
        self.assertEqual(np.asarray(a["waveforms"]["source_nam"]).shape, (1, 400))
        self.assertEqual(len(a["conditions"]), 4)
        self.assertEqual(a["conditions"][0]["artifact_scale"], 0)
        self.assertEqual(len(a["strength_curve"]), 16)
        self.assertLess(len(json.dumps(a, allow_nan=False).encode()), 16 * 1024 * 1024)

    def test_preview_never_changes_scores_and_strength_never_changes_noise(self):
        data = inputs()
        a = sr.simulate(data, request())
        with patch.object(sr.legacy, "preview", lambda *args: [999]):
            b = sr.simulate(data, request())
        self.assertEqual(a["conditions"], b["conditions"])
        self.assertEqual(a["strength_curve"], b["strength_curve"])
        c = sr.simulate(data, request(artifact_scale=4))
        self.assertEqual(a["strength_curve"], c["strength_curve"])
        for side in ("baseline", "candidate"):
            self.assertEqual(a["waveforms"][side]["noise_uv"], c["waveforms"][side]["noise_uv"])
            assert_allclose(np.asarray(a["waveforms"][side]["eog_uv"]) * 4, c["waveforms"][side]["eog_uv"], atol=2.5e-6)

    def test_multi_source_preserves_all_v1_numerical_outputs(self):
        data = inputs()
        req = {"record_id": "2" * 64, "brain_region": "frontal", "waveform": "burst", "artifact_scale": 1, "seed": 2026}
        old = sr.legacy.simulate(data, req)
        new = sr.simulate(data, {**req, "mode": "multi_source"})
        for field in ("conditions", "strength_curve", "waveforms", "events", "metrics"):
            self.assertEqual(old[field], new[field], field)
        self.assertEqual(new["source"]["patch_count"], 6)
        ids = new["source"]["generation_source_indices"]
        assert_array_equal(new["source"]["normals_mri"], data["generation_normals"][ids])

    def test_invalid_normals_and_incomplete_forward_matrix_fail(self):
        data = inputs()
        data["generation_normals"][17] *= 2
        with self.assertRaisesRegex(ValueError, "unit normals"):
            sr.simulate(data, request())
        data = inputs()
        data["candidate_h"] = data["candidate_h"][:, :-1]
        with self.assertRaisesRegex(ValueError, "complete prior"):
            sr.simulate(data, request())

    def test_catalog_only_calls_read_only_provider_and_returns_all_normals(self):
        catalog = {**inputs(), "dictionary_count": 4096}
        provider = types.ModuleType("reception_forward_provider")
        calls = []
        def load(root):
            calls.append(root)
            return catalog, {"source_inputs_sha256": "3" * 64}
        provider.load_frozen_source_catalog = load
        atlas = {"sha256": "4" * 64, "definition": {}, "generation_sources": [
            {"id": i, "roi_id": sr.CROSS_REGION_ORDER[i % 6], "xyz_mm": catalog["generation_xyz_mm"][i].tolist(), "normal": catalog["generation_normals"][i].tolist()}
            for i in range(256)]}
        with patch.dict(sys.modules, {"compact_eeg.workflows.reception_forward_provider": provider}), patch.object(sr.source_roi, "load_atlas", return_value=atlas):
            result = sr.get_source_catalog(ROOT)
        self.assertEqual(calls, [ROOT])
        self.assertEqual(len(result["sources"]), 256)
        self.assertEqual(result["sources"][17]["id"], 17)
        assert_array_equal(result["sources"][17]["normal"], catalog["generation_normals"][17])
        self.assertEqual(result["provenance"]["source_inputs_sha256"], "3" * 64)
        self.assertEqual(result["cross_region_order"], list(sr.CROSS_REGION_ORDER))
        self.assertEqual(len(result["cross_region_representatives"]), 6)
        for representative in result["cross_region_representatives"]:
            index = representative["generation_source_index"]
            self.assertEqual(representative["bank_source_index"], 4096 + index)
            assert_array_equal(representative["normal"], catalog["generation_normals"][index])

    def test_load_rejects_preview_and_legacy_multi_without_calling_provider(self):
        provider = types.ModuleType("reception_forward_provider")
        provider.load_reception_forward = lambda *a, **k: self.fail("rejected records must not compute a forward model")
        multi = {key: val for key, val in request(mode="multi_source", brain_region="frontal").items() if key != "source_index"}
        with patch.dict(sys.modules, {"reception_forward_provider": provider}):
            for req, record in ((request(), {"id": "2" * 64, "status": "pending", "layout": {}}),
                                (multi, {"id": "2" * 64, "status": "completed", "dataset_id": "cache", "layout": {}})):
                with self.subTest(request=req), self.assertRaises(ValueError):
                    sr.load_inputs(ROOT, {"request": req, "record": record})

    def test_provider_fraction_progress_is_adapted_to_reception_events(self):
        provider = types.ModuleType("reception_forward_provider")
        calls, events = [], []
        def load(root, record, *, progress, allow_native):
            calls.append((root, record["id"], allow_native))
            progress(.8, "forward test")
            return {**inputs(), "dictionary_count": 4096}, {"forward_mode": "exact_bank"}
        provider.load_reception_forward = load
        record = {"id": "2" * 64, "status": "completed", "dataset_id": "cache", "layout": {}}
        with patch.dict(sys.modules, {"compact_eeg.workflows.reception_forward_provider": provider}), patch.object(sr.legacy, "sha256_file", lambda path: "0" * 64):
            _, _, _, provenance = sr.load_inputs(ROOT, {"request": request(), "record": record}, lambda **event: events.append(event))
        self.assertEqual(calls, [(ROOT, record["id"], True)])
        self.assertEqual(events[0]["stage"], "forward")
        self.assertAlmostEqual(events[0]["progress"], .13)
        self.assertEqual(provenance["thread_limit"], 1)

    def test_cross_region_load_accepts_bank_and_native_records_with_updated_provenance(self):
        provider = types.ModuleType("reception_forward_provider")
        calls = []
        def load(root, record, *, progress, allow_native):
            calls.append((record["dataset_id"], allow_native))
            return {**inputs(), "dictionary_count": 4096}, {"forward_mode": "test-provider"}
        provider.load_reception_forward = load
        for dataset in ("cache", "strict_area", "historical_area", "design_evaluation"):
            record = {"id": "2" * 64, "status": "completed", "dataset_id": dataset, "layout": {}}
            with patch.dict(sys.modules, {"compact_eeg.workflows.reception_forward_provider": provider}), patch.object(sr.legacy, "sha256_file", lambda path: "0" * 64):
                req, _, _, provenance = sr.load_inputs(ROOT, {"request": cross_request(["temporal_right", "frontal"]), "record": record})
            self.assertEqual(req["brain_regions"], ["frontal", "temporal_right"])
            self.assertEqual(provenance["algorithm_version"], sr.ALGORITHM_VERSION)
            self.assertFalse(provenance["physiological_artifact_forward_model"])
            self.assertFalse(provenance["independent_head_validation"])
        self.assertEqual(calls, [(dataset, True) for dataset in ("cache", "strict_area", "historical_area", "design_evaluation")])

    @unittest.skipUnless(os.environ.get("SOURCE_RECEPTION_V2_REAL_BANK") == "1", "opt-in read-only existing bank plus bounded no-FEM job")
    def test_real_catalog_and_existing_bank_cli(self):
        from reception_forward_provider import load_frozen_source_catalog
        catalog, _ = load_frozen_source_catalog(ROOT)
        result = sr.get_source_catalog(ROOT)
        assert_array_equal([s["xyz_mm"] for s in result["sources"]], catalog["generation_xyz_mm"])
        assert_array_equal([s["normal"] for s in result["sources"]], catalog["generation_normals"])
        pointer = json.loads((ROOT / "results/v2/current_multiregion_bank.json").read_text())
        with np.load(ROOT / pointer["path"], allow_pickle=False) as bank:
            record = {"id": "2" * 64, "status": "completed", "dataset_id": "cache", "label": "existing-bank v2 test fixture",
                      "layout": {"xyzMm": bank["candidate_xyz_mm"][:64].tolist(), "referenceXyzMm": bank["reference_xyz_mm"].tolist(), "regionIndices": [0] * 64}}
        with tempfile.TemporaryDirectory(prefix="source-reception-v2-") as folder:
            payload, output = Path(folder) / "request.json", Path(folder) / "result.json"
            payload.write_text(json.dumps({"request": request(), "record": record}))
            command = [sys.executable, str(ROOT / "scripts/run_source_reception_v2.py"), "--repository-root", str(ROOT), "--request", str(payload), "--output", str(output)]
            run = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            saved = json.loads(output.read_text())
            self.assertEqual(saved["schema_version"], "source-reception/2")
            self.assertEqual(saved["layout"], record["layout"])
            self.assertEqual(saved["source"]["generation_source_indices"], [17])
            before = output.read_bytes()
            repeated = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual(output.read_bytes(), before)
            catalog_run = subprocess.run([sys.executable, str(ROOT / "scripts/run_source_reception_v2.py"), "--repository-root", str(ROOT), "--catalog"], capture_output=True, text=True, timeout=20)
            self.assertEqual(catalog_run.returncode, 0, catalog_run.stdout + catalog_run.stderr)
            self.assertEqual(json.loads(catalog_run.stdout)["sources"], result["sources"])


if __name__ == "__main__":
    unittest.main()
