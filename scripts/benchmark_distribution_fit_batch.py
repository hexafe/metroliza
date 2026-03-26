#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.distribution_fit_service import (  # noqa: E402
    _coerce_measurements_array,
    fit_measurement_distribution,
    fit_measurement_distribution_batch,
    measurement_fingerprint,
)
from modules.distribution_fit_native import (  # noqa: E402
    native_backend_available,
    native_monte_carlo_backend_available,
    estimate_ad_pvalue_monte_carlo_native,
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


def _run_batch(fixture, *, include_kde_reference=False, candidate_kernel_mode=None):
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
            candidate_kernel_mode=candidate_kernel_mode,
        )
    return time.perf_counter() - start, results


def _run_marshaling_benchmark(*, groups: int, samples: int, repeats: int, seed: int) -> dict[str, float]:
    rng = np.random.default_rng(seed)
    list_groups = [rng.normal(loc=i * 0.05, scale=1.0, size=samples).astype(float).tolist() for i in range(groups)]
    ndarray_groups = [np.ascontiguousarray(np.asarray(group, dtype=np.float64)) for group in list_groups]

    start = time.perf_counter()
    for _ in range(max(1, repeats)):
        for values in list_groups:
            _coerce_measurements_array(values)
    list_seconds = time.perf_counter() - start

    start = time.perf_counter()
    for _ in range(max(1, repeats)):
        for values in ndarray_groups:
            _coerce_measurements_array(values)
    ndarray_seconds = time.perf_counter() - start

    return {
        'list_input_seconds': float(list_seconds),
        'ndarray_input_seconds': float(ndarray_seconds),
        'ndarray_vs_list_speedup_ratio': float((list_seconds / ndarray_seconds) if ndarray_seconds > 0 else 0.0),
    }


def _validate_parity(baseline, candidate, *, full_ranking=False):
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
            if full_ranking:
                left_rank = row.get('ranking_metrics') or []
                right_rank = compare.get('ranking_metrics') or []
                if len(left_rank) != len(right_rank):
                    mismatches.append((metric, group, 'ranking_length', len(left_rank), len(right_rank)))
                    continue
                for idx, (left_item, right_item) in enumerate(zip(left_rank, right_rank, strict=False)):
                    for key in ('model', 'rank'):
                        if left_item.get(key) != right_item.get(key):
                            mismatches.append((metric, group, f'ranking_{idx}_{key}', left_item.get(key), right_item.get(key)))
                    for key in ('nll', 'aic', 'bic', 'ad_statistic', 'ks_statistic'):
                        lv = left_item.get(key)
                        rv = right_item.get(key)
                        if lv is None and rv is None:
                            continue
                        if lv is None or rv is None or abs(float(lv) - float(rv)) > 1e-9:
                            mismatches.append((metric, group, f'ranking_{idx}_{key}', lv, rv))
    return mismatches


def _run_native_monte_carlo_once(*, iterations: int, sample_size: int, seed: int, reps: int) -> float:
    start = time.perf_counter()
    for _ in range(reps):
        result = estimate_ad_pvalue_monte_carlo_native(
            distribution='norm',
            fitted_params=(0.0, 1.0),
            sample_size=sample_size,
            observed_stat=0.65,
            iterations=iterations,
            seed=seed,
        )
        if result is None:
            raise RuntimeError('Native backend unavailable in worker process.')
    return time.perf_counter() - start


def _native_monte_carlo_throughput(*, iterations: int, reps: int, elapsed_seconds: float) -> float:
    if elapsed_seconds <= 0:
        return 0.0
    total_iterations = max(0, int(iterations)) * max(0, int(reps))
    return total_iterations / elapsed_seconds


def _run_native_mode_subprocess(*, mode: str, args) -> float:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        '--native-monte-carlo-mode',
        mode,
        '--native-iterations',
        str(args.native_iterations),
        '--native-sample-size',
        str(args.native_sample_size),
        '--native-seed',
        str(args.native_seed),
        '--native-repetitions',
        str(args.native_repetitions),
    ]
    env = dict(os.environ)
    if mode == 'single':
        env['RAYON_NUM_THREADS'] = '1'

    completed = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
    return float(completed.stdout.strip())


