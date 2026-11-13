"""#1159: partial and interrupted enrichment keeps honest terminal accounting."""

from types import SimpleNamespace

import pytest


def _batch(monkeypatch, outcomes, *, cancel_after=None):
    from metroliza.parsing import metadata_enrichment_thread as worker

    visited = []
    warnings = []

    def enrich(_database, item, **_kwargs):
        visited.append(item.report_id)
        outcome = outcomes[item.report_id]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(worker, "enrich_existing_report_metadata", enrich)
    items = [worker.MetadataEnrichmentWorkItem(i, f"synthetic-{i}.pdf", "digest") for i in range(len(outcomes))]
    result = worker.run_metadata_enrichment_batch(
        "unused.db", items,
        should_cancel=lambda: cancel_after is not None and len(visited) >= cancel_after,
        on_warning=lambda item, error: warnings.append(item.report_id),
    )
    return result, visited, warnings


def test_cancel_enrichment_accounts_not_processed_and_keeps_updated(monkeypatch):
    result, visited, _ = _batch(monkeypatch, [True, True, True], cancel_after=1)
    assert result.cancellation_requested is True
    assert result.cancelled_files == 2
    assert result.enriched_files == 1
    assert result.not_processed_files == 2
    assert result.termination_reason == "cancelled"
    assert visited == [0]


def test_cancel_during_last_report_still_has_cancelled_termination(monkeypatch):
    result, _, _ = _batch(monkeypatch, [True], cancel_after=1)
    assert result.cancellation_requested
    assert result.termination_reason == "cancelled"
    assert result.not_processed_files == 0 and result.enriched_files == 1


@pytest.mark.parametrize("outcomes,counts", [([True, True], (2, 0, 0)), ([True, ValueError("NOK"), False], (1, 1, 1)), ([], (0, 0, 0))])
def test_enrichment_completed_partial_and_no_work_are_distinct(monkeypatch, outcomes, counts):
    result, _, warnings = _batch(monkeypatch, outcomes)
    assert (result.enriched_files, result.failed_files, result.skipped_files) == counts
    assert result.processed_files == len(outcomes)
    assert result.not_processed_files == 0
    assert result.termination_reason == "completed"
    assert warnings == ([1] if counts[1] else [])


@pytest.mark.parametrize("kind", ["success", "warnings", "cancel", "empty"])
def test_enrichment_terminal_ui_is_not_green_100_for_partial_or_cancel(monkeypatch, kind):
    from metroliza.parsing.parse_reports_thread import MetadataEnrichmentBatchResult
    from metroliza.ui import main_window

    text, progress, variants = [], [], []
    result = {
        "success": MetadataEnrichmentBatchResult(3, 3),
        "warnings": MetadataEnrichmentBatchResult(1, 3, failed_files=1, skipped_files=1),
        "cancel": MetadataEnrichmentBatchResult(1, 3, cancelled_files=2, cancellation_requested=True),
        "empty": MetadataEnrichmentBatchResult(0, 0),
    }[kind]
    host = SimpleNamespace(
        metadata_enrichment_thread=SimpleNamespace(result=result), metadata_enrichment_error_message=None,
        enrich_metadata_action=SimpleNamespace(setEnabled=lambda _: None),
        cancel_metadata_enrichment_button=SimpleNamespace(setEnabled=lambda _: None, setVisible=lambda _: None),
        metadata_enrichment_progress_bar=SimpleNamespace(setValue=progress.append),
        metadata_enrichment_status_label=SimpleNamespace(setText=text.append, setToolTip=lambda _: None),
        _pdf_execution_available=lambda: True, log_and_exit=lambda error: pytest.fail(str(error)),
    )
    host._show_metadata_enrichment_result = lambda value: main_window.MainWindow._show_metadata_enrichment_result(host, value)
    monkeypatch.setattr(main_window, "set_status_variant", lambda _label, variant: variants.append(variant))
    main_window.MainWindow.on_metadata_enrichment_finished(host)
    if kind == "success":
        assert variants[-1] == "success" and progress[-1] == 100
    else:
        assert variants[-1] != "success" and progress[-1] < 100
        assert {"cancel": "Cancelled", "warnings": "Completed with warnings", "empty": "No reports"}[kind] in text[-1]


def test_enrichment_warning_is_visible(monkeypatch):
    from metroliza.ui import main_window

    texts, tooltips = [], []
    host = SimpleNamespace(metadata_enrichment_status_label=SimpleNamespace(setText=texts.append, setToolTip=tooltips.append))
    monkeypatch.setattr(main_window, "set_status_variant", lambda *_: None)
    main_window.MainWindow.on_metadata_enrichment_warning(host, "Report 2 failed: NOK")
    assert "NOK" in texts[-1] and "NOK" in tooltips[-1]


