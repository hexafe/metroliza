"""Filter presentation preserves the selected source rows and guarded draft state."""

from contextlib import closing
import sqlite3

import pandas as pd
import pytest
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit, QVBoxLayout

from metroliza.tabular.tabular_analytics_service import TabularColumnFilter, apply_tabular_row_filter
from metroliza.ui.filter_dialog import FilterDialog
from metroliza.ui.tabular_analytics_filter_dialog import TabularAnalyticsFilterDialog
from tests.qt_key_input import press_key
from tests.qt_geometry_diagnostics import geometry_snapshot
from tests.test_report_planner_integration import wait_until
from tests.test_wave0_filters_groups import scoped_header_dialog as scoped_header_dialog, wait_for_choices


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


def key(app, widget, sequence):
    press_key(app, widget, sequence)


def source_ids(dialog):
    with closing(sqlite3.connect(dialog.db_file)) as connection:
        return {row[0] for row in connection.execute(f"SELECT measurement_id FROM ({dialog.filter_query})")}


def test_report_search_and_clear_controls_preserve_explicit_scope(scoped_header_dialog, app):
    editor = scoped_header_dialog
    with closing(sqlite3.connect(editor.db_file)) as connection, connection:
        connection.executescript("""
            INSERT INTO source_files(id,sha256,source_format,discovered_at) VALUES(3,'synthetic-later','pdf','2026');
            INSERT INTO parsed_reports(id,source_file_id,parser_id,template_family,parse_status,created_at,updated_at)
            VALUES(3,3,'synthetic','synthetic','parsed','2026','2026');
            INSERT INTO report_metadata(report_id,reference,report_date,metadata_version) VALUES(3,'LATER','2025-02-01','v1');
            INSERT INTO report_measurements(report_id,row_order,header,status_code,is_nok) VALUES(3,1,'Later','nok',1);
        """)
    editor.reference_list.findItems("REF-NOK", Qt.MatchFlag.MatchExactly)[0].setSelected(True)
    wait_for_choices(editor)
    editor.date_range_selector.setCurrentText("Custom")
    editor.date_from_calendar.setDate(QDate(2024, 2, 1))
    editor.date_to_calendar.setDate(QDate(2024, 2, 1))
    editor.expression_input.setText("Status=NOK")
    assert "Draft edited" in editor.draft_status_label.text()
    assert editor.apply_filters() is True and source_ids(editor) == {2, 3}
    before = editor._draft_snapshot()
    editor.show()
    wait_for_choices(editor)
    editor.reference_search_input.setText("REF-OK")
    summary = editor._choice_status_labels[editor.reference_list].text()
    assert "Selected (1)" in summary and "1 hidden selected" in summary
    assert editor._draft_snapshot() == before and not editor._is_dirty()
    editor.clear_search_button.click()
    assert editor._draft_snapshot() == before
    assert editor.apply_filters() is True and source_ids(editor) == {2, 3}
    editor.show()
    wait_for_choices(editor)
    editor.clear_values_button.click()
    assert "Values: All" in editor._choice_status_labels[editor.reference_list].text()
    assert editor.expression_input.text() == "Status=NOK"
    assert editor.date_from_calendar.date() == editor.date_to_calendar.date() == QDate(2024, 2, 1)
    assert editor.apply_filters() is True and source_ids(editor) == {2, 3}
    editor.show()
    wait_for_choices(editor)
    editor.clear_expression_button.click()
    assert editor.apply_filters() is True and source_ids(editor) == {1, 2, 3}
    editor._request_reset_draft()
    assert editor.apply_filters() is True and source_ids(editor) == {1, 2, 3, 4}


def make_csv():
    frame = pd.DataFrame({"source_key": [11, 22, 33, 44], "part": ["A", "B", "A", "C"],
                          "time_stamp": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
                          "value": [1, 2, 3, 4]})
    editor = TabularAnalyticsFilterDialog(dataframe=frame, column_filters=(
        TabularColumnFilter("part", selected_values=("A",)),
        TabularColumnFilter("time_stamp", date_mode="between", date_from="2024-01-01", date_to="2024-01-03"),
    ), filter_expression="value >= 2")
    editor._confirm_discard = lambda **_kwargs: True
    return editor, frame


def current_column(editor, column):
    for row in range(editor.selected_columns_list.count()):
        item = editor.selected_columns_list.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == column:
            editor.selected_columns_list.setCurrentItem(item)
            return
    raise AssertionError(column)


