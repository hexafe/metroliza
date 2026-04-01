from __future__ import annotations

from io import BytesIO

import matplotlib.pyplot as plt
import numpy as np
import pytest
from unittest import mock

from modules import native_chart_compositor
from modules.chart_render_spec import (
    build_resolved_distribution_spec,
    build_resolved_histogram_spec,
    build_resolved_iqr_spec,
    build_resolved_trend_spec,
    histogram_spec_to_mapping,
)
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
    native_chart_renderer_rollout_enabled,
    native_chart_renderer_rollout_enabled_for,
    resolve_histogram_renderer_backend,
    resolve_distribution_renderer_backend,
    resolve_iqr_renderer_backend,
    resolve_chart_renderer_backend,
    resolve_trend_renderer_backend,
)
from modules.backend_diagnostics import build_backend_diagnostic_summary


def _decode_png_shape(payload: bytes) -> tuple[int, int]:
    arr = plt.imread(BytesIO(payload), format="png")
    return int(arr.shape[0]), int(arr.shape[1])


def _attach_histogram_resolved_spec(payload):
    payload["resolved_render_spec"] = histogram_spec_to_mapping(build_resolved_histogram_spec(payload))
    return payload


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


def test_native_backend_rollout_gate_is_disabled_by_default():
    assert native_chart_renderer_rollout_enabled() is False
    assert native_chart_renderer_rollout_enabled_for("histogram") is False
    assert native_chart_renderer_rollout_enabled_for("distribution") is False
    assert native_chart_renderer_rollout_enabled_for("iqr") is False
    assert native_chart_renderer_rollout_enabled_for("trend") is False


def test_resolve_backend_auto_uses_matplotlib_even_when_extension_available(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "auto")
    with mock.patch("modules.chart_renderer._native_render_histogram_png", lambda payload: b"png"):
        assert resolve_chart_renderer_backend() == "matplotlib"


def test_resolve_backend_native_warns_and_falls_back_even_when_extension_available(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "native")
    with mock.patch("modules.chart_renderer._native_render_histogram_png", lambda payload: b"png"):
        with mock.patch("warnings.warn") as warn:
            assert resolve_chart_renderer_backend() == "matplotlib"
    warn.assert_called_once()
    assert "disabled by rollout policy" in str(warn.call_args[0][0])


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
        assert resolve_chart_renderer_backend() == "matplotlib"
        assert resolve_distribution_renderer_backend() == "matplotlib"
        assert resolve_iqr_renderer_backend() == "matplotlib"
        assert resolve_trend_renderer_backend() == "matplotlib"




def test_build_chart_renderer_native_env_falls_back_to_matplotlib_when_extension_missing(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "native")
    with mock.patch("modules.chart_renderer._native_render_histogram_png", None):
        renderer = build_chart_renderer()
    assert isinstance(renderer, MatplotlibChartRenderer)


def test_build_chart_renderer_keeps_matplotlib_even_when_native_capability_is_present(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "native")
    with mock.patch("modules.chart_renderer._native_render_histogram_png", lambda payload: b"png"):
        with mock.patch("warnings.warn") as warn:
            renderer = build_chart_renderer()
    assert isinstance(renderer, MatplotlibChartRenderer)
    assert warn.called
    assert "disabled by rollout policy" in str(warn.call_args[0][0])


def test_build_chart_renderer_matplotlib(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "matplotlib")
    renderer = build_chart_renderer()
    assert isinstance(renderer, MatplotlibChartRenderer)


