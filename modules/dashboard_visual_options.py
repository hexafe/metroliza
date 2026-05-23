"""Shared dashboard visual options and preview builders."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import colorsys
import copy
import re
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
DASHBOARD_VISUAL_THEME_LIBRARY_VERSION = 1

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
    "model_curve": 0.58,
}
_MARKER_SYMBOLS = ("circle", "diamond", "square", "cross", "x", "triangle-up")
_PATTERN_SHAPES = ("", "/", "\\", "x", ".", "-")
_REFERENCE_DEFAULTS = {
    "lsl": {
        "color": str(SUMMARY_PLOT_PALETTE["spec_limit"]).lower(),
        "dash": "dash",
        "width": 1.5,
        "opacity": 1.0,
    },
    "usl": {
        "color": str(SUMMARY_PLOT_PALETTE["spec_limit"]).lower(),
        "dash": "dash",
        "width": 1.5,
        "opacity": 1.0,
    },
    "nominal": {
        "color": str(SUMMARY_PLOT_PALETTE["central_tendency"]).lower(),
        "dash": "solid",
        "width": 1.5,
        "opacity": 1.0,
    },
}
_PALETTE_PRESETS: dict[str, dict[str, Any]] = {
    "metroliza": {
        "label": "Metroliza default",
        "kind": "categorical",
        "colors": DEFAULT_DASHBOARD_PALETTE,
        "note": "Existing dashboard colors.",
    },
    "okabe_ito": {
        "label": "Okabe-Ito",
        "kind": "categorical",
        "colors": (
            "#0072b2",
            "#d55e00",
            "#009e73",
            "#cc79a7",
            "#f0e442",
            "#56b4e9",
            "#e69f00",
            "#000000",
        ),
        "note": "Color-vision-deficiency friendly categorical palette.",
    },
    "tableau_10": {
        "label": "Tableau 10",
        "kind": "categorical",
        "colors": (
            "#4e79a7",
            "#f28e2b",
            "#e15759",
            "#76b7b2",
            "#59a14f",
            "#edc949",
            "#af7aa1",
            "#ff9da7",
            "#9c755f",
            "#bab0ab",
        ),
        "note": "General-purpose categorical dashboard palette.",
    },
    "colorbrewer_set2": {
        "label": "ColorBrewer Set2",
        "kind": "categorical",
        "colors": (
            "#66c2a5",
            "#fc8d62",
            "#8da0cb",
            "#e78ac3",
            "#a6d854",
            "#ffd92f",
            "#e5c494",
            "#b3b3b3",
        ),
        "note": "Soft qualitative palette.",
    },
    "colorbrewer_dark2": {
        "label": "ColorBrewer Dark2",
        "kind": "categorical",
        "colors": (
            "#1b9e77",
            "#d95f02",
            "#7570b3",
            "#e7298a",
            "#66a61e",
            "#e6ab02",
            "#a6761d",
            "#666666",
        ),
        "note": "Higher-contrast qualitative palette.",
    },
    "colorbrewer_paired": {
        "label": "ColorBrewer Paired",
        "kind": "categorical",
        "colors": (
            "#a6cee3",
            "#1f78b4",
            "#b2df8a",
            "#33a02c",
            "#fb9a99",
            "#e31a1c",
            "#fdbf6f",
            "#ff7f00",
            "#cab2d6",
            "#6a3d9a",
            "#ffff99",
            "#b15928",
        ),
        "note": "Paired categorical colors for related groups.",
    },
    "viridis": {
        "label": "Viridis",
        "kind": "sequential",
        "colors": ("#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"),
        "note": "Perceptually uniform sequential palette.",
    },
    "cividis": {
        "label": "Cividis",
        "kind": "sequential",
        "colors": ("#00204c", "#31446b", "#666970", "#958f78", "#c7b96e", "#ffea46"),
        "note": "Color-vision-deficiency optimized sequential palette.",
    },
    "plasma": {
        "label": "Plasma",
        "kind": "sequential",
        "colors": ("#0d0887", "#6a00a8", "#b12a90", "#e16462", "#fca636", "#f0f921"),
        "note": "High-energy perceptual sequential palette.",
    },
    "magma": {
        "label": "Magma",
        "kind": "sequential",
        "colors": ("#000004", "#3b0f70", "#8c2981", "#de4968", "#fe9f6d", "#fcfdbf"),
        "note": "Dark-to-light perceptual sequential palette.",
    },
    "rdbu": {
        "label": "RdBu",
        "kind": "diverging",
        "colors": ("#b2182b", "#ef8a62", "#fddbc7", "#d1e5f0", "#67a9cf", "#2166ac"),
        "note": "Blue-red diverging palette.",
    },
    "puor": {
        "label": "PuOr",
        "kind": "diverging",
        "colors": ("#b35806", "#f1a340", "#fee0b6", "#d8daeb", "#998ec3", "#542788"),
        "note": "Orange-purple diverging palette.",
    },
    "brbg": {
        "label": "BrBG",
        "kind": "diverging",
        "colors": ("#8c510a", "#d8b365", "#f6e8c3", "#c7eae5", "#5ab4ac", "#01665e"),
        "note": "Brown-teal diverging palette.",
    },
}
DASHBOARD_VISUAL_PALETTE_PRESET_IDS = tuple(_PALETTE_PRESETS.keys()) + ("custom",)
_PRESET_LABELS = {
    "auto": "Auto",
    "distinct": "Distinct groups",
    "print": "Print friendly",
    "custom": "Custom",
}
_GROUP_COUNT_SUFFIX_PATTERN = re.compile(r"\s*\(n\s*=\s*\d+\)\s*$", re.IGNORECASE)


def default_dashboard_visual_settings() -> dict[str, Any]:
    """Return the serializable default dashboard visual settings."""

    return {
        "theme_id": "",
        "theme_name": "",
        "preset": "auto",
        "palette_preset": "metroliza",
        "palette_mode": "fixed",
        "palette": list(DEFAULT_DASHBOARD_PALETTE),
        "anchor_color": DEFAULT_HIGHLIGHT_ANCHOR,
        "gradient_spread": "normal",
        "distinguish": "when_similar",
        "opacity": dict(DEFAULT_OPACITY),
        "marker_size": 7.0,
        "stat_lines": {"accent_by_stat": False, "width": 2.0},
        "series_overrides": {},
        "stat_line_overrides": {},
        "reference_lines": copy.deepcopy(_REFERENCE_DEFAULTS),
    }


def default_dashboard_visual_config_path() -> Path:
    """Return the shared user config path for dashboard visual settings."""

    return Path.home() / ".metroliza" / ".dashboard_visual_options.json"


def default_dashboard_visual_theme_library_path() -> Path:
    """Return the shared user config path for saved dashboard visual themes."""

    return Path.home() / ".metroliza" / ".dashboard_visual_themes.json"


def dashboard_visual_palette_presets() -> dict[str, dict[str, Any]]:
    """Return built-in palette preset metadata."""

    return copy.deepcopy(_PALETTE_PRESETS)


def default_dashboard_visual_theme_library() -> dict[str, Any]:
    """Return an empty normalized visual theme library."""

    return {
        "version": DASHBOARD_VISUAL_THEME_LIBRARY_VERSION,
        "default_theme_id": "",
        "themes": [],
    }


def load_dashboard_visual_theme_library(
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load saved visual themes, returning an empty library when unavailable."""

    path = (
        Path(config_path)
        if config_path is not None
        else default_dashboard_visual_theme_library_path()
    )
    if not path.exists():
        return default_dashboard_visual_theme_library()
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default_dashboard_visual_theme_library()
    return normalize_dashboard_visual_theme_library(payload)


