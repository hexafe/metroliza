from __future__ import annotations

import types

import pytest
from metroliza.ui.shortcuts import plain_text

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
        assert plain_text(dialog.apply_button.text()) == "Apply Filters [Ctrl+S]"
        assert dialog.apply_button.isDefault()
        assert plain_text(dialog.reset_button.text()) == "Reset draft [Ctrl+Shift+R]"
        assert plain_text(dialog.cancel_button.text()) == "Cancel [Ctrl+W]"
        assert dialog.has_nok_button.isCheckable()
        assert not dialog.has_nok_button.isChecked()
        assert dialog.filter_summary_label.text() == "No active filters | All dates"
        assert dialog._selected_value_count(dialog.ax_list) == 0

        _select_list_value(dialog.ax_list, "AX1")
        dialog.has_nok_button.setChecked(True)
        dialog.date_from_calendar.setDate(QDate(2024, 1, 1))
        dialog._refresh_filter_summary()

        assert dialog._selected_value_count(dialog.ax_list) == 1
        assert "Active filters:" in dialog.filter_summary_label.text()
        assert "Reports with at least one NOK" in dialog.filter_summary_label.text()

        dialog.select_beginning_of_time()
        dialog.select_today_as_date_to()

        assert dialog.date_from_calendar.date().toString("yyyy-MM-dd") == "1970-01-01"
        assert dialog.date_to_calendar.date().toString("yyyy-MM-dd") == QDate.currentDate().toString(
            "yyyy-MM-dd"
        )
    finally:
        dialog.close()


def test_named_filter_roundtrip_retains_unavailable_values_until_explicit_apply(monkeypatch, tmp_path):
    from metroliza.shared.filter_state import FilterState
    from metroliza.ui.report_filter_presets import ReportFilterPresets
    from dataclasses import asdict
    import json

    class Owner(QDialog):
        def set_filter_query(self, query):
            self.query = query

        def set_filter_state(self, state):
            self.state = state

    app = _app()
    path = tmp_path / "presets.ini"
    store = ReportFilterPresets(path)
    expected = FilterState(header_values=("WIDTH",), status_code_values=("nok",),
                           date_from="2024-01-01", date_to="2024-01-31")
    store.save("January NOK", expected)
    settings = store._settings()
    settings.setValue("invalid-entry", "not valid JSON")
    obsolete = "Obsolete field"
    settings.setValue(store._key(obsolete), json.dumps({
        "name": obsolete, "filter": {**asdict(expected), "old_measurement_field": []},
    }))
    settings.sync()
    presets, unavailable = ReportFilterPresets(path).load()
    assert presets == [("January NOK", expected)]
    assert len(unavailable) == 2
    assert "old_measurement_field" in dict(unavailable)[obsolete]

    owner = Owner()
    prior_query = "previous query"
    owner.query = prior_query
    dialog = _build_dialog(monkeypatch, parent=owner)
    dialog.show()
    try:
        dialog._load_saved_filter(presets[0][1])
        assert owner.query == prior_query
        assert dialog._current_filter_state() == expected
        assert dialog.measurement_nok_button.isChecked()
        assert "Unavailable selections" in dialog.filter_summary_label.text()
        assert dialog.header_list.accessibleName() == "Header choices"
        app.processEvents()
        QTest.keyClick(dialog.apply_button, Qt.Key.Key_Space)
        assert owner.state == expected
        assert "header IN ('WIDTH')" in owner.query and "status_code IN ('nok')" in owner.query
    finally:
        dialog.close()
        owner.close()


@pytest.mark.parametrize("unavailable", [True, False])
def test_replacing_saved_filter_requires_consent(monkeypatch, tmp_path, unavailable):
    from metroliza.shared.filter_state import FilterState
    from metroliza.ui.report_filter_presets import ReportFilterPresets

    path = tmp_path / "filters" / "reports.ini"
    store = ReportFilterPresets(path)
    store.save("January", FilterState(header_values=("WIDTH",)))
    if unavailable:
        settings = store._settings()
        settings.setValue(store._key("January"), "invalid JSON")
        settings.sync()
    assert bool(store.load()[1]) == unavailable
    original = path.read_bytes()

    monkeypatch.setattr("metroliza.ui.report_filter_presets.local_metroliza_directory", lambda: tmp_path)
    widgets = filter_dialog.QtWidgets
    monkeypatch.setattr(widgets.QMenu, "exec", lambda menu, _pos: menu.actions()[0].trigger())
    monkeypatch.setattr(widgets.QInputDialog, "getText", lambda *_args: (" january ", True))
    no = widgets.QMessageBox.StandardButton.No
    yes = widgets.QMessageBox.StandardButton.Yes
    responses = iter((no, yes))
    prompts = []

    def question(_dialog, _heading, text, _choices, default):
        prompts.append((text, default))
        return next(responses)

    monkeypatch.setattr(widgets.QMessageBox, "question", question)
    dialog = _build_dialog(monkeypatch)
    try:
        _select_list_value(dialog.header_list, "LENGTH")
        expected = dialog._current_filter_state()
        dialog._show_saved_filters()
        assert path.read_bytes() == original
        dialog._show_saved_filters()
        assert path.read_bytes() != original
        assert store.load() == ([("january", expected)], [])
        assert prompts == [("Replace the saved filter 'january'?", no)] * 2
    finally:
        dialog.close()


