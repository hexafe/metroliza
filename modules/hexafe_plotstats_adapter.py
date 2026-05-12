"""Narrow adapter for histogram rendering through hexafe-plotstats."""

from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO
from typing import Any, Iterable

import numpy as np
import pandas as pd

from modules.export_chart_payload_helpers import build_histogram_table_data
from modules.export_summary_utils import resolve_histogram_bin_count
from modules.matplotlib_runtime import configure_headless_matplotlib
from modules.summary_plot_palette import SUMMARY_PLOT_PALETTE

configure_headless_matplotlib()


@dataclass(frozen=True)
class HistogramStatsTable:
    """Display-ready histogram statistics rows."""

    title: str
    rows: tuple[tuple[str, str], ...]
    backend: str = "metroliza"

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "backend": self.backend,
            "rows": [{"label": label, "value": value} for label, value in self.rows],
        }


@dataclass(frozen=True)
class HistogramRenderResult:
    """Rendered histogram image and the stats table embedded in it."""

    png_bytes: bytes
    backend: str
    stats_table: HistogramStatsTable


def build_histogram_stats_table(
    values: Iterable[Any],
    *,
    title: str = "Parameter",
    backend: str = "metroliza",
) -> HistogramStatsTable | None:
    array = _finite_values(values)
    if array.size == 0:
        return None
    table_payload = build_histogram_table_data(_summary_stats(array))
    rows = tuple((str(label), str(value)) for label, value in table_payload.get("rows", ()))
    return HistogramStatsTable(title=str(title or "Parameter"), rows=rows, backend=backend)


def render_histogram_png(
    values: Iterable[Any],
    *,
    title: str,
    metric_label: str,
    bin_count: int | None = None,
) -> HistogramRenderResult | None:
    """Render a histogram PNG through hexafe-plotstats, falling back to local Matplotlib."""

    array = _finite_values(values)
    if array.size == 0:
        return None
    resolved_bin_count = _resolved_bin_count(array, bin_count=bin_count)
    stats_table = build_histogram_stats_table(array, title="Parameter", backend="hexafe-plotstats")
    if stats_table is None:
        return None

    result = _render_with_hexafe_plotstats(
        array,
        title=title,
        metric_label=metric_label,
        bin_count=resolved_bin_count,
        stats_table=stats_table,
    )
    if result is not None:
        return result
    return _render_with_metroliza_fallback(
        array,
        title=title,
        metric_label=metric_label,
        bin_count=resolved_bin_count,
        stats_table=replace(stats_table, backend="metroliza-fallback"),
    )


def _render_with_hexafe_plotstats(
    values: np.ndarray,
    *,
    title: str,
    metric_label: str,
    bin_count: int,
    stats_table: HistogramStatsTable,
) -> HistogramRenderResult | None:
    try:
        from hexafe_plotstats import HistogramConfig, build_histogram_payload, render_histogram
        from hexafe_plotstats.models.payloads import TableRow
    except Exception:
        return None

    try:
        payload = build_histogram_payload(
            values,
            config=HistogramConfig(bins=bin_count, density=False, include_fit=False),
            metadata={
                "title": title,
                "axis_labels": {"x": metric_label, "y": "Count"},
            },
        )
        payload = replace(
            payload,
            table_rows=tuple(
                TableRow(label=label, value=value, kind="summary_metric")
                for label, value in stats_table.rows
            ),
        )
        render_result = render_histogram(payload, backend="matplotlib")
        png_bytes = _figure_png_bytes(render_result.fig)
        return HistogramRenderResult(
            png_bytes=png_bytes,
            backend="hexafe-plotstats",
            stats_table=stats_table,
        )
    except Exception:
        return None
    finally:
        _close_plotstats_figure(locals().get("render_result"))


