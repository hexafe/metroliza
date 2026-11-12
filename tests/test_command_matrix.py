"""Actual keys for the integrated window/component command matrix (#1204/#946)."""
import os
from threading import Event

import pandas as pd
import pytest
from PyQt6.QtCore import QEvent, QPoint, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox

from metroliza.industrial.industrial_analytics_state import ProductionMetricSelection
from metroliza.ui import detached_threads
from metroliza.ui import industrial_analytics_dialog as analytics, export_dialog as exporting
from metroliza.ui import characteristic_mapping_dialog as mapping
from metroliza.ui.shortcuts import PRIMARY_BUTTON_COMMANDS, install_button_commands, plain_text
from tests.test_report_planner_integration import wait_until
from tests.test_report_workspace_shell import app as app, window as window  # noqa: F401
from tests.test_wave0_modifydb_mapping import _database


CONTEXTS = tuple(PRIMARY_BUTTON_COMMANDS)


def press(app, target, sequence):
    window = target.window()
    window.activateWindow()
    wait_until(app, window.isActiveWindow)
    target.setFocus()
    combination = QKeySequence(sequence)[0]
    QTest.keyClick(target, combination.key(), combination.keyboardModifiers())
    app.processEvents()


@pytest.fixture
def factory(qapplication_session, tmp_path, monkeypatch):
    from metroliza.ui.data_grouping import DataGrouping
    from metroliza.ui.modify_db import ModifyDB
    from metroliza.ui.industrial_source_profiles_dialog import IndustrialSourceProfilesDialog
    from metroliza.ui.industrial_sync_dialog import IndustrialSyncDialog, IndustrialSqlQueryDialog
    from metroliza.ui.industrial_filter_dialog import IndustrialFilterDialog
    from metroliza.ui.industrial_grouping_dialog import IndustrialGroupingDialog
    from metroliza.ui.industrial_export_dialog import IndustrialExportDialog
    from metroliza.ui.tabular_analytics_grouping_dialog import TabularAnalyticsGroupingDialog

    path, _repo, _one, _two, _ids = _database(tmp_path)
    frame = pd.DataFrame({'part': ['A', 'B'], 'value': [1., 2.]})
    metrics = (ProductionMetricSelection('value', 'Value'),)
    config = tmp_path / 'sources.yaml'
    monkeypatch.setattr(analytics, 'load_dashboard_visual_settings', lambda: {'preset': 'auto'})
    monkeypatch.setattr(exporting, 'load_dashboard_visual_settings', lambda: {'preset': 'auto'})
    monkeypatch.setattr(exporting.ExportDialog, '_load_dialog_config', lambda self: {'selected_preset': 'fast_diagnostics'})
    monkeypatch.setattr(exporting.ExportDialog, '_save_dialog_config', lambda self: None)
    monkeypatch.setattr(QMessageBox, 'information', lambda *_args: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *_args: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, 'question', lambda *_args: QMessageBox.StandardButton.Yes)
    created = []

    def create(context):
        if context == 'modify':
            dialog = ModifyDB(db_file=path, modal=False)
        elif context == 'csv_summary':
            dialog = analytics.IndustrialAnalyticsDialog(source_kind=analytics.SOURCE_TABULAR_FILE)
        elif context == 'export':
            dialog = exporting.ExportDialog()
        elif context == 'csv_grouping':
            dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
        elif context == 'grouping':
            dialog = DataGrouping(db_file=path)
        elif context == 'mapping':
            dialog = mapping.CharacteristicMappingDialog(db_file=path, modal=False)
        elif context == 'metrics':
            dialog = analytics.MetricSelectionDialog(metrics=metrics)
        elif context == 'limits':
            dialog = analytics.MetricLimitsDialog(metrics=metrics)
        elif context == 'industrial_sources':
            dialog = IndustrialSourceProfilesDialog(db_file=path, config_path=config)
        elif context == 'industrial_sql':
            parent = IndustrialSyncDialog(db_file=path, report_db_file=None, config_path=config)
            created.append(parent)
            dialog = IndustrialSqlQueryDialog(parent)
        elif context == 'industrial_filter':
            dialog = IndustrialFilterDialog(db_file=path)
        elif context == 'industrial_grouping':
            dialog = IndustrialGroupingDialog()
        else:
            dialog = IndustrialExportDialog(db_file=path, report_db_file=None, config_path=config)
        created.append(dialog)
        dialog.show()
        if context == 'mapping':
            wait_until(qapplication_session, lambda: not dialog.is_loading_source_options())
        return dialog

    yield create
    for dialog in reversed(created):
        # No command-routing test starts a worker or dirty-domain edit except the explicitly named journeys.
        assert dialog.close()
    wait_until(qapplication_session, lambda: not detached_threads.running_threads())