def test_typed_named_filter_roundtrips_separately_from_magic_after_restart(tmp_path):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys

    from metroliza.shared.filter_state import FilterState
    from metroliza.ui.report_filter_presets import ReportFilterPresets

    store = ReportFilterPresets(tmp_path / "reports.ini")
    state = FilterState(header_values=("Width",), expression_text='rEf IN ("001")')
    legacy = FilterState(expression_text='Ref IN ("1")')
    store.save("Daily", legacy)
    store.save_typed("DAILY", state)
    assert store.load() == ([("Daily", legacy)], [])
    assert store.contains_name("daily") and store.contains_name("daily", typed=True)
    settings = store._settings(typed=True)
    saved = json.loads(settings.value(store._key("daily"), "", type=str))
    assert saved.keys() == {"name", "version", "filter", "typed_expression", "definition_sha256"}
    assert saved["version"] == 2
    assert saved["typed_expression"]["expression"]["field"] == "reference"
    assert saved["typed_expression"]["expression"]["values"] == ["001"]

    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-c", (
            "import sys\nfrom metroliza.ui.report_filter_presets import ReportFilterPresets\n"
            "store = ReportFilterPresets(sys.argv[1])\nprint(store.load_typed()[0][0][1].expression_text)"
        ), str(store.path)],
        cwd=root, env={**os.environ, "PYTHONPATH": os.pathsep.join(map(str, (root / "src", root)))},
        check=True, text=True, capture_output=True, timeout=15,
    )
    assert completed.stdout.strip() == state.expression_text
    assert ReportFilterPresets(store.path).load_typed() == ([("DAILY", state)], [])


@pytest.mark.parametrize(("corruption", "expected"), [
    ("field", "retired_reference"), ("kind", "found text"), ("operator", "unsupported"),
    ("field_alias", "OldAlias"), ("future", "Unsupported typed report preset version"),
    ("experimental", "Experimental typed preset has no integrity check"),
    ("future_expression", "Unsupported filter document version"),
    ("mismatch", "conditions and expression text disagree"),
    ("malformed", "could not be read"), ("oversized", "could not be read"),
])
def test_unavailable_typed_presets_are_diagnosed_without_rewriting(tmp_path, corruption, expected):
    from hashlib import sha256
    import json

    from metroliza.shared.filter_state import FilterState
    from metroliza.ui.report_filter_presets import ReportFilterPresets

    store = ReportFilterPresets(tmp_path / "reports.ini")
    state = FilterState(expression_text='Ref IN ("001")')
    store.save_typed("Daily", state)
    settings = store._settings(typed=True)
    key = store._key("Daily")
    payload = json.loads(settings.value(key, "", type=str))
    condition = payload["typed_expression"]["expression"]
    if corruption in {"field", "kind", "operator"}:
        condition[corruption] = {"field": "retired_reference", "kind": "number", "operator": "unsupported"}[corruption]
    if corruption == "field_alias":
        payload["filter"]["expression_text"] = 'OldAlias IN ("001")'
    if corruption == "future":
        payload["version"] = 999
    if corruption == "future_expression":
        payload["typed_expression"]["version"] = 2
    if corruption == "mismatch":
        payload["filter"]["expression_text"] = 'Ref IN ("1")'
    payload.pop("definition_sha256")
    if corruption == "experimental":
        payload["version"] = 1
    else:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        payload["definition_sha256"] = sha256(canonical.encode("ascii")).hexdigest()
    raw = {"malformed": "not JSON", "oversized": "x" * 131073}.get(corruption, json.dumps(payload))
    settings.setValue(key, raw)
    settings.sync()
    before = store.path.read_bytes()
    presets, unavailable = ReportFilterPresets(store.path).load_typed()
    assert presets == [] and len(unavailable) == 1
    assert expected in unavailable[0][1]
    repair = store.load_typed_repair_draft("Daily")
    if corruption in {"field", "kind", "operator", "field_alias"}:
        assert repair is not None and repair.expression_text == payload["filter"]["expression_text"]
    else:
        assert repair is None
    with pytest.raises(ValueError, match="Confirm replacement"):
        store.save_typed("daily", state)
    with pytest.raises(ValueError, match="Enter a typed report filter expression"):
        store.save_typed("Daily", FilterState(), expected_record=raw)
    assert store.path.read_bytes() == before


