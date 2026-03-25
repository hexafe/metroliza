from __future__ import annotations

from io import BytesIO

import matplotlib.pyplot as plt
import numpy as np
from unittest import mock

from modules.chart_renderer import (
    MatplotlibChartRenderer,
    NativeChartRenderer,
    benchmark_histogram_render_runtime,
    build_chart_renderer,
    build_histogram_native_payload,
    resolve_chart_renderer_backend,
)


def _decode_png_shape(payload: bytes) -> tuple[int, int]:
    arr = plt.imread(BytesIO(payload), format="png")
    return int(arr.shape[0]), int(arr.shape[1])


def test_resolve_backend_defaults_to_matplotlib_when_native_unavailable(monkeypatch):
    monkeypatch.delenv("METROLIZA_CHART_RENDERER_BACKEND", raising=False)
    with mock.patch("modules.chart_renderer._native_render_histogram_png", None):
        assert resolve_chart_renderer_backend() == "matplotlib"


def test_resolve_backend_native_requires_extension(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "native")
    with mock.patch("modules.chart_renderer._native_render_histogram_png", None):
        try:
            resolve_chart_renderer_backend()
        except RuntimeError as exc:
            assert "unavailable" in str(exc).lower()
        else:  # pragma: no cover - defensive assertion
            raise AssertionError("Expected RuntimeError when native backend is forced but unavailable")


def test_build_chart_renderer_matplotlib(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "matplotlib")
    renderer = build_chart_renderer()
    assert isinstance(renderer, MatplotlibChartRenderer)


def test_native_histogram_renderer_parity_tolerates_small_differences():
    payload = build_histogram_native_payload(
        values=np.array([1.0, 1.1, 1.2, 1.3, 1.6, 1.8]),
        lsl=1.0,
        usl=2.0,
        title="Parity Histogram",
    )
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.hist(payload["values"], bins=8)
    ax.set_title(payload["title"])
    fallback_png = MatplotlibChartRenderer().render_figure_png(fig).png_bytes
    plt.close(fig)

    def _fake_native_renderer(native_payload):
        fig2, ax2 = plt.subplots(figsize=(6, 3))
        ax2.hist(native_payload["values"], bins=8)
        ax2.set_title(native_payload["title"])
        png = MatplotlibChartRenderer().render_figure_png(fig2).png_bytes
        plt.close(fig2)
        return png

    with mock.patch("modules.chart_renderer._native_render_histogram_png", _fake_native_renderer):
        native_png = NativeChartRenderer().render_histogram_png(payload).png_bytes

    fb_h, fb_w = _decode_png_shape(fallback_png)
    nat_h, nat_w = _decode_png_shape(native_png)
    assert abs(fb_h - nat_h) <= 2
    assert abs(fb_w - nat_w) <= 2
    assert abs(len(fallback_png) - len(native_png)) <= max(15000, int(0.30 * len(fallback_png)))


def test_benchmark_runtime_metadata_large_cardinality_payload():
    values = np.linspace(0.0, 100.0, 5000)
    payload = build_histogram_native_payload(values=values, lsl=10.0, usl=90.0, title="Large Header Cardinality POC")
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(values, bins=30)
    with mock.patch("modules.chart_renderer._native_render_histogram_png", None):
        metrics = benchmark_histogram_render_runtime(
            NativeChartRenderer(),
            payload,
            iterations=2,
        )
    plt.close(fig)
    assert metrics["iterations"] == 2.0
    assert metrics["runtime_min_ms"] > 0.0
    assert metrics["runtime_avg_ms"] > 0.0
    assert metrics["runtime_max_ms"] >= metrics["runtime_min_ms"]


def test_build_histogram_native_payload_includes_bin_count_when_provided():
    payload = build_histogram_native_payload(
        values=[1.0, 2.0, 3.0],
        lsl=0.0,
        usl=4.0,
        title="Histogram",
        bin_count=7,
    )
    assert payload["bin_count"] == 7
