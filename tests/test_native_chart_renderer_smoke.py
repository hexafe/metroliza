from __future__ import annotations

import pytest

from modules.chart_render_spec import (
    build_resolved_distribution_spec,
    build_resolved_histogram_spec,
    build_resolved_iqr_spec,
    build_resolved_trend_spec,
    histogram_spec_to_mapping,
)
from modules.chart_renderer import (
    NativeChartRenderer,
    build_chart_renderer,
    build_distribution_native_payload,
    build_histogram_native_payload,
    native_full_chart_backend_available,
)


@pytest.mark.skipif(
    not native_full_chart_backend_available(),
    reason="Native chart renderer is not available in the current environment",
)
def test_native_chart_renderer_smoke_covers_all_supported_summary_charts(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "auto")
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS", "histogram,distribution,iqr,trend")
    renderer = build_chart_renderer()
    assert isinstance(renderer, NativeChartRenderer)

    histogram_payload = build_histogram_native_payload(
        values=[1.0, 1.2, 1.4, 1.8, 2.0, 2.1, 2.2],
        lsl=1.0,
        usl=2.3,
        title="Smoke Histogram",
        bin_count=6,
    )
    histogram_payload["resolved_render_spec"] = histogram_spec_to_mapping(build_resolved_histogram_spec(histogram_payload))

    distribution_payload = build_distribution_native_payload(
        values=[[1.0, 1.08, 1.12], [1.34, 1.43, 1.52]],
        labels=["Alpha", "Beta"],
        title="Smoke Distribution",
        lsl=0.9,
        usl=1.8,
    )
    distribution_payload.update(
        {
            "render_mode": "scatter",
            "x_values": [0.2, 0.8],
            "y_values": [1.05, 1.41],
            "x_domain": {"min": 0.0, "max": 1.0},
            "canvas": {"width_px": 960, "height_px": 540, "dpi": 150},
        }
    )
    distribution_payload["resolved_render_spec"] = build_resolved_distribution_spec(distribution_payload)

    iqr_payload = {
        "type": "iqr",
        "labels": ["Only"],
        "series": [[1.0, 1.1, 1.2, 1.3, 5.0]],
        "title": "Smoke IQR",
        "lsl": 0.8,
        "usl": 5.2,
        "nominal": 1.2,
        "one_sided": False,
        "layout": {"rotation": 0, "display_positions": [1.0], "display_labels": ["Only"], "bottom_margin": 0.18},
        "canvas": {"width_px": 960, "height_px": 540, "dpi": 150},
        "x_label": "Group",
        "y_label": "Measurement",
        "legend": {"items": [{"label": "Median", "kind": "line", "color": "#E69F00"}]},
    }
    iqr_payload["resolved_render_spec"] = build_resolved_iqr_spec(iqr_payload)

    trend_payload = {
        "type": "trend",
        "x_values": [0.0, 1.0, 2.0, 3.0],
        "y_values": [1.0, 1.2, 1.1, 1.35],
        "labels": ["S1", "S2", "S3", "S4"],
        "title": "Smoke Trend",
        "x_label": "Sample #",
        "y_label": "Measurement",
        "horizontal_limits": [0.9, 1.4],
        "layout": {"rotation": 0, "display_positions": [0.0, 1.0, 2.0, 3.0], "display_labels": ["S1", "S2", "S3", "S4"], "bottom_margin": 0.22},
        "canvas": {"width_px": 960, "height_px": 540, "dpi": 150},
    }
    trend_payload["resolved_render_spec"] = build_resolved_trend_spec(trend_payload)

    for chart_type, payload in (
        ("histogram", histogram_payload),
        ("distribution", distribution_payload),
        ("iqr", iqr_payload),
        ("trend", trend_payload),
    ):
        result = getattr(renderer, f"render_{chart_type}_png")(payload)
        assert result.backend == "native"
        assert isinstance(result.png_bytes, bytes)
        assert len(result.png_bytes) > 0
