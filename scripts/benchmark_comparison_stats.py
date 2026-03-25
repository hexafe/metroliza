#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np

from modules.comparison_stats import ComparisonStatsConfig, compute_metric_pairwise_stats
from modules.comparison_stats_native import native_backend_available


def _build_fixture(*, group_count: int, samples_per_group: int, seed: int) -> dict[str, list[float]]:
    rng = np.random.default_rng(seed)
    fixture: dict[str, list[float]] = {}
    for idx in range(group_count):
        fixture[f'G{idx:02d}'] = rng.normal(loc=10.0 + (idx * 0.03), scale=0.4 + (idx % 3) * 0.05, size=samples_per_group).astype(float).tolist()
    return fixture


def _run_ci_path(grouped_values: dict[str, list[float]], *, iterations: int, ci_level: float) -> float:
    start = time.perf_counter()
    compute_metric_pairwise_stats(
        'METRIC_CI',
        grouped_values,
        config=ComparisonStatsConfig(
            include_effect_size_ci=True,
            ci_level=ci_level,
            ci_bootstrap_iterations=iterations,
            correction_method='holm',
        ),
    )
    return time.perf_counter() - start


def _run_pairwise_path(grouped_values: dict[str, list[float]]) -> float:
    start = time.perf_counter()
    compute_metric_pairwise_stats(
        'METRIC_PAIRWISE',
        grouped_values,
        config=ComparisonStatsConfig(
            include_effect_size_ci=False,
            correction_method='holm',
        ),
    )
    return time.perf_counter() - start


def main() -> int:
    parser = argparse.ArgumentParser(description='Benchmark comparison-stats CI and pairwise execution paths.')
    parser.add_argument('--groups', type=int, default=8)
    parser.add_argument('--samples', type=int, default=160)
    parser.add_argument('--seed', type=int, default=2026)
    parser.add_argument('--ci-iterations', type=int, default=600)
    parser.add_argument('--ci-level', type=float, default=0.95)
    parser.add_argument('--output-json', help='Optional path to write machine-readable benchmark output JSON.')
    args = parser.parse_args()

    grouped_values = _build_fixture(group_count=max(2, args.groups), samples_per_group=max(2, args.samples), seed=args.seed)
    row_count = sum(len(v) for v in grouped_values.values())

    os.environ['METROLIZA_COMPARISON_STATS_CI_BACKEND'] = 'python'
    ci_python = _run_ci_path(grouped_values, iterations=max(1, args.ci_iterations), ci_level=args.ci_level)

    ci_native = 0.0
    ci_backend = 'python'
    if native_backend_available():
        os.environ['METROLIZA_COMPARISON_STATS_CI_BACKEND'] = 'native'
        ci_native = _run_ci_path(grouped_values, iterations=max(1, args.ci_iterations), ci_level=args.ci_level)
        ci_backend = 'native'

    os.environ['METROLIZA_COMPARISON_STATS_BACKEND'] = 'python'
    pairwise_python = _run_pairwise_path(grouped_values)

    pairwise_native = 0.0
    pairwise_backend = 'python'
    if native_backend_available():
        os.environ['METROLIZA_COMPARISON_STATS_BACKEND'] = 'native'
        pairwise_native = _run_pairwise_path(grouped_values)
        pairwise_backend = 'native'

    payload = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'config': {
            'groups': int(args.groups),
            'samples': int(args.samples),
            'seed': int(args.seed),
            'ci_iterations': int(args.ci_iterations),
            'ci_level': float(args.ci_level),
        },
        'results': [
            {
                'scenario': 'comparison_stats_ci_flow',
                'wall_time_s': float(ci_python + ci_native),
                'stage_timings_s': {
                    'python_ci_seconds': float(ci_python),
                    'native_ci_seconds': float(ci_native),
                    'native_ci_speedup_ratio': float((ci_python / ci_native) if ci_native > 0 else 0.0),
                },
                'input_metrics': {
                    'rows': int(row_count),
                    'headers': int(args.groups),
                    'chart_count': 0,
                    'native_available': int(native_backend_available()),
                    'ci_backend_used': ci_backend,
                },
            },
            {
                'scenario': 'comparison_stats_pairwise_flow',
                'wall_time_s': float(pairwise_python + pairwise_native),
                'stage_timings_s': {
                    'python_pairwise_seconds': float(pairwise_python),
                    'native_pairwise_seconds': float(pairwise_native),
                    'native_pairwise_speedup_ratio': float((pairwise_python / pairwise_native) if pairwise_native > 0 else 0.0),
                },
                'input_metrics': {
                    'rows': int(row_count),
                    'headers': int(args.groups),
                    'chart_count': 0,
                    'native_available': int(native_backend_available()),
                    'pairwise_backend_used': pairwise_backend,
                },
            },
        ],
    }

    print(f'comparison_stats_ci_python_seconds={ci_python:.6f}')
    if ci_native > 0:
        print(f'comparison_stats_ci_native_seconds={ci_native:.6f}')
    print(f'comparison_stats_pairwise_python_seconds={pairwise_python:.6f}')
    if pairwise_native > 0:
        print(f'comparison_stats_pairwise_native_seconds={pairwise_native:.6f}')

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        print(f'json_output={output_path}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
