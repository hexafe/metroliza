from __future__ import annotations

import pandas as pd
import pytest

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    from modules.list_selection_utils import ListSelectionUtils
    from modules.tabular_analytics_grouping_dialog import TabularAnalyticsGroupingDialog
except ImportError as exc:  # pragma: no cover - depends on PyQt collection order
    Qt = None
    QApplication = None
    ListSelectionUtils = None
    TabularAnalyticsGroupingDialog = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None

_APP = None


def _app():
    if TabularAnalyticsGroupingDialog is None:
        pytest.skip(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")
    global _APP
    _APP = QApplication.instance() or _APP or QApplication([])
    return _APP


def _dialog_for_frame(frame: pd.DataFrame):
    if TabularAnalyticsGroupingDialog is None:
        pytest.skip(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")
    dialog = TabularAnalyticsGroupingDialog.__new__(TabularAnalyticsGroupingDialog)
    dialog.source_dataframe = frame
    dialog.column_labels = {}
    dialog.selector_columns = []
    dialog.selected_selector_keys = set()
    dialog.default_group = "POPULATION"
    return dialog


class _FakeMouseEvent:
    def __init__(self, *, position, modifiers):
        self._position = position
        self._modifiers = modifiers
        self.accepted = False

    def pos(self):
        return self._position

    def modifiers(self):
        return self._modifiers

    def accept(self):
        self.accepted = True


def test_available_grouping_columns_include_tracecode_even_when_reference_is_different() -> None:
    dialog = _dialog_for_frame(
        pd.DataFrame(
            {
                "source_row_number": [1, 2, 3],
                "reference": ["B1", "B1", "B2"],
                "tracecode": ["TC-001", "TC-002", "TC-003"],
                "length_mm": [10.0, 10.1, 10.2],
            }
        )
    )
    dialog.selector_columns = ["reference"]

    assert "tracecode" in dialog._available_columns()
    assert "reference" not in dialog._available_columns()
    assert "source_row_number" not in dialog._available_columns()


def test_selected_tracecode_keys_resolve_source_rows_independent_of_reference() -> None:
    dialog = _dialog_for_frame(
        pd.DataFrame(
            {
                "source_row_number": [1, 2, 3],
                "reference": ["B1", "B1", "B2"],
                "tracecode": ["TC-001", "TC-002", "TC-003"],
                "length_mm": [10.0, 10.1, 10.2],
            }
        )
    )
    dialog.selector_columns = ["tracecode"]
    dialog.selected_selector_keys = {("TC-001",), ("TC-003",)}

    assert dialog._row_ids_for_selected_keys() == [1, 3]


def test_grouping_dataframe_labels_rows_with_selected_column_chain() -> None:
    dialog = _dialog_for_frame(
        pd.DataFrame(
            {
                "source_row_number": [1, 2],
                "reference": ["B1", "B1"],
                "tracecode": ["TC-001", "TC-002"],
                "cavity": ["C1", "C2"],
            }
        )
    )
    dialog.selector_columns = ["tracecode", "cavity"]

    grouping_frame = dialog._build_grouping_dataframe()

    assert grouping_frame["REFERENCE"].tolist() == ["TC-001 | C1", "TC-002 | C2"]
    assert grouping_frame["GROUP"].tolist() == ["POPULATION", "POPULATION"]


def test_grouping_column_status_uses_original_column_labels() -> None:
    dialog = _dialog_for_frame(
        pd.DataFrame(
            {
                "source_row_number": [1],
                "tracecode": ["TC-001"],
                "cavity": ["C1"],
            }
        )
    )
    dialog.column_labels = {"tracecode": "TraceCode", "cavity": "Cavity"}
    dialog.selector_columns = ["tracecode", "cavity"]

    assert dialog._selector_columns_text() == "TraceCode | Cavity"


def test_removing_middle_grouping_column_projects_selected_keys_by_column_name() -> None:
    dialog = _dialog_for_frame(
        pd.DataFrame(
            {
                "source_row_number": [1, 2],
                "tracecode": ["TC-001", "TC-002"],
                "cavity": ["C1", "C2"],
                "fixture": ["F1", "F2"],
            }
        )
    )
    dialog.selector_columns = ["tracecode", "fixture"]
    dialog.selected_selector_keys = {
        ("TC-001", "C1", "F1"),
        ("TC-002", "C2", "F2"),
    }
    dialog.df = dialog._build_grouping_dataframe()
    dialog._rebuild_preserving_groups = lambda: None
    dialog._refresh_all = lambda: None

    dialog._after_selector_columns_removed(previous_columns=("tracecode", "cavity", "fixture"))

    assert dialog.selected_selector_keys == {("TC-001", "F1"), ("TC-002", "F2")}


def test_grouping_dialog_column_panes_are_tall_enough_for_multiple_columns() -> None:
    _app()
    dialog = TabularAnalyticsGroupingDialog(
        dataframe=pd.DataFrame(
            {
                "source_row_number": [1, 2],
                "tracecode": ["TC-001", "TC-002"],
                "cavity": ["C1", "C2"],
                "fixture": ["F1", "F2"],
            }
        )
    )
    try:
        assert dialog.available_columns_list.minimumHeight() >= 150
        assert dialog.selected_columns_list.minimumHeight() >= 120
        assert dialog.selector_list.minimumHeight() >= 220
    finally:
        dialog.close()


def test_selector_pages_high_cardinality_groups_and_keeps_selection_across_pages() -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": list(range(1, 2506)),
            "tracecode": [f"TC-{index:04d}" for index in range(2505)],
            "length_mm": [float(index) for index in range(2505)],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()

        assert dialog.selector_list.count() == 1000
        assert dialog.selector_page_label.text() == "Page 1 of 3"
        dialog.next_selector_page()

        assert dialog.selector_page_label.text() == "Page 2 of 3"
        assert dialog.selector_list.item(0).data(Qt.ItemDataRole.UserRole) == ("TC-1000",)
        dialog.select_visible_matching()

        assert len(dialog.selected_selector_keys) == 1000
        assert ("TC-1000",) in dialog.selected_selector_keys
        dialog.previous_selector_page()
        assert ("TC-1000",) in dialog.selected_selector_keys
    finally:
        dialog.close()


def test_select_all_matching_can_group_beyond_visible_preview() -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": list(range(1, 5001)),
            "tracecode": [f"TC-{index:04d}" for index in range(5000)],
            "length_mm": [float(index) for index in range(5000)],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()

        dialog.select_all_matching()

        assert len(dialog.selected_selector_keys) == 5000
        assert dialog._row_ids_for_selected_keys() == list(range(1, 5001))
    finally:
        dialog.close()


def test_create_group_uses_selected_keys_from_paged_selector() -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": list(range(1, 1501)),
            "tracecode": [f"TC-{index:04d}" for index in range(1500)],
            "length_mm": [float(index) for index in range(1500)],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        dialog.next_selector_page()
        dialog.select_visible_matching()

        dialog.create_group(initial_group_name="Paged group")

        grouped = dialog.df.loc[dialog.df["GROUP"] == "Paged group", "REPORT_ID"].tolist()
        assert grouped == list(range(1001, 1501))
        assert dialog.groups_list.currentItem().data(Qt.ItemDataRole.UserRole) == "Paged group"
    finally:
        dialog.close()


def test_shift_range_selection_uses_pre_click_anchor_and_ctrl_toggles_range() -> None:
    _app()
    dialog = TabularAnalyticsGroupingDialog(dataframe=pd.DataFrame())
    list_widget = dialog.selector_list
    helper = ListSelectionUtils()
    try:
        dialog.show()
        _app().processEvents()
        for index in range(5):
            list_widget.addItem(f"Row {index}")
            list_widget.item(index).setData(Qt.ItemDataRole.UserRole, (str(index),))
        _app().processEvents()

        anchor_event = _FakeMouseEvent(
            position=list_widget.visualItemRect(list_widget.item(0)).center(),
            modifiers=Qt.KeyboardModifier.NoModifier,
        )
        assert helper.handle_mouse_press(list_widget, anchor_event) is False

        shift_event = _FakeMouseEvent(
            position=list_widget.visualItemRect(list_widget.item(3)).center(),
            modifiers=Qt.KeyboardModifier.ShiftModifier,
        )
        assert helper.handle_mouse_press(list_widget, shift_event) is True
        assert shift_event.accepted is True
        assert [list_widget.item(index).isSelected() for index in range(5)] == [
            True,
            True,
            True,
            True,
            False,
        ]

        ctrl_shift_event = _FakeMouseEvent(
            position=list_widget.visualItemRect(list_widget.item(1)).center(),
            modifiers=Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier,
        )
        assert helper.handle_mouse_press(list_widget, ctrl_shift_event) is True
        assert [list_widget.item(index).isSelected() for index in range(5)] == [
            False,
            False,
            True,
            True,
            False,
        ]
    finally:
        dialog.close()


def test_existing_grouping_assignments_are_preserved_when_dialog_reopens() -> None:
    dialog = _dialog_for_frame(
        pd.DataFrame(
            {
                "source_row_number": [1, 2, 3],
                "reference": ["B1", "B1", "B2"],
                "tracecode": ["TC-001", "TC-002", "TC-003"],
            }
        )
    )
    dialog.df = dialog._build_grouping_dataframe()
    assignments = dialog._group_assignments(
        pd.DataFrame(
            {
                "REPORT_ID": [1, 3],
                "GROUP": ["Fixture A", "Fixture B"],
            }
        )
    )

    dialog._apply_group_assignments(assignments)

    assert dialog.df["GROUP"].tolist() == ["Fixture A", "POPULATION", "Fixture B"]
