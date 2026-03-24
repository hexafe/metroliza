#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.comparison_stats import ComparisonStatsConfig, compute_metric_pairwise_stats  # noqa: E402
from modules.comparison_stats_native import native_backend_available  # noqa: E402


def _build_fixture(metric_count: int, group_count: int, samples_per_group: int, seed: int) -> dict[str, dict[str, list[float]]]:
    rng = np.random.default_rng(seed)
    fixture: dict[str, dict[str, list[float]]] = {}
    for metric_idx in range(metric_count):
        metric = f'M{metric_idx:03d}'
        groups: dict[str, list[float]] = {}
        for group_idx in range(group_count):
            loc = 25.0 + metric_idx * 0.05 + group_idx * 0.15
            scale = 0.55 + ((group_idx + metric_idx) % 3) * 0.08
            groups[f'G{group_idx + 1}'] = rng.normal(loc=loc, scale=scale, size=samples_per_group).astype(float).tolist()
        fixture[metric] = groups
    return fixture


def _run_bootstrap_ci_path(
    fixture: dict[str, dict[str, list[float]]],
    *,
    ci_iterations: int,
    force_backend: str,
) -> tuple[float, list[dict[str, Any]]]:
    import os

    backend = force_backend if force_backend != 'native' or native_backend_available() else 'python'
    os.environ['METROLIZA_COMPARISON_STATS_CI_BACKEND'] = backend

    config = ComparisonStatsConfig(
        include_effect_size_ci=True,
        ci_bootstrap_iterations=ci_iterations,
        correction_method='holm',
    )

    start = time.perf_counter()
    rows: list[dict[str, Any]] = []
    for metric, grouped_values in fixture.items():
        outcome = compute_metric_pairwise_stats(metric, grouped_values, config=config)
        rows.append({'metric': metric, 'pair_count': len(outcome)})
    return time.perf_counter() - start, rows


def _run_pairwise_path(fixture: dict[str, dict[str, list[float]]], *, force_backend: str) -> tuple[float, list[dict[str, Any]]]:
    import os

    backend = force_backend if force_backend != 'native' or native_backend_available() else 'python'
    os.environ['METROLIZA_COMPARISON_STATS_BACKEND'] = backend

    config = ComparisonStatsConfig(
        include_effect_size_ci=False,
        correction_method='holm',
    )
    start = time.perf_counter()
    rows: list[dict[str, Any]] = []
    for metric, grouped_values in fixture.items():
        outcome = compute_metric_pairwise_stats(metric, grouped_values, config=config)
        rows.append({'metric': metric, 'pair_count': len(outcome)})
    return time.perf_counter() - start, rows


def _execute_repeated(runs: int, fn):
    timings: list[float] = []
    sample_rows: list[dict[str, Any]] = []
    for _ in range(max(1, runs)):
        elapsed, sample_rows = fn()
        timings.append(elapsed)
    return timings, sample_rows


def _scenario_payload(name: str, timings: list[float], input_metrics: dict[str, int]) -> dict[str, Any]:
    return {
        'scenario': name,
        'timings_s': timings,
        'median_wall_time_s': statistics.median(timings),
        'input_metrics': input_metrics,
    }


def _write_output(output_dir: Path, payload: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    path = output_dir / f'comparison-stats-benchmark-{stamp}.json'
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description='Benchmark comparison-stats CI and pairwise flows.')
    parser.add_argument('--metrics', type=int, default=24)
    parser.add_argument('--groups', type=int, default=4)
    parser.add_argument('--samples', type=int, default=120)
    parser.add_argument('--ci-bootstrap-iterations', type=int, default=500)
    parser.add_argument('--seed', type=int, default=123)
    parser.add_argument('--warmup-runs', type=int, default=1)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--output-dir', default='benchmark_results', help='Directory for machine-readable benchmark outputs.')
    args = parser.parse_args()

    fixture = _build_fixture(args.metrics, args.groups, args.samples, args.seed)

    for _ in range(max(0, args.warmup_runs)):
        _run_bootstrap_ci_path(fixture, ci_iterations=args.ci_bootstrap_iterations, force_backend='python')
        _run_pairwise_path(fixture, force_backend='python')

    ci_python_timings, _ = _execute_repeated(
        args.runs,
        lambda: _run_bootstrap_ci_path(fixture, ci_iterations=args.ci_bootstrap_iterations, force_backend='python'),
    )
    ci_native_timings, _ = _execute_repeated(
        args.runs,
        lambda: _run_bootstrap_ci_path(fixture, ci_iterations=args.ci_bootstrap_iterations, force_backend='native'),
    )
    pair_python_timings, _ = _execute_repeated(args.runs, lambda: _run_pairwise_path(fixture, force_backend='python'))
    pair_native_timings, _ = _execute_repeated(args.runs, lambda: _run_pairwise_path(fixture, force_backend='native'))

    input_metrics = {
        'metrics': args.metrics,
        'groups': args.groups,
        'samples_per_group': args.samples,
        'total_cells': args.metrics * args.groups * args.samples,
        'ci_bootstrap_iterations': args.ci_bootstrap_iterations,
    }

    payload = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'benchmark': 'comparison_stats',
        'config': {
            'warmup_runs': args.warmup_runs,
            'measured_runs': args.runs,
            'native_backend_available': native_backend_available(),
        },
        'scenarios': [
            _scenario_payload('comparison_stats_ci_python', ci_python_timings, input_metrics),
            _scenario_payload('comparison_stats_ci_native', ci_native_timings, input_metrics),
            _scenario_payload('comparison_stats_pairwise_python', pair_python_timings, input_metrics),
            _scenario_payload('comparison_stats_pairwise_native', pair_native_timings, input_metrics),
        ],
    }

    out_path = _write_output(Path(args.output_dir), payload)
    print(f'Benchmark JSON: {out_path}')
    for scenario in payload['scenarios']:
        print(f"{scenario['scenario']}_median={scenario['median_wall_time_s']:.4f}s")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
