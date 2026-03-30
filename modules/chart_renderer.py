"""Compatibility-layer chart rendering backends for export PNG generation.

The compatibility layer keeps worksheet writing unchanged by only replacing the
image-bytes generation step. Backends can be selected via environment variable
for immediate rollback.
"""

from __future__ import annotations

import os
import statistics
import warnings
from abc import ABC, abstractmethod
from io import BytesIO
from typing import Any, Literal, NamedTuple

from modules.matplotlib_runtime import configure_headless_matplotlib

configure_headless_matplotlib()

import matplotlib
matplotlib.use(os.environ.get("MPLBACKEND", "Agg"), force=True)
import matplotlib.pyplot as plt
import numpy as np

BackendChoice = Literal["auto", "native", "matplotlib"]
ResolvedBackend = Literal["native", "matplotlib"]
NATIVE_CHART_RENDERER_ROLLOUT_ENABLED = False

try:
    from _metroliza_chart_native import render_histogram_png as _native_render_histogram_png  # type: ignore
except Exception:  # pragma: no cover - optional native extension
    _native_render_histogram_png = None

try:
    from _metroliza_chart_native import render_distribution_png as _native_render_distribution_png  # type: ignore
except Exception:  # pragma: no cover - optional native extension
    _native_render_distribution_png = None

try:
    from _metroliza_chart_native import render_iqr_png as _native_render_iqr_png  # type: ignore
except Exception:  # pragma: no cover - optional native extension
    _native_render_iqr_png = None

try:
    from _metroliza_chart_native import render_trend_png as _native_render_trend_png  # type: ignore
except Exception:  # pragma: no cover - optional native extension
    _native_render_trend_png = None


class ChartRenderResult(NamedTuple):
    png_bytes: bytes
    backend: ResolvedBackend


class ChartRenderer(ABC):
    """Chart rendering interface used by export paths."""

    @abstractmethod
    def render_figure_png(self, fig: Any, *, mode: str = "workbook", chart_type: str | None = None) -> ChartRenderResult:
        """Render an existing matplotlib figure into PNG bytes."""

    @abstractmethod
    def render_histogram_png(self, payload: dict[str, Any], *, fallback_fig: Any | None = None, mode: str = "workbook") -> ChartRenderResult:
        """Render histogram payload into PNG bytes."""

    @abstractmethod
    def render_distribution_png(self, payload: dict[str, Any], *, fallback_fig: Any | None = None, mode: str = "workbook") -> ChartRenderResult:
        """Render distribution payload into PNG bytes."""

    @abstractmethod
    def render_iqr_png(self, payload: dict[str, Any], *, fallback_fig: Any | None = None, mode: str = "workbook") -> ChartRenderResult:
        """Render IQR boxplot payload into PNG bytes."""

    @abstractmethod
    def render_trend_png(self, payload: dict[str, Any], *, fallback_fig: Any | None = None, mode: str = "workbook") -> ChartRenderResult:
        """Render trend payload into PNG bytes."""


def _savefig_bytes(fig: Any, *, mode: str = "workbook", dpi: int = 150) -> bytes:
    save_kwargs = {"format": "png", "dpi": dpi}
    if mode == "clipped":
        save_kwargs["bbox_inches"] = "tight"
    image_buffer = BytesIO()
    fig.savefig(image_buffer, **save_kwargs)
    return image_buffer.getvalue()


