# Performance Baseline (Canonical Scenarios)

This document defines canonical benchmark scenarios and pass/fail policy for CI performance trend monitoring.

## Policy Summary

- **Warmup:** run each benchmark script once and discard results.
- **Measured runs:** run each benchmark script **3** times after warmup.
- **Statistic used for regression gate:** median wall time (`wall_time_s`) per scenario across measured runs.
- **Regression threshold:** fail a scenario if median wall time regresses by **more than 10%** vs `docs/perf_baseline_snapshot.json`.
- **Current CI status:** benchmark trend job is intentionally **non-blocking** (`continue-on-error: true`) during rollout.

## Canonical Scenarios

## 1) CMM parse path (`scripts/benchmark_paths.py`)

- Scenario key: `pdf_parse_path`
- Purpose: end-to-end report discovery + parse loop path.
- Fixture sizes:
  - `--pdf-count 20`
- Bench config (shared run):
  - `--report-count 40`
  - `--headers-per-report 6`
  - `--csv-rows 300`
  - `--csv-columns 4`
  - `--fit-group-count 12`
  - `--fit-sample-size 90`
  - `--fit-monte-carlo-samples 40`
  - `--group-preprocess-groups 10`
  - `--group-preprocess-values 1500`
  - `--cmm-bench-report-count 120`
  - `--cmm-bench-measurements-per-report 120`
- Expected telemetry in output:
  - `parse_python_backend_rate`, `parse_native_backend_rate`
  - `persistence_python_backend_rate`, `persistence_native_backend_rate`

### CMM native parser guardrail baselines

For CI quality-gate enforcement on `cmm_parser_backend_compare`:

- `--cmm-native-min-speedup-ratio 1.00`
- `--cmm-native-min-usage-rate 0.95`
- trend median regression threshold: `12%` for the dedicated `cmm-parser-perf-gate` CI job
- trend absolute regression floor: `0.050s` for the dedicated `cmm-parser-perf-gate` CI job

These values are pinned in CI and should only change with a dedicated baseline-governance PR that includes fresh trend evidence and explicit threshold-change justification.

## 2) Distribution fit batch path (`scripts/benchmark_distribution_fit_batch.py`)

- Scenario key: `distribution_fit_batch_compare`
- Purpose: legacy per-group distribution-fit vs batch ndarray flow parity/performance.
- Fixture sizes:
  - `--metrics 40`
  - `--groups 6`
  - `--samples 120`
- Required parity check:
  - `parity_mismatches` must remain `0`.

## 3) Comparison-stats CI and pairwise flows

Sources:
- `modules/comparison_stats.py`
- `modules/comparison_stats_native.py`
- benchmark driver: `scripts/benchmark_comparison_stats.py`

Canonical scenario keys:
- `comparison_stats_ci_flow`
- `comparison_stats_pairwise_flow`

Fixture sizes:
- `--groups 8`
- `--samples 160`
- `--ci-iterations 600`

Notes:
- CI flow enables effect-size bootstrap CI path.
- Pairwise flow benchmarks assumption-driven pairwise rows and multiplicity correction path.
- Native timings are recorded when native backend is available; otherwise Python-only metrics are still emitted.

## Baseline Snapshot

Checked-in baseline medians are stored in:
- `docs/perf_baseline_snapshot.json`

Baseline provenance:
- The snapshot should be captured from canonical runs on the same CI runner class (`ubuntu-latest`) used by the trend job to avoid host-to-host skew.

Update process:
1. Run canonical warmup + measured benchmark sequence on CI runner class (`ubuntu-latest`) using the same scenario args enforced in CI.
2. Validate parity and stability, and preserve CMM guardrail checks (`--cmm-native-min-usage-rate 0.95`, trend thresholds unchanged).
3. Capture evidence from measured runs: per-run `benchmark-paths.json`, `trend-report.json`, and a PR summary table of old/new medians with percent + absolute deltas.
4. If changing any threshold (for example, `--cmm-native-min-speedup-ratio`), include explicit rationale for why the previous threshold is no longer appropriate and why the new threshold is safe.
5. Update baseline medians in `docs/perf_baseline_snapshot.json` in the same dedicated governance PR as any threshold changes.
