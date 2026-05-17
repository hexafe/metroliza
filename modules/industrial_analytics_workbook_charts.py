"""Workbook chart helpers for production and CSV/Excel analytics exports."""

from __future__ import annotations

from io import BytesIO
from typing import Protocol

import numpy as np
import pandas as pd

from modules.excel_sheet_utils import unique_sheet_name
from modules.export_summary_utils import resolve_histogram_bin_count
from modules.hexafe_plotstats_adapter import build_histogram_stats_table, plotstats_export_charts_enabled
from modules.hexafe_plotstats_adapter import render_chart_artifact_png
from modules.hexafe_plotstats_adapter import render_histogram_png as render_plotstats_histogram_png
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
    group_fields: tuple[str, ...] = (),
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
                charts_sheet_name=charts_sheet,
                source_rows=source_rows,
                row=row,
                group_fields=group_fields,
            )
            if inserted:
                chart_count += 1
                row += 17
        if charts.histogram:
            inserted = _insert_histogram_chart(
                workbook=workbook,
                worksheet=worksheet,
                dataframe=dataframe,
                metric=metric,
                charts_sheet_name=charts_sheet,
                row=row,
                group_fields=group_fields,
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
                group_fields=group_fields,
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
                group_fields=group_fields,
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
    charts_sheet_name: str,
    source_rows: int,
    row: int,
    group_fields: tuple[str, ...],
) -> bool:
    x_column = _time_axis_column(dataframe)
    if x_column is None or source_rows <= 0:
        return False
    groups = _time_series_groups(dataframe, metric.field_name, x_column, group_fields=group_fields)
    if not groups:
        return False

    chart = workbook.add_chart({"type": "scatter"})
    table_col = 8
    for group_index, (label, x_values, y_values) in enumerate(groups):
        x_table_col = table_col + group_index * 2
        y_table_col = x_table_col + 1
        worksheet.write(row, x_table_col, f"{label} x")
        worksheet.write(row, y_table_col, label)
        for offset, (x_value, y_value) in enumerate(zip(x_values, y_values, strict=False), start=1):
            worksheet.write(row + offset, x_table_col, _excel_chart_value(x_value))
            worksheet.write_number(row + offset, y_table_col, float(y_value))
        color = _plot_color(group_index, label)
        marker_type = "diamond" if "selected" in label.casefold() else "circle"
        chart.add_series(
            {
                "name": label if len(groups) > 1 else metric.display_label,
                "categories": [
                    charts_sheet_name,
                    row + 1,
                    x_table_col,
                    row + len(x_values),
                    x_table_col,
                ],
                "values": [
                    charts_sheet_name,
                    row + 1,
                    y_table_col,
                    row + len(y_values),
                    y_table_col,
                ],
                "line": {"none": True},
                "marker": {
                    "type": marker_type,
                    "size": 5 if marker_type == "diamond" else 4,
                    "border": {"color": color},
                    "fill": {"color": color},
                },
            }
        )
    chart.set_title({"name": f"{metric.display_label} over time"})
    chart.set_x_axis({"name": _axis_label(x_column), "major_gridlines": {"visible": False}})
    chart.set_y_axis({"name": metric.display_label, "major_gridlines": {"visible": True}})
    chart.set_legend({"none": True} if len(groups) == 1 else {"position": "bottom"})
    chart.set_style(10)
    worksheet.insert_chart(row, 0, chart, {"x_scale": 1.35, "y_scale": 1.15})
    return True


