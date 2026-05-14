from __future__ import annotations

import pandas as pd
import pytest

try:
    from PyQt6.QtCore import QDate, Qt
    from PyQt6.QtWidgets import QApplication
    import modules.tabular_analytics_filter_dialog as filter_dialog_module
    from modules.tabular_analytics_filter_dialog import TabularAnalyticsFilterDialog
    from modules.tabular_analytics_service import (
        TabularColumnFilter,
        cleanup_tabular_load_result,
        load_tabular_analytics_file,
    )
except ImportError as exc:  # pragma: no cover - depends on optional PyQt availability
    QApplication = None
    QDate = None
    Qt = None
    filter_dialog_module = None
    TabularAnalyticsFilterDialog = None
    TabularColumnFilter = None
    cleanup_tabular_load_result = None
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
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=4, freq="D"),
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


def _selected_column_keys(dialog: TabularAnalyticsFilterDialog) -> list[str]:
    return [
        str(dialog.selected_columns_list.item(index).data(Qt.ItemDataRole.UserRole))
        for index in range(dialog.selected_columns_list.count())
    ]


def _select_available_column(dialog: TabularAnalyticsFilterDialog, column: str) -> None:
    for index in range(dialog.column_list.count()):
        item = dialog.column_list.item(index)
        if item.data(Qt.ItemDataRole.UserRole) == column:
            dialog.column_list.setCurrentItem(item)
            return
    raise AssertionError(f"Column {column!r} is not available; found {_column_keys(dialog)}")


def _select_filter_column(dialog: TabularAnalyticsFilterDialog, column: str) -> None:
    for index in range(dialog.selected_columns_list.count()):
        item = dialog.selected_columns_list.item(index)
        if item.data(Qt.ItemDataRole.UserRole) == column:
            dialog.selected_columns_list.setCurrentItem(item)
            return
    raise AssertionError(f"Column {column!r} is not selected; found {_selected_column_keys(dialog)}")


def _select_matching_keys(
    dialog: TabularAnalyticsFilterDialog,
    keys: set[tuple[str, ...]],
) -> None:
    for index in range(dialog.matching_list.count()):
        item = dialog.matching_list.item(index)
        item.setSelected(tuple(item.data(Qt.ItemDataRole.UserRole)) in keys)
    dialog._store_current_selection()
    dialog._flush_pending_status_update()


def _select_values(
    dialog: TabularAnalyticsFilterDialog,
    values: set[str],
) -> None:
    for index in range(dialog.matching_list.count()):
        item = dialog.matching_list.item(index)
        item.setSelected(str(item.data(Qt.ItemDataRole.UserRole)) in values)
    dialog._store_current_selection()
    dialog._flush_pending_status_update()


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
        _select_values(dialog, {"TC-001", "TC-003"})

        assert dialog.get_filter() == (
            ("tracecode",),
            (("TC-001",), ("TC-003",)),
        )
        assert dialog.get_column_filters() == (
            TabularColumnFilter("tracecode", selected_values=("TC-001", "TC-003")),
        )
        assert dialog.status_label.text() == "1 column filter(s), 2 rows"
    finally:
        dialog.close()


def test_filter_dialog_keeps_independent_value_choices_per_selected_column(tmp_path) -> None:
    _app()
    loaded = _sample_loaded_table(tmp_path)

    dialog = TabularAnalyticsFilterDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
    )
    try:
        _select_available_column(dialog, "line")
        dialog.add_filter_column()
        _select_values(dialog, {"L1"})

        _select_available_column(dialog, "tracecode")
        dialog.add_filter_column()
        _select_filter_column(dialog, "tracecode")
        _select_values(dialog, {"TC-001", "TC-003"})

        columns, keys = dialog.get_filter()
        assert columns == ("line", "tracecode")
        assert set(keys) == {("L1", "TC-001"), ("L1", "TC-003")}
        assert dialog.get_column_filters() == (
            TabularColumnFilter("line", selected_values=("L1",)),
            TabularColumnFilter("tracecode", selected_values=("TC-001", "TC-003")),
        )
        assert dialog.status_label.text() == "2 column filter(s), 2 rows"
    finally:
        dialog.close()


