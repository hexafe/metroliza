from __future__ import annotations

import types

import pytest

try:
    from PyQt6.QtCore import QDate, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QDialog, QListWidget, QListWidgetItem

    import metroliza.ui.filter_dialog as filter_dialog
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QApplication = None
    QDate = None
    QDialog = None
    QTest = None
    Qt = None
    QListWidget = None
    QListWidgetItem = None
    filter_dialog = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 filter dialog widgets are not available: {PYQT_IMPORT_ERROR}",
)
_QT_APP = None


def _app():
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def _build_dialog(monkeypatch, *, parent=None, db_file=""):
    _app()
    monkeypatch.setattr(filter_dialog.FilterDialog, "populate_list_widgets", lambda self: None)
    dialog = filter_dialog.FilterDialog(parent=parent, db_file=db_file)
    return dialog


def _select_list_value(list_widget, value):
    previous_signal_state = list_widget.blockSignals(True)
    for row in range(list_widget.count()):
        item = list_widget.item(row)
        if item.text() == value:
            item.setSelected(True)
            list_widget.blockSignals(previous_signal_state)
            return item
    item = QListWidgetItem(value)
    list_widget.addItem(item)
    item.setSelected(True)
    list_widget.blockSignals(previous_signal_state)
    return item


def _replace_items(list_widget, values):
    list_widget.clear()
    for value in values:
        list_widget.addItem(QListWidgetItem(value))


def test_filter_dialog_construction_controls_and_summary(monkeypatch):
    dialog = _build_dialog(monkeypatch)
    try:
        assert dialog.isModal()
        assert dialog.filter_tabs.count() == 3
        assert dialog.apply_button.text() == "Apply Filters"
        assert dialog.apply_button.isDefault()
        assert dialog.reset_button.text() == "Reset draft"
        assert dialog.cancel_button.text() == "Cancel"
        assert dialog.has_nok_button.isCheckable()
        assert not dialog.has_nok_button.isChecked()
        assert dialog.filter_summary_label.text() == "No active filters"
        assert dialog._selected_value_count(dialog.ax_list) == 0

        _select_list_value(dialog.ax_list, "AX1")
        dialog.has_nok_button.setChecked(True)
        dialog.date_from_calendar.setDate(QDate(2024, 1, 1))
        dialog._refresh_filter_summary()

        assert dialog._selected_value_count(dialog.ax_list) == 1
        assert "Active filters:" in dialog.filter_summary_label.text()
        assert "NOK only" in dialog.filter_summary_label.text()

        dialog.select_beginning_of_time()
        dialog.select_today_as_date_to()

        assert dialog.date_from_calendar.date().toString("yyyy-MM-dd") == "1970-01-01"
        assert dialog.date_to_calendar.date().toString("yyyy-MM-dd") == QDate.currentDate().toString(
            "yyyy-MM-dd"
        )
    finally:
        dialog.close()


def test_filter_dialog_invalid_expression_and_native_exits_are_transactional(
    monkeypatch,
):
    dialog = _build_dialog(monkeypatch)
    try:
        dialog.expression_input.setText("Reference IN ()")
        dialog._refresh_filter_summary()

        assert dialog.apply_button.isEnabled() is False
        assert dialog.filter_summary_label.text().startswith("Invalid expression:")

        dialog.expression_input.setText("Reference=REF1")
        dialog.show()
        _app().processEvents()
        answers = iter(
            [
                filter_dialog.QtWidgets.QMessageBox.StandardButton.No,
                filter_dialog.QtWidgets.QMessageBox.StandardButton.Yes,
                filter_dialog.QtWidgets.QMessageBox.StandardButton.No,
                filter_dialog.QtWidgets.QMessageBox.StandardButton.Yes,
            ]
        )
        monkeypatch.setattr(
            filter_dialog.QtWidgets.QMessageBox,
            "question",
            lambda *_args, **_kwargs: next(answers),
        )

        assert dialog.close() is False
        _app().processEvents()
        assert dialog.isVisible()
        assert dialog.expression_input.text() == "Reference=REF1"
        assert dialog.close() is True
        _app().processEvents()
        assert not dialog.isVisible()
        assert dialog.expression_input.text() == ""

        dialog.show()
        dialog.expression_input.setText("Reference=REF2")
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        _app().processEvents()
        assert dialog.isVisible()
        assert dialog.expression_input.text() == "Reference=REF2"
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        _app().processEvents()
        assert not dialog.isVisible()
        assert dialog.expression_input.text() == ""
    finally:
        dialog.close()