def save_dashboard_visual_theme_library(
    library: Mapping[str, Any] | None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Persist and return a normalized visual theme library."""

    normalized = normalize_dashboard_visual_theme_library(library)
    path = (
        Path(config_path)
        if config_path is not None
        else default_dashboard_visual_theme_library_path()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(normalized, handle, indent=2, sort_keys=True)
    return normalized


def normalize_dashboard_visual_theme_library(value: Any) -> dict[str, Any]:
    """Normalize a saved theme library into a stable serializable shape."""

    defaults = default_dashboard_visual_theme_library()
    if not isinstance(value, Mapping):
        return defaults
    normalized = copy.deepcopy(defaults)
    normalized["version"] = DASHBOARD_VISUAL_THEME_LIBRARY_VERSION
    normalized["default_theme_id"] = _text(value.get("default_theme_id"), "")
    themes = value.get("themes")
    if not isinstance(themes, Sequence) or isinstance(themes, (str, bytes)):
        return normalized
    seen: set[str] = set()
    for index, theme in enumerate(themes, start=1):
        if not isinstance(theme, Mapping):
            continue
        settings = normalize_dashboard_visual_settings(theme.get("settings"))
        theme_id = _text(theme.get("id"), "") or _theme_id_from_name(
            _text(theme.get("name"), f"Theme {index}")
        )
        if not theme_id:
            theme_id = f"theme-{index}"
        base_id = theme_id
        suffix = 2
        while theme_id in seen:
            theme_id = f"{base_id}-{suffix}"
            suffix += 1
        seen.add(theme_id)
        name = _text(theme.get("name"), "") or _PRESET_LABELS.get(
            settings.get("preset"),
            "Dashboard theme",
        )
        settings["theme_id"] = theme_id
        settings["theme_name"] = name
        normalized["themes"].append(
            {
                "id": theme_id,
                "name": name,
                "settings": settings,
            }
        )
    if normalized["default_theme_id"] not in seen:
        normalized["default_theme_id"] = ""
    return normalized


def upsert_dashboard_visual_theme(
    library: Mapping[str, Any] | None,
    *,
    name: str,
    settings: Mapping[str, Any] | None,
    theme_id: str | None = None,
    set_default: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Insert or update a named theme in a normalized library."""

    normalized = normalize_dashboard_visual_theme_library(library)
    clean_name = _text(name, "Dashboard theme") or "Dashboard theme"
    clean_id = _text(theme_id, "") or _theme_id_from_name(clean_name)
    existing_ids = {
        str(theme["id"])
        for theme in normalized["themes"]
        if isinstance(theme, Mapping) and str(theme.get("id") or "") != clean_id
    }
    base_id = clean_id or "theme"
    suffix = 2
    while clean_id in existing_ids:
        clean_id = f"{base_id}-{suffix}"
        suffix += 1
    theme_settings = normalize_dashboard_visual_settings(settings)
    theme_settings["theme_id"] = clean_id
    theme_settings["theme_name"] = clean_name
    theme = {"id": clean_id, "name": clean_name, "settings": theme_settings}
    replaced = False
    for index, current in enumerate(normalized["themes"]):
        if isinstance(current, Mapping) and current.get("id") == clean_id:
            normalized["themes"][index] = theme
            replaced = True
            break
    if not replaced:
        normalized["themes"].append(theme)
    if set_default:
        normalized["default_theme_id"] = clean_id
    return normalized, theme


def remove_dashboard_visual_theme(
    library: Mapping[str, Any] | None,
    *,
    theme_id: str,
) -> dict[str, Any]:
    """Remove a named theme from a library."""

    normalized = normalize_dashboard_visual_theme_library(library)
    clean_id = _text(theme_id, "")
    normalized["themes"] = [
        theme
        for theme in normalized["themes"]
        if not (isinstance(theme, Mapping) and theme.get("id") == clean_id)
    ]
    if normalized["default_theme_id"] == clean_id:
        normalized["default_theme_id"] = ""
    return normalized


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
    normalized["theme_id"] = _text(settings.get("theme_id"), defaults["theme_id"])
    normalized["theme_name"] = _text(settings.get("theme_name"), defaults["theme_name"])
    normalized["preset"] = _choice(settings.get("preset"), DASHBOARD_VISUAL_PRESETS, defaults["preset"])
    palette_preset_fallback = defaults["palette_preset"]
    if "palette_preset" not in settings and "palette" in settings:
        palette_preset_fallback = "custom"
    normalized["palette_preset"] = _choice(
        settings.get("palette_preset"),
        DASHBOARD_VISUAL_PALETTE_PRESET_IDS,
        palette_preset_fallback,
    )
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
    normalized["series_overrides"] = _normalize_series_overrides(
        settings.get("series_overrides")
    )
    normalized["stat_line_overrides"] = _normalize_line_overrides(
        settings.get("stat_line_overrides")
    )
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
    palette_preset = normalized.get("palette_preset")
    if palette_preset and palette_preset != "custom":
        preset_meta = _PALETTE_PRESETS.get(str(palette_preset))
        if preset_meta:
            return f"Custom: {preset_meta['label']}"
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
            "overrides": copy.deepcopy(normalized["series_overrides"]),
        },
        "stat_lines": {
            **dict(normalized["stat_lines"]),
            "overrides": copy.deepcopy(normalized["stat_line_overrides"]),
        },
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


