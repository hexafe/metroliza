from scripts.benchmark_paths import (
    benchmark_csv_summary_large_data_probe,
    benchmark_csv_summary_path,
    benchmark_distribution_fit_gof_policy_compare,
    benchmark_production_dashboard_workbook_path,
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
                'workbook_close': 0.4,
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
        'csv_summary_dashboard_workbook_timing_s',
        'production_dashboard_workbook_timing_s',
    }
    assert summary['chart_backend_distribution']['counts'] == {'native': 2, 'matplotlib': 6}
    assert summary['per_chart_type_timing_medians_s']['histogram'] == 0.6
    assert summary['high_header_cardinality_scenario_timing_s']['speedup_ratio'] == 2.0


def test_csv_summary_benchmark_runs_groupstats_path(tmp_path):
    result = benchmark_csv_summary_path(tmp_path, row_count=18, data_columns=2)

    assert result.scenario == 'csv_summary_export_path'
    assert result.stage_timings_s['groupstats_analysis'] > 0.0
    assert result.stage_timings_s['dashboard_manifest'] >= 0.0
    assert result.stage_timings_s['dashboard_html_write'] > 0.0
    assert result.stage_timings_s['dashboard_write'] > 0.0
    assert result.stage_timings_s['dashboard_write_overhead'] >= 0.0
    assert result.stage_timings_s['workbook_export'] > 0.0
    assert result.stage_timings_s['workbook_sheet_writes'] > 0.0
    assert result.stage_timings_s['workbook_close'] >= 0.0
    assert result.stage_timings_s['workbook_export_overhead'] >= 0.0
    assert result.input_metrics['groupstats_metric_count'] == 2
    assert result.input_metrics['dashboard_html_bytes'] > 0
    assert result.input_metrics['dashboard_plotly_spec_count'] >= result.input_metrics[
        'dashboard_embedded_plotly_spec_count'
    ]
    assert result.input_metrics['dashboard_plotly_budget_over'] == 0
    assert result.input_metrics['workbook_sheet_write_count'] >= 4


def test_production_dashboard_workbook_benchmark_captures_output_timings(tmp_path):
    result = benchmark_production_dashboard_workbook_path(
        tmp_path,
        row_count=24,
        metric_count=2,
    )

    assert result.scenario == 'production_dashboard_workbook_path'
    assert result.stage_timings_s['dashboard_manifest'] >= 0.0
    assert result.stage_timings_s['dashboard_html_write'] > 0.0
    assert result.stage_timings_s['dashboard_write'] > 0.0
    assert result.stage_timings_s['workbook_export'] > 0.0
    assert result.stage_timings_s['workbook_sheet_writes'] > 0.0
    assert result.stage_timings_s['workbook_close'] >= 0.0
    assert result.stage_timings_s['workbook_export_overhead'] >= 0.0
    assert result.input_metrics['rows'] == 24
    assert result.input_metrics['headers'] == 2
    assert result.input_metrics['chart_count'] >= 2
    assert result.input_metrics['dashboard_html_bytes'] > 0
    assert result.input_metrics['dashboard_plotly_spec_count'] >= result.input_metrics[
        'dashboard_embedded_plotly_spec_count'
    ]
    assert result.input_metrics['dashboard_plotly_budget_over'] == 0
    assert result.input_metrics['workbook_sheet_write_count'] >= 4
    assert result.input_metrics['workbook_bytes'] > 0


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
    assert result.stage_timings_s['csv_load_read_file'] >= 0.0
    assert result.stage_timings_s['csv_load_sampling'] >= 0.0
    assert result.stage_timings_s['csv_load_chunk_read'] >= 0.0
    assert result.stage_timings_s['csv_load_normalize_columns'] >= 0.0
    assert result.stage_timings_s['csv_load_chunk_normalize'] >= 0.0
    assert result.stage_timings_s['csv_load_chunk_build_rows'] >= 0.0
    assert result.stage_timings_s['csv_load_metric_stats'] >= 0.0
    assert result.stage_timings_s['csv_load_sqlite_ingest'] >= 0.0
    assert result.stage_timings_s['csv_load_sqlite_setup'] >= 0.0
    assert result.stage_timings_s['csv_load_sqlite_write'] >= 0.0
    assert result.stage_timings_s['csv_load_indexing'] >= 0.0
    assert result.stage_timings_s['csv_load_metric_candidates'] >= 0.0
    assert result.stage_timings_s['csv_load_preview'] >= 0.0
    assert result.stage_timings_s['csv_load_internal_total'] >= 0.0
    assert result.stage_timings_s['csv_load_unattributed'] >= 0.0
    assert result.stage_timings_s['sqlite_value_preview'] >= 0.0
    assert result.stage_timings_s['sqlite_multi_column_group_preview'] >= 0.0
    assert result.stage_timings_s['sqlite_assign_filtered_scope'] >= 0.0
    assert result.stage_timings_s['sqlite_use_grouping_sparse_assignment'] >= 0.0
    assert result.stage_timings_s['group_preview'] >= 0.0
    assert result.input_metrics['rows'] == 24
    assert result.input_metrics['csv_load_substage_available'] == 1
    assert result.input_metrics['storage_mode_sqlite'] == 1
    assert result.input_metrics['materialized_columns'] >= 3
    assert result.input_metrics['preview_multi_column_group_total'] >= 1
    assert result.input_metrics['assign_filtered_scope_rows'] >= 1


def test_distribution_fit_gof_policy_compare_smoke(tmp_path):
    result = benchmark_distribution_fit_gof_policy_compare(
        tmp_path,
        group_count=2,
        sample_size=36,
        monte_carlo_samples=3,
        gof_max_sample_size=12,
    )

    assert result.scenario == 'distribution_fit_gof_policy_compare'
    assert result.stage_timings_s['full_monte_carlo_path'] >= 0.0
    assert result.stage_timings_s['auto_gof_policy_path'] >= 0.0
    assert result.stage_timings_s['auto_cache_warm_path'] >= 0.0
    assert result.stage_timings_s['auto_cached_refit_path'] >= 0.0
    assert result.stage_timings_s['auto_policy_speedup_ratio'] >= 0.0
    assert result.input_metrics['full_sample_size'] == 36
    assert result.input_metrics['requested_gof_max_sample_size'] == 12
    assert result.input_metrics['full_selected_policy_full'] == 2
    assert result.input_metrics['auto_selected_policy_subsampled'] == 2
    assert result.input_metrics['auto_effective_gof_sample_size_min'] == 12
    assert result.input_metrics['auto_effective_gof_sample_size_max'] == 12
