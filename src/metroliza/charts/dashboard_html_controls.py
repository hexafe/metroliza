"""Shared HTML controls and browser runtime helpers for Plotly dashboards."""

from __future__ import annotations

import hashlib
import html
import json

from metroliza.charts.dashboard_visual_options import (
    DEFAULT_DASHBOARD_PALETTE,
    DEFAULT_HIGHLIGHT_ANCHOR,
    DASHBOARD_VISUAL_MARKER_SYMBOLS,
    DASHBOARD_VISUAL_PATTERN_SHAPES,
    DASHBOARD_VISUAL_RECIPES,
    PRINT_DASHBOARD_PALETTE,
    dashboard_visual_palette_presets,
    dashboard_visual_preview_labels,
    dashboard_visual_recipe_choices,
    dashboard_visual_recipe_settings,
    default_dashboard_visual_settings,
    normalize_dashboard_visual_settings,
)


DASHBOARD_THEME_STORAGE_KEY = "metroliza-dashboard-theme"
DASHBOARD_VISUAL_STORAGE_KEY = "metroliza-dashboard-visuals"
DASHBOARD_VISUAL_THEME_STORAGE_KEY = "metroliza-dashboard-visual-themes"
DASHBOARD_POINT_MARK_STORAGE_KEY = "metroliza-dashboard-point-marks"


def _render_visual_range_field(
    *,
    label: str,
    range_id: str | None = None,
    value: str | float,
    minimum: str | float,
    maximum: str | float,
    step: str | float,
    extra_attrs: str = "",
    selected_field: str | None = None,
) -> str:
    """Return a range input paired with a visible numeric input."""

    escaped_label = html.escape(label)
    value_text = html.escape(str(value))
    min_text = html.escape(str(minimum))
    max_text = html.escape(str(maximum))
    step_text = html.escape(str(step))
    field_attr = (
        f' data-visual-selected-field="{html.escape(selected_field)}"'
        if selected_field
        else ""
    )
    id_attr = f' id="{html.escape(range_id)}"' if range_id else ""
    number_for = f' data-visual-range-value-for="{html.escape(range_id)}"' if range_id else ""
    return (
        f'<label class="visual-field visual-range-field"{field_attr}><span>{escaped_label}</span>'
        '<div class="visual-range-row">'
        f'<input type="range" min="{min_text}" max="{max_text}" step="{step_text}" '
        f'value="{value_text}"{id_attr}{extra_attrs}>'
        f'<input type="number" min="{min_text}" max="{max_text}" step="{step_text}" '
        f'value="{value_text}" class="visual-range-number" data-visual-range-value{number_for} '
        f'aria-label="{escaped_label} value">'
        '</div></label>'
    )


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


def render_dashboard_theme_runtime_helpers(
    *,
    storage_key_var: str = "themeStorageKey",
    indent: str = "      ",
) -> str:
    """Return shared browser-side helpers for dashboard theme switching."""

    storage_key = str(storage_key_var or "themeStorageKey")
    return f"""
{indent}const allowedThemeChoices = new Set(['auto', 'light', 'dark']);
{indent}const themeMedia = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

{indent}const sanitizeThemeChoice = (value) => (
{indent}  allowedThemeChoices.has(value) ? value : 'auto'
{indent});

{indent}const currentThemeChoice = () => sanitizeThemeChoice(
{indent}  document.documentElement.dataset.themeChoice || 'auto'
{indent});

{indent}const resolveTheme = (choice) => (
{indent}  choice === 'auto'
{indent}    ? ((themeMedia && themeMedia.matches) ? 'dark' : 'light')
{indent}    : choice
{indent});

{indent}const persistThemeChoice = (choice) => {{
{indent}  try {{
{indent}    window.localStorage.setItem({storage_key}, choice);
{indent}  }} catch (_error) {{
{indent}    // Ignore storage failures in locked-down browser contexts.
{indent}  }}
{indent}}};

{indent}const readStoredThemeChoice = () => {{
{indent}  try {{
{indent}    return sanitizeThemeChoice(window.localStorage.getItem({storage_key}) || currentThemeChoice());
{indent}  }} catch (_error) {{
{indent}    return currentThemeChoice();
{indent}  }}
{indent}}};""".strip("\n")


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