def csv_ids(editor, frame):
    filtered = apply_tabular_row_filter(frame, column_filters=editor.get_column_filters(),
                                        row_filter_expression=editor.get_filter_expression()).dataframe
    return set(filtered["source_key"])


def test_csv_hidden_values_dates_clear_and_cancel_keep_source_ids(app):
    editor, frame = make_csv()
    editor.show()
    try:
        current_column(editor, "part")
        assert csv_ids(editor, frame) == {33}
        before = editor._draft_signature()
        editor.matching_search.setText("B")
        assert "Selected (1)" in editor.value_scope_label.text()
        assert "1 hidden selected" in editor.value_scope_label.text()
        editor.selected_column_search.setText("no column matches")
        assert not editor.remove_column_button.isEnabled()
        editor.remove_selected_filter_column()
        assert editor.filter_columns == ["part", "time_stamp"]
        editor.clear_search_button.click()
        current_column(editor, "part")
        assert editor._draft_signature() == before and csv_ids(editor, frame) == {33}
        editor.clear_values_only_button.click()
        assert csv_ids(editor, frame) == {22, 33}
        assert editor.date_filters["time_stamp"]["mode"] == "between"
        current_column(editor, "time_stamp")
        editor.clear_selection_button.click()  # explicitly named values + dates
        assert csv_ids(editor, frame) == {22, 33, 44}
        editor.clear_expression_button.click()
        assert csv_ids(editor, frame) == {11, 22, 33, 44}
        assert "Draft edited" in editor.draft_status_label.text()
        assert "Applied:" in editor.draft_status_label.text() and "2024-01-03" in editor.draft_status_label.text()
        key(app, editor.expression_input, "Ctrl+W")
        assert not editor.isVisible()
        assert editor.result() == QDialog.DialogCode.Rejected
        assert csv_ids(editor, frame) == {33}
    finally:
        editor.close()


def test_csv_invalid_date_and_expression_block_actual_apply(app):
    editor, _frame = make_csv()
    editor.show()
    try:
        current_column(editor, "time_stamp")
        editor.date_from_calendar.setDate(QDate(2024, 1, 4))
        editor.date_to_calendar.setDate(QDate(2024, 1, 1))
        editor._flush_pending_status_update()
        assert not editor.apply_button.isEnabled()
        assert "Invalid date range" in editor.date_error_label.text()
        key(app, editor.expression_input, "Ctrl+S")
        assert editor.isVisible() and editor.result() != QDialog.DialogCode.Accepted
        editor.date_from_calendar.setDate(QDate(2024, 1, 1))
        editor.date_to_calendar.setDate(QDate(2024, 1, 3))
        editor.expression_input.setText("value >=")
        editor._flush_pending_status_update()
        assert not editor.apply_button.isEnabled() and editor.expression_error_label.isVisible()
        editor.expression_input.setText("value >= 2")
        editor._flush_pending_status_update()
        key(app, editor.expression_input, "Ctrl+S")
        assert editor.result() == QDialog.DialogCode.Accepted
    finally:
        editor.close()


def test_csv_command_keys_are_focus_scoped_exact_and_guarded(app):
    editor = TabularAnalyticsFilterDialog(dataframe=pd.DataFrame({"part": ["A", "B"], "value": [1, 2]}))
    editor._confirm_discard = lambda **_kwargs: True
    editor.show()
    try:
        key(app, editor.column_search, "E")
        assert editor.column_search.text() == "e" and editor.filter_columns == []
        editor.column_search.clear()
        key(app, editor.column_list, "E")
        assert len(editor.filter_columns) == 1
        column = editor.filter_columns[0]
        repeated = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_R, Qt.KeyboardModifier.NoModifier, "r", True, 2)
        editor.selected_columns_list.setFocus()
        QApplication.sendEvent(editor.selected_columns_list, repeated)
        assert editor.filter_columns == [column]
        key(app, editor.selected_column_search, "Ctrl+A")
        QTest.keyClicks(editor.selected_column_search, "safe")
        assert editor.selected_column_search.text() == "safe"
        editor.selected_column_search.clear()
        assert editor._current_filter_column() is None
        key(app, editor.selected_columns_list, "R")
        assert editor.filter_columns == [column]  # search did not implicitly choose a removal target
        current_column(editor, column)
        key(app, editor.selected_columns_list, "R")
        assert editor.filter_columns == []
        child = QDialog(editor)
        child.setModal(True)
        layout = QVBoxLayout(child)
        text = QLineEdit()
        layout.addWidget(text)
        child.show()
        try:
            key(app, text, "Ctrl+E")
            assert editor.filter_columns == []
            editor.filter_commands.actions["Ctrl+E"].trigger()
            assert editor.filter_columns == []
        finally:
            child.close()
        editor.activateWindow()
        app.processEvents()
        key(app, editor.column_list, "Ctrl+E")
        assert editor.filter_columns
        key(app, editor.expression_input, "Ctrl+Shift+R")
        assert editor.filter_columns == []
    finally:
        editor.close()


