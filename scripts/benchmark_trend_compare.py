#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path


EXPORT_STAGE_METRICS = (
    'excel_export_path:chart_payload_preparation',
    'excel_export_path:chart_rendering',
    'excel_export_path:worksheet_writes',
    'excel_export_path:workbook_close',
    'excel_export_write_vs_shape_path:data_shaping',
    'excel_export_write_vs_shape_path:write_only_worksheet_ops',
    'excel_export_write_vs_shape_path:workbook_close',
    'excel_export_high_header_cardinality_compare:after_sampling',
    'excel_export_high_header_cardinality_compare:after_distribution_payload',
    'excel_export_high_header_cardinality_compare:after_histogram_payload',
    'excel_export_high_header_cardinality_compare:after_trend_payload',
    'csv_summary_export_path:chart_generation',
    'csv_summary_export_path:dashboard_writer_plotly_json_measurement',
    'csv_summary_export_path:dashboard_writer_html_rendering',
    'csv_summary_export_path:dashboard_writer_html_write',
    'csv_summary_export_path:workbook_write',
    'csv_summary_export_path:workbook_close',
    'production_dashboard_workbook_path:dashboard_writer_static_population_layer',
    'production_dashboard_workbook_path:dashboard_writer_plotly_budget_resolution',
    'production_dashboard_workbook_path:dashboard_writer_plotly_json_measurement',
    'production_dashboard_workbook_path:dashboard_writer_html_rendering',
    'production_dashboard_workbook_path:dashboard_writer_html_write',
)


def _collect_wall_times(run_payloads: list[dict]) -> dict[str, list[float]]:
    by_scenario: dict[str, list[float]] = {}
    for payload in run_payloads:
        for scenario in payload.get('results', []):
            scenario_name = str(scenario.get('scenario', '')).strip()
            if not scenario_name:
                continue
            wall = float(scenario.get('wall_time_s', 0.0))
            by_scenario.setdefault(scenario_name, []).append(wall)
    return by_scenario


