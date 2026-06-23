import csv
import json
import sys
from pathlib import Path

import pytest

from scripts import benchmark_paths
from scripts.benchmark_paths import (
    ScenarioResult,
    _collect_distribution_gof_metrics,
    _coerce_legacy,
    _write_outputs,
    benchmark_dashboard_static_multi_group_probe,
    benchmark_csv_summary_large_data_probe,
    benchmark_csv_summary_path,
    benchmark_cmm_fingerprint_sqlite_state_probe,
    benchmark_distribution_fit_gof_policy_compare,
    benchmark_export_sqlite_materialization_probe,
    benchmark_industrial_cache_ingest_probe,
    benchmark_industrial_cache_to_csv_summary_bridge_probe,
    benchmark_population_static_render_probe,
    benchmark_production_dashboard_workbook_path,
    benchmark_sqlite_grouping_high_cardinality_probe,
    benchmark_tabular_sqlite_aggregate_probe,
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
    assert result.stage_timings_s['dashboard_writer_plotly_json_measurement'] >= 0.0
    assert result.stage_timings_s['dashboard_writer_html_rendering'] >= 0.0
    assert result.stage_timings_s['dashboard_writer_html_write'] >= 0.0
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
    assert result.stage_timings_s['dashboard_writer_static_population_layer'] >= 0.0
    assert result.stage_timings_s['dashboard_writer_plotly_budget_resolution'] >= 0.0
    assert result.stage_timings_s['dashboard_writer_plotly_json_measurement'] >= 0.0
    assert result.stage_timings_s['dashboard_writer_html_rendering'] >= 0.0
    assert result.stage_timings_s['dashboard_writer_html_write'] >= 0.0
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


def test_cmm_fingerprint_sqlite_state_probe_smoke(tmp_path):
    result = benchmark_cmm_fingerprint_sqlite_state_probe(tmp_path, report_count=18)

    assert result.scenario == 'cmm_fingerprint_sqlite_state_probe'
    assert result.stage_timings_s['complete_fingerprint_load'] >= 0.0
    assert result.stage_timings_s['light_fingerprint_load'] >= 0.0
    assert result.stage_timings_s['query_plan_probe'] >= 0.0
    assert result.input_metrics['rows'] == 18
    assert result.input_metrics['complete_fingerprints'] == result.input_metrics[
        'complete_expected_fingerprints'
    ]
    assert result.input_metrics['light_fingerprints'] == result.input_metrics[
        'light_expected_fingerprints'
    ]
    assert result.input_metrics['complete_fingerprint_query_plan_steps'] > 0
    assert result.input_metrics['complete_fingerprint_query_plan_index_steps'] > 0


def test_export_sqlite_materialization_probe_smoke(tmp_path):
    result = benchmark_export_sqlite_materialization_probe(
        tmp_path,
        report_count=8,
        headers_per_report=3,
    )

    assert result.scenario == 'export_sqlite_materialization_probe'
    assert result.stage_timings_s['dataframe_materialize'] >= 0.0
    assert result.stage_timings_s['dataframe_groupby'] >= 0.0
    assert result.stage_timings_s['sqlite_aggregate'] >= 0.0
    assert result.stage_timings_s['query_plan_probe'] >= 0.0
    assert result.input_metrics['rows'] == 24
    assert result.input_metrics['headers'] == 3
    assert result.input_metrics['dataframe_rows'] == 24
    assert result.input_metrics['dataframe_cells'] >= 24
    assert result.input_metrics['dataframe_groups'] == result.input_metrics['sqlite_groups']
    assert result.input_metrics['sqlite_aggregate_query_plan_steps'] > 0


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


def test_population_static_render_probe_smoke(tmp_path):
    result = benchmark_population_static_render_probe(tmp_path, row_count=256)

    assert result.scenario == 'population_static_render_probe'
    assert result.stage_timings_s['array_generation'] >= 0.0
    assert result.stage_timings_s['full_density_render'] > 0.0
    assert result.stage_timings_s['sampled_marker_render'] > 0.0
    assert result.input_metrics['rows'] == 256
    assert result.input_metrics['density_contributed_points'] == 256
    assert result.input_metrics['density_png_bytes'] > 0
    assert result.input_metrics['density_non_empty_pixels'] > 0
    assert result.input_metrics['sampled_marker_points'] == 256
    assert result.input_metrics['sampled_marker_png_bytes'] > 0


def test_industrial_cache_ingest_probe_smoke(tmp_path):
    result = benchmark_industrial_cache_ingest_probe(
        tmp_path,
        row_count=12,
        dynamic_fields=2,
        source_count=2,
    )

    assert result.scenario == 'industrial_cache_ingest_probe'
    assert result.stage_timings_s['schema_setup'] >= 0.0
    assert result.stage_timings_s['source_profile_and_sync_setup'] >= 0.0
    assert result.stage_timings_s['cache_insert'] > 0.0
    assert result.stage_timings_s['sync_finish'] >= 0.0
    assert result.stage_timings_s['cache_summary'] >= 0.0
    assert result.input_metrics['rows'] == 12
    assert result.input_metrics['headers'] == 2
    assert result.input_metrics['source_count'] == 2
    assert result.input_metrics['processed_rows'] == 12
    assert result.input_metrics['inserted_rows'] == 12
    assert result.input_metrics['updated_rows'] == 0
    assert result.input_metrics['dynamic_value_rows'] == 24
    assert result.input_metrics['cache_records'] == 12
    assert result.input_metrics['cache_record_values'] == 24
    assert result.input_metrics['cache_db_bytes'] > 0


def test_industrial_cache_to_csv_summary_bridge_probe_smoke(tmp_path):
    result = benchmark_industrial_cache_to_csv_summary_bridge_probe(
        tmp_path,
        row_count=10,
        dynamic_fields=2,
        source_count=2,
        materialize_columns=2,
    )

    assert result.scenario == 'industrial_cache_to_csv_summary_bridge_probe'
    assert result.stage_timings_s['industrial_cache_populate'] > 0.0
    assert result.stage_timings_s['bridge_to_tabular_sqlite'] > 0.0
    assert result.stage_timings_s['source_group_preview'] >= 0.0
    assert result.stage_timings_s['source_line_group_preview'] >= 0.0
    assert result.stage_timings_s['materialize_required_columns'] >= 0.0
    assert result.input_metrics['rows'] == 10
    assert result.input_metrics['headers'] == 2
    assert result.input_metrics['source_count'] == 2
    assert result.input_metrics['cache_records'] == 10
    assert result.input_metrics['cache_record_values'] == 20
    assert result.input_metrics['bridge_row_count'] == 10
    assert result.input_metrics['bridge_columns'] >= 20
    assert result.input_metrics['source_preview_total'] == 2
    assert result.input_metrics['source_line_preview_total'] >= 2
    assert result.input_metrics['materialized_rows'] == 10
    assert result.input_metrics['materialized_columns'] >= 5


def test_dashboard_static_multi_group_probe_smoke(tmp_path):
    result = benchmark_dashboard_static_multi_group_probe(
        tmp_path,
        group_count=3,
        rows_per_group=64,
    )

    assert result.scenario == 'dashboard_static_multi_group_probe'
    assert result.stage_timings_s['array_generation'] >= 0.0
    assert result.stage_timings_s['density_layer_render'] > 0.0
    assert result.stage_timings_s['sampled_marker_layer_render'] > 0.0
    assert result.input_metrics['rows'] == 192
    assert result.input_metrics['headers'] == 3
    assert result.input_metrics['group_count'] == 3
    assert result.input_metrics['rows_per_group'] == 64
    assert result.input_metrics['density_layer_count'] == 3
    assert result.input_metrics['density_contributed_points'] == 192
    assert result.input_metrics['density_png_bytes'] > 0
    assert result.input_metrics['density_non_empty_pixels'] > 0
    assert result.input_metrics['sampled_marker_points_per_group'] == 64
    assert result.input_metrics['sampled_marker_total_points'] == 192
    assert result.input_metrics['sampled_marker_png_bytes'] > 0


def test_sqlite_grouping_high_cardinality_probe_smoke(tmp_path):
    result = benchmark_sqlite_grouping_high_cardinality_probe(
        tmp_path,
        row_count=24,
        group_count=24,
        search_text='G-0000000',
        materialize_columns=2,
    )

    assert result.scenario == 'sqlite_grouping_high_cardinality_probe'
    assert result.stage_timings_s['csv_sqlite_load'] >= 0.0
    assert result.stage_timings_s['value_preview'] >= 0.0
    assert result.stage_timings_s['single_column_group_preview'] >= 0.0
    assert result.stage_timings_s['multi_column_group_preview'] >= 0.0
    assert result.stage_timings_s['row_ids_for_group_search'] >= 0.0
    assert result.stage_timings_s['assign_filtered_scope'] >= 0.0
    assert result.stage_timings_s['materialize_required_columns'] >= 0.0
    assert result.input_metrics['rows'] == 24
    assert result.input_metrics['headers'] == 5
    assert result.input_metrics['configured_group_count'] == 24
    assert result.input_metrics['storage_mode_sqlite'] == 1
    assert result.input_metrics['sqlite_row_count'] == 24
    assert result.input_metrics['value_preview_total'] >= 1
    assert result.input_metrics['group_preview_total'] >= 1
    assert result.input_metrics['multi_group_preview_total'] >= 1
    assert result.input_metrics['row_ids_for_search'] >= 1
    assert result.input_metrics['assign_filtered_scope_rows'] >= 1
    assert result.input_metrics['materialized_rows'] == 24
    assert result.input_metrics['materialized_columns'] >= 5


def test_tabular_sqlite_aggregate_probe_smoke(tmp_path):
    result = benchmark_tabular_sqlite_aggregate_probe(
        tmp_path,
        row_count=24,
        group_count=6,
        materialize_columns=2,
    )

    assert result.scenario == 'tabular_sqlite_aggregate_probe'
    assert result.stage_timings_s['csv_sqlite_load'] >= 0.0
    assert result.stage_timings_s['sqlite_grouped_aggregate'] >= 0.0
    assert result.stage_timings_s['sqlite_row_batch_stream'] >= 0.0
    assert result.stage_timings_s['materialize_required_columns'] >= 0.0
    assert result.stage_timings_s['materialize_to_sqlite_aggregate_ratio'] >= 0.0
    assert result.input_metrics['rows'] == 24
    assert result.input_metrics['headers'] == 5
    assert result.input_metrics['configured_group_count'] == 6
    assert result.input_metrics['storage_mode_sqlite'] == 1
    assert result.input_metrics['sqlite_row_count'] == 24
    assert result.input_metrics['aggregate_metrics'] == 2
    assert result.input_metrics['aggregate_rows'] == 12
    assert result.input_metrics['streamed_rows'] == 24
    assert result.input_metrics['materialized_rows'] == 24
    assert result.input_metrics['materialized_columns'] >= 5


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


def test_distribution_gof_metrics_counts_methods_policies_and_effective_sizes():
    metrics = _collect_distribution_gof_metrics(
        [
            {
                'gof_metrics': {
                    'ad_pvalue_method': 'monte_carlo',
                    'ad_sample_policy': 'full',
                    'ad_effective_sample_size': 40,
                },
                'ranking_metrics': [
                    {'ad_pvalue_method': 'ks_proxy'},
                    {'ad_pvalue_method': 'monte_carlo'},
                ],
            },
            {
                'gof_metrics': {
                    'ad_pvalue_method': 'ks_proxy',
                    'ad_sample_policy': 'subsampled',
                    'ad_effective_sample_size': 12,
                },
                'ranking_metrics': [{'ad_pvalue_method': None}],
            },
            {},
        ],
        prefix='auto',
    )

    assert metrics == {
        'auto_selected_count': 3,
        'auto_effective_gof_sample_size_min': 12,
        'auto_effective_gof_sample_size_max': 40,
        'auto_selected_method_monte_carlo': 1,
        'auto_selected_method_ks_proxy': 1,
        'auto_selected_method_unknown': 1,
        'auto_selected_policy_full': 1,
        'auto_selected_policy_subsampled': 1,
        'auto_selected_policy_unknown': 1,
        'auto_ranking_method_ks_proxy': 1,
        'auto_ranking_method_monte_carlo': 1,
        'auto_ranking_method_unknown': 1,
    }


def test_coerce_legacy_converts_mixed_values_to_float_array():
    values = _coerce_legacy(['1.5', None, 'bad', 2])

    assert values.tolist()[0] == 1.5
    assert values.tolist()[3] == 2.0
    assert values.shape == (4,)
    assert values.dtype.kind == 'f'
    assert values[1] != values[1]
    assert values[2] != values[2]


def test_write_outputs_writes_parseable_json_and_flat_csv(tmp_path: Path):
    payload = {
        'results': [
            {
                'scenario': 'synthetic_path',
                'wall_time_s': 1.25,
                'stage_timings_s': {'load': 0.5, 'write': 0.75},
                'input_metrics': {'rows': 10, 'headers': 2},
            }
        ]
    }

    json_path, csv_path = _write_outputs(tmp_path / 'benchmarks', payload)

    assert json.loads(json_path.read_text(encoding='utf-8')) == payload
    rows = list(csv.DictReader(csv_path.open(encoding='utf-8')))
    assert rows == [
        {
            'scenario': 'synthetic_path',
            'metric_type': 'wall_time_s',
            'metric_name': 'total',
            'value': '1.25',
        },
        {
            'scenario': 'synthetic_path',
            'metric_type': 'stage_timing_s',
            'metric_name': 'load',
            'value': '0.5',
        },
        {
            'scenario': 'synthetic_path',
            'metric_type': 'stage_timing_s',
            'metric_name': 'write',
            'value': '0.75',
        },
        {
            'scenario': 'synthetic_path',
            'metric_type': 'input_metric',
            'metric_name': 'rows',
            'value': '10',
        },
        {
            'scenario': 'synthetic_path',
            'metric_type': 'input_metric',
            'metric_name': 'headers',
            'value': '2',
        },
    ]


def test_benchmark_main_runs_selected_mocked_scenarios_and_writes_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    calls: list[str] = []

    def fake_result(scenario: str) -> ScenarioResult:
        return ScenarioResult(
            scenario=scenario,
            wall_time_s=0.1,
            stage_timings_s={'selected': float(len(calls))},
            input_metrics={
                'rows': 1,
                'headers': 1,
                'chart_count': 1,
                'chart_backend_native_count': 1 if scenario == 'excel_export_path' else 0,
                'chart_backend_matplotlib_count': 2 if scenario == 'excel_export_path' else 0,
                'chart_type_median_distribution_s': 0.3,
            },
        )

    def fake_excel(temp_path: Path, *, report_count: int, headers_per_report: int) -> ScenarioResult:
        assert temp_path.exists()
        assert report_count == 3
        assert headers_per_report == 4
        calls.append('excel_export_path')
        return fake_result('excel_export_path')

    def fake_chart(temp_path: Path, *, chart_type: str, iterations: int) -> ScenarioResult:
        assert temp_path.exists()
        assert chart_type == 'histogram'
        assert iterations == 2
        calls.append('chart_type_native_compare')
        return fake_result('chart_type_native_compare')

    monkeypatch.setattr(benchmark_paths, 'benchmark_excel_export_path', fake_excel)
    monkeypatch.setattr(benchmark_paths, 'benchmark_chart_type_native_compare_path', fake_chart)
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'benchmark_paths.py',
            '--output-dir',
            str(tmp_path),
            '--report-count',
            '3',
            '--headers-per-report',
            '4',
            '--chart-type-benchmark-chart',
            'histogram',
            '--chart-type-benchmark-iterations',
            '2',
            '--scenarios',
            'excel_export_path',
            'chart_type_native_compare',
        ],
    )

    result = benchmark_paths.main()

    assert result == 0
    assert calls == ['excel_export_path', 'chart_type_native_compare']
    output = capsys.readouterr().out
    assert 'Benchmark JSON:' in output
    json_path = next(tmp_path.glob('benchmark-*.json'))
    payload = json.loads(json_path.read_text(encoding='utf-8'))
    assert [item['scenario'] for item in payload['results']] == [
        'excel_export_path',
        'chart_type_native_compare',
    ]
    assert payload['config']['scenarios'] == ['excel_export_path', 'chart_type_native_compare']
    assert payload['summary']['chart_backend_distribution']['counts'] == {
        'native': 1,
        'matplotlib': 2,
    }


