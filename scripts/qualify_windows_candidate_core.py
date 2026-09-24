"""Run the closed synthetic core scenario in the actual Windows onedir.

The build host uses its checked-out driver/runtime; the relocated application
uses only its bundled runtime. This is not a clean-machine claim. The existing
diagnostics driver owns restricted-token launch, Job containment and private
temporary-directory handling. No product worker or data service is substituted.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import importlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
from pathlib import Path

from scripts.verify_windows_candidate_closeout import ALL_FACETS as CLOSEOUT_CHECKS

SCENARIO_FILE = "windows-candidate-result.json"
STAGE_FILE = "core-stage.json"
FAILED_DIAGNOSTIC_FILE = "core-failed-diagnostic.json"
MAX_FAILED_DIAGNOSTIC_BYTES = 2048
_CHILD_FAILURE_STAGES = frozenset({
    "root_validation", "fixture_validation", "startup_marker", "runtime_ack",
    "qapplication", "selected_import", "ocr", "ocr_fixture_validation",
    "ocr_asset_validation", "ocr_fixture_inspection", "ocr_parser_construction",
    "ocr_parser_execution", "ocr_onnxruntime_import", "ocr_rapidocr_import",
    "ocr_engine_construction", "ocr_engine_inference", "ocr_result_normalization",
    "ocr_result_validation", "reopen", "tabular", "xlsx",
    "inference", "import_guards", "ui", "closeout", "complete",
})
_REOPEN_FAILURE_STAGES = frozenset({
    "input", "host_ready", "reopen", "database_preservation",
})
REQUIRED_CHECKS = (
    "selected_import", "zero_selection_no_write", "finite_precision_filters", "persisted_measurements",
    "group_membership", "workbook_cells",
    "literal_chart_titles_series_caches_references", "value_limit_order",
    "local_chart_cells_and_negative_control", "pre_cancelled_export_preserves_workbook",
    "oversized_label_rejection_preserves_workbook", "active_export_cancellation_preserves_workbook",
    "successful_group_inference", "reopen_preserves_completed_import",
    "hidden_selection_import", "stale_source_rereview", "duplicate_review", "active_import_cancel_close",
    "private_dashboard_generation", "offline_html_source",
    "declared_ocr_model_assets", "image_only_header_provenance",
    "rapidocr_header_inference", "parser_metadata_selection",
)
ARTIFACTS = ("database", "workbook", "grouping", "tabular", "literal_workbook", "inference_database", "group_inference")
CORE_OBSERVATIONS = {"W03": "passed", "W04": "passed", "W05": "passed", "W06": "passed", "W07": "passed"}
NATIVE_BINDINGS = (
    "cmm.parse_blocks", "cmm.normalize_measurement_rows", "cmm.persist_measurement_rows",
    "comparison.bootstrap_percentile_ci", "comparison.bootstrap_percentile_ci_batch", "comparison.pairwise_stats",
    "distribution.compute_ad_ks_statistics", "distribution.estimate_ad_pvalue_monte_carlo",
    "candidate.compute_candidate_metrics", "candidate.compute_candidate_metrics_batch", "candidate.compute_candidate_fit_params_batch",
    "group.coerce_sequence_to_float64",
    "chart.render_histogram_png", "chart.render_distribution_png", "chart.render_iqr_png", "chart.render_trend_png",
)
RESULT_LIMITS = [
    "Observed core facets only; no complete W01-W16 gate is implied.",
    "Import cancellation is observed at real batch entry; export cancellation occurs after real export progress. Arbitrary later commit boundaries are not implied.",
    "Inference covers only the fixed public two-group PDF case; no general analysis or real-data qualification.",
    "Build-host automation is not clean-machine evidence.",
    "No representative operator data or release acceptance.",
]
MAX_RECEIPT_BYTES = 64 * 1024
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_SECONDS = 900
PUBLIC_FIXTURE_HASHES = {'finite-source.csv': 'de2724bd3b6b55d362016423a2f78168235d3833d7a89298a7fdf4a5ec747938', 'integer-precision.csv': '8e2c837472d6465d319b37b4afe09998f9c45680edc27d1a169f33e145a70508', 'report-0.pdf': '183b46650a7e37113927f7a99eb6a66484d07126d3134b3a6056defaef21af3f', 'report-1.pdf': '315032987a656191260945242c89996976640f3629c4499c428f44ac9b3679ad', 'report-2.pdf': '7a6fe37457385188f9b466a8f9c3061bf7d118290b0c8e74583dba5e76f29048', 'report-3.pdf': 'cb801c452d9608c227606a4c10325d19d7d8a095fe80976fa60338fd6bfd0849', 'report-4.pdf': 'b9f83ee23a191eccfa3515594e6ba85ede670a2163444cd0daf7b9bb5edd83d9'}


class CandidateFailure(RuntimeError):
    """Only fixed identifiers from this driver are exposed in its receipt."""


_PRIVATE_CORE_STAGES = frozenset({
    "package_relocation", "fixtures", "owned_launch", "runtime_observation",
    "runtime_receipt", "owned_topology", "fresh_reopen", "package_integrity",
    "retained_artifacts", "evidence_receipts", "cleanup",
})
_CLOSED_CHILD_FAILURES = frozenset({
    "completed_import_reopen_failed", "database_observation_sidecars_present",
    "export_failed", "export_failed_or_cancelled", "fixture_dir_invalid",
    "fixture_dir_missing", "fixture_hash_mismatch", "fixture_set_mismatch",
    "group_assignment_not_applied", "group_inference_checks_failed",
    "group_metric_missing", "grouped_row_count", "import_count_mismatch",
    "import_deadline", "import_guard_checks_failed", "import_worker_not_started",
    "invalid_ui_scale", "literal_workbook_checks_failed",
    "literal_workbook_copy_mismatch", "ocr_checks_failed", "ocr_evidence_mismatch",
    "ocr_evidence_schema_mismatch", "ocr_fixture_invalid", "ocr_fixture_missing",
    "ocr_observation_schema_mismatch", "reopen_input_identity_mismatch",
    "reopen_output_identity_mismatch", "reports_navigation_missing",
    "review_deadline", "review_mutated_or_count_mismatch", "root_missing",
    "root_not_new_empty_directory", "selection_control_rejected",
    "selection_mismatch", "source_preservation_failed", "staged_source_changed",
    "tabular_filter_ids_mismatch", "tabular_fixture_mismatch",
    "tabular_public_store_missing", "ui_checks_failed", "workbook_incomplete",
    "workspace_context_rejected", "zero_selection_guard_failed",
    "closeout_privacy_failed", "closeout_shell_failed", "closeout_lifecycle_failed",
    "TypeError", "ValueError", "KeyError", "OSError", "RuntimeError",
    "AssertionError", "OperationalError", "FileNotFoundError", "PermissionError",
})


def _closed_unexpected_stage(stage: str) -> CandidateFailure:
    return CandidateFailure(
        "unexpected_" + (stage if stage in _PRIVATE_CORE_STAGES else "private_core_unknown")
    )


def _child_failure_observation(work: Path, expected_source_sha: str | None = None) -> dict[str, str]:
    observation = {
        "receipt_state": "invalid", "producer_stage": "unavailable",
        "allowlisted_failure": "unavailable", "reason": "package_scenario_nonzero_exit_receipt_invalid",
    }
    try:
        payload = _json(work / SCENARIO_FILE)
    except FileNotFoundError:
        observation["receipt_state"] = "missing"
        observation["reason"] = "package_scenario_nonzero_exit_receipt_missing"
    except (CandidateFailure, OSError, ValueError, TypeError):
        pass
    else:
        if (type(payload) is dict
                and payload.get("schema") == "metroliza-windows-candidate-core-v1"
                and type(payload.get("schema_version")) is int and payload["schema_version"] == 1
                and payload.get("scenario") == "core" and payload.get("status") == "failed"
                and type(payload.get("stage")) is str and payload["stage"] in _CHILD_FAILURE_STAGES
                and (expected_source_sha is None or payload.get("source_sha") == expected_source_sha)
                and type(payload.get("failure")) is str):
            failure = payload["failure"]
            observation["producer_stage"] = payload["stage"]
            base_fields = {"schema", "schema_version", "scenario", "status", "stage", "source_sha", "failure"}
            if failure == "literal_workbook_checks_failed":
                from metroliza.app.windows_candidate_xlsx import _SAFE_FAILURE_CODES, _SAFE_FAILURE_STAGES

                code = payload.get("xlsx_failure")
                substage = payload.get("xlsx_failure_stage")
                if (set(payload) != base_fields | {"xlsx_failure", "xlsx_failure_stage"}
                        or type(code) is not str or code not in _SAFE_FAILURE_CODES | {"operation_failed"}
                        or type(substage) is not str or substage not in _SAFE_FAILURE_STAGES | {"unavailable"}):
                    return observation
                observation["xlsx_failure"] = code
                observation["xlsx_failure_stage"] = substage
            elif set(payload) != base_fields:
                return observation
            if failure in _CLOSED_CHILD_FAILURES:
                observation["receipt_state"] = "valid_allowlisted"
                observation["allowlisted_failure"] = failure
                observation["reason"] = "package_scenario_nonzero_exit_" + failure
            else:
                observation["receipt_state"] = "valid_unclassified"
                observation["reason"] = "package_scenario_nonzero_exit_receipt_unclassified"
    return observation


def _retain_child_failure_observation(observation: dict, child: dict, marker: dict) -> None:
    observation.update({
        key: child[key] for key in ("receipt_state", "producer_stage", "allowlisted_failure")
    })
    for key in ("xlsx_failure", "xlsx_failure_stage"):
        if key in child:
            observation[key] = child[key]
    observation["stage_marker_state"] = marker["stage_marker_state"]


def _closed_child_exit_reason(work: Path) -> str:
    return _child_failure_observation(work)["reason"]


def _child_stage_observation(work: Path, expected_source_sha: str) -> dict[str, str]:
    observation = {"stage_marker_state": "invalid", "producer_stage": "unavailable"}
    try:
        payload = _json(work / STAGE_FILE, 1024)
    except FileNotFoundError:
        observation["stage_marker_state"] = "missing"
    except (CandidateFailure, OSError, ValueError, TypeError):
        pass
    else:
        if (type(payload) is dict
                and set(payload) == {"schema_version", "scenario", "stage", "source_sha"}
                and type(payload.get("schema_version")) is int and payload["schema_version"] == 1
                and payload["scenario"] == "core" and payload["source_sha"] == expected_source_sha
                and type(payload["stage"]) is str and payload["stage"] in _CHILD_FAILURE_STAGES):
            observation.update(stage_marker_state="valid", producer_stage=payload["stage"])
    return observation


def _reopen_failure_observation(root: Path, expected_source_sha: str) -> dict[str, str]:
    observation = {"receipt_state": "invalid", "producer_stage": "unavailable"}
    try:
        payload = _json(root / "fresh-reopen-result.json")
    except FileNotFoundError:
        observation["receipt_state"] = "missing"
    except (CandidateFailure, OSError, ValueError, TypeError):
        pass
    else:
        if (type(payload) is dict and payload.get("schema_version") == 1
                and type(payload.get("schema_version")) is int
                and payload.get("scenario") == "reopen" and payload.get("status") == "failed"
                and payload.get("source_sha") == expected_source_sha
                and type(payload.get("failure_stage")) is str
                and payload["failure_stage"] in _REOPEN_FAILURE_STAGES):
            observation.update(receipt_state="valid_reopen_failed", producer_stage=payload["failure_stage"])
    return observation


def _guard_private_core(action, stage: dict[str, str], failures: list[CandidateFailure]):
    try:
        return action()
    except CandidateFailure as error:
        failures.append(error)
    except Exception as error:
        if getattr(error, "qualification_cleanup", None) == "failed":
            prior = stage.get("before_cleanup", stage["name"])
            code = prior if prior in _PRIVATE_CORE_STAGES else "private_core_unknown"
            failures.append(CandidateFailure("private_process_cleanup_failed_at_" + code))
        else:
            failures.append(_closed_unexpected_stage(stage["name"]))
    return None


def _close_private_core_owned(diag, owned, *, terminate: bool, stage: dict[str, str],
                              failure_observation: dict | None = None) -> None:
    primary = sys.exc_info()[1]
    try:
        diag._close_owned_processes(owned, terminate=terminate)
    except Exception as error:
        if failure_observation is not None:
            if getattr(error, "qualification_cleanup", None) != "complete":
                failure_observation["owned_cleanup"] = "failed"
            elif failure_observation["owned_cleanup"] != "failed":
                failure_observation["owned_cleanup"] = "complete"
        # The diagnostics helper intentionally hides arbitrary primary errors
        # with QualificationFailure("unexpected") even when cleanup succeeded.
        # Keep our already-closed core reason; a failed cleanup still wins.
        qualification = getattr(diag, "QualificationFailure", ())
        if (isinstance(primary, Exception) and isinstance(error, qualification)
                and error.qualification_reason == "unexpected"
                and error.qualification_cleanup == "complete"):
            raise primary from None
        stage["before_cleanup"] = stage["name"]
        stage["name"] = "cleanup"
        raise
    else:
        if failure_observation is not None and failure_observation["owned_cleanup"] != "failed":
            failure_observation["owned_cleanup"] = "complete"


def _run_private_directory_closed(diag, action, failure_observation: dict | None = None):
    try:
        result = diag._run_in_private_directory(action)
    except diag.QualificationFailure as error:
        if failure_observation is not None:
            failure_observation["private_cleanup"] = error.qualification_cleanup
        reason = error.qualification_reason
        if reason == "qualification_cleanup_failed" or error.qualification_cleanup == "failed":
            raise CandidateFailure("private_root_cleanup_failed") from None
        if reason == "invalid_qualification_root":
            raise CandidateFailure("private_root_unavailable") from None
        raise CandidateFailure("unexpected_private_root_wrapper") from None
    if failure_observation is not None:
        failure_observation["private_cleanup"] = "complete"
    return result


def _regular(path: Path) -> bool:
    info = path.lstat()
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and not getattr(info, "st_file_attributes", 0) & 0x400
    )


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CandidateFailure("duplicate_receipt_field")
        result[key] = value
    return result


def _json(path: Path, maximum: int = MAX_RECEIPT_BYTES):
    if not _regular(path) or path.stat().st_size > maximum:
        raise CandidateFailure("unsafe_or_oversized_receipt")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise CandidateFailure("unsafe_or_oversized_receipt")
    return json.loads(data, object_pairs_hook=_unique)


def _hash(path: Path) -> str:
    if not _regular(path) or path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise CandidateFailure("unsafe_or_oversized_scenario_artifact")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        remaining = MAX_ARTIFACT_BYTES + 1
        while remaining:
            block = stream.read(min(65536, remaining))
            if not block:
                break
            digest.update(block)
            remaining -= len(block)
    if not remaining:
        raise CandidateFailure("unsafe_or_oversized_scenario_artifact")
    return digest.hexdigest()


def _directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise CandidateFailure("unsafe_scenario_directory")


def _input_directory(path: Path) -> Path:
    if not path.is_absolute():
        raise CandidateFailure("absolute_input_directory_required")
    # Check the supplied path before resolving it so a junction/symlink in any
    # parent cannot be hidden by Path.resolve().
    for component in (path, *path.parents):
        _directory(component)
    return path.resolve(strict=True)


def _validate_core_result(payload: object) -> dict:
    """Validate the closed scenario payload independently of runtime identity."""
    if type(payload) is not dict or type(payload.get("schema_version")) is not int:
        raise CandidateFailure("invalid_runtime_receipt")
    if payload["schema_version"] != 1:
        raise CandidateFailure("invalid_runtime_receipt")
    if payload.get("stage") != "complete" or payload.get("status") != "passed":
        raise CandidateFailure("scenario_incomplete")
    if payload.get("checks") != CORE_OBSERVATIONS:
        raise CandidateFailure("core_observation_state_mismatch")
    relative = payload.get("relative_artifact_dir")
    if type(relative) is not str or re.fullmatch(r"core-[0-9a-f]{32}", relative) is None:
        raise CandidateFailure("invalid_artifact_directory")
    checks = payload.get("facets")
    if (
        type(checks) is not dict
        or set(checks) != set(REQUIRED_CHECKS) | {"group_analysis_status"}
        or checks.get("group_analysis_status") != "insufficient_groups"
        or any(checks.get(key) != "passed" for key in REQUIRED_CHECKS)
    ):
        raise CandidateFailure("required_core_check_incomplete")
    _validate_core_artifacts(payload.get("artifacts"))
    _validate_import_guard_evidence(payload.get("import_guard_evidence"))
    _validate_ui_observation(payload.get("ui_observation"))
    _validate_ocr_observation(payload.get("ocr_observation"))
    _validate_native_observation(payload.get("native_observation"))
    _validate_closeout_observation(payload.get("closeout_observation"))
    return payload


def _validate_closeout_observation(value, *, packaged=False, expected_dpr=None):
    from scripts.verify_windows_candidate_closeout import validate
    try:
        return validate(value, packaged=packaged, expected_dpr=expected_dpr)
    except (ValueError, TypeError, KeyError):
        raise CandidateFailure("invalid_closeout_observation") from None


def _validate_native_observation(value, *, packaged=False, expected_mode=None):
    if (type(value) is not dict or set(value) != {
        "mode", "runtime_context", "bindings", "available_before", "forced_unavailable", "restored"
    } or value["mode"] not in ("default", "unavailable")
            or value["runtime_context"] not in ("source", "packaged")
            or value["bindings"] != list(NATIVE_BINDINGS)
            or type(value["available_before"]) is not int or not 0 <= value["available_before"] <= 16
            or type(value["forced_unavailable"]) is not int
            or value["forced_unavailable"] != (16 if value["mode"] == "unavailable" else 0)
            or value["restored"] is not True):
        raise CandidateFailure("invalid_native_observation")
    if expected_mode is not None and value["mode"] != expected_mode:
        raise CandidateFailure("native_mode_mismatch")
    if packaged and (value["runtime_context"] != "packaged" or value["available_before"] != 16):
        raise CandidateFailure("packaged_native_bindings_missing")
    return value


def _ocr_oracle():
    return _adjacent_module("verify_windows_candidate_ocr.py", "_metroliza_candidate_ocr_oracle")


def _validate_ocr_observation(value: object, *, packaged: bool = False) -> dict:
    try:
        return _ocr_oracle().validate(value, packaged=packaged)
    except ValueError as error:
        raise CandidateFailure(str(error)) from None


def _validate_ui_observation(value: object, *, expected_dpr: float | None = None) -> dict:
    if (type(value) is not dict or set(value) != {"schema_version", "status", "facets", "error_codes", "evidence"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["error_codes"] != [] or value["status"] not in {"passed", "partial"}):
        raise CandidateFailure("invalid_ui_observation")
    facets = value["facets"]
    if (type(facets) is not dict or set(facets) != {
            "private_dashboard_generation", "offline_html_source", "industrial_geometry", "browser_rendering"}
            or facets["private_dashboard_generation"] != "passed"
            or facets["offline_html_source"] != "passed" or facets["browser_rendering"] != "not_assessed"
            or facets["industrial_geometry"] not in {"passed", "not_assessed"}
            or (value["status"] == "passed") != (facets["industrial_geometry"] == "passed")):
        raise CandidateFailure("invalid_ui_observation")
    evidence = value["evidence"]
    if (type(evidence) is not dict or set(evidence) != {
            "relative_artifact_dir", "screen", "sample_count", "dashboard_sha256", "retained_html",
            "owned_handle_observed", "private_directory_removed_after_close", "dialog_geometry", "browser_rendered"}
            or type(evidence["relative_artifact_dir"]) is not str
            or re.fullmatch(r"ui-checks-[0-9a-f]{32}", evidence["relative_artifact_dir"]) is None
            or type(evidence["sample_count"]) is not int or evidence["sample_count"] != 2
            or evidence["retained_html"] != "dashboard.html"
            or evidence["private_directory_removed_after_close"] is not True
            or evidence["browser_rendered"] is not False
            or type(evidence["dashboard_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", evidence["dashboard_sha256"]) is None):
        raise CandidateFailure("invalid_ui_observation")
    if expected_dpr is not None:
        screen = evidence["screen"]
        geometry = evidence["dialog_geometry"]
        if (value["status"] != "passed" or evidence["owned_handle_observed"] is not True
                or type(screen) is not dict or set(screen) != {"qpa", "dpr", "physical_screen", "logical_screen"}
                or screen["qpa"] != "windows" or type(screen["dpr"]) not in {int, float}
                or not 0.95 <= screen["dpr"] <= 1.55
                or abs(screen["dpr"] - expected_dpr) > 0.05
                or screen["physical_screen"] != [1920, 1080]
                or type(screen["logical_screen"]) is not list or len(screen["logical_screen"]) != 2
                or any(type(size) is not int or not 1 <= size <= 1920 for size in screen["logical_screen"])
                or type(geometry) is not dict or set(geometry) != {"industrial_data", "source_profiles", "industrial_sync"}):
            raise CandidateFailure("native_ui_observation_incomplete")
        for dimensions in geometry.values():
            if (type(dimensions) is not dict or set(dimensions) != {"client", "frame"}
                    or any(type(dimensions[key]) is not list or len(dimensions[key]) != 2
                           or any(type(size) is not int or not 1 <= size <= 1920 for size in dimensions[key])
                           for key in ("client", "frame"))):
                raise CandidateFailure("invalid_ui_geometry")
    return evidence


def _retain_ui_dashboard(child: Path, payload: dict, output: Path) -> dict:
    evidence = _validate_ui_observation(payload.get("ui_observation"))
    directory = child / evidence["relative_artifact_dir"]
    _directory(directory)
    source = directory / "dashboard.html"
    before = _hash(source)
    if before != evidence["dashboard_sha256"]:
        raise CandidateFailure("dashboard_hash_mismatch")
    raw = source.read_bytes()
    if (len(raw) > 1024 * 1024 or not raw.startswith(b"<!doctype html>")
            or b'data-section="signal-charts"' not in raw or b"cycle_time_s" not in raw or b"10.25" not in raw
            or any(marker in raw.lower() for marker in (b"http://", b"https://", b"<script", b"<link", b"fetch(", b"xmlhttprequest"))):
        raise CandidateFailure("dashboard_source_invalid")
    target = output / "dashboard.html"
    with target.open("xb") as stream:
        stream.write(raw)
    if _hash(source) != before or _hash(target) != before:
        raise CandidateFailure("dashboard_changed_during_copy")
    return {"path": target.name, "sha256": before}


def _validate_import_guard_evidence(record: object) -> dict:
    keys = {
        "relative_artifact_dir", "initial_imported", "duplicate_count", "drift_rejected",
        "cancelled_files", "cancel_barrier_stage", "committed_database_sha256",
        "committed_logical_sha256", "database_sha256_after_close", "sidecars_after_window_close",
        "source_hashes",
    }
    if type(record) is not dict or set(record) != keys:
        raise CandidateFailure("invalid_import_guard_evidence")
    if (type(record["relative_artifact_dir"]) is not str
            or re.fullmatch(r"import-guards-[0-9a-f]{32}", record["relative_artifact_dir"]) is None
            or any(type(record[key]) is not int or record[key] != value for key, value in
                   (("initial_imported", 2), ("duplicate_count", 2), ("drift_rejected", 1)))
            or type(record["cancelled_files"]) is not int or not 1 <= record["cancelled_files"] <= 3
            or record["cancel_barrier_stage"] != "real_parse_batch_entry"):
        raise CandidateFailure("invalid_import_guard_evidence")
    for key in ("committed_database_sha256", "committed_logical_sha256", "database_sha256_after_close"):
        if type(record[key]) is not str or re.fullmatch(r"[0-9a-f]{64}", record[key]) is None:
            raise CandidateFailure("invalid_import_guard_evidence")
    sidecars = record["sidecars_after_window_close"]
    if (type(sidecars) is not list or len(sidecars) > 2
            or any(type(item) is not str or item not in {"-wal", "-shm"} for item in sidecars)
            or len(set(sidecars)) != len(sidecars)):
        raise CandidateFailure("invalid_import_guard_evidence")
    sources = record["source_hashes"]
    expected_sources = {f"REF001_2024-01-01_{i}.pdf": PUBLIC_FIXTURE_HASHES[f"report-{i}.pdf"] for i in range(5)}
    if type(sources) is not dict or sources != expected_sources:
        raise CandidateFailure("invalid_import_guard_evidence")
    return record


def _verify_import_guard_outputs(child: Path, payload: dict, output: Path, oracle: Path) -> dict:
    record = _validate_import_guard_evidence(payload.get("import_guard_evidence"))
    guard = child / record["relative_artifact_dir"]
    _directory(guard)
    reports = guard / "reports"
    _directory(reports)
    if {path.name for path in reports.iterdir()} != set(record["source_hashes"]):
        raise CandidateFailure("import_guard_sources_changed")
    if any(_hash(reports / name) != digest for name, digest in record["source_hashes"].items()):
        raise CandidateFailure("import_guard_sources_changed")
    database = guard / "reports.sqlite"
    sidecars_before = _inert_import_guard_sidecars(database, "import_guard_database_sidecars_remain")
    before = _hash(database)
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
        logical = hashlib.sha256("\n".join(connection.iterdump()).encode("utf-8")).hexdigest()
    if logical != record["committed_logical_sha256"]:
        raise CandidateFailure("import_guard_committed_database_changed")
    _assert_import_guard_unchanged(database, before, sidecars_before,
                                   "import_guard_observation_changed_database")
    verifier = _adjacent_module("verify_synthetic_oracle.py", "_metroliza_import_guard_oracle")
    expected = verifier._load_oracle(oracle)
    retained = output / "import-guards.sqlite"
    with database.open("rb") as source, retained.open("xb") as destination:
        shutil.copyfileobj(source, destination)
    _assert_import_guard_unchanged(database, before, sidecars_before,
                                   "import_guard_observation_changed_database")
    if _hash(retained) != before:
        raise CandidateFailure("import_guard_retained_database_changed")
    # The independent oracle requires a sidecar-free file. A zero-byte WAL
    # contains no uncheckpointed pages, so this exact-byte copy is equivalent
    # to the immutable snapshot checked above.
    try:
        verifier.assert_database(expected, retained)
    except Exception:
        raise CandidateFailure("retained_import_guard_oracle_failed") from None
    if _hash(retained) != before:
        raise CandidateFailure("import_guard_retained_database_changed")
    _assert_import_guard_unchanged(database, before, sidecars_before,
                                   "import_guard_database_sidecars_created")
    if any(_hash(reports / name) != digest for name, digest in record["source_hashes"].items()):
        raise CandidateFailure("import_guard_sources_changed")
    return {"path": retained.name, "sha256": before}


def _validate_core_artifacts(artifacts: object) -> None:
    if type(artifacts) is not dict or set(artifacts) != set(ARTIFACTS):
        raise CandidateFailure("missing_scenario_artifact")
    seen = set()
    for record in artifacts.values():
        if type(record) is not dict or set(record) != {"path", "sha256"}:
            raise CandidateFailure("invalid_artifact_record")
        name, digest = record["path"], record["sha256"]
        if (
            type(name) is not str
            or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}\.(sqlite|xlsx|json)", name) is None
            or name in seen
            or type(digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise CandidateFailure("invalid_artifact_record")
        seen.add(name)


def validate_runtime_receipt(payload: object, expected_source: str, *, native_mode="default") -> dict:
    """Reject source-only, partial, stale, elevated and offscreen observations."""
    result = _validate_core_result(payload)
    if result.get("packaged") is not True:
        raise CandidateFailure("source_execution_is_not_package_evidence")
    if result.get("qpa") != "windows" or result.get("ordinary_user") is not True:
        raise CandidateFailure("native_ordinary_user_evidence_missing")
    if result.get("source_sha") != expected_source:
        raise CandidateFailure("runtime_source_mismatch")
    _validate_ocr_observation(result.get("ocr_observation"), packaged=True)
    _validate_native_observation(result.get("native_observation"), packaged=True, expected_mode=native_mode)
    return result


def _source_driver(checkout: Path, source_sha: str):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=checkout, text=True).strip()

    if git("rev-parse", "HEAD") != source_sha or git("status", "--porcelain"):
        raise CandidateFailure("source_checkout_not_exact_and_clean")
    module_path = checkout / "scripts" / "qualify_windows_diagnostics.py"
    if not module_path.is_file():
        raise CandidateFailure("required_diagnostics_driver_not_integrated")
    sys.path[:0] = [str(checkout / "src"), str(checkout)]
    module = importlib.import_module("scripts.qualify_windows_diagnostics")
    if Path(module.__file__).resolve() != module_path.resolve():
        raise CandidateFailure("driver_import_identity_mismatch")
    return module



def _stage_known_fixtures(fixtures: Path, private: Path) -> Path:
    """Copy only the previously authored public byte set into the private job."""
    expected = PUBLIC_FIXTURE_HASHES
    if {p.name for p in fixtures.iterdir()} != {"reports", "finite-source.csv", "integer-precision.csv"}:
        raise CandidateFailure("prepared_fixture_set_mismatch")
    reports = _input_directory(fixtures / "reports")
    if {p.name for p in reports.iterdir()} != {f"report-{i}.pdf" for i in range(5)}:
        raise CandidateFailure("prepared_fixture_set_mismatch")
    output = private / "known public fixtures"
    output.mkdir()
    for name, digest in expected.items():
        source = (reports if name.endswith(".pdf") else fixtures) / name
        if _hash(source) != digest:
            raise CandidateFailure("prepared_fixture_hash_mismatch")
        target = output / name
        with source.open("rb") as original, target.open("xb") as copied:
            shutil.copyfileobj(original, copied)
        if _hash(target) != digest:
            raise CandidateFailure("prepared_fixture_copy_mismatch")
    return output


def _stage_ocr_fixture(checkout: Path, private: Path) -> Path:
    oracle = _ocr_oracle()
    folder = _input_directory(checkout / "tests" / "fixtures" / "windows_candidate_ocr")
    source = folder / oracle.FIXTURE_NAME
    if _hash(source) != oracle.FIXTURE_SHA256:
        raise CandidateFailure("prepared_ocr_fixture_hash_mismatch")
    target = private / oracle.FIXTURE_NAME
    with source.open("rb") as original, target.open("xb") as copied:
        shutil.copyfileobj(original, copied)
    if _hash(target) != oracle.FIXTURE_SHA256:
        raise CandidateFailure("prepared_ocr_fixture_copy_mismatch")
    return target


def _adjacent_module(filename: str, name: str):
    path = Path(__file__).with_name(filename).resolve(strict=True)
    digest = _hash(path)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CandidateFailure("independent_verifier_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if Path(module.__file__).resolve() != path or _hash(path) != digest:
        raise CandidateFailure("independent_verifier_identity_changed")
    return module


def _independent_verifier():
    return _adjacent_module("verify_synthetic_oracle.py", "_metroliza_independent_candidate_oracle").verify


def _independent_xlsx_verifier():
    # Only the standalone standard-library OOXML comparator is called here.
    return _adjacent_module("windows_candidate_xlsx.py", "_metroliza_independent_xlsx_oracle")._verify_workbook


def _independent_inference_verifier():
    return _adjacent_module("verify_group_inference.py", "_metroliza_independent_inference_oracle").verify


def _assert_artifact_hashes(paths: dict, payload: dict, reason: str) -> None:
    if any(_hash(paths[key]) != payload["artifacts"][key]["sha256"] for key in ARTIFACTS):
        raise CandidateFailure(reason)


def _assert_database_sidecars_absent(database: Path, reason: str) -> None:
    if any(database.with_name(database.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise CandidateFailure(reason)


def _inert_import_guard_sidecars(database: Path, reason: str) -> dict[str, str]:
    """Accept only no sidecars or SQLite's inert, closed WAL/SHM pair."""
    paths = {suffix: database.with_name(database.name + suffix)
             for suffix in ("-wal", "-shm", "-journal")}
    if paths["-journal"].exists() or paths["-journal"].is_symlink():
        raise CandidateFailure(reason)
    present = {suffix for suffix in ("-wal", "-shm")
               if paths[suffix].exists() or paths[suffix].is_symlink()}
    if present not in (set(), {"-wal", "-shm"}):
        raise CandidateFailure(reason)
    if not present:
        return {}
    wal, shm = paths["-wal"], paths["-shm"]
    if not _regular(wal) or not _regular(shm) or wal.stat().st_size != 0 or shm.stat().st_size != 32768:
        raise CandidateFailure(reason)
    return {suffix: _hash(paths[suffix]) for suffix in ("-wal", "-shm")}


