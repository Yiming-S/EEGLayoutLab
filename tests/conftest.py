"""Keep original scientific tests intact; gate only external dataset fixtures."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA_TESTS = {
    "test_legacy_cavity_layout_rejected_before_native_solver",
    "test_frozen_problem_region_and_controls",
}


def pytest_collection_modifyitems(items):
    restored = (ROOT / "results/v2/historical_strict_area_budget_study.json").is_file()
    for item in items:
        if item.name in DATA_TESTS:
            item.add_marker(pytest.mark.data_bundle)
            if not restored:
                item.add_marker(pytest.mark.skip(reason="Restore the separately shared scientific data bundle to run this original historical-data regression"))
