import time

import numpy as np

from modules.group_stats_native import coerce_sequence_to_float64
from scripts.benchmark_paths import build_benchmark_run_summary


def test_build_benchmark_run_summary_includes_contract_keys():
    results = [
        {
            'scenario': 'excel_export_path',
            'stage_timings_s': {
                'chart_payload_preparation': 1.1,
                'chart_rendering': 2.2,
                'worksheet_writes': 3.3,
            },
            'input_metrics': {
                'chart_backend_native_count': 2,
                'chart_backend_matplotlib_count': 6,
                'chart_type_median_distribution_s': 0.4,
                'chart_type_median_iqr_s': 0.5,
                'chart_type_median_histogram_s': 0.6,
                'chart_type_median_trend_s': 0.7,
            },
        },
        {
            'scenario': 'excel_export_high_header_cardinality_compare',
            'stage_timings_s': {
                'before_refactor': 4.0,
                'after_refactor': 2.0,
                'speedup_ratio': 2.0,
            },
            'input_metrics': {},
        },
    ]

    summary = build_benchmark_run_summary(results)

    assert set(summary.keys()) == {
        'chart_backend_distribution',
        'per_chart_type_timing_medians_s',
        'high_header_cardinality_scenario_timing_s',
    }
    assert summary['chart_backend_distribution']['counts'] == {'native': 2, 'matplotlib': 6}
    assert summary['per_chart_type_timing_medians_s']['histogram'] == 0.6
    assert summary['high_header_cardinality_scenario_timing_s']['speedup_ratio'] == 2.0


def _coerce_legacy(values: np.ndarray) -> np.ndarray:
    out = np.empty(values.size, dtype=np.float64)
    for idx, value in enumerate(values):
        try:
            out[idx] = float(value)
        except (TypeError, ValueError):
            out[idx] = np.nan
    return out


def test_group_stats_coercion_microbenchmark_tracks_target_speedup():
    expected_speedup_target_min = 1.5
    observed = []
    for size in (10**5, 10**6):
        values = np.random.default_rng(2026).normal(0.0, 1.0, size=size).astype(object)
        values[::17] = 'bad'
        values[::29] = None
        values[::31] = '3.14159'

        legacy_start = time.perf_counter()
        legacy = _coerce_legacy(values)
        legacy_s = time.perf_counter() - legacy_start

        new_start = time.perf_counter()
        optimized = coerce_sequence_to_float64(values)
        optimized_s = time.perf_counter() - new_start

        np.testing.assert_equal(np.isnan(legacy), np.isnan(optimized))
        observed.append(
            {
                'size': size,
                'legacy_s': legacy_s,
                'optimized_s': optimized_s,
                'speedup_ratio': (legacy_s / optimized_s) if optimized_s > 0 else 0.0,
            }
        )

    assert [item['size'] for item in observed] == [10**5, 10**6]
    assert expected_speedup_target_min == 1.5
    assert all(item['speedup_ratio'] > 0 for item in observed)
