from __future__ import annotations

import time

import pandas as pd
import pytest

try:
    from PyQt6.QtCore import QDate, Qt
    from PyQt6.QtWidgets import QApplication, QListWidgetItem
    import metroliza.ui.tabular_analytics_filter_dialog as filter_dialog_module
    from metroliza.ui.tabular_analytics_filter_dialog import TabularAnalyticsFilterDialog
    from metroliza.tabular.tabular_analytics_service import (
        TabularColumnFilter,
        cleanup_tabular_load_result,
        load_tabular_analytics_file,
    )
except ImportError as exc:  # pragma: no cover - depends on optional PyQt availability
    QApplication = None
    QListWidgetItem = None
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


def _wait_for_value_preview(dialog: TabularAnalyticsFilterDialog, *, timeout_seconds: float = 3.0) -> None:
    app = _app()
    deadline = time.monotonic() + timeout_seconds
    while getattr(dialog, "_preview_threads", None) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert not getattr(dialog, "_preview_threads", None)


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


def test_filter_dialog_uses_distinct_footer_actions(tmp_path) -> None:
    _app()
    loaded = _sample_loaded_table(tmp_path)

    dialog = TabularAnalyticsFilterDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
    )
    try:
        assert dialog.clear_selection_button.text() == "Clear values"
        assert dialog.clear_filter_button.text() == "Reset filter"
        assert dialog.clear_selection_button.accessibleName() == "Clear selected CSV filter values"
        assert dialog.clear_filter_button.accessibleName() == "Reset CSV row filter"
        assert dialog.apply_button.accessibleName() == "Apply CSV row filter"
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


def test_filter_dialog_magic_expression_counts_and_clears(tmp_path) -> None:
    _app()
    loaded = _sample_loaded_table(tmp_path)

    dialog = TabularAnalyticsFilterDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
        filter_expression="Length mm > 10.1 and < 10.5",
    )
    try:
        dialog._sync_status_now()

        assert dialog.get_filter_expression() == "Length mm > 10.1 and < 10.5"
        assert dialog.get_column_filters() == ()
        assert dialog.status_label.text() == "Magic filter, 2 rows"

        dialog.clear_filter()

        assert dialog.get_filter_expression() == ""
        assert dialog.status_label.text() == "No row filter selected"
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
        _wait_for_value_preview(dialog)
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
        _wait_for_value_preview(dialog)
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
        _wait_for_value_preview(dialog)
        _select_values(dialog, {"L1"})

        assert dialog.status_label.text() == "1 column filter(s), 2 rows"
        assert dialog.get_column_filters() == (TabularColumnFilter("line", selected_values=("L1",)),)
        assert dialog.get_filter() == (("line",), (("L1",),))
    finally:
        dialog.close()
        cleanup_tabular_load_result(loaded)


def test_filter_dialog_sqlite_value_search_waits_for_enter(tmp_path, monkeypatch) -> None:
    _app()
    input_file = tmp_path / "sqlite_filter_search.csv"
    pd.DataFrame(
        {
            "Line": ["L1", "L2", "L1", "L3"],
            "Length mm": [10.0, 10.2, 10.4, 10.6],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)
    original_preview = type(loaded.sqlite_store).preview_value_rows
    searches: list[str] = []

    def preview_spy(store, column, **kwargs):
        searches.append(str(kwargs.get("search_text") or ""))
        return original_preview(store, column, **kwargs)

    dialog = TabularAnalyticsFilterDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
        sqlite_store=loaded.sqlite_store,
    )
    try:
        monkeypatch.setattr(type(loaded.sqlite_store), "preview_value_rows", preview_spy)
        _select_available_column(dialog, "line")
        dialog.add_filter_column()
        _wait_for_value_preview(dialog)
        searches.clear()

        dialog.matching_search.setText("L2")

        assert searches == []
        assert dialog.matching_status_label.text() == "Press Enter to search values."

        dialog.matching_search.returnPressed.emit()
        _wait_for_value_preview(dialog)

        assert searches == ["L2"]
        assert [
            dialog.matching_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(dialog.matching_list.count())
        ] == ["L2"]
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


def test_filter_dialog_loads_modern_and_legacy_initial_filters(tmp_path) -> None:
    _app()
    loaded = _sample_loaded_table(tmp_path)

    modern = TabularAnalyticsFilterDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
        column_filters=(
            TabularColumnFilter("line", selected_values=("L1",)),
            TabularColumnFilter("time_stamp", date_mode="from", date_from="2026-05-11"),
            TabularColumnFilter("time_stamp", date_mode="to", date_to="2026-05-13"),
            TabularColumnFilter("missing", selected_values=("ignored",)),
            object(),
        ),
    )
    try:
        assert modern.filter_columns == ["line", "time_stamp"]
        assert modern._selected_column_label("line") == "Line: 1 value(s)"
        assert modern._selected_column_label("time_stamp") == "Time Stamp: <= 2026-05-13"
    finally:
        modern.close()

    legacy = TabularAnalyticsFilterDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
        filter_columns=("line", "tracecode", "missing"),
        selected_filter_keys=(("L1", "TC-001"), ("L2", "TC-002"), ("bad-length",)),
    )
    try:
        assert legacy.filter_columns == ["line", "tracecode"]
        assert legacy.value_filters == {"line": {"L1", "L2"}, "tracecode": {"TC-001", "TC-002"}}
        assert legacy.date_filters["line"] == {"mode": "any", "from": None, "to": None}
    finally:
        legacy.close()