class MatplotlibChartRenderer(ChartRenderer):
    """Matplotlib-only renderer (current behavior)."""

    def render_figure_png(self, fig: Any, *, mode: str = "workbook", chart_type: str | None = None) -> ChartRenderResult:
        return ChartRenderResult(png_bytes=_savefig_bytes(fig, mode=mode), backend="matplotlib")

    def render_histogram_png(self, payload: dict[str, Any], *, fallback_fig: Any | None = None, mode: str = "workbook") -> ChartRenderResult:
        if fallback_fig is None:
            raise RuntimeError("Matplotlib histogram fallback requires a matplotlib figure.")
        return self.render_figure_png(fallback_fig, mode=mode, chart_type="histogram")

    def render_distribution_png(self, payload: dict[str, Any], *, fallback_fig: Any | None = None, mode: str = "workbook") -> ChartRenderResult:
        if fallback_fig is None:
            raise RuntimeError("Matplotlib distribution fallback requires a matplotlib figure.")
        return self.render_figure_png(fallback_fig, mode=mode, chart_type="distribution")

    def render_iqr_png(self, payload: dict[str, Any], *, fallback_fig: Any | None = None, mode: str = "workbook") -> ChartRenderResult:
        if fallback_fig is None:
            raise RuntimeError("Matplotlib IQR fallback requires a matplotlib figure.")
        return self.render_figure_png(fallback_fig, mode=mode, chart_type="iqr")

    def render_trend_png(self, payload: dict[str, Any], *, fallback_fig: Any | None = None, mode: str = "workbook") -> ChartRenderResult:
        if fallback_fig is None:
            raise RuntimeError("Matplotlib trend fallback requires a matplotlib figure.")
        return self.render_figure_png(fallback_fig, mode=mode, chart_type="trend")


class NativeChartRenderer(ChartRenderer):
    """Native histogram renderer with matplotlib fallback for compatibility."""

    def __init__(self, *, fallback_renderer: ChartRenderer | None = None):
        self._fallback = fallback_renderer or MatplotlibChartRenderer()

    def render_figure_png(self, fig: Any, *, mode: str = "workbook", chart_type: str | None = None) -> ChartRenderResult:
        return self._fallback.render_figure_png(fig, mode=mode, chart_type=chart_type)

    def render_histogram_png(self, payload: dict[str, Any], *, fallback_fig: Any | None = None, mode: str = "workbook") -> ChartRenderResult:
        if _native_render_histogram_png is None:
            if fallback_fig is None:
                raise RuntimeError("Native chart renderer unavailable and no matplotlib fallback figure provided.")
            fallback_result = self._fallback.render_figure_png(fallback_fig, mode=mode, chart_type="histogram")
            return ChartRenderResult(png_bytes=fallback_result.png_bytes, backend=fallback_result.backend)

        _validate_histogram_native_payload(payload)
        png_bytes = _native_render_histogram_png(payload)
        if not isinstance(png_bytes, (bytes, bytearray)):
            raise RuntimeError("Native chart renderer returned non-bytes payload.")
        return ChartRenderResult(png_bytes=bytes(png_bytes), backend="native")

    def render_distribution_png(self, payload: dict[str, Any], *, fallback_fig: Any | None = None, mode: str = "workbook") -> ChartRenderResult:
        if _native_render_distribution_png is None:
            if fallback_fig is None:
                raise RuntimeError("Native distribution renderer unavailable and no matplotlib fallback figure provided.")
            fallback_result = self._fallback.render_figure_png(fallback_fig, mode=mode, chart_type="distribution")
            return ChartRenderResult(png_bytes=fallback_result.png_bytes, backend=fallback_result.backend)

        _validate_distribution_native_payload(payload)
        if _distribution_payload_requires_matplotlib_fallback(payload):
            if fallback_fig is None:
                raise RuntimeError(
                    "Native distribution rendering requires finalized matplotlib geometry or a matplotlib fallback figure."
                )
            fallback_result = self._fallback.render_figure_png(fallback_fig, mode=mode, chart_type="distribution")
            return ChartRenderResult(png_bytes=fallback_result.png_bytes, backend=fallback_result.backend)
        try:
            png_bytes = _native_render_distribution_png(payload)
        except Exception:
            if fallback_fig is None:
                raise
            fallback_result = self._fallback.render_figure_png(fallback_fig, mode=mode, chart_type="distribution")
            return ChartRenderResult(png_bytes=fallback_result.png_bytes, backend=fallback_result.backend)
        if not isinstance(png_bytes, (bytes, bytearray)):
            raise RuntimeError("Native distribution renderer returned non-bytes payload.")
        return ChartRenderResult(png_bytes=bytes(png_bytes), backend="native")

    def render_iqr_png(self, payload: dict[str, Any], *, fallback_fig: Any | None = None, mode: str = "workbook") -> ChartRenderResult:
        if _native_render_iqr_png is None:
            if fallback_fig is None:
                raise RuntimeError("Native IQR renderer unavailable and no matplotlib fallback figure provided.")
            fallback_result = self._fallback.render_figure_png(fallback_fig, mode=mode, chart_type="iqr")
            return ChartRenderResult(png_bytes=fallback_result.png_bytes, backend=fallback_result.backend)

        _validate_iqr_native_payload(payload)
        png_bytes = _native_render_iqr_png(payload)
        if not isinstance(png_bytes, (bytes, bytearray)):
            raise RuntimeError("Native IQR renderer returned non-bytes payload.")
        return ChartRenderResult(png_bytes=bytes(png_bytes), backend="native")

    def render_trend_png(self, payload: dict[str, Any], *, fallback_fig: Any | None = None, mode: str = "workbook") -> ChartRenderResult:
        if _native_render_trend_png is None:
            if fallback_fig is None:
                raise RuntimeError("Native trend renderer unavailable and no matplotlib fallback figure provided.")
            fallback_result = self._fallback.render_figure_png(fallback_fig, mode=mode, chart_type="trend")
            return ChartRenderResult(png_bytes=fallback_result.png_bytes, backend=fallback_result.backend)

        _validate_trend_native_payload(payload)
        png_bytes = _native_render_trend_png(payload)
        if not isinstance(png_bytes, (bytes, bytearray)):
            raise RuntimeError("Native trend renderer returned non-bytes payload.")
        return ChartRenderResult(png_bytes=bytes(png_bytes), backend="native")


