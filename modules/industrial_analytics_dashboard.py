"""Offline Plotly dashboard writer for cached production analytics."""

from __future__ import annotations

from datetime import datetime, timezone
import html
import json
from pathlib import Path
import shutil
from typing import Any

import pandas as pd

from modules.industrial_analytics_service import (
    ProductionAggregationResult,
    ProductionAnalyticsDiagnostic,
    ProductionGroupstatsResult,
)
from modules.industrial_analytics_state import (
    ProductionAggregationState,
    ProductionChartSelection,
    ProductionMetricSelection,
    ReferenceCohortState,
)


DASHBOARD_SCHEMA = "metroliza.production_analytics_dashboard.v1"
PLOTLY_ASSET_NAME = "plotly-2.27.0.min.js"
PLOTLY_ASSET_SOURCE = Path(__file__).resolve().parent / "html_dashboard_assets" / PLOTLY_ASSET_NAME


def build_production_dashboard_manifest(
    *,
    frame: pd.DataFrame,
    metric_selection: tuple[ProductionMetricSelection, ...],
    aggregation_state: ProductionAggregationState | None = None,
    aggregation_result: ProductionAggregationResult | None = None,
    groupstats_result: ProductionGroupstatsResult | None = None,
    chart_selection: ProductionChartSelection | None = None,
    cohort_state: ReferenceCohortState | None = None,
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...] = (),
) -> dict[str, Any]:
    """Build a renderer-neutral manifest for the production analytics dashboard."""

    aggregation = aggregation_state or ProductionAggregationState()
    charts = chart_selection or ProductionChartSelection()
    cohort = cohort_state or ReferenceCohortState()
    aggregate_frame = (
        aggregation_result.dataframe
        if aggregation_result is not None and not aggregation_result.dataframe.empty
        else pd.DataFrame()
    )

    chart_specs: list[dict[str, Any]] = []
    for metric in metric_selection:
        if metric.field_name not in frame.columns:
            continue
        metric_frame = frame[frame[metric.field_name].notna()].copy()
        if metric_frame.empty:
            continue
        if charts.time_series:
            spec = _build_time_series_chart(
                metric,
                raw_frame=metric_frame,
                aggregate_frame=aggregate_frame,
                aggregation=aggregation,
            )
            if spec:
                chart_specs.append(spec)
        if charts.histogram:
            spec = _build_histogram_chart(metric, metric_frame)
            if spec:
                chart_specs.append(spec)
        if charts.violin:
            spec = _build_distribution_chart(metric, metric_frame, chart_type="violin")
            if spec:
                chart_specs.append(spec)
        if charts.box:
            spec = _build_distribution_chart(metric, metric_frame, chart_type="box")
            if spec:
                chart_specs.append(spec)

    summary = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_rows": int(len(frame.index)),
        "aggregate_rows": (
            int(aggregation_result.output_row_count)
            if aggregation_result is not None
            else 0
        ),
        "metric_count": len(metric_selection),
        "chart_count": len(chart_specs),
        "time_bucket": aggregation.time_bucket,
        "aggregation_methods": list(aggregation.aggregation_methods),
        "group_fields": list(aggregation.group_fields),
        "reference_cohort_count": len(cohort.references),
        "reference_cohort_mode": cohort.mode,
        "groupstats_metric_count": (
            groupstats_result.analyzed_metric_count
            if groupstats_result is not None
            else 0
        ),
    }
    return {
        "schema": DASHBOARD_SCHEMA,
        "summary": summary,
        "metrics": [
            {
                "field_name": metric.field_name,
                "display_label": metric.display_label,
                "source_kind": metric.source_kind,
            }
            for metric in metric_selection
        ],
        "charts": chart_specs,
        "groupstats": _groupstats_payload(groupstats_result),
        "diagnostics": [_diagnostic_payload(diagnostic) for diagnostic in diagnostics],
    }


