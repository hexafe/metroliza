# ruff: noqa: E402
from __future__ import annotations

import sys
import types

import matplotlib.pyplot as plt
import pytest

qtcore_stub = sys.modules.get("PyQt6.QtCore") or types.ModuleType("PyQt6.QtCore")


class _DummyThread:
    def __init__(self, *args, **kwargs):
        pass


class _DummyCoreApp:
    @staticmethod
    def processEvents():
        return None


def _dummy_signal(*args, **kwargs):
    class _Signal:
        def emit(self, *a, **k):
            return None

    return _Signal()


qtcore_stub.QCoreApplication = getattr(qtcore_stub, "QCoreApplication", _DummyCoreApp)
qtcore_stub.QThread = getattr(qtcore_stub, "QThread", _DummyThread)
qtcore_stub.pyqtSignal = getattr(qtcore_stub, "pyqtSignal", _dummy_signal)
sys.modules["PyQt6.QtCore"] = qtcore_stub

custom_logger_stub = types.ModuleType("modules.custom_logger")


class _DummyLogger:
    def __init__(self, *args, **kwargs):
        pass


custom_logger_stub.CustomLogger = _DummyLogger
sys.modules["modules.custom_logger"] = custom_logger_stub

from modules.export_data_thread import (
    apply_minimal_axis_style,
    finalize_extended_chart_layout,
    move_legend_to_figure,
    render_scatter_numeric,
    render_spec_reference_lines,
    render_tolerance_band,
    render_violin,
)
from modules.matplotlib_distribution_geometry import extract_distribution_geometry


def test_extract_distribution_geometry_returns_violin_layout_legend_and_primitives():
    fig, ax = plt.subplots(figsize=(6.5, 4.0))
    render_violin(
        ax,
        [[1.0, 1.1, 1.2, 1.3], [1.4, 1.5, 1.6, 1.7]],
        ["A", "B"],
        nom=1.4,
        lsl=0.9,
        usl=1.8,
        one_sided=False,
        show_annotation_legend=True,
    )
    ax.set_xlabel("Group")
    ax.set_ylabel("Measurement")
    ax.set_title("Distribution Title", pad=20)
    apply_minimal_axis_style(ax, grid_axis="y")
    figure_legend = move_legend_to_figure(ax)
    finalize_extended_chart_layout(fig, ax, legend=figure_legend, strategy={"bottom_margin": 0.23})

    geometry = extract_distribution_geometry(fig, ax, render_mode="violin", payload={"title": "Distribution Title"})

    plt.close(fig)

    assert geometry["chart_type"] == "distribution"
    assert geometry["source"] == "matplotlib_finalized"
    assert geometry["render_mode"] == "violin"
    assert geometry["canvas"]["width_px"] > 0
    assert geometry["plot_area"]["x"] == pytest.approx(ax.get_position().x0)
    assert geometry["plot_area"]["y"] == pytest.approx(ax.get_position().y0)
    assert geometry["title"]["text"] == "Distribution Title"
    assert geometry["axes"]["x_label"] == "Group"
    assert geometry["axes"]["y_label"] == "Measurement"
    assert [tick["label"] for tick in geometry["axes"]["x_ticks"]] == ["A", "B"]
    assert geometry["legend"] is not None
    assert [item["label"] for item in geometry["legend"]["items"]] == [
        "Mean marker (\u03bc)",
        "Min marker",
        "Max marker",
        "\u00b13\u03c3 span (visual)",
    ]
    assert len(geometry["reference_bands"]) == 1
    assert len(geometry["reference_lines"]) == 2
    assert len(geometry["violin_bodies"]) == 2
    assert len(geometry["annotations"]["markers"]) >= 6
    assert len(geometry["annotations"]["texts"]) >= 6


def test_extract_distribution_geometry_returns_scatter_points_without_violin_bodies():
    fig, ax = plt.subplots(figsize=(6.5, 4.0))
    render_scatter_numeric(ax, [0.0, 1.0, 2.0], [1.2, 1.5, 1.7])
    render_tolerance_band(ax, 1.5, 1.0, 2.0, one_sided=False)
    render_spec_reference_lines(ax, 1.5, 1.0, 2.0, include_nominal=False)
    ax.set_xlabel("Sample #")
    ax.set_ylabel("Measurement")
    ax.set_title("Scatter Distribution", pad=20)
    ax.set_xticks([0.0, 1.0, 2.0])
    ax.set_xticklabels(["S1", "S2", "S3"])
    apply_minimal_axis_style(ax, grid_axis="y")
    finalize_extended_chart_layout(fig, ax, strategy={"bottom_margin": 0.18})

    geometry = extract_distribution_geometry(fig, ax, render_mode="scatter", payload={"title": "Scatter Distribution"})

    plt.close(fig)

    assert geometry["source"] == "matplotlib_finalized"
    assert geometry["render_mode"] == "scatter"
    assert geometry["legend"] is None
    assert len(geometry["reference_bands"]) == 1
    assert len(geometry["reference_lines"]) == 2
    assert len(geometry["scatter_points"]) == 3
    assert geometry["violin_bodies"] == []
    assert geometry["annotations"] == {"markers": [], "segments": [], "texts": []}
    assert [tick["label"] for tick in geometry["axes"]["x_ticks"]] == ["S1", "S2", "S3"]
