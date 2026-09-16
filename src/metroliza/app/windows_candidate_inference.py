"""Synthetic-only W06 Group Analysis producer for the Windows candidate lane.

The module is inert during ordinary application startup.  A qualification
launcher may call :func:`run_inference_checks` with a new private directory to
exercise the normal Reports workspace, parser worker, public export query, and
public Group Analysis service.  Its two retained artifacts are intended for an
independent oracle; this producer does not qualify a package by itself.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
_REPORT_DATE = "2024-01-01"
_ORIGINALS = {
    "REF001_2024-01-01_5.pdf": "report-1.pdf",
    "REF001_2024-01-01_6.pdf": "report-3.pdf",
}
_SAMPLES = (
    ("REF001_2024-01-01_1.pdf", "A", 9.90),
    ("REF001_2024-01-01_2.pdf", "A", 9.92),
    ("REF001_2024-01-01_3.pdf", "A", 9.94),
    ("REF001_2024-01-01_4.pdf", "A", 9.96),
    ("REF001_2024-01-01_5.pdf", "A", 10.02),
    ("REF001_2024-01-01_6.pdf", "B", 10.02),
    ("REF001_2024-01-01_7.pdf", "B", 10.04),
    ("REF001_2024-01-01_8.pdf", "B", 10.06),
    ("REF001_2024-01-01_9.pdf", "B", 10.08),
    ("REF001_2024-01-01_10.pdf", "B", 10.10),
)
_EXPECTED_FILES = tuple(name for name, _group, _value in _SAMPLES)
_ASSIGNMENTS = {name: group for name, group, _value in _SAMPLES}
_EXPECTED_VALUES = {name: value for name, _group, value in _SAMPLES}


class InferenceFailure(ValueError):
    """A fixed, path-free producer failure for the qualification receipt."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    """Return the public analysis payload in JSON form without hiding NaN values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InferenceFailure("analysis_contains_nonfinite_value")
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    item = getattr(value, "item", None)
    if callable(item):
        return _json_safe(item())
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    raise InferenceFailure("analysis_value_not_json_safe")


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    staged = path.with_name(f".{path.name}.{uuid.uuid4().hex}")
    try:
        with staged.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
        staged.replace(path)
    finally:
        if staged.exists():
            staged.unlink()


def _require_private_root(scratch: Path) -> Path:
    if not scratch.is_absolute() or scratch.is_symlink() or not scratch.is_dir():
        raise InferenceFailure("scratch_root_invalid")
    return scratch


def _write_cmm_pdf(path: Path, value: float) -> None:
    from metroliza.parsing.pdf_backend import require_pdf_backend

    deviation = value - 10.0
    text = (
        "CMM REPORT\n"
        "REFERENCE: REF001\n"
        f"DATE: {_REPORT_DATE}\n"
        "#SMOKE FEATURE\n"
        "DIM\n"
        f"X 10 0.1 -0.1 {value:.2f} {deviation:.2f} 0\n"
    )
    backend = require_pdf_backend()
    document = backend.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), text)
        document.save(str(path), garbage=4, deflate=True)
    finally:
        document.close()


def _stage_reports(fixtures: Path, private: Path) -> tuple[Path, dict[str, str]]:
    if not fixtures.is_absolute() or fixtures.is_symlink() or not fixtures.is_dir():
        raise InferenceFailure("fixture_directory_invalid")
    reports = private / "reports"
    reports.mkdir()
    for staged_name, source_name in _ORIGINALS.items():
        source = fixtures / source_name
        if not source.is_file():
            raise InferenceFailure("original_fixture_missing")
        shutil.copyfile(source, reports / staged_name)
    for staged_name, _group, value in _SAMPLES:
        if staged_name not in _ORIGINALS:
            _write_cmm_pdf(reports / staged_name, value)
    hashes = {name: _sha256(reports / name) for name in _EXPECTED_FILES}
    if set(item.name for item in reports.iterdir()) != set(_EXPECTED_FILES):
        raise InferenceFailure("staged_fixture_set_mismatch")
    return reports, hashes