@pytest.mark.parametrize("kind", ["reports", "csv"])
def test_filter_short_screen_has_visible_primary_actions(app, monkeypatch, kind):
    from PyQt6.QtCore import QSize

    monkeypatch.setattr(FilterDialog, "populate_list_widgets", lambda self: None)
    editor = FilterDialog() if kind == "reports" else make_csv()[0]
    editor._confirm_discard = lambda **_kwargs: True
    editor.show()
    wait_until(app, lambda: editor._metroliza_window_size_config["finalized"])
    editor.resize(720, 480)
    app.processEvents()
    try:
        assert editor.size() == QSize(720, 480), (
            geometry_snapshot(editor, requested=(720, 480), pinned=('apply_button', 'cancel_button'))
            if kind == 'reports' else None
        )
        assert editor.apply_button.isVisibleTo(editor) and editor.cancel_button.isVisibleTo(editor)
        for button in (editor.apply_button, editor.cancel_button):
            point = button.mapTo(editor, button.rect().center())
            assert editor.rect().contains(point)
        import os
        configured = os.environ.get("METROLIZA_FILTER_TEST_SCREEN")
        if configured:
            assert app.primaryScreen().geometry().size() == QSize(*map(int, configured.split("x")))
            assert app.primaryScreen().devicePixelRatio() == 1
        else:
            assert app.primaryScreen().geometry().width() >= 720
            assert app.primaryScreen().devicePixelRatio() > 0
    finally:
        editor.close()


def test_actual_csv_caller_retains_groups_on_unchanged_apply_and_warns_on_real_change(app, tmp_path, monkeypatch):
    from metroliza.analytics.row_table import RowTable
    from metroliza.tabular.tabular_analytics_service import cleanup_tabular_load_result, load_tabular_analytics_file
    from metroliza.ui.industrial_analytics_dialog import IndustrialAnalyticsDialog, SOURCE_TABULAR_FILE
    from PyQt6.QtWidgets import QMessageBox

    path = tmp_path / "synthetic.csv"
    path.write_text("Part,Value\nA,1\nB,2\nC,3\n")
    loaded = load_tabular_analytics_file(path, force_sqlite=True)
    owner = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE, tabular_load_result=loaded)
    filters = (TabularColumnFilter("part", selected_values=("A", "B")),)
    owner.tabular_column_filters = filters
    groups = RowTable(((1, "One"), (2, "Two")), ("REPORT_ID", "GROUP"))
    owner.set_df_for_grouping(groups)
    owner.set_grouping_applied(True)
    mode = ["unchanged"]
    answers, prompts = [], []

    def question(*args):
        prompts.append(args[2])
        return answers.pop(0)

    def execute(editor):
        editor.show()
        wait_until(app, lambda: not editor._preview_threads)
        current_column(editor, "part")
        if mode[0] == "unchanged":
            editor.matching_search.setText("C")
            editor._apply_matching_search()
            wait_until(app, lambda: not editor._preview_threads)
            assert editor.value_filters["part"] == {"A", "B"}
        else:
            editor.value_filters["part"] = {"A"}
            editor._refresh_values()
            wait_until(app, lambda: not editor._preview_threads)
        editor._accept_filter()
        return editor.result()

    monkeypatch.setattr(QMessageBox, "question", question)
    monkeypatch.setattr(TabularAnalyticsFilterDialog, "exec", execute)
    try:
        owner.open_tabular_filter_dialog()
        assert owner.df_for_grouping is groups and owner.tabular_column_filters == filters and prompts == []
        mode[0] = "narrow"
        answers.append(QMessageBox.StandardButton.No)
        owner.open_tabular_filter_dialog()
        assert owner.df_for_grouping is groups and owner.tabular_column_filters == filters
        assert len(prompts) == 1
        answers.append(QMessageBox.StandardButton.Yes)
        owner.open_tabular_filter_dialog()
        assert len(prompts) == 2
        assert owner.tabular_column_filters == (TabularColumnFilter("part", selected_values=("A",)),)
        assert set(owner.df_for_grouping["REPORT_ID"]) == {1}
    finally:
        owner.close()
        cleanup_tabular_load_result(loaded)



