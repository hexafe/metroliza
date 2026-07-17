from __future__ import annotations

import builtins
from datetime import datetime, timezone
import importlib
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import numpy as np


def test_csv_runtime_load_filter_group_preview_and_cleanup_block_pandas_imports(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    script = textwrap.dedent(
        f"""
        import builtins
        from pathlib import Path
        import sys

        real_import = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name == "pandas" or name.startswith("pandas."):
                raise AssertionError(f"unexpected pandas import: {{name}}")
            return real_import(name, *args, **kwargs)
        builtins.__import__ = guarded_import

        from metroliza.analytics.row_table import RowTable
        from metroliza.tabular.tabular_analytics_service import (
            TabularColumnFilter,
            cleanup_tabular_load_result,
            load_tabular_analytics_file,
            materialize_tabular_rows,
        )
        from metroliza.ui import tabular_analytics_filter_dialog
        from metroliza.ui import tabular_analytics_grouping_dialog
        from PyQt6.QtWidgets import QApplication

        source = Path({str(tmp_path / "runtime.csv")!r})
        source.write_text(
            "When,Station,Metric\\n"
            "2026-05-01,A,1\\n"
            "2026-05-02,B,2\\n"
            "2026-05-03,A,3\\n",
            encoding="utf-8",
        )
        loaded = load_tabular_analytics_file(source)
        sqlite_path = Path(loaded.sqlite_store.path)
        try:
            assert isinstance(loaded.dataframe, RowTable)
            assert isinstance(loaded.row_table, RowTable)
            assert loaded.row_table["metric"].tolist() == [1.0, 2.0, 3.0]

            filtered = materialize_tabular_rows(
                loaded,
                column_filters=(
                    TabularColumnFilter("station", selected_values=("A",)),
                    TabularColumnFilter(
                        "when",
                        date_operator=">=",
                        date_value="2026-05-02",
                    ),
                ),
                row_filter_expression="Metric >= 3",
            )
            assert isinstance(filtered.dataframe, RowTable)
            assert filtered.dataframe["source_row_number"].tolist() == [3]

            groups, total = loaded.sqlite_store.preview_group_rows(("station",), limit=10)
            assert total == 2
            assert {{tuple(row["key"]): row["row_count"] for row in groups}} == {{
                ("A",): 2,
                ("B",): 1,
            }}

            app = QApplication.instance() or QApplication([])
            filter_dialog = tabular_analytics_filter_dialog.TabularAnalyticsFilterDialog(
                dataframe=loaded.dataframe,
                column_mapping=loaded.column_mapping,
                sqlite_store=loaded.sqlite_store,
            )
            assert isinstance(filter_dialog.source_dataframe, RowTable)
            filter_dialog.reject()
            grouping_dialog = tabular_analytics_grouping_dialog.TabularAnalyticsGroupingDialog(
                dataframe=loaded.dataframe,
                column_mapping=loaded.column_mapping,
                sqlite_store=loaded.sqlite_store,
            )
            assert isinstance(grouping_dialog.source_dataframe, RowTable)
            grouping_dialog.dont_use_grouping()
            app.processEvents()
            assert "pandas" not in sys.modules
        finally:
            cleanup_tabular_load_result(loaded)
        assert not sqlite_path.exists()
        assert "pandas" not in sys.modules
        """
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = f"{project_root / 'src'}:{project_root}"
    environment["QT_QPA_PLATFORM"] = "offscreen"

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_lightweight_runtime_helpers_import_without_pandas(monkeypatch):
    module_names = (
        "metroliza.charts.chart_render_service",
        "metroliza.charts.hexafe_plotstats_adapter",
        "metroliza.analytics.distribution_fit_service",
        "metroliza.exporting.export_grouping_utils",
        "metroliza.exporting.export_summary_sheet_compute",
        "metroliza.industrial.json_safety",
        "metroliza.industrial.industrial_analytics_helpers",
    )
    for module_name in module_names:
        sys.modules.pop(module_name, None)

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "pandas" or name.startswith("pandas."):
            raise AssertionError(f"unexpected pandas import: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    for module_name in module_names:
        importlib.import_module(module_name)


def test_industrial_runtime_export_modules_import_without_pandas(monkeypatch, tmp_path):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))
    module_names = (
        "metroliza.industrial.industrial_export_service",
        "metroliza.industrial.industrial_analytics_service",
        "metroliza.industrial.industrial_analytics_workbook",
        "metroliza.industrial.industrial_analytics_workbook_charts",
        "metroliza.industrial.industrial_tabular_bridge",
    )
    for module_name in module_names:
        sys.modules.pop(module_name, None)

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "pandas" or name.startswith("pandas."):
            raise AssertionError(f"unexpected pandas import: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    for module_name in module_names:
        importlib.import_module(module_name)


def test_distribution_fit_measurement_coercion_drops_non_numeric_values():
    from metroliza.analytics.distribution_fit_service import _coerce_measurements_array

    values = _coerce_measurements_array(["1.25", "", None, "not-a-number", np.nan, "3.5"])

    assert values.dtype == np.float64
    assert values.tolist() == [1.25, 3.5]
    assert values.flags["C_CONTIGUOUS"]


def test_json_safety_handles_numpy_and_pandas_missing_sentinels_without_pandas_import():
    from metroliza.industrial.json_safety import json_safe_value

    PandasNA = type("NAType", (), {"__module__": "pandas._libs.missing"})
    PandasNaT = type("NaTType", (), {"__module__": "pandas._libs.tslibs.nattype"})

    assert json_safe_value(np.float64("nan")) is None
    assert json_safe_value(np.datetime64("NaT")) is None
    assert json_safe_value(PandasNA()) is None
    assert json_safe_value(PandasNaT()) is None


def test_time_bucket_labels_do_not_require_pandas_timestamp():
    from metroliza.industrial.industrial_analytics_helpers import format_time_bucket_label

    assert format_time_bucket_label("2026-06-23T08:15:30Z", "hour") == "2026-06-23 08:00"
    assert (
        format_time_bucket_label(datetime(2026, 6, 23, 10, 15, tzinfo=timezone.utc), "day")
        == "2026-06-23"
    )


def test_diagnostics_payload_writes_workbook_rows_without_pandas():
    from metroliza.industrial.industrial_analytics_helpers import diagnostics_dataframe

    class FakeWorksheet:
        def __init__(self):
            self.cells = {}

        def write(self, row, column, value):
            self.cells[(row, column)] = value

    class FakeBook:
        def __init__(self):
            self.worksheets = {}

        def add_worksheet(self, name):
            worksheet = FakeWorksheet()
            self.worksheets[name] = worksheet
            return worksheet

    class FakeWriter:
        def __init__(self):
            self.book = FakeBook()
            self.sheets = {}

    writer = FakeWriter()
    diagnostics_dataframe(()).to_excel(writer, sheet_name="Diagnostics", index=False)

    worksheet = writer.sheets["Diagnostics"]
    assert worksheet.cells[(0, 0)] == "severity"
    assert worksheet.cells[(0, 1)] == "code"
    assert worksheet.cells[(0, 2)] == "message"
    assert worksheet.cells[(1, 0)] == "info"
    assert worksheet.cells[(1, 1)] == "ok"


def test_plotstats_finite_values_use_local_numeric_coercion():
    from metroliza.charts.hexafe_plotstats_adapter import _finite_values

    values = _finite_values(["1.0", "", None, "bad", np.inf, "2.5"])

    assert values.tolist() == [1.0, 2.5]