def _select_all_reports(workspace) -> tuple[str, ...]:
    from PyQt6.QtCore import Qt

    planner = workspace.report_planner
    planner.model.clear_selection()
    for row in range(planner.model.rowCount()):
        item = planner.model.item_at(row)
        if item is None or item.display_name not in _EXPECTED_FILES:
            raise InferenceFailure("reviewed_filename_mismatch")
        if not planner.model.setData(
            planner.model.index(row, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
        ):
            raise InferenceFailure("selection_control_rejected")
    selected = planner.model.selected_ids
    names = {
        planner.model.item_at(row).display_name
        for row in range(planner.model.rowCount())
        if planner.model.item_at(row) is not None
        and planner.model.item_at(row).stable_occurrence_id in selected
    }
    if names != set(_EXPECTED_FILES) or len(selected) != len(_EXPECTED_FILES):
        raise InferenceFailure("selection_mismatch")
    return selected


def _report_ids_by_filename(database: Path) -> dict[str, int]:
    query = """
        SELECT location.file_name, report.id
        FROM parsed_reports AS report
        JOIN source_file_locations AS location
          ON location.source_file_id = report.source_file_id
        WHERE location.is_active = 1
    """
    with closing(sqlite3.connect(database)) as connection:
        rows = connection.execute(query).fetchall()
    mapped = {str(name): int(report_id) for name, report_id in rows}
    if set(mapped) != set(_EXPECTED_FILES) or len(mapped) != len(rows):
        raise InferenceFailure("persisted_filename_keyset_mismatch")
    return mapped


def _database_counts(database: Path) -> dict[str, int]:
    queries = {
        "source_files": "SELECT COUNT(*) FROM source_files",
        "active_locations": "SELECT COUNT(*) FROM source_file_locations WHERE is_active = 1",
        "parsed_reports": "SELECT COUNT(*) FROM parsed_reports",
        "metadata": "SELECT COUNT(*) FROM report_metadata",
        "measurements": "SELECT COUNT(*) FROM report_measurements",
    }
    with closing(sqlite3.connect(database)) as connection:
        return {key: int(connection.execute(query).fetchone()[0]) for key, query in queries.items()}


def _analysis_projection(database: Path, report_ids: Mapping[str, int]) -> dict[str, Any]:
    from metroliza.analytics.group_analysis_service import build_group_analysis_payload
    from metroliza.exporting.export_grouping_utils import (
        apply_group_assignments,
        prepare_grouping_dataframe,
    )
    from metroliza.exporting.export_query_service import (
        build_export_dataframe,
        build_measurement_export_dataframe,
        execute_export_query,
    )
    from metroliza.reports.report_query_service import build_measurement_export_query
    from metroliza.tabular.contracts import GroupingAssignment

    rows, columns = execute_export_query(str(database), build_measurement_export_query())
    measurements = build_measurement_export_dataframe(build_export_dataframe(rows, columns))
    assignments = tuple(
        GroupingAssignment(group=_ASSIGNMENTS[name], report_id=report_ids[name])
        for name in _EXPECTED_FILES
    )
    grouping = prepare_grouping_dataframe(assignments)
    grouped, applied, keys, duplicates = apply_group_assignments(
        measurements, grouping, group_analysis_mode=True, fallback_group_label="POPULATION"
    )
    if not applied or keys != ["GROUP_KEY"] or duplicates:
        raise InferenceFailure("group_assignment_not_applied")

    names_by_id = {value: key for key, value in report_ids.items()}
    records = [
        dict(row)
        for row in grouped.iter_rows(as_dict=True)
        if row.get("HEADER - AX") == "SMOKE FEATURE - X"
    ]
    if len(records) != len(_EXPECTED_FILES):
        raise InferenceFailure("grouped_metric_row_count_mismatch")
    observed_by_name: dict[str, dict[str, Any]] = {}
    for row in records:
        report_id = int(row["REPORT_ID"])
        name = names_by_id.get(report_id)
        if name is None or name in observed_by_name:
            raise InferenceFailure("grouped_report_identity_mismatch")
        value = float(row["MEAS"])
        if not math.isfinite(value) or value != _EXPECTED_VALUES[name]:
            raise InferenceFailure("grouped_measurement_value_mismatch")
        if row.get("GROUP") != _ASSIGNMENTS[name]:
            raise InferenceFailure("grouped_assignment_mismatch")
        if row.get("UNIT") not in (None, ""):
            raise InferenceFailure("grouped_unit_mismatch")
        observed_by_name[name] = {
            "filename": name,
            "report_id": report_id,
            "measurement_id": int(row["MEASUREMENT_ID"]),
            "group": str(row["GROUP"]),
            "reference": row.get("REFERENCE"),
            "header": row.get("HEADER"),
            "axis": row.get("AX"),
            "unit": row.get("UNIT"),
            "nominal": float(row["NOM"]),
            "upper_tolerance": float(row["+TOL"]),
            "lower_tolerance": float(row["-TOL"]),
            "measurement": value,
        }
    if set(observed_by_name) != set(_EXPECTED_FILES):
        raise InferenceFailure("grouped_filename_keyset_mismatch")

    analysis = build_group_analysis_payload(
        grouped,
        requested_scope="auto",
        analysis_level="light",
        default_group_label="POPULATION",
    )
    if analysis.get("status") != "ready" or not (analysis.get("readiness") or {}).get("runnable"):
        raise InferenceFailure("group_analysis_not_ready")
    if not analysis.get("metric_rows"):
        raise InferenceFailure("group_analysis_metric_missing")
    return {
        "status": analysis.get("status"),
        "readiness": analysis.get("readiness"),
        "effective_scope": analysis.get("effective_scope"),
        "analysis_level": analysis.get("analysis_level"),
        "metric_rows": analysis.get("metric_rows"),
        "projection": {
            "metric": "SMOKE FEATURE - X",
            "members": [observed_by_name[name] for name in _EXPECTED_FILES],
        },
    }


def _failure_result(private: Path | None, code: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "stage": "failed",
        "status": "failed",
        "relative_artifact_dir": private.name if private is not None else None,
        "facets": {
            "planner_review": "failed",
            "selected_import": "failed",
            "persisted_measurements": "failed",
            "filename_resolved_group_assignments": "failed",
            "group_analysis_light": "failed",
        },
        "failure": code,
    }


def run_inference_checks(scratch: Path, fixtures: Path) -> dict[str, Any]:
    """Run the real synthetic W06 producer and return retained-artifact metadata.

    ``scratch`` is caller-owned and must already be an absolute directory.  The
    producer creates one unique child so retained artifact paths are relative to
    that child and cannot expose the caller's filesystem layout.
    """
    private: Path | None = None
    window = None
    app = None
    try:
        root = _require_private_root(scratch)
        private = root / f"inference-w06-{uuid.uuid4().hex}"
        private.mkdir()
        reports, source_hashes = _stage_reports(fixtures, private)
        database = private / "inference.sqlite"
        grouping_file = private / "group-inference.json"

        from PyQt6.QtCore import QSettings
        from metroliza.app.bootstrap import get_or_create_qapplication
        from metroliza.app.windows_candidate_qualification import DEADLINES_S, _wait
        from metroliza.ui.main_window import MainWindow
        from metroliza.ui.ui_preferences import UiPreferences

        app = get_or_create_qapplication()
        settings = QSettings(str(private / "isolated-settings.ini"), QSettings.Format.IniFormat)
        window = MainWindow("candidate-w06-inference", None, ui_preferences=UiPreferences(settings))
        window.show()
        app.processEvents()
        reports_index = window.navigation_combo.findData("reports")
        if reports_index < 0:
            raise InferenceFailure("reports_navigation_missing")
        window.navigation_list.setCurrentRow(reports_index)
        workspace = window.reports_workspace
        if not window.set_directory(str(reports)) or not window.set_db_file(str(database)):
            raise InferenceFailure("workspace_context_rejected")
        workspace.scan_button.click()
        _wait(
            app,
            lambda: workspace.preflight_thread is None,
            deadline_s=DEADLINES_S["review"],
            stage="review",
        )
        if database.exists() or workspace.report_planner.model.counts["total"] != len(
            _EXPECTED_FILES
        ):
            raise InferenceFailure("review_mutated_or_count_mismatch")
        _select_all_reports(workspace)
        workspace.parse_button.click()
        worker = workspace.parse_thread
        if worker is None:
            raise InferenceFailure("import_worker_not_started")
        _wait(
            app,
            lambda: workspace.parse_thread is None,
            deadline_s=DEADLINES_S["import"],
            stage="import",
        )
        result = worker.last_parse_result
        if (
            result is None
            or result.imported_files != len(_EXPECTED_FILES)
            or result.intentionally_excluded_files
        ):
            raise InferenceFailure("import_count_mismatch")
        if any(_sha256(reports / name) != digest for name, digest in source_hashes.items()):
            raise InferenceFailure("source_preservation_failed")
        report_ids = _report_ids_by_filename(database)
        analysis = _json_safe(_analysis_projection(database, report_ids))
        payload = {
            "schema_version": SCHEMA_VERSION,
            "source_hashes": source_hashes,
            "assignments": _ASSIGNMENTS,
            "database_counts": _database_counts(database),
            "analysis": analysis,
        }
        _atomic_json(grouping_file, payload)
        if not database.is_file() or not grouping_file.is_file():
            raise InferenceFailure("retained_artifact_missing")
        return {
            "schema_version": SCHEMA_VERSION,
            "stage": "complete",
            "status": "passed",
            "relative_artifact_dir": private.name,
            "facets": {
                "planner_review": "passed",
                "selected_import": "passed",
                "persisted_measurements": "passed",
                "filename_resolved_group_assignments": "passed",
                "group_analysis_light": "passed",
            },
            "source_hashes": source_hashes,
            "assignments": _ASSIGNMENTS,
            "artifacts": {
                "inference_database": {"path": database.name, "sha256": _sha256(database)},
                "group_inference": {"path": grouping_file.name, "sha256": _sha256(grouping_file)},
            },
        }
    except Exception as error:
        code = str(error) if isinstance(error, InferenceFailure) else type(error).__name__
        return _failure_result(private, code)
    finally:
        if window is not None:
            window.close()
        if app is not None:
            app.processEvents()
