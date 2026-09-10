"""Additive single-source contracts; keep v1 numerics and cache files intact."""
from __future__ import annotations

import json
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
            return catalog, {"source_input_sha256": "3" * 64}
        provider.load_frozen_source_catalog = load
        with patch.dict(sys.modules, {"compact_eeg.workflows.reception_forward_provider": provider}):
            result = sr.get_source_catalog(ROOT)
        self.assertEqual(calls, [ROOT])
        self.assertEqual(len(result["sources"]), 256)
        self.assertEqual(result["sources"][17]["id"], 17)
        assert_array_equal(result["sources"][17]["normal"], catalog["generation_normals"][17])
        self.assertEqual(result["provenance"]["source_input_sha256"], "3" * 64)

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
