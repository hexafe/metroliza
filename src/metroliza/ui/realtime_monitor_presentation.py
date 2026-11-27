"""Presentation from persisted events and observed monitor metadata."""
import math

from metroliza.industrial.industrial_data_repository import redact_sensitive_text


_EVENT_THRESHOLDS = {
    "lsl": "Lower specification limit (LSL)",
    "usl": "Upper specification limit (USL)",
    "lower_warning": "Lower warning limit",
    "upper_warning": "Upper warning limit",
    "lower_fence": "Lower IQR fence",
    "upper_fence": "Upper IQR fence",
    "z": "Absolute z-score limit",
    "robust_z": "Absolute robust z-score limit",
    "mad_z": "MAD z-score limit",
    "warning_seconds": "Warning age (seconds)",
    "major_seconds": "Major age (seconds)",
    "info_threshold": "Information score limit",
    "warning_threshold": "Warning score limit",
    "decision_threshold": "Decision score limit",
    "major_score": "Major score limit",
    "critical_score": "Critical score limit",
}
_WINDOW_NAMES = {
    "trigger_sample": "Triggering sample",
    "stored_baseline": "Stored baseline",
    "prior_samples": "Prior samples",
    "elapsed_since_last_sample": "Time since the last sample",
}
_WINDOW_LABELS = {
    "version": "Baseline version",
    "start": "Baseline start",
    "end": "Baseline end",
    "count": "Samples in window",
    "last_sample_id": "Last sample ID",
    "last_event_time": "Last sample time",
    "values_sha256": "History digest (SHA-256)",
    "evaluated_at": "Evaluated at",
}


def _event_number(value):
    if type(value) is int:
        return str(value)
    if type(value) is float and math.isfinite(value):
        return str(value)
    return ""


def _event_threshold_lines(threshold):
    if not isinstance(threshold, dict):
        return []
    return [
        f"{label}: {number}" for key, label in _EVENT_THRESHOLDS.items()
        if (number := _event_number(threshold.get(key)))
    ]


def _decision_lines(evidence):
    if evidence.algorithm is None:
        return ["Versioned detector and window evidence is unavailable for this saved event."]
    lines = [f"Algorithm version: {evidence.algorithm_version}"]
    if evidence.configuration_revision:
        lines.append(f"Configuration revision (SHA-256): {evidence.configuration_revision}")
    else:
        lines.append("Configuration revision: unavailable")
    lines.append(f"Decision window: {_WINDOW_NAMES.get(evidence.window_kind, 'Unavailable')}")
    for key, value in evidence.window_fields:
        lines.append(f"{_WINDOW_LABELS[key]}: {redact_sensitive_text(str(value), max_len=120)}")
    return lines


def event_review_details(event, evidence):
    """Format the selected open event as bounded plain text."""
    source = redact_sensitive_text(event.profile_name, max_len=120)
    signal = redact_sensitive_text(event.signal_key, max_len=120)
    metric = redact_sensitive_text(getattr(event, "metric_name", ""), max_len=120)
    if metric and metric != signal:
        signal = f"{signal} ({metric})"
    unit = redact_sensitive_text(getattr(event, "unit", ""), max_len=24)
    value = _event_number(event.observed_value)
    lines = [
        f"Event ID: {event.id}",
        f"Time: {redact_sensitive_text(event.event_time, max_len=120)}",
        f"Source: {source}",
        f"Signal: {signal}",
        f"Severity: {redact_sensitive_text(event.severity, max_len=40)}",
        f"Observed: {' '.join(item for item in (value, unit) if item) if value else 'Unavailable'}",
        f"Recorded detector: {redact_sensitive_text(event.detector_key, max_len=120)}",
        "",
        "Recorded thresholds",
        *(_event_threshold_lines(getattr(event, "threshold", None)) or ["No numeric decision limits were saved."]),
        "",
        *_decision_lines(evidence),
        "",
        "Explanation",
        redact_sensitive_text(event.explanation, max_len=640) or "No explanation was saved.",
    ]
    return "\n".join(lines)


def observed_freshness(results, *, scheduled, poll_owned, stopping):
    if stopping:
        poller = "poller stopping"
    elif scheduled:
        poller = "scheduled monitoring running"
    elif poll_owned:
        poller = "one-off or finishing poll owned"
    else:
        poller = "monitoring stopped"
    if not results:
        return f"Data freshness: no completed poll snapshot; {poller}."
    lags = []
    watermark = ""
    for result in results:
        value = getattr(result, "lag_seconds", None)
        try:
            lag = float(value) if value is not None else float("nan")
        except (TypeError, ValueError):
            lag = float("nan")
        if math.isfinite(lag):
            lags.append(max(0.0, lag))
        if not watermark:
            watermark = str(getattr(result, "event_time_watermark", "") or "")[:80]
    lag_text = f"max lag {max(lags):.1f}s" if lags else "lag unavailable"
    through = f"; first reported data-through {watermark}" if watermark else "; data-through unavailable"
    return f"Data freshness: last poll snapshot {lag_text}{through}; {poller}. Snapshot, not live age."