def _runtime_backend_choice() -> BackendChoice:
    choice = os.getenv("METROLIZA_CHART_RENDERER_BACKEND", "auto").strip().lower()
    if choice in {"auto", "native", "matplotlib"}:
        return choice
    return "auto"


def native_chart_backend_available() -> bool:
    """Return whether the native chart renderer can accelerate primary export charts.

    `NativeChartRenderer` is selected for native histogram acceleration and
    keeps per-chart matplotlib fallbacks for unsupported chart types.
    """

    return native_histogram_backend_available()


def native_full_chart_backend_available() -> bool:
    """Return whether all currently modeled chart types have native support."""

    return (
        native_histogram_backend_available()
        and native_distribution_backend_available()
        and native_iqr_backend_available()
        and native_trend_backend_available()
    )


def native_histogram_backend_available() -> bool:
    """Return whether native histogram rendering is available."""
    return _native_render_histogram_png is not None


def native_distribution_backend_available() -> bool:
    """Return whether native distribution rendering is available."""
    return _native_render_distribution_png is not None


def native_iqr_backend_available() -> bool:
    """Return whether native IQR rendering is available."""
    return _native_render_iqr_png is not None


def native_trend_backend_available() -> bool:
    """Return whether native trend rendering is available."""
    return _native_render_trend_png is not None


def native_chart_renderer_rollout_enabled() -> bool:
    """Return whether the native chart backend is allowed past the rollout gate."""

    return bool(NATIVE_CHART_RENDERER_ROLLOUT_ENABLED)


def _warn_native_backend_disabled(*, chart_kind: str) -> None:
    warnings.warn(
        f"METROLIZA_CHART_RENDERER_BACKEND=native requested for {chart_kind} charts, but native chart rendering is disabled by rollout policy; falling back to matplotlib backend.",
        RuntimeWarning,
        stacklevel=2,
    )


def _resolve_native_backend_with_policy(*, chart_kind: str, backend_available: bool, backend: BackendChoice) -> ResolvedBackend:
    if backend == "matplotlib":
        return "matplotlib"
    if backend == "native":
        if not native_chart_renderer_rollout_enabled():
            _warn_native_backend_disabled(chart_kind=chart_kind)
            return "matplotlib"
        if not backend_available:
            warnings.warn(
                f"METROLIZA_CHART_RENDERER_BACKEND=native requested for {chart_kind} charts, but the native renderer is unavailable; falling back to matplotlib backend.",
                RuntimeWarning,
                stacklevel=2,
            )
            return "matplotlib"
        return "native"
    return "matplotlib"


