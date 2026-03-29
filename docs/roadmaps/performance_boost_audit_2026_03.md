# Performance Boost Audit (2026-03-28)

## Goal
Audit the `performance-boost` branch for measurable runtime bottlenecks, write an implementation plan anchored to benchmark evidence, and land the highest-value fixes immediately.

## Audit method
- Reused the existing benchmark harnesses in `scripts/benchmark_paths.py`, `scripts/benchmark_comparison_stats.py`, and `scripts/benchmark_distribution_fit_batch.py`.
- Used focused `cProfile` runs to avoid optimizing the wrong layer.
- Prioritized Python-path regressions and dominant hot loops that were still active in this checkout.

## Measured bottlenecks

### 1. Comparison-stats CI fallback was dominated by Python bootstrap loops
Command:

```bash
PYTHONPATH=. python -m scripts.benchmark_comparison_stats --groups 8 --samples 160 --ci-iterations 600
```

Before this pass:
- `comparison_stats_ci_python_seconds=1.574677`
- `comparison_stats_pairwise_python_seconds=0.032869`

After this pass:
- `comparison_stats_ci_python_seconds=0.138546`
- `comparison_stats_pairwise_python_seconds=0.031322`

Interpretation:
- The pairwise hypothesis-test path was already acceptable.
- The real cost was bootstrap effect-size confidence intervals in the Python fallback.
- `cProfile` showed `_bootstrap_ci(...)`, `_cohen_d(...)`, and `_eta_or_omega_squared(...)` dominating the CI path.

Root cause:
- The Python fallback recalculated effect sizes in a Python loop for every bootstrap replicate.

Fix landed:
- Added vectorized percentile-CI fallbacks for `cohen_d`, `eta_squared`, and `omega_squared` in [`modules/comparison_stats.py`](../../modules/comparison_stats.py).

Impact:
- About `11.4x` faster on the benchmarked CI scenario without changing public behavior.

### 2. Distribution-fit batch mode was doing wasted precompute work without native batch metrics
Command:

```bash
PYTHONPATH=. python -m scripts.benchmark_distribution_fit_batch --metrics 20 --groups 4 --samples 80
```

Before this pass:
- `legacy_seconds=5.5214`
- `batch_seconds=9.6837`
- `speedup_x=0.57`
- `parity_mismatches=0`

After the first batch fix in this pass:
- `legacy_seconds=5.1822`
- `batch_seconds=5.1128`
- `speedup_x=1.01`
- `parity_mismatches=0`

After the second pass in this branch:
- `legacy_seconds=2.4257`
- `batch_seconds=2.0717`
- `speedup_x=1.17`
- `parity_mismatches=0`

Focused single-metric spot check before:
- `batch_auto=0.5399`
- `batch_python=0.2751`
- `legacy=0.2910`

Focused single-metric spot check after:
- `batch_auto=0.2961`
- `batch_python=0.2956`
- `legacy=0.2907`

Interpretation:
- The batch API was not inherently slow.
- `auto` mode was slow because it still entered the batch precompute path even when native batch metrics were unavailable.
- After removing that regression, the remaining dominant waste on the benchmark fixture was unnecessary `johnsonsu` fitting on near-normal bilateral samples.

Root cause:
- `_fit_candidates_batch_native(...)` was calling the batch-fit bridge in a configuration where native batch metrics could not be produced, so the precompute work was discarded and the normal per-group path still ran afterward.
- Bilateral fitting always evaluated `johnsonsu`, even on large near-normal samples where the benchmark fixture almost always selected `norm` and only rarely selected `skewnorm`.

Fix landed:
- Skip batch candidate precompute when native batch metrics are unavailable in [`modules/distribution_fit_service.py`](../../modules/distribution_fit_service.py).
- Added adaptive bilateral candidate pruning so near-normal samples skip `johnsonsu` while heavy-tail/skewed samples still keep it in the candidate pool in [`modules/distribution_fit_service.py`](../../modules/distribution_fit_service.py).
- Added regression coverage in [`tests/test_distribution_fit_service.py`](../../tests/test_distribution_fit_service.py).

Impact:
- Removed the `auto`-mode regression, restored batch mode to parity, and then pushed it beyond parity in this no-native environment.

Additional evidence:

