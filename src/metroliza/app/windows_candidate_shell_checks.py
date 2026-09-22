"""Packaged W13 shell/planner acceptance through the real Reports workspace."""

from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any
import uuid


FACETS = (
    "single_planner_owner",
    "real_review_import",
    "native_shell_layout",
    "windows_qt_planner_keyboard",
)
NATIVE_FACETS = frozenset(("native_shell_layout", "windows_qt_planner_keyboard"))

_EXPECTED_IMPORT_ROWS = (
    (1, 1, "REF001_2024-01-01_1.pdf",
     "315032987a656191260945242c89996976640f3629c4499c428f44ac9b3679ad",
     1, 0, "REF001", "2024-01-01", "1", "filename_tail", 1,
     "SMOKE FEATURE", "SMOKE FEATURE", "SMOKE FEATURE", "LOC", "LOC",
     "SMOKE FEATURE", "X", 10.0, 0.1, -0.1, 0.0, 10.02, 0.02, 0.0, 0, "ok"),
    (2, 2, "REF001_2024-01-01_3.pdf",
     "cb801c452d9608c227606a4c10325d19d7d8a095fe80976fa60338fd6bfd0849",
     1, 0, "REF001", "2024-01-01", "3", "filename_tail", 1,
     "SMOKE FEATURE", "SMOKE FEATURE", "SMOKE FEATURE", "LOC", "LOC",
     "SMOKE FEATURE", "X", 10.0, 0.1, -0.1, 0.0, 10.02, 0.02, 0.0, 0, "ok"),
)


class ShellChecksFailure(ValueError):
    """A stable, closed W13 failure code."""


_RETAINED_WINDOWS: list[object] = []


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ShellChecksFailure(code)


def _wait(app, predicate, *, seconds: float, code: str) -> None:
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    _require(bool(predicate()), code)


def _contained(root, widget) -> bool:
    from PyQt6.QtCore import QPoint, QRect

    if not widget.isVisibleTo(root) or widget.width() <= 0 or widget.height() <= 0:
        return False
    bounds = QRect(QPoint(0, 0), root.size())
    rectangle = QRect(widget.mapTo(root, QPoint(0, 0)), widget.size())
    if not bounds.contains(rectangle):
        return False
    parent = widget.parentWidget()
    while parent is not None and parent is not root:
        local = QRect(widget.mapTo(parent, QPoint(0, 0)), widget.size())
        if not parent.contentsRect().contains(local):
            return False
        parent = parent.parentWidget()
    return True


def _planner_geometry(workspace, app) -> dict[str, Any]:
    from PyQt6.QtCore import QPoint, QRect

    planner = workspace.report_planner
    controls = (
        workspace.directory_button,
        workspace.archive_button,
        workspace.database_button,
        workspace.metadata_mode_combo,
        workspace.scan_button,
        planner.search,
        planner.status_filter,
        planner.parser_filter,
        planner.attention_filter,
        planner.select_ready,
        planner.clear,
        planner.details_button,
        planner.table,
        workspace.parse_button,
    )
    _require(all(_contained(workspace, control) for control in controls),
             "planner_control_clipped")
    rectangles = [QRect(control.mapTo(workspace, QPoint(0, 0)), control.size())
                  for control in controls]
    _require(all(not first.intersects(second)
                 for offset, first in enumerate(rectangles)
                 for second in rectangles[offset + 1:]), "planner_control_overlap")
    _require(planner.table.height() >= 60, "planner_table_too_short")
    requested = workspace.size()
    planner.details_button.setChecked(True)
    app.processEvents()
    _require(workspace.size() == requested and _contained(workspace, planner.details),
             "planner_details_layout")
    planner.details_button.setChecked(False)
    planner.show_outcome("Synthetic acceptance outcome.")
    app.processEvents()
    _require(workspace.size() == requested and _contained(workspace, planner.outcome),
             "planner_outcome_layout")
    planner.outcome_button.setChecked(False)
    return {
        "workspace_client": [workspace.width(), workspace.height()],
        "table_height": planner.table.height(),
    }