def resolve_chart_renderer_backend() -> ResolvedBackend:
    """Resolve the primary chart renderer backend policy for histogram exports.

    Native rendering is held behind an explicit rollout gate; the default
    policy keeps export rendering on matplotlib.
    """
    backend = _runtime_backend_choice()
    return _resolve_native_backend_with_policy(
        chart_kind="histogram",
        backend_available=native_histogram_backend_available(),
        backend=backend,
    )


def resolve_distribution_renderer_backend() -> ResolvedBackend:
    """Resolve the effective backend for distribution chart rendering."""

    backend = _runtime_backend_choice()
    return _resolve_native_backend_with_policy(
        chart_kind="distribution",
        backend_available=native_distribution_backend_available(),
        backend=backend,
    )


def build_chart_renderer() -> ChartRenderer:
    """Build the configured chart renderer implementation."""
    resolved = resolve_chart_renderer_backend()
    if resolved == "native":
        return NativeChartRenderer()
    return MatplotlibChartRenderer()


def build_histogram_native_payload(
    *,
    values: np.ndarray | list[float],
    lsl: float | None,
    usl: float | None,
    title: str,
    bin_count: int | None = None,
    compact_render: bool = False,
) -> dict[str, Any]:
    """Build the base native histogram payload.

    Contract:
    - `type`: fixed string `"histogram"`.
    - `values`: finite numeric sample list.
    - `title`: chart title.
    - `lsl`/`usl`: optional numeric spec limits.
    - `bin_count`: optional explicit bin count.
    - `visual_metadata`: optional worksheet-parity metadata used by callers.
      - `specification_lines`: list[dict] for LSL/USL/nominal line intent.
      - `summary_stats_table`: dict with rendered row metadata.
      - `annotation_rows`: list[dict] with label placement hints.
      - `modeled_overlays`: dict describing disabled/enabled model overlays.
    - `compact_render`: explicit stripped-render fast path. Rich workbook
      exports should leave this disabled.
    """
    numeric = np.asarray(values, dtype=float)
    finite = numeric[np.isfinite(numeric)]
    payload: dict[str, Any] = {
        "type": "histogram",
        "values": finite.tolist(),
        "title": title,
        "lsl": None if lsl is None else float(lsl),
        "usl": None if usl is None else float(usl),
        "bin_count": None if bin_count is None else int(bin_count),
        "compact_render": bool(compact_render),
        "summary_table_title": "Parameter",
        "summary_table_rows": [],
        "annotation_rows": [],
        "specification_lines": [],
        "modeled_overlay_rows": [],
        "visual_metadata": {
            "specification_lines": [],
            "summary_stats_table": {"title": "Parameter", "columns": ["Parameter", "Value"], "rows": []},
            "annotation_rows": [],
            "modeled_overlays": {"advanced_annotations_enabled": False, "overlays_enabled": False, "rows": []},
        },
    }
    return payload


def build_distribution_native_payload(
    *,
    values: list[list[float]] | np.ndarray,
    labels: list[str],
    title: str,
    lsl: float | None = None,
    usl: float | None = None,
) -> dict[str, Any]:
    """Build base native payload contract for distribution charts."""
    normalized_values: list[list[float]] = []
    for series in values:
        numeric = np.asarray(series, dtype=float)
        normalized_values.append(numeric[np.isfinite(numeric)].tolist())
    return {
        "type": "distribution",
        "series": normalized_values,
        "labels": [str(label) for label in labels],
        "title": str(title),
        "lsl": None if lsl is None else float(lsl),
        "usl": None if usl is None else float(usl),
    }


