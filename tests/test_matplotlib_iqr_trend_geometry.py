from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import pytest

from modules.matplotlib_iqr_trend_geometry import extract_iqr_geometry, extract_trend_geometry


def test_extract_iqr_geometry_captures_finalized_layout_and_box_stats():
    fig, ax = plt.subplots(figsize=(7.0, 4.0), dpi=120)
    try:
        ax.boxplot(
            [[1.0, 2.0, 3.0, 4.0, 5.0], [2.0, 2.0, 2.0, 3.0, 4.0, 8.0]],
            whis=1.5,
            patch_artist=True,
            boxprops={"facecolor": "#56B4E9", "edgecolor": "#1f2937", "linewidth": 1.0, "alpha": 0.45},
            medianprops={"color": "#E69F00", "linewidth": 1.1},
            whiskerprops={"color": "#1f2937", "linewidth": 0.9},
            capprops={"color": "#1f2937", "linewidth": 0.9},
            flierprops={"marker": "o", "markersize": 3.0, "markerfacecolor": "#D55E00", "markeredgecolor": "#D55E00", "alpha": 0.9},
        )
        ax.axhspan(1.5, 5.5, alpha=0.08, color="#56B4E9", zorder=0)
        ax.axhline(1.0, color="#D55E00", linewidth=1.5, alpha=0.8)
        ax.axhline(6.0, color="#D55E00", linewidth=1.5, alpha=0.8)
        ax.set_xticks([1.0, 2.0])
        ax.set_xticklabels(["G1", "G2"], rotation=30, ha="right")
        ax.set_xlabel("Group")
        ax.set_ylabel("Measurement")
        ax.set_title("IQR Geometry")
        fig.legend(
            handles=[
                Patch(facecolor="#56B4E9", edgecolor="#1f2937", label="IQR range (Q1-Q3)"),
                Line2D([0], [0], color="#E69F00", linewidth=1.1, label="Median"),
                Line2D([0], [0], marker="o", linestyle="None", color="#D55E00", label="Outliers"),
            ],
            loc="upper right",
            bbox_to_anchor=(0.98, 0.98),
            frameon=True,
        )
        fig.subplots_adjust(left=0.16, right=0.82, bottom=0.24, top=0.80)

        resolved = extract_iqr_geometry(
            fig,
            ax,
            payload={
                "labels": ["G1", "G2"],
                "title": "IQR Payload Title",
                "x_label": "Group",
                "y_label": "Measurement",
            },
        )
    finally:
        plt.close(fig)

    assert resolved["chart_type"] == "iqr"
    assert resolved["title"]["text"] == "IQR Geometry"
    assert resolved["plot_area"]["x"] > 0.10
    assert resolved["plot_area"]["y"] > 0.15
    assert resolved["plot_area"]["width"] < 0.80
    assert resolved["axes"]["rotation"] == 30
    assert resolved["axes"]["x_label"] == "Group"
    assert resolved["legend"] is not None
    assert {item["label"] for item in resolved["legend"]["items"]} >= {"Median", "Outliers"}

    line_values = sorted(round(float(item["value"]), 3) for item in resolved["reference_lines"] if item["axis"] == "y")
    assert 1.0 in line_values
    assert 6.0 in line_values

    assert len(resolved["reference_bands"]) >= 1
    assert resolved["reference_bands"][0]["start"] == pytest.approx(1.5, rel=0.0, abs=0.05)
    assert resolved["reference_bands"][0]["end"] == pytest.approx(5.5, rel=0.0, abs=0.05)

    assert len(resolved["boxplots"]) == 2
    assert resolved["boxplots"][0]["label"] == "G1"
    assert resolved["boxplots"][1]["label"] == "G2"
    assert resolved["boxplots"][0]["median"] == pytest.approx(3.0, rel=0.0, abs=0.2)
    assert resolved["boxplots"][1]["outliers"] == pytest.approx([8.0], rel=0.0, abs=0.2)


def test_extract_trend_geometry_captures_points_ticks_and_reference_lines():
    fig, ax = plt.subplots(figsize=(6.0, 4.0), dpi=120)
    try:
        ax.scatter([0.0, 1.0, 2.0, 3.0], [1.2, 1.4, 1.3, 1.5], marker=".", s=24, color="#0072B2")
        ax.axhline(1.1, color="#D55E00", linestyle="--", linewidth=1.0, alpha=0.8)
        ax.axhline(1.6, color="#D55E00", linestyle="--", linewidth=1.0, alpha=0.8)
        ax.set_xticks([0.0, 1.0, 2.0, 3.0])
        ax.set_xticklabels(["A", "B", "C", "D"], rotation=45, ha="right")
        ax.set_xlabel("Sample #")
        ax.set_ylabel("Measurement")
        ax.set_title("Trend Geometry")
        ax.grid(axis="y", alpha=0.35)
        fig.subplots_adjust(left=0.14, right=0.96, bottom=0.30, top=0.82)

        resolved = extract_trend_geometry(
            fig,
            ax,
            payload={
                "x_values": [0.0, 1.0, 2.0, 3.0],
                "y_values": [1.2, 1.4, 1.3, 1.5],
                "title": "Trend Payload Title",
                "x_label": "Sample #",
                "y_label": "Measurement",
            },
        )
    finally:
        plt.close(fig)

    assert resolved["chart_type"] == "trend"
    assert resolved["title"]["text"] == "Trend Geometry"
    assert resolved["plot_area"]["x"] > 0.10
    assert resolved["plot_area"]["y"] > 0.20
    assert resolved["axes"]["rotation"] == 45
    assert resolved["axes"]["grid_axis"] in {"y", "both"}
    assert len(resolved["points"]) == 4
    assert resolved["points"][0]["x"] == pytest.approx(0.0)
    assert resolved["points"][0]["y"] == pytest.approx(1.2)
    assert resolved["points"][0]["size"] > 0.0

    line_values = sorted(round(float(item["value"]), 3) for item in resolved["reference_lines"] if item["axis"] == "y")
    assert 1.1 in line_values
    assert 1.6 in line_values


def test_extract_trend_geometry_applies_payload_fallbacks_when_axis_text_is_missing():
    fig, ax = plt.subplots(figsize=(5.0, 3.0), dpi=100)
    try:
        ax.scatter([0.0, 1.0], [2.0, 2.2], marker=".", s=20, color="#0072B2")
        resolved = extract_trend_geometry(
            fig,
            ax,
            payload={
                "title": "Payload Fallback Title",
                "x_label": "Payload X",
                "y_label": "Payload Y",
            },
        )
    finally:
        plt.close(fig)

    assert resolved["title"]["text"] == "Payload Fallback Title"
    assert resolved["axes"]["x_label"] == "Payload X"
    assert resolved["axes"]["y_label"] == "Payload Y"
