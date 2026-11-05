"""Keyboard contracts for the Export, filtering and grouping windows (#1159)."""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QAbstractButton, QApplication, QDialog, QGroupBox, QLabel, QTabWidget

from metroliza.ui import data_grouping, export_dialog, filter_dialog
from metroliza.ui.shortcuts import plain_text


BUTTONS = {
    "export": ("select_db_button", "select_excel_button", "filter_button",
               "clear_filter_button", "group_button", "clear_group_button",
               "export_button", "close_button", "dashboard_visuals_button",
               "advanced_toggle_button"),
    "filter": ("apply_button", "reset_button", "cancel_button", "has_nok_button",
               "select_today_button", "select_beginning_button"),
    "grouping": ("create_group_button", "rename_group_button", "remove_from_group_button",
                 "delete_group_button", "use_grouping_button", "dont_use_grouping_button",
                 "cancel_button"),
}

def _wait_until(condition, timeout_ms=2000):
    """Poll the event loop; animateClick-delivered clicks can lag on loaded CI hosts."""
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(20)
        waited += 20
    return condition()



def _patch_dialog_open_manual(monkeypatch, dialog, opened):
    """Patch open_manual where this dialog's help menu resolves it (full-suite module copies may differ)."""
    attach = type(dialog).__init__.__globals__["attach_help_menu_to_layout"]
    monkeypatch.setitem(
        attach.__globals__["build_help_menu"].__globals__, "open_manual",
        lambda owner, key: opened.append((owner, key)),
    )


@pytest.fixture(params=BUTTONS)
def window(request, monkeypatch):
    app = QApplication.instance() or QApplication([])
    kind = request.param
    if kind == "export":
        monkeypatch.setattr(export_dialog.ExportDialog, "_load_dialog_config",
                            lambda self: {"selected_preset": "fast_diagnostics"})
        monkeypatch.setattr(export_dialog.ExportDialog, "_save_dialog_config", lambda self: None)
        monkeypatch.setattr(export_dialog, "load_dashboard_visual_settings", lambda: {"preset": "auto"})
        dialog = export_dialog.ExportDialog()
    elif kind == "filter":
        monkeypatch.setattr(filter_dialog.FilterDialog, "populate_list_widgets", lambda self: None)
        dialog = filter_dialog.FilterDialog()
    else:
        import pandas as pd

        frame = pd.DataFrame([{"REPORT_ID": 1, "REFERENCE": "R1", "PART_NAME": "Part",
                               "DATE": "2026-01-01", "SAMPLE_NUMBER": "1"}])
        monkeypatch.setattr(data_grouping.DataGrouping, "read_data_to_df",
                            lambda self: setattr(self, "df", frame.copy()))
        monkeypatch.setattr(data_grouping.DataGrouping, "_restore_saved_grouping_state", lambda self: None)
        dialog = data_grouping.DataGrouping()
    dialog.show()
    dialog.activateWindow()
    app.processEvents()
    yield kind, dialog, app
    dialog.hide()
    dialog.deleteLater()
    app.processEvents()