def test_typed_saved_filter_runs_fresh_preview_before_apply(monkeypatch, tmp_path):
    from metroliza.reports.report_repository import ReportRepository
    from metroliza.reports.report_schema import ensure_report_schema
    from metroliza.ui.report_filter_presets import ReportFilterPresets
    from tests.test_1089_acceptance_analytics import _persist_report
    from tests.test_export_dialog_behavior import _build_dialog as build_export_dialog

    database = tmp_path / "reports.sqlite"
    ensure_report_schema(str(database))
    repository = ReportRepository(str(database))
    _persist_report(repository, tmp_path, number=1, reference="001")
    _persist_report(repository, tmp_path, number=2, reference="1")
    monkeypatch.setattr("metroliza.ui.report_filter_presets.local_metroliza_directory", lambda: tmp_path)
    monkeypatch.setattr(filter_dialog.FilterDialog, "populate_list_widgets", lambda self: None)
    monkeypatch.setattr(filter_dialog.FilterDialog, "_confirm_discard", lambda *_args, **_kwargs: True)
    widgets = filter_dialog.QtWidgets
    monkeypatch.setattr(widgets.QInputDialog, "getText", lambda *_args: (" Daily ", True))
    monkeypatch.setattr(widgets.QMenu, "exec", lambda menu, _pos: menu.actions()[0].trigger())

    owner = build_export_dialog(monkeypatch, tmp_path, db_file=str(database))
    try:
        owner.open_filter_window()
        editor = owner.filter_window
        editor.typed_mode_button.click()
        editor.expression_input.setText('rEf IN ("001")')
        assert not editor.apply_button.isEnabled()
        editor._show_saved_filters()
        store = ReportFilterPresets()
        assert store.load_typed()[0][0][0] == "Daily"
        saved_bytes = store.path.read_bytes()
        monkeypatch.setattr(widgets.QInputDialog, "getText", lambda *_args: (" dAILY ", True))
        monkeypatch.setattr(widgets.QMessageBox, "question", lambda *_args: widgets.QMessageBox.StandardButton.No)
        editor.expression_input.setText('Ref = "1"')
        editor._show_saved_filters()
        assert store.path.read_bytes() == saved_bytes
        assert owner._typed_report_scope is None
    finally:
        owner.close()

    def load_restarted(menu, _position):
        next(action for action in menu.actions() if action.text() == "Load typed as draft: Daily").trigger()

    monkeypatch.setattr(widgets.QMenu, "exec", load_restarted)
    results = []
    monkeypatch.setattr(filter_dialog.FilterDialog, "_show_typed_preview", lambda self, result: results.append(result))
    current_database = tmp_path / "current.sqlite"
    ensure_report_schema(str(current_database))
    current_repository = ReportRepository(str(current_database))
    _persist_report(current_repository, tmp_path, number=1, reference="1")
    _persist_report(current_repository, tmp_path, number=2, reference="001")
    owner = build_export_dialog(monkeypatch, tmp_path, db_file=str(current_database))
    owner.excel_file = tmp_path / "typed.xlsx"
    try:
        # The preset remains a typed draft on a currently unsupported target.
        owner.generate_html_dashboard_checkbox.setChecked(True)
        owner.open_filter_window()
        editor = owner.filter_window
        editor._show_saved_filters()
        assert editor.typed_mode_button.isChecked() and editor.typed_mode_button.isEnabled()
        assert not editor.typed_preview_button.isEnabled() and not editor.apply_button.isEnabled()
        assert "Main plots" in editor.filter_summary_label.text()
        owner.generate_html_dashboard_checkbox.setChecked(False)
        editor._refresh_filter_summary()
        assert editor._typed_mode() and editor._typed_preview_scope is None
        assert not editor.apply_filters() and owner._typed_report_scope is None
        editor.typed_preview_button.click()
        for _ in range(200):
            if results:
                break
            QTest.qWait(10)
        assert results and [(row[0], row[1]) for row in results[0].rows] == [(2, "001")]

        # Loading the identical preset again still invalidates the prior preview.
        editor._show_saved_filters()
        assert not editor.apply_filters()
        editor.typed_preview_button.click()
        for _ in range(200):
            if len(results) == 2:
                break
            QTest.qWait(10)
        assert len(results) == 2
        assert editor.apply_filters()
        assert owner._build_export_request().typed_report_scope is editor._typed_preview_scope
    finally:
        owner.close()


@pytest.mark.parametrize("supports_typed", [False, True])
def test_typed_preset_cannot_load_as_magic_or_clamp_a_date(monkeypatch, supports_typed):
    from metroliza.shared.filter_state import FilterState

    _app()
    parent = QDialog()
    if supports_typed:
        parent.typed_report_filter_blocker = lambda: ""
    dialog = _build_dialog(monkeypatch, parent=parent)
    messages = []
    monkeypatch.setattr(dialog, "_show_unavailable_filter", messages.append)
    try:
        dialog.date_from_calendar.setMinimumDate(QDate(2020, 1, 1))
        original = dialog._draft_snapshot()
        dialog._load_saved_filter(
            FilterState(date_from="2010-01-01", date_to="2024-01-01", expression_text='Ref IN ("001")'),
            typed=True,
        )
        assert dialog._draft_snapshot() == original
        assert ("saved From date" if supports_typed else "cannot load a typed Reports draft") in messages[0]
    finally:
        dialog.close()
        parent.close()


