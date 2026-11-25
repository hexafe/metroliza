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


def wait_until(app, predicate, *, parse_dialog=None):
    deadline = time.monotonic() + 20
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    if not predicate() and parse_dialog is not None:
        worker = parse_dialog.parse_thread
        assert worker is not None, "Qt parse worker disappeared without terminal state"
        result = getattr(worker, "last_parse_result", None)
        progress = parse_dialog._operation_progress
        assert False, (
            "Qt parse worker did not reach terminal state: "
            f"running={worker.isRunning()} result_finalized={getattr(result, 'total_files', 0) > 0} "
            f"progress={progress} error_seen={bool(parse_dialog.parse_error_message)}"
        )
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
    # The automatic background metadata read (#1100) is part of a finished review.
    wait_until(app, lambda: dialog.preflight_thread is None and dialog.metadata_thread is None)
    yield dialog, source, database
    for worker in (dialog.preflight_thread, dialog.parse_thread, dialog.metadata_thread):
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
        wait_until(app, lambda: dialog.preflight_thread is None and dialog.metadata_thread is None)
        assert not database.exists(), "Review must not create the destination database"
        planner = dialog.report_planner
        assert len(planner.model.selected_ids) == 5
        planner.model.clear_selection()
        reference_column = planner.model.column_for_field("reference")
        assert planner.model.setData(planner.model.index(4, reference_column), "MANUAL-4")
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
        wait_until(app, lambda: dialog.parse_thread is None, parse_dialog=dialog)
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
        dialog.scan_button.click()
        wait_until(app, lambda: dialog.preflight_thread is None and dialog.metadata_thread is None)
        assert planner.model.selected_ids == ("report-0.pdf", "report-2.pdf", "report-4.pdf")
        assert planner.model.metadata_row("report-4.pdf").value("reference") == "MANUAL-4"
        assert "Kept 1 metadata edit" in dialog.readiness_label.text()
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


def test_first_input_selection_gives_neutral_next_action_guidance(app, reports, monkeypatch):
    source, database = reports
    dialog = ParsingDialog()
    try:
        dialog._set_parse_source(str(source))
        assert "Select or create a database" in dialog.readiness_label.text()
        monkeypatch.setattr(
            "metroliza.ui.parsing_dialog.QFileDialog.getSaveFileName",
            lambda *_args: (str(database.with_suffix(".db")), ""),
        )
        dialog.select_database()
        assert "Ready to review" in dialog.readiness_label.text()
        dialog.metadata_mode_combo.setCurrentIndex(1)
        assert "Ready to review" in dialog.readiness_label.text()
        assert "invalidated" not in dialog.readiness_label.text()
        assert dialog.preflight_thread is None and dialog.parse_thread is None
        assert not Path(dialog.db_file).exists()
    finally:
        dialog.close()
        app.processEvents()