def test_reference_header_controls_search_and_distinct_population(monkeypatch):
    dialog = _build_dialog(monkeypatch)
    try:
        _replace_items(dialog.reference_list, ["SELECT ALL", "REF1"])
        _replace_items(dialog.header_list, ["SELECT ALL", "OLD"])
        _replace_items(dialog.all_headers_list, ["SELECT ALL", "H1", "H2"])

        captured = {}

        def fake_populate(list_widget, column_name, *, source_view="vw_measurement_export", filter_query=None):
            captured["list_widget"] = list_widget
            captured["column_name"] = column_name
            captured["source_view"] = source_view
            captured["filter_query"] = filter_query
            list_widget.addItem(QListWidgetItem("H-REF1"))

        monkeypatch.setattr(
            filter_dialog,
            "build_measurement_filter_query",
            lambda **kwargs: "SELECT * FROM vw_measurement_export WHERE reference IN ('REF1')",
        )
        dialog._populate_distinct_values = fake_populate

        _select_list_value(dialog.reference_list, "REF1")
        dialog.on_reference_selection_changed()

        assert captured["list_widget"] is dialog.header_list
        assert captured["column_name"] == "HEADER"
        assert "reference IN ('REF1')" in captured["filter_query"]
        assert dialog.selected_headers_list.count() == 0

        _replace_items(dialog.reference_list, ["SELECT ALL", "REF1"])
        _select_list_value(dialog.reference_list, "SELECT ALL")
        dialog.on_reference_selection_changed()

        assert [dialog.header_list.item(row).text() for row in range(dialog.header_list.count())] == [
            "SELECT ALL",
            "H1",
            "H2",
        ]

        calls = {}
        dialog._list_selection_utils = types.SimpleNamespace(
            preserve_selection_during_filter=lambda list_widget, search_text: calls.update(
                {"list_widget": list_widget, "search_text": search_text}
            )
        )
        dialog.search_list_widgets(dialog.header_list, "h2")

        assert calls == {"list_widget": dialog.header_list, "search_text": "h2"}
    finally:
        dialog.close()


def test_apply_filters_sets_parent_query_state_and_hides(monkeypatch):
    class _Parent(QDialog):
        def __init__(self):
            super().__init__()
            self.query = None
            self.filter_state = None
            self.applied_state = None

        def set_filter_query(self, query):
            self.query = query

        def set_filter_state(self, state):
            self.filter_state = state

        def set_filter_applied(self, state):
            self.applied_state = state

    _app()
    parent = _Parent()
    dialog = _build_dialog(monkeypatch, parent=parent)
    try:
        _select_list_value(dialog.ax_list, "AX1")
        _select_list_value(dialog.header_list, "H1")
        _select_list_value(dialog.reference_list, "REF1")
        _select_list_value(dialog.filename_list, "source.csv")
        _select_list_value(dialog.parser_id_list, "cmm_pdf")
        dialog.has_nok_button.setChecked(True)
        dialog.date_from_calendar.setDate(QDate(2024, 1, 1))
        dialog.date_to_calendar.setDate(QDate(2024, 12, 31))

        dialog.apply_filters()

        assert parent.query == dialog.filter_query
        assert "ax IN ('AX1')" in parent.query
        assert "header IN ('H1')" in parent.query
        assert "reference IN ('REF1')" in parent.query
        assert "file_name IN ('source.csv')" in parent.query
        assert "parser_id IN ('cmm_pdf')" in parent.query
        assert "has_nok = 1" in parent.query
        assert parent.filter_state == parent.applied_state
        assert parent.filter_state.ax_values == ("AX1",)
        assert parent.filter_state.filename_values == ("source.csv",)
        assert parent.filter_state.has_nok_only is True
        assert not dialog.isVisible()
    finally:
        dialog.close()
        parent.close()


