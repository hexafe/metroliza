"""Bounded W04 subset: reopen an already completed synthetic import.

The caller owns the completed SQLite database and staged report directory.  This
operation creates a new ordinary MainWindow only to reopen that context.  It
does not import, alter selection, or construct a replacement database.
"""
from __future__ import annotations

from contextlib import closing

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from metroliza.reports.db import sqlite_readonly_connection_scope

from typing import Any, Mapping


_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
_EXPECTED_COUNTS = {
    "source_files": 2,
    "active_locations": 2,
    "parsed_reports": 2,
    "metadata": 2,
    "measurements": 2,
}
_EXPECTED_MEASUREMENTS = {
    ("1", "SMOKE FEATURE - X"): (10.0, 0.1, -0.1, 10.02),
    ("3", "SMOKE FEATURE - X"): (10.0, 0.1, -0.1, 10.02),
}


class ReopenScenarioFailure(ValueError):
    """The completed-import reopen observation was not preserved."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sidecars(database: Path) -> tuple[str, ...]:
    return tuple(suffix for suffix in _SIDECAR_SUFFIXES if database.with_name(database.name + suffix).exists())


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ReopenScenarioFailure(code)


def _validate_inputs(database: Path, reports: Path, expected_hashes: Mapping[str, str]) -> dict[str, str]:
    _require(database.is_file() and not database.is_symlink(), "database_invalid")
    _require(reports.is_dir() and not reports.is_symlink(), "reports_invalid")
    _require(bool(expected_hashes), "source_hashes_missing")
    observed = {path.name: _sha256(path) for path in reports.iterdir() if path.is_file()}
    _require(observed == dict(expected_hashes), "source_hashes_changed")
    _require(not _sidecars(database), "database_sidecars_present")
    return observed


def _database_counts(database: Path) -> dict[str, int]:
    queries = {
        "source_files": "SELECT COUNT(*) FROM source_files",
        "active_locations": "SELECT COUNT(*) FROM source_file_locations WHERE is_active = 1",
        "parsed_reports": "SELECT COUNT(*) FROM parsed_reports",
        "metadata": "SELECT COUNT(*) FROM report_metadata",
        "measurements": "SELECT COUNT(*) FROM report_measurements",
    }
    with sqlite_readonly_connection_scope(str(database), immutable=True) as connection:
        return {name: int(connection.execute(query).fetchone()[0]) for name, query in queries.items()}


def _schema_digest(database: Path) -> str:
    with sqlite_readonly_connection_scope(str(database), immutable=True) as connection:
        schema = list(
            connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
            )
        )
    encoded = json.dumps(schema, ensure_ascii=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _logical_dump_digest(database: Path) -> str:
    with sqlite_readonly_connection_scope(str(database), immutable=True) as connection:
        dump = "\n".join(sorted(connection.iterdump())).encode("utf-8")
    return hashlib.sha256(dump).hexdigest()


def _readonly_select_with_columns(database: str, query: str) -> tuple[list[tuple[Any, ...]], list[str]]:
    with sqlite_readonly_connection_scope(database, immutable=True) as connection:
        with closing(connection.cursor()) as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [description[0] for description in cursor.description or ()]
    return rows, columns


def _public_measurements(database: Path) -> dict[tuple[str, str], tuple[float, float, float, float]]:
    from metroliza.exporting.export_query_service import (
        build_export_dataframe,
        build_measurement_export_dataframe,
        execute_export_query,
    )
    from metroliza.reports.report_query_service import build_measurement_export_query

    rows, columns = execute_export_query(
        str(database),
        build_measurement_export_query(),
        select_reader=_readonly_select_with_columns,
    )
    table = build_measurement_export_dataframe(build_export_dataframe(rows, columns))
    observed: dict[tuple[str, str], tuple[float, float, float, float]] = {}
    for row in table.iter_rows(as_dict=True):
        key = (str(row["SAMPLE_NUMBER"]), str(row["HEADER - AX"]))
        _require(key not in observed, "public_measurement_duplicate")
        observed[key] = (
            float(row["NOM"]),
            float(row["+TOL"]),
            float(row["-TOL"]),
            float(row["MEAS"]),
        )
    return observed


def _readonly_observation(
    database: Path,
    reports: Path,
    source_hashes: Mapping[str, str],
    operation,
) -> Any:
    database_before = _sha256(database)
    result = operation(database)
    _require(_sha256(database) == database_before, "readonly_database_bytes_changed")
    _require(not _sidecars(database), "database_sidecars_created")
    _require(_validate_inputs(database, reports, source_hashes) == source_hashes, "source_hashes_changed")
    return result


def _reopen_window(database: Path, reports: Path) -> None:
    from PyQt6.QtCore import QSettings
    from metroliza.app.bootstrap import get_or_create_qapplication
    from importlib import import_module
    from metroliza.app.ui_entrypoint import load_main_window_factory

    MainWindow = load_main_window_factory()
    UiPreferences = import_module("metroliza.ui.ui_preferences").UiPreferences

    application = get_or_create_qapplication()
    settings = QSettings(str(database.with_name("reopen-settings.ini")), QSettings.Format.IniFormat)
    window = MainWindow("candidate-reopen", None, ui_preferences=UiPreferences(settings))
    try:
        window.show()
        application.processEvents()
        reports_index = window.navigation_combo.findData("reports")
        _require(reports_index >= 0, "reports_navigation_missing")
        window.navigation_list.setCurrentRow(reports_index)
        workspace = window.reports_workspace
        _require(workspace is not None, "reports_workspace_missing")
        _require(window.set_directory(str(reports)), "reopen_source_rejected")
        _require(window.set_db_file(str(database)), "reopen_database_rejected")
        _require(workspace.directory == str(reports), "reopen_source_context")
        _require(workspace.db_file == str(database), "reopen_database_context")
    finally:
        from metroliza.app.windows_candidate_native_check import close_report_owner
        close_report_owner(window, application)


def run_reopen_checks(
    database_file: str | Path,
    reports_directory: str | Path,
    expected_source_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Reopen completed synthetic reports and prove the retained import is unchanged."""
    database, reports = Path(database_file), Path(reports_directory)
    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "failed",
        "facets": {"reopen_preserves_completed_import": "failed"},
    }
    try:
        source_before = _validate_inputs(database, reports, expected_source_hashes)
        database_before = _sha256(database)
        schema_before = _readonly_observation(
            database, reports, source_before, _schema_digest
        )
        logical_before = _readonly_observation(
            database, reports, source_before, _logical_dump_digest
        )
        counts_before = _readonly_observation(
            database, reports, source_before, _database_counts
        )
        _require(counts_before == _EXPECTED_COUNTS, "database_counts_before_reopen")
        measurements_before = _readonly_observation(
            database, reports, source_before, _public_measurements
        )
        _require(measurements_before == _EXPECTED_MEASUREMENTS, "public_measurements_before_reopen")
        _reopen_window(database, reports)
        schema_after = _readonly_observation(
            database, reports, source_before, _schema_digest
        )
        logical_after = _readonly_observation(
            database, reports, source_before, _logical_dump_digest
        )
        _require(schema_after == schema_before, "schema_changed_after_reopen")
        _require(logical_after == logical_before, "logical_dump_changed_after_reopen")
        database_after = _sha256(database)
        _require(not _sidecars(database), "database_sidecars_created")
        _require(_validate_inputs(database, reports, source_before) == source_before, "source_hashes_changed")
        counts_after = _readonly_observation(database, reports, source_before, _database_counts)
        _require(counts_after == _EXPECTED_COUNTS, "database_counts_after_reopen")
        measurements_after = _readonly_observation(
            database, reports, source_before, _public_measurements
        )
        _require(measurements_after == _EXPECTED_MEASUREMENTS, "public_measurements_after_reopen")
    except ReopenScenarioFailure as error:
        result["failure_code"] = str(error)
    else:
        result.update(
            {
                "status": "passed",
                "facets": {"reopen_preserves_completed_import": "passed"},
                "database": {
                    "sha256": database_after,
                    "before_sha256": database_before,
                    "schema_sha256": schema_after,
                    "logical_dump_sha256": logical_after,
                    "counts": _EXPECTED_COUNTS,
                },
                "source_hashes": source_before,
            }
        )
    return result


