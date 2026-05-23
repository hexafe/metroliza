"""Shared dashboard visual options and preview builders."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import colorsys
import copy
import json
import math
from pathlib import Path
import tempfile
from typing import Any
from io import BytesIO

from modules.dashboard_plotly_visuals import apply_dashboard_visual_settings
from modules.summary_plot_palette import SUMMARY_PLOT_PALETTE


DASHBOARD_VISUAL_PRESETS = ("auto", "distinct", "print", "custom")
DASHBOARD_VISUAL_PALETTE_MODES = ("fixed", "auto_gradient", "highlight_gradient")
DASHBOARD_VISUAL_GRADIENT_SPREADS = ("narrow", "normal", "wide")
DASHBOARD_VISUAL_DISTINGUISH_MODES = ("color_only", "when_similar", "always")
DASHBOARD_VISUAL_CHART_TYPES = ("histogram", "violin", "iqr", "scatter")

DEFAULT_DASHBOARD_PALETTE = tuple(
    str(color).lower()
    for color in (
        SUMMARY_PLOT_PALETTE["distribution_foreground"],
        "#D55E00",
        "#009E73",
        SUMMARY_PLOT_PALETTE["outlier"],
        SUMMARY_PLOT_PALETTE["central_tendency"],
        SUMMARY_PLOT_PALETTE["distribution_base"],
    )
)
PRINT_DASHBOARD_PALETTE = ("#111827", "#4b5563", "#737373", "#9ca3af", "#d4d4d4", "#6b7280")
DEFAULT_HIGHLIGHT_ANCHOR = "#facc15"
DEFAULT_OPACITY = {
    "histogram": 0.86,
    "grouped_histogram": 0.55,
    "distribution": 0.84,
    "iqr": 0.62,
    "scatter": 0.82,
    "trend": 0.35,
}
_MARKER_SYMBOLS = ("circle", "diamond", "square", "cross", "x", "triangle-up")
_PATTERN_SHAPES = ("", "/", "\\", "x", ".", "-")
_REFERENCE_DEFAULTS = {
    "lsl": {"color": str(SUMMARY_PLOT_PALETTE["spec_limit"]).lower(), "dash": "dash", "width": 1.5},
    "usl": {"color": str(SUMMARY_PLOT_PALETTE["spec_limit"]).lower(), "dash": "dash", "width": 1.5},
    "nominal": {
        "color": str(SUMMARY_PLOT_PALETTE["central_tendency"]).lower(),
        "dash": "solid",
        "width": 1.5,
    },
}
_PRESET_LABELS = {
    "auto": "Auto",
    "distinct": "Distinct groups",
    "print": "Print friendly",
    "custom": "Custom",
}


def default_dashboard_visual_settings() -> dict[str, Any]:
    """Return the serializable default dashboard visual settings."""

    return {
        "preset": "auto",
        "palette_mode": "fixed",
        "palette": list(DEFAULT_DASHBOARD_PALETTE),
        "anchor_color": DEFAULT_HIGHLIGHT_ANCHOR,
        "gradient_spread": "normal",
        "distinguish": "when_similar",
        "opacity": dict(DEFAULT_OPACITY),
        "marker_size": 7.0,
        "stat_lines": {"accent_by_stat": False, "width": 2.0},
        "reference_lines": copy.deepcopy(_REFERENCE_DEFAULTS),
    }


def default_dashboard_visual_config_path() -> Path:
    """Return the shared user config path for dashboard visual settings."""

    return Path.home() / ".metroliza" / ".dashboard_visual_options.json"


def load_dashboard_visual_settings(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load persisted visual settings, returning defaults when unavailable."""

    path = Path(config_path) if config_path is not None else default_dashboard_visual_config_path()
    if not path.exists():
        return default_dashboard_visual_settings()
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default_dashboard_visual_settings()
    return normalize_dashboard_visual_settings(payload)