def test_filter_helpers_and_parent_callback_compatibility(monkeypatch):
    assert filter_dialog._normalize_filter_values([" A ", None, "", "B"]) == ["A", "B"]
    assert filter_dialog._build_in_clause("name", ["O'Brien", ""]) == "name IN ('O''Brien')"
    assert filter_dialog._build_in_clause("name", []) is None

    class _NoArgParent:
        def __init__(self):
            self.called = False

        def set_filter_applied(self):
            self.called = True

    no_arg_parent = _NoArgParent()
    filter_dialog.FilterDialog._call_parent_filter_applied(no_arg_parent, object())

    assert no_arg_parent.called

    dialog = _build_dialog(monkeypatch)
    calls = []
    dialog._start_value_load = lambda specs, query: calls.append((specs, query))
    try:
        dialog._populate_distinct_values(dialog.ax_list, "AX", filter_query="scope")
        assert calls == [((("ax_list", "AX", "vw_measurement_export"),), "scope")]
    finally:
        dialog.close()


def test_selected_header_delete_branches(monkeypatch):
    dialog = _build_dialog(monkeypatch)
    try:
        _replace_items(dialog.header_list, ["H1", "H2", "H3"])
        for row in range(dialog.header_list.count()):
            dialog.header_list.item(row).setSelected(True)
        dialog.update_selected_headers()

        assert dialog.selected_headers_list.count() == 3
        assert dialog._delete_selected_headers() is False

        dialog.selected_headers_list.item(1).setSelected(True)
        assert dialog._delete_selected_headers() is True

        assert [dialog.selected_headers_list.item(row).text() for row in range(dialog.selected_headers_list.count())] == [
            "H1",
            "H3",
        ]
        assert dialog.header_list.item(1).isSelected() is False
    finally:
        dialog.close()


def _wait_for_filter(predicate):
    import time

    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(5)
    assert predicate(), "Filter worker did not finish"


def test_background_choices_keep_gui_responsive_and_close_safe(monkeypatch):
    import threading
    from metroliza.ui import filter_values_loader

    app = _app()
    started = threading.Event()
    release = threading.Event()
    gui_thread = threading.get_ident()
    workers = []

    def slow_load(*_args, **kwargs):
        workers.append(threading.get_ident())
        started.set()
        assert release.wait(5)
        return {attribute: ("A", "Z") for attribute, _, _ in kwargs["specs"]}

    monkeypatch.setattr(filter_values_loader, "load_filter_values", slow_load)
    dialog = filter_dialog.FilterDialog(db_file="synthetic.sqlite")
    try:
        dialog.show()
        _wait_for_filter(started.is_set)
        assert workers == [workers[0]] and workers[0] != gui_thread
        assert dialog._values_loading
        assert dialog.filter_summary_label.text() == "Loading filter values…"
        assert not dialog.apply_button.isEnabled()
        assert not dialog.filter_tabs.isEnabled()
        assert dialog.cancel_button.isEnabled()
        # Processing events while the worker is gated proves the GUI is free.
        app.processEvents()
        assert dialog.close()
        assert not dialog.isVisible()
        # Even a queued result cannot repopulate the closed dialog.
        original_count = dialog.ax_list.count()
        dialog._receive_filter_values(dialog._value_request - 1, {"ax_list": ("late",)})
        assert dialog.ax_list.count() == original_count
        dialog.deleteLater()
        app.processEvents()
    finally:
        release.set()
        _wait_for_filter(lambda: not filter_values_loader._RUNNING_LOADERS)


def test_background_success_error_and_reopen(monkeypatch):
    from metroliza.ui import filter_values_loader

    _app()
    calls = []

    def load(*args, **kwargs):
        calls.append(args)
        return {attribute: ("A", "Z") for attribute, _, _ in kwargs["specs"]}

    monkeypatch.setattr(filter_values_loader, "load_filter_values", load)
    dialog = filter_dialog.FilterDialog(db_file="synthetic.sqlite")
    try:
        dialog.show()
        _wait_for_filter(lambda: not dialog._values_loading)
        for attr in ("ax_list", "header_list", "all_headers_list", "filename_list"):
            widget = getattr(dialog, attr)
            assert [widget.item(row).text() for row in range(widget.count())] == ["SELECT ALL", "A", "Z"]
        assert dialog.apply_button.isEnabled()
        assert dialog.close()
        dialog.show()
        _wait_for_filter(lambda: not dialog._values_loading)
        assert len(calls) == 2

        def fail(*_args, **_kwargs):
            raise RuntimeError("synthetic load failure")

        errors = []
        monkeypatch.setattr(filter_values_loader, "load_filter_values", fail)
        dialog.log_and_exit = errors.append
        dialog.populate_list_widgets()
        _wait_for_filter(lambda: not dialog._values_loading)
        assert len(errors) == 1
        assert not dialog.apply_button.isEnabled()
        assert "Unable to load" in dialog.filter_summary_label.text()
        dialog.apply_filters()
        assert dialog.isVisible()
    finally:
        dialog.close()
        _wait_for_filter(lambda: not filter_values_loader._RUNNING_LOADERS)


