"""Independent closed-receipt checks for W04, W12 and Windows Qt W13.

Source controls may be partial. Only packaged Windows observations can satisfy
the host acceptance gate; QTest events do not claim native Win32 input delivery.
"""
from __future__ import annotations

import math
import re

FACETS = {
    "privacy": ("private_creation_denial", "explicit_output_survives", "unowned_sibling_survives",
                "idle_cleanup_denial_retry", "active_cleanup_denial_retry"),
    "shell": ("single_planner_owner", "real_review_import", "native_shell_layout", "windows_qt_planner_keyboard"),
    "lifecycle": ("active_review_close", "active_export_close", "dirty_realtime_close_refusal", "active_dashboard_rebind"),
}
NATIVE_FACETS = {"idle_cleanup_denial_retry", "active_cleanup_denial_retry",
                "native_shell_layout", "windows_qt_planner_keyboard"}
ALL_FACETS = tuple(name for names in FACETS.values() for name in names)


def _require(condition):
    if not condition:
        raise ValueError("invalid_closeout_observation")


def _digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _record(value, kind, packaged):
    keys = {"schema_version", "status", "runtime_context", "facets", "error_codes"}
    if kind != "privacy":
        keys.add("evidence")
    _require(type(value) is dict and set(value) == keys)
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1
             and value["error_codes"] == [] and value["runtime_context"] in {"source", "packaged"})
    facets = value["facets"]
    _require(type(facets) is dict and set(facets) == set(FACETS[kind]))
    for name, state in facets.items():
        _require(state == "passed" or (not packaged and name in NATIVE_FACETS and state == "not_assessed"))
    expected = "passed" if all(state == "passed" for state in facets.values()) else "partial"
    _require(value["status"] == expected)
    if packaged:
        _require(value["runtime_context"] == "packaged" and expected == "passed")


def _shell(value, packaged, expected_dpr):
    evidence = value["evidence"]
    _require(type(evidence) is dict and set(evidence) == {
        "relative_artifact_dir", "qpa", "dpr", "physical_screen", "fixture_count",
        "imported_count", "excluded_count", "planner_geometry", "import_oracle",
    })
    _require(type(evidence["relative_artifact_dir"]) is str
             and re.fullmatch(r"shell-checks-[0-9a-f]{32}", evidence["relative_artifact_dir"]) is not None)
    for key, expected in (("fixture_count", 5), ("imported_count", 2), ("excluded_count", 3)):
        _require(type(evidence[key]) is int and evidence[key] == expected)
    _import_oracle(evidence["import_oracle"])
    dpr = evidence["dpr"]
    _require(type(dpr) in {int, float} and math.isfinite(dpr) and 0 < dpr <= 4)
    size = evidence["physical_screen"]
    _require(type(size) is list and len(size) == 2
             and all(type(item) is int and 0 < item <= 16384 for item in size))
    geometry = evidence["planner_geometry"]
    _require(type(geometry) is dict and set(geometry) == {"workspace_client", "table_height"})
    client = geometry["workspace_client"]
    _require(type(client) is list and len(client) == 2
             and all(type(item) is int and 0 < item <= 1920 for item in client)
             and type(geometry["table_height"]) is int and 60 <= geometry["table_height"] <= client[1])
    if value["status"] == "passed":
        _require(evidence["qpa"] == "windows" and size == [1920, 1080])
    else:
        _require(evidence["qpa"] in {"offscreen", "xcb", "wayland", "cocoa"})
    if packaged:
        _require(type(expected_dpr) in {int, float} and math.isfinite(expected_dpr)
                 and abs(dpr - expected_dpr) <= 0.05)


def _import_oracle(value):
    _require(type(value) is dict and set(value) == {
        "table_counts", "file_names", "measurement_values", "database_sha256",
    })
    counts = value["table_counts"]
    _require(type(counts) is dict and counts == dict.fromkeys(
        ("source_files", "active_locations", "parsed_reports", "metadata", "measurements"), 2)
        and all(type(count) is int for count in counts.values()))
    _require(value["file_names"] == ["REF001_2024-01-01_1.pdf", "REF001_2024-01-01_3.pdf"]
             and value["measurement_values"] == [10.02, 10.02] and _digest(value["database_sha256"]))


def _lifecycle(value, packaged):
    evidence = value["evidence"]
    expected = {
        "fixture_count": 5, "review_database_created": False, "export_status": "cancelled",
        "cancelled_export_published": False, "dirty_close_deferred": False,
        "dashboard_worker_class": "RealtimeDashboardWriterThread", "rebound_same_dialog": True,
    }
    keys = set(expected) | {"relative_artifact_dir", "committed_database_logical_sha256",
                            "rebind_target_logical_sha256", "qpa", "native_windows_assessed"}
    _require(type(evidence) is dict and set(evidence) == keys)
    _require(all(type(evidence[key]) is type(wanted) and evidence[key] == wanted for key, wanted in expected.items()))
    _require(type(evidence["relative_artifact_dir"]) is str
             and re.fullmatch(r"lifecycle-checks-[0-9a-f]{32}", evidence["relative_artifact_dir"]) is not None
             and _digest(evidence["committed_database_logical_sha256"])
             and _digest(evidence["rebind_target_logical_sha256"]))
    _require(type(evidence["native_windows_assessed"]) is bool
             and evidence["qpa"] in {"windows", "offscreen", "xcb", "wayland", "cocoa"}
             and evidence["native_windows_assessed"] == (evidence["qpa"] == "windows"))
    if packaged:
        _require(evidence["native_windows_assessed"] is True)


def validate(value, *, packaged=False, expected_dpr=None):
    _require(type(value) is dict and set(value) == set(FACETS))
    for kind, record in value.items():
        _record(record, kind, packaged)
    _shell(value["shell"], packaged, expected_dpr)
    _lifecycle(value["lifecycle"], packaged)
    return value
