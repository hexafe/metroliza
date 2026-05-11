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
except ImportError as exc:  # pragma: no cover - environment/order dependent
    QApplication = None
    IndustrialAnalyticsDialog = None
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
        assert dialog.start_button.isEnabled()
    finally:
        dialog.close()