```bash
PYTHONPATH=. python - <<'PY'
from scripts.benchmark_paths import benchmark_distribution_fit_monte_carlo_path
from pathlib import Path
print(benchmark_distribution_fit_monte_carlo_path(Path('/tmp'), group_count=12, sample_size=90, monte_carlo_samples=40))
PY
```

- Earlier in this audit: `wall_time_s=2.4106`
- After candidate pruning: `wall_time_s=0.8966`

Interpretation:
- The improvement is not limited to the batch benchmark; it also helps chart/export flows that invoke distribution fitting on similarly near-normal grouped samples.

### 2b. Distribution-fit parameter estimation is now native-backed for the full current candidate pool
Command:

```bash
PYTHONPATH=/tmp/metroliza-distribution-fit-site:. python -m scripts.benchmark_distribution_fit_batch --metrics 20 --groups 4 --samples 80 --batch-native-benchmark
```

Measured after landing the native fit batch backend:
- `batch_native_mode=native`
- `batch_native_legacy_seconds=1.7663`
- `batch_native_seconds=0.1823`
- `batch_native_speedup_x=9.69`
- `batch_native_ranking_parity_mismatches=0`
- Overall batch result on the same extension-backed run:
  - `legacy_seconds=1.7663`
  - `batch_seconds=0.2827`
  - `speedup_x=6.25`
  - `parity_mismatches=0`

Interpretation:
- The biggest remaining distribution-fit bottleneck in the earlier audit was SciPy parameter estimation.
- That bottleneck is now materially reduced across the full current candidate pool, including the previously-unaccelerated `foldnorm` and `johnsonsu` paths.
- Native fit ranking parity is exact at the model/rank level; numeric metric drift remains small but tolerance-based for `skewnorm` and `johnsonsu`, and it does not change model selection on the audited fixtures.

Fix landed:
- Added native batch fit-parameter estimation for `norm`, `skewnorm`, `halfnorm`, `foldnorm`, `gamma`, `weibull_min`, `lognorm`, and `johnsonsu` in [`modules/native/distribution_fit_ad/src/lib.rs`](../../modules/native/distribution_fit_ad/src/lib.rs).
- Wired the Python bridge to expose `compute_candidate_fit_params_batch(...)` and merge unresolved candidates back through Python fallback in [`modules/distribution_fit_candidate_native.py`](../../modules/distribution_fit_candidate_native.py).
- Added parity coverage for mixed native/Python fit fallback in [`tests/test_distribution_fit_native_parity.py`](../../tests/test_distribution_fit_native_parity.py).

### 3. Group-stats mixed-type coercion had regressed below the legacy path
Command:

```bash
PYTHONPATH=. python -m scripts.benchmark_paths --scenarios group_preprocess_mixed_types_compare --group-preprocess-groups 10 --group-preprocess-values 1500
```

Before this pass:
- `legacy_coercion=0.002511`
- `optimized_coercion=0.003101`
- `speedup_ratio=0.81`

After this pass:
- `legacy_coercion=0.004548`
- `optimized_coercion=0.002282`
- `speedup_ratio=1.99`

Interpretation:
- The “optimized” fallback path was slower because it paid for object-array materialization plus a Python indexed write loop.

Fix landed:
- Added ndarray fast paths and replaced the mixed-value fallback with a faster list-comprehension conversion path in [`modules/group_stats_native.py`](../../modules/group_stats_native.py).

Impact:
- The Python fallback is now about `2x` faster than the benchmark’s legacy baseline on the same mixed-type workload.

### 4. Extended summary charts were still paying the full matplotlib composition cost
Command:

```bash
PYTHONPATH=/tmp/metroliza-chart-site:. python - <<'PY'
from pathlib import Path
import tempfile
from scripts.benchmark_paths import benchmark_chart_type_native_compare_path

with tempfile.TemporaryDirectory() as tmpdir:
    temp_dir = Path(tmpdir)
    for chart_type in ('distribution', 'iqr', 'histogram', 'trend'):
        print(chart_type, benchmark_chart_type_native_compare_path(temp_dir, chart_type=chart_type, iterations=2))
PY
```