def test_benchmark_main_registers_rc_manual_probe_scenarios(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[str] = []

    def runner(name: str):
        def _run(_temp_path: Path, **_kwargs) -> ScenarioResult:
            calls.append(name)
            return ScenarioResult(
                scenario=name,
                wall_time_s=0.01,
                stage_timings_s={},
                input_metrics={},
            )

        return _run

    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_industrial_cache_ingest_probe',
        runner('industrial_cache_ingest_probe'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_industrial_cache_to_csv_summary_bridge_probe',
        runner('industrial_cache_to_csv_summary_bridge_probe'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_dashboard_static_multi_group_probe',
        runner('dashboard_static_multi_group_probe'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_sqlite_grouping_high_cardinality_probe',
        runner('sqlite_grouping_high_cardinality_probe'),
    )
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'benchmark_paths.py',
            '--output-dir',
            str(tmp_path),
            '--industrial-cache-rows',
            '12',
            '--industrial-cache-dynamic-fields',
            '2',
            '--industrial-cache-source-count',
            '2',
            '--static-group-count',
            '3',
            '--static-group-rows-per-group',
            '64',
            '--grouping-high-cardinality-rows',
            '24',
            '--grouping-high-cardinality-groups',
            '24',
            '--scenarios',
            'industrial_cache_ingest_probe',
            'industrial_cache_to_csv_summary_bridge_probe',
            'dashboard_static_multi_group_probe',
            'sqlite_grouping_high_cardinality_probe',
        ],
    )

    assert benchmark_paths.main() == 0
    assert calls == [
        'industrial_cache_ingest_probe',
        'industrial_cache_to_csv_summary_bridge_probe',
        'dashboard_static_multi_group_probe',
        'sqlite_grouping_high_cardinality_probe',
    ]
    json_path = next(tmp_path.glob('benchmark-*.json'))
    payload = json.loads(json_path.read_text(encoding='utf-8'))
    assert payload['config']['scenarios'] == calls


def test_benchmark_main_default_selection_skips_manual_large_csv_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    called: list[str] = []

    def runner(name: str):
        def _run(_temp_path: Path, **_kwargs) -> ScenarioResult:
            called.append(name)
            return ScenarioResult(
                scenario=name,
                wall_time_s=0.01,
                stage_timings_s={},
                input_metrics={},
            )

        return _run

    monkeypatch.setattr(benchmark_paths, 'benchmark_parse_path', runner('pdf_parse_path'))
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_cmm_fingerprint_sqlite_state_probe',
        runner('cmm_fingerprint_sqlite_state_probe'),
    )
    monkeypatch.setattr(benchmark_paths, 'benchmark_excel_export_path', runner('excel_export_path'))
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_export_sqlite_materialization_probe',
        runner('export_sqlite_materialization_probe'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_export_write_vs_shape_path',
        runner('excel_export_write_vs_shape_path'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_export_high_header_cardinality_path',
        runner('excel_export_high_header_cardinality_compare'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_csv_summary_path',
        runner('csv_summary_export_path'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_production_dashboard_workbook_path',
        runner('production_dashboard_workbook_path'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_csv_summary_large_data_probe',
        runner('csv_summary_large_data_probe'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_population_static_render_probe',
        runner('population_static_render_probe'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_industrial_cache_ingest_probe',
        runner('industrial_cache_ingest_probe'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_industrial_cache_to_csv_summary_bridge_probe',
        runner('industrial_cache_to_csv_summary_bridge_probe'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_dashboard_static_multi_group_probe',
        runner('dashboard_static_multi_group_probe'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_sqlite_grouping_high_cardinality_probe',
        runner('sqlite_grouping_high_cardinality_probe'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_distribution_fit_monte_carlo_path',
        runner('distribution_fit_monte_carlo_path'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_distribution_fit_gof_policy_compare',
        runner('distribution_fit_gof_policy_compare'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_group_preprocess_mixed_types_path',
        runner('group_preprocess_mixed_types_compare'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_cmm_parser_backend_compare',
        runner('cmm_parser_backend_compare'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_chart_render_budget_path',
        runner('chart_render_budget_path'),
    )
    monkeypatch.setattr(
        benchmark_paths,
        'benchmark_chart_type_native_compare_path',
        runner('chart_type_native_compare'),
    )
    monkeypatch.setattr(
        sys,
        'argv',
        ['benchmark_paths.py', '--output-dir', str(tmp_path)],
    )

    assert benchmark_paths.main() == 0
    assert 'csv_summary_large_data_probe' not in called
    assert 'population_static_render_probe' not in called
    assert 'industrial_cache_ingest_probe' not in called
    assert 'industrial_cache_to_csv_summary_bridge_probe' not in called
    assert 'dashboard_static_multi_group_probe' not in called
    assert 'sqlite_grouping_high_cardinality_probe' not in called
    assert called == [
        'pdf_parse_path',
        'cmm_fingerprint_sqlite_state_probe',
        'excel_export_path',
        'export_sqlite_materialization_probe',
        'excel_export_write_vs_shape_path',
        'excel_export_high_header_cardinality_compare',
        'csv_summary_export_path',
        'production_dashboard_workbook_path',
        'distribution_fit_monte_carlo_path',
        'distribution_fit_gof_policy_compare',
        'group_preprocess_mixed_types_compare',
        'cmm_parser_backend_compare',
        'chart_render_budget_path',
        'chart_type_native_compare',
    ]


def test_benchmark_main_validates_cli_choices(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        sys,
        'argv',
        ['benchmark_paths.py', '--chart-type-benchmark-chart', 'scatter'],
    )

    with pytest.raises(SystemExit) as exc_info:
        benchmark_paths.main()

    assert exc_info.value.code == 2
