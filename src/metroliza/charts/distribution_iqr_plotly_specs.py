"""Shared Plotly spec builders for dashboard distribution and IQR payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, ROUND_HALF_UP
import math
import re
from typing import Any

from metroliza.charts.summary_plot_palette import SUMMARY_PLOT_PALETTE

_GROUP_COUNT_SUFFIX_PATTERN = re.compile(r"\s*\(n\s*=\s*\d+\)\s*$", re.IGNORECASE)
_STAT_DASH_BY_LABEL = {
    "Min": "dot",
    "Q1": "dash",
    "Median": "solid",
    "Mean": "dashdot",
    "Q3": "dash",
    "Max": "dot",
}
_DEFAULT_COLORWAY = (
    SUMMARY_PLOT_PALETTE["distribution_foreground"],
    "#D55E00",
    "#009E73",
    SUMMARY_PLOT_PALETTE["outlier"],
    SUMMARY_PLOT_PALETTE["central_tendency"],
    SUMMARY_PLOT_PALETTE["distribution_base"],
)


def build_distribution_plotly_spec(
    payload: Mapping[str, Any],
    *,
    title: str,
    static: bool = True,
    theme: str | Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a Plotly violin spec for a Metroliza ``type=distribution`` payload."""

    return build_distribution_iqr_plotly_spec(
        payload,
        title=title,
        chart_type="distribution",
        static=static,
        theme=theme,
    )