def _assert_import_guard_unchanged(database: Path, expected_hash: str,
                                   expected_sidecars: dict[str, str], reason: str) -> None:
    if (_hash(database) != expected_hash
            or _inert_import_guard_sidecars(database, reason) != expected_sidecars):
        raise CandidateFailure(reason)


def _assert_both_databases_closed(paths: dict, reason: str) -> None:
    for key in ("database", "inference_database"):
        _assert_database_sidecars_absent(paths[key], reason)


def _check_inference_outputs(paths: dict) -> None:
    try:
        _independent_inference_verifier()(paths["inference_database"], paths["group_inference"])
    except Exception:
        raise CandidateFailure("independent_inference_oracle_failed") from None


def _copy_verified_results(work: Path, payload: dict, output: Path, oracle: Path) -> dict:
    child = work / payload["relative_artifact_dir"]
    _directory(child)
    actual = {}
    for key, record in payload["artifacts"].items():
        source = child / record["path"]
        if _hash(source) != record["sha256"]:
            raise CandidateFailure("scenario_artifact_hash_mismatch")
        actual[key] = source
    _assert_both_databases_closed(actual, "database_sidecars_remain")
    # This verifier imports no Metroliza and does not derive expected values
    # from application output. Its independent expected inputs were reviewed.
    verify = _independent_verifier()
    try:
        verify(oracle, actual["database"], actual["workbook"], actual["grouping"], actual["tabular"])
    except Exception:
        raise CandidateFailure("independent_core_oracle_failed") from None
    verify_xlsx = _independent_xlsx_verifier()
    try:
        verify_xlsx(actual["literal_workbook"])
    except Exception:
        raise CandidateFailure("independent_literal_workbook_oracle_failed") from None
    _check_inference_outputs(actual)
    _assert_artifact_hashes(actual, payload, "scenario_artifact_changed_after_comparison")
    _assert_both_databases_closed(actual, "scenario_database_sidecars_created_after_comparison")
    copied = {}
    for key, source in actual.items():
        destination = output / payload["artifacts"][key]["path"]
        with source.open("rb") as original, destination.open("xb") as target:
            shutil.copyfileobj(original, target, length=65536)
        digest = _hash(destination)
        if digest != payload["artifacts"][key]["sha256"]:
            raise CandidateFailure("copied_artifact_hash_mismatch")
        copied[key] = {"path": destination.name, "sha256": digest}
    try:
        verify(oracle, *(output / copied[key]["path"] for key in ARTIFACTS[:4]))
        verify_xlsx(output / copied["literal_workbook"]["path"])
    except Exception:
        raise CandidateFailure("retained_outputs_oracle_failed") from None
    retained = {key: output / copied[key]["path"] for key in ARTIFACTS}
    _check_inference_outputs(retained)
    _assert_artifact_hashes(retained, payload, "retained_artifact_changed_after_comparison")
    _assert_both_databases_closed(retained, "retained_database_sidecars_created_after_comparison")
    copied["import_guards_database"] = _verify_import_guard_outputs(child, payload, output, oracle)
    copied["private_dashboard"] = _retain_ui_dashboard(child, payload, output)
    return copied


