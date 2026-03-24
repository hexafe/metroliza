# Performance Baseline (Canonical Scenarios)

This document defines the canonical performance scenarios, fixture sizing, run policy, and regression thresholds used by CI benchmark-trending.

## Global benchmark policy

- **Fixture determinism:** fixed synthetic fixtures + fixed random seeds.
- **Warmup policy:** `1` warmup run before measurements.
- **Measured run count:** `5` runs.
- **Primary comparison metric:** **median wall time** across measured runs.
- **Regression threshold:** fail trend check when median wall time regresses by **more than 10%** vs checked-in baseline snapshot.
- **Initial CI mode:** non-blocking (`continue-on-error: true`) while baselines stabilize.

## Canonical scenarios

## 1) CMM parse path (`scripts/benchmark_paths.py`)

### Scenario ID
- `pdf_parse_path`

### Fixture
- `--pdf-count 80`
- Synthetic PDF file names and placeholders.

### Measured scope
- report discovery
- existing fingerprint lookup
- parse loop
- backend telemetry snapshot (parse/persistence native-vs-python rates + totals)

### Target metric / threshold
- Compare `wall_time_s` median against baseline snapshot.
- Pass if regression is `<= 10%`.

## 2) Distribution fit batch path (`scripts/benchmark_distribution_fit_batch.py`)

### Scenario ID
- `distribution_fit_batch_path`

### Fixture
- `--metrics 40`
- `--groups 6`
- `--samples 120`
- `--seed 42`

### Measured scope
- Legacy per-group fit wall time
- Batch fit wall time
- parity mismatch count

### Target metric / threshold
- Baseline-trend comparison uses **batch median** (`batch_median_seconds`).
- Pass if regression is `<= 10%`.
- Hard fail benchmark run if parity mismatches are present.

## 3) Comparison-stats flows (`modules/comparison_stats.py` + `modules/comparison_stats_native.py`)

Benchmarked with `scripts/benchmark_comparison_stats.py`.

### Scenario IDs
- `comparison_stats_ci_python`
- `comparison_stats_ci_native`
- `comparison_stats_pairwise_python`
- `comparison_stats_pairwise_native`

### Fixture
- `--metrics 24`
- `--groups 4`
- `--samples 120`
- `--ci-bootstrap-iterations 500`
- `--seed 123`

### Measured scope
- CI/bootstrap flow with effect-size CIs enabled
- Pairwise flow with effect-size CIs disabled
- Python and native forced backend modes

### Target metric / threshold
- Compare each scenario median against baseline snapshot.
- Pass if each regression is `<= 10%`.

## CI artifacts and trend comparison

CI benchmark job writes JSON benchmark outputs and a trend report under `benchmark_results/` and uploads them as workflow artifacts.

- Checked-in baseline snapshot: `benchmarks/perf_baseline_snapshot.json`
- Trend comparator: `scripts/benchmark_compare_to_baseline.py`

The trend report includes:
- scenario regressions above threshold,
- scenarios missing from observed output,
- scenarios present in observed output but missing from baseline.