def test_replaced_background_request_ignores_old_results(monkeypatch):
    import threading
    from metroliza.ui import filter_values_loader

    _app()
    started = threading.Event()
    release = threading.Event()
    calls = []

    def load(*_args, **kwargs):
        calls.append(kwargs["specs"])
        if len(calls) == 1:
            started.set()
            assert release.wait(5)
            return {"ax_list": ("old",)}
        return {"ax_list": ("new",)}

    monkeypatch.setattr(filter_values_loader, "load_filter_values", load)
    dialog = filter_dialog.FilterDialog(db_file="synthetic.sqlite")
    try:
        _wait_for_filter(started.is_set)
        old_request = dialog._value_request
        dialog.populate_list_widgets()
        _wait_for_filter(lambda: not dialog._values_loading)
        dialog._receive_filter_values(old_request, {"ax_list": ("old",)})
        assert dialog.ax_list.item(1).text() == "new"
    finally:
        release.set()
        dialog.close()
        _wait_for_filter(lambda: not filter_values_loader._RUNNING_LOADERS)


def test_real_database_load_refreshes_retained_dialog_after_commit(tmp_path, monkeypatch):
    from contextlib import closing
    import sqlite3
    import threading

    from metroliza.reports import filter_values
    from metroliza.reports.report_schema import ensure_report_schema
    from metroliza.ui.filter_values_loader import _RUNNING_LOADERS

    _app()
    database = str(tmp_path / "synthetic.sqlite")
    ensure_report_schema(database)
    with closing(sqlite3.connect(database)) as writer, writer:
        writer.executescript("""
            INSERT INTO source_files(id,sha256,source_format,discovered_at)
            VALUES (1,'synthetic','pdf','2026');
            INSERT INTO parsed_reports(id,source_file_id,parser_id,template_family,parse_status,created_at,updated_at)
            VALUES (1,1,'synthetic','synthetic','parsed','2026','2026');
            INSERT INTO report_measurements(report_id,row_order,header,ax,status_code)
            VALUES (1,1,'H','X','ok');
        """)
    original = filter_values.ensure_report_schema
    gui_thread = threading.get_ident()
    workers = []

    def ensure_in_worker(*args, **kwargs):
        workers.append(threading.get_ident())
        assert threading.get_ident() != gui_thread
        return original(*args, **kwargs)

    monkeypatch.setattr(filter_values, "ensure_report_schema", ensure_in_worker)
    dialog = filter_dialog.FilterDialog(db_file=database)
    try:
        dialog.show()
        _wait_for_filter(lambda: not dialog._values_loading)
        assert dialog.ax_list.item(1).text() == "X"
        assert dialog.header_list.item(1).text() == "H"
        dialog.hide()  # Apply also retains the dialog by hiding it.
        with closing(sqlite3.connect(database)) as writer, writer:
            writer.execute("UPDATE report_measurements SET ax = 'Y'")
        dialog.show()
        _wait_for_filter(lambda: not dialog._values_loading)
        assert dialog.ax_list.item(1).text() == "Y"
        assert len(workers) == 2
    finally:
        dialog.close()
        _wait_for_filter(lambda: not _RUNNING_LOADERS)