def test_filter_dialog_column_actions_reset_state_and_handle_noops(tmp_path) -> None:
    _app()
    loaded = _sample_loaded_table(tmp_path)
    dialog = TabularAnalyticsFilterDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
    )
    try:
        dialog.column_list.setCurrentItem(None)
        dialog.add_filter_column()
        assert dialog.filter_columns == []

        _select_available_column(dialog, "line")
        dialog.add_filter_column()
        assert dialog.filter_columns == ["line"]
        duplicate_item = QListWidgetItem("Line")
        duplicate_item.setData(Qt.ItemDataRole.UserRole, "line")
        dialog.column_list.addItem(duplicate_item)
        dialog.column_list.setCurrentItem(duplicate_item)
        dialog.add_filter_column()
        assert dialog.filter_columns == ["line"]

        _select_values(dialog, {"L1"})
        assert dialog.clear_selection_button.isEnabled() is True
        dialog.clear_selection()
        assert dialog.value_filters["line"] == set()
        assert dialog.date_filters["line"] == {"mode": "any", "from": None, "to": None}
        assert dialog.clear_selection_button.isEnabled() is False

        dialog.selected_columns_list.setCurrentItem(None)
        dialog.remove_selected_filter_column()
        assert dialog.filter_columns == []

        _select_available_column(dialog, "tracecode")
        dialog.add_filter_column()
        dialog._value_index_by_column["tracecode"] = object()
        dialog.clear_filter_columns()
        assert dialog.filter_columns == []
        assert dialog.value_filters == {}
        assert dialog._value_index_by_column == {}

        _select_available_column(dialog, "time_stamp")
        dialog.add_filter_column()
        dialog.value_filters["time_stamp"] = {"2026-05-10 08:00:00"}
        dialog.clear_filter()
        assert dialog.get_filter() == ((), ())
        assert dialog.status_label.text() == "No row filter selected"
    finally:
        dialog.close()


def test_filter_dialog_search_and_preview_helpers_cover_empty_and_limited_states(tmp_path) -> None:
    _app()
    loaded = _sample_loaded_table(tmp_path)
    dialog = TabularAnalyticsFilterDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
    )
    try:
        refreshed = []
        original_refresh_values = dialog._refresh_values
        dialog._refresh_values = lambda: refreshed.append("refresh")
        dialog.matching_search.setText("TC")
        assert refreshed == ["refresh"]
        dialog._refresh_values = original_refresh_values

        dialog._syncing_current_filter = True
        dialog._store_current_selection()
        dialog._commit_current_filter_controls()
        assert dialog.value_filters == {}
        dialog._syncing_current_filter = False

        dialog._apply_value_preview(
            "tracecode",
            [{"label": "TC-001", "row_count": 1, "key": ("TC-001",)}],
            2,
        )
        assert dialog.matching_status_label.text() == (
            "Showing 1 of 2 value(s). Search to narrow."
        )

        dialog.matching_list.clear()
        dialog._refresh_values()
        assert dialog.matching_status_label.text() == "Add a filter column to preview values."
    finally:
        dialog.close()


def test_filter_dialog_date_helpers_cover_non_date_and_bounds_fallbacks(tmp_path) -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2],
            "length_mm": [10.1, 10.2],
            "status": ["open", "closed"],
            "created_date": [None, None],
            "updated_time": ["bad", "2026-05-12"],
            "empty_date": [None, None],
        }
    )
    dialog = TabularAnalyticsFilterDialog(dataframe=frame)
    try:
        assert dialog._is_date_filterable(None) is False
        assert dialog._is_date_filterable("length_mm") is False
        assert dialog._is_date_filterable("status") is False
        assert dialog._is_date_filterable("created_date") is False
        assert dialog._is_date_filterable("updated_time") is False

        lower, upper = dialog._column_date_bounds("empty_date")
        assert lower.isValid()
        assert upper == lower

        _select_available_column(dialog, "updated_time")
        dialog.add_filter_column()
        dialog._store_current_date_filter()
        assert dialog.date_filters["updated_time"] == {"mode": "any", "from": None, "to": None}

        dialog._set_combo_data(dialog.date_mode_combo, "missing-mode")
        assert dialog.date_mode_combo.currentData() == "any"
    finally:
        dialog.close()


def test_filter_dialog_sqlite_lifecycle_handlers_ignore_stale_results_and_report_errors(
    tmp_path,
) -> None:
    _app()
    input_file = tmp_path / "sqlite_filter_lifecycle.csv"
    pd.DataFrame(
        {
            "Line": ["L1", "L2"],
            "Time Stamp": ["2026-05-10", "2026-05-11"],
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
        _wait_for_value_preview(dialog)
        dialog._preview_request_id = 7

        dialog._on_sqlite_value_preview_ready(
            6,
            "line",
            [{"label": "stale", "row_count": 1, "key": ("stale",)}],
            1,
        )
        assert all(dialog.matching_list.item(index).text() != "stale (n=1)" for index in range(dialog.matching_list.count()))

        dialog._on_sqlite_value_preview_error(7, "line", "boom")
        assert dialog.matching_status_label.text() == "Could not load values: boom"

        class _Label:
            def __init__(self):
                self.text = ""

            def setText(self, text):
                self.text = text

        class _Dialog:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        loading_dialog = _Dialog()
        loading_label = _Label()
        dialog._preview_loading_dialog = loading_dialog
        dialog._preview_loading_label = loading_label
        dialog._cancel_sqlite_value_preview()

        assert loading_label.text.startswith("Canceling value preview")
        assert loading_dialog.closed is True
        assert dialog.matching_status_label.text() == "Value preview canceled."
    finally:
        dialog.close()
        cleanup_tabular_load_result(loaded)