def build_iqr_plotly_spec(
    payload: Mapping[str, Any],
    *,
    title: str,
    static: bool = True,
    theme: str | Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a Plotly box spec for a Metroliza ``type=iqr`` payload."""

    return build_distribution_iqr_plotly_spec(
        payload,
        title=title,
        chart_type="iqr",
        static=static,
        theme=theme,
    )


def build_distribution_iqr_plotly_spec(
    payload: Mapping[str, Any],
    *,
    title: str,
    chart_type: str | None = None,
    static: bool = True,
    theme: str | Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a shared Plotly spec for distribution violin and IQR box payloads."""

    resolved_type = str(chart_type or payload.get("type") or "").strip().casefold()
    if resolved_type not in {"distribution", "iqr"}:
        return None
    render_mode = str(payload.get("render_mode") or "violin").strip().casefold()
    if resolved_type == "distribution" and render_mode != "violin":
        return None

    series_items = _payload_distribution_series(payload)
    raw_labels = [str(item) for item in (payload.get("labels") or [])]
    groups: list[tuple[str, list[float]]] = []
    for index, series in enumerate(series_items, start=1):
        values = _coerce_finite_float_list(series)
        if not values:
            continue
        label = raw_labels[index - 1] if index <= len(raw_labels) and raw_labels[index - 1] else f"Group {index}"
        groups.append((label, values))
    if not groups:
        return None

    tokens = _theme_tokens(theme)
    group_count = len(groups)
    axis_range = [0.5, group_count + 0.5]
    mean_precision = _mean_precision_from_groups(groups)
    traces: list[dict[str, Any]] = []
    for position, (label, values) in enumerate(groups, start=1):
        color = tokens["colorway"][(position - 1) % len(tokens["colorway"])]
        trace_name = _format_group_statistics_trace_name(label, values)
        base_trace = {
            "type": "violin" if resolved_type == "distribution" else "box",
            "name": trace_name,
            "x": [position] * len(values),
            "y": values,
            "marker": {"color": color},
            "line": {"color": color, "width": 1.2},
            "hovertemplate": f"{trace_name}<br>Measurement=%{{y}}<extra></extra>",
        }
        if resolved_type == "distribution":
            base_trace.update(
                {
                    "box": {"visible": True},
                    "meanline": {"visible": True},
                    "fillcolor": color,
                    "opacity": 0.84,
                    "points": False,
                    "scalemode": "count",
                    "spanmode": "hard",
                }
            )
        else:
            base_trace.update({"boxpoints": False, "boxmean": True})
        traces.append(base_trace)

    traces.extend(
        _stat_line_traces(
            groups,
            axis_range=axis_range,
            mean_precision=mean_precision,
            colorway=tokens["colorway"],
        )
    )
    traces.extend(
        _reference_line_traces(
            payload,
            axis_range=axis_range,
            mean_precision=mean_precision,
            tokens=tokens,
        )
    )

    return {
        "data": traces,
        "layout": _layout(
            title=title,
            x_label=str(payload.get("x_label") or "Group"),
            y_label=str(payload.get("y_label") or "Measurement"),
            ticktext=[label for label, _values in groups],
            axis_range=axis_range,
            tokens=tokens,
        ),
        "config": {
            "responsive": True,
            "scrollZoom": False,
            "displaylogo": False,
            "staticPlot": bool(static),
        },
        "metadata": {"kind": resolved_type, "mean_precision": mean_precision},
    }


def _payload_distribution_series(payload: Mapping[str, Any]) -> list[Any]:
    series = payload.get("series")
    if isinstance(series, list):
        return series
    values = payload.get("values")
    if isinstance(values, list):
        return values
    return []


def _coerce_finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _coerce_finite_float_list(values: Any) -> list[float]:
    return [number for value in values or [] if (number := _coerce_finite_float(value)) is not None]


def _format_group_statistics_trace_name(label: str, values: Sequence[float]) -> str:
    text = str(label)
    if _GROUP_COUNT_SUFFIX_PATTERN.search(text.strip()):
        return text
    return f"{text} (n={len(values)})"


def _strip_group_count_suffix(label: str) -> str:
    stripped = _GROUP_COUNT_SUFFIX_PATTERN.sub("", str(label or "").strip()).strip()
    return stripped or str(label or "").strip()


def _stat_line_traces(
    groups: Sequence[tuple[str, list[float]]],
    *,
    axis_range: Sequence[float],
    mean_precision: int,
    colorway: Sequence[str],
) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    populated_count = len(groups)
    for index, (label, raw_values) in enumerate(groups):
        values = sorted(raw_values)
        group_label = _strip_group_count_suffix(label)
        prefix = "" if populated_count <= 1 else f"({group_label}) "
        stats = {
            "Min": min(values),
            "Q1": _percentile_sorted(values, 0.25),
            "Median": _percentile_sorted(values, 0.5),
            "Mean": sum(values) / len(values),
            "Q3": _percentile_sorted(values, 0.75),
            "Max": max(values),
        }
        for stat_label, value in stats.items():
            traces.append(
                _line_trace(
                    name=(
                        f"{prefix}{stat_label}="
                        f"{_format_metrology_legend_value(stat_label, value, mean_precision=mean_precision)}"
                    ),
                    value=value,
                    axis_range=axis_range,
                    color=colorway[index % len(colorway)],
                    dash=_STAT_DASH_BY_LABEL[stat_label],
                    visible="legendonly",
                )
            )
    return traces


def _reference_line_traces(
    payload: Mapping[str, Any],
    *,
    axis_range: Sequence[float],
    mean_precision: int,
    tokens: Mapping[str, Any],
) -> list[dict[str, Any]]:
    limits = payload.get("limits") if isinstance(payload.get("limits"), Mapping) else {}
    traces: list[dict[str, Any]] = []
    for label, key, color, dash in (
        ("LSL", "lsl", tokens["reference_limit"], "dash"),
        ("Nominal", "nominal", tokens["reference_nominal"], "solid"),
        ("USL", "usl", tokens["reference_limit"], "dash"),
    ):
        value = _coerce_finite_float(limits.get(key, payload.get(key)))
        if value is None:
            continue
        traces.append(
            _line_trace(
                name=f"{label}={_format_metrology_legend_value(label, value, mean_precision=mean_precision)}",
                value=value,
                axis_range=axis_range,
                color=str(color),
                dash=dash,
                visible=None,
            )
        )
    return traces


def _line_trace(
    *,
    name: str,
    value: float,
    axis_range: Sequence[float],
    color: str,
    dash: str,
    visible: str | None,
) -> dict[str, Any]:
    trace = {
        "type": "scatter",
        "mode": "lines",
        "name": name,
        "x": [float(axis_range[0]), float(axis_range[1])],
        "y": [float(value), float(value)],
        "line": {"color": color, "width": 2, "dash": dash},
        "hoverinfo": "skip",
        "showlegend": True,
    }
    if visible is not None:
        trace["visible"] = visible
    return trace


def _layout(
    *,
    title: str,
    x_label: str,
    y_label: str,
    ticktext: Sequence[str],
    axis_range: Sequence[float],
    tokens: Mapping[str, Any],
) -> dict[str, Any]:
    tickvals = list(range(1, len(ticktext) + 1))
    return {
        "title": {"text": str(title or ""), "font": {"size": 18}},
        "font": {"family": 'Aptos, "Segoe UI", "Helvetica Neue", sans-serif', "color": tokens["text"]},
        "paper_bgcolor": tokens["paper_bg"],
        "plot_bgcolor": tokens["plot_bg"],
        "colorway": list(tokens["colorway"]),
        "dragmode": "zoom",
        "margin": {"l": 56, "r": 188, "t": 72, "b": 62},
        "hoverlabel": {"bgcolor": tokens["hover_bg"], "font": {"color": tokens["hover_text"]}},
        "xaxis": {
            "title": {"text": x_label},
            "type": "linear",
            "range": [float(axis_range[0]), float(axis_range[1])],
            "autorange": False,
            "tickmode": "array",
            "tickvals": tickvals,
            "ticktext": [str(label) for label in ticktext],
            "gridcolor": tokens["grid"],
            "zerolinecolor": tokens["zero"],
            "linecolor": tokens["axis"],
        },
        "yaxis": {
            "title": {"text": y_label},
            "gridcolor": tokens["grid"],
            "zerolinecolor": tokens["zero"],
            "linecolor": tokens["axis"],
        },
        "legend": {
            "orientation": "v",
            "xanchor": "left",
            "x": 1.02,
            "yanchor": "top",
            "y": 1.0,
            "bgcolor": tokens["legend_bg"],
            "bordercolor": tokens["legend_border"],
            "borderwidth": 1,
        },
    }


def _theme_tokens(theme: str | Mapping[str, Any] | None) -> dict[str, Any]:
    colorway = _colorway_from_theme(theme) or list(_DEFAULT_COLORWAY)
    if isinstance(theme, Mapping):
        colors = theme.get("colors") if isinstance(theme.get("colors"), Mapping) else {}
        text = str(colors.get("text") or "#162330")
        background = str(colors.get("background") or "#ffffff")
        plot_background = str(colors.get("plot_background") or background)
        grid = str(colors.get("grid") or "rgba(22,35,48,0.08)")
        axis = str(colors.get("axis") or "rgba(22,35,48,0.18)")
        return {
            "colorway": colorway,
            "text": text,
            "paper_bg": background,
            "plot_bg": plot_background,
            "grid": grid,
            "zero": axis,
            "axis": axis,
            "legend_bg": background,
            "legend_border": axis,
            "hover_bg": background,
            "hover_text": text,
            "reference_limit": str(colors.get("spec_limit") or SUMMARY_PLOT_PALETTE["spec_limit"]),
            "reference_nominal": str(
                colors.get("nominal") or SUMMARY_PLOT_PALETTE["central_tendency"]
            ),
        }
    dark = str(theme or "").strip().casefold() == "dark"
    if dark:
        return {
            "colorway": colorway,
            "text": "#edf3fb",
            "paper_bg": "rgba(0,0,0,0)",
            "plot_bg": "rgba(10,17,27,0.96)",
            "grid": "rgba(233,241,251,0.10)",
            "zero": "rgba(233,241,251,0.14)",
            "axis": "rgba(233,241,251,0.18)",
            "legend_bg": "rgba(8,16,26,0.82)",
            "legend_border": "rgba(233,241,251,0.10)",
            "hover_bg": "#07111a",
            "hover_text": "#f8fbff",
            "reference_limit": "#ffb454",
            "reference_nominal": "#5fd6ba",
        }
    return {
        "colorway": colorway,
        "text": "#162330",
        "paper_bg": "rgba(255,255,255,0)",
        "plot_bg": "rgba(255,255,255,0.88)",
        "grid": "rgba(22,35,48,0.08)",
        "zero": "rgba(22,35,48,0.12)",
        "axis": "rgba(22,35,48,0.18)",
        "legend_bg": "rgba(255,255,255,0.86)",
        "legend_border": "rgba(22,35,48,0.12)",
        "hover_bg": "#ffffff",
        "hover_text": "#162330",
        "reference_limit": SUMMARY_PLOT_PALETTE["spec_limit"],
        "reference_nominal": SUMMARY_PLOT_PALETTE["central_tendency"],
    }


def _colorway_from_theme(theme: str | Mapping[str, Any] | None) -> list[str] | None:
    if not isinstance(theme, Mapping):
        return None
    raw_colors = theme.get("colorway")
    if not isinstance(raw_colors, list):
        colors = theme.get("colors") if isinstance(theme.get("colors"), Mapping) else {}
        raw_colors = colors.get("colorway")
    if not isinstance(raw_colors, list):
        return None
    colorway = [str(color) for color in raw_colors if color]
    return colorway or None


def _percentile_sorted(values: Sequence[float], fraction: float) -> float:
    if len(values) == 1:
        return float(values[0])
    position = max(0.0, min(1.0, float(fraction))) * (len(values) - 1)
    lower_index = int(math.floor(position))
    upper_index = int(math.ceil(position))
    if lower_index == upper_index:
        return float(values[lower_index])
    weight = position - lower_index
    return float(values[lower_index] * (1.0 - weight) + values[upper_index] * weight)


def _mean_precision_from_groups(groups: Sequence[tuple[str, list[float]]]) -> int:
    values = [value for _label, series in groups for value in series]
    if not values:
        return 4
    decimals = _infer_decimal_places(values)
    return max(0, min(decimals + 1, 8))


def _infer_decimal_places(values: Sequence[float], *, max_decimals: int = 6) -> int:
    for decimals in range(max_decimals + 1):
        tolerance = max(1e-12, 10.0 ** (-(decimals + 3)))
        if all(math.isclose(value, round(value, decimals), rel_tol=0.0, abs_tol=tolerance) for value in values):
            return decimals
    return max_decimals


def _format_metrology_legend_value(
    label: str,
    value: float | None,
    *,
    mean_precision: int | None = None,
) -> str:
    if value is None or not math.isfinite(float(value)):
        return ""
    precision = int(mean_precision) if label.strip().casefold() == "mean" else 3
    precision = max(0, min(precision, 8))
    quantizer = Decimal("1").scaleb(-precision)
    rounded = Decimal(str(round(float(value), 12))).quantize(quantizer, rounding=ROUND_HALF_UP)
    return f"{rounded:.{precision}f}"


__all__ = [
    "build_distribution_iqr_plotly_spec",
    "build_distribution_plotly_spec",
    "build_iqr_plotly_spec",
]
