from __future__ import annotations

from hashlib import sha256
import json

import pytest

from metroliza.industrial.dashboard_manifest import (
    DASHBOARD_SCHEMA,
    REQUIRED_MANIFEST_KEYS,
    REQUIRED_SUMMARY_KEYS,
    REQUIRED_WRITE_RESULT_KEYS,
    ProductionDashboardManifest,
    build_dashboard_write_result,
    copy_dashboard_manifest_for_render,
    copy_dashboard_write_result,
    validate_dashboard_manifest,
    validate_dashboard_write_result,
)
from metroliza.industrial.industrial_analytics_dashboard import write_production_dashboard


_PRE_EXTRACTION_EMPTY_DASHBOARD_SHA256 = (
    "167acf15dbe7029e6b25d3dfd81cb2c8eb485a16c86436fd6972b42a9292b870"
)


def _manifest() -> ProductionDashboardManifest:
    return {
        "schema": DASHBOARD_SCHEMA,
        "summary": {
            "source_rows": 2,
            "metric_count": 1,
            "chart_count": 1,
        },
        "metrics": [
            {
                "field_name": "length_mm",
                "display_label": "Length Mm",
                "source_kind": "measurement",
            }
        ],
        "charts": [{"id": "length-mm", "title": "Length Mm"}],
        "groupstats": {},
        "diagnostics": [],
    }


def _empty_manifest() -> ProductionDashboardManifest:
    manifest = _manifest()
    manifest["summary"] = {
        "source_rows": 0,
        "metric_count": 0,
        "chart_count": 0,
    }
    manifest["metrics"] = []
    manifest["charts"] = []
    return manifest


def test_manifest_contract_requires_public_schema_and_keys_without_normalizing() -> None:
    manifest = _manifest()
    serialized_before = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))

    validated = validate_dashboard_manifest(manifest)

    assert validated is manifest
    assert set(validated) == REQUIRED_MANIFEST_KEYS
    assert REQUIRED_SUMMARY_KEYS.issubset(validated["summary"])
    assert json.dumps(validated, ensure_ascii=False, separators=(",", ":")) == serialized_before
    validated["summary"]["dashboard_title"] = "Mutable public result"
    assert manifest["summary"]["dashboard_title"] == "Mutable public result"


def test_render_copy_preserves_legacy_selective_copy_and_private_source_identity() -> None:
    private_key = "_private_source"
    private_source = object()
    manifest = _manifest()
    manifest["charts"][0].update(
        {
            "plotly_spec": {"data": [{"x": (1, 2), "y": (3, 4)}]},
            "optimization_options": [
                {
                    "id": "static_population_layer",
                    "thresholds": (5, 10),
                    private_key: private_source,
                }
            ],
        }
    )

    copied = copy_dashboard_manifest_for_render(
        manifest,
        private_optimization_keys=(private_key,),
    )

    assert copied is not manifest
    assert copied["summary"] is not manifest["summary"]
    assert copied["charts"] is not manifest["charts"]
    assert copied["charts"][0] is not manifest["charts"][0]
    assert copied["charts"][0]["plotly_spec"] == {
        "data": [{"x": [1, 2], "y": [3, 4]}]
    }
    copied_option = copied["charts"][0]["optimization_options"][0]
    assert copied_option["thresholds"] == [5, 10]
    assert copied_option[private_key] is private_source
    assert copied["metrics"] is manifest["metrics"]
    assert copied["groupstats"] is manifest["groupstats"]
    assert copied["diagnostics"] is manifest["diagnostics"]


@pytest.mark.parametrize(
    "invalid_manifest, expected_message",
    [
        ({**_manifest(), "schema": "metroliza.unsupported.v2"}, "Unsupported dashboard"),
        (
            {key: value for key, value in _manifest().items() if key != "metrics"},
            "missing required keys: metrics",
        ),
        ({**_manifest(), "charts": "not-a-list"}, "'charts' must be a list"),
    ],
)
def test_invalid_manifest_fails_before_any_filesystem_write(
    tmp_path,
    invalid_manifest: object,
    expected_message: str,
) -> None:
    output_root = tmp_path / "not-created"

    with pytest.raises(ValueError, match=expected_message):
        write_production_dashboard(
            invalid_manifest,
            output_root / "dashboard.html",
            assets_dir=output_root / "assets",
        )

    assert not output_root.exists()


def test_empty_dashboard_html_is_byte_identical_to_pre_extraction_output(tmp_path) -> None:
    output_path = tmp_path / "dashboard.html"

    result = write_production_dashboard(_empty_manifest(), output_path)
    output_bytes = output_path.read_bytes()

    assert result["html_dashboard_html_bytes"] == len(output_bytes)
    assert sha256(output_bytes).hexdigest() == _PRE_EXTRACTION_EMPTY_DASHBOARD_SHA256


def test_write_result_contract_preserves_exact_dictionary_shape_and_copy_semantics() -> None:
    static_population_layer = {"status": "not_applicable", "render_strategy_counts": {}}
    result = build_dashboard_write_result(
        html_dashboard_path="dashboard.html",
        html_dashboard_assets_path="dashboard_assets",
        chart_count=3,
        interactive_chart_count=2,
        plotly_spec_count=3,
        embedded_plotly_spec_count=2,
        plotly_serialized_json_bytes=120,
        embedded_plotly_serialized_json_bytes=80,
        html_bytes=500,
        plotly_budget_status="over_budget",
        plotly_budget_reason="spec_count>2",
        plotly_spec_count_budget=2,
        plotly_serialized_json_bytes_budget=None,
        plotly_runtime_status="local",
        static_population_layer=static_population_layer,
        timings_s={"manifest_clone": 0, "total": 1.25},
    )
    expected = {
        "html_dashboard_path": "dashboard.html",
        "html_dashboard_assets_path": "dashboard_assets",
        "html_dashboard_chart_count": 3,
        "html_dashboard_interactive_chart_count": 2,
        "html_dashboard_plotly_spec_count": 3,
        "html_dashboard_embedded_plotly_spec_count": 2,
        "html_dashboard_plotly_serialized_json_bytes": 120,
        "html_dashboard_embedded_plotly_serialized_json_bytes": 80,
        "html_dashboard_html_bytes": 500,
        "html_dashboard_plotly_budget": {
            "status": "over_budget",
            "reason": "spec_count>2",
            "spec_count_budget": 2,
            "serialized_json_bytes_budget": None,
        },
        "html_dashboard_plotly_runtime_status": "local",
        "html_dashboard_static_population_layer": static_population_layer,
        "html_dashboard_timings_s": {"manifest_clone": 0.0, "total": 1.25},
    }

    assert validate_dashboard_write_result(result) is result
    assert set(result) == REQUIRED_WRITE_RESULT_KEYS
    assert json.dumps(result, separators=(",", ":")) == json.dumps(
        expected,
        separators=(",", ":"),
    )
    copied = copy_dashboard_write_result(result)
    assert copied == result
    assert copied is not result
    assert copied["html_dashboard_plotly_budget"] is not result["html_dashboard_plotly_budget"]
    assert (
        copied["html_dashboard_static_population_layer"]
        is not result["html_dashboard_static_population_layer"]
    )