def test_native_rollout_allowlist_enables_only_selected_chart_types(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "auto")
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS", "distribution,trend")

    histogram_payload = build_histogram_native_payload(
        values=[1.0, 1.1, 1.2, 1.3],
        lsl=0.9,
        usl=1.4,
        title="Rollout Histogram",
    )
    distribution_payload = build_distribution_native_payload(
        values=[[1.0, 1.2, 1.3], [1.4, 1.45, 1.5]],
        labels=["A", "B"],
        title="Rollout Distribution",
    )
    distribution_payload.update(
        {
            "render_mode": "scatter",
            "x_values": [0.2, 0.8],
            "y_values": [1.1, 1.4],
            "x_domain": {"min": 0.0, "max": 1.0},
            "canvas": {"width_px": 960, "height_px": 540, "dpi": 150},
            "legend": {
                "items": [
                    {"label": "Measurement", "kind": "marker", "marker": "circle", "color": "#0072B2"}
                ]
            },
        }
    )
    distribution_payload["resolved_render_spec"] = build_resolved_distribution_spec(distribution_payload)
    distribution_payload["resolved_render_spec"]["annotations"] = {"markers": [], "segments": [], "texts": []}
    distribution_payload["resolved_render_spec"]["violin_bodies"] = []
    histogram_fig, histogram_ax = plt.subplots(figsize=(6, 3))
    histogram_ax.hist(histogram_payload["values"], bins=4)
    distribution_fig, distribution_ax = plt.subplots(figsize=(6, 3))
    distribution_ax.scatter([0, 1], [1.0, 1.1], s=10)

    with (
        mock.patch("modules.chart_renderer._native_render_histogram_png", lambda payload: b"hist"),
        mock.patch("modules.chart_renderer._native_render_distribution_png", lambda payload: b"dist"),
        mock.patch("modules.chart_renderer._native_render_iqr_png", lambda payload: b"iqr"),
        mock.patch("modules.chart_renderer._native_render_trend_png", lambda payload: b"trend"),
        mock.patch("warnings.warn") as warn,
    ):
        renderer = build_chart_renderer()
        assert isinstance(renderer, NativeChartRenderer)
        assert native_chart_renderer_rollout_enabled() is True
        assert native_chart_renderer_rollout_enabled_for("histogram") is False
        assert native_chart_renderer_rollout_enabled_for("distribution") is True
        assert native_chart_renderer_rollout_enabled_for("iqr") is False
        assert native_chart_renderer_rollout_enabled_for("trend") is True
        assert resolve_histogram_renderer_backend() == "matplotlib"
        assert resolve_distribution_renderer_backend() == "native"
        assert resolve_iqr_renderer_backend() == "matplotlib"
        assert resolve_trend_renderer_backend() == "native"

        histogram_result = renderer.render_histogram_png(histogram_payload, fallback_fig=histogram_fig)
        distribution_result = renderer.render_distribution_png(distribution_payload, fallback_fig=distribution_fig)

    plt.close(histogram_fig)
    plt.close(distribution_fig)

    assert histogram_result.backend == "matplotlib"
    assert distribution_result.backend == "native"
    assert warn.called


def test_native_histogram_renderer_parity_tolerates_small_differences():
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS", "histogram")
        payload = build_histogram_native_payload(
            values=np.array([1.0, 1.1, 1.2, 1.3, 1.6, 1.8]),
            lsl=1.0,
            usl=2.0,
            title="Parity Histogram",
        )
        _attach_histogram_resolved_spec(payload)
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
        compact_render=True,
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


def test_rich_histogram_renderer_recovers_layout_from_top_level_metadata():
    payload = build_histogram_native_payload(
        values=[1.0, 1.1, 1.3, 1.5, 1.7, 1.9, 2.0, 2.1],
        lsl=0.8,
        usl=2.2,
        title="Recovered Rich Histogram",
        bin_count=6,
    )
    payload["visual_metadata"] = {}
    payload["summary_table_rows"] = [
        {"label": "Mean", "value": "1.58"},
        {"label": "Cp", "value": "1.25"},
        {"label": "Cpk", "value": "1.11"},
    ]
    payload["annotation_rows"] = [
        {"label": "LSL", "text": "LSL=0.800", "kind": "lsl", "x": 0.8, "row_index": 1},
        {"label": "Mean", "text": "Mean = 1.580", "kind": "mean", "x": 1.58, "row_index": 0},
        {"label": "USL", "text": "USL=2.200", "kind": "usl", "x": 2.2, "row_index": 1},
    ]
    payload["specification_lines"] = [
        {"id": "lsl", "label": "LSL", "value": 0.8, "enabled": True},
        {"id": "usl", "label": "USL", "value": 2.2, "enabled": True},
    ]

    png = native_chart_compositor.render_histogram_png(payload)
    image = plt.imread(BytesIO(png), format="png")
    height, width = image.shape[:2]
    table_region = image[int(height * 0.12): int(height * 0.92), int(width * 0.72): int(width * 0.98), :3]
    annotation_region = image[: int(height * 0.18), int(width * 0.10): int(width * 0.65), :3]

    assert np.count_nonzero(np.any(table_region < 0.97, axis=2)) > 4000
    assert np.count_nonzero(np.any(annotation_region < 0.97, axis=2)) > 900


