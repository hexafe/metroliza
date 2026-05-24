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
    assert "Toned report" in dialog_html
    assert "High-color groups" in dialog_html
    assert "Group 1" in dialog_html
    assert "Population" in dialog_html
    assert 'id="dashboard-visual-customize-open"' in dialog_html
    assert 'id="dashboard-visual-customize" class="visual-customize" hidden' in dialog_html
    assert "Color set" in dialog_html
    assert "Color generation" in dialog_html
    assert "Default marker size" in dialog_html
    assert "Selection inspector" in dialog_html
    assert "dashboard-visual-element-marker-symbol" in dialog_html
    assert "dashboard-visual-element-outline-enabled" in dialog_html
    assert "dashboard-visual-element-outline-color-mode" in dialog_html
    assert '<option value="when_similar" selected>When similar</option>' in dialog_html
    assert 'id="dashboard-visual-apply"' not in dialog_html


def test_dashboard_visual_dialog_pairs_ranges_with_number_readouts() -> None:
    dialog_html = render_dashboard_visual_dialog()

    assert dialog_html.index("Visual recipe") < dialog_html.index("Color set")
    assert dialog_html.index("Color set") < dialog_html.index("Fine tuning")
    assert dialog_html.index("Fine tuning") < dialog_html.index("Selection inspector")
    assert dialog_html.count('class="visual-range-number"') >= 12
    assert 'data-visual-range-value-for="dashboard-visual-marker-size"' in dialog_html
    assert 'data-visual-range-value-for="dashboard-visual-stat-width"' in dialog_html
    assert 'data-visual-range-value-for="dashboard-visual-element-opacity"' in dialog_html
    assert 'data-visual-range-value-for="dashboard-visual-element-width"' in dialog_html
    assert 'data-visual-range-value-for="dashboard-visual-element-marker-size"' in dialog_html
    assert 'data-visual-range-value-for="dashboard-visual-element-outline-width"' in dialog_html
    assert 'aria-label="Element opacity value"' in dialog_html
    assert 'type="number"' in dialog_html


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
    assert "toned_report" in config["recipes"]
    assert "population_baseline" in config["recipes"]["toned_report"]
    assert config["recipes"]["toned_report"]["population_baseline"]["marker_size"] < config["recipes"]["toned_report"]["comparison_focus"]["marker_size"]
    assert config["initialSettings"]["preset"] == "custom"
    assert config["initialSettings"]["palette_preset"] == "custom"
    assert config["initialSettings"]["palette"][:2] == ["#123456", "#abcdef"]
    assert config["initialSettings"] != config["defaults"]
    assert config["initialSettingsSignature"] != config["defaultSettingsSignature"]
    assert "const visualStorageBaseKey" in runtime_js
    assert "const visualStorageKey = `${visualStorageBaseKey}:${dashboardVisualScope()}`;" in runtime_js
    assert "window.metrolizaDashboardVisualStorageKey = visualStorageKey;" in runtime_js
    assert "parsed.initialSettingsSignature === currentSignature" in runtime_js
    assert "initialSettingsSignature" in runtime_js
    assert "initialSettings || dashboardVisualConfig.defaults" in runtime_js
    assert '"initialSettings":{' in runtime_js
    assert '"preset":"custom"' in runtime_js
    assert "#123456" in runtime_js


def test_dashboard_visual_runtime_range_readouts_use_existing_update_path() -> None:
    runtime_js = render_dashboard_visual_runtime_js()

    assert "const initializeVisualRangeReadouts" in runtime_js
    assert "const syncRangeNumberReadouts" in runtime_js
    assert (
        "const customizeButton = document.getElementById('dashboard-visual-customize-open')"
        in runtime_js
    )
    assert "customizePanel.toggleAttribute('hidden', !expanded)" in runtime_js
    assert "document.querySelectorAll('[data-visual-range-value]')" in runtime_js
    assert "range.dispatchEvent(new Event('input', { bubbles: true }));" in runtime_js
    assert "range.dispatchEvent(new Event('change', { bubbles: true }));" in runtime_js
    assert "syncRangeNumberReadouts();" in runtime_js
    assert "control.addEventListener('input', () => setDashboardVisualState(collectVisualStateFromControls()))" in runtime_js
    assert "window.setTimeout(() => {" in runtime_js