def test_typed_preset_repair_requires_an_explicit_edit_before_opening_draft(monkeypatch):
    from metroliza.shared.filter_state import FilterState

    initial = FilterState(expression_text='OldAlias IN ("001")')
    opened = []
    dialog = types.SimpleNamespace(_load_saved_filter=lambda state, **kwargs: opened.append((state, kwargs)))
    selected = iter(((initial.expression_text, True), ('Ref IN ("001")', False), ('Ref IN ("001")', True)))
    monkeypatch.setattr(filter_dialog.QtWidgets.QInputDialog, "getMultiLineText", lambda *_args: next(selected))
    for _ in range(3):
        filter_dialog.FilterDialog._edit_typed_preset_expression(dialog, initial)
    assert len(opened) == 1
    fixed, options = opened[0]
    assert fixed.expression_text == 'Ref IN ("001")' and options == {"typed": True}


def test_typed_preset_save_preserves_previous_file_when_another_writer_holds_lock(tmp_path):
    from PyQt6.QtCore import QLockFile

    from metroliza.shared.filter_state import FilterState
    from metroliza.ui.report_filter_presets import ReportFilterPresets

    store = ReportFilterPresets(tmp_path / "reports.ini")
    original = FilterState(expression_text='Ref IN ("001")')
    store.save_typed("Daily", original)
    prior = store.path.read_bytes()
    lock = QLockFile(f"{store.path}.typed-write.lock")
    assert lock.tryLock(0)
    try:
        with pytest.raises(OSError, match="Another window"):
            store.save_typed("DAILY", FilterState(expression_text='Ref IN ("1")'),
                             expected_record=store.typed_record("DAILY"))
    finally:
        lock.unlock()
    assert store.path.read_bytes() == prior


def test_typed_preset_rejects_replacement_if_record_changes_during_consent(monkeypatch, tmp_path):
    from metroliza.shared.filter_state import FilterState
    from metroliza.ui.report_filter_presets import ReportFilterPresets

    _app()
    parent = QDialog()
    parent.typed_report_filter_blocker = lambda: ""
    dialog = _build_dialog(monkeypatch, parent=parent)
    store = ReportFilterPresets(tmp_path / "reports.ini")
    opened = FilterState(expression_text='Ref = "001"')
    newer = FilterState(expression_text='Ref = "newer"')
    store.save_typed("Daily", opened)
    widgets = filter_dialog.QtWidgets
    monkeypatch.setattr(widgets.QInputDialog, "getText", lambda *_args: ("DAILY", True))

    def replace_during_prompt(*_args):
        writer = ReportFilterPresets(store.path)
        writer.save_typed("Daily", newer, expected_record=writer.typed_record("Daily"))
        return widgets.QMessageBox.StandardButton.Yes

    monkeypatch.setattr(widgets.QMessageBox, "question", replace_during_prompt)
    errors = []
    monkeypatch.setattr(dialog, "_show_unavailable_filter", lambda reason, **_: errors.append(reason))
    try:
        dialog.typed_mode_button.setChecked(True)
        dialog.expression_input.setText('Ref = "my draft"')
        dialog._save_filter_draft(store)
        assert store.load_typed() == ([("Daily", newer)], [])
        assert errors and "changed" in errors[0]
        monkeypatch.setattr(widgets.QMessageBox, "question", lambda *_args: widgets.QMessageBox.StandardButton.Yes)
        dialog._save_filter_draft(store)
        assert store.load_typed() == ([("DAILY", dialog._current_filter_state())], [])
    finally:
        dialog.close()
        parent.close()


@pytest.mark.parametrize(("field", "changed"), [("header_values", []), ("has_nok_only", False)])
def test_typed_preset_detects_drift_outside_the_expression(tmp_path, field, changed):
    import json

    from metroliza.shared.filter_state import FilterState
    from metroliza.ui.report_filter_presets import ReportFilterPresets

    store = ReportFilterPresets(tmp_path / "reports.ini")
    state = FilterState(header_values=("WIDTH",), has_nok_only=True, expression_text='Ref = "001"')
    store.save_typed("Daily", state)
    settings = store._settings(typed=True)
    key = store._key("Daily")
    payload = json.loads(settings.value(key, "", type=str))
    payload["filter"][field] = changed
    settings.setValue(key, json.dumps(payload))
    settings.sync()
    before = store.path.read_bytes()
    available, unavailable = store.load_typed()
    assert not available
    assert "integrity" in dict(unavailable)["Daily"]
    assert store.load_typed_repair_draft("Daily") is None
    assert store.path.read_bytes() == before


def test_loading_a_typed_preset_cannot_truncate_a_valid_prefix(monkeypatch):
    from metroliza.shared.filter_state import FilterState

    _app()
    parent = QDialog()
    parent.typed_report_filter_blocker = lambda: ""
    dialog = _build_dialog(monkeypatch, parent=parent)
    original = dialog._draft_snapshot()
    errors = []
    monkeypatch.setattr(dialog, "_show_unavailable_filter", errors.append)
    try:
        dialog.expression_input.setMaxLength(len('Ref = "001"'))
        dialog._load_saved_filter(FilterState(expression_text='Ref = "001" AND Status = OK'), typed=True)
        assert dialog._draft_snapshot() == original
        assert errors and "too long" in errors[0]
    finally:
        dialog.close()
        parent.close()


