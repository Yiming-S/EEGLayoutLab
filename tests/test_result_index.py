import json
from pathlib import Path
import tempfile
import unittest

from compact_eeg.artifacts import atomic_write_json
from compact_eeg.result_index import build_result_index


class ResultIndexTests(unittest.TestCase):
    def test_indexes_complete_and_running_batches_without_metric_interpretation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "campaigns" / "stage1" / "runs" / "run_a"
            complete = run / "batches" / "batch_complete"
            running = run / "batches" / "batch_running"
            complete.mkdir(parents=True)
            running.mkdir(parents=True)
            atomic_write_json(
                run / "run_manifest.json",
                {
                    "run_id": "run_a",
                    "scientific_role": "qualification_only",
                    "formal_v2_performance_eligible": False,
                },
            )
            atomic_write_json(
                complete / "BATCH_STARTED.json",
                {"started_utc": "2026-01-01T00:00:00+00:00"},
            )
            atomic_write_json(
                complete / "qualification_report.json", {"metric": 123}
            )
            atomic_write_json(
                complete / "BATCH_COMPLETE.json",
                {
                    "completed_utc": "2026-01-01T00:01:00+00:00",
                    "status": "blocked_manual_gate",
                },
            )
            atomic_write_json(
                running / "BATCH_STARTED.json",
                {"started_utc": "2026-01-01T00:02:00+00:00"},
            )

            index = build_result_index(
                root,
                selection={
                    "current_runs": [
                        {
                            "campaign_id": "stage1",
                            "run_id": "run_a",
                            "role": "current_test",
                        }
                    ],
                    "superseded_runs": [],
                },
            )

            self.assertEqual(index["summary"]["campaign_count"], 1)
            self.assertEqual(index["summary"]["total_batch_count"], 2)
            self.assertEqual(index["summary"]["complete_batch_count"], 1)
            self.assertEqual(index["summary"]["current_run_count"], 1)
            self.assertEqual(
                index["summary"]["formal_performance_eligible_complete_batch_count"],
                0,
            )
            batches = index["campaigns"][0]["runs"][0]["batches"]
            run = index["campaigns"][0]["runs"][0]
            self.assertEqual(run["selection_status"], "current")
            self.assertEqual(run["selection_role"], "current_test")
            self.assertEqual(batches[0]["lifecycle"], "complete")
            self.assertEqual(batches[0]["scientific_status"], "blocked_manual_gate")
            self.assertEqual(len(batches[0]["reports"]), 1)
            self.assertEqual(batches[1]["lifecycle"], "running")
            self.assertNotIn("metric", json.dumps(index))

    def test_rejects_batch_with_two_terminal_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = (
                root
                / "campaigns"
                / "stage"
                / "runs"
                / "run"
                / "batches"
                / "batch"
            )
            batch.mkdir(parents=True)
            atomic_write_json(
                batch.parents[1] / "run_manifest.json", {"run_id": "run"}
            )
            atomic_write_json(batch / "BATCH_COMPLETE.json", {})
            atomic_write_json(batch / "BATCH_FAILED.json", {})

            with self.assertRaisesRegex(ValueError, "both complete and failed"):
                build_result_index(root)

    def test_rejects_selection_of_absent_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "campaigns").mkdir()
            with self.assertRaisesRegex(ValueError, "absent runs"):
                build_result_index(
                    root,
                    selection={
                        "current_runs": [
                            {"campaign_id": "missing", "run_id": "missing"}
                        ],
                        "superseded_runs": [],
                    },
                )


if __name__ == "__main__":
    unittest.main()