def build_dashboard_visual_preview_html(
    spec: Mapping[str, Any],
    *,
    enable_selection_bridge: bool = False,
) -> str:
    """Build a small standalone Plotly preview document for QWebEngine."""

    plotly_asset = Path(__file__).resolve().parent / "html_dashboard_assets" / "plotly-2.27.0.min.js"
    spec_json = json.dumps(spec, ensure_ascii=False)
    asset_uri = plotly_asset.resolve().as_uri()
    qwebchannel_script = ""
    if enable_selection_bridge:
        qwebchannel_script = "<script src='qrc:///qtwebchannel/qwebchannel.js'></script>"
    bridge_script = """
let metrolizaVisualBridge = null;
if (window.qt && window.QWebChannel && qt.webChannelTransport) {
  new QWebChannel(qt.webChannelTransport, (channel) => {
    metrolizaVisualBridge = channel.objects.metrolizaVisualBridge || null;
  });
}
const visualTargetForTrace = (trace, traceIndex) => {
  const meta = (trace && typeof trace.meta === 'object') ? trace.meta : {};
  const target = meta.metroliza_target_id || meta.dashboard_visual_target || '';
  if (target) {
    return {
      target,
      role: meta.metroliza_role || meta.dashboard_visual_role || 'series',
      label: meta.metroliza_legend_label || trace.name || target,
      trace: traceIndex,
    };
  }
  const name = String((trace && trace.name) || '').trim();
  const reference = name.split('=')[0].trim().toLowerCase();
  if (['lsl', 'usl', 'nominal'].includes(reference)) {
    return {target: `reference:${reference}`, role: 'reference', key: reference, label: name, trace: traceIndex};
  }
  const stat = name.match(/^(?:\\((.+?)\\)\\s*)?(Min|Q1|Median|Mean|Q3|Max)=/i);
  if (stat) {
    const group = stat[1] || '';
    const statName = stat[2].toLowerCase();
    return {target: `stat:${group}:${statName}`, role: 'stat', group, stat: statName, label: name, trace: traceIndex};
  }
  if (name) {
    return {target: `series:${name}`, role: 'series', label: name, trace: traceIndex};
  }
  return null;
};
const notifyVisualTarget = (payload) => {
  if (!payload || !metrolizaVisualBridge || typeof metrolizaVisualBridge.selectTarget !== 'function') return;
  metrolizaVisualBridge.selectTarget(JSON.stringify(payload));
};
"""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>html,body,#chart{height:100%;margin:0;background:#fff;}</style>"
        f"<script src='{asset_uri}'></script>{qwebchannel_script}</head><body><div id='chart'></div>"
        "<script>"
        f"const spec = {spec_json};"
        f"{bridge_script}"
        "const chart = document.getElementById('chart');"
        "Plotly.newPlot(chart, spec.data || [], spec.layout || {}, spec.config || {}).then(() => {"
        "chart.on('plotly_click', (eventData) => {"
        "const point = eventData && eventData.points && eventData.points[0];"
        "if (!point || typeof point.curveNumber !== 'number') return;"
        "notifyVisualTarget(visualTargetForTrace((spec.data || [])[point.curveNumber], point.curveNumber));"
        "});"
        "chart.on('plotly_legendclick', (eventData) => {"
        "const curveNumber = eventData && typeof eventData.curveNumber === 'number' ? eventData.curveNumber : -1;"
        "notifyVisualTarget(visualTargetForTrace((spec.data || [])[curveNumber], curveNumber));"
        "});"
        "});"
        "</script></body></html>"
    )


