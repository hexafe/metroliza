from modules.hexafe_groupstats_adapter import analyze_group_metric


def test_groupstats_adapter_exposes_rc3_summary_and_row_adapters() -> None:
    payload = analyze_group_metric(
        "Length",
        {
            "Line A": [99.8, 99.9, 100.0, 100.1, 100.2, 100.3],
            "Line B": [100.8, 100.9, 101.0, 101.1, 101.2, 101.3],
            "Line C": [99.0, 99.1, 99.2, 99.3, 99.4, 99.5],
        },
        spec_records=[{"lsl": 98.5, "nominal": 100.0, "usl": 101.5}],
        backend="python",
        capability_benchmark=1.25,
    )

    assert payload["metric_summary"]["metric"] == "Length"
    assert payload["correction_method"] == "Holm"
    assert payload["correction_policy"]
    assert payload["backend_requested"] == "python"
    assert payload["backend_used"] == "python"
    assert payload["capability_benchmark"] == 1.25
    assert payload["posthoc_rows"]
    assert payload["capability_rows"]

    pairwise = payload["pairwise_rows"][0]
    assert {
        "effect_type",
        "method_family",
        "comparison_estimate",
        "comparison_estimate_label",
        "comparison_ci",
        "effect_size_ci",
        "warnings",
    }.issubset(pairwise)


def test_groupstats_adapter_passes_optional_simulation_validation() -> None:
    payload = analyze_group_metric(
        "Length",
        {
            "Line A": [99.8, 99.9, 100.0, 100.1, 100.2, 100.3],
            "Line B": [100.8, 100.9, 101.0, 101.1, 101.2, 101.3],
            "Line C": [99.0, 99.1, 99.2, 99.3, 99.4, 99.5],
        },
        spec_records=[],
        backend="python",
        simulation_validation_iterations=2,
        simulation_random_seed=7,
    )

    validation = payload["simulation_validation"]
    assert validation["iterations"] == 2
    assert validation["seed"] == 7
    assert "pairwise_stability" in validation
