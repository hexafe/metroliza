"""Real MainWindow reopen coverage for the bounded W04 acceptance subset."""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
import time
from pathlib import Path

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QSettings, Qt

from metroliza.app.bootstrap import get_or_create_qapplication
from metroliza.app.windows_candidate_reopen import run_reopen_checks
from metroliza.ui.main_window import MainWindow
from metroliza.ui.ui_preferences import UiPreferences


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wait(application, predicate, *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    assert predicate()


@pytest.fixture(scope="module")
def application():
    return get_or_create_qapplication()


def _stage_reports(root: Path) -> tuple[Path, dict[str, str]]:
    original = Path(__file__).parent / "fixtures" / "windows_candidate" / "reports"
    reports = root / "reports"
    reports.mkdir()
    for index in range(5):
        shutil.copyfile(original / f"report-{index}.pdf", reports / f"REF001_2024-01-01_{index}.pdf")
    return reports, {path.name: _sha256(path) for path in reports.iterdir()}


def _close_window(application, window) -> None:
    window.close()
    window.deleteLater()
    application.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def _seed_completed_import(application, root: Path) -> tuple[Path, Path, dict[str, str]]:
    reports, hashes = _stage_reports(root)
    database = root / "reports.sqlite"
    settings = QSettings(str(root / "seed.ini"), QSettings.Format.IniFormat)
    window = MainWindow("candidate-reopen-seed", None, ui_preferences=UiPreferences(settings))
    try:
        window.show()
        application.processEvents()
        reports_index = window.navigation_combo.findData("reports")
        assert reports_index >= 0
        window.navigation_list.setCurrentRow(reports_index)
        workspace = window.reports_workspace
        assert window.set_directory(str(reports))
        assert window.set_db_file(str(database))
        workspace.scan_button.click()
        _wait(application, lambda: workspace.preflight_thread is None, timeout_s=30.0)
        assert not database.exists()
        assert workspace.report_planner.model.counts["total"] == 5
        workspace.report_planner.clear.click()
        assert not workspace.parse_button.isEnabled()
        for row in range(workspace.report_planner.model.rowCount()):
            item = workspace.report_planner.model.item_at(row)
            if item is not None and item.display_name in {
                "REF001_2024-01-01_1.pdf",
                "REF001_2024-01-01_3.pdf",
            }:
                assert workspace.report_planner.model.setData(
                    workspace.report_planner.model.index(row, 0),
                    Qt.CheckState.Checked,
                    Qt.ItemDataRole.CheckStateRole,
                )
        workspace.parse_button.click()
        worker = workspace.parse_thread
        assert worker is not None
        _wait(application, lambda: workspace.parse_thread is None, timeout_s=45.0)
        assert worker.last_parse_result is not None
        assert worker.last_parse_result.imported_files == 2
        assert worker.last_parse_result.intentionally_excluded_files == 3
    finally:
        _close_window(application, window)
    return database, reports, hashes


@pytest.mark.parametrize("directory", ("plain", "owned # próba"))
def test_reopen_preserves_completed_import_after_real_window_close(application, tmp_path: Path, directory) -> None:
    root = tmp_path / directory
    root.mkdir()
    database, reports, hashes = _seed_completed_import(application, root)

    result = run_reopen_checks(database, reports, hashes)

    assert result["status"] == "passed", result
    assert result["facets"] == {"reopen_preserves_completed_import": "passed"}
    assert result["database"]["counts"] == {
        "source_files": 2,
        "active_locations": 2,
        "parsed_reports": 2,
        "metadata": 2,
        "measurements": 2,
    }
    assert result["database"]["sha256"] == _sha256(database)
    assert len(result["database"]["before_sha256"]) == 64
    assert result["database"]["schema_sha256"]
    assert result["database"]["logical_dump_sha256"]
    assert result["source_hashes"] == hashes
    assert not [database.with_name(database.name + suffix) for suffix in ("-wal", "-shm", "-journal") if database.with_name(database.name + suffix).exists()]


def test_count_observation_closes_its_connection_without_leaving_sidecars(application, tmp_path):
    from metroliza.app.windows_candidate_qualification import _database_observation

    database, _, _ = _seed_completed_import(application, tmp_path)
    before = _sha256(database)
    assert _database_observation(database) == {
        "source_files": 2, "active_locations": 2, "parsed_reports": 2,
        "metadata": 2, "measurements": 2,
    }
    assert _sha256(database) == before
    assert not any(database.with_name(database.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))


def test_reopen_rejects_a_sidecar_left_by_the_last_observation(application, tmp_path, monkeypatch):
    from metroliza.app import windows_candidate_reopen as operation

    database, reports, hashes = _seed_completed_import(application, tmp_path)
    original = operation._public_measurements
    calls = []

    def leave_sidecar_after_last_read(path):
        result = original(path)
        calls.append(path)
        if len(calls) == 2:
            path.with_name(path.name + "-journal").write_bytes(b"controlled adverse sidecar")
        return result

    monkeypatch.setattr(operation, "_public_measurements", leave_sidecar_after_last_read)
    result = operation.run_reopen_checks(database, reports, hashes)
    assert result["status"] == "failed"
    assert result["failure_code"] == "database_sidecars_created"


@pytest.mark.parametrize(
    ("mutation", "expected_failure"),
    (
        (
            "UPDATE report_measurements SET meas = meas + 1 WHERE id = 1",
            "logical_dump_changed_after_reopen",
        ),
        (
            "CREATE TABLE w04_reopen_schema_control (value INTEGER)",
            "schema_changed_after_reopen",
        ),
    ),
)
def test_reopen_rejects_actual_semantic_mutation_after_real_window_rebind(
    application, tmp_path, monkeypatch, mutation, expected_failure
):
    from metroliza.app import windows_candidate_reopen as operation

    database, reports, hashes = _seed_completed_import(application, tmp_path)
    actual_reopen = operation._reopen_window

    def mutate_after_actual_reopen(path, sources):
        actual_reopen(path, sources)
        with sqlite3.connect(path) as connection:
            connection.execute(mutation)
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode=DELETE")

    monkeypatch.setattr(operation, "_reopen_window", mutate_after_actual_reopen)
    result = operation.run_reopen_checks(database, reports, hashes)

    assert result["status"] == "failed"
    assert result["failure_code"] == expected_failure
