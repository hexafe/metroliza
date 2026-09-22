"""Gated core package-acceptance scenario using only synthetic prepared inputs.

This module is inert unless the final Windows launcher enables both gates.  It
uses the ordinary MainWindow Reports workspace, its actual review/import QThreads,
and public report/export/grouping services.  It produces safe artifacts for the
independent oracle; it never treats a source-engineering run as package evidence.
"""
from __future__ import annotations


import hashlib
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path
from metroliza.reports.db import sqlite_readonly_connection_scope

from typing import Any

SCENARIO = "core"
ROOT_ENV = "METROLIZA_WINDOWS_CANDIDATE_ROOT"
FIXTURES_ENV = "METROLIZA_WINDOWS_CANDIDATE_FIXTURE_DIR"
OCR_FIXTURE_ENV = "METROLIZA_WINDOWS_CANDIDATE_OCR_FIXTURE"
GATES = ("METROLIZA_STARTUP_SMOKE", "METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION")
DEADLINES_S = {"review": 30.0, "import": 45.0}
FIXTURES = {
    "finite-source.csv": "de2724bd3b6b55d362016423a2f78168235d3833d7a89298a7fdf4a5ec747938",
    "integer-precision.csv": "8e2c837472d6465d319b37b4afe09998f9c45680edc27d1a169f33e145a70508",
    "report-0.pdf": "183b46650a7e37113927f7a99eb6a66484d07126d3134b3a6056defaef21af3f",
    "report-1.pdf": "315032987a656191260945242c89996976640f3629c4499c428f44ac9b3679ad",
    "report-2.pdf": "7a6fe37457385188f9b466a8f9c3061bf7d118290b0c8e74583dba5e76f29048",
    "report-3.pdf": "cb801c452d9608c227606a4c10325d19d7d8a095fe80976fa60338fd6bfd0849",
    "report-4.pdf": "b9f83ee23a191eccfa3515594e6ba85ede670a2163444cd0daf7b9bb5edd83d9",
}
SELECTED = (1, 3)


class ScenarioFailure(ValueError):
    pass


def requested_scenario() -> str | None:
    if all(os.getenv(name) == "1" for name in GATES):
        phase = os.getenv("METROLIZA_WINDOWS_CANDIDATE_PHASE", SCENARIO)
        return phase if phase in {SCENARIO, "reopen"} else None
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _root() -> Path:
    raw = os.getenv(ROOT_ENV)
    if not raw:
        raise ScenarioFailure("root_missing")
    root = Path(raw)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir() or any(root.iterdir()):
        raise ScenarioFailure("root_not_new_empty_directory")
    return root


def _fixture_dir() -> Path:
    raw = os.getenv(FIXTURES_ENV)
    if not raw:
        raise ScenarioFailure("fixture_dir_missing")
    directory = Path(raw)
    if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise ScenarioFailure("fixture_dir_invalid")
    present = {item.name for item in directory.iterdir() if item.is_file()}
    if present != set(FIXTURES):
        raise ScenarioFailure("fixture_set_mismatch")
    for name, expected_hash in FIXTURES.items():
        if _sha256(directory / name) != expected_hash:
            raise ScenarioFailure("fixture_hash_mismatch")
    return directory


def _ocr_fixture() -> Path:
    raw = os.getenv(OCR_FIXTURE_ENV)
    if not raw:
        raise ScenarioFailure("ocr_fixture_missing")
    fixture = Path(raw)
    if not fixture.is_absolute() or fixture.is_symlink() or not fixture.is_file():
        raise ScenarioFailure("ocr_fixture_invalid")
    return fixture


def _ordinary_user() -> bool:
    if os.name != "nt":
        return os.geteuid() != 0
    import ctypes
    return ctypes.windll.shell32.IsUserAnAdmin() == 0


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    stage = path.with_name(f".{path.name}.{uuid.uuid4().hex}")
    with stage.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True, indent=2)
        stream.write("\n")
    stage.replace(path)


def _runtime_provenance() -> dict[str, Any]:
    try:
        from metroliza.app.build_provenance import load_build_provenance
        value = load_build_provenance()
        return {"source_sha": getattr(value, "git_sha", None), "mode": getattr(value, "mode", None)}
    except Exception:
        return {"source_sha": None, "mode": "unavailable"}