def build_dashboard_visual_preview_png(
    settings: Any,
    *,
    chart_type: str = "histogram",
) -> bytes | None:
    """Render a lightweight PNG preview that reflects the current visual settings."""

    chart_type = _choice(chart_type, DASHBOARD_VISUAL_CHART_TYPES, "histogram")
    spec = build_dashboard_visual_preview_spec(settings, chart_type=chart_type)
    image_bytes = _preview_plotly_spec_png(spec, chart_type=chart_type, settings=settings)
    if image_bytes:
        return image_bytes

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
    palette_mode = settings["palette_mode"]
    if palette_mode in {"auto_gradient", "highlight_gradient"}:
        preset_meta = _PALETTE_PRESETS.get(str(settings.get("palette_preset") or ""))
        if preset_meta and preset_meta.get("kind") in {"sequential", "diverging"}:
            return _expand_palette(preset_meta.get("colors"), count=count)
        return _gradient_palette(
            settings["anchor_color"],
            count=count,
            spread=settings["gradient_spread"],
            highlight=palette_mode == "highlight_gradient",
        )
    palette_preset = str(settings.get("palette_preset") or "metroliza")
    if palette_preset != "custom":
        preset_meta = _PALETTE_PRESETS.get(palette_preset)
        if preset_meta:
            return _expand_palette(preset_meta.get("colors"), count=count)
    if preset == "distinct":
        return list(DEFAULT_DASHBOARD_PALETTE[:count])
    return _palette(settings.get("palette"), fallback=DEFAULT_DASHBOARD_PALETTE)[:count]


def _expand_palette(value: Any, *, count: int) -> list[str]:
    colors = _palette(value, fallback=DEFAULT_DASHBOARD_PALETTE)
    if not colors:
        colors = list(DEFAULT_DASHBOARD_PALETTE)
    output: list[str] = []
    for index in range(max(1, int(count))):
        output.append(colors[index % len(colors)])
    return output


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
        "opacity": _bounded_float(
            source.get("opacity"),
            fallback=float(fallback.get("opacity", 1.0)),
            minimum=0.05,
            maximum=1.0,
        ),
    }


