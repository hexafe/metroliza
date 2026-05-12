from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import pandas as pd

from modules.industrial_analytics_state import ProductionChartSelection, ProductionMetricSelection
from modules.industrial_analytics_workbook_charts import (
    _plot_groups,
    _time_series_groups,
    add_analytics_workbook_charts,
)


def test_workbook_distribution_groups_use_selected_group_field_before_defaults() -> None:
    dataframe = pd.DataFrame(
        {
            "station": ["S1", "S1", "S1", "S1"],
            "machine": ["M1", "M2", "M1", "M2"],
            "cycle_time_s": [35.0, 36.0, 34.8, 36.2],
        }
    )

    groups = _plot_groups(dataframe, "cycle_time_s", group_fields=("machine",))

    assert [label for label, _values in groups] == ["M1", "M2"]
    assert [values.tolist() for _label, values in groups] == [[35.0, 34.8], [36.0, 36.2]]


def test_workbook_time_series_groups_use_selected_group_field() -> None:
    dataframe = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-05-10 08:00", periods=4, freq="h"),
            "reference_cohort": [
                "Selected references",
                "Other references",
                "Selected references",
                "Other references",
            ],
            "cycle_time_s": [35.0, 36.0, 35.2, 36.1],
        }
    )

    groups = _time_series_groups(
        dataframe,
        "cycle_time_s",
        "process_datetime",
        group_fields=("reference_cohort",),
    )

    assert [label for label, _x_values, _y_values in groups] == [
        "Other references",
        "Selected references",
    ]
    assert [y_values for _label, _x_values, y_values in groups] == [[36.0, 36.1], [35.0, 35.2]]


def test_workbook_time_series_groups_combine_manual_group_and_highlight_cohort() -> None:
    dataframe = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-05-10 08:00", periods=4, freq="h"),
            "GROUP": ["POPULATION", "POPULATION", "Fixture A", "Fixture A"],
            "reference_cohort": [
                "Other references",
                "Selected references",
                "Other references",
                "Selected references",
            ],
            "cycle_time_s": [36.0, 35.0, 36.2, 35.2],
        }
    )

    groups = _time_series_groups(
        dataframe,
        "cycle_time_s",
        "process_datetime",
        group_fields=("GROUP",),
    )

    assert [label for label, _x_values, _y_values in groups] == [
        "Fixture A | Other references",
        "Fixture A | Selected references",
        "POPULATION | Other references",
        "POPULATION | Selected references",
    ]


def test_workbook_grouped_histogram_uses_normalized_group_shares() -> None:
    dataframe = pd.DataFrame(
        {
            "source_row_number": list(range(1, 9)),
            "GROUP": ["POPULATION"] * 6 + ["Selected"] * 2,
            "cycle_time_s": [34.8, 35.0, 35.1, 35.2, 35.4, 35.6, 36.0, 36.2],
        }
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "charts.xlsx"
        with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
            dataframe.to_excel(writer, sheet_name="Data", index=False)
            chart_count = add_analytics_workbook_charts(
                writer=writer,
                dataframe=dataframe,
                metric_selection=(ProductionMetricSelection("cycle_time_s", "Cycle Time S"),),
                chart_selection=ProductionChartSelection(
                    time_series=False,
                    histogram=True,
                    violin=False,
                    box=False,
                ),
                data_sheet_name="Data",
                used_names={"Data"},
                sheet_names=["Data"],
                group_fields=("GROUP",),
            )

        assert chart_count == 1
        with zipfile.ZipFile(output_file, "r") as workbook_zip:
            text_payload = "\n".join(
                workbook_zip.read(name).decode("utf-8", errors="ignore")
                for name in workbook_zip.namelist()
                if name.endswith(".xml")
            )

    assert "Share of group" in text_payload
    assert "POPULATION" in text_payload
    assert "Selected" in text_payload
    assert "0%" in text_payload
    assert "Stats: POPULATION" in text_payload
    assert "Samples" in text_payload


def test_workbook_single_histogram_uses_rendered_plot_with_stats_table() -> None:
    dataframe = pd.DataFrame(
        {
            "source_row_number": list(range(1, 5)),
            "cycle_time_s": [34.8, 35.0, 35.1, 35.2],
        }
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "charts.xlsx"
        with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
            dataframe.to_excel(writer, sheet_name="Data", index=False)
            chart_count = add_analytics_workbook_charts(
                writer=writer,
                dataframe=dataframe,
                metric_selection=(ProductionMetricSelection("cycle_time_s", "Cycle Time S"),),
                chart_selection=ProductionChartSelection(
                    time_series=False,
                    histogram=True,
                    violin=False,
                    box=False,
                ),
                data_sheet_name="Data",
                used_names={"Data"},
                sheet_names=["Data"],
            )

        assert chart_count == 1
        with zipfile.ZipFile(output_file, "r") as workbook_zip:
            names = workbook_zip.namelist()
            text_payload = "\n".join(
                workbook_zip.read(name).decode("utf-8", errors="ignore")
                for name in names
                if name.endswith(".xml")
            )

    assert any(name.startswith("xl/media/") and name.endswith(".png") for name in names)
    assert "Histogram rendered by" in text_payload
