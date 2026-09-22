"""Closed host negatives; synthetic dictionaries are protocol fixtures only."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest

from scripts import verify_windows_candidate_closeout as gate


def closeout_observation(context="packaged", scale=1.0):
    result = {kind: {"schema_version": 1, "status": "passed", "runtime_context": context,
                     "error_codes": [], "facets": dict.fromkeys(names, "passed")}
              for kind, names in gate.FACETS.items()}
    result["shell"]["evidence"] = {
        "relative_artifact_dir": "shell-checks-" + "a" * 32, "qpa": "windows", "dpr": scale,
        "physical_screen": [1920, 1080], "fixture_count": 5, "imported_count": 2, "excluded_count": 3,
        "planner_geometry": {"workspace_client": [700, 420], "table_height": 100},
        "import_oracle": {
            "table_counts": dict.fromkeys(("source_files", "active_locations", "parsed_reports", "metadata", "measurements"), 2),
            "file_names": ["REF001_2024-01-01_1.pdf", "REF001_2024-01-01_3.pdf"],
            "measurement_values": [10.02, 10.02], "database_sha256": "3" * 64,
        },
    }
    result["lifecycle"]["evidence"] = {
        "relative_artifact_dir": "lifecycle-checks-" + "b" * 32, "fixture_count": 5,
        "review_database_created": False, "export_status": "cancelled", "cancelled_export_published": False,
        "committed_database_logical_sha256": "1" * 64, "dirty_close_deferred": False,
        "dashboard_worker_class": "RealtimeDashboardWriterThread", "rebound_same_dialog": True,
        "rebind_target_logical_sha256": "2" * 64, "qpa": "windows", "native_windows_assessed": True,
    }
    if context == "source":
        for record in result.values():
            for name in record["facets"]:
                if name in gate.NATIVE_FACETS:
                    record["facets"][name] = "not_assessed"
            if "not_assessed" in record["facets"].values():
                record["status"] = "partial"
        result["shell"]["evidence"].update(qpa="offscreen", physical_screen=[800, 800])
        result["lifecycle"]["evidence"].update(qpa="offscreen", native_windows_assessed=False)
    return result


def test_source_closeout_is_valid_content_but_not_packaged_acceptance():
    value = closeout_observation("source")
    assert gate.validate(value) is value
    with pytest.raises(ValueError):
        gate.validate(value, packaged=True, expected_dpr=1.0)


@pytest.mark.parametrize("kind", gate.FACETS)
@pytest.mark.parametrize("field,value", [("status", "partial"), ("runtime_context", "source"),
                                         ("schema_version", True), ("facets", {}), ("error_codes", ["unknown"])])
def test_missing_partial_or_source_closeout_never_passes_package(kind, field, value):
    observation = closeout_observation()
    observation[kind][field] = value
    with pytest.raises(ValueError):
        gate.validate(observation, packaged=True, expected_dpr=1.0)


@pytest.mark.parametrize("kind,field,value", [
    ("shell", "qpa", "offscreen"), ("shell", "dpr", 1.5), ("shell", "dpr", float("nan")),
    ("shell", "imported_count", 0), ("shell", "fixture_count", True),
    ("shell", "physical_screen", [800, 800]), ("shell", "relative_artifact_dir", "../private"),
    ("shell", "import_oracle", {}),
    ("shell", "planner_geometry", {"workspace_client": [700, 420], "table_height": 1}),
    ("lifecycle", "native_windows_assessed", False), ("lifecycle", "qpa", "offscreen"),
    ("lifecycle", "export_status", "complete"), ("lifecycle", "cancelled_export_published", True),
    ("lifecycle", "review_database_created", True), ("lifecycle", "dirty_close_deferred", True),
    ("lifecycle", "dashboard_worker_class", "Stub"), ("lifecycle", "rebound_same_dialog", False),
])
def test_closeout_facts_are_checked_independently_of_pass_labels(kind, field, value):
    observation = copy.deepcopy(closeout_observation())
    observation[kind]["evidence"][field] = value
    with pytest.raises(ValueError):
        gate.validate(observation, packaged=True, expected_dpr=1.0)


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5])
def test_closed_native_protocol_control_requires_the_requested_scale(scale):
    observation = closeout_observation(scale=scale)
    assert gate.validate(observation, packaged=True, expected_dpr=scale) is observation


@pytest.mark.skipif(os.name == "nt", reason="Source offscreen integration; Windows display runs in the actual package")
def test_actual_source_closeout_hooks_match_the_host_contract(tmp_path, monkeypatch):
    from metroliza.app.bootstrap import get_or_create_qapplication
    from metroliza.app.windows_candidate_qualification import _run_closeout_slices

    monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1")
    monkeypatch.setenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION", "1")
    app = get_or_create_qapplication()
    assert app is not None
    fixtures = Path(__file__).parent / "fixtures/windows_candidate/reports"
    receipt = {}
    _run_closeout_slices(tmp_path, fixtures, receipt)
    observation = receipt["closeout_observation"]
    assert gate.validate(observation) is observation
    with pytest.raises(ValueError):
        gate.validate(observation, packaged=True, expected_dpr=1.0)
