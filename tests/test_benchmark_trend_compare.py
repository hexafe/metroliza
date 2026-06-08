import json
import sys

import pytest

from scripts import benchmark_trend_compare


def test_trend_compare_reports_stage_metrics_without_affecting_exit_code(tmp_path, monkeypatch, capsys):
    baseline_path = tmp_path / 'baseline.json'
    run_path = tmp_path / 'run.json'
    output_path = tmp_path / 'trend-report.json'
    baseline_path.write_text(
        json.dumps(
            {
                'scenarios': {
                    'excel_export_high_header_cardinality_compare': {
                        'median_wall_time_s': 2.0,
                    },
                },
            }
        ),
        encoding='utf-8',
    )
    run_path.write_text(
        json.dumps(
            {
                'results': [
                    {
                        'scenario': 'excel_export_high_header_cardinality_compare',
                        'wall_time_s': 1.0,
                        'stage_timings_s': {
                            'after_distribution_payload': 0.25,
                        },
                    },
                ],
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'benchmark_trend_compare.py',
            '--baseline',
            str(baseline_path),
            '--runs',
            str(run_path),
            '--output-json',
            str(output_path),
            '--stage-metrics',
            'excel_export_high_header_cardinality_compare:after_distribution_payload',
            'excel_export_high_header_cardinality_compare:after_histogram_payload',
        ],
    )

    assert benchmark_trend_compare.main() == 0

    report = json.loads(output_path.read_text(encoding='utf-8'))
    assert report['failed_scenarios'] == []
    assert report['stage_metric_results'] == [
        {
            'scenario': 'excel_export_high_header_cardinality_compare',
            'stage': 'after_distribution_payload',
            'observed_median_s': 0.25,
            'sample_count': 1,
            'status': 'observed',
        },
        {
            'scenario': 'excel_export_high_header_cardinality_compare',
            'stage': 'after_histogram_payload',
            'observed_median_s': 0.0,
            'sample_count': 0,
            'status': 'missing',
        },
    ]
    output = capsys.readouterr().out
    assert 'stage_metric scenario=excel_export_high_header_cardinality_compare stage=after_distribution_payload' in output


def test_trend_compare_stage_metrics_remain_advisory_when_wall_time_fails(tmp_path, monkeypatch):
    baseline_path = tmp_path / 'baseline.json'
    run_path = tmp_path / 'run.json'
    output_path = tmp_path / 'trend-report.json'
    baseline_path.write_text(
        json.dumps({'scenarios': {'excel_export_path': {'median_wall_time_s': 1.0}}}),
        encoding='utf-8',
    )
    run_path.write_text(
        json.dumps(
            {
                'results': [
                    {
                        'scenario': 'excel_export_path',
                        'wall_time_s': 2.0,
                        'stage_timings_s': {
                            'chart_payload_preparation': 0.5,
                        },
                    },
                ],
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'benchmark_trend_compare.py',
            '--baseline',
            str(baseline_path),
            '--runs',
            str(run_path),
            '--output-json',
            str(output_path),
            '--max-median-regression-pct',
            '10',
            '--min-median-regression-s',
            '0.1',
            '--stage-metrics',
            'excel_export_path:chart_payload_preparation',
        ],
    )

    assert benchmark_trend_compare.main() == 1

    report = json.loads(output_path.read_text(encoding='utf-8'))
    assert report['failed_scenarios'] == ['excel_export_path']
    assert report['stage_metric_results'][0]['status'] == 'observed'


def test_trend_compare_required_baseline_fails_missing_requested_baseline(
    tmp_path,
    monkeypatch,
):
    baseline_path = tmp_path / 'baseline.json'
    run_path = tmp_path / 'run.json'
    output_path = tmp_path / 'trend-report.json'
    baseline_path.write_text(json.dumps({'scenarios': {}}), encoding='utf-8')
    run_path.write_text(
        json.dumps({'results': [{'scenario': 'cmm_parser_backend_compare', 'wall_time_s': 1.0}]}),
        encoding='utf-8',
    )
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'benchmark_trend_compare.py',
            '--baseline',
            str(baseline_path),
            '--runs',
            str(run_path),
            '--output-json',
            str(output_path),
            '--scenarios',
            'cmm_parser_backend_compare',
            '--require-baselines',
        ],
    )

    assert benchmark_trend_compare.main() == 1

    report = json.loads(output_path.read_text(encoding='utf-8'))
    assert report['failed_scenarios'] == ['cmm_parser_backend_compare']
    assert report['results'][0]['status'] == 'missing_baseline'


def test_trend_compare_required_observed_fails_missing_requested_rows(
    tmp_path,
    monkeypatch,
):
    baseline_path = tmp_path / 'baseline.json'
    run_path = tmp_path / 'run.json'
    output_path = tmp_path / 'trend-report.json'
    baseline_path.write_text(
        json.dumps({'scenarios': {'cmm_parser_backend_compare': {'median_wall_time_s': 1.0}}}),
        encoding='utf-8',
    )
    run_path.write_text(json.dumps({'results': []}), encoding='utf-8')
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'benchmark_trend_compare.py',
            '--baseline',
            str(baseline_path),
            '--runs',
            str(run_path),
            '--output-json',
            str(output_path),
            '--scenarios',
            'cmm_parser_backend_compare',
            '--require-observed',
        ],
    )

    assert benchmark_trend_compare.main() == 1

    report = json.loads(output_path.read_text(encoding='utf-8'))
    assert report['failed_scenarios'] == ['cmm_parser_backend_compare']
    assert report['results'][0]['status'] == 'missing_observed'


def test_parse_stage_metric_specs_rejects_ambiguous_values():
    with pytest.raises(ValueError, match='SCENARIO:STAGE'):
        benchmark_trend_compare._parse_stage_metric_specs(['excel_export_path'])