def test_selected_column_search_reuses_unchanged_preview_and_date_bounds(app, monkeypatch):
    editor, _frame = make_csv()
    current_column(editor, "time_stamp")
    editor._flush_pending_status_update()
    before = editor._draft_signature()
    calls = []
    monkeypatch.setattr(editor, "_refresh_values", lambda: calls.append("value preview"))
    monkeypatch.setattr(editor, "_sync_date_controls", lambda: calls.append("date bounds"))
    try:
        for search in ("t", "ti", "time"):
            editor.selected_column_search.setText(search)
        assert calls == [] and editor._draft_signature() == before
        editor.selected_column_search.setText("part")
        assert calls == ["value preview", "date bounds"]  # clears the editor; neither reads source
        assert editor._current_filter_column() is None
        editor.selected_column_search.clear()
        assert editor._current_filter_column() is None and len(calls) == 2
        assert editor._draft_signature() == before
    finally:
        editor.close()


def test_reports_reset_refreshes_hidden_choice_labels_without_applying(scoped_header_dialog):
    editor = scoped_header_dialog
    selected = editor.status_code_list.findItems('nok', Qt.MatchFlag.MatchExactly)[0]
    selected.setSelected(True)
    assert editor.apply_filters()
    applied_query = editor.filter_query
    applied_snapshot = editor._committed_draft_snapshot
    applied_ids = source_ids(editor)
    editor.show()
    wait_for_choices(editor)
    editor.status_code_search_input.setText('ok-but-not-nok')
    label = editor._choice_status_labels[editor.status_code_list]
    assert 'Selected (1)' in label.text() and '1 hidden selected' in label.text()
    editor.reset_button.click()
    assert editor.status_code_list.selectedItems() == []
    assert 'Values: All' in label.text() and 'hidden selected' not in label.text()
    assert editor.filter_query == applied_query and source_ids(editor) == applied_ids == {2, 3}
    assert editor._committed_draft_snapshot == applied_snapshot
    editor.reject()
    assert editor._committed_draft_snapshot == applied_snapshot
    assert 'Selected (1)' in label.text() and '1 hidden selected' in label.text()


def test_reports_scope_labels_fit_initial_short_viewport(scoped_header_dialog, app, monkeypatch):
    from PyQt6.QtCore import QPoint, QRect, QSize
    from PyQt6.QtWidgets import QScrollArea
    import os
    from metroliza.ui import ui_foundation

    editor = scoped_header_dialog
    # The layout target is deterministic on ordinary CI as well as explicitly
    # declared native/offscreen screens; do not make a host resolution a fixture.
    monkeypatch.setattr(ui_foundation, "_available_window_size", lambda *_args: (760, 560))
    editor._apply_window_size_constraints()
    editor.reference_list.findItems('REF-NOK', Qt.MatchFlag.MatchExactly)[0].setSelected(True)
    wait_for_choices(editor)
    editor.reference_search_input.setText('REF-OK')
    QTest.qWait(40)  # allow the existing deferred initial-size finalizer to complete
    editor.resize(760, 560)
    app.processEvents()
    assert editor.size() == QSize(760, 560)
    screen = app.primaryScreen()
    print(f'filter-scope-screen={screen.geometry().width()}x{screen.geometry().height()} DPR={screen.devicePixelRatio()}')
    declared_screen = os.environ.get('METROLIZA_FILTER_SCOPE_SCREEN')
    if declared_screen:
        assert screen.geometry().size() == QSize(*map(int, declared_screen.split('x')))
        assert screen.devicePixelRatio() == float(os.environ['METROLIZA_FILTER_SCOPE_DPR'])
    else:
        assert screen.devicePixelRatio() > 0
    for tab_index, (_title, fields) in enumerate(editor.FILTER_SECTIONS):
        editor.filter_tabs.setCurrentIndex(tab_index)
        scroll = editor.filter_tabs.currentWidget().findChild(QScrollArea)
        scroll.verticalScrollBar().setValue(0)
        app.processEvents()
        # Headings in the first row are initially exposed; their complete scope labels must be too.
        for _heading, _search, listing in fields[:3]:
            widget = getattr(editor, listing)
            label = editor._choice_status_labels.get(widget)
            if label is None:
                continue
            visible = QRect(label.mapTo(scroll.viewport(), QPoint()), label.size())
            assert scroll.viewport().rect().contains(visible), (listing, visible, scroll.viewport().rect())
            assert label.isVisibleTo(editor)
    reference_text = editor._choice_status_labels[editor.reference_list].text()
    assert 'Selected (1)' in reference_text and '1 hidden selected' in reference_text


