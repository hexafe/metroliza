"""Business outcomes for visible CSV grouping controls and member identity."""
from __future__ import annotations

import pandas as pd
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QMessageBox

from metroliza.ui.tabular_analytics_grouping_dialog import TabularAnalyticsGroupingDialog


def _choose_group(dialog, name):
    for index in range(dialog.groups_list.count()):
        item = dialog.groups_list.item(index)
        if item.data(Qt.ItemDataRole.UserRole) == name:
            dialog.groups_list.setCurrentItem(item)
            return
    raise AssertionError(name)


@pytest.fixture
def dialog(qapplication_session, monkeypatch):
    frame = pd.DataFrame({"source_row_number": [11, 27, 42], "part": ["A", "A", "B"]})
    window = TabularAnalyticsGroupingDialog(dataframe=frame)
    window._assign_rows_to_group([11, 27], "Chosen")
    window._refresh_all(preferred_group="Chosen")
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes)
    yield window
    window.close()


def test_remove_member_button_only_returns_selected_record_to_default(dialog):
    assert "Alt+X" in dialog.remove_from_group_button.text()
    assert not dialog.remove_from_group_button.isEnabled()
    member = dialog.group_members_list.item(1)
    assert member.data(Qt.ItemDataRole.UserRole) == 27
    dialog.group_members_list.setCurrentItem(member)
    assert dialog.remove_from_group_button.isEnabled()
    dialog.remove_from_group_button.click()
    assert set(dialog._temp_assignments()) == {11}
    assert dialog._group_counts() == {"Chosen": 1, dialog.default_group: 2}
    assert dialog.source_dataframe["source_row_number"].tolist() == [11, 27, 42]
    _choose_group(dialog, dialog.default_group)
    dialog.group_members_list.setCurrentRow(0)
    assert not dialog.remove_from_group_button.isEnabled()


def test_remove_member_shortcut_and_reset_keep_draft_boundary(dialog, qapplication_session):
    dialog._capture_committed_grouping_state()
    dialog.show()
    dialog.activateWindow()
    dialog.group_members_list.setFocus()
    dialog.group_members_list.setCurrentRow(0)
    qapplication_session.processEvents()
    QTest.keyClick(dialog.group_members_list, Qt.Key.Key_X, Qt.KeyboardModifier.AltModifier)
    assert set(dialog._temp_assignments()) == {27}
    assert dialog._is_grouping_dirty()
    dialog._request_reset_grouping()
    assert set(dialog._temp_assignments()) == {11, 27}
    assert not dialog._is_grouping_dirty()


def test_column_controls_respect_visible_search_and_preserve_groups(dialog):
    assert "Alt+W" in dialog.add_column_button.text()
    assert "Alt+E" in dialog.remove_column_button.text()
    dialog.add_column_button.click()
    assert dialog.selector_columns == ["part"]
    assert set(dialog._temp_assignments()) == {11, 27}
    dialog.selected_column_search.setText("absent")
    dialog._apply_selected_column_search()
    assert dialog.selected_columns_list.currentItem() is None
    assert not dialog.remove_column_button.isEnabled()
    dialog.remove_selected_selector_column()
    assert dialog.selector_columns == ["part"]
    dialog.selected_column_search.clear()
    dialog._apply_selected_column_search()
    dialog.remove_column_button.click()
    assert dialog.selector_columns == []
    assert set(dialog._temp_assignments()) == {11, 27}
    dialog.column_search.setText("absent")
    dialog._apply_column_search()
    assert not dialog.add_column_button.isEnabled()


def test_column_shortcuts_work_from_search_without_stealing_text_editing(dialog, qapplication_session):
    dialog.show()
    dialog.activateWindow()
    dialog.column_search.setFocus()
    qapplication_session.processEvents()
    QTest.keyClick(dialog.column_search, Qt.Key.Key_W, Qt.KeyboardModifier.AltModifier)
    assert dialog.selector_columns == ["part"]
    QTest.keyClicks(dialog.column_search, "part")
    QTest.keyClick(dialog.column_search, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert dialog.column_search.selectedText() == "part"
    QTest.keyClick(dialog.column_search, Qt.Key.Key_E, Qt.KeyboardModifier.AltModifier)
    assert dialog.selector_columns == []