def _exercise_keyboard(window, workspace, app) -> None:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    planner = workspace.report_planner
    ready_row = next((row for row in range(planner.proxy.rowCount())
                      if planner.proxy.index(row, 0).isValid()), None)
    _require(ready_row is not None, "planner_ready_row_missing")
    planner.table.setCurrentIndex(planner.proxy.index(ready_row, 0))
    planner.table.setFocus()
    app.processEvents()
    _require(planner.table.hasFocus(), "planner_table_focus_missing")
    before = planner.model.selected_ids
    QTest.keyClick(planner.table, Qt.Key.Key_Space)
    app.processEvents()
    _require(planner.model.selected_ids != before, "planner_space_toggle_failed")
    QTest.keyClick(planner.table, Qt.Key.Key_Space)
    workspace.directory_button.setFocus()
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)
    _require(QApplication.focusWidget() is workspace.archive_button,
             "planner_tab_order_failed")
    for page in ("home", "tools", "reports"):
        window._show_workspace_page(page)
        app.processEvents()
        _require(window.reports_workspace is workspace, "planner_owner_replaced")


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _import_oracle(database: Path) -> dict[str, Any]:
    """Independently read and match the pinned synthetic-report SQLite oracle."""
    before = _sha256(database)
    uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        measurement_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(report_measurements)")
        }
        _require("unit" not in measurement_columns, "import_oracle_unit_invented")
        counts = tuple(int(connection.execute(query).fetchone()[0]) for query in (
            "SELECT COUNT(*) FROM source_files",
            "SELECT COUNT(*) FROM source_file_locations WHERE is_active = 1",
            "SELECT COUNT(*) FROM parsed_reports",
            "SELECT COUNT(*) FROM report_metadata",
            "SELECT COUNT(*) FROM report_measurements",
        ))
        rows = tuple(connection.execute("""
            SELECT pr.id, m.id, sfl.file_name, sf.sha256,
                   pr.measurement_count, pr.has_nok, rm.reference, rm.report_date,
                   rm.sample_number, rm.sample_number_kind, m.row_order, m.header,
                   m.section_name, m.feature_label, m.characteristic_name,
                   m.characteristic_family, m.description, m.ax, m.nominal,
                   m.tol_plus, m.tol_minus, m.bonus, m.meas, m.dev, m.outtol,
                   m.is_nok, m.status_code
            FROM parsed_reports pr
            JOIN source_files sf ON sf.id = pr.source_file_id
            JOIN source_file_locations sfl
              ON sfl.source_file_id = sf.id AND sfl.is_active = 1
            JOIN report_metadata rm ON rm.report_id = pr.id
            JOIN report_measurements m ON m.report_id = pr.id
            ORDER BY pr.id, m.id
        """))
    _require(_sha256(database) == before, "import_oracle_mutated_database")
    _require(counts == (2, 2, 2, 2, 2), "import_oracle_cardinality")
    _require(rows == _EXPECTED_IMPORT_ROWS, "import_oracle_rows")
    return {
        "table_counts": {
            "source_files": 2,
            "active_locations": 2,
            "parsed_reports": 2,
            "metadata": 2,
            "measurements": 2,
        },
        "file_names": [row[2] for row in rows],
        "measurement_values": [row[22] for row in rows],
        "database_sha256": before,
    }


def _close_shell_owner(window, app) -> None:
    from metroliza.app.windows_candidate_native_check import close_report_owner

    try:
        close_report_owner(window, app)
    except Exception as error:
        _RETAINED_WINDOWS.append(window)
        raise ShellChecksFailure("window_owner_cleanup_failed") from error


