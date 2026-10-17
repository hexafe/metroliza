"""Metadata step UI (#1100): model, worker threading, OCR/cancel and import hand-off."""

from contextlib import closing
from pathlib import Path
import sqlite3
import threading
import time

import pytest
from PyQt6.QtCore import QThread, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.parsing.metadata_review import MetadataReviewReader
from metroliza.parsing.preflight import ImportPlan, ParsePreflightService
from metroliza.reports.report_metadata_review import ReviewRow, build_overrides
from metroliza.ui.metadata_review_dialog import MetadataReviewDialog
from metroliza.ui.metadata_review_model import MetadataReviewModel
from metroliza.ui.parsing_dialog import ParsingDialog

FIXTURE = Path(__file__).parent / "fixtures" / "pdf" / "cmm_smoke_fixture.pdf"
NAMES = ("AAAAA11111_Alpha_2024-01-01_1.pdf", "BBBBB22222_Beta_2024-01-02_2.pdf", "plain.pdf")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_until(app, predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert predicate(), "condition not reached"


def _ocr_item(text, x0, y0, x1, y1):
    return {"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "page_number": 1, "region_name": "page1_header_band_ocr"}


OCR_ITEMS = [
    _ocr_item("DRAWING No", 296.5, 44.8, 337.2, 50.6),
    _ocr_item("OCR-REF-9", 358.4, 45.1, 405.8, 50.6),
    _ocr_item("PART NAME", 150, 10, 178, 16),
    _ocr_item("Header Part", 182, 10, 220, 16),
]


@pytest.fixture
def review(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for index, name in enumerate(NAMES):
        (source / name).write_bytes(FIXTURE.read_bytes() + f"\n% ui-{index}\n".encode())
    database = tmp_path / "reports.sqlite3"
    result = ParsePreflightService().scan_source(
        source_path=source, database_path=database, metadata_parsing_mode="light"
    )
    return source, database, result


def _rows(result):
    return [
        ReviewRow(i.stable_occurrence_id, i.fingerprint, i.display_name, i.parser_id)
        for i in result.ready_files
    ]


def _open(app, result, **kwargs):
    dialog = MetadataReviewDialog(MetadataReviewReader(result), _rows(result), **kwargs)
    dialog.show()
    wait_until(app, lambda: not dialog.panel.is_busy() and all(r.state != "pending" for r in dialog.rows()))
    return dialog


def _close(app, dialog):
    dialog.reject()
    wait_until(app, lambda: not dialog.panel.is_busy())
    dialog.deleteLater()
    app.processEvents()


def _row(dialog, name):
    return next(row for row in dialog.rows() if row.display_name == name)


def test_model_edit_validation_and_missing_highlight(app, review):
    _source, _db, result = review
    rows = _rows(result)
    reader = MetadataReviewReader(result)
    for reading in _read_all(reader, rows):
        pass
    model = MetadataReviewModel(rows)
    position = next(i for i, row in enumerate(model.rows) if row.display_name == "plain.pdf")
    reference = model.index(position, model.column_for_field("reference"))
    rejected = []
    model.edit_rejected.connect(rejected.append)

    assert model.data(reference) == "(missing)"
    assert model.data(reference, Qt.ItemDataRole.BackgroundRole) is not None
    assert model.flags(reference) & Qt.ItemFlag.ItemIsEditable
    assert not model.flags(model.index(position, model.FILE_COLUMN)) & Qt.ItemFlag.ItemIsEditable

    assert model.setData(reference, "  NEW  REF ")
    assert model.data(reference) == "NEW REF"
    assert model.data(reference, Qt.ItemDataRole.BackgroundRole) is None
    assert model.data(reference, Qt.ItemDataRole.FontRole).bold()
    date = model.index(position, model.column_for_field("report_date"))
    assert not model.setData(date, "garbage") and rejected
    assert model.data(date) == "(missing)"


def _read_all(reader, rows):
    readings = []
    reader.read([r.occurrence_id for r in rows], on_reading=readings.append)
    by_id = {r.occurrence_id: r for r in rows}
    for reading in readings:
        by_id[reading.occurrence_id].apply_fast(reading.selection)
    return readings


def test_fast_prefill_runs_off_the_gui_thread_and_fills_the_table(app, review, monkeypatch):
    _source, database, result = review
    threads = []
    original = MetadataReviewReader._read_one

    def spy(self, *args, **kwargs):
        threads.append(QThread.currentThread())
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MetadataReviewReader, "_read_one", spy)
    dialog = _open(app, result)
    try:
        assert threads and all(t is not app.thread() for t in threads)
        assert _row(dialog, NAMES[0]).value("reference") == "AAAAA11111"
        assert dialog.panel.proxy.rowCount() == 3
        dialog.panel.attention_only.setChecked(True)
        assert dialog.panel.proxy.rowCount() == 3  # all three need attention (low confidence / missing)
        dialog.panel.search.setText("beta")
        assert dialog.panel.proxy.rowCount() == 1
        assert not database.exists()
    finally:
        _close(app, dialog)


def test_bulk_apply_and_reset_through_the_panel(app, review):
    _source, _db, result = review
    dialog = _open(app, result)
    try:
        panel = dialog.panel
        panel.table.selectAll()
        panel.bulk_field.setCurrentIndex(panel.bulk_field.findData("reference"))
        panel.bulk_value.setText("BULK-REF")
        panel.apply_to_selected()
        assert {row.value("reference") for row in dialog.rows()} == {"BULK-REF"}
        assert len(dialog.overrides()) == 3

        panel.bulk_field.setCurrentIndex(panel.bulk_field.findData("report_date"))
        panel.bulk_value.setText("not a date")
        panel.apply_to_selected()
        assert "valid date" in panel.message.text()

        panel.reset_selected_edits()
        assert dialog.overrides() == ()
        assert _row(dialog, NAMES[0]).value("reference") == "AAAAA11111"
    finally:
        _close(app, dialog)


def test_ocr_runs_off_the_gui_thread_and_keeps_manual_edits(app, review, monkeypatch):
    _source, _db, result = review
    ocr_threads = []

    def fake(cls, page, bbox, pdf_backend):
        ocr_threads.append(QThread.currentThread())
        return list(OCR_ITEMS), None

    monkeypatch.setattr(CMMReportParser, "_ocr_header_items_from_pixmap", classmethod(fake))
    dialog = _open(app, result)
    try:
        panel = dialog.panel
        manual = _row(dialog, NAMES[0])
        manual.set_user_value("reference", "MANUAL")
        panel.table.selectAll()
        assert panel.start_ocr(selected_only=True)
        assert panel.is_busy() and not dialog.use_button.isEnabled()
        wait_until(app, lambda: not panel.is_busy())

        assert len(ocr_threads) == 3 and all(t is not app.thread() for t in ocr_threads)
        assert manual.value("reference") == "MANUAL"
        assert manual.conflict_fields == ("reference",)
        assert panel.accept_ocr.isVisibleTo(panel)
        other = _row(dialog, NAMES[1])
        assert other.value("reference") == "OCR-REF-9" and other.value("part_name") == "Header Part"

        # Replacing a manual value needs explicit confirmation.
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
        panel.confirm_accept_ocr()
        assert manual.value("reference") == "MANUAL"
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        panel.confirm_accept_ocr()
        assert manual.value("reference") == "OCR-REF-9"
        # The table can be corrected again after OCR.
        assert other.set_user_value("part_name", "Fixed") == (True, None)
    finally:
        _close(app, dialog)


def test_ocr_cancel_keeps_what_was_already_filled(app, review, monkeypatch):
    _source, database, result = review
    holder = {}

    def fake(cls, page, bbox, pdf_backend):
        holder["dialog"].panel._thread.stop_reading()  # cancel requested from inside the first report
        return list(OCR_ITEMS), None

    monkeypatch.setattr(CMMReportParser, "_ocr_header_items_from_pixmap", classmethod(fake))
    dialog = _open(app, result)
    holder["dialog"] = dialog
    try:
        dialog.panel.table.selectAll()
        dialog.panel.start_ocr(selected_only=True)
        wait_until(app, lambda: not dialog.panel.is_busy())
        done = [row for row in dialog.rows() if row.ocr_state == "done"]
        assert len(done) == 1 and done[0].value("part_name") == "Header Part"
        assert "stopped" in dialog.panel.message.text()
        assert not database.exists()
    finally:
        _close(app, dialog)


def test_closing_while_reading_defers_until_the_worker_stops(app, review, monkeypatch):
    _source, _db, result = review
    gate = threading.Event()
    original = MetadataReviewReader._read_one

    def slow(self, *args, **kwargs):
        gate.wait(5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MetadataReviewReader, "_read_one", slow)
    dialog = MetadataReviewDialog(MetadataReviewReader(result), _rows(result))
    dialog.show()
    assert dialog.panel.is_busy()
    dialog.reject()
    assert dialog.isVisible()  # close deferred while the worker is running
    gate.set()
    wait_until(app, lambda: not dialog.isVisible())
    dialog.deleteLater()


# --- ParsingDialog hand-off ---------------------------------------------------


def _parsing_dialog(app, source, database, result):
    dialog = ParsingDialog(parent=None, directory=str(source), db_file=str(database))
    dialog.on_preflight_completed(result)
    assert dialog.parse_button.isEnabled() and dialog.metadata_button.isEnabled()
    return dialog


def _fake_exec(monkeypatch, app, action, accepted):
    def run(self):
        wait_until(app, lambda: not self.panel.is_busy())
        action(self)
        return QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected

    monkeypatch.setattr(MetadataReviewDialog, "exec", run)


def test_cancelled_metadata_step_discards_edits_and_never_writes(app, review, monkeypatch):
    source, database, result = review
    dialog = _parsing_dialog(app, source, database, result)
    _fake_exec(monkeypatch, app, lambda d: _row(d, NAMES[0]).set_user_value("reference", "X"), accepted=False)
    try:
        dialog._open_metadata_review()
        assert dialog._metadata_rows == {}
        assert not database.exists()
    finally:
        dialog.close()


def test_accepted_metadata_step_flows_into_the_import_plan(app, review, monkeypatch):
    source, database, result = review
    dialog = _parsing_dialog(app, source, database, result)
    _fake_exec(monkeypatch, app, lambda d: _row(d, "plain.pdf").set_user_value("reference", "FILLED"), accepted=True)
    started = []

    class _FakeThread:
        def __init__(self, request):
            started.append(request)
            for name in ("update_label", "update_progress", "error_occurred", "finished"):
                setattr(self, name, type("S", (), {"connect": lambda *_: None})())

        def start(self):
            pass

    monkeypatch.setattr("metroliza.ui.parsing_dialog.ParseReportsThread", _FakeThread)
    monkeypatch.setattr(
        "metroliza.ui.parsing_dialog.create_worker_progress_dialog",
        lambda *a, **k: (type("D", (), {"show": lambda s: None, "accept": lambda s: None})(),
                         type("L", (), {"setText": lambda s, t: None})(),
                         type("B", (), {"setValue": lambda s, v: None})(), None),
    )
    try:
        dialog._open_metadata_review()
        assert "1 edited" in dialog.readiness_label.text() and "Metadata:" in dialog.readiness_label.text()
        dialog._import_reviewed_reports()
        plan = started[0]
        assert isinstance(plan, ImportPlan)
        assert [(o.occurrence_id, [(f.field_name, f.value, f.origin) for f in o.fields])
                for o in plan.metadata_overrides] == [("plain.pdf", [("reference", "FILLED", "user")])]
        assert not database.exists()  # the stubbed worker never ran; review itself wrote nothing
    finally:
        dialog.close()


def test_changing_the_review_discards_metadata_edits(app, review, monkeypatch):
    source, database, result = review
    dialog = _parsing_dialog(app, source, database, result)
    _fake_exec(monkeypatch, app, lambda d: _row(d, "plain.pdf").set_user_value("reference", "FILLED"), accepted=True)
    try:
        dialog._open_metadata_review()
        assert dialog._metadata_rows
        dialog._invalidate_preflight()
        assert dialog._metadata_rows == {}
    finally:
        dialog.close()


def test_metadata_step_end_to_end_writes_confirmed_values_only_on_import(app, review, monkeypatch):
    from metroliza.parsing.parse_reports_thread import ParseReportsThread

    source, database, result = review
    dialog = _parsing_dialog(app, source, database, result)
    _fake_exec(monkeypatch, app, lambda d: _row(d, "plain.pdf").set_user_value("reference", "FILLED"), accepted=True)
    try:
        dialog._open_metadata_review()
        assert not database.exists()
        plan = ImportPlan.from_preflight(
            _request(source, database),
            result,
            selected_occurrence_ids=dialog.report_planner.model.selected_ids,
            metadata_overrides=build_overrides(dialog._selected_metadata_rows()),
        )
        ParseReportsThread(plan).run()
        with closing(sqlite3.connect(database)) as connection:
            references = sorted(r[0] or "" for r in connection.execute("SELECT reference FROM report_metadata"))
        assert references == ["AAAAA11111", "BBBBB22222", "FILLED"]
    finally:
        dialog.close()


def _request(source, database):
    from metroliza.shared.parse_contracts import ParseRequest

    return ParseRequest(source_directory=str(source), db_file=str(database), metadata_parsing_mode="light")


def test_column_widths_and_filter_are_remembered_via_ui_preferences(app, review, tmp_path):
    from PyQt6.QtCore import QSettings

    from metroliza.ui.ui_preferences import UiPreferences

    _source, _db, result = review
    ini = str(tmp_path / "prefs.ini")
    first = _open(app, result, ui_preferences=UiPreferences(QSettings(ini, QSettings.Format.IniFormat)))
    first.panel.table.setColumnWidth(1, 321)
    first.panel.attention_only.setChecked(True)
    first.accept()
    first.deleteLater()

    second = _open(app, result, ui_preferences=UiPreferences(QSettings(ini, QSettings.Format.IniFormat)))
    try:
        assert second.panel.table.columnWidth(1) == 321
        assert second.panel.attention_only.isChecked()
    finally:
        _close(app, second)
