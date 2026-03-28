"""Generate HTML dashboard sidecars for export summary charts."""

from __future__ import annotations

from datetime import datetime
import html
import json
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


def write_export_html_dashboard(
    *,
    excel_file: str | Path,
    output_path: str | Path,
    assets_dir: str | Path,
    sections: list[dict[str, Any]],
    chart_observability_summary: dict[str, Any] | None = None,
    backend_diagnostics_lines: list[str] | None = None,
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

    manifest = {
        "excel_file": str(Path(str(excel_file)).name),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "section_count": len(section_entries),
        "chart_count": chart_count,
        "sections": section_entries,
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
        normalized.append({"label": str(label or ""), "value": str(value or "")})
    return normalized


def _render_dashboard_html(manifest: dict[str, Any]) -> str:
    sections = manifest.get("sections") or []
    section_nav = "".join(
        f'<a class="section-chip" href="#{html.escape(section["id"])}">{html.escape(section["header"] or section["id"])}</a>'
        for section in sections
    )
    section_blocks = "".join(_render_section(section) for section in sections) or (
        '<section class="empty-state"><h2>No extended summary charts were generated.</h2>'
        '<p>Enable Extended plots or HTML dashboard export for chart-backed dashboard content.</p></section>'
    )
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
    payload_json = html.escape(json.dumps(chart.get("payload_summary") or {}, ensure_ascii=False, indent=2, sort_keys=True))
    note_markup = (
        f'<p class="chart-note">{html.escape(chart["note"])}</p>'
        if str(chart.get("note") or "").strip()
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
        '<details><summary>Chart metadata</summary>'
        f'<pre>{payload_json}</pre>'
        '</details>'
        '</article>'
    )
