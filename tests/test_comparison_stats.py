import math
import time

import numpy as np

from modules.comparison_stats import ComparisonStatsConfig, _adjust_pvalues, _cliffs_delta, compute_metric_pairwise_stats


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


def test_multi_group_rows_include_distinct_pairwise_and_omnibus_effect_sizes():
    grouped_values = {
        'A': [0.0, 0.1, -0.1, 0.05, -0.05],
        'B': [0.4, 0.5, 0.45, 0.55, 0.5],
        'C': [2.0, 2.1, 1.9, 2.05, 1.95],
    }

    rows = compute_metric_pairwise_stats(
        'metric_z',
        grouped_values,
        config=ComparisonStatsConfig(correction_method='bh', include_effect_size_ci=True, ci_bootstrap_iterations=200),
    )

    assert len(rows) == 3
    pairwise_effects = {}
    omnibus_effects = set()
    for row in rows:
        assert set([
            'group_a',
            'group_b',
            'test_used',
            'pairwise_test_name',
            'p_value',
            'adjusted_p_value',
            'effect_size',
            'effect_type',
            'pairwise_effect_type',
            'omnibus_effect_size',
            'omnibus_effect_type',
            'effect_types',
            'significant',
            'normality_check_used',
            'variance_test_used',
            'omnibus_test_used',
            'omnibus_test_name',
            'post_hoc_strategy',
            'correction_policy',
            'assumption_outcomes',
            'selection_detail',
        ]).issubset(row.keys())
        assert row['normality_check_used'] == 'Shapiro-Wilk'
        assert row['post_hoc_strategy'] in {
            'pairwise t-tests + Benjamini-Hochberg',
            'pairwise Welch t-tests + Benjamini-Hochberg',
            'pairwise Mann-Whitney + Benjamini-Hochberg',
        }
        assert row['correction_method'] == 'Benjamini-Hochberg'
        assert row['correction_policy'] == 'Exploratory false-discovery-rate control (Benjamini-Hochberg/FDR)'
        assert row['effect_type'] in {'cohen_d', 'cliffs_delta'}
        assert row['pairwise_effect_type'] == row['effect_type']
        assert row['effect_size'] is not None
        assert row['effect_size_ci'] is not None
        assert row['omnibus_effect_size'] is not None
        assert row['omnibus_effect_type'] in {'eta_squared', 'omega_squared', 'cliffs_delta'}
        assert row['effect_types']['pairwise'] == row['pairwise_effect_type']
        assert row['effect_types']['omnibus'] == row['omnibus_effect_type']
        assert row['omnibus_effect_size_ci'] is not None
        assert row['pairwise_test_name'] == row['test_used']
        assert row['omnibus_test_name'] == row['omnibus_test_used']
        assert row['selection_detail']
        assert row['assumption_outcomes']['selection_mode'] in {
            'parametric_equal_variance',
            'parametric_unequal_variance',
            'non_parametric',
        }
        pairwise_effects[(row['group_a'], row['group_b'])] = row['effect_size']
        omnibus_effects.add(row['omnibus_effect_size'])

    assert len(omnibus_effects) == 1
    assert not math.isclose(pairwise_effects[('A', 'B')], pairwise_effects[('A', 'C')], rel_tol=1e-9)
    assert not math.isclose(pairwise_effects[('A', 'B')], pairwise_effects[('B', 'C')], rel_tol=1e-9)
    assert not math.isclose(pairwise_effects[('A', 'B')], next(iter(omnibus_effects)), rel_tol=1e-9)




def test_multi_group_parametric_fixture_uses_pair_specific_effects_and_shared_strategy():
    grouped_values = {
        'A': [0.0, 0.1, -0.1, 0.0, 0.05],
        'B': [0.2, 0.3, 0.25, 0.35, 0.3],
        'C': [1.4, 1.5, 1.45, 1.55, 1.6],
    }

    rows = compute_metric_pairwise_stats('metric_pair_specific', grouped_values)

    assert len(rows) == 3
    assert {row['post_hoc_strategy'] for row in rows} == {'pairwise t-tests + Holm'}
    pair_effects = {(row['group_a'], row['group_b']): row['effect_size'] for row in rows}

    assert pair_effects[('A', 'B')] != pair_effects[('A', 'C')]
    assert pair_effects[('A', 'B')] != pair_effects[('B', 'C')]
    assert pair_effects[('A', 'C')] != pair_effects[('B', 'C')]
    assert all(row['pairwise_effect_type'] == 'cohen_d' for row in rows)
    assert all(row['omnibus_effect_type'] == 'eta_squared' for row in rows)

