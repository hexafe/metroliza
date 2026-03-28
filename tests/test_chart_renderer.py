from __future__ import annotations

from io import BytesIO

import matplotlib.pyplot as plt
import numpy as np
import pytest
from unittest import mock

from modules import native_chart_compositor
from modules.chart_renderer import (
    MatplotlibChartRenderer,
    NativeChartRenderer,
    benchmark_histogram_render_runtime,
    build_chart_renderer,
    build_distribution_native_payload,
    build_histogram_native_payload,
    native_distribution_backend_available,
    native_chart_backend_available,
    native_full_chart_backend_available,
    native_histogram_backend_available,
    resolve_distribution_renderer_backend,
    resolve_chart_renderer_backend,
)


def _decode_png_shape(payload: bytes) -> tuple[int, int]:
    arr = plt.imread(BytesIO(payload), format="png")
    return int(arr.shape[0]), int(arr.shape[1])


def test_resolve_backend_defaults_to_matplotlib_when_native_unavailable(monkeypatch):
    monkeypatch.delenv("METROLIZA_CHART_RENDERER_BACKEND", raising=False)
    with mock.patch("modules.chart_renderer._native_render_histogram_png", None):
        assert resolve_chart_renderer_backend() == "matplotlib"


def test_resolve_backend_native_warns_and_falls_back_when_extension_missing(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "native")
    with mock.patch("modules.chart_renderer._native_render_histogram_png", None):
        with mock.patch("warnings.warn") as warn:
            assert resolve_chart_renderer_backend() == "matplotlib"
    assert warn.called
    assert "METROLIZA_CHART_RENDERER_BACKEND=native" in str(warn.call_args[0][0])


def test_resolve_backend_auto_prefers_native_when_extension_available(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "auto")
    with mock.patch("modules.chart_renderer._native_render_histogram_png", lambda payload: b"png"):
        assert resolve_chart_renderer_backend() == "native"


def test_resolve_backend_native_forces_native_without_warning_when_extension_available(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "native")
    with mock.patch("modules.chart_renderer._native_render_histogram_png", lambda payload: b"png"):
        with mock.patch("warnings.warn") as warn:
            assert resolve_chart_renderer_backend() == "native"
    warn.assert_not_called()


def test_native_chart_backend_available_requires_histogram_symbol_only():
    with (
        mock.patch("modules.chart_renderer._native_render_histogram_png", lambda payload: b"png"),
        mock.patch("modules.chart_renderer._native_render_distribution_png", None),
    ):
        assert native_histogram_backend_available() is True
        assert native_distribution_backend_available() is False
        assert native_chart_backend_available() is True
        assert native_full_chart_backend_available() is False


def test_resolve_distribution_backend_falls_back_when_distribution_symbol_is_missing(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "native")
    with (
        mock.patch("modules.chart_renderer._native_render_histogram_png", lambda payload: b"png"),
        mock.patch("modules.chart_renderer._native_render_distribution_png", None),
    ):
        assert resolve_chart_renderer_backend() == "native"
        assert resolve_distribution_renderer_backend() == "matplotlib"




def test_build_chart_renderer_native_env_falls_back_to_matplotlib_when_extension_missing(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "native")
    with mock.patch("modules.chart_renderer._native_render_histogram_png", None):
        renderer = build_chart_renderer()
    assert isinstance(renderer, MatplotlibChartRenderer)

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
    assert metrics["median_s"] > 0.0
    assert metrics["runtime_min_ms"] > 0.0
    assert metrics["runtime_avg_ms"] > 0.0
    assert metrics["runtime_median_ms"] > 0.0
    assert metrics["runtime_median_ms"] >= metrics["runtime_min_ms"]
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
    assert "visual_metadata" in payload
    assert payload["visual_metadata"]["summary_stats_table"]["columns"] == ["Parameter", "Value"]


def test_compact_histogram_renderer_uses_fast_png_encoding(monkeypatch):
    payload = build_histogram_native_payload(
        values=[1.0, 1.5, 2.0, 2.5],
        lsl=0.0,
        usl=3.0,
        title="Compact Histogram",
    )
    captured = {}

    def _capture_encode(_image, *, optimize=True, compress_level=None):
        captured["optimize"] = optimize
        captured["compress_level"] = compress_level
        return b"png"

    monkeypatch.setattr(native_chart_compositor, "_encode_png", _capture_encode)

    assert native_chart_compositor.render_histogram_png(payload) == b"png"
    assert captured["optimize"] is False
    assert captured["compress_level"] == 1


def test_rich_histogram_renderer_keeps_default_png_encoding(monkeypatch):
    payload = build_histogram_native_payload(
        values=[1.0, 1.5, 2.0, 2.5],
        lsl=0.0,
        usl=3.0,
        title="Rich Histogram",
    )
    payload["visual_metadata"]["summary_stats_table"]["rows"] = [{"label": "Mean", "value": "1.75"}]
    captured = {}

    def _capture_encode(_image, *, optimize=True, compress_level=None):
        captured["optimize"] = optimize
        captured["compress_level"] = compress_level
        return b"png"

    monkeypatch.setattr(native_chart_compositor, "_encode_png", _capture_encode)

    assert native_chart_compositor.render_histogram_png(payload) == b"png"
    assert captured["optimize"] is True
    assert captured["compress_level"] is None


