"""Keyboard contracts for Modify DB and the CSV Summary launcher (#1159 P5c)."""

from pathlib import Path

import sys

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QAbstractButton, QApplication, QDialog, QGroupBox, QLabel, QTabWidget

from metroliza.ui import industrial_analytics_dialog as analytics, modify_db
from metroliza.ui.shortcuts import plain_text


BUTTONS = {
    "modify": ("select_db_button", "apply_button", "cancel_button"),
    "csv_summary": ("browse_input_button", "filters_button", "clear_filter_button",
                    "load_metrics_button", "choose_metrics_button", "edit_limits_button",
                    "edit_groups_button", "clear_groups_button", "dashboard_button",
                    "workbook_button", "close_button", "start_button", "advanced_toggle_button"),
}


def _patch_dialog_open_manual(monkeypatch, dialog, opened):
    """Patch open_manual where this dialog's help menu resolves it (full-suite module copies may differ)."""
    module = sys.modules[type(dialog).__module__]
    monkeypatch.setitem(
        module.attach_help_menu_to_layout.__globals__, "open_manual",
        lambda owner, key: opened.append((owner, key)),
    )


@pytest.fixture(params=BUTTONS)
def window(request, monkeypatch):
    app = QApplication.instance() or QApplication([])
    if request.param == "modify":
        dialog = modify_db.ModifyDB()
    else:
        monkeypatch.setattr(analytics, "load_dashboard_visual_settings", lambda: {"preset": "auto"})
        dialog = analytics.IndustrialAnalyticsDialog(source_kind=analytics.SOURCE_TABULAR_FILE)
    dialog.show()
    dialog.activateWindow()
    app.processEvents()
    yield request.param, dialog, app
    dialog.hide()
    dialog.deleteLater()
    app.processEvents()


