from __future__ import annotations

from modules.dashboard_html_controls import render_dashboard_visual_runtime_js


def test_dashboard_visual_runtime_detects_trend_before_scatter() -> None:
    runtime_js = render_dashboard_visual_runtime_js()

    assert "const traceLooksLikeTrend" in runtime_js
    assert "name === 'trend' && mode.includes('lines')" in runtime_js
    assert runtime_js.index("return 'trend'") < runtime_js.index("return 'scatter'")
    assert "const chartKindForTrace" in runtime_js
    assert "if (chartKind === 'trend' && traceHasMarkers(trace)) return 'scatter';" in runtime_js
    assert "dashboard_visual_role: isTrendLine ? 'trend' : 'series'" in runtime_js


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