def test_direct_histogram_compositor_synthesizes_fallback_metadata_for_legacy_payloads():
    payload = build_histogram_native_payload(
        values=[1.0, 1.1, 1.3, 1.5, 1.7, 1.9, 2.0, 2.1],
        lsl=0.8,
        usl=2.2,
        title="Fallback Rich Histogram",
        bin_count=6,
    )
    assert "resolved_render_spec" not in payload
    payload["visual_metadata"] = {}
    payload["summary"] = {"count": 8, "mean": 1.58, "std": 0.39, "min": 1.0, "max": 2.1}
    payload["limits"] = {"lsl": 0.8, "usl": 2.2, "nominal": 1.5}
    payload["mean_line"] = {"value": 1.58}

    png = native_chart_compositor.render_histogram_png(payload)
    image = plt.imread(BytesIO(png), format="png")
    height, width = image.shape[:2]
    table_region = image[int(height * 0.12): int(height * 0.92), int(width * 0.72): int(width * 0.98), :3]

    assert np.count_nonzero(np.any(table_region < 0.97, axis=2)) > 2500


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
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS", "histogram")
        payload = build_histogram_native_payload(
            values=[1.0, 2.0, 3.0],
            lsl=0.0,
            usl=4.0,
            title="Parity Histogram",
        )
        payload["visual_metadata"]["summary_stats_table"]["rows"] = [{"label": "Mean", "value": "2.0"}]
        _attach_histogram_resolved_spec(payload)

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
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS", "histogram")
        payload = build_histogram_native_payload(
            values=[1.0, 2.0, 3.0],
            lsl=0.0,
            usl=4.0,
            title="Parity Histogram",
        )
        payload["visual_metadata"]["annotation_rows"] = [{"label": "LSL", "x": 0.0}]
        _attach_histogram_resolved_spec(payload)

        with mock.patch("modules.chart_renderer._native_render_histogram_png", lambda _payload: b"native"):
            with mock.patch("warnings.warn") as warn:
                result = NativeChartRenderer().render_histogram_png(payload)

        warn.assert_not_called()
        assert result.backend == "native"
        assert result.png_bytes == b"native"


def test_native_renderer_falls_back_for_disabled_chart_even_when_native_is_available(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "native")
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS", "distribution")

    payload = build_histogram_native_payload(
        values=[1.0, 2.0, 3.0],
        lsl=0.0,
        usl=4.0,
        title="Disabled Histogram",
    )
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.hist(payload["values"], bins=4)

    with mock.patch("modules.chart_renderer._native_render_histogram_png", lambda _payload: b"png"):
        with mock.patch("warnings.warn") as warn:
            result = NativeChartRenderer().render_histogram_png(payload, fallback_fig=fig)

    plt.close(fig)
    assert result.backend == "matplotlib"
    assert warn.called
    assert "disabled by rollout policy" in str(warn.call_args[0][0])


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