def test_preset_expression_length_is_bounded_in_utf16_before_publication(tmp_path):
    from metroliza.shared.filter_state import FilterState
    from metroliza.ui.report_filter_presets import ReportFilterPresets

    store = ReportFilterPresets(tmp_path / "reports.ini")
    store.save_typed("Daily", FilterState(expression_text='Ref = "001"'))
    prior = store.path.read_bytes()
    text = 'Ref = "' + "😀" * 16384 + '"'
    assert len(text) < 32767
    with pytest.raises(ValueError, match="too long"):
        store.save_typed("Daily", FilterState(expression_text=text), expected_record=store.typed_record("Daily"))
    assert store.path.read_bytes() == prior


def test_typed_preset_menu_keeps_repeated_spaces_in_distinct_names():
    from metroliza.shared.filter_state import FilterState

    _app()
    menu = filter_dialog.QtWidgets.QMenu()
    dialog = types.SimpleNamespace(_values_loading=False)
    state = FilterState(expression_text='Ref = "001"')
    filter_dialog.FilterDialog._add_saved_filter_actions(
        dialog, menu, [("Daily Report", state), ("Daily  Report", state)], [], typed_store=object(),
    )
    assert [action.text() for action in menu.actions()] == [
        "Load typed as draft: Daily Report", "Load typed as draft: Daily  Report",
    ]


def test_report_nok_and_measurement_nok_produce_different_preview_and_export(monkeypatch, tmp_path):
    from contextlib import closing
    import sqlite3

    from openpyxl import load_workbook
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest
    from metroliza.exporting.export_data_thread import ExportDataThread
    from metroliza.reports.report_query_service import build_grouping_scope_query_from_filter_state
    from metroliza.shared.filter_state import summarize_filter_state
    from tests.test_1089_acceptance_analytics import _fixture_db

    class FilterOwner(QDialog):
        def set_filter_query(self, value):
            self.query = value

        def set_filter_state(self, value):
            self.state = value

    database = _fixture_db(tmp_path)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE report_measurements SET header = 'WIDTH', status_code = 'nok', "
                           "is_nok = 1, outtol = 0.5 WHERE report_id = 1")
        connection.execute("UPDATE parsed_reports SET has_nok = 1, nok_count = 1, measurement_count = 2 WHERE id = 1")
        connection.execute("""INSERT INTO report_measurements
            (report_id, page_number, row_order, header, ax, nominal, tol_plus, tol_minus,
             meas, dev, outtol, status_code)
            VALUES (1, 1, 2, 'HEIGHT', 'X', 10, 0.5, -0.5, 10.1, 0.1, 0, 'ok')""")

    _app()
    owner = FilterOwner()
    dialog = _build_dialog(monkeypatch, parent=owner, db_file=str(database))
    try:
        _select_list_value(dialog.header_list, "HEIGHT")
        dialog.has_nok_button.setChecked(True)
        dialog.apply_filters()
        assert summarize_filter_state(owner.state)[0].endswith("Reports with at least one NOK")
        assert owner.state.status_code_values == () and owner.state.has_nok_only
        output = tmp_path / "report-nok.xlsx"
        for only_measurements in (False, True):
            if only_measurements:
                dialog.has_nok_button.setChecked(False)
                dialog.measurement_nok_button.setChecked(True)
                dialog.apply_filters()
                assert summarize_filter_state(owner.state)[0].endswith("Only NOK measurements")
                assert owner.state.status_code_values == ("nok",) and not owner.state.has_nok_only
                output = tmp_path / "measurement-nok.xlsx"

            with closing(sqlite3.connect(database)) as connection:
                report_preview = connection.execute(build_grouping_scope_query_from_filter_state(owner.state)).fetchall()
            assert len(report_preview) == (0 if only_measurements else 1)
            worker = ExportDataThread(ExportRequest(
                paths=AppPaths(db_file=str(database), excel_file=str(output)),
                options=ExportOptions(), filter_query=owner.query,
            ))
            worker.run()
            workbook = load_workbook(output, read_only=True)
            try:
                columns, *measurements = workbook["MEASUREMENTS"].values
                if only_measurements:
                    assert measurements == []
                else:
                    assert len(measurements) == 1
                    assert measurements[0][columns.index("HEADER")] == "HEIGHT"
                    assert measurements[0][columns.index("STATUS_CODE")] == "ok"
            finally:
                workbook.close()
    finally:
        dialog.close()
        owner.close()


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
            preserve_selection_during_filter=lambda list_widget, search_text, **kwargs: calls.update(
                {"list_widget": list_widget, "search_text": search_text, **kwargs}
            )
        )
        dialog.search_list_widgets(dialog.header_list, "h2")

        assert calls == {"list_widget": dialog.header_list, "search_text": "h2", "visibility_only": True}
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

