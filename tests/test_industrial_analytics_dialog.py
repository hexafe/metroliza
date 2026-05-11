from __future__ import annotations

import pandas as pd

from tests.industrial_analytics_fixtures import seed_production_analytics_cache

try:
    from PyQt6.QtWidgets import QApplication
    from modules.industrial_analytics_dialog import (
        IndustrialAnalyticsDialog,
        SOURCE_PRODUCTION_CACHE,
        SOURCE_TABULAR_FILE,
    )
    from modules.industrial_analytics_filter_dialog import IndustrialAnalyticsFilterDialog
    from modules.industrial_analytics_state import ProductionFilterState
    from modules.industrial_workers import IndustrialAnalyticsThread
except ImportError as exc:  # pragma: no cover - environment/order dependent
    QApplication = None
    IndustrialAnalyticsDialog = None
    IndustrialAnalyticsFilterDialog = None
    IndustrialAnalyticsThread = None
    ProductionFilterState = None
    SOURCE_PRODUCTION_CACHE = "production_cache"
    SOURCE_TABULAR_FILE = "tabular_file"
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None

_APP = None


def _app():
    if PYQT_IMPORT_ERROR is not None:
        import pytest

        pytest.skip(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")
    global _APP
    _APP = QApplication.instance() or _APP or QApplication([])
    return _APP


def test_production_analytics_dialog_loads_cached_metric_candidates(tmp_path) -> None:
    _app()
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)

    dialog = IndustrialAnalyticsDialog(db_file=db_path, source_kind=SOURCE_PRODUCTION_CACHE)
    try:
        dialog.load_metrics()

        metric_labels = [
            dialog.metrics_list.item(index).text()
            for index in range(dialog.metrics_list.count())
        ]
        group_values = [
            dialog.group_field_combo.itemData(index)
            for index in range(dialog.group_field_combo.count())
        ]
        assert "Cycle Time S" in metric_labels
        assert "line" in group_values
        assert dialog.start_button.isEnabled()
    finally:
        dialog.close()


def test_production_analytics_dialog_passes_filter_state_to_worker(tmp_path) -> None:
    _app()
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)

    dialog = IndustrialAnalyticsDialog(db_file=db_path, source_kind=SOURCE_PRODUCTION_CACHE)
    try:
        dialog.filter_state = ProductionFilterState(references=("REF-100",), stations=("S1",))
        dialog.load_metrics()

        assert "Reference: REF-100" in dialog.filter_summary_label.text()
        thread = dialog.create_analytics_thread()
        assert thread.filter_state.references == ("REF-100",)
        assert thread.filter_state.stations == ("S1",)
    finally:
        dialog.close()


def test_production_filter_dialog_builds_fixed_and_dynamic_filters() -> None:
    _app()
    dialog = IndustrialAnalyticsFilterDialog()
    try:
        dialog.source_profile_ids_field.setText("1, 2")
        dialog.time_start_field.setText("2026-05-10T00:00:00Z")
        dialog.time_end_field.setText("2026-05-11T00:00:00Z")
        dialog.text_fields["stations"].setText("S1; S2")
        dialog.text_fields["references"].setText("REF-100 REF-200")
        dialog.dynamic_filters_edit.setPlainText(
            "cycle_time_s gt 40\nfixture_text_code contains alpha\ncavity in 1,2"
        )

        state = dialog.current_state()

        assert state.source_profile_ids == (1, 2)
        assert state.time_start == "2026-05-10T00:00:00Z"
        assert state.time_end == "2026-05-11T00:00:00Z"
        assert state.stations == ("S1", "S2")
        assert state.references == ("REF-100", "REF-200")
        assert [dynamic_filter.field_name for dynamic_filter in state.dynamic_filters] == [
            "cycle_time_s",
            "fixture_text_code",
            "cavity",
        ]
        assert state.dynamic_filters[0].operator == "gt"
        assert state.dynamic_filters[2].values == ("1", "2")
    finally:
        dialog.close()


def test_tabular_analytics_dialog_loads_csv_metrics_and_group_columns(tmp_path) -> None:
    _app()
    input_file = tmp_path / "table.csv"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=4, freq="h"),
            "Reference ID": ["R1", "R1", "R2", "R2"],
            "Line": ["L1", "L2", "L1", "L2"],
            "Length mm": [10.0, 10.2, 10.1, 10.4],
            "Width mm": [5.0, 5.2, 5.1, 5.4],
        }
    ).to_csv(input_file, index=False)

    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    try:
        dialog.input_file = str(input_file)
        dialog.output_dashboard_file = str(tmp_path / "table_analytics.html")
        dialog.output_workbook_file = str(tmp_path / "table_analytics.xlsx")
        dialog.load_metrics()

        metric_labels = [
            dialog.metrics_list.item(index).text()
            for index in range(dialog.metrics_list.count())
        ]
        group_values = [
            dialog.group_field_combo.itemData(index)
            for index in range(dialog.group_field_combo.count())
        ]
        assert {"Length Mm", "Width Mm"}.issubset(metric_labels)
        assert "line" in group_values
        assert dialog.timestamp_column_combo.currentData() == "time_stamp"
        assert dialog.reference_column_combo.currentData() == "reference_id"
        assert dialog.start_button.isEnabled()
        thread = dialog.create_analytics_thread()
        assert thread.timestamp_column == "time_stamp"
        assert thread.reference_column == "reference_id"
    finally:
        dialog.close()


def test_analytics_dialog_wires_cancellable_worker_without_running_job(tmp_path) -> None:
    _app()

    class NonStartingAnalyticsThread(IndustrialAnalyticsThread):
        def __init__(self) -> None:
            super().__init__(
                source_kind=SOURCE_PRODUCTION_CACHE,
                output_dashboard_file=str(tmp_path / "analytics.html"),
            )
            self.started = False
            self.cancel_called = False

        def start(self) -> None:
            self.started = True

        def cancel(self) -> None:
            self.cancel_called = True

    thread = NonStartingAnalyticsThread()
    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_PRODUCTION_CACHE)
    try:
        dialog.create_analytics_thread = lambda: thread

        dialog.show_loading_screen()

        assert dialog.analytics_thread is thread
        assert thread.started

        dialog.cancel_analytics()
        assert thread.cancel_called

        thread.finished.emit()
        assert dialog.analytics_thread is None
    finally:
        if hasattr(dialog, "loading_dialog"):
            dialog.loading_dialog.close()
        dialog.close()
