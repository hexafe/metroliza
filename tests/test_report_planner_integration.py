"""Production planner through real Qt workers and synthetic scratch SQLite."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
from threading import Event
import time
import zipfile

import fitz
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

from metroliza.ui.parsing_dialog import ParsingDialog
from metroliza.parsing.preflight import ParsePreflightService


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    expected = os.environ.get("METROLIZA_EXPECT_QT_PLATFORM")
    if expected:
        assert application.platformName().casefold() == expected.casefold()
    return application


def wait_until(app, predicate):
    deadline = time.monotonic() + 20
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert predicate(), "Qt worker did not reach the expected terminal state"


@pytest.fixture
def reports(tmp_path):
    source = tmp_path / "public synthetic reports"
    source.mkdir()
    fixture = Path(__file__).parent / "fixtures/pdf/cmm_smoke_fixture.pdf"
    for number in range(5):
        with fitz.open(fixture) as document:
            document.set_metadata({"title": f"Public synthetic report {number}"})
            document.save(source / f"report-{number}.pdf")
    return source, tmp_path / "scratch.sqlite3"


@pytest.fixture
def reviewed(app, reports, monkeypatch):
    source, database = reports
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    dialog = ParsingDialog(directory=str(source), db_file=str(database))
    dialog.show()
    dialog.scan_reports()
    wait_until(app, lambda: dialog.preflight_thread is None)
    yield dialog, source, database
    for worker in (dialog.preflight_thread, dialog.parse_thread):
        if worker is not None:
            dialog._request_active_worker_cancellation()
            worker.wait(20000)
    app.processEvents()
    dialog.close()


def test_real_review_selection_imports_exactly_two_of_five(app, reports, monkeypatch):
    source, database = reports
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[2]))
    dialog = ParsingDialog(directory=str(source), db_file=str(database))
    dialog.show()
    try:
        dialog.scan_button.click()
        wait_until(app, lambda: dialog.preflight_thread is None)
        assert not database.exists(), "Review must not create the destination database"
        planner = dialog.report_planner
        assert len(planner.model.selected_ids) == 5
        planner.model.clear_selection()
        for row in (1, 3):
            planner.model.setData(
                planner.model.index(row, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
            )
        planner.search.setText("report-0")
        assert planner.proxy.rowCount() == 1
        assert len(planner.model.selected_ids) == 2
        assert dialog.parse_button.text() == "Import 2 selected reports"
        dialog.parse_button.click()
        worker = dialog.parse_thread
        assert worker is not None
        wait_until(app, lambda: dialog.parse_thread is None)
        assert worker.last_parse_result.imported_files == 2
        assert worker.last_parse_result.intentionally_excluded_files == 3
        with closing(sqlite3.connect(database)) as connection:
            names = {row[0] for row in connection.execute(
                "SELECT file_name FROM source_file_locations"
            )}
            assert names == {"report-1.pdf", "report-3.pdf"}
            assert connection.execute("SELECT count(*) FROM report_measurements").fetchone()[0] > 0
        assert not dialog.parse_button.isEnabled()
        assert not planner.model.selected_ids
        assert "Saved: 2 report files" in planner.outcome.toPlainText()
        assert messages
    finally:
        if dialog.parse_thread is not None:
            dialog.parse_thread.stop_parsing()
            dialog.parse_thread.wait(20000)
        if dialog.preflight_thread is not None:
            dialog.preflight_thread.stop_scan()
            dialog.preflight_thread.wait(20000)
        dialog.close()


def test_empty_selection_never_starts_worker_or_writes(reviewed):
    dialog, _source, database = reviewed
    dialog.report_planner.clear.click()
    assert dialog.parse_button.text() == "Import 0 selected reports"
    assert not dialog.parse_button.isEnabled()
    assert "Select ready reports" in dialog.parse_button.toolTip()
    dialog._import_reviewed_reports()
    assert dialog.parse_thread is None
    assert not database.exists()


@pytest.mark.parametrize("stage", ["review", "import"])
def test_worker_start_failure_releases_busy_state_and_allows_retry(app, reviewed, monkeypatch, stage):
    from metroliza.ui import parsing_dialog

    dialog, _source, database = reviewed
    worker_type = (parsing_dialog.ParsePreflightThread if stage == "review"
                   else parsing_dialog.ParseReportsThread)
    errors = []
    monkeypatch.setattr(dialog, "log_and_exit", errors.append)

    def start_failed(_worker):
        raise RuntimeError("Synthetic thread startup failure")

    with monkeypatch.context() as startup:
        startup.setattr(worker_type, "start", start_failed)
        if stage == "review":
            dialog.scan_reports()
        else:
            dialog._import_reviewed_reports()
    assert len(errors) == 1
    assert dialog.preflight_thread is None and dialog.parse_thread is None
    assert dialog.scan_button.isEnabled()
    assert not dialog.parse_button.isEnabled()
    assert "could not start" in dialog.readiness_label.text()
    assert not database.exists()
    dialog.scan_reports()
    wait_until(app, lambda: dialog.preflight_thread is None)
    assert dialog.parse_button.isEnabled()
    assert len(dialog.report_planner.model.selected_ids) == 5


@pytest.mark.parametrize("terminal", ["missing", "failed", "cancelled"])
def test_persistent_outcome_never_invents_success_without_result(reviewed, terminal):
    from types import SimpleNamespace

    dialog, _source, database = reviewed
    dialog.parse_thread = SimpleNamespace(last_parse_result=None)
    dialog.parse_error_message = "Synthetic worker failure" if terminal == "failed" else None
    dialog.parsing_canceled = terminal == "cancelled"
    dialog.on_parse_finished()
    dialog._on_parse_thread_stopped(dialog.parse_thread)
    text = dialog.report_planner.outcome.toPlainText()
    assert "outcome unavailable" in text
    assert "successful" not in text
    assert "saved to" not in text
    assert not database.exists()


@pytest.mark.parametrize("field", ["source", "destination", "metadata"])
def test_input_change_invalidates_review_and_selection(reviewed, monkeypatch, field):
    dialog, source, database = reviewed
    if field == "source":
        dialog._set_parse_source(str(source / "other"))
    elif field == "destination":
        monkeypatch.setattr(
            "metroliza.ui.parsing_dialog.QFileDialog.getSaveFileName",
            lambda *_args: (str(database.with_name("another.db")), ""),
        )
        dialog.select_database()
    else:
        dialog.metadata_mode_combo.setCurrentIndex(1)
    assert dialog.report_planner.model.selected_ids == ()
    assert dialog.report_planner.model.rowCount() == 0
    assert not dialog.parse_button.isEnabled()
    assert "invalidated" in dialog.readiness_label.text()
    assert not database.exists()


def test_changed_selected_source_is_blocked_by_real_worker(app, reviewed):
    dialog, source, database = reviewed
    planner = dialog.report_planner
    planner.model.clear_selection()
    for row in (0, 1):
        planner.model.setData(planner.model.index(row, 0), Qt.CheckState.Checked,
                              Qt.ItemDataRole.CheckStateRole)
    (source / "report-0.pdf").write_bytes(b"changed public synthetic input")
    dialog.parse_button.click()
    worker = dialog.parse_thread
    wait_until(app, lambda: dialog.parse_thread is None)
    result = worker.last_parse_result
    assert result.imported_files == 1
    assert result.preflight_changed_files == 1
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT file_name FROM source_file_locations").fetchall() == [
            ("report-1.pdf",)
        ]
    assert "Changed since review" in planner.outcome.toPlainText()
    assert not planner.model.selected_ids


def test_destination_matches_cannot_be_selected_after_refresh(app, reviewed):
    dialog, _source, _database = reviewed
    dialog.parse_button.click()
    wait_until(app, lambda: dialog.parse_thread is None)
    dialog.scan_button.click()
    wait_until(app, lambda: dialog.preflight_thread is None)
    model = dialog.report_planner.model
    assert model.rowCount() == 5
    assert not model.selected_ids
    for row in range(5):
        assert model.data(model.index(row, 2)) == "Already imported"
        assert not model.flags(model.index(row, 0)) & Qt.ItemFlag.ItemIsUserCheckable
    assert not dialog.parse_button.isEnabled()


def test_concurrent_destination_claim_keeps_exact_selected_plan(app, reviewed):
    from metroliza.parsing.parse_reports_thread import ParseReportsThread
    from metroliza.parsing.preflight import ImportPlan
    from metroliza.shared.parse_contracts import ParseRequest

    dialog, source, database = reviewed
    review = dialog._preflight_result
    concurrent = ParseReportsThread(ImportPlan.from_preflight(
        ParseRequest(source_directory=str(source), db_file=str(database),
                     metadata_parsing_mode="light"),
        review, selected_occurrence_ids=("report-1.pdf",),
    ))
    concurrent.run()
    assert concurrent.last_parse_result.imported_files == 1
    model = dialog.report_planner.model
    model.clear_selection()
    for row in (1, 3):
        model.setData(model.index(row, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    dialog._import_reviewed_reports()
    worker = dialog.parse_thread
    wait_until(app, lambda: dialog.parse_thread is None)
    assert worker.last_parse_result.imported_files == 1
    assert worker.last_parse_result.already_present_files == 1
    assert worker.last_parse_result.intentionally_excluded_files == 3
    with closing(sqlite3.connect(database)) as connection:
        assert set(connection.execute("SELECT file_name FROM source_file_locations")) == {
            ("report-1.pdf",), ("report-3.pdf",),
        }


def test_parser_generation_drift_clears_ui_approval(reviewed, monkeypatch):
    from dataclasses import replace
    from metroliza.parsing import report_parser_factory

    dialog, _source, database = reviewed
    snapshot = report_parser_factory.get_registry_snapshot()
    monkeypatch.setattr(report_parser_factory, "get_registry_snapshot", lambda: replace(
        snapshot, generation_id=snapshot.generation_id + 1,
    ))
    dialog._import_reviewed_reports()
    assert dialog.parse_thread is None
    assert dialog.report_planner.model.selected_ids == ()
    assert not dialog.parse_button.isEnabled()
    assert "Changed since review" in dialog.readiness_label.text()
    assert not database.exists()


def test_archive_selection_uses_member_location_and_real_import(app, reports, monkeypatch):
    source, database = reports
    archive = source.parent / "public archive.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for path in source.glob("*.pdf"):
            output.write(path, f"nested/{path.name}")
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    dialog = ParsingDialog(directory=str(archive), db_file=str(database))
    try:
        dialog.scan_reports()
        wait_until(app, lambda: dialog.preflight_thread is None)
        planner = dialog.report_planner
        model = planner.model
        assert set(model.selected_ids) == {f"nested/report-{n}.pdf" for n in range(5)}
        assert Path(model.data(model.index(0, 1))).as_posix() == "nested/report-0.pdf"
        assert str(source.parent) not in model.details_text(0)
        model.clear_selection()
        model.setData(model.index(2, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        dialog._import_reviewed_reports()
        worker = dialog.parse_thread
        wait_until(app, lambda: dialog.parse_thread is None)
        assert worker.last_parse_result.imported_files == 1
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT file_name FROM source_file_locations").fetchall() == [
                ("report-2.pdf",)
            ]
    finally:
        dialog.close()


@pytest.mark.parametrize("close", [False, True])
def test_real_review_cancellation_and_deferred_close(app, reports, monkeypatch, close):
    source, database = reports
    entered, release = Event(), Event()
    original = ParsePreflightService.scan_source

    def gated_scan(self, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(self, **kwargs)

    monkeypatch.setattr(ParsePreflightService, "scan_source", gated_scan)
    dialog = ParsingDialog(directory=str(source), db_file=str(database))
    dialog.show()
    try:
        dialog.scan_button.click()
        worker = dialog.preflight_thread
        wait_until(app, entered.is_set)
        dialog.scan_reports()
        dialog._import_reviewed_reports()
        assert dialog.preflight_thread is worker
        assert dialog.parse_thread is None
        if close:
            dialog.close()
            assert dialog.is_close_deferred()
            assert dialog.isVisible()
        else:
            dialog.stop_scanning()
        release.set()
        wait_until(app, lambda: dialog.preflight_thread is None)
        assert not database.exists()
        assert not dialog.report_planner.model.selected_ids
        assert not dialog.parse_button.isEnabled()
        if close:
            assert not dialog.isVisible()
            assert not dialog.is_close_deferred()
        else:
            assert dialog.scan_button.isEnabled()
            assert "cancelled" in dialog.readiness_label.text()
            assert dialog.scan_button.hasFocus()
    finally:
        release.set()
        if dialog.preflight_thread:
            dialog.stop_scanning()
            dialog.preflight_thread.wait(20000)
        dialog.close()
