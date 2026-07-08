"""Shared helpers for Plotly dashboard labels, stat traces, and spec inspection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, ROUND_HALF_UP
import math
import re
from typing import Any

GROUP_COUNT_SUFFIX_PATTERN = re.compile(r"\s*\(n\s*=\s*\d+\)\s*$", re.IGNORECASE)
STAT_LEGEND_VALUE_PATTERN = re.compile(
    r"^(?:\((?P<group>.+?)\)\s*)?(?P<stat>Min|Q1|Median|Mean|Q3|Max)=",
    re.IGNORECASE,
)


def group_label_has_count_suffix(label: str) -> bool:
    """Return True when a group label already ends with an ``(n=...)`` suffix."""

    return bool(GROUP_COUNT_SUFFIX_PATTERN.search(str(label or "").strip()))


def strip_group_count_suffix(label: str) -> str:
    """Return a group label without the generated sample-count suffix."""

    stripped = GROUP_COUNT_SUFFIX_PATTERN.sub("", str(label or "").strip()).strip()
    return stripped or str(label or "").strip()


def normalize_group_label_key(label: str) -> str:
    """Normalize a group label for case-insensitive duplicate checks."""

    return strip_group_count_suffix(label).casefold()


def stat_legend_prefix(group_label: str, *, populated_count: int) -> str:
    """Return the visible group prefix used for per-group stat legend rows."""

    if populated_count <= 1:
        return ""
    return f"({strip_group_count_suffix(group_label)}) "


def format_group_statistics_trace_name(label: str, values: Sequence[float]) -> str:
    """Append a stable ``n`` suffix to a grouped distribution trace name."""

    if not values:
        return str(label)
    if group_label_has_count_suffix(label):
        return str(label)
    return f"{label} (n={len(values)})"


def payload_distribution_series(payload: Mapping[str, Any]) -> list[Any]:
    """Return distribution series from either current or legacy payload keys."""

    def _as_series_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, (str, bytes, Mapping)):
            return [value]
        try:
            return list(value)
        except TypeError:
            return [value]

    series = payload.get("series")
    series_items = _as_series_list(series)
    if series_items:
        return series_items
    values = payload.get("values")
    return _as_series_list(values)


def legend_only_reference_trace(
    *,
    name: str,
    value: float | None,
    color: str,
    dash: str,
    x_values: list[Any] | None = None,
) -> dict[str, Any]:
    """Build a Plotly trace that appears only in the legend until toggled on."""

    numeric = 0.0 if value is None else float(value)
    resolved_x = list(x_values) if x_values else [None, None]
    return {
        "type": "scatter",
        "mode": "lines",
        "name": name,
        "x": resolved_x,
        "y": [numeric, numeric],
        "line": {"color": color, "width": 2, "dash": dash},
        "hoverinfo": "skip",
        "visible": "legendonly",
        "showlegend": True,
    }


def format_plotly_stat_value(value: float | None) -> str:
    """Format compact Plotly stat values with deterministic half-up rounding."""

    if value is None or not math.isfinite(float(value)):
        return ""
    number = float(value)
    magnitude = abs(number)
    if magnitude >= 10_000 or (0.0 < magnitude < 0.001):
        return f"{number:.4g}"
    rounded = Decimal(str(round(number, 12))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    text = f"{rounded:f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def plotly_spec_variants(spec: Any) -> list[dict[str, Any]]:
    """Return concrete Plotly specs from either direct or light/dark wrapper payloads."""

    if not isinstance(spec, dict):
        return []
    if isinstance(spec.get("data"), list):
        return [spec]
    variants: list[dict[str, Any]] = []
    for key in ("light", "dark"):
        variant = spec.get(key)
        if isinstance(variant, dict) and isinstance(variant.get("data"), list):
            variants.append(variant)
    return variants


def series_labels_from_plotly_spec(
    spec: Mapping[str, Any],
    *,
    extra_generic_labels: set[str] | frozenset[str] | None = None,
) -> list[str]:
    """Return user-facing data-series labels from a Plotly spec."""

    labels: list[str] = []
    generic = {"frequency", "histogram", "measurements", "trend"}
    generic.update(label.casefold() for label in (extra_generic_labels or ()))
    for trace in spec.get("data") or []:
        if not isinstance(trace, Mapping):
            continue
        name = strip_group_count_suffix(str(trace.get("name") or "").strip())
        if not name or name.casefold() in generic:
            continue
        if name.split("=", 1)[0].strip().casefold() in {"lsl", "usl", "nominal"}:
            continue
        if STAT_LEGEND_VALUE_PATTERN.match(name):
            continue
        trace_type = str(trace.get("type") or "").casefold()
        mode = str(trace.get("mode") or "").casefold()
        if trace_type in {"bar", "histogram", "box", "violin"} or "markers" in mode:
            labels.append(name)
    return labels
