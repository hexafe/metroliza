"""Shared HTML controls and browser runtime helpers for Plotly dashboards."""

from __future__ import annotations

import html
import json

from modules.dashboard_visual_options import (
    DEFAULT_DASHBOARD_PALETTE,
    DEFAULT_HIGHLIGHT_ANCHOR,
    DEFAULT_OPACITY,
    PRINT_DASHBOARD_PALETTE,
    default_dashboard_visual_settings,
)


DASHBOARD_THEME_STORAGE_KEY = "metroliza-dashboard-theme"
DASHBOARD_VISUAL_STORAGE_KEY = "metroliza-dashboard-visuals"


def render_dashboard_theme_bootstrap_script() -> str:
    """Return early theme bootstrap JS used before CSS paints."""

    return f"""  <script>
    (() => {{
      const storageKey = {json.dumps(DASHBOARD_THEME_STORAGE_KEY)};
      const allowedChoices = new Set(['auto', 'light', 'dark']);
      let choice = 'auto';
      try {{
        const storedChoice = window.localStorage.getItem(storageKey) || 'auto';
        if (allowedChoices.has(storedChoice)) {{
          choice = storedChoice;
        }}
      }} catch (_error) {{
        choice = 'auto';
      }}
      const themeMedia = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
      const resolvedTheme = choice === 'auto'
        ? ((themeMedia && themeMedia.matches) ? 'dark' : 'light')
        : choice;
      document.documentElement.dataset.themeChoice = choice;
      document.documentElement.dataset.theme = resolvedTheme;
    }})();
  </script>"""


def render_dashboard_theme_switch() -> str:
    """Return compact Auto/Light/Dark dashboard theme controls."""

    options = (
        ("auto", "Auto"),
        ("light", "Light"),
        ("dark", "Dark"),
    )
    buttons = "".join(
        (
            f'<button type="button" class="theme-option" data-theme-choice="{choice}" '
            f'aria-pressed="false">{label}</button>'
        )
        for choice, label in options
    )
    return (
        '<div class="theme-switch" role="group" aria-label="Dashboard theme">'
        '<span class="theme-switch-label">Theme</span>'
        f'<div class="theme-options">{buttons}</div>'
        '</div>'
    )


def render_dashboard_control_bar(*, include_visuals: bool) -> str:
    """Return the top-level dashboard display controls."""

    visual_button = (
        '<button type="button" class="visual-settings-trigger" id="dashboard-visuals-open">'
        "Visuals</button>"
        if include_visuals
        else ""
    )
    return (
        '<div class="dashboard-control-bar">'
        f"{render_dashboard_theme_switch()}{visual_button}"
        "</div>"
    )


def render_dashboard_visual_dialog() -> str:
    """Return a compact visual settings dialog for saved Plotly dashboards."""

    palette_inputs = "".join(
        (
            '<label class="visual-swatch" '
            f'aria-label="Series color {index + 1}">'
            f'<input type="color" data-visual-palette-index="{index}" value="{html.escape(color)}">'
            "</label>"
        )
        for index, color in enumerate(DEFAULT_DASHBOARD_PALETTE[:6])
    )
    opacity_controls = (
        ("histogram", "Histogram"),
        ("grouped_histogram", "Grouped histogram"),
        ("distribution", "Violin"),
        ("iqr", "IQR"),
        ("scatter", "Scatter"),
        ("trend", "Trend"),
    )
    opacity_inputs = "".join(
        (
            '<label class="visual-field">'
            f"<span>{label}</span>"
            f'<input type="range" min="0.10" max="1" step="0.01" '
            f'data-visual-opacity="{key}" value="{DEFAULT_OPACITY[key]}">'
            "</label>"
        )
        for key, label in opacity_controls
    )
    return (
        '<dialog id="dashboard-visual-dialog" class="visual-dialog" aria-label="Plot visual settings">'
        '<form method="dialog" class="visual-panel">'
        '<div class="visual-panel-header">'
        '<div><h2>Plot Visuals</h2></div>'
        '<button type="button" class="visual-dialog-close" id="dashboard-visuals-close">Close</button>'
        '</div>'
        '<section class="visual-section">'
        '<div class="visual-segmented" role="group" aria-label="Visual preset">'
        '<button type="button" data-visual-preset="auto" aria-pressed="true">Auto</button>'
        '<button type="button" data-visual-preset="distinct" aria-pressed="false">Distinct</button>'
        '<button type="button" data-visual-preset="print" aria-pressed="false">Print</button>'
        '<button type="button" data-visual-preset="custom" aria-pressed="false">Custom</button>'
        '</div>'
        '</section>'
        '<section class="visual-section visual-grid">'
        '<label class="visual-field"><span>Palette</span>'
        '<select id="dashboard-visual-palette-mode">'
        '<option value="fixed">Fixed</option>'
        '<option value="auto_gradient">Auto gradient</option>'
        '<option value="highlight_gradient">Highlight gradient</option>'
        '</select></label>'
        '<label class="visual-field"><span>Anchor</span>'
        f'<input type="color" id="dashboard-visual-anchor" value="{DEFAULT_HIGHLIGHT_ANCHOR}"></label>'
        '<label class="visual-field"><span>Spread</span>'
        '<select id="dashboard-visual-gradient-spread">'
        '<option value="narrow">Narrow</option>'
        '<option value="normal">Normal</option>'
        '<option value="wide">Wide</option>'
        '</select></label>'
        '<label class="visual-field"><span>Markers</span>'
        '<select id="dashboard-visual-distinguish">'
        '<option value="color_only">Color only</option>'
        '<option value="when_similar">When similar</option>'
        '<option value="always">Always</option>'
        '</select></label>'
        '</section>'
        f'<section class="visual-section visual-swatches">{palette_inputs}</section>'
        '<section class="visual-section visual-grid">'
        '<label class="visual-field"><span>Marker size</span>'
        '<input type="range" min="2" max="18" step="0.5" id="dashboard-visual-marker-size" value="7"></label>'
        '<label class="visual-field"><span>Stat width</span>'
        '<input type="range" min="0.5" max="6" step="0.25" id="dashboard-visual-stat-width" value="2"></label>'
        '<label class="visual-field visual-check"><input type="checkbox" id="dashboard-visual-stat-accent">'
        '<span>Stat accents</span></label>'
        '</section>'
        f'<section class="visual-section visual-grid">{opacity_inputs}</section>'
        '<section class="visual-section visual-actions">'
        '<button type="button" id="dashboard-visual-reset">Reset</button>'
        '<button type="button" id="dashboard-visual-apply">Apply</button>'
        '</section>'
        '</form>'
        '</dialog>'
    )