def render_dashboard_visual_dialog(
    *,
    preview_labels: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Return a compact visual settings dialog for saved Plotly dashboards."""

    resolved_preview_labels = dashboard_visual_preview_labels(preview_labels)
    palette_preset_options = "".join(
        (
            f'<option value="{html.escape(key)}">{html.escape(str(meta.get("label") or key))}</option>'
            for key, meta in dashboard_visual_palette_presets().items()
        )
    ) + '<option value="custom">Custom swatches</option>'
    palette_inputs = "".join(
        (
            '<label class="visual-swatch" '
            f'aria-label="Series color {index + 1}">'
            f'<input type="color" data-visual-palette-index="{index}" value="{html.escape(color)}">'
            "</label>"
        )
        for index, color in enumerate(DEFAULT_DASHBOARD_PALETTE[:6])
    )
    marker_symbol_options = "".join(
        (
            f'<option value="{html.escape(symbol)}">'
            f'{html.escape(symbol.replace("-", " ").title())}</option>'
        )
        for symbol in DASHBOARD_VISUAL_MARKER_SYMBOLS
    )
    group_color_chips = "".join(
        (
            '<button type="button" class="visual-color-chip" data-visual-group-chip '
            f'data-visual-chip-index="{index}">'
            '<span class="visual-color-chip-swatch"></span>'
            f'<span class="visual-color-chip-label">{html.escape(label)}</span>'
            "</button>"
        )
        for index, label in enumerate(resolved_preview_labels)
    )
    recipe_options = "".join(
        (
            f'<option value="{html.escape(recipe_id)}"'
            f'{" selected" if recipe_id == "auto" else ""}>{html.escape(label)}</option>'
        )
        for label, recipe_id in dashboard_visual_recipe_choices()
    )
    fine_tuning_controls = (
        _render_visual_range_field(
            label="Default marker size",
            range_id="dashboard-visual-marker-size",
            value="7",
            minimum="2",
            maximum="18",
            step="0.5",
        )
        + _render_visual_range_field(
            label="Stat width",
            range_id="dashboard-visual-stat-width",
            value="2",
            minimum="0.5",
            maximum="6",
            step="0.25",
        )
        + '<label class="visual-field visual-check"><input type="checkbox" id="dashboard-visual-stat-accent">'
        '<span>Stat accents</span></label>'
    )
    selection_controls = (
        '<label class="visual-field"><span>Selection inspector</span>'
        '<select id="dashboard-visual-element"><option value="">Click a plot element</option></select></label>'
        '<label class="visual-field" data-visual-selected-field="color"><span>Element color</span>'
        '<input type="color" id="dashboard-visual-element-color" value="#245a5a"></label>'
        + _render_visual_range_field(
            label="Element opacity",
            range_id="dashboard-visual-element-opacity",
            value="1",
            minimum="0.05",
            maximum="1",
            step="0.01",
            selected_field="opacity",
        )
        + _render_visual_range_field(
            label="Line width",
            range_id="dashboard-visual-element-width",
            value="2",
            minimum="0.5",
            maximum="8",
            step="0.25",
            selected_field="width",
        )
        + '<label class="visual-field" data-visual-selected-field="dash"><span>Dash</span>'
        '<select id="dashboard-visual-element-dash">'
        '<option value="solid">Solid</option><option value="dash">Dash</option>'
        '<option value="dot">Dot</option><option value="dashdot">Dash-dot</option>'
        '</select></label>'
        + _render_visual_range_field(
            label="Marker size",
            range_id="dashboard-visual-element-marker-size",
            value="7",
            minimum="2",
            maximum="18",
            step="0.5",
            selected_field="marker_size",
        )
        + '<label class="visual-field" data-visual-selected-field="marker_symbol"><span>Shape</span>'
        f'<select id="dashboard-visual-element-marker-symbol">{marker_symbol_options}</select></label>'
        '<label class="visual-field visual-check" data-visual-selected-field="outline_enabled">'
        '<input type="checkbox" id="dashboard-visual-element-outline-enabled">'
        '<span>Marker border</span></label>'
        + _render_visual_range_field(
            label="Border width",
            range_id="dashboard-visual-element-outline-width",
            value="1.25",
            minimum="0",
            maximum="6",
            step="0.25",
            selected_field="outline_width",
        )
        + '<label class="visual-field" data-visual-selected-field="outline_color_mode"><span>Border color mode</span>'
        '<select id="dashboard-visual-element-outline-color-mode">'
        '<option value="auto">Auto contrast</option><option value="custom">Custom color</option>'
        '</select></label>'
        '<label class="visual-field" data-visual-selected-field="outline_color"><span>Border color</span>'
        '<input type="color" id="dashboard-visual-element-outline-color" value="#111827"></label>'
        '<label class="visual-field" data-visual-selected-field="pattern_shape"><span>Pattern</span>'
        '<select id="dashboard-visual-element-pattern">'
        '<option value="">None</option><option value="/">Slash</option>'
        '<option value="\\\\">Backslash</option><option value="x">Cross</option>'
        '<option value=".">Dot</option><option value="-">Dash</option>'
        '</select></label>'
        '<div class="visual-actions visual-actions-inline">'
        '<button type="button" id="dashboard-visual-element-reset">Clear selected style</button>'
        '</div>'
    )
    point_mark_controls = (
        '<label class="visual-field"><span>Find point</span>'
        '<input type="search" id="dashboard-visual-point-search" '
        'placeholder="TraceCode or point value"></label>'
        '<label class="visual-field"><span>Search in</span>'
        '<select id="dashboard-visual-point-search-scope">'
        '<option value="record">TraceCode / record key</option>'
        '<option value="any">Any field</option>'
        '<option value="trace">Trace / series</option>'
        '<option value="x">X axis</option>'
        '<option value="y">Y axis</option>'
        '<option value="metadata">Text / custom data</option>'
        '</select></label>'
        '<label class="visual-field"><span>Matches</span>'
        '<output id="dashboard-visual-point-search-count">0 matches</output></label>'
        '<div class="visual-actions visual-actions-inline visual-point-search-actions">'
        '<button type="button" id="dashboard-visual-point-search-prev">Previous</button>'
        '<button type="button" id="dashboard-visual-point-search-next">Next</button>'
        '</div>'
        '<ol id="dashboard-visual-point-search-results" class="visual-point-search-results" '
        'aria-label="Point search results"></ol>'
        '<label class="visual-field" data-visual-point-field="summary"><span>Selected point</span>'
        '<output id="dashboard-visual-point-summary">None selected</output></label>'
        '<label class="visual-field"><span>Point mark color</span>'
        '<input type="color" id="dashboard-visual-point-color" value="#d66e2f"></label>'
        '<div class="visual-actions visual-actions-inline visual-point-actions">'
        '<button type="button" id="dashboard-visual-point-mark">Mark selected point</button>'
        '<button type="button" id="dashboard-visual-point-clear">Clear selected mark</button>'
        '<button type="button" id="dashboard-visual-point-clear-all">Clear all marks</button>'
        '</div>'
    )
    return (
        '<dialog id="dashboard-visual-dialog" class="visual-dialog" aria-label="Plot visual settings">'
        '<form method="dialog" class="visual-panel">'
        '<div class="visual-panel-header">'
        '<div><h2>Plot Visuals</h2></div>'
        '<button type="button" class="visual-dialog-close" id="dashboard-visuals-close">Close</button>'
        '</div>'
        '<section class="visual-section">'
        '<label class="visual-field"><span>Visual preset</span>'
        f'<select id="dashboard-visual-preset">{recipe_options}</select></label>'
        f'<div class="visual-palette-preview" aria-label="Resolved group colors">{group_color_chips}</div>'
        '</section>'
        '<section class="visual-section visual-grid">'
        '<label class="visual-field"><span>Theme</span>'
        '<select id="dashboard-visual-theme"><option value="">Current settings</option></select></label>'
        '<label class="visual-field"><span>Name</span>'
        '<input type="text" id="dashboard-visual-theme-name" placeholder="Theme name"></label>'
        '<div class="visual-actions visual-actions-inline">'
        '<button type="button" id="dashboard-visual-theme-save">Save theme</button>'
        '<button type="button" id="dashboard-visual-theme-delete">Delete</button>'
        '</div>'
        '</section>'
        '<section class="visual-section visual-actions visual-actions-inline">'
        '<button type="button" id="dashboard-visual-customize-open" '
        'aria-expanded="false" aria-controls="dashboard-visual-customize">Customize...</button>'
        '</section>'
        '<div id="dashboard-visual-customize" class="visual-customize" hidden>'
        '<section class="visual-section visual-grid">'
        '<label class="visual-field"><span>Palette</span>'
        f'<select id="dashboard-visual-palette-preset">{palette_preset_options}</select></label>'
        '<label class="visual-field"><span>Palette mode</span>'
        '<select id="dashboard-visual-palette-mode">'
        '<option value="fixed">Use color set</option>'
        '<option value="auto_gradient">Generate gradient</option>'
        '<option value="highlight_gradient">Around highlight</option>'
        '</select></label>'
        '<label class="visual-field"><span>Anchor</span>'
        f'<input type="color" id="dashboard-visual-anchor" value="{DEFAULT_HIGHLIGHT_ANCHOR}"></label>'
        '<label class="visual-field"><span>Spread</span>'
        '<select id="dashboard-visual-gradient-spread">'
        '<option value="narrow">Narrow</option>'
        '<option value="normal">Normal</option>'
        '<option value="wide">Wide</option>'
        '</select></label>'
        '<label class="visual-field"><span>Differentiate</span>'
        '<select id="dashboard-visual-distinguish">'
        '<option value="color_only">Color only</option>'
        '<option value="when_similar" selected>When similar</option>'
        '<option value="always">Always</option>'
        '</select></label>'
        '</section>'
        f'<section class="visual-section visual-swatches">{palette_inputs}</section>'
        '<section class="visual-section">'
        '<div class="visual-section-title">Fine tuning</div>'
        f'<div class="visual-grid">{fine_tuning_controls}</div>'
        '</section>'
        f'<section class="visual-section visual-grid">{selection_controls}</section>'
        '<section class="visual-section">'
        '<div class="visual-section-title">Point marks</div>'
        f'<div class="visual-grid">{point_mark_controls}</div>'
        '</section>'
        '</div>'
        '<section class="visual-section visual-actions">'
        '<button type="button" id="dashboard-visual-reset">Reset</button>'
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
    .plotly-point-controls button:focus-visible,
    .visual-segmented button:focus-visible,
    .visual-field input:focus-visible,
    .visual-field select:focus-visible,
    .plotly-point-controls input:focus-visible,
    .plotly-point-controls select:focus-visible {
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
    .visual-customize[hidden] {
      display: none;
    }
    .visual-section-title {
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.08em;
      margin-bottom: 8px;
      text-transform: uppercase;
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
    .visual-field input[type="color"],
    .visual-field input[type="search"],
    .visual-field input[type="text"],
    .visual-field input[type="number"] {
      min-height: 34px;
      width: 100%;
    }
    .visual-field select,
    .visual-field input[type="text"],
    .visual-field input[type="search"],
    .visual-field input[type="number"],
    .visual-field output {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel, #ffffff);
      color: var(--ink, var(--text));
      padding: 6px 8px;
      text-transform: none;
      letter-spacing: 0;
      font-weight: 600;
    }
    .visual-field output {
      align-items: center;
      display: flex;
      min-height: 34px;
    }
    .visual-range-row {
      align-items: center;
      display: grid;
      grid-template-columns: minmax(92px, 1fr) minmax(64px, 82px);
      gap: 8px;
    }
    .visual-range-number {
      text-align: right;
    }
    .visual-field[data-disabled="1"] {
      opacity: 0.46;
    }
    .visual-field[data-disabled="1"] select,
    .visual-field[data-disabled="1"] input {
      cursor: not-allowed;
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
    .visual-swatch[data-disabled="1"] input {
      cursor: not-allowed;
      opacity: 0.72;
    }
    .visual-palette-preview {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }
    .visual-color-chip {
      appearance: none;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      cursor: pointer;
      display: inline-flex;
      gap: 8px;
      min-width: 0;
      padding: 7px 8px;
      background: var(--panel, #ffffff);
      color: var(--ink, var(--text));
      font-size: 12px;
      font-weight: 700;
      text-align: left;
    }
    .visual-color-chip:focus-visible {
      outline: 2px solid var(--accent, #245a5a);
      outline-offset: 2px;
    }
    .visual-color-chip-swatch {
      border: 1px solid rgba(15, 23, 42, 0.28);
      border-radius: 999px;
      display: inline-block;
      flex: 0 0 18px;
      height: 18px;
      width: 18px;
    }
    .visual-color-chip-label {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .visual-actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
    }
    .visual-actions-inline {
      align-items: end;
      justify-content: flex-start;
      flex-wrap: wrap;
    }
    .visual-point-search-results {
      border: 1px solid var(--line);
      border-radius: 8px;
      grid-column: 1 / -1;
      list-style: none;
      margin: 0;
      max-height: 150px;
      overflow: auto;
      padding: 4px;
      background: var(--panel, #ffffff);
    }
    .visual-point-search-results:empty {
      display: none;
    }
    .visual-point-search-results li {
      margin: 0;
      padding: 0;
    }
    .visual-point-search-results button {
      appearance: none;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--ink, var(--text));
      cursor: pointer;
      display: block;
      font-size: 12px;
      font-weight: 700;
      line-height: 1.35;
      overflow: hidden;
      padding: 7px 8px;
      text-align: left;
      text-overflow: ellipsis;
      white-space: nowrap;
      width: 100%;
    }
    .visual-point-search-results button:hover,
    .visual-point-search-results button[data-active="1"] {
      background: var(--accent-soft, rgba(23, 105, 170, 0.12));
    }
    .plotly-point-controls {
      align-items: end;
      background: var(--detail-panel-bg, rgba(22, 35, 48, 0.04));
      border: 1px solid var(--line);
      border-radius: 8px;
      display: grid;
      gap: 8px;
      grid-template-columns:
        minmax(170px, 1.4fr) minmax(108px, 0.6fr) minmax(146px, auto)
        minmax(72px, auto) minmax(174px, auto);
      margin-top: 10px;
      padding: 10px;
    }
    .plotly-point-controls label {
      color: var(--muted);
      display: grid;
      font-size: 11px;
      font-weight: 800;
      gap: 4px;
      letter-spacing: 0;
      min-width: 0;
      text-transform: uppercase;
    }
    .plotly-point-controls input[type="search"],
    .plotly-point-controls input[type="color"],
    .plotly-point-controls select,
    .plotly-point-controls output {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel, #ffffff);
      color: var(--ink, var(--text));
      font-size: 12px;
      font-weight: 700;
      min-height: 32px;
      min-width: 0;
      padding: 5px 7px;
      width: 100%;
    }
    .plotly-point-controls input[type="color"] {
      padding: 2px;
    }
    .plotly-point-controls button {
      appearance: none;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-strong, var(--panel));
      color: var(--ink, var(--text));
      cursor: pointer;
      font-size: 12px;
      font-weight: 800;
      min-height: 32px;
      padding: 6px 8px;
    }
    .plotly-point-controls button:hover:not(:disabled) {
      border-color: var(--accent);
      color: var(--accent);
    }
    .plotly-point-controls button:disabled {
      cursor: not-allowed;
      opacity: 0.48;
    }
    .plotly-point-nav,
    .plotly-point-actions {
      align-items: end;
      display: flex;
      gap: 6px;
      min-width: 0;
    }
    .plotly-point-nav output {
      align-items: center;
      display: inline-flex;
      justify-content: center;
      min-width: 72px;
      width: auto;
    }
    .plotly-point-selection {
      align-items: center;
      display: none;
      grid-column: 1 / -1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .plotly-point-controls[data-has-selected="1"] .plotly-point-selection {
      display: flex;
    }
    @media (max-width: 780px) {
      .dashboard-control-bar { width: 100%; justify-content: space-between; }
      .visual-dialog { width: min(100vw - 20px, 760px); }
      .visual-swatches { grid-template-columns: repeat(3, minmax(42px, 1fr)); }
      .plotly-point-controls {
        grid-template-columns: 1fr 1fr;
      }
      .plotly-point-search-field,
      .plotly-point-actions {
        grid-column: 1 / -1;
      }
    }
    """


def _dashboard_visual_state_signature(settings: dict) -> str:
    payload = json.dumps(settings, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def dashboard_visual_runtime_config_json(
    initial_settings: dict | None = None,
    *,
    preview_labels: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Return shared defaults as compact JSON for browser runtime."""

    normalized_initial_settings = normalize_dashboard_visual_settings(initial_settings)
    default_settings = default_dashboard_visual_settings()
    resolved_preview_labels = dashboard_visual_preview_labels(preview_labels)
    return json.dumps(
        {
            "storageKey": DASHBOARD_VISUAL_STORAGE_KEY,
            "themeStorageKey": DASHBOARD_VISUAL_THEME_STORAGE_KEY,
            "pointMarkStorageKey": DASHBOARD_POINT_MARK_STORAGE_KEY,
            "storageVersion": 1,
            "defaults": default_settings,
            "initialSettings": normalized_initial_settings,
            "defaultSettingsSignature": _dashboard_visual_state_signature(default_settings),
            "initialSettingsSignature": _dashboard_visual_state_signature(normalized_initial_settings),
            "recipes": {
                key: dashboard_visual_recipe_settings(key)
                for key in DASHBOARD_VISUAL_RECIPES
            },
            "recipeIds": list(DASHBOARD_VISUAL_RECIPES),
            "defaultPalette": list(DEFAULT_DASHBOARD_PALETTE),
            "printPalette": list(PRINT_DASHBOARD_PALETTE),
            "previewLabels": list(resolved_preview_labels),
            "palettePresets": {
                key: {
                    "label": str(meta.get("label") or key),
                    "kind": str(meta.get("kind") or "categorical"),
                    "colors": list(meta.get("colors") or []),
                }
                for key, meta in dashboard_visual_palette_presets().items()
            },
            "markerSymbols": list(DASHBOARD_VISUAL_MARKER_SYMBOLS),
            "patterns": list(DASHBOARD_VISUAL_PATTERN_SHAPES),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")


def render_dashboard_visual_runtime_js(
    config_var: str = "dashboardVisualConfig",
    *,
    initial_settings: dict | None = None,
    preview_labels: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Return browser functions for applying dashboard visual settings to Plotly specs."""

    return f"""
      const {config_var} = {dashboard_visual_runtime_config_json(initial_settings, preview_labels=preview_labels)};
      const visualStorageBaseKey = {config_var}.storageKey;
      const visualThemeStorageKey = {config_var}.themeStorageKey;
      const pointMarkStorageBaseKey = {config_var}.pointMarkStorageKey || 'metroliza-dashboard-point-marks';
      let dashboardVisualState = null;
      let dashboardVisualThemeLibrary = null;
      let dashboardVisualSelectedTarget = null;
      let dashboardVisualSelectedPoint = null;
      let dashboardPointMarkState = null;
      let dashboardPointSearchMatches = [];
      let dashboardPointSearchIndex = -1;
      let dashboardPointSearchSelectedId = '';
      let visualRefreshTimer = 0;

      const dashboardVisualScope = () => {{
        const explicitScope = document.documentElement.getAttribute('data-dashboard-visual-scope')
          || (document.body ? document.body.getAttribute('data-dashboard-visual-scope') : '')
          || '';
        const locationScope = window.location
          ? `${{window.location.pathname || ''}}${{window.location.search || ''}}`
          : '';
        return String(explicitScope || locationScope || document.title || 'dashboard')
          .trim()
          .toLowerCase()
          .replace(/[^a-z0-9._/-]+/g, '-')
          .replace(/^-+|-+$/g, '')
          .slice(0, 180) || 'dashboard';
      }};

      const visualStorageKey = `${{visualStorageBaseKey}}:${{dashboardVisualScope()}}`;
      const pointMarkStorageKey = `${{pointMarkStorageBaseKey}}:${{dashboardVisualScope()}}`;
      window.metrolizaDashboardVisualStorageKey = visualStorageKey;
      window.metrolizaDashboardPointMarkStorageKey = pointMarkStorageKey;

      const visualChoice = (value, allowed, fallback) => (
        allowed.includes(value) ? value : fallback
      );

      const clonePlotlySpec = (spec) => JSON.parse(JSON.stringify(spec || {{}}));

      const cloneJsonValue = (value) => {{
        if (value === undefined) return undefined;
        try {{
          return JSON.parse(JSON.stringify(value));
        }} catch (_error) {{
          return String(value);
        }}
      }};

      const embeddedInitialVisualState = () => (
        sanitizeVisualState({config_var}.initialSettings || {config_var}.defaults)
      );

      const normalizeColor = (value, fallback) => (
        typeof value === 'string' && /^#[0-9a-f]{{6}}$/i.test(value.trim())
          ? value.trim().toLowerCase()
          : fallback
      );

      const visualColorSourceForState = (state) => {{
        if (!state || state.preset === 'auto') return 'auto';
        if (state.preset === 'distinct') return 'distinct';
        if (state.preset === 'print') return 'print';
        if (state.palette_mode === 'auto_gradient') return 'gradient';
        if (state.palette_mode === 'highlight_gradient') return 'highlight';
        return state.palette_preset === 'custom' ? 'custom' : 'preset';
      }};

      const boundedNumber = (value, fallback, minimum, maximum) => {{
        const number = Number(value);
        if (!Number.isFinite(number)) {{
          return fallback;
        }}
        return Math.min(maximum, Math.max(minimum, number));
      }};

      const normalizeMarkerSymbol = (value, fallback = '') => {{
        const clean = String(value || '').trim().toLowerCase().replace(/[\\s_]+/g, '-');
        const allowed = Array.isArray({config_var}.markerSymbols) ? {config_var}.markerSymbols : [];
        return allowed.includes(clean) ? clean : fallback;
      }};

      const sanitizeVisualState = (value) => {{
        const defaults = clonePlotlySpec({config_var}.defaults);
        const source = (value && typeof value === 'object') ? value : {{}};
        const state = Object.assign({{}}, defaults, source);
        const recipeIds = Array.isArray({config_var}.recipeIds)
          ? {config_var}.recipeIds
          : ['auto', 'distinct', 'print', 'custom'];
        state.recipe = visualChoice(state.recipe || state.visual_recipe || state.preset, recipeIds, defaults.recipe || defaults.preset);
        state.preset = visualChoice(state.preset, ['auto', 'distinct', 'print', 'custom'], defaults.preset);
        state.theme_id = typeof state.theme_id === 'string' ? state.theme_id : '';
        state.theme_name = typeof state.theme_name === 'string' ? state.theme_name : '';
        const palettePresetIds = Object.keys({config_var}.palettePresets || {{}}).concat(['custom']);
        state.palette_preset = visualChoice(state.palette_preset, palettePresetIds, defaults.palette_preset || 'metroliza');
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
        state.marker_size = boundedNumber(state.marker_size, defaults.marker_size, 2, 18);
        if (state.preset === 'distinct') {{
          state.palette_preset = 'okabe_ito';
          state.palette_mode = 'fixed';
        }} else if (state.preset === 'print') {{
          state.palette_preset = 'custom';
          state.palette_mode = 'fixed';
          state.palette = expandPalette({config_var}.printPalette || defaults.palette, 6);
        }}
        state.population_baseline = sanitizePopulationBaseline(
          state.population_baseline,
          defaults.population_baseline
        );
        state.comparison_focus = sanitizeComparisonFocus(
          state.comparison_focus,
          defaults.comparison_focus
        );
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
          state.reference_lines[key].opacity = boundedNumber(
            state.reference_lines[key].opacity,
            defaults.reference_lines[key].opacity || 1,
            0.05,
            1
          );
        }});
        state.series_overrides = sanitizeStyleOverrides(state.series_overrides);
        state.stat_line_overrides = sanitizeStyleOverrides(state.stat_line_overrides);
        state.color_source = visualColorSourceForState(state);
        return state;
      }};

      const sanitizeChartFloatMap = (value, minimum, maximum) => {{
        if (!value || typeof value !== 'object' || Array.isArray(value)) return {{}};
        const output = {{}};
        Object.entries(value).forEach(([key, number]) => {{
          if (!key) return;
          output[String(key)] = boundedNumber(number, 1, minimum, maximum);
        }});
        return output;
      }};

      const sanitizePopulationBaseline = (value, fallback = {{}}) => {{
        const source = value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length
          ? value
          : fallback;
        if (!source || typeof source !== 'object' || Array.isArray(source)) return {{}};
        const aliases = Array.isArray(source.aliases)
          ? source.aliases.map((alias) => String(alias || '').trim()).filter(Boolean)
          : ['population', 'population points'];
        const clean = {{
          aliases: aliases.length ? aliases : ['population', 'population points'],
          draw_first: source.draw_first !== false,
        }};
        const color = normalizeColor(source.color, '');
        if (color) clean.color = color;
        const opacity = sanitizeChartFloatMap(source.opacity, 0, 1);
        if (Object.keys(opacity).length) clean.opacity = opacity;
        if (Object.prototype.hasOwnProperty.call(source, 'marker_size')) clean.marker_size = boundedNumber(source.marker_size, 4.5, 2, 18);
        const markerSymbol = normalizeMarkerSymbol(source.marker_symbol, '');
        if (markerSymbol) clean.marker_symbol = markerSymbol;
        if (Object.prototype.hasOwnProperty.call(source, 'outline_width')) clean.outline_width = boundedNumber(source.outline_width, 0, 0, 6);
        if (typeof source.outline_color_mode === 'string') clean.outline_color_mode = visualChoice(source.outline_color_mode, ['auto', 'custom'], 'auto');
        const outlineColor = normalizeColor(source.outline_color, '');
        if (outlineColor) clean.outline_color = outlineColor;
        return clean;
      }};

      const sanitizeComparisonFocus = (value, fallback = {{}}) => {{
        const source = value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length
          ? value
          : fallback;
        if (!source || typeof source !== 'object' || Array.isArray(source)) return {{}};
        const clean = {{}};
        const opacity = sanitizeChartFloatMap(source.opacity, 0, 1);
        if (Object.keys(opacity).length) clean.opacity = opacity;
        if (Object.prototype.hasOwnProperty.call(source, 'marker_size')) clean.marker_size = boundedNumber(source.marker_size, 8.5, 2, 18);
        const markerSymbol = normalizeMarkerSymbol(source.marker_symbol, '');
        if (markerSymbol) clean.marker_symbol = markerSymbol;
        if (Object.prototype.hasOwnProperty.call(source, 'outline_width')) clean.outline_width = boundedNumber(source.outline_width, 1.25, 0, 6);
        if (typeof source.outline_color_mode === 'string') clean.outline_color_mode = visualChoice(source.outline_color_mode, ['auto', 'custom'], 'auto');
        const outlineColor = normalizeColor(source.outline_color, '');
        if (outlineColor) clean.outline_color = outlineColor;
        return clean;
      }};

      const sanitizeStyleOverrides = (value) => {{
        if (!value || typeof value !== 'object' || Array.isArray(value)) return {{}};
        const output = {{}};
        Object.entries(value).forEach(([key, style]) => {{
          if (!key || !style || typeof style !== 'object' || Array.isArray(style)) return;
          const clean = {{}};
          if (style.color) clean.color = normalizeColor(style.color, '');
          if (clean.color === '') delete clean.color;
          if (Object.prototype.hasOwnProperty.call(style, 'opacity')) clean.opacity = boundedNumber(style.opacity, 1, 0, 1);
          if (Object.prototype.hasOwnProperty.call(style, 'width')) clean.width = boundedNumber(style.width, 2, 0.5, 8);
          if (Object.prototype.hasOwnProperty.call(style, 'marker_size')) clean.marker_size = boundedNumber(style.marker_size, 7, 2, 18);
          if (Object.prototype.hasOwnProperty.call(style, 'outline_width')) clean.outline_width = boundedNumber(style.outline_width, 0, 0, 6);
          if (typeof style.outline_color_mode === 'string') clean.outline_color_mode = visualChoice(style.outline_color_mode, ['auto', 'custom'], 'auto');
          if (String(style.outline_color || '').toLowerCase() === 'auto') clean.outline_color_mode = 'auto';
          if (style.outline_color && String(style.outline_color).toLowerCase() !== 'auto') clean.outline_color = normalizeColor(style.outline_color, '');
          if (clean.outline_color === '') delete clean.outline_color;
          if (typeof style.dash === 'string') clean.dash = visualChoice(style.dash, ['solid', 'dash', 'dot', 'dashdot', 'longdash'], 'solid');
          const markerSymbol = normalizeMarkerSymbol(style.marker_symbol, '');
          if (markerSymbol) clean.marker_symbol = markerSymbol;
          if (typeof style.pattern_shape === 'string') clean.pattern_shape = style.pattern_shape;
          if (Object.keys(clean).length) output[String(key).toLowerCase()] = clean;
        }});
        return output;
      }};

      const readStoredVisualState = () => {{
        const embedded = {config_var}.initialSettings || {config_var}.defaults;
        try {{
          const raw = window.localStorage.getItem(visualStorageKey);
          if (!raw) return sanitizeVisualState(embedded);
          const parsed = JSON.parse(raw);
          const currentSignature = {config_var}.initialSettingsSignature || '';
          const defaultSignature = {config_var}.defaultSettingsSignature || '';
          if (parsed && typeof parsed === 'object' && parsed.state) {{
            if (parsed.initialSettingsSignature === currentSignature) {{
              return sanitizeVisualState(parsed.state);
            }}
            return sanitizeVisualState(embedded);
          }}
          if (currentSignature && defaultSignature && currentSignature !== defaultSignature) {{
            return sanitizeVisualState(embedded);
          }}
          return sanitizeVisualState(parsed);
        }} catch (_error) {{
          return sanitizeVisualState(embedded);
        }}
      }};

      const persistVisualState = (state) => {{
        try {{
          window.localStorage.setItem(visualStorageKey, JSON.stringify({{
            version: {config_var}.storageVersion || 1,
            initialSettingsSignature: {config_var}.initialSettingsSignature || '',
            state,
          }}));
        }} catch (_error) {{
          // Ignore storage failures in locked-down browser contexts.
        }}
      }};

      const dashboardChartKeyForContainer = (container) => {{
        const explicitKey = container && container.dataset
          ? container.dataset.dashboardChartKey
          : '';
        const attributeKey = container && typeof container.getAttribute === 'function'
          ? container.getAttribute('data-dashboard-chart-key')
          : '';
        const labelKey = container && typeof container.getAttribute === 'function'
          ? container.getAttribute('aria-label')
          : '';
        return String(explicitKey || attributeKey || labelKey || dashboardVisualScope())
          .trim() || 'dashboard';
      }};
      window.metrolizaDashboardChartKeyForContainer = dashboardChartKeyForContainer;

      const stablePointValue = (value) => {{
        if (value === undefined || value === null) return '';
        if (typeof value === 'object') {{
          try {{
            return JSON.stringify(value).slice(0, 120);
          }} catch (_error) {{
            return String(value).slice(0, 120);
          }}
        }}
        return String(value).slice(0, 120);
      }};

      const pointMarkId = (mark) => [
        mark.chartKey,
        Number.isInteger(mark.curveNumber) ? mark.curveNumber : -1,
        Number.isInteger(mark.pointNumber) ? mark.pointNumber : -1,
        stablePointValue(mark.x),
        stablePointValue(mark.y),
      ].join(':');

      const sanitizePointIndex = (value) => {{
        const number = Number(value);
        return Number.isInteger(number) ? number : -1;
      }};

      const sanitizePointMark = (value) => {{
        if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
        const chartKey = String(value.chartKey || value.chart_key || '').trim();
        const x = cloneJsonValue(value.x);
        const y = cloneJsonValue(value.y);
        if (!chartKey || x === undefined || y === undefined) return null;
        const mark = {{
          chartKey,
          curveNumber: sanitizePointIndex(value.curveNumber ?? value.curve_number),
          pointNumber: sanitizePointIndex(value.pointNumber ?? value.point_number),
          x,
          y,
          color: normalizeColor(value.color, '#d66e2f'),
          label: String(value.label || '').slice(0, 160),
          target: String(value.target || '').slice(0, 160),
        }};
        if (Object.prototype.hasOwnProperty.call(value, 'customdata')) {{
          mark.customdata = cloneJsonValue(value.customdata);
        }}
        if (typeof value.xaxis === 'string') mark.xaxis = value.xaxis;
        if (typeof value.yaxis === 'string') mark.yaxis = value.yaxis;
        mark.id = String(value.id || pointMarkId(mark)).slice(0, 320);
        return mark;
      }};

      const sanitizePointMarkState = (value) => {{
        const source = value && typeof value === 'object' && !Array.isArray(value) ? value : {{}};
        const state = {{
          version: 1,
          activeColor: normalizeColor(source.activeColor || source.color, '#d66e2f'),
          marks: [],
        }};
        const marksById = new Map();
        (Array.isArray(source.marks) ? source.marks : []).forEach((item) => {{
          const mark = sanitizePointMark(item);
          if (mark) marksById.set(mark.id, mark);
        }});
        state.marks = Array.from(marksById.values());
        return state;
      }};

      const readStoredPointMarks = () => {{
        try {{
          const raw = window.localStorage.getItem(pointMarkStorageKey);
          return sanitizePointMarkState(raw ? JSON.parse(raw) : null);
        }} catch (_error) {{
          return sanitizePointMarkState(null);
        }}
      }};

      const persistPointMarks = (state) => {{
        try {{
          window.localStorage.setItem(pointMarkStorageKey, JSON.stringify(sanitizePointMarkState(state)));
        }} catch (_error) {{
          // Ignore storage failures in locked-down browser contexts.
        }}
      }};

      const readVisualThemeLibrary = () => {{
        try {{
          const raw = window.localStorage.getItem(visualThemeStorageKey);
          const parsed = raw ? JSON.parse(raw) : null;
          if (parsed && typeof parsed === 'object' && Array.isArray(parsed.themes)) {{
            return parsed;
          }}
        }} catch (_error) {{
          // Ignore storage failures in locked-down browser contexts.
        }}
        return {{ version: 1, default_theme_id: '', themes: [] }};
      }};

      const persistVisualThemeLibrary = (library) => {{
        dashboardVisualThemeLibrary = library && typeof library === 'object'
          ? library
          : {{ version: 1, default_theme_id: '', themes: [] }};
        try {{
          window.localStorage.setItem(visualThemeStorageKey, JSON.stringify(dashboardVisualThemeLibrary));
        }} catch (_error) {{
          // Ignore storage failures in locked-down browser contexts.
        }}
      }};

      const visualThemeIdFromName = (name) => String(name || 'dashboard-theme')
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 80) || 'dashboard-theme';

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
        const preset = ({config_var}.palettePresets || {{}})[state.palette_preset];
        if (state.palette_mode === 'auto_gradient' || state.palette_mode === 'highlight_gradient') {{
          if (preset && ['sequential', 'diverging'].includes(preset.kind) && Array.isArray(preset.colors)) {{
            return expandPalette(preset.colors, count);
          }}
          return gradientPalette(
            state.anchor_color,
            count,
            state.gradient_spread,
            state.palette_mode === 'highlight_gradient'
          );
        }}
        if (preset && Array.isArray(preset.colors)) {{
          return expandPalette(preset.colors, count);
        }}
        if (state.preset === 'distinct') {{
          return {config_var}.defaultPalette.slice(0, count);
        }}
        return state.palette.slice(0, count);
      }};

      const expandPalette = (colors, count = 6) => {{
        const source = Array.isArray(colors) && colors.length ? colors : {config_var}.defaultPalette;
        const clean = source.map((color, index) => normalizeColor(color, {config_var}.defaultPalette[index % {config_var}.defaultPalette.length] || '#245a5a'));
        const output = [];
        for (let index = 0; index < count; index += 1) {{
          output.push(clean[index % clean.length]);
        }}
        return output;
      }};

      const applyVisualRecipe = (recipe, currentState = dashboardVisualState) => {{
        const defaults = sanitizeVisualState({config_var}.initialSettings || {config_var}.defaults);
        const state = sanitizeVisualState(Object.assign({{}}, currentState || defaults));
        const configuredRecipes = {config_var}.recipes || {{}};
        const configured = configuredRecipes[recipe] ? sanitizeVisualState(configuredRecipes[recipe]) : null;
        const preservedTheme = {{
          theme_id: state.theme_id || '',
          theme_name: state.theme_name || '',
        }};
        const next = recipe === 'custom'
          ? state
          : sanitizeVisualState(Object.assign({{}}, defaults, configured || {{}}, preservedTheme));
        next.recipe = visualChoice(recipe, Object.keys(configuredRecipes).concat(['custom']), 'auto');
        next.preset = visualChoice(next.preset, ['auto', 'distinct', 'print', 'custom'], 'custom');
        if (recipe === 'custom' && next.palette_preset !== 'custom') {{
          next.palette = resolvedVisualPalette(state, 6);
          next.palette_preset = 'custom';
          next.palette_mode = 'fixed';
        }}
        next.series_overrides = recipe === 'custom' ? clonePlotlySpec(state.series_overrides || {{}}) : {{}};
        next.stat_line_overrides = recipe === 'custom' ? clonePlotlySpec(state.stat_line_overrides || {{}}) : {{}};
        next.reference_lines = recipe === 'custom'
          ? clonePlotlySpec(state.reference_lines || defaults.reference_lines)
          : clonePlotlySpec(next.reference_lines || defaults.reference_lines);
        if (next.preset === 'custom') {{
          next.preset = 'custom';
        }}
        return sanitizeVisualState(next);
      }};

      const lowLevelVisualSettings = (state) => {{
        if (!state || state.preset === 'auto') {{
          return {{}};
        }}
        const useDistinguishers = state.distinguish !== 'color_only' || state.preset === 'print';
        return {{
          recipe: state.recipe,
          color_source: state.color_source,
          preserve_colors_on_theme: true,
          series: {{
            palette: resolvedVisualPalette(state, 6),
            marker_size: state.marker_size,
            marker_symbols: useDistinguishers ? {config_var}.markerSymbols.slice() : [],
            patterns: useDistinguishers ? {config_var}.patterns.slice() : [],
            auto_distinguish: state.distinguish === 'when_similar',
            always_distinguish: state.distinguish === 'always' || state.preset === 'print',
            population_baseline: clonePlotlySpec(state.population_baseline || {{}}),
            comparison_focus: clonePlotlySpec(state.comparison_focus || {{}}),
            overrides: clonePlotlySpec(state.series_overrides || {{}}),
          }},
          stat_lines: Object.assign({{}}, state.stat_lines, {{
            overrides: clonePlotlySpec(state.stat_line_overrides || {{}}),
          }}),
          reference_lines: clonePlotlySpec(state.reference_lines),
        }};
      }};

      const stripGroupCount = (label) => String(label || '').replace(/\\s*\\(n\\s*=\\s*\\d+\\)\\s*$/i, '').trim();
      const normalizeLabelKey = (label) => stripGroupCount(label).toLowerCase();
      const chartSetting = (value, chartKind) => (
        value && typeof value === 'object' && !Array.isArray(value)
          ? (value[chartKind] ?? value.default)
          : value
      );
      const isPopulationLabel = (label, population) => {{
        const aliases = population && Array.isArray(population.aliases)
          ? population.aliases
          : ['population', 'population points'];
        const labelKey = normalizeLabelKey(label);
        return aliases.some((alias) => labelKey === normalizeLabelKey(alias));
      }};
      const roleStyleFromSettings = (settings, chartKind) => {{
        if (!settings || typeof settings !== 'object') return {{}};
        const style = {{}};
        if (settings.color) style.color = settings.color;
        const opacity = Number(chartSetting(settings.opacity, chartKind));
        if (Number.isFinite(opacity)) style.opacity = opacity;
        if (Number.isFinite(Number(settings.marker_size))) style.marker_size = Number(settings.marker_size);
        if (settings.marker_symbol) style.marker_symbol = settings.marker_symbol;
        if (Number.isFinite(Number(settings.outline_width))) style.outline_width = Number(settings.outline_width);
        if (settings.outline_color_mode) style.outline_color_mode = settings.outline_color_mode;
        if (settings.outline_color) style.outline_color = settings.outline_color;
        return style;
      }};
      const mergeRoleStyle = (style, roleStyle, override) => {{
        const merged = Object.assign({{}}, style);
        Object.entries(roleStyle || {{}}).forEach(([key, value]) => {{
          if (!Object.prototype.hasOwnProperty.call(override || {{}}, key)) merged[key] = value;
        }});
        return merged;
      }};
      const visualPreviewLabels = Array.isArray({config_var}.previewLabels) && {config_var}.previewLabels.length
        ? {config_var}.previewLabels.slice()
        : ['POPULATION', 'Group 1', 'Group 2', 'Group 3', 'Group 4'];
      const comparisonLabelsForPalette = (labels, population) => (
        (labels || []).filter((item) => !isPopulationLabel(item, population))
      );
      const paletteIndexForLabel = (label, labels, population, fallbackIndex) => {{
        if (isPopulationLabel(label, population)) return 0;
        const key = normalizeLabelKey(label);
        const comparisonLabels = comparisonLabelsForPalette(labels, population);
        const comparisonIndex = comparisonLabels.findIndex((item) => normalizeLabelKey(item) === key);
        return comparisonIndex >= 0 ? comparisonIndex : fallbackIndex;
      }};
      const paletteIndexForPreviewLabel = (label, population = {{}}) => {{
        const key = normalizeLabelKey(label);
        const comparisonLabels = comparisonLabelsForPalette(visualPreviewLabels, population);
        const index = comparisonLabels.findIndex((item) => normalizeLabelKey(item) === key);
        return index >= 0 ? index : null;
      }};
      const previewLabelsPopulationFirst = (labels, population) => {{
        const populationLabels = [];
        const comparisonLabels = [];
        const seen = new Set();
        (labels || []).forEach((label) => {{
          const clean = stripGroupCount(label);
          const key = normalizeLabelKey(clean);
          if (!key || seen.has(key)) return;
          seen.add(key);
          if (isPopulationLabel(clean, population)) populationLabels.push(clean);
          else comparisonLabels.push(clean);
        }});
        return populationLabels.concat(comparisonLabels);
      }};
      const effectiveSeriesColor = (
        label,
        labelIndex,
        chartKind,
        series,
        palette,
        population,
        comparison,
        overrides
      ) => {{
        const key = normalizeLabelKey(label);
        const populationLike = isPopulationLabel(label, population);
        const paletteIndex = paletteIndexForLabel(label, series.__labels || [], population, labelIndex);
        const override = overrides[key] || {{}};
        let style = {{ color: palette[paletteIndex % Math.max(1, palette.length)] || '#245a5a' }};
        const roleStyle = populationLike
          ? roleStyleFromSettings(population, chartKind)
          : roleStyleFromSettings(comparison, chartKind);
        style = mergeRoleStyle(Object.assign(style, override), roleStyle, override);
        return normalizeColor(style.color, '');
      }};
      const effectiveSeriesColors = (
        labels,
        chartKind,
        series,
        palette,
        population,
        comparison,
        overrides
      ) => {{
        const labelSource = previewLabelsPopulationFirst(labels || [], population);
        const seriesWithLabels = Object.assign({{}}, series || {{}}, {{ __labels: labels || [] }});
        return labelSource
          .map((label, index) => effectiveSeriesColor(
            label,
            index,
            chartKind,
            seriesWithLabels,
            palette,
            population,
            comparison,
            overrides || {{}}
          ))
          .filter(Boolean);
      }};
      const statOverrideKey = (group, stat) => {{
        const groupKey = normalizeLabelKey(group);
        const statKey = normalizeLabelKey(stat);
        return groupKey ? `${{groupKey}}::${{statKey}}` : statKey;
      }};
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
      const traceLooksLikeModelCurve = (trace) => {{
        if (!trace || typeof trace !== 'object') return false;
        const name = String(trace.name || '').trim().toLowerCase();
        const mode = String(trace.mode || '').toLowerCase();
        if (!mode.includes('lines') || isReferenceName(name) || groupStatMatch(name)) return false;
        return name.includes('curve') || name.includes('kde') || name.includes('model');
      }};
      const chartKindForTrace = (trace, chartKind) => {{
        if (traceLooksLikeTrend(trace)) return 'trend';
        if (traceLooksLikeModelCurve(trace)) return 'model_curve';
        if (chartKind === 'trend' && traceHasMarkers(trace)) return 'scatter';
        return chartKind;
      }};

      const chartKindForSpec = (spec) => {{
        const metadata = (spec.metadata && typeof spec.metadata === 'object') ? spec.metadata : {{}};
        const traces = Array.isArray(spec.data) ? spec.data : [];
        const histogramCount = traces.filter((trace) => ['histogram', 'bar'].includes(String(trace.type || '').toLowerCase())).length;
        const kind = String(metadata.kind || '').toLowerCase();
        if (kind === 'histogram' && histogramCount > 1) return 'grouped_histogram';
        if (kind) return kind;
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
          if (isStaticImageLayerProxyTrace(trace)) return;
          if (isMetrolizaPointOverlayTrace(trace)) return;
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

      const contrastOutlineColor = (color) => {{
        const text = String(color || '').trim();
        const match = /^#([0-9a-f]{{2}})([0-9a-f]{{2}})([0-9a-f]{{2}})$/i.exec(text);
        if (!match) return '#111827';
        const red = parseInt(match[1], 16);
        const green = parseInt(match[2], 16);
        const blue = parseInt(match[3], 16);
        const luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255;
        return luminance >= 0.58 ? '#111827' : '#ffffff';
      }};

      const pointMarkOverlayTrace = (mark) => {{
        const color = normalizeColor(mark.color, '#d66e2f');
        const trace = {{
          type: 'scatter',
          mode: 'markers',
          name: 'Point mark',
          x: [cloneJsonValue(mark.x)],
          y: [cloneJsonValue(mark.y)],
          marker: {{
            color,
            size: 15,
            symbol: 'star',
            line: {{
              color: contrastOutlineColor(color),
              width: 1.8,
            }},
          }},
          hovertemplate: 'Marked point<br>x=%{{x}}<br>y=%{{y}}<extra></extra>',
          showlegend: false,
          meta: {{
            dashboard_visual_role: 'point_mark',
            dashboard_visual_preserve_color: true,
            metroliza_trace_schema: 'metroliza.plotly_trace.v1',
            metroliza_role: 'point_mark',
            metroliza_point_mark: true,
            metroliza_point_mark_id: mark.id,
            metroliza_chart_key: mark.chartKey,
            metroliza_curve_number: mark.curveNumber,
            metroliza_point_number: mark.pointNumber,
          }},
        }};
        if (mark.customdata !== undefined) {{
          trace.customdata = [cloneJsonValue(mark.customdata)];
        }}
        if (mark.xaxis) trace.xaxis = mark.xaxis;
        if (mark.yaxis) trace.yaxis = mark.yaxis;
        return trace;
      }};

      const pointSearchOverlayTrace = (point) => {{
        const color = '#1769aa';
        const trace = {{
          type: 'scatter',
          mode: 'markers',
          name: 'Search result',
          x: [cloneJsonValue(point.x)],
          y: [cloneJsonValue(point.y)],
          marker: {{
            color: 'rgba(0,0,0,0)',
            size: 22,
            symbol: 'circle-open',
            line: {{
              color,
              width: 3,
            }},
          }},
          hovertemplate: 'Search result<br>x=%{{x}}<br>y=%{{y}}<extra></extra>',
          showlegend: false,
          meta: {{
            dashboard_visual_role: 'point_search',
            dashboard_visual_preserve_color: true,
            metroliza_trace_schema: 'metroliza.plotly_trace.v1',
            metroliza_role: 'point_search',
            metroliza_point_search: true,
            metroliza_point_search_id: point.id,
            metroliza_chart_key: point.chartKey,
            metroliza_curve_number: point.curveNumber,
            metroliza_point_number: point.pointNumber,
          }},
        }};
        if (point.customdata !== undefined) {{
          trace.customdata = [cloneJsonValue(point.customdata)];
        }}
        if (point.xaxis) trace.xaxis = point.xaxis;
        if (point.yaxis) trace.yaxis = point.yaxis;
        return trace;
      }};

      const applyDashboardPointMarksToPlotlySpec = (spec, chartKey = '') => {{
        if (!spec || typeof spec !== 'object') return spec;
        const normalizedChartKey = String(chartKey || '').trim() || 'dashboard';
        const pointState = sanitizePointMarkState(dashboardPointMarkState || readStoredPointMarks());
        dashboardPointMarkState = pointState;
        const baseData = Array.isArray(spec.data)
          ? spec.data.filter((trace) => !isMetrolizaPointOverlayTrace(trace))
          : [];
        const marks = pointState.marks.filter((mark) => mark.chartKey === normalizedChartKey);
        const searchPoint = dashboardVisualSelectedPoint
          && dashboardVisualSelectedPoint.chartKey === normalizedChartKey
          && dashboardPointSearchMatches.length
          && dashboardPointSearchSelectedId === dashboardVisualSelectedPoint.id
          ? pointSearchOverlayTrace(dashboardVisualSelectedPoint)
          : null;
        spec.data = baseData
          .concat(marks.map((mark) => pointMarkOverlayTrace(mark)))
          .concat(searchPoint ? [searchPoint] : []);
        if (marks.length || searchPoint) {{
          spec.metadata = Object.assign({{}}, spec.metadata || {{}}, {{
            dashboard_point_marks_applied: true,
            dashboard_point_search_applied: Boolean(searchPoint),
          }});
        }}
        return spec;
      }};
      window.metrolizaApplyDashboardPointMarksToPlotlySpec = applyDashboardPointMarksToPlotlySpec;

      const setTraceColor = (trace, color) => {{
        trace.marker = Object.assign({{}}, trace.marker || {{}}, {{ color }});
        trace.line = Object.assign({{}}, trace.line || {{}}, {{ color }});
        const type = String(trace.type || '').toLowerCase();
        if (['violin', 'box', 'scatter'].includes(type)) {{
          trace.fillcolor = color;
        }}
      }};

      const traceHasMarkers = (trace) => String(trace.mode || '').toLowerCase().includes('markers');

      const shouldResetMarkerSymbol = (trace, chartKind) => {{
        if (!traceHasMarkers(trace)) return false;
        const kind = String(chartKind || '').toLowerCase();
        if (kind.startsWith('time_series')) return false;
        return ['scatter', 'distribution'].includes(kind);
      }};

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

      const traceVisibilityKey = (trace) => {{
        if (!trace || typeof trace !== 'object') return '';
        const meta = (trace.meta && typeof trace.meta === 'object') ? trace.meta : {{}};
        const candidates = [
          meta.metroliza_target_id,
          meta.dashboard_visual_target,
          trace.metroliza_static_population_layer_label,
          trace.uid,
          trace.name ? `${{String(trace.type || 'trace')}}:${{String(trace.name)}}` : '',
        ];
        return candidates
          .map((value) => String(value || '').trim())
          .find((value) => value.length > 0) || '';
      }};

      const isRawLayerProxyTrace = (trace) => (
        trace && typeof trace === 'object' && typeof trace.metroliza_raw_layer_index === 'number'
      );

      const isStaticPopulationLayerProxyTrace = (trace) => (
        trace && typeof trace === 'object'
        && typeof trace.metroliza_static_population_layer_index === 'number'
      );

      const isStaticImageLayerProxyTrace = (trace) => (
        isRawLayerProxyTrace(trace) || isStaticPopulationLayerProxyTrace(trace)
      );

      const isMetrolizaPointMarkTrace = (trace) => {{
        if (!trace || typeof trace !== 'object') return false;
        const meta = trace.meta && typeof trace.meta === 'object' ? trace.meta : {{}};
        return Boolean(meta.metroliza_point_mark || meta.dashboard_visual_role === 'point_mark');
      }};

      const isMetrolizaPointSearchTrace = (trace) => {{
        if (!trace || typeof trace !== 'object') return false;
        const meta = trace.meta && typeof trace.meta === 'object' ? trace.meta : {{}};
        return Boolean(meta.metroliza_point_search || meta.dashboard_visual_role === 'point_search');
      }};

      const isMetrolizaPointOverlayTrace = (trace) => (
        isMetrolizaPointMarkTrace(trace) || isMetrolizaPointSearchTrace(trace)
      );

      const preservePlotlyTraceVisibility = (container, nextData) => {{
        const node = typeof container === 'string' ? document.getElementById(container) : container;
        const currentData = node && Array.isArray(node.data) ? node.data : [];
        if (!Array.isArray(nextData) || !currentData.length) {{
          return nextData;
        }}
        const allCurrentTracesHidden = currentData.every((trace) => traceIsHidden(trace));
        const visibilityByKey = new Map();
        const visibilityByIndex = new Map();
        currentData.forEach((trace, index) => {{
          const visibility = traceVisibilityState(trace);
          if (!visibility.hasVisible) return;
          const key = traceVisibilityKey(trace);
          if (key) visibilityByKey.set(key, visibility.value);
          visibilityByIndex.set(index, visibility.value);
        }});
        nextData.forEach((trace, index) => {{
          if (!trace || typeof trace !== 'object') return;
          const key = traceVisibilityKey(trace);
          if (key && visibilityByKey.has(key)) {{
            trace.visible = visibilityByKey.get(key);
          }} else if (!key && visibilityByIndex.has(index)) {{
            trace.visible = visibilityByIndex.get(index);
          }} else if (allCurrentTracesHidden) {{
            trace.visible = 'legendonly';
          }} else if (!allCurrentTracesHidden && Object.prototype.hasOwnProperty.call(trace, 'visible')) {{
            delete trace.visible;
          }}
        }});
        return nextData;
      }};

      const layoutImageVisibilityKey = (image) => {{
        if (!image || typeof image !== 'object') return '';
        const candidates = [
          image.metroliza_raw_layer_label,
          image.metroliza_static_population_layer_label,
          image.name,
          image.source ? `source:${{String(image.source).slice(0, 120)}}` : '',
        ];
        return candidates
          .map((value) => String(value || '').trim())
          .find((value) => value.length > 0) || '';
      }};

      const preservePlotlyLayoutImageVisibility = (container, nextLayout) => {{
        const node = typeof container === 'string' ? document.getElementById(container) : container;
        const currentImages = node && node.layout && Array.isArray(node.layout.images)
          ? node.layout.images
          : [];
        const nextImages = nextLayout && Array.isArray(nextLayout.images) ? nextLayout.images : [];
        if (!currentImages.length || !nextImages.length) {{
          return nextLayout;
        }}
        const visibilityByKey = new Map();
        const visibilityByIndex = new Map();
        currentImages.forEach((image, index) => {{
          if (!image || typeof image !== 'object' || !Object.prototype.hasOwnProperty.call(image, 'visible')) return;
          const key = layoutImageVisibilityKey(image);
          if (key) visibilityByKey.set(key, image.visible);
          visibilityByIndex.set(index, image.visible);
        }});
        nextImages.forEach((image, index) => {{
          if (!image || typeof image !== 'object') return;
          const key = layoutImageVisibilityKey(image);
          if (key && visibilityByKey.has(key)) {{
            image.visible = visibilityByKey.get(key);
          }} else if (!key && visibilityByIndex.has(index)) {{
            image.visible = visibilityByIndex.get(index);
          }}
        }});
        return nextLayout;
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
          preservePlotlyLayoutImageVisibility(container, layout);
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
        for (let leftIndex = 0; leftIndex < palette.length; leftIndex += 1) {{
          for (let rightIndex = leftIndex + 1; rightIndex < palette.length; rightIndex += 1) {{
            const a = hexToRgb(palette[leftIndex]);
            const b = hexToRgb(palette[rightIndex]);
            const distance = Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
            if (distance < 42) return true;
          }}
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
        const populationBaseline = (series.population_baseline && typeof series.population_baseline === 'object')
          ? series.population_baseline
          : {{}};
        const comparisonFocus = (series.comparison_focus && typeof series.comparison_focus === 'object')
          ? series.comparison_focus
          : {{}};
        const seriesOverrides = (series.overrides && typeof series.overrides === 'object') ? series.overrides : {{}};
        const statOverrides = (settings.stat_lines && settings.stat_lines.overrides && typeof settings.stat_lines.overrides === 'object')
          ? settings.stat_lines.overrides
          : {{}};
        const useDistinguishers = Boolean(series.always_distinguish)
          || (Boolean(series.auto_distinguish) && paletteHasSimilarColors(
            effectiveSeriesColors(
              labels,
              chartKind,
              series,
              palette,
              populationBaseline,
              comparisonFocus,
              seriesOverrides
            )
          ));

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
          if (isStaticImageLayerProxyTrace(trace)) return;
          if (isMetrolizaPointOverlayTrace(trace)) return;
          const name = String(trace.name || '');
          const stat = groupStatMatch(name);
          if (stat) {{
            const groupLabel = stat.group || (labels.length === 1 ? labels[0] : '');
            const override = statOverrides[statOverrideKey(groupLabel, stat.stat)] || statOverrides[normalizeLabelKey(stat.stat)] || {{}};
            let color = traceColor(trace);
            if (groupLabel) {{
              const groupIndex = labels.findIndex((item) => normalizeLabelKey(item) === normalizeLabelKey(groupLabel));
              const labelIndex = paletteIndexForLabel(
                groupLabel,
                labels,
                populationBaseline,
                groupIndex >= 0 ? groupIndex : traceIndex
              );
              color = palette[labelIndex % Math.max(1, palette.length)] || color;
            }}
            if (color && !override.color && settings.stat_lines && settings.stat_lines.accent_by_stat) {{
              color = accentColor(color, stat.stat);
            }}
            if (override.color) color = override.color;
            trace.line = Object.assign({{}}, trace.line || {{}});
            if (color) trace.line.color = color;
            const statWidth = Number.isFinite(Number(override.width))
              ? Number(override.width)
              : Number(settings.stat_lines && settings.stat_lines.width);
            if (Number.isFinite(statWidth)) {{
              trace.line.width = Math.max(0, statWidth);
            }}
            if (override.dash) trace.line.dash = override.dash;
            if (Number.isFinite(Number(override.opacity))) {{
              trace.opacity = Math.max(0, Math.min(1, Number(override.opacity)));
            }}
            trace.meta = Object.assign({{}}, trace.meta || {{}}, {{
              dashboard_visual_role: 'stat',
              dashboard_visual_target: `stat:${{statOverrideKey(groupLabel, stat.stat)}}`,
              dashboard_visual_preserve_color: Boolean(color),
              metroliza_trace_schema: 'metroliza.plotly_trace.v1',
              metroliza_role: 'stat',
              metroliza_target_id: `stat:${{statOverrideKey(groupLabel, stat.stat)}}`,
              metroliza_series_id: normalizeLabelKey(groupLabel),
              metroliza_stat_id: normalizeLabelKey(stat.stat),
              metroliza_legend_label: name,
              dashboard_visual_capabilities: ['color', 'opacity', 'width', 'dash'],
              metroliza_style_capabilities: ['color', 'opacity', 'width', 'dash'],
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
            if (Number.isFinite(Number(reference.opacity))) trace.opacity = Math.max(0, Math.min(1, Number(reference.opacity)));
            trace.meta = Object.assign({{}}, trace.meta || {{}}, {{
              dashboard_visual_role: 'reference',
              dashboard_visual_target: `reference:${{referenceKey}}`,
              metroliza_trace_schema: 'metroliza.plotly_trace.v1',
              metroliza_role: 'reference',
              metroliza_target_id: `reference:${{referenceKey}}`,
              metroliza_reference_id: referenceKey,
              metroliza_legend_label: name,
              dashboard_visual_capabilities: ['color', 'opacity', 'width', 'dash'],
              metroliza_style_capabilities: ['color', 'opacity', 'width', 'dash'],
            }});
            return;
          }}

          const traceChartKind = chartKindForTrace(trace, chartKind);
          const isTrendLine = ['trend', 'model_curve'].includes(traceChartKind)
            && (traceLooksLikeTrend(trace) || traceLooksLikeModelCurve(trace));
          const rawLabel = stripGroupCount(name);
          let label = labels.includes(rawLabel) ? rawLabel : null;
          if (!label && labels.length === 1 && ['Frequency', 'Histogram', 'Measurements', ''].includes(name)) {{
            label = labels[0];
          }}
          if (!label && isTrendLine) {{
            label = 'Trend';
          }}
          if (!label && traceLooksLikeModelCurve(trace)) {{
            label = rawLabel;
          }}
          if (!label && !labels.length && rawLabel) {{
            label = rawLabel;
          }}
          if (!label) return;

          const rawLabelIndex = labels.findIndex((item) => normalizeLabelKey(item) === normalizeLabelKey(label));
          const populationLike = isPopulationLabel(label, populationBaseline);
          const labelIndex = paletteIndexForLabel(
            label,
            labels,
            populationBaseline,
            rawLabelIndex >= 0 ? rawLabelIndex : traceIndex
          );
          const override = seriesOverrides[normalizeLabelKey(label)] || {{}};
          let style = {{
            color: palette[labelIndex % Math.max(1, palette.length)] || traceColor(trace),
          }};
          const roleStyle = populationLike
            ? roleStyleFromSettings(populationBaseline, traceChartKind)
            : roleStyleFromSettings(comparisonFocus, traceChartKind);
          style = mergeRoleStyle(Object.assign(style, override), roleStyle, override);
          const color = style.color || traceColor(trace);
          if (color) {{
            if (isTrendLine) setTrendTraceColor(trace, color);
            else setTraceColor(trace, color);
          }}
          const resolvedOpacity = Number(style.opacity);
          if (Number.isFinite(resolvedOpacity)) {{
            trace.opacity = Math.max(0, Math.min(1, resolvedOpacity));
          }}
          if (isTrendLine && trace.line && typeof trace.line === 'object') {{
            if (Number.isFinite(Number(style.width))) trace.line.width = Math.max(0, Number(style.width));
            if (style.dash) trace.line.dash = style.dash;
          }}
          if (!isTrendLine) {{
            trace.marker = Object.assign({{}}, trace.marker || {{}});
            const resolvedMarkerSize = Number.isFinite(Number(style.marker_size)) ? Number(style.marker_size) : Number(series.marker_size);
            if (traceHasMarkers(trace) && Number.isFinite(resolvedMarkerSize)) {{
              trace.marker.size = resolvedMarkerSize;
            }}
            if (traceHasMarkers(trace) && style.marker_symbol) {{
              trace.marker.symbol = style.marker_symbol;
            }} else if (traceHasMarkers(trace) && !populationLike && useDistinguishers && markerSymbols.length) {{
              trace.marker.symbol = markerSymbols[labelIndex % markerSymbols.length];
            }} else if (shouldResetMarkerSymbol(trace, traceChartKind)) {{
              trace.marker.symbol = 'circle';
            }}
            if (['bar', 'histogram'].includes(String(trace.type || '').toLowerCase()) && style.pattern_shape !== undefined) {{
              trace.marker.pattern = Object.assign({{}}, trace.marker.pattern || {{}}, {{
                shape: style.pattern_shape,
              }});
            }} else if (['bar', 'histogram'].includes(String(trace.type || '').toLowerCase()) && !populationLike && useDistinguishers && patterns.length) {{
              trace.marker.pattern = Object.assign({{}}, trace.marker.pattern || {{}}, {{
                shape: patterns[labelIndex % patterns.length],
              }});
            }} else if (['bar', 'histogram'].includes(String(trace.type || '').toLowerCase()) && trace.marker.pattern && typeof trace.marker.pattern === 'object') {{
              trace.marker.pattern.shape = '';
            }}
            if (traceHasMarkers(trace)) {{
              const resolvedOutlineWidth = Number.isFinite(Number(style.outline_width))
                ? Number(style.outline_width)
                : (Number.isFinite(Number(series.outline_width)) ? Number(series.outline_width) : null);
              const outlineMode = style.outline_color_mode || series.outline_color_mode || '';
              let resolvedOutlineColor = style.outline_color || series.outline_color || '';
              if (String(resolvedOutlineColor).toLowerCase() === 'auto' || outlineMode === 'auto') {{
                resolvedOutlineColor = resolvedOutlineWidth && resolvedOutlineWidth > 0
                  ? contrastOutlineColor(trace.marker.color || color)
                  : '';
              }}
              if (resolvedOutlineWidth !== null || resolvedOutlineColor) {{
                trace.marker.line = Object.assign({{}}, trace.marker.line || {{}});
                if (resolvedOutlineWidth !== null) trace.marker.line.width = Math.max(0, resolvedOutlineWidth);
                if (resolvedOutlineColor) trace.marker.line.color = resolvedOutlineColor;
              }}
            }}
          }}
          const role = traceChartKind === 'model_curve' ? 'model_curve' : (isTrendLine ? 'trend' : 'series');
          let visualCapabilities = ['trend', 'model_curve'].includes(role)
            ? ['color', 'opacity', 'width', 'dash']
            : ['color', 'opacity'];
          if (role === 'series' && traceHasMarkers(trace)) {{
            visualCapabilities = visualCapabilities.concat(['marker_size', 'marker_symbol', 'outline_width', 'outline_color', 'outline_color_mode']);
          }}
          if (role === 'series' && ['bar', 'histogram'].includes(String(trace.type || '').toLowerCase())) {{
            visualCapabilities = visualCapabilities.concat(['pattern_shape']);
          }}
          trace.meta = Object.assign({{}}, trace.meta || {{}}, {{
            dashboard_visual_role: role,
            dashboard_visual_target: `${{role}}:${{normalizeLabelKey(label)}}`,
            dashboard_visual_preserve_color: Boolean(color),
            dashboard_visual_chart_kind: traceChartKind,
            metroliza_trace_schema: 'metroliza.plotly_trace.v1',
            metroliza_role: role,
            metroliza_target_id: `${{role}}:${{normalizeLabelKey(label)}}`,
            metroliza_series_id: normalizeLabelKey(label),
            metroliza_chart_kind: traceChartKind,
            metroliza_legend_label: label,
            dashboard_visual_capabilities: visualCapabilities,
            metroliza_style_capabilities: visualCapabilities,
          }});
        }});
        spec.metadata = Object.assign({{}}, spec.metadata || {{}}, {{
          dashboard_visual_settings_applied: true,
        }});
        if (populationBaseline && Object.keys(populationBaseline).length && populationBaseline.draw_first !== false) {{
          spec.data = spec.data
            .map((trace, index) => ({{ trace, index }}))
            .sort((left, right) => {{
              const leftMeta = left.trace && left.trace.meta && typeof left.trace.meta === 'object' ? left.trace.meta : {{}};
              const rightMeta = right.trace && right.trace.meta && typeof right.trace.meta === 'object' ? right.trace.meta : {{}};
              const leftLabel = leftMeta.metroliza_legend_label || (left.trace ? left.trace.name : '');
              const rightLabel = rightMeta.metroliza_legend_label || (right.trace ? right.trace.name : '');
              const leftPopulation = isPopulationLabel(leftLabel, populationBaseline) ? 0 : 1;
              const rightPopulation = isPopulationLabel(rightLabel, populationBaseline) ? 0 : 1;
              return leftPopulation - rightPopulation || left.index - right.index;
            }})
            .map((item) => item.trace);
        }}
        return spec;
      }};

      const setVisualFieldAvailability = (selectorOrId, enabled) => {{
        const control = selectorOrId.startsWith('#')
          ? document.querySelector(selectorOrId)
          : document.getElementById(selectorOrId);
        if (!control) return;
        const field = control.closest('.visual-field');
        if (field) {{
          field.dataset.disabled = enabled ? '0' : '1';
          field.querySelectorAll('input, select').forEach((fieldControl) => {{
            fieldControl.disabled = !enabled;
          }});
        }} else {{
          control.disabled = !enabled;
        }}
      }};

      const syncRangeNumberReadouts = () => {{
        document.querySelectorAll('[data-visual-range-value]').forEach((numberInput) => {{
          let range = null;
          const pairedId = numberInput.getAttribute('data-visual-range-value-for') || '';
          if (pairedId) range = document.getElementById(pairedId);
          if (!range) {{
            const row = numberInput.closest('.visual-range-row');
            range = row ? row.querySelector('input[type="range"]') : null;
          }}
          if (range) numberInput.value = range.value;
        }});
      }};

      const initializeVisualRangeReadouts = () => {{
        document.querySelectorAll('[data-visual-range-value]').forEach((numberInput) => {{
          let range = null;
          const pairedId = numberInput.getAttribute('data-visual-range-value-for') || '';
          if (pairedId) range = document.getElementById(pairedId);
          if (!range) {{
            const row = numberInput.closest('.visual-range-row');
            range = row ? row.querySelector('input[type="range"]') : null;
          }}
          if (!range) return;
          range.addEventListener('input', () => {{ numberInput.value = range.value; }});
          range.addEventListener('change', () => {{ numberInput.value = range.value; }});
          numberInput.addEventListener('input', () => {{
            range.value = numberInput.value;
            range.dispatchEvent(new Event('input', {{ bubbles: true }}));
          }});
          numberInput.addEventListener('change', () => {{
            range.value = numberInput.value;
            range.dispatchEvent(new Event('change', {{ bubbles: true }}));
          }});
        }});
        syncRangeNumberReadouts();
      }};

      const syncVisualControlAvailability = (state) => {{
        const printLocked = state.preset === 'print';
        const customSwatches = state.recipe === 'custom'
          && state.palette_preset === 'custom'
          && state.palette_mode === 'fixed';
        const gradientMode = state.palette_mode === 'auto_gradient' || state.palette_mode === 'highlight_gradient';
        setVisualFieldAvailability('dashboard-visual-palette-preset', !printLocked);
        setVisualFieldAvailability('dashboard-visual-palette-mode', !printLocked);
        setVisualFieldAvailability('dashboard-visual-anchor', !printLocked && gradientMode);
        setVisualFieldAvailability('dashboard-visual-gradient-spread', !printLocked && gradientMode);
        document.querySelectorAll('[data-visual-palette-index]').forEach((input) => {{
          input.disabled = !customSwatches;
          const field = input.closest('.visual-swatch');
          if (field) field.dataset.disabled = customSwatches ? '0' : '1';
        }});
      }};

      const refreshResolvedPalettePreview = (state) => {{
        const palette = resolvedVisualPalette(state, 6);
        const previewStyles = effectiveSeriesColors(
          visualPreviewLabels,
          'grouped_histogram',
          {{ __labels: visualPreviewLabels }},
          palette,
          state.population_baseline || {{}},
          state.comparison_focus || {{}},
          state.series_overrides || {{}}
        );
        document.querySelectorAll('[data-visual-group-chip]').forEach((chip) => {{
          const index = Number(chip.getAttribute('data-visual-chip-index'));
          const color = previewStyles[index % Math.max(1, previewStyles.length)]
            || palette[index % Math.max(1, palette.length)]
            || '#245a5a';
          const swatch = chip.querySelector('.visual-color-chip-swatch');
          if (swatch) swatch.style.backgroundColor = color;
          chip.setAttribute('data-visual-chip-color', color);
        }});
        document.querySelectorAll('[data-visual-palette-index]').forEach((input) => {{
          const index = Number(input.getAttribute('data-visual-palette-index'));
          if (Number.isInteger(index)) {{
            input.value = normalizeColor(palette[index % Math.max(1, palette.length)], '#245a5a');
          }}
        }});
      }};

      const applyVisualStateToControls = (state) => {{
        const activeRecipe = state.recipe === 'distinct' ? 'colorblind_distinct' : state.recipe;
        const setValue = (id, value) => {{
          const control = document.getElementById(id);
          if (control) control.value = value;
        }};
        setValue('dashboard-visual-preset', activeRecipe);
        setValue('dashboard-visual-theme', state.theme_id || '');
        setValue('dashboard-visual-theme-name', state.theme_name || '');
        setValue('dashboard-visual-palette-preset', state.palette_preset || 'metroliza');
        setValue('dashboard-visual-palette-mode', state.palette_mode);
        setValue('dashboard-visual-anchor', state.anchor_color);
        setValue('dashboard-visual-gradient-spread', state.gradient_spread);
        setValue('dashboard-visual-distinguish', state.distinguish);
        setValue('dashboard-visual-marker-size', state.marker_size);
        setValue('dashboard-visual-stat-width', state.stat_lines.width);
        const statAccent = document.getElementById('dashboard-visual-stat-accent');
        if (statAccent) statAccent.checked = Boolean(state.stat_lines.accent_by_stat);
        syncRangeNumberReadouts();
        refreshResolvedPalettePreview(state);
        syncVisualControlAvailability(state);
      }};

      const collectVisualStateFromControls = (presetOverride = null) => {{
        const state = sanitizeVisualState(dashboardVisualState);
        if (presetOverride) {{
          return applyVisualRecipe(presetOverride, state);
        }} else {{
          state.preset = 'custom';
          state.recipe = 'custom';
        }}
        const valueOf = (id, fallback) => {{
          const control = document.getElementById(id);
          return control ? control.value : fallback;
        }};
        state.theme_id = valueOf('dashboard-visual-theme', state.theme_id || '');
        state.theme_name = valueOf('dashboard-visual-theme-name', state.theme_name || '');
        state.palette_preset = valueOf('dashboard-visual-palette-preset', state.palette_preset || 'metroliza');
        state.palette_mode = valueOf('dashboard-visual-palette-mode', state.palette_mode);
        state.anchor_color = valueOf('dashboard-visual-anchor', state.anchor_color);
        state.gradient_spread = valueOf('dashboard-visual-gradient-spread', state.gradient_spread);
        state.distinguish = valueOf('dashboard-visual-distinguish', state.distinguish);
        state.marker_size = Number(valueOf('dashboard-visual-marker-size', state.marker_size));
        state.stat_lines.width = Number(valueOf('dashboard-visual-stat-width', state.stat_lines.width));
        const statAccent = document.getElementById('dashboard-visual-stat-accent');
        if (statAccent) state.stat_lines.accent_by_stat = Boolean(statAccent.checked);
        if (state.palette_preset === 'custom' && state.palette_mode === 'fixed') {{
          document.querySelectorAll('[data-visual-palette-index]').forEach((input) => {{
            const index = Number(input.getAttribute('data-visual-palette-index'));
            if (Number.isInteger(index)) state.palette[index] = input.value;
          }});
        }}
        return sanitizeVisualState(state);
      }};

      const setDashboardVisualState = (state, {{ persist = true, rerender = true }} = {{}}) => {{
        dashboardVisualState = sanitizeVisualState(state);
        applyVisualStateToControls(dashboardVisualState);
        if (dashboardVisualSelectedTarget) rehydrateSelectedVisualTarget();
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
          if (dashboardVisualSelectedTarget) rehydrateSelectedVisualTarget();
        }}, 90);
      }};

      const refreshVisualThemeControls = () => {{
        const select = document.getElementById('dashboard-visual-theme');
        if (!select) return;
        const current = select.value;
        select.innerHTML = '<option value="">Current settings</option>';
        (dashboardVisualThemeLibrary && Array.isArray(dashboardVisualThemeLibrary.themes)
          ? dashboardVisualThemeLibrary.themes
          : []
        ).forEach((theme) => {{
          if (!theme || typeof theme !== 'object') return;
          const option = document.createElement('option');
          option.value = String(theme.id || '');
          option.textContent = String(theme.name || 'Dashboard theme');
          select.appendChild(option);
        }});
        select.value = current;
      }};

      const traceStyleForSelection = (trace) => {{
        const marker = trace && trace.marker && typeof trace.marker === 'object' ? trace.marker : {{}};
        const line = trace && trace.line && typeof trace.line === 'object' ? trace.line : {{}};
        const markerLine = marker.line && typeof marker.line === 'object' ? marker.line : {{}};
        const pattern = marker.pattern && typeof marker.pattern === 'object' ? marker.pattern : {{}};
        return {{
          color: traceColor(trace) || '#245a5a',
          opacity: Number.isFinite(Number(trace && trace.opacity)) ? Number(trace.opacity) : 1,
          width: Number.isFinite(Number(line.width)) ? Number(line.width) : 2,
          dash: typeof line.dash === 'string' ? line.dash : 'solid',
          marker_size: Number.isFinite(Number(marker.size)) ? Number(marker.size) : 7,
          marker_symbol: normalizeMarkerSymbol(marker.symbol, 'circle'),
          outline_width: Number.isFinite(Number(markerLine.width)) ? Number(markerLine.width) : 0,
          outline_color: normalizeColor(markerLine.color, '#111827'),
          outline_color_mode: 'custom',
          pattern_shape: typeof pattern.shape === 'string' ? pattern.shape : '',
        }};
      }};

      const traceCapabilitiesForSelection = (trace, role) => {{
        const meta = trace && trace.meta && typeof trace.meta === 'object' ? trace.meta : {{}};
        const taggedCapabilities = meta.metroliza_style_capabilities
          || meta.dashboard_visual_capabilities
          || meta.metroliza_visual_capabilities;
        if (Array.isArray(taggedCapabilities)) {{
          const caps = {{}};
          taggedCapabilities.forEach((name) => {{
            caps[String(name)] = true;
          }});
          return Object.assign(
            {{
              color: false,
              opacity: false,
              width: false,
              dash: false,
              marker_size: false,
              marker_symbol: false,
              outline_width: false,
              outline_color: false,
              outline_color_mode: false,
              pattern_shape: false,
            }},
            caps
          );
        }}
        const type = String(trace && trace.type || '').toLowerCase();
        const mode = String(trace && trace.mode || '').toLowerCase();
        const lineLike = ['reference', 'stat', 'trend', 'model_curve'].includes(role)
          || mode.includes('lines');
        const markerLike = traceHasMarkers(trace);
        const patternLike = ['bar', 'histogram'].includes(type);
        return {{
          color: true,
          opacity: true,
          width: lineLike,
          dash: lineLike,
          marker_size: markerLike,
          marker_symbol: markerLike,
          outline_width: markerLike,
          outline_color: markerLike,
          outline_color_mode: markerLike,
          pattern_shape: patternLike,
        }};
      }};

      const selectedTargetFromTrace = (trace, curveNumber = -1) => {{
        if (!trace || typeof trace !== 'object') return null;
        if (isStaticImageLayerProxyTrace(trace)) return null;
        if (isMetrolizaPointOverlayTrace(trace)) return null;
        const meta = trace.meta && typeof trace.meta === 'object' ? trace.meta : {{}};
        const roleFromMeta = meta.metroliza_role || meta.dashboard_visual_role || 'series';
        if (meta.metroliza_target_id || meta.dashboard_visual_target) {{
          return {{
            target: meta.metroliza_target_id || meta.dashboard_visual_target,
            role: roleFromMeta,
            label: meta.metroliza_legend_label || trace.name || meta.metroliza_target_id,
            group: meta.metroliza_series_id || '',
            stat: meta.metroliza_stat_id || '',
            key: meta.metroliza_reference_id || '',
            chart_kind: meta.metroliza_chart_kind || meta.dashboard_visual_chart_kind || '',
            style: traceStyleForSelection(trace),
            capabilities: traceCapabilitiesForSelection(trace, roleFromMeta),
            curveNumber,
          }};
        }}
        const name = String(trace.name || '').trim();
        const reference = name.split('=')[0].trim().toLowerCase();
        if (['lsl', 'usl', 'nominal'].includes(reference)) {{
          return {{
            target: `reference:${{reference}}`,
            role: 'reference',
            key: reference,
            chart_kind: meta.metroliza_chart_kind || meta.dashboard_visual_chart_kind || '',
            label: name,
            style: traceStyleForSelection(trace),
            capabilities: traceCapabilitiesForSelection(trace, 'reference'),
            curveNumber,
          }};
        }}
        const stat = groupStatMatch(name);
        if (stat) {{
          return {{
            target: `stat:${{statOverrideKey(stat.group, stat.stat)}}`,
            role: 'stat',
            group: stat.group,
            stat: stat.stat,
            chart_kind: meta.metroliza_chart_kind || meta.dashboard_visual_chart_kind || '',
            label: name,
            style: traceStyleForSelection(trace),
            capabilities: traceCapabilitiesForSelection(trace, 'stat'),
            curveNumber,
          }};
        }}
        if (name) {{
          const role = traceLooksLikeModelCurve(trace) ? 'model_curve' : (traceLooksLikeTrend(trace) ? 'trend' : 'series');
          return {{
            target: `${{role}}:${{normalizeLabelKey(name)}}`,
            role,
            chart_kind: meta.metroliza_chart_kind || meta.dashboard_visual_chart_kind || String(trace.type || ''),
            label: name,
            style: traceStyleForSelection(trace),
            capabilities: traceCapabilitiesForSelection(trace, role),
            curveNumber,
          }};
        }}
        return null;
      }};

      const tracePointValue = (trace, field, pointNumber, fallback) => {{
        if (fallback !== undefined) return cloneJsonValue(fallback);
        const values = trace && trace[field];
        if (Array.isArray(values) && pointNumber >= 0 && pointNumber < values.length) {{
          return cloneJsonValue(values[pointNumber]);
        }}
        return undefined;
      }};

      const selectedPointFromPlotlyClick = (container, point) => {{
        if (!container || !point || typeof point !== 'object') return null;
        const curveNumber = sanitizePointIndex(point.curveNumber);
        const pointNumber = sanitizePointIndex(point.pointNumber);
        if (curveNumber < 0) return null;
        const trace = Array.isArray(container.data) ? container.data[curveNumber] : null;
        if (!trace || isMetrolizaPointOverlayTrace(trace)) return null;
        const x = tracePointValue(trace, 'x', pointNumber, point.x);
        const y = tracePointValue(trace, 'y', pointNumber, point.y);
        if (x === undefined || y === undefined) return null;
        const visualTarget = selectedTargetFromTrace(trace, curveNumber);
        const customdata = point.customdata !== undefined
          ? cloneJsonValue(point.customdata)
          : tracePointValue(trace, 'customdata', pointNumber, undefined);
        const mark = {{
          chartKey: dashboardChartKeyForContainer(container),
          curveNumber,
          pointNumber,
          x,
          y,
          color: dashboardPointMarkState && dashboardPointMarkState.activeColor
            ? dashboardPointMarkState.activeColor
            : '#d66e2f',
          label: visualTarget ? (visualTarget.label || visualTarget.target || '') : String(trace.name || ''),
          target: visualTarget ? (visualTarget.target || '') : String(trace.name || ''),
          customdata,
        }};
        if (typeof trace.xaxis === 'string') mark.xaxis = trace.xaxis;
        if (typeof trace.yaxis === 'string') mark.yaxis = trace.yaxis;
        return sanitizePointMark(mark);
      }};

      const pointSearchValueStrings = (value, depth = 0) => {{
        if (value === undefined || value === null || depth > 2) return [];
        if (Array.isArray(value)) {{
          return value.flatMap((item) => pointSearchValueStrings(item, depth + 1));
        }}
        if (typeof value === 'object') {{
          const parts = [];
          Object.entries(value).forEach(([key, nested]) => {{
            parts.push(String(key));
            parts.push(...pointSearchValueStrings(nested, depth + 1));
          }});
          return parts;
        }}
        const text = String(value).trim();
        return text ? [text] : [];
      }};

      const pointSearchTraceLength = (trace) => {{
        const lengths = ['x', 'y', 'ids', 'text', 'hovertext', 'customdata']
          .map((field) => Array.isArray(trace && trace[field]) ? trace[field].length : 0);
        return Math.max(...lengths, 0);
      }};

      const pointSearchValueAt = (trace, field, pointNumber) => {{
        const values = trace && trace[field];
        if (Array.isArray(values)) return values[pointNumber];
        if (values !== undefined && field !== 'x' && field !== 'y') return values;
        return undefined;
      }};

      const pointSearchEntryForTracePoint = (container, trace, curveNumber, pointNumber) => {{
        const x = pointSearchValueAt(trace, 'x', pointNumber);
        const y = pointSearchValueAt(trace, 'y', pointNumber);
        if (x === undefined || y === undefined) return null;
        const chartKey = dashboardChartKeyForContainer(container);
        const chartLabel = String(container.getAttribute('aria-label') || chartKey || 'Chart');
        const traceName = String(trace.name || `Trace ${{curveNumber + 1}}`);
        const idValue = pointSearchValueAt(trace, 'ids', pointNumber);
        const textValue = pointSearchValueAt(trace, 'text', pointNumber);
        const hoverTextValue = pointSearchValueAt(trace, 'hovertext', pointNumber);
        const customdata = pointSearchValueAt(trace, 'customdata', pointNumber);
        const point = sanitizePointMark({{
          chartKey,
          curveNumber,
          pointNumber,
          x: cloneJsonValue(x),
          y: cloneJsonValue(y),
          color: dashboardPointMarkState && dashboardPointMarkState.activeColor
            ? dashboardPointMarkState.activeColor
            : '#d66e2f',
          label: traceName,
          target: traceName,
          customdata: cloneJsonValue(customdata),
          xaxis: typeof trace.xaxis === 'string' ? trace.xaxis : undefined,
          yaxis: typeof trace.yaxis === 'string' ? trace.yaxis : undefined,
        }});
        if (!point) return null;
        const recordFields = [
          ...pointSearchValueStrings(idValue),
          ...pointSearchValueStrings(customdata),
          ...pointSearchValueStrings(textValue),
          ...pointSearchValueStrings(hoverTextValue),
        ];
        const fields = {{
          record: recordFields,
          trace: [traceName, chartLabel, chartKey],
          x: pointSearchValueStrings(x),
          y: pointSearchValueStrings(y),
          metadata: recordFields,
        }};
        fields.any = [
          ...fields.record,
          ...fields.trace,
          ...fields.x,
          ...fields.y,
          String(pointNumber + 1),
        ];
        const primary = fields.record.find((item) => item) || `${{traceName}} point ${{pointNumber + 1}}`;
        return {{
          id: point.id,
          chartKey,
          container,
          point,
          fields,
          label: `${{primary}} - ${{traceName}}`,
        }};
      }};

      const buildPointSearchIndex = (chartKey = '') => {{
        const requestedChartKey = String(chartKey || '').trim();
        const entries = [];
        document.querySelectorAll('.plotly-chart').forEach((container) => {{
          const containerChartKey = dashboardChartKeyForContainer(container);
          if (requestedChartKey && containerChartKey !== requestedChartKey) return;
          const traces = Array.isArray(container.data) ? container.data : [];
          traces.forEach((trace, curveNumber) => {{
            if (!trace || typeof trace !== 'object') return;
            if (isStaticImageLayerProxyTrace(trace)) return;
            if (isMetrolizaPointOverlayTrace(trace)) return;
            const length = pointSearchTraceLength(trace);
            for (let pointNumber = 0; pointNumber < length; pointNumber += 1) {{
              const entry = pointSearchEntryForTracePoint(container, trace, curveNumber, pointNumber);
              if (entry) entries.push(entry);
            }}
          }});
        }});
        return entries;
      }};

      const pointSearchControls = (root = null) => {{
        if (root && typeof root.querySelector === 'function') {{
          return {{
            query: root.querySelector('[data-dashboard-point-search-input]'),
            scope: root.querySelector('[data-dashboard-point-search-scope]'),
            count: root.querySelector('[data-dashboard-point-search-count]'),
            previous: root.querySelector('[data-dashboard-point-search-prev]'),
            next: root.querySelector('[data-dashboard-point-search-next]'),
            results: root.querySelector('[data-dashboard-point-search-results]'),
          }};
        }}
        return {{
          query: document.getElementById('dashboard-visual-point-search'),
          scope: document.getElementById('dashboard-visual-point-search-scope'),
          count: document.getElementById('dashboard-visual-point-search-count'),
          previous: document.getElementById('dashboard-visual-point-search-prev'),
          next: document.getElementById('dashboard-visual-point-search-next'),
          results: document.getElementById('dashboard-visual-point-search-results'),
        }};
      }};

      const pointSearchTextMatches = (entry, query, scope) => {{
        if (!query) return false;
        const fields = entry.fields[scope] || entry.fields.any || [];
        return fields.some((value) => String(value).toLowerCase().includes(query));
      }};

      const syncPointSearchDefaultScope = (root = null, chartKey = '') => {{
        const controls = pointSearchControls(root);
        if (!controls.scope || controls.scope.dataset.userChosen === '1') return;
        const hasRecordMetadata = buildPointSearchIndex(chartKey).some((entry) => (
          Array.isArray(entry.fields.record) && entry.fields.record.length > 0
        ));
        controls.scope.value = hasRecordMetadata ? 'record' : 'any';
      }};

      const renderPointSearchResults = (controls = pointSearchControls()) => {{
        const count = dashboardPointSearchMatches.length;
        if (controls.count) {{
          if (!count) controls.count.textContent = '0 matches';
          else controls.count.textContent = `${{dashboardPointSearchIndex + 1}} of ${{count}}`;
        }}
        if (controls.previous) controls.previous.disabled = count === 0;
        if (controls.next) controls.next.disabled = count === 0;
        if (!controls.results) return;
        controls.results.innerHTML = '';
        dashboardPointSearchMatches.slice(0, 50).forEach((entry, index) => {{
          const item = document.createElement('li');
          const button = document.createElement('button');
          button.type = 'button';
          button.textContent = entry.label;
          button.title = entry.label;
          button.dataset.searchResultIndex = String(index);
          if (index === dashboardPointSearchIndex) button.dataset.active = '1';
          button.addEventListener('click', () => selectPointSearchMatch(index, {{ scroll: true }}));
          item.appendChild(button);
          controls.results.appendChild(item);
        }});
      }};

      const refreshPointSearch = ({{ selectFirst = true, scroll = false, root = null, chartKey = '' }} = {{}}) => {{
        const controls = pointSearchControls(root);
        const query = String((controls.query && controls.query.value) || '').trim().toLowerCase();
        const scope = String((controls.scope && controls.scope.value) || 'record');
        dashboardPointSearchMatches = query
          ? buildPointSearchIndex(chartKey).filter((entry) => pointSearchTextMatches(entry, query, scope))
          : [];
        dashboardPointSearchIndex = dashboardPointSearchMatches.length && selectFirst ? 0 : -1;
        dashboardPointSearchSelectedId = '';
        renderPointSearchResults(controls);
        if (dashboardPointSearchIndex >= 0) {{
          selectPointSearchMatch(dashboardPointSearchIndex, {{ scroll, root }});
        }} else if (typeof refreshPlotlyCharts === 'function') {{
          scheduleVisualRefresh();
        }}
        syncInlinePointControls();
      }};

      const selectPointSearchMatch = (index, {{ scroll = true, root = null }} = {{}}) => {{
        const count = dashboardPointSearchMatches.length;
        if (!count) {{
          dashboardPointSearchIndex = -1;
          renderPointSearchResults(pointSearchControls(root));
          return;
        }}
        dashboardPointSearchIndex = ((index % count) + count) % count;
        const entry = dashboardPointSearchMatches[dashboardPointSearchIndex];
        dashboardVisualSelectedPoint = entry.point;
        dashboardPointSearchSelectedId = entry.point.id;
        syncPointMarkControls();
        renderPointSearchResults(pointSearchControls(root));
        syncInlinePointControls();
        if (scroll && entry.container && typeof entry.container.scrollIntoView === 'function') {{
          entry.container.setAttribute('tabindex', '-1');
          entry.container.scrollIntoView({{ block: 'center', behavior: 'smooth' }});
          if (typeof entry.container.focus === 'function') {{
            entry.container.focus({{ preventScroll: true }});
          }}
        }}
        if (typeof refreshPlotlyCharts === 'function') scheduleVisualRefresh();
      }};

      const movePointSearch = (delta, {{ root = null, chartKey = '', scroll = true }} = {{}}) => {{
        const requestedChartKey = String(chartKey || '').trim();
        const matchesCurrentChart = !requestedChartKey
          || dashboardPointSearchMatches.every((entry) => entry.chartKey === requestedChartKey);
        if (!dashboardPointSearchMatches.length || !matchesCurrentChart) {{
          refreshPointSearch({{ selectFirst: true, scroll, root, chartKey: requestedChartKey }});
          return;
        }}
        selectPointSearchMatch(dashboardPointSearchIndex + delta, {{ scroll, root }});
      }};

      const selectedPointMarkIndex = (state = dashboardPointMarkState) => {{
        const point = dashboardVisualSelectedPoint;
        if (!point || !state || !Array.isArray(state.marks)) return -1;
        return state.marks.findIndex((mark) => mark.id === point.id);
      }};

      const pointMarkSummaryText = (point) => {{
        if (!point) return 'None selected';
        const source = point.label || point.target || `Trace ${{point.curveNumber + 1}}`;
        const pointLabel = point.pointNumber >= 0 ? `point ${{point.pointNumber + 1}}` : 'point';
        return `${{source}} - ${{pointLabel}}`;
      }};

      const dashboardPointControlChartKey = (controls) => (
        String(controls && controls.dataset ? controls.dataset.dashboardChartKey || '' : '').trim()
      );

      const selectedPointMatchesChart = (chartKey) => (
        Boolean(
          dashboardVisualSelectedPoint
          && (!chartKey || dashboardVisualSelectedPoint.chartKey === chartKey)
        )
      );

      const syncInlinePointControls = () => {{
        dashboardPointMarkState = sanitizePointMarkState(dashboardPointMarkState || readStoredPointMarks());
        document.querySelectorAll('[data-dashboard-point-controls]').forEach((controls) => {{
          const chartKey = dashboardPointControlChartKey(controls);
          const selectedInChart = selectedPointMatchesChart(chartKey);
          const selectedIndex = selectedInChart ? selectedPointMarkIndex(dashboardPointMarkState) : -1;
          const summary = controls.querySelector('[data-dashboard-point-summary]');
          const color = controls.querySelector('[data-dashboard-point-color]');
          const markButton = controls.querySelector('[data-dashboard-point-mark]');
          const clearButton = controls.querySelector('[data-dashboard-point-clear]');
          if (summary) summary.textContent = selectedInChart
            ? pointMarkSummaryText(dashboardVisualSelectedPoint)
            : 'None selected';
          if (color) color.value = normalizeColor(dashboardPointMarkState.activeColor, '#d66e2f');
          if (markButton) markButton.disabled = !selectedInChart;
          if (clearButton) clearButton.disabled = !selectedInChart || selectedIndex < 0;
          controls.dataset.hasSelected = selectedInChart ? '1' : '0';
        }});
      }};

      const syncPointMarkControls = () => {{
        dashboardPointMarkState = sanitizePointMarkState(dashboardPointMarkState || readStoredPointMarks());
        const summary = document.getElementById('dashboard-visual-point-summary');
        const color = document.getElementById('dashboard-visual-point-color');
        const markButton = document.getElementById('dashboard-visual-point-mark');
        const clearButton = document.getElementById('dashboard-visual-point-clear');
        const clearAllButton = document.getElementById('dashboard-visual-point-clear-all');
        const selected = Boolean(dashboardVisualSelectedPoint);
        const selectedIndex = selectedPointMarkIndex(dashboardPointMarkState);
        if (summary) summary.textContent = pointMarkSummaryText(dashboardVisualSelectedPoint);
        if (color) color.value = normalizeColor(dashboardPointMarkState.activeColor, '#d66e2f');
        if (markButton) markButton.disabled = !selected;
        if (clearButton) clearButton.disabled = !selected || selectedIndex < 0;
        if (clearAllButton) clearAllButton.disabled = dashboardPointMarkState.marks.length === 0;
        syncInlinePointControls();
      }};

      const setDashboardPointMarkState = (state, {{ persist = true, rerender = true }} = {{}}) => {{
        dashboardPointMarkState = sanitizePointMarkState(state);
        if (persist) persistPointMarks(dashboardPointMarkState);
        syncPointMarkControls();
        if (rerender && typeof refreshPlotlyCharts === 'function') {{
          scheduleVisualRefresh();
        }}
      }};

      const pointMarkColorInput = (control = null) => {{
        const candidate = control && control.target ? control.target : control;
        if (
          candidate
          && typeof candidate.matches === 'function'
          && candidate.matches('input[type="color"]')
        ) {{
          return candidate;
        }}
        return document.getElementById('dashboard-visual-point-color')
          || document.querySelector('[data-dashboard-point-color]');
      }};

      const markSelectedPoint = (colorControl = null) => {{
        if (!dashboardVisualSelectedPoint) return;
        const state = sanitizePointMarkState(dashboardPointMarkState || readStoredPointMarks());
        const color = pointMarkColorInput(colorControl);
        state.activeColor = normalizeColor(color ? color.value : state.activeColor, '#d66e2f');
        const mark = sanitizePointMark(Object.assign({{}}, dashboardVisualSelectedPoint, {{
          color: state.activeColor,
        }}));
        if (!mark) return;
        const index = state.marks.findIndex((item) => item.id === mark.id);
        if (index >= 0) state.marks[index] = mark;
        else state.marks.push(mark);
        dashboardVisualSelectedPoint = mark;
        setDashboardPointMarkState(state);
      }};

      const clearSelectedPointMark = () => {{
        if (!dashboardVisualSelectedPoint) return;
        const state = sanitizePointMarkState(dashboardPointMarkState || readStoredPointMarks());
        state.marks = state.marks.filter((mark) => mark.id !== dashboardVisualSelectedPoint.id);
        setDashboardPointMarkState(state);
      }};

      const clearAllPointMarks = () => {{
        const state = sanitizePointMarkState(dashboardPointMarkState || readStoredPointMarks());
        state.marks = [];
        setDashboardPointMarkState(state);
      }};

      const applyPointMarkColorFromControl = (colorControl = null) => {{
        const color = pointMarkColorInput(colorControl);
        const state = sanitizePointMarkState(dashboardPointMarkState || readStoredPointMarks());
        state.activeColor = normalizeColor(color ? color.value : state.activeColor, '#d66e2f');
        const index = selectedPointMarkIndex(state);
        if (index >= 0) {{
          state.marks[index] = Object.assign({{}}, state.marks[index], {{ color: state.activeColor }});
          dashboardVisualSelectedPoint = state.marks[index];
        }}
        setDashboardPointMarkState(state, {{ rerender: index >= 0 }});
      }};

      const createInlinePointControls = (chartKey) => {{
        const controls = document.createElement('div');
        controls.className = 'plotly-point-controls';
        controls.dataset.dashboardPointControls = '1';
        controls.dataset.dashboardChartKey = String(chartKey || '');
        controls.setAttribute('aria-label', 'Point marking controls');
        controls.innerHTML = ''
          + '<label class="plotly-point-search-field"><span>Find point</span>'
          + '<input type="search" data-dashboard-point-search-input placeholder="TraceCode or value"></label>'
          + '<label class="plotly-point-scope-field"><span>Scope</span>'
          + '<select data-dashboard-point-search-scope>'
          + '<option value="record">Record</option>'
          + '<option value="any">Any field</option>'
          + '<option value="trace">Trace</option>'
          + '<option value="x">X</option>'
          + '<option value="y">Y</option>'
          + '<option value="metadata">Metadata</option>'
          + '</select></label>'
          + '<div class="plotly-point-nav" role="group" aria-label="Point search matches">'
          + '<button type="button" data-dashboard-point-search-prev>Prev</button>'
          + '<output data-dashboard-point-search-count>0 matches</output>'
          + '<button type="button" data-dashboard-point-search-next>Next</button>'
          + '</div>'
          + '<label class="plotly-point-color-field"><span>Color</span>'
          + '<input type="color" data-dashboard-point-color value="#d66e2f"></label>'
          + '<div class="plotly-point-actions" role="group" aria-label="Point mark actions">'
          + '<button type="button" data-dashboard-point-mark>Mark selected</button>'
          + '<button type="button" data-dashboard-point-clear>Clear selected</button>'
          + '</div>'
          + '<output class="plotly-point-selection" data-dashboard-point-summary>None selected</output>';
        return controls;
      }};

      const bindInlinePointControls = (controls) => {{
        if (!controls || controls.dataset.dashboardPointControlsBound === '1') return;
        controls.dataset.dashboardPointControlsBound = '1';
        const chartKey = dashboardPointControlChartKey(controls);
        const searchInput = controls.querySelector('[data-dashboard-point-search-input]');
        const searchScope = controls.querySelector('[data-dashboard-point-search-scope]');
        const previous = controls.querySelector('[data-dashboard-point-search-prev]');
        const next = controls.querySelector('[data-dashboard-point-search-next]');
        const color = controls.querySelector('[data-dashboard-point-color]');
        const markButton = controls.querySelector('[data-dashboard-point-mark]');
        const clearButton = controls.querySelector('[data-dashboard-point-clear]');
        if (searchInput) {{
          searchInput.addEventListener('input', () => refreshPointSearch({{
            selectFirst: true,
            scroll: false,
            root: controls,
            chartKey,
          }}));
          searchInput.addEventListener('keydown', (event) => {{
            if (event.key === 'Enter') {{
              event.preventDefault();
              movePointSearch(1, {{ root: controls, chartKey, scroll: true }});
            }}
          }});
        }}
        if (searchScope) {{
          searchScope.addEventListener('change', () => {{
            searchScope.dataset.userChosen = '1';
            refreshPointSearch({{ selectFirst: true, scroll: false, root: controls, chartKey }});
          }});
        }}
        if (previous) {{
          previous.addEventListener('click', () => movePointSearch(-1, {{
            root: controls,
            chartKey,
            scroll: true,
          }}));
        }}
        if (next) {{
          next.addEventListener('click', () => movePointSearch(1, {{
            root: controls,
            chartKey,
            scroll: true,
          }}));
        }}
        if (color) {{
          color.addEventListener('input', () => applyPointMarkColorFromControl(color));
          color.addEventListener('change', () => applyPointMarkColorFromControl(color));
        }}
        if (markButton) {{
          markButton.addEventListener('click', () => {{
            if (!selectedPointMatchesChart(chartKey)) return;
            markSelectedPoint(color);
          }});
        }}
        if (clearButton) {{
          clearButton.addEventListener('click', () => {{
            if (!selectedPointMatchesChart(chartKey)) return;
            clearSelectedPointMark();
          }});
        }}
        syncPointSearchDefaultScope(controls, chartKey);
        renderPointSearchResults(pointSearchControls(controls));
      }};

      const ensureInlinePointControls = () => {{
        document.querySelectorAll('.plotly-chart').forEach((container) => {{
          const parent = container.parentElement;
          if (!parent) return;
          const chartKey = dashboardChartKeyForContainer(container);
          let controls = Array.from(parent.querySelectorAll('[data-dashboard-point-controls]'))
            .find((candidate) => dashboardPointControlChartKey(candidate) === chartKey);
          if (!controls) {{
            controls = createInlinePointControls(chartKey);
            container.insertAdjacentElement('afterend', controls);
          }}
          bindInlinePointControls(controls);
        }});
        syncInlinePointControls();
      }};
      window.metrolizaEnsureInlinePointControls = ensureInlinePointControls;

      const collectVisualTargets = () => {{
        const targets = new Map();
        document.querySelectorAll('.plotly-chart').forEach((node) => {{
          const data = Array.isArray(node.data) ? node.data : [];
          data.forEach((trace, index) => {{
            const target = selectedTargetFromTrace(trace, index);
            if (target && target.target) {{
              target.selection_key = target.selection_key
                || `${{target.chart_kind || 'plot'}}:${{target.target}}:${{index}}`;
              if (!targets.has(target.selection_key)) targets.set(target.selection_key, target);
            }}
          }});
        }});
        return Array.from(targets.values());
      }};

      const refreshVisualElementControls = () => {{
        const select = document.getElementById('dashboard-visual-element');
        if (!select) return;
        const current = dashboardVisualSelectedTarget && dashboardVisualSelectedTarget.selection_key
          ? dashboardVisualSelectedTarget.selection_key
          : '';
        const targets = collectVisualTargets();
        select.innerHTML = '<option value="">Click a plot element</option>';
        targets.forEach((target) => {{
          const option = document.createElement('option');
          option.value = target.selection_key || target.target;
          const chartLabel = target.chart_kind
            ? `${{String(target.chart_kind).replace(/_/g, ' ')}} - `
            : '';
          option.textContent = `${{chartLabel}}${{target.label || target.target}}`;
          option.dataset.visualTarget = JSON.stringify(target);
          select.appendChild(option);
        }});
        select.value = current;
        const seriesTargets = orderSeriesTargetsPopulationFirst(
          targets.filter((target) => target.role === 'series')
        );
        document.querySelectorAll('[data-visual-group-chip]').forEach((chip) => {{
          const index = Number(chip.getAttribute('data-visual-chip-index'));
          const label = chip.querySelector('.visual-color-chip-label');
          const target = Number.isInteger(index) ? seriesTargets[index] : null;
          if (label && target) label.textContent = target.label || target.target;
        }});
      }};

      const rehydrateSelectedVisualTarget = () => {{
        if (!dashboardVisualSelectedTarget) {{
          syncSelectedElementControls(null);
          return;
        }}
        const previous = dashboardVisualSelectedTarget;
        const targets = collectVisualTargets();
        const match = targets.find((target) => (
          (previous.selection_key && target.selection_key === previous.selection_key)
          || (previous.target && target.target === previous.target)
        ));
        if (match) {{
          applySelectedVisualTargetToControls(match);
          return;
        }}
        dashboardVisualSelectedTarget = null;
        refreshVisualElementControls();
        syncSelectedElementControls(null);
      }};

      const orderSeriesTargetsPopulationFirst = (targets, state = dashboardVisualState) => {{
        const population = state && state.population_baseline && typeof state.population_baseline === 'object'
          ? state.population_baseline
          : {{}};
        return (targets || [])
          .map((target, index) => ({{ target, index }}))
          .sort((left, right) => {{
            const leftLabel = left.target && (left.target.label || left.target.group || left.target.target);
            const rightLabel = right.target && (right.target.label || right.target.group || right.target.target);
            const leftPopulation = isPopulationLabel(leftLabel, population) ? 0 : 1;
            const rightPopulation = isPopulationLabel(rightLabel, population) ? 0 : 1;
            return leftPopulation - rightPopulation || left.index - right.index;
          }})
          .map((item) => item.target);
      }};

      const selectVisualTargetByChipIndex = (index) => {{
        const targets = collectVisualTargets();
        const seriesTargets = orderSeriesTargetsPopulationFirst(
          targets.filter((target) => target.role === 'series')
        );
        const target = seriesTargets[index] || targets[index] || null;
        if (target) applySelectedVisualTargetToControls(target);
      }};

      const selectedTargetOverrideKey = (target) => (
        normalizeLabelKey(target.group || target.label || target.target)
      );

      const selectedTargetChartKind = (target) => {{
        const raw = String(target && target.chart_kind || '').trim().toLowerCase();
        if (raw === 'violin') return 'distribution';
        if (['histogram', 'grouped_histogram', 'distribution', 'iqr', 'scatter', 'trend', 'model_curve'].includes(raw)) {{
          return raw;
        }}
        const role = String(target && target.role || '').toLowerCase();
        if (['trend', 'model_curve'].includes(role)) return role;
        return 'grouped_histogram';
      }};

      const selectionSeriesLabels = (fallbackLabel = '') => {{
        const labels = collectVisualTargets()
          .filter((target) => target.role === 'series')
          .map((target) => stripGroupCount(target.label || target.group || target.target))
          .filter(Boolean);
        const key = normalizeLabelKey(fallbackLabel);
        if (key && !labels.some((label) => normalizeLabelKey(label) === key)) {{
          labels.push(fallbackLabel);
        }}
        return labels.length ? labels : visualPreviewLabels.slice();
      }};

      const resolvedSelectedSeriesStyle = (target, state, currentStyle = {{}}) => {{
        const label = stripGroupCount(target.label || target.group || target.target);
        const labels = selectionSeriesLabels(label);
        const population = state.population_baseline || {{}};
        const comparison = state.comparison_focus || {{}};
        const palette = resolvedVisualPalette(state, Math.max(1, labels.length, 6));
        const fallbackIndex = labels.findIndex((item) => normalizeLabelKey(item) === normalizeLabelKey(label));
        const paletteIndex = paletteIndexForLabel(
          label,
          labels,
          population,
          fallbackIndex >= 0 ? fallbackIndex : 0
        );
        const override = state.series_overrides[selectedTargetOverrideKey(target)] || {{}};
        let style = {{
          color: palette[paletteIndex % Math.max(1, palette.length)] || currentStyle.color || '#245a5a',
        }};
        const roleStyle = isPopulationLabel(label, population)
          ? roleStyleFromSettings(population, selectedTargetChartKind(target))
          : roleStyleFromSettings(comparison, selectedTargetChartKind(target));
        style = mergeRoleStyle(Object.assign(style, override), roleStyle, override);
        return Object.assign({{}}, currentStyle, style);
      }};

      const setSelectedElementFieldAvailability = (name, enabled) => {{
        const field = document.querySelector(`[data-visual-selected-field="${{name}}"]`);
        if (!field) return;
        field.dataset.disabled = enabled ? '0' : '1';
        field.hidden = !enabled;
        field.querySelectorAll('input, select').forEach((control) => {{
          control.disabled = !enabled;
        }});
      }};

      const syncSelectedElementControls = (target) => {{
        const caps = target && target.capabilities ? target.capabilities : {{}};
        [
          'color',
          'opacity',
          'width',
          'dash',
          'marker_size',
          'marker_symbol',
          'pattern_shape',
          'outline_enabled',
          'outline_width',
          'outline_color_mode',
          'outline_color',
        ].forEach((name) => {{
          setSelectedElementFieldAvailability(name, Boolean(target && caps[name]));
        }});
        const outlineAvailable = Boolean(
          target && (caps.outline_width || caps.outline_color || caps.outline_color_mode)
        );
        setSelectedElementFieldAvailability('outline_enabled', outlineAvailable);
        const outlineEnabled = Boolean(
          outlineAvailable
          && document.getElementById('dashboard-visual-element-outline-enabled')
          && document.getElementById('dashboard-visual-element-outline-enabled').checked
        );
        setSelectedElementFieldAvailability('outline_width', outlineEnabled);
        setSelectedElementFieldAvailability('outline_color_mode', outlineEnabled);
        const outlineMode = document.getElementById('dashboard-visual-element-outline-color-mode');
        setSelectedElementFieldAvailability(
          'outline_color',
          outlineEnabled && outlineMode && outlineMode.value === 'custom'
        );
      }};

      const applySelectedVisualTargetToControls = (target) => {{
        dashboardVisualSelectedTarget = target;
        refreshVisualElementControls();
        const color = document.getElementById('dashboard-visual-element-color');
        const opacity = document.getElementById('dashboard-visual-element-opacity');
        const width = document.getElementById('dashboard-visual-element-width');
        const dash = document.getElementById('dashboard-visual-element-dash');
        const markerSize = document.getElementById('dashboard-visual-element-marker-size');
        const markerSymbol = document.getElementById('dashboard-visual-element-marker-symbol');
        const outlineEnabled = document.getElementById('dashboard-visual-element-outline-enabled');
        const outlineWidth = document.getElementById('dashboard-visual-element-outline-width');
        const outlineColorMode = document.getElementById('dashboard-visual-element-outline-color-mode');
        const outlineColor = document.getElementById('dashboard-visual-element-outline-color');
        const pattern = document.getElementById('dashboard-visual-element-pattern');
        syncSelectedElementControls(target);
        if (!target) return;
        const state = sanitizeVisualState(dashboardVisualState);
        const currentStyle = target.style && typeof target.style === 'object' ? target.style : {{}};
        let style = {{}};
        if (target.role === 'reference' && target.key && state.reference_lines[target.key]) {{
          style = state.reference_lines[target.key];
        }} else if (target.role === 'stat') {{
          style = state.stat_line_overrides[statOverrideKey(target.group, target.stat)] || {{}};
        }} else if (target.role === 'series') {{
          style = resolvedSelectedSeriesStyle(target, state, currentStyle);
        }} else {{
          style = state.series_overrides[selectedTargetOverrideKey(target)] || {{}};
        }}
        if (color) color.value = normalizeColor(style.color, normalizeColor(currentStyle.color, '#245a5a'));
        if (opacity) opacity.value = Number.isFinite(Number(style.opacity)) ? style.opacity : (currentStyle.opacity ?? 1);
        if (width) width.value = Number.isFinite(Number(style.width)) ? style.width : (currentStyle.width ?? 2);
        if (dash) dash.value = style.dash || currentStyle.dash || 'solid';
        if (markerSize) markerSize.value = Number.isFinite(Number(style.marker_size)) ? style.marker_size : (currentStyle.marker_size ?? state.marker_size);
        if (markerSymbol) markerSymbol.value = style.marker_symbol || currentStyle.marker_symbol || 'circle';
        const styleOutlineWidth = Number.isFinite(Number(style.outline_width))
          ? Number(style.outline_width)
          : (Number.isFinite(Number(currentStyle.outline_width)) ? Number(currentStyle.outline_width) : 0);
        if (outlineEnabled) outlineEnabled.checked = styleOutlineWidth > 0;
        if (outlineWidth) outlineWidth.value = styleOutlineWidth > 0 ? styleOutlineWidth : 1.25;
        if (outlineColorMode) outlineColorMode.value = style.outline_color_mode || currentStyle.outline_color_mode || 'auto';
        if (outlineColor) outlineColor.value = normalizeColor(style.outline_color, normalizeColor(currentStyle.outline_color, '#111827'));
        if (pattern) pattern.value = typeof style.pattern_shape === 'string' ? style.pattern_shape : (currentStyle.pattern_shape || '');
        syncRangeNumberReadouts();
        syncSelectedElementControls(target);
      }};

      const applySelectedElementStyle = () => {{
        if (!dashboardVisualSelectedTarget) return;
        const state = sanitizeVisualState(dashboardVisualState);
        state.preset = 'custom';
        state.recipe = 'custom';
        const target = dashboardVisualSelectedTarget;
        const caps = target.capabilities || {{}};
        const color = document.getElementById('dashboard-visual-element-color');
        const opacity = document.getElementById('dashboard-visual-element-opacity');
        const width = document.getElementById('dashboard-visual-element-width');
        const dash = document.getElementById('dashboard-visual-element-dash');
        const markerSize = document.getElementById('dashboard-visual-element-marker-size');
        const markerSymbol = document.getElementById('dashboard-visual-element-marker-symbol');
        const outlineEnabled = document.getElementById('dashboard-visual-element-outline-enabled');
        const outlineWidth = document.getElementById('dashboard-visual-element-outline-width');
        const outlineColorMode = document.getElementById('dashboard-visual-element-outline-color-mode');
        const outlineColor = document.getElementById('dashboard-visual-element-outline-color');
        const pattern = document.getElementById('dashboard-visual-element-pattern');
        const style = {{}};
        if (caps.color && color) style.color = color.value;
        if (caps.opacity && opacity) style.opacity = Number(opacity.value);
        if (caps.width && width) style.width = Number(width.value);
        if (caps.dash && dash) style.dash = dash.value;
        if (caps.marker_size && markerSize) style.marker_size = Number(markerSize.value);
        if (caps.marker_symbol && markerSymbol) style.marker_symbol = normalizeMarkerSymbol(markerSymbol.value, 'circle');
        if ((caps.outline_width || caps.outline_color || caps.outline_color_mode) && outlineEnabled) {{
          style.outline_width = outlineEnabled.checked && outlineWidth ? Number(outlineWidth.value) : 0;
          style.outline_color_mode = outlineColorMode ? outlineColorMode.value : 'auto';
          if (style.outline_color_mode === 'custom' && outlineColor) {{
            style.outline_color = outlineColor.value;
          }}
        }}
        if (caps.pattern_shape && pattern) style.pattern_shape = pattern.value;
        if (target.role === 'reference' && target.key && state.reference_lines[target.key]) {{
          state.reference_lines[target.key] = Object.assign({{}}, state.reference_lines[target.key], style);
        }} else if (target.role === 'stat') {{
          state.stat_line_overrides[statOverrideKey(target.group, target.stat)] = style;
        }} else {{
          const overrideKey = selectedTargetOverrideKey(target);
          if (target.role === 'series' && isPopulationLabel(target.label || target.group, state.population_baseline)) {{
            const populationStyle = Object.assign({{}}, style);
            if (Object.prototype.hasOwnProperty.call(populationStyle, 'opacity')) {{
              const opacity = Object.assign(
                {{}},
                state.population_baseline && typeof state.population_baseline.opacity === 'object'
                  ? state.population_baseline.opacity
                  : {{}}
              );
              opacity[selectedTargetChartKind(target)] = populationStyle.opacity;
              populationStyle.opacity = opacity;
            }}
            state.population_baseline = Object.assign({{}}, state.population_baseline || {{}}, populationStyle);
            delete state.series_overrides[overrideKey];
          }} else {{
            const paletteIndex = paletteIndexForPreviewLabel(
              target.label || target.group,
              state.population_baseline || {{}}
            );
            if (paletteIndex !== null && style.color) {{
              state.palette = resolvedVisualPalette(state, 6).slice();
              while (state.palette.length < 6) state.palette.push('#245a5a');
              state.palette[paletteIndex] = style.color;
              state.palette_preset = 'custom';
              state.palette_mode = 'fixed';
              delete style.color;
            }}
            if (Object.keys(style).length) state.series_overrides[overrideKey] = style;
            else delete state.series_overrides[overrideKey];
          }}
          }}
        setDashboardVisualState(state);
        applySelectedVisualTargetToControls(target);
      }};

      const resetSelectedSeriesPaletteEntry = (state, embedded, target) => {{
        const paletteIndex = paletteIndexForPreviewLabel(
          target.label || target.group,
          state.population_baseline || {{}}
        );
        if (paletteIndex === null) return;
        const resetPalette = resolvedVisualPalette(embedded, 6).slice();
        const nextPalette = resolvedVisualPalette(state, 6).slice();
        while (resetPalette.length < 6) resetPalette.push('#245a5a');
        while (nextPalette.length < 6) nextPalette.push('#245a5a');
        nextPalette[paletteIndex] = resetPalette[paletteIndex] || '#245a5a';
        state.palette = nextPalette;
        if (nextPalette.every((color, index) => (
          normalizeColor(color, '') === normalizeColor(resetPalette[index], '')
        ))) {{
          state.palette_preset = embedded.palette_preset;
          state.palette_mode = embedded.palette_mode;
        }}
      }};

      const resetSelectedElementStyle = () => {{
        if (!dashboardVisualSelectedTarget) return;
        const state = sanitizeVisualState(dashboardVisualState);
        const embedded = embeddedInitialVisualState();
        const target = dashboardVisualSelectedTarget;
        if (target.role === 'reference' && target.key && state.reference_lines[target.key]) {{
          state.reference_lines[target.key] = clonePlotlySpec(embedded.reference_lines[target.key]);
        }} else if (target.role === 'stat') {{
          delete state.stat_line_overrides[statOverrideKey(target.group, target.stat)];
        }} else if (target.role === 'series' && isPopulationLabel(target.label || target.group, state.population_baseline)) {{
          state.population_baseline = clonePlotlySpec(embedded.population_baseline || dashboardVisualConfig.defaults.population_baseline || {{}});
        }} else {{
          delete state.series_overrides[selectedTargetOverrideKey(target)];
          if (target.role === 'series') {{
            resetSelectedSeriesPaletteEntry(state, embedded, target);
          }}
        }}
        setDashboardVisualState(state);
        applySelectedVisualTargetToControls(target);
      }};

      window.metrolizaInstallVisualSelectionHandlers = (target) => {{
        if (!target || target.__metrolizaVisualSelectionHandlers) return;
        target.__metrolizaVisualSelectionHandlers = true;
        const handleCurve = (curveNumber) => {{
          const trace = Array.isArray(target.data) ? target.data[curveNumber] : null;
          const visualTarget = selectedTargetFromTrace(trace, curveNumber);
          if (visualTarget) applySelectedVisualTargetToControls(visualTarget);
        }};
        target.on('plotly_click', (eventData) => {{
          const point = eventData && eventData.points && eventData.points[0];
          if (point && typeof point.curveNumber === 'number') {{
            const trace = Array.isArray(target.data) ? target.data[point.curveNumber] : null;
            if (isMetrolizaPointOverlayTrace(trace)) return;
            dashboardVisualSelectedPoint = selectedPointFromPlotlyClick(target, point);
            dashboardPointSearchSelectedId = '';
            syncPointMarkControls();
            handleCurve(point.curveNumber);
          }}
        }});
        target.on('plotly_legendclick', (eventData) => {{
          if (eventData && typeof eventData.curveNumber === 'number') handleCurve(eventData.curveNumber);
        }});
      }};

      const initializeDashboardVisualControls = () => {{
        dashboardVisualThemeLibrary = readVisualThemeLibrary();
        dashboardVisualState = readStoredVisualState();
        dashboardPointMarkState = readStoredPointMarks();
        refreshVisualThemeControls();
        initializeVisualRangeReadouts();
        applyVisualStateToControls(dashboardVisualState);
        ensureInlinePointControls();
        syncPointMarkControls();
        renderPointSearchResults();
        const dialog = document.getElementById('dashboard-visual-dialog');
        const openButton = document.getElementById('dashboard-visuals-open');
        const closeButton = document.getElementById('dashboard-visuals-close');
        const resetButton = document.getElementById('dashboard-visual-reset');
        const themeSelect = document.getElementById('dashboard-visual-theme');
        const presetSelect = document.getElementById('dashboard-visual-preset');
        const saveThemeButton = document.getElementById('dashboard-visual-theme-save');
        const deleteThemeButton = document.getElementById('dashboard-visual-theme-delete');
        const elementSelect = document.getElementById('dashboard-visual-element');
        const elementResetButton = document.getElementById('dashboard-visual-element-reset');
        const pointColor = document.getElementById('dashboard-visual-point-color');
        const pointMarkButton = document.getElementById('dashboard-visual-point-mark');
        const pointClearButton = document.getElementById('dashboard-visual-point-clear');
        const pointClearAllButton = document.getElementById('dashboard-visual-point-clear-all');
        const pointSearchInput = document.getElementById('dashboard-visual-point-search');
        const pointSearchScope = document.getElementById('dashboard-visual-point-search-scope');
        const pointSearchPrevious = document.getElementById('dashboard-visual-point-search-prev');
        const pointSearchNext = document.getElementById('dashboard-visual-point-search-next');
        const customizeButton = document.getElementById('dashboard-visual-customize-open');
        const customizePanel = document.getElementById('dashboard-visual-customize');
        if (openButton && dialog) {{
          openButton.addEventListener('click', () => {{
            refreshVisualElementControls();
            syncPointSearchDefaultScope();
            refreshPointSearch({{ selectFirst: true, scroll: false }});
            if (typeof dialog.showModal === 'function') dialog.showModal();
            else dialog.setAttribute('open', 'open');
          }});
        }}
        if (closeButton && dialog) {{
          closeButton.addEventListener('click', () => dialog.close ? dialog.close() : dialog.removeAttribute('open'));
        }}
        if (resetButton) {{
          resetButton.addEventListener('click', () => setDashboardVisualState(embeddedInitialVisualState()));
        }}
        if (customizeButton && customizePanel) {{
          customizeButton.addEventListener('click', () => {{
            const expanded = customizePanel.hasAttribute('hidden');
            customizePanel.toggleAttribute('hidden', !expanded);
            customizeButton.setAttribute('aria-expanded', expanded ? 'true' : 'false');
            customizeButton.textContent = expanded ? 'Hide customization' : 'Customize...';
            if (expanded) refreshVisualElementControls();
          }});
        }}
        if (themeSelect) {{
          themeSelect.addEventListener('change', () => {{
            const theme = (dashboardVisualThemeLibrary.themes || []).find((item) => item && item.id === themeSelect.value);
            if (theme && theme.settings) setDashboardVisualState(theme.settings);
          }});
        }}
        if (saveThemeButton) {{
          saveThemeButton.addEventListener('click', () => {{
            const nameControl = document.getElementById('dashboard-visual-theme-name');
            const name = (nameControl && nameControl.value.trim()) || 'Dashboard theme';
            const themeId = visualThemeIdFromName(name);
            const state = sanitizeVisualState(collectVisualStateFromControls());
            state.theme_id = themeId;
            state.theme_name = name;
            dashboardVisualThemeLibrary.themes = (dashboardVisualThemeLibrary.themes || []).filter((theme) => theme.id !== themeId);
            dashboardVisualThemeLibrary.themes.push({{ id: themeId, name, settings: state }});
            dashboardVisualThemeLibrary.default_theme_id = themeId;
            persistVisualThemeLibrary(dashboardVisualThemeLibrary);
            refreshVisualThemeControls();
            setDashboardVisualState(state);
          }});
        }}
        if (deleteThemeButton) {{
          deleteThemeButton.addEventListener('click', () => {{
            const themeId = themeSelect ? themeSelect.value : '';
            if (!themeId) return;
            dashboardVisualThemeLibrary.themes = (dashboardVisualThemeLibrary.themes || []).filter((theme) => theme.id !== themeId);
            if (dashboardVisualThemeLibrary.default_theme_id === themeId) dashboardVisualThemeLibrary.default_theme_id = '';
            persistVisualThemeLibrary(dashboardVisualThemeLibrary);
            refreshVisualThemeControls();
            setDashboardVisualState(Object.assign(sanitizeVisualState(dashboardVisualState), {{ theme_id: '', theme_name: '' }}));
          }});
        }}
        if (elementSelect) {{
          elementSelect.addEventListener('change', () => {{
            const option = elementSelect.selectedOptions && elementSelect.selectedOptions[0];
            if (!option || !option.dataset.visualTarget) {{
              dashboardVisualSelectedTarget = null;
              return;
            }}
            try {{
              applySelectedVisualTargetToControls(JSON.parse(option.dataset.visualTarget));
            }} catch (_error) {{
              dashboardVisualSelectedTarget = null;
            }}
          }});
        }}
        [
          'dashboard-visual-element-color',
          'dashboard-visual-element-opacity',
          'dashboard-visual-element-width',
          'dashboard-visual-element-dash',
          'dashboard-visual-element-marker-size',
          'dashboard-visual-element-marker-symbol',
          'dashboard-visual-element-outline-enabled',
          'dashboard-visual-element-outline-width',
          'dashboard-visual-element-outline-color-mode',
          'dashboard-visual-element-outline-color',
          'dashboard-visual-element-pattern',
        ].forEach((id) => {{
          const control = document.getElementById(id);
          if (control) {{
            control.addEventListener('input', applySelectedElementStyle);
            control.addEventListener('change', applySelectedElementStyle);
          }}
        }});
        if (elementResetButton) {{
          elementResetButton.addEventListener('click', resetSelectedElementStyle);
        }}
        if (pointColor) {{
          pointColor.addEventListener('input', applyPointMarkColorFromControl);
          pointColor.addEventListener('change', applyPointMarkColorFromControl);
        }}
        if (pointMarkButton) {{
          pointMarkButton.addEventListener('click', markSelectedPoint);
        }}
        if (pointClearButton) {{
          pointClearButton.addEventListener('click', clearSelectedPointMark);
        }}
        if (pointClearAllButton) {{
          pointClearAllButton.addEventListener('click', clearAllPointMarks);
        }}
        if (pointSearchInput) {{
          pointSearchInput.addEventListener('input', () => refreshPointSearch({{ selectFirst: true, scroll: false }}));
          pointSearchInput.addEventListener('keydown', (event) => {{
            if (event.key === 'Enter') {{
              event.preventDefault();
              movePointSearch(1);
            }}
          }});
        }}
        if (pointSearchScope) {{
          pointSearchScope.addEventListener('change', () => {{
            pointSearchScope.dataset.userChosen = '1';
            refreshPointSearch({{ selectFirst: true, scroll: false }});
          }});
        }}
        if (pointSearchPrevious) {{
          pointSearchPrevious.addEventListener('click', () => movePointSearch(-1));
        }}
        if (pointSearchNext) {{
          pointSearchNext.addEventListener('click', () => movePointSearch(1));
        }}
        document.querySelectorAll('[data-visual-group-chip]').forEach((chip) => {{
          chip.addEventListener('click', () => {{
            const index = Number(chip.getAttribute('data-visual-chip-index'));
            if (Number.isInteger(index)) selectVisualTargetByChipIndex(index);
          }});
        }});
        if (presetSelect) {{
          presetSelect.addEventListener('change', () => {{
            setDashboardVisualState(applyVisualRecipe(presetSelect.value || 'auto'));
          }});
        }}
        document.querySelectorAll(
          '#dashboard-visual-palette-preset, #dashboard-visual-palette-mode, #dashboard-visual-anchor, #dashboard-visual-gradient-spread, '
          + '#dashboard-visual-distinguish, #dashboard-visual-marker-size, #dashboard-visual-stat-width, '
          + '#dashboard-visual-stat-accent, [data-visual-palette-index]'
        ).forEach((control) => {{
          control.addEventListener('input', () => setDashboardVisualState(collectVisualStateFromControls()));
          control.addEventListener('change', () => setDashboardVisualState(collectVisualStateFromControls()));
        }});
        syncSelectedElementControls(dashboardVisualSelectedTarget);
      }};
    """
