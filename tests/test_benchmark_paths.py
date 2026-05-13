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
