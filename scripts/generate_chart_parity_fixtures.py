#!/usr/bin/env python3
# ruff: noqa: E402
"""Generate deterministic chart parity fixtures for native-vs-matplotlib rollout.

Output structure (under tests/fixtures/chart_parity by default):
- <fixture>/payload.json
- <fixture>/planner_spec.json
- <fixture>/matplotlib_reference.png
- <fixture>/matplotlib_oracle_geometry.json (where matplotlib extraction exists)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle

# Allow direct execution without requiring external PYTHONPATH configuration.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.chart_render_spec import (
    build_resolved_distribution_spec,
    build_resolved_histogram_spec,
    build_resolved_iqr_spec,
    build_resolved_trend_spec,
    histogram_spec_to_mapping,
)
from modules.chart_renderer import build_distribution_native_payload, build_histogram_native_payload
from modules.matplotlib_distribution_geometry import extract_distribution_geometry
from modules.matplotlib_iqr_trend_geometry import extract_iqr_geometry, extract_trend_geometry


FIXTURE_SET_VERSION = 1
DEFAULT_DPI = 150


def _configure_matplotlib() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
            "axes.facecolor": "white",
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def _write_json(path: Path, payload: Mapping[str, Any] | list[Any]) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
    path.write_text(f"{text}\n", encoding="utf-8")


def _save_fig_png(fig: plt.Figure, path: Path) -> None:
    fig.savefig(
        path,
        format="png",
        dpi=int(round(float(fig.dpi))),
        metadata={"Software": "metroliza chart parity fixture generator"},
    )


def _spec_rect_to_axes_position(rect: Mapping[str, Any]) -> list[float]:
    return [
        float(rect.get("x") or 0.0),
        1.0 - float(rect.get("y") or 0.0) - float(rect.get("height") or 0.0),
        float(rect.get("width") or 0.0),
        float(rect.get("height") or 0.0),
    ]


def _marker_name(marker: Any) -> str:
    marker_text = str(marker or "circle").lower()
    return {
        "circle": "o",
        "triangle_up": "^",
        "triangle_down": "v",
        "square": "s",
    }.get(marker_text, marker_text)


def _apply_spec_axes(ax: plt.Axes, spec: Mapping[str, Any]) -> None:
    axes = spec.get("axes") if isinstance(spec.get("axes"), Mapping) else {}
    x_limits = axes.get("x_limits") if isinstance(axes.get("x_limits"), Mapping) else {}
    y_limits = axes.get("y_limits") if isinstance(axes.get("y_limits"), Mapping) else {}
    ax.set_xlim(float(x_limits.get("min") or 0.0), float(x_limits.get("max") or 1.0))
    ax.set_ylim(float(y_limits.get("min") or 0.0), float(y_limits.get("max") or 1.0))
    x_ticks = [float(item.get("value") or 0.0) for item in list(axes.get("x_ticks") or []) if isinstance(item, Mapping)]
    x_labels = [str(item.get("label") or "") for item in list(axes.get("x_ticks") or []) if isinstance(item, Mapping)]
    y_ticks = [float(item.get("value") or 0.0) for item in list(axes.get("y_ticks") or []) if isinstance(item, Mapping)]
    y_labels = [str(item.get("label") or "") for item in list(axes.get("y_ticks") or []) if isinstance(item, Mapping)]
    if x_ticks:
        ax.set_xticks(x_ticks)
        ax.set_xticklabels(x_labels, rotation=int(axes.get("rotation") or 0))
    if y_ticks:
        ax.set_yticks(y_ticks)
        ax.set_yticklabels(y_labels)
    ax.set_xlabel(str(axes.get("x_label") or ""))
    ax.set_ylabel(str(axes.get("y_label") or ""))
    ax.grid(axis=str(axes.get("grid_axis") or "y"), color="#d9dfe7", linewidth=0.8)
    ax.tick_params(axis="both", colors="#4d5968")


def _apply_spec_title(fig: plt.Figure, spec: Mapping[str, Any]) -> None:
    title = spec.get("title") if isinstance(spec.get("title"), Mapping) else {}
    anchor = title.get("anchor") if isinstance(title.get("anchor"), Mapping) else {}
    font = title.get("font") if isinstance(title.get("font"), Mapping) else {}
    text = str(title.get("text") or "")
    if not text:
        return
    fig.text(
        float(anchor.get("x") or 0.06),
        1.0 - float(anchor.get("y") or 0.985),
        text,
        ha=str(title.get("ha") or "left"),
        va=str(title.get("va") or "top"),
        fontsize=float(font.get("size") or 10.0),
        fontweight=str(font.get("weight") or "bold"),
        color=str(title.get("color") or "#1f1f1f"),
    )


def _render_histogram_from_spec(spec: Mapping[str, Any], output_path: Path) -> None:
    canvas = spec.get("canvas") if isinstance(spec.get("canvas"), Mapping) else {}
    width_px = int(canvas.get("width_px") or 900)
    height_px = int(canvas.get("height_px") or 450)
    dpi = int(canvas.get("dpi") or DEFAULT_DPI)
    fig = plt.figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    try:
        _apply_spec_title(fig, spec)
        plot_area = spec.get("plot_area") if isinstance(spec.get("plot_area"), Mapping) else {}
        ax = fig.add_axes(_spec_rect_to_axes_position(plot_area))
        _apply_spec_axes(ax, spec)

        for bar in list(spec.get("bars") or []):
            if not isinstance(bar, Mapping):
                continue
            left = float(bar.get("left_edge") or 0.0)
            right = float(bar.get("right_edge") or left)
            count = float(bar.get("count") or 0.0)
            width = max(0.0, right - left)
            ax.bar(
                left,
                count,
                width=width,
                align="edge",
                color=str(bar.get("fill_color") or "#56B4E9"),
                alpha=float(bar.get("fill_alpha") or 0.84),
                edgecolor=str(bar.get("edge_color") or "#ffffff"),
                linewidth=float(bar.get("edge_width") or 1.0),
            )

        lines = spec.get("lines") if isinstance(spec.get("lines"), Mapping) else {}
        mean_line = lines.get("mean") if isinstance(lines.get("mean"), Mapping) else None
        if mean_line is not None:
            ax.axvline(
                float(mean_line.get("value") or 0.0),
                color=str(mean_line.get("color") or "#E69F00"),
                linewidth=float(mean_line.get("width") or 1.8),
                alpha=float(mean_line.get("alpha") or 0.9),
                linestyle="--" if mean_line.get("dash") else "-",
            )
        for line in list(lines.get("specification") or []):
            if not isinstance(line, Mapping):
                continue
            ax.axvline(
                float(line.get("value") or 0.0),
                color=str(line.get("color") or "#D55E00"),
                linewidth=float(line.get("width") or 1.5),
                alpha=float(line.get("alpha") or 0.9),
                linestyle="--" if line.get("dash") else "-",
            )

        table_rect = spec.get("table_rect") if isinstance(spec.get("table_rect"), Mapping) else None
        table_payload = spec.get("table") if isinstance(spec.get("table"), Mapping) else None
        if table_rect is not None and table_payload is not None:
            table_ax = fig.add_axes(_spec_rect_to_axes_position(table_rect))
            table_ax.axis("off")
            title = str(table_payload.get("title") or "")
            rows = list(table_payload.get("rows") or [])
            table_text = [f"{str(item.get('label') or '')}: {str(item.get('value') or '')}" for item in rows if isinstance(item, Mapping)]
            text = title + ("\n" if title and table_text else "") + "\n".join(table_text)
            table_ax.text(0.0, 1.0, text, ha="left", va="top", fontsize=8.0, color="#1f1f1f")
            table_ax.add_patch(Rectangle((0.0, 0.0), 1.0, 1.0, fill=False, linewidth=0.8, edgecolor="#c7ced7"))

        for item in list(spec.get("annotations") or []):
            if not isinstance(item, Mapping):
                continue
            text = str(item.get("text") or "")
            x_value = float(item.get("x_value") or 0.0)
            leader_y = float(item.get("leader_y") or 0.85)
            box_y = float(item.get("box_y") or 0.90)
            color = str(item.get("color") or "#4d5968")
            ax.annotate(
                text,
                xy=(x_value, leader_y),
                xycoords=("data", "axes fraction"),
                xytext=(x_value, box_y),
                textcoords=("data", "axes fraction"),
                fontsize=7.4,
                color=color,
                ha=str(item.get("align") or "center"),
                va="bottom",
                arrowprops={"arrowstyle": "-", "color": color, "linewidth": 0.8},
                bbox={"boxstyle": "round,pad=0.18", "facecolor": "white", "edgecolor": "#c7ced7", "linewidth": 0.6},
            )
        _save_fig_png(fig, output_path)
    finally:
        plt.close(fig)


def _distribution_scatter_payload() -> dict[str, Any]:
    payload = build_distribution_native_payload(
        values=[[1.0, 1.08, 1.12], [1.34, 1.43, 1.52]],
        labels=["Alpha", "Beta"],
        title="Distribution Parity Scatter",
        lsl=0.9,
        usl=1.8,
    )
    payload.update(
        {
            "render_mode": "scatter",
            "x_values": [0.2, 0.8],
            "y_values": [1.05, 1.41],
            "x_domain": {"min": 0.0, "max": 1.0},
            "x_label": "Group",
            "y_label": "Measurement",
            "layout": {
                "rotation": 0,
                "display_positions": [0.0, 1.0],
                "display_labels": ["Alpha", "Beta"],
                "bottom_margin": 0.22,
            },
            "canvas": {"width_px": 960, "height_px": 540, "dpi": DEFAULT_DPI},
        }
    )
    return payload


def _distribution_violin_payload() -> dict[str, Any]:
    payload = build_distribution_native_payload(
        values=[[0.96, 1.00, 1.05, 1.10, 1.14], [1.32, 1.37, 1.42, 1.48, 1.55]],
        labels=["Alpha", "Beta"],
        title="Distribution Parity Violin",
        lsl=0.9,
        usl=1.8,
    )
    payload.update(
        {
            "render_mode": "violin",
            "positions": [0.0, 1.0],
            "x_label": "Group",
            "y_label": "Measurement",
            "layout": {
                "rotation": 0,
                "display_positions": [0.0, 1.0],
                "display_labels": ["Alpha", "Beta"],
                "bottom_margin": 0.22,
            },
            "annotation_style": {"show_minmax": True, "show_sigma": True},
            "violin_annotations": [
                {
                    "position": 0.0,
                    "mean": 1.05,
                    "minimum": 0.96,
                    "maximum": 1.14,
                    "sigma_start": 0.98,
                    "sigma_high": 1.12,
                    "show_sigma_segment": True,
                },
                {
                    "position": 1.0,
                    "mean": 1.43,
                    "minimum": 1.32,
                    "maximum": 1.55,
                    "sigma_start": 1.36,
                    "sigma_high": 1.50,
                    "show_sigma_segment": True,
                },
            ],
            "legend": {
                "items": [
                    {"label": "Mean", "kind": "marker", "marker": "circle", "color": "#0072B2"},
                    {"label": "Spec limits", "kind": "line", "color": "#D55E00"},
                ]
            },
            "canvas": {"width_px": 960, "height_px": 540, "dpi": DEFAULT_DPI},
        }
    )
    return payload


def _build_distribution_figure(payload: dict[str, Any]) -> tuple[plt.Figure, plt.Axes]:
    canvas = payload.get("canvas") if isinstance(payload.get("canvas"), Mapping) else {}
    dpi = int(canvas.get("dpi") or DEFAULT_DPI)
    width = int(canvas.get("width_px") or 960)
    height = int(canvas.get("height_px") or 540)
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    mode = str(payload.get("render_mode") or "violin").strip().lower()

    if mode == "scatter":
        ax.scatter(
            np.asarray(payload.get("x_values") or [], dtype=float),
            np.asarray(payload.get("y_values") or [], dtype=float),
            marker="o",
            s=28.0,
            color="#0072B2",
            zorder=3,
        )
    else:
        values = [np.asarray(item, dtype=float) for item in payload.get("series") or []]
        positions = [float(item) for item in list(payload.get("positions") or list(range(len(values))))]
        parts = ax.violinplot(values, positions=positions, showmeans=False, showmedians=False, showextrema=False)
        for body in parts.get("bodies", []):
            body.set_facecolor("#8cb8d9")
            body.set_edgecolor("#0072B2")
            body.set_alpha(0.45)
        for item in list(payload.get("violin_annotations") or []):
            if not isinstance(item, Mapping):
                continue
            x = float(item.get("position") or 0.0)
            mean = float(item.get("mean") or 0.0)
            minimum = float(item.get("minimum") or mean)
            maximum = float(item.get("maximum") or mean)
            ax.scatter([x], [mean], marker="o", s=32.0, color="#0072B2", zorder=4)
            ax.scatter([x], [minimum], marker="v", s=24.0, color="#4d5968", zorder=4)
            ax.scatter([x], [maximum], marker="^", s=24.0, color="#4d5968", zorder=4)
            ax.text(x + 0.02, mean, f"u={mean:.3f}", fontsize=8.0, color="#4d5968", va="center", ha="left")

    domain = payload.get("x_domain") if isinstance(payload.get("x_domain"), Mapping) else {}
    if "min" in domain and "max" in domain:
        ax.set_xlim(float(domain["min"]), float(domain["max"]))

    lsl = payload.get("lsl")
    usl = payload.get("usl")
    if lsl is not None:
        ax.axhline(float(lsl), color="#D55E00", linewidth=1.8, alpha=0.82)
    if usl is not None:
        ax.axhline(float(usl), color="#D55E00", linewidth=1.8, alpha=0.82)

    layout = payload.get("layout") if isinstance(payload.get("layout"), Mapping) else {}
    display_positions = [float(item) for item in list(layout.get("display_positions") or [])]
    display_labels = [str(item) for item in list(layout.get("display_labels") or [])]
    if display_positions and display_labels and len(display_positions) == len(display_labels):
        ax.set_xticks(display_positions)
        ax.set_xticklabels(display_labels, rotation=int(layout.get("rotation") or 0))

    legend_payload = payload.get("legend") if isinstance(payload.get("legend"), Mapping) else {}
    legend_items = list(legend_payload.get("items") or [])
    handles: list[Any] = []
    labels: list[str] = []
    for item in legend_items:
        if not isinstance(item, Mapping):
            continue
        labels.append(str(item.get("label") or ""))
        kind = str(item.get("kind") or "line")
        if kind == "marker":
            handles.append(
                Line2D(
                    [0],
                    [0],
                    linestyle="None",
                    marker=_marker_name(item.get("marker")),
                    color=str(item.get("color") or "#0072B2"),
                    markersize=6.0,
                )
            )
        elif kind == "band":
            handles.append(
                Patch(
                    facecolor=str(item.get("fill_color") or "#d0d0d0"),
                    edgecolor=str(item.get("color") or "#1f1f1f"),
                    alpha=float(item.get("alpha") or 0.2),
                )
            )
        else:
            handles.append(
                Line2D(
                    [0],
                    [0],
                    color=str(item.get("color") or "#D55E00"),
                    linewidth=1.6,
                )
            )
    if handles:
        fig.legend(handles, labels, loc="upper right", bbox_to_anchor=(0.985, 0.985), framealpha=0.92)

    ax.set_xlabel(str(payload.get("x_label") or "Group"))
    ax.set_ylabel(str(payload.get("y_label") or "Measurement"))
    ax.set_title(str(payload.get("title") or ""), pad=18.0)
    ax.grid(axis="y", color="#d9dfe7", linewidth=0.8)
    fig.subplots_adjust(left=0.14, right=0.96, bottom=0.22, top=0.82)
    return fig, ax


def _iqr_payload() -> dict[str, Any]:
    return {
        "type": "iqr",
        "labels": ["Alpha", "Beta"],
        "series": [[1.0, 1.1, 1.2, 1.3], [2.0, 2.1, 2.2, 5.0]],
        "title": "IQR Parity",
        "lsl": 0.8,
        "usl": 5.2,
        "nominal": 2.0,
        "one_sided": False,
        "layout": {
            "rotation": 0,
            "display_positions": [1.0, 2.0],
            "display_labels": ["Alpha", "Beta"],
            "bottom_margin": 0.22,
        },
        "canvas": {"width_px": 960, "height_px": 540, "dpi": DEFAULT_DPI},
        "x_label": "Group",
        "y_label": "Measurement",
        "legend": {
            "items": [
                {"label": "IQR", "kind": "band", "fill_color": "#8cb8d9", "color": "#0072B2", "alpha": 0.45},
                {"label": "Median", "kind": "line", "color": "#E69F00"},
            ]
        },
    }


def _build_iqr_figure(payload: dict[str, Any]) -> tuple[plt.Figure, plt.Axes]:
    canvas = payload.get("canvas") if isinstance(payload.get("canvas"), Mapping) else {}
    dpi = int(canvas.get("dpi") or DEFAULT_DPI)
    width = int(canvas.get("width_px") or 960)
    height = int(canvas.get("height_px") or 540)
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)

    labels = [str(item) for item in payload.get("labels") or []]
    series = [np.asarray(item, dtype=float) for item in payload.get("series") or []]
    positions = [float(item) for item in list(payload.get("layout", {}).get("display_positions") or list(range(1, len(series) + 1)))]
    box = ax.boxplot(series, positions=positions, patch_artist=True, tick_labels=labels, widths=0.28)
    for patch in box.get("boxes", []):
        patch.set_facecolor("#8cb8d9")
        patch.set_alpha(0.45)
        patch.set_edgecolor("#0072B2")
        patch.set_linewidth(1.2)
    for median in box.get("medians", []):
        median.set_color("#E69F00")
        median.set_linewidth(1.6)
    for whisker in box.get("whiskers", []):
        whisker.set_color("#0072B2")
    for cap in box.get("caps", []):
        cap.set_color("#0072B2")
    for flier in box.get("fliers", []):
        flier.set_marker("o")
        flier.set_markersize(4.0)
        flier.set_markerfacecolor("#d55e00")
        flier.set_markeredgecolor("#d55e00")

    lsl = payload.get("lsl")
    usl = payload.get("usl")
    nominal = payload.get("nominal")
    if lsl is not None:
        ax.axhline(float(lsl), color="#D55E00", linewidth=1.8, alpha=0.82)
    if usl is not None:
        ax.axhline(float(usl), color="#D55E00", linewidth=1.8, alpha=0.82)
    if nominal is not None:
        ax.axhline(float(nominal), color="#D55E00", linewidth=1.6, alpha=0.82, linestyle="--", dashes=(8, 5))

    legend_handles = [
        Patch(facecolor="#8cb8d9", edgecolor="#0072B2", alpha=0.45, label="IQR"),
        Line2D([0], [0], color="#E69F00", linewidth=1.6, label="Median"),
    ]
    fig.legend(legend_handles, ["IQR", "Median"], loc="upper right", bbox_to_anchor=(0.985, 0.985), framealpha=0.92)

    ax.set_xlabel(str(payload.get("x_label") or "Group"))
    ax.set_ylabel(str(payload.get("y_label") or "Measurement"))
    ax.set_title(str(payload.get("title") or ""), pad=18.0)
    ax.grid(axis="y", color="#d9dfe7", linewidth=0.8)
    fig.subplots_adjust(left=0.14, right=0.96, bottom=0.22, top=0.82)
    return fig, ax


def _trend_payload() -> dict[str, Any]:
    x_values = [0.0, 1.0, 2.0, 3.0]
    y_values = [1.0, 1.2, 1.1, 1.35]
    horizontal_limits = [0.9, 1.4]
    x_min = min(x_values)
    x_max = max(x_values)
    x_padding = (x_max - x_min) * 0.05
    y_min = min(y_values + horizontal_limits)
    y_max = max(y_values + horizontal_limits)
    y_padding = (y_max - y_min) * 0.05
    return {
        "type": "trend",
        "x_values": x_values,
        "y_values": y_values,
        "labels": ["S1", "S2", "S3", "S4"],
        "title": "Trend Parity",
        "x_label": "Sample #",
        "y_label": "Measurement",
        "horizontal_limits": horizontal_limits,
        "layout": {
            "rotation": 0,
            "display_positions": [0.0, 1.0, 2.0, 3.0],
            "display_labels": ["S1", "S2", "S3", "S4"],
            "bottom_margin": 0.22,
        },
        "x_limits": {"min": x_min - x_padding, "max": x_max + x_padding},
        "y_limits": {"min": y_min - y_padding, "max": y_max + y_padding},
        "canvas": {"width_px": 960, "height_px": 540, "dpi": DEFAULT_DPI},
    }


def _build_trend_figure(payload: dict[str, Any]) -> tuple[plt.Figure, plt.Axes]:
    canvas = payload.get("canvas") if isinstance(payload.get("canvas"), Mapping) else {}
    dpi = int(canvas.get("dpi") or DEFAULT_DPI)
    width = int(canvas.get("width_px") or 960)
    height = int(canvas.get("height_px") or 540)
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)

    x_values = np.asarray(payload.get("x_values") or [], dtype=float)
    y_values = np.asarray(payload.get("y_values") or [], dtype=float)
    ax.scatter(x_values, y_values, marker="o", s=28.0, color="#0072B2", zorder=3)

    for limit in list(payload.get("horizontal_limits") or []):
        ax.axhline(float(limit), color="#D55E00", linewidth=1.8, alpha=0.82)

    layout = payload.get("layout") if isinstance(payload.get("layout"), Mapping) else {}
    display_positions = [float(item) for item in list(layout.get("display_positions") or [])]
    display_labels = [str(item) for item in list(layout.get("display_labels") or [])]
    if display_positions and display_labels and len(display_positions) == len(display_labels):
        ax.set_xticks(display_positions)
        ax.set_xticklabels(display_labels, rotation=int(layout.get("rotation") or 0))

    x_limits = payload.get("x_limits") if isinstance(payload.get("x_limits"), Mapping) else {}
    y_limits = payload.get("y_limits") if isinstance(payload.get("y_limits"), Mapping) else {}
    if "min" in x_limits and "max" in x_limits:
        ax.set_xlim(float(x_limits["min"]), float(x_limits["max"]))
    if "min" in y_limits and "max" in y_limits:
        ax.set_ylim(float(y_limits["min"]), float(y_limits["max"]))

    ax.set_xlabel(str(payload.get("x_label") or "Sample #"))
    ax.set_ylabel(str(payload.get("y_label") or "Measurement"))
    ax.set_title(str(payload.get("title") or ""), pad=18.0)
    ax.grid(axis="y", color="#d9dfe7", linewidth=0.8)
    fig.subplots_adjust(left=0.14, right=0.96, bottom=0.22, top=0.82)
    return fig, ax


def _generate_histogram_fixture(base_dir: Path) -> None:
    fixture_dir = base_dir / "histogram"
    fixture_dir.mkdir(parents=True, exist_ok=True)

    payload = build_histogram_native_payload(
        values=[1.0, 1.05, 1.1, 1.2, 1.25, 1.35, 1.4, 1.55, 1.7, 1.8],
        lsl=0.9,
        usl=1.85,
        title="Histogram Parity",
        bin_count=7,
    )
    payload.update(
        {
            "canvas": {"width_px": 960, "height_px": 540, "dpi": DEFAULT_DPI},
            "summary_table_rows": [
                {"label": "Samples", "value": "10"},
                {"label": "Mean", "value": "1.34"},
                {"label": "Sigma", "value": "0.27"},
                {"label": "Cp", "value": "1.16"},
                {"label": "Cpk", "value": "1.02"},
            ],
            "annotation_rows": [
                {"label": "LSL", "text": "LSL=0.900", "kind": "lsl", "x": 0.9, "row_index": 1},
                {"label": "Mean", "text": "Mean=1.340", "kind": "mean", "x": 1.34, "row_index": 0},
                {"label": "USL", "text": "USL=1.850", "kind": "usl", "x": 1.85, "row_index": 1},
            ],
        }
    )
    planner_spec = histogram_spec_to_mapping(build_resolved_histogram_spec(payload))
    _write_json(fixture_dir / "payload.json", payload)
    _write_json(fixture_dir / "planner_spec.json", planner_spec)
    _render_histogram_from_spec(planner_spec, fixture_dir / "matplotlib_reference.png")


def _generate_distribution_fixture(base_dir: Path, *, mode: str) -> None:
    fixture_name = f"distribution_{mode}"
    fixture_dir = base_dir / fixture_name
    fixture_dir.mkdir(parents=True, exist_ok=True)

    payload = _distribution_scatter_payload() if mode == "scatter" else _distribution_violin_payload()
    planner_spec = build_resolved_distribution_spec(payload)
    fig, ax = _build_distribution_figure(payload)
    try:
        oracle = extract_distribution_geometry(fig, ax, render_mode=mode, payload=payload)
        _save_fig_png(fig, fixture_dir / "matplotlib_reference.png")
    finally:
        plt.close(fig)

    _write_json(fixture_dir / "payload.json", payload)
    _write_json(fixture_dir / "planner_spec.json", planner_spec)
    _write_json(fixture_dir / "matplotlib_oracle_geometry.json", oracle)


def _generate_iqr_fixture(base_dir: Path) -> None:
    fixture_dir = base_dir / "iqr"
    fixture_dir.mkdir(parents=True, exist_ok=True)

    payload = _iqr_payload()
    planner_spec = build_resolved_iqr_spec(payload)
    fig, ax = _build_iqr_figure(payload)
    try:
        oracle = extract_iqr_geometry(fig, ax, payload=payload)
        _save_fig_png(fig, fixture_dir / "matplotlib_reference.png")
    finally:
        plt.close(fig)

    _write_json(fixture_dir / "payload.json", payload)
    _write_json(fixture_dir / "planner_spec.json", planner_spec)
    _write_json(fixture_dir / "matplotlib_oracle_geometry.json", oracle)


def _generate_trend_fixture(base_dir: Path) -> None:
    fixture_dir = base_dir / "trend"
    fixture_dir.mkdir(parents=True, exist_ok=True)

    payload = _trend_payload()
    planner_spec = build_resolved_trend_spec(payload)
    fig, ax = _build_trend_figure(payload)
    try:
        oracle = extract_trend_geometry(fig, ax, payload=payload)
        _save_fig_png(fig, fixture_dir / "matplotlib_reference.png")
    finally:
        plt.close(fig)

    _write_json(fixture_dir / "payload.json", payload)
    _write_json(fixture_dir / "planner_spec.json", planner_spec)
    _write_json(fixture_dir / "matplotlib_oracle_geometry.json", oracle)


def _write_manifest(base_dir: Path, fixtures: list[str]) -> None:
    manifest = {
        "fixture_set": "chart_parity",
        "version": FIXTURE_SET_VERSION,
        "generator": "scripts/generate_chart_parity_fixtures.py",
        "fixtures": fixtures,
    }
    _write_json(base_dir / "manifest.json", manifest)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate chart parity fixtures.")
    parser.add_argument(
        "--output-dir",
        default="tests/fixtures/chart_parity",
        help="Fixture output directory.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete output directory before generation.",
    )
    return parser.parse_args()


def _clean_output_dir(output_dir: Path) -> None:
    """Remove generated fixture artifacts while preserving static root docs."""
    if not output_dir.exists():
        return
    for path in output_dir.iterdir():
        if path.name == "README.md":
            continue
        if path.is_dir():
            shutil.rmtree(path)
            continue
        path.unlink()


def main() -> int:
    args = _parse_args()
    _configure_matplotlib()
    np.random.seed(0)

    output_dir = Path(args.output_dir).resolve()
    if args.clean and output_dir.exists():
        _clean_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _generate_histogram_fixture(output_dir)
    _generate_distribution_fixture(output_dir, mode="scatter")
    _generate_distribution_fixture(output_dir, mode="violin")
    _generate_iqr_fixture(output_dir)
    _generate_trend_fixture(output_dir)

    fixtures = [
        "histogram",
        "distribution_scatter",
        "distribution_violin",
        "iqr",
        "trend",
    ]
    _write_manifest(output_dir, fixtures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