def _run_native_monte_carlo_scaling_benchmark(args) -> int:
    if not native_monte_carlo_backend_available():
        print('native backend unavailable; skipping native single-thread vs parallel benchmark')
        return 0

    single_seconds = _run_native_mode_subprocess(mode='single', args=args)
    parallel_seconds = _run_native_mode_subprocess(mode='parallel', args=args)
    speedup = single_seconds / parallel_seconds if parallel_seconds > 0 else float('inf')
    single_throughput = _native_monte_carlo_throughput(
        iterations=args.native_iterations,
        reps=args.native_repetitions,
        elapsed_seconds=single_seconds,
    )
    parallel_throughput = _native_monte_carlo_throughput(
        iterations=args.native_iterations,
        reps=args.native_repetitions,
        elapsed_seconds=parallel_seconds,
    )

    print('native_monte_carlo_scaling_benchmark')
    print(f'native_iterations={args.native_iterations}, sample_size={args.native_sample_size}, repetitions={args.native_repetitions}')
    print(f'single_thread_seconds={single_seconds:.4f}')
    print(f'single_thread_iterations_per_second={single_throughput:.2f}')
    print(f'parallel_seconds={parallel_seconds:.4f}')
    print(f'parallel_iterations_per_second={parallel_throughput:.2f}')
    print(f'parallel_speedup_x={speedup:.2f}')
    print('expected_speedup_band_x=1.3-4.0 (compute-bound; lower on small iteration counts, higher on multi-core hosts)')
    return 0


