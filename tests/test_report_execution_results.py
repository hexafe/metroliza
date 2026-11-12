"""Execution facts survive import without becoming another approved import plan."""

from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from metroliza.parsing import parse_reports_thread as backend
from metroliza.ui.parsing_dialog import ParsingDialog
from metroliza.ui.report_planner import ReportPlanner
from metroliza.ui.report_planner_model import (
    ExecutionStatus, ReportExecutionRow, build_execution_rows,
)
from tests.test_report_planner_integration import app as app, reports as reports, wait_until
from tests.test_report_planner_model import _review


def test_execution_rows_require_exact_unambiguous_receipts(app):
    review = _review()
    first = review.files[0]
    second = replace(first, display_name="other/A-ready.pdf", occurrence_id="other/A-ready.pdf")
    review = replace(review, files=(first, second, *review.files[1:]))
    selected = (first.stable_occurrence_id, second.stable_occurrence_id)
    rows = build_execution_rows(review, selected, (backend.ReportImportReceipt(selected[0], "saved"),))
    assert [row.status for row in rows] == [ExecutionStatus.SAVED, ExecutionStatus.UNKNOWN,
                                          ExecutionStatus.SKIPPED, ExecutionStatus.SKIPPED]
    assert {field.name for field in fields(ReportExecutionRow)} == {
        "stable_occurrence_id", "display_name", "parser_id", "status", "detail", "needs_attention",
    }
    planner = ReportPlanner()
    planner.set_review(review)
    planner.show_execution_rows(rows)
    assert planner.model._review is None
    assert planner.model.metadata_rows == {}
    assert not planner.model.valid and planner.model.selected_ids == ()
    assert planner.proxy.rowCount() == 4
    assert "1 saved" in planner.counts.text() and "1 unknown" in planner.counts.text()
    for row in range(4):
        index = planner.model.index(row, 0)
        assert not planner.model.flags(index) & (Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
        assert not planner.model.setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    planner.attention_filter.setChecked(True)
    assert planner.proxy.rowCount() == 2  # unknown + unsupported; review duplicates were not submitted
    planner.search.setText("other/A-ready")
    assert planner.proxy.rowCount() == 1
    planner.invalidate()
    assert planner.model.rowCount() == 0 and planner.model.execution_rows == ()
    planner.close()


@pytest.mark.parametrize("receipts", [(),
    (SimpleNamespace(occurrence_id="archive/A-ready.pdf", state="unknown-state"),),
    (SimpleNamespace(occurrence_id="archive/A-ready.pdf", state="saved"),) * 2,
])
def test_missing_invalid_or_duplicate_evidence_never_means_saved(receipts):
    review = _review()
    rows = build_execution_rows(review, ("archive/A-ready.pdf",), receipts)
    assert rows[0].status is ExecutionStatus.UNKNOWN
    ambiguous = replace(review, files=(review.files[0], review.files[0]))
    rows = build_execution_rows(ambiguous, ("archive/A-ready.pdf",),
                                (backend.ReportImportReceipt("archive/A-ready.pdf", "saved"),))
    assert all(row.status is ExecutionStatus.UNKNOWN for row in rows)


@pytest.fixture
def dialog(app, reports, monkeypatch):
    source, database = reports
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    owner = ParsingDialog(directory=str(source), db_file=str(database))
    owner.show()
    yield owner, source, database
    for worker in (owner.preflight_thread, owner.parse_thread, *owner._metadata_threads):
        if worker is not None:
            owner._request_active_worker_cancellation()
            assert worker.wait(20000)
    app.processEvents()
    owner.close()


def review_and_import(app, owner):
    owner.scan_button.click()
    wait_until(app, lambda: owner.preflight_thread is None and owner.metadata_thread is None)
    owner.parse_button.click()
    worker = owner.parse_thread
    assert worker is not None
    wait_until(app, lambda: owner.parse_thread is None, parse_dialog=owner)
    return worker


def test_twelve_reports_keep_result_rows_then_require_fresh_review(app, dialog):
    owner, source, _database = dialog
    fixture = source / "report-0.pdf"
    for number in range(5, 12):
        with fitz.open(fixture) as document:
            document.set_metadata({"title": f"Public synthetic result {number}"})
            document.save(source / f"report-{number}.pdf")
    worker = review_and_import(app, owner)
    planner = owner.report_planner
    assert worker.last_parse_result.imported_files == 12
    assert len(worker.last_report_outcomes) == 12
    assert all(receipt.state == "saved" for receipt in worker.last_report_outcomes)
    assert len(planner.model.execution_rows) == 12
    assert planner.model.execution_counts == {"saved": 12}
    assert "12 report results" in planner.counts.text() and "12 saved" in planner.counts.text()
    assert "Saved: 12 report files" in planner.outcome.toPlainText()
    assert owner.import_succeeded and owner._preflight_result is None
    assert planner.model._review is None and planner.model.metadata_rows == {}
    assert not owner.parse_button.isEnabled()
    assert owner.scan_button.text() == "Review again"
    owner._import_reviewed_reports()
    assert owner.parse_thread is None
    owner.scan_button.click()
    wait_until(app, lambda: owner.preflight_thread is None and owner.metadata_thread is None)
    assert planner.model.valid and planner.model.execution_rows == ()
    assert planner.model.rowCount() == 12 and planner.model.counts["ready"] == 0
    assert not owner.parse_button.isEnabled()


def test_partial_failure_results_match_exact_occurrence_and_attention(app, dialog, monkeypatch):
    owner, _source, _database = dialog
    get_parser = backend.get_parser

    def parser(path, *args, **kwargs):
        if Path(path).name == "report-1.pdf":
            raise ValueError("synthetic untrusted diagnostic must stay out of result table")
        return get_parser(path, *args, **kwargs)

    monkeypatch.setattr(backend, "get_parser", parser)
    worker = review_and_import(app, owner)
    planner = owner.report_planner
    assert worker.last_parse_result.failed_files == 1
    assert planner.model.execution_counts == {"saved": 4, "failed": 1}
    planner.attention_filter.setChecked(True)
    assert planner.proxy.rowCount() == 1
    assert planner.proxy.index(0, planner.model.LOCATION_COLUMN).data() == "report-1.pdf"
    assert not owner.import_succeeded and not owner.parse_button.isEnabled()
    assert "untrusted" not in planner.model.details_text(1)


def test_cancel_keeps_proven_success_and_marks_unproven_reports_unknown(app, dialog, monkeypatch):
    owner, _source, _database = dialog
    parse = backend.parse_new_reports

    def cancel_after_first(*args, **kwargs):
        accepted = []
        callback = kwargs["on_file_accepted"]
        cancelled = kwargs["should_cancel"]

        def record(*receipt):
            callback(*receipt)
            accepted.append(True)

        kwargs["on_file_accepted"] = record
        kwargs["should_cancel"] = lambda: bool(accepted) or cancelled()
        return parse(*args, **kwargs)

    monkeypatch.setattr(backend, "parse_new_reports", cancel_after_first)
    worker = review_and_import(app, owner)
    assert worker.last_parse_result.cancelled_files == 4
    assert owner.report_planner.model.execution_counts == {"saved": 1, "unknown": 4}
    assert not owner.import_succeeded and not owner.parse_button.isEnabled()


def test_checkpoint_failure_publishes_no_saved_receipts(app, dialog, monkeypatch):
    owner, _source, _database = dialog

    def fail_checkpoint(_connection):
        raise OSError("synthetic checkpoint failure")

    monkeypatch.setattr(backend, "checkpoint_pending_import_commits", fail_checkpoint)
    worker = review_and_import(app, owner)
    assert worker.last_parse_result.imported_files == 5
    assert worker.last_report_outcomes == ()
    assert owner.report_planner.model.execution_counts == {"unknown": 5}
    assert not owner.import_succeeded
    assert "Import failed" in owner.report_planner.outcome.toPlainText()


def test_worker_receipts_keep_same_filenames_in_separate_directories(app, dialog):
    owner, source, _database = dialog
    nested = source / "nested"
    nested.mkdir()
    (source / "report-1.pdf").rename(nested / "report-0.pdf")
    worker = review_and_import(app, owner)
    identities = {receipt.occurrence_id for receipt in worker.last_report_outcomes}
    assert {"report-0.pdf", "nested/report-0.pdf"} <= identities
    assert len(identities) == 5
    rows = owner.report_planner.model.execution_rows
    assert {row.stable_occurrence_id for row in rows} == identities
    owner._on_parse_inputs_changed()
    assert owner.report_planner.model.execution_rows == ()
    assert not owner.import_succeeded and not owner.parse_button.isEnabled()


@pytest.mark.parametrize("change", ["uncheck_one", "clear_all", "check_extra"])
def test_queued_import_result_uses_submitted_selection(app, dialog, monkeypatch, change):
    from contextlib import closing
    import sqlite3
    from threading import Event
    from metroliza.ui.metadata_review_worker import MetadataReviewThread

    owner, _source, database = dialog
    entered, release = Event(), Event()
    run = MetadataReviewThread.run

    def held_metadata(worker):
        entered.set()
        assert release.wait(10)
        run(worker)

    monkeypatch.setattr(MetadataReviewThread, "run", held_metadata)
    owner.scan_button.click()
    try:
        wait_until(app, lambda: entered.is_set() and owner.preflight_thread is None)
        model = owner.report_planner.model
        if change == "check_extra":
            model.clear_selection()
            for row in (0, 1):
                model.setData(model.index(row, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        submitted = frozenset(model.selected_ids)
        owner.parse_button.click()
        operation = owner.import_operation
        assert owner._start_pending and operation.worker is None and owner.parse_thread is None
        assert not owner.report_planner.table.isEnabled()
        assert not owner.report_planner.clear.isEnabled() and not owner.report_planner.select_ready.isEnabled()
        assert not owner.directory_button.isEnabled() and not owner.database_button.isEnabled()
        if change == "clear_all":
            owner.report_planner.clear.click()
        else:
            row = 2 if change == "check_extra" else 1
            table = owner.report_planner.table
            table.setCurrentIndex(owner.report_planner.proxy.mapFromSource(model.index(row, 0)))
            table.setFocus()
            from PyQt6.QtTest import QTest
            QTest.keyClick(table, Qt.Key.Key_Space)
        assert frozenset(model.selected_ids) == submitted  # queued operation disables UI selection edits
        # Preserve the independent actual-plan regression even against a programmatic model mutation.
        if change == "clear_all":
            model.clear_selection()
        else:
            model.setData(model.index(row, 0),
                          Qt.CheckState.Checked if change == "check_extra" else Qt.CheckState.Unchecked,
                          Qt.ItemDataRole.CheckStateRole)
        assert frozenset(model.selected_ids) != submitted
    finally:
        release.set()
    wait_until(app, lambda: operation.worker is not None)
    worker = operation.worker
    wait_until(app, lambda: owner.parse_thread is None, parse_dialog=owner)
    assert {identity.occurrence_id for identity in worker.import_plan.selected_reports} == submitted
    with closing(sqlite3.connect(database)) as connection:
        assert {row[0] for row in connection.execute("SELECT file_name FROM source_file_locations")} == submitted
    rows = owner.report_planner.model.execution_rows
    assert len(rows) == 5
    assert {row.stable_occurrence_id for row in rows if row.status is ExecutionStatus.SAVED} == submitted
    assert owner.report_planner.model.execution_counts == {"saved": len(submitted), **(
        {"skipped": 5 - len(submitted)} if len(submitted) < 5 else {}
    )}
    assert owner.import_succeeded and not owner.parse_button.isEnabled()


@pytest.mark.parametrize("change", ["registry_invalidation", "foreign_finish", "unbound_operation"])
def test_running_import_results_remain_bound_to_actual_operation(app, dialog, monkeypatch, change):
    from threading import Event
    from metroliza.parsing import report_parser_factory

    owner, _source, _database = dialog
    owner.scan_button.click()
    wait_until(app, lambda: owner.preflight_thread is None and owner.metadata_thread is None)
    review = owner._preflight_result
    entered, release = Event(), Event()
    run = backend.ParseReportsThread.run

    def held_import(worker):
        entered.set()
        assert release.wait(10)
        run(worker)

    monkeypatch.setattr(backend.ParseReportsThread, "run", held_import)
    owner.parse_button.click()
    worker = owner.parse_thread
    assert worker is not None
    foreign = backend.ParseReportsThread(worker.import_plan)
    try:
        wait_until(app, entered.is_set)
        if change == "registry_invalidation":
            snapshot = report_parser_factory.get_registry_snapshot()
            with monkeypatch.context() as context:
                context.setattr(report_parser_factory, "get_registry_snapshot",
                                lambda **_kwargs: replace(snapshot, generation_id=snapshot.generation_id + 1))
                owner._sync_readiness_state()
            assert owner._preflight_result is None and owner.report_planner.model.rowCount() == 0
        else:
            if change == "foreign_finish":
                foreign.finished.connect(owner.on_parse_finished)
                foreign.finished.emit()
            else:
                owner.import_operation.worker = foreign
                try:
                    owner.on_parse_finished()
                finally:
                    owner.import_operation.worker = worker
            assert owner._preflight_result is review
            assert owner.report_planner.model.execution_rows == ()
            assert owner.report_planner.model.valid
    finally:
        release.set()
        foreign.deleteLater()
    wait_until(app, lambda: owner.parse_thread is None, parse_dialog=owner)
    assert owner.report_planner.model.execution_counts == {"saved": 5}
    assert owner.import_succeeded and owner._preflight_result is None
    assert not owner.report_planner.model.valid and not owner.parse_button.isEnabled()


@pytest.mark.parametrize("state,detail", [
    ("saved", "Saved to the selected database."),
    ("already_present", "Report already present in the selected database."),
    ("failed", "Report processing failed."),
])
def test_execution_details_describe_user_result(state, detail):
    review = _review()
    identity = review.files[0].stable_occurrence_id
    row = build_execution_rows(review, (identity,), (backend.ReportImportReceipt(identity, state),))[0]
    assert row.detail == detail
    assert "checkpoint" not in row.detail.lower()