def _fresh_input(root: Path) -> tuple[Path, dict[str, str], str]:
    from metroliza.app.windows_candidate_qualification import FIXTURES

    raw = os.getenv("METROLIZA_WINDOWS_CANDIDATE_REOPEN_INPUT", "")
    expected = os.getenv("METROLIZA_WINDOWS_CANDIDATE_REOPEN_SHA256", "")
    child = Path(raw)
    _require(child.is_absolute() and child.parent == root.parent / "core scenario"
             and re.fullmatch(r"core-[0-9a-f]{32}", child.name) is not None,
             "fresh_reopen_input_not_owned_sibling")
    for path in (root.parent, child.parent, child, child / "reports"):
        info = path.lstat()
        _require(stat.S_ISDIR(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                 "fresh_reopen_input_directory_invalid")
    database = child / "reports.sqlite"
    info = database.lstat()
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
             and not getattr(info, "st_file_attributes", 0) & 0x400,
             "fresh_reopen_database_invalid")
    _require(re.fullmatch(r"[0-9a-f]{64}", expected) is not None and _sha256(database) == expected,
             "fresh_reopen_database_identity_mismatch")
    hashes = {f"REF001_2024-01-01_{i}.pdf": FIXTURES[f"report-{i}.pdf"] for i in range(5)}
    reports = child / "reports"
    _require({item.name for item in reports.iterdir()} == set(hashes), "fresh_reopen_sources_invalid")
    for name in hashes:
        info = (reports / name).lstat()
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                 and not getattr(info, "st_file_attributes", 0) & 0x400,
                 "fresh_reopen_source_invalid")
    _validate_inputs(database, reports, hashes)
    return child, hashes, expected