Measured native-backed deltas after landing the new chart compositor:
- `distribution`: `0.2026s -> 0.0918s` (`2.21x` faster)
- `iqr`: `0.1273s -> 0.0493s` (`2.59x` faster)
- `histogram`: `0.9597s -> 0.1749s` (`5.49x` faster)
- `trend`: `0.1538s -> 0.0835s` (`1.84x` faster)

Additional bare-histogram micro-benchmark after the compact fast-encode pass:
- `histogram_matplotlib_median_s=0.0235`
- `histogram_native_median_s=0.0306`
- `histogram_branch_regression_ratio=0.77`

Interpretation:
- The old native chart path accelerated only the stripped histogram surface and deliberately refused the rich worksheet histogram/dashboard layout.
- The new native path wins decisively on the actual export workload where matplotlib had to compose titles, axes, legends, annotation bands, and the right-side histogram panel.
- The remaining stripped-histogram gap is now small enough that it is no longer the dominant chart concern on this branch.

Fix landed:
- Added a payload-driven native chart compositor in [`modules/native_chart_compositor.py`](../../modules/native_chart_compositor.py).
- Extended the native chart module bridge in [`lib.rs`](../../modules/native/chart_renderer/src/lib.rs) and [`Cargo.toml`](../../modules/native/chart_renderer/Cargo.toml).
- Enabled native export for histogram, distribution, IQR, and trend summary charts in [`modules/export_data_thread.py`](../../modules/export_data_thread.py).
- Updated renderer contracts and validation in [`modules/chart_renderer.py`](../../modules/chart_renderer.py).
- Added an optional HTML dashboard sidecar that reuses the same rendered summary charts and chart payload metadata in [`modules/export_html_dashboard.py`](../../modules/export_html_dashboard.py).
- Added a compact histogram fast-encode path so stripped render-budget payloads no longer pay workbook-grade PNG compression in [`modules/native_chart_compositor.py`](../../modules/native_chart_compositor.py).

## Remaining bottlenecks

### P1. Export high-header-cardinality work still has limited win
From the focused export benchmark:
- `before_refactor=0.900573`
- `after_refactor=0.879749`
- `speedup_ratio=1.02`

Implication:
- The existing export-path cleanup is not wrong, but it is no longer the obvious compute bottleneck.
- The remaining export budget is now more likely in workbook write density, large-sheet image counts, and any future HTML/dashboard interactivity layers than in chart composition or distribution-fit parameter estimation for the covered plots.

Build caveat:
- On Python `3.14`, `PyO3 0.21` still needed `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` for the local wheel build to proceed.

## Implementation plan

### Phase 1: completed in this pass
1. Remove Python-path regressions that make “optimized” code slower than legacy.
2. Eliminate wasted precompute work in distribution-fit batch auto mode.
3. Vectorize the hottest Python bootstrap CI kernels so CI generation no longer dominates grouped comparison flows.
4. Replace worksheet summary-chart matplotlib composition with a native non-matplotlib compositor for histogram, distribution, IQR, and trend exports.

### Phase 2: next recommended performance work
1. Re-profile full workbook/export scenarios now that the main compute kernels are accelerated.
   - Focus on `worksheet_writes`, image insertion density, and any repeated summary-sheet planning work.
2. Reduce candidate-fit volume before optimization starts where repeated groups still appear.
   - Add low-risk candidate pruning heuristics based on support mode and simple shape stats.
   - Consider caching fitted params by `(distribution, measurement_fingerprint)` when repeated export flows revisit identical groups.
3. Convert the local native build recipe into a repo-supported workflow for Python `3.14+`.
   - Either upgrade `PyO3` or codify the forward-compat build flag where appropriate.
4. Add an interactive layer on top of the new HTML dashboard/export sidecar.
   - Keep `xlsx` as the portable static artifact and the current HTML dashboard as the dependency-free browser artifact.
   - Reuse the same payloads for future Plotly/interactive HTML output instead of re-deriving chart semantics.

### Phase 3: governance and guardrails
1. Keep these benchmark commands as the canonical verification set for this branch:
   - `PYTHONPATH=. python -m scripts.benchmark_comparison_stats --groups 8 --samples 160 --ci-iterations 600`
   - `PYTHONPATH=. python -m scripts.benchmark_distribution_fit_batch --metrics 20 --groups 4 --samples 80`
   - `PYTHONPATH=. python -m scripts.benchmark_paths --scenarios group_preprocess_mixed_types_compare --group-preprocess-groups 10 --group-preprocess-values 1500`
