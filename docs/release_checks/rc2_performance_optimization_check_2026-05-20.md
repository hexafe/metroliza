# RC2 Performance Optimization Check - 2026-05-20

Performance slice for CSV Summary grouping/filtering, Group Analysis, and HTML dashboard/export paths.

## Implemented

- CSV/Excel Summary SQLite loading now exposes progress and cancellation hooks, and the UI load thread passes those hooks to the service.
- CSV Summary row-value search avoids SQLite preview refresh on every keystroke; SQLite-backed search applies on Enter.
- `build_tabular_grouping_dataframe()` no longer builds selector labels with `iterrows()`.
- `DataFrameGroupingIndex` avoids unnecessary sorted grouping for previews.
- Group Analysis payload construction now supports progress, cancellation, batch distribution profile fitting, and optional chart payload generation.
- Export Group Analysis now wires progress/cancel into `build_group_analysis_payload()` and skips chart payload lists outside Standard mode.
- HTML dashboard writing records dashboard timing metadata and avoids rebuilding Plotly data for dark theme specs.
- Workbook column width sizing samples large columns instead of stringifying every cell.
- Added `csv_summary_large_data_probe` to `scripts/benchmark_paths.py` for local/release-scale CSV Summary performance evidence.

## Validation

Commands run locally on 2026-05-20:

```bash
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python -m pytest -q tests/test_benchmark_paths.py tests/test_distribution_shape_analysis.py tests/test_group_analysis_service.py tests/test_export_html_dashboard.py tests/test_export_thread_label_helpers.py tests/test_thread_flow_helpers.py tests/test_tabular_analytics_service.py tests/test_grouping_filter_core.py tests/test_tabular_analytics_filter_dialog.py tests/test_tabular_analytics_grouping_dialog.py tests/test_industrial_analytics_workers.py
```

Result: `239 passed, 48 skipped, 1 warning, 9 subtests passed in 27.98s`.

```bash
python -m ruff check modules/distribution_shape_analysis.py modules/export_data_thread.py modules/export_html_dashboard.py modules/group_analysis_service.py modules/grouping_filter_core.py modules/industrial_analytics_dialog.py modules/industrial_workers.py modules/tabular_analytics_filter_dialog.py modules/tabular_analytics_service.py scripts/benchmark_paths.py tests/test_benchmark_paths.py tests/test_distribution_shape_analysis.py tests/test_export_html_dashboard.py tests/test_export_thread_label_helpers.py tests/test_group_analysis_service.py tests/test_grouping_filter_core.py tests/test_industrial_analytics_workers.py tests/test_tabular_analytics_filter_dialog.py tests/test_tabular_analytics_service.py tests/test_thread_flow_helpers.py
```

Result: `All checks passed!`.

```bash
python -m compileall -q modules/distribution_shape_analysis.py modules/export_data_thread.py modules/export_html_dashboard.py modules/group_analysis_service.py modules/grouping_filter_core.py modules/industrial_analytics_dialog.py modules/industrial_workers.py modules/tabular_analytics_filter_dialog.py modules/tabular_analytics_service.py scripts/benchmark_paths.py tests/test_benchmark_paths.py tests/test_distribution_shape_analysis.py tests/test_export_html_dashboard.py tests/test_export_thread_label_helpers.py tests/test_group_analysis_service.py tests/test_grouping_filter_core.py tests/test_industrial_analytics_workers.py tests/test_tabular_analytics_filter_dialog.py tests/test_tabular_analytics_service.py tests/test_thread_flow_helpers.py
```

Result: passed.

## Benchmark Evidence

Existing slow-path probe:

```bash
MPLCONFIGDIR=/tmp/metroliza-mpl python scripts/benchmark_paths.py --output-dir /tmp/metroliza_perf_implementation_existing --scenarios csv_summary_export_path distribution_fit_monte_carlo_path
```

- `csv_summary_export_path`: `5.4517s`
  - `groupstats_analysis`: `1.5787s`
  - `chart_generation`: `1.5719s`
  - `workbook_write`: `2.2296s`
- `distribution_fit_monte_carlo_path`: `15.8113s`
  - `monte_carlo_bootstrap_path`: `6.6916s`
  - `monte_carlo_cache_warm_path`: `6.9010s`
  - `monte_carlo_cached_refit_path`: `1.1525s`

SQLite threshold probe:

```bash
MPLCONFIGDIR=/tmp/metroliza-mpl python scripts/benchmark_paths.py --output-dir /tmp/metroliza_perf_implementation_sqlite --scenarios csv_summary_large_data_probe --large-csv-rows 160000 --large-csv-columns 20 --large-csv-materialize-columns 5 --large-csv-search P-00
```

- `csv_summary_large_data_probe`: `9.4427s`
  - `csv_load`: `8.5136s`
  - `materialize_required_columns`: `0.4638s`
  - `value_preview`: `0.3231s`
  - `group_preview`: `0.0710s`
  - `row_ids_for_search`: `0.0711s`

Target-size probe:

```bash
MPLCONFIGDIR=/tmp/metroliza-mpl python scripts/benchmark_paths.py --output-dir /tmp/metroliza_perf_implementation_1m --scenarios csv_summary_large_data_probe --large-csv-rows 1000000 --large-csv-columns 20 --large-csv-materialize-columns 5 --large-csv-search P-00
```

- `csv_summary_large_data_probe`: `64.0852s`
  - `csv_load`: `58.2580s`
  - `materialize_required_columns`: `2.9420s`
  - `value_preview`: `1.9967s`
  - `group_preview`: `0.4428s`
  - `row_ids_for_search`: `0.4457s`

## Remaining Optimization Candidates

- CSV import is still the dominant `1M x 20` bottleneck and remains the best candidate for bulk SQLite tuning, Arrow/Polars/DuckDB experiments, or Rust/C++ parsing/import.
- Distribution Monte Carlo remains a multi-second path and remains a candidate for native acceleration or stricter policy caps.
- Browser/dashboard payload budgets should be enforced in a later slice for very large interactive chart sets.
