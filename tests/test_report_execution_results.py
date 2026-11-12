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