def _prepare_paths(args) -> tuple[Path, Path, Path, Path]:
    checkout = _input_directory(args.source_checkout)
    artifact = _input_directory(args.artifact_dir)
    fixtures = _input_directory(args.fixture_dir)
    if not args.output_dir.is_absolute():
        raise CandidateFailure("absolute_output_directory_required")
    output = args.output_dir
    if output.exists():
        raise CandidateFailure("output_must_be_new")
    for parent in (artifact, checkout, fixtures):
        if output == parent or parent in output.parents:
            raise CandidateFailure("output_must_be_outside_inputs")
    _input_directory(output.parent)
    return checkout, artifact, fixtures, output


def _verify_dashboard_rendering(diag, output: Path, artifacts: dict, browser: Path) -> None:
    verifier = _adjacent_module("verify_windows_candidate_dashboard.py", "_metroliza_candidate_browser_verifier")
    dashboard = artifacts["private_dashboard"]
    observations = []

    def render(private):
        observations.append(verifier.verify_dashboard(
            output / dashboard["path"], dashboard["sha256"], browser, private
        ))

    diag._run_in_private_directory(render)
    try:
        result = verifier.validate_receipt(observations[0], dashboard["sha256"], require_windows=True)
    except (ValueError, IndexError):
        raise CandidateFailure("offline_browser_verification_failed") from None
    path = output / "browser-observation.json"
    with path.open("x", encoding="ascii") as stream:
        json.dump(result, stream, sort_keys=True)
    artifacts["browser_evidence"] = {"path": path.name, "sha256": _hash(path)}


