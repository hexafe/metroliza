"""Bounded W04 subset: reopen an already completed synthetic import.

The caller owns the completed SQLite database and staged report directory.  This
operation creates a new ordinary MainWindow only to reopen that context.  It
does not import, alter selection, or construct a replacement database.
"""
from __future__ import annotations

from contextlib import closing

import hashlib
import sqlite3
from pathlib import Path
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
    uri = database.resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        return {name: int(connection.execute(query).fetchone()[0]) for name, query in queries.items()}


def _public_measurements(database: Path) -> dict[tuple[str, str], tuple[float, float, float, float]]:
    from metroliza.exporting.export_query_service import (
        build_export_dataframe,
        build_measurement_export_dataframe,
        execute_export_query,
    )
    from metroliza.reports.report_query_service import build_measurement_export_query

    rows, columns = execute_export_query(str(database), build_measurement_export_query())
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


def _reopen_window(database: Path, reports: Path) -> None:
    from PyQt6.QtCore import QCoreApplication, QEvent, QSettings
    from metroliza.app.bootstrap import get_or_create_qapplication
    from metroliza.ui.main_window import MainWindow
    from metroliza.ui.ui_preferences import UiPreferences

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
        window.close()
        window.deleteLater()
        application.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        application.processEvents()


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
        _require(_database_counts(database) == _EXPECTED_COUNTS, "database_counts_before_reopen")
        _require(_public_measurements(database) == _EXPECTED_MEASUREMENTS, "public_measurements_before_reopen")
        _reopen_window(database, reports)
        _require(_sha256(database) == database_before, "database_bytes_changed")
        _require(not _sidecars(database), "database_sidecars_created")
        _require(_validate_inputs(database, reports, source_before) == source_before, "source_hashes_changed")
        _require(_database_counts(database) == _EXPECTED_COUNTS, "database_counts_after_reopen")
        _require(_public_measurements(database) == _EXPECTED_MEASUREMENTS, "public_measurements_after_reopen")
        # The observation itself must finish without altering retained evidence.
        _require(_sha256(database) == database_before, "database_bytes_changed")
        _require(not _sidecars(database), "database_sidecars_created")
        _require(_validate_inputs(database, reports, source_before) == source_before, "source_hashes_changed")
    except ReopenScenarioFailure as error:
        result["failure_code"] = str(error)
    else:
        result.update(
            {
                "status": "passed",
                "facets": {"reopen_preserves_completed_import": "passed"},
                "database": {"sha256": database_before, "counts": _EXPECTED_COUNTS},
                "source_hashes": source_before,
            }
        )
    return result
