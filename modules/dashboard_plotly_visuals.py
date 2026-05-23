"""Configurable Plotly visual styling for HTML dashboard specs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
import math
import re
from typing import Any


_GROUP_COUNT_SUFFIX_PATTERN = re.compile(r"\s*\(n\s*=\s*\d+\)\s*$", re.IGNORECASE)
_GROUP_STAT_PATTERN = re.compile(
    r"^(?:\((?P<group>.+?)\)\s*)?(?P<stat>Min|Q1|Median|Mean|Q3|Max)=",
    re.IGNORECASE,
)
_REFERENCE_PREFIXES = {
    "lsl": "lsl",
    "usl": "usl",
    "nominal": "nominal",
}
_STAT_ACCENT_FACTORS = {
    "min": 0.78,
    "q1": 0.90,
    "median": 1.0,
    "mean": 1.14,
    "q3": 1.24,
    "max": 1.36,
}
_DEFAULT_SIMILARITY_THRESHOLD = 42.0
_TRACE_SCHEMA_VERSION = "metroliza.plotly_trace.v1"
_LINE_STYLE_CAPABILITIES = ("color", "opacity", "width", "dash")
_PATTERN_STYLE_CAPABILITY = "pattern_shape"


def dashboard_visual_settings_from_theme(theme: Any) -> dict[str, Any]:
    """Return the dashboard visual settings block from a plotstats-style theme."""

    if not isinstance(theme, Mapping):
        return {}
    visual = theme.get("visual")
    return copy.deepcopy(dict(visual)) if isinstance(visual, Mapping) else {}


def merge_dashboard_visual_settings(*settings: Any) -> dict[str, Any]:
    """Merge visual settings blocks, preserving nested mapping semantics."""

    merged: dict[str, Any] = {}
    for setting in settings:
        if not isinstance(setting, Mapping):
            continue
        _deep_merge(merged, setting)
    return merged


def tag_plotly_visual_trace(
    trace: dict[str, Any],
    *,
    role: str,
    target_id: str,
    label: str,
    capabilities: Sequence[str],
    chart_kind: str | None = None,
    series_id: str | None = None,
    stat_id: str | None = None,
    reference_id: str | None = None,
    preserve_color: bool = False,
) -> dict[str, Any]:
    """Attach stable Metroliza visual metadata to a styleable Plotly trace."""

    if not isinstance(trace, dict):
        return trace
    clean_role = _normalize_label_key(role).replace(" ", "_") or "series"
    clean_target = str(target_id or "").strip() or clean_role
    meta = trace.setdefault("meta", {})
    if not isinstance(meta, dict):
        meta = {}
        trace["meta"] = meta
    capability_list = _unique_strings(capabilities)
    meta.update(
        {
            "dashboard_visual_role": clean_role,
            "dashboard_visual_target": clean_target,
            "dashboard_visual_capabilities": capability_list,
            "metroliza_trace_schema": _TRACE_SCHEMA_VERSION,
            "metroliza_role": clean_role,
            "metroliza_target_id": clean_target,
            "metroliza_visual_target_id": clean_target,
            "metroliza_style_capabilities": capability_list,
            "metroliza_legend_label": str(label or clean_target),
        }
    )
    if chart_kind:
        meta["dashboard_visual_chart_kind"] = chart_kind
        meta["metroliza_chart_kind"] = chart_kind
    if series_id:
        meta["metroliza_series_id"] = series_id
    if stat_id:
        meta["metroliza_stat_id"] = stat_id
    if reference_id:
        meta["metroliza_reference_id"] = reference_id
    if preserve_color:
        meta["dashboard_visual_preserve_color"] = True
    return trace


def apply_dashboard_visual_settings(
    spec: dict[str, Any],
    *,
    payload: Mapping[str, Any] | None = None,
    visual_settings: Mapping[str, Any] | None = None,
    theme: Any = None,
) -> dict[str, Any]:
    """Apply dashboard visual settings to an already-built Plotly spec.

    Plotly layout ``colorway`` is not enough for Metroliza dashboards because the
    accepted chart builders set explicit trace colors. This helper resolves the
    user/template visual settings into trace-level Plotly attributes while
    preserving the existing legend-controlled trace contract.
    """

    if not isinstance(spec, dict):
        return spec
    payload_map = payload if isinstance(payload, Mapping) else {}
    payload_visual = _payload_visual_settings(payload_map)
    theme_visual = dashboard_visual_settings_from_theme(theme)
    resolved = merge_dashboard_visual_settings(theme_visual, payload_visual, visual_settings)
    if not resolved:
        return spec
    preserve_colors = bool(resolved.get("preserve_colors_on_theme")) or bool(
        payload_visual or visual_settings
    )

    series = _series_settings(resolved)
    reference_settings = _reference_settings(resolved)
    stat_settings = _stat_settings(resolved)
    palette = _string_list(series.get("palette") or resolved.get("palette"))
    overrides = _series_overrides(series.get("overrides") or resolved.get("series_overrides"))
    labels = _series_labels(payload_map, spec)
    chart_kind = _chart_kind(payload_map, spec)
    marker_symbols = _string_list(series.get("marker_symbols") or series.get("symbols"))
    pattern_shapes = _string_list(series.get("patterns") or series.get("pattern_shapes"))
    marker_size = _finite_float(series.get("marker_size"))
    outline_width = _finite_float(series.get("outline_width"))
    outline_color = _string_or_none(series.get("outline_color"))
    outline_color_mode = _outline_color_mode(series.get("outline_color_mode"))
    auto_distinguish = bool(series.get("auto_distinguish"))
    similar_palette = _palette_has_similar_colors(palette, threshold=_similarity_threshold(series))
    use_distinguishers = bool(marker_symbols or pattern_shapes) and (
        auto_distinguish or bool(series.get("always_distinguish"))
    )
    if auto_distinguish and similar_palette:
        use_distinguishers = True

    if palette:
        layout = spec.setdefault("layout", {})
        if isinstance(layout, dict):
            layout["colorway"] = list(palette)
            if preserve_colors:
                meta = layout.setdefault("meta", {})
                if isinstance(meta, dict):
                    meta["dashboard_visual_preserve_colorway"] = True

    data = spec.get("data")
    if not isinstance(data, list):
        return spec

    for trace_index, trace in enumerate(data):
        if not isinstance(trace, dict):
            continue
        name = str(trace.get("name") or "")
        group_stat = _group_stat_match(name)
        if group_stat is not None:
            group_label, stat_label = group_stat
            style_label = _stat_style_label(group_label, labels)
            style = (
                _resolve_series_style(
                    style_label,
                    labels,
                    trace_index=trace_index,
                    palette=palette,
                    overrides=overrides,
                    fallback_color=_trace_color(trace),
                )
                if style_label
                else {"color": _trace_color(trace)}
            )
            _apply_stat_trace_style(
                trace,
                style,
                group_label=group_label,
                stat_label=stat_label,
                stat_settings=stat_settings,
                preserve_color=preserve_colors,
            )
            continue

        reference_key = _reference_key(name)
        if reference_key:
            _apply_reference_trace_style(trace, reference_key, reference_settings)
            continue

        trace_chart_kind = _chart_kind_for_trace(trace, chart_kind)
        label = _series_label_for_trace(trace, labels)
        if label is None and trace_chart_kind == "trend" and _trace_looks_like_trend(trace):
            label = "Trend"
        if label is None and _trace_looks_like_model_curve(trace):
            trace_chart_kind = "model_curve"
            label = _strip_group_count_suffix(name)
        if label is None:
            continue
        style = _resolve_series_style(
            label,
            labels,
            trace_index=trace_index,
            palette=palette,
            overrides=overrides,
            fallback_color=_trace_color(trace),
        )
        _apply_series_trace_style(
            trace,
            style,
            label=label,
            chart_kind=trace_chart_kind,
            opacity=_chart_setting(series.get("opacity"), trace_chart_kind),
            marker_size=marker_size,
            marker_symbol=_distinguishing_value(marker_symbols, labels, label, use_distinguishers),
            pattern_shape=_distinguishing_value(pattern_shapes, labels, label, use_distinguishers),
            outline_width=outline_width,
            outline_color=outline_color,
            outline_color_mode=outline_color_mode,
            preserve_color=preserve_colors,
        )

    metadata = spec.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["dashboard_visual_settings_applied"] = True
    return spec


def _payload_visual_settings(payload: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("plotly_visual_settings", "visual_settings", "dashboard_visual_settings"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            return copy.deepcopy(dict(value))
    style = payload.get("style") if isinstance(payload.get("style"), Mapping) else {}
    value = style.get("plotly_visual_settings") if isinstance(style, Mapping) else None
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _series_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    series = settings.get("series")
    if isinstance(series, Mapping):
        return copy.deepcopy(dict(series))
    return {}


def _reference_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("reference_lines", "references"):
        value = settings.get(key)
        if isinstance(value, Mapping):
            return copy.deepcopy(dict(value))
    return {}


def _stat_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    value = settings.get("stat_lines")
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _deep_merge(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, Sequence):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _series_overrides(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        return {}
    overrides: dict[str, dict[str, Any]] = {}
    for key, raw_style in value.items():
        if isinstance(raw_style, Mapping):
            overrides[_normalize_label_key(str(key))] = copy.deepcopy(dict(raw_style))
    return overrides


def _line_overrides(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        return {}
    overrides: dict[str, dict[str, Any]] = {}
    for key, raw_style in value.items():
        if isinstance(raw_style, Mapping):
            overrides[_normalize_label_key(str(key))] = copy.deepcopy(dict(raw_style))
    return overrides


def _series_labels(payload: Mapping[str, Any], spec: Mapping[str, Any]) -> list[str]:
    labels: list[str] = []
    groups = payload.get("groups")
    if isinstance(groups, Sequence) and not isinstance(groups, (str, bytes)):
        for index, group in enumerate(groups, start=1):
            if isinstance(group, Mapping):
                label = str(group.get("group") or group.get("label") or f"Group {index}").strip()
                if label:
                    labels.append(_strip_group_count_suffix(label))
    raw_labels = payload.get("labels")
    if isinstance(raw_labels, Sequence) and not isinstance(raw_labels, (str, bytes)):
        for index, raw_label in enumerate(raw_labels, start=1):
            label = str(raw_label or f"Group {index}").strip()
            if label:
                labels.append(_strip_group_count_suffix(label))
    if labels:
        return _unique(labels)

    data = spec.get("data") if isinstance(spec.get("data"), list) else []
    for trace in data:
        if not isinstance(trace, Mapping):
            continue
        if _reference_key(str(trace.get("name") or "")):
            continue
        if _group_stat_match(str(trace.get("name") or "")):
            continue
        trace_type = str(trace.get("type") or "").casefold()
        mode = str(trace.get("mode") or "").casefold()
        if trace_type in {"bar", "histogram", "box", "violin"} or "markers" in mode:
            label = str(trace.get("name") or "").strip()
            if label:
                labels.append(_strip_group_count_suffix(label))
    return _unique(labels)


def _chart_kind(payload: Mapping[str, Any], spec: Mapping[str, Any]) -> str:
    raw = str(payload.get("type") or "").strip().casefold()
    if raw == "histogram" and isinstance(payload.get("groups"), Sequence):
        return "grouped_histogram"
    if raw == "distribution" and str(payload.get("render_mode") or "").strip().casefold() == "scatter":
        return "scatter"
    if raw:
        return raw
    metadata = spec.get("metadata") if isinstance(spec.get("metadata"), Mapping) else {}
    return str(metadata.get("kind") or "").strip().casefold()


def _chart_setting(value: Any, chart_kind: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(chart_kind, value.get("default"))
    return value


def _chart_kind_for_trace(trace: Mapping[str, Any], chart_kind: str) -> str:
    if _trace_looks_like_trend(trace):
        return "trend"
    if _trace_looks_like_model_curve(trace):
        return "model_curve"
    if str(chart_kind or "").casefold() == "trend" and _trace_has_markers(trace):
        return "scatter"
    return chart_kind


def _resolve_series_style(
    label: str,
    labels: Sequence[str],
    *,
    trace_index: int,
    palette: Sequence[str],
    overrides: Mapping[str, Mapping[str, Any]],
    fallback_color: str | None,
) -> dict[str, Any]:
    label_key = _normalize_label_key(label)
    style = dict(overrides.get(label_key) or {})
    try:
        label_index = list(labels).index(label)
    except ValueError:
        label_index = trace_index
    color = _string_or_none(style.get("color")) or (
        palette[label_index % len(palette)] if palette else fallback_color
    )
    style["color"] = color
    return style


def _apply_series_trace_style(
    trace: dict[str, Any],
    style: Mapping[str, Any],
    *,
    label: str,
    chart_kind: str,
    opacity: Any,
    marker_size: float | None,
    marker_symbol: str | None,
    pattern_shape: str | None,
    outline_width: float | None,
    outline_color: str | None,
    outline_color_mode: str,
    preserve_color: bool,
) -> None:
    is_trend_line = chart_kind in {"trend", "model_curve"} and (
        _trace_looks_like_trend(trace) or _trace_looks_like_model_curve(trace)
    )
    color = _string_or_none(style.get("color"))
    if color:
        if is_trend_line:
            line = trace.setdefault("line", {})
            if isinstance(line, dict):
                line["color"] = color
        else:
            _set_trace_color(trace, color)
    resolved_opacity = _finite_float(style.get("opacity"))
    if resolved_opacity is None:
        resolved_opacity = _finite_float(opacity)
    if resolved_opacity is not None:
        trace["opacity"] = max(0.0, min(1.0, resolved_opacity))

    marker = trace.setdefault("marker", {}) if not is_trend_line else {}
    if is_trend_line:
        line = trace.setdefault("line", {})
        if isinstance(line, dict):
            width = _finite_float(style.get("width"))
            dash = _string_or_none(style.get("dash"))
            if width is not None:
                line["width"] = max(0.0, width)
            if dash:
                line["dash"] = dash
    if isinstance(marker, dict) and not is_trend_line:
        resolved_marker_size = _finite_float(style.get("marker_size"))
        if resolved_marker_size is None:
            resolved_marker_size = marker_size
        if resolved_marker_size is not None and _trace_has_markers(trace):
            marker["size"] = resolved_marker_size
        resolved_symbol = _string_or_none(style.get("marker_symbol")) or marker_symbol
        if resolved_symbol and _trace_has_markers(trace):
            marker["symbol"] = resolved_symbol
        pattern_overridden = "pattern_shape" in style
        resolved_pattern = (
            str(style.get("pattern_shape") or "")
            if pattern_overridden
            else pattern_shape
        )
        if (
            (pattern_overridden or resolved_pattern)
            and str(trace.get("type") or "").casefold() in {"bar", "histogram"}
        ):
            pattern = marker.setdefault("pattern", {})
            if isinstance(pattern, dict):
                pattern["shape"] = resolved_pattern
        resolved_outline_width = _finite_float(style.get("outline_width"))
        if resolved_outline_width is None:
            resolved_outline_width = outline_width
        style_outline_color_mode = _outline_color_mode(style.get("outline_color_mode"))
        resolved_outline_color_mode = style_outline_color_mode or outline_color_mode
        raw_outline_color = _string_or_none(style.get("outline_color"))
        if raw_outline_color and raw_outline_color.casefold() == "auto":
            resolved_outline_color_mode = "auto"
            raw_outline_color = None
        resolved_outline_color = raw_outline_color or outline_color
        if resolved_outline_color and resolved_outline_color.casefold() == "auto":
            resolved_outline_color_mode = "auto"
            resolved_outline_color = None
        if resolved_outline_color_mode == "auto" and (resolved_outline_width or 0.0) > 0.0:
            resolved_outline_color = _contrasting_marker_outline_color(
                _string_or_none(marker.get("color")) or color or _trace_color(trace)
            )
        if resolved_outline_width is not None or resolved_outline_color:
            line = marker.setdefault("line", {})
            if isinstance(line, dict):
                if resolved_outline_width is not None:
                    line["width"] = max(0.0, resolved_outline_width)
                if resolved_outline_color:
                    line["color"] = resolved_outline_color

    role = chart_kind if chart_kind == "model_curve" else ("trend" if is_trend_line else "series")
    tag_plotly_visual_trace(
        trace,
        role=role,
        target_id=f"{role}:{_normalize_label_key(label)}",
        label=label,
        capabilities=_style_capabilities_for_series_trace(trace, role),
        chart_kind=chart_kind,
        series_id=_normalize_label_key(label),
        preserve_color=bool(color and preserve_color),
    )


def _apply_stat_trace_style(
    trace: dict[str, Any],
    style: Mapping[str, Any],
    *,
    group_label: str,
    stat_label: str,
    stat_settings: Mapping[str, Any],
    preserve_color: bool,
) -> None:
    overrides = _line_overrides(stat_settings.get("overrides"))
    override = overrides.get(_stat_override_key(group_label, stat_label)) or overrides.get(
        _normalize_label_key(stat_label)
    ) or {}
    color = _string_or_none(style.get("color"))
    override_color = _string_or_none(override.get("color"))
    if color and not override_color and bool(stat_settings.get("accent_by_stat")):
        color = _accent_color(color, stat_label)
    if override_color:
        color = override_color
    if color:
        line = trace.setdefault("line", {})
        if isinstance(line, dict):
            line["color"] = color
    width = _finite_float(override.get("width"))
    if width is None:
        width = _finite_float(stat_settings.get("width"))
    if width is not None:
        line = trace.setdefault("line", {})
        if isinstance(line, dict):
            line["width"] = max(0.0, width)
    dash = _string_or_none(override.get("dash"))
    if dash:
        line = trace.setdefault("line", {})
        if isinstance(line, dict):
            line["dash"] = dash
    opacity = _finite_float(override.get("opacity"))
    if opacity is not None:
        trace["opacity"] = max(0.0, min(1.0, opacity))
    tag_plotly_visual_trace(
        trace,
        role="stat",
        target_id=f"stat:{_stat_override_key(group_label, stat_label)}",
        label=str(trace.get("name") or stat_label),
        capabilities=_LINE_STYLE_CAPABILITIES,
        series_id=_normalize_label_key(group_label),
        stat_id=_normalize_label_key(stat_label),
        preserve_color=bool(color and preserve_color),
    )


def _apply_reference_trace_style(
    trace: dict[str, Any],
    reference_key: str,
    reference_settings: Mapping[str, Any],
) -> None:
    raw_style = reference_settings.get(reference_key)
    if not isinstance(raw_style, Mapping):
        return
    line = trace.setdefault("line", {})
    if not isinstance(line, dict):
        return
    color = _string_or_none(raw_style.get("color"))
    dash = _string_or_none(raw_style.get("dash"))
    width = _finite_float(raw_style.get("width"))
    opacity = _finite_float(raw_style.get("opacity"))
    if color:
        line["color"] = color
    if dash:
        line["dash"] = dash
    if width is not None:
        line["width"] = max(0.0, width)
    if opacity is not None:
        trace["opacity"] = max(0.0, min(1.0, opacity))
    tag_plotly_visual_trace(
        trace,
        role="reference",
        target_id=f"reference:{reference_key}",
        label=str(trace.get("name") or reference_key.upper()),
        capabilities=_LINE_STYLE_CAPABILITIES,
        reference_id=reference_key,
    )


def _series_label_for_trace(trace: Mapping[str, Any], labels: Sequence[str]) -> str | None:
    name = _strip_group_count_suffix(str(trace.get("name") or "").strip())
    if name in labels:
        return name
    if len(labels) == 1 and name in {"Frequency", "Histogram", "Measurements", ""}:
        return labels[0]
    if not labels and name:
        return name
    return None


def _style_capabilities_for_series_trace(trace: Mapping[str, Any], role: str) -> tuple[str, ...]:
    if role in {"trend", "model_curve"}:
        return _LINE_STYLE_CAPABILITIES
    capabilities = ["color", "opacity", "outline_width", "outline_color", "outline_color_mode"]
    if _trace_has_markers(trace):
        capabilities.extend(("marker_size", "marker_symbol"))
    if str(trace.get("type") or "").casefold() in {"bar", "histogram"}:
        capabilities.append(_PATTERN_STYLE_CAPABILITY)
    return tuple(capabilities)


def _set_trace_color(trace: dict[str, Any], color: str) -> None:
    marker = trace.setdefault("marker", {})
    if isinstance(marker, dict):
        marker["color"] = color
    line = trace.setdefault("line", {})
    if isinstance(line, dict):
        line["color"] = color
    if str(trace.get("type") or "").casefold() in {"violin", "box", "scatter"}:
        trace["fillcolor"] = color


def _trace_has_markers(trace: Mapping[str, Any]) -> bool:
    mode = str(trace.get("mode") or "").casefold()
    return "markers" in mode


def _trace_color(trace: Mapping[str, Any]) -> str | None:
    marker = trace.get("marker") if isinstance(trace.get("marker"), Mapping) else {}
    line = trace.get("line") if isinstance(trace.get("line"), Mapping) else {}
    for value in (marker.get("color"), line.get("color"), trace.get("fillcolor")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _reference_key(name: str) -> str | None:
    key = str(name or "").split("=", 1)[0].strip().casefold()
    return _REFERENCE_PREFIXES.get(key)


def _group_stat_match(name: str) -> tuple[str, str] | None:
    match = _GROUP_STAT_PATTERN.match(str(name or "").strip())
    if not match:
        return None
    group = match.group("group")
    return (_strip_group_count_suffix(group) if group is not None else ""), match.group("stat")


def _stat_style_label(group_label: str, labels: Sequence[str]) -> str:
    if group_label:
        return group_label
    if len(labels) == 1:
        return labels[0]
    return ""


def _trace_looks_like_trend(trace: Mapping[str, Any]) -> bool:
    name = str(trace.get("name") or "").strip().casefold()
    mode = str(trace.get("mode") or "").casefold()
    return name == "trend" and "lines" in mode and _reference_key(name) is None


def _trace_looks_like_model_curve(trace: Mapping[str, Any]) -> bool:
    name = str(trace.get("name") or "").strip().casefold()
    mode = str(trace.get("mode") or "").casefold()
    if "lines" not in mode or _reference_key(name) is not None or _group_stat_match(name):
        return False
    return "curve" in name or "kde" in name or "model" in name


def _distinguishing_value(
    values: Sequence[str],
    labels: Sequence[str],
    label: str,
    enabled: bool,
) -> str | None:
    if not enabled or not values:
        return None
    try:
        index = list(labels).index(label)
    except ValueError:
        index = 0
    return values[index % len(values)]


def _palette_has_similar_colors(colors: Sequence[str], *, threshold: float) -> bool:
    parsed = [_parse_hex_color(color) for color in colors]
    parsed = [item for item in parsed if item is not None]
    for index, left in enumerate(parsed):
        for right in parsed[index + 1 :]:
            distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))
            if distance < threshold:
                return True
    return False


def _similarity_threshold(series_settings: Mapping[str, Any]) -> float:
    value = _finite_float(series_settings.get("similarity_threshold"))
    return value if value is not None and value > 0 else _DEFAULT_SIMILARITY_THRESHOLD


def _parse_hex_color(value: str) -> tuple[int, int, int] | None:
    text = str(value or "").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        return None
    return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)


def _contrasting_marker_outline_color(color: str | None) -> str:
    rgb = _parse_hex_color(str(color or ""))
    if rgb is None:
        return "#111827"
    red, green, blue = rgb
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255.0
    return "#111827" if luminance >= 0.58 else "#ffffff"


def _outline_color_mode(value: Any) -> str:
    text = str(value or "").strip().casefold()
    return text if text in {"auto", "custom"} else ""


def _accent_color(color: str, stat_label: str) -> str:
    rgb = _parse_hex_color(color)
    if rgb is None:
        return color
    factor = _STAT_ACCENT_FACTORS.get(str(stat_label or "").casefold(), 1.0)
    adjusted = []
    for channel in rgb:
        if factor >= 1.0:
            adjusted.append(round(channel + (255 - channel) * min(factor - 1.0, 0.55)))
        else:
            adjusted.append(round(channel * max(factor, 0.25)))
    return "#{:02X}{:02X}{:02X}".format(*[max(0, min(255, int(value))) for value in adjusted])


def _strip_group_count_suffix(label: str) -> str:
    stripped = _GROUP_COUNT_SUFFIX_PATTERN.sub("", str(label or "").strip()).strip()
    return stripped or str(label or "").strip()


def _normalize_label_key(label: str) -> str:
    return _strip_group_count_suffix(label).casefold()


def _stat_override_key(group_label: str, stat_label: str) -> str:
    stat_key = _normalize_label_key(stat_label)
    group_key = _normalize_label_key(group_label)
    return f"{group_key}::{stat_key}" if group_key else stat_key


def _unique(values: Sequence[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _normalize_label_key(value)
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _unique_strings(values: Sequence[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _string_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