def _parse_stage_metric_specs(specs: list[str]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for spec in specs:
        raw_spec = str(spec).strip()
        if not raw_spec:
            continue
        if ':' not in raw_spec:
            raise ValueError(f"Stage metric must use SCENARIO:STAGE format, got {raw_spec!r}")
        scenario_name, stage_key = raw_spec.split(':', 1)
        scenario_name = scenario_name.strip()
        stage_key = stage_key.strip()
        if not scenario_name or not stage_key:
            raise ValueError(f"Stage metric must use SCENARIO:STAGE format, got {raw_spec!r}")
        parsed.append((scenario_name, stage_key))
    return parsed


def _collect_stage_times(
    run_payloads: list[dict],
    stage_metrics: list[tuple[str, str]],
) -> dict[tuple[str, str], list[float]]:
    requested = set(stage_metrics)
    by_stage: dict[tuple[str, str], list[float]] = {metric: [] for metric in stage_metrics}
    if not requested:
        return by_stage
    for payload in run_payloads:
        for scenario in payload.get('results', []):
            scenario_name = str(scenario.get('scenario', '')).strip()
            if not scenario_name:
                continue
            stage_timings = scenario.get('stage_timings_s') or {}
            for stage_key, stage_value in stage_timings.items():
                metric_key = (scenario_name, str(stage_key))
                if metric_key in requested:
                    by_stage.setdefault(metric_key, []).append(float(stage_value))
    return by_stage


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def main() -> int:
    parser = argparse.ArgumentParser(description='Compare benchmark run medians against checked-in baseline medians.')
    parser.add_argument('--baseline', required=True, help='Path to checked-in baseline snapshot JSON.')
    parser.add_argument('--runs', nargs='+', required=True, help='Benchmark JSON files from measured runs.')
    parser.add_argument('--output-json', required=True, help='Path to write trend comparison JSON.')
    parser.add_argument('--max-median-regression-pct', type=float, default=10.0)
    parser.add_argument(
        '--min-median-regression-s',
        type=float,
        default=0.0,
        help='Optional absolute slowdown floor in seconds. Fails only when both pct and absolute thresholds are exceeded.',
    )
    parser.add_argument(
        '--scenarios',
        nargs='+',
        help='Optional scenario keys to compare. When provided, only these scenarios are evaluated.',
    )
    parser.add_argument(
        '--stage-metrics',
        nargs='*',
        default=[],
        help='Optional advisory stage metrics in SCENARIO:STAGE format. These are reported but never fail the trend check.',
    )
    parser.add_argument(
        '--export-stage-metrics',
        action='store_true',
        help='Report the canonical export stage metrics as advisory observed medians.',
    )
    args = parser.parse_args()

    baseline = json.loads(Path(args.baseline).read_text(encoding='utf-8'))
    run_payloads = [json.loads(Path(path).read_text(encoding='utf-8')) for path in args.runs]

    run_times = _collect_wall_times(run_payloads)
    baseline_times = {
        str(name): float(stats.get('median_wall_time_s', 0.0))
        for name, stats in (baseline.get('scenarios') or {}).items()
    }

    threshold = float(args.max_median_regression_pct)
    min_regression_s = max(0.0, float(args.min_median_regression_s))
    rows: list[dict] = []
    failures: list[str] = []
    stage_metric_specs = list(args.stage_metrics or [])
    if args.export_stage_metrics:
        stage_metric_specs.extend(EXPORT_STAGE_METRICS)
    stage_metrics = _parse_stage_metric_specs(stage_metric_specs)

    scenario_names = sorted(set(run_times.keys()) | set(baseline_times.keys()))
    if args.scenarios:
        requested = {name.strip() for name in args.scenarios if str(name).strip()}
        scenario_names = [name for name in scenario_names if name in requested]

    for scenario_name in scenario_names:
        observed_median = _median(run_times.get(scenario_name, []))
        baseline_median = float(baseline_times.get(scenario_name, 0.0))
        if baseline_median <= 0:
            regression_pct = 0.0
            regression_s = 0.0
            status = 'missing_baseline'
        else:
            regression_s = observed_median - baseline_median
            regression_pct = ((observed_median - baseline_median) / baseline_median) * 100.0
            exceeds_pct = regression_pct > threshold
            exceeds_abs = regression_s > min_regression_s
            status = 'fail' if (exceeds_pct and exceeds_abs) else 'pass'
            if status == 'fail':
                failures.append(scenario_name)
        rows.append(
            {
                'scenario': scenario_name,
                'baseline_median_wall_time_s': baseline_median,
                'observed_median_wall_time_s': observed_median,
                'median_regression_s': regression_s,
                'median_regression_pct': regression_pct,
                'status': status,
            }
        )

    stage_times = _collect_stage_times(run_payloads, stage_metrics)
    stage_rows = [
        {
            'scenario': scenario_name,
            'stage': stage_key,
            'observed_median_s': _median(values),
            'sample_count': len(values),
            'status': 'observed' if values else 'missing',
        }
        for (scenario_name, stage_key), values in stage_times.items()
    ]

    report = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'max_median_regression_pct': threshold,
        'min_median_regression_s': min_regression_s,
        'baseline_path': args.baseline,
        'run_files': args.runs,
        'results': rows,
        'stage_metric_results': stage_rows,
        'failed_scenarios': failures,
    }

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding='utf-8')

    for row in rows:
        print(
            f"scenario={row['scenario']} status={row['status']} "
            f"baseline={row['baseline_median_wall_time_s']:.6f}s observed={row['observed_median_wall_time_s']:.6f}s "
            f"regression_s={row['median_regression_s']:.6f}s "
            f"regression_pct={row['median_regression_pct']:.2f}"
        )
    for row in stage_rows:
        print(
            f"stage_metric scenario={row['scenario']} stage={row['stage']} status={row['status']} "
            f"observed_median={row['observed_median_s']:.6f}s samples={row['sample_count']}"
        )

    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
