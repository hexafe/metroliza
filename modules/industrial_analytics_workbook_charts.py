"""Workbook chart helpers for production and CSV/Excel analytics exports."""

from __future__ import annotations

from io import BytesIO
from typing import Protocol

import numpy as np
import pandas as pd

from modules.excel_sheet_utils import unique_sheet_name
from modules.export_summary_utils import resolve_histogram_bin_count
from modules.industrial_analytics_state import ProductionChartSelection
from modules.matplotlib_runtime import configure_headless_matplotlib
from modules.summary_plot_palette import SUMMARY_PLOT_PALETTE

configure_headless_matplotlib()

import matplotlib.pyplot as plt  # noqa: E402


class AnalyticsMetric(Protocol):
    field_name: str
    display_label: str


_PLOT_COLORWAY = (
    SUMMARY_PLOT_PALETTE["distribution_foreground"],
    "#D55E00",
    "#009E73",
    SUMMARY_PLOT_PALETTE["outlier"],
    SUMMARY_PLOT_PALETTE["central_tendency"],
    SUMMARY_PLOT_PALETTE["distribution_base"],
)


def add_analytics_workbook_charts(
    *,
    writer,
    dataframe: pd.DataFrame,
    metric_selection: tuple[AnalyticsMetric, ...],
    chart_selection: ProductionChartSelection | None,
    data_sheet_name: str,
    used_names: set[str],
    sheet_names: list[str],
) -> int:
    """Add a workbook chart sheet using selected analytics chart types."""

    charts = chart_selection or ProductionChartSelection(
        time_series=False,
        histogram=False,
        violin=False,
        box=False,
        groupstats=False,
    )
    if not (charts.time_series or charts.histogram or charts.violin or charts.box):
        return 0

    safe_metrics = tuple(
        metric
        for metric in metric_selection
        if metric.field_name in dataframe.columns
        and not pd.to_numeric(dataframe[metric.field_name], errors="coerce").dropna().empty
    )
    if not safe_metrics:
        return 0

    charts_sheet = unique_sheet_name("Charts", used_names)
    workbook = writer.book
    worksheet = workbook.add_worksheet(charts_sheet)
    writer.sheets[charts_sheet] = worksheet
    sheet_names.append(charts_sheet)

    worksheet.set_column(0, 0, 22)
    worksheet.set_column(1, 7, 14)
    worksheet.set_column(8, 10, 14)
    title_format = workbook.add_format({"bold": True, "font_size": 12})

    row = 0
    chart_count = 0
    source_rows = len(dataframe.index)
    for metric in safe_metrics:
        worksheet.write(row, 0, metric.display_label, title_format)
        row += 1
        if charts.time_series:
            inserted = _insert_native_time_series_chart(
                workbook=workbook,
                worksheet=worksheet,
                dataframe=dataframe,
                metric=metric,
                data_sheet_name=data_sheet_name,
                source_rows=source_rows,
                row=row,
            )
            if inserted:
                chart_count += 1
                row += 17
        if charts.histogram:
            inserted = _insert_native_histogram_chart(
                workbook=workbook,
                worksheet=worksheet,
                dataframe=dataframe,
                metric=metric,
                charts_sheet_name=charts_sheet,
                row=row,
            )
            if inserted:
                chart_count += 1
                row += 18
        if charts.violin:
            inserted = _insert_matplotlib_distribution_image(
                worksheet=worksheet,
                dataframe=dataframe,
                metric=metric,
                chart_type="violin",
                row=row,
            )
            if inserted:
                chart_count += 1
                row += 20
        if charts.box:
            inserted = _insert_matplotlib_distribution_image(
                worksheet=worksheet,
                dataframe=dataframe,
                metric=metric,
                chart_type="box",
                row=row,
            )
            if inserted:
                chart_count += 1
                row += 20
        row += 2

    if chart_count == 0:
        worksheet.write(0, 0, "No selected charts could be generated for the selected metrics.")
    return chart_count


