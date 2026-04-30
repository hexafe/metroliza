# Metroliza Audit Next Session

Last updated: 2026-04-30

## Start Here

Branch: `codex/report-metadata-redesign`

The current audit pass has validated, uncommitted changes in:

- `docs/perf_baseline.md`
- `modules/distribution_fit_service.py`
- `modules/report_schema.py`
- `scripts/benchmark_paths.py`
- `tests/test_distribution_fit_service.py`
- `tests/test_schema_index_query_plans.py`

All benchmark and test additions use synthetic data only. Do not add real reports,
real report-derived filenames, customer names, or customer-derived values to the
repository, including benchmark artifacts.

## Completed In This Pass

1. Added export benchmark stage timing for workbook close, write-vs-shape,
   high-header distribution/histogram/trend payloads, and CSV summary writes.
2. Added Monte Carlo AD p-value caching for repeated distribution-fit spec
   refits using the existing `memoization_cache`.
3. Added `idx_source_file_locations_latest_active` for latest active source file
   location lookups.
4. Audited OCR packaging/confidentiality posture. Source-level OCR validation
   passed and tracked files had no exact hits against ignored 272-PDF manifest
   filename/stem tokens.

Commit checkpoint:

- `e7f70b0 Add audit benchmark instrumentation`

## 2026-04-30 Export Payload Optimization

Completed after the audit checkpoint:

- Optimized `build_violin_payload_vectorized(...)` to avoid the pandas
  copy/dropna/astype/groupby path for grouped payloads. The replacement keeps
  order-preserving labels and value lists while using a single pass over
  numeric measurements and group labels.
- Removed the duplicate distribution/IQR violin-payload rebuild in
  `ExportDataThread`; `resolve_sampling_context(...)` already computes those
  payloads before chart preparation.

Focused validation:

```bash
python -m pytest tests/test_chart_render_service.py tests/test_export_grouping_and_sorting.py tests/test_export_summary_sheet_compute.py tests/test_thread_flow_helpers.py -q
python -m ruff check modules/chart_render_service.py modules/export_data_thread.py tests/test_chart_render_service.py tests/test_export_grouping_and_sorting.py tests/test_export_summary_sheet_compute.py tests/test_thread_flow_helpers.py
```

Result: focused tests passed (`118 passed, 2 subtests passed`), and ruff passed.

Benchmark command:

```bash
python -m scripts.benchmark_paths \
  --output-dir /tmp/metroliza_high_header_dense_after \
  --scenarios excel_export_high_header_cardinality_compare \
  --report-count 12 \
  --headers-per-report 80
```

Result:

- `/tmp/metroliza_high_header_dense_after/benchmark-20260430-192337.json`
- `/tmp/metroliza_high_header_dense_after/benchmark-20260430-192337.csv`
- `after_refactor=0.254s`
- `after_distribution_payload=0.055s`
- `after_histogram_payload=0.183s`
- `speedup_ratio=1.12x`

For comparison, the pre-optimization 12-report/8-header local check showed
`after_refactor=1.246s` and `after_distribution_payload=1.079s`. The older
audit handoff measured the same distribution-payload bottleneck at about
`1.13s` to `1.14s`.

## 2026-04-30 Export Stage Trend Advisory

Completed:

- Extended `scripts/benchmark_trend_compare.py` with advisory stage-metric
  reporting.
- Wired the non-blocking `perf-benchmarks` CI job to pass
  `--export-stage-metrics`.
- Documented that export stage medians are reported in `stage_metric_results`
  and never add failure conditions beyond the existing scenario wall-time trend
  comparison.

Focused validation:

```bash
python -m pytest tests/test_benchmark_trend_compare.py tests/test_ci_policy_sync.py -q
python -m ruff check scripts/benchmark_trend_compare.py tests/test_benchmark_trend_compare.py
```

Result: focused tests passed (`14 passed`), ruff passed, and py_compile passed.

## 2026-04-30 Histogram Density Payload Optimization

Completed:

- Optimized the histogram density curve adapter path for already-tabular numeric
  input by avoiding the generic `pd.Series(list(...))` conversion.