def test_cleared_reference_cancels_pending_header_scope(monkeypatch):
    import threading
    from metroliza.ui import filter_values_loader

    _app()
    started = threading.Event()
    release = threading.Event()
    calls = []

    def load(*_args, **kwargs):
        calls.append(kwargs["specs"])
        if len(calls) == 1:
            return {attribute: ("A", "Z") for attribute, _, _ in kwargs["specs"]}
        started.set()
        assert release.wait(5)
        return {"header_list": ("stale-scope",)}

    monkeypatch.setattr(filter_values_loader, "load_filter_values", load)
    dialog = filter_dialog.FilterDialog(db_file="synthetic.sqlite")
    try:
        _wait_for_filter(lambda: not dialog._values_loading)
        dialog.reference_list.item(1).setSelected(True)
        _wait_for_filter(started.is_set)
        assert dialog._values_loading
        # A controller can clear selection even while user input is disabled.
        dialog.reference_list.clearSelection()
        assert not dialog._values_loading
        release.set()
        _wait_for_filter(lambda: not filter_values_loader._RUNNING_LOADERS)
        assert [dialog.header_list.item(i).text() for i in range(dialog.header_list.count())] == ["SELECT ALL", "A", "Z"]
    finally:
        release.set()
        dialog.close()
        _wait_for_filter(lambda: not filter_values_loader._RUNNING_LOADERS)


@pytest.fixture
def applied_choices_db(tmp_path):
    from contextlib import closing
    import sqlite3

    from metroliza.reports.report_schema import ensure_report_schema

    database = str(tmp_path / "applied-choices.sqlite")
    ensure_report_schema(database)
    with closing(sqlite3.connect(database)) as writer, writer:
        writer.executescript("""
            INSERT INTO source_files(id,sha256,source_format,discovered_at)
            VALUES (1,'synthetic-review','pdf','2026');
            INSERT INTO parsed_reports(id,source_file_id,parser_id,template_family,parse_status,created_at,updated_at)
            VALUES (1,1,'synthetic','synthetic','parsed','2026','2026');
            INSERT INTO report_metadata(report_id,report_date,metadata_version)
            VALUES (1,'2026-01-01','v1');
            INSERT INTO report_measurements(report_id,row_order,header,ax,status_code)
            VALUES (1,1,'H','X','ok'),(1,2,'H','Y','ok');
        """)
    return database


def _selected_ax_rows(database, query):
    from contextlib import closing
    import sqlite3

    with closing(sqlite3.connect(database)) as reader:
        return [row[0] for row in reader.execute(f'SELECT AX FROM ({query}) ORDER BY AX')]


@pytest.mark.parametrize("change", ["replace", "delete"])
def test_refresh_preserves_unavailable_applied_value_until_explicit_clear(applied_choices_db, change):
    from contextlib import closing
    import sqlite3

    from metroliza.ui.filter_values_loader import _RUNNING_LOADERS

    _app()
    dialog = filter_dialog.FilterDialog(db_file=applied_choices_db)
    try:
        dialog.show()
        _wait_for_filter(lambda: not dialog._values_loading)
        dialog.ax_list.findItems("X", Qt.MatchFlag.MatchExactly)[0].setSelected(True)
        dialog.apply_filters()
        assert _selected_ax_rows(applied_choices_db, dialog.filter_query) == ["X"]
        applied_query = dialog.filter_query
        with closing(sqlite3.connect(applied_choices_db)) as writer, writer:
            if change == "replace":
                writer.execute("UPDATE report_measurements SET ax = 'Z' WHERE ax = 'X'")
            else:
                writer.execute("DELETE FROM report_measurements WHERE ax = 'X'")
        dialog.show()
        _wait_for_filter(lambda: not dialog._values_loading)
        assert [item.text() for item in dialog.ax_list.selectedItems()] == ["X"]
        assert "No active filters" not in dialog.filter_summary_label.text()
        dialog.apply_filters()
        assert dialog.filter_query == applied_query
        assert _selected_ax_rows(applied_choices_db, dialog.filter_query) == []
        # It remains a normal selectable condition, including explicit clearing.
        dialog.show()
        _wait_for_filter(lambda: not dialog._values_loading)
        dialog.ax_list.clearSelection()
        dialog.apply_filters()
        assert _selected_ax_rows(applied_choices_db, dialog.filter_query) == (["Y", "Z"] if change == "replace" else ["Y"])
    finally:
        dialog._confirm_discard = lambda **_kwargs: True
        dialog.close()
        _wait_for_filter(lambda: not _RUNNING_LOADERS)