def main():
    parser = argparse.ArgumentParser(description='Benchmark distribution-fit legacy per-group path vs batch ndarray path.')
    parser.add_argument('--metrics', type=int, default=40)
    parser.add_argument('--groups', type=int, default=6)
    parser.add_argument('--samples', type=int, default=120)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--native-scaling', action='store_true', help='Benchmark native Monte Carlo single-thread vs parallel runtime.')
    parser.add_argument('--native-iterations', type=int, default=20000)
    parser.add_argument('--native-sample-size', type=int, default=64)
    parser.add_argument('--native-seed', type=int, default=123)
    parser.add_argument('--native-repetitions', type=int, default=3)
    parser.add_argument('--native-monte-carlo-mode', choices=['single', 'parallel'], help=argparse.SUPPRESS)
    parser.add_argument('--candidate-kernel-benchmark', action='store_true', help='Benchmark candidate metric kernel mode (python vs auto/native if available).')
    parser.add_argument('--batch-native-benchmark', action='store_true', help='Benchmark explicit batch-native dispatch path (python vs native).')
    parser.add_argument('--marshal-repeats', type=int, default=400, help='Repetitions for marshaling micro-benchmark.')
    parser.add_argument('--output-json', help='Optional path to write machine-readable benchmark output JSON.')
    args = parser.parse_args()

    if args.native_monte_carlo_mode:
        seconds = _run_native_monte_carlo_once(
            iterations=args.native_iterations,
            sample_size=args.native_sample_size,
            seed=args.native_seed,
            reps=args.native_repetitions,
        )
        print(f'{seconds:.10f}')
        return

    if args.native_scaling:
        raise SystemExit(_run_native_monte_carlo_scaling_benchmark(args))

    fixture = _build_fixture(args.metrics, args.groups, args.samples, args.seed)
    marshaling = _run_marshaling_benchmark(
        groups=max(1, args.groups),
        samples=max(2, args.samples),
        repeats=max(1, args.marshal_repeats),
        seed=args.seed + 19,
    )

    legacy_seconds, legacy_results = _run_legacy_per_group(fixture)
    batch_seconds, batch_results = _run_batch(fixture)
    mismatches = _validate_parity(legacy_results, batch_results)
    kernel_payload = None
    if args.candidate_kernel_benchmark:
        python_seconds, python_results = _run_batch(fixture, candidate_kernel_mode='python')
        mode = 'native' if native_backend_available() else 'auto'
        kernel_seconds, kernel_results = _run_batch(fixture, candidate_kernel_mode=mode)
        kernel_mismatches = _validate_parity(python_results, kernel_results, full_ranking=True)
        kernel_speedup = python_seconds / kernel_seconds if kernel_seconds > 0 else float('inf')
        kernel_payload = {
            'python_seconds': float(python_seconds),
            'kernel_seconds': float(kernel_seconds),
            'kernel_mode': mode,
            'kernel_speedup': float(kernel_speedup),
            'ranking_parity_mismatches': int(len(kernel_mismatches)),
        }
        print(f"candidate_kernel_mode={mode}")
        print(f"candidate_kernel_python_seconds={python_seconds:.4f}")
        print(f"candidate_kernel_seconds={kernel_seconds:.4f}")
        print(f"candidate_kernel_speedup_x={kernel_speedup:.2f}")
        print(f"candidate_kernel_ranking_parity_mismatches={len(kernel_mismatches)}")
        if kernel_mismatches:
            print(f"candidate_kernel_first_mismatch={kernel_mismatches[0]}")
            raise SystemExit(1)

    batch_native_payload = None
    if args.batch_native_benchmark:
        python_seconds, python_results = _run_batch(fixture, candidate_kernel_mode='python')
        native_mode = 'native' if native_backend_available() else 'auto'
        native_seconds, native_results = _run_batch(fixture, candidate_kernel_mode=native_mode)
        native_mismatches = _validate_parity(python_results, native_results, full_ranking=True)
        native_speedup = python_seconds / native_seconds if native_seconds > 0 else float('inf')
        batch_native_payload = {
            'python_seconds': float(python_seconds),
            'native_seconds': float(native_seconds),
            'native_mode': native_mode,
            'native_speedup': float(native_speedup),
            'ranking_parity_mismatches': int(len(native_mismatches)),
        }
        print(f"batch_native_mode={native_mode}")
        print(f"batch_native_python_seconds={python_seconds:.4f}")
        print(f"batch_native_seconds={native_seconds:.4f}")
        print(f"batch_native_speedup_x={native_speedup:.2f}")
        print(f"batch_native_ranking_parity_mismatches={len(native_mismatches)}")
        if native_mismatches:
            print(f"batch_native_first_mismatch={native_mismatches[0]}")
            raise SystemExit(1)

    print(f"metrics={args.metrics}, groups={args.groups}, samples={args.samples}")
    print(f"legacy_seconds={legacy_seconds:.4f}")
    print(f"batch_seconds={batch_seconds:.4f}")
    speedup = legacy_seconds / batch_seconds if batch_seconds > 0 else float('inf')
    marshaling_seconds = float(marshaling['ndarray_input_seconds'])
    baseline_total_seconds = marshaling_seconds + float(batch_seconds)
    marshaling_share = (marshaling_seconds / baseline_total_seconds) if baseline_total_seconds > 0 else 0.0
    compute_share = (float(batch_seconds) / baseline_total_seconds) if baseline_total_seconds > 0 else 0.0
    print(f"speedup_x={speedup:.2f}")
    print(f"parity_mismatches={len(mismatches)}")
    print(f"marshaling_list_seconds={marshaling['list_input_seconds']:.4f}")
    print(f"marshaling_ndarray_seconds={marshaling['ndarray_input_seconds']:.4f}")
    print(f"marshaling_speedup_ratio={marshaling['ndarray_vs_list_speedup_ratio']:.2f}")
    print(f"marshaling_only_share={marshaling_share:.6f}")
    print(f"compute_share={compute_share:.6f}")

    payload = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'config': {
            'metrics': args.metrics,
            'groups': args.groups,
            'samples': args.samples,
            'seed': args.seed,
        },
        'results': [
            {
                'scenario': 'distribution_fit_batch_compare',
                'wall_time_s': float(legacy_seconds + batch_seconds),
                'stage_timings_s': {
                    'legacy_per_group': float(legacy_seconds),
                    'batch_path': float(batch_seconds),
                    'speedup_ratio': float(speedup),
                    'marshaling_list_seconds': float(marshaling['list_input_seconds']),
                    'marshaling_ndarray_seconds': float(marshaling['ndarray_input_seconds']),
                    'marshaling_speedup_ratio': float(marshaling['ndarray_vs_list_speedup_ratio']),
                    'marshaling_only_share': float(marshaling_share),
                    'compute_share': float(compute_share),
                },
                'input_metrics': {
                    'metrics': int(args.metrics),
                    'groups': int(args.groups),
                    'samples': int(args.samples),
                    'marshal_repeats': int(args.marshal_repeats),
                    'parity_mismatches': int(len(mismatches)),
                },
                'candidate_kernel': kernel_payload,
                'batch_native': batch_native_payload,
            }
        ],
    }
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        print(f'json_output={output_path}')

    if mismatches:
        first = mismatches[0]
        print(f"first_mismatch={first}")
        raise SystemExit(1)


if __name__ == '__main__':
    main()