def test_native_histogram_renderer_validates_payload_contract():
    payload = {"type": "histogram", "values": "not-a-list", "title": "Bad Payload"}
    with mock.patch("modules.chart_renderer._native_render_histogram_png", lambda _payload: b"png"):
        with pytest.raises(RuntimeError, match="values"):
            NativeChartRenderer().render_histogram_png(payload)


def test_native_chart_renderer_falls_back_to_matplotlib_when_extension_missing():
    payload = build_histogram_native_payload(
        values=[1.0, 2.0, 3.0],
        lsl=0.0,
        usl=4.0,
        title="Fallback Histogram",
    )
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.hist(payload["values"], bins=4)

    with mock.patch("modules.chart_renderer._native_render_histogram_png", None):
        result = NativeChartRenderer().render_histogram_png(payload, fallback_fig=fig)

    plt.close(fig)
    assert result.backend == "matplotlib"
    assert isinstance(result.png_bytes, bytes)
    assert len(result.png_bytes) > 0


def test_native_chart_renderer_keeps_rich_histogram_visual_metadata_on_native_path():
    payload = build_histogram_native_payload(
        values=[1.0, 2.0, 3.0],
        lsl=0.0,
        usl=4.0,
        title="Parity Histogram",
    )
    payload["visual_metadata"]["summary_stats_table"]["rows"] = [{"label": "Mean", "value": "2.0"}]

    fig, ax = plt.subplots(figsize=(6, 3))
    ax.hist(payload["values"], bins=4)

    captured = {}

    def _capture(native_payload):
        captured["payload"] = native_payload
        return b"native"

    with mock.patch("modules.chart_renderer._native_render_histogram_png", _capture):
        result = NativeChartRenderer().render_histogram_png(payload, fallback_fig=fig)

    plt.close(fig)
    assert result.backend == "native"
    assert result.png_bytes == b"native"
    assert captured["payload"]["visual_metadata"]["summary_stats_table"]["rows"][0]["label"] == "Mean"


def test_native_chart_renderer_uses_native_for_annotation_rows_without_warning():
    payload = build_histogram_native_payload(
        values=[1.0, 2.0, 3.0],
        lsl=0.0,
        usl=4.0,
        title="Parity Histogram",
    )
    payload["visual_metadata"]["annotation_rows"] = [{"label": "LSL", "x": 0.0}]

    with mock.patch("modules.chart_renderer._native_render_histogram_png", lambda _payload: b"native"):
        with mock.patch("warnings.warn") as warn:
            result = NativeChartRenderer().render_histogram_png(payload)

    warn.assert_not_called()
    assert result.backend == "native"
    assert result.png_bytes == b"native"


def test_native_distribution_renderer_falls_back_to_matplotlib_when_extension_missing():
    payload = build_distribution_native_payload(
        values=[[1.0, 1.2, 1.3], [1.4, 1.45, 1.5]],
        labels=["A", "B"],
        title="Fallback Distribution",
    )
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.scatter([0, 1, 2], [1.0, 1.1, 1.2], s=10)

    with mock.patch("modules.chart_renderer._native_render_distribution_png", None):
        result = NativeChartRenderer().render_distribution_png(payload, fallback_fig=fig)

    plt.close(fig)
    assert result.backend == "matplotlib"
    assert isinstance(result.png_bytes, bytes)
    assert len(result.png_bytes) > 0


def test_native_distribution_renderer_validates_payload_contract():
    payload = {"type": "distribution", "labels": ["A"], "series": "invalid", "title": "Bad Payload"}
    with mock.patch("modules.chart_renderer._native_render_distribution_png", lambda _payload: b"png"):
        with pytest.raises(RuntimeError, match="series"):
            NativeChartRenderer().render_distribution_png(payload)


def test_native_iqr_renderer_validates_payload_contract():
    payload = {"type": "iqr", "labels": ["A"], "series": "invalid"}
    with mock.patch("modules.chart_renderer._native_render_iqr_png", lambda _payload: b"png"):
        with pytest.raises(RuntimeError, match="series"):
            NativeChartRenderer().render_iqr_png(payload)


def test_native_trend_renderer_validates_payload_contract():
    payload = {"type": "trend", "x_values": [0.0], "y_values": [1.0], "labels": []}
    with mock.patch("modules.chart_renderer._native_render_trend_png", lambda _payload: b"png"):
        with pytest.raises(RuntimeError, match="equal x/y/labels"):
            NativeChartRenderer().render_trend_png(payload)


@pytest.mark.skipif(not native_histogram_backend_available(), reason="Native histogram renderer is not available in current environment")
def test_native_histogram_renderer_uses_real_extension_when_available():
    payload = build_histogram_native_payload(
        values=[1.0, 1.2, 1.4, 1.8, 2.0, 2.1, 2.2],
        lsl=1.0,
        usl=2.3,
        title="Real Native Histogram",
        bin_count=6,
    )
    result = NativeChartRenderer().render_histogram_png(payload)
    assert result.backend == "native"
    assert isinstance(result.png_bytes, bytes)
    assert len(result.png_bytes) > 0