def test_backend_diagnostics_exposes_per_chart_rollout_state(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_BACKEND", "native")
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS", "distribution,trend")

    with (
        mock.patch("modules.chart_renderer._native_render_histogram_png", lambda payload: b"png"),
        mock.patch("modules.chart_renderer._native_render_distribution_png", lambda payload: b"png"),
        mock.patch("modules.chart_renderer._native_render_iqr_png", lambda payload: b"png"),
        mock.patch("modules.chart_renderer._native_render_trend_png", lambda payload: b"png"),
    ):
        summary = build_backend_diagnostic_summary()["chart_renderer"]

    assert summary["rollout_enabled"] is True
    assert summary["histogram_rollout_enabled"] is False
    assert summary["distribution_rollout_enabled"] is True
    assert summary["iqr_rollout_enabled"] is False
    assert summary["trend_rollout_enabled"] is True
    assert summary["histogram_effective_backend"] == "matplotlib"
    assert summary["distribution_effective_backend"] == "native"
    assert summary["iqr_effective_backend"] == "matplotlib"
    assert summary["trend_effective_backend"] == "native"


def test_native_distribution_renderer_validates_payload_contract():
    payload = {"type": "distribution", "labels": ["A"], "series": "invalid", "title": "Bad Payload"}
    with mock.patch("modules.chart_renderer._native_render_distribution_png", lambda _payload: b"png"):
        with pytest.raises(RuntimeError, match="series"):
            NativeChartRenderer().render_distribution_png(payload)


def test_native_distribution_renderer_falls_back_when_native_call_raises():
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS", "distribution")
        payload = build_distribution_native_payload(
            values=[[1.0, 1.2, 1.3], [1.4, 1.45, 1.5]],
            labels=["A", "B"],
            title="Runtime Failure Distribution",
        )
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.scatter([0, 1, 2], [1.0, 1.1, 1.2], s=10)

        def _raise_runtime_error(_payload):
            raise RuntimeError("failed to import modules.native_chart_compositor")

        with mock.patch("modules.chart_renderer._native_render_distribution_png", _raise_runtime_error):
            result = NativeChartRenderer().render_distribution_png(payload, fallback_fig=fig)

        plt.close(fig)
        assert result.backend == "matplotlib"
        assert isinstance(result.png_bytes, bytes)
        assert len(result.png_bytes) > 0


def test_native_distribution_renderer_falls_back_when_resolved_geometry_is_missing():
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS", "distribution")
        payload = build_distribution_native_payload(
            values=[[1.0, 1.2, 1.3], [1.4, 1.45, 1.5]],
            labels=["A", "B"],
            title="Missing Geometry Distribution",
        )
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.scatter([0, 1, 2], [1.0, 1.1, 1.2], s=10)

        native = mock.Mock(return_value=b"native")
        with mock.patch("modules.chart_renderer._native_render_distribution_png", native):
            result = NativeChartRenderer().render_distribution_png(payload, fallback_fig=fig)

        plt.close(fig)
        native.assert_not_called()
        assert result.backend == "matplotlib"
        assert isinstance(result.png_bytes, bytes)
        assert len(result.png_bytes) > 0


def test_native_distribution_renderer_uses_native_when_finalized_geometry_is_attached():
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS", "distribution")
        payload = build_distribution_native_payload(
            values=[[1.0, 1.2, 1.3], [1.4, 1.45, 1.5]],
            labels=["A", "B"],
            title="Resolved Geometry Distribution",
        )
        payload["render_mode"] = "scatter"
        payload["resolved_render_spec"] = {
            "source": "matplotlib_finalized",
            "render_mode": "scatter",
            "title": {"text": "Resolved Geometry Distribution"},
            "plot_area": {"x": 0.14, "y": 0.18, "width": 0.62, "height": 0.56},
            "axes": {
                "x_limits": {"min": 0.0, "max": 1.0},
                "y_limits": {"min": 0.0, "max": 2.0},
                "x_ticks": [{"value": 0.0, "label": "A"}, {"value": 1.0, "label": "B"}],
                "y_ticks": [{"value": 0.0, "label": "0"}, {"value": 1.0, "label": "1"}, {"value": 2.0, "label": "2"}],
            },
            "legend": None,
            "reference_lines": [],
            "reference_bands": [],
            "scatter_points": [{"x": 0.2, "y": 1.2, "marker": "circle", "size": 6.0, "color": "#0072B2"}],
            "violin_bodies": [],
            "annotations": {"markers": [], "segments": [], "texts": []},
        }
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.scatter([0, 1, 2], [1.0, 1.1, 1.2], s=10)

        native = mock.Mock(return_value=b"native")
        with mock.patch("modules.chart_renderer._native_render_distribution_png", native):
            result = NativeChartRenderer().render_distribution_png(payload, fallback_fig=fig)

        plt.close(fig)
        native.assert_called_once_with(payload)
        assert result.backend == "native"
        assert result.png_bytes == b"native"


def test_native_iqr_renderer_uses_native_when_finalized_geometry_is_attached(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS", "iqr")
    payload = {
        "type": "iqr",
        "labels": ["Only"],
        "series": [[1.0, 1.1, 1.2, 1.3, 5.0]],
        "title": "Resolved Geometry IQR",
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
    payload["resolved_render_spec"] = build_resolved_iqr_spec(payload)

    native = mock.Mock(return_value=b"native")
    with mock.patch("modules.chart_renderer._native_render_iqr_png", native):
        result = NativeChartRenderer().render_iqr_png(payload)

    native.assert_called_once_with(payload)
    assert result.backend == "native"
    assert result.png_bytes == b"native"


def test_native_trend_renderer_uses_native_when_finalized_geometry_is_attached(monkeypatch):
    monkeypatch.setenv("METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS", "trend")
    payload = {
        "type": "trend",
        "x_values": [0.0, 1.0, 2.0, 3.0],
        "y_values": [1.0, 1.2, 1.1, 1.35],
        "labels": ["S1", "S2", "S3", "S4"],
        "title": "Resolved Geometry Trend",
        "x_label": "Sample #",
        "y_label": "Measurement",
        "horizontal_limits": [0.9, 1.4],
        "layout": {"rotation": 0, "display_positions": [0.0, 1.0, 2.0, 3.0], "display_labels": ["S1", "S2", "S3", "S4"], "bottom_margin": 0.22},
        "canvas": {"width_px": 960, "height_px": 540, "dpi": 150},
    }
    payload["resolved_render_spec"] = build_resolved_trend_spec(payload)

    native = mock.Mock(return_value=b"native")
    with mock.patch("modules.chart_renderer._native_render_trend_png", native):
        result = NativeChartRenderer().render_trend_png(payload)

    native.assert_called_once_with(payload)
    assert result.backend == "native"
    assert result.png_bytes == b"native"


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
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS", "histogram")
        payload = build_histogram_native_payload(
            values=[1.0, 1.2, 1.4, 1.8, 2.0, 2.1, 2.2],
            lsl=1.0,
            usl=2.3,
            title="Real Native Histogram",
            bin_count=6,
        )
        _attach_histogram_resolved_spec(payload)
        result = NativeChartRenderer().render_histogram_png(payload)
        assert result.backend == "native"
        assert isinstance(result.png_bytes, bytes)
        assert len(result.png_bytes) > 0