def render_dashboard_controls_css() -> str:
    """Return CSS shared by the theme switch and visual settings dialog."""

    return """
    .dashboard-control-bar {
      display: inline-flex;
      align-items: center;
      justify-content: flex-end;
      gap: 10px;
      flex-wrap: wrap;
    }
    .theme-switch {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .theme-options {
      display: inline-flex;
      gap: 4px;
      padding: 4px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--detail-panel-bg, rgba(22, 35, 48, 0.04));
    }
    .theme-option {
      appearance: none;
      border: 1px solid transparent;
      background: transparent;
      color: var(--muted);
      border-radius: 999px;
      padding: 7px 10px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      text-transform: none;
      letter-spacing: 0;
    }
    .theme-option[data-active="1"] {
      color: var(--ink, var(--text));
      background: var(--accent-soft, rgba(23, 105, 170, 0.12));
      border-color: var(--accent-border, var(--line));
    }
    .visual-settings-trigger,
    .visual-dialog-close,
    .visual-actions button {
      appearance: none;
      border: 1px solid var(--line);
      background: var(--panel-strong, var(--panel));
      color: var(--ink, var(--text));
      border-radius: 999px;
      padding: 10px 13px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
    }
    .visual-settings-trigger:hover,
    .visual-dialog-close:hover,
    .visual-actions button:hover {
      border-color: var(--accent);
      color: var(--accent);
    }
    .visual-settings-trigger:focus-visible,
    .theme-option:focus-visible,
    .visual-dialog-close:focus-visible,
    .visual-actions button:focus-visible,
    .visual-segmented button:focus-visible,
    .visual-field input:focus-visible,
    .visual-field select:focus-visible {
      outline: 3px solid var(--focus-ring, rgba(214, 110, 47, 0.45));
      outline-offset: 2px;
    }
    .visual-dialog {
      width: min(94vw, 760px);
      border: 0;
      border-radius: 12px;
      padding: 0;
      background: transparent;
      color: var(--ink, var(--text));
    }
    .visual-dialog::backdrop {
      background: var(--overlay-bg, rgba(15, 23, 42, 0.74));
    }
    .visual-panel {
      background: var(--panel-strong, var(--panel));
      border: 1px solid var(--line);
      border-radius: 12px;
      box-shadow: var(--shadow, 0 20px 52px rgba(0, 0, 0, 0.24));
      padding: 16px;
    }
    .visual-panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }
    .visual-panel h2 {
      margin: 0;
      font-size: 18px;
      line-height: 1.2;
    }
    .visual-section {
      border-top: 1px solid var(--line);
      padding-top: 12px;
      margin-top: 12px;
    }
    .visual-segmented {
      display: inline-flex;
      flex-wrap: wrap;
      gap: 6px;
      padding: 4px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--detail-panel-bg, rgba(22, 35, 48, 0.04));
    }
    .visual-segmented button {
      appearance: none;
      border: 1px solid transparent;
      background: transparent;
      color: var(--muted);
      border-radius: 999px;
      padding: 8px 11px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
    }
    .visual-segmented button[data-active="1"] {
      color: var(--ink, var(--text));
      background: var(--accent-soft, rgba(23, 105, 170, 0.12));
      border-color: var(--accent-border, var(--line));
    }
    .visual-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
    }
    .visual-field {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .visual-field select,
    .visual-field input[type="range"],
    .visual-field input[type="color"] {
      min-height: 34px;
      width: 100%;
    }
    .visual-field select {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel, #ffffff);
      color: var(--ink, var(--text));
      padding: 6px 8px;
      text-transform: none;
      letter-spacing: 0;
      font-weight: 600;
    }
    .visual-check {
      display: flex;
      align-items: center;
      gap: 8px;
      align-self: end;
      min-height: 34px;
    }
    .visual-check input {
      width: 18px;
      height: 18px;
    }
    .visual-swatches {
      display: grid;
      grid-template-columns: repeat(6, minmax(42px, 1fr));
      gap: 8px;
    }
    .visual-swatch input {
      width: 100%;
      height: 36px;
      padding: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: transparent;
      cursor: pointer;
    }
    .visual-actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
    }
    @media (max-width: 780px) {
      .dashboard-control-bar { width: 100%; justify-content: space-between; }
      .visual-dialog { width: min(100vw - 20px, 760px); }
      .visual-swatches { grid-template-columns: repeat(3, minmax(42px, 1fr)); }
    }
    """


