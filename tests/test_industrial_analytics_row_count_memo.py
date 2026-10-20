"""The CSV Summary filtered row count is computed once per load result and filter state."""

from __future__ import annotations

import dataclasses

import pytest

try:
    from PyQt6.QtWidgets import QApplication

    from metroliza.ui.industrial_analytics_dialog import IndustrialAnalyticsDialog
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QApplication = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None

from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.industrial_tabular_bridge import load_industrial_cache_tabular_result
from metroliza.tabular.tabular_analytics_service import (
    TabularColumnFilter,
    TabularSqliteStore,
    cleanup_tabular_load_result,
)

pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 analytics dialog widgets are not available: {PYQT_IMPORT_ERROR}",
)

_QT_APP = None


def _app():
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


@pytest.fixture()
def cache_db(tmp_path):
    db_file = str(tmp_path / "industrial.sqlite")
    repository = IndustrialDataRepository(db_file)
    profile = repository.upsert_source_profile(
        profile_key="line_a", profile_name="Line A", source_db_alias="prod_a",
        database_type="mssql", source_object_name="measurements",
    )
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=(
            {
                "source_record_key": f"row-{index}",
                "process_timestamp": f"2026-06-01T10:{index:02d}:00Z",
                "reference": f"REF-{index % 3}",
                "length_mm": str(10 + index),
                "fixture": ("F1", "F2")[index % 2],
            }
            for index in range(12)
        ),
    )
    return db_file


@pytest.fixture()
def count_calls(monkeypatch):
    calls = []
    original = TabularSqliteStore.count_rows

    def counting(self, **kwargs):
        calls.append(kwargs)
        return original(self, **kwargs)

    monkeypatch.setattr(TabularSqliteStore, "count_rows", counting)
    return calls


def _dialog(cache_db, loaded, presentation_mode="industrial_cache"):
    return IndustrialAnalyticsDialog(
        None, db_file=cache_db, source_kind="tabular_file", tabular_load_result=loaded,
        input_file=cache_db, presentation_mode=presentation_mode,
    )


def test_unfiltered_industrial_dialog_construction_issues_no_count_query(cache_db, count_calls):
    _app()
    loaded = load_industrial_cache_tabular_result(cache_db)
    dialog = _dialog(cache_db, loaded)
    try:
        dialog.show()
        _app().processEvents()
        assert dialog._tabular_filtered_row_count() == 12
        assert dialog._tabular_filter_summary() == ("All rows (12)", "neutral")
        # The unfiltered count is the row count the bridge established for the same scope.
        assert loaded.sqlite_store.count_rows() == 12
        assert len(count_calls) == 1  # only the explicit check above
    finally:
        dialog.close()
        cleanup_tabular_load_result(dialog.tabular_load_result)


def test_filtered_state_is_counted_once_and_recounted_after_any_filter_change(cache_db, count_calls):
    _app()
    loaded = load_industrial_cache_tabular_result(cache_db)
    dialog = _dialog(cache_db, loaded)
    store = loaded.sqlite_store
    first = (TabularColumnFilter(column="length_mm", numeric_operator=">", numeric_value=15),)
    second = (TabularColumnFilter(column="length_mm", numeric_operator=">", numeric_value=19),)
    keyed = {"filter_columns": ("fixture",), "selected_filter_keys": (("F1",),)}
    both_keys = {"filter_columns": ("fixture",), "selected_filter_keys": (("F1",), ("F2",))}
    try:
        # Reference values straight from the store (these calls are not the dialog's).
        expected_first = store.count_rows(column_filters=first)
        expected_second = store.count_rows(column_filters=second)
        expected_keyed = store.count_rows(**keyed)
        expected_both = store.count_rows(**both_keys)
        assert (expected_first, expected_second, expected_keyed, expected_both) == (6, 2, 6, 12)

        count_calls.clear()
        dialog.tabular_column_filters = first
        for _ in range(3):
            dialog._sync_ui_state()
        summary = dialog._tabular_filter_summary()
        assert dialog._tabular_filtered_row_count() == expected_first
        assert f"{expected_first} rows" in summary[0]
        assert len(count_calls) == 1

        dialog.tabular_column_filters = second
        dialog._sync_ui_state()
        dialog._sync_ui_state()
        assert dialog._tabular_filtered_row_count() == expected_second
        assert len(count_calls) == 2

        # Key filters are part of the state as well.
        dialog.tabular_column_filters = ()
        dialog.tabular_filter_columns = keyed["filter_columns"]
        dialog.tabular_filter_keys = keyed["selected_filter_keys"]
        assert dialog._tabular_filtered_row_count() == expected_keyed
        dialog._tabular_filtered_row_count()
        assert len(count_calls) == 3
        dialog.tabular_filter_keys = both_keys["selected_filter_keys"]
        assert dialog._tabular_filtered_row_count() == expected_both
        assert len(count_calls) == 4
    finally:
        dialog.close()
        cleanup_tabular_load_result(dialog.tabular_load_result)


def test_new_load_result_invalidates_the_remembered_count(cache_db, count_calls):
    _app()
    loaded = load_industrial_cache_tabular_result(cache_db)
    dialog = _dialog(cache_db, loaded)
    try:
        dialog.tabular_column_filters = (
            TabularColumnFilter(column="length_mm", numeric_operator=">", numeric_value=15),
        )
        assert dialog._tabular_filtered_row_count() == 6
        replacement = load_industrial_cache_tabular_result(cache_db, source_db_aliases=("prod_a",))
        dialog._set_tabular_load_result(replacement)
        count_calls.clear()
        assert dialog._tabular_filtered_row_count() == 6
        assert len(count_calls) == 1
    finally:
        dialog.close()
        cleanup_tabular_load_result(dialog.tabular_load_result)


def test_other_presentations_count_the_unfiltered_state_with_a_query(cache_db, count_calls):
    _app()
    industrial = load_industrial_cache_tabular_result(cache_db)
    loaded = dataclasses.replace(industrial, csv_config={"source": "csv"})
    count_calls.clear()
    dialog = _dialog(cache_db, loaded, presentation_mode=None)
    assert not dialog.is_industrial_cache_presentation
    try:
        assert dialog._tabular_filtered_row_count() == 12
        dialog._tabular_filtered_row_count()
        # One query for the whole construction and the explicit calls above.
        assert len(count_calls) == 1
    finally:
        dialog.close()
        cleanup_tabular_load_result(dialog.tabular_load_result)
