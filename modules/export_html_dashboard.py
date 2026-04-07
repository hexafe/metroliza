"""Generate HTML dashboard sidecars for export summary charts."""

from __future__ import annotations

from datetime import datetime
import html
import json
import math
from pathlib import Path
import re
from typing import Any


_PLOTLY_COLORWAY = [
    "#245a5a",
    "#d66e2f",
    "#476f95",
    "#7a8f3d",
    "#b2503c",
    "#6a5f85",
]
_PLOTLY_JS_ASSET_DIRNAME = "html_dashboard_assets"
_PLOTLY_JS_FILENAME = "plotly-2.27.0.min.js"
_PLOTLY_MODEBAR_REMOVE = [
    "lasso2d",
    "select2d",
    "autoScale2d",
    "toggleSpikelines",
]


def resolve_html_dashboard_path(excel_file: str | Path) -> Path:
    """Return the default HTML dashboard path for an exported workbook."""

    excel_path = Path(str(excel_file))
    stem = excel_path.stem or "metroliza_export"
    return excel_path.with_name(f"{stem}_dashboard.html")


def resolve_html_dashboard_assets_dir(html_path: str | Path) -> Path:
    """Return the asset directory paired with an HTML dashboard."""

    dashboard_path = Path(str(html_path))
    stem = dashboard_path.stem or "metroliza_dashboard"
    return dashboard_path.with_name(f"{stem}_assets")


def _resolve_bundled_plotly_js_path() -> Path:
    return Path(__file__).resolve().with_name(_PLOTLY_JS_ASSET_DIRNAME) / _PLOTLY_JS_FILENAME


def summarize_dashboard_chart_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Build a compact, JSON-safe payload summary for dashboard diagnostics."""

    if not isinstance(payload, dict):
        return {}

    chart_type = str(payload.get("type") or "").strip().lower()
    summary: dict[str, Any] = {
        "type": chart_type,
        "title": str(payload.get("title") or ""),
    }

    if chart_type == "histogram":
        visual_metadata = payload.get("visual_metadata") if isinstance(payload.get("visual_metadata"), dict) else {}
        modeled_overlays = visual_metadata.get("modeled_overlays") if isinstance(visual_metadata, dict) else {}
        summary.update(
            {
                "sample_count": len(payload.get("values") or []),
                "bin_count": payload.get("bin_count"),
                "limits": {
                    "lsl": payload.get("lsl"),
                    "usl": payload.get("usl"),
                    "nominal": (payload.get("limits") or {}).get("nominal") if isinstance(payload.get("limits"), dict) else None,
                },
                "annotation_count": len(visual_metadata.get("annotation_rows") or []),
                "summary_row_count": len(((visual_metadata.get("summary_stats_table") or {}).get("rows") or [])),
                "overlay_count": len((modeled_overlays or {}).get("rows") or []),
            }
        )
        return summary

    if chart_type == "distribution":
        series = payload.get("series") or []
        summary.update(
            {
                "render_mode": payload.get("render_mode") or "violin",
                "group_count": len(payload.get("labels") or []),
                "series_sizes": [len(values or []) for values in series[:6]],
                "label_preview": [str(label) for label in (payload.get("labels") or [])[:6]],
                "legend_items": len(((payload.get("legend") or {}).get("items") or [])),
            }
        )
        if payload.get("render_mode") == "scatter":
            summary["point_count"] = len(payload.get("x_values") or [])
        return summary

    if chart_type == "iqr":
        series = payload.get("series") or []
        summary.update(
            {
                "group_count": len(payload.get("labels") or []),
                "series_sizes": [len(values or []) for values in series[:6]],
                "label_preview": [str(label) for label in (payload.get("labels") or [])[:6]],
                "legend_items": len(((payload.get("legend") or {}).get("items") or [])),
            }
        )
        return summary

    if chart_type == "trend":
        summary.update(
            {
                "point_count": len(payload.get("x_values") or []),
                "label_preview": [str(label) for label in (payload.get("labels") or [])[:8]],
                "horizontal_limits": [value for value in (payload.get("horizontal_limits") or []) if value is not None],
            }
        )
        return summary

    return summary


def extract_dashboard_chart_details(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Build display-focused chart metadata for richer dashboard rendering."""

    if not isinstance(payload, dict):
        return {}

    chart_type = str(payload.get("type") or "").strip().lower()
    if chart_type != "histogram":
        return {}

    visual_metadata = payload.get("visual_metadata") if isinstance(payload.get("visual_metadata"), dict) else {}
    summary_stats_table = (
        visual_metadata.get("summary_stats_table")
        if isinstance(visual_metadata.get("summary_stats_table"), dict)
        else {}
    )
    modeled_overlays = (
        visual_metadata.get("modeled_overlays")
        if isinstance(visual_metadata.get("modeled_overlays"), dict)
        else {}
    )
    style = payload.get("style") if isinstance(payload.get("style"), dict) else {}
    raw_limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
    limits = {
        "nominal": raw_limits.get("nominal"),
        "lsl": raw_limits.get("lsl", payload.get("lsl")),
        "usl": raw_limits.get("usl", payload.get("usl")),
    }
    overlay_labels = []
    for index, row in enumerate(modeled_overlays.get("rows") or [], start=1):
        normalized_label = _resolve_histogram_overlay_label(row, index=index)
        if normalized_label:
            overlay_labels.append(normalized_label)

    return {
        "sample_count": len(payload.get("values") or []),
        "bin_count": payload.get("bin_count"),
        "axis_labels": {
            "x": str(style.get("axis_label_x") or "Measurement"),
            "y": str(style.get("axis_label_y") or "Count"),
        },
        "limits": _normalize_limits(limits),
        "summary_stats_table": {
            "title": str(summary_stats_table.get("title") or payload.get("summary_table_title") or "Parameter"),
            "rows": _normalize_summary_rows(
                (summary_stats_table.get("rows") or [])
                or (payload.get("summary_table_rows") or [])
            ),
        },
        "annotations": _normalize_histogram_annotation_rows(
            (visual_metadata.get("annotation_rows") or [])
            or (payload.get("annotation_rows") or [])
        ),
        "specification_lines": _normalize_histogram_specification_lines(
            (visual_metadata.get("specification_lines") or [])
            or (payload.get("specification_lines") or [])
        ),
        "modeled_overlays": {
            "status": str(modeled_overlays.get("status") or ("enabled" if overlay_labels else "disabled")),
            "rows": overlay_labels,
        },
    }