def _press(widget, key, modifiers=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(widget, key, modifiers)
    QApplication.processEvents()


def _search_pairs(kind, dialog):
    if kind == "filter":
        return [(getattr(dialog, search), getattr(dialog, listing))
                for _, fields in dialog.FILTER_SECTIONS
                for _, search, listing in fields if search]
    return [(dialog.reference_search_input, dialog.reference_list),
            (dialog.part_search_input, dialog.part_list),
            (dialog.group_search_input, dialog.groups_list),
            (dialog.part_group_search_input, dialog.part_group_list),
            (dialog.scope_filter_input, dialog.scope_filter_input)]


def test_ctrl_f_selects_search_for_focused_pane_and_active_tab(window):
    kind, dialog, app = window
    if kind == "export":
        pytest.skip("Export has no search field")
    for field, listing in _search_pairs(kind, dialog):
        if kind == "filter":
            for index in range(dialog.filter_tabs.count()):
                if dialog.filter_tabs.widget(index).isAncestorOf(field):
                    dialog.filter_tabs.setCurrentIndex(index)
        field.blockSignals(True)
        field.setText("find this value")
        field.blockSignals(False)
        listing.setFocus()
        app.processEvents()
        _press(listing, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        assert field.hasFocus()
        assert field.selectedText() == "find this value"
        assert "Ctrl+F" in field.toolTip()


def test_ctrl_f_fallback_disabled_and_modal_boundary(window):
    kind, dialog, app = window
    if kind == "export":
        assert not any(a.shortcut() == QKeySequence("Ctrl+F") for a in dialog.findChildren(QAction))
        return
    field, _ = _search_pairs(kind, dialog)[0]
    field.setText("sample")
    dialog.cancel_button.setFocus()
    _press(dialog, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert field.hasFocus() and field.selectedText() == "sample"
    actions = [a for a in dialog.actions() if a.shortcut() == QKeySequence("Ctrl+F")]
    assert len(actions) == 1
    action = actions[0]
    assert action.shortcutContext() == Qt.ShortcutContext.WindowShortcut
    calls = []
    action.triggered.connect(lambda: calls.append(True))
    action.setEnabled(False)
    dialog.cancel_button.setFocus()
    _press(dialog, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert not calls and not field.hasFocus()
    action.setEnabled(True)
    child = QDialog(dialog)
    child.setModal(True)
    child.show()
    child.activateWindow()
    app.processEvents()
    try:
        _press(child, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        assert not calls
    finally:
        child.hide()
        child.deleteLater()
    # During background loading every search may be disabled; Ctrl+F is inert.
    for edit, _ in _search_pairs(kind, dialog):
        edit.setEnabled(False)
    dialog.activateWindow()
    dialog.cancel_button.setFocus()
    app.processEvents()
    action.trigger()
    assert dialog.cancel_button.hasFocus()


def test_primary_button_mnemonics_unique_and_accessible(window):
    kind, dialog, _ = window
    for name in BUTTONS[kind]:
        button = getattr(dialog, name)
        assert not button.shortcut().isEmpty(), name
        assert "&" not in button.accessibleName()
        assert button.accessibleName()
        assert button.shortcut().toString() in button.toolTip()
    sequences = []
    for action in dialog.findChildren(QAction):
        sequences.extend(sequence.toString() for sequence in action.shortcuts())
        mnemonic = QKeySequence.mnemonic(action.text())
        if not mnemonic.isEmpty():
            sequences.append(mnemonic.toString())
    sequences.extend(shortcut.key().toString() for shortcut in dialog.findChildren(QShortcut))
    sequences.extend(button.shortcut().toString() for button in dialog.findChildren(QAbstractButton)
                     if not button.shortcut().isEmpty())
    captions = [label.text() for label in dialog.findChildren(QLabel) if label.buddy() is not None]
    captions += [group.title() for group in dialog.findChildren(QGroupBox)]
    captions += [tabs.tabText(index) for tabs in dialog.findChildren(QTabWidget)
                 for index in range(tabs.count())]
    sequences += [QKeySequence.mnemonic(caption).toString() for caption in captions
                  if not QKeySequence.mnemonic(caption).isEmpty()]
    assert len(sequences) == len(set(sequences)), sequences
    reserved = {f"Ctrl+{key}" for key in "CVXZYA"}
    reserved.update(("Tab", "Shift+Tab", "Backtab", "Return", "Enter", "Space", "Delete", "Backspace",
                     "Left", "Right", "Up", "Down", "Home", "End", "PgUp", "PgDown"))
    assert not set(sequences) & reserved


def test_mnemonics_trigger_enabled_buttons_only(window):
    kind, dialog, _ = window
    # Disconnect heavy operations; exercise the real Qt mnemonic dispatch.
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
        key = sequence[0].key()
        _press(dialog, key, Qt.KeyboardModifier.AltModifier)
        assert _wait_until(lambda: hits == [True]), (name, button.isVisible(), button.isEnabled(), dialog.isActiveWindow())
        button.setEnabled(False)
        _press(dialog, key, Qt.KeyboardModifier.AltModifier)
        QTest.qWait(150)
        assert hits == [True], name


def test_export_advanced_caption_retains_mnemonic_and_visible_text(window):
    kind, dialog, _ = window
    if kind != "export":
        pytest.skip("Export's dynamic caption")
    button = dialog.advanced_toggle_button
    for expanded in (True, False):
        button.setChecked(expanded)
        assert plain_text(button.text()) == ("Hide advanced options" if expanded else "Show advanced options")
        assert button.shortcut() == QKeySequence("Alt+A")


def test_f1_uses_dialog_manual(window, monkeypatch):
    from metroliza.ui import help_menu

    kind, dialog, _ = window
    opened = []
    monkeypatch.setattr(help_menu, "open_manual", lambda owner, key: opened.append((owner, key)))
    _patch_dialog_open_manual(monkeypatch, dialog, opened)
    _press(dialog, Qt.Key.Key_F1)
    expected = {"export": "export_overview", "filter": "export_filtering", "grouping": "export_grouping"}
    assert opened == [(dialog, expected[kind])]


def test_modal_child_owns_f1_and_blocks_parent_mnemonic(window, monkeypatch):
    from metroliza.ui import help_menu

    kind, dialog, app = window
    button = getattr(dialog, BUTTONS[kind][0])
    if button.receivers(button.clicked):
        button.clicked.disconnect()
    hits = []
    button.clicked.connect(lambda: hits.append(True))
    opened = []
    monkeypatch.setattr(help_menu, "open_manual", lambda owner, key: opened.append((owner, key)))
    _patch_dialog_open_manual(monkeypatch, dialog, opened)
    child = QDialog(dialog)
    help_menu.build_help_menu(child, [("Child manual", "export_overview")])
    child.setModal(True)
    child.show()
    child.activateWindow()
    app.processEvents()
    try:
        _press(child, button.shortcut()[0].key(), Qt.KeyboardModifier.AltModifier)
        QTest.qWait(150)
        assert not hits
        _press(child, Qt.Key.Key_F1)
        assert opened == [(child, "export_overview")]
    finally:
        child.hide()
        child.deleteLater()