def _insert_native_time_series_chart(
    *,
    workbook,
    worksheet,
    dataframe: pd.DataFrame,
    metric: AnalyticsMetric,
    data_sheet_name: str,
    source_rows: int,
    row: int,
) -> bool:
    x_column = _time_axis_column(dataframe)
    if x_column is None or source_rows <= 0:
        return False
    metric_col = dataframe.columns.get_loc(metric.field_name)
    x_col = dataframe.columns.get_loc(x_column)
    chart_type = "scatter" if x_column == "process_datetime" else "line"
    chart_options = {"type": chart_type}
    if chart_type == "scatter":
        chart_options["subtype"] = "straight_with_markers"
    chart = workbook.add_chart(chart_options)
    chart.add_series(
        {
            "name": metric.display_label,
            "categories": [data_sheet_name, 1, x_col, source_rows, x_col],
            "values": [data_sheet_name, 1, metric_col, source_rows, metric_col],
            "line": {"color": SUMMARY_PLOT_PALETTE["distribution_foreground"], "width": 1.5},
            "marker": {
                "type": "circle",
                "size": 4,
                "border": {"color": SUMMARY_PLOT_PALETTE["distribution_foreground"]},
                "fill": {"color": SUMMARY_PLOT_PALETTE["distribution_base"]},
            },
        }
    )
    chart.set_title({"name": f"{metric.display_label} over time"})
    chart.set_x_axis({"name": _axis_label(x_column), "major_gridlines": {"visible": False}})
    chart.set_y_axis({"name": metric.display_label, "major_gridlines": {"visible": True}})
    chart.set_legend({"none": True})
    chart.set_style(10)
    worksheet.insert_chart(row, 0, chart, {"x_scale": 1.35, "y_scale": 1.15})
    return True


def _insert_native_histogram_chart(
    *,
    workbook,
    worksheet,
    dataframe: pd.DataFrame,
    metric: AnalyticsMetric,
    charts_sheet_name: str,
    row: int,
) -> bool:
    values = pd.to_numeric(dataframe[metric.field_name], errors="coerce").dropna().to_numpy(dtype=float)
    if values.size == 0:
        return False
    binning = resolve_histogram_bin_count(values)
    bin_count = max(1, int(binning.get("bin_count") or 1))
    if np.isclose(float(np.min(values)), float(np.max(values))):
        center = float(values[0])
        padding = max(abs(center) * 0.01, 0.5)
        edges = np.linspace(center - padding, center + padding, bin_count + 1)
        counts, edges = np.histogram(values, bins=edges)
    else:
        counts, edges = np.histogram(values, bins=bin_count)

    table_col = 8
    worksheet.write(row, table_col, "Bin")
    worksheet.write(row, table_col + 1, "Count")
    for offset, count in enumerate(counts, start=1):
        start = float(edges[offset - 1])
        end = float(edges[offset])
        worksheet.write(row + offset, table_col, f"{start:.3g} - {end:.3g}")
        worksheet.write_number(row + offset, table_col + 1, int(count))

    chart = workbook.add_chart({"type": "column"})
    chart.add_series(
        {
            "name": metric.display_label,
            "categories": [charts_sheet_name, row + 1, table_col, row + len(counts), table_col],
            "values": [charts_sheet_name, row + 1, table_col + 1, row + len(counts), table_col + 1],
            "fill": {"color": SUMMARY_PLOT_PALETTE["distribution_base"], "transparency": 18},
            "border": {"color": SUMMARY_PLOT_PALETTE["distribution_foreground"], "width": 1},
        }
    )
    chart.set_title({"name": f"{metric.display_label} distribution"})
    chart.set_x_axis({"name": metric.display_label, "label_position": "low"})
    chart.set_y_axis({"name": "Count", "major_gridlines": {"visible": True}})
    chart.set_legend({"none": True})
    chart.set_style(10)
    worksheet.insert_chart(row, 0, chart, {"x_scale": 1.35, "y_scale": 1.15})
    return True


