#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _collect_observed_metrics(benchmark_dir: Path) -> dict[str, float]:
    observed: dict[str, float] = {}
    for raw_path in benchmark_dir.glob('*.json'):
        payload = _load_json(raw_path)
        if payload.get('benchmark') == 'distribution_fit_batch':
            scenario = payload.get('scenario', {})
            observed['distribution_fit_batch_path'] = float(scenario.get('run_metrics', {}).get('batch_median_seconds', 0.0))
        elif payload.get('benchmark') == 'comparison_stats':
            for scenario in payload.get('scenarios', []):
                observed[str(scenario.get('scenario'))] = float(scenario.get('median_wall_time_s', 0.0))
        elif 'results' in payload:
            for result in payload.get('results', []):
                key = str(result.get('scenario'))
                observed[key] = float(result.get('wall_time_s', 0.0))
    return observed


def main() -> int:
    parser = argparse.ArgumentParser(description='Compare benchmark medians against checked-in baseline snapshot.')
    parser.add_argument('--baseline', required=True, help='Path to checked-in baseline JSON snapshot.')
    parser.add_argument('--benchmark-dir', required=True, help='Directory containing benchmark JSON outputs.')
    parser.add_argument('--max-regression-pct', type=float, default=10.0)
    parser.add_argument('--output-report', default='benchmark_results/perf-trend-report.json')
    args = parser.parse_args()

    baseline = _load_json(Path(args.baseline)).get('scenarios', {})
    observed = _collect_observed_metrics(Path(args.benchmark_dir))
    threshold = float(args.max_regression_pct)

    report = {
        'baseline_path': args.baseline,
        'benchmark_dir': args.benchmark_dir,
        'max_regression_pct': threshold,
        'regressions': [],
        'missing_in_observed': [],
        'missing_in_baseline': [],
    }

    for scenario, baseline_value in baseline.items():
        if scenario not in observed:
            report['missing_in_observed'].append(scenario)
            continue
        current = observed[scenario]
        if baseline_value <= 0:
            continue
        delta_pct = ((current - baseline_value) / baseline_value) * 100.0
        if delta_pct > threshold:
            report['regressions'].append(
                {
                    'scenario': scenario,
                    'baseline': baseline_value,
                    'current': current,
                    'delta_pct': delta_pct,
                }
            )

    for scenario in observed:
        if scenario not in baseline:
            report['missing_in_baseline'].append(scenario)

    out_path = Path(args.output_report)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding='utf-8')

    print(f'Perf trend report: {out_path}')
    print(f"Observed scenarios={len(observed)}, baseline scenarios={len(baseline)}")
    print(f"Regressions={len(report['regressions'])}")

    if report['regressions']:
        for item in report['regressions']:
            print(
                f"REGRESSION {item['scenario']}: baseline={item['baseline']:.4f}s, "
                f"current={item['current']:.4f}s, delta={item['delta_pct']:.2f}%"
            )
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
