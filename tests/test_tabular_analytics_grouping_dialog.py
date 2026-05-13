from __future__ import annotations

import pandas as pd
import pytest

try:
    from PyQt6.QtWidgets import QApplication
    from modules.tabular_analytics_grouping_dialog import TabularAnalyticsGroupingDialog
except ImportError as exc:  # pragma: no cover - depends on PyQt collection order
    QApplication = None
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
