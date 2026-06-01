"""Shared copy and rendering helpers for saved HTML dashboards."""

from __future__ import annotations

from dataclasses import dataclass
import html
import re
from typing import Any, Iterable


_REASON_LABELS = {
    "asset_missing": "Plot image was unavailable.",
    "eligible": "Eligible.",
    "insufficient_groups": "At least 2 groups with numeric data are required.",
    "invalid_spec": "Specification is missing or invalid.",
    "limit_mismatch": "Limits differ across groups.",
    "low_group_samples": "At least 3 numeric samples per group are required.",
    "low_total_samples": "At least 6 total numeric samples are required.",
    "metric_excluded": "Metric is excluded from this comparison.",
    "nom_mismatch": "Nominal values differ across groups.",
    "standard_only": "Available only in Standard group comparison.",
    "unknown": "Reason was not provided.",
}

_INFO_DIAGNOSTIC_NOTES = {
    "tabular_sqlite_store_created": "Rows were prepared in a fast local cache for this run.",
    "tabular_sqlite_column_pruning": "Only the columns needed for this dashboard were prepared, so the run stayed responsive.",
}

_HIDDEN_DEBUG_PATTERNS = (
    re.compile(r"\bbackend diagnostics?\b", re.IGNORECASE),
    re.compile(r"\bchart_renderer:\s*status\b", re.IGNORECASE),
    re.compile(r"\bpayload_(?:summary|details)\b", re.IGNORECASE),
    re.compile(r"\bembedded dashboard manifest\b", re.IGNORECASE),
    re.compile(r"\braw_record_json\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class DashboardDiagnostics:
    """Dashboard diagnostics split into user-facing sections."""

    attention: tuple[str, ...] = ()
    run_notes: tuple[str, ...] = ()


def compact_dashboard_label(value: Any) -> str:
    """Return a compact title-style label for dashboard fields."""

    text = str(value or "").strip()
    if not text:
        return ""
    if text.upper() in {"LSL", "USL", "N", "CP", "CPK", "IQR"}:
        return text.upper()
    return text.replace("_", " ").strip().title()


def humanize_dashboard_reason_code(value: Any) -> str:
    """Return a plain-English label for internal skip/status codes."""

    code = str(value or "").strip().lower()
    if not code:
        return ""
    return _REASON_LABELS.get(code, compact_dashboard_label(code))


def clean_dashboard_copy(value: Any) -> str:
    """Rewrite technical dashboard copy into shorter end-user wording."""

    text = str(value or "").strip()
    if not text:
        return ""
    status_match = re.fullmatch(r"Status:\s*([^;]+);\s*mode=(.+)\.?", text)
    if status_match:
        status = status_match.group(1).strip().rstrip(".")
        mode = status_match.group(2).strip().rstrip(".")
        return f"{status}. {mode}."
    text = re.sub(r"\bmode=([^;,.]+)", r"mode \1", text)
    replacements = (
        ("Plotly payload", "interactive chart data"),
        ("Plotly interactivity", "dashboard interactivity"),
        ("Plotly charts", "interactive charts"),
        ("Plotly chart", "interactive chart"),
        ("saved-dashboard budget", "saved dashboard size limit"),
        ("dashboard budget", "dashboard size limit"),
        ("spec_count", "chart count"),
        ("serialized_json_bytes", "interactive chart data size"),
        ("temporary SQLite store", "fast local data cache"),
        ("SQLite column set", "column set"),
        ("before materialization", "before preparing rows"),
        ("materialization", "row preparation"),
        ("Groupstats", "Group comparison"),
        ("All production rows", "All rows"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    for code, label in _REASON_LABELS.items():
        text = re.sub(rf"\b{re.escape(code)}\b", label.rstrip("."), text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def should_hide_dashboard_debug_text(value: Any) -> bool:
    """Return whether text is internal-only dashboard diagnostics copy."""

    text = str(value or "").strip()
    if not text:
        return True
    return any(pattern.search(text) for pattern in _HIDDEN_DEBUG_PATTERNS)


def classify_dashboard_diagnostics(diagnostics: Iterable[Any]) -> DashboardDiagnostics:
    """Split diagnostics into actionable messages and informational run notes."""

    attention: list[str] = []
    run_notes: list[str] = []
    for item in diagnostics:
        if isinstance(item, dict):
            severity = str(item.get("severity") or "info").strip().lower()
            code = str(item.get("code") or "").strip().lower()
            message = str(item.get("message") or "").strip()
            text = _INFO_DIAGNOSTIC_NOTES.get(code, message)
        else:
            severity = "info"
            text = str(item or "").strip()
        if should_hide_dashboard_debug_text(text):
            continue
        cleaned = clean_dashboard_copy(text)
        if not cleaned:
            continue
        target = attention if severity in {"warning", "error", "critical"} else run_notes
        if cleaned not in target:
            target.append(cleaned)
    return DashboardDiagnostics(attention=tuple(attention), run_notes=tuple(run_notes))


def dashboard_key_takeaway_rows(
    *,
    primary_insight: Any = None,
    structured_insights: Any = None,
    legacy_insights: Any = None,
    summary_rows: Any = None,
) -> list[dict[str, str]]:
    """Build labelled, plain-English takeaway rows for dashboard metric cards."""

    rows: list[dict[str, str]] = []

    def add(label: str, value: Any) -> None:
        cleaned = clean_dashboard_copy(value)
        if not cleaned or should_hide_dashboard_debug_text(cleaned):
            return
        key = (label.casefold(), cleaned.casefold())
        existing = {(row["label"].casefold(), row["value"].casefold()) for row in rows}
        if key not in existing:
            rows.append({"label": label, "value": cleaned})

    if isinstance(primary_insight, dict):
        add("Result", primary_insight.get("headline"))
        add("Why it matters", primary_insight.get("why"))
        add("Recommended action", primary_insight.get("first_action"))
        add("Limits", primary_insight.get("limits"))

    if isinstance(summary_rows, list):
        for row in summary_rows:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "").strip()
            if label in {"Takeaway", "Recommended action"}:
                add("Result" if label == "Takeaway" else "Recommended action", row.get("value"))

    if isinstance(structured_insights, list):
        for insight in structured_insights[:3]:
            if isinstance(insight, dict):
                add(compact_dashboard_label(insight.get("label") or "Insight"), insight.get("value"))
            else:
                add("Insight", insight)

    if not rows and isinstance(legacy_insights, list):
        labels = ("Result", "Why it matters", "Limits")
        for index, insight in enumerate(legacy_insights[:3]):
            add(labels[min(index, len(labels) - 1)], insight)

    return rows


def render_dashboard_message_section(
    *,
    section_id: str,
    title: str,
    messages: Iterable[str],
    css_class: str,
    collapsed: bool = True,
) -> str:
    """Render a compact dashboard message section."""

    rows = "".join(
        f"<li>{html.escape(message)}</li>"
        for message in messages
        if str(message or "").strip()
    )
    if not rows:
        return ""
    open_attr = "" if collapsed else " open"
    return (
        f'<details id="{html.escape(section_id)}" class="{html.escape(css_class)}"{open_attr}>'
        f"<summary>{html.escape(title)}</summary>"
        f"<ul>{rows}</ul>"
        "</details>"
    )


def render_dashboard_overview_cards(rows: Iterable[tuple[Any, Any]]) -> str:
    """Render the shared KPI card grid used by saved dashboards."""

    cards = []
    for label, value in rows:
        label_text = str(label or "").strip()
        if not label_text:
            continue
        value_text = str(value if value not in (None, "") else "n/a")
        value_markup = "".join(
            f'<span class="metric-value-line">{html.escape(line)}</span>'
            for line in value_text.splitlines()
            if line
        )
        if not value_markup:
            value_markup = '<span class="metric-value-line">n/a</span>'
        cards.append(
            '<div class="metric-card">'
            f'<div class="metric-label">{html.escape(label_text)}</div>'
            f'<div class="metric-value">{value_markup}</div>'
            '</div>'
        )
    return f'<section class="overview-grid">{"".join(cards)}</section>' if cards else ""


def render_dashboard_hero(
    *,
    eyebrow: str,
    headline: str,
    lede_markup: str = "",
    controls_markup: str = "",
    notice_markup: str = "",
    overview_markup: str = "",
    nav_markup: str = "",
) -> str:
    """Render the shared dashboard hero/header layout."""

    return (
        '<header class="hero" id="dashboard-start">'
        '<div class="hero-top">'
        '<div class="hero-copy">'
        f'<p class="eyebrow">{html.escape(str(eyebrow or "Metroliza Dashboard"))}</p>'
        f'<h1>{html.escape(str(headline or "Metroliza dashboard"))}</h1>'
        f"{lede_markup}"
        '</div>'
        f"{controls_markup}"
        '</div>'
        f"{notice_markup}"
        f"{overview_markup}"
        f"{nav_markup}"
        "</header>"
    )


def render_dashboard_takeaways_section(
    rows: Iterable[dict[str, str] | tuple[Any, Any]],
    *,
    section_id: str = "key-takeaways",
    title: str = "Key takeaways",
) -> str:
    """Render shared, plain-English dashboard insight cards."""

    cards = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if isinstance(row, dict):
            label = str(row.get("label") or "Insight").strip()
            value = clean_dashboard_copy(row.get("value"))
        else:
            label = str(row[0] if len(row) > 0 else "Insight").strip()
            value = clean_dashboard_copy(row[1] if len(row) > 1 else "")
        if not label or not value or should_hide_dashboard_debug_text(value):
            continue
        key = (label.casefold(), value.casefold())
        if key in seen:
            continue
        seen.add(key)
        cards.append(
            '<div class="insight-card">'
            f'<div class="insight-label">{html.escape(label)}</div>'
            f'<div class="insight-value">{html.escape(value)}</div>'
            '</div>'
        )
    if not cards:
        return ""
    return (
        f'<section id="{html.escape(section_id)}" class="measurement-section dashboard-takeaways">'
        '<div class="section-top">'
        f'<div><h2>{html.escape(title)}</h2></div>'
        '<div class="section-actions"></div>'
        '</div>'
        f'<div class="insight-grid">{"".join(cards)}</div>'
        '</section>'
    )
