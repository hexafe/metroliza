"""Generate HTML dashboard sidecars for export summary charts."""

from __future__ import annotations

from datetime import datetime
import html
import json
import math
from pathlib import Path
import re
from typing import Any


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

    manifest = {
        "excel_file": str(Path(str(excel_file)).name),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "section_count": len(section_entries),
        "chart_count": chart_count,
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
        plots = []
        for plot_key in ("violin", "histogram"):
            plot_asset = per_metric_assets.get(plot_key) if isinstance(per_metric_assets, dict) else {}
            image_buffer = plot_asset.get("image_data") if isinstance(plot_asset, dict) else None
            if image_buffer is None:
                continue
            image_name = f"group_metric_{metric_index:03d}_{_slugify(metric_name)}_{plot_key}.png"
            image_path = asset_directory / image_name
            image_path.write_bytes(_coerce_image_bytes(image_buffer))
            plots.append(
                {
                    "chart_type": plot_key,
                    "title": f"{metric_name} - {_humanize_field_label(plot_key)}",
                    "backend": "matplotlib",
                    "note": str(plot_asset.get("description") or ""),
                    "image_path": f"{asset_directory.name}/{image_name}",
                    "payload_summary": {},
                    "payload_details": {},
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

    return {
        "columns": [{"key": key, "label": _humanize_field_label(str(key))} for key in column_order],
        "rows": [
            {key: _format_display_value(row.get(key)) for key in column_order}
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
    manifest_json = html.escape(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    nav_markup = f'<nav class="section-nav">{section_nav}</nav>' if section_nav else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Metroliza Dashboard</title>
  <style>
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
    .chart-card img {{
      display: block;
      width: 100%;
      height: auto;
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      background: #fff;
      margin-top: 14px;
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
      <p class="lede">Extended summary charts exported alongside the workbook. The PNG panels here come from the same render path used for the workbook output, so labels, annotations, and right-side histogram metadata stay aligned.</p>
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
        ("Generated", str(manifest.get("generated_at") or "n/a")),
        ("Sections", str(manifest.get("section_count") or 0)),
        ("Charts", str(manifest.get("chart_count") or 0)),
        ("Native renders", str(native_count)),
        ("Matplotlib renders", str(matplotlib_count)),
    ]
    metrics = group_analysis.get("metrics") or []
    if metrics:
        cards.append(("Group metrics", str(len(metrics))))
    return '<div class="overview-grid">' + "".join(
        f'<div class="metric-card"><div class="metric-label">{html.escape(label)}</div><div class="metric-value">{html.escape(value)}</div></div>'
        for label, value in cards
    ) + '</div>'


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
    detail_markup = _render_chart_payload_details(chart.get("payload_details") or {})
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
        f'<img src="{html.escape(str(chart.get("image_path") or ""))}" alt="{html.escape(str(chart.get("title") or chart.get("chart_type") or "chart"))}">'
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
                _render_summary_table(rendered_summary_rows),
            )
        )

    annotations = _normalize_summary_rows(details.get("annotations"))
    if annotations:
        panels.append(_render_detail_panel("Annotations", _render_summary_table(annotations)))

    spec_lines = _normalize_summary_rows(details.get("specification_lines"))
    if spec_lines:
        panels.append(_render_detail_panel("Specification Lines", _render_summary_table(spec_lines)))

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
        panels.append(_render_detail_panel("Context", _render_summary_table(context_rows)))

    return f'<div class="detail-grid">{"".join(panels)}</div>' if panels else ""


def _render_detail_panel(title: str, content: str) -> str:
    return f'<section class="detail-panel"><h4>{html.escape(str(title or ""))}</h4>{content}</section>'


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