@pytest.mark.parametrize("reset", [False, True])
@pytest.mark.parametrize("scoped", [False, True])
def test_reopen_keeps_original_choices_and_allows_switch(applied_choices_db, reset, scoped):
    from contextlib import closing
    import sqlite3

    from metroliza.ui.filter_values_loader import _RUNNING_LOADERS

    _app()
    parent = QDialog()
    if scoped:
        with closing(sqlite3.connect(applied_choices_db)) as writer, writer:
            writer.execute("INSERT INTO report_measurements(report_id,row_order,header,ax,status_code) VALUES (1,3,'Other','Z','ok')")
        scope = filter_dialog.build_measurement_filter_query(ax_values=["X", "Y"])
        parent.get_filter_query = lambda: scope
    dialog = filter_dialog.FilterDialog(parent, db_file=applied_choices_db)
    try:
        dialog.show()
        _wait_for_filter(lambda: not dialog._values_loading)
        dialog.ax_list.findItems("X", Qt.MatchFlag.MatchExactly)[0].setSelected(True)
        dialog.apply_filters()
        assert _selected_ax_rows(applied_choices_db, dialog.filter_query) == ["X"]
        dialog.show()
        _wait_for_filter(lambda: not dialog._values_loading)
        assert [dialog.ax_list.item(i).text() for i in range(dialog.ax_list.count())] == ["SELECT ALL", "X", "Y"]
        if reset:
            dialog._reset_draft()
        else:
            dialog.ax_list.clearSelection()
        dialog.ax_list.findItems("Y", Qt.MatchFlag.MatchExactly)[0].setSelected(True)
        dialog.apply_filters()
        assert _selected_ax_rows(applied_choices_db, dialog.filter_query) == ["Y"]
        dialog.show()
        _wait_for_filter(lambda: not dialog._values_loading)
        assert dialog.ax_list.findItems("X", Qt.MatchFlag.MatchExactly)
    finally:
        dialog._confirm_discard = lambda **_kwargs: True
        dialog.close()
        parent.close()
        _wait_for_filter(lambda: not _RUNNING_LOADERS)


@pytest.fixture
def date_preset_dialog(monkeypatch):
    class FrozenDate(QDate):
        today = QDate(2026, 3, 1)

        @staticmethod
        def currentDate():
            return FrozenDate.today

    monkeypatch.setattr(filter_dialog, "QDate", FrozenDate)
    dialog = _build_dialog(monkeypatch)
    monkeypatch.setattr(dialog, "_confirm_discard", lambda **kwargs: True)
    yield dialog, FrozenDate
    dialog.reject()
    dialog.deleteLater()
    _app().processEvents()


def _date_pair(dialog):
    return tuple(widget.date().toString("yyyy-MM-dd") for widget in (
        dialog.date_from_calendar, dialog.date_to_calendar,
    ))


@pytest.mark.parametrize("preset, expected", [
    ("All dates", ("1970-01-01", "2026-03-01")),
    ("Today", ("2026-03-01", "2026-03-01")),
    ("Yesterday", ("2026-02-28", "2026-02-28")),
    ("Last 7 days", ("2026-02-23", "2026-03-01")),
    ("This month", ("2026-03-01", "2026-03-01")),
    ("Custom", ("1970-01-01", "2026-03-01")),
])
def test_date_presets_fill_inclusive_ranges_and_summary(date_preset_dialog, preset, expected):
    dialog, _clock = date_preset_dialog
    dialog.date_range_selector.setCurrentText(preset)
    assert _date_pair(dialog) == expected
    active = preset != "All dates"
    assert dialog._has_active_draft() == active
    assert dialog._has_custom_date_range() == active
    assert dialog._is_dirty() == active
    assert dialog.date_from_calendar.isEnabled() == active
    assert dialog.date_to_calendar.isEnabled() == active
    assert dialog.select_beginning_button.isEnabled() == active
    assert dialog.select_today_button.isEnabled() == active
    assert preset in dialog.filter_summary_label.text()
    assert dialog.apply_button.isEnabled()
    if active:
        assert all(day in dialog.filter_summary_label.text() for day in expected)
    assert dialog.apply_filters() is True
    assert dialog.filter_query == filter_dialog.build_measurement_filter_query(
        date_from=expected[0] if active else None, date_to=expected[1] if active else None,
    )
    assert not dialog._is_dirty()