def write_production_dashboard(
    manifest: dict[str, Any],
    output_path: str | Path,
    *,
    assets_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Write an offline production analytics dashboard and local Plotly asset."""

    destination = Path(output_path)
    if destination.suffix.lower() != ".html":
        destination = destination.with_suffix(".html")
    destination.parent.mkdir(parents=True, exist_ok=True)
    asset_directory = (
        Path(assets_dir)
        if assets_dir is not None
        else destination.with_name(f"{destination.stem}_assets")
    )
    asset_directory.mkdir(parents=True, exist_ok=True)
    plotly_target = asset_directory / PLOTLY_ASSET_NAME
    if not plotly_target.exists():
        shutil.copy2(PLOTLY_ASSET_SOURCE, plotly_target)

    html_text = _render_dashboard_html(manifest, asset_directory_name=asset_directory.name)
    destination.write_text(html_text, encoding="utf-8")
    return {
        "html_dashboard_path": str(destination),
        "html_dashboard_assets_path": str(asset_directory),
        "html_dashboard_chart_count": len(manifest.get("charts") or []),
    }


def _build_time_series_chart(
    metric: ProductionMetricSelection,
    *,
    raw_frame: pd.DataFrame,
    aggregate_frame: pd.DataFrame,
    aggregation: ProductionAggregationState,
) -> dict[str, Any]:
    method = aggregation.aggregation_methods[0] if aggregation.aggregation_methods else "mean"
    aggregate_metric = f"{metric.field_name}__{method}"
    if (
        aggregation.is_aggregated
        and not aggregate_frame.empty
        and "time_bucket_start" in aggregate_frame.columns
        and aggregate_metric in aggregate_frame.columns
    ):
        traces = _time_series_traces(
            aggregate_frame,
            x_column="time_bucket_start",
            y_column=aggregate_metric,
            group_columns=[
                column
                for column in aggregation.group_fields
                if column in aggregate_frame.columns
            ],
            default_name=f"{metric.display_label} ({method})",
        )
        x_title = _bucket_axis_title(aggregation.time_bucket)
        y_title = f"{metric.display_label} ({method})"
    else:
        traces = _time_series_traces(
            raw_frame,
            x_column="process_datetime",
            y_column=metric.field_name,
            group_columns=_preferred_group_columns(raw_frame),
            default_name=metric.display_label,
        )
        x_title = "Process time"
        y_title = metric.display_label

    if not traces:
        return {}
    return _chart_payload(
        chart_id=f"time-series-{metric.field_name}",
        title=f"{metric.display_label} over time",
        chart_type="time_series",
        data=traces,
        layout={
            "xaxis": {"title": x_title},
            "yaxis": {"title": y_title},
            "hovermode": "x unified",
        },
    )


def _build_histogram_chart(
    metric: ProductionMetricSelection,
    frame: pd.DataFrame,
) -> dict[str, Any]:
    traces = []
    for index, (label, group) in enumerate(_plot_groups(frame), start=0):
        values = _numeric_values(group[metric.field_name])
        if not values:
            continue
        traces.append(
            {
                "type": "histogram",
                "name": label,
                "x": values,
                "opacity": 0.72 if len(_plot_groups(frame)) > 1 else 0.86,
                "marker": {"color": _plot_color(index, label)},
                "hovertemplate": f"{html.escape(label)}<br>{metric.display_label}=%{{x}}<br>Count=%{{y}}<extra></extra>",
            }
        )
    if not traces:
        return {}
    return _chart_payload(
        chart_id=f"histogram-{metric.field_name}",
        title=f"{metric.display_label} distribution",
        chart_type="histogram",
        data=traces,
        layout={
            "barmode": "overlay",
            "xaxis": {"title": metric.display_label},
            "yaxis": {"title": "Count"},
        },
    )


def _build_distribution_chart(
    metric: ProductionMetricSelection,
    frame: pd.DataFrame,
    *,
    chart_type: str,
) -> dict[str, Any]:
    traces = []
    for index, (label, group) in enumerate(_plot_groups(frame), start=0):
        values = _numeric_values(group[metric.field_name])
        if not values:
            continue
        trace_type = "box" if chart_type == "box" else "violin"
        trace = {
            "type": trace_type,
            "name": label,
            "y": values,
            "marker": {"color": _plot_color(index, label)},
            "hovertemplate": f"{html.escape(label)}<br>{metric.display_label}=%{{y}}<extra></extra>",
        }
        if trace_type == "violin":
            trace.update({"box": {"visible": True}, "meanline": {"visible": True}, "points": False})
        else:
            trace.update({"boxmean": True, "boxpoints": False})
        traces.append(trace)
    if not traces:
        return {}
    return _chart_payload(
        chart_id=f"{chart_type}-{metric.field_name}",
        title=f"{metric.display_label} {chart_type}",
        chart_type=chart_type,
        data=traces,
        layout={
            "xaxis": {"title": "Group"},
            "yaxis": {"title": metric.display_label},
        },
    )


def _time_series_traces(
    frame: pd.DataFrame,
    *,
    x_column: str,
    y_column: str,
    group_columns: list[str],
    default_name: str,
) -> list[dict[str, Any]]:
    if x_column not in frame.columns or y_column not in frame.columns:
        return []
    traces = []
    groups = _grouped_frames(frame, group_columns, default_name=default_name)
    for index, (label, group) in enumerate(groups, start=0):
        group = group.sort_values(x_column)
        x_values = _json_values(group[x_column])
        y_values = _numeric_values(group[y_column])
        if not x_values or not y_values:
            continue
        marker_symbol = "diamond" if "selected" in label.casefold() else "circle"
        traces.append(
            {
                "type": "scatter",
                "mode": "lines+markers",
                "name": label,
                "x": x_values,
                "y": y_values,
                "marker": {
                    "color": _plot_color(index, label),
                    "size": 9 if marker_symbol == "diamond" else 7,
                    "symbol": marker_symbol,
                },
                "line": {"color": _plot_color(index, label), "width": 2},
                "hovertemplate": f"{html.escape(label)}<br>Time=%{{x}}<br>Value=%{{y}}<extra></extra>",
            }
        )
    return traces


def _chart_payload(
    *,
    chart_id: str,
    title: str,
    chart_type: str,
    data: list[dict[str, Any]],
    layout: dict[str, Any],
) -> dict[str, Any]:
    resolved_layout = {
        "title": {"text": title, "font": {"size": 18}},
        "margin": {"l": 58, "r": 24, "t": 54, "b": 52},
        "legend": {"orientation": "h", "y": -0.24},
        "template": "plotly_white",
    }
    resolved_layout.update(layout)
    return {
        "id": chart_id,
        "title": title,
        "chart_type": chart_type,
        "plotly_spec": {
            "data": data,
            "layout": resolved_layout,
            "config": {"responsive": True, "displaylogo": False},
        },
    }


def _plot_groups(frame: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    group_columns = _preferred_group_columns(frame)
    return _grouped_frames(frame, group_columns, default_name="All production rows")


def _preferred_group_columns(frame: pd.DataFrame) -> list[str]:
    if "reference_cohort" in frame.columns and frame["reference_cohort"].nunique(dropna=True) > 1:
        return ["reference_cohort"]
    for column in ("station", "line", "process_status", "source_db_alias"):
        if column in frame.columns and frame[column].nunique(dropna=True) > 1:
            return [column]
    return []


def _grouped_frames(
    frame: pd.DataFrame,
    group_columns: list[str],
    *,
    default_name: str,
) -> list[tuple[str, pd.DataFrame]]:
    if not group_columns:
        return [(default_name, frame)]
    groups = []
    for key, group in frame.groupby(group_columns, dropna=False, sort=True):
        if not isinstance(key, tuple):
            key = (key,)
        label = " | ".join(str(item) if str(item).strip() else "(blank)" for item in key)
        groups.append((label, group))
    return groups


def _plot_color(index: int, label: str) -> str:
    if "selected" in label.casefold():
        return "#d62728"
    palette = ("#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#7f7f7f")
    return palette[index % len(palette)]


def _numeric_values(series: pd.Series) -> list[float]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return [float(value) for value in values.tolist()]


def _json_values(series: pd.Series) -> list[Any]:
    values: list[Any] = []
    for value in series.tolist():
        if pd.isna(value):
            values.append(None)
        elif hasattr(value, "isoformat"):
            values.append(value.isoformat())
        else:
            values.append(value)
    return values


def _bucket_axis_title(time_bucket: str) -> str:
    labels = {
        "hour": "Hour",
        "day": "Day",
        "week": "Week starting",
        "month": "Month",
        "year": "Year",
    }
    return labels.get(time_bucket, "Process time")


def _diagnostic_payload(diagnostic: ProductionAnalyticsDiagnostic) -> dict[str, Any]:
    return {
        "severity": diagnostic.severity,
        "code": diagnostic.code,
        "message": diagnostic.message,
        "context": diagnostic.context,
    }


def _groupstats_payload(groupstats_result: ProductionGroupstatsResult | None) -> dict[str, Any]:
    if groupstats_result is None:
        return {"metrics": [], "diagnostics": []}
    return {
        "metrics": list(groupstats_result.metrics),
        "diagnostics": [_diagnostic_payload(diagnostic) for diagnostic in groupstats_result.diagnostics],
    }


def _render_dashboard_html(manifest: dict[str, Any], *, asset_directory_name: str) -> str:
    summary = manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {}
    charts = manifest.get("charts") if isinstance(manifest.get("charts"), list) else []
    diagnostics = manifest.get("diagnostics") if isinstance(manifest.get("diagnostics"), list) else []
    groupstats = manifest.get("groupstats") if isinstance(manifest.get("groupstats"), dict) else {}
    charts_json = json.dumps(charts, ensure_ascii=False).replace("</", "<\\/")
    cards = _render_summary_cards(summary)
    diagnostics_markup = _render_diagnostics(diagnostics)
    groupstats_markup = _render_groupstats(groupstats)
    chart_markup = "".join(_render_chart_shell(chart) for chart in charts)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Production Analytics</title>
  <script src="{html.escape(asset_directory_name)}/{PLOTLY_ASSET_NAME}"></script>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #687385;
      --line: #d8dde6;
      --accent: #1769aa;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #15181d;
        --panel: #20252c;
        --text: #edf1f7;
        --muted: #aab4c2;
        --line: #384250;
        --accent: #5aa9e6;
      }}
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, Segoe UI, Roboto, Arial, sans-serif;
    }}
    header, main {{
      width: min(1280px, calc(100vw - 32px));
      margin: 0 auto;
    }}
    header {{
      padding: 28px 0 14px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 28px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    .subtitle {{
      color: var(--muted);
      font-size: 14px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 10px;
      margin: 18px 0;
    }}
    .card, .chart-card, .diagnostics {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .card {{
      padding: 12px 14px;
    }}
    .card-label {{
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }}
    .card-value {{
      font-size: 20px;
      font-weight: 650;
    }}
    .chart-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
      gap: 14px;
      padding-bottom: 24px;
    }}
    .chart-card {{
      min-height: 420px;
      padding: 12px;
    }}
    .chart-title {{
      font-size: 15px;
      font-weight: 650;
      margin: 0 0 8px;
    }}
    .plotly-chart {{
      width: 100%;
      height: 360px;
    }}
    .diagnostics {{
      padding: 12px 14px;
      margin: 0 0 14px;
    }}
    .diagnostics h2 {{
      margin: 0 0 8px;
      font-size: 16px;
    }}
    .diagnostics ul {{
      margin: 0;
      padding-left: 18px;
    }}
    .stats-section {{
      margin: 0 0 14px;
      display: grid;
      gap: 12px;
    }}
    .stats-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      overflow-x: auto;
    }}
    .stats-card h2 {{
      margin: 0 0 10px;
      font-size: 17px;
    }}
    .stats-card h3 {{
      margin: 12px 0 8px;
      font-size: 14px;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      font-size: 13px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 7px 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-weight: 650;
      white-space: nowrap;
    }}
    @media (max-width: 640px) {{
      header, main {{
        width: min(100vw - 20px, 1280px);
      }}
      .chart-grid {{
        grid-template-columns: 1fr;
      }}
      .chart-card {{
        min-height: 360px;
      }}
      .plotly-chart {{
        height: 310px;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Production Analytics</h1>
    <div class="subtitle">Cached production data dashboard generated by Metroliza.</div>
    {cards}
  </header>
  <main>
    {diagnostics_markup}
    {groupstats_markup}
    <section class="chart-grid">
      {chart_markup}
    </section>
  </main>
  <script id="production-dashboard-charts" type="application/json">{charts_json}</script>
  <script>
    const chartData = JSON.parse(document.getElementById('production-dashboard-charts').textContent);
    for (const chart of chartData) {{
      const target = document.getElementById(chart.id);
      if (!target || !chart.plotly_spec) continue;
      Plotly.newPlot(target, chart.plotly_spec.data, chart.plotly_spec.layout, chart.plotly_spec.config);
    }}
  </script>
</body>
</html>
"""


def _render_summary_cards(summary: dict[str, Any]) -> str:
    rows = (
        ("Rows", summary.get("source_rows")),
        ("Aggregate rows", summary.get("aggregate_rows")),
        ("Metrics", summary.get("metric_count")),
        ("Charts", summary.get("chart_count")),
        ("Bucket", summary.get("time_bucket")),
        ("Aggregation", ", ".join(summary.get("aggregation_methods") or [])),
        ("Reference cohort", summary.get("reference_cohort_count")),
        ("Stats metrics", summary.get("groupstats_metric_count")),
    )
    markup = []
    for label, value in rows:
        markup.append(
            '<div class="card">'
            f'<div class="card-label">{html.escape(str(label))}</div>'
            f'<div class="card-value">{html.escape(str(value if value not in (None, "") else "n/a"))}</div>'
            '</div>'
        )
    return f'<section class="cards">{"".join(markup)}</section>'


def _render_diagnostics(diagnostics: list[dict[str, Any]]) -> str:
    messages = [
        str(item.get("message") or "").strip()
        for item in diagnostics
        if isinstance(item, dict) and str(item.get("message") or "").strip()
    ]
    if not messages:
        return ""
    rows = "".join(f"<li>{html.escape(message)}</li>" for message in messages)
    return f'<section class="diagnostics"><h2>Diagnostics</h2><ul>{rows}</ul></section>'


def _render_groupstats(groupstats: dict[str, Any]) -> str:
    metrics = groupstats.get("metrics") if isinstance(groupstats.get("metrics"), list) else []
    if not metrics:
        return ""
    cards = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        title = str(metric.get("metric") or metric.get("field_name") or "Metric")
        if metric.get("skipped"):
            reason = str(metric.get("skip_reason") or "skipped").replace("_", " ")
            cards.append(
                '<article class="stats-card">'
                f"<h2>{html.escape(title)}</h2>"
                f"<p>Groupstats skipped: {html.escape(reason)}.</p>"
                "</article>"
            )
            continue
        descriptive = _render_table(
            metric.get("descriptive_stats"),
            columns=("group", "n", "mean", "std", "median", "iqr", "min", "max"),
        )
        pairwise = _render_table(
            metric.get("pairwise_rows"),
            columns=("group_a", "group_b", "p_value", "adjusted_p_value", "effect_size", "test_used"),
        )
        insight = metric.get("primary_insight") if isinstance(metric.get("primary_insight"), dict) else {}
        insight_text = str(
            insight.get("headline") or insight.get("first_action") or ""
        ).strip()
        insight_markup = (
            f"<p>{html.escape(insight_text)}</p>"
            if insight_text
            else ""
        )
        cards.append(
            '<article class="stats-card">'
            f"<h2>{html.escape(title)}</h2>"
            f"{insight_markup}"
            "<h3>Descriptive stats</h3>"
            f"{descriptive}"
            "<h3>Pairwise tests</h3>"
            f"{pairwise}"
            "</article>"
        )
    if not cards:
        return ""
    return f'<section class="stats-section">{"".join(cards)}</section>'


def _render_table(rows: Any, *, columns: tuple[str, ...]) -> str:
    if not isinstance(rows, list) or not rows:
        return "<p>No rows available.</p>"
    header = "".join(f"<th>{html.escape(_table_label(column))}</th>" for column in columns)
    body_rows = []
    for row in rows[:200]:
        if not isinstance(row, dict):
            continue
        cells = "".join(
            f"<td>{html.escape(_format_table_value(row.get(column)))}</td>"
            for column in columns
        )
        body_rows.append(f"<tr>{cells}</tr>")
    if not body_rows:
        return "<p>No rows available.</p>"
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _table_label(column: str) -> str:
    return column.replace("_", " ").title()


def _format_table_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _render_chart_shell(chart: dict[str, Any]) -> str:
    chart_id = str(chart.get("id") or "")
    title = str(chart.get("title") or "Chart")
    if not chart_id:
        return ""
    return (
        '<article class="chart-card">'
        f'<div class="chart-title">{html.escape(title)}</div>'
        f'<div class="plotly-chart" id="{html.escape(chart_id)}"></div>'
        '</article>'
    )


__all__ = [
    "DASHBOARD_SCHEMA",
    "build_production_dashboard_manifest",
    "write_production_dashboard",
]
