#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path


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
    args = parser.parse_args()

    baseline = json.loads(Path(args.baseline).read_text(encoding='utf-8'))
    run_payloads = [json.loads(Path(path).read_text(encoding='utf-8')) for path in args.runs]

    run_times = _collect_wall_times(run_payloads)
    baseline_times = {
        str(name): float(stats.get('median_wall_time_s', 0.0))
        for name, stats in (baseline.get('scenarios') or {}).items()
    }

    threshold = float(args.max_median_regression_pct)
    rows: list[dict] = []
    failures: list[str] = []

    for scenario_name in sorted(set(run_times.keys()) | set(baseline_times.keys())):
        observed_median = _median(run_times.get(scenario_name, []))
        baseline_median = float(baseline_times.get(scenario_name, 0.0))
        if baseline_median <= 0:
            regression_pct = 0.0
            status = 'missing_baseline'
        else:
            regression_pct = ((observed_median - baseline_median) / baseline_median) * 100.0
            status = 'pass' if regression_pct <= threshold else 'fail'
            if status == 'fail':
                failures.append(scenario_name)
        rows.append(
            {
                'scenario': scenario_name,
                'baseline_median_wall_time_s': baseline_median,
                'observed_median_wall_time_s': observed_median,
                'median_regression_pct': regression_pct,
                'status': status,
            }
        )

    report = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'max_median_regression_pct': threshold,
        'baseline_path': args.baseline,
        'run_files': args.runs,
        'results': rows,
        'failed_scenarios': failures,
    }

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding='utf-8')

    for row in rows:
        print(
            f"scenario={row['scenario']} status={row['status']} "
            f"baseline={row['baseline_median_wall_time_s']:.6f}s observed={row['observed_median_wall_time_s']:.6f}s "
            f"regression_pct={row['median_regression_pct']:.2f}"
        )

    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