def _insert_histogram_chart(
    *,
    workbook,
    worksheet,
    dataframe: pd.DataFrame,
    metric: AnalyticsMetric,
    charts_sheet_name: str,
    row: int,
    group_fields: tuple[str, ...],
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

    groups = _plot_groups(dataframe, metric.field_name, group_fields=group_fields)
    grouped_histogram = len(groups) > 1
    if plotstats_export_charts_enabled():
        payload: dict[str, object] = {
            "type": "histogram",
            "title": f"{metric.display_label} distribution",
            "bin_count": bin_count,
            "limits": _metric_limits(metric),
        }
        if grouped_histogram:
            payload["groups"] = [
                {"group": label, "values": group_values.tolist()}
                for label, group_values in groups
            ]
        else:
            payload["values"] = values.tolist()
            payload["style"] = {"axis_label_x": metric.display_label, "axis_label_y": "Count"}
        rendered = render_chart_artifact_png(payload, target="workbook_image", backend="auto")
        if rendered is not None:
            worksheet.write(row, 8, f"Histogram rendered by {rendered.backend}")
            worksheet.insert_image(
                row,
                0,
                f"{metric.field_name}_histogram.png",
                {"image_data": BytesIO(rendered.png_bytes)},
            )
            return True

    if not grouped_histogram:
        rendered = render_plotstats_histogram_png(
            values,
            title=f"{metric.display_label} distribution",
            metric_label=metric.display_label,
            bin_count=bin_count,
            lsl=getattr(metric, "lsl", None),
            usl=getattr(metric, "usl", None),
        )
        if rendered is not None:
            worksheet.write(row, 8, f"Histogram rendered by {rendered.backend}")
            worksheet.insert_image(
                row,
                0,
                f"{metric.field_name}_histogram.png",
                {"image_data": BytesIO(rendered.png_bytes)},
            )
            return True

    table_col = 8
    worksheet.write(row, table_col, "Bin")
    if grouped_histogram:
        for group_index, (label, group_values) in enumerate(groups, start=1):
            worksheet.write(row, table_col + group_index, label)
            group_counts, _edges = np.histogram(group_values, bins=edges)
            total = float(np.sum(group_counts))
            for offset, count in enumerate(group_counts, start=1):
                worksheet.write_number(
                    row + offset,
                    table_col + group_index,
                    float(count) / total if total > 0 else 0.0,
                )
    else:
        worksheet.write(row, table_col + 1, "Count")
    for offset, count in enumerate(counts, start=1):
        start = float(edges[offset - 1])
        end = float(edges[offset])
        worksheet.write(row + offset, table_col, f"{start:.3g} - {end:.3g}")
        if not grouped_histogram:
            worksheet.write_number(row + offset, table_col + 1, int(count))

    chart = workbook.add_chart({"type": "column"})
    if grouped_histogram:
        for group_index, (label, _group_values) in enumerate(groups, start=1):
            color = _plot_color(group_index - 1, label)
            chart.add_series(
                {
                    "name": label,
                    "categories": [charts_sheet_name, row + 1, table_col, row + len(counts), table_col],
                    "values": [
                        charts_sheet_name,
                        row + 1,
                        table_col + group_index,
                        row + len(counts),
                        table_col + group_index,
                    ],
                    "fill": {"color": color, "transparency": 22},
                    "border": {"color": color, "width": 1},
                }
            )
    else:
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
    chart.set_y_axis(
        {
            "name": "Share of group" if grouped_histogram else "Count",
            "major_gridlines": {"visible": True},
            **({"num_format": "0%"} if grouped_histogram else {}),
        }
    )
    chart.set_legend({"position": "bottom"} if grouped_histogram else {"none": True})
    chart.set_style(10)
    worksheet.insert_chart(row, 0, chart, {"x_scale": 1.35, "y_scale": 1.15})
    if grouped_histogram:
        _write_histogram_stats_tables(
            worksheet,
            row=row,
            column=table_col + len(groups) + 2,
            groups=groups,
            lsl=getattr(metric, "lsl", None),
            usl=getattr(metric, "usl", None),
        )
    return True


def _write_histogram_stats_tables(
    worksheet,
    *,
    row: int,
    column: int,
    groups: list[tuple[str, np.ndarray]],
    lsl: float | None = None,
    usl: float | None = None,
) -> None:
    current_column = column
    for label, values in groups[:4]:
        table = build_histogram_stats_table(
            values,
            title=label,
            backend="metroliza",
            lsl=lsl,
            usl=usl,
        )
        if table is None:
            continue
        worksheet.write(row, current_column, f"Stats: {table.title}")
        worksheet.write(row + 1, current_column, "Parameter")
        worksheet.write(row + 1, current_column + 1, "Value")
        for offset, (stat_label, stat_value) in enumerate(table.rows, start=2):
            worksheet.write(row + offset, current_column, stat_label)
            worksheet.write(row + offset, current_column + 1, stat_value)
        current_column += 3


def _insert_matplotlib_distribution_image(
    *,
    worksheet,
    dataframe: pd.DataFrame,
    metric: AnalyticsMetric,
    chart_type: str,
    row: int,
    group_fields: tuple[str, ...],
) -> bool:
    groups = _plot_groups(dataframe, metric.field_name, group_fields=group_fields)
    if not groups:
        return False

    labels = [label for label, _values in groups]
    values = [series for _label, series in groups]
    if plotstats_export_charts_enabled():
        payload = {
            "type": "distribution" if chart_type == "violin" else "iqr",
            "render_mode": "violin" if chart_type == "violin" else "iqr",
            "title": f"{metric.display_label} {'violin' if chart_type == 'violin' else 'box plot'}",
            "labels": labels,
            "series": [series.tolist() for series in values],
            "limits": _metric_limits(metric),
        }
        rendered = render_chart_artifact_png(payload, target="workbook_image", backend="auto")
        if rendered is not None:
            worksheet.write(row, 8, f"{chart_type.title()} rendered by {rendered.backend}")
            worksheet.insert_image(
                row,
                0,
                f"{metric.field_name}_{chart_type}.png",
                {"image_data": BytesIO(rendered.png_bytes)},
            )
            return True

    fig, ax = plt.subplots(figsize=(7.4, 3.7))
    try:
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


def _metric_limits(metric: AnalyticsMetric) -> dict[str, float | None]:
    lsl = _optional_float(getattr(metric, "lsl", None))
    usl = _optional_float(getattr(metric, "usl", None))
    nominal = ((lsl + usl) / 2.0) if lsl is not None and usl is not None and lsl <= usl else None
    return {"lsl": lsl, "nominal": nominal, "usl": usl}


def _optional_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _plot_groups(
    dataframe: pd.DataFrame,
    metric_field: str,
    *,
    group_fields: tuple[str, ...] = (),
) -> list[tuple[str, np.ndarray]]:
    group_columns = _preferred_group_columns(dataframe, group_fields=group_fields)
    if not group_columns:
        values = pd.to_numeric(dataframe[metric_field], errors="coerce").dropna().to_numpy(dtype=float)
        return [("All rows", values)] if values.size else []

    groups: list[tuple[str, np.ndarray]] = []
    for key, group in dataframe.groupby(group_columns, dropna=False, sort=True):
        values = pd.to_numeric(group[metric_field], errors="coerce").dropna().to_numpy(dtype=float)
        if values.size:
            groups.append((_group_label(key), values))
    return groups


def _time_series_groups(
    dataframe: pd.DataFrame,
    metric_field: str,
    x_column: str,
    *,
    group_fields: tuple[str, ...] = (),
) -> list[tuple[str, list[object], list[float]]]:
    group_columns = _preferred_group_columns(dataframe, group_fields=group_fields)
    if not group_columns:
        grouped_frames = [("All rows", dataframe)]
    else:
        grouped_frames = [
            (_group_label(key), group)
            for key, group in dataframe.groupby(group_columns, dropna=False, sort=True)
        ]

    groups: list[tuple[str, list[object], list[float]]] = []
    for label, group in grouped_frames:
        group = group.sort_values(x_column)
        y_series = pd.to_numeric(group[metric_field], errors="coerce")
        valid_mask = group[x_column].notna() & y_series.notna()
        if not valid_mask.any():
            continue
        filtered = group.loc[valid_mask]
        y_values = [float(value) for value in y_series.loc[valid_mask].tolist()]
        x_values = filtered[x_column].tolist()
        if x_values and y_values:
            groups.append((label, x_values, y_values))
    return groups


def _preferred_group_columns(
    dataframe: pd.DataFrame,
    *,
    group_fields: tuple[str, ...] = (),
) -> list[str]:
    columns: list[str] = []
    for column in group_fields:
        if column in dataframe.columns and dataframe[column].nunique(dropna=True) > 1:
            columns.append(column)
    if (
        "reference_cohort" in dataframe.columns
        and dataframe["reference_cohort"].nunique(dropna=True) > 1
        and "reference_cohort" not in columns
    ):
        columns.append("reference_cohort")
    if columns:
        return columns
    if "GROUP" in dataframe.columns and dataframe["GROUP"].nunique(dropna=True) > 1:
        return ["GROUP"]
    if "reference_cohort" in dataframe.columns and dataframe["reference_cohort"].nunique(dropna=True) > 1:
        return ["reference_cohort"]
    for column in ("station", "line", "process_status", "source_db_alias"):
        if column in dataframe.columns and dataframe[column].nunique(dropna=True) > 1:
            return [column]
    return []


def _group_label(key) -> str:
    if not isinstance(key, tuple):
        key = (key,)
    return " | ".join(str(item) if str(item).strip() else "(blank)" for item in key)


def _plot_color(index: int, label: str) -> str:
    if "selected" in label.casefold():
        return SUMMARY_PLOT_PALETTE["spec_limit"]
    return _PLOT_COLORWAY[index % len(_PLOT_COLORWAY)]


def _excel_chart_value(value):
    if pd.isna(value):
        return ""
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is not None:
            value = value.tz_convert(None)
        return value.to_pydatetime()
    return value


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