def _insert_matplotlib_distribution_image(
    *,
    worksheet,
    dataframe: pd.DataFrame,
    metric: AnalyticsMetric,
    chart_type: str,
    row: int,
) -> bool:
    groups = _plot_groups(dataframe, metric.field_name)
    if not groups:
        return False

    fig, ax = plt.subplots(figsize=(7.4, 3.7))
    try:
        labels = [label for label, _values in groups]
        values = [series for _label, series in groups]
        positions = np.arange(1, len(values) + 1)
        if chart_type == "violin":
            parts = ax.violinplot(
                values,
                positions=positions,
                showmeans=False,
                showmedians=True,
                showextrema=False,
            )
            for index, body in enumerate(parts.get("bodies", [])):
                color = _PLOT_COLORWAY[index % len(_PLOT_COLORWAY)]
                body.set_facecolor(color)
                body.set_edgecolor(SUMMARY_PLOT_PALETTE["distribution_foreground"])
                body.set_alpha(0.48)
            for key in ("cmedians",):
                if key in parts:
                    parts[key].set_color(SUMMARY_PLOT_PALETTE["central_tendency"])
                    parts[key].set_linewidth(1.2)
            title = f"{metric.display_label} violin"
        else:
            box = ax.boxplot(
                values,
                positions=positions,
                patch_artist=True,
                showmeans=True,
                showfliers=True,
                medianprops={"color": SUMMARY_PLOT_PALETTE["central_tendency"], "linewidth": 1.15},
                meanprops={
                    "marker": "o",
                    "markerfacecolor": SUMMARY_PLOT_PALETTE["central_tendency"],
                    "markeredgecolor": SUMMARY_PLOT_PALETTE["central_tendency"],
                    "markersize": 4,
                },
                flierprops={
                    "marker": "o",
                    "markersize": 3,
                    "markerfacecolor": SUMMARY_PLOT_PALETTE["outlier"],
                    "markeredgecolor": SUMMARY_PLOT_PALETTE["outlier"],
                    "alpha": 0.85,
                },
            )
            for patch in box.get("boxes", []):
                patch.set_facecolor(SUMMARY_PLOT_PALETTE["distribution_base"])
                patch.set_edgecolor(SUMMARY_PLOT_PALETTE["distribution_foreground"])
                patch.set_alpha(0.45)
            title = f"{metric.display_label} box plot"

        ax.set_title(title, color=SUMMARY_PLOT_PALETTE["annotation_text"])
        ax.set_ylabel(metric.display_label, color=SUMMARY_PLOT_PALETTE["axis_text"])
        ax.set_xticks(positions)
        ax.set_xticklabels(labels, rotation=30 if max(len(label) for label in labels) > 12 else 0, ha="right")
        _apply_minimal_axis_style(ax)
        fig.tight_layout()
        image_data = BytesIO()
        fig.savefig(image_data, format="png", dpi=150)
        image_data.seek(0)
    finally:
        plt.close(fig)

    worksheet.insert_image(row, 0, f"{metric.field_name}_{chart_type}.png", {"image_data": image_data})
    return True


def _plot_groups(dataframe: pd.DataFrame, metric_field: str) -> list[tuple[str, np.ndarray]]:
    group_column = _preferred_group_column(dataframe)
    if group_column is None:
        values = pd.to_numeric(dataframe[metric_field], errors="coerce").dropna().to_numpy(dtype=float)
        return [("All rows", values)] if values.size else []

    groups: list[tuple[str, np.ndarray]] = []
    for label, group in dataframe.groupby(group_column, dropna=False, sort=True):
        values = pd.to_numeric(group[metric_field], errors="coerce").dropna().to_numpy(dtype=float)
        if values.size:
            groups.append((str(label) if str(label).strip() else "(blank)", values))
    return groups


def _preferred_group_column(dataframe: pd.DataFrame) -> str | None:
    if "GROUP" in dataframe.columns and dataframe["GROUP"].nunique(dropna=True) > 1:
        return "GROUP"
    if "reference_cohort" in dataframe.columns and dataframe["reference_cohort"].nunique(dropna=True) > 1:
        return "reference_cohort"
    for column in ("station", "line", "process_status", "source_db_alias"):
        if column in dataframe.columns and dataframe[column].nunique(dropna=True) > 1:
            return column
    return None


def _time_axis_column(dataframe: pd.DataFrame) -> str | None:
    for column in ("process_datetime", "source_row_number", "industrial_record_id"):
        if column in dataframe.columns and dataframe[column].notna().any():
            return column
    return None


def _axis_label(column: str) -> str:
    return {
        "process_datetime": "Process time",
        "source_row_number": "Source row",
        "industrial_record_id": "Record",
    }.get(column, column.replace("_", " ").title())


def _apply_minimal_axis_style(ax) -> None:
    ax.set_facecolor("white")
    ax.grid(
        True,
        axis="y",
        linestyle="-",
        linewidth=0.5,
        color=SUMMARY_PLOT_PALETTE["grid"],
        alpha=0.4,
    )
    ax.grid(False, axis="x")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(SUMMARY_PLOT_PALETTE["axis_spine"])
    ax.spines["bottom"].set_color(SUMMARY_PLOT_PALETTE["axis_spine"])
    ax.tick_params(axis="both", colors=SUMMARY_PLOT_PALETTE["axis_text"])


__all__ = ["add_analytics_workbook_charts"]
