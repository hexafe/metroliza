"""Static HTML rendering for persisted realtime industrial dashboard snapshots."""

from __future__ import annotations

from dataclasses import dataclass, replace
from html import escape as html_escape
import math
from pathlib import Path
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class DashboardSamplePoint:
    """One persisted observed value shown in the static signal chart."""

    event_time: str
    value: float
    sample_id: int | None = None


@dataclass(frozen=True)
class DashboardAnomalyEvent:
    """One persisted anomaly marker or open event row."""

    event_time: str
    severity: str
    detector_key: str
    observed_value: float | None
    explanation: str
    event_id: int | None = None
    sample_id: int | None = None
    signal_id: int | None = None
    signal_key: str = ""
    expected_value: float | None = None
    score: float | None = None
    status: str = "open"


@dataclass(frozen=True)
class DashboardSignalSeries:
    """Persisted sample series and anomaly markers for one signal."""

    signal_key: str
    metric_name: str
    signal_id: int | None = None
    unit: str | None = None
    source_name: str | None = None
    samples: tuple[DashboardSamplePoint, ...] = ()
    events: tuple[DashboardAnomalyEvent, ...] = ()


@dataclass(frozen=True)
class DashboardSourceHealth:
    """Persisted source-stream health metadata for the static dashboard."""

    source_name: str
    status: str
    health: str | None = None
    source_profile_id: int | None = None
    last_success_at: str | None = None
    last_event_time: str | None = None
    lag_seconds: float | None = None
    open_events: int = 0
    last_error: str | None = None


@dataclass(frozen=True)
class DashboardAggregateRow:
    """One persisted sample aggregate row rendered in the static dashboard."""

    signal_key: str
    metric_name: str
    sample_count: int
    minimum: float | None
    maximum: float | None
    average: float | None
    latest_value: float | None
    signal_id: int | None = None
    source_name: str | None = None
    unit: str | None = None
    first_event_time: str = ""
    last_event_time: str = ""
    nominal: float | None = None
    lsl: float | None = None
    usl: float | None = None
    below_lsl_count: int = 0
    above_usl_count: int = 0
    nok_count: int = 0
    nok_pct: float = 0.0


@dataclass(frozen=True)
class DashboardSummaryCard:
    """Small summary metric rendered at the top of the dashboard."""

    label: str
    value: str
    detail: str = ""


@dataclass(frozen=True)
class RealtimeDashboardSnapshot:
    """Renderer input contract until realtime_dashboard_service provides one."""

    generated_at: str
    title: str = "Realtime Industrial Anomaly Dashboard"
    source_health: tuple[DashboardSourceHealth, ...] = ()
    signals: tuple[DashboardSignalSeries, ...] = ()
    events: tuple[DashboardAnomalyEvent, ...] = ()
    aggregate_rows: tuple[DashboardAggregateRow, ...] = ()
    summary_cards: tuple[DashboardSummaryCard, ...] = ()


