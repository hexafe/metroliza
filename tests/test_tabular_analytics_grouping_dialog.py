from __future__ import annotations

import time

import pandas as pd
import pytest

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QWidget
    from modules import ui_theme_tokens
    from modules.grouping_filter_core import DataFrameGroupingIndex
    from modules.list_selection_utils import ListSelectionUtils
    from modules.tabular_analytics_service import (
        TabularColumnFilter,
        cleanup_tabular_load_result,
        load_tabular_analytics_file,
    )
    from modules.tabular_analytics_grouping_dialog import TabularAnalyticsGroupingDialog
except ImportError as exc:  # pragma: no cover - depends on PyQt collection order
    Qt = None
    QApplication = None
    QWidget = None
    TabularColumnFilter = None
    DataFrameGroupingIndex = None
    cleanup_tabular_load_result = None
    load_tabular_analytics_file = None
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


def _process_events_until(predicate, *, timeout_ms: int = 1500) -> bool:
    app = _app()
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


def _dialog_for_frame(frame: pd.DataFrame):
    if TabularAnalyticsGroupingDialog is None:
        pytest.skip(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")
    dialog = TabularAnalyticsGroupingDialog.__new__(TabularAnalyticsGroupingDialog)
    dialog.source_dataframe = frame
    dialog.column_labels = {}
    dialog.selector_columns = []
    dialog.selected_selector_keys = set()
    dialog._selector_index = None
    dialog._selector_index_source_frame = None
    dialog._selector_preview_cache = {}
    dialog._applied_selector_filter_text = ""
    dialog.default_group = "POPULATION"
    dialog.default_group_color = ui_theme_tokens.DEFAULT_GROUP_COLOR
    dialog.group_color_column = "GROUP_COLOR"
    dialog.group_palette = ui_theme_tokens.themed_group_palette()
    dialog.sqlite_store = None
    dialog._temp_group_assignments = {}
    dialog._sqlite_assignment_operations = []
    dialog._base_grouping_dataframe_cache = None
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


class _FakeKeyEvent:
    def __init__(self, key):
        self._key = key
        self.accepted = False

    def key(self):
        return self._key

    def accept(self):
        self.accepted = True


def _background_hex(item) -> str:
    return item.background().color().name().upper()


def _item_for_data(list_widget, expected):
    for index in range(list_widget.count()):
        item = list_widget.item(index)
        if item.data(Qt.ItemDataRole.UserRole) == expected:
            return item
    raise AssertionError(f"Missing list item for {expected!r}")


def _select_selector_rows(dialog, start: int, stop: int) -> None:
    dialog.selector_list.blockSignals(True)
    for index in range(start, stop):
        dialog.selector_list.item(index).setSelected(True)
    dialog.selector_list.blockSignals(False)
    dialog._store_current_selection()


def _apply_selector_search(dialog, text: str) -> None:
    dialog.selector_search.setText(text)
    dialog._apply_selector_filter()


def _temporary_groups(dialog) -> dict[int, str]:
    return {
        int(row_id): group_name
        for row_id, (group_name, _color) in dialog._temp_group_assignments.items()
    }


def _temporary_colors(dialog) -> dict[int, str]:
    return {
        int(row_id): color
        for row_id, (_group_name, color) in dialog._temp_group_assignments.items()
    }


def test_selector_search_recognizes_in_expression_without_breaking_plain_search() -> None:
    if TabularAnalyticsGroupingDialog is None:
        pytest.skip(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")

    assert TabularAnalyticsGroupingDialog._looks_like_filter_expression("Part IN (body*, cap)")
    assert TabularAnalyticsGroupingDialog._looks_like_filter_expression(
        "Supplier NOT IN (OTHER, TEST*)"
    )
    assert not TabularAnalyticsGroupingDialog._looks_like_filter_expression("bearing insert")


class _GroupingParent(QWidget if QWidget is not None else object):
    def __init__(self):
        super().__init__()
        self.grouping_frames: list[pd.DataFrame | None] = []
        self.grouping_applied: list[bool] = []

    def set_df_for_grouping(self, frame):
        self.grouping_frames.append(frame)

    def set_grouping_applied(self, applied: bool):
        self.grouping_applied.append(bool(applied))


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


def test_scoped_dataframe_for_applied_filter_is_cached(monkeypatch) -> None:
    dialog = _dialog_for_frame(
        pd.DataFrame(
            {
                "source_row_number": [1, 2, 3, 4],
                "TimeStamp": ["2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04"],
                "Value": [1, 2, 3, 4],
            }
        )
    )
    dialog._applied_selector_filter_text = "TimeStamp >= 2026-05-02 AND Value > 2"
    calls = 0
    original_apply_filter_specs = (
        TabularAnalyticsGroupingDialog._scoped_source_dataframe.__globals__["apply_filter_specs"]
    )

    def spy_apply_filter_specs(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_apply_filter_specs(*args, **kwargs)

    monkeypatch.setitem(
        TabularAnalyticsGroupingDialog._scoped_source_dataframe.__globals__,
        "apply_filter_specs",
        spy_apply_filter_specs,
    )

    first = dialog._scoped_source_dataframe()
    second = dialog._scoped_source_dataframe()
    dialog.selector_columns = ["TimeStamp", "Value"]
    dialog._current_selector_index()
    dialog._current_selector_index()

    assert first is second
    assert first["source_row_number"].tolist() == [3, 4]
    assert calls == 1


def test_apply_selector_filter_refreshes_selector_scope_without_full_refresh() -> None:
    dialog = _dialog_for_frame(
        pd.DataFrame(
            {
                "source_row_number": [1],
                "Value": [1],
            }
        )
    )

    class _Search:
        def text(self):
            return "Value > 0"

    calls: list[object] = []
    dialog.selector_search = _Search()
    dialog._refresh_all = lambda *args, **kwargs: calls.append("full-refresh")
    dialog._refresh_selectors = lambda *args, **kwargs: calls.append("selectors")
    dialog._sync_status = lambda **kwargs: calls.append(("status", kwargs))

    dialog._apply_selector_filter()

    assert dialog._applied_selector_filter_text == "Value > 0"
    assert "full-refresh" not in calls
    assert calls == [
        "selectors",
        ("status", {"recompute_counts": False, "recompute_scope": True}),
    ]


def test_dataframe_grouping_index_caches_row_ids_by_selected_keys() -> None:
    if DataFrameGroupingIndex is None:
        pytest.skip(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")
    index = DataFrameGroupingIndex(
        pd.DataFrame(
            {
                "source_row_number": [1, 2, 3, 4],
                "line": ["L1", "L1", "L2", "L1"],
                "station": ["A", "B", "A", "A"],
            }
        ),
        ("line", "station"),
    )

    assert index.row_ids_for_keys({("L1", "A")}) == [1, 4]
    assert index.row_ids_by_key({("L1", "A"), ("L2", "A")}) == {
        ("L1", "A"): (1, 4),
        ("L2", "A"): (3,),
    }
    assert index.row_ids_for_keys({("missing", "A")}) == []


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
    assert grouping_frame["GROUP_COLOR"].tolist() == ["#FFFFFF", "#FFFFFF"]


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
    dialog._rebuild_preserving_groups = lambda: None
    dialog._refresh_all = lambda: None

    dialog._after_selector_columns_removed(previous_columns=("tracecode", "cavity", "fixture"))

    assert dialog.selected_selector_keys == {("TC-001", "F1"), ("TC-002", "F2")}


def test_grouping_dialog_column_panes_are_tall_enough_for_multiple_columns() -> None:
    app = _app()
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
        dialog.show()
        app.processEvents()
        app.processEvents()
        assert dialog.available_columns_list.minimumHeight() >= 120
        assert dialog.selected_columns_list.minimumHeight() >= 120
        assert dialog.available_columns_list.height() >= 120
        assert dialog.selected_columns_list.height() >= 120
        assert dialog.selector_list.minimumHeight() >= 80
    finally:
        dialog.close()


def test_grouping_dialog_uses_double_click_column_selection_without_action_buttons() -> None:
    _app()
    dialog = TabularAnalyticsGroupingDialog(
        dataframe=pd.DataFrame(
            {
                "source_row_number": [1, 2],
                "tracecode": ["TC-001", "TC-002"],
                "cavity": ["C1", "C2"],
            }
        )
    )
    try:
        button_texts = {button.text() for button in dialog.findChildren(QPushButton)}
        assert not hasattr(dialog, "add_column_button")
        assert not hasattr(dialog, "remove_column_button")
        assert not hasattr(dialog, "clear_columns_button")
        assert {"Add column", "Remove selected column", "Clear columns"}.isdisjoint(button_texts)
        assert "Create or add" not in button_texts
        assert "Assign all filtered rows..." in button_texts
        assert "Assign selected row values..." in button_texts
        assert "Add filter row" not in button_texts
        assert "Clear scope filters" not in button_texts
        assert not hasattr(dialog, "add_scope_filter_button")
        assert not hasattr(dialog, "clear_scope_filters_button")
        assert dialog.selector_search.placeholderText() == (
            "Search values or filter, e.g. Supplier=SUPPLIER AND Value > 1"
        )
        assert dialog.create_group_button.accessibleName() == (
            "Assign selected CSV row values to a CSV analytics group"
        )
        assert dialog.assign_filtered_rows_button.accessibleName() == (
            "Assign all rows matching current search or filter"
        )
        action_buttons = (
            dialog.assign_filtered_rows_button,
            dialog.create_group_button,
            dialog.rename_group_button,
            dialog.delete_group_button,
            dialog.clear_selection_button,
            dialog.dont_use_grouping_button,
            dialog.use_grouping_button,
        )
        assert [button.isDefault() for button in action_buttons] == [False] * len(action_buttons)
        assert [button.autoDefault() for button in action_buttons] == [False] * len(action_buttons)
        assert dialog.previous_page_button.accessibleName() == "Previous matching rows page"
        assert dialog.selector_page_label.accessibleName() == "Matching rows page"

        trace_item = _item_for_data(dialog.available_columns_list, "tracecode")
        dialog.available_columns_list.setCurrentItem(trace_item)
        dialog.available_columns_list.itemDoubleClicked.emit(trace_item)

        assert dialog.selector_columns == ["tracecode"]

        selected_item = _item_for_data(dialog.selected_columns_list, "tracecode")
        dialog.selected_columns_list.setCurrentItem(selected_item)
        dialog.selected_columns_list.itemDoubleClicked.emit(selected_item)

        assert dialog.selector_columns == []
    finally:
        dialog.close()


def test_sqlite_grouping_dialog_uses_preview_rows_and_sparse_assignments(tmp_path) -> None:
    _app()
    input_file = tmp_path / "grouping.csv"
    pd.DataFrame(
        {
            "Line": ["A", "B", "A", "B"],
            "Station": ["S1", "S1", "S2", "S2"],
            "Length mm": [10.0, 10.2, 10.4, 10.6],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)

    dialog = TabularAnalyticsGroupingDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
        sqlite_store=loaded.sqlite_store,
    )
    try:
        assert dialog.df.empty

        line_item = _item_for_data(dialog.available_columns_list, "line")
        dialog.available_columns_list.setCurrentItem(line_item)
        dialog.add_selector_column()

        assert dialog.selector_columns == ["line"]
        assert dialog.selector_list.count() == 2
        a_item = _item_for_data(dialog.selector_list, ("A",))
        dialog.selector_list.setCurrentItem(a_item)
        a_item.setSelected(True)
        dialog._store_current_selection()
        dialog.create_group(initial_group_name="Line A")

        assert dialog.df.empty
        assert _temporary_groups(dialog) == {}
        assert [operation.kind for operation in dialog._sqlite_assignment_operations] == ["scope"]
        first_operation = dialog._sqlite_assignment_operations[0]
        assert first_operation.scope is not None
        assert first_operation.scope.selected_group_keys == (("A",),)
        group_labels = {
            dialog.groups_list.item(index).text()
            for index in range(dialog.groups_list.count())
        }
        assert group_labels == {"POPULATION (n=2)", "Line A (n=2)"}

        b_item = _item_for_data(dialog.selector_list, ("B",))
        dialog.selector_list.setCurrentItem(b_item)
        b_item.setSelected(True)
        dialog._store_current_selection()
        dialog.create_group(initial_group_name="Line B")

        assert _temporary_groups(dialog) == {}
        assert [operation.kind for operation in dialog._sqlite_assignment_operations] == [
            "scope",
            "scope",
        ]
        group_labels = {
            dialog.groups_list.item(index).text()
            for index in range(dialog.groups_list.count())
        }
        assert group_labels == {"Line A (n=2)", "Line B (n=2)"}

        materialized = dialog._materialize_grouping_dataframe()
        assert materialized["REPORT_ID"].tolist() == [1, 2, 3, 4]
        assert materialized["GROUP"].tolist() == ["Line A", "Line B", "Line A", "Line B"]
    finally:
        dialog.close()
        cleanup_tabular_load_result(loaded)


def test_sqlite_grouping_dialog_loads_large_multi_column_preview_async(tmp_path) -> None:
    _app()
    input_file = tmp_path / "grouping_async.csv"
    pd.DataFrame(
        {
            "Line": ["A", "B", "A", "B"],
            "Station": ["S1", "S1", "S2", "S2"],
            "Length mm": [10.0, 10.2, 10.4, 10.6],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)
    object.__setattr__(loaded.sqlite_store, "row_count", 300_000)

    dialog = TabularAnalyticsGroupingDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
        sqlite_store=loaded.sqlite_store,
    )
    try:
        dialog.selector_columns = ["line", "station"]
        dialog._refresh_selectors()

        assert dialog.selector_preview_label.text() == "Loading matching groups..."
        assert _process_events_until(lambda: dialog.selector_list.count() == 4)
        assert dialog._selector_total_rows == 4
        assert dialog.selector_preview_label.text() == "Showing 4 matching group(s)."
    finally:
        dialog.close()
        cleanup_tabular_load_result(loaded)


def test_grouping_parent_is_updated_only_after_use_grouping() -> None:
    _app()
    parent = _GroupingParent()
    dialog = TabularAnalyticsGroupingDialog(
        parent,
        dataframe=pd.DataFrame(
            {
                "source_row_number": [1, 2, 3],
                "tracecode": ["TC-001", "TC-002", "TC-003"],
                "length_mm": [1.0, 2.0, 3.0],
            }
        ),
    )
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        _select_selector_rows(dialog, 0, 2)
        dialog.create_group(initial_group_name="Fixture A")

        assert parent.grouping_frames == []
        assert parent.grouping_applied == []
        assert dialog.df.empty
        assert _temporary_groups(dialog) == {1: "Fixture A", 2: "Fixture A"}

        dialog.use_grouping()

        assert parent.grouping_applied == [True]
        materialized = parent.grouping_frames[0]
        assert materialized["GROUP"].tolist() == ["Fixture A", "Fixture A", "POPULATION"]
        assert dialog.df is materialized
    finally:
        dialog.close()
        parent.close()


def test_sqlite_use_grouping_materializes_sparse_temp_assignments(tmp_path) -> None:
    _app()
    input_file = tmp_path / "sqlite_use_grouping.csv"
    pd.DataFrame(
        {
            "Line": ["A", "B", "A"],
            "TraceCode": ["TC-001", "TC-002", "TC-003"],
            "Length mm": [10.0, 10.1, 10.2],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)
    parent = _GroupingParent()
    dialog = TabularAnalyticsGroupingDialog(
        parent,
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
        sqlite_store=loaded.sqlite_store,
    )
    try:
        dialog.selector_columns = ["line"]
        dialog._selector_index = None
        dialog._refresh_all()
        a_item = _item_for_data(dialog.selector_list, ("A",))
        dialog.selector_list.setCurrentItem(a_item)
        a_item.setSelected(True)
        dialog._store_current_selection()
        dialog.create_group(initial_group_name="Line A")

        assert parent.grouping_frames == []
        assert dialog.df.empty
        assert _temporary_groups(dialog) == {}
        assert [operation.kind for operation in dialog._sqlite_assignment_operations] == ["scope"]
        assert dialog._sqlite_assignment_operations[0].scope is not None
        assert dialog._sqlite_assignment_operations[0].scope.selected_group_keys == (("A",),)

        dialog.use_grouping()

        materialized = parent.grouping_frames[0]
        assert parent.grouping_applied == [True]
        assert materialized["REPORT_ID"].tolist() == [1, 3]
        assert materialized["GROUP"].tolist() == ["Line A", "Line A"]
    finally:
        dialog.close()
        parent.close()
        cleanup_tabular_load_result(loaded)


def test_clear_grouping_discards_temporary_assignments_without_materializing() -> None:
    _app()
    parent = _GroupingParent()
    dialog = TabularAnalyticsGroupingDialog(
        parent,
        dataframe=pd.DataFrame(
            {
                "source_row_number": [1, 2],
                "tracecode": ["TC-001", "TC-002"],
            }
        ),
    )
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        _select_selector_rows(dialog, 0, 1)
        dialog.create_group(initial_group_name="Fixture A")

        dialog.dont_use_grouping()

        assert dialog._temp_group_assignments == {}
        assert dialog.df.empty
        assert parent.grouping_frames == [None]
        assert parent.grouping_applied == [False]
    finally:
        dialog.close()
        parent.close()


def test_sqlite_source_filters_do_not_narrow_group_counts(tmp_path) -> None:
    _app()
    input_file = tmp_path / "filtered_group_counts.csv"
    pd.DataFrame(
        {
            "Line": ["A", "B", "A", "B"],
            "Station": ["S1", "S1", "S2", "S2"],
            "Length mm": [10.0, 10.2, 10.4, 10.6],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)
    existing_grouping = pd.DataFrame(
        {
            "REPORT_ID": [2, 4],
            "GROUP": ["Line B", "Line B"],
        }
    )

    dialog = TabularAnalyticsGroupingDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
        grouping_dataframe=existing_grouping,
        sqlite_store=loaded.sqlite_store,
        column_filters=(TabularColumnFilter("line", selected_values=("A",)),),
    )
    try:
        group_labels = {
            dialog.groups_list.item(index).text()
            for index in range(dialog.groups_list.count())
        }

        assert group_labels == {"POPULATION (n=2)", "Line B (n=2)"}
    finally:
        dialog.close()
        cleanup_tabular_load_result(loaded)


def test_sqlite_assign_filtered_rows_combines_parent_and_search_expression(tmp_path) -> None:
    _app()
    input_file = tmp_path / "sqlite_scope_assign.csv"
    pd.DataFrame(
        {
            "Line": ["A", "A", "B", "B"],
            "Supplier": ["SUPPLIER", "SUPPLIER", "OTHER", "SUPPLIER"],
            "TimeStamp": ["2026-04-30", "2026-05-02", "2026-05-03", "2026-05-04"],
            "Value": [1, 2, 1, 2],
            "Value2": [0, 2, 2, 3],
            "TraceCode": ["TC-001", "TC-002", "TC-003", "TC-004"],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)

    dialog = TabularAnalyticsGroupingDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
        sqlite_store=loaded.sqlite_store,
        column_filters=(TabularColumnFilter("line", selected_values=("A",)),),
    )
    try:
        _apply_selector_search(dialog, "Supplier=SUPPLIER AND TimeStamp>2026-05-01 AND Value2>1")

        assert dialog.assign_filtered_rows_button.isEnabled() is True
        assert dialog.selector_preview_label.text() == "Add a grouping column to preview row groups."

        dialog.assign_filtered_rows(initial_group_name="Scoped")
        assert dialog.df.empty
        assert _temporary_groups(dialog) == {}
        assert [operation.kind for operation in dialog._sqlite_assignment_operations] == ["scope"]
        materialized = dialog._materialize_grouping_dataframe()
        assert materialized["REPORT_ID"].tolist() == [2]
        assert materialized["GROUP"].tolist() == ["Scoped"]
    finally:
        dialog.close()
        cleanup_tabular_load_result(loaded)


def test_sqlite_search_expression_filters_preview_and_assigns_all_matching_rows(
    tmp_path,
) -> None:
    _app()
    input_file = tmp_path / "sqlite_expression_selector.csv"
    pd.DataFrame(
        {
            "Line": ["A", "A", "B", "A", "A"],
            "Supplier": ["SUPPLIER", "SUPPLIER", "SUPPLIER", "OTHER", "SUPPLIER"],
            "Part": ["body1", "body-side", "body-other", "cap", "bolt"],
            "Value2": [0, 1, 4, 3, 1],
            "TraceCode": ["TC-001", "TC-002", "TC-003", "TC-004", "TC-005"],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)

    dialog = TabularAnalyticsGroupingDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
        sqlite_store=loaded.sqlite_store,
        column_filters=(TabularColumnFilter("line", selected_values=("A",)),),
    )
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        _apply_selector_search(dialog, "(Part=body* AND Supplier=SUPPLIER) OR Value2>2")

        assert dialog.selector_page_label.text() == "Page 1 of 1"
        assert dialog.selector_preview_label.text() == "Showing 3 matching group(s)."
        assert [
            dialog.selector_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(dialog.selector_list.count())
        ] == [("TC-001",), ("TC-002",), ("TC-004",)]

        dialog.assign_filtered_rows(initial_group_name="Expression")

        assert _temporary_groups(dialog) == {}
        assert [operation.kind for operation in dialog._sqlite_assignment_operations] == ["scope"]
        materialized = dialog._materialize_grouping_dataframe()
        assert materialized["REPORT_ID"].tolist() == [1, 2, 4]
        assert materialized["GROUP"].tolist() == ["Expression", "Expression", "Expression"]
        assert dialog.selected_selector_keys == set()
    finally:
        dialog.close()
        cleanup_tabular_load_result(loaded)


def test_sqlite_search_membership_expression_filters_preview_and_assigns_rows(
    tmp_path,
) -> None:
    _app()
    input_file = tmp_path / "sqlite_membership_selector.csv"
    pd.DataFrame(
        {
            "Line": ["A", "A", "B", "A"],
            "Supplier": ["SUPPLIER", "SUPPLIER", "OTHER", "SUPPLIER"],
            "Part": ["body1", "body-side", "cap", "bolt"],
            "TraceCode": ["TC-001", "TC-002", "TC-003", "TC-004"],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)

    dialog = TabularAnalyticsGroupingDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
        sqlite_store=loaded.sqlite_store,
        column_filters=(TabularColumnFilter("line", selected_values=("A",)),),
    )
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        _apply_selector_search(dialog, "Part IN (body*, cap) AND Supplier IN (SUPPLIER)")

        assert [
            dialog.selector_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(dialog.selector_list.count())
        ] == [("TC-001",), ("TC-002",)]

        dialog.assign_filtered_rows(initial_group_name="Membership")
        materialized = dialog._materialize_grouping_dataframe()
        assert materialized["REPORT_ID"].tolist() == [1, 2]
        assert materialized["GROUP"].tolist() == ["Membership", "Membership"]
    finally:
        dialog.close()
        cleanup_tabular_load_result(loaded)


def test_sqlite_assign_filtered_rows_defers_row_id_expansion_until_materialization(
    tmp_path,
    monkeypatch,
) -> None:
    _app()
    input_file = tmp_path / "sqlite_deferred_scope_assign.csv"
    pd.DataFrame(
        {
            "Line": ["A", "A", "B", "A"],
            "TraceCode": ["MATCH-001", "MATCH-002", "OTHER-003", "MATCH-004"],
            "Length mm": [10.0, 10.1, 10.2, 10.3],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)
    assert loaded.sqlite_store is not None

    def fail_row_id_expansion(*_args, **_kwargs):
        raise AssertionError("assign-all should not eagerly fetch every matching row id")

    store_type = type(loaded.sqlite_store)
    monkeypatch.setattr(store_type, "row_ids", fail_row_id_expansion)
    monkeypatch.setattr(store_type, "row_ids_for_group_search", fail_row_id_expansion)

    dialog = TabularAnalyticsGroupingDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
        sqlite_store=loaded.sqlite_store,
    )
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        _apply_selector_search(dialog, "MATCH")

        dialog.assign_filtered_rows(initial_group_name="Matches")

        assert _temporary_groups(dialog) == {}
        assert [operation.kind for operation in dialog._sqlite_assignment_operations] == ["scope"]
        group_labels = {
            dialog.groups_list.item(index).text()
            for index in range(dialog.groups_list.count())
        }
        assert group_labels == {"POPULATION (n=1)", "Matches (n=3)"}

        materialized = dialog._materialize_grouping_dataframe()
        assert materialized["REPORT_ID"].tolist() == [1, 2, 4]
        assert materialized["GROUP"].tolist() == ["Matches", "Matches", "Matches"]
    finally:
        dialog.close()
        cleanup_tabular_load_result(loaded)


def test_sqlite_create_group_defers_selected_key_row_id_expansion_until_materialization(
    tmp_path,
    monkeypatch,
) -> None:
    _app()
    input_file = tmp_path / "sqlite_deferred_selected_key_assign.csv"
    pd.DataFrame(
        {
            "Line": ["A", "A", "B", "A"],
            "Station": ["S1", "S2", "S1", "S3"],
            "TraceCode": ["TC-001", "TC-002", "TC-003", "TC-004"],
            "Length mm": [10.0, 10.1, 10.2, 10.3],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)
    assert loaded.sqlite_store is not None

    def fail_row_id_expansion(*_args, **_kwargs):
        raise AssertionError("selected-key assignment should not eagerly fetch row ids")

    store_type = type(loaded.sqlite_store)
    monkeypatch.setattr(store_type, "row_ids_for_group_keys", fail_row_id_expansion)

    dialog = TabularAnalyticsGroupingDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
        sqlite_store=loaded.sqlite_store,
    )
    try:
        dialog.selector_columns = ["line"]
        dialog._selector_index = None
        dialog._refresh_all()
        a_item = _item_for_data(dialog.selector_list, ("A",))
        dialog.selector_list.setCurrentItem(a_item)
        a_item.setSelected(True)
        dialog._store_current_selection()

        dialog.create_group(initial_group_name="Line A")

        assert _temporary_groups(dialog) == {}
        assert len(dialog._sqlite_assignment_operations) == 1
        operation = dialog._sqlite_assignment_operations[0]
        assert operation.kind == "scope"
        assert operation.group_name == "Line A"
        assert operation.scope is not None
        assert operation.scope.selector_columns == ("line",)
        assert operation.scope.selected_group_keys == (("A",),)
        assert operation.scope.search_text == ""

        group_item = _item_for_data(dialog.groups_list, "Line A")
        assert _background_hex(group_item) == operation.color.upper()
        assert dialog.group_members_list.count() == 3
        assert [
            dialog.group_members_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(dialog.group_members_list.count())
        ] == [1, 2, 4]

        materialized = dialog._materialize_grouping_dataframe()
        assert materialized["REPORT_ID"].tolist() == [1, 2, 4]
        assert materialized["GROUP"].tolist() == ["Line A", "Line A", "Line A"]
        assert materialized["GROUP_COLOR"].tolist() == [operation.color] * 3
    finally:
        dialog.close()
        cleanup_tabular_load_result(loaded)


def test_delete_and_backspace_remove_focused_selected_grouping_column() -> None:
    app = _app()
    dialog = TabularAnalyticsGroupingDialog(
        dataframe=pd.DataFrame(
            {
                "source_row_number": [1, 2],
                "tracecode": ["TC-001", "TC-002"],
                "cavity": ["C1", "C2"],
            }
        )
    )
    try:
        dialog.selector_columns = ["tracecode", "cavity"]
        dialog._selector_index = None
        dialog._refresh_all()
        dialog.show()
        app.processEvents()

        selected_item = _item_for_data(dialog.selected_columns_list, "tracecode")
        dialog.selected_columns_list.setCurrentItem(selected_item)
        dialog.selected_columns_list.setFocus()
        app.processEvents()

        delete_event = _FakeKeyEvent(Qt.Key.Key_Delete)
        dialog.keyPressEvent(delete_event)

        assert delete_event.accepted is True
        assert dialog.selector_columns == ["cavity"]

        selected_item = _item_for_data(dialog.selected_columns_list, "cavity")
        dialog.selected_columns_list.setCurrentItem(selected_item)
        dialog.selected_columns_list.setFocus()
        app.processEvents()

        backspace_event = _FakeKeyEvent(Qt.Key.Key_Backspace)
        dialog.keyPressEvent(backspace_event)

        assert backspace_event.accepted is True
        assert dialog.selector_columns == []
    finally:
        dialog.close()


def test_matching_rows_pane_removes_bulk_buttons_and_keeps_compact_pagination_row() -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": list(range(1, 1003)),
            "tracecode": [f"TC-{index:04d}" for index in range(1002)],
            "length_mm": [float(index) for index in range(1002)],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        button_texts = {button.text() for button in dialog.findChildren(QPushButton)}
        assert not hasattr(dialog, "select_visible_button")
        assert not hasattr(dialog, "select_all_matching_button")
        assert not hasattr(dialog, "clear_matching_button")
        assert {"Select visible", "Select all matching", "Clear matching"}.isdisjoint(button_texts)
        label_texts = {label.text() for label in dialog.findChildren(QLabel)}
        assert "Grouping columns" not in label_texts
        assert "Grouping-scope filters" not in label_texts
        assert "Match" not in label_texts
        assert button_texts.isdisjoint({"Assign filtered rows...", "Assign to group..."})
        assert "Assign all filtered rows..." in button_texts
        assert "Assign selected row values..." in button_texts

        footer_layout = dialog.layout().itemAt(dialog.layout().count() - 1).layout()
        assign_all_index = footer_layout.indexOf(dialog.assign_filtered_rows_button)
        assign_selected_index = footer_layout.indexOf(dialog.create_group_button)
        assert -1 not in (assign_all_index, assign_selected_index)
        assert assign_all_index < assign_selected_index

        selector_layout = dialog.selector_list.parentWidget().layout()
        paging_layout = selector_layout.itemAt(selector_layout.count() - 1).layout()
        previous_index = paging_layout.indexOf(dialog.previous_page_button)
        label_index = paging_layout.indexOf(dialog.selector_page_label)
        next_index = paging_layout.indexOf(dialog.next_page_button)
        assert -1 not in (previous_index, label_index, next_index)
        assert previous_index < label_index < next_index

        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()

        assert dialog.selector_page_label.text() == "Page 1 of 2"
        assert dialog.selector_preview_label.text() == (
            "Showing 1-1000 of 1002; Assign all filtered rows skips paging."
        )
        assert dialog.previous_page_button.isEnabled() is False
        assert dialog.next_page_button.isEnabled() is True
    finally:
        dialog.close()


def test_matching_rows_paging_controls_stay_below_selector_list_at_constrained_height() -> None:
    app = _app()
    frame = pd.DataFrame(
        {
            "source_row_number": list(range(1, 1003)),
            "tracecode": [f"TC-{index:04d}" for index in range(1002)],
            "length_mm": [float(index) for index in range(1002)],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        dialog.resize(dialog.width(), 520)
        dialog.show()
        app.processEvents()
        app.processEvents()

        selector_rect = dialog.selector_list.geometry()
        paging_rects = [
            widget.geometry()
            for widget in (
                dialog.previous_page_button,
                dialog.selector_page_label,
                dialog.next_page_button,
            )
        ]

        assert all(widget.isVisible() for widget in (
            dialog.previous_page_button,
            dialog.selector_page_label,
            dialog.next_page_button,
        ))
        assert all(rect.height() > 0 and rect.width() > 0 for rect in paging_rects)
        assert all(selector_rect.intersected(rect).isEmpty() for rect in paging_rects)
        assert all(selector_rect.bottom() < rect.top() for rect in paging_rects)
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
        _select_selector_rows(dialog, 0, 2)

        assert ("TC-1000",) in dialog.selected_selector_keys
        assert ("TC-1001",) in dialog.selected_selector_keys
        dialog.previous_selector_page()
        assert ("TC-1000",) in dialog.selected_selector_keys
        dialog.next_selector_page()
        assert dialog.selector_list.item(0).isSelected() is True
        assert dialog.selector_list.item(1).isSelected() is True
    finally:
        dialog.close()


def test_assign_all_filtered_rows_uses_plain_search_across_pages() -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": list(range(1, 2506)),
            "tracecode": [
                f"MATCH-{index:04d}" if index < 1500 else f"OTHER-{index:04d}"
                for index in range(2505)
            ],
            "length_mm": [float(index) for index in range(2505)],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        _apply_selector_search(dialog, "MATCH")

        assert dialog.selector_page_label.text() == "Page 1 of 2"
        assert dialog.selector_list.item(0).data(Qt.ItemDataRole.UserRole) == ("MATCH-0000",)
        assert dialog.assign_filtered_rows_button.isEnabled() is True

        dialog.assign_filtered_rows(initial_group_name="Matched values")

        grouped = [
            row_id
            for row_id, group_name in sorted(_temporary_groups(dialog).items())
            if group_name == "Matched values"
        ]
        assert grouped == list(range(1, 1501))
        assert dialog.selector_page_label.text() == "Page 1 of 2"
        assert dialog.selected_selector_keys == set()
    finally:
        dialog.close()


def test_selector_search_waits_for_explicit_apply() -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3],
            "tracecode": ["MATCH-1", "OTHER-1", "MATCH-2"],
            "length_mm": [1.0, 2.0, 3.0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()

        dialog.selector_search.setText("MATCH")

        assert dialog.selector_list.count() == 3
        assert dialog.selector_preview_label.text() == "Showing 3 matching group(s)."

        dialog._apply_selector_filter()

        assert dialog.selector_list.count() == 2
        assert [
            dialog.selector_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(dialog.selector_list.count())
        ] == [("MATCH-1",), ("MATCH-2",)]
    finally:
        dialog.close()


def test_selector_filter_does_not_clear_temporary_assignments() -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3],
            "tracecode": ["MATCH-1", "OTHER-1", "MATCH-2"],
            "length_mm": [1.0, 2.0, 3.0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        _select_selector_rows(dialog, 0, 1)
        dialog.create_group(initial_group_name="Matched")

        _apply_selector_search(dialog, "OTHER")

        assert _temporary_groups(dialog) == {1: "Matched"}
        assert dialog.selector_list.count() == 1
        assert dialog.selector_list.item(0).data(Qt.ItemDataRole.UserRole) == ("OTHER-1",)
    finally:
        dialog.close()


def test_enter_in_selector_search_applies_empty_filter_without_group_shortcut() -> None:
    app = _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3],
            "tracecode": ["MATCH-1", "OTHER-1", "MATCH-2"],
            "length_mm": [1.0, 2.0, 3.0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        _apply_selector_search(dialog, "MATCH")
        assert dialog.selector_list.count() == 2

        dialog.show()
        app.processEvents()
        dialog.selector_search.setText("")
        dialog.selector_search.setFocus()
        app.processEvents()

        enter_event = _FakeKeyEvent(Qt.Key.Key_Return)
        dialog.keyPressEvent(enter_event)

        assert enter_event.accepted is True
        assert dialog._applied_selector_filter_text == ""
        assert dialog.selector_list.count() == 3
        assert dialog._temp_group_assignments == {}
    finally:
        dialog.close()


def test_selection_change_does_not_recount_matching_rows(monkeypatch) -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3],
            "tracecode": ["TC-001", "TC-002", "TC-003"],
            "length_mm": [1.0, 2.0, 3.0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()

        monkeypatch.setattr(
            dialog,
            "_current_selector_index",
            lambda: (_ for _ in ()).throw(AssertionError("selection should not recount")),
        )
        dialog.selector_list.item(0).setSelected(True)
        dialog._store_current_selection()

        assert dialog.selected_selector_keys == {("TC-001",)}
        assert dialog.selector_status_label.text() == "tracecode: 1 selected group(s)"
    finally:
        dialog.close()


def test_selector_navigation_supports_first_last_and_page_jump() -> None:
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

        assert dialog.selector_page_label.text() == "Page 1 of 3"
        dialog.last_selector_page()
        assert dialog.selector_page_label.text() == "Page 3 of 3"
        assert dialog.next_page_button.isEnabled() is False
        dialog.first_selector_page()
        assert dialog.selector_page_label.text() == "Page 1 of 3"
        assert dialog.previous_page_button.isEnabled() is False

        dialog.page_jump_input.setText("2")
        dialog.jump_selector_page()
        assert dialog.selector_page_label.text() == "Page 2 of 3"

        dialog.page_jump_input.setText("99")
        dialog.jump_selector_page()
        assert dialog.selector_page_label.text() == "Page 3 of 3"
    finally:
        dialog.close()


def test_standard_selection_can_group_rows_on_later_page() -> None:
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

        _select_selector_rows(dialog, 0, dialog.selector_list.count())

        assert len(dialog.selected_selector_keys) == 500
        assert dialog._row_ids_for_selected_keys() == list(range(1001, 1501))
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
        _select_selector_rows(dialog, 0, dialog.selector_list.count())

        dialog.create_group(initial_group_name="Paged group")

        grouped = [
            row_id
            for row_id, group_name in sorted(_temporary_groups(dialog).items())
            if group_name == "Paged group"
        ]
        assert grouped == list(range(1001, 1501))
        assert dialog.groups_list.currentItem().data(Qt.ItemDataRole.UserRole) == "Paged group"
    finally:
        dialog.close()


def test_search_expression_filters_preview_and_assign_all_rows() -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3, 4, 5],
            "tracecode": ["TC-001", "TC-002", "TC-003", "TC-004", "TC-005"],
            "value": [1, 1, 2, "x", None],
            "value2": [0, 2, 2, "x", 0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        _apply_selector_search(dialog, "value=1 AND value2>1")

        assert dialog.selector_list.count() == 1
        assert dialog.selector_list.item(0).data(Qt.ItemDataRole.UserRole) == ("TC-002",)
        assert dialog.selector_preview_label.text() == "Showing 1 matching group(s)."
        assert dialog.assign_filtered_rows_button.isEnabled() is True

        dialog.assign_filtered_rows(initial_group_name="Expression")
        assert _temporary_groups(dialog) == {2: "Expression"}
    finally:
        dialog.close()


def test_search_membership_expression_filters_preview_and_assign_all_rows() -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3, 4, 5],
            "tracecode": ["TC-001", "TC-002", "TC-003", "TC-004", "TC-005"],
            "part": ["body1", "cap", "body-side", "nut", "gear"],
            "value2": [0, 2, 3, "x", 0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        _apply_selector_search(dialog, "part IN (body*, cap)")

        assert [
            dialog.selector_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(dialog.selector_list.count())
        ] == [("TC-001",), ("TC-002",), ("TC-003",)]

        dialog.assign_filtered_rows(initial_group_name="Membership")
        assert _temporary_groups(dialog) == {1: "Membership", 2: "Membership", 3: "Membership"}
    finally:
        dialog.close()


def test_invalid_search_expression_disables_assign_all_and_preview() -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3, 4],
            "TraceCode": ["TC-001", "TC-002", "TC-003", "TC-004"],
            "Supplier": ["SUPPLIER", "SUPPLIER", "OTHER", "SUPPLIER"],
            "TimeStamp": ["2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04"],
            "Value2": [2, 2, 3, 0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        dialog.selector_columns = ["TraceCode"]
        dialog._selector_index = None
        dialog._refresh_all()
        _apply_selector_search(dialog, "MissingColumn=SUPPLIER")

        assert dialog.selector_list.count() == 0
        assert dialog.selector_preview_label.text().startswith("Invalid filter:")
        assert dialog.selector_page_label.text() == "Page 0 of 0"
        assert dialog.assign_filtered_rows_button.isEnabled() is False
    finally:
        dialog.close()


def test_create_or_add_prompts_each_time_so_second_group_can_be_created(monkeypatch) -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3],
            "tracecode": ["TC-001", "TC-002", "TC-003"],
            "length_mm": [1.0, 2.0, 3.0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    responses = iter([("Fixture A", True), ("Fixture B", True)])
    monkeypatch.setattr(
        "modules.tabular_analytics_grouping_dialog.QInputDialog.getText",
        lambda *_args, **_kwargs: next(responses),
    )
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()

        _select_selector_rows(dialog, 0, 1)
        dialog.create_group_button.click()
        assert dialog.groups_list.currentItem().data(Qt.ItemDataRole.UserRole) == "Fixture A"

        _select_selector_rows(dialog, 1, 2)
        dialog.create_group_button.click()

        assignments = _temporary_groups(dialog)
        assert assignments == {1: "Fixture A", 2: "Fixture B"}
        colors = _temporary_colors(dialog)
        assert colors[1] != dialog.default_group_color
        assert colors[2] != dialog.default_group_color
        assert colors[1] != colors[2]
    finally:
        dialog.close()


def test_create_group_prefills_prompt_with_selected_custom_group(monkeypatch) -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3],
            "tracecode": ["TC-001", "TC-002", "TC-003"],
            "length_mm": [1.0, 2.0, 3.0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    prompt_defaults: list[str | None] = []

    def capture_prompt(*_args, **kwargs):
        prompt_defaults.append(kwargs.get("text"))
        return "", False

    monkeypatch.setattr(
        "modules.tabular_analytics_grouping_dialog.QInputDialog.getText",
        capture_prompt,
    )
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        _select_selector_rows(dialog, 0, 1)
        dialog.create_group(initial_group_name="Fixture A")

        fixture_item = next(
            dialog.groups_list.item(index)
            for index in range(dialog.groups_list.count())
            if dialog.groups_list.item(index).data(Qt.ItemDataRole.UserRole) == "Fixture A"
        )
        dialog.groups_list.setCurrentItem(fixture_item)
        _select_selector_rows(dialog, 1, 2)

        dialog.create_group()

        assert prompt_defaults == ["Fixture A"]
    finally:
        dialog.close()


@pytest.mark.parametrize("selected_group_name", [None, "POPULATION", ""])
def test_create_group_does_not_prefill_prompt_for_default_or_blank_selection(
    monkeypatch,
    selected_group_name,
) -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2],
            "tracecode": ["TC-001", "TC-002"],
            "length_mm": [1.0, 2.0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    prompt_defaults: list[str | None] = []

    def capture_prompt(*_args, **kwargs):
        prompt_defaults.append(kwargs.get("text"))
        return "", False

    monkeypatch.setattr(
        "modules.tabular_analytics_grouping_dialog.QInputDialog.getText",
        capture_prompt,
    )
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        _select_selector_rows(dialog, 0, 1)
        if selected_group_name is None:
            dialog.groups_list.setCurrentItem(None)
        else:
            monkeypatch.setattr(dialog, "_selected_group_name", lambda: selected_group_name)

        dialog.create_group()

        assert prompt_defaults == [""]
    finally:
        dialog.close()


def test_assign_filtered_rows_prefills_prompt_with_selected_custom_group(monkeypatch) -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3],
            "tracecode": ["TC-001", "TC-002", "TC-003"],
            "length_mm": [1.0, 2.0, 3.0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    prompt_defaults: list[str | None] = []

    def capture_prompt(*_args, **kwargs):
        prompt_defaults.append(kwargs.get("text"))
        return "", False

    monkeypatch.setattr(
        "modules.tabular_analytics_grouping_dialog.QInputDialog.getText",
        capture_prompt,
    )
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        _select_selector_rows(dialog, 0, 1)
        dialog.create_group(initial_group_name="Fixture A")

        fixture_item = next(
            dialog.groups_list.item(index)
            for index in range(dialog.groups_list.count())
            if dialog.groups_list.item(index).data(Qt.ItemDataRole.UserRole) == "Fixture A"
        )
        dialog.groups_list.setCurrentItem(fixture_item)

        dialog.assign_filtered_rows()

        assert prompt_defaults == ["Fixture A"]
    finally:
        dialog.close()


@pytest.mark.parametrize("selected_group_name", [None, "POPULATION", ""])
def test_assign_filtered_rows_does_not_prefill_prompt_for_default_or_blank_selection(
    monkeypatch,
    selected_group_name,
) -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2],
            "tracecode": ["TC-001", "TC-002"],
            "length_mm": [1.0, 2.0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    prompt_defaults: list[str | None] = []

    def capture_prompt(*_args, **kwargs):
        prompt_defaults.append(kwargs.get("text"))
        return "", False

    monkeypatch.setattr(
        "modules.tabular_analytics_grouping_dialog.QInputDialog.getText",
        capture_prompt,
    )
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        if selected_group_name is None:
            dialog.groups_list.setCurrentItem(None)
        else:
            monkeypatch.setattr(dialog, "_selected_group_name", lambda: selected_group_name)

        dialog.assign_filtered_rows()

        assert prompt_defaults == [""]
    finally:
        dialog.close()


def test_population_group_is_hidden_when_all_rows_are_assigned() -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3],
            "tracecode": ["TC-001", "TC-002", "TC-003"],
            "length_mm": [1.0, 2.0, 3.0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()

        _select_selector_rows(dialog, 0, 2)
        dialog.create_group(initial_group_name="Fixture A")
        assert {
            dialog.groups_list.item(index).text()
            for index in range(dialog.groups_list.count())
        } == {"POPULATION (n=1)", "Fixture A (n=2)"}

        _select_selector_rows(dialog, 2, 3)
        dialog.create_group(initial_group_name="Fixture B")

        assert {
            dialog.groups_list.item(index).text()
            for index in range(dialog.groups_list.count())
        } == {"Fixture A (n=2)", "Fixture B (n=1)"}
    finally:
        dialog.close()


def test_enter_in_matching_rows_opens_group_prompt_and_assigns_rows(monkeypatch) -> None:
    app = _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3],
            "tracecode": ["TC-001", "TC-002", "TC-003"],
            "length_mm": [1.0, 2.0, 3.0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    monkeypatch.setattr(
        "modules.tabular_analytics_grouping_dialog.QInputDialog.getText",
        lambda *_args, **_kwargs: ("Fixture A", True),
    )
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        dialog.show()
        app.processEvents()

        _select_selector_rows(dialog, 0, 2)
        dialog.selector_list.setFocus()
        app.processEvents()

        enter_event = _FakeKeyEvent(Qt.Key.Key_Return)
        dialog.keyPressEvent(enter_event)

        assert enter_event.accepted is True
        assert _temporary_groups(dialog) == {1: "Fixture A", 2: "Fixture A"}
    finally:
        dialog.close()


def test_double_click_matching_rows_opens_group_prompt_and_assigns_selection(monkeypatch) -> None:
    app = _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3],
            "tracecode": ["TC-001", "TC-002", "TC-003"],
            "length_mm": [1.0, 2.0, 3.0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    monkeypatch.setattr(
        "modules.tabular_analytics_grouping_dialog.QInputDialog.getText",
        lambda *_args, **_kwargs: ("Fixture A", True),
    )
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        dialog.show()
        app.processEvents()

        _select_selector_rows(dialog, 0, 2)
        dialog.selector_list.itemDoubleClicked.emit(dialog.selector_list.item(1))

        assert _temporary_groups(dialog) == {1: "Fixture A", 2: "Fixture A"}
    finally:
        dialog.close()


def test_double_click_group_item_opens_rename_prompt(monkeypatch) -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3],
            "tracecode": ["TC-001", "TC-002", "TC-003"],
            "length_mm": [1.0, 2.0, 3.0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        dialog.selected_selector_keys = {("TC-001",)}
        dialog.create_group(initial_group_name="Fixture A")
        monkeypatch.setattr(
            "modules.tabular_analytics_grouping_dialog.QInputDialog.getText",
            lambda *_args, **_kwargs: ("Fixture B", True),
        )

        group_item = next(
            dialog.groups_list.item(index)
            for index in range(dialog.groups_list.count())
            if dialog.groups_list.item(index).data(Qt.ItemDataRole.UserRole) == "Fixture A"
        )
        dialog.groups_list.setCurrentItem(group_item)
        dialog.groups_list.itemDoubleClicked.emit(group_item)

        assignments = _temporary_groups(dialog)
        assert assignments[1] == "Fixture B"
        assert "Fixture B" in {
            dialog.groups_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(dialog.groups_list.count())
        }
    finally:
        dialog.close()


def test_delete_key_on_group_list_confirms_and_deletes_custom_group(monkeypatch) -> None:
    app = _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3],
            "tracecode": ["TC-001", "TC-002", "TC-003"],
            "length_mm": [1.0, 2.0, 3.0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    monkeypatch.setattr(
        "modules.tabular_analytics_grouping_dialog.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        dialog.show()
        app.processEvents()

        dialog.selected_selector_keys = {("TC-001",), ("TC-002",)}
        dialog.create_group(initial_group_name="Fixture A")
        group_item = next(
            dialog.groups_list.item(index)
            for index in range(dialog.groups_list.count())
            if dialog.groups_list.item(index).data(Qt.ItemDataRole.UserRole) == "Fixture A"
        )
        dialog.groups_list.setCurrentItem(group_item)
        dialog.groups_list.setFocus()
        app.processEvents()

        delete_event = _FakeKeyEvent(Qt.Key.Key_Delete)
        dialog.keyPressEvent(delete_event)

        assert delete_event.accepted is True
        assert _temporary_groups(dialog) == {}
    finally:
        dialog.close()


def test_delete_key_on_group_members_removes_selected_rows_from_group() -> None:
    app = _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3],
            "tracecode": ["TC-001", "TC-002", "TC-003"],
            "length_mm": [1.0, 2.0, 3.0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()
        dialog.show()
        app.processEvents()

        dialog.selected_selector_keys = {("TC-001",), ("TC-002",)}
        dialog.create_group(initial_group_name="Fixture A")
        member_item = dialog.group_members_list.item(0)
        member_item.setSelected(True)
        dialog.group_members_list.setFocus()
        app.processEvents()

        delete_event = _FakeKeyEvent(Qt.Key.Key_Delete)
        dialog.keyPressEvent(delete_event)

        assert delete_event.accepted is True
        assert _temporary_groups(dialog) == {2: "Fixture A"}
    finally:
        dialog.close()


def test_add_to_existing_group_reuses_color_and_refreshes_colored_panes() -> None:
    _app()
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3],
            "tracecode": ["TC-001", "TC-002", "TC-003"],
            "length_mm": [1.0, 2.0, 3.0],
        }
    )
    dialog = TabularAnalyticsGroupingDialog(dataframe=frame)
    try:
        dialog.selector_columns = ["tracecode"]
        dialog._selector_index = None
        dialog._refresh_all()

        dialog.selected_selector_keys = {("TC-001",)}
        dialog.create_group(initial_group_name="Fixture A")
        group_color = _temporary_colors(dialog)[1]

        dialog.selected_selector_keys = {("TC-002",)}
        dialog._refresh_selectors()
        dialog.create_group(initial_group_name="Fixture A")

        grouped = _temporary_groups(dialog)
        assert grouped == {1: "Fixture A", 2: "Fixture A"}
        assert set(_temporary_colors(dialog).values()) == {group_color}
        assert dialog.selected_selector_keys == set()
        assert dialog.selector_list.selectedItems() == []

        selector_colors = {
            dialog.selector_list.item(index).data(Qt.ItemDataRole.UserRole): _background_hex(
                dialog.selector_list.item(index)
            )
            for index in range(dialog.selector_list.count())
        }
        assert selector_colors[("TC-001",)] == group_color.upper()
        assert selector_colors[("TC-002",)] == group_color.upper()
        assert selector_colors[("TC-003",)] == dialog.default_group_color.upper()

        group_colors = {
            dialog.groups_list.item(index).data(Qt.ItemDataRole.UserRole): _background_hex(
                dialog.groups_list.item(index)
            )
            for index in range(dialog.groups_list.count())
        }
        assert group_colors["Fixture A"] == group_color.upper()
        assert group_colors["POPULATION"] == dialog.default_group_color.upper()

        assert dialog.group_members_list.count() == 2
        assert {
            _background_hex(dialog.group_members_list.item(index))
            for index in range(dialog.group_members_list.count())
        } == {group_color.upper()}
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
    assignments = dialog._group_assignments(
        pd.DataFrame(
            {
                "REPORT_ID": [1, 3],
                "GROUP": ["Fixture A", "Fixture B"],
                "GROUP_COLOR": ["#ABCDEF", "#FEDCBA"],
            }
        )
    )

    dialog._apply_group_assignments(assignments)

    assert _temporary_groups(dialog) == {1: "Fixture A", 3: "Fixture B"}
    assert _temporary_colors(dialog) == {1: "#ABCDEF", 3: "#FEDCBA"}

    materialized = dialog._materialize_grouping_dataframe()
    assert materialized["GROUP"].tolist() == ["Fixture A", "POPULATION", "Fixture B"]
    assert materialized["GROUP_COLOR"].tolist() == ["#ABCDEF", "#FFFFFF", "#FEDCBA"]