def _verify_dashboard_closed(diag, output: Path, artifacts: dict, browser: Path) -> None:
    try:
        _verify_dashboard_rendering(diag, output, artifacts, browser)
    except CandidateFailure:
        raise
    except Exception:
        raise CandidateFailure("unexpected_browser_verifier") from None


def _closed_value(value: object, allowed: frozenset[str] | set[str], fallback: str) -> str:
    return value if type(value) is str and value in allowed else fallback


def _failed_diagnostic_payload(observation: dict, stage: dict[str, str], error: CandidateFailure,
                               expected_source_sha: str) -> dict:
    role = _closed_value(observation.get("observed_process"),
                         {"requested_launcher_handle", "fresh_reopen_launcher_handle"}, "unavailable")
    code = observation.get("observed_exit_code")
    if type(code) is not int or not 0 <= code <= 2**32 - 1:
        code = None
    marker = _closed_value(observation.get("startup_marker"), {"observed", "not_observed"}, "unavailable")
    receipt_state = _closed_value(observation.get("receipt_state"), {
        "not_checked", "missing", "invalid", "valid_allowlisted", "valid_unclassified",
        "valid_reopen_failed", "valid_success",
    }, "not_checked")
    stage_marker_state = _closed_value(observation.get("stage_marker_state"),
                                       {"not_checked", "missing", "invalid", "valid"}, "not_checked")
    producer_stage = _closed_value(observation.get("producer_stage"),
                                   _CHILD_FAILURE_STAGES | _REOPEN_FAILURE_STAGES, "unavailable")
    failure_code = _closed_value(observation.get("allowlisted_failure"), _CLOSED_CHILD_FAILURES, "unavailable")
    from metroliza.app.windows_candidate_xlsx import _SAFE_FAILURE_CODES, _SAFE_FAILURE_STAGES

    xlsx_failure = _closed_value(observation.get("xlsx_failure"),
                                 _SAFE_FAILURE_CODES | {"operation_failed"}, "unavailable")
    xlsx_stage = _closed_value(observation.get("xlsx_failure_stage"),
                               _SAFE_FAILURE_STAGES | {"unavailable"}, "unavailable")
    from scripts.windows_owned_process_probe import UNAVAILABLE_SOURCES

    raw_sources = observation.get("probe_unavailable_sources")
    probe_sources = (
        sorted({source for source in raw_sources
                if type(source) is str and source in UNAVAILABLE_SOURCES})
        if type(raw_sources) is list and len(raw_sources) <= len(UNAVAILABLE_SOURCES) else []
    )
    host_stage = _closed_value(stage.get("before_cleanup", stage.get("name")), _PRIVATE_CORE_STAGES, "unavailable")
    owned_cleanup = _closed_value(observation.get("owned_cleanup"), {"not_attempted", "complete", "failed"},
                                  "not_attempted")
    private_cleanup = _closed_value(observation.get("private_cleanup"), {"not_attempted", "complete", "failed"},
                                    "not_attempted")
    reason = str(error)
    if reason == "private_root_cleanup_failed" or owned_cleanup == "failed":
        category = "cleanup_failure"
    elif receipt_state == "valid_allowlisted":
        category = "allowlisted_producer_failure"
    elif receipt_state == "valid_reopen_failed":
        category = "reopen_producer_failure"
    elif receipt_state in {"missing", "invalid", "valid_unclassified"}:
        category = "unclassified_nonzero_exit"
    else:
        category = "closed_driver_failure"
    return {
        "schema_version": 1, "status": "failed",
        "source_sha": expected_source_sha if type(expected_source_sha) is str
        and re.fullmatch(r"[0-9a-f]{40}", expected_source_sha) else "unavailable",
        "observed_process": role, "observed_exit_code": code,
        "host_stage": host_stage, "startup_marker": marker,
        "producer_stage": producer_stage, "stage_marker_state": stage_marker_state,
        "receipt_state": receipt_state,
        "allowlisted_failure": failure_code, "failure_category": category,
        "xlsx_failure": xlsx_failure, "xlsx_failure_stage": xlsx_stage,
        "probe_unavailable_sources": probe_sources,
        "owned_cleanup": owned_cleanup, "private_cleanup": private_cleanup,
    }


