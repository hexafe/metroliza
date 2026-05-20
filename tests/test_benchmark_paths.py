from scripts.benchmark_paths import (
    benchmark_csv_summary_large_data_probe,
    benchmark_csv_summary_path,
    build_benchmark_run_summary,
)


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


def test_csv_summary_benchmark_runs_groupstats_path(tmp_path):
    result = benchmark_csv_summary_path(tmp_path, row_count=18, data_columns=2)

    assert result.scenario == 'csv_summary_export_path'
    assert result.stage_timings_s['groupstats_analysis'] > 0.0
    assert result.input_metrics['groupstats_metric_count'] == 2


def test_csv_summary_large_data_probe_smoke(tmp_path):
    result = benchmark_csv_summary_large_data_probe(
        tmp_path,
        row_count=24,
        data_columns=3,
        search_text='P-00',
        materialize_columns=2,
    )

    assert result.scenario == 'csv_summary_large_data_probe'
    assert result.stage_timings_s['csv_load'] >= 0.0
    assert result.stage_timings_s['sqlite_value_preview'] >= 0.0
    assert result.stage_timings_s['sqlite_multi_column_group_preview'] >= 0.0
    assert result.stage_timings_s['sqlite_assign_filtered_scope'] >= 0.0
    assert result.stage_timings_s['sqlite_use_grouping_sparse_assignment'] >= 0.0
    assert result.stage_timings_s['group_preview'] >= 0.0
    assert result.input_metrics['rows'] == 24
    assert result.input_metrics['storage_mode_sqlite'] == 1
    assert result.input_metrics['materialized_columns'] >= 3
    assert result.input_metrics['preview_multi_column_group_total'] >= 1
    assert result.input_metrics['assign_filtered_scope_rows'] >= 1