2. If a future optimization claims improvement, require:
   - before/after numbers,
   - parity result,
   - a clear statement of whether the gain depends on native extensions being present.

## Implemented files
- [`modules/comparison_stats.py`](../../modules/comparison_stats.py)
- [`modules/chart_renderer.py`](../../modules/chart_renderer.py)
- [`modules/distribution_fit_service.py`](../../modules/distribution_fit_service.py)
- [`modules/distribution_fit_candidate_native.py`](../../modules/distribution_fit_candidate_native.py)
- [`modules/export_dialog.py`](../../modules/export_dialog.py)
- [`modules/export_dialog_service.py`](../../modules/export_dialog_service.py)
- [`modules/export_data_thread.py`](../../modules/export_data_thread.py)
- [`modules/export_html_dashboard.py`](../../modules/export_html_dashboard.py)
- [`modules/group_stats_native.py`](../../modules/group_stats_native.py)
- [`modules/native/distribution_fit_ad/src/lib.rs`](../../modules/native/distribution_fit_ad/src/lib.rs)
- [`tests/test_distribution_fit_native_parity.py`](../../tests/test_distribution_fit_native_parity.py)
- [`modules/contracts.py`](../../modules/contracts.py)
- [`modules/native/chart_renderer/Cargo.toml`](../../modules/native/chart_renderer/Cargo.toml)
- [`modules/native/chart_renderer/src/lib.rs`](../../modules/native/chart_renderer/src/lib.rs)
- [`modules/native_chart_compositor.py`](../../modules/native_chart_compositor.py)
- [`tests/test_chart_renderer.py`](../../tests/test_chart_renderer.py)
- [`tests/test_contracts.py`](../../tests/test_contracts.py)
- [`tests/test_thread_flow_helpers.py`](../../tests/test_thread_flow_helpers.py)
- [`tests/test_export_html_dashboard.py`](../../tests/test_export_html_dashboard.py)
- [`tests/test_export_presets.py`](../../tests/test_export_presets.py)
- [`tests/test_distribution_fit_service.py`](../../tests/test_distribution_fit_service.py)

## Validation
- `PYTHONPATH=. pytest tests/test_group_stats_tests.py tests/test_distribution_fit_service.py tests/test_comparison_stats.py -q`
  - Result: `65 passed`
- `PYTHONPATH=. ruff check modules/group_stats_native.py modules/distribution_fit_service.py modules/comparison_stats.py tests/test_distribution_fit_service.py`
  - Result: clean
- `PYTHONPATH=. pytest tests/test_distribution_fit_service.py tests/test_benchmark_paths.py tests/test_docs_markdown_links.py -q`
  - Result: `32 passed`
- `PYTHONPATH=/tmp/metroliza-native-site:. pytest tests/test_distribution_fit_native_parity.py -q`
  - Result: `18 passed`
- `PYTHONPATH=/tmp/metroliza-chart-site:. pytest tests/test_chart_renderer.py tests/test_thread_flow_helpers.py tests/test_backend_diagnostics.py tests/test_benchmark_paths.py -q`
  - Result: `104 passed`, `2 subtests passed`
- `PYTHONPATH=. ruff check modules/chart_renderer.py modules/export_data_thread.py modules/native_chart_compositor.py tests/test_chart_renderer.py tests/test_thread_flow_helpers.py`
  - Result: clean
- `PYTHONPATH=. pytest tests/test_contracts.py tests/test_export_html_dashboard.py tests/test_export_presets.py tests/test_thread_flow_helpers.py tests/test_export_data_thread_group_analysis.py tests/test_backend_diagnostics.py tests/test_benchmark_paths.py tests/test_docs_markdown_links.py -q`
  - Result: `155 passed`, `2 subtests passed`
- `PYTHONPATH=. ruff check modules/contracts.py modules/export_dialog_service.py modules/export_dialog.py modules/export_data_thread.py modules/export_html_dashboard.py tests/test_contracts.py tests/test_export_presets.py tests/test_export_html_dashboard.py tests/test_thread_flow_helpers.py`
  - Result: clean
