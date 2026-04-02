from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pytest

from modules.chart_render_spec import (
    build_resolved_distribution_spec,
    build_resolved_iqr_spec,
    build_resolved_trend_spec,
    histogram_spec_to_mapping,
    build_resolved_histogram_spec,
)
from modules.native_chart_compositor import (
    render_distribution_png,
    render_histogram_png,
    render_iqr_png,
    render_trend_png,
)


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "chart_parity"
PARITY_THRESHOLDS = {
    "histogram": 0.05,
    "distribution_scatter": 0.03,
    "distribution_violin": 0.04,
    "iqr": 0.03,
    "trend": 0.02,
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _decode_png_bytes(png_bytes: bytes) -> np.ndarray:
    return plt.imread(BytesIO(png_bytes), format="png")[..., :3]


def _mean_absolute_image_difference(left: np.ndarray, right: np.ndarray) -> float:
    if left.shape != right.shape:
        raise ValueError(f"shape mismatch: {left.shape} != {right.shape}")
    return float(np.mean(np.abs(left.astype(np.float32) - right.astype(np.float32))))


def _fixture_payload(fixture_name: str) -> dict:
    payload = _read_json(FIXTURE_ROOT / fixture_name / "payload.json")
    if fixture_name == "histogram":
        payload["resolved_render_spec"] = histogram_spec_to_mapping(build_resolved_histogram_spec(payload))
    elif fixture_name.startswith("distribution_"):
        payload["resolved_render_spec"] = build_resolved_distribution_spec(payload)
    elif fixture_name == "iqr":
        payload["resolved_render_spec"] = build_resolved_iqr_spec(payload)
    elif fixture_name == "trend":
        payload["resolved_render_spec"] = _read_json(FIXTURE_ROOT / fixture_name / "matplotlib_oracle_geometry.json")
    else:
        raise ValueError(f"Unsupported fixture: {fixture_name}")
    return payload


def _planner_spec_for_fixture(fixture_name: str) -> dict:
    return _read_json(FIXTURE_ROOT / fixture_name / "planner_spec.json")


def _build_planner_spec_from_payload(*, fixture_name: str, payload: dict) -> dict:
    if fixture_name == "histogram":
        return histogram_spec_to_mapping(build_resolved_histogram_spec(payload))
    if fixture_name.startswith("distribution_"):
        return build_resolved_distribution_spec(payload)
    if fixture_name == "iqr":
        return build_resolved_iqr_spec(payload)
    if fixture_name == "trend":
        return build_resolved_trend_spec(payload)
    raise ValueError(f"Unsupported fixture: {fixture_name}")


def _fixture_reference_image(fixture_name: str) -> np.ndarray:
    return plt.imread(str(FIXTURE_ROOT / fixture_name / "matplotlib_reference.png"))[..., :3]


def _render_fixture_native(fixture_name: str) -> np.ndarray:
    payload = _fixture_payload(fixture_name)
    if fixture_name == "histogram":
        png_bytes = render_histogram_png(payload)
    elif fixture_name.startswith("distribution_"):
        png_bytes = render_distribution_png(payload)
    elif fixture_name == "iqr":
        png_bytes = render_iqr_png(payload)
    elif fixture_name == "trend":
        png_bytes = render_trend_png(payload)
    else:
        raise ValueError(f"Unsupported fixture: {fixture_name}")
    return _decode_png_bytes(png_bytes)


def test_chart_parity_manifest_matches_fixture_directories():
    manifest = _read_json(FIXTURE_ROOT / "manifest.json")
    manifest_fixtures = sorted(manifest.get("fixtures") or [])
    actual_fixtures = sorted(
        path.name
        for path in FIXTURE_ROOT.iterdir()
        if path.is_dir()
    )
    assert manifest.get("fixture_set") == "chart_parity"
    assert manifest_fixtures == actual_fixtures


@pytest.mark.parametrize(
    ("fixture_name", "max_mean_abs_diff"),
    [(name, threshold) for name, threshold in PARITY_THRESHOLDS.items()],
)
def test_native_chart_matches_checked_in_matplotlib_reference(fixture_name: str, max_mean_abs_diff: float):
    native_image = _render_fixture_native(fixture_name)
    reference_image = _fixture_reference_image(fixture_name)

    assert native_image.shape == reference_image.shape
    assert _mean_absolute_image_difference(native_image, reference_image) <= max_mean_abs_diff


@pytest.mark.parametrize(
    "fixture_name",
    ["distribution_scatter", "distribution_violin", "iqr", "trend"],
)
def test_oracle_geometry_fixtures_remain_matplotlib_finalized(fixture_name: str):
    oracle_geometry = _read_json(FIXTURE_ROOT / fixture_name / "matplotlib_oracle_geometry.json")

    assert oracle_geometry.get("source") == "matplotlib_finalized"
    assert isinstance(oracle_geometry.get("plot_area"), dict)
    assert isinstance(oracle_geometry.get("axes"), dict)


@pytest.mark.parametrize("fixture_name", sorted(PARITY_THRESHOLDS))
def test_planner_spec_fixtures_match_live_planner_builders(fixture_name: str):
    payload = _read_json(FIXTURE_ROOT / fixture_name / "payload.json")
    checked_in_planner_spec = _planner_spec_for_fixture(fixture_name)

    assert _build_planner_spec_from_payload(fixture_name=fixture_name, payload=payload) == checked_in_planner_spec