def direct_sequences(window):
    values = [sequence.toString() for action in window.actions() for sequence in action.shortcuts() if not sequence.isEmpty()]
    values += [shortcut.key().toString() for shortcut in window.findChildren(QShortcut)
               if shortcut.parent() is window]
    return values


@pytest.mark.parametrize('context', CONTEXTS)
def test_catalog_real_keys_are_unique_guarded_repeat_safe_and_text_safe(factory, qapplication_session, context):
    dialog = factory(context)
    sequences = direct_sequences(dialog)
    assert len(sequences) == len(set(sequences)), (context, sequences)
    assert not set(sequences) & {f'Ctrl+{letter}' for letter in 'ACXVZY'}
    before = len(dialog.actions())
    install_button_commands(dialog, context)
    assert len(dialog.actions()) == before
    text = QLineEdit(dialog)
    text.setGeometry(10, 10, 200, 30)
    text.show()
    for attribute, sequence in PRIMARY_BUTTON_COMMANDS[context]:
        button = getattr(dialog, attribute)
        assert sequence in button.text() and sequence in button.toolTip()
        assert not dialog._catalog_button_actions[(context, attribute)].autoRepeat()
        if button.receivers(button.clicked):
            button.clicked.disconnect()
        hits = []
        button.clicked.connect(lambda checked=False, hits=hits: hits.append(True))
        button.show()
        button.setEnabled(False)
        press(qapplication_session, text, sequence)
        assert hits == []
        button.setEnabled(True)
        button.hide()
        press(qapplication_session, text, sequence)
        assert hits == []
        button.show()
        press(qapplication_session, text, sequence)
        assert hits == [True], (context, attribute, sequence)
        key = QKeySequence(sequence)[0]
        QApplication.sendEvent(text, QKeyEvent(QEvent.Type.KeyPress, key.key(), key.keyboardModifiers(), '', True, 2))
        qapplication_session.processEvents()
        assert hits == [True]
        # Extra Ctrl+Alt is never treated as the Ctrl primary command.
        QApplication.sendEvent(text, QKeyEvent(QEvent.Type.KeyPress, key.key(),
            key.keyboardModifiers() | Qt.KeyboardModifier.AltModifier, 'ę'))
        assert hits == [True]
        for editing in ('Ctrl+A', 'Ctrl+C', 'Ctrl+X', 'Ctrl+V', 'Ctrl+Z', 'Ctrl+Y'):
            press(qapplication_session, text, editing)
        assert hits == [True]
        child = QDialog(dialog)
        child.setModal(True)
        child.show()
        try:
            press(qapplication_session, child, sequence)
            assert hits == [True]
        finally:
            child.close()
    text.setText('standard text')
    press(qapplication_session, text, 'Ctrl+A')
    assert text.selectedText() == 'standard text'
    press(qapplication_session, text, 'Ctrl+X')
    assert text.text() == ''
    press(qapplication_session, text, 'Ctrl+V')
    assert text.text() == 'standard text'
    press(qapplication_session, text, 'Ctrl+Z')
    assert text.text() == ''
    press(qapplication_session, text, 'Ctrl+Y')
    assert text.text() == 'standard text'
    press(qapplication_session, text, 'E')
    press(qapplication_session, text, 'R')
    assert text.text().endswith('er')


def test_dynamic_csv_hints_do_not_disappear_or_accumulate(factory):
    dialog = factory('csv_summary')
    for cached in (False, True, False, True):
        dialog._preloaded_tabular_source = cached
        dialog._sync_source_visibility()
        dialog._sync_ui_state()
        for attribute in ('load_metrics_button', 'filters_button'):
            button = getattr(dialog, attribute)
            key = dict(PRIMARY_BUTTON_COMMANDS['csv_summary'])[attribute]
            assert button.text().count(key) == 1 and button.toolTip().count(key) == 1
            assert button.shortcut().toString() in button.toolTip()


