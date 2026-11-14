"""Explicit data and native-runtime tiers; original scientific tests stay intact."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA_TESTS = {
    "test_legacy_cavity_layout_rejected_before_native_solver",
    "test_frozen_problem_region_and_controls",
    "test_real_bank_posterior25_has_same_constraint_32_plus32_solution",
    "test_real_existing_bank_integration",
    "test_real_catalog_and_existing_bank_cli",
}
NATIVE_TESTS = {
    "test_four_tetrahedra_continuous_electrodes_and_fallback",
    "test_closed_inner_surface_occluded_outer_surface_exposed",
}


def pytest_collection_modifyitems(items):
    restored = (ROOT / "results/v2/historical_strict_area_budget_study.json").is_file()
    for item in items:
        if item.name in NATIVE_TESTS:
            item.add_marker(pytest.mark.native_runtime)
        if item.name in DATA_TESTS:
            item.add_marker(pytest.mark.data_bundle)
            if not restored:
                item.add_marker(pytest.mark.skip(reason="Restore the separately shared scientific data bundle to run this original historical-data regression"))