def test_pairwise_rows_include_holm_adjustment_for_all_pairs():
    grouped_values = {
        'A': [1.0, 1.1, 1.2, 1.3, 1.4],
        'B': [1.0, 1.05, 1.1, 1.2, 1.25],
        'C': [2.0, 2.1, 2.2, 2.1, 2.0],
    }

    rows = compute_metric_pairwise_stats('metric_holm', grouped_values)

    assert len(rows) == 3
    assert all(row['adjusted_p_value'] is not None for row in rows)
    assert all(row['adjusted_p_value'] >= row['p_value'] for row in rows if row['p_value'] is not None)


def test_pairwise_stats_handles_unequal_group_sizes_and_sets_sample_specific_test():
    grouped_values = {
        'A': [1.0, 1.2, 1.1, 1.3, 1.4, 1.5],
        'B': [2.0, 2.2, 2.1],
    }

    rows = compute_metric_pairwise_stats('metric_unequal_n', grouped_values)

    assert len(rows) == 1
    assert rows[0]['group_a'] == 'A'
    assert rows[0]['group_b'] == 'B'
    assert rows[0]['test_used'] in {'Student t-test', 'Welch t-test', 'Mann-Whitney U'}


def test_pairwise_rows_include_method_traceability_for_non_parametric_path():
    grouped_values = {
        'A': [0.0, 0.0, 0.0, 10.0, 10.0],
        'B': [1.0, 1.0, 1.0, 11.0, 11.0],
    }

    rows = compute_metric_pairwise_stats('metric_trace', grouped_values)

    assert len(rows) == 1
    row = rows[0]
    assert row['normality_check_used'] == 'Shapiro-Wilk'
    assert row['variance_test_used'] in {'Levene', 'Brown-Forsythe'}
    assert row['omnibus_test_used'] == 'Mann-Whitney U'
    assert row['omnibus_test_name'] == 'Mann-Whitney U'
    assert row['post_hoc_strategy'] == 'pairwise Mann-Whitney + Holm'
    assert row['correction_method'] == 'Holm'
    assert row['correction_policy'] == 'Strict family-wise error control (Holm)'
    assert row['assumption_outcomes']['normality'] == 'failed'


def _legacy_cliffs_delta(sample_a, sample_b):
    greater = 0
    lesser = 0
    for left in sample_a:
        greater += int(np.sum(left > sample_b))
        lesser += int(np.sum(left < sample_b))
    return float((greater - lesser) / (sample_a.size * sample_b.size))


def test_cliffs_delta_rank_based_path_matches_legacy_loop_with_ties():
    rng = np.random.default_rng(1234)
    sample_a = rng.integers(-3, 4, size=257).astype(float)
    sample_b = rng.integers(-3, 4, size=211).astype(float)

    effect_size = _cliffs_delta(sample_a, sample_b)
    legacy_effect_size = _legacy_cliffs_delta(sample_a, sample_b)

    assert effect_size is not None
    assert math.isclose(effect_size, legacy_effect_size, rel_tol=1e-12, abs_tol=1e-12)


def test_cliffs_delta_rank_based_path_scales_better_on_large_arrays():
    rng = np.random.default_rng(99)
    sample_a = rng.integers(0, 101, size=4000).astype(float)
    sample_b = rng.integers(0, 101, size=4000).astype(float)

    optimized_durations = []
    legacy_durations = []
    for _ in range(3):
        start = time.perf_counter()
        optimized = _cliffs_delta(sample_a, sample_b)
        optimized_durations.append(time.perf_counter() - start)

        start = time.perf_counter()
        legacy = _legacy_cliffs_delta(sample_a, sample_b)
        legacy_durations.append(time.perf_counter() - start)

    optimized_time = min(optimized_durations)
    legacy_time = min(legacy_durations)

    assert optimized is not None
    assert legacy is not None
    assert math.isclose(optimized, legacy, rel_tol=1e-12, abs_tol=1e-12)
    assert optimized_time < legacy_time