def test_all_dates_default_and_return_include_undated_and_outside_calendar(date_preset_dialog):
    dialog, _clock = date_preset_dialog
    assert dialog.date_range_selector.currentText() == "All dates"
    assert "All dates" in dialog.filter_summary_label.text()
    assert not dialog._is_dirty()
    original = dialog._draft_snapshot()
    dialog.date_range_selector.setCurrentText("Yesterday")
    dialog.date_range_selector.setCurrentText("All dates")
    assert dialog._draft_snapshot() == original
    assert dialog.apply_filters() is True
    from contextlib import closing
    import sqlite3
    with closing(sqlite3.connect(":memory:")) as connection:
        from metroliza.reports.report_schema import ensure_report_schema
        ensure_report_schema(":memory:", connection=connection)
        connection.execute("CREATE TEMP TABLE vw_measurement_export AS SELECT * FROM main.vw_measurement_export LIMIT 0")
        dates = [(None,), ("1969-01-01",), ("2099-01-01",)]
        connection.executemany("INSERT INTO vw_measurement_export(report_date) VALUES (?)", dates)
        assert connection.execute(f"SELECT DATE FROM ({dialog.filter_query}) ORDER BY DATE").fetchall() == dates


@pytest.mark.parametrize("field", ["date_from_calendar", "date_to_calendar"])
def test_manual_date_change_selects_custom(date_preset_dialog, field):
    dialog, _clock = date_preset_dialog
    dialog.date_range_selector.setCurrentText("Last 7 days")
    getattr(dialog, field).setDate(QDate(2026, 2, 27))
    assert dialog.date_range_selector.currentText() == "Custom"
    assert "Custom" in dialog.filter_summary_label.text()
    assert dialog._is_dirty()


@pytest.mark.parametrize("path", ["button", "enter", "accept", "apply", "builder"])
def test_preset_custom_invalid_dates_keep_wave0_guard(date_preset_dialog, path):
    dialog, _clock = date_preset_dialog
    dialog.date_range_selector.setCurrentText("Today")
    dialog.date_from_calendar.setDate(QDate(2026, 3, 2))
    assert dialog.date_range_selector.currentText() == "Custom"
    assert not dialog.apply_button.isEnabled()
    query = dialog.filter_query
    if path == "builder":
        with pytest.raises(ValueError, match="From"):
            filter_dialog.build_measurement_filter_query(
                date_from="2026-03-02", date_to="2026-03-01",
            )
    elif path == "button":
        dialog.apply_button.click()
    elif path == "enter":
        dialog.show()
        _app().processEvents()
        dialog.date_from_calendar.setFocus()
        QTest.keyClick(dialog.date_from_calendar, Qt.Key.Key_Return)
    else:
        getattr(dialog, "accept" if path == "accept" else "apply_filters")()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.filter_query == query
    assert _date_pair(dialog) == ("2026-03-02", "2026-03-01")
    assert "Invalid date range" in dialog.filter_summary_label.text()


@pytest.mark.parametrize("preset", ["All dates", "Today", "Yesterday", "Last 7 days", "This month", "Custom"])
def test_cancel_reopens_committed_preset_and_dates(date_preset_dialog, preset):
    dialog, _clock = date_preset_dialog
    dialog.date_range_selector.setCurrentText(preset)
    committed_dates = _date_pair(dialog)
    dialog.apply_filters()
    committed_query = dialog.filter_query
    dialog.show()
    dialog.date_range_selector.setCurrentText("Yesterday" if preset != "Yesterday" else "Today")
    dialog.reject()
    dialog.show()
    _app().processEvents()
    assert dialog.date_range_selector.currentText() == preset
    assert _date_pair(dialog) == committed_dates
    assert dialog.filter_query == committed_query
    assert not dialog._is_dirty()


@pytest.mark.parametrize("preset", ["Today", "Yesterday", "Last 7 days", "This month"])
def test_reopen_after_day_change_keeps_committed_dates_as_custom(date_preset_dialog, preset):
    dialog, clock = date_preset_dialog
    dialog.date_range_selector.setCurrentText(preset)
    dialog.apply_filters()
    dates, query = _date_pair(dialog), dialog.filter_query
    clock.today = QDate(2026, 3, 2)
    dialog.show()
    _app().processEvents()
    assert _date_pair(dialog) == dates
    assert dialog.filter_query == query
    assert dialog.date_range_selector.currentText() == "Custom"
    assert not dialog._is_dirty()
    dialog.date_range_selector.setCurrentText("Yesterday")
    dialog.reject()
    assert dialog.date_range_selector.currentText() == "Custom"
    assert _date_pair(dialog) == dates
    assert not dialog._is_dirty()


def test_preset_keyboard_selection_and_tab_order(date_preset_dialog):
    dialog, _clock = date_preset_dialog
    dialog.show()
    _app().processEvents()
    selector = dialog.date_range_selector
    assert selector.accessibleName() == "Date range"
    selector.setFocus()
    QTest.keyClick(selector, Qt.Key.Key_Down)
    assert selector.currentText() == "Today"
    assert _date_pair(dialog) == ("2026-03-01", "2026-03-01")
    QTest.keyClick(selector, Qt.Key.Key_Tab)
    assert dialog.date_from_calendar.hasFocus()
    # QDateEdit traverses its date sections before handing focus to To.
    for _ in range(3):
        QTest.keyClick(dialog.date_from_calendar, Qt.Key.Key_Tab)
        if dialog.date_to_calendar.hasFocus():
            break
        assert dialog.date_from_calendar.hasFocus()
    assert dialog.date_to_calendar.hasFocus()