def test_mapping_parent_export_and_modal_child_save_share_ctrl_s_without_double_activation(factory, qapplication_session, monkeypatch):
    from metroliza.reports.characteristic_alias_service import fetch_all_characteristic_aliases
    dialog = factory('mapping')
    exports, failures = [], []
    monkeypatch.setattr(mapping.QFileDialog, 'getSaveFileName', lambda *_args: exports.append(True) or ('', ''))
    assert 'Export CSV' in plain_text(dialog.export_button.text()) and 'Ctrl+S' in dialog.export_button.text()
    press(qapplication_session, dialog.export_button, 'Ctrl+S')
    assert exports == [True]

    def save_child():
        child = QApplication.activeModalWidget()
        try:
            assert isinstance(child, mapping.CharacteristicAliasEditorDialog)
            child.alias_input.setCurrentText('Synthetic metric')
            child.common_name_input.setCurrentText('Shared metric')
            child.activateWindow()
            wait_until(qapplication_session, child.isActiveWindow)
            child.common_name_input.setFocus()
            QTest.keyClick(child.common_name_input, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
            assert not child.isVisible()
        except Exception as exc:
            failures.append(exc)
            if isinstance(child, QDialog):
                child.reject()

    dialog.activateWindow()
    wait_until(qapplication_session, dialog.isActiveWindow)
    QTimer.singleShot(0, save_child)
    QTest.keyClick(dialog, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    assert not failures, failures
    assert exports == [True]
    assert len(fetch_all_characteristic_aliases(dialog.db_file)) == 1
    press(qapplication_session, dialog.export_button, 'Ctrl+S')
    assert exports == [True, True]


def test_keypad_enter_confirms_compact_navigation_once_and_modifiers_remain_preview(app, window, monkeypatch):  # noqa: F811
    calls = []
    monkeypatch.setattr(window, 'launch_csv_summary_dialog', lambda: calls.append('csv'))
    window.resize(800, 700)
    combo = window.navigation_combo
    combo.setCurrentIndex(2)
    press(app, combo, 'Ctrl+Return')
    assert calls == []
    combo.activateWindow()
    wait_until(app, window.isActiveWindow)
    combo.setFocus()
    QTest.keyClick(combo, Qt.Key.Key_Enter, Qt.KeyboardModifier.KeypadModifier)
    assert calls == ['csv']
    combo.showPopup()
    app.processEvents()
    QTest.keyClick(combo.view(), Qt.Key.Key_Enter, Qt.KeyboardModifier.KeypadModifier)
    app.processEvents()
    assert calls == ['csv', 'csv']


def test_later_sidebar_click_is_not_swallowed_after_unpaired_double_click(app, window, monkeypatch):  # noqa: F811
    calls = []
    monkeypatch.setattr(window, 'launch_csv_summary_dialog', lambda: calls.append('csv'))
    window.resize(1200, 700)
    app.processEvents()
    viewport = window.navigation_list.viewport()
    position = window.navigation_list.visualItemRect(window.navigation_list.item(2)).center()
    QTest.mouseDClick(viewport, Qt.MouseButton.LeftButton, pos=position)
    assert window._skip_navigation_release  # the double-click's matching release was not delivered
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=position)
    assert calls == ['csv'] and not window._skip_navigation_release


@pytest.mark.parametrize('kind', ['metrics', 'limits'])
@pytest.mark.parametrize('sequence', ['Ctrl+S', 'Ctrl+W'])
def test_csv_modal_metric_children_own_shared_save_close_and_return_focus(factory, qapplication_session, kind, sequence):
    parent = factory('csv_summary')
    starts, closes = [], []
    parent.start_button.clicked.disconnect()
    parent.start_button.clicked.connect(lambda: starts.append(True))
    parent.start_button.setEnabled(True)
    parent.close_button.clicked.disconnect()
    parent.close_button.clicked.connect(lambda: closes.append(True))
    metric = (ProductionMetricSelection('value', 'Value'),)
    child_type = analytics.MetricSelectionDialog if kind == 'metrics' else analytics.MetricLimitsDialog
    child = child_type(parent, metrics=metric)
    child.setModal(True)
    child.show()
    try:
        press(qapplication_session, child, sequence)
        assert not child.isVisible()
        assert child.result() == (QDialog.DialogCode.Accepted if sequence == 'Ctrl+S' else QDialog.DialogCode.Rejected)
        assert starts == closes == []
        assert parent.isVisible()
        press(qapplication_session, parent.start_button, 'Ctrl+S')
        assert starts == [True] and not closes
    finally:
        child.close()


def test_grouping_ctrl_q_clears_only_active_child_without_main_quit(app, window):  # noqa: F811
    from metroliza.ui.tabular_analytics_grouping_dialog import TabularAnalyticsGroupingDialog
    # MainWindow's real File/Close action has no Ctrl+Q binding.
    assert 'Ctrl+Q' not in direct_sequences(window)
    child = TabularAnalyticsGroupingDialog(window, dataframe=pd.DataFrame({'part': ['A', 'B']}))
    child.show()
    try:
        child.available_columns_list.setCurrentRow(0)
        press(app, child.available_columns_list, 'Ctrl+E')
        assert child.selector_columns and child.selector_list.count() == 2
        child.selector_list.selectAll()
        assert child.selector_list.selectedItems()
        press(app, child.selector_list, 'Ctrl+Q')
        assert not child.selector_list.selectedItems()
        assert window.isVisible() and child.isVisible()
        child.selector_list.selectAll()
        press(app, window, 'Ctrl+Q')
        assert child.selector_list.selectedItems()  # inactive child does not receive the parent key
        assert window.isVisible()
    finally:
        child.close()


def test_industrial_export_stop_reaches_actual_modal_progress_once(factory, qapplication_session, monkeypatch):
    class Worker(QThread):
        result_ready = pyqtSignal(dict)
        error_occurred = pyqtSignal(str)
        cancelled = pyqtSignal(str)

        def __init__(self):
            super().__init__()
            self.release = Event()
            self.requests = 0

        def run(self):
            if self.release.wait(10):
                self.cancelled.emit('Cancelled')

        def cancel(self):
            self.requests += 1

    dialog = factory('industrial_export')
    worker = Worker()
    monkeypatch.setattr(dialog, 'create_export_thread', lambda: worker)
    dialog.show_loading_screen()
    try:
        wait_until(qapplication_session, lambda: dialog.loading_dialog.isVisible())
        progress = dialog.loading_dialog
        assert QApplication.activeModalWidget() is progress
        assert 'Ctrl+Shift+S' in progress.windowTitle()
        press(qapplication_session, progress, 'Ctrl+Shift+S')
        assert worker.requests == 1 and dialog.export_thread is worker
        key = QKeySequence('Ctrl+Shift+S')[0]
        QApplication.sendEvent(progress, QKeyEvent(QEvent.Type.KeyPress, key.key(), key.keyboardModifiers(), '', True, 2))
        assert worker.requests == 1
        assert 'Waiting' in dialog.loading_label.text()
    finally:
        worker.release.set()
        wait_until(qapplication_session, lambda: dialog.export_thread is None)
        assert worker.wait(1000)


@pytest.mark.parametrize('context', ['csv_grouping', 'industrial_sources', 'industrial_sql'])
def test_new_command_hints_fit_short_frame_and_native_source_controls(factory, qapplication_session, monkeypatch, context):
    from metroliza.app.windows_candidate_ui_checks import _geometry_dialog
    expected_screen = os.environ.get('METROLIZA_COMMAND_TEST_SCREEN')
    if not expected_screen:
        from metroliza.ui import ui_foundation
        monkeypatch.setattr(ui_foundation, '_available_window_size', lambda *_args: (1240, 760))
    dialog = factory(context)
    screen = qapplication_session.primaryScreen()
    print(f'command-screen={screen.geometry().width()}x{screen.geometry().height()} DPR={screen.devicePixelRatio()}')
    if expected_screen:
        assert (screen.geometry().width(), screen.geometry().height()) == tuple(map(int, expected_screen.split('x')))
    expected_dpr = os.environ.get('METROLIZA_COMMAND_TEST_DPR')
    if expected_dpr:
        assert screen.devicePixelRatio() == float(expected_dpr)
    controls = [getattr(dialog, attribute) for attribute, _key in PRIMARY_BUTTON_COMMANDS[context]]
    if context == 'industrial_sources':
        # Preserve the exact shipped native consumer, including the scrolled timestamp focus.
        native_controls = (dialog.status_label, dialog.timestamp_column_edit,
                           dialog.new_source_button, dialog.save_source_button, dialog.close_button)
        _geometry_dialog(dialog, qapplication_session, native_controls,
                         focus_controls=(dialog.timestamp_column_edit,), scroll=dialog.form_scroll)
    else:
        actual = _geometry_dialog(dialog, qapplication_session, tuple(controls))
        assert actual['client'] == [760, 560]
    rectangles = [control.rect().translated(control.mapTo(dialog, QPoint())) for control in controls]
    assert all(control.isVisibleTo(dialog) for control in controls)
    assert all(dialog.rect().contains(rect) for rect in rectangles)
    assert all(not first.intersects(second) for index, first in enumerate(rectangles) for second in rectangles[index + 1:])
