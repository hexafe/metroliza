from __future__ import annotations

import numpy as np
import pytest

from metroliza.charts.plotly_stat_helpers import (
    format_group_statistics_trace_name,
    normalize_group_label_key,
    payload_distribution_series,
    strip_group_count_suffix,
)
from metroliza.native_bridges.native_array_utils import as_float64_1d_contiguous
from metroliza.shared.dashboard_interactivity import (
    DashboardInteractivityOptions,
    normalize_dashboard_interactivity_mapping,
    normalize_dashboard_interactivity_options,
    summarize_dashboard_interactivity_options,
)
from metroliza.shared.numeric_coercion import coerce_finite_float
from metroliza.shared.progress_status import diagnostic_progress_message


def test_plotly_stat_helpers_normalize_group_labels_and_stats() -> None:
    assert strip_group_count_suffix("Line A (n = 42)") == "Line A"
    assert normalize_group_label_key("Line A (n = 42)") == "line a"
    assert format_group_statistics_trace_name("Line A", [1.0, 2.0]) == "Line A (n=2)"
    assert format_group_statistics_trace_name("Line A (n = 42)", [1.0, 2.0]) == "Line A (n = 42)"


def test_plotly_stat_helpers_extract_payload_distribution_series() -> None:
    payload = {"series": [{"label": "A", "values": [1, 2]}]}

    assert [series["label"] for series in payload_distribution_series(payload)] == ["A"]
    assert payload_distribution_series({"values": [{"label": "B", "values": [3]}]})[0]["label"] == "B"


def test_dashboard_interactivity_shared_contracts() -> None:
    options = normalize_dashboard_interactivity_options(
        {
            "mode": "sampled",
            "sample_size": "50000",
            "populationLayerMode": "static",
            "sizeLimitMode": "custom",
            "sizeLimitMb": "96",
        },
        strict=True,
    )

    assert options == DashboardInteractivityOptions(
        mode="sampled",
        sample_size=50_000,
        population_layer_mode="static",
        size_limit_mode="custom",
        size_limit_mb=96,
    )
    assert normalize_dashboard_interactivity_mapping(
        {"mode": "bad", "sample_size": "bad"},
        strict=False,
        default_mode="full",
        default_sample_size=12_345,
    ) == {
        "mode": "full",
        "sample_size": 12_345,
        "population_layer_mode": "auto",
        "large_group_layer_mode": "auto",
        "large_group_static_threshold": 5_000,
        "large_group_total_static_threshold": 50_000,
        "size_limit_mode": "default",
        "size_limit_mb": 24,
    }
    assert "Interactive random sample" in summarize_dashboard_interactivity_options(options)
    assert "96 mb dashboard size limit" in summarize_dashboard_interactivity_options(options).lower()


def test_dashboard_interactivity_strict_sample_bounds() -> None:
    with pytest.raises(ValueError, match="between 5000 and 200000"):
        normalize_dashboard_interactivity_options({"sample_size": 1}, strict=True)


def test_progress_diagnostic_message_fallback() -> None:
    status = type("Status", (), {"value": "running"})()
    diagnostic = type("Diagnostic", (), {"message": "", "source_alias": "Line 1", "status": status})()

    assert diagnostic_progress_message(diagnostic) == "Line 1: running"


def test_numeric_and_native_array_helpers() -> None:
    assert coerce_finite_float("1.25") == 1.25
    assert coerce_finite_float(float("nan")) is None

    contiguous = as_float64_1d_contiguous([1, 2, 3])
    assert contiguous.dtype == np.float64
    assert contiguous.flags["C_CONTIGUOUS"]
    with pytest.raises(ValueError, match="Expected 1D numeric input"):
        as_float64_1d_contiguous([[1], [2]])


def test_dashboard_visual_dialog_rejects_dummy_cancel_color() -> None:
    pytest.importorskip("PyQt6.QtWidgets")
    from metroliza.ui.dashboard_visual_options_dialog import DashboardVisualOptionsDialog

    class DummyColor:
        def __init__(self, value: str = "#000000") -> None:
            self._value = value

        def isValid(self) -> bool:
            return True

        def name(self) -> str:
            return self._value

    assert DashboardVisualOptionsDialog._color_dialog_result_is_valid(DummyColor("#abcdef"))
    assert not DashboardVisualOptionsDialog._color_dialog_result_is_valid(DummyColor())