_CONNECTION_KEY = (
    r"server|data source|host|database|initial catalog|uid|user id|user|pwd|password|"
    r"port|driver"
)
_CONNECTION_STRING_RE = re.compile(
    rf"\b(?:{_CONNECTION_KEY})\s*=\s*[^;\n]+"
    rf"(?:\s*;\s*(?:{_CONNECTION_KEY})\s*=\s*[^;\n]+)+\s*;?",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(password|passwd|pwd|token|api[_ -]?key|secret|client[_ -]?secret|"
    r"access[_ -]?token|connection[_ -]?string|conn(?:ection)?str)\s*([:=])\s*"
    r"(\"[^\"]*\"|'[^']*'|[^,;\s<]+)",
    re.IGNORECASE,
)
_URL_USERINFO_RE = re.compile(r"\b([a-z][a-z0-9+.-]*://)([^/@\s:]+):([^/@\s]+)@", re.I)
_AUTH_HEADER_RE = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", re.I)
_SAFE_CLASS_RE = re.compile(r"[^a-z0-9_-]+")

_SEVERITY_ORDER = {"critical": 0, "major": 1, "warning": 2, "info": 3}
_SEVERITY_LABELS = ("critical", "major", "warning", "info")


def render_realtime_dashboard_html(snapshot: RealtimeDashboardSnapshot | Mapping[str, Any] | Any) -> str:
    """Return a complete static HTML dashboard from persisted snapshot data."""

    normalized = _normalize_snapshot(snapshot)
    all_events = _all_events(normalized)
    open_events = _open_events(all_events)
    summary_cards = normalized.summary_cards or tuple(_default_summary_cards(normalized, open_events))
    title = _safe_text(normalized.title)
    generated_at = _safe_text(normalized.generated_at or "not recorded")

    return "\n".join(
        (
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{title}</title>",
            "<style>",
            _stylesheet(),
            "</style>",
            "</head>",
            "<body>",
            "<header>",
            f"<h1>{title}</h1>",
            f'<p class="generated">Generated from persisted data: {generated_at}</p>',
            "</header>",
            "<main>",
            _render_summary_cards(summary_cards),
            _render_open_events_table(open_events),
            _render_severity_timeline(open_events),
            _render_top_signals(normalized.signals, open_events),
            _render_aggregate_rows(normalized.aggregate_rows),
            _render_source_health(normalized.source_health, normalized.signals, open_events),
            _render_signal_charts(normalized.signals),
            "</main>",
            "</body>",
            "</html>",
        )
    )


def generate_realtime_dashboard_html(
    snapshot: RealtimeDashboardSnapshot | Mapping[str, Any] | Any,
) -> str:
    """Compatibility alias for callers that prefer a generate_* verb."""

    return render_realtime_dashboard_html(snapshot)


def write_realtime_dashboard_html(
    snapshot: RealtimeDashboardSnapshot | Mapping[str, Any] | Any,
    output_path: str | Path,
) -> Path:
    """Write the static dashboard HTML and return the resolved output path."""

    path = Path(output_path)
    path.write_text(render_realtime_dashboard_html(snapshot), encoding="utf-8")
    return path


def _normalize_snapshot(raw: RealtimeDashboardSnapshot | Mapping[str, Any] | Any) -> RealtimeDashboardSnapshot:
    if isinstance(raw, RealtimeDashboardSnapshot):
        return _merge_explicit_events_into_signals(raw)

    title = _raw_text(_field(raw, "title"), default="Realtime Industrial Anomaly Dashboard")
    generated_at = _raw_text(_field(raw, "generated_at", "created_at", "snapshot_time"), default="")
    source_health = tuple(
        _normalize_source_health(item)
        for item in _as_sequence(_field(raw, "source_health", "sources", "source_status"))
    )
    events = tuple(
        _normalize_event(item)
        for item in _as_sequence(_field(raw, "events", "open_events", "anomaly_events"))
    )
    signals = tuple(
        _normalize_signal(item, explicit_events=events)
        for item in _as_sequence(_field(raw, "signals", "signal_series", "series"))
    )
    aggregate_rows = tuple(
        _normalize_aggregate_row(item)
        for item in _as_sequence(_field(raw, "aggregate_rows", "sample_aggregates", "aggregates"))
    )
    summary_cards = tuple(
        _normalize_summary_card(item)
        for item in _as_sequence(_field(raw, "summary_cards", "cards"))
    )
    return _merge_explicit_events_into_signals(
        RealtimeDashboardSnapshot(
            generated_at=generated_at,
            title=title,
            source_health=source_health,
            signals=signals,
            events=events,
            aggregate_rows=aggregate_rows,
            summary_cards=summary_cards,
        )
    )


def _merge_explicit_events_into_signals(snapshot: RealtimeDashboardSnapshot) -> RealtimeDashboardSnapshot:
    if not snapshot.events:
        return snapshot

    merged_signals: list[DashboardSignalSeries] = []
    for signal in snapshot.signals:
        matching = [
            event
            for event in snapshot.events
            if _event_matches_signal(event, signal) and event not in signal.events
        ]
        if matching:
            merged_signals.append(
                replace(signal, events=_dedupe_events((*signal.events, *matching)))
            )
        else:
            merged_signals.append(signal)
    return replace(snapshot, signals=tuple(merged_signals))


def _normalize_signal(
    raw: DashboardSignalSeries | Mapping[str, Any] | Any,
    *,
    explicit_events: tuple[DashboardAnomalyEvent, ...] = (),
) -> DashboardSignalSeries:
    if isinstance(raw, DashboardSignalSeries):
        return raw

    signal_id = _to_int(_field(raw, "signal_id", "id"))
    signal_key = _raw_text(_field(raw, "signal_key", "key", "name"), default="")
    metric_name = _raw_text(_field(raw, "metric_name", "metric", "metric_key"), default=signal_key)
    if not signal_key:
        signal_key = metric_name or "signal"
    if not metric_name:
        metric_name = signal_key

    samples = tuple(
        point
        for point in (_normalize_sample_point(item) for item in _as_sequence(_field(raw, "samples", "points")))
        if point is not None
    )
    local_events = tuple(
        _normalize_event(item, default_signal_id=signal_id, default_signal_key=signal_key)
        for item in _as_sequence(_field(raw, "events", "anomaly_events", "markers"))
    )
    matched_events = tuple(
        event
        for event in explicit_events
        if _event_matches_signal(
            event,
            DashboardSignalSeries(
                signal_id=signal_id,
                signal_key=signal_key,
                metric_name=metric_name,
            ),
        )
    )
    return DashboardSignalSeries(
        signal_id=signal_id,
        signal_key=signal_key,
        metric_name=metric_name,
        unit=_optional_text(_field(raw, "unit")),
        source_name=_optional_text(_field(raw, "source_name", "source", "profile_name")),
        samples=samples,
        events=_dedupe_events((*local_events, *matched_events)),
    )


def _normalize_sample_point(
    raw: DashboardSamplePoint | Mapping[str, Any] | Any,
) -> DashboardSamplePoint | None:
    if isinstance(raw, DashboardSamplePoint):
        return raw

    value = _to_float(_field(raw, "value", "observed_value"))
    if value is None:
        return None
    return DashboardSamplePoint(
        event_time=_raw_text(_field(raw, "event_time", "time", "timestamp"), default=""),
        value=value,
        sample_id=_to_int(_field(raw, "sample_id", "id")),
    )


def _normalize_event(
    raw: DashboardAnomalyEvent | Mapping[str, Any] | Any,
    *,
    default_signal_id: int | None = None,
    default_signal_key: str = "",
) -> DashboardAnomalyEvent:
    if isinstance(raw, DashboardAnomalyEvent):
        return raw

    signal_id = _to_int(_field(raw, "signal_id")) or default_signal_id
    signal_key = _raw_text(_field(raw, "signal_key"), default=default_signal_key)
    return DashboardAnomalyEvent(
        event_id=_to_int(_field(raw, "event_id", "id")),
        sample_id=_to_int(_field(raw, "sample_id")),
        signal_id=signal_id,
        signal_key=signal_key,
        event_time=_raw_text(_field(raw, "event_time", "time", "timestamp", "created_at"), default=""),
        severity=_raw_text(_field(raw, "severity"), default="info").lower(),
        detector_key=_raw_text(_field(raw, "detector_key", "detector"), default="unknown"),
        observed_value=_to_float(_field(raw, "observed_value", "value")),
        expected_value=_to_float(_field(raw, "expected_value", "expected")),
        score=_to_float(_field(raw, "score")),
        explanation=_raw_text(_field(raw, "explanation", "message", "detail"), default=""),
        status=_raw_text(_field(raw, "status"), default="open").lower(),
    )


def _normalize_source_health(
    raw: DashboardSourceHealth | Mapping[str, Any] | Any,
) -> DashboardSourceHealth:
    if isinstance(raw, DashboardSourceHealth):
        return raw

    source_name = _raw_text(
        _field(raw, "source_name", "profile_name", "profile_key", "source_db_alias", "stream_key"),
        default="source",
    )
    return DashboardSourceHealth(
        source_profile_id=_to_int(_field(raw, "source_profile_id", "profile_id", "id")),
        source_name=source_name,
        status=_raw_text(_field(raw, "status"), default="unknown"),
        health=_optional_text(_field(raw, "health")),
        last_success_at=_optional_text(_field(raw, "last_success_at")),
        last_event_time=_optional_text(_field(raw, "last_event_time", "event_time_watermark")),
        lag_seconds=_to_float(_field(raw, "lag_seconds", "lag")),
        open_events=_to_int(_field(raw, "open_events", "open_event_count")) or 0,
        last_error=_optional_text(_field(raw, "last_error", "error")),
    )


def _normalize_aggregate_row(
    raw: DashboardAggregateRow | Mapping[str, Any] | Any,
) -> DashboardAggregateRow:
    if isinstance(raw, DashboardAggregateRow):
        return raw

    signal_id = _to_int(_field(raw, "signal_id", "id"))
    signal_key = _raw_text(_field(raw, "signal_key", "key", "name"), default="")
    metric_name = _raw_text(_field(raw, "metric_name", "metric", "metric_key"), default=signal_key)
    if not signal_key:
        signal_key = metric_name or "signal"
    if not metric_name:
        metric_name = signal_key

    source_name = _optional_text(
        _field(raw, "source_name", "profile_name", "profile_key", "source", "source_db_alias")
    )
    return DashboardAggregateRow(
        signal_id=signal_id,
        signal_key=signal_key,
        metric_name=metric_name,
        source_name=source_name,
        unit=_optional_text(_field(raw, "unit")),
        sample_count=_to_int(_field(raw, "sample_count", "record_count", "count", "sample_size")) or 0,
        first_event_time=_raw_text(_field(raw, "first_event_time", "window_start"), default=""),
        last_event_time=_raw_text(_field(raw, "last_event_time", "window_end"), default=""),
        minimum=_to_float(_field(raw, "minimum", "min")),
        maximum=_to_float(_field(raw, "maximum", "max")),
        average=_to_float(_field(raw, "average", "mean")),
        latest_value=_to_float(_field(raw, "latest_value", "last_value")),
        nominal=_to_float(_field(raw, "nominal", "nom")),
        lsl=_to_float(_field(raw, "lsl", "lower_spec_limit")),
        usl=_to_float(_field(raw, "usl", "upper_spec_limit")),
        below_lsl_count=_to_int(_field(raw, "below_lsl_count", "observed_nok_below_lsl_count"))
        or 0,
        above_usl_count=_to_int(_field(raw, "above_usl_count", "observed_nok_above_usl_count"))
        or 0,
        nok_count=_to_int(_field(raw, "nok_count", "observed_nok_count")) or 0,
        nok_pct=_to_float(_field(raw, "nok_pct", "observed_nok_pct")) or 0.0,
    )


def _normalize_summary_card(raw: DashboardSummaryCard | Mapping[str, Any] | Any) -> DashboardSummaryCard:
    if isinstance(raw, DashboardSummaryCard):
        return raw
    return DashboardSummaryCard(
        label=_raw_text(_field(raw, "label", "title"), default="Metric"),
        value=_raw_text(_field(raw, "value"), default=""),
        detail=_raw_text(_field(raw, "detail", "subtitle", "description"), default=""),
    )


def _all_events(snapshot: RealtimeDashboardSnapshot) -> tuple[DashboardAnomalyEvent, ...]:
    return _dedupe_events((*snapshot.events, *(event for signal in snapshot.signals for event in signal.events)))


def _open_events(events: tuple[DashboardAnomalyEvent, ...]) -> tuple[DashboardAnomalyEvent, ...]:
    return tuple(
        sorted(
            (
                event
                for event in events
                if event.status not in {"acknowledged", "closed", "resolved", "false_positive"}
            ),
            key=_event_sort_key,
        )
    )


def _default_summary_cards(
    snapshot: RealtimeDashboardSnapshot,
    open_events: tuple[DashboardAnomalyEvent, ...],
) -> list[DashboardSummaryCard]:
    sample_count = sum(len(signal.samples) for signal in snapshot.signals)
    severity_counts = _severity_counts(open_events)
    max_lag = max(
        (source.lag_seconds for source in snapshot.source_health if source.lag_seconds is not None),
        default=None,
    )
    cards = [
        DashboardSummaryCard("Open events", str(len(open_events)), "Persisted anomalies awaiting review"),
        DashboardSummaryCard("Critical", str(severity_counts.get("critical", 0)), "Open critical events"),
        DashboardSummaryCard("Signals", str(len(snapshot.signals)), "Signals with persisted dashboard data"),
        DashboardSummaryCard("Samples", str(sample_count), "Observed values in this snapshot"),
        DashboardSummaryCard("Sources", str(len(snapshot.source_health)), "Source health rows"),
    ]
    if max_lag is not None:
        cards.append(DashboardSummaryCard("Max lag", f"{_format_number(max_lag)}s", "Largest source lag"))
    return cards


def _render_summary_cards(cards: tuple[DashboardSummaryCard, ...]) -> str:
    body = "\n".join(
        "".join(
            (
                '<article class="summary-card">',
                f"<h3>{_safe_text(card.label)}</h3>",
                f'<p class="summary-value">{_safe_text(card.value)}</p>',
                f'<p class="summary-detail">{_safe_text(card.detail)}</p>',
                "</article>",
            )
        )
        for card in cards
    )
    return (
        '<section class="section" data-section="summary-cards">'
        "<h2>Summary</h2>"
        f'<div class="summary-grid">{body}</div>'
        "</section>"
    )


def _render_open_events_table(events: tuple[DashboardAnomalyEvent, ...]) -> str:
    if not events:
        return (
            '<section class="section" data-section="open-events">'
            "<h2>Open Events</h2>"
            '<p class="empty">No open persisted anomaly events in this snapshot.</p>'
            "</section>"
        )
    rows = "\n".join(
        "<tr>"
        f"<td>{_safe_text(event.event_time)}</td>"
        f'<td><span class="severity {_severity_class(event.severity)}">'
        f"{_safe_text(event.severity)}</span></td>"
        f"<td>{_safe_text(event.signal_key or _signal_label_from_event(event))}</td>"
        f"<td>{_safe_text(event.detector_key)}</td>"
        f"<td>{_safe_text(_format_optional_number(event.observed_value))}</td>"
        f"<td>{_safe_text(_format_optional_number(event.expected_value))}</td>"
        f"<td>{_safe_text(event.explanation)}</td>"
        "</tr>"
        for event in events
    )
    return (
        '<section class="section" data-section="open-events">'
        "<h2>Open Events</h2>"
        '<div class="table-scroll">'
        "<table>"
        "<thead><tr>"
        "<th>Time</th><th>Severity</th><th>Signal</th><th>Detector</th>"
        "<th>Observed</th><th>Expected</th><th>Explanation</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
        "</div>"
        "</section>"
    )


def _render_severity_timeline(events: tuple[DashboardAnomalyEvent, ...]) -> str:
    if not events:
        return (
            '<section class="section" data-section="severity-timeline">'
            "<h2>Severity Timeline</h2>"
            '<p class="empty">No open anomaly markers to plot.</p>'
            "</section>"
        )

    ordered = tuple(sorted(events, key=lambda event: (event.event_time, event.event_id or 0)))
    width = 720
    left = 48
    right = 28
    usable = width - left - right
    count = max(len(ordered) - 1, 1)
    dots = []
    for index, event in enumerate(ordered):
        x = left + (usable * index / count)
        y = 38 + (_SEVERITY_ORDER.get(event.severity, 3) * 24)
        dots.append(
            f'<circle class="timeline-dot {_severity_class(event.severity)}" '
            f'cx="{x:.1f}" cy="{y:.1f}" r="7">'
            f"<title>{_safe_text(_event_title(event))}</title>"
            "</circle>"
        )
    labels = "\n".join(
        f'<text class="axis-label" x="8" y="{42 + index * 24}">{_safe_text(label)}</text>'
        for index, label in enumerate(_SEVERITY_LABELS)
    )
    svg = (
        '<svg class="timeline" viewBox="0 0 720 150" role="img" '
        'aria-label="Severity timeline for open anomaly events">'
        '<line class="timeline-axis" x1="48" y1="128" x2="692" y2="128"></line>'
        f"{labels}"
        f"{''.join(dots)}"
        "</svg>"
    )
    return (
        '<section class="section" data-section="severity-timeline">'
        "<h2>Severity Timeline</h2>"
        f"{svg}"
        "</section>"
    )


def _render_top_signals(
    signals: tuple[DashboardSignalSeries, ...],
    open_events: tuple[DashboardAnomalyEvent, ...],
) -> str:
    rows = _top_signal_rows(signals, open_events)
    if not rows:
        return (
            '<section class="section" data-section="top-signals">'
            "<h2>Top Signals</h2>"
            '<p class="empty">No signal activity available.</p>'
            "</section>"
        )
    body = "\n".join(
        "<tr>"
        f"<td>{_safe_text(row['signal'])}</td>"
        f"<td>{_safe_text(row['source'])}</td>"
        f"<td>{row['open_events']}</td>"
        f"<td>{row['critical_events']}</td>"
        f"<td>{_safe_text(row['latest_value'])}</td>"
        "</tr>"
        for row in rows
    )
    return (
        '<section class="section" data-section="top-signals">'
        "<h2>Top Signals</h2>"
        '<div class="table-scroll">'
        "<table>"
        "<thead><tr><th>Signal</th><th>Source</th><th>Open</th><th>Critical</th>"
        "<th>Latest value</th></tr></thead>"
        f"<tbody>{body}</tbody>"
        "</table>"
        "</div>"
        "</section>"
    )


def _render_aggregate_rows(rows: tuple[DashboardAggregateRow, ...]) -> str:
    if not rows:
        return (
            '<section class="section" data-section="sample-aggregates">'
            "<h2>Sample Aggregates</h2>"
            '<p class="empty">No persisted sample aggregates available.</p>'
            "</section>"
        )
    body = "\n".join(
        "<tr>"
        f"<td>{_safe_text(_aggregate_signal_title(row))}</td>"
        f"<td>{_safe_text(row.source_name or '')}</td>"
        f"<td>{row.sample_count}</td>"
        f"<td>{_safe_text(_format_optional_number(row.minimum))}</td>"
        f"<td>{_safe_text(_format_optional_number(row.average))}</td>"
        f"<td>{_safe_text(_format_optional_number(row.maximum))}</td>"
        f"<td>{_safe_text(_format_optional_number(row.latest_value))}</td>"
        f"<td>{_safe_text(_format_nok(row))}</td>"
        f"<td>{_safe_text(_format_limits(row))}</td>"
        f"<td>{_safe_text(_format_period(row))}</td>"
        "</tr>"
        for row in rows
    )
    return (
        '<section class="section" data-section="sample-aggregates">'
        "<h2>Sample Aggregates</h2>"
        '<div class="table-scroll">'
        "<table>"
        "<thead><tr><th>Signal</th><th>Source</th><th>Samples</th><th>Min</th>"
        "<th>Mean</th><th>Max</th><th>Latest</th><th>NOK</th><th>Limits</th><th>Period</th>"
        "</tr></thead>"
        f"<tbody>{body}</tbody>"
        "</table>"
        "</div>"
        "</section>"
    )


def _render_source_health(
    source_health: tuple[DashboardSourceHealth, ...],
    signals: tuple[DashboardSignalSeries, ...],
    open_events: tuple[DashboardAnomalyEvent, ...],
) -> str:
    sources = source_health or _infer_source_health(signals, open_events)
    if not sources:
        return (
            '<section class="section" data-section="source-health">'
            "<h2>Source Health</h2>"
            '<p class="empty">No source health rows available.</p>'
            "</section>"
        )
    rows = "\n".join(
        _render_source_health_row(source)
        for source in sources
    )
    return (
        '<section class="section" data-section="source-health">'
        "<h2>Source Health</h2>"
        '<div class="table-scroll">'
        "<table>"
        "<thead><tr><th>Source</th><th>Health</th><th>Last success</th>"
        "<th>Watermark</th><th>Lag seconds</th><th>Open events</th><th>Source status</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
        "</div>"
        "</section>"
    )


def _render_source_health_row(source: DashboardSourceHealth) -> str:
    health = source.health or source.status
    status_detail = source.status if source.status != health else ""
    return (
        "<tr>"
        f"<td>{_safe_text(source.source_name)}</td>"
        f'<td><span class="status {_status_class(health)}">'
        f"{_safe_text(health)}</span></td>"
        f"<td>{_safe_text(source.last_success_at or '')}</td>"
        f"<td>{_safe_text(source.last_event_time or '')}</td>"
        f"<td>{_safe_text(_format_optional_number(source.lag_seconds))}</td>"
        f"<td>{source.open_events}</td>"
        f"<td>{_safe_text(status_detail)}</td>"
        "</tr>"
    )


def _render_signal_charts(signals: tuple[DashboardSignalSeries, ...]) -> str:
    if not signals:
        return (
            '<section class="section" data-section="signal-charts">'
            "<h2>Signal Charts</h2>"
            '<p class="empty">No persisted signal series available.</p>'
            "</section>"
        )
    charts = "\n".join(_render_signal_chart(signal, index) for index, signal in enumerate(signals, 1))
    return (
        '<section class="section" data-section="signal-charts">'
        "<h2>Signal Charts</h2>"
        f"{charts}"
        "</section>"
    )


def _render_signal_chart(signal: DashboardSignalSeries, index: int) -> str:
    title = _signal_title(signal)
    source = f"Source: {signal.source_name}" if signal.source_name else "Source: not recorded"
    chart = _signal_chart_svg(signal, chart_id=f"signal-chart-{index}")
    return (
        '<article class="signal-panel">'
        f"<h3>{_safe_text(title)}</h3>"
        f'<p class="signal-meta">{_safe_text(source)}</p>'
        f"{chart}"
        "</article>"
    )


def _signal_chart_svg(signal: DashboardSignalSeries, *, chart_id: str) -> str:
    sample_points = tuple(sorted(signal.samples, key=lambda item: (item.event_time, item.sample_id or 0)))
    markers = tuple(sorted(signal.events, key=lambda item: (item.event_time, item.event_id or 0)))
    y_values = [point.value for point in sample_points]
    y_values.extend(event.observed_value for event in markers if event.observed_value is not None)
    if not y_values:
        return '<p class="empty">No persisted samples or anomaly markers available.</p>'

    width = 720
    height = 260
    left = 54
    top = 24
    right = 24
    bottom = 42
    chart_width = width - left - right
    chart_height = height - top - bottom
    y_min, y_max = _chart_bounds(y_values)
    x_index = _chart_x_indexes(sample_points, markers)
    max_index = max(x_index.values(), default=0)

    def _x(key: tuple[str, Any]) -> float:
        denominator = max(max_index, 1)
        return left + (chart_width * x_index[key] / denominator)

    def _y(value: float) -> float:
        return top + chart_height - ((value - y_min) / (y_max - y_min) * chart_height)

    polyline = ""
    if len(sample_points) > 1:
        line_points = " ".join(
            f"{_x(_sample_key(point)):.1f},{_y(point.value):.1f}" for point in sample_points
        )
        polyline = f'<polyline class="observed-line" points="{line_points}"></polyline>'
    samples = "\n".join(
        f'<circle class="sample-point" cx="{_x(_sample_key(point)):.1f}" '
        f'cy="{_y(point.value):.1f}" r="4">'
        f"<title>{_safe_text(point.event_time)}: {_safe_text(_format_number(point.value))}</title>"
        "</circle>"
        for point in sample_points
    )
    marker_nodes = "\n".join(
        _event_marker_svg(event, _x(_event_key(event)), _y(event.observed_value))
        for event in markers
        if event.observed_value is not None
    )
    return (
        f'<svg id="{chart_id}" class="signal-chart" viewBox="0 0 {width} {height}" '
        'role="img" aria-label="Observed signal values with anomaly markers">'
        f'<line class="grid-line" x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}"></line>'
        f'<line class="grid-line" x1="{left}" y1="{height - bottom}" '
        f'x2="{width - right}" y2="{height - bottom}"></line>'
        f'<text class="axis-label" x="{left}" y="{height - 12}">'
        f"{_safe_text(_first_time_label(sample_points, markers))}</text>"
        f'<text class="axis-label" x="{width - right - 130}" y="{height - 12}">'
        f"{_safe_text(_last_time_label(sample_points, markers))}</text>"
        f'<text class="axis-label" x="8" y="{top + 8}">{_safe_text(_format_number(y_max))}</text>'
        f'<text class="axis-label" x="8" y="{height - bottom}">'
        f"{_safe_text(_format_number(y_min))}</text>"
        f"{polyline}{samples}{marker_nodes}"
        "</svg>"
    )


def _event_marker_svg(event: DashboardAnomalyEvent, x: float, y: float) -> str:
    size = 7
    points = (
        f"{x:.1f},{y - size:.1f} "
        f"{x + size:.1f},{y:.1f} "
        f"{x:.1f},{y + size:.1f} "
        f"{x - size:.1f},{y:.1f}"
    )
    return (
        f'<polygon class="anomaly-marker {_severity_class(event.severity)}" points="{points}">'
        f"<title>{_safe_text(_event_title(event))}</title>"
        "</polygon>"
    )


def _top_signal_rows(
    signals: tuple[DashboardSignalSeries, ...],
    open_events: tuple[DashboardAnomalyEvent, ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for signal in signals:
        events = [event for event in open_events if _event_matches_signal(event, signal)]
        latest = max(signal.samples, key=lambda point: (point.event_time, point.sample_id or 0), default=None)
        latest_value = _format_optional_number(latest.value if latest is not None else None)
        if signal.unit and latest_value:
            latest_value = f"{latest_value} {signal.unit}"
        rows.append(
            {
                "signal": _signal_title(signal),
                "source": signal.source_name or "",
                "open_events": len(events),
                "critical_events": sum(event.severity == "critical" for event in events),
                "latest_value": latest_value,
            }
        )

    known_keys = {signal.signal_key for signal in signals}
    for event in open_events:
        if event.signal_key and event.signal_key in known_keys:
            continue
        rows.append(
            {
                "signal": _signal_label_from_event(event),
                "source": "",
                "open_events": 1,
                "critical_events": int(event.severity == "critical"),
                "latest_value": _format_optional_number(event.observed_value),
            }
        )
    return sorted(
        rows,
        key=lambda row: (-int(row["open_events"]), -int(row["critical_events"]), str(row["signal"])),
    )


def _infer_source_health(
    signals: tuple[DashboardSignalSeries, ...],
    open_events: tuple[DashboardAnomalyEvent, ...],
) -> tuple[DashboardSourceHealth, ...]:
    sources: dict[str, int] = {}
    for signal in signals:
        source_name = signal.source_name or "not recorded"
        event_count = sum(1 for event in open_events if _event_matches_signal(event, signal))
        sources[source_name] = sources.get(source_name, 0) + event_count
    return tuple(
        DashboardSourceHealth(source_name=source_name, status="unknown", open_events=open_count)
        for source_name, open_count in sorted(sources.items())
    )


def _chart_x_indexes(
    sample_points: tuple[DashboardSamplePoint, ...],
    markers: tuple[DashboardAnomalyEvent, ...],
) -> dict[tuple[str, Any], int]:
    keys: list[tuple[str, Any]] = []
    for point in sample_points:
        keys.append(_sample_key(point))
    for event in markers:
        key = _event_key(event)
        if key not in keys:
            keys.append(key)
    return {key: index for index, key in enumerate(keys)}


def _sample_key(point: DashboardSamplePoint) -> tuple[str, Any]:
    if point.sample_id is not None:
        return ("sample", point.sample_id)
    return ("time", point.event_time)


def _event_key(event: DashboardAnomalyEvent) -> tuple[str, Any]:
    if event.sample_id is not None:
        return ("sample", event.sample_id)
    if event.event_id is not None:
        return ("event", event.event_id)
    return ("time", event.event_time)


def _chart_bounds(values: list[float]) -> tuple[float, float]:
    y_min = min(values)
    y_max = max(values)
    if math.isclose(y_min, y_max):
        padding = max(abs(y_min) * 0.05, 1.0)
    else:
        padding = (y_max - y_min) * 0.08
    return y_min - padding, y_max + padding


def _first_time_label(
    sample_points: tuple[DashboardSamplePoint, ...],
    markers: tuple[DashboardAnomalyEvent, ...],
) -> str:
    labels = [point.event_time for point in sample_points]
    labels.extend(event.event_time for event in markers)
    return next((label for label in labels if label), "")


def _last_time_label(
    sample_points: tuple[DashboardSamplePoint, ...],
    markers: tuple[DashboardAnomalyEvent, ...],
) -> str:
    labels = [point.event_time for point in sample_points]
    labels.extend(event.event_time for event in markers)
    return next((label for label in reversed(labels) if label), "")


def _event_matches_signal(event: DashboardAnomalyEvent, signal: DashboardSignalSeries) -> bool:
    if event.signal_id is not None and signal.signal_id is not None:
        return event.signal_id == signal.signal_id
    return bool(event.signal_key and event.signal_key == signal.signal_key)


def _dedupe_events(events: tuple[DashboardAnomalyEvent, ...]) -> tuple[DashboardAnomalyEvent, ...]:
    unique: list[DashboardAnomalyEvent] = []
    seen: set[tuple[Any, ...]] = set()
    for event in events:
        key = (
            event.event_id if event.event_id is not None else None,
            event.sample_id,
            event.signal_id,
            event.signal_key,
            event.event_time,
            event.detector_key,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return tuple(unique)


def _event_sort_key(event: DashboardAnomalyEvent) -> tuple[int, str, int]:
    return (_SEVERITY_ORDER.get(event.severity, 4), event.event_time, event.event_id or 0)


def _severity_counts(events: tuple[DashboardAnomalyEvent, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        counts[event.severity] = counts.get(event.severity, 0) + 1
    return counts


def _signal_title(signal: DashboardSignalSeries) -> str:
    if signal.unit:
        return f"{signal.metric_name} ({signal.unit})"
    return signal.metric_name or signal.signal_key


def _signal_label_from_event(event: DashboardAnomalyEvent) -> str:
    if event.signal_key:
        return event.signal_key
    if event.signal_id is not None:
        return f"signal #{event.signal_id}"
    return "signal"


def _aggregate_signal_title(row: DashboardAggregateRow) -> str:
    title = row.metric_name or row.signal_key
    if row.unit:
        return f"{title} ({row.unit})"
    return title


def _event_title(event: DashboardAnomalyEvent) -> str:
    observed = _format_optional_number(event.observed_value)
    return (
        f"{event.severity} {event.detector_key} at {event.event_time}; "
        f"observed {observed}; {event.explanation}"
    )


def _severity_class(severity: str) -> str:
    return f"severity-{_safe_class(severity or 'info')}"


def _status_class(status: str) -> str:
    return f"status-{_safe_class(status or 'unknown')}"


def _safe_class(value: str) -> str:
    normalized = _SAFE_CLASS_RE.sub("-", value.lower()).strip("-")
    return normalized or "unknown"


def _field(raw: Any, *names: str) -> Any:
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        for name in names:
            if name in raw:
                return raw[name]
        return None
    for name in names:
        if hasattr(raw, name):
            return getattr(raw, name)
    return None


def _as_sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _raw_text(value: Any, *, default: str) -> str:
    if value is None:
        return default
    return str(value)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _format_optional_number(value: float | int | None) -> str:
    if value is None:
        return ""
    return _format_number(float(value))


def _format_number(value: float | int) -> str:
    number = float(value)
    if math.isclose(number, round(number)):
        return str(int(round(number)))
    return f"{number:.4g}"


def _format_nok(row: DashboardAggregateRow) -> str:
    if row.sample_count <= 0:
        return "0 (0%)"
    return f"{row.nok_count} ({_format_percent(row.nok_pct)})"


def _format_limits(row: DashboardAggregateRow) -> str:
    parts = []
    if row.lsl is not None:
        parts.append(f"LSL {_format_number(row.lsl)}")
    if row.nominal is not None:
        parts.append(f"NOM {_format_number(row.nominal)}")
    if row.usl is not None:
        parts.append(f"USL {_format_number(row.usl)}")
    return " / ".join(parts)


def _format_period(row: DashboardAggregateRow) -> str:
    if row.first_event_time and row.last_event_time and row.first_event_time != row.last_event_time:
        return f"{row.first_event_time} to {row.last_event_time}"
    return row.last_event_time or row.first_event_time


def _format_percent(value: float | int) -> str:
    return f"{float(value) * 100:.1f}%"


def _safe_text(value: Any) -> str:
    return html_escape(_redact_sensitive_text(str(value)), quote=True)


def _redact_sensitive_text(text: str) -> str:
    redacted = _CONNECTION_STRING_RE.sub("[redacted connection string]", text)
    redacted = _URL_USERINFO_RE.sub(r"\1[redacted]@", redacted)
    redacted = _AUTH_HEADER_RE.sub(r"\1 [redacted]", redacted)
    return _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", redacted)


def _stylesheet() -> str:
    return """
:root {
  color: #1d232a;
  background: #f5f7f9;
  font-family: Arial, Helvetica, sans-serif;
}
body {
  margin: 0;
  background: #f5f7f9;
}
header {
  background: #243447;
  color: #ffffff;
  padding: 28px 32px;
}
h1, h2, h3, p {
  margin-top: 0;
}
main {
  margin: 0 auto;
  max-width: 1180px;
  padding: 24px 20px 40px;
}
.generated {
  color: #d9e2ec;
  margin-bottom: 0;
}
.section {
  margin-bottom: 24px;
}
.summary-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
}
.summary-card, .signal-panel {
  background: #ffffff;
  border: 1px solid #d8dee6;
  border-radius: 8px;
  padding: 14px 16px;
}
.summary-card h3 {
  color: #4e5b68;
  font-size: 0.82rem;
  margin-bottom: 6px;
  text-transform: uppercase;
}
.summary-value {
  font-size: 1.8rem;
  font-weight: 700;
  margin-bottom: 4px;
}
.summary-detail, .signal-meta, .empty {
  color: #5d6975;
}
.table-scroll {
  overflow-x: auto;
}
table {
  background: #ffffff;
  border-collapse: collapse;
  min-width: 760px;
  width: 100%;
}
th, td {
  border: 1px solid #d8dee6;
  padding: 9px 10px;
  text-align: left;
  vertical-align: top;
}
th {
  background: #edf1f5;
  color: #334155;
}
.severity, .status {
  border-radius: 8px;
  display: inline-block;
  font-weight: 700;
  padding: 2px 8px;
}
.severity-critical {
  background: #b42318;
  color: #ffffff;
  fill: #b42318;
}
.severity-major {
  background: #d45a16;
  color: #ffffff;
  fill: #d45a16;
}
.severity-warning {
  background: #f2c94c;
  color: #2f2500;
  fill: #d79d00;
}
.severity-info {
  background: #4c78a8;
  color: #ffffff;
  fill: #4c78a8;
}
.status-ok, .status-healthy, .status-idle, .status-running {
  background: #d1fadf;
  color: #14532d;
}
.status-lagging {
  background: #fef0c7;
  color: #7a4b00;
}
.status-error, .status-failed {
  background: #fee4e2;
  color: #7a271a;
}
.status-unknown {
  background: #e5e7eb;
  color: #374151;
}
.timeline, .signal-chart {
  background: #ffffff;
  border: 1px solid #d8dee6;
  border-radius: 8px;
  height: auto;
  max-width: 100%;
}
.timeline-dot {
  stroke: #ffffff;
  stroke-width: 2;
}
.timeline-axis, .grid-line {
  stroke: #b8c2cc;
  stroke-width: 1;
}
.axis-label {
  fill: #52606d;
  font-size: 12px;
}
.observed-line {
  fill: none;
  stroke: #2f80ed;
  stroke-width: 2.5;
}
.sample-point {
  fill: #ffffff;
  stroke: #2f80ed;
  stroke-width: 2;
}
.anomaly-marker {
  stroke: #ffffff;
  stroke-width: 2;
}
.signal-panel {
  margin-bottom: 14px;
}
""".strip()


__all__ = [
    "DashboardAggregateRow",
    "DashboardAnomalyEvent",
    "DashboardSamplePoint",
    "DashboardSignalSeries",
    "DashboardSourceHealth",
    "DashboardSummaryCard",
    "RealtimeDashboardSnapshot",
    "generate_realtime_dashboard_html",
    "render_realtime_dashboard_html",
    "write_realtime_dashboard_html",
]
