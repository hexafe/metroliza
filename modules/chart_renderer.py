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

try:
    from _metroliza_chart_native import render_histogram_png as _native_render_histogram_png  # type: ignore
except Exception:  # pragma: no cover - optional native extension
    _native_render_histogram_png = None

try:
    from _metroliza_chart_native import render_distribution_png as _native_render_distribution_png  # type: ignore
except Exception:  # pragma: no cover - optional native extension
    _native_render_distribution_png = None


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
        png_bytes = _native_render_distribution_png(payload)
        if not isinstance(png_bytes, (bytes, bytearray)):
            raise RuntimeError("Native distribution renderer returned non-bytes payload.")
        return ChartRenderResult(png_bytes=bytes(png_bytes), backend="native")


def _runtime_backend_choice() -> BackendChoice:
    choice = os.getenv("METROLIZA_CHART_RENDERER_BACKEND", "auto").strip().lower()
    if choice in {"auto", "native", "matplotlib"}:
        return choice
    return "auto"


def native_chart_backend_available() -> bool:
    """Backward-compatible aggregate availability check for native chart support."""
    return native_histogram_backend_available() and native_distribution_backend_available()


def native_histogram_backend_available() -> bool:
    """Return whether native histogram rendering is available."""
    return _native_render_histogram_png is not None


def native_distribution_backend_available() -> bool:
    """Return whether native distribution rendering is available."""
    return _native_render_distribution_png is not None


def resolve_chart_renderer_backend() -> ResolvedBackend:
    """Resolve chart renderer backend policy based on runtime configuration."""
    backend = _runtime_backend_choice()
    if backend == "matplotlib":
        return "matplotlib"
    if backend == "native":
        if not native_histogram_backend_available():
            warnings.warn(
                "METROLIZA_CHART_RENDERER_BACKEND=native requested but _metroliza_chart_native is unavailable; falling back to matplotlib backend.",
                RuntimeWarning,
                stacklevel=2,
            )
            return "matplotlib"
        return "native"
    if native_histogram_backend_available():
        return "native"
    return "matplotlib"


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