def _press(widget, key, modifiers=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(widget, key, modifiers)
    QApplication.processEvents()


def _search_pairs(dialog):
    return [(dialog.reference_filter_edit, dialog.reference_table),
            (dialog.part_number_filter_edit, dialog.part_number_table),
            (dialog.header_filter_edit, dialog.header_table),
            (dialog.report_filter_edit, dialog.report_records_table),
            (dialog.measurement_filter_edit, dialog.measurement_records_table)]


def test_ctrl_f_selects_search_on_each_modify_tab(window):
    kind, dialog, app = window
    if kind != "modify":
        assert not any(a.shortcut() == QKeySequence("Ctrl+F") for a in dialog.actions())
        return  # The CSV launcher has no search field.
    for index, (field, table) in enumerate(_search_pairs(dialog)):
        dialog.tab_widget.setCurrentIndex(0 if index < 3 else index - 2)
        if index < 3:
            dialog.normalize_tab_widget.setCurrentIndex(index)
        field.blockSignals(True)
        field.setText("find this value")
        field.blockSignals(False)
        table.setFocus()
        app.processEvents()
        _press(table, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        assert field.hasFocus()
        assert field.selectedText() == "find this value"
        assert "Ctrl+F" in field.toolTip()


def test_ctrl_f_disabled_fallback_and_modal_boundary(window):
    kind, dialog, app = window
    if kind != "modify":
        pytest.skip("Only Modify DB has search fields")
    field = dialog.reference_filter_edit
    field.setText("sample")
    dialog.cancel_button.setFocus()
    _press(dialog, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert field.hasFocus() and field.selectedText() == "sample"
    actions = [a for a in dialog.actions() if a.shortcut() == QKeySequence("Ctrl+F")]
    assert len(actions) == 1
    action = actions[0]
    assert action.shortcutContext() == Qt.ShortcutContext.WindowShortcut
    hits = []
    action.triggered.connect(lambda: hits.append(True))
    action.setEnabled(False)
    dialog.cancel_button.setFocus()
    _press(dialog, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert not hits and not field.hasFocus()
    action.setEnabled(True)
    child = QDialog(dialog)
    child.setModal(True)
    child.show()
    child.activateWindow()
    app.processEvents()
    try:
        _press(child, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        assert not hits
    finally:
        child.hide()
        child.deleteLater()
    for edit, _ in _search_pairs(dialog):
        edit.setEnabled(False)
    dialog.activateWindow()
    dialog.cancel_button.setFocus()
    app.processEvents()
    action.trigger()
    assert dialog.cancel_button.hasFocus()


def test_primary_mnemonics_unique_accessible_and_no_reserved_shortcuts(window):
    kind, dialog, _ = window
    for name in BUTTONS[kind]:
        button = getattr(dialog, name)
        assert not button.shortcut().isEmpty(), name
        assert button.accessibleName() and "&" not in button.accessibleName()
        assert button.shortcut().toString() in button.toolTip()
    sequences = []
    for action in dialog.findChildren(QAction):
        sequences.extend(s.toString() for s in action.shortcuts())
        mnemonic = QKeySequence.mnemonic(action.text())
        if not mnemonic.isEmpty():
            sequences.append(mnemonic.toString())
    sequences.extend(s.key().toString() for s in dialog.findChildren(QShortcut))
    sequences.extend(b.shortcut().toString() for b in dialog.findChildren(QAbstractButton)
                     if not b.shortcut().isEmpty())
    captions = [label.text() for label in dialog.findChildren(QLabel) if label.buddy() is not None]
    captions += [group.title() for group in dialog.findChildren(QGroupBox)]
    captions += [tabs.tabText(i) for tabs in dialog.findChildren(QTabWidget) for i in range(tabs.count())]
    sequences += [QKeySequence.mnemonic(caption).toString() for caption in captions
                  if not QKeySequence.mnemonic(caption).isEmpty()]
    assert len(sequences) == len(set(sequences)), sequences
    reserved = {f"Ctrl+{key}" for key in "CVXZYA"}
    reserved.update(("Tab", "Shift+Tab", "Backtab", "Return", "Enter", "Space", "Delete", "Backspace",
                     "Left", "Right", "Up", "Down", "Home", "End", "PgUp", "PgDown"))
    assert not set(sequences) & reserved


def test_mnemonics_dispatch_enabled_only(window):
    kind, dialog, _ = window
    if kind == "csv_summary":
        dialog.advanced_toggle_button.setChecked(True)
    for name in BUTTONS[kind]:
        button = getattr(dialog, name)
        if button.receivers(button.clicked):
            button.clicked.disconnect()
        if button.isCheckable():
            button.toggled.disconnect()
        button.show()
        button.setEnabled(True)
        hits = []
        button.clicked.connect(lambda _checked=False: hits.append(True))
        sequence = button.shortcut()
        assert not sequence.isEmpty(), name
        _press(dialog, sequence[0].key(), Qt.KeyboardModifier.AltModifier)
        QTest.qWait(150)
        assert hits == [True], name
        button.setEnabled(False)
        _press(dialog, sequence[0].key(), Qt.KeyboardModifier.AltModifier)
        QTest.qWait(150)
        assert hits == [True], name


def test_f1_manual_and_modal_child_blocks_parent_mnemonic(window, monkeypatch):
    from metroliza.ui import help_menu

    kind, dialog, app = window
    opened = []
    monkeypatch.setattr(help_menu, "open_manual", lambda owner, key: opened.append((owner, key)))
    _patch_dialog_open_manual(monkeypatch, dialog, opened)
    _press(dialog, Qt.Key.Key_F1)
    assert opened == [(dialog, "modify_database" if kind == "modify" else "csv_summary")]
    button = getattr(dialog, BUTTONS[kind][0])
    assert not button.shortcut().isEmpty()
    button.clicked.disconnect()
    hits = []
    button.clicked.connect(lambda: hits.append(True))
    child = QDialog(dialog)
    help_menu.build_help_menu(child, [("Child manual", "csv_summary")])
    child.setModal(True)
    child.show()
    child.activateWindow()
    app.processEvents()
    try:
        _press(child, button.shortcut()[0].key(), Qt.KeyboardModifier.AltModifier)
        QTest.qWait(150)
        assert not hits
        _press(child, Qt.Key.Key_F1)
        assert opened[-1] == (child, "csv_summary")
        assert len(opened) == 2
    finally:
        child.hide()
        child.deleteLater()


def test_hidden_button_mnemonic_is_inert(window):
    kind, dialog, _ = window
    button = dialog.apply_button if kind == "modify" else dialog.workbook_button
    button.clicked.disconnect()
    button.setEnabled(True)
    if kind == "modify":
        button.hide()
    # The workbook browse button belongs to the collapsed Advanced section.
    assert not button.isVisibleTo(dialog)
    assert not button.shortcut().isEmpty()
    hits = []
    button.clicked.connect(lambda: hits.append(True))
    _press(dialog, button.shortcut()[0].key(), Qt.KeyboardModifier.AltModifier)
    QTest.qWait(150)
    assert not hits


def test_csv_dynamic_captions_keep_mnemonics(window):
    kind, dialog, _ = window
    if kind != "csv_summary":
        pytest.skip("CSV Summary's dynamic captions")
    for expanded in (True, False):
        dialog.advanced_toggle_button.setChecked(expanded)
        assert plain_text(dialog.advanced_toggle_button.text()) == (
            "Hide advanced options" if expanded else "Show advanced options")
        assert dialog.advanced_toggle_button.shortcut() == QKeySequence("Alt+A")
    for cached in (False, True):
        dialog._preloaded_tabular_source = cached
        dialog._sync_source_visibility()
        for notice in ("", "Reload required"):
            dialog._tabular_reload_notice = notice
            dialog._sync_ui_state()
            assert dialog.load_metrics_button.shortcut() == QKeySequence("Alt+M")
            assert dialog.filters_button.shortcut() == QKeySequence("Alt+F")
            assert "&" not in dialog.load_metrics_button.accessibleName()


def test_production_analytics_does_not_get_csv_mnemonics(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(analytics, "load_dashboard_visual_settings", lambda: {"preset": "auto"})
    dialog = analytics.IndustrialAnalyticsDialog(source_kind=analytics.SOURCE_PRODUCTION_CACHE)
    try:
        for name in BUTTONS["csv_summary"]:
            assert getattr(dialog, name).shortcut().isEmpty(), name
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_manual_keyboard_notes_are_utf8():
    modify = Path("docs/user_manual/modify_database.md").read_text(encoding="utf-8")
    csv = Path("docs/user_manual/csv_summary.md").read_text(encoding="utf-8")
    assert "Ctrl+F" in modify and "Alt+B" in modify and "F1" in modify
    assert "Alt+Y" in csv and "Alt+A" in csv and "F1" in csv
