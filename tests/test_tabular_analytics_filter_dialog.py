from __future__ import annotations

import pandas as pd
import pytest

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    from modules.tabular_analytics_filter_dialog import TabularAnalyticsFilterDialog
    from modules.tabular_analytics_service import load_tabular_analytics_file
except ImportError as exc:  # pragma: no cover - depends on optional PyQt availability
    QApplication = None
    Qt = None
    TabularAnalyticsFilterDialog = None
    load_tabular_analytics_file = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None

_APP = None


def _app():
    if PYQT_IMPORT_ERROR is not None:
        pytest.skip(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")
    global _APP
    _APP = QApplication.instance() or _APP or QApplication([])
    return _APP


def _sample_loaded_table(tmp_path):
    input_file = tmp_path / "parts.csv"
    pd.DataFrame(
        {
            "Reference ID": ["R1", "R2", "R3", "R4"],
            "Line": ["L1", "L2", "L1", "L2"],
            "TraceCode": ["TC-001", "TC-002", "TC-003", "TC-004"],
            "Length mm": [10.0, 10.2, 10.4, 10.6],
        }
    ).to_csv(input_file, index=False)
    return load_tabular_analytics_file(input_file)


def _column_keys(dialog: TabularAnalyticsFilterDialog) -> list[str]:
    return [
        str(dialog.column_list.item(index).data(Qt.ItemDataRole.UserRole))
        for index in range(dialog.column_list.count())
    ]


def _select_available_column(dialog: TabularAnalyticsFilterDialog, column: str) -> None:
    for index in range(dialog.column_list.count()):
        item = dialog.column_list.item(index)
        if item.data(Qt.ItemDataRole.UserRole) == column:
            dialog.column_list.setCurrentItem(item)
            return
    raise AssertionError(f"Column {column!r} is not available; found {_column_keys(dialog)}")


def _select_matching_keys(
    dialog: TabularAnalyticsFilterDialog,
    keys: set[tuple[str, ...]],
) -> None:
    for index in range(dialog.matching_list.count()):
        item = dialog.matching_list.item(index)
        item.setSelected(tuple(item.data(Qt.ItemDataRole.UserRole)) in keys)
    dialog._store_current_selection()


def test_filter_dialog_exposes_source_columns_without_internal_helpers(tmp_path) -> None:
    _app()
    loaded = _sample_loaded_table(tmp_path)

    dialog = TabularAnalyticsFilterDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
    )
    try:
        available = _column_keys(dialog)

        assert "tracecode" in available
        assert "reference_id" in available
        assert "source_row_number" not in available
        assert "process_datetime" not in available
        assert "reference" not in available
    finally:
        dialog.close()


def test_filter_dialog_returns_selected_tracecode_keys(tmp_path) -> None:
    _app()
    loaded = _sample_loaded_table(tmp_path)

    dialog = TabularAnalyticsFilterDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
    )
    try:
        _select_available_column(dialog, "tracecode")
        dialog.add_filter_column()
        _select_matching_keys(dialog, {("TC-001",), ("TC-003",)})

        assert dialog.get_filter() == (
            ("tracecode",),
            (("TC-001",), ("TC-003",)),
        )
        assert dialog.status_label.text() == "TraceCode: 2 selected, 2 rows"
    finally:
        dialog.close()


def test_filter_dialog_expands_existing_selection_when_second_column_is_added(tmp_path) -> None:
    _app()
    loaded = _sample_loaded_table(tmp_path)

    dialog = TabularAnalyticsFilterDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
    )
    try:
        _select_available_column(dialog, "line")
        dialog.add_filter_column()
        _select_matching_keys(dialog, {("L1",)})

        _select_available_column(dialog, "tracecode")
        dialog.add_filter_column()

        columns, keys = dialog.get_filter()
        assert columns == ("line", "tracecode")
        assert set(keys) == {("L1", "TC-001"), ("L1", "TC-003")}
        assert dialog.status_label.text() == "Line | TraceCode: 2 selected, 2 rows"
    finally:
        dialog.close()