@pytest.mark.parametrize('storage', ['pandas', 'sqlite'])
def test_column_search_never_auto_selects_or_scans_date_source(app, tmp_path, monkeypatch, storage):
    from metroliza.tabular.tabular_analytics_service import cleanup_tabular_load_result, load_tabular_analytics_file

    frame = pd.DataFrame({'source_key': [11, 22, 33, 44], 'part': ['A', 'B', 'A', 'C'],
                          'time_stamp': ['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04']})
    filters = (TabularColumnFilter('part', selected_values=('A',)),
               TabularColumnFilter('time_stamp', date_mode='between', date_from='2024-01-01', date_to='2024-01-03'))
    loaded = None
    if storage == 'sqlite':
        path = tmp_path / 'dates.csv'
        frame.to_csv(path, index=False)
        loaded = load_tabular_analytics_file(path, force_sqlite=True)
        editor = TabularAnalyticsFilterDialog(sqlite_store=loaded.sqlite_store, column_filters=filters)
    else:
        editor = TabularAnalyticsFilterDialog(dataframe=frame, column_filters=filters)
    editor._confirm_discard = lambda **_kwargs: True
    editor.show()
    try:
        wait_until(app, lambda: not editor._preview_threads)
        current_column(editor, 'part')
        wait_until(app, lambda: not editor._preview_threads)
        editor._flush_pending_status_update()
        before = editor._draft_signature()
        bounds_calls, preview_calls, parse_calls = [], [], []
        original_bounds = editor._column_date_bounds
        original_preview = editor._start_sqlite_value_preview if storage == 'sqlite' else editor._value_index
        original_parse = pd.to_datetime

        def bounds(column):
            bounds_calls.append(column)
            return original_bounds(column)

        def preview(column):
            preview_calls.append(column)
            return original_preview(column)

        def parse(value, *args, **kwargs):
            parse_calls.append(value)
            return original_parse(value, *args, **kwargs)

        with monkeypatch.context() as checks:
            checks.setattr(editor, '_column_date_bounds', bounds)
            checks.setattr(editor, '_start_sqlite_value_preview' if storage == 'sqlite' else '_value_index', preview)
            checks.setattr(pd, 'to_datetime', parse)
            editor.selected_column_search.setText('time')
            assert editor.selected_columns_list.count() == 1
            assert editor._current_filter_column() is None
            assert editor.matching_list.count() == 0
            assert all(widget.isHidden() for widget in editor.date_filter_widgets)
            assert 'Select a column' in editor.matching_status_label.text()
            editor.selected_column_search.clear()
            assert editor.selected_columns_list.count() == 2 and editor._current_filter_column() is None
            assert bounds_calls == preview_calls == parse_calls == []
            assert editor._draft_signature() == before
            current_column(editor, 'time_stamp')  # explicit user choice retains the existing bounds contract
            wait_until(app, lambda: not editor._preview_threads)
            assert bounds_calls == ['time_stamp'] and preview_calls == ['time_stamp']
            assert editor.date_mode_combo.currentData() == 'between'
            assert editor.date_from_calendar.date() == QDate(2024, 1, 1)
            assert editor.date_to_calendar.date() == QDate(2024, 1, 3)
            assert all(not widget.isHidden() for widget in editor.date_filter_widgets)
        assert editor._draft_signature() == before
        assert editor.get_column_filters() == filters
        assert set(apply_tabular_row_filter(frame, column_filters=editor.get_column_filters()).dataframe.source_key) == {11, 33}
    finally:
        editor.close()
        if loaded is not None:
            cleanup_tabular_load_result(loaded)