def write_export_html_dashboard(
    *,
    excel_file: str | Path,
    output_path: str | Path,
    assets_dir: str | Path,
    sections: list[dict[str, Any]],
    chart_observability_summary: dict[str, Any] | None = None,
    backend_diagnostics_lines: list[str] | None = None,
    group_analysis_payload: dict[str, Any] | None = None,
    group_analysis_plot_assets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist an HTML dashboard plus a sibling asset directory."""

    dashboard_path = Path(str(output_path))
    asset_directory = Path(str(assets_dir))
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    asset_directory.mkdir(parents=True, exist_ok=True)

    section_entries: list[dict[str, Any]] = []
    chart_count = 0
    for section_index, raw_section in enumerate(sections, start=1):
        charts: list[dict[str, Any]] = []
        for chart_index, raw_chart in enumerate(raw_section.get("charts") or [], start=1):
            image_bytes = _coerce_image_bytes(raw_chart.get("image_buffer"))
            image_name = (
                f"section_{section_index:03d}_{_slugify(raw_section.get('header') or 'header')}_"
                f"{_slugify(raw_chart.get('chart_type') or 'chart')}_{chart_index:02d}.png"
            )
            image_path = asset_directory / image_name
            image_path.write_bytes(image_bytes)
            charts.append(
                {
                    "chart_type": str(raw_chart.get("chart_type") or ""),
                    "title": str(raw_chart.get("title") or ""),
                    "backend": str(raw_chart.get("backend") or ""),
                    "note": str(raw_chart.get("note") or ""),
                    "image_path": f"{asset_directory.name}/{image_name}",
                    "payload_summary": summarize_dashboard_chart_payload(raw_chart.get("payload")),
                    "payload_details": extract_dashboard_chart_details(raw_chart.get("payload")),
                    "plotly_spec": _build_plotly_chart_spec(
                        raw_chart.get("payload"),
                        title=str(raw_chart.get("title") or raw_chart.get("chart_type") or "Chart"),
                    ),
                }
            )
            chart_count += 1

        section_entries.append(
            {
                "id": f"section-{section_index:03d}",
                "header": str(raw_section.get("header") or ""),
                "subtitle": str(raw_section.get("subtitle") or ""),
                "reference": str(raw_section.get("reference") or ""),
                "axis": str(raw_section.get("axis") or ""),
                "grouping_applied": bool(raw_section.get("grouping_applied")),
                "sample_size": int(raw_section.get("sample_size") or 0),
                "limits": _normalize_limits(raw_section.get("limits")),
                "summary_rows": _normalize_summary_rows(raw_section.get("summary_rows")),
                "charts": charts,
            }
        )

    normalized_group_analysis = _normalize_group_analysis_manifest(
        group_analysis_payload,
        group_analysis_plot_assets,
        asset_directory=asset_directory,
    )
    chart_count += int(normalized_group_analysis.get("plot_count") or 0) if normalized_group_analysis else 0
    interactive_chart_count = _count_plotly_specs(section_entries, normalized_group_analysis)
    plotly_runtime_status = "not_needed"
    plotly_js_path = (
        _copy_plotly_runtime_asset(asset_directory)
        if interactive_chart_count > 0
        else None
    )
    if interactive_chart_count > 0 and not plotly_js_path:
        _drop_plotly_specs(section_entries, normalized_group_analysis)
        interactive_chart_count = 0
        plotly_runtime_status = "snapshot_only"
    elif plotly_js_path:
        plotly_runtime_status = "local"

    manifest = {
        "excel_file": str(Path(str(excel_file)).name),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "section_count": len(section_entries),
        "chart_count": chart_count,
        "interactive_chart_count": interactive_chart_count,
        "plotly_js_path": plotly_js_path,
        "plotly_runtime_status": plotly_runtime_status,
        "sections": section_entries,
        "group_analysis": normalized_group_analysis,
        "chart_observability_summary": chart_observability_summary or {},
        "backend_diagnostics_lines": [str(line) for line in (backend_diagnostics_lines or []) if str(line).strip()],
    }
    dashboard_path.write_text(_render_dashboard_html(manifest), encoding="utf-8")
    return {
        "html_dashboard_path": str(dashboard_path),
        "html_dashboard_assets_path": str(asset_directory),
        "html_dashboard_section_count": int(len(section_entries)),
        "html_dashboard_chart_count": int(chart_count),
    }


def _coerce_image_bytes(image_buffer: Any) -> bytes:
    if isinstance(image_buffer, (bytes, bytearray)):
        return bytes(image_buffer)
    if hasattr(image_buffer, "getvalue"):
        return bytes(image_buffer.getvalue())
    raise TypeError("Dashboard chart image buffer must expose bytes or getvalue().")


def _copy_plotly_runtime_asset(asset_directory: Path) -> str | None:
    source_path = _resolve_bundled_plotly_js_path()
    if not source_path.exists():
        return None

    destination_path = asset_directory / _PLOTLY_JS_FILENAME
    destination_path.write_bytes(source_path.read_bytes())
    return f"{asset_directory.name}/{destination_path.name}"


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized or "item"


def _normalize_limits(limits: Any) -> dict[str, Any]:
    if not isinstance(limits, dict):
        return {"nominal": None, "lsl": None, "usl": None}
    return {
        "nominal": limits.get("nominal"),
        "lsl": limits.get("lsl"),
        "usl": limits.get("usl"),
    }


def _normalize_summary_rows(rows: Any) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for row in rows or []:
        if isinstance(row, dict):
            label = row.get("label")
            value = row.get("value")
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            label, value = row[0], row[1]
        else:
            continue
        normalized.append(
            {
                "label": "" if label is None else str(label),
                "value": _format_display_value(value),
            }
        )
    return normalized


def _normalize_histogram_annotation_rows(rows: Any) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or row.get("kind") or "").strip()
        text = str(row.get("text") or "").strip()
        if not label and not text:
            continue
        normalized.append(
            {
                "label": label or "Annotation",
                "value": text or _format_display_value(row.get("x")),
            }
        )
    return normalized


def _normalize_histogram_specification_lines(rows: Any) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        enabled = bool(row.get("enabled", row.get("value") is not None))
        if not enabled:
            continue
        label = str(row.get("label") or row.get("id") or "Spec line").strip()
        normalized.append({"label": label, "value": _format_display_value(row.get("value"))})
    return normalized


def _resolve_histogram_overlay_label(row: Any, *, index: int) -> str:
    if not isinstance(row, dict):
        return ""
    kind = str(row.get("kind") or "").strip().lower()
    explicit_label = str(row.get("label") or "").strip()
    if explicit_label:
        return explicit_label
    if kind == "curve_note":
        return str(row.get("label") or "Overlay note").strip()
    if row.get("fill_to_baseline"):
        return "Tail shading"
    if row.get("dash"):
        return "KDE reference (dashed)"
    if kind == "curve":
        return "Selected model curve" if index == 1 else f"Curve overlay {index}"
    return kind.replace("_", " ").strip().title() or f"Overlay {index}"


def _format_display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        if math.isclose(value, round(value), abs_tol=1e-9):
            return str(int(round(value)))
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, (list, tuple)):
        return ", ".join(_format_display_value(item) for item in value if _format_display_value(item))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _coerce_finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _coerce_finite_float_list(values: Any) -> list[float]:
    output: list[float] = []
    for value in values or []:
        number = _coerce_finite_float(value)
        if number is not None:
            output.append(number)
    return output


def _coerce_xy_points(x_values: Any, y_values: Any, *, labels: Any = None) -> list[tuple[float, float, str]]:
    points: list[tuple[float, float, str]] = []
    raw_labels = labels or []
    for index, (raw_x, raw_y) in enumerate(zip(x_values or [], y_values or [])):
        x_value = _coerce_finite_float(raw_x)
        y_value = _coerce_finite_float(raw_y)
        if x_value is None or y_value is None:
            continue
        label = ""
        if index < len(raw_labels) and raw_labels[index] is not None:
            label = str(raw_labels[index])
        points.append((x_value, y_value, label))
    return points


def _resolve_plotly_histogram_bin_count(values: list[float], *, preferred: Any = None) -> int:
    preferred_count = int(preferred or 0) if _coerce_finite_float(preferred) is not None else 0
    if preferred_count > 0:
        return preferred_count
    sample_count = len(values)
    if sample_count <= 1:
        return 1
    return max(6, min(24, int(round(math.sqrt(sample_count)))))


def _resolve_plotly_histogram_bins(values: list[float], *, preferred: Any = None) -> dict[str, float]:
    if not values:
        return {}

    minimum = min(values)
    maximum = max(values)
    if math.isclose(minimum, maximum, rel_tol=1e-9, abs_tol=1e-9):
        padding = max(abs(minimum) * 0.01, 0.5)
        minimum -= padding
        maximum += padding

    bin_count = _resolve_plotly_histogram_bin_count(values, preferred=preferred)
    bin_size = (maximum - minimum) / max(bin_count, 1)
    if not math.isfinite(bin_size) or bin_size <= 0:
        bin_size = 1.0

    return {
        "start": minimum,
        "end": maximum,
        "size": bin_size,
    }


def _build_plotly_base_layout(*, title: str, x_label: str, y_label: str) -> dict[str, Any]:
    return {
        "title": {"text": str(title or ""), "font": {"size": 18}},
        "font": {"family": 'Aptos, "Segoe UI", "Helvetica Neue", sans-serif', "color": "#162330"},
        "paper_bgcolor": "rgba(255,255,255,0)",
        "plot_bgcolor": "rgba(255,255,255,0.88)",
        "colorway": list(_PLOTLY_COLORWAY),
        "dragmode": "zoom",
        "margin": {"l": 56, "r": 24, "t": 58, "b": 56},
        "hoverlabel": {"bgcolor": "#162330", "font": {"color": "#f8fafc"}},
        "xaxis": {
            "title": {"text": str(x_label or "")},
            "gridcolor": "rgba(22,35,48,0.08)",
            "zerolinecolor": "rgba(22,35,48,0.12)",
            "linecolor": "rgba(22,35,48,0.18)",
        },
        "yaxis": {
            "title": {"text": str(y_label or "")},
            "gridcolor": "rgba(22,35,48,0.08)",
            "zerolinecolor": "rgba(22,35,48,0.12)",
            "linecolor": "rgba(22,35,48,0.18)",
        },
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0.0,
            "bgcolor": "rgba(255,255,255,0.72)",
            "bordercolor": "rgba(22,35,48,0.08)",
            "borderwidth": 1,
        },
    }


def _build_plotly_config() -> dict[str, Any]:
    return {
        "responsive": True,
        "scrollZoom": False,
        "displaylogo": False,
        "modeBarButtonsToRemove": list(_PLOTLY_MODEBAR_REMOVE),
    }


def _build_vertical_reference_shapes(*, nominal: Any = None, lsl: Any = None, usl: Any = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    shapes: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    for label, value, color, dash in (
        ("LSL", lsl, "#B45309", "dash"),
        ("Nominal", nominal, "#0F766E", "dot"),
        ("USL", usl, "#B45309", "dash"),
    ):
        numeric = _coerce_finite_float(value)
        if numeric is None:
            continue
        shapes.append(
            {
                "type": "line",
                "xref": "x",
                "yref": "paper",
                "x0": numeric,
                "x1": numeric,
                "y0": 0,
                "y1": 1,
                "line": {"color": color, "width": 2, "dash": dash},
            }
        )
        annotations.append(
            {
                "xref": "x",
                "yref": "paper",
                "x": numeric,
                "y": 1.02,
                "text": f"{label}={numeric:.3f}",
                "showarrow": False,
                "font": {"size": 11, "color": color},
                "bgcolor": "rgba(255,255,255,0.84)",
            }
        )
    return shapes, annotations


def _build_horizontal_reference_shapes(*, nominal: Any = None, lsl: Any = None, usl: Any = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    shapes: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    for label, value, color, dash in (
        ("LSL", lsl, "#B45309", "dash"),
        ("Nominal", nominal, "#0F766E", "dot"),
        ("USL", usl, "#B45309", "dash"),
    ):
        numeric = _coerce_finite_float(value)
        if numeric is None:
            continue
        shapes.append(
            {
                "type": "line",
                "xref": "paper",
                "yref": "y",
                "x0": 0,
                "x1": 1,
                "y0": numeric,
                "y1": numeric,
                "line": {"color": color, "width": 2, "dash": dash},
            }
        )
        annotations.append(
            {
                "xref": "paper",
                "yref": "y",
                "x": 1.0,
                "y": numeric,
                "xanchor": "right",
                "text": f"{label}={numeric:.3f}",
                "showarrow": False,
                "font": {"size": 11, "color": color},
                "bgcolor": "rgba(255,255,255,0.84)",
            }
        )
    return shapes, annotations


def _apply_plotly_categorical_axis(layout: dict[str, Any], axis_key: str, axis_layout: dict[str, Any] | None) -> None:
    if not isinstance(axis_layout, dict):
        return

    tick_values = _coerce_finite_float_list(axis_layout.get("display_positions"))
    tick_labels = [str(item) for item in (axis_layout.get("display_labels") or [])]
    axis = layout.setdefault(axis_key, {})
    if tick_values and len(tick_values) == len(tick_labels):
        axis.update({"tickmode": "array", "tickvals": tick_values, "ticktext": tick_labels})

    rotation = int(axis_layout.get("rotation") or 0)
    if rotation:
        axis["tickangle"] = -rotation


def _build_plotly_histogram_spec(payload: dict[str, Any], *, title: str) -> dict[str, Any]:
    values = _coerce_finite_float_list(payload.get("values"))
    if not values:
        return {}

    limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
    lsl = limits.get("lsl", payload.get("lsl")) if isinstance(limits, dict) else payload.get("lsl")
    usl = limits.get("usl", payload.get("usl")) if isinstance(limits, dict) else payload.get("usl")
    nominal = limits.get("nominal") if isinstance(limits, dict) else None
    mean_value = _coerce_finite_float(((payload.get("summary") or {}).get("mean") if isinstance(payload.get("summary"), dict) else None))
    if mean_value is None and values:
        mean_value = float(sum(values) / len(values))

    layout = _build_plotly_base_layout(
        title=title,
        x_label=str(((payload.get("style") or {}).get("axis_label_x") if isinstance(payload.get("style"), dict) else "") or "Measurement"),
        y_label=str(((payload.get("style") or {}).get("axis_label_y") if isinstance(payload.get("style"), dict) else "") or "Count"),
    )
    shapes, annotations = _build_vertical_reference_shapes(nominal=nominal, lsl=lsl, usl=usl)
    if mean_value is not None:
        shapes.append(
            {
                "type": "line",
                "xref": "x",
                "yref": "paper",
                "x0": mean_value,
                "x1": mean_value,
                "y0": 0,
                "y1": 1,
                "line": {"color": "#245a5a", "width": 2, "dash": "dashdot"},
            }
        )
        annotations.append(
            {
                "xref": "x",
                "yref": "paper",
                "x": mean_value,
                "y": 1.10,
                "text": f"Mean={mean_value:.3f}",
                "showarrow": False,
                "font": {"size": 11, "color": "#245a5a"},
                "bgcolor": "rgba(255,255,255,0.84)",
            }
        )
    layout["shapes"] = shapes
    layout["annotations"] = annotations
    x_view = payload.get("x_view") if isinstance(payload.get("x_view"), dict) else {}
    x_min = _coerce_finite_float(x_view.get("min"))
    x_max = _coerce_finite_float(x_view.get("max"))
    if x_min is not None and x_max is not None and x_min < x_max:
        layout["xaxis"]["range"] = [x_min, x_max]
    layout["bargap"] = 0.04
    bins = _resolve_plotly_histogram_bins(values, preferred=payload.get("bin_count"))

    return {
        "data": [
            {
                "type": "histogram",
                "x": values,
                "xbins": bins,
                "bingroup": f"hist-{_slugify(title)[:40]}",
                "marker": {"color": "#245a5a", "line": {"color": "#ffffff", "width": 1}},
                "opacity": 0.86,
                "hovertemplate": "Measurement=%{x}<br>Count=%{y}<extra></extra>",
            }
        ],
        "layout": layout,
        "config": _build_plotly_config(),
    }


def _build_plotly_distribution_spec(payload: dict[str, Any], *, title: str) -> dict[str, Any]:
    render_mode = str(payload.get("render_mode") or "violin").strip().lower()
    limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
    lsl = limits.get("lsl", payload.get("lsl")) if isinstance(limits, dict) else payload.get("lsl")
    usl = limits.get("usl", payload.get("usl")) if isinstance(limits, dict) else payload.get("usl")
    nominal = limits.get("nominal", payload.get("nominal")) if isinstance(limits, dict) else payload.get("nominal")

    if render_mode == "scatter":
        points = _coerce_xy_points(
            payload.get("x_values"),
            payload.get("y_values"),
            labels=payload.get("labels"),
        )
        if not points:
            return {}
        x_values = [point[0] for point in points]
        y_values = [point[1] for point in points]
        point_labels = [point[2] or _format_display_value(point[0]) for point in points]
        layout = _build_plotly_base_layout(
            title=title,
            x_label=str(payload.get("x_label") or "Sample"),
            y_label=str(payload.get("y_label") or "Measurement"),
        )
        shapes, annotations = _build_horizontal_reference_shapes(nominal=nominal, lsl=lsl, usl=usl)
        layout["shapes"] = shapes
        layout["annotations"] = annotations
        _apply_plotly_categorical_axis(
            layout,
            "xaxis",
            payload.get("layout") if isinstance(payload.get("layout"), dict) else None,
        )
        y_limits = payload.get("y_limits") if isinstance(payload.get("y_limits"), dict) else {}
        y_min = _coerce_finite_float(y_limits.get("min"))
        y_max = _coerce_finite_float(y_limits.get("max"))
        if y_min is not None and y_max is not None and y_min < y_max:
            layout["yaxis"]["range"] = [y_min, y_max]
        return {
            "data": [
                {
                    "type": "scatter",
                    "mode": "markers",
                    "x": x_values,
                    "y": y_values,
                    "customdata": point_labels,
                    "marker": {"color": "#245a5a", "size": 8, "opacity": 0.82},
                    "hovertemplate": "Point=%{customdata}<br>X=%{x}<br>Measurement=%{y}<extra></extra>",
                }
            ],
            "layout": layout,
            "config": _build_plotly_config(),
        }

    labels = [str(item) for item in (payload.get("labels") or [])]
    series_list = payload.get("series") or []
    traces = []
    for index, (label, series) in enumerate(zip(labels, series_list), start=1):
        values = _coerce_finite_float_list(series)
        if not values:
            continue
        traces.append(
            {
                "type": "violin",
                "name": label or f"Group {index}",
                "y": values,
                "x": [label or f"Group {index}"] * len(values),
                "box": {"visible": True},
                "meanline": {"visible": True},
                "line": {"width": 1.2},
                "opacity": 0.84,
                "points": False,
                "scalemode": "count",
                "spanmode": "hard",
                "hovertemplate": f"{label or f'Group {index}'}<br>Measurement=%{{y}}<extra></extra>",
            }
        )
    if not traces:
        return {}

    layout = _build_plotly_base_layout(
        title=title,
        x_label=str(payload.get("x_label") or "Group"),
        y_label=str(payload.get("y_label") or "Measurement"),
    )
    shapes, annotations = _build_horizontal_reference_shapes(nominal=nominal, lsl=lsl, usl=usl)
    layout["shapes"] = shapes
    layout["annotations"] = annotations
    y_limits = payload.get("y_limits") if isinstance(payload.get("y_limits"), dict) else {}
    y_min = _coerce_finite_float(y_limits.get("min"))
    y_max = _coerce_finite_float(y_limits.get("max"))
    if y_min is not None and y_max is not None and y_min < y_max:
        layout["yaxis"]["range"] = [y_min, y_max]
    return {
        "data": traces,
        "layout": layout,
        "config": _build_plotly_config(),
    }


def _build_plotly_iqr_spec(payload: dict[str, Any], *, title: str) -> dict[str, Any]:
    labels = [str(item) for item in (payload.get("labels") or [])]
    series_list = payload.get("series") or []
    traces = []
    for index, (label, series) in enumerate(zip(labels, series_list), start=1):
        values = _coerce_finite_float_list(series)
        if not values:
            continue
        traces.append(
            {
                "type": "box",
                "name": label or f"Group {index}",
                "y": values,
                "boxpoints": False,
                "boxmean": True,
                "marker": {"color": _PLOTLY_COLORWAY[(index - 1) % len(_PLOTLY_COLORWAY)]},
                "hovertemplate": f"{label or f'Group {index}'}<br>Measurement=%{{y}}<extra></extra>",
            }
        )
    if not traces:
        return {}

    layout = _build_plotly_base_layout(
        title=title,
        x_label=str(payload.get("x_label") or "Group"),
        y_label=str(payload.get("y_label") or "Measurement"),
    )
    shapes, annotations = _build_horizontal_reference_shapes(
        nominal=payload.get("nominal"),
        lsl=payload.get("lsl"),
        usl=payload.get("usl"),
    )
    layout["shapes"] = shapes
    layout["annotations"] = annotations
    _apply_plotly_categorical_axis(
        layout,
        "xaxis",
        payload.get("layout") if isinstance(payload.get("layout"), dict) else None,
    )
    y_limits = payload.get("y_limits") if isinstance(payload.get("y_limits"), dict) else {}
    y_min = _coerce_finite_float(y_limits.get("min"))
    y_max = _coerce_finite_float(y_limits.get("max"))
    if y_min is not None and y_max is not None and y_min < y_max:
        layout["yaxis"]["range"] = [y_min, y_max]
    return {
        "data": traces,
        "layout": layout,
        "config": _build_plotly_config(),
    }


def _build_plotly_trend_spec(payload: dict[str, Any], *, title: str) -> dict[str, Any]:
    points = _coerce_xy_points(
        payload.get("x_values"),
        payload.get("y_values"),
        labels=payload.get("labels"),
    )
    if not points:
        return {}
    points.sort(key=lambda item: item[0])
    x_values = [point[0] for point in points]
    y_values = [point[1] for point in points]
    sample_labels = [point[2] or _format_display_value(point[0]) for point in points]
    layout = _build_plotly_base_layout(
        title=title,
        x_label=str(payload.get("x_label") or "Sample"),
        y_label=str(payload.get("y_label") or "Measurement"),
    )
    layout["hovermode"] = "x unified"
    shapes = []
    annotations = []
    for index, limit in enumerate(payload.get("horizontal_limits") or [], start=1):
        numeric_limit = _coerce_finite_float(limit)
        if numeric_limit is None:
            continue
        shapes.append(
            {
                "type": "line",
                "xref": "paper",
                "yref": "y",
                "x0": 0,
                "x1": 1,
                "y0": numeric_limit,
                "y1": numeric_limit,
                "line": {"color": "#B45309", "width": 2, "dash": "dash"},
            }
        )
        annotations.append(
            {
                "xref": "paper",
                "yref": "y",
                "x": 1.0,
                "y": numeric_limit,
                "xanchor": "right",
                "text": f"Limit {index}={numeric_limit:.3f}",
                "showarrow": False,
                "font": {"size": 11, "color": "#B45309"},
                "bgcolor": "rgba(255,255,255,0.84)",
            }
        )
    layout["shapes"] = shapes
    layout["annotations"] = annotations
    _apply_plotly_categorical_axis(
        layout,
        "xaxis",
        payload.get("layout") if isinstance(payload.get("layout"), dict) else None,
    )
    x_limits = payload.get("x_limits") if isinstance(payload.get("x_limits"), dict) else {}
    x_min = _coerce_finite_float(x_limits.get("min"))
    x_max = _coerce_finite_float(x_limits.get("max"))
    if x_min is not None and x_max is not None and x_min < x_max:
        layout["xaxis"]["range"] = [x_min, x_max]
    y_limits = payload.get("y_limits") if isinstance(payload.get("y_limits"), dict) else {}
    y_min = _coerce_finite_float(y_limits.get("min"))
    y_max = _coerce_finite_float(y_limits.get("max"))
    if y_min is not None and y_max is not None and y_min < y_max:
        layout["yaxis"]["range"] = [y_min, y_max]
    return {
        "data": [
            {
                "type": "scatter",
                "mode": "lines+markers",
                "x": x_values,
                "y": y_values,
                "customdata": sample_labels,
                "line": {"color": "#245a5a", "width": 2},
                "marker": {"size": 8, "color": "#d66e2f"},
                "hovertemplate": "Sample=%{customdata}<br>Measurement=%{y}<extra></extra>",
            }
        ],
        "layout": layout,
        "config": _build_plotly_config(),
    }


def _build_group_analysis_plotly_spec(
    metric_name: str,
    plot_key: str,
    chart_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(chart_payload, dict):
        return {}

    groups = chart_payload.get("groups") or []
    normalized_groups = []
    all_values: list[float] = []
    for index, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            continue
        label = str(group.get("group") or f"Group {index}")
        values = _coerce_finite_float_list(group.get("values"))
        if not values:
            continue
        normalized_groups.append((label, values))
        all_values.extend(values)
    if not normalized_groups:
        return {}

    spec_limits = chart_payload.get("spec_limits") if isinstance(chart_payload.get("spec_limits"), dict) else {}
    plot_key_normalized = str(plot_key or "").strip().lower()
    if plot_key_normalized == "violin":
        payload = {
            "render_mode": "violin",
            "labels": [label for label, _values in normalized_groups],
            "series": [values for _label, values in normalized_groups],
            "x_label": "Group",
            "y_label": "Measurement",
            "limits": dict(spec_limits),
        }
        return _build_plotly_distribution_spec(payload, title=f"{metric_name} - Violin")

    if plot_key_normalized == "histogram":
        layout = _build_plotly_base_layout(
            title=f"{metric_name} - Histogram",
            x_label="Measurement",
            y_label="Count",
        )
        layout["bargap"] = 0.04
        layout["hovermode"] = "x unified"
        shapes, annotations = _build_vertical_reference_shapes(
            nominal=spec_limits.get("nominal"),
            lsl=spec_limits.get("lsl"),
            usl=spec_limits.get("usl"),
        )
        for index, (label, values) in enumerate(normalized_groups, start=1):
            mean_value = float(sum(values) / len(values))
            color = _PLOTLY_COLORWAY[(index - 1) % len(_PLOTLY_COLORWAY)]
            shapes.append(
                {
                    "type": "line",
                    "xref": "x",
                    "yref": "paper",
                    "x0": mean_value,
                    "x1": mean_value,
                    "y0": 0,
                    "y1": 1,
                    "line": {"color": color, "width": 2, "dash": "dashdot"},
                }
            )
            annotations.append(
                {
                    "xref": "x",
                    "yref": "paper",
                    "x": mean_value,
                    "y": 1.08,
                    "text": f"{label} μ={mean_value:.3f}",
                    "showarrow": False,
                    "font": {"size": 11, "color": color},
                    "bgcolor": "rgba(255,255,255,0.84)",
                }
            )
        layout["shapes"] = shapes
        layout["annotations"] = annotations
        bins = _resolve_plotly_histogram_bins(all_values)
        return {
            "data": [
                {
                    "type": "histogram",
                    "name": label,
                    "x": values,
                    "xbins": bins,
                    "bingroup": f"group-hist-{_slugify(metric_name)[:32]}",
                    "marker": {
                        "color": _PLOTLY_COLORWAY[(index - 1) % len(_PLOTLY_COLORWAY)],
                        "line": {"color": "#ffffff", "width": 0.8},
                    },
                    "opacity": 0.55,
                    "hovertemplate": f"{label}<br>Measurement=%{{x}}<br>Count=%{{y}}<extra></extra>",
                }
                for index, (label, values) in enumerate(normalized_groups, start=1)
            ],
            "layout": {**layout, "barmode": "overlay"},
            "config": _build_plotly_config(),
        }

    return {}


def _build_plotly_chart_spec(payload: dict[str, Any] | None, *, title: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    chart_type = str(payload.get("type") or "").strip().lower()
    if chart_type == "histogram":
        return _build_plotly_histogram_spec(payload, title=title)
    if chart_type == "distribution":
        return _build_plotly_distribution_spec(payload, title=title)
    if chart_type == "iqr":
        return _build_plotly_iqr_spec(payload, title=title)
    if chart_type == "trend":
        return _build_plotly_trend_spec(payload, title=title)
    return {}


def _format_ci_interval(interval: Any, *, digits: int = 3) -> str:
    if not isinstance(interval, dict):
        return ""
    lower = _coerce_finite_float(interval.get("lower"))
    upper = _coerce_finite_float(interval.get("upper"))
    if lower is None or upper is None:
        return ""
    return f"95% CI {lower:.{int(digits)}f} to {upper:.{int(digits)}f}"


def _format_capability_ci_value(value: Any) -> str:
    if not isinstance(value, dict):
        return _format_display_value(value)

    parts = []
    for label, key in (("Cp", "cp"), ("Cpk", "cpk")):
        interval_text = _format_ci_interval(value.get(key), digits=3)
        if interval_text:
            parts.append(f"{label}: {interval_text}")

    return "; ".join(parts) if parts else "N/A"


def _humanize_field_label(value: str) -> str:
    overrides = {
        "group": "Group",
        "n": "N",
        "std": "Std dev",
        "cp": "Cp",
        "cpk": "Cpk",
        "group_a": "Group A",
        "group_b": "Group B",
        "delta_mean": "Delta mean",
        "adjusted_p_value": "Adj p",
        "effect_size": "Effect size",
        "test_rationale": "Test / why",
        "best_fit_model": "Best fit model",
        "fit_quality": "Fit quality",
        "distribution_shape_caution": "Shape caution",
        "capability_type": "Capability type",
        "capability_ci": "Capability CI",
        "metric_takeaway": "Takeaway",
        "recommended_action": "Recommended action",
        "diagnostics_comment": "Diagnostics",
        "metric_flags": "Flags",
    }
    if value in overrides:
        return overrides[value]
    if any(token in value for token in (" ", "/", "%", "(", ")")):
        return value
    return value.replace("_", " ").strip().title()


def _normalize_group_analysis_manifest(
    payload: dict[str, Any] | None,
    plot_assets: dict[str, Any] | None,
    *,
    asset_directory: Path,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
    warning_summary = diagnostics.get("warning_summary") if isinstance(diagnostics.get("warning_summary"), dict) else {}
    histogram_skip_summary = (
        diagnostics.get("histogram_skip_summary")
        if isinstance(diagnostics.get("histogram_skip_summary"), dict)
        else {}
    )
    skip_reason = payload.get("skip_reason") if isinstance(payload.get("skip_reason"), dict) else {}
    if not skip_reason:
        readiness = payload.get("readiness") if isinstance(payload.get("readiness"), dict) else {}
        skip_reason = readiness.get("skip_reason") if isinstance(readiness.get("skip_reason"), dict) else {}

    metric_assets = plot_assets.get("metrics") if isinstance(plot_assets, dict) else {}
    metrics = []
    plot_count = 0
    for metric_index, raw_metric in enumerate(payload.get("metric_rows") or [], start=1):
        if not isinstance(raw_metric, dict):
            continue

        metric_name = str(raw_metric.get("metric") or f"Metric {metric_index}")
        per_metric_assets = metric_assets.get(metric_name) if isinstance(metric_assets, dict) else {}
        chart_payload = raw_metric.get("chart_payload") if isinstance(raw_metric.get("chart_payload"), dict) else {}
        plots = []
        for plot_key in ("violin", "histogram"):
            plot_asset = per_metric_assets.get(plot_key) if isinstance(per_metric_assets, dict) else {}
            image_buffer = plot_asset.get("image_data") if isinstance(plot_asset, dict) else None
            plotly_spec = _build_group_analysis_plotly_spec(metric_name, plot_key, chart_payload)
            if image_buffer is None and not plotly_spec:
                continue
            image_relative_path = ""
            if image_buffer is not None:
                image_name = f"group_metric_{metric_index:03d}_{_slugify(metric_name)}_{plot_key}.png"
                image_path = asset_directory / image_name
                image_path.write_bytes(_coerce_image_bytes(image_buffer))
                image_relative_path = f"{asset_directory.name}/{image_name}"
            plots.append(
                {
                    "chart_type": plot_key,
                    "title": f"{metric_name} - {_humanize_field_label(plot_key)}",
                    "backend": "matplotlib",
                    "note": str(plot_asset.get("description") or ""),
                    "image_path": image_relative_path,
                    "payload_summary": {},
                    "payload_details": {},
                    "plotly_spec": plotly_spec,
                }
            )
            plot_count += 1

        distribution_difference = raw_metric.get("distribution_difference")
        distribution_rows = _normalize_summary_rows(
            [
                (str(key), _format_display_value(value))
                for key, value in (distribution_difference.items() if isinstance(distribution_difference, dict) else [])
                if _format_display_value(value)
            ]
        )

        summary_rows = _normalize_summary_rows(
            [
                ("Spec status", raw_metric.get("spec_status_label")),
                ("Restrictions", raw_metric.get("analysis_restriction_label")),
                ("Takeaway", raw_metric.get("metric_takeaway")),
                ("Recommended action", raw_metric.get("recommended_action")),
                ("Diagnostics", raw_metric.get("diagnostics_comment")),
                ("Flags", raw_metric.get("metric_flags")),
            ]
        )

        metrics.append(
            {
                "id": f"group-metric-{metric_index:03d}",
                "metric": metric_name,
                "reference": str(raw_metric.get("reference") or ""),
                "group_count": int(raw_metric.get("group_count") or 0),
                "summary_rows": summary_rows,
                "insights": [str(item) for item in (raw_metric.get("insights") or []) if str(item).strip()],
                "descriptive_stats": _normalize_rows_table(
                    raw_metric.get("descriptive_stats"),
                    preferred_columns=[
                        "group",
                        "n",
                        "mean",
                        "std",
                        "median",
                        "iqr",
                        "min",
                        "max",
                        "cp",
                        "capability",
                        "capability_type",
                        "best_fit_model",
                        "fit_quality",
                        "flags",
                    ],
                ),
                "pairwise_rows": _normalize_rows_table(
                    raw_metric.get("pairwise_rows"),
                    preferred_columns=[
                        "group_a",
                        "group_b",
                        "delta_mean",
                        "adjusted_p_value",
                        "effect_size",
                        "difference",
                        "comment",
                        "takeaway",
                        "test_rationale",
                    ],
                ),
                "distribution_difference": distribution_rows,
                "distribution_pairwise_rows": _normalize_rows_table(raw_metric.get("distribution_pairwise_rows")),
                "plot_eligibility": _normalize_group_analysis_plot_eligibility(raw_metric.get("plot_eligibility")),
                "plots": plots,
            }
        )

    reason_counts = histogram_skip_summary.get("reason_counts") if isinstance(histogram_skip_summary.get("reason_counts"), dict) else {}
    return {
        "status": str(payload.get("status") or ""),
        "analysis_level": _humanize_field_label(str(payload.get("analysis_level") or "")).lower(),
        "effective_scope": str(payload.get("effective_scope") or "").replace("_", " "),
        "skip_reason_message": str(skip_reason.get("message") or ""),
        "summary_rows": _normalize_summary_rows(
            [
                ("Status", payload.get("status")),
                ("Analysis level", str(payload.get("analysis_level") or "").replace("_", " ")),
                ("Scope", str(payload.get("effective_scope") or "").replace("_", " ")),
                ("Metrics", diagnostics.get("metric_count", len(metrics))),
                ("Groups", diagnostics.get("group_count")),
                ("References", diagnostics.get("reference_count")),
                ("Warnings", warning_summary.get("count")),
            ]
        ),
        "warning_messages": [str(item) for item in (warning_summary.get("messages") or []) if str(item).strip()],
        "histogram_skip_summary": {
            "applies": bool(histogram_skip_summary.get("applies")),
            "count": int(histogram_skip_summary.get("count") or 0),
            "reason_rows": _normalize_summary_rows(
                [(str(key), value) for key, value in sorted(reason_counts.items())]
            ),
        },
        "metrics": metrics,
        "plot_count": plot_count,
    }


def _normalize_rows_table(rows: Any, *, preferred_columns: list[str] | None = None) -> dict[str, Any]:
    normalized_rows = [dict(row) for row in (rows or []) if isinstance(row, dict)]
    if not normalized_rows:
        return {"columns": [], "rows": []}

    column_order: list[str] = []
    preferred = list(preferred_columns or [])
    for key in preferred:
        if any(key in row for row in normalized_rows) and key not in column_order:
            column_order.append(key)
    for row in normalized_rows:
        for key in row:
            if key not in column_order:
                column_order.append(key)

    column_labels: dict[str, str] = {}
    if "capability" in column_order and "capability_type" in column_order:
        capability_types = {
            str(row.get("capability_type")).strip()
            for row in normalized_rows
            if str(row.get("capability_type") or "").strip()
        }
        if len(capability_types) == 1:
            capability_label = next(iter(capability_types))
            column_labels["capability"] = capability_label
            column_order = [key for key in column_order if key != "capability_type"]

    return {
        "columns": [
            {"key": key, "label": column_labels.get(key) or _humanize_field_label(str(key))}
            for key in column_order
        ],
        "rows": [
            {
                key: _format_capability_ci_value(row.get(key))
                if key == "capability_ci"
                else _format_display_value(row.get(key))
                for key in column_order
            }
            for row in normalized_rows
        ],
    }


def _normalize_group_analysis_plot_eligibility(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return []
    rows = []
    for plot_key in ("violin", "histogram"):
        plot_meta = value.get(plot_key) if isinstance(value.get(plot_key), dict) else {}
        if not plot_meta:
            continue
        status = "Eligible" if bool(plot_meta.get("eligible")) else "Skipped"
        reason = str(plot_meta.get("skip_reason") or "").replace("_", " ").strip()
        rows.append(
            {
                "label": _humanize_field_label(plot_key),
                "value": status if not reason else f"{status}: {reason}",
            }
        )
    return rows


def _build_debug_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        return {}

    debug_manifest = json.loads(json.dumps(manifest, ensure_ascii=False))
    for section in debug_manifest.get("sections") or []:
        for chart in section.get("charts") or []:
            chart.pop("plotly_spec", None)
    group_analysis = debug_manifest.get("group_analysis") or {}
    for metric in group_analysis.get("metrics") or []:
        for chart in metric.get("plots") or []:
            chart.pop("plotly_spec", None)
    return debug_manifest


def _count_plotly_specs(sections: list[dict[str, Any]], group_analysis: dict[str, Any]) -> int:
    count = 0
    for section in sections:
        for chart in section.get("charts") or []:
            if isinstance(chart.get("plotly_spec"), dict) and chart.get("plotly_spec"):
                count += 1
    for metric in (group_analysis or {}).get("metrics") or []:
        for chart in metric.get("plots") or []:
            if isinstance(chart.get("plotly_spec"), dict) and chart.get("plotly_spec"):
                count += 1
    return count


def _drop_plotly_specs(sections: list[dict[str, Any]], group_analysis: dict[str, Any]) -> None:
    for section in sections:
        for chart in section.get("charts") or []:
            chart.pop("plotly_spec", None)
    for metric in (group_analysis or {}).get("metrics") or []:
        for chart in metric.get("plots") or []:
            chart.pop("plotly_spec", None)


def _render_dashboard_html(manifest: dict[str, Any]) -> str:
    sections = manifest.get("sections") or []
    group_analysis = manifest.get("group_analysis") or {}
    nav_chips = [
        f'<a class="section-chip" href="#{html.escape(section["id"])}">{html.escape(section["header"] or section["id"])}</a>'
        for section in sections
    ]
    if group_analysis:
        nav_chips.append('<a class="section-chip" href="#group-analysis">Group Analysis</a>')
    section_nav = "".join(nav_chips)
    section_blocks = "".join(_render_section(section) for section in sections)
    if not section_blocks and not group_analysis:
        section_blocks = (
            '<section class="empty-state"><h2>No extended summary charts were generated.</h2>'
            '<p>Enable Extended plots or HTML dashboard export for chart-backed dashboard content.</p></section>'
        )
    group_analysis_block = _render_group_analysis(group_analysis)
    diagnostics_block = _render_diagnostics(manifest.get("backend_diagnostics_lines") or [])
    overview_cards = _render_overview_cards(manifest)
    manifest_json = html.escape(json.dumps(_build_debug_manifest(manifest), ensure_ascii=False, indent=2, sort_keys=True))
    nav_markup = f'<nav class="section-nav">{section_nav}</nav>' if section_nav else ""
    plotly_js_path = str(manifest.get("plotly_js_path") or "").strip()
    plotly_script_tag = (
        f'  <script src="{html.escape(plotly_js_path)}" defer></script>\n'
        if plotly_js_path
        else ""
    )
    plotly_status_notice = ""
    if str(manifest.get("plotly_runtime_status") or "") == "snapshot_only":
        plotly_status_notice = (
            '<p class="runtime-note">Interactive Plotly views were unavailable in this export, '
            'so the dashboard is showing workbook-matching PNG snapshots only.</p>'
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Metroliza Dashboard</title>
{plotly_script_tag}  <style>
    :root {{
      --paper: #f5f1e8;
      --ink: #162330;
      --muted: #556270;
      --accent: #d66e2f;
      --accent-soft: #f4c59c;
      --teal: #245a5a;
      --panel: rgba(255, 255, 255, 0.82);
      --line: rgba(22, 35, 48, 0.12);
      --shadow: 0 18px 44px rgba(14, 23, 32, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Aptos, "Segoe UI", "Helvetica Neue", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(214, 110, 47, 0.18), transparent 34%),
        radial-gradient(circle at top right, rgba(36, 90, 90, 0.18), transparent 32%),
        linear-gradient(180deg, #fbf8f2 0%, var(--paper) 100%);
    }}
    .shell {{
      width: min(1480px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 28px 0 52px;
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(255,255,255,0.92), rgba(255,249,241,0.9));
      border: 1px solid var(--line);
      border-radius: 28px;
      box-shadow: var(--shadow);
      padding: 28px 28px 22px;
    }}
    .eyebrow {{
      margin: 0 0 10px;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      color: var(--teal);
      font-weight: 700;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(30px, 3.6vw, 46px);
      line-height: 1.05;
    }}
    .lede {{
      margin: 12px 0 0;
      max-width: 780px;
      color: var(--muted);
      line-height: 1.5;
    }}
    .runtime-note {{
      margin: 14px 0 0;
      max-width: 780px;
      border-left: 4px solid var(--accent);
      padding: 10px 14px;
      border-radius: 12px;
      background: rgba(214, 110, 47, 0.1);
      color: var(--ink);
      line-height: 1.5;
    }}
    .overview-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 24px;
    }}
    .metric-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 16px 18px;
    }}
    .metric-label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      margin-bottom: 8px;
    }}
    .metric-value {{
      font-size: 28px;
      font-weight: 700;
    }}
    .metric-value-line {{
      display: block;
      line-height: 1.15;
    }}
    .section-nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 18px;
    }}
    .section-chip {{
      text-decoration: none;
      color: var(--ink);
      background: rgba(214, 110, 47, 0.12);
      border: 1px solid rgba(214, 110, 47, 0.22);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 13px;
      font-weight: 600;
    }}
    .diagnostics, .measurement-section, .empty-state {{
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow);
      padding: 22px;
    }}
    .measurement-section h2 {{
      margin: 0;
      font-size: 24px;
    }}
    .section-top {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      flex-wrap: wrap;
    }}
    .section-meta {{
      color: var(--muted);
      margin-top: 8px;
      line-height: 1.5;
    }}
    .pill-row {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .pill {{
      border-radius: 999px;
      padding: 8px 12px;
      background: rgba(36, 90, 90, 0.10);
      border: 1px solid rgba(36, 90, 90, 0.18);
      color: var(--teal);
      font-size: 13px;
      font-weight: 600;
    }}
    .summary-table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 18px;
      font-size: 14px;
    }}
    .summary-table td {{
      padding: 9px 10px;
      border-top: 1px solid var(--line);
      vertical-align: top;
    }}
    .summary-table td:first-child {{
      width: 34%;
      color: var(--muted);
      font-weight: 600;
    }}
    .chart-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
      margin-top: 20px;
    }}
    .chart-card {{
      background: rgba(255,255,255,0.88);
      border: 1px solid var(--line);
      border-radius: 20px;
      overflow: hidden;
    }}
    .chart-card header {{
      padding: 16px 18px 0;
    }}
    .chart-meta-row {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-weight: 700;
    }}
    .backend-badge {{
      border-radius: 999px;
      padding: 5px 10px;
      font-size: 11px;
      color: #fff;
      background: var(--teal);
    }}
    .backend-badge.backend-badge--matplotlib {{
      background: var(--accent);
    }}
    .chart-card h3 {{
      margin: 12px 0 0;
      font-size: 18px;
      line-height: 1.25;
    }}
    .chart-note {{
      margin: 10px 0 0;
      color: var(--muted);
      line-height: 1.5;
    }}
    .plotly-shell {{
      margin: 14px 18px 0;
      border-top: 1px solid var(--line);
      padding-top: 14px;
    }}
    .plotly-shell-header {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }}
    .plotly-kicker {{
      color: var(--teal);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-weight: 700;
    }}
    .plotly-shell-note {{
      color: var(--muted);
      font-size: 12px;
    }}
    .plotly-chart {{
      width: 100%;
      min-height: 360px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255,255,255,0.92);
      overflow: hidden;
    }}
    .chart-fallback-shell {{
      margin-top: 14px;
      border-top: 1px solid var(--line);
      padding-top: 14px;
    }}
    .chart-fallback-note {{
      margin: 8px 18px 0;
      color: var(--muted);
      font-size: 12px;
    }}
    .chart-card img {{
      display: block;
      width: 100%;
      height: auto;
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      background: #fff;
      margin-top: 14px;
    }}
    .chart-image-trigger {{
      display: block;
      width: 100%;
      border: 0;
      padding: 0;
      margin: 0;
      background: transparent;
      cursor: zoom-in;
      text-align: left;
    }}
    .chart-image-trigger:focus-visible {{
      outline: 3px solid rgba(214, 110, 47, 0.45);
      outline-offset: 2px;
    }}
    .lightbox {{
      position: fixed;
      inset: 0;
      z-index: 900;
      border: 0;
      margin: 0;
      padding: 0;
      max-width: 100vw;
      max-height: 100vh;
      width: 100vw;
      height: 100vh;
      background: rgba(10, 16, 24, 0.9);
    }}
    .lightbox::backdrop {{
      background: rgba(10, 16, 24, 0.9);
    }}
    .lightbox-shell {{
      position: relative;
      width: min(1600px, calc(100vw - 24px));
      height: min(96vh, calc(100vh - 24px));
      margin: 12px auto;
      display: grid;
      grid-template-rows: auto 1fr;
      gap: 8px;
    }}
    .lightbox-close {{
      justify-self: end;
      border: 1px solid rgba(255, 255, 255, 0.35);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.12);
      color: #fff;
      padding: 8px 14px;
      font-weight: 600;
      cursor: pointer;
    }}
    .lightbox-figure {{
      margin: 0;
      min-height: 0;
      display: grid;
      justify-items: center;
      align-content: center;
      gap: 10px;
    }}
    .lightbox-figure img {{
      width: auto;
      max-width: 100%;
      max-height: calc(100vh - 132px);
      border-radius: 10px;
      background: #fff;
    }}
    .lightbox-figure figcaption {{
      color: #f3f7fb;
      font-size: 15px;
      text-align: center;
    }}
    .detail-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      padding: 16px 18px 0;
    }}
    .detail-panel {{
      background: rgba(22, 35, 48, 0.035);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px 14px;
    }}
    .detail-panel h4 {{
      margin: 0 0 10px;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
    }}
    .detail-cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
      gap: 10px;
    }}
    .detail-card {{
      background: rgba(255, 255, 255, 0.68);
      border: 1px solid rgba(22, 35, 48, 0.08);
      border-radius: 14px;
      padding: 10px 12px;
      min-width: 0;
    }}
    .detail-card-label {{
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.10em;
      font-weight: 700;
      margin-bottom: 6px;
    }}
    .detail-card-value {{
      color: var(--ink);
      font-size: 14px;
      line-height: 1.35;
      font-weight: 600;
      overflow-wrap: anywhere;
    }}
    .detail-table,
    .data-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    .detail-table td,
    .data-table td,
    .data-table th {{
      padding: 8px 9px;
      border-top: 1px solid var(--line);
      vertical-align: top;
      text-align: left;
    }}
    .detail-table td:first-child {{
      width: 42%;
      color: var(--muted);
      font-weight: 600;
    }}
    .data-table th {{
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.10em;
      background: rgba(22, 35, 48, 0.04);
    }}
    .detail-list {{
      margin: 0;
      padding-left: 18px;
    }}
    .table-shell {{
      margin-top: 16px;
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(255,255,255,0.78);
    }}
    .subsection-title {{
      margin: 20px 0 8px;
      font-size: 15px;
      color: var(--teal);
    }}
    .metric-stack {{
      display: grid;
      gap: 16px;
      margin-top: 20px;
    }}
    .metric-block {{
      background: rgba(255,255,255,0.7);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 18px;
    }}
    .metric-block h3 {{
      margin: 0;
      font-size: 20px;
    }}
    .insight-list {{
      margin: 14px 0 0;
    }}
    details {{
      padding: 14px 18px 18px;
    }}
    summary {{
      cursor: pointer;
      font-weight: 600;
    }}
    pre {{
      margin: 12px 0 0;
      background: #121a22;
      color: #eef4f8;
      border-radius: 14px;
      padding: 14px;
      overflow: auto;
      font-size: 12px;
      line-height: 1.45;
    }}
    ul {{
      margin: 12px 0 0;
      padding-left: 18px;
      color: var(--muted);
      line-height: 1.55;
    }}
    @media (max-width: 780px) {{
      .shell {{ width: min(100vw - 18px, 1480px); padding-top: 12px; }}
      .hero, .diagnostics, .measurement-section, .empty-state {{ padding: 18px; border-radius: 18px; }}
      .chart-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <header class="hero">
      <p class="eyebrow">Metroliza Export Dashboard</p>
      <h1>{html.escape(str(manifest.get("excel_file") or "Workbook export"))}</h1>
      <p class="lede">Extended summary charts exported alongside the workbook. When interactive charts are available, the dashboard copies a local Plotly runtime into the asset folder so zoom, pan, and hover inspection work offline, while workbook-matching PNG snapshots stay available for parity checks against the exported sheet.</p>
      {plotly_status_notice}
      {overview_cards}
      {nav_markup}
    </header>
    {diagnostics_block}
    {section_blocks}
    {group_analysis_block}
    <details class="diagnostics">
      <summary>Embedded dashboard manifest</summary>
      <pre>{manifest_json}</pre>
    </details>
  </div>
  <dialog id="chart-lightbox" class="lightbox" aria-label="Enlarged chart">
    <div class="lightbox-shell">
      <button type="button" class="lightbox-close" id="chart-lightbox-close">Close</button>
      <figure class="lightbox-figure">
        <img id="chart-lightbox-image" src="" alt="">
        <figcaption id="chart-lightbox-caption"></figcaption>
      </figure>
    </div>
  </dialog>
  <script>
    (() => {{
      const initializePlotlyCharts = () => {{
        if (!window.Plotly) {{
          return false;
        }}

        document.querySelectorAll('.plotly-chart').forEach((container) => {{
          if (container.dataset.plotlyReady === '1') {{
            return;
          }}
          const rawSpec = container.getAttribute('data-plotly-spec') || '';
          if (!rawSpec) {{
            return;
          }}
          try {{
            const spec = JSON.parse(rawSpec);
            if (!spec || !Array.isArray(spec.data) || !spec.layout) {{
              return;
            }}
            window.Plotly.newPlot(
              container,
              spec.data,
              spec.layout,
              Object.assign({{responsive: true}}, spec.config || {{}})
            );
            container.dataset.plotlyReady = '1';
          }} catch (_error) {{
            container.dataset.plotlyReady = 'error';
          }}
        }});
        return true;
      }};

      const lightbox = document.getElementById('chart-lightbox');
      const lightboxImage = document.getElementById('chart-lightbox-image');
      const lightboxCaption = document.getElementById('chart-lightbox-caption');
      const closeButton = document.getElementById('chart-lightbox-close');
      let plotlyAttempts = 0;
      const tryInitPlotly = () => {{
        if (initializePlotlyCharts() || plotlyAttempts >= 16) {{
          return;
        }}
        plotlyAttempts += 1;
        window.setTimeout(tryInitPlotly, 250);
      }};
      tryInitPlotly();

      if (!lightbox || !lightboxImage || !closeButton) return;

      const closeLightbox = () => {{
        if (lightbox.open) {{
          lightbox.close();
        }}
      }};

      document.querySelectorAll('.chart-image-trigger').forEach((trigger) => {{
        trigger.addEventListener('click', () => {{
          const source = trigger.getAttribute('data-image-src') || '';
          const caption = trigger.getAttribute('data-image-caption') || '';
          if (!source) return;
          lightboxImage.setAttribute('src', source);
          lightboxImage.setAttribute('alt', caption || 'Enlarged chart');
          lightboxCaption.textContent = caption;
          lightbox.showModal();
        }});
      }});

      closeButton.addEventListener('click', closeLightbox);
      lightbox.addEventListener('click', (event) => {{
        if (event.target === lightbox) closeLightbox();
      }});
      document.addEventListener('keydown', (event) => {{
        if (event.key === 'Escape' && lightbox.open) closeLightbox();
      }});
      window.addEventListener('resize', () => {{
        if (!window.Plotly) return;
        document.querySelectorAll('.plotly-chart[data-plotly-ready="1"]').forEach((container) => {{
          window.Plotly.Plots.resize(container);
        }});
      }});
    }})();
  </script>
</body>
</html>
"""


def _render_overview_cards(manifest: dict[str, Any]) -> str:
    summary = manifest.get("chart_observability_summary") or {}
    group_analysis = manifest.get("group_analysis") or {}
    backend_counts = ((summary.get("chart_backend_distribution") or {}).get("counts") or {})
    native_count = int(backend_counts.get("native", 0))
    matplotlib_count = int(backend_counts.get("matplotlib", 0))
    cards = [
        ("Generated", _format_generated_card_value(manifest.get("generated_at")), True),
        ("Sections", str(manifest.get("section_count") or 0), False),
        ("Charts", str(manifest.get("chart_count") or 0), False),
        ("Native renders", str(native_count), False),
        ("Matplotlib renders", str(matplotlib_count), False),
    ]
    metrics = group_analysis.get("metrics") or []
    if metrics:
        cards.append(("Group metrics", str(len(metrics)), False))
    return '<div class="overview-grid">' + "".join(
        f'<div class="metric-card"><div class="metric-label">{html.escape(label)}</div><div class="metric-value">{value if is_markup else html.escape(value)}</div></div>'
        for label, value, is_markup in cards
    ) + '</div>'


def _format_generated_card_value(generated_at: Any) -> str:
    text = str(generated_at or "n/a").strip() or "n/a"
    if text == "n/a":
        escaped = html.escape(text)
        return f'<span class="metric-value-line">{escaped}</span>'

    if "T" in text:
        date_part, time_part = text.split("T", 1)
    elif " " in text:
        date_part, time_part = text.split(" ", 1)
    else:
        escaped = html.escape(text)
        return f'<span class="metric-value-line">{escaped}</span>'

    date_markup = html.escape(date_part.strip() or "n/a")
    time_markup = html.escape(time_part.strip() or "n/a")
    return (
        f'<span class="metric-value-line">{date_markup}</span>'
        f'<span class="metric-value-line">{time_markup}</span>'
    )


def _render_diagnostics(lines: list[str]) -> str:
    if not lines:
        return ""
    items = "".join(f"<li>{html.escape(line)}</li>" for line in lines)
    return f'<section class="diagnostics"><h2>Backend diagnostics</h2><ul>{items}</ul></section>'


def _render_section(section: dict[str, Any]) -> str:
    pills = [
        f"Sample size: {int(section.get('sample_size') or 0)}",
        f"Grouping: {'on' if section.get('grouping_applied') else 'off'}",
    ]
    limits = section.get("limits") or {}
    for label, key in (("Nominal", "nominal"), ("LSL", "lsl"), ("USL", "usl")):
        value = limits.get(key)
        if value is not None:
            pills.append(f"{label}: {value}")
    if section.get("reference"):
        pills.append(f"Reference: {section['reference']}")
    if section.get("axis"):
        pills.append(f"Axis: {section['axis']}")
    pill_markup = "".join(f'<span class="pill">{html.escape(str(pill))}</span>' for pill in pills)
    summary_rows = section.get("summary_rows") or []
    summary_table = ""
    if summary_rows:
        rows_markup = "".join(
            f"<tr><td>{html.escape(row['label'])}</td><td>{html.escape(row['value'])}</td></tr>"
            for row in summary_rows
        )
        summary_table = f'<table class="summary-table">{rows_markup}</table>'
    chart_blocks = "".join(_render_chart_card(chart) for chart in (section.get("charts") or []))
    return (
        f'<section id="{html.escape(section["id"])}" class="measurement-section">'
        f'<div class="section-top"><div><h2>{html.escape(section.get("header") or section["id"])}</h2>'
        f'<div class="section-meta">{html.escape(section.get("subtitle") or "Extended summary output")}</div></div>'
        f'<div class="pill-row">{pill_markup}</div></div>'
        f'{summary_table}'
        f'<div class="chart-grid">{chart_blocks}</div>'
        f'</section>'
    )


def _render_plotly_shell(chart: dict[str, Any]) -> str:
    plotly_spec = chart.get("plotly_spec")
    if not isinstance(plotly_spec, dict) or not plotly_spec:
        return ""

    spec_json = html.escape(json.dumps(plotly_spec, ensure_ascii=False, separators=(",", ":")))
    title = str(chart.get("title") or chart.get("chart_type") or "chart")
    return (
        '<div class="plotly-shell">'
        '<div class="plotly-shell-header">'
        '<span class="plotly-kicker">Interactive Plotly view</span>'
        '<span class="plotly-shell-note">Zoom, pan, and inspect points directly in the saved dashboard.</span>'
        '</div>'
        f'<div class="plotly-chart" aria-label="Interactive chart: {html.escape(title)}" data-plotly-spec="{spec_json}"></div>'
        '</div>'
    )


def _render_chart_snapshot(chart: dict[str, Any], *, interactive_available: bool) -> str:
    image_path = str(chart.get("image_path") or "").strip()
    if not image_path:
        return ""

    title = str(chart.get("title") or chart.get("chart_type") or "chart")
    fallback_note = (
        '<p class="chart-fallback-note">Workbook snapshot PNG kept for parity with the exported sheet.</p>'
        if interactive_available
        else ""
    )
    wrapper_class = "chart-fallback-shell" if interactive_available else ""
    return (
        f'<div class="{wrapper_class}">' if wrapper_class else ""
    ) + (
        f'<button type="button" class="chart-image-trigger" aria-label="Enlarge chart: {html.escape(title)}" '
        f'data-image-src="{html.escape(image_path)}" '
        f'data-image-caption="{html.escape(title)}">'
        f'<img src="{html.escape(image_path)}" alt="{html.escape(title)}">'
        '</button>'
        f'{fallback_note}'
    ) + (
        '</div>' if wrapper_class else ""
    )


def _render_chart_card(chart: dict[str, Any]) -> str:
    backend = str(chart.get("backend") or "")
    backend_class = "backend-badge backend-badge--native" if backend == "native" else "backend-badge backend-badge--matplotlib"
    payload_metadata = {
        "summary": chart.get("payload_summary") or {},
        "details": chart.get("payload_details") or {},
    }
    payload_json = html.escape(json.dumps(payload_metadata, ensure_ascii=False, indent=2, sort_keys=True))
    note_markup = (
        f'<p class="chart-note">{html.escape(chart["note"])}</p>'
        if str(chart.get("note") or "").strip()
        else ""
    )
    chart_type = str(chart.get("chart_type") or "").strip().lower()
    detail_markup = ""
    if chart_type != "histogram":
        detail_markup = _render_chart_payload_details(chart.get("payload_details") or {})
    plotly_markup = _render_plotly_shell(chart)
    snapshot_markup = _render_chart_snapshot(chart, interactive_available=bool(plotly_markup))
    details_toggle = (
        '<details><summary>Chart metadata</summary>'
        f'<pre>{payload_json}</pre>'
        '</details>'
        if payload_metadata["summary"] or payload_metadata["details"]
        else ""
    )
    return (
        '<article class="chart-card">'
        '<header>'
        f'<div class="chart-meta-row"><span>{html.escape(str(chart.get("chart_type") or "chart"))}</span>'
        f'<span class="{backend_class}">{html.escape(backend or "unknown")}</span></div>'
        f'<h3>{html.escape(str(chart.get("title") or ""))}</h3>'
        f'{note_markup}'
        '</header>'
        f'{plotly_markup}'
        f'{snapshot_markup}'
        f'{detail_markup}'
        f'{details_toggle}'
        '</article>'
    )


def _render_chart_payload_details(details: dict[str, Any]) -> str:
    if not isinstance(details, dict) or not details:
        return ""

    panels = []
    summary_rows = details.get("summary_stats_table") if isinstance(details.get("summary_stats_table"), dict) else {}
    rendered_summary_rows = _normalize_summary_rows(summary_rows.get("rows"))
    if rendered_summary_rows:
        panels.append(
            _render_detail_panel(
                summary_rows.get("title") or "Statistics",
                _render_detail_cards(rendered_summary_rows),
            )
        )

    annotations = _normalize_summary_rows(details.get("annotations"))
    if annotations:
        panels.append(_render_detail_panel("Annotations", _render_detail_cards(annotations)))

    spec_lines = _normalize_summary_rows(details.get("specification_lines"))
    if spec_lines:
        panels.append(_render_detail_panel("Specification Lines", _render_detail_cards(spec_lines)))

    overlay_meta = details.get("modeled_overlays") if isinstance(details.get("modeled_overlays"), dict) else {}
    overlay_rows = [str(item) for item in (overlay_meta.get("rows") or []) if str(item).strip()]
    if overlay_rows:
        panels.append(_render_detail_panel("Modeled Overlays", _render_text_list(overlay_rows)))

    context_rows = _normalize_summary_rows(
        [
            ("Samples", details.get("sample_count")),
            ("Bins", details.get("bin_count")),
            ("Axis X", ((details.get("axis_labels") or {}).get("x") if isinstance(details.get("axis_labels"), dict) else "")),
            ("Axis Y", ((details.get("axis_labels") or {}).get("y") if isinstance(details.get("axis_labels"), dict) else "")),
            ("LSL", ((details.get("limits") or {}).get("lsl") if isinstance(details.get("limits"), dict) else None)),
            ("Nominal", ((details.get("limits") or {}).get("nominal") if isinstance(details.get("limits"), dict) else None)),
            ("USL", ((details.get("limits") or {}).get("usl") if isinstance(details.get("limits"), dict) else None)),
        ]
    )
    if context_rows:
        panels.append(_render_detail_panel("Context", _render_detail_cards(context_rows)))

    return f'<div class="detail-grid">{"".join(panels)}</div>' if panels else ""


def _render_detail_panel(title: str, content: str) -> str:
    return f'<section class="detail-panel"><h4>{html.escape(str(title or ""))}</h4>{content}</section>'


def _render_detail_cards(rows: list[dict[str, str]]) -> str:
    if not rows:
        return ""
    cards = "".join(
        f'<div class="detail-card"><div class="detail-card-label">{html.escape(row["label"])}</div>'
        f'<div class="detail-card-value">{html.escape(row["value"])}</div></div>'
        for row in rows
    )
    return f'<div class="detail-cards">{cards}</div>'


def _render_summary_table(rows: list[dict[str, str]]) -> str:
    if not rows:
        return ""
    rows_markup = "".join(
        f"<tr><td>{html.escape(row['label'])}</td><td>{html.escape(row['value'])}</td></tr>"
        for row in rows
    )
    return f'<table class="detail-table">{rows_markup}</table>'


def _render_text_list(items: list[str]) -> str:
    if not items:
        return ""
    return '<ul class="detail-list">' + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>"


def _render_group_analysis(group_analysis: dict[str, Any]) -> str:
    if not isinstance(group_analysis, dict) or not group_analysis:
        return ""

    pills = []
    if group_analysis.get("analysis_level"):
        pills.append(f"Level: {group_analysis['analysis_level']}")
    if group_analysis.get("effective_scope"):
        pills.append(f"Scope: {group_analysis['effective_scope']}")
    metrics = group_analysis.get("metrics") or []
    pills.append(f"Metrics: {len(metrics)}")
    pill_markup = "".join(f'<span class="pill">{html.escape(item)}</span>' for item in pills)

    summary_table = _render_summary_table(group_analysis.get("summary_rows") or [])
    warning_messages = _render_text_list([str(item) for item in (group_analysis.get("warning_messages") or []) if str(item).strip()])

    histogram_skip = group_analysis.get("histogram_skip_summary") if isinstance(group_analysis.get("histogram_skip_summary"), dict) else {}
    histogram_block = ""
    if histogram_skip.get("applies"):
        histogram_rows = _normalize_summary_rows(
            [("Skipped histograms", histogram_skip.get("count"))] + [
                (row.get("label"), row.get("value"))
                for row in (histogram_skip.get("reason_rows") or [])
            ]
        )
        histogram_block = _render_detail_panel("Histogram coverage", _render_summary_table(histogram_rows))

    skip_message = ""
    if group_analysis.get("skip_reason_message"):
        skip_message = f'<p class="chart-note">{html.escape(group_analysis["skip_reason_message"])}</p>'

    metric_nav = ""
    if metrics:
        metric_nav_chips = "".join(
            f'<a class="section-chip" href="#{html.escape(str(metric.get("id") or ""))}">'
            f'{html.escape(str(metric.get("metric") or "Metric"))}</a>'
            for metric in metrics
            if str(metric.get("id") or "").strip()
        )
        if metric_nav_chips:
            metric_nav = f'<nav class="section-nav">{metric_nav_chips}</nav>'

    metrics_markup = "".join(_render_group_analysis_metric(metric) for metric in metrics)
    details_row = ""
    if warning_messages or histogram_block:
        panels = []
        if warning_messages:
            panels.append(_render_detail_panel("Warnings", warning_messages))
        if histogram_block:
            panels.append(histogram_block)
        details_row = f'<div class="detail-grid">{"".join(panels)}</div>'

    return (
        '<section id="group-analysis" class="measurement-section">'
        '<div class="section-top"><div><h2>Group Analysis</h2>'
        '<div class="section-meta">Workbook-level grouped metric comparison data mirrored from the export payload.</div></div>'
        f'<div class="pill-row">{pill_markup}</div></div>'
        f'{skip_message}'
        f'{summary_table}'
        f'{details_row}'
        f'{metric_nav}'
        f'<div class="metric-stack">{metrics_markup}</div>'
        '</section>'
    )


def _render_group_analysis_metric(metric: dict[str, Any]) -> str:
    summary_rows = metric.get("summary_rows") or []
    insights = metric.get("insights") or []
    descriptive_stats = metric.get("descriptive_stats") or {}
    pairwise_rows = metric.get("pairwise_rows") or {}
    distribution_difference = metric.get("distribution_difference") or []
    distribution_pairwise_rows = metric.get("distribution_pairwise_rows") or {}
    plot_eligibility = metric.get("plot_eligibility") or []
    plots = metric.get("plots") or []

    pills = [f"Groups: {int(metric.get('group_count') or 0)}"]
    if metric.get("reference"):
        pills.append(f"Reference: {metric['reference']}")
    pill_markup = "".join(f'<span class="pill">{html.escape(item)}</span>' for item in pills)

    subsections = []
    if summary_rows:
        subsections.append('<div class="subsection-title">Metric summary</div>' + _render_summary_table(summary_rows))
    if insights:
        subsections.append('<div class="subsection-title">Key insights</div>' + _render_text_list(insights))
    if plot_eligibility:
        subsections.append('<div class="subsection-title">Plot eligibility</div>' + _render_summary_table(plot_eligibility))
    if descriptive_stats.get("rows"):
        subsections.append('<div class="subsection-title">Descriptive stats</div>' + _render_data_table(descriptive_stats))
    if pairwise_rows.get("rows"):
        subsections.append('<div class="subsection-title">Pairwise comparisons</div>' + _render_data_table(pairwise_rows))
    if distribution_difference:
        subsections.append('<div class="subsection-title">Distribution difference</div>' + _render_summary_table(distribution_difference))
    if distribution_pairwise_rows.get("rows"):
        subsections.append('<div class="subsection-title">Distribution pairwise rows</div>' + _render_data_table(distribution_pairwise_rows))

    plot_markup = ""
    if plots:
        plot_markup = '<div class="subsection-title">Plots</div><div class="chart-grid">' + "".join(
            _render_chart_card(chart) for chart in plots
        ) + "</div>"

    return (
        f'<article id="{html.escape(metric.get("id") or "")}" class="metric-block">'
        f'<div class="section-top"><div><h3>{html.escape(str(metric.get("metric") or "Metric"))}</h3></div>'
        f'<div class="pill-row">{pill_markup}</div></div>'
        f'{"".join(subsections)}'
        f'{plot_markup}'
        '</article>'
    )


def _render_data_table(table_meta: dict[str, Any]) -> str:
    columns = table_meta.get("columns") or []
    rows = table_meta.get("rows") or []
    if not columns or not rows:
        return ""
    header_markup = "".join(f"<th>{html.escape(str(column.get('label') or ''))}</th>" for column in columns)
    row_markup = "".join(
        "<tr>" + "".join(
            f"<td>{html.escape(str(row.get(column.get('key')) or ''))}</td>"
            for column in columns
        ) + "</tr>"
        for row in rows
    )
    return f'<div class="table-shell"><table class="data-table"><thead><tr>{header_markup}</tr></thead><tbody>{row_markup}</tbody></table></div>'