def _validate_histogram_native_payload(payload: dict[str, Any]) -> None:
    """Validate native histogram payload contract before crossing backend boundary."""
    if not isinstance(payload, dict):
        raise RuntimeError("Native histogram payload must be a mapping.")
    if payload.get("type") != "histogram":
        raise RuntimeError("Native histogram payload `type` must equal `histogram`.")
    values = payload.get("values")
    if not isinstance(values, list):
        raise RuntimeError("Native histogram payload `values` must be a list.")
    if any(not isinstance(item, (int, float)) for item in values):
        raise RuntimeError("Native histogram payload `values` must only contain numbers.")
    if not isinstance(payload.get("title"), str):
        raise RuntimeError("Native histogram payload `title` must be a string.")

    visual_metadata = payload.get("visual_metadata")
    if visual_metadata is None:
        return
    if not isinstance(visual_metadata, dict):
        raise RuntimeError("Native histogram payload `visual_metadata` must be a mapping when provided.")

    spec_lines = visual_metadata.get("specification_lines")
    if spec_lines is not None and not isinstance(spec_lines, list):
        raise RuntimeError("Native histogram payload `visual_metadata.specification_lines` must be a list.")

    table_meta = visual_metadata.get("summary_stats_table")
    if table_meta is not None and not isinstance(table_meta, dict):
        raise RuntimeError("Native histogram payload `visual_metadata.summary_stats_table` must be a mapping.")

    annotation_rows = visual_metadata.get("annotation_rows")
    if annotation_rows is not None and not isinstance(annotation_rows, list):
        raise RuntimeError("Native histogram payload `visual_metadata.annotation_rows` must be a list.")

    modeled_overlays = visual_metadata.get("modeled_overlays")
    if modeled_overlays is not None and not isinstance(modeled_overlays, dict):
        raise RuntimeError("Native histogram payload `visual_metadata.modeled_overlays` must be a mapping.")

    top_level_table_rows = payload.get("summary_table_rows")
    if top_level_table_rows is not None and not isinstance(top_level_table_rows, list):
        raise RuntimeError("Native histogram payload `summary_table_rows` must be a list when provided.")

    top_level_annotation_rows = payload.get("annotation_rows")
    if top_level_annotation_rows is not None and not isinstance(top_level_annotation_rows, list):
        raise RuntimeError("Native histogram payload `annotation_rows` must be a list when provided.")

    top_level_spec_lines = payload.get("specification_lines")
    if top_level_spec_lines is not None and not isinstance(top_level_spec_lines, list):
        raise RuntimeError("Native histogram payload `specification_lines` must be a list when provided.")

    top_level_overlay_rows = payload.get("modeled_overlay_rows")
    if top_level_overlay_rows is not None and not isinstance(top_level_overlay_rows, list):
        raise RuntimeError("Native histogram payload `modeled_overlay_rows` must be a list when provided.")


def _validate_distribution_native_payload(payload: dict[str, Any]) -> None:
    """Validate native distribution payload contract before backend dispatch."""
    if not isinstance(payload, dict):
        raise RuntimeError("Native distribution payload must be a mapping.")
    if payload.get("type") != "distribution":
        raise RuntimeError("Native distribution payload `type` must equal `distribution`.")
    labels = payload.get("labels")
    if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
        raise RuntimeError("Native distribution payload `labels` must be a list[str].")
    series = payload.get("series")
    if not isinstance(series, list):
        raise RuntimeError("Native distribution payload `series` must be a list of numeric series.")
    for values in series:
        if not isinstance(values, list) or any(not isinstance(item, (int, float)) for item in values):
            raise RuntimeError("Native distribution payload `series` entries must be list[float].")
    if len(series) != len(labels):
        raise RuntimeError("Native distribution payload requires equal series/labels length.")
    if not isinstance(payload.get("title"), str):
        raise RuntimeError("Native distribution payload `title` must be a string.")


def _resolved_rect_complete(rect: Any) -> bool:
    return (
        isinstance(rect, dict)
        and all(isinstance(rect.get(key), (int, float)) for key in ("x", "y", "width", "height"))
    )


def _resolved_axes_complete(axes: Any) -> bool:
    return (
        isinstance(axes, dict)
        and isinstance(axes.get("x_limits"), dict)
        and isinstance(axes.get("y_limits"), dict)
        and isinstance(axes.get("x_ticks"), list)
        and isinstance(axes.get("y_ticks"), list)
    )


