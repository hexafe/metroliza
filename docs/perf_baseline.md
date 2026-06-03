# Performance Baseline (Canonical Scenarios)

This document defines canonical benchmark scenarios and pass/fail policy for CI performance trend monitoring.

## Policy Summary

- **Warmup:** run each benchmark script once and discard results.
- **Measured runs:** run each benchmark script **3** times after warmup.
- **Statistic used for regression gate:** median wall time (`wall_time_s`) per scenario across measured runs.
- **Regression threshold:** flag a scenario if median wall time regresses beyond the percentage threshold vs `docs/perf_baseline_snapshot.json` and beyond the configured absolute slowdown floor.
- **Current CI status:** the shared benchmark trend job and its trend-comparison
  step are intentionally **non-blocking** (`continue-on-error: true`) during
  rollout so advisory benchmark drift does not publish a red PR check.
- **Shared benchmark noise floor:** the non-blocking shared benchmark job uses a `12%` median-regression threshold plus a `0.100s` absolute slowdown floor. This keeps sub-100 ms hosted-runner jitter from producing red advisory jobs while preserving the trend report values for review.
- **Export stage metrics:** the shared non-blocking benchmark job also records
  canonical export stage medians in `stage_metric_results`. These stage medians
  are advisory diagnostics only; they do not add failure conditions beyond the
  existing scenario wall-time trend comparison.
- **Startup profile diagnostics:** startup JSONL files can be summarized with
  `python scripts/summarize_startup_profile.py <profile.jsonl>` to report first
  feedback, first main-window show, event-loop tick, and post-paint feature
  warmup spans.

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

## Export benchmark stage coverage (`scripts/benchmark_paths.py`)

All export benchmark fixtures are synthetic. Do not add real report files,
real report-derived names, or customer-derived CSV values to these scenarios.

Canonical export scenario keys:
- `excel_export_path`
- `excel_export_write_vs_shape_path`
- `excel_export_high_header_cardinality_compare`
- `csv_summary_export_path`

Expected stage-level timings include:
- Excel workbook path: `transform_grouping`, `worksheet_write_planning`,
  `worksheet_writes`, `chart_payload_preparation`, `chart_rendering`,
  and `workbook_close`.
- Excel write-vs-shape path: `data_load`, `dataframe_grouping`,
  `data_sorting`, `write_bundle_planning`, `write_measurement_blocks`,
  `write_only_worksheet_ops`, and `workbook_close`.
- High-header-cardinality path: before/after sampling and chart-payload
  timings for distribution, histogram, and trend payloads.
- CSV summary path: `groupstats_analysis`, `transform_grouping`,
  `detail_sheet_to_excel`, `worksheet_writes`, `chart_generation`,
  `overview_sheet_write`, `workbook_write`, and `workbook_close`.
- Dashboard writer subspans use the `dashboard_writer_` prefix, including
  `dashboard_writer_plotly_json_measurement`, `dashboard_writer_html_rendering`,
  and `dashboard_writer_html_write`. Production dashboard scenarios also record
  `dashboard_writer_static_population_layer` and
  `dashboard_writer_plotly_budget_resolution`.
- Static POPULATION render probe: `array_generation`, `full_density_render`,
  and `sampled_marker_render`.

CI trend reporting uses `scripts/benchmark_trend_compare.py
--export-stage-metrics` to include these export stage keys in the uploaded
non-blocking trend report. Missing stage keys are reported as `missing` in the
JSON output rather than failing the job.

Manual release-scale dashboard probes:

```bash
PYTHONPATH=src:. python scripts/benchmark_paths.py \
  --scenarios population_static_render_probe \
  --population-static-render-rows 10000000

PYTHONPATH=src:. python scripts/benchmark_paths.py \
  --scenarios csv_summary_large_data_probe \
  --large-csv-rows 10000000 \
  --large-csv-columns 20 \
  --large-csv-materialize-columns 5
```

The 10M-point static POPULATION probe is opt-in and is not part of default CI.
It records full-density render time, sampled-marker comparison time, PNG size,
non-empty pixel count, and peak RSS when the platform exposes it.

## 2) Distribution fit batch path (`scripts/benchmark_distribution_fit_batch.py`)

- Scenario key: `distribution_fit_batch_compare`
- Purpose: per-group distribution-fit vs batch ndarray flow parity/performance.
- Fixture sizes:
  - `--metrics 40`
  - `--groups 6`
  - `--samples 120`
- Required parity check:
  - `parity_mismatches` must remain `0`.

## 3) Comparison-stats CI and pairwise flows

Sources:
- `src/metroliza/analytics/comparison_stats.py`
- `src/metroliza/native_bridges/comparison_stats_native.py`
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