def dashboard_visual_runtime_config_json() -> str:
    """Return shared defaults as compact JSON for browser runtime."""

    return json.dumps(
        {
            "storageKey": DASHBOARD_VISUAL_STORAGE_KEY,
            "defaults": default_dashboard_visual_settings(),
            "defaultPalette": list(DEFAULT_DASHBOARD_PALETTE),
            "printPalette": list(PRINT_DASHBOARD_PALETTE),
            "markerSymbols": ["circle", "diamond", "square", "cross", "x", "triangle-up"],
            "patterns": ["", "/", "\\", "x", ".", "-"],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def render_dashboard_visual_runtime_js(config_var: str = "dashboardVisualConfig") -> str:
    """Return browser functions for applying dashboard visual settings to Plotly specs."""

    return f"""
      const {config_var} = {dashboard_visual_runtime_config_json()};
      const visualStorageKey = {config_var}.storageKey;
      let dashboardVisualState = null;
      let visualRefreshTimer = 0;

      const visualChoice = (value, allowed, fallback) => (
        allowed.includes(value) ? value : fallback
      );

      const clonePlotlySpec = (spec) => JSON.parse(JSON.stringify(spec || {{}}));

      const normalizeColor = (value, fallback) => (
        typeof value === 'string' && /^#[0-9a-f]{{6}}$/i.test(value.trim())
          ? value.trim().toLowerCase()
          : fallback
      );

      const boundedNumber = (value, fallback, minimum, maximum) => {{
        const number = Number(value);
        if (!Number.isFinite(number)) {{
          return fallback;
        }}
        return Math.min(maximum, Math.max(minimum, number));
      }};

      const sanitizeVisualState = (value) => {{
        const defaults = clonePlotlySpec({config_var}.defaults);
        const source = (value && typeof value === 'object') ? value : {{}};
        const state = Object.assign(defaults, source);
        state.preset = visualChoice(state.preset, ['auto', 'distinct', 'print', 'custom'], defaults.preset);
        state.palette_mode = visualChoice(
          state.palette_mode,
          ['fixed', 'auto_gradient', 'highlight_gradient'],
          defaults.palette_mode
        );
        state.gradient_spread = visualChoice(
          state.gradient_spread,
          ['narrow', 'normal', 'wide'],
          defaults.gradient_spread
        );
        state.distinguish = visualChoice(
          state.distinguish,
          ['color_only', 'when_similar', 'always'],
          defaults.distinguish
        );
        state.anchor_color = normalizeColor(state.anchor_color, defaults.anchor_color);
        const palette = Array.isArray(state.palette) ? state.palette : defaults.palette;
        state.palette = palette.slice(0, 6).map((color, index) => (
          normalizeColor(color, defaults.palette[index] || '#245a5a')
        ));
        while (state.palette.length < 6) {{
          state.palette.push(defaults.palette[state.palette.length] || '#245a5a');
        }}
        state.opacity = Object.assign({{}}, defaults.opacity, state.opacity || {{}});
        Object.keys(defaults.opacity).forEach((key) => {{
          state.opacity[key] = boundedNumber(state.opacity[key], defaults.opacity[key], 0.05, 1);
        }});
        state.marker_size = boundedNumber(state.marker_size, defaults.marker_size, 2, 18);
        state.stat_lines = Object.assign({{}}, defaults.stat_lines, state.stat_lines || {{}});
        state.stat_lines.width = boundedNumber(state.stat_lines.width, defaults.stat_lines.width, 0.5, 6);
        state.stat_lines.accent_by_stat = Boolean(state.stat_lines.accent_by_stat);
        state.reference_lines = Object.assign({{}}, defaults.reference_lines, state.reference_lines || {{}});
        ['lsl', 'usl', 'nominal'].forEach((key) => {{
          state.reference_lines[key] = Object.assign(
            {{}},
            defaults.reference_lines[key],
            state.reference_lines[key] || {{}}
          );
          state.reference_lines[key].color = normalizeColor(
            state.reference_lines[key].color,
            defaults.reference_lines[key].color
          );
          state.reference_lines[key].width = boundedNumber(
            state.reference_lines[key].width,
            defaults.reference_lines[key].width,
            0.5,
            6
          );
        }});
        return state;
      }};

      const readStoredVisualState = () => {{
        try {{
          const raw = window.localStorage.getItem(visualStorageKey);
          return sanitizeVisualState(raw ? JSON.parse(raw) : null);
        }} catch (_error) {{
          return sanitizeVisualState(null);
        }}
      }};

      const persistVisualState = (state) => {{
        try {{
          window.localStorage.setItem(visualStorageKey, JSON.stringify(state));
        }} catch (_error) {{
          // Ignore storage failures in locked-down browser contexts.
        }}
      }};

      const hexToRgb = (value) => {{
        const color = normalizeColor(value, '#245a5a').slice(1);
        return [
          parseInt(color.slice(0, 2), 16),
          parseInt(color.slice(2, 4), 16),
          parseInt(color.slice(4, 6), 16),
        ];
      }};

      const rgbToHex = (red, green, blue) => (
        '#' + [red, green, blue].map((value) => {{
          const normalized = Math.max(0, Math.min(255, Math.round(value)));
          return normalized.toString(16).padStart(2, '0');
        }}).join('')
      );

      const rgbToHsl = (red, green, blue) => {{
        red /= 255; green /= 255; blue /= 255;
        const max = Math.max(red, green, blue);
        const min = Math.min(red, green, blue);
        let hue = 0;
        let saturation = 0;
        const lightness = (max + min) / 2;
        if (max !== min) {{
          const delta = max - min;
          saturation = lightness > 0.5 ? delta / (2 - max - min) : delta / (max + min);
          if (max === red) hue = (green - blue) / delta + (green < blue ? 6 : 0);
          else if (max === green) hue = (blue - red) / delta + 2;
          else hue = (red - green) / delta + 4;
          hue /= 6;
        }}
        return [hue, saturation, lightness];
      }};

      const hslToRgb = (hue, saturation, lightness) => {{
        if (saturation === 0) {{
          const gray = lightness * 255;
          return [gray, gray, gray];
        }}
        const hueToRgb = (p, q, t) => {{
          if (t < 0) t += 1;
          if (t > 1) t -= 1;
          if (t < 1 / 6) return p + (q - p) * 6 * t;
          if (t < 1 / 2) return q;
          if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
          return p;
        }};
        const q = lightness < 0.5
          ? lightness * (1 + saturation)
          : lightness + saturation - lightness * saturation;
        const p = 2 * lightness - q;
        return [
          hueToRgb(p, q, hue + 1 / 3) * 255,
          hueToRgb(p, q, hue) * 255,
          hueToRgb(p, q, hue - 1 / 3) * 255,
        ];
      }};

      const gradientPalette = (anchorColor, count, spread, highlight) => {{
        const [red, green, blue] = hexToRgb(anchorColor);
        const [hue, saturation, lightness] = rgbToHsl(red, green, blue);
        const step = ({{ narrow: 0.035, normal: 0.065, wide: 0.105 }})[spread] || 0.065;
        const midpoint = (count - 1) / 2;
        const colors = [];
        for (let index = 0; index < count; index += 1) {{
          const offset = (index - midpoint) * step;
          const localHue = (hue + offset + 1) % 1;
          const localSaturation = Math.max(0.35, Math.min(0.95, saturation * (highlight ? 0.95 : 1.05)));
          const localLightness = Math.max(0.26, Math.min(0.74, lightness + (index - midpoint) * 0.015));
          colors.push(rgbToHex(...hslToRgb(localHue, localSaturation, localLightness)));
        }}
        return colors;
      }};

      const resolvedVisualPalette = (state, count = 6) => {{
        if (state.preset === 'print') {{
          return {config_var}.printPalette.slice(0, count);
        }}
        if (state.preset === 'distinct') {{
          return {config_var}.defaultPalette.slice(0, count);
        }}
        if (state.palette_mode === 'auto_gradient' || state.palette_mode === 'highlight_gradient') {{
          return gradientPalette(
            state.anchor_color,
            count,
            state.gradient_spread,
            state.palette_mode === 'highlight_gradient'
          );
        }}
        return state.palette.slice(0, count);
      }};

      const lowLevelVisualSettings = (state) => {{
        if (!state || state.preset === 'auto') {{
          return {{}};
        }}
        const useDistinguishers = state.distinguish !== 'color_only' || state.preset === 'print';
        return {{
          preserve_colors_on_theme: true,
          series: {{
            palette: resolvedVisualPalette(state, 6),
            opacity: Object.assign({{}}, state.opacity),
            marker_size: state.marker_size,
            marker_symbols: useDistinguishers ? {config_var}.markerSymbols.slice() : [],
            patterns: useDistinguishers ? {config_var}.patterns.slice() : [],
            auto_distinguish: state.distinguish === 'when_similar',
            always_distinguish: state.distinguish === 'always' || state.preset === 'print',
          }},
          stat_lines: Object.assign({{}}, state.stat_lines),
          reference_lines: clonePlotlySpec(state.reference_lines),
        }};
      }};

      const stripGroupCount = (label) => String(label || '').replace(/\\s*\\(n\\s*=\\s*\\d+\\)\\s*$/i, '').trim();
      const isReferenceName = (name) => ['lsl', 'usl', 'nominal'].includes(String(name || '').split('=')[0].trim().toLowerCase());
      const groupStatMatch = (name) => {{
        const match = String(name || '').trim().match(/^(?:\\((.+?)\\)\\s*)?(Min|Q1|Median|Mean|Q3|Max)=/i);
        if (!match) return null;
        return {{ group: match[1] ? stripGroupCount(match[1]) : '', stat: match[2] }};
      }};
      const traceLooksLikeTrend = (trace) => {{
        if (!trace || typeof trace !== 'object') return false;
        const name = String(trace.name || '').trim().toLowerCase();
        const mode = String(trace.mode || '').toLowerCase();
        return name === 'trend' && mode.includes('lines') && !isReferenceName(name);
      }};
      const chartKindForTrace = (trace, chartKind) => {{
        if (traceLooksLikeTrend(trace)) return 'trend';
        if (chartKind === 'trend' && traceHasMarkers(trace)) return 'scatter';
        return chartKind;
      }};

      const chartKindForSpec = (spec) => {{
        const metadata = (spec.metadata && typeof spec.metadata === 'object') ? spec.metadata : {{}};
        const kind = String(metadata.kind || '').toLowerCase();
        if (kind) return kind;
        const traces = Array.isArray(spec.data) ? spec.data : [];
        const histogramCount = traces.filter((trace) => ['histogram', 'bar'].includes(String(trace.type || '').toLowerCase())).length;
        if (histogramCount > 1) return 'grouped_histogram';
        if (histogramCount === 1) return 'histogram';
        if (traces.some((trace) => String(trace.type || '').toLowerCase() === 'violin')) return 'distribution';
        if (traces.some((trace) => String(trace.type || '').toLowerCase() === 'box')) return 'iqr';
        if (traces.some((trace) => traceLooksLikeTrend(trace))) return 'trend';
        if (traces.some((trace) => String(trace.mode || '').toLowerCase().includes('markers'))) return 'scatter';
        return 'default';
      }};

      const seriesLabelsForSpec = (spec) => {{
        const labels = [];
        const seen = new Set();
        const traces = Array.isArray(spec.data) ? spec.data : [];
        traces.forEach((trace) => {{
          if (!trace || typeof trace !== 'object') return;
          const name = String(trace.name || '').trim();
          if (!name || isReferenceName(name) || groupStatMatch(name)) return;
          const type = String(trace.type || '').toLowerCase();
          const mode = String(trace.mode || '').toLowerCase();
          if (!['bar', 'histogram', 'box', 'violin'].includes(type) && !mode.includes('markers')) return;
          const label = stripGroupCount(name);
          if (label && !seen.has(label)) {{
            seen.add(label);
            labels.push(label);
          }}
        }});
        return labels;
      }};

      const traceColor = (trace) => {{
        if (trace.marker && typeof trace.marker.color === 'string') return trace.marker.color;
        if (trace.line && typeof trace.line.color === 'string') return trace.line.color;
        if (typeof trace.fillcolor === 'string') return trace.fillcolor;
        return null;
      }};

      const setTraceColor = (trace, color) => {{
        trace.marker = Object.assign({{}}, trace.marker || {{}}, {{ color }});
        trace.line = Object.assign({{}}, trace.line || {{}}, {{ color }});
        const type = String(trace.type || '').toLowerCase();
        if (['violin', 'box', 'scatter'].includes(type)) {{
          trace.fillcolor = color;
        }}
      }};

      const traceHasMarkers = (trace) => String(trace.mode || '').toLowerCase().includes('markers');

      const setTrendTraceColor = (trace, color) => {{
        trace.line = Object.assign({{}}, trace.line || {{}}, {{ color }});
      }};

      const traceVisibilityState = (trace) => {{
        if (!trace || typeof trace !== 'object') {{
          return {{ hasVisible: false, value: undefined }};
        }}
        return Object.prototype.hasOwnProperty.call(trace, 'visible')
          ? {{ hasVisible: true, value: trace.visible }}
          : {{ hasVisible: false, value: undefined }};
      }};

      const traceIsHidden = (trace) => {{
        const visibility = traceVisibilityState(trace);
        return visibility.hasVisible && (visibility.value === 'legendonly' || visibility.value === false);
      }};

      const preservePlotlyTraceVisibility = (container, nextData) => {{
        const node = typeof container === 'string' ? document.getElementById(container) : container;
        const currentData = node && Array.isArray(node.data) ? node.data : [];
        if (!Array.isArray(nextData) || !currentData.length) {{
          return nextData;
        }}
        const allCurrentTracesHidden = currentData.every((trace) => traceIsHidden(trace));
        nextData.forEach((trace, index) => {{
          if (!trace || typeof trace !== 'object') return;
          const visibility = traceVisibilityState(currentData[index]);
          if (visibility.hasVisible) {{
            trace.visible = visibility.value;
          }} else if (allCurrentTracesHidden) {{
            trace.visible = 'legendonly';
          }} else if (!allCurrentTracesHidden && Object.prototype.hasOwnProperty.call(trace, 'visible')) {{
            delete trace.visible;
          }}
        }});
        return nextData;
      }};

      let plotlyVisibilityPatchAttempts = 0;
      const installPlotlyVisibilityReactPatch = () => {{
        if (!window.Plotly || typeof window.Plotly.react !== 'function') {{
          return false;
        }}
        if (window.Plotly.react.__metrolizaPreservesTraceVisibility) {{
          return true;
        }}
        const originalReact = window.Plotly.react.bind(window.Plotly);
        const patchedReact = (container, data, layout, config) => {{
          preservePlotlyTraceVisibility(container, data);
          return originalReact(container, data, layout, config);
        }};
        patchedReact.__metrolizaPreservesTraceVisibility = true;
        window.Plotly.react = patchedReact;
        return true;
      }};

      const ensurePlotlyVisibilityReactPatch = () => {{
        if (installPlotlyVisibilityReactPatch()) {{
          return;
        }}
        if (plotlyVisibilityPatchAttempts >= 40) {{
          return;
        }}
        plotlyVisibilityPatchAttempts += 1;
        window.setTimeout(ensurePlotlyVisibilityReactPatch, 250);
      }};
      ensurePlotlyVisibilityReactPatch();

      const paletteHasSimilarColors = (palette) => {{
        if (!Array.isArray(palette) || palette.length < 2) return false;
        for (let index = 1; index < palette.length; index += 1) {{
          const a = hexToRgb(palette[index - 1]);
          const b = hexToRgb(palette[index]);
          const distance = Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
          if (distance < 42) return true;
        }}
        return false;
      }};

      const accentColor = (color, statLabel) => {{
        const factors = {{ min: 0.78, q1: 0.90, median: 1.0, mean: 1.14, q3: 1.24, max: 1.36 }};
        const [red, green, blue] = hexToRgb(color);
        const [hue, saturation, lightness] = rgbToHsl(red, green, blue);
        const factor = factors[String(statLabel || '').toLowerCase()] || 1;
        return rgbToHex(...hslToRgb(hue, saturation, Math.max(0.18, Math.min(0.82, lightness * factor))));
      }};

      const applyDashboardVisualsToPlotlySpec = (spec, state = dashboardVisualState) => {{
        const settings = lowLevelVisualSettings(state);
        if (!settings || Object.keys(settings).length === 0 || !spec || typeof spec !== 'object') {{
          return spec;
        }}
        const series = settings.series || {{}};
        const palette = Array.isArray(series.palette) ? series.palette : [];
        const labels = seriesLabelsForSpec(spec);
        const chartKind = chartKindForSpec(spec);
        const markerSymbols = Array.isArray(series.marker_symbols) ? series.marker_symbols : [];
        const patterns = Array.isArray(series.patterns) ? series.patterns : [];
        const useDistinguishers = Boolean(series.always_distinguish)
          || (Boolean(series.auto_distinguish) && paletteHasSimilarColors(palette));

        spec.layout = (spec.layout && typeof spec.layout === 'object') ? spec.layout : {{}};
        if (palette.length) {{
          spec.layout.colorway = palette.slice();
          spec.layout.meta = Object.assign({{}}, spec.layout.meta || {{}}, {{
            dashboard_visual_preserve_colorway: true,
          }});
        }}

        const traces = Array.isArray(spec.data) ? spec.data : [];
        traces.forEach((trace, traceIndex) => {{
          if (!trace || typeof trace !== 'object') return;
          const name = String(trace.name || '');
          const stat = groupStatMatch(name);
          if (stat) {{
            const groupLabel = stat.group || (labels.length === 1 ? labels[0] : '');
            let color = traceColor(trace);
            if (groupLabel) {{
              const groupIndex = labels.indexOf(groupLabel);
              const labelIndex = groupIndex >= 0 ? groupIndex : traceIndex;
              color = palette[labelIndex % Math.max(1, palette.length)] || color;
            }}
            if (color && settings.stat_lines && settings.stat_lines.accent_by_stat) {{
              color = accentColor(color, stat.stat);
            }}
            trace.line = Object.assign({{}}, trace.line || {{}});
            if (color) trace.line.color = color;
            if (settings.stat_lines && Number.isFinite(Number(settings.stat_lines.width))) {{
              trace.line.width = Math.max(0, Number(settings.stat_lines.width));
            }}
            trace.meta = Object.assign({{}}, trace.meta || {{}}, {{
              dashboard_visual_role: 'stat',
              dashboard_visual_preserve_color: Boolean(color),
            }});
            return;
          }}

          const referenceKey = String(name.split('=')[0] || '').trim().toLowerCase();
          if (['lsl', 'usl', 'nominal'].includes(referenceKey)) {{
            const reference = (settings.reference_lines || {{}})[referenceKey] || {{}};
            trace.line = Object.assign({{}}, trace.line || {{}});
            if (reference.color) trace.line.color = reference.color;
            if (reference.dash) trace.line.dash = reference.dash;
            if (Number.isFinite(Number(reference.width))) trace.line.width = Math.max(0, Number(reference.width));
            return;
          }}

          const traceChartKind = chartKindForTrace(trace, chartKind);
          const opacity = series.opacity && Object.prototype.hasOwnProperty.call(series.opacity, traceChartKind)
            ? Number(series.opacity[traceChartKind])
            : Number(series.opacity && series.opacity.default);
          const isTrendLine = traceChartKind === 'trend' && traceLooksLikeTrend(trace);
          const rawLabel = stripGroupCount(name);
          let label = labels.includes(rawLabel) ? rawLabel : null;
          if (!label && labels.length === 1 && ['Frequency', 'Histogram', 'Measurements', ''].includes(name)) {{
            label = labels[0];
          }}
          if (!label && isTrendLine) {{
            label = 'Trend';
          }}
          if (!label && !labels.length && rawLabel) {{
            label = rawLabel;
          }}
          if (!label) return;

          const rawLabelIndex = labels.indexOf(label);
          const labelIndex = rawLabelIndex >= 0 ? rawLabelIndex : traceIndex;
          const color = palette[labelIndex % Math.max(1, palette.length)] || traceColor(trace);
          if (color) {{
            if (isTrendLine) setTrendTraceColor(trace, color);
            else setTraceColor(trace, color);
          }}
          if (Number.isFinite(opacity)) {{
            trace.opacity = Math.max(0, Math.min(1, opacity));
          }}
          if (!isTrendLine) {{
            trace.marker = Object.assign({{}}, trace.marker || {{}});
            if (traceHasMarkers(trace) && Number.isFinite(Number(series.marker_size))) {{
              trace.marker.size = Number(series.marker_size);
            }}
            if (traceHasMarkers(trace) && useDistinguishers && markerSymbols.length) {{
              trace.marker.symbol = markerSymbols[labelIndex % markerSymbols.length];
            }}
            if (['bar', 'histogram'].includes(String(trace.type || '').toLowerCase()) && useDistinguishers && patterns.length) {{
              trace.marker.pattern = Object.assign({{}}, trace.marker.pattern || {{}}, {{
                shape: patterns[labelIndex % patterns.length],
              }});
            }}
          }}
          trace.meta = Object.assign({{}}, trace.meta || {{}}, {{
            dashboard_visual_role: isTrendLine ? 'trend' : 'series',
            dashboard_visual_preserve_color: Boolean(color),
            dashboard_visual_chart_kind: traceChartKind,
          }});
        }});
        spec.metadata = Object.assign({{}}, spec.metadata || {{}}, {{
          dashboard_visual_settings_applied: true,
        }});
        return spec;
      }};

      const applyVisualStateToControls = (state) => {{
        document.querySelectorAll('[data-visual-preset]').forEach((button) => {{
          const active = button.getAttribute('data-visual-preset') === state.preset;
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
          button.dataset.active = active ? '1' : '0';
        }});
        const setValue = (id, value) => {{
          const control = document.getElementById(id);
          if (control) control.value = value;
        }};
        setValue('dashboard-visual-palette-mode', state.palette_mode);
        setValue('dashboard-visual-anchor', state.anchor_color);
        setValue('dashboard-visual-gradient-spread', state.gradient_spread);
        setValue('dashboard-visual-distinguish', state.distinguish);
        setValue('dashboard-visual-marker-size', state.marker_size);
        setValue('dashboard-visual-stat-width', state.stat_lines.width);
        const statAccent = document.getElementById('dashboard-visual-stat-accent');
        if (statAccent) statAccent.checked = Boolean(state.stat_lines.accent_by_stat);
        document.querySelectorAll('[data-visual-palette-index]').forEach((input) => {{
          const index = Number(input.getAttribute('data-visual-palette-index'));
          if (Number.isInteger(index) && state.palette[index]) input.value = state.palette[index];
        }});
        document.querySelectorAll('[data-visual-opacity]').forEach((input) => {{
          const key = input.getAttribute('data-visual-opacity');
          if (key && Object.prototype.hasOwnProperty.call(state.opacity, key)) input.value = state.opacity[key];
        }});
      }};

      const collectVisualStateFromControls = (presetOverride = null) => {{
        const state = sanitizeVisualState(dashboardVisualState);
        if (presetOverride) {{
          state.preset = presetOverride;
        }} else if (state.preset !== 'print' && state.preset !== 'distinct') {{
          state.preset = 'custom';
        }}
        const valueOf = (id, fallback) => {{
          const control = document.getElementById(id);
          return control ? control.value : fallback;
        }};
        state.palette_mode = valueOf('dashboard-visual-palette-mode', state.palette_mode);
        state.anchor_color = valueOf('dashboard-visual-anchor', state.anchor_color);
        state.gradient_spread = valueOf('dashboard-visual-gradient-spread', state.gradient_spread);
        state.distinguish = valueOf('dashboard-visual-distinguish', state.distinguish);
        state.marker_size = Number(valueOf('dashboard-visual-marker-size', state.marker_size));
        state.stat_lines.width = Number(valueOf('dashboard-visual-stat-width', state.stat_lines.width));
        const statAccent = document.getElementById('dashboard-visual-stat-accent');
        if (statAccent) state.stat_lines.accent_by_stat = Boolean(statAccent.checked);
        document.querySelectorAll('[data-visual-palette-index]').forEach((input) => {{
          const index = Number(input.getAttribute('data-visual-palette-index'));
          if (Number.isInteger(index)) state.palette[index] = input.value;
        }});
        document.querySelectorAll('[data-visual-opacity]').forEach((input) => {{
          const key = input.getAttribute('data-visual-opacity');
          if (key) state.opacity[key] = Number(input.value);
        }});
        return sanitizeVisualState(state);
      }};

      const setDashboardVisualState = (state, {{ persist = true, rerender = true }} = {{}}) => {{
        dashboardVisualState = sanitizeVisualState(state);
        applyVisualStateToControls(dashboardVisualState);
        if (persist) persistVisualState(dashboardVisualState);
        if (rerender && typeof refreshPlotlyCharts === 'function') {{
          scheduleVisualRefresh();
        }}
      }};

      const scheduleVisualRefresh = () => {{
        ensurePlotlyVisibilityReactPatch();
        window.clearTimeout(visualRefreshTimer);
        visualRefreshTimer = window.setTimeout(() => {{
          refreshPlotlyCharts();
          if (typeof refreshOpenLightboxPlotly === 'function') {{
            refreshOpenLightboxPlotly();
          }}
        }}, 90);
      }};

      const initializeDashboardVisualControls = () => {{
        dashboardVisualState = readStoredVisualState();
        applyVisualStateToControls(dashboardVisualState);
        const dialog = document.getElementById('dashboard-visual-dialog');
        const openButton = document.getElementById('dashboard-visuals-open');
        const closeButton = document.getElementById('dashboard-visuals-close');
        const applyButton = document.getElementById('dashboard-visual-apply');
        const resetButton = document.getElementById('dashboard-visual-reset');
        if (openButton && dialog) {{
          openButton.addEventListener('click', () => {{
            if (typeof dialog.showModal === 'function') dialog.showModal();
            else dialog.setAttribute('open', 'open');
          }});
        }}
        if (closeButton && dialog) {{
          closeButton.addEventListener('click', () => dialog.close ? dialog.close() : dialog.removeAttribute('open'));
        }}
        if (applyButton && dialog) {{
          applyButton.addEventListener('click', () => {{
            setDashboardVisualState(collectVisualStateFromControls());
            if (dialog.close) dialog.close();
          }});
        }}
        if (resetButton) {{
          resetButton.addEventListener('click', () => setDashboardVisualState(sanitizeVisualState(null)));
        }}
        document.querySelectorAll('[data-visual-preset]').forEach((button) => {{
          button.addEventListener('click', () => {{
            setDashboardVisualState(collectVisualStateFromControls(button.getAttribute('data-visual-preset') || 'auto'));
          }});
        }});
        document.querySelectorAll(
          '#dashboard-visual-palette-mode, #dashboard-visual-anchor, #dashboard-visual-gradient-spread, '
          + '#dashboard-visual-distinguish, #dashboard-visual-marker-size, #dashboard-visual-stat-width, '
          + '#dashboard-visual-stat-accent, [data-visual-palette-index], [data-visual-opacity]'
        ).forEach((control) => {{
          control.addEventListener('input', () => setDashboardVisualState(collectVisualStateFromControls()));
          control.addEventListener('change', () => setDashboardVisualState(collectVisualStateFromControls()));
        }});
      }};
    """
