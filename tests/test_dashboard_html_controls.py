from __future__ import annotations

import json

from modules.dashboard_html_controls import (
    dashboard_visual_runtime_config_json,
    render_dashboard_visual_dialog,
    render_dashboard_visual_runtime_js,
)


def test_dashboard_visual_runtime_detects_trend_before_scatter() -> None:
    runtime_js = render_dashboard_visual_runtime_js()

    assert "const traceLooksLikeTrend" in runtime_js
    assert "const traceLooksLikeModelCurve" in runtime_js
    assert "name === 'trend' && mode.includes('lines')" in runtime_js
    assert runtime_js.index("return 'trend'") < runtime_js.index("return 'scatter'")
    assert "const chartKindForTrace" in runtime_js
    assert "if (chartKind === 'trend' && traceHasMarkers(trace)) return 'scatter';" in runtime_js
    assert "dashboard_visual_role: role" in runtime_js


def test_dashboard_visual_runtime_matches_prefixed_and_unprefixed_stat_lines() -> None:
    runtime_js = render_dashboard_visual_runtime_js()

    assert (
        r"match(/^(?:\((.+?)\)\s*)?(Min|Q1|Median|Mean|Q3|Max)=/i)"
        in runtime_js
    )
    assert "return { group: match[1] ? stripGroupCount(match[1]) : '', stat: match[2] };" in runtime_js


def test_dashboard_visual_runtime_preserves_trace_visibility_before_plotly_react() -> None:
    runtime_js = render_dashboard_visual_runtime_js()

    assert "const preservePlotlyTraceVisibility" in runtime_js
    assert "const allCurrentTracesHidden = currentData.every((trace) => traceIsHidden(trace));" in runtime_js
    assert "trace.visible = 'legendonly';" in runtime_js
    assert "delete trace.visible;" in runtime_js
    assert "preservePlotlyTraceVisibility(container, data);" in runtime_js
    assert "window.Plotly.react = patchedReact;" in runtime_js


def test_dashboard_visual_runtime_supports_palettes_themes_and_element_selection() -> None:
    runtime_js = render_dashboard_visual_runtime_js()

    assert "palettePresets" in runtime_js
    assert "okabe_ito" in runtime_js
    assert "visualThemeStorageKey" in runtime_js
    assert "readVisualThemeLibrary" in runtime_js
    assert "series_overrides" in runtime_js
    assert "stat_line_overrides" in runtime_js
    assert "window.metrolizaInstallVisualSelectionHandlers" in runtime_js
    assert "plotly_click" in runtime_js
    assert "dashboard_visual_target" in runtime_js
    assert "__metrolizaVisualSelectionHandlers" in runtime_js


def test_dashboard_visual_dialog_uses_live_recipe_and_group_color_chips() -> None:
    dialog_html = render_dashboard_visual_dialog()

    assert "Visual recipe" in dialog_html
    assert "data-visual-group-chip" in dialog_html
    assert "Group 1" in dialog_html
    assert "Population" in dialog_html
    assert "Color set" in dialog_html
    assert "Color generation" in dialog_html
    assert 'id="dashboard-visual-apply"' not in dialog_html


def test_dashboard_visual_runtime_scopes_storage_and_uses_initial_settings() -> None:
    initial_settings = {
        "preset": "custom",
        "palette_preset": "custom",
        "palette_mode": "fixed",
        "palette": ["#123456", "#abcdef"],
    }
    config = json.loads(dashboard_visual_runtime_config_json(initial_settings))
    runtime_js = render_dashboard_visual_runtime_js(initial_settings=initial_settings)

    assert config["storageVersion"] == 1
    assert config["initialSettings"]["preset"] == "custom"
    assert config["initialSettings"]["palette_preset"] == "custom"
    assert config["initialSettings"]["palette"][:2] == ["#123456", "#abcdef"]
    assert config["initialSettings"] != config["defaults"]
    assert "const visualStorageBaseKey" in runtime_js
    assert "const visualStorageKey = `${visualStorageBaseKey}:${dashboardVisualScope()}`;" in runtime_js
    assert "window.metrolizaDashboardVisualStorageKey = visualStorageKey;" in runtime_js
    assert "initialSettings || dashboardVisualConfig.defaults" in runtime_js
    assert '"initialSettings":{' in runtime_js
    assert '"preset":"custom"' in runtime_js
    assert "#123456" in runtime_js


def test_dashboard_visual_runtime_recipes_update_controls_and_palette_preview() -> None:
    runtime_js = render_dashboard_visual_runtime_js()

    assert "const applyVisualRecipe" in runtime_js
    assert "const configuredRecipes = dashboardVisualConfig.recipes || {};" in runtime_js
    assert "sanitizeVisualState(Object.assign({}, defaults, configured || {}, preservedTheme))" in runtime_js
    assert "const refreshResolvedPalettePreview" in runtime_js
    assert "document.querySelectorAll('[data-visual-group-chip]')" in runtime_js
    assert "setDashboardVisualState(applyVisualRecipe(button.getAttribute('data-visual-preset')" in runtime_js


def test_dashboard_visual_runtime_selected_element_controls_are_role_aware() -> None:
    runtime_js = render_dashboard_visual_runtime_js()

    assert "const traceStyleForSelection" in runtime_js
    assert "const traceCapabilitiesForSelection" in runtime_js
    assert "style: traceStyleForSelection(trace)" in runtime_js
    assert "capabilities: traceCapabilitiesForSelection(trace, roleFromMeta)" in runtime_js
    assert "const syncSelectedElementControls" in runtime_js
    assert "data-visual-selected-field" in render_dashboard_visual_dialog()
    assert "dashboard-visual-element-marker-size" in runtime_js
    assert "dashboard-visual-element-pattern" in runtime_js