def test_dashboard_visual_runtime_reference_reset_uses_embedded_initial_settings() -> None:
    initial_settings = {
        "reference_lines": {
            "lsl": {"color": "#123456", "width": 4.5, "dash": "dot", "opacity": 0.42},
        }
    }
    config = json.loads(dashboard_visual_runtime_config_json(initial_settings))
    runtime_js = render_dashboard_visual_runtime_js(initial_settings=initial_settings)

    assert config["initialSettings"]["reference_lines"]["lsl"]["color"] == "#123456"
    assert config["initialSettings"]["reference_lines"]["lsl"]["width"] == 4.5
    assert config["initialSettings"]["reference_lines"]["lsl"]["opacity"] == 0.42
    assert config["initialSettings"]["reference_lines"]["lsl"] != config["defaults"]["reference_lines"]["lsl"]
    assert "const embeddedInitialVisualState" in runtime_js
    assert "const embedded = embeddedInitialVisualState();" in runtime_js
    assert "state.reference_lines[target.key] = clonePlotlySpec(embedded.reference_lines[target.key]);" in runtime_js
    assert (
        "state.reference_lines[target.key] = "
        "clonePlotlySpec(dashboardVisualConfig.defaults.reference_lines[target.key]);"
        not in runtime_js
    )


def test_dashboard_visual_runtime_recipes_update_controls_and_palette_preview() -> None:
    runtime_js = render_dashboard_visual_runtime_js()

    assert "const applyVisualRecipe" in runtime_js
    assert "const configuredRecipes = dashboardVisualConfig.recipes || {};" in runtime_js
    assert "sanitizeVisualState(Object.assign({}, defaults, configured || {}, preservedTheme))" in runtime_js
    assert "state.recipe = visualChoice(state.recipe || state.visual_recipe || state.preset" in runtime_js
    assert "const refreshResolvedPalettePreview" in runtime_js
    assert "const effectiveSeriesColors" in runtime_js
    assert "visualPreviewLabels" in runtime_js
    assert "document.querySelectorAll('[data-visual-group-chip]')" in runtime_js
    assert "selectVisualTargetByChipIndex" in runtime_js
    assert "setDashboardVisualState(applyVisualRecipe(button.getAttribute('data-visual-preset')" in runtime_js


def test_dashboard_visual_runtime_selected_element_controls_are_role_aware() -> None:
    runtime_js = render_dashboard_visual_runtime_js()

    assert "const traceStyleForSelection" in runtime_js
    assert "const traceCapabilitiesForSelection" in runtime_js
    assert "style: traceStyleForSelection(trace)" in runtime_js
    assert "capabilities: traceCapabilitiesForSelection(trace, roleFromMeta)" in runtime_js
    assert "const syncSelectedElementControls" in runtime_js
    assert "field.hidden = !enabled;" in runtime_js
    assert "data-visual-selected-field" in render_dashboard_visual_dialog()
    assert "dashboard-visual-element-marker-size" in runtime_js
    assert "dashboard-visual-element-marker-symbol" in runtime_js
    assert "dashboard-visual-element-outline-width" in runtime_js
    assert "contrastOutlineColor" in runtime_js
    assert "dashboard-visual-element-pattern" in runtime_js
    assert "outline_width: markerLike," in runtime_js
    assert "pattern_shape: patternLike" in runtime_js


def test_dashboard_visual_runtime_carries_population_focus_contract() -> None:
    runtime_js = render_dashboard_visual_runtime_js()
    config = json.loads(dashboard_visual_runtime_config_json())

    assert "population_baseline" in config["defaults"]
    assert "comparison_focus" in config["defaults"]
    assert "sanitizePopulationBaseline" in runtime_js
    assert "population_baseline: clonePlotlySpec(state.population_baseline || {})" in runtime_js
    assert "comparison_focus: clonePlotlySpec(state.comparison_focus || {})" in runtime_js
    assert "const isPopulationLabel" in runtime_js
    assert "mergeRoleStyle(Object.assign(style, override), roleStyle, override)" in runtime_js
    assert "state.population_baseline = Object.assign({}, state.population_baseline || {}, style);" in runtime_js
    assert "state.palette[paletteIndex] = style.color;" in runtime_js
