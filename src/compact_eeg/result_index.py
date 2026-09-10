"""Read-only indexing of append-only V2 campaign artifacts."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any, Mapping

from .artifacts import sha256_file


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _artifact_entry(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _selection_lookup(
    selection: Mapping[str, Any] | None,
) -> tuple[dict[tuple[str, str], dict[str, Any]], set[tuple[str, str]]]:
    if selection is None:
        return {}, set()
    current: dict[tuple[str, str], dict[str, Any]] = {}
    superseded: set[tuple[str, str]] = set()
    for item in selection.get("current_runs", []):
        key = (str(item["campaign_id"]), str(item["run_id"]))
        if key in current or key in superseded:
            raise ValueError(f"duplicate run selection: {key}")
        current[key] = dict(item)
    for item in selection.get("superseded_runs", []):
        key = (str(item["campaign_id"]), str(item["run_id"]))
        if key in current or key in superseded:
            raise ValueError(f"duplicate run selection: {key}")
        superseded.add(key)
    return current, superseded


def build_result_index(
    results_root: str | Path,
    *,
    selection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a relocatable inventory of complete and incomplete V2 batches.

    The index does not interpret metric values.  Its purpose is to keep
    qualification data, technical pilots, and formal performance batches
    visibly separate while exposing immutable report hashes to the App.
    """

    root = Path(results_root).resolve()
    campaigns_root = root / "campaigns"
    if not campaigns_root.is_dir():
        raise ValueError(f"campaign directory does not exist: {campaigns_root}")

    current_runs, superseded_runs = _selection_lookup(selection)
    seen_runs: set[tuple[str, str]] = set()
    campaigns: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    scientific_role_counts: Counter[str] = Counter()
    total_batches = 0
    total_complete_batches = 0
    total_formal_eligible_batches = 0

    for campaign_dir in sorted(path for path in campaigns_root.iterdir() if path.is_dir()):
        run_entries: list[dict[str, Any]] = []
        runs_dir = campaign_dir / "runs"
        if runs_dir.is_dir():
            for run_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
                manifest_path = run_dir / "run_manifest.json"
                if not manifest_path.is_file():
                    raise ValueError(f"missing run manifest: {manifest_path}")
                manifest = _load_object(manifest_path)
                run_id = str(manifest.get("run_id", run_dir.name))
                run_key = (campaign_dir.name, run_id)
                seen_runs.add(run_key)
                role = str(manifest.get("scientific_role", "unclassified"))
                formal_eligible = bool(
                    manifest.get("formal_v2_performance_eligible", False)
                )
                scientific_role_counts[role] += 1

                batch_entries: list[dict[str, Any]] = []
                batches_dir = run_dir / "batches"
                if batches_dir.is_dir():
                    for batch_dir in sorted(
                        path for path in batches_dir.iterdir() if path.is_dir()
                    ):
                        started_path = batch_dir / "BATCH_STARTED.json"
                        complete_path = batch_dir / "BATCH_COMPLETE.json"
                        failed_path = batch_dir / "BATCH_FAILED.json"
                        if complete_path.is_file() and failed_path.is_file():
                            raise ValueError(
                                f"batch cannot be both complete and failed: {batch_dir}"
                            )
                        started = (
                            _load_object(started_path) if started_path.is_file() else {}
                        )
                        terminal_path: Path | None = None
                        terminal: dict[str, Any] = {}
                        lifecycle = "running"
                        if complete_path.is_file():
                            lifecycle = "complete"
                            terminal_path = complete_path
                            terminal = _load_object(complete_path)
                            total_complete_batches += 1
                            if formal_eligible:
                                total_formal_eligible_batches += 1
                        elif failed_path.is_file():
                            lifecycle = "failed"
                            terminal_path = failed_path
                            terminal = _load_object(failed_path)
                        elif not started_path.is_file():
                            lifecycle = "orphaned_directory"

                        scientific_status = str(
                            terminal.get("status", started.get("status", lifecycle))
                        )
                        status_counts[scientific_status] += 1
                        total_batches += 1
                        report_paths = sorted(
                            path
                            for path in batch_dir.glob("*_report.json")
                            if path.is_file()
                        )
                        batch_entry: dict[str, Any] = {
                            "batch_id": batch_dir.name,
                            "formal_v2_performance_eligible": formal_eligible,
                            "lifecycle": lifecycle,
                            "reports": [
                                _artifact_entry(path, root) for path in report_paths
                            ],
                            "scientific_status": scientific_status,
                        }
                        if started_path.is_file():
                            batch_entry["started_event"] = _artifact_entry(
                                started_path, root
                            )
                            if "started_utc" in started:
                                batch_entry["started_utc"] = started["started_utc"]
                        if terminal_path is not None:
                            batch_entry["terminal_event"] = _artifact_entry(
                                terminal_path, root
                            )
                            if "completed_utc" in terminal:
                                batch_entry["completed_utc"] = terminal["completed_utc"]
                        batch_entries.append(batch_entry)

                run_entry: dict[str, Any] = {
                        "batches": batch_entries,
                        "formal_v2_performance_eligible": formal_eligible,
                        "manifest": _artifact_entry(manifest_path, root),
                        "run_id": run_id,
                        "scientific_role": role,
                }
                if run_key in current_runs:
                    run_entry["selection_status"] = "current"
                    run_entry["selection_role"] = current_runs[run_key].get("role")
                elif run_key in superseded_runs:
                    run_entry["selection_status"] = "superseded"
                elif selection is not None:
                    run_entry["selection_status"] = "unregistered"
                run_entries.append(run_entry)
        campaigns.append({"campaign_id": campaign_dir.name, "runs": run_entries})

    referenced = set(current_runs) | superseded_runs
    missing_references = sorted(referenced - seen_runs)
    if missing_references:
        raise ValueError(f"selection references absent runs: {missing_references}")

    return {
        "schema_version": "compact-eeg-result-index/1",
        "summary": {
            "campaign_count": len(campaigns),
            "complete_batch_count": total_complete_batches,
            "formal_performance_eligible_complete_batch_count": (
                total_formal_eligible_batches
            ),
            "run_count": sum(len(item["runs"]) for item in campaigns),
            "current_run_count": len(set(current_runs) & seen_runs),
            "superseded_run_count": len(superseded_runs & seen_runs),
            "scientific_role_counts": dict(sorted(scientific_role_counts.items())),
            "scientific_status_counts": dict(sorted(status_counts.items())),
            "total_batch_count": total_batches,
        },
        "campaigns": campaigns,
    }


__all__ = ["build_result_index"]
