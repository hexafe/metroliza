import math

from modules.comparison_stats import ComparisonStatsConfig, _adjust_pvalues, compute_metric_pairwise_stats


def _is_monotone_non_decreasing(values):
    return all(left <= right for left, right in zip(values, values[1:]))


def test_holm_correction_monotonicity_in_sorted_order():
    raw = [0.03, 0.001, 0.02, 0.04]
    adjusted = _adjust_pvalues(raw, 'holm')

    by_raw = sorted(zip(raw, adjusted), key=lambda item: item[0])
    sorted_adjusted = [item[1] for item in by_raw]
    assert _is_monotone_non_decreasing(sorted_adjusted)


def test_bh_correction_monotonicity_in_sorted_order():
    raw = [0.03, 0.001, 0.02, 0.04]
    adjusted = _adjust_pvalues(raw, 'bh')

    by_raw = sorted(zip(raw, adjusted), key=lambda item: item[0])
    sorted_adjusted = [item[1] for item in by_raw]
    assert _is_monotone_non_decreasing(sorted_adjusted)


def test_effect_size_for_two_group_parametric_fixture_matches_cohen_d():
    grouped_values = {
        'A': [1.0, 2.0, 3.0],
        'B': [4.0, 5.0, 6.0],
    }

    rows = compute_metric_pairwise_stats('metric_x', grouped_values)

    assert len(rows) == 1
    row = rows[0]
    assert row['test_used'] in {'Student t-test', 'Welch t-test'}
    assert math.isclose(row['effect_size'], -3.0, rel_tol=1e-9)


def test_effect_size_for_two_group_non_parametric_fixture_matches_cliffs_delta():
    grouped_values = {
        'A': [0.0, 0.0, 0.0, 10.0, 10.0],
        'B': [1.0, 1.0, 1.0, 11.0, 11.0],
    }

    rows = compute_metric_pairwise_stats('metric_y', grouped_values)

    assert len(rows) == 1
    row = rows[0]
    assert row['test_used'] == 'Mann-Whitney U'
    assert math.isclose(row['effect_size'], -0.52, rel_tol=1e-9)


def test_multi_group_rows_include_overall_effect_and_adjusted_significance():
    grouped_values = {
        'A': [1.0, 1.1, 0.9, 1.0, 1.2],
        'B': [2.0, 2.1, 2.2, 1.9, 2.0],
        'C': [3.0, 2.9, 3.1, 3.2, 3.0],
    }

    rows = compute_metric_pairwise_stats(
        'metric_z',
        grouped_values,
        config=ComparisonStatsConfig(correction_method='bh', include_effect_size_ci=True, ci_bootstrap_iterations=200),
    )

    assert len(rows) == 3
    for row in rows:
        assert set(['group_a', 'group_b', 'test_used', 'p_value', 'adjusted_p_value', 'effect_size', 'significant']).issubset(row.keys())
        assert row['effect_size'] is not None
        assert row['effect_size_ci'] is not None