def test_filter_dialog_status_count_uses_cached_debounced_path(tmp_path, monkeypatch) -> None:
    _app()
    loaded = _sample_loaded_table(tmp_path)
    calls = {"apply": 0}

    def fail_apply(*args, **kwargs):
        calls["apply"] += 1
        raise AssertionError("status count should not call full row filter")

    monkeypatch.setattr(filter_dialog_module, "apply_tabular_row_filter", fail_apply)
    dialog = TabularAnalyticsFilterDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
    )
    try:
        _select_available_column(dialog, "line")
        dialog.add_filter_column()
        _select_values(dialog, {"L1"})

        assert calls["apply"] == 0
        assert dialog.status_label.text() == "1 column filter(s), 2 rows"
    finally:
        dialog.close()


def test_filter_dialog_uses_sqlite_store_for_value_preview_and_counts(tmp_path) -> None:
    _app()
    input_file = tmp_path / "sqlite_filter.csv"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=4, freq="D"),
            "Line": ["L1", "L2", "L1", "L2"],
            "Length mm": [10.0, 10.2, 10.4, 10.6],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)

    dialog = TabularAnalyticsFilterDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
        sqlite_store=loaded.sqlite_store,
    )
    try:
        _select_available_column(dialog, "line")
        dialog.add_filter_column()
        _select_values(dialog, {"L1"})

        assert dialog.status_label.text() == "1 column filter(s), 2 rows"
        assert dialog.get_column_filters() == (TabularColumnFilter("line", selected_values=("L1",)),)
        assert dialog.get_filter() == (("line",), (("L1",),))
    finally:
        dialog.close()
        cleanup_tabular_load_result(loaded)


def test_filter_dialog_supports_per_column_values_and_calendar_date_bounds(tmp_path) -> None:
    _app()
    loaded = _sample_loaded_table(tmp_path)

    dialog = TabularAnalyticsFilterDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
    )
    try:
        _select_available_column(dialog, "line")
        dialog.add_filter_column()
        _select_values(dialog, {"L1"})

        _select_available_column(dialog, "time_stamp")
        dialog.add_filter_column()
        _select_filter_column(dialog, "time_stamp")
        dialog.date_mode_combo.setCurrentIndex(dialog.date_mode_combo.findData("between"))
        dialog.date_from_calendar.setDate(QDate(2026, 5, 11))
        dialog.date_to_calendar.setDate(QDate(2026, 5, 13))
        dialog._store_current_date_filter()
        dialog._flush_pending_status_update()

        assert dialog.get_column_filters() == (
            TabularColumnFilter("line", selected_values=("L1",)),
            TabularColumnFilter(
                "time_stamp",
                date_mode="between",
                date_from="2026-05-11",
                date_to="2026-05-13",
            ),
        )
        assert dialog.get_filter() == (("line", "time_stamp"), (("L1", "2026-05-12 08:00:00"),))
        assert dialog.status_label.text() == "2 column filter(s), 1 rows"
    finally:
        dialog.close()


def test_filter_dialog_apply_commits_pending_date_editor_text(tmp_path) -> None:
    _app()
    loaded = _sample_loaded_table(tmp_path)

    dialog = TabularAnalyticsFilterDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
    )
    try:
        _select_available_column(dialog, "time_stamp")
        dialog.add_filter_column()
        _select_filter_column(dialog, "time_stamp")
        dialog.date_mode_combo.setCurrentIndex(dialog.date_mode_combo.findData("between"))
        dialog.date_from_calendar.lineEdit().setText("2026-05-11")
        dialog.date_to_calendar.lineEdit().setText("2026-05-12")

        dialog.apply_button.click()

        assert dialog.get_column_filters() == (
            TabularColumnFilter(
                "time_stamp",
                date_mode="between",
                date_from="2026-05-11",
                date_to="2026-05-12",
            ),
        )
        assert dialog.get_filter() == (
            ("time_stamp",),
            (("2026-05-11 08:00:00",), ("2026-05-12 08:00:00",)),
        )
    finally:
        dialog.close()