def _normalize_series_overrides(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_style in value.items():
        key = _text(raw_key, "")
        if not key or not isinstance(raw_style, Mapping):
            continue
        style: dict[str, Any] = {}
        color = _color(raw_style.get("color"), "")
        if color:
            style["color"] = color
        opacity = _optional_bounded_float(raw_style.get("opacity"), minimum=0.0, maximum=1.0)
        if opacity is not None:
            style["opacity"] = opacity
        marker_size = _optional_bounded_float(raw_style.get("marker_size"), minimum=2.0, maximum=18.0)
        if marker_size is not None:
            style["marker_size"] = marker_size
        marker_symbol = _choice(raw_style.get("marker_symbol"), _MARKER_SYMBOLS, "")
        if marker_symbol:
            style["marker_symbol"] = marker_symbol
        pattern_shape = _choice(raw_style.get("pattern_shape"), _PATTERN_SHAPES, "")
        if pattern_shape or raw_style.get("pattern_shape") == "":
            style["pattern_shape"] = pattern_shape
        outline_width = _optional_bounded_float(raw_style.get("outline_width"), minimum=0.0, maximum=6.0)
        if outline_width is not None:
            style["outline_width"] = outline_width
        outline_color = _color(raw_style.get("outline_color"), "")
        if outline_color:
            style["outline_color"] = outline_color
        line_width = _optional_bounded_float(raw_style.get("width"), minimum=0.5, maximum=8.0)
        if line_width is not None:
            style["width"] = line_width
        dash = _dash(raw_style.get("dash"), "")
        if dash:
            style["dash"] = dash
        if style:
            normalized[key] = style
    return normalized


def _normalize_line_overrides(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_style in value.items():
        key = _text(raw_key, "")
        if not key or not isinstance(raw_style, Mapping):
            continue
        style: dict[str, Any] = {}
        color = _color(raw_style.get("color"), "")
        if color:
            style["color"] = color
        dash = _dash(raw_style.get("dash"), "")
        if dash:
            style["dash"] = dash
        width = _optional_bounded_float(raw_style.get("width"), minimum=0.5, maximum=8.0)
        if width is not None:
            style["width"] = width
        opacity = _optional_bounded_float(raw_style.get("opacity"), minimum=0.0, maximum=1.0)
        if opacity is not None:
            style["opacity"] = opacity
        if style:
            normalized[key] = style
    return normalized


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


def _optional_bounded_float(value: Any, *, minimum: float, maximum: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return max(float(minimum), min(float(maximum), number))


def _text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _theme_id_from_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(name or "").casefold()).strip("-")
    return slug[:80]


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


def _preview_plotly_spec_png(
    spec: Mapping[str, Any] | None,
    *,
    chart_type: str,
    settings: Any = None,
) -> bytes | None:
    if not isinstance(spec, Mapping):
        return None
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    width = 640
    height = 380
    image = Image.new("RGBA", (width, height), "white")
    draw = ImageDraw.Draw(image)
    plot_left, plot_top, plot_right, plot_bottom = 58, 48, width - 28, height - 74
    draw.rectangle((plot_left, plot_top, plot_right, plot_bottom), fill="#fbfdff", outline="#d8dde6")
    for index in range(1, 5):
        y = plot_top + (plot_bottom - plot_top) * index / 5
        draw.line((plot_left, y, plot_right, y), fill="#e5e7eb", width=1)
    draw.text((24, 16), "Dashboard visual preview", fill="#1f2933")

    series = _preview_series_traces(spec)
    if not series:
        return None
    reference_traces = _preview_reference_traces_with_settings(
        _preview_reference_traces(spec),
        settings,
    )
    stat_traces = _preview_stat_traces(spec)
    line_domain_traces = [*series, *reference_traces, *stat_traces]
    if chart_type == "histogram":
        _draw_preview_histogram(draw, series, (plot_left, plot_top, plot_right, plot_bottom))
    elif chart_type == "iqr":
        _draw_preview_iqr(draw, series, (plot_left, plot_top, plot_right, plot_bottom))
    elif chart_type == "scatter":
        _draw_preview_scatter(draw, series, (plot_left, plot_top, plot_right, plot_bottom))
    else:
        _draw_preview_violins(draw, series, (plot_left, plot_top, plot_right, plot_bottom))
    _draw_preview_line_traces(
        draw,
        stat_traces,
        chart_type,
        (plot_left, plot_top, plot_right, plot_bottom),
        domain_traces=line_domain_traces,
    )
    _draw_preview_references(
        draw,
        reference_traces,
        chart_type,
        (plot_left, plot_top, plot_right, plot_bottom),
        domain_traces=line_domain_traces,
    )
    _draw_preview_legend(draw, series, (plot_left, plot_bottom + 20, plot_right, height - 16))

    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def _preview_series_traces(spec: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    traces = spec.get("data")
    if not isinstance(traces, Sequence) or isinstance(traces, (str, bytes)):
        return []
    series: list[Mapping[str, Any]] = []
    for trace in traces:
        if not isinstance(trace, Mapping):
            continue
        name = str(trace.get("name") or "").strip()
        if _preview_reference_key(name) or name.startswith("("):
            continue
        trace_type = str(trace.get("type") or "").strip().casefold()
        mode = str(trace.get("mode") or "").strip().casefold()
        if trace_type in {"histogram", "bar", "violin", "box"} or "markers" in mode:
            series.append(trace)
    return series[:6]


def _preview_reference_traces(spec: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    traces = spec.get("data")
    if not isinstance(traces, Sequence) or isinstance(traces, (str, bytes)):
        return []
    return [
        trace
        for trace in traces
        if isinstance(trace, Mapping) and _preview_reference_key(str(trace.get("name") or ""))
    ]


def _preview_reference_traces_with_settings(
    traces: Sequence[Mapping[str, Any]],
    settings: Any,
) -> list[Mapping[str, Any]]:
    """Return reference traces styled from the dashboard settings contract.

    The preview should show LSL/Nominal/USL styling even when the installed plot
    renderer does not emit reference-line traces for the sample payload.
    """

    normalized = normalize_dashboard_visual_settings(settings)
    reference_styles = normalized["reference_lines"]
    merged: dict[str, Mapping[str, Any]] = {}
    for trace in traces:
        key = _preview_reference_key(str(trace.get("name") or ""))
        if not key:
            continue
        trace_copy = dict(trace)
        line = dict(trace_copy.get("line") if isinstance(trace_copy.get("line"), Mapping) else {})
        line.update(reference_styles[key])
        trace_copy["line"] = line
        merged[key] = trace_copy

    for key in ("lsl", "nominal", "usl"):
        if key in merged:
            continue
        merged[key] = {
            "name": "Nominal" if key == "nominal" else key.upper(),
            "mode": "lines",
            "line": dict(reference_styles[key]),
        }
    return [merged[key] for key in ("lsl", "nominal", "usl")]


def _preview_stat_traces(spec: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    traces = spec.get("data")
    if not isinstance(traces, Sequence) or isinstance(traces, (str, bytes)):
        return []
    stat_traces: list[Mapping[str, Any]] = []
    for trace in traces:
        if not isinstance(trace, Mapping):
            continue
        meta = trace.get("meta") if isinstance(trace.get("meta"), Mapping) else {}
        if meta.get("dashboard_visual_role") != "stat":
            continue
        mode = str(trace.get("mode") or "").casefold()
        if "lines" in mode:
            stat_traces.append(trace)
    return stat_traces


def _preview_reference_key(name: str) -> str:
    key = str(name or "").split("=", 1)[0].strip().casefold()
    return key if key in {"lsl", "usl", "nominal"} else ""


def _preview_trace_color(trace: Mapping[str, Any], fallback: str = "#245a5a") -> str:
    marker = trace.get("marker") if isinstance(trace.get("marker"), Mapping) else {}
    line = trace.get("line") if isinstance(trace.get("line"), Mapping) else {}
    for value in (marker.get("color"), line.get("color"), trace.get("fillcolor")):
        if isinstance(value, str) and value.strip():
            return _color(value, fallback)
    return fallback


def _preview_trace_opacity(trace: Mapping[str, Any], fallback: float = 0.78) -> float:
    return _bounded_float(trace.get("opacity"), fallback=fallback, minimum=0.05, maximum=1.0)


def _preview_rgba(color: str, opacity: float) -> tuple[int, int, int, int]:
    red, green, blue = _hex_to_rgb(_color(color, "#245a5a"))
    return red, green, blue, round(max(0.05, min(1.0, opacity)) * 255)


def _draw_preview_histogram(
    draw: Any,
    traces: Sequence[Mapping[str, Any]],
    bounds: tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = bounds
    if not traces:
        return
    span = right - left
    group_width = span / max(1, len(traces))
    heights = [0.58, 0.70, 0.50, 0.82, 0.62, 0.74]
    for index, trace in enumerate(traces):
        color = _preview_rgba(_preview_trace_color(trace), _preview_trace_opacity(trace, 0.62))
        x0 = left + index * group_width + group_width * 0.18
        x1 = left + (index + 1) * group_width - group_width * 0.18
        bar_height = (bottom - top) * heights[index % len(heights)]
        y0 = bottom - bar_height
        draw.rounded_rectangle((x0, y0, x1, bottom), radius=5, fill=color, outline="#334155")
        pattern = _preview_trace_pattern(trace)
        if pattern:
            _draw_preview_pattern(draw, (x0, y0, x1, bottom), pattern)


def _draw_preview_violins(
    draw: Any,
    traces: Sequence[Mapping[str, Any]],
    bounds: tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = bounds
    if not traces:
        return
    span = right - left
    group_width = span / max(1, len(traces))
    for index, trace in enumerate(traces):
        color = _preview_rgba(_preview_trace_color(trace), _preview_trace_opacity(trace, 0.72))
        cx = left + group_width * (index + 0.5)
        half_width = group_width * 0.22
        y0 = top + 18 + (index % 2) * 12
        y1 = bottom - 14 - (index % 3) * 8
        mid = (y0 + y1) / 2
        points = [
            (cx, y0),
            (cx + half_width, mid - 48),
            (cx + half_width * 0.74, mid + 44),
            (cx, y1),
            (cx - half_width * 0.74, mid + 44),
            (cx - half_width, mid - 48),
        ]
        draw.polygon(points, fill=color, outline="#334155")
        draw.line((cx - half_width * 0.8, mid, cx + half_width * 0.8, mid), fill="#1f2933", width=2)


def _draw_preview_iqr(
    draw: Any,
    traces: Sequence[Mapping[str, Any]],
    bounds: tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = bounds
    if not traces:
        return
    span = right - left
    group_width = span / max(1, len(traces))
    for index, trace in enumerate(traces):
        color = _preview_rgba(_preview_trace_color(trace), _preview_trace_opacity(trace, 0.62))
        cx = left + group_width * (index + 0.5)
        box_width = group_width * 0.34
        q1 = top + 84 + (index % 2) * 10
        q3 = bottom - 76 - (index % 3) * 8
        whisker_top = max(top + 18, q1 - 42)
        whisker_bottom = min(bottom - 14, q3 + 42)
        draw.line((cx, whisker_top, cx, whisker_bottom), fill="#334155", width=2)
        draw.rectangle((cx - box_width, q1, cx + box_width, q3), fill=color, outline="#334155")
        draw.line((cx - box_width, (q1 + q3) / 2, cx + box_width, (q1 + q3) / 2), fill="#111827", width=2)


def _draw_preview_scatter(
    draw: Any,
    traces: Sequence[Mapping[str, Any]],
    bounds: tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = bounds
    if not traces:
        return
    point_count = 5
    for index, trace in enumerate(traces):
        color = _preview_rgba(_preview_trace_color(trace), _preview_trace_opacity(trace, 0.82))
        marker = trace.get("marker") if isinstance(trace.get("marker"), Mapping) else {}
        symbol = str(marker.get("symbol") or "circle")
        size = _bounded_float(marker.get("size"), fallback=7.0, minimum=2.0, maximum=18.0)
        for point_index in range(point_count):
            x = left + 34 + point_index * (right - left - 68) / max(1, point_count - 1)
            y = bottom - 34 - index * 31 - ((point_index % 2) * 12)
            _draw_preview_marker(draw, x, y, size + 2, color, symbol)


def _draw_preview_marker(
    draw: Any,
    x: float,
    y: float,
    size: float,
    color: tuple[int, int, int, int],
    symbol: str,
) -> None:
    half = size / 2
    normalized = str(symbol or "circle").casefold()
    if normalized == "square":
        draw.rectangle((x - half, y - half, x + half, y + half), fill=color, outline="#334155")
    elif normalized == "diamond":
        draw.polygon([(x, y - half), (x + half, y), (x, y + half), (x - half, y)], fill=color, outline="#334155")
    elif normalized in {"x", "cross"}:
        draw.line((x - half, y - half, x + half, y + half), fill=color, width=2)
        draw.line((x - half, y + half, x + half, y - half), fill=color, width=2)
        if normalized == "cross":
            draw.line((x - half, y, x + half, y), fill=color, width=2)
            draw.line((x, y - half, x, y + half), fill=color, width=2)
    elif normalized.startswith("triangle"):
        draw.polygon([(x, y - half), (x + half, y + half), (x - half, y + half)], fill=color, outline="#334155")
    else:
        draw.ellipse((x - half, y - half, x + half, y + half), fill=color, outline="#334155")


def _preview_trace_pattern(trace: Mapping[str, Any]) -> str:
    marker = trace.get("marker") if isinstance(trace.get("marker"), Mapping) else {}
    pattern = marker.get("pattern") if isinstance(marker.get("pattern"), Mapping) else {}
    return str(pattern.get("shape") or "")


def _draw_preview_pattern(
    draw: Any,
    rect: tuple[float, float, float, float],
    pattern: str,
) -> None:
    x0, y0, x1, y1 = rect
    pattern = str(pattern or "")
    if pattern in {"/", "\\", "x"}:
        spacing = 12
        start = int(x0 - (y1 - y0))
        end = int(x1 + (y1 - y0))
        for offset in range(start, end, spacing):
            if pattern in {"/", "x"}:
                segment = _clip_segment_to_rect(
                    offset,
                    y1,
                    offset + (y1 - y0),
                    y0,
                    (x0, y0, x1, y1),
                )
                if segment is not None:
                    draw.line(segment, fill="#0f172a", width=1)
            if pattern in {"\\", "x"}:
                segment = _clip_segment_to_rect(
                    offset,
                    y0,
                    offset + (y1 - y0),
                    y1,
                    (x0, y0, x1, y1),
                )
                if segment is not None:
                    draw.line(segment, fill="#0f172a", width=1)
    elif pattern in {".", "-"}:
        spacing = 10
        for y in range(int(y0) + spacing, int(y1), spacing):
            if pattern == "-":
                draw.line((x0 + 4, y, x1 - 4, y), fill="#0f172a", width=1)
            else:
                for x in range(int(x0) + spacing, int(x1), spacing):
                    draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill="#0f172a")


def _clip_segment_to_rect(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    rect: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    left, top, right, bottom = rect
    dx = x1 - x0
    dy = y1 - y0
    lower = 0.0
    upper = 1.0
    for edge, distance in (
        (-dx, x0 - left),
        (dx, right - x0),
        (-dy, y0 - top),
        (dy, bottom - y0),
    ):
        if edge == 0:
            if distance < 0:
                return None
            continue
        ratio = distance / edge
        if edge < 0:
            lower = max(lower, ratio)
        else:
            upper = min(upper, ratio)
        if lower > upper:
            return None
    return (
        x0 + lower * dx,
        y0 + lower * dy,
        x0 + upper * dx,
        y0 + upper * dy,
    )


def _draw_preview_references(
    draw: Any,
    reference_traces: Sequence[Mapping[str, Any]],
    chart_type: str,
    bounds: tuple[int, int, int, int],
    *,
    domain_traces: Sequence[Mapping[str, Any]] = (),
) -> None:
    _draw_preview_line_traces(
        draw,
        reference_traces[:3],
        chart_type,
        bounds,
        domain_traces=domain_traces,
        fallback_positions=(0.18, 0.50, 0.82),
    )


def _draw_preview_line_traces(
    draw: Any,
    traces: Sequence[Mapping[str, Any]],
    chart_type: str,
    bounds: tuple[int, int, int, int],
    *,
    domain_traces: Sequence[Mapping[str, Any]] = (),
    fallback_positions: Sequence[float] = (0.20, 0.35, 0.50, 0.65, 0.80),
) -> None:
    if not traces:
        return
    left, top, right, bottom = bounds
    axis = "x" if chart_type == "histogram" else "y"
    axis_range = _preview_numeric_range(domain_traces or traces, axis)
    for index, trace in enumerate(traces):
        line = trace.get("line") if isinstance(trace.get("line"), Mapping) else {}
        color = _preview_trace_color(trace, "#b45309")
        width = round(_bounded_float(line.get("width"), fallback=2.0, minimum=1.0, maximum=6.0))
        dash = str(line.get("dash") or "solid")
        value = _first_finite_number(trace.get(axis))
        if value is None or axis_range is None:
            position = fallback_positions[index % len(fallback_positions)]
        else:
            minimum, maximum = axis_range
            position = (value - minimum) / (maximum - minimum)
            position = max(0.02, min(0.98, position))
        if chart_type == "histogram":
            x = left + (right - left) * position
            _draw_preview_line(draw, (x, top + 4, x, bottom), fill=color, width=width, dash=dash)
        else:
            y = bottom - (bottom - top) * position
            _draw_preview_line(draw, (left, y, right, y), fill=color, width=width, dash=dash)


def _preview_numeric_range(
    traces: Sequence[Mapping[str, Any]],
    axis: str,
) -> tuple[float, float] | None:
    values: list[float] = []
    for trace in traces:
        raw_values = trace.get(axis)
        if isinstance(raw_values, Sequence) and not isinstance(raw_values, (str, bytes)):
            candidates = raw_values
        else:
            candidates = (raw_values,)
        for value in candidates:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                values.append(number)
    if not values:
        return None
    minimum = min(values)
    maximum = max(values)
    if math.isclose(minimum, maximum):
        padding = max(1.0, abs(minimum) * 0.05)
    else:
        padding = (maximum - minimum) * 0.05
    return minimum - padding, maximum + padding


def _first_finite_number(raw_values: Any) -> float | None:
    values = (
        raw_values
        if isinstance(raw_values, Sequence) and not isinstance(raw_values, (str, bytes))
        else (raw_values,)
    )
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def _draw_preview_line(
    draw: Any,
    xy: tuple[float, float, float, float],
    *,
    fill: str,
    width: int,
    dash: str,
) -> None:
    dash_key = str(dash or "solid").strip().casefold()
    pattern = {
        "dash": (12.0, 7.0),
        "dot": (2.5, 5.5),
        "dashdot": (12.0, 5.0, 2.5, 5.0),
        "longdash": (18.0, 7.0),
    }.get(dash_key)
    if not pattern:
        draw.line(xy, fill=fill, width=width)
        return

    x0, y0, x1, y1 = xy
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    if length <= 0:
        return
    ux = dx / length
    uy = dy / length
    distance = 0.0
    draw_segment = True
    pattern_index = 0
    while distance < length:
        segment_length = pattern[pattern_index % len(pattern)]
        next_distance = min(length, distance + segment_length)
        if draw_segment and next_distance > distance:
            draw.line(
                (
                    x0 + ux * distance,
                    y0 + uy * distance,
                    x0 + ux * next_distance,
                    y0 + uy * next_distance,
                ),
                fill=fill,
                width=width,
            )
        draw_segment = not draw_segment
        distance = next_distance
        pattern_index += 1


def _draw_preview_legend(
    draw: Any,
    traces: Sequence[Mapping[str, Any]],
    bounds: tuple[int, int, int, int],
) -> None:
    left, top, right, _bottom = bounds
    x = left
    y = top
    for trace in traces[:5]:
        name = _strip_preview_label(str(trace.get("name") or "Group"))
        color = _preview_rgba(_preview_trace_color(trace), 1.0)
        draw.rounded_rectangle((x, y, x + 16, y + 16), radius=3, fill=color, outline="#334155")
        draw.text((x + 22, y), name[:18], fill="#334155")
        x += min(112, max(74, 32 + len(name[:18]) * 6))
        if x > right - 92:
            x = left
            y += 20


def _strip_preview_label(label: str) -> str:
    return _GROUP_COUNT_SUFFIX_PATTERN.sub("", str(label or "")).strip() or "Group"


__all__ = [
    "DASHBOARD_VISUAL_CHART_TYPES",
    "DASHBOARD_VISUAL_DISTINGUISH_MODES",
    "DASHBOARD_VISUAL_GRADIENT_SPREADS",
    "DASHBOARD_VISUAL_PALETTE_MODES",
    "DASHBOARD_VISUAL_PALETTE_PRESET_IDS",
    "DASHBOARD_VISUAL_PRESETS",
    "DASHBOARD_VISUAL_THEME_LIBRARY_VERSION",
    "DEFAULT_DASHBOARD_PALETTE",
    "DEFAULT_HIGHLIGHT_ANCHOR",
    "build_dashboard_visual_preview_html",
    "build_dashboard_visual_preview_png",
    "build_dashboard_visual_preview_spec",
    "dashboard_visual_palette_presets",
    "dashboard_visual_settings_summary",
    "dashboard_visual_settings_to_plotly_settings",
    "dashboard_visual_swatch_palette",
    "default_dashboard_visual_config_path",
    "default_dashboard_visual_settings",
    "default_dashboard_visual_theme_library",
    "default_dashboard_visual_theme_library_path",
    "load_dashboard_visual_settings",
    "load_dashboard_visual_theme_library",
    "normalize_dashboard_visual_settings",
    "normalize_dashboard_visual_theme_library",
    "remove_dashboard_visual_theme",
    "save_dashboard_visual_settings",
    "save_dashboard_visual_theme_library",
    "temporary_dashboard_visual_preview_html",
    "upsert_dashboard_visual_theme",
]