def test_selection_does_not_recompute_immutable_review_approval(reviewed, monkeypatch):
    from metroliza.parsing.preflight import ParsePreflightResult

    dialog, _source, _database = reviewed

    approval_calls = []
    original_approval = ParsePreflightResult.atomic_import_candidates

    def track_full_approval(*args, **kwargs):
        approval_calls.append(True)
        return original_approval(*args, **kwargs)

    monkeypatch.setattr(ParsePreflightResult, "atomic_import_candidates", track_full_approval)
    planner = dialog.report_planner
    planner.clear.click()
    planner.model.setData(planner.model.index(3, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    planner.search.setText("report-0")
    assert approval_calls == [], "Checkbox edits must not recompute every reviewed row"
    assert dialog.parse_button.isEnabled()
    assert dialog.parse_button.text() == "Import 1 selected report"


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
    wait_until(app, lambda: dialog.preflight_thread is None and dialog.metadata_thread is None)
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


@pytest.mark.parametrize("termination", ["cancel", "error"])
def test_batch_retains_only_committed_ids_and_digests_after_early_termination(app, reviewed, monkeypatch, termination):
    from metroliza.parsing import parse_reports_thread
    from metroliza.reports.report_repository import ReportRepository

    dialog, _source, database = reviewed
    entered, release = Event(), Event()
    records = []
    dialog.import_batch_finished.connect(records.append)
    if termination == "cancel":
        persist = ReportRepository.import_report_if_absent

        def pause_after_commit(self, **kwargs):
            outcome = persist(self, **kwargs)
            entered.set()
            assert release.wait(10)
            return outcome

        monkeypatch.setattr(ReportRepository, "import_report_if_absent", pause_after_commit)
    else:
        parse = parse_reports_thread.parse_new_reports

        def fail_after_commit(*args, **kwargs):
            def interrupt(*_args):
                raise RuntimeError("synthetic post-commit error")

            kwargs["on_file_accepted"] = interrupt
            return parse(*args, **kwargs)

        monkeypatch.setattr(parse_reports_thread, "parse_new_reports", fail_after_commit)
    dialog.parse_button.click()
    try:
        if termination == "cancel":
            wait_until(app, entered.is_set)
            dialog.stop_parsing()
    finally:
        release.set()
    wait_until(app, lambda: dialog.parse_thread is None, parse_dialog=dialog)
    assert len(records) == 1 and records[0].matches_database(database)
    with closing(sqlite3.connect(database)) as connection:
        saved = connection.execute(
            "SELECT pr.id, sf.sha256 FROM parsed_reports pr JOIN source_files sf ON sf.id = pr.source_file_id"
        ).fetchall()
    assert len(saved) == 1
    assert records[0].reports == tuple(saved)


@pytest.mark.parametrize("field", ["source", "destination", "metadata"])
def test_input_change_invalidates_review_and_selection(reviewed, monkeypatch, field):
    dialog, source, database = reviewed
    model = dialog.report_planner.model
    assert model.setData(model.index(0, model.column_for_field("reference")), "MANUAL")
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
    assert bool(dialog._metadata_carryover) is (field == "metadata")


def test_metadata_mode_review_keeps_edits_for_exact_unchanged_occurrences(app, reports):
    source, database = reports
    nested = source / "nested"
    nested.mkdir()
    fixture = source / "report-0.pdf"
    with fitz.open(fixture) as document:
        document.set_metadata({"title": "Same name in a different folder"})
        document.save(nested / fixture.name)

    dialog = ParsingDialog(directory=str(source), db_file=str(database))
    try:
        dialog.scan_button.click()
        wait_until(app, dialog.pdf_workers_idle)
        model = dialog.report_planner.model
        column = model.column_for_field("reference")
        corrections = {"report-0.pdf": "OUTSIDE-EDIT", "nested/report-0.pdf": "NESTED-EDIT"}
        for row in range(model.rowCount()):
            occurrence = model.item_at(row).stable_occurrence_id
            if occurrence in corrections:
                assert model.setData(model.index(row, column), corrections[occurrence])
        with fitz.open(fixture) as document:
            document.set_metadata({"title": "Replacement at the original path"})
            document.saveIncr()
        dialog.metadata_mode_combo.setCurrentIndex(dialog.metadata_mode_combo.findData("complete"))
        assert not dialog.parse_button.isEnabled()
        dialog.scan_button.click()
        wait_until(app, dialog.pdf_workers_idle)

        assert model.metadata_row("report-0.pdf").value("reference") != "OUTSIDE-EDIT"
        assert model.metadata_row("nested/report-0.pdf").value("reference") == "NESTED-EDIT"
        assert "Check previous metadata edits for report-0.pdf" in dialog.readiness_label.text()
        assert dialog.parse_button.isEnabled()
    finally:
        dialog.close()


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
    wait_until(app, lambda: dialog.parse_thread is None, parse_dialog=dialog)
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
    wait_until(app, lambda: dialog.parse_thread is None, parse_dialog=dialog)
    dialog.scan_button.click()
    wait_until(app, lambda: dialog.preflight_thread is None and dialog.metadata_thread is None)
    model = dialog.report_planner.model
    assert model.rowCount() == 5
    assert not model.selected_ids
    for row in range(5):
        assert model.data(model.index(row, 2)) == "Already imported"
        assert not model.flags(model.index(row, 0)) & Qt.ItemFlag.ItemIsUserCheckable
    assert not dialog.parse_button.isEnabled()
    assert "All reviewed reports are already in the database" in dialog.readiness_label.text()
    assert "Select ready reports" not in dialog.readiness_label.text()


@pytest.mark.parametrize("archive", [False, True])
def test_no_ready_report_guidance_matches_empty_or_unreadable_source(app, tmp_path, archive):
    source = tmp_path / ("damaged.zip" if archive else "empty")
    if archive:
        source.write_bytes(b"synthetic invalid archive")
    else:
        source.mkdir()
    database = tmp_path / "scratch.sqlite3"
    dialog = ParsingDialog(directory=str(source), db_file=str(database))
    dialog.show()
    try:
        dialog.scan_button.click()
        wait_until(app, dialog.pdf_workers_idle)
        message = dialog.readiness_label.text()
        assert "Select ready reports" not in message
        if archive:
            assert "could not be read" in message and "Report details" in message
            assert dialog.focusWidget() is dialog.report_planner.details_button
            dialog.report_planner.details_button.click()
            assert "synthetic invalid archive" not in dialog.report_planner.details.toPlainText()
        else:
            assert "No reports were found" in message and "Choose another folder or archive" in message
            assert dialog.focusWidget() is dialog.directory_button
        assert not database.exists()
    finally:
        dialog.close()


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
    monkeypatch.setattr(
        report_parser_factory, "get_registry_snapshot",
        lambda *, refresh=True: replace(snapshot, generation_id=snapshot.generation_id + 1)
        if refresh else snapshot,
    )
    dialog._import_reviewed_reports()
    assert dialog.parse_thread is None
    assert dialog.report_planner.model.selected_ids == ()
    assert not dialog.parse_button.isEnabled()
    assert "Changed since review" in dialog.readiness_label.text()
    assert not database.exists()


def test_selection_uses_cached_registry_but_import_refreshes_before_real_execution(app, reviewed, monkeypatch):
    from metroliza.parsing import report_parser_factory

    dialog, _source, database = reviewed
    original_refresh = report_parser_factory._ensure_external_plugins_loaded_once
    refreshes = []

    def track_filesystem_refresh():
        refreshes.append(True)
        return original_refresh()

    monkeypatch.setattr(report_parser_factory, "_ensure_external_plugins_loaded_once", track_filesystem_refresh)
    planner = dialog.report_planner
    planner.clear.click()
    planner.model.setData(planner.model.index(2, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    planner.search.setText("report-0")
    assert refreshes == [], "Selection and filters must not refresh external parser files"
    assert dialog.parse_button.text() == "Import 1 selected report"
    dialog._import_reviewed_reports()
    assert refreshes, "Import must refresh the authoritative registry before dispatch"
    worker = dialog.parse_thread
    wait_until(app, lambda: dialog.parse_thread is None)
    assert worker.last_parse_result.imported_files == 1
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT file_name FROM source_file_locations").fetchall() == [
            ("report-2.pdf",),
        ]


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
        wait_until(app, lambda: dialog.preflight_thread is None and dialog.metadata_thread is None)
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
        wait_until(app, lambda: dialog.preflight_thread is None and dialog.metadata_thread is None)
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


def _profile_journey_yaml(version, reference_field, header, marker="SYNTHETIC PROFILE JOURNEY"):
    row_pattern = (
        r"^DIM\s+(?P<axis_code>\w+)\s+(?P<nominal>[-0-9.]+)"
        r"\s+(?P<tol_plus>[-0-9.]+)\s+(?P<tol_minus>[-0-9.]+)\s+(?P<bonus>[-0-9.]+)"
        r"\s+(?P<measured>[-0-9.]+)\s+(?P<deviation>[-0-9.]+)"
        r"\s+(?P<out_of_tolerance>[-0-9.]+)$"
    )
    return rf"""
schema_version: 1
plugin:
  plugin_id: synthetic_profile_journey
  display_name: Synthetic profile journey
  version: {version}
  source_format: pdf
  supported_locales: ["*"]
  template_ids: [synthetic_profile_template]
  priority: 910
probe:
  required_markers: ["{marker}"]
  reject_markers: []
  confidence: 91
extraction:
  report_fields:
    reference: '^{reference_field}:\s*(?P<value>\S+)$'
    report_date: '^Date:\s*(?P<value>\d{{4}}-\d{{2}}-\d{{2}})$'
    sample_number: '^Sample:\s*(?P<value>\S+)$'
  blocks:
    - header: "{header}"
      pattern: '{row_pattern}'
normalization:
  decimal_separator: "."
  date_formats: ["%Y-%m-%d"]
"""


def _write_profile_journey_expectations(expected, reference, header):
    expected.write_text(
        "sample_file,reference,report_date,sample_number,block_index,header_normalized,"
        "axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance\n"
        f"profile-sample.pdf,{reference},2026-01-05,0007,0,{header},X,10,0.2,-0.2,,10.09,0.09,0\n"
        f"profile-sample.pdf,{reference},2026-01-05,0007,0,{header},Y,20,0.2,-0.2,0.01,20.35,0.35,0.14\n",
        encoding="utf-8",
    )


def _review_and_import_profile(app, source, database, *, approved=True):
    dialog = ParsingDialog(directory=str(source), db_file=str(database))
    try:
        dialog.scan_button.click()
        wait_until(app, lambda: dialog.preflight_thread is None and dialog.metadata_thread is None)
        assert not database.exists()
        if not approved:
            assert not dialog.parse_button.isEnabled()
            assert not dialog.report_planner.model.selected_ids
            dialog._import_reviewed_reports()
            assert dialog.parse_thread is None
            assert not database.exists()
            return

        assert dialog.report_planner.model.selected_ids == ("profile-sample.pdf",)
        dialog.parse_button.click()
        worker = dialog.parse_thread
        assert worker is not None
        wait_until(app, lambda: dialog.parse_thread is None, parse_dialog=dialog)
        assert worker.last_parse_result.imported_files == 1
        assert worker.last_parse_result.failed_files == 0
    finally:
        if dialog.parse_thread is not None:
            dialog.parse_thread.stop_parsing()
            dialog.parse_thread.wait(20000)
        if dialog.preflight_thread is not None:
            dialog.preflight_thread.stop_scan()
            dialog.preflight_thread.wait(20000)
        dialog.close()


def _assert_profile_journey_database(database, *, version, reference, header):
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("""
            SELECT pr.parser_id, pr.parser_version, pr.template_variant, pr.measurement_count,
                   pr.has_nok, pr.nok_count, rm.reference, rm.report_date, rm.sample_number,
                   src.file_name
            FROM parsed_reports AS pr
            JOIN report_metadata AS rm ON rm.report_id = pr.id
            JOIN source_file_locations AS src ON src.source_file_id = pr.source_file_id
        """).fetchall() == [
            ("synthetic_profile_journey", version, "synthetic_profile_template", 2, 1, 1,
             reference, "2026-01-05", "0007", "profile-sample.pdf"),
        ]
        assert connection.execute("""
            SELECT header, ax, nominal, tol_plus, tol_minus, bonus, meas, dev, outtol,
                   status_code, is_nok
            FROM report_measurements
            ORDER BY row_order
        """).fetchall() == [
            (header, "X", 10.0, 0.2, -0.2, None, 10.09, 0.09, 0.0, "ok", 0),
            (header, "Y", 20.0, 0.2, -0.2, 0.01, 20.35, 0.35, 0.14, "nok", 1),
        ]


def test_profile_handoff_approval_and_rollback_drive_real_reports_import(app, tmp_path, monkeypatch):
    from metroliza.parsing.declarative_parser_profiles import approved_profiles_dir
    from metroliza.parsing.parser_plugin_paths import invalidate_parser_plugin_runtime
    from metroliza.parsing.report_parser_factory import get_registry_snapshot
    from scripts import parser_plugin_self_service as cli

    home = tmp_path / "isolated operator profile"
    handoff = tmp_path / "parser handoff"
    plugin_id = "synthetic_profile_journey"
    assert cli.main([
        "--home", str(home), "handoff", "--plugin-id", plugin_id, "--output-dir", str(handoff),
    ]) == 0
    assert cli.main(["integrity", str(handoff)]) == 0

    profile = handoff / "profile.yaml"
    expected = handoff / "expected_results.csv"
    source = handoff / "samples"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), (
            "SYNTHETIC PROFILE JOURNEY\nReference: REF-A\nAlternate reference: REF-B\n"
            "Date: 2026-01-05\nSample: 0007\n"
            "DIM X 10 0.2 -0.2 - 10.09 0.09 0\nDIM Y 20 0.2 -0.2 0.01 20.35 0.35 0.14"
        ))
        document.save(source / "profile-sample.pdf")
    _write_profile_journey_expectations(expected, "REF-A", "TEST FEATURE")
    candidate_args = [str(profile), "--expected-results", str(expected), "--workspace", str(handoff)]
    install_args = ["--home", str(home), "install", *candidate_args, "--approved-by", "test operator"]

    profile.write_text(
        _profile_journey_yaml("0.1.0", "Reference", "TEST FEATURE", marker="WRONG MARKER"),
        encoding="utf-8",
    )
    assert cli.main(["repair", *candidate_args]) == 1
    repair_prompt = (handoff / "artifacts" / "profile_repair_prompt.md").read_text(encoding="utf-8")
    assert "Return complete corrected `profile.yaml` only" in repair_prompt
    assert "sample_profile_probe_selected" in repair_prompt
    assert "probe_required_markers_present" not in repair_prompt
    assert "profile-sample.pdf" not in repair_prompt
    assert cli.main(install_args) == 1
    approved_profile = approved_profiles_dir(home=home) / plugin_id / "profile.yaml"
    assert not approved_profile.exists()

    profile.write_text(_profile_journey_yaml("0.1.0", "Reference", "TEST FEATURE"), encoding="utf-8")
    assert cli.main(["validate", *candidate_args]) == 0
    approved_profile.parent.mkdir(parents=True)
    approved_profile.write_bytes(profile.read_bytes())

    try:
        with monkeypatch.context() as context:
            context.setattr(Path, "home", lambda: home)
            context.delenv("PARSER_EXTERNAL_PLUGIN_PATHS", raising=False)
            context.delenv("PARSER_DISABLED_PLUGIN_IDS", raising=False)
            context.setattr(QMessageBox, "information", lambda *_args: None)
            context.setattr(QMessageBox, "warning", lambda *_args: None)
            invalidate_parser_plugin_runtime()

            _review_and_import_profile(app, source, tmp_path / "unapproved.db", approved=False)
            approved_profile.unlink()
            approved_profile.parent.rmdir()

            first_database = tmp_path / "first.db"
            assert cli.main(install_args) == 0
            _review_and_import_profile(app, source, first_database)
            _assert_profile_journey_database(
                first_database, version="0.1.0", reference="REF-A", header="TEST FEATURE",
            )

            updated_database = tmp_path / "updated.db"
            profile.write_text(
                _profile_journey_yaml("0.2.0", "Alternate reference", "SECOND FEATURE"),
                encoding="utf-8",
            )
            _write_profile_journey_expectations(expected, "REF-B", "SECOND FEATURE")
            assert cli.main(install_args) == 0
            _review_and_import_profile(app, source, updated_database)
            _assert_profile_journey_database(
                updated_database, version="0.2.0", reference="REF-B", header="SECOND FEATURE",
            )

            restored_database = tmp_path / "restored.db"
            assert cli.main(["--home", str(home), "rollback", plugin_id]) == 0
            _review_and_import_profile(app, source, restored_database)
            _assert_profile_journey_database(
                restored_database, version="0.1.0", reference="REF-A", header="TEST FEATURE",
            )

            store_args = ["--home", str(home)]
            assert cli.main([*store_args, "uninstall", plugin_id]) == 0
            assert not approved_profile.exists()
            archives = list(approved_profile.parents[2].glob(f"backups/{plugin_id}-removed-*"))
            archive, = archives
            _review_and_import_profile(app, source, tmp_path / "removed.db", approved=False)
            assert cli.main([*store_args, "rollback", plugin_id]) == 1
            assert not approved_profile.exists()
            assert cli.main([*store_args, "rollback", plugin_id, "--backup-name", archive.name]) == 0
            reenabled_database = tmp_path / "reenabled.db"
            _review_and_import_profile(app, source, reenabled_database)
            _assert_profile_journey_database(
                reenabled_database, version="0.1.0", reference="REF-A", header="TEST FEATURE",
            )
    finally:
        invalidate_parser_plugin_runtime()
        get_registry_snapshot()
