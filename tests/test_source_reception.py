"""Scientific and contract checks for the isolated source/reception experiment."""
from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from compact_eeg.workflows import source_reception as sr


def request(**changes):
    return {"record_id": "1" * 64, "brain_region": "frontal", "waveform": "burst", "artifact_scale": 1, "seed": 42, **changes}


def inputs(seed=9):
    rng = np.random.default_rng(seed)
    n, g = 32, 18
    xyzb = rng.normal(size=(64, 3)) * [50, 70, 40] + [0, 15, 30]
    xyzx = rng.normal(size=(64, 3)) * [20, 10, 20] + [0, 80, 30]
    return {"baseline_h": rng.normal(size=(64, n + g)) * 100,
            "candidate_h": rng.normal(size=(64, n + g)) * 60,
            "baseline_xyz_mm": xyzb, "candidate_xyz_mm": xyzx,
            "dictionary_count": n, "area_weights": np.ones(n) / n,
            "generation_xyz_mm": rng.normal(size=(g, 3)) * [40, 60, 30],
            "generation_area_weights": np.ones(g) / g}


class SourceReceptionTests(unittest.TestCase):
    def test_request_bounds_and_types(self):
        self.assertEqual(sr.validate_request(request()), request())
        for key, val in (("record_id", "../record"), ("record_id", "A" * 64), ("brain_region", "atlas_frontal"),
                         ("waveform", "wrong"), ("artifact_scale", True), ("artifact_scale", 3),
                         ("artifact_scale", float("nan")), ("seed", True), ("seed", -1), ("seed", 10000), ("seed", 1.5)):
            with self.subTest(key=key, value=val), self.assertRaises(ValueError):
                sr.validate_request(request(**{key: val}))
        with self.assertRaises(ValueError):
            sr.validate_request({**request(), "ar": .9})

    def test_helmert_is_orthonormal_reference_free(self):
        w = sr.helmert()
        assert_allclose(w @ w.T, np.eye(63), atol=2e-15)
        assert_allclose(w @ np.ones(64), 0, atol=1e-15)
        assert_allclose(w.T @ w, np.eye(64) - np.ones((64, 64)) / 64, atol=1e-15)

    def test_forward_linearity_and_common_reference(self):
        rng = np.random.default_rng(8)
        h, a, b = rng.normal(size=(64, 6)), rng.normal(size=(6, 100)), rng.normal(size=(6, 100))
        assert_allclose(sr.average_reference(h @ (2 * a - b)), 2 * sr.average_reference(h @ a) - sr.average_reference(h @ b), atol=1e-14)
        assert_allclose(sr.average_reference(h @ a).sum(axis=0), 0, atol=1e-13)
        offset = rng.normal(size=(1, 100))
        assert_allclose(sr.average_reference(h @ a + offset), sr.average_reference(h @ a), atol=3e-15)

    def test_exact_coordinate_identity_no_nearest_substitution(self):
        bank = np.arange(300, dtype=float).reshape(100, 3) / 10
        ids = np.arange(12, 76)
        assert_array_equal(sr.exact_layout_rows(bank[ids].tolist(), bank), ids)
        mutated = bank[ids].copy()
        mutated[0, 0] += 1e-10
        with self.assertRaisesRegex(ValueError, "nearest-neighbour"):
            sr.exact_layout_rows(mutated, bank)
        mutated[0] = mutated[1]
        with self.assertRaisesRegex(ValueError, "distinct"):
            sr.exact_layout_rows(mutated, bank)

    def test_decoder_noiseless_same_layout_identity(self):
        d = inputs()
        n = d["dictionary_count"]
        fit = sr.fit_decoders(d["baseline_h"][:, :n], d["baseline_h"][:, :n], d["area_weights"])
        assert_allclose(fit["baseline"], fit["candidate"], atol=1e-13)
        signal = sr.average_reference(d["baseline_h"][:, n:] @ np.ones((18, 30)) * 1e-8)
        # Even if regularization creates reconstruction bias, equal layouts
        # with the same (here noiseless) observation must have identical error.
        ma = sr.metrics_for(signal, fit["baseline"] @ signal, signal, signal * 0)
        mb = sr.metrics_for(signal, fit["candidate"] @ signal, signal, signal * 0)
        self.assertEqual(ma, mb)
        self.assertEqual(sr.relative_field(ma["explained_energy"], mb["explained_energy"]), 1.)
        assert_allclose(fit["candidate"] @ np.ones(64), 0, atol=2e-15)

    def test_decoder_only_uses_clean_allbrain_prior(self):
        signature = list(inspect.signature(sr.fit_decoders).parameters)
        self.assertEqual(signature, ["baseline_h", "candidate_h", "area_weights"])
        d = inputs()
        received = []
        original = sr.fit_decoders
        def capture(b, x, weights):
            received.append((b.copy(), x.copy(), weights.copy()))
            return original(b, x, weights)
        with patch.object(sr, "fit_decoders", capture):
            sr.simulate(d, request(brain_region="occipital", waveform="rhythm"))
        assert_array_equal(received[0][0], d["baseline_h"][:, :d["dictionary_count"]])
        assert_array_equal(received[0][1], d["candidate_h"][:, :d["dictionary_count"]])
        assert_array_equal(received[0][2], d["area_weights"])

    def test_noise_calibration_does_not_follow_candidate_gain(self):
        d = inputs()
        n = d["dictionary_count"]
        a = sr.fit_decoders(d["baseline_h"][:, :n], d["candidate_h"][:, :n], d["area_weights"])
        b = sr.fit_decoders(d["baseline_h"][:, :n], 100 * d["candidate_h"][:, :n], d["area_weights"])
        self.assertEqual(a["noise_std_v"], b["noise_std_v"])
        self.assertAlmostEqual(a["noise_std_v"] / a["signal_std_v"], .1)

    def test_latent_sources_are_shared_non_rank_one_deterministic(self):
        a = sr.generate_latents(4, "burst", np.ones(6))
        b = sr.generate_latents(4, "burst", np.ones(6))
        for key in ("source_am", "ecg", "eog", "noise_baseline", "noise_candidate"):
            assert_array_equal(a[key], b[key])
        self.assertEqual(np.linalg.matrix_rank(a["source_am"]), 6)
        self.assertFalse(np.array_equal(a["noise_baseline"], a["noise_candidate"]))
        self.assertAlmostEqual(float(np.sum(np.mean(a["source_am"] ** 2, axis=1))), sr.SOURCE_MOMENT_AM ** 2, delta=1e-28)
        self.assertTrue(any(0 < t < 8 for t in a["blink_times_s"]))

    def test_artifact_coefficient_is_baseline_only(self):
        d = inputs()
        m1, c1 = sr.artifact_maps(d["baseline_xyz_mm"], d["candidate_xyz_mm"], 1e-6)
        changed = d["candidate_xyz_mm"].copy()
        changed[1:] += 15
        m2, c2 = sr.artifact_maps(d["baseline_xyz_mm"], changed, 1e-6)
        self.assertEqual(c1, c2)
        for kind in ("ecg", "eog"):
            assert_array_equal(m1[kind]["baseline"], m2[kind]["baseline"])
            raw = sr.raw_artifact_map(d["candidate_xyz_mm"], kind)
            expected = (raw - raw.mean()) * c1[kind]["shared_voltage_coefficient_v"]
            assert_allclose(m1[kind]["candidate"], expected, rtol=0, atol=0)
            self.assertGreater(float(np.std(m1[kind]["candidate"])), 0)

    def test_commonmode_artifact_is_not_misused_as_signal(self):
        d = inputs()
        with patch.object(sr, "raw_artifact_map", lambda xyz, kind: np.ones(len(xyz))):
            with self.assertRaisesRegex(ValueError, "constant"):
                sr.artifact_maps(d["baseline_xyz_mm"], d["candidate_xyz_mm"], 1e-6)
        assert_allclose(sr.average_reference(np.ones((64, 50))), 0)

    def test_negative_and_unavailable_metrics_are_not_clipped(self):
        t = np.ones((64, 30)) * 1e-6
        scores = sr.metrics_for(t, -t, t, np.zeros_like(t))
        self.assertEqual(scores["nmse"], 4)
        self.assertEqual(scores["explained_energy"], -3)
        self.assertIsNone(scores["brain_artifact_ratio_db"])
        self.assertEqual(sr.relative_field(-3, .5), -6)
        self.assertIsNone(sr.relative_field(-3, 0))
        self.assertIsNone(sr.relative_field(.3, -1))
        self.assertIsNone(sr.relative_field(.3, 1e-9))
        self.assertIsNone(sr.relative_field(float("nan"), .5))
        self.assertIsNone(sr.metrics_for(t * 0, t, t * 0, t)["nmse"])

    def test_mixture_decomposition_and_shared_noise_across_strength(self):
        rng = np.random.default_rng(99)
        p = {k: sr.average_reference(rng.normal(size=(64, 50))) * 1e-6 for k in sr.COMPONENTS}
        p.update({"reconstructed_" + k: .7 * p[k] for k in sr.COMPONENTS})
        both = {"baseline": p, "candidate": p}
        target = p["brain"]
        actual = sr.evaluate_condition(both, target, "mixed", 2.)
        reconstruction = .7 * (p["brain"] + p["noise"] + 2 * p["ecg"] + 2 * p["eog"])
        expected = sr.metrics_for(target, reconstruction, p["brain"], 2 * p["ecg"] + 2 * p["eog"], p["noise"])
        self.assertEqual(actual["candidate"], expected)
        clean = sr.evaluate_condition(both, target, "clean", 0.)
        for kind in ("ecg", "eog", "mixed"):
            zero = sr.evaluate_condition(both, target, kind, 0.)
            self.assertEqual(zero["candidate"], clean["candidate"])
        one = sr.evaluate_condition(both, target, "ecg", 1.)
        two = sr.evaluate_condition(both, target, "ecg", 2.)
        self.assertAlmostEqual(two["candidate"]["artifact_power_uv2"], 4 * one["candidate"]["artifact_power_uv2"])
        self.assertEqual(one["candidate"]["noise_power_uv2"], two["candidate"]["noise_power_uv2"])

    def test_preview_antialiases_and_not_used_for_metrics(self):
        t = np.arange(4000) / 200
        reduced = np.asarray(sr.preview(np.sin(2 * np.pi * 70 * t)))
        self.assertEqual(reduced.shape, (400,))
        self.assertLess(float(np.sqrt(np.mean(reduced[20:] ** 2))), .01)
        d = inputs()
        a = sr.simulate(d, request())
        with patch.object(sr, "preview", lambda value, multiplier=1: [999]):
            b = sr.simulate(d, request())
        self.assertEqual(a["conditions"], b["conditions"])
        self.assertEqual(a["strength_curve"], b["strength_curve"])

    def test_protocol_contract_and_determinism(self):
        d = inputs()
        a = sr.simulate(d, request())
        b = sr.simulate(d, request())
        self.assertEqual(a, b)
        self.assertEqual(a["request"], request())
        self.assertEqual(a["source"]["patch_count"], 6)
        self.assertTrue(all(i >= d["dictionary_count"] for i in a["source"]["bank_source_indices"]))
        self.assertEqual(len(a["conditions"]), 4)
        self.assertEqual(a["conditions"][0]["artifact_scale"], 0.)
        self.assertEqual(len(a["strength_curve"]), 16)
        for side in ("baseline", "candidate"):
            self.assertEqual(len(a["waveforms"][side]), 8)
            for values in a["waveforms"][side].values():
                self.assertEqual(np.asarray(values).shape, (64, 400))
        self.assertLess(len(json.dumps(a, allow_nan=False).encode()), 16 * 1024 * 1024)

    def test_strength_selection_preserves_all_curve_conditions(self):
        d = inputs()
        a, b = sr.simulate(d, request(artifact_scale=.5)), sr.simulate(d, request(artifact_scale=4))
        self.assertEqual(a["strength_curve"], b["strength_curve"])
        for side in ("baseline", "candidate"):
            self.assertEqual(a["waveforms"][side]["brain_uv"], b["waveforms"][side]["brain_uv"])
            self.assertEqual(a["waveforms"][side]["noise_uv"], b["waveforms"][side]["noise_uv"])
            for field in ("ecg_uv", "eog_uv", "reconstructed_ecg_uv", "reconstructed_eog_uv"):
                assert_allclose(np.asarray(a["waveforms"][side][field]) * 8, b["waveforms"][side][field], atol=5e-6)

    @unittest.skipUnless(os.environ.get("SOURCE_RECEPTION_REAL_BANK") == "1", "opt-in existing Ernie bank integration; no new FEM")
    def test_real_existing_bank_integration(self):
        pointer = json.loads((ROOT / "results/v2/current_multiregion_bank.json").read_text())
        with np.load(ROOT / pointer["path"], allow_pickle=False) as bank:
            # Select exact existing points deterministically; no synthetic FEM.
            record = {"id": "1" * 64, "dataset_id": "integration_fixture", "label": "existing-bank exact-coordinate check",
                      "layout": {"xyzMm": bank["candidate_xyz_mm"][:64].tolist(), "referenceXyzMm": bank["reference_xyz_mm"].tolist(), "regionIndices": [0] * 64}}
        payload = {"request": request(), "record": record}
        result = sr.run_experiment(ROOT, payload)
        self.assertEqual(result["provenance"]["bank_sha256"], pointer["sha256"])
        self.assertEqual(result["layout"], record["layout"])
        self.assertFalse(result["provenance"]["fem_recomputed"])
        for condition in result["conditions"]:
            self.assertTrue(np.isfinite(condition["baseline"]["nmse"]))
            self.assertTrue(np.isfinite(condition["candidate"]["nmse"]))
        self.assertLess(len(json.dumps(result, allow_nan=False).encode()), 16 * 1024 * 1024)
        with tempfile.TemporaryDirectory(prefix="source-reception-cli-") as folder:
            request_file = Path(folder) / "request.json"
            output_file = Path(folder) / "result.json"
            request_file.write_text(json.dumps(payload))
            command = [sys.executable, str(ROOT / "scripts/run_source_reception.py"), "--repository-root", str(ROOT),
                       "--request", str(request_file), "--output", str(output_file)]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            events = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertEqual(events[-1]["type"], "result")
            self.assertEqual(events[-1]["status"], "completed")
            stored = json.loads(output_file.read_text())
            self.assertEqual(stored["conditions"], result["conditions"])
            self.assertEqual(stored["waveforms"], result["waveforms"])
            before = output_file.read_bytes()
            repeat = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(repeat.returncode, 0)
            self.assertIn("already exists", repeat.stdout)
            self.assertEqual(output_file.read_bytes(), before)
        payload["record"]["layout"]["referenceXyzMm"][0][0] += 1e-9
        with self.assertRaisesRegex(ValueError, "exact reference"):
            sr.load_inputs(ROOT, payload)


if __name__ == "__main__":
    unittest.main()
