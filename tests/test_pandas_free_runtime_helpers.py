from __future__ import annotations

import builtins
from datetime import datetime, timezone
import importlib
import sys

import numpy as np


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