def run_fresh_qualification() -> int:
    """Reopen only the prior synthetic import in a second application process."""
    from metroliza.app import windows_candidate_qualification as core
    from metroliza.shared.diagnostic_runtime_audit import wait_for_host_ready

    if core.requested_scenario() != "reopen":
        return 20
    root = None
    receipt = {"schema_version": 1, "scenario": "reopen", "status": "failed",
               "packaged": bool(getattr(sys, "frozen", False)), "qpa": None,
               "ordinary_user": core._ordinary_user(),
               "source_sha": core._runtime_provenance()["source_sha"]}
    failure_stage = "input"
    try:
        root = core._root()
        child, hashes, expected = _fresh_input(root)
        core._atomic_json(root / "core-startup.json", {
            "schema_version": 1, "scenario": "reopen", "stage": "startup_ready",
        })
        failure_stage = "host_ready"
        wait_for_host_ready()
        failure_stage = "reopen"
        observed = run_reopen_checks(child / "reports.sqlite", child / "reports", hashes)
        _require(observed.get("status") == "passed", "fresh_reopen_ui_failed")
        failure_stage = "database_preservation"
        _require(observed["database"]["before_sha256"] == expected,
                 "fresh_reopen_input_identity_changed")
        from metroliza.app.bootstrap import get_or_create_qapplication
        receipt.update(status="passed", qpa=get_or_create_qapplication().platformName(), observation=observed)
        core._atomic_json(root / "fresh-reopen-result.json", receipt)
        return 0
    except Exception:
        # The host retains only a closed failure, never exception text or paths.
        if root is not None:
            receipt["failure_stage"] = failure_stage
            core._atomic_json(root / "fresh-reopen-result.json", receipt)
        return 21