def save_dashboard_visual_settings(
    settings: Mapping[str, Any] | None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Persist and return normalized visual settings."""

    normalized = normalize_dashboard_visual_settings(settings)
    path = Path(config_path) if config_path is not None else default_dashboard_visual_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(normalized, handle, indent=2, sort_keys=True)
    return normalized


def normalize_dashboard_visual_settings(settings: Any) -> dict[str, Any]:
    """Normalize user/dashboard visual options into a stable serializable shape."""

    defaults = default_dashboard_visual_settings()
    if not isinstance(settings, Mapping):
        return defaults
    normalized = copy.deepcopy(defaults)
    normalized["preset"] = _choice(settings.get("preset"), DASHBOARD_VISUAL_PRESETS, defaults["preset"])
    normalized["palette_mode"] = _choice(
        settings.get("palette_mode"),
        DASHBOARD_VISUAL_PALETTE_MODES,
        defaults["palette_mode"],
    )
    normalized["palette"] = _palette(settings.get("palette"), fallback=defaults["palette"])
    normalized["anchor_color"] = _color(settings.get("anchor_color"), defaults["anchor_color"])
    normalized["gradient_spread"] = _choice(
        settings.get("gradient_spread"),
        DASHBOARD_VISUAL_GRADIENT_SPREADS,
        defaults["gradient_spread"],
    )
    normalized["distinguish"] = _choice(
        settings.get("distinguish"),
        DASHBOARD_VISUAL_DISTINGUISH_MODES,
        defaults["distinguish"],
    )
    opacity = settings.get("opacity")
    if isinstance(opacity, Mapping):
        normalized["opacity"] = {
            key: _bounded_float(opacity.get(key), fallback=value, minimum=0.05, maximum=1.0)
            for key, value in defaults["opacity"].items()
        }
    normalized["marker_size"] = _bounded_float(
        settings.get("marker_size"),
        fallback=defaults["marker_size"],
        minimum=2.0,
        maximum=18.0,
    )
    stat_lines = settings.get("stat_lines")
    if isinstance(stat_lines, Mapping):
        normalized["stat_lines"] = {
            "accent_by_stat": bool(stat_lines.get("accent_by_stat", False)),
            "width": _bounded_float(
                stat_lines.get("width"),
                fallback=defaults["stat_lines"]["width"],
                minimum=0.5,
                maximum=6.0,
            ),
        }
    reference_lines = settings.get("reference_lines")
    if isinstance(reference_lines, Mapping):
        normalized["reference_lines"] = {
            key: _normalize_reference_style(reference_lines.get(key), defaults["reference_lines"][key])
            for key in ("lsl", "usl", "nominal")
        }
    return normalized


def dashboard_visual_settings_summary(settings: Any) -> str:
    """Return short user-facing summary text for a visual-settings payload."""

    normalized = normalize_dashboard_visual_settings(settings)
    preset = normalized["preset"]
    if preset != "custom":
        return _PRESET_LABELS[preset]
    mode = normalized["palette_mode"]
    if mode == "auto_gradient":
        return "Custom gradient"
    if mode == "highlight_gradient":
        return "Custom highlight gradient"
    return "Custom palette"


def dashboard_visual_swatch_palette(settings: Any, *, count: int = 6) -> list[str]:
    """Return the palette that should be previewed in the UI."""

    normalized = normalize_dashboard_visual_settings(settings)
    return _resolved_palette(normalized, count=max(1, int(count)))


def dashboard_visual_settings_to_plotly_settings(settings: Any) -> dict[str, Any]:
    """Convert high-level UI settings into the dashboard Plotly visual contract."""

    normalized = normalize_dashboard_visual_settings(settings)
    if normalized["preset"] == "auto":
        return {}

    palette = _resolved_palette(normalized, count=6)
    distinguish = normalized["distinguish"]
    always_distinguish = distinguish == "always" or normalized["preset"] == "print"
    use_distinguishers = distinguish != "color_only" or normalized["preset"] == "print"
    return {
        "preserve_colors_on_theme": True,
        "series": {
            "palette": palette,
            "opacity": dict(normalized["opacity"]),
            "marker_size": normalized["marker_size"],
            "marker_symbols": list(_MARKER_SYMBOLS if use_distinguishers else ()),
            "patterns": list(_PATTERN_SHAPES if use_distinguishers else ()),
            "auto_distinguish": distinguish == "when_similar",
            "always_distinguish": always_distinguish,
        },
        "stat_lines": dict(normalized["stat_lines"]),
        "reference_lines": copy.deepcopy(normalized["reference_lines"]),
    }


def build_dashboard_visual_preview_spec(
    settings: Any,
    *,
    chart_type: str = "histogram",
) -> dict[str, Any] | None:
    """Build a Plotly preview spec from deterministic sample data."""

    normalized = normalize_dashboard_visual_settings(settings)
    plotly_settings = dashboard_visual_settings_to_plotly_settings(normalized)
    chart_type = _choice(chart_type, DASHBOARD_VISUAL_CHART_TYPES, "histogram")
    if chart_type == "scatter":
        return _scatter_preview_spec(plotly_settings)

    from modules.hexafe_plotstats_adapter import (
        build_dashboard_plotly_spec,
        metroliza_dashboard_plotstats_theme,
    )

    payload = _preview_payload(chart_type)
    if plotly_settings:
        payload["plotly_visual_settings"] = plotly_settings
    theme = metroliza_dashboard_plotstats_theme()
    spec = build_dashboard_plotly_spec(
        payload,
        title="Dashboard visual preview",
        theme=theme,
        static=False,
    )
    if spec and plotly_settings:
        apply_dashboard_visual_settings(
            spec,
            payload=payload,
            visual_settings=plotly_settings,
            theme=theme,
        )
    return spec


def build_dashboard_visual_preview_html(spec: Mapping[str, Any]) -> str:
    """Build a small standalone Plotly preview document for QWebEngine."""

    plotly_asset = Path(__file__).resolve().parent / "html_dashboard_assets" / "plotly-2.27.0.min.js"
    spec_json = json.dumps(spec, ensure_ascii=False)
    asset_uri = plotly_asset.resolve().as_uri()
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>html,body,#chart{height:100%;margin:0;background:#fff;}</style>"
        f"<script src='{asset_uri}'></script></head><body><div id='chart'></div>"
        "<script>"
        f"const spec = {spec_json};"
        "Plotly.newPlot('chart', spec.data || [], spec.layout || {}, spec.config || {});"
        "</script></body></html>"
    )


def build_dashboard_visual_preview_png(
    settings: Any,
    *,
    chart_type: str = "histogram",
) -> bytes | None:
    """Render a lightweight PNG preview through the plotstats artifact path."""

    payload = _preview_payload(chart_type)
    low_level = dashboard_visual_settings_to_plotly_settings(settings)
    from modules.hexafe_plotstats_adapter import metroliza_dashboard_plotstats_theme, render_chart_artifact_png

    if low_level:
        payload["plotly_visual_settings"] = low_level
        theme = metroliza_dashboard_plotstats_theme()
        theme["visual"] = low_level
    else:
        theme = metroliza_dashboard_plotstats_theme()
    try:
        rendered = render_chart_artifact_png(
            payload,
            target="workbook_image",
            backend="auto",
            theme=theme,
        )
    except TypeError:
        rendered = render_chart_artifact_png(payload, target="workbook_image", backend="auto")
    if rendered is not None and rendered.png_bytes:
        return rendered.png_bytes
    return _preview_svg_png_fallback(settings)


def temporary_dashboard_visual_preview_html(spec: Mapping[str, Any]) -> Path:
    """Write preview HTML into a temp file and return its path."""

    path = Path(tempfile.gettempdir()) / "metroliza_dashboard_visual_preview.html"
    path.write_text(build_dashboard_visual_preview_html(spec), encoding="utf-8")
    return path


def _preview_payload(chart_type: str) -> dict[str, Any]:
    labels = ["Group 1", "Group 2", "Group 3", "Group 4", "Population points"]
    series = [
        [6.10, 6.20, 6.23, 6.28, 6.32, 6.37, 6.41, 6.47],
        [6.31, 6.38, 6.42, 6.48, 6.53, 6.57, 6.61, 6.66],
        [6.52, 6.59, 6.63, 6.67, 6.71, 6.78, 6.82, 6.87],
        [6.72, 6.77, 6.83, 6.88, 6.94, 6.99, 7.05, 7.10],
        [6.18, 6.44, 6.70, 6.96, 7.12],
    ]
    limits = {"lsl": 6.0, "nominal": 6.55, "usl": 7.15}
    if chart_type == "scatter":
        x_values: list[float] = []
        y_values: list[float] = []
        point_labels: list[str] = []
        for group_index, (label, values) in enumerate(zip(labels, series, strict=False)):
            for point_index, value in enumerate(values[:5], start=1):
                x_values.append(float(point_index))
                y_values.append(float(value + group_index * 0.02))
                point_labels.append(label)
        return {
            "type": "distribution",
            "render_mode": "scatter",
            "title": "Dashboard visual preview",
            "x_values": x_values,
            "y_values": y_values,
            "labels": point_labels,
            "limits": limits,
            "x_label": "Sample",
            "y_label": "Measurement",
        }
    if chart_type == "histogram":
        return {
            "type": "histogram",
            "title": "Dashboard visual preview",
            "groups": [
                {"group": label, "values": values}
                for label, values in zip(labels, series, strict=False)
            ],
            "limits": limits,
            "style": {"axis_label_x": "Measurement", "axis_label_y": "Frequency (%)"},
        }
    if chart_type == "iqr":
        return {
            "type": "iqr",
            "render_mode": "iqr",
            "title": "Dashboard visual preview",
            "labels": labels,
            "series": series,
            "limits": limits,
            "x_label": "Groups",
            "y_label": "Measurement",
        }
    return {
        "type": "distribution",
        "render_mode": "violin",
        "title": "Dashboard visual preview",
        "labels": labels,
        "series": series,
        "limits": limits,
        "x_label": "Groups",
        "y_label": "Measurement",
    }


def _scatter_preview_spec(plotly_settings: Mapping[str, Any]) -> dict[str, Any]:
    from modules.hexafe_plotstats_adapter import metroliza_dashboard_plotstats_theme

    labels = ["Group 1", "Group 2", "Group 3", "Group 4", "Population points"]
    theme = metroliza_dashboard_plotstats_theme()
    palette = dashboard_visual_swatch_palette({"preset": "distinct"}, count=len(labels))
    traces = []
    for index, label in enumerate(labels):
        x_values = [1, 2, 3, 4, 5]
        offset = index * 0.18
        y_values = [6.1 + offset, 6.18 + offset, 6.14 + offset, 6.28 + offset, 6.35 + offset]
        traces.append(
            {
                "type": "scatter",
                "mode": "markers",
                "name": label,
                "x": x_values,
                "y": y_values,
                "marker": {"color": palette[index % len(palette)], "size": 7},
                "hovertemplate": f"{label}<br>Sample=%{{x}}<br>Measurement=%{{y:.3f}}<extra></extra>",
            }
        )
    spec = {
        "data": traces,
        "layout": {
            "title": {"text": "Dashboard visual preview"},
            "font": {"family": str(theme.get("font_family") or 'Aptos, "Segoe UI", sans-serif')},
            "colorway": palette,
            "xaxis": {"title": {"text": "Sample"}},
            "yaxis": {"title": {"text": "Measurement"}},
            "legend": {"orientation": "h"},
            "paper_bgcolor": "#ffffff",
            "plot_bgcolor": "#ffffff",
        },
        "config": {"responsive": True, "displaylogo": False, "staticPlot": False},
        "metadata": {"kind": "scatter"},
    }
    if plotly_settings:
        apply_dashboard_visual_settings(spec, visual_settings=plotly_settings)
    return spec


def _resolved_palette(settings: Mapping[str, Any], *, count: int) -> list[str]:
    preset = settings["preset"]
    if preset == "print":
        return list(PRINT_DASHBOARD_PALETTE[:count])
    if preset == "distinct":
        return list(DEFAULT_DASHBOARD_PALETTE[:count])
    palette_mode = settings["palette_mode"]
    if palette_mode in {"auto_gradient", "highlight_gradient"}:
        return _gradient_palette(
            settings["anchor_color"],
            count=count,
            spread=settings["gradient_spread"],
            highlight=palette_mode == "highlight_gradient",
        )
    return _palette(settings.get("palette"), fallback=DEFAULT_DASHBOARD_PALETTE)[:count]


def _gradient_palette(
    anchor_color: str,
    *,
    count: int,
    spread: str,
    highlight: bool,
) -> list[str]:
    red, green, blue = _hex_to_rgb(_color(anchor_color, DEFAULT_HIGHLIGHT_ANCHOR))
    hue, lightness, saturation = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
    step = {"narrow": 0.035, "normal": 0.065, "wide": 0.105}.get(spread, 0.065)
    midpoint = (count - 1) / 2
    colors: list[str] = []
    for index in range(count):
        offset = (index - midpoint) * step
        local_hue = (hue + offset) % 1.0
        local_saturation = max(0.35, min(0.95, saturation * (0.95 if highlight else 1.05)))
        local_lightness = max(0.26, min(0.74, lightness + (index - midpoint) * 0.015))
        r_float, g_float, b_float = colorsys.hls_to_rgb(local_hue, local_lightness, local_saturation)
        colors.append(_rgb_to_hex(round(r_float * 255), round(g_float * 255), round(b_float * 255)))
    return colors


def _normalize_reference_style(value: Any, fallback: Mapping[str, Any]) -> dict[str, Any]:
    source = value if isinstance(value, Mapping) else {}
    return {
        "color": _color(source.get("color"), str(fallback["color"])),
        "dash": _dash(source.get("dash"), str(fallback["dash"])),
        "width": _bounded_float(source.get("width"), fallback=float(fallback["width"]), minimum=0.5, maximum=6.0),
    }


def _palette(value: Any, *, fallback: Sequence[str]) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return list(fallback)
    colors = [_color(item, "") for item in value]
    colors = [color for color in colors if color]
    return (colors + list(fallback))[: max(1, len(fallback))]


def _color(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if text.startswith("#") and len(text) in {4, 7}:
        try:
            _hex_to_rgb(text)
        except ValueError:
            return fallback
        return text.lower()
    return fallback


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    text = color.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    if len(text) != 6:
        raise ValueError(f"Invalid hex color: {color}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _rgb_to_hex(red: int, green: int, blue: int) -> str:
    return f"#{max(0, min(255, red)):02x}{max(0, min(255, green)):02x}{max(0, min(255, blue)):02x}"


def _choice(value: Any, allowed: Sequence[str], fallback: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in allowed else fallback


def _dash(value: Any, fallback: str) -> str:
    return _choice(value, ("solid", "dash", "dot", "dashdot", "longdash"), fallback)


def _bounded_float(value: Any, *, fallback: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(fallback)
    if not math.isfinite(number):
        number = float(fallback)
    return max(float(minimum), min(float(maximum), number))


def _preview_svg_png_fallback(settings: Any) -> bytes | None:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    image = Image.new("RGB", (520, 240), "white")
    draw = ImageDraw.Draw(image)
    palette = dashboard_visual_swatch_palette(settings, count=5)
    draw.text((24, 20), "Dashboard visual preview", fill="#1f2933")
    draw.line((24, 170, 480, 170), fill="#d8dde6", width=1)
    for index, color in enumerate(palette):
        x = 36 + index * 82
        height = 40 + index * 12
        draw.rounded_rectangle((x, 170 - height, x + 48, 170), radius=4, fill=color)
        draw.ellipse((x + 18, 70 + index * 12, x + 30, 82 + index * 12), fill=color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


__all__ = [
    "DASHBOARD_VISUAL_CHART_TYPES",
    "DASHBOARD_VISUAL_DISTINGUISH_MODES",
    "DASHBOARD_VISUAL_GRADIENT_SPREADS",
    "DASHBOARD_VISUAL_PALETTE_MODES",
    "DASHBOARD_VISUAL_PRESETS",
    "DEFAULT_DASHBOARD_PALETTE",
    "DEFAULT_HIGHLIGHT_ANCHOR",
    "build_dashboard_visual_preview_html",
    "build_dashboard_visual_preview_png",
    "build_dashboard_visual_preview_spec",
    "dashboard_visual_settings_summary",
    "dashboard_visual_settings_to_plotly_settings",
    "dashboard_visual_swatch_palette",
    "default_dashboard_visual_config_path",
    "default_dashboard_visual_settings",
    "load_dashboard_visual_settings",
    "normalize_dashboard_visual_settings",
    "save_dashboard_visual_settings",
    "temporary_dashboard_visual_preview_html",
]