def _distribution_payload_requires_matplotlib_fallback(payload: dict[str, Any]) -> bool:
    resolved = payload.get("resolved_render_spec")
    if not isinstance(resolved, dict):
        return True
    plot_area = resolved.get("plot_area")
    if not _resolved_rect_complete(plot_area):
        plot_area = resolved.get("plot_rect")
    if not _resolved_rect_complete(plot_area):
        return True
    if not isinstance(resolved.get("title"), dict):
        return True
    if not _resolved_axes_complete(resolved.get("axes")):
        return True
    if "legend" not in resolved:
        return True
    if not isinstance(resolved.get("reference_lines"), list):
        return True
    if not isinstance(resolved.get("reference_bands"), list):
        return True

    render_mode = str(resolved.get("render_mode") or payload.get("render_mode") or "violin").strip().lower()
    if render_mode == "scatter":
        return not (
            isinstance(resolved.get("scatter_points"), list)
            and isinstance(resolved.get("annotations"), dict)
            and isinstance(resolved.get("violin_bodies"), list)
        )
    return not (
        isinstance(resolved.get("violin_bodies"), list)
        and isinstance(resolved.get("annotations"), dict)
        and isinstance(resolved.get("scatter_points"), list)
    )


def _validate_iqr_native_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise RuntimeError("Native IQR payload must be a mapping.")
    if payload.get("type") != "iqr":
        raise RuntimeError("Native IQR payload `type` must equal `iqr`.")
    labels = payload.get("labels")
    series = payload.get("series")
    if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
        raise RuntimeError("Native IQR payload `labels` must be a list[str].")
    if not isinstance(series, list) or len(series) != len(labels):
        raise RuntimeError("Native IQR payload requires equal series/labels length.")
    for values in series:
        if not isinstance(values, list) or any(not isinstance(item, (int, float)) for item in values):
            raise RuntimeError("Native IQR payload `series` entries must be list[float].")


def _validate_trend_native_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise RuntimeError("Native trend payload must be a mapping.")
    if payload.get("type") != "trend":
        raise RuntimeError("Native trend payload `type` must equal `trend`.")
    x_values = payload.get("x_values")
    y_values = payload.get("y_values")
    labels = payload.get("labels")
    if not isinstance(x_values, list) or any(not isinstance(item, (int, float)) for item in x_values):
        raise RuntimeError("Native trend payload `x_values` must be a list[float].")
    if not isinstance(y_values, list) or any(not isinstance(item, (int, float)) for item in y_values):
        raise RuntimeError("Native trend payload `y_values` must be a list[float].")
    if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
        raise RuntimeError("Native trend payload `labels` must be a list[str].")
    if len(x_values) != len(y_values) or len(x_values) != len(labels):
        raise RuntimeError("Native trend payload requires equal x/y/labels length.")


def _histogram_visual_metadata_requires_matplotlib_fallback(payload: dict[str, Any]) -> bool:
    """Compatibility shim kept for tests and old callers."""
    return False


def benchmark_histogram_render_runtime(renderer: ChartRenderer, payload: dict[str, Any], *, iterations: int = 3) -> dict[str, float]:
    """Simple runtime benchmark helper for large-cardinality export scenarios."""
    import time

    samples: list[float] = []
    for _ in range(max(1, int(iterations))):
        start = time.perf_counter()
        _ = renderer.render_histogram_png(payload, fallback_fig=plt.figure(figsize=(8, 4)))
        samples.append(time.perf_counter() - start)
        plt.close("all")
    median_s = float(statistics.median(samples)) if samples else 0.0
    return {
        "iterations": float(len(samples)),
        "median_s": median_s,
        "runtime_min_ms": float(min(samples) * 1000.0),
        "runtime_avg_ms": float(sum(samples) / len(samples) * 1000.0),
        "runtime_median_ms": float(median_s * 1000.0),
        "runtime_max_ms": float(max(samples) * 1000.0),
    }