def _render_with_metroliza_fallback(
    values: np.ndarray,
    *,
    title: str,
    metric_label: str,
    bin_count: int,
    stats_table: HistogramStatsTable,
) -> HistogramRenderResult:
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(7.4, 3.7))
    try:
        grid = fig.add_gridspec(1, 2, width_ratios=(3.0, 1.35), wspace=0.25)
        ax = fig.add_subplot(grid[0, 0])
        table_ax = fig.add_subplot(grid[0, 1])
        ax.hist(
            values,
            bins=bin_count,
            color=SUMMARY_PLOT_PALETTE["distribution_base"],
            edgecolor=SUMMARY_PLOT_PALETTE["distribution_foreground"],
            alpha=0.82,
        )
        ax.set_title(title, color=SUMMARY_PLOT_PALETTE["annotation_text"])
        ax.set_xlabel(metric_label, color=SUMMARY_PLOT_PALETTE["axis_text"])
        ax.set_ylabel("Count", color=SUMMARY_PLOT_PALETTE["axis_text"])
        ax.grid(
            True,
            axis="y",
            color=SUMMARY_PLOT_PALETTE["grid"],
            linewidth=0.5,
            alpha=0.45,
        )
        for spine in ax.spines.values():
            spine.set_color(SUMMARY_PLOT_PALETTE["axis_spine"])
        ax.tick_params(axis="both", colors=SUMMARY_PLOT_PALETTE["axis_text"])
        _draw_stats_table(table_ax, stats_table)
        fig.subplots_adjust(left=0.08, right=0.98, bottom=0.16, top=0.88, wspace=0.28)
        png_bytes = _figure_png_bytes(fig)
    finally:
        plt.close(fig)
    return HistogramRenderResult(
        png_bytes=png_bytes,
        backend=stats_table.backend,
        stats_table=stats_table,
    )


def _draw_stats_table(table_ax, stats_table: HistogramStatsTable) -> None:
    table_ax.axis("off")
    cell_text = [[label, value] for label, value in stats_table.rows]
    table = table_ax.table(
        cellText=cell_text,
        colLabels=["Parameter", "Value"],
        cellLoc="left",
        colLoc="left",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.4)
    table.scale(1.0, 1.12)
    for (row, _col), cell in table.get_celld().items():
        cell.set_edgecolor("#d1d5db")
        cell.set_linewidth(0.55)
        if row == 0:
            cell.set_facecolor("#eef2f7")
            cell.set_text_props(weight="bold", color="#111827")
        else:
            cell.set_facecolor("#ffffff")
            cell.set_text_props(color="#1f2933")
    table_ax.set_title(stats_table.title, fontsize=10, fontweight="bold", color="#111827")


def _figure_png_bytes(fig) -> bytes:
    image = BytesIO()
    fig.savefig(image, format="png", dpi=150, bbox_inches="tight")
    image.seek(0)
    return image.getvalue()


def _close_plotstats_figure(render_result) -> None:
    if render_result is None or not hasattr(render_result, "fig"):
        return
    try:
        import matplotlib.pyplot as plt

        plt.close(render_result.fig)
    except Exception:
        return


def _finite_values(values: Iterable[Any]) -> np.ndarray:
    series = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    if series.empty:
        return np.asarray([], dtype=float)
    array = series.to_numpy(dtype=float)
    return array[np.isfinite(array)]


def _summary_stats(values: np.ndarray) -> dict[str, Any]:
    sample_size = int(values.size)
    sigma = float(np.std(values, ddof=1)) if sample_size > 1 else None
    return {
        "minimum": float(np.min(values)),
        "maximum": float(np.max(values)),
        "average": float(np.mean(values)),
        "median": float(np.median(values)),
        "sigma": sigma,
        "cp": "N/A",
        "cpk": "N/A",
        "capability_ci": {},
        "sample_size": sample_size,
        "nok_count": 0,
        "nok_pct": 0.0,
        "observed_nok_count": 0,
        "observed_nok_pct": 0.0,
        "estimated_nok_pct": None,
        "estimated_nok_ppm": None,
        "estimated_yield_pct": None,
    }


def _resolved_bin_count(values: np.ndarray, *, bin_count: int | None = None) -> int:
    if bin_count is not None and int(bin_count) > 0:
        return int(bin_count)
    return max(1, int(resolve_histogram_bin_count(values).get("bin_count") or 1))


__all__ = [
    "HistogramRenderResult",
    "HistogramStatsTable",
    "build_histogram_stats_table",
    "render_histogram_png",
]