def test_reports_compact_window_keeps_complete_footer_targets_and_wrapped_scope(app, monkeypatch):
    from PyQt6.QtCore import QPoint, QRect, QSize

    monkeypatch.setattr(FilterDialog, 'populate_list_widgets', lambda self: None)
    editor = FilterDialog()
    editor.show()
    wait_until(app, lambda: editor._metroliza_window_size_config['finalized'])
    editor.resize(720, 480)
    app.processEvents()
    try:
        assert editor.size() == QSize(720, 480)
        for button in (editor.apply_button, editor.cancel_button, editor.reset_button,
                       editor.select_today_button, editor.select_beginning_button, editor.has_nok_button):
            assert button.isVisibleTo(editor) and button.height() >= 36
            assert editor.rect().contains(QRect(button.mapTo(editor, QPoint()), button.size()))
            ancestor = button.parentWidget()
            while ancestor is not None:
                assert ancestor.rect().contains(QRect(button.mapTo(ancestor, QPoint()), button.size()))
                if ancestor is editor:
                    break
                ancestor = ancestor.parentWidget()
        for label in (editor.draft_status_label, editor.filter_summary_label):
            assert label.isVisibleTo(editor)
            assert label.height() >= label.heightForWidth(label.width())
            assert editor.rect().contains(QRect(label.mapTo(editor, QPoint()), label.size()))
    finally:
        editor.close()


def test_reports_compact_real_export_owner_selected_scope_fits_footer_ancestors(scoped_header_dialog, app):
    from PyQt6 import sip
    from PyQt6.QtCore import QPoint, QRect, QSize
    from metroliza.ui.export_dialog import ExportDialog
    from metroliza.ui.filter_values_loader import _RUNNING_LOADERS

    database = scoped_header_dialog.db_file
    scoped_header_dialog.close()
    wait_until(app, lambda: not _RUNNING_LOADERS)
    owner = ExportDialog(db_file=database)
    owner.show()
    editor = None
    try:
        owner.filter_button.click()  # Actual Export -> Filter constructor and real SQLite loader.
        editor = owner.filter_window
        assert isinstance(editor, FilterDialog) and editor.parentWidget() is owner
        wait_for_choices(editor)
        editor.reference_list.findItems('REF-NOK', Qt.MatchFlag.MatchExactly)[0].setSelected(True)
        wait_for_choices(editor)
        editor.header_list.findItems('Diameter-NOK', Qt.MatchFlag.MatchExactly)[0].setSelected(True)
        wait_for_choices(editor)
        editor.apply_button.click()
        assert not editor.isVisible() and source_ids(editor) == {2}
        applied = owner.filter_state
        assert applied.reference_values == ('REF-NOK',) and applied.header_values == ('Diameter-NOK',)
        owner.filter_button.click()
        assert owner.filter_window is editor
        wait_for_choices(editor)
        wait_until(app, lambda: editor._metroliza_window_size_config['finalized'])
        editor.resize(720, 480)
        app.processEvents()
        assert editor.size() == QSize(720, 480)
        for button in (editor.apply_button, editor.cancel_button, editor.reset_button,
                       editor.select_today_button, editor.select_beginning_button, editor.has_nok_button):
            assert button.isVisibleTo(editor) and button.height() >= 36
            assert editor.rect().contains(QRect(button.mapTo(editor, QPoint()), button.size()))
            ancestor = button.parentWidget()
            while ancestor is not None:
                assert ancestor.rect().contains(QRect(button.mapTo(ancestor, QPoint()), button.size()))
                if ancestor is editor:
                    break
                ancestor = ancestor.parentWidget()
        for label in (editor.draft_status_label, editor.filter_summary_label):
            assert label.isVisibleTo(editor)
            assert label.height() >= label.heightForWidth(label.width())
            assert editor.rect().contains(QRect(label.mapTo(editor, QPoint()), label.size()))
        assert owner.filter_state is applied and source_ids(editor) == {2}
        editor.cancel_button.click()
    finally:
        if editor is not None and not sip.isdeleted(editor):
            # Failure teardown must not enter a new dirty-draft confirmation.
            editor._stop_value_load()
            QDialog.reject(editor)
        owner.close()
        wait_until(app, lambda: not _RUNNING_LOADERS)