def test_reset_restores_all_dates_and_helpers_keep_endpoints(date_preset_dialog):
    dialog, _clock = date_preset_dialog
    dialog.date_range_selector.setCurrentText("Yesterday")
    dialog.select_beginning_of_time()
    dialog.select_today_as_date_to()
    assert _date_pair(dialog) == ("1970-01-01", "2026-03-01")
    dialog._reset_draft()
    assert dialog.date_range_selector.currentText() == "All dates"
    assert not dialog._has_active_draft()
    assert not dialog._is_dirty()


@pytest.mark.parametrize("today, preset, expected", [
    ((2026, 1, 1), "Yesterday", ("2025-12-31", "2025-12-31")),
    ((2026, 1, 1), "Last 7 days", ("2025-12-26", "2026-01-01")),
    ((2024, 3, 1), "Yesterday", ("2024-02-29", "2024-02-29")),
    ((2024, 2, 29), "This month", ("2024-02-01", "2024-02-29")),
])
def test_date_presets_calendar_boundaries(date_preset_dialog, today, preset, expected):
    # Plain tuples: QDate is None at collection time when PyQt6 is unavailable.
    dialog, clock = date_preset_dialog
    clock.today = QDate(*today)
    dialog.date_range_selector.setCurrentText(preset)
    assert _date_pair(dialog) == expected
    assert dialog.apply_button.isEnabled()


def test_cancel_after_midnight_restores_other_conditions_and_concrete_dates(date_preset_dialog):
    dialog, clock = date_preset_dialog
    dialog.date_range_selector.setCurrentText("Today")
    dialog.expression_input.setText("Reference=REF1")
    dialog.has_nok_button.setChecked(True)
    dialog.apply_filters()
    dialog.show()
    dialog.expression_input.clear()
    dialog.has_nok_button.setChecked(False)
    dialog.date_range_selector.setCurrentText("Yesterday")
    clock.today = QDate(2026, 3, 2)
    dialog.reject()
    assert dialog.expression_input.text() == "Reference=REF1"
    assert dialog.has_nok_button.isChecked()
    assert dialog.date_range_selector.currentText() == "Custom"
    assert _date_pair(dialog) == ("2026-03-01", "2026-03-01")
    assert not dialog._is_dirty()


@pytest.mark.parametrize("reopen", [False, True])
@pytest.mark.parametrize("action", ["apply_filters", "accept"])
def test_all_dates_refresh_after_midnight(date_preset_dialog, reopen, action):
    dialog, clock = date_preset_dialog
    assert dialog.apply_filters() is True
    dialog.show()
    _app().processEvents()
    changes = []
    dialog.date_from_calendar.dateChanged.connect(lambda date: changes.append(date))
    dialog.date_to_calendar.dateChanged.connect(lambda date: changes.append(date))
    if reopen:
        dialog.reject()
    clock.today = QDate(2026, 3, 2)
    if reopen:
        dialog.show()
        _app().processEvents()
        assert _date_pair(dialog) == ("1970-01-01", "2026-03-02")
        assert not dialog._is_dirty()
    getattr(dialog, action)()
    assert _date_pair(dialog) == ("1970-01-01", "2026-03-02")
    assert dialog.filter_query == filter_dialog.build_measurement_filter_query()
    assert changes == []
    assert dialog.date_range_selector.currentText() == "All dates"
    assert dialog.filter_summary_label.text() == "No active filters | All dates"
    assert not dialog._has_active_draft()
    assert not dialog._has_custom_date_range()
    assert not dialog._is_dirty()


def test_all_dates_midnight_refresh_preserves_other_dirty_conditions(date_preset_dialog):
    dialog, clock = date_preset_dialog
    assert dialog.apply_filters() is True
    dialog.expression_input.setText("Reference=REF1")
    clock.today = QDate(2026, 3, 2)
    dialog.show()
    assert _date_pair(dialog) == ("1970-01-01", "2026-03-02")
    assert dialog.expression_input.text() == "Reference=REF1"
    assert dialog._is_dirty()
    dialog.reject()
    assert dialog.date_range_selector.currentText() == "All dates"
    assert _date_pair(dialog) == ("1970-01-01", "2026-03-02")
    assert dialog.expression_input.text() == ""
    assert not dialog._is_dirty()


@pytest.mark.parametrize("preset", ["Today", "Yesterday", "Last 7 days", "This month"])
def test_relative_presets_become_custom_on_apply_after_midnight(date_preset_dialog, preset):
    dialog, clock = date_preset_dialog
    dialog.date_range_selector.setCurrentText(preset)
    assert dialog.apply_filters() is True
    dates, query = _date_pair(dialog), dialog.filter_query
    dialog.show()
    _app().processEvents()
    clock.today = QDate(2026, 3, 2)
    assert dialog.apply_filters() is True
    assert dialog.date_range_selector.currentText() == "Custom"
    assert _date_pair(dialog) == dates
    assert dialog.filter_query == query
    assert "Custom" in dialog.filter_summary_label.text()
    assert not dialog._is_dirty()