def _wait(app, predicate, *, deadline_s: float, stage: str) -> None:
    deadline = time.monotonic() + deadline_s
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    if not predicate():
        raise ScenarioFailure(f"{stage}_deadline")


def _stage_reports(fixtures: Path, scratch: Path) -> tuple[Path, dict[str, str]]:
    reports = scratch / "reports"
    reports.mkdir()
    hashes: dict[str, str] = {}
    for index in range(5):
        source = fixtures / f"report-{index}.pdf"
        alias = reports / f"REF001_2024-01-01_{index}.pdf"
        shutil.copyfile(source, alias)
        digest = _sha256(alias)
        if digest != FIXTURES[source.name]:
            raise ScenarioFailure("staged_source_changed")
        hashes[alias.name] = digest
    return reports, hashes


def _select_exact_reports(workspace) -> tuple[str, ...]:
    from PyQt6.QtCore import Qt

    planner = workspace.report_planner
    planner.model.clear_selection()
    expected = {f"REF001_2024-01-01_{index}.pdf" for index in SELECTED}
    for row in range(planner.model.rowCount()):
        item = planner.model.item_at(row)
        if item is not None and item.display_name in expected:
            if not planner.model.setData(
                planner.model.index(row, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
            ):
                raise ScenarioFailure("selection_control_rejected")
    selected = planner.model.selected_ids
    names = {
        planner.model.item_at(row).display_name
        for row in range(planner.model.rowCount())
        if planner.model.item_at(row) is not None
        and planner.model.item_at(row).stable_occurrence_id in selected
    }
    if names != expected or len(selected) != 2:
        raise ScenarioFailure("selection_mismatch")
    return selected


def _grouping_snapshot(database: Path) -> dict[str, Any]:
    from metroliza.analytics.group_analysis_service import build_group_analysis_payload
    from metroliza.exporting.export_grouping_utils import apply_group_assignments, prepare_grouping_dataframe
    from metroliza.exporting.export_query_service import build_export_dataframe, build_measurement_export_dataframe, execute_export_query
    from metroliza.reports.report_query_service import build_measurement_export_query
    from metroliza.tabular.contracts import GroupingAssignment

    rows, columns = execute_export_query(str(database), build_measurement_export_query())
    measurements = build_measurement_export_dataframe(build_export_dataframe(rows, columns))
    grouping = prepare_grouping_dataframe(tuple(GroupingAssignment("POPULATION", report_id=value) for value in (1, 2)))
    grouped, applied, keys, duplicates = apply_group_assignments(
        measurements, grouping, group_analysis_mode=True, fallback_group_label="POPULATION"
    )
    if not applied or keys != ["GROUP_KEY"] or duplicates:
        raise ScenarioFailure("group_assignment_not_applied")
    records = list(grouped.iter_rows(as_dict=True))
    if len(records) != 2:
        raise ScenarioFailure("grouped_row_count")
    metric_rows = [row for row in records if row.get("HEADER - AX") == "SMOKE FEATURE - X"]
    if len(metric_rows) != 2:
        raise ScenarioFailure("group_metric_missing")
    analysis = build_group_analysis_payload(grouped, analysis_level="light", default_group_label="POPULATION")
    readiness = analysis.get("readiness") or {}
    reason = readiness.get("skip_reason") or {}
    return {
        "projection": {
            "default_group": "POPULATION",
            "members": {"POPULATION": {
                "report_ids": sorted(int(row["REPORT_ID"]) for row in metric_rows),
                "measurement_ids": sorted(int(row["MEASUREMENT_ID"]) for row in metric_rows),
            }},
            "metric": {
                "header": "SMOKE FEATURE - X", "axis": "X", "unit": None,
                "values": [float(row["MEAS"]) for row in metric_rows],
                "n": len(metric_rows), "mean": sum(float(row["MEAS"]) for row in metric_rows) / len(metric_rows),
                "nominal": float(metric_rows[0]["NOM"]), "usl": float(metric_rows[0]["NOM"] + metric_rows[0]["+TOL"]),
                "lsl": float(metric_rows[0]["NOM"] + metric_rows[0]["-TOL"]),
            },
        },
        "group_analysis": {
            "requested_level": "light",
            "expected_status": str(reason.get("code") or analysis.get("status") or ""),
            "reason": "One POPULATION group with two equal observations is a membership/export projection, not an inferential analysis acceptance.",
        },
    }


def _database_observation(database: Path) -> dict[str, Any]:
    if any(database.with_name(database.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ScenarioFailure("database_observation_sidecars_present")
    with sqlite_readonly_connection_scope(str(database), immutable=True) as connection:
        tables = {
            "source_files": "SELECT COUNT(*) FROM source_files",
            "active_locations": "SELECT COUNT(*) FROM source_file_locations WHERE is_active = 1",
            "parsed_reports": "SELECT COUNT(*) FROM parsed_reports",
            "metadata": "SELECT COUNT(*) FROM report_metadata",
            "measurements": "SELECT COUNT(*) FROM report_measurements",
        }
        return {name: int(connection.execute(query).fetchone()[0]) for name, query in tables.items()}


def capture_tabular_w05(fixture_dir: Path, output: Path) -> dict[str, Any]:
    """Load the two prepared CSVs through the public SQLite tabular consumer.

    This function has no Qt dependency and is intentionally callable in a
    separately pinned numeric composition.  A joined EXE may call the same
    function only after its bundled source includes that numeric composition.
    """
    from metroliza.tabular.tabular_analytics_service import (
        TabularColumnFilter,
        cleanup_tabular_load_result,
        load_tabular_analytics_file,
    )

    expected_finite = {
        "eq_zero": [7, 8, 9, 10],
        "ne_zero": [11, 12, 13, 14, 15, 16, 17, 18, 22],
    }
    expected_precision = {
        "9007199254740992": [1], "9007199254740993": [2],
        "9223372036854775807": [3], "9223372036854775808": [4],
        "-123456789012345678": [5], "-123456789012345679": [6],
        "123456789012345678": [7, 8],
    }
    inputs = {name: fixture_dir / name for name in ("finite-source.csv", "integer-precision.csv")}
    if any(not path.is_file() or _sha256(path) != FIXTURES[name] for name, path in inputs.items()):
        raise ScenarioFailure("tabular_fixture_mismatch")
    snapshots: dict[str, Any] = {}
    for name, path in inputs.items():
        loaded = load_tabular_analytics_file(path, reference_column="reference", force_sqlite=True)
        try:
            store = loaded.sqlite_store
            if store is None or loaded.storage_mode != "sqlite":
                raise ScenarioFailure("tabular_public_store_missing")
            expected = expected_finite if name == "finite-source.csv" else expected_precision
            observed: dict[str, list[int]] = {}
            for literal, ids in expected.items():
                operator, value = ("=", 0) if literal == "eq_zero" else (
                    ("!=", 0) if literal == "ne_zero" else ("=", literal)
                )
                actual = store.row_ids(column_filters=(
                    TabularColumnFilter("reference", numeric_operator=operator, numeric_value=value),
                ))
                if actual != ids:
                    raise ScenarioFailure("tabular_filter_ids_mismatch")
                observed[literal] = actual
            rows = store.read_query_result(columns=("source_row_number", "reference")).rows
            snapshots[name] = {
                "sha256": _sha256(path), "row_count": loaded.row_count,
                "filters": observed,
                "source_rows": [[int(row[0]), row[1], type(row[1]).__name__] for row in rows],
            }
        finally:
            cleanup_tabular_load_result(loaded)
    payload = {"schema": "metroliza-w05-tabular-snapshot-v1", "source": "public_tabular_sqlite_consumer", "files": snapshots}
    output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return payload


def _require_complete_workbook(result) -> str:
    from metroliza.exporting.export_outcomes import ExportArtifactStatus, ExportRunResult, ExportRunStatus

    if not isinstance(result, ExportRunResult) or result.status not in {
        ExportRunStatus.COMPLETE, ExportRunStatus.COMPLETE_WITH_OMISSIONS
    }:
        raise ScenarioFailure("export_failed_or_cancelled")
    artifacts = [item for item in result.artifacts if item.artifact_id == "workbook"]
    if len(artifacts) != 1 or artifacts[0].status is not ExportArtifactStatus.COMPLETE:
        raise ScenarioFailure("workbook_incomplete")
    return result.status.value


def _run_core(root: Path, fixtures: Path, receipt: dict[str, Any], app) -> None:
    from PyQt6.QtCore import QSettings
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest
    from metroliza.exporting.export_data_thread import ExportDataThread
    from importlib import import_module
    from metroliza.app.ui_entrypoint import load_main_window_factory

    MainWindow = load_main_window_factory()
    UiPreferences = import_module("metroliza.ui.ui_preferences").UiPreferences

    scratch = root / f"core-{uuid.uuid4().hex}"
    scratch.mkdir()
    receipt["relative_artifact_dir"] = scratch.name
    reports, staged_hashes = _stage_reports(fixtures, scratch)
    database, workbook, grouping_file = scratch / "reports.sqlite", scratch / "export.xlsx", scratch / "grouping.json"
    receipt["qpa"] = app.platformName()
    settings = QSettings(str(scratch / "isolated-settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow("candidate-qualification", None, ui_preferences=UiPreferences(settings))
    try:
        window.show()
        app.processEvents()
        reports_index = window.navigation_combo.findData("reports")
        if reports_index < 0:
            raise ScenarioFailure("reports_navigation_missing")
        window.navigation_list.setCurrentRow(reports_index)
        workspace = window.reports_workspace
        if not window.set_directory(str(reports)) or not window.set_db_file(str(database)):
            raise ScenarioFailure("workspace_context_rejected")
        workspace.scan_button.click()
        _wait(app, lambda: workspace.preflight_thread is None, deadline_s=DEADLINES_S["review"], stage="review")
        if database.exists() or workspace.report_planner.model.counts["total"] != 5:
            raise ScenarioFailure("review_mutated_or_count_mismatch")
        workspace.report_planner.clear.click()
        if workspace.parse_button.isEnabled() or database.exists():
            raise ScenarioFailure("zero_selection_guard_failed")
        _select_exact_reports(workspace)
        workspace.parse_button.click()
        worker = workspace.parse_thread
        if worker is None:
            raise ScenarioFailure("import_worker_not_started")
        _wait(app, lambda: workspace.parse_thread is None, deadline_s=DEADLINES_S["import"], stage="import")
        result = worker.last_parse_result
        if result is None or result.imported_files != 2 or result.intentionally_excluded_files != 3:
            raise ScenarioFailure("import_count_mismatch")
        if any(_sha256(reports / name) != digest for name, digest in staged_hashes.items()):
            raise ScenarioFailure("source_preservation_failed")
        grouping_snapshot = _grouping_snapshot(database)
        grouping_file.write_text(json.dumps(grouping_snapshot, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        export = ExportDataThread(ExportRequest(
            paths=AppPaths(db_file=str(database), excel_file=str(workbook)),
            options=ExportOptions(generate_summary_sheet=False, group_analysis_level="light"),
        ))
        export.run()
        if not workbook.is_file():
            raise ScenarioFailure("export_failed")
        export_status = _require_complete_workbook(export.export_run_result)
        receipt.update({
            "operations": {"planner_review": "observed", "zero_selection_no_write": "observed", "exact_selection": "observed", "selected_import": "observed", "grouping_projection": "observed", "group_analysis": "observed", "workbook_export": "observed"},
            "deadlines_s": DEADLINES_S,
            "export_bound": "Synchronous real export; outer driver Job watchdog only, no per-export cancellation deadline",
            "export_status": export_status,
            "source_hashes": staged_hashes,
            "database_counts": _database_observation(database),
            "facets": {
                "selected_import": "passed", "zero_selection_no_write": "passed",
                "persisted_measurements": "passed", "group_membership": "passed",
                "group_analysis_status": "insufficient_groups", "workbook_cells": "passed",
            },
            "artifacts": {
                "database": {"path": database.name, "sha256": _sha256(database)},
                "workbook": {"path": workbook.name, "sha256": _sha256(workbook)},
                "grouping": {"path": grouping_file.name, "sha256": _sha256(grouping_file)},
            },
        })
    finally:
        if window is not None:
            from metroliza.app.windows_candidate_native_check import close_report_owner
            close_report_owner(window, app)


def _run_ui_slice(child: Path, receipt: dict[str, Any]) -> None:
    from metroliza.app.windows_candidate_ui_checks import run_ui_checks
    scale = os.environ.get("METROLIZA_WINDOWS_CANDIDATE_DPR", "1.0")
    if scale not in {"1.0", "1.25", "1.5"}:
        raise ScenarioFailure("invalid_ui_scale")
    ui = run_ui_checks(child, expected_dpr=float(scale))
    receipt["ui_observation"] = ui
    expected_ui = {
        "private_dashboard_generation": "passed", "offline_html_source": "passed",
        "industrial_geometry": "passed" if sys.platform == "win32" else "not_assessed",
        "browser_rendering": "not_assessed",
    }
    if (ui.get("facets") != expected_ui or ui.get("error_codes") != []
            or ui.get("status") != ("passed" if sys.platform == "win32" else "partial")):
        raise ScenarioFailure("ui_checks_failed")
    receipt["facets"].update({key: "passed" for key in (
        "private_dashboard_generation", "offline_html_source",
    )})


def _run_import_guards_slice(child: Path, fixtures: Path, receipt: dict[str, Any]) -> None:
    from metroliza.app.windows_candidate_import_guards import FACETS, run_import_guard_checks
    guards = run_import_guard_checks(child, fixtures)
    if (guards.get("status") != "passed"
            or guards.get("facets") != dict.fromkeys(FACETS, "passed")
            or guards.get("error_codes") != []):
        raise ScenarioFailure("import_guard_checks_failed")
    receipt["facets"].update(guards["facets"])
    receipt["import_guard_evidence"] = guards["evidence"]


def _run_ocr_slice(child: Path, fixture: Path, receipt: dict[str, Any]) -> None:
    from metroliza.app.windows_candidate_ocr_check import (
        EMBEDDED_TEXT_SHA256,
        EXPECTED_FIELD_SOURCES,
        EXPECTED_METADATA,
        EXPECTED_OCR_TOKENS,
        FACETS,
        FIXTURE_NAME,
        FIXTURE_SHA256,
        run_ocr_check,
    )
    from metroliza.parsing.header_ocr_backend import RAPIDOCR_MODEL_ASSET_MANIFEST

    observation = run_ocr_check(child, fixture)
    receipt["ocr_observation"] = observation
    expected_top_level = {
        "schema_version", "status", "facets", "error_codes", "evidence",
    }
    if not isinstance(observation, dict) or set(observation) != expected_top_level:
        raise ScenarioFailure("ocr_observation_schema_mismatch")
    if (observation.get("schema_version") != 1
            or observation.get("status") != "passed"
            or observation.get("facets") != dict.fromkeys(FACETS, "passed")
            or observation.get("error_codes") != []):
        raise ScenarioFailure("ocr_checks_failed")

    evidence = observation.get("evidence")
    expected_evidence_keys = {
        "runtime_context", "fixture_name", "fixture_sha256",
        "embedded_text_sha256", "embedded_header_word_count",
        "header_image_count", "parser_plugin_id", "measurement_count",
        "header_extraction_mode", "header_structured_word_count",
        "header_ocr_engine", "header_ocr_runtime_engine",
        "header_ocr_runtime_accelerator", "recognized_header_sha256",
        "matched_ocr_tokens", "selected_metadata", "field_sources",
        "model_asset_sha256",
    }
    if not isinstance(evidence, dict) or set(evidence) != expected_evidence_keys:
        raise ScenarioFailure("ocr_evidence_schema_mismatch")
    expected_runtime = "packaged" if receipt.get("packaged") is True else "source"
    expected_models = {
        name: values["sha256"]
        for name, values in sorted(RAPIDOCR_MODEL_ASSET_MANIFEST.items())
    }
    digest = evidence.get("recognized_header_sha256")
    expected_evidence = {
        "runtime_context": expected_runtime,
        "fixture_name": FIXTURE_NAME,
        "fixture_sha256": FIXTURE_SHA256,
        "embedded_text_sha256": EMBEDDED_TEXT_SHA256,
        "embedded_header_word_count": 0,
        "header_image_count": 1,
        "parser_plugin_id": "cmm",
        "measurement_count": 1,
        "header_extraction_mode": "ocr",
        "header_structured_word_count": 0,
        "header_ocr_engine": "rapidocr_latin",
        "header_ocr_runtime_engine": "onnxruntime",
        "header_ocr_runtime_accelerator": "cpu",
        "matched_ocr_tokens": list(EXPECTED_OCR_TOKENS),
        "selected_metadata": EXPECTED_METADATA,
        "field_sources": EXPECTED_FIELD_SOURCES,
        "model_asset_sha256": expected_models,
    }
    evidence_mismatch = any(
        evidence.get(name) != expected for name, expected in expected_evidence.items()
    )
    invalid_digest = (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    )
    if evidence_mismatch or invalid_digest:
        raise ScenarioFailure("ocr_evidence_mismatch")
    receipt["facets"].update(observation["facets"])


def _run_closeout_slices(child, fixtures, receipt):
    from metroliza.app.windows_candidate_privacy_checks import run_privacy_checks
    from metroliza.app.windows_candidate_shell_checks import run_shell_checks
    from metroliza.app.windows_candidate_lifecycle_checks import run_lifecycle_checks

    scale = os.environ.get("METROLIZA_WINDOWS_CANDIDATE_DPR", "1.0")
    if scale not in {"1.0", "1.25", "1.5"}:
        raise ScenarioFailure("invalid_ui_scale")
    observations = {}
    receipt["closeout_observation"] = observations
    for name, operation in (
        ("privacy", lambda: run_privacy_checks(child)),
        ("shell", lambda: run_shell_checks(child, fixtures, expected_dpr=float(scale))),
        ("lifecycle", lambda: run_lifecycle_checks(child, fixtures)),
    ):
        record = operation()
        observations[name] = record
        expected = "passed" if os.name == "nt" or name == "lifecycle" else "partial"
        if record.get("status") != expected or record.get("error_codes") != []:
            raise ScenarioFailure("closeout_" + name + "_failed")


def _execute_core_checks(root, fixtures, ocr_fixture, receipt):
    from metroliza.app.bootstrap import get_or_create_qapplication
    # Each stage closes its own windows. Keep their shared application alive
    # until all subsequent widget and worker stages have finished.
    application = get_or_create_qapplication()
    _run_core(root, fixtures, receipt, application)
    child = root / receipt["relative_artifact_dir"]
    _run_ocr_slice(child, ocr_fixture, receipt)
    from metroliza.app.windows_candidate_reopen import run_reopen_checks
    completed_import = root / receipt["relative_artifact_dir"]
    reopened = run_reopen_checks(
        completed_import / "reports.sqlite", completed_import / "reports", receipt["source_hashes"]
    )
    if reopened.get("status") != "passed" or reopened.get("facets") != {"reopen_preserves_completed_import": "passed"}:
        receipt["reopen_failure"] = reopened.get("failure_code", "invalid_reopen_result")
        raise ScenarioFailure("completed_import_reopen_failed")
    if reopened["database"]["before_sha256"] != receipt["artifacts"]["database"]["sha256"]:
        raise ScenarioFailure("reopen_input_identity_mismatch")
    reopened_hash = _sha256(completed_import / "reports.sqlite")
    if reopened["database"]["sha256"] != reopened_hash:
        raise ScenarioFailure("reopen_output_identity_mismatch")
    receipt["artifacts"]["database"]["sha256"] = reopened_hash
    receipt["reopen_database"] = reopened["database"]
    receipt["facets"].update(reopened["facets"])
    tabular_file = root / receipt["relative_artifact_dir"] / "tabular.json"
    capture_tabular_w05(fixtures, tabular_file)
    receipt["artifacts"]["tabular"] = {"path": tabular_file.name, "sha256": _sha256(tabular_file)}
    receipt["facets"]["finite_precision_filters"] = "passed"
    from metroliza.app.windows_candidate_xlsx import _SAFE_FAILURE_CODES as xlsx_failure_codes
    from metroliza.app.windows_candidate_xlsx import run_export_checks
    xlsx_result = run_export_checks(child)
    expected_xlsx_facets = {
        "literal_chart_titles_series_caches_references", "value_limit_order",
        "local_chart_cells_and_negative_control", "pre_cancelled_export_preserves_workbook",
        "oversized_label_rejection_preserves_workbook", "active_export_cancellation_preserves_workbook",
    }
    xlsx_facets = xlsx_result.get("facets", {})
    if (xlsx_result.get("status") != "passed" or set(xlsx_facets) != expected_xlsx_facets
            or any(value != "passed" for value in xlsx_facets.values())):
        failure = xlsx_result.get("failure_code")
        receipt["xlsx_failure"] = failure if type(failure) is str and failure in xlsx_failure_codes else "operation_failed"
        raise ScenarioFailure("literal_workbook_checks_failed")
    original_workbook = child / xlsx_result["relative_artifact_dir"] / xlsx_result["artifacts"]["workbook"]["workbook"]
    literal_workbook = child / "literal-workbook.xlsx"
    shutil.copyfile(original_workbook, literal_workbook)
    literal_hash = _sha256(literal_workbook)
    if literal_hash != xlsx_result["artifacts"]["workbook"]["sha256"]:
        raise ScenarioFailure("literal_workbook_copy_mismatch")
    receipt["artifacts"]["literal_workbook"] = {"path": literal_workbook.name, "sha256": literal_hash}
    receipt["facets"].update(xlsx_facets)
    from metroliza.app.windows_candidate_inference import run_inference_checks
    inference = run_inference_checks(child, fixtures)
    if inference.get("status") != "passed" or inference.get("facets") != {"successful_group_inference": "passed"}:
        raise ScenarioFailure("group_inference_checks_failed")
    receipt["artifacts"].update(inference["artifacts"])
    receipt["facets"].update(inference["facets"])
    _run_import_guards_slice(child, fixtures, receipt)
    _run_ui_slice(child, receipt)
    _run_closeout_slices(child, fixtures, receipt)


def run_qualification() -> int:
    if requested_scenario() == "reopen":
        from metroliza.app.windows_candidate_reopen import run_fresh_qualification
        return run_fresh_qualification()
    if requested_scenario() != SCENARIO:
        return 20
    receipt: dict[str, Any] = {
        "schema": "metroliza-windows-candidate-core-v1", "schema_version": 1,
        "scenario": SCENARIO, "stage": "failed", "status": "failed",
        "packaged": bool(getattr(sys, "frozen", False)), "qpa": None,
        "ordinary_user": _ordinary_user(), "source_sha": _runtime_provenance()["source_sha"],
        "checks": {key: "not_executed" for key in ("W03", "W04", "W05", "W06", "W07")},
        "ocr_observation": None,
    }
    root: Path | None = None
    try:
        root = _root()
        fixtures = _fixture_dir()
        ocr_fixture = _ocr_fixture()
        from metroliza.shared.diagnostic_runtime_audit import wait_for_host_ready
        _atomic_json(root / "core-startup.json", {
            "schema_version": 1, "scenario": "core", "stage": "startup_ready",
        })
        wait_for_host_ready()
        from metroliza.app.windows_candidate_native_check import run_with_native_mode
        receipt["native_observation"] = run_with_native_mode(
            lambda: _execute_core_checks(root, fixtures, ocr_fixture, receipt)
        )
        receipt["stage"] = "complete"
        receipt["status"] = "passed"
        receipt["checks"].update({"W03": "passed", "W04": "passed", "W05": "passed", "W06": "passed", "W07": "passed"})
        _atomic_json(root / "windows-candidate-result.json", receipt)
        return 0
    except Exception as error:
        receipt["failure"] = type(error).__name__ if not isinstance(error, ScenarioFailure) else str(error)
        if root is not None:
            _atomic_json(root / "windows-candidate-result.json", receipt)
        return 21


if __name__ == "__main__":
    raise SystemExit(run_qualification())
