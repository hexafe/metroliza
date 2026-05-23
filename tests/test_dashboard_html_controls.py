from __future__ import annotations

from modules.dashboard_html_controls import render_dashboard_visual_runtime_js


def test_dashboard_visual_runtime_detects_trend_before_scatter() -> None:
    runtime_js = render_dashboard_visual_runtime_js()

    assert "const traceLooksLikeTrend" in runtime_js
    assert "name === 'trend' && mode.includes('lines')" in runtime_js
    assert runtime_js.index("return 'trend'") < runtime_js.index("return 'scatter'")