def test_enrichment_discovery_failure_has_failed_termination(monkeypatch, tmp_path):
    from metroliza.parsing import metadata_enrichment_thread as worker

    monkeypatch.setattr(worker, "ensure_cmm_report_schema", lambda *a, **k: None)

    def fail(*_args, **_kwargs):
        raise RuntimeError("NOK discovery")

    monkeypatch.setattr(worker, "discover_metadata_enrichment_work", fail)
    thread = worker.MetadataEnrichmentThread(str(tmp_path / "reports.db"))
    errors, finished = [], []
    thread.error_occurred.connect(errors.append)
    thread.enrichment_finished.connect(lambda: finished.append(True))
    thread.run()
    assert thread.result.termination_reason == "failed"
    assert errors == ["NOK discovery"] and finished == [True]


def test_enrichment_launch_connects_warning_and_animated_progress(monkeypatch, qapplication_session, tmp_path):
    from PyQt6.QtCore import QSettings
    from metroliza.parsing import metadata_enrichment_thread as worker
    from metroliza.parsing.parse_reports_thread import MetadataEnrichmentBatchResult
    from metroliza.ui.main_window import MainWindow
    from metroliza.ui.ui_preferences import UiPreferences

    class FakeThread(worker.MetadataEnrichmentThread):
        def start(self):
            pass

        def isRunning(self):  # noqa: N802
            return False

    monkeypatch.setattr(worker, "MetadataEnrichmentThread", FakeThread)
    preferences = UiPreferences(QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat))
    window = MainWindow(version_label="test", days_until_expiration=None, ui_preferences=preferences)
    monkeypatch.setattr(window, "_report_database_action_allowed", lambda: True)
    window.db_file = str(tmp_path / "synthetic.sqlite3")
    try:
        window.launch_metadata_enrichment()
        thread = window.metadata_enrichment_thread
        assert window._metadata_enrichment_progress_dialog._loading_gif is not None
        thread.warning.emit("Report failed: NOK")
        assert "NOK" in window.metadata_enrichment_status_label.text()
        thread.result = MetadataEnrichmentBatchResult(1, 2, failed_files=1)
        window.on_metadata_enrichment_finished()
        assert "Completed with warnings" in window.metadata_enrichment_status_label.text()
        assert "NOK" in window.metadata_enrichment_status_label.toolTip()
        window._clear_metadata_enrichment_thread()
        assert window._metadata_enrichment_progress_dialog is None
    finally:
        window.metadata_enrichment_thread = None
        window.close()


def test_cancelled_batch_keeps_committed_metadata_and_all_measurements(tmp_path):
    from contextlib import closing
    import sqlite3

    from metroliza.parsing.metadata_enrichment_thread import discover_metadata_enrichment_work, run_metadata_enrichment_batch
    from metroliza.reports.report_repository import ReportRepository
    from tests.test_metadata_enrichment_thread import _persist_report, _selection_result

    database = str(tmp_path / "reports.sqlite3")
    repository = ReportRepository(database)
    ids = [
        _persist_report(tmp_path, repository, name=f"report-{number}.pdf", metadata_json={})[0]
        for number in range(2)
    ]
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE report_measurements SET meas = ?, status_code = ?", (12.5, "nok"))
        before = connection.execute("SELECT * FROM report_measurements ORDER BY report_id, row_order").fetchall()

    class Parser:
        metadata_parsing_mode = "light"
        _metadata_selection_result = _selection_result()

        def open_report(self):
            pass

        def extract_metadata(self):
            return self._metadata_selection_result

    stop = []
    result = run_metadata_enrichment_batch(
        database, discover_metadata_enrichment_work(database),
        parser_factory=lambda *_a, **_k: Parser(), should_cancel=lambda: bool(stop),
        on_item_enriched=lambda *_a: stop.append(True),
    )
    with closing(sqlite3.connect(database)) as connection:
        metadata = connection.execute("SELECT report_id, reference, revision FROM report_metadata ORDER BY report_id").fetchall()
        after = connection.execute("SELECT * FROM report_measurements ORDER BY report_id, row_order").fetchall()
    assert metadata == [(ids[0], "LIGHT-REF", "B"), (ids[1], "LIGHT-REF", None)]
    assert after == before
    assert result.cancellation_requested and result.enriched_files == 1
    assert result.cancelled_files == 1