def _run(scratch: Path, fixtures: Path, app, expected_dpr: float | None,
         result: dict[str, Any]) -> None:
    from PyQt6.QtCore import QSettings
    from metroliza.app.windows_candidate_import_guards import _select_names
    from metroliza.app.windows_candidate_qualification import ScenarioFailure, _stage_reports
    from metroliza.ui.main_window import MainWindow
    from metroliza.ui.ui_preferences import UiPreferences

    child = scratch / f"shell-checks-{uuid.uuid4().hex}"
    child.mkdir()
    try:
        reports, fixture_hashes = _stage_reports(fixtures, child)
    except ScenarioFailure as error:
        raise ShellChecksFailure("fixture_staging_failed") from error
    database = child / "shell.sqlite"
    settings = QSettings(str(child / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow("candidate-shell-checks", None, ui_preferences=UiPreferences(settings))
    try:
        window.show()
        window._show_workspace_page("reports")
        app.processEvents()
        workspace = window.reports_workspace
        _require(window.launch_parsing_dialog() is workspace, "planner_owner_not_single")
        _require(window.set_directory(str(reports)) and window.set_db_file(str(database)),
                 "workspace_context_rejected")
        workspace.scan_button.click()
        _wait(app, lambda: workspace.preflight_thread is None, seconds=30.0,
              code="review_deadline")
        model = workspace.report_planner.model
        _require(model.valid and model.counts["total"] == 5 and model.counts["ready"] == 5,
                 "review_counts_mismatch")
        result["facets"]["single_planner_owner"] = "passed"

        window.resize(720, 480)
        app.processEvents()
        _require(window.width() == 720 and window.height() == 480,
                 "shell_compact_resize_rejected")
        _require(window.navigation_combo.isVisible() and window.navigation_list.isHidden(),
                 "shell_compact_navigation_mismatch")
        for control in (window.navigation_combo, workspace, window.modifydb_button,
                        window.map_characteristics_button, window.export_button):
            _require(_contained(window, control), "shell_control_clipped")
        geometry = _planner_geometry(workspace, app)
        _exercise_keyboard(window, workspace, app)

        selected_names = {f"REF001_2024-01-01_{number}.pdf" for number in (1, 3)}
        _select_names(model, selected_names)
        workspace.parse_button.click()
        worker = workspace.parse_thread
        _require(worker is not None, "import_worker_missing")
        _wait(app, lambda: workspace.parse_thread is None, seconds=45.0,
              code="import_deadline")
        outcome = worker.last_parse_result
        _require(outcome is not None and outcome.imported_files == 2
                 and outcome.intentionally_excluded_files == 3,
                 "import_outcome_mismatch")
        _require(database.is_file(), "import_database_missing")
        import_oracle = _import_oracle(database)
        result["facets"]["real_review_import"] = "passed"

        screen = app.primaryScreen()
        _require(screen is not None, "primary_screen_missing")
        dpr = float(screen.devicePixelRatio())
        physical = [round(screen.size().width() * dpr),
                    round(screen.size().height() * dpr)]
        result["evidence"].update({
            "relative_artifact_dir": child.name,
            "qpa": app.platformName(),
            "dpr": round(dpr, 3),
            "physical_screen": physical,
            "fixture_count": len(fixture_hashes),
            "imported_count": outcome.imported_files,
            "excluded_count": outcome.intentionally_excluded_files,
            "import_oracle": import_oracle,
            "planner_geometry": geometry,
        })
        native_display = os.name == "nt" and app.platformName().casefold() == "windows"
        if native_display:
            _require(expected_dpr is not None and expected_dpr > 0,
                     "expected_dpr_missing")
            _require(abs(dpr - expected_dpr) <= 0.05, "native_dpr_mismatch")
            _require(physical == [1920, 1080], "native_physical_screen_mismatch")
            available = window.screen().availableGeometry()
            window.move(available.topLeft() + (window.pos() - window.frameGeometry().topLeft()))
            app.processEvents()
            _require(available.contains(window.frameGeometry()),
                     "native_shell_frame_outside_screen")
            result["facets"]["native_shell_layout"] = "passed"
            result["facets"]["windows_qt_planner_keyboard"] = "passed"
    finally:
        _close_shell_owner(window, app)


def run_shell_checks(scratch_directory: str | Path, fixture_directory: str | Path,
                     *, expected_dpr: float | None = None) -> dict[str, Any]:
    """Run W13 through real product UI; native facets stay unassessed off Windows."""
    from metroliza.app.bootstrap import get_or_create_qapplication

    result: dict[str, Any] = {
        "schema_version": 1,
        "runtime_context": "packaged" if getattr(sys, "frozen", False) else "source",
        "status": "failed",
        "facets": {name: "not_assessed" if name in NATIVE_FACETS else "not_run"
                   for name in FACETS},
        "error_codes": [],
        "evidence": {
            "relative_artifact_dir": None,
            "qpa": None,
            "dpr": None,
            "physical_screen": None,
            "fixture_count": None,
            "imported_count": None,
            "excluded_count": None,
            "import_oracle": None,
            "planner_geometry": None,
        },
    }
    try:
        scratch, fixtures = Path(scratch_directory), Path(fixture_directory)
        _require(scratch.is_dir() and not scratch.is_symlink(), "scratch_invalid")
        _require(fixtures.is_dir() and not fixtures.is_symlink(), "fixtures_invalid")
        app = get_or_create_qapplication()
        _run(scratch, fixtures, app, expected_dpr, result)
        native_display = os.name == "nt" and app.platformName().casefold() == "windows"
        expected = "passed" if native_display else "not_assessed"
        _require(all(value == "passed" for name, value in result["facets"].items()
                     if name not in NATIVE_FACETS), "source_facet_incomplete")
        _require(all(value == expected for name, value in result["facets"].items()
                     if name in NATIVE_FACETS), "native_facet_incomplete")
        result["status"] = "passed" if native_display else "partial"
    except ShellChecksFailure as error:
        result["error_codes"].append(str(error))
    except Exception:
        result["error_codes"].append("unexpected_exception")
    return result
