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

from modules.distribution_fit_service import (  # noqa: E402
    fit_measurement_distribution,
    fit_measurement_distribution_batch,
    measurement_fingerprint,
)


def _build_fixture(metric_count: int, group_count: int, samples_per_group: int, seed: int):
    rng = np.random.default_rng(seed)
    fixture: dict[str, dict[str, np.ndarray]] = {}
    for metric_idx in range(metric_count):
        metric = f"M{metric_idx:03d}"
        groups: dict[str, np.ndarray] = {}
        for group_idx in range(group_count):
            loc = 10.0 + metric_idx * 0.02 + group_idx * 0.05
            scale = 0.8 + (group_idx % 3) * 0.15
            values = np.ascontiguousarray(rng.normal(loc=loc, scale=scale, size=samples_per_group).astype(float))
            groups[f"G{group_idx:03d}"] = values
        fixture[metric] = groups
    return fixture


def _run_legacy_per_group(fixture, *, include_kde_reference=False):
    start = time.perf_counter()
    results = {}
    for metric, grouped_values in fixture.items():
        metric_result = {}
        for group_name, values in grouped_values.items():
            metric_result[group_name] = fit_measurement_distribution(
                values.tolist(),
                include_kde_reference=include_kde_reference,
            )
        results[metric] = metric_result
    return time.perf_counter() - start, results


def _run_batch(fixture, *, include_kde_reference=False):
    start = time.perf_counter()
    results = {}
    memo = {}
    for metric, grouped_values in fixture.items():
        fingerprints = {group: measurement_fingerprint(values) for group, values in grouped_values.items()}
        results[metric] = fit_measurement_distribution_batch(
            grouped_values,
            include_kde_reference=include_kde_reference,
            memoization_cache=memo,
            fingerprints_by_group=fingerprints,
        )
    return time.perf_counter() - start, results


def _validate_parity(baseline, candidate):
    mismatches = []
    for metric, grouped in baseline.items():
        for group, row in grouped.items():
            compare = candidate[metric][group]
            left_model = (row.get('selected_model') or {}).get('name')
            right_model = (compare.get('selected_model') or {}).get('name')
            if left_model != right_model:
                mismatches.append((metric, group, 'selected_model', left_model, right_model))
            left_risk = (row.get('risk_estimates') or {}).get('outside_probability')
            right_risk = (compare.get('risk_estimates') or {}).get('outside_probability')
            if left_risk is None and right_risk is None:
                continue
            if left_risk is None or right_risk is None or abs(float(left_risk) - float(right_risk)) > 1e-9:
                mismatches.append((metric, group, 'outside_probability', left_risk, right_risk))
    return mismatches


def _build_summary(*, fixture: dict[str, dict[str, np.ndarray]], legacy_runs: list[float], batch_runs: list[float], mismatches: list[tuple[Any, ...]], args: argparse.Namespace) -> dict[str, Any]:
    legacy_median = statistics.median(legacy_runs)
    batch_median = statistics.median(batch_runs)
    speedup = legacy_median / batch_median if batch_median > 0 else float('inf')
    return {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'benchmark': 'distribution_fit_batch',
        'config': {
            'metrics': args.metrics,
            'groups': args.groups,
            'samples': args.samples,
            'seed': args.seed,
            'warmup_runs': args.warmup_runs,
            'measured_runs': args.runs,
        },
        'scenario': {
            'scenario': 'distribution_fit_batch_path',
            'input_metrics': {
                'metrics': args.metrics,
                'groups': args.groups,
                'samples_per_group': args.samples,
                'cells': args.metrics * args.groups * args.samples,
            },
            'run_metrics': {
                'legacy_seconds': legacy_runs,
                'batch_seconds': batch_runs,
                'legacy_median_seconds': legacy_median,
                'batch_median_seconds': batch_median,
                'speedup_x_median': speedup,
            },
            'parity_mismatches': len(mismatches),
            'parity_ok': len(mismatches) == 0,
        },
        'fixture_metrics': {
            'metric_count': len(fixture),
            'group_count': len(next(iter(fixture.values()))) if fixture else 0,
        },
    }


def _write_output(output_dir: Path, payload: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    path = output_dir / f'distribution-fit-benchmark-{stamp}.json'
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    return path


def main():
    parser = argparse.ArgumentParser(description='Benchmark distribution-fit legacy per-group path vs batch ndarray path.')
    parser.add_argument('--metrics', type=int, default=40)
    parser.add_argument('--groups', type=int, default=6)
    parser.add_argument('--samples', type=int, default=120)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--warmup-runs', type=int, default=1)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--output-dir', default='benchmark_results', help='Directory for machine-readable benchmark outputs.')
    args = parser.parse_args()

    fixture = _build_fixture(args.metrics, args.groups, args.samples, args.seed)

    for _ in range(max(0, args.warmup_runs)):
        _run_legacy_per_group(fixture)
        _run_batch(fixture)

    legacy_runs: list[float] = []
    batch_runs: list[float] = []
    legacy_results = {}
    batch_results = {}
    for _ in range(max(1, args.runs)):
        legacy_seconds, legacy_results = _run_legacy_per_group(fixture)
        batch_seconds, batch_results = _run_batch(fixture)
        legacy_runs.append(legacy_seconds)
        batch_runs.append(batch_seconds)

    mismatches = _validate_parity(legacy_results, batch_results)
    payload = _build_summary(
        fixture=fixture,
        legacy_runs=legacy_runs,
        batch_runs=batch_runs,
        mismatches=mismatches,
        args=args,
    )
    output_path = _write_output(Path(args.output_dir), payload)

    print(f"metrics={args.metrics}, groups={args.groups}, samples={args.samples}")
    print(f"legacy_median_seconds={payload['scenario']['run_metrics']['legacy_median_seconds']:.4f}")
    print(f"batch_median_seconds={payload['scenario']['run_metrics']['batch_median_seconds']:.4f}")
    print(f"speedup_x_median={payload['scenario']['run_metrics']['speedup_x_median']:.2f}")
    print(f"parity_mismatches={len(mismatches)}")
    print(f"Benchmark JSON: {output_path}")
    if mismatches:
        first = mismatches[0]
        print(f"first_mismatch={first}")
        raise SystemExit(1)


if __name__ == '__main__':
    main()