def _write_failed_diagnostic(output: Path, payload: dict) -> None:
    data = (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")
    if len(data) > MAX_FAILED_DIAGNOSTIC_BYTES:
        raise CandidateFailure("failed_diagnostic_too_large")
    with (output / FAILED_DIAGNOSTIC_FILE).open("xb") as stream:
        stream.write(data)


def _remove_partial_output(output: Path) -> None:
    try:
        shutil.rmtree(output)
    except OSError:
        raise CandidateFailure("failed_output_cleanup_failed") from None


def _retain_failed_diagnostic(output: Path, payload: dict) -> None:
    _remove_partial_output(output)
    try:
        output.mkdir(mode=0o700)
        _write_failed_diagnostic(output, payload)
    except (OSError, CandidateFailure):
        if output.exists():
            _remove_partial_output(output)
        raise CandidateFailure("failed_diagnostic_write_failed") from None


def _observe_core_startup(work: Path, process, observed: bool, *, scenario="core") -> bool:
    if observed:
        return True
    marker = work / "core-startup.json"
    if not marker.exists():
        return False
    payload = _json(marker, 1024)
    if (payload != {"schema_version": 1, "scenario": scenario, "stage": "startup_ready"}
            or type(payload.get("schema_version")) is not int):
        raise CandidateFailure("invalid_core_startup_receipt")
    process.mark_runtime_ready()
    return True


def _wait_for_launcher_exit(work: Path, process, deadline: float, *, scenario: str,
                            timeout_reason: str, failure_observation: dict | None) -> tuple[int, bool]:
    startup_observed = False
    while time.monotonic() < deadline:
        process.observe()
        startup_observed = _observe_core_startup(work, process, startup_observed, scenario=scenario)
        if startup_observed and failure_observation is not None:
            failure_observation["startup_marker"] = "observed"
        code = process.poll()
        if code is not None:
            if failure_observation is not None:
                failure_observation["observed_exit_code"] = code
            return code, startup_observed
        time.sleep(0.005)
    raise CandidateFailure(timeout_reason)


def _validate_fresh_reopen(payload, prior, expected_source, *, packaged=True, after_hash=None):
    expected_hash = prior["artifacts"]["database"]["sha256"]
    expected = {
        "schema_version": 1, "scenario": "reopen", "status": "passed",
        "packaged": packaged, "qpa": "windows" if packaged else "offscreen",
        "ordinary_user": True, "source_sha": expected_source,
    }
    if (type(payload) is not dict or set(payload) != set(expected) | {"observation"}
            or any(type(payload.get(k)) is not type(v) or payload.get(k) != v for k, v in expected.items())):
        raise CandidateFailure("fresh_reopen_runtime_mismatch")
    observation = payload["observation"]
    expected_database = dict(prior["reopen_database"], sha256=after_hash or expected_hash, before_sha256=expected_hash)
    expected_observation = {
        "schema_version": 1, "status": "passed",
        "facets": {"reopen_preserves_completed_import": "passed"},
        "database": expected_database, "source_hashes": prior["source_hashes"],
    }
    if (type(observation) is not dict or observation != expected_observation
            or type(observation.get("schema_version")) is not int):
        raise CandidateFailure("fresh_reopen_data_mismatch")
    return payload


def _validate_fresh_reopen_evidence(value, before_hash, after_hash, expected_source, diag):
    if (type(value) is not dict
            or set(value) != {"schema_version", "status", "process_boundary", "observation", "topology"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["status"] != "passed"
            or value["process_boundary"] != "new_owned_job_after_initial_job_drained"):
        raise CandidateFailure("fresh_reopen_boundary_not_proved")
    payload = value["observation"]
    observed = payload.get("observation") if type(payload) is dict else None
    database = observed.get("database") if type(observed) is dict else None
    counts = dict.fromkeys(("source_files", "active_locations", "parsed_reports", "metadata", "measurements"), 2)
    if (type(database) is not dict
            or set(database) != {"sha256", "before_sha256", "schema_sha256", "logical_dump_sha256", "counts"}
            or database["counts"] != counts
            or any(type(database[key]) is not str or re.fullmatch(r"[0-9a-f]{64}", database[key]) is None
                   for key in ("sha256", "before_sha256", "schema_sha256", "logical_dump_sha256"))):
        raise CandidateFailure("fresh_reopen_database_observation_invalid")
    prior = {"artifacts": {"database": {"sha256": before_hash}}, "reopen_database": database,
             "source_hashes": {f"REF001_2024-01-01_{i}.pdf": PUBLIC_FIXTURE_HASHES[f"report-{i}.pdf"] for i in range(5)}}
    _validate_fresh_reopen(payload, prior, expected_source, after_hash=after_hash)
    diag._validate_topology_record(value["topology"], supervised=True, require_runtime_evidence=True)


def _reopen_database_semantics(database: Path):
    # Compare every logical statement, including duplicates, plus the complete
    # schema; file bytes may legitimately differ while both are preserved.
    import sqlite3
    from contextlib import closing

    _hash(database)
    _assert_database_sidecars_absent(database, "fresh_reopen_database_sidecar")
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise CandidateFailure("fresh_reopen_database_integrity_failed")
            schema = connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
            ).fetchall()
            statements = sorted(connection.iterdump())
            persistent = (
                connection.execute("PRAGMA user_version").fetchone(),
                connection.execute("PRAGMA application_id").fetchone(),
                connection.execute("PRAGMA encoding").fetchone(),
            )
    except sqlite3.Error:
        raise CandidateFailure("fresh_reopen_database_invalid") from None
    return schema, statements, persistent


def _assert_reopen_databases_preserved(before: Path, after: Path, *, before_hash, after_hash, observation=None):
    for path, expected in ((before, before_hash), (after, after_hash)):
        if _hash(path) != expected:
            raise CandidateFailure("fresh_reopen_database_identity_changed")
    before_semantics = _reopen_database_semantics(before)
    if before_semantics != _reopen_database_semantics(after):
        raise CandidateFailure("fresh_reopen_database_semantics_changed")
    digests = {
        "schema_sha256": hashlib.sha256(json.dumps(before_semantics[0], ensure_ascii=True,
            separators=(",", ":"), default=str).encode("utf-8")).hexdigest(),
        "logical_dump_sha256": hashlib.sha256("\n".join(before_semantics[1]).encode("utf-8")).hexdigest(),
    }
    if observation is not None and any(observation.get(key) != value for key, value in digests.items()):
        raise CandidateFailure("fresh_reopen_database_digest_mismatch")
    for path, expected in ((before, before_hash), (after, after_hash)):
        _assert_database_sidecars_absent(path, "fresh_reopen_database_sidecar")
        if _hash(path) != expected:
            raise CandidateFailure("fresh_reopen_database_identity_changed")
    return digests


def _validate_reopen_sources(reports: Path):
    expected = {f"REF001_2024-01-01_{i}.pdf": PUBLIC_FIXTURE_HASHES[f"report-{i}.pdf"] for i in range(5)}
    _input_directory(reports)
    if ({path.name for path in reports.iterdir()} != set(expected)
            or any(_hash(reports / name) != digest for name, digest in expected.items())):
        raise CandidateFailure("fresh_reopen_sources_changed")


def _run_fresh_reopen(private, *, diag, relocated, environment, work, prior, args, deadline, output, stage,
                      failure_observation=None):
    # The first Job has fully drained before this function creates another Job.
    # A new launcher, application, root and runtime journal prove process reopen.
    root, launch_cwd = private / "fresh reopen", private / "fresh launcher work"
    root.mkdir()
    launch_cwd.mkdir()
    child = work / prior["relative_artifact_dir"]
    database = child / "reports.sqlite"
    expected_hash = prior["artifacts"]["database"]["sha256"]
    if _hash(database) != expected_hash:
        raise CandidateFailure("fresh_reopen_input_changed")
    _assert_database_sidecars_absent(database, "fresh_reopen_database_sidecar")
    _validate_reopen_sources(child / "reports")
    before_database = output / "before-reopen.sqlite"
    with database.open("rb") as source, before_database.open("xb") as destination:
        shutil.copyfileobj(source, destination)
    if _hash(before_database) != expected_hash:
        raise CandidateFailure("fresh_reopen_copy_changed")
    verifier = _independent_verifier()
    verifier.assert_database(verifier._load_oracle(args.oracle), before_database)
    next_environment = dict(environment, METROLIZA_WINDOWS_CANDIDATE_PHASE="reopen",
                            METROLIZA_WINDOWS_CANDIDATE_ROOT=str(root),
                            METROLIZA_WINDOWS_CANDIDATE_REOPEN_INPUT=str(child),
                            METROLIZA_WINDOWS_CANDIDATE_REOPEN_SHA256=expected_hash)
    owned = []
    terminate = True
    if failure_observation is not None:
        failure_observation.update({
            "observed_process": "unavailable", "observed_exit_code": None,
            "startup_marker": "not_observed", "receipt_state": "not_checked",
            "stage_marker_state": "not_checked", "producer_stage": "unavailable",
            "allowlisted_failure": "unavailable",
        })
    try:
        process = diag._WindowsApi().launch(
            relocated / "metroliza.exe", next_environment, launch_cwd, owned=owned,
            expected_images=(relocated / "metroliza.exe", relocated / "metroliza_application.exe"),
        )
        if failure_observation is not None:
            failure_observation["observed_process"] = "fresh_reopen_launcher_handle"
        code, observed = _wait_for_launcher_exit(
            root, process, deadline, scenario="reopen", timeout_reason="fresh_reopen_process_timeout",
            failure_observation=failure_observation,
        )
        if code != 0:
            if failure_observation is not None:
                failure_observation.update(_reopen_failure_observation(root, args.expected_source_sha))
            raise CandidateFailure("fresh_reopen_process_failed")
        if not observed:
            raise CandidateFailure("fresh_reopen_process_failed")
        if not diag._wait_for_job_exit(process, deadline):
            raise CandidateFailure("fresh_reopen_owned_processes_remain")
        after_hash = _hash(database)
        payload = _validate_fresh_reopen(
            _json(root / "fresh-reopen-result.json"), prior, args.expected_source_sha, after_hash=after_hash
        )
        topology = diag._topology_record(process.topology(relocated, all_exited=True))
        diag._validate_topology_record(topology, supervised=True, require_runtime_evidence=True)
        _assert_reopen_databases_preserved(before_database, database, before_hash=expected_hash, after_hash=after_hash,
                                         observation=payload["observation"]["database"])
        _validate_reopen_sources(child / "reports")
        verifier.assert_database(verifier._load_oracle(args.oracle), database)
        result = {"schema_version": 1, "status": "passed", "process_boundary": "new_owned_job_after_initial_job_drained",
                  "observation": payload, "topology": topology}
        destination = output / "fresh-reopen-observation.json"
        with destination.open("x", encoding="ascii") as stream:
            json.dump(result, stream, sort_keys=True)
        terminate = False
        return {
            "fresh_reopen_evidence": {"path": destination.name, "sha256": _hash(destination)},
            "before_reopen_database": {"path": before_database.name, "sha256": expected_hash},
        }
    finally:
        _close_private_core_owned(
            diag, owned, terminate=terminate, stage=stage,
            failure_observation=failure_observation,
        )


def _validated_core_payload(work: Path, args, failure_observation: dict | None):
    result_path = work / SCENARIO_FILE
    if not result_path.exists():
        raise CandidateFailure("package_core_hook_or_receipt_missing")
    payload = validate_runtime_receipt(_json(result_path), args.expected_source_sha, native_mode=args.native_mode)
    if failure_observation is not None:
        failure_observation.update(receipt_state="valid_success", producer_stage="complete")
    return payload


def _verified_core_topology(diag, process, relocated: Path, failure_observation: dict | None):
    try:
        topology = process.topology(relocated, all_exited=True)
        # The accepted dependency checks both launcher processes plus the
        # fixed OCR worker; a failed probe remains a hard topology failure.
        diag._validate_topology_record(diag._topology_record(topology), supervised=True,
                                       require_runtime_evidence=True, allow_ocr_worker=True)
    except diag.QualificationFailure:
        if failure_observation is not None:
            evidence = getattr(process, "runtime_evidence", None)
            sources = getattr(getattr(evidence, "probe", None), "unavailable_sources", None)
            failure_observation["probe_unavailable_sources"] = sorted(sources) if type(sources) is set else []
        raise
    return topology


def _run_private_core(private: Path, *, args, diag, artifact: Path, fixtures: Path,
                      output: Path, deadline: float, before: str, stage: dict[str, str],
                      failure_observation: dict | None = None) -> dict:
    stage["name"] = "package_relocation"
    relocated = diag._relocate_package(artifact, private, deadline)
    stage["name"] = "fixtures"
    staged_fixtures = _stage_known_fixtures(fixtures, private)
    staged_ocr = _stage_ocr_fixture(args.source_checkout, private)
    work = private / "core scenario"
    launch_cwd = private / "launcher work"
    state = private / "ordinary user state"
    work.mkdir()
    launch_cwd.mkdir()
    scratch_temp = private / "temporary files"
    scratch_temp.mkdir()
    (state / "Roaming").mkdir(parents=True)
    environment = diag._sanitized_environment(relocated, work, state, "idle")
    environment.pop("METROLIZA_DIAGNOSTIC_QUALIFICATION", None)
    environment.pop("METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT", None)
    environment.update({
        "QT_QPA_PLATFORM": "windows",
        "QT_SCALE_FACTOR": args.dpi_scale,
        "METROLIZA_WINDOWS_CANDIDATE_DPR": args.dpi_scale,
        "METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION": "1",
        "METROLIZA_WINDOWS_CANDIDATE_ROOT": str(work),
        "METROLIZA_WINDOWS_CANDIDATE_FIXTURE_DIR": str(staged_fixtures),
        "METROLIZA_WINDOWS_CANDIDATE_OCR_FIXTURE": str(staged_ocr),
        "METROLIZA_WINDOWS_CANDIDATE_NATIVE_MODE": args.native_mode,
        "TEMP": str(scratch_temp),
        "TMP": str(scratch_temp),
        "TMPDIR": str(scratch_temp),
    })
    owned = []
    terminate = True
    try:
        stage["name"] = "owned_launch"
        process = diag._WindowsApi().launch(
            relocated / "metroliza.exe", environment, launch_cwd, owned=owned,
            expected_images=(
                relocated / "metroliza.exe", relocated / "metroliza_application.exe",
                relocated / "metroliza_ocr_worker.exe",
            ),
        )
        if failure_observation is not None:
            failure_observation["observed_process"] = "requested_launcher_handle"
        stage["name"] = "runtime_observation"
        code, startup_observed = _wait_for_launcher_exit(
            work, process, deadline, scenario="core", timeout_reason="owned_package_scenario_timeout",
            failure_observation=failure_observation,
        )
        if code != 0:
            child_failure = _child_failure_observation(work, args.expected_source_sha)
            stage_observation = _child_stage_observation(work, args.expected_source_sha)
            if child_failure["receipt_state"] in {"missing", "invalid"}:
                child_failure["producer_stage"] = stage_observation["producer_stage"]
            elif (stage_observation["stage_marker_state"] == "valid"
                  and child_failure["producer_stage"] != stage_observation["producer_stage"]):
                child_failure = {
                    "receipt_state": "invalid", "producer_stage": stage_observation["producer_stage"],
                    "allowlisted_failure": "unavailable",
                    "reason": "package_scenario_nonzero_exit_receipt_invalid",
                }
            if failure_observation is not None:
                _retain_child_failure_observation(
                    failure_observation, child_failure, stage_observation,
                )
            raise CandidateFailure(child_failure["reason"])
        if not startup_observed:
            raise CandidateFailure("core_startup_receipt_missing")
        stage["name"] = "runtime_receipt"
        payload = _validated_core_payload(work, args, failure_observation)
        _validate_ui_observation(payload.get("ui_observation"), expected_dpr=float(args.dpi_scale))
        _validate_closeout_observation(payload.get("closeout_observation"), packaged=True, expected_dpr=float(args.dpi_scale))
        if not diag._wait_for_job_exit(process, deadline):
            raise CandidateFailure("owned_processes_remain")
        stage["name"] = "owned_topology"
        topology = _verified_core_topology(diag, process, relocated, failure_observation)
        stage["name"] = "fresh_reopen"
        fresh_reopen = _run_fresh_reopen(
            private, diag=diag, relocated=relocated, environment=environment, work=work,
            prior=payload, args=args, deadline=deadline, output=output, stage=stage,
            failure_observation=failure_observation,
        )
        stage["name"] = "package_integrity"
        after = diag._tree_digest(diag._package_inventory(relocated))
        if after != before:
            raise CandidateFailure("package_tree_changed_during_scenario")
        stage["name"] = "retained_artifacts"
        payload["artifacts"]["database"]["sha256"] = _hash(work / payload["relative_artifact_dir"] / "reports.sqlite")
        artifacts = _copy_verified_results(work, payload, output, args.oracle)
        artifacts.update(fresh_reopen)
        stage["name"] = "evidence_receipts"
        process_result = output / "process-topology.json"
        with process_result.open("x", encoding="ascii") as stream:
            json.dump(diag._topology_record(topology), stream)
        artifacts["process_evidence"] = {"path": process_result.name, "sha256": _hash(process_result)}
        ocr_result = output / "ocr-observation.json"
        with ocr_result.open("x", encoding="ascii") as stream:
            json.dump(_validate_ocr_observation(payload["ocr_observation"], packaged=True), stream)
        artifacts["ocr_evidence"] = {"path": ocr_result.name, "sha256": _hash(ocr_result)}
        native_result = output / "native-observation.json"
        with native_result.open("x", encoding="ascii") as stream:
            json.dump(payload["native_observation"], stream)
        artifacts["native_evidence"] = {"path": native_result.name, "sha256": _hash(native_result)}
        closeout_result = output / "closeout-observation.json"
        with closeout_result.open("x", encoding="ascii") as stream:
            json.dump(payload["closeout_observation"], stream)
        artifacts["closeout_evidence"] = {"path": closeout_result.name, "sha256": _hash(closeout_result)}
        terminate = False
        return artifacts
    finally:
        _close_private_core_owned(
            diag, owned, terminate=terminate, stage=stage,
            failure_observation=failure_observation,
        )


def qualify(args) -> dict:
    if os.name != "nt":
        raise CandidateFailure("native_windows_required")
    if re.fullmatch(r"[0-9a-f]{40}", args.expected_source_sha) is None:
        raise CandidateFailure("invalid_expected_source_sha")
    checkout, artifact, fixtures, output = _prepare_paths(args)
    try:
        _adjacent_module("verify_windows_candidate_dashboard.py", "_metroliza_candidate_browser_verifier").check_host_runtime(args.browser)
    except ValueError:
        raise CandidateFailure("browser_host_prerequisite_missing") from None
    diag = _source_driver(checkout, args.expected_source_sha)
    identity = diag._validate_package(artifact)
    # The declared build writes the launcher sidecar; the adjacent child is
    # bound through the supervision manifest and its embedded provenance.
    if identity.get("git_sha") != args.expected_source_sha:
        raise CandidateFailure("package_source_mismatch")
    diag._validate_sidecar(artifact / "metroliza.exe", args.expected_source_sha)
    sidecar = _json(artifact / "metroliza.exe.provenance.json", 16 * 1024)
    if sidecar.get("dirty") is not False:
        raise CandidateFailure("dirty_package_provenance")
    notices = diag._validate_notices(artifact / "metroliza.exe")
    before = diag._tree_digest(diag._package_inventory(artifact))
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    deadline = time.monotonic() + MAX_SECONDS

    # Keep our closed failure identifier across the dependency's wrapper, which
    # intentionally replaces unknown exception text. Cleanup still has to pass.
    failures = []
    private_stage = {"name": "package_relocation"}
    failure_observation = {
        "observed_process": "unavailable", "observed_exit_code": None,
        "startup_marker": "not_observed", "receipt_state": "not_checked",
        "stage_marker_state": "not_checked", "producer_stage": "unavailable",
        "allowlisted_failure": "unavailable", "probe_unavailable_sources": [],
        "owned_cleanup": "not_attempted", "private_cleanup": "not_attempted",
    }

    def guarded_run(private):
        return _guard_private_core(
            lambda: _run_private_core(
                private, args=args, diag=diag, artifact=artifact, fixtures=fixtures,
                output=output, deadline=deadline, before=before, stage=private_stage,
                failure_observation=failure_observation,
            ), private_stage, failures,
        )

    try:
        artifacts = _run_private_directory_closed(diag, guarded_run, failure_observation)
        if failures:
            raise failures[0]
        _verify_dashboard_closed(diag, output, artifacts, args.browser)
        result = {
            "schema_version": 1,
            "status": "passed",
            "scope": [*REQUIRED_CHECKS, *CLOSEOUT_CHECKS, "offline_browser_dom_and_layout", "fresh_process_reopen_preserves_completed_import"],
            "source_sha": args.expected_source_sha,
            "ui_scale": args.dpi_scale,
            "native_mode": args.native_mode,
            "native_geometry": "passed",
            "offline_browser_rendering": "passed",
            "source_tree": subprocess.check_output(
                ["git", "rev-parse", "HEAD^{tree}"], cwd=checkout, text=True
            ).strip(),
            "package_tree_sha256": before,
            "launcher_sha256": identity["launcher_sha256"],
            "application_sha256": identity["application_sha256"],
            "artifacts": artifacts,
            "facets": dict.fromkeys((*REQUIRED_CHECKS, *CLOSEOUT_CHECKS, "offline_browser_dom_and_layout", "fresh_process_reopen_preserves_completed_import"), "passed"),
            "independent_oracle": "passed",
            "launch": "restricted_ordinary_user_native_windows_outside_checkout",
            "provenance_validated": bool(identity),
            "notices_validated": bool(notices),
            "notice_hashes": notices,
            "supervision_manifest_sha256": identity["manifest_sha256"],
            "oracle_sha256": _hash(args.oracle),
            "verifier_sha256": _hash(Path(__file__).with_name("verify_synthetic_oracle.py")),
            "driver_sha256": _hash(Path(__file__)),
            "ocr_verifier_sha256": _hash(Path(__file__).with_name("verify_windows_candidate_ocr.py")),
            "closeout_verifier_sha256": _hash(Path(__file__).with_name("verify_windows_candidate_closeout.py")),
            "browser_verifier_sha256": _hash(Path(__file__).with_name("verify_windows_candidate_dashboard.py")),
            "ocr_fixture_sha256": _ocr_oracle().FIXTURE_SHA256,
            "literal_xlsx_verifier_sha256": _hash(Path(__file__).with_name("windows_candidate_xlsx.py")),
            "inference_oracle_sha256": _hash(Path(__file__).with_name("synthetic-inference-oracle.json")),
            "inference_verifier_sha256": _hash(Path(__file__).with_name("verify_group_inference.py")),
            "limits": list(RESULT_LIMITS),
        }
        with (output / "core-driver-receipt.json").open("x", encoding="ascii") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
        return result
    except CandidateFailure as error:
        payload = _failed_diagnostic_payload(failure_observation, private_stage, error, args.expected_source_sha)
        _retain_failed_diagnostic(output, payload)
        raise
    except BaseException:
        _remove_partial_output(output)
        raise



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-checkout", "artifact-dir", "fixture-dir", "output-dir", "oracle", "browser"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--dpi-scale", choices=("1.0", "1.25", "1.5"), default="1.0")
    parser.add_argument("--native-mode", choices=("default", "unavailable"), default="default")
    args = parser.parse_args()
    try:
        qualify(args)
        print(json.dumps({"status": "passed", "scope": [*REQUIRED_CHECKS, *CLOSEOUT_CHECKS, "offline_browser_dom_and_layout", "fresh_process_reopen_preserves_completed_import"]}))
        return 0
    except CandidateFailure as error:
        print(json.dumps({"status": "failed", "reason": str(error)}))
        return 1
    except Exception:
        # Never echo child output, file contents, exception messages or paths.
        print(json.dumps({"status": "failed", "reason": "unexpected_driver_error"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