- Replaced the fallback normal-curve `scipy.stats.norm.fit(...)` call with the
  equivalent NumPy mean/std MLE calculation.

Focused validation:

```bash
python -m pytest tests/test_distribution_fit_service.py tests/test_export_summary_utils.py tests/test_export_plot_helpers.py::TestExportPlotHelpers::test_build_histogram_density_curve_payload_builds_curve_for_variable_data tests/test_export_plot_helpers.py::TestExportPlotHelpers::test_build_histogram_density_curve_payload_returns_none_for_constant_data tests/test_export_plot_helpers.py::TestExportPlotHelpers::test_build_histogram_density_curve_payload_accepts_numeric_string_measurements tests/test_export_plot_helpers.py::TestExportPlotHelpers::test_build_histogram_density_curve_payload_supports_kde_mode -q
python -m ruff check modules/distribution_fit_service.py tests/test_distribution_fit_service.py tests/test_export_summary_utils.py tests/test_export_plot_helpers.py
```

Result: focused tests passed (`42 passed`), and ruff passed.

Benchmark command:

```bash
python -m scripts.benchmark_paths \
  --output-dir /tmp/metroliza_high_header_hist_after \
  --scenarios excel_export_high_header_cardinality_compare \
  --report-count 12 \
  --headers-per-report 80
```

Result:

- `/tmp/metroliza_high_header_hist_after/benchmark-20260430-192930.json`
- `/tmp/metroliza_high_header_hist_after/benchmark-20260430-192930.csv`
- `after_refactor=0.216s`
- `after_distribution_payload=0.071s`
- `after_histogram_payload=0.125s`
- `speedup_ratio=1.11x`

## Validation Already Run

```bash
python -m pytest tests/test_benchmark_paths.py tests/test_distribution_fit_service.py tests/test_schema_index_query_plans.py tests/test_report_schema_repository.py -q
python -m ruff check scripts/benchmark_paths.py modules/distribution_fit_service.py modules/report_schema.py tests/test_benchmark_paths.py tests/test_distribution_fit_service.py tests/test_schema_index_query_plans.py
git diff --check
python scripts/validate_packaged_pdf_parser.py --require-header-ocr
```

Result: focused tests passed (`45 passed`), ruff passed, diff check passed, and
packaged OCR dependency/model validation passed.

Integrated synthetic benchmark:

```bash
python -m scripts.benchmark_paths \
  --output-dir /tmp/metroliza_audit_integrated \
  --scenarios excel_export_path excel_export_write_vs_shape_path excel_export_high_header_cardinality_compare csv_summary_export_path distribution_fit_monte_carlo_path \
  --report-count 12 \
  --headers-per-report 8 \
  --csv-rows 120 \
  --csv-columns 3 \
  --fit-group-count 6 \
  --fit-sample-size 60 \
  --fit-monte-carlo-samples 60
```

Output:

- `/tmp/metroliza_audit_integrated/benchmark-20260429-080233.json`
- `/tmp/metroliza_audit_integrated/benchmark-20260429-080233.csv`

Key readings:

- High-header export: `before_refactor=1.323s`, `after_refactor=1.320s`,
  `speedup_ratio=1.00x`.
- High-header distribution payload dominates: about `1.13s` to `1.14s`.
- Monte Carlo path: uncached `0.480s`, cached spec refit `0.266s`,
  cached/uncached ratio `0.55`.
- CSV summary: `0.113s` wall, workbook write `0.060s`.
- Excel write-vs-shape: shaping `0.121s`, worksheet ops `0.038s`.

## Next Priority Order

1. Run clean-machine Windows packaged EXE smoke. Source OCR validation is green,
   but release confidence still needs packaged artifact launch/parser evidence.
2. Return to DB bulk-update APIs for Modify DB flows after export and Windows
   release evidence are handled.

## Do Not Rerun By Default

- Do not rerun the full 272-PDF OCR benchmark unless OCR/parser behavior changes.
- Do not reopen broad test deletion; the test cleanup roadmap is frozen except
  for named stale/duplicate tests with explicit replacement coverage.
- Do not add Rust/native work for workbook writing, dashboard HTML, or UI paths.
