"""Inline metadata review in the report planner (#1100).

The review table itself carries the metadata: a background fast read fills it
after every review, cells are corrected in place, OCR is optional, and only the
checked reports' confirmed values travel in the import plan.  The lifecycle is
exercised for both owners of the planner, the standalone ``ParsingDialog`` and
the embedded ``ReportsWorkspace``.
"""

from contextlib import closing
from dataclasses import replace
import gc
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import threading
import time

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QLineEdit

from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.parsing.metadata_review import MODE_FAST, MODE_OCR, MetadataReviewReader
from metroliza.parsing.preflight import ImportPlan, ParsePreflightService, ParsePreflightStatus
from metroliza.reports.report_metadata_review import ReviewRow, build_overrides
from metroliza.ui import parsing_dialog as parsing_dialog_module
from metroliza.ui import report_planner_metadata as meta
from metroliza.ui import ui_theme_tokens as tokens
from metroliza.ui.parsing_dialog import ParsingDialog, ReportsWorkspace, _ReportOperations
from metroliza.ui.ui_foundation import apply_metroliza_theme
from tests.metadata_review_fakes import (
    FILE_NAME,
    install_fake_reader,
    make_selection,
    review_result,
)

FIXTURE = Path(__file__).parent / "fixtures" / "pdf" / "cmm_smoke_fixture.pdf"
HOSTS = ("dialog", "workspace")
FULL = {
    "reference": "REF-A", "part_name": "Part A", "sample_number": "1", "report_date": "2024-01-01",
}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_until(app, predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert predicate(), "condition not reached"


# --- fixtures -----------------------------------------------------------------


@pytest.fixture
def readers(monkeypatch):
    """Fake reader seam; ``queue`` holds per-review options, then ``options``."""

    return install_fake_reader(monkeypatch)


@pytest.fixture
def started(monkeypatch):
    """Capture the import request instead of starting a parse worker."""

    requests = []

    class _FakeThread:
        def __init__(self, request):
            requests.append(request)
            for name in ("update_label", "update_progress", "error_occurred", "finished"):
                setattr(self, name, type("S", (), {"connect": lambda *_: None})())

        def start(self):
            pass

        def isRunning(self):  # noqa: N802
            return False

    monkeypatch.setattr(parsing_dialog_module, "ParseReportsThread", _FakeThread)
    monkeypatch.setattr(
        parsing_dialog_module, "create_worker_progress_dialog",
        lambda *a, **k: (type("D", (), {"show": lambda s: None, "accept": lambda s: None,
                                        "reject": lambda s: None,
                                        "setWindowModality": lambda s, m: None})(),
                         type("L", (), {"setText": lambda s, t: None})(),
                         type("B", (), {"setValue": lambda s, v: None})(), None),
    )
    return requests


@pytest.fixture
def make_host(app, tmp_path, readers):
    created = []

    def build(kind):
        (tmp_path / "source").mkdir(exist_ok=True)
        directory, database = str(tmp_path / "source"), str(tmp_path / "reports.sqlite3")
        if kind == "dialog":
            host = ParsingDialog(parent=None, directory=directory, db_file=database)
        else:
            host = ReportsWorkspace()
            host.apply_workspace_snapshot(SimpleNamespace(source_directory=directory, database_file=database))
        host.show()
        created.append(host)
        return host

    yield build
    for host in created:
        readers.release_all()
        host._request_active_worker_cancellation()
        wait_until(app, lambda: not host._workers_running())
        host.parse_thread = None
        host.deleteLater()
    flush_widgets(app)


def flush_widgets(app):
    """Really delete finished widgets and drop their Python wrappers before the next test.

    Lingering wrappers of deleted Qt objects make later tests (that look up children
    of new windows) crash intermittently on this PyQt build.
    """

    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()


def open_review(make_host, readers, kind, names=("a.pdf", "b.pdf", "c.pdf"), *, other=(), fast=None, **options):
    host = make_host(kind)
    readers.options = dict(options, fast=fast if fast is not None else {name: dict(FULL) for name in names})
    review = review_result(names, other=other, source=host.directory, database=host.db_file)
    host.on_preflight_completed(review)
    return host, review


def settle(app, host):
    wait_until(app, lambda: host.metadata_thread is None and not host._metadata_workers_running())


def index(planner, name, column):
    for row in range(planner.proxy.rowCount()):
        candidate = planner.proxy.index(row, planner.model.LOCATION_COLUMN)
        if candidate.data() == name:
            return planner.proxy.index(row, column)
    raise AssertionError(f"{name} is not shown")


def cell(planner, name, field):
    return index(planner, name, planner.model.column_for_field(field))


def open_editor(table):
    """The visible cell editor (a closed one lingers until its deferred delete)."""

    editors = [e for e in table.viewport().findChildren(QLineEdit) if e.isVisible()]
    return editors[-1] if editors else None


def check(planner, name, checked):
    state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
    assert planner.proxy.setData(index(planner, name, 0), state, Qt.ItemDataRole.CheckStateRole)


# --- automatic fast read -------------------------------------------------------


@pytest.mark.parametrize("kind", HOSTS)
def test_review_starts_the_fast_read_automatically_and_fills_the_cells(app, make_host, readers, kind):
    gate = threading.Event()
    host, _review = open_review(make_host, readers, kind, names=("c.pdf", "a.pdf", "b.pdf"), gate=gate)
    planner = host.report_planner

    # Pending placeholder before the read; inline progress with a Stop button.
    assert host.metadata_thread is not None and host.metadata_thread.isRunning()
    pending = cell(planner, "a.pdf", "reference")
    assert pending.data() == meta.PENDING_TEXT
    assert pending.data(planner.model.STYLE_ROLE) == meta.KIND_PENDING
    assert planner.metadata_status_text.startswith("Reading metadata ")
    assert planner.metadata_status_text in planner.counts.text()  # progress leads the counts line
    assert planner.stop_action.isEnabled()  # Stop stays reachable in the Metadata menu
    assert not planner.ocr_button.isEnabled()  # one worker at a time

    gate.set()
    settle(app, host)
    mode, ids = readers.instances[0].calls[0]
    assert mode == MODE_FAST
    assert ids == ("a.pdf", "b.pdf", "c.pdf")  # the order the table shows them, not the review order
    assert cell(planner, "a.pdf", "reference").data() == "REF-A"
    assert cell(planner, "c.pdf", "report_date").data() == "2024-01-01"
    assert not planner.stop_action.isEnabled() and planner.metadata_status_text == ""
    assert planner.ocr_button.isEnabled()
    assert planner.model.metadata_counts["pending"] == 0


@pytest.mark.parametrize("kind", HOSTS)
def test_unreadable_rows_are_read_only_with_a_note(app, make_host, readers, kind):
    host, _ = open_review(
        make_host, readers, kind, names=("ok.pdf", "same.pdf", "broken.pdf", "foreign.pdf"),
        statuses={"same.pdf": "changed", "broken.pdf": "failed", "foreign.pdf": "unsupported"},
        other=(("twin.pdf", ParsePreflightStatus.DUPLICATE),),
    )
    settle(app, host)
    planner, model = host.report_planner, host.report_planner.model
    for name, text in (("same.pdf", "Changed since review"), ("foreign.pdf", "cannot be edited")):
        reference = cell(planner, name, "reference")
        assert not model.flags(planner.proxy.mapToSource(reference)) & Qt.ItemFlag.ItemIsEditable
        assert reference.data() == meta.READONLY_TEXT
        assert text in reference.data(Qt.ItemDataRole.ToolTipRole)
        assert not planner.proxy.setData(reference, "X")
    # A failed read keeps the cell editable (the user can type the values).
    assert model.flags(planner.proxy.mapToSource(cell(planner, "broken.pdf", "reference"))) & Qt.ItemFlag.ItemIsEditable
    # Reports that were not READY have no metadata row at all.
    twin = cell(planner, "twin.pdf", "reference")
    assert twin.data() == "" and "not part of the metadata review" in twin.data(Qt.ItemDataRole.ToolTipRole)
    assert model.metadata_row("twin.pdf") is None


# --- inline editing ------------------------------------------------------------


@pytest.mark.parametrize("kind", HOSTS)
def test_inline_edit_sets_a_manual_value_and_rejects_a_bad_date(app, make_host, readers, kind):
    host, _ = open_review(make_host, readers, kind)
    settle(app, host)
    planner = host.report_planner

    reference = cell(planner, "a.pdf", "reference")
    assert planner.proxy.setData(reference, "  NEW  REF ")
    assert reference.data() == "NEW REF"
    assert reference.data(planner.model.STYLE_ROLE) == meta.KIND_MANUAL
    assert reference.data(Qt.ItemDataRole.FontRole).bold()
    assert "Source: entered by you" in reference.data(Qt.ItemDataRole.ToolTipRole)
    assert "Detected value: REF-A" in reference.data(Qt.ItemDataRole.ToolTipRole)

    date = cell(planner, "a.pdf", "report_date")
    assert not planner.proxy.setData(date, "not a date")
    assert date.data() == "2024-01-01"  # the old value stays
    assert "valid date" in planner.metadata_status_text
    assert "valid date" in planner.counts.text()
    assert planner.proxy.setData(date, "2024-05-06")
    assert date.data() == "2024-05-06"


@pytest.mark.parametrize("kind", HOSTS)
def test_cells_edit_from_the_keyboard_and_space_still_toggles_the_checkbox(app, make_host, readers, kind):
    host, _ = open_review(make_host, readers, kind)
    settle(app, host)
    planner, table = host.report_planner, host.report_planner.table
    table.setFocus()
    table.setCurrentIndex(cell(planner, "b.pdf", "part_name"))

    QTest.keyClick(table, Qt.Key.Key_Return)  # Enter starts editing
    editor = open_editor(table)
    assert editor is not None and editor.text() == "Part A"
    editor.setText("Typed part")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    app.processEvents()
    assert planner.model.metadata_row("b.pdf").value("part_name") == "Typed part"

    QTest.keyClick(table, Qt.Key.Key_F2)  # F2 as well
    editor = open_editor(table)
    assert editor is not None and editor.text() == "Typed part"
    QTest.keyClick(editor, Qt.Key.Key_Escape)  # cancelling keeps the value
    app.processEvents()
    assert open_editor(table) is None
    assert planner.model.metadata_row("b.pdf").value("part_name") == "Typed part"

    assert "b.pdf" in planner.model.selected_ids
    QTest.keyClick(table, Qt.Key.Key_Space)
    assert "b.pdf" not in planner.model.selected_ids  # Space on a metadata cell toggles the row


@pytest.mark.parametrize("kind", HOSTS)
def test_copy_to_checked_and_reset_to_detected(app, make_host, readers, kind):
    host, _ = open_review(
        make_host, readers, kind, names=("a.pdf", "b.pdf", "c.pdf", "foreign.pdf"),
        statuses={"foreign.pdf": "unsupported"},
    )
    settle(app, host)
    planner, model = host.report_planner, host.report_planner.model
    check(planner, "c.pdf", False)
    planner.proxy.setData(cell(planner, "a.pdf", "reference"), "COPIED")
    planner.table.setCurrentIndex(cell(planner, "a.pdf", "reference"))
    assert planner.copy_to_checked.isEnabled()

    planner.copy_to_checked.trigger()
    assert model.metadata_row("b.pdf").value("reference") == "COPIED"
    assert model.metadata_row("b.pdf").cells["reference"].user_set
    assert model.metadata_row("c.pdf").value("reference") == "REF-A"  # unchecked: untouched
    assert model.metadata_row("foreign.pdf").value("reference") is None  # read-only: untouched
    assert "copied to 1 checked report" in planner.metadata_status_text

    assert planner.reset_to_detected.isEnabled()
    planner.reset_to_detected.trigger()  # current row: a.pdf
    assert model.metadata_row("a.pdf").value("reference") == "REF-A"
    assert model.metadata_row("b.pdf").value("reference") == "COPIED"  # only the current row

    planner.proxy.setData(cell(planner, "a.pdf", "reference"), "")
    planner.table.setCurrentIndex(cell(planner, "a.pdf", "reference"))
    assert not planner.copy_to_checked.isEnabled()  # an empty cell has nothing to copy


@pytest.mark.parametrize("kind", HOSTS)
def test_metadata_actions_live_in_one_keyboard_reachable_menu_on_the_action_row(app, make_host, readers, kind):
    gate = threading.Event()
    host, _ = open_review(make_host, readers, kind, gate=gate)
    planner = host.report_planner
    button = planner.metadata_button
    assert button.menu() is planner.metadata_menu and button.focusPolicy() != Qt.FocusPolicy.NoFocus
    assert button.accessibleName() == "Metadata actions"
    assert [a.text() for a in planner.metadata_menu.actions()] == [
        "Copy to checked", "Reset to detected", "Stop metadata read",
    ]
    assert all(a.toolTip() for a in planner.metadata_menu.actions())
    # No third toolbar row: OCR and the menu share the row of the selection buttons.
    row_tops = {w.mapTo(planner, w.rect().topLeft()).y() for w in (planner.select_ready, planner.ocr_button, button)}
    assert max(row_tops) - min(row_tops) <= 2
    assert planner.stop_action.isEnabled()  # reachable while the fast read runs
    planner.stop_action.trigger()
    gate.set()
    settle(app, host)
    assert not planner.stop_action.isEnabled()
    assert "stopped" in planner.metadata_status_text


@pytest.mark.parametrize("kind", HOSTS)
def test_optional_columns_are_hidden_until_enabled_from_the_header_menu(app, make_host, readers, kind):
    host, _ = open_review(make_host, readers, kind)
    settle(app, host)
    planner, model = host.report_planner, host.report_planner.model
    time_column = model.column_for_field("report_time")
    assert planner.table.isColumnHidden(time_column)
    menu = planner.build_columns_menu()
    assert menu.title() == "Columns"
    actions = {action.text(): action for action in menu.actions()}
    assert actions["Date"].isChecked() and not actions["Time"].isChecked()
    actions["Time"].toggle()
    assert not planner.table.isColumnHidden(time_column)
    planner.resize(600, planner.height())  # compact: metadata stays, parser details go
    app.processEvents()
    assert not planner.table.isColumnHidden(time_column)
    assert planner.table.isColumnHidden(model.PARSER_COLUMN)


# --- OCR -----------------------------------------------------------------------


@pytest.mark.parametrize("kind", HOSTS)
def test_ocr_fills_unedited_fields_keeps_manual_values_and_exposes_the_conflict(app, make_host, readers, kind):
    names = ("a.pdf", "b.pdf", "c.pdf")
    fast = {name: {"reference": "FAST", "report_date": "2024-01-01"} for name in names}
    ocr = {name: {"reference": "OCR-REF", "report_date": "2024-01-01", "operator_name": "Op"} for name in names}
    host, _ = open_review(make_host, readers, kind, names=names, fast=fast, ocr=ocr)
    settle(app, host)
    planner, model = host.report_planner, host.report_planner.model
    planner.proxy.setData(cell(planner, "a.pdf", "reference"), "MANUAL")
    check(planner, "c.pdf", False)

    host.report_planner.ocr_button.click()
    assert host.metadata_thread is not None and host.metadata_thread.mode == MODE_OCR
    settle(app, host)

    assert readers.instances[-1].calls == [(MODE_OCR, ("a.pdf", "b.pdf"))]  # checked reports only
    manual = model.metadata_row("a.pdf")
    assert manual.value("reference") == "MANUAL" and manual.conflict_fields == ("reference",)
    conflict = cell(planner, "a.pdf", "reference")
    assert conflict.data(model.STYLE_ROLE) == meta.KIND_CONFLICT
    assert "OCR suggests OCR-REF; your value is kept." in conflict.data(Qt.ItemDataRole.ToolTipRole)
    assert conflict.data(Qt.ItemDataRole.BackgroundRole) is not None
    assert "OCR suggests OCR-REF; your value is kept" in model.details_text(planner.proxy.mapToSource(conflict).row())
    other = model.metadata_row("b.pdf")
    assert other.value("reference") == "OCR-REF" and other.value("operator_name") == "Op"
    assert cell(planner, "b.pdf", "reference").data(model.STYLE_ROLE) == meta.KIND_OCR
    assert model.metadata_row("c.pdf").value("reference") == "FAST"  # not checked: not read
    # The table can be corrected again after OCR.
    assert planner.proxy.setData(cell(planner, "b.pdf", "part_name"), "Fixed")
    assert "stopped" not in planner.metadata_status_text


@pytest.mark.parametrize("kind", HOSTS)
def test_ocr_is_disabled_with_the_reason_when_unavailable(app, make_host, readers, monkeypatch, kind):
    monkeypatch.setattr(
        _ReportOperations, "_ocr_unavailable_reason", staticmethod(lambda: "OCR is unavailable: the OCR models are not installed.")
    )
    host, _ = open_review(make_host, readers, kind)
    settle(app, host)
    planner = host.report_planner
    assert not planner.ocr_button.isEnabled()
    assert planner.ocr_button.toolTip() == "OCR is unavailable: the OCR models are not installed."
    assert not host.start_metadata_ocr()
    assert len(readers.instances) == 1  # only the fast read ever ran


def test_ocr_unavailable_reason_reflects_backend_and_models(monkeypatch, tmp_path):
    from metroliza.parsing.metadata_review import ocr_unavailable_reason

    monkeypatch.setenv("METROLIZA_HEADER_OCR_BACKEND", "disabled")
    assert "disabled" in ocr_unavailable_reason()
    monkeypatch.setenv("METROLIZA_HEADER_OCR_BACKEND", "other")
    assert "not supported" in ocr_unavailable_reason()
    monkeypatch.setenv("METROLIZA_HEADER_OCR_BACKEND", "rapidocr_latin")
    monkeypatch.setenv("METROLIZA_HEADER_OCR_MODEL_DIR", str(tmp_path))
    assert "models are not installed" in ocr_unavailable_reason()


# --- import ------------------------------------------------------------------


@pytest.mark.parametrize("kind", HOSTS)
def test_import_passes_overrides_for_checked_reports_only(app, make_host, readers, started, kind):
    host, _ = open_review(make_host, readers, kind)
    settle(app, host)
    planner = host.report_planner
    planner.proxy.setData(cell(planner, "a.pdf", "reference"), "EDITED-A")
    planner.proxy.setData(cell(planner, "c.pdf", "reference"), "EDITED-C")
    check(planner, "c.pdf", False)  # edit on an unchecked row

    host._import_reviewed_reports()
    plan = started[0]
    assert isinstance(plan, ImportPlan)
    assert [(o.occurrence_id, [(f.field_name, f.value, f.origin) for f in o.fields])
            for o in plan.metadata_overrides] == [("a.pdf", [("reference", "EDITED-A", "user")])]


@pytest.mark.parametrize("kind", HOSTS)
def test_a_finished_import_discards_the_rows(app, make_host, readers, started, monkeypatch, kind):
    from PyQt6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    host, _ = open_review(make_host, readers, kind)
    settle(app, host)
    cell_index = cell(host.report_planner, "a.pdf", "reference")
    host.report_planner.proxy.setData(cell_index, "EDIT")
    host._import_reviewed_reports()
    assert started and host.report_planner.model.metadata_rows

    host.on_parse_finished()  # the destination changed: the review and its rows are stale

    assert host.report_planner.model.metadata_rows == {} and host.metadata_thread is None


@pytest.mark.parametrize("kind", HOSTS)
def test_import_stops_a_running_fast_read_and_proceeds(app, make_host, readers, started, kind):
    host, _ = open_review(make_host, readers, kind, gate=threading.Event())
    planner = host.report_planner
    reader = readers.instances[0]
    wait_until(app, reader.started.is_set)
    planner.proxy.setData(cell(planner, "a.pdf", "reference"), "WHILE-READING")
    assert host.metadata_thread.isRunning() and host.parse_button.isEnabled()

    host._import_reviewed_reports()  # never blocks: the worker is asked to stop

    wait_until(app, lambda: bool(started))
    assert reader.cancelled_seen.is_set()  # the reader was stopped, not waited for to the end
    assert host.metadata_thread is None and not host._metadata_workers_running()
    assert [(o.occurrence_id, o.fields[0].value) for o in started[0].metadata_overrides] == [
        ("a.pdf", "WHILE-READING")
    ]


@pytest.mark.parametrize("kind", HOSTS)
def test_import_starts_only_after_a_slow_report_ended_without_blocking_the_gui(
    app, make_host, readers, started, kind
):
    blocker = threading.Event()
    host, _ = open_review(make_host, readers, kind, blocker=blocker)
    wait_until(app, readers.instances[0].started.is_set)
    planner = host.report_planner
    planner.proxy.setData(cell(planner, "a.pdf", "reference"), "SLOW")

    host._import_reviewed_reports()  # the worker is inside one slow report

    assert started == [] and host._start_pending  # PyMuPDF never runs in two threads at once
    assert not host.parse_button.isEnabled() and not host.scan_button.isEnabled()
    assert "Stopping the metadata read" in host.readiness_label.text()
    host._import_reviewed_reports()  # a second click is ignored while the first is pending
    assert started == []

    blocker.set()
    wait_until(app, lambda: bool(started))
    assert len(started) == 1 and not host._start_pending
    assert [o.occurrence_id for o in started[0].metadata_overrides] == ["a.pdf"]


@pytest.mark.parametrize("kind", HOSTS)
def test_a_new_read_queues_behind_a_worker_that_is_still_stopping(app, make_host, readers, kind):
    blocker = threading.Event()
    readers.queue = [{"blocker": blocker}, {"fast": {"a.pdf": dict(FULL)}}]
    host = make_host(kind)
    host.on_preflight_completed(review_result(("a.pdf",), source=host.directory, database=host.db_file))
    wait_until(app, readers.instances[0].started.is_set)

    # A retired worker (source change) is still in its report when the next review completes.
    host._invalidate_preflight()
    host.on_preflight_completed(review_result(("a.pdf",), source=host.directory, database=host.db_file))
    assert len(readers.instances) == 1 and host.metadata_thread is None  # the new read waits

    blocker.set()
    wait_until(app, lambda: len(readers.instances) == 2)
    settle(app, host)
    assert cell(host.report_planner, "a.pdf", "reference").data() == "REF-A"


@pytest.mark.parametrize("kind", HOSTS)
def test_refresh_review_starts_only_after_a_slow_report_ended(app, make_host, readers, monkeypatch, kind):
    blocker = threading.Event()
    host, _ = open_review(make_host, readers, kind, blocker=blocker)
    wait_until(app, readers.instances[0].started.is_set)
    monkeypatch.setattr(parsing_dialog_module, "ParsePreflightThread", _FakePreflightThread)
    _FakePreflightThread.result = review_result(("a.pdf", "b.pdf", "c.pdf"), source=host.directory, database=host.db_file)

    host.scan_reports()

    assert host.preflight_thread is None and host._start_pending  # queued, the GUI did not block
    blocker.set()
    wait_until(app, lambda: host.preflight_thread is None and not host._start_pending)
    settle(app, host)
    assert host.report_planner.model.metadata_row("a.pdf") is not None


@pytest.mark.parametrize("kind", HOSTS)
def test_import_is_disabled_while_ocr_runs(app, make_host, readers, started, kind):
    host, _ = open_review(make_host, readers, kind)
    settle(app, host)
    gate = threading.Event()
    readers.options = dict(readers.options, gate=gate)
    assert host.start_metadata_ocr()
    reader = readers.instances[-1]
    wait_until(app, reader.started.is_set)

    assert not host.parse_button.isEnabled()
    assert "OCR" in host.parse_button.toolTip() and "Stop" in host.parse_button.toolTip()
    host._import_reviewed_reports()
    assert started == []

    host.report_planner.stop_action.trigger()
    settle(app, host)
    assert reader.cancelled_seen.is_set() and host.parse_button.isEnabled()
    assert "stopped" in host.report_planner.metadata_status_text


# --- lifecycle -----------------------------------------------------------------


@pytest.mark.parametrize("kind", HOSTS)
def test_changing_the_context_stops_the_worker_and_discards_rows(app, make_host, readers, kind):
    gate = threading.Event()
    host, _ = open_review(make_host, readers, kind, gate=gate)
    wait_until(app, readers.instances[0].started.is_set)
    thread = host.metadata_thread
    assert host.can_change_workspace()  # a background read never blocks a context change

    host.apply_workspace_snapshot(SimpleNamespace(source_directory="/other", database_file=host.db_file))

    assert host.metadata_thread is None
    assert host.report_planner.model.metadata_rows == {}
    assert thread.cancel_requested
    assert thread in host._metadata_threads  # accounted for until it has ended
    wait_until(app, lambda: host._metadata_threads == [])
    assert not host._workers_running()


@pytest.mark.parametrize("kind", HOSTS)
def test_changing_the_mode_discards_rows_and_stops_the_worker(app, make_host, readers, kind):
    host, _ = open_review(make_host, readers, kind, gate=threading.Event())
    wait_until(app, readers.instances[0].started.is_set)
    host.metadata_mode_combo.setCurrentIndex(host.metadata_mode_combo.findData("complete"))
    assert host.metadata_thread is None and host.report_planner.model.metadata_rows == {}
    wait_until(app, lambda: not host._workers_running())


@pytest.mark.parametrize("kind", HOSTS)
def test_a_retired_worker_never_touches_the_next_review(app, make_host, readers, kind):
    blocker = threading.Event()
    readers.queue = [{"blocker": blocker, "fast": {"a.pdf": dict(FULL)}}, {"gate": threading.Event(), "fast": {}}]
    host = make_host(kind)
    first = review_result(("a.pdf",), source=host.directory, database=host.db_file)
    host.on_preflight_completed(first)
    wait_until(app, readers.instances[0].started.is_set)
    old_thread = host.metadata_thread

    host._invalidate_preflight()  # the old worker is mid-report and cannot stop yet
    host.on_preflight_completed(review_result(("a.pdf",), source=host.directory, database=host.db_file))
    assert host.metadata_thread is not old_thread and old_thread.isRunning()

    blocker.set()  # the old report now finishes and emits its reading
    wait_until(app, lambda: old_thread not in host._metadata_threads)
    app.processEvents()
    app.processEvents()
    assert host.report_planner.model.metadata_row("a.pdf").state == "pending"
    assert cell(host.report_planner, "a.pdf", "reference").data() == meta.PENDING_TEXT


@pytest.mark.parametrize("kind", HOSTS)
def test_refresh_review_keeps_unchanged_rows_and_drops_the_rest(app, make_host, readers, kind):
    host, _ = open_review(make_host, readers, kind, names=("a.pdf", "b.pdf", "c.pdf"))
    settle(app, host)
    planner = host.report_planner
    planner.proxy.setData(cell(planner, "a.pdf", "reference"), "KEEP-ME")
    planner.proxy.setData(cell(planner, "b.pdf", "reference"), "LOSE-ME")
    kept = planner.model.metadata_row("a.pdf")

    # Refresh with the same source: a is unchanged, b changed on disk, c is gone, d is new.
    host._invalidate_preflight(keep_metadata=True)
    refreshed = review_result(("a.pdf", "b.pdf", "d.pdf"), source=host.directory, database=host.db_file)
    changed = tuple(
        replace(item, fingerprint="sha256:" + "9" * 64) if item.display_name == "b.pdf" else item
        for item in refreshed.files
    )
    host.on_preflight_completed(replace(refreshed, files=changed))
    settle(app, host)

    model = planner.model
    assert model.metadata_row("a.pdf") is kept and kept.value("reference") == "KEEP-ME"
    assert model.metadata_row("b.pdf").value("reference") == "REF-A"  # re-read, the old edit is gone
    assert model.metadata_row("c.pdf") is None
    assert readers.instances[-1].calls[0][1] == ("b.pdf", "d.pdf")  # only unread reports are read again


@pytest.mark.parametrize("kind", HOSTS)
def test_source_change_discards_every_row_including_edits(app, make_host, readers, kind):
    host, _ = open_review(make_host, readers, kind)
    settle(app, host)
    planner = host.report_planner
    planner.proxy.setData(cell(planner, "a.pdf", "reference"), "EDIT")
    host._invalidate_preflight()  # a source/database change never carries rows over
    host.on_preflight_completed(review_result(("a.pdf",), source=host.directory, database=host.db_file))
    settle(app, host)
    assert planner.model.metadata_row("a.pdf").value("reference") == "REF-A"


class _FakePreflightThread(QThread):
    update_label = pyqtSignal(str)
    update_progress = pyqtSignal(int)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    result = None

    def __init__(self, source_path, database_path, metadata_parsing_mode):
        super().__init__()

    def stop_scan(self):
        pass

    def run(self):
        self.completed.emit(type(self).result)


@pytest.mark.parametrize("kind", HOSTS)
def test_a_real_refresh_through_scan_reports_keeps_edits(app, make_host, readers, monkeypatch, kind):
    host, first = open_review(make_host, readers, kind)
    settle(app, host)
    planner = host.report_planner
    planner.proxy.setData(cell(planner, "a.pdf", "reference"), "KEEP-ME")
    monkeypatch.setattr(parsing_dialog_module, "ParsePreflightThread", _FakePreflightThread)
    _FakePreflightThread.result = review_result(
        ("a.pdf", "b.pdf", "c.pdf"), source=host.directory, database=host.db_file
    )
    host.scan_reports()
    wait_until(app, lambda: host.preflight_thread is None)
    settle(app, host)
    assert planner.model.metadata_row("a.pdf").value("reference") == "KEEP-ME"
    assert len(readers.instances) == 1  # nothing was left to read: no second worker started


@pytest.mark.parametrize("kind", HOSTS)
def test_close_and_shutdown_are_deferred_until_the_worker_stopped(app, make_host, readers, kind):
    blocker = threading.Event()
    host, _ = open_review(make_host, readers, kind, blocker=blocker)
    wait_until(app, readers.instances[0].started.is_set)
    thread = host.metadata_thread
    assert thread.isRunning()

    if kind == "dialog":
        host.reject()
        assert host.isVisible()  # the close waits for the worker
        host.close()
        assert host.isVisible() and host.is_close_deferred()
        assert thread.cancel_requested
        blocker.set()
        wait_until(app, lambda: not host.isVisible())
    else:
        ready = QSignalSpy(host.shutdown_ready)
        assert host.request_shutdown() is False
        assert host.is_close_deferred() and thread.cancel_requested
        blocker.set()
        wait_until(app, lambda: len(ready) == 1)
    assert host._metadata_threads == [] and host.metadata_thread is None
    assert host.request_shutdown() is True


# --- attention, search, counts ---------------------------------------------------


@pytest.mark.parametrize("kind", HOSTS)
def test_attention_filter_and_counts_cover_metadata(app, make_host, readers, kind):
    fast = {
        "a.pdf": dict(FULL),
        "b.pdf": {**FULL, "reference": None},  # missing reference
        "c.pdf": {**FULL, "part_name": ("Part", FILE_NAME, 0.4)},  # low confidence
    }
    host, _ = open_review(make_host, readers, kind, fast=fast)
    settle(app, host)
    planner, model = host.report_planner, host.report_planner.model

    assert model.metadata_counts["missing_reference"] == 1
    assert "1 missing reference" in planner.counts.text()
    assert model.counts["attention"] == 2

    planner.attention_filter.setChecked(True)
    shown = {planner.proxy.index(row, model.LOCATION_COLUMN).data() for row in range(planner.proxy.rowCount())}
    assert shown == {"b.pdf", "c.pdf"}
    missing = cell(planner, "b.pdf", "reference")
    assert missing.data() == meta.MISSING_TEXT and missing.data(model.STYLE_ROLE) == meta.KIND_MISSING
    assert "missing reference" in index(planner, "b.pdf", model.DETAIL_COLUMN).data()
    assert cell(planner, "c.pdf", "part_name").data(model.STYLE_ROLE) == meta.KIND_LOW_CONFIDENCE

    planner.proxy.setData(missing, "FILLED")  # editing the value ends the attention
    shown = {planner.proxy.index(row, model.LOCATION_COLUMN).data() for row in range(planner.proxy.rowCount())}
    assert shown == {"c.pdf"} and model.metadata_counts["missing_reference"] == 0
    assert "missing reference" not in planner.counts.text()


@pytest.mark.parametrize("kind", HOSTS)
def test_search_matches_metadata_values(app, make_host, readers, kind):
    fast = {"a.pdf": dict(FULL), "b.pdf": {**FULL, "reference": "SPECIAL-77"}}
    host, _ = open_review(make_host, readers, kind, names=("a.pdf", "b.pdf"), fast=fast)
    settle(app, host)
    planner = host.report_planner
    planner.search.setText("special-77")
    assert planner.proxy.rowCount() == 1 and planner.proxy.index(0, 1).data() == "b.pdf"
    planner.proxy.setData(cell(planner, "b.pdf", "comment"), "needle in a comment")
    planner.search.setText("needle")  # edits are searchable too, even in hidden columns
    assert planner.proxy.rowCount() == 1


@pytest.mark.parametrize("kind", HOSTS)
def test_sorting_by_a_metadata_column_orders_by_value(app, make_host, readers, kind):
    fast = {"a.pdf": {**FULL, "reference": "Z"}, "b.pdf": {**FULL, "reference": "A"}, "c.pdf": {**FULL, "reference": "M"}}
    host, _ = open_review(make_host, readers, kind, fast=fast)
    settle(app, host)
    planner = host.report_planner
    planner.table.sortByColumn(planner.model.column_for_field("reference"), Qt.SortOrder.AscendingOrder)
    assert [planner.proxy.index(row, 1).data() for row in range(3)] == ["b.pdf", "c.pdf", "a.pdf"]


def test_readiness_message_summarizes_the_checked_metadata(app, make_host, readers):
    fast = {"a.pdf": dict(FULL), "b.pdf": {**FULL, "reference": None}}
    host, _ = open_review(make_host, readers, "dialog", names=("a.pdf", "b.pdf"), fast=fast)
    settle(app, host)
    assert "Metadata: 2 reports, 0 edited, 1 missing a reference" in host.readiness_label.text()
    planner = host.report_planner
    planner.proxy.setData(cell(planner, "b.pdf", "reference"), "FILLED")
    assert "Metadata: 2 reports, 1 edited, all have a reference" in host.readiness_label.text()


# --- theme ---------------------------------------------------------------------


def _luminance(color: QColor) -> float:
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(color.red()) + 0.7152 * channel(color.green()) + 0.0722 * channel(color.blue())


def _contrast(foreground: QColor, background: QColor) -> float:
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize("kind", HOSTS)
def test_attention_and_manual_styling_follow_the_theme(app, make_host, readers, kind):
    fast = {
        "a.pdf": {**FULL, "reference": None},                           # missing
        "b.pdf": {**FULL, "part_name": ("Part", FILE_NAME, 0.4)},       # low confidence
        "c.pdf": dict(FULL),
    }
    ocr = {"c.pdf": {**FULL, "reference": "OCR-REF"}}
    host, _ = open_review(make_host, readers, kind, fast=fast, ocr=ocr)
    settle(app, host)
    planner = host.report_planner
    planner.proxy.setData(cell(planner, "c.pdf", "reference"), "MINE")
    check(planner, "a.pdf", False)
    assert host.start_metadata_ocr()
    settle(app, host)

    probes = {
        "missing": cell(planner, "a.pdf", "reference"),
        "low": cell(planner, "b.pdf", "part_name"),
        "conflict": cell(planner, "c.pdf", "reference"),
        "manual": cell(planner, "c.pdf", "part_name"),
    }
    planner.proxy.setData(probes["manual"], "Typed")
    colors = {}
    for dark in (False, True):
        apply_metroliza_theme(host, dark_mode=dark)  # the real theme layer, not the desktop palette
        palette = tokens.theme_tokens(dark_mode=dark)
        status = palette["STATUS_COLORS"]
        surface = QColor(palette["SURFACE_BACKGROUND"])

        def brush(probe, role):
            value = probe.data(role)
            return None if value is None else value.color()

        missing_fg, missing_bg = brush(probes["missing"], Qt.ItemDataRole.ForegroundRole), brush(probes["missing"], Qt.ItemDataRole.BackgroundRole)
        assert missing_fg.name().upper() == status["warning"][0].upper()
        assert missing_bg.name().upper() == status["warning"][1].upper()
        assert brush(probes["low"], Qt.ItemDataRole.ForegroundRole).name().upper() == status["warning"][0].upper()
        assert brush(probes["conflict"], Qt.ItemDataRole.BackgroundRole).name().upper() == status["info"][1].upper()
        manual_fg = brush(probes["manual"], Qt.ItemDataRole.ForegroundRole)
        assert manual_fg.name().upper() == palette["ACCENT_PRIMARY"].upper()
        # Readable on the table surface (or on the tint the cell is drawn over).
        assert _contrast(missing_fg, missing_bg) >= 4.5
        assert _contrast(manual_fg, surface) >= 4.5
        assert _contrast(brush(probes["low"], Qt.ItemDataRole.ForegroundRole), surface) >= 4.5
        colors[dark] = (missing_fg.name(), missing_bg.name(), manual_fg.name(),
                        brush(probes["conflict"], Qt.ItemDataRole.BackgroundRole).name())
    assert all(light != dark for light, dark in zip(colors[False], colors[True]))


# --- real files: nothing is written before Import ------------------------------


NAMES = ("AAAAA11111_Alpha_2024-01-01_1.pdf", "BBBBB22222_Beta_2024-01-02_2.pdf", "plain.pdf")


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
def real_review(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for index_, name in enumerate(NAMES):
        (source / name).write_bytes(FIXTURE.read_bytes() + f"\n% ui-{index_}\n".encode())
    database = tmp_path / "reports.sqlite3"
    result = ParsePreflightService().scan_source(
        source_path=source, database_path=database, metadata_parsing_mode="light"
    )
    return source, database, result


@pytest.mark.parametrize("kind", HOSTS)
def test_real_reader_runs_off_the_gui_thread_and_writes_nothing_before_import(
    app, real_review, monkeypatch, started, kind
):
    source, database, result = real_review
    threads = []
    original = MetadataReviewReader._read_one

    def spy(self, *args, **kwargs):
        threads.append(QThread.currentThread())
        return original(self, *args, **kwargs)

    def fake_ocr(cls, page, bbox, pdf_backend):
        threads.append(QThread.currentThread())
        return list(OCR_ITEMS), None

    monkeypatch.setattr(MetadataReviewReader, "_read_one", spy)
    monkeypatch.setattr(CMMReportParser, "_ocr_header_items_from_pixmap", classmethod(fake_ocr))
    monkeypatch.setattr(_ReportOperations, "_ocr_unavailable_reason", staticmethod(lambda: ""))
    if kind == "dialog":
        host = ParsingDialog(parent=None, directory=str(source), db_file=str(database))
    else:
        host = ReportsWorkspace()
        host.apply_workspace_snapshot(SimpleNamespace(source_directory=str(source), database_file=str(database)))
    host.show()
    try:
        host.on_preflight_completed(result)
        settle(app, host)
        planner = host.report_planner
        assert threads and all(t is not app.thread() for t in threads)
        assert cell(planner, NAMES[0], "reference").data() == "AAAAA11111"
        assert cell(planner, "plain.pdf", "reference").data() == meta.MISSING_TEXT

        planner.proxy.setData(cell(planner, NAMES[0], "reference"), "MANUAL")
        planner.table.selectRow(0)
        host.report_planner.ocr_button.click()
        settle(app, host)
        assert planner.model.metadata_row(NAMES[0]).value("reference") == "MANUAL"
        assert planner.model.metadata_row(NAMES[1]).value("reference") == "OCR-REF-9"

        # A cancelled OCR run keeps the cells that were already filled.
        host.start_metadata_ocr()
        host.stop_metadata_read()
        settle(app, host)
        planner.proxy.setData(cell(planner, "plain.pdf", "reference"), "FILLED")
        assert not database.exists()

        host._import_reviewed_reports()
        plan = started[0]
        by_id = {o.occurrence_id: {f.field_name: (f.value, f.origin) for f in o.fields} for o in plan.metadata_overrides}
        assert by_id[NAMES[0]]["reference"] == ("MANUAL", "user")
        assert by_id[NAMES[1]]["reference"] == ("OCR-REF-9", "ocr")
        assert by_id["plain.pdf"]["reference"] == ("FILLED", "user")
        assert not database.exists()  # review, reads, edits and cancel never create the destination
    finally:
        host._request_active_worker_cancellation()
        wait_until(app, lambda: not host._workers_running())
        host.parse_thread = None
        host.deleteLater()
        flush_widgets(app)


def test_end_to_end_import_writes_the_confirmed_values_only_on_import(real_review):
    from metroliza.parsing.parse_reports_thread import ParseReportsThread
    from metroliza.shared.parse_contracts import ParseRequest

    source, database, result = real_review
    rows = {
        item.stable_occurrence_id: ReviewRow(item.stable_occurrence_id, item.fingerprint, item.display_name, item.parser_id)
        for item in result.ready_files
    }
    rows["plain.pdf"].set_user_value("reference", "FILLED")
    assert not database.exists()
    request = ParseRequest(source_directory=str(source), db_file=str(database), metadata_parsing_mode="light")
    plan = ImportPlan.from_preflight(
        request, result, selected_occurrence_ids=tuple(rows), metadata_overrides=build_overrides(rows.values()),
    )
    ParseReportsThread(plan).run()
    with closing(sqlite3.connect(database)) as connection:
        references = sorted(r[0] or "" for r in connection.execute("SELECT reference FROM report_metadata"))
    assert references == ["AAAAA11111", "BBBBB22222", "FILLED"]


# --- presentation helpers (Qt-free) ----------------------------------------------


def test_cell_text_tooltips_and_accessible_text():
    row = ReviewRow("a.pdf", "sha256:" + "1" * 64, "a.pdf", "cmm")
    assert meta.display_text(row, "reference") == meta.PENDING_TEXT
    assert meta.accessible_text(row, "a.pdf", "reference") == "a.pdf, Reference: not read yet"

    row.apply_fast(make_selection({"reference": ("R1", FILE_NAME, 0.4), "part_name": "P", "report_date": "2024-01-01"}))
    assert meta.accessible_text(row, "a.pdf", "reference") == "a.pdf, Reference: R1"
    assert meta.accessible_text(row, "a.pdf", "sample_number") == "a.pdf, Sample no.: missing"
    assert meta.display_text(row, "sample_number") == meta.MISSING_TEXT
    assert meta.display_text(row, "comment") == ""  # optional fields are never "missing"
    tip = meta.cell_tooltip(row, "a.pdf", "reference")
    assert "Source: file name (40%)" in tip and "Low confidence" in tip
    assert "Source: report header (99%)" in meta.cell_tooltip(row, "a.pdf", "part_name")
    assert "Missing" in meta.cell_tooltip(row, "a.pdf", "sample_number")
    assert meta.metadata_attention_reasons(row) == ("missing sample no.", "low confidence reference")

    row.set_user_value("sample_number", "7")
    assert "Source: entered by you" in meta.cell_tooltip(row, "a.pdf", "sample_number")
    assert meta.cell_style(row, "sample_number") == meta.CellStyle(meta.KIND_MANUAL, bold=True)
    assert meta.summarize_rows([row]) == "1 report, 1 edited, all have a reference"


def test_details_list_value_source_confidence_candidates_and_notes():
    selection = make_selection({"reference": ("R1", "header_exact", 0.99)})
    alternative = selection.candidates[0].__class__(
        field_name="reference", raw_value="R2", normalized_value="R2", source_type=FILE_NAME,
        source_detail=None, page_number=None, region_name=None, label_text=None, rule_id="alt",
        confidence=0.4, evidence_text=None, selected=False,
    )
    row = ReviewRow("a.pdf", "sha256:" + "1" * 64, "a.pdf", "cmm")
    row.apply_fast(selection.__class__(metadata=selection.metadata, candidates=(*selection.candidates, alternative)))
    row.set_user_value("part_name", "Mine")
    text = "\n".join(meta.details_lines(row))
    assert "Reference: R1 · source report header · confidence 99% · other candidates: R2 (file name (40%))" in text
    assert "Part name: Mine · source entered by you" in text
    assert "Date: missing" in text
    notes = ReviewRow("n.pdf", "sha256:" + "2" * 64, "n.pdf", "other")
    notes.mark_failed("Changed since review.", state="changed")
    assert "Changed since review." in "\n".join(meta.details_lines(notes))
