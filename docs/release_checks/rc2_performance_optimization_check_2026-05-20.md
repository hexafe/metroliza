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

## Second-Pass Optimization UX Slice

- Worker progress dialogs now use a delayed duck dialog helper: workers start immediately, and the dialog appears only if work is still running after 1 second.
- Parsing, Export, CSV/Excel loading, and CSV/Excel analytics generation use the delayed helper to avoid flashing progress UI for quick paths.
- SQLite-backed CSV Summary filter value previews now run in a worker thread and preserve Enter-to-apply search behavior.
- Large SQLite multi-column grouping previews now run in a worker thread with the same delayed duck dialog, covering the measured `>1s` selector preview case.
- SQLite value preview now uses one grouped query with `COUNT(*) OVER ()` instead of a separate grouped count scan.
- SQLite-backed `Assign all filtered rows...` defers broad scope assignment instead of eagerly expanding all row IDs; final grouping materialization resolves pending scopes through SQLite temp tables.
- Production groupstats now supports per-metric progress and cooperative cancellation.
- Large export distribution profile fitting uses `skip_large_exports` policy while preserving pairwise/nonparametric outputs.
- HTML dashboard export now enforces Plotly payload budgets and falls back to PNG snapshots when embedded interactive payloads are too large.
- Export completion metadata records dashboard finalization, Plotly spec/JSON sizes, HTML bytes, and workbook close timing.

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

Second-pass local validation on 2026-05-20:

```bash
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python -m pytest -q tests/test_worker_progress_dialog.py tests/test_tabular_analytics_filter_dialog.py tests/test_tabular_analytics_grouping_dialog.py tests/test_tabular_analytics_service.py tests/test_benchmark_paths.py tests/test_export_html_dashboard.py tests/test_thread_flow_helpers.py tests/test_export_thread_label_helpers.py tests/test_industrial_analytics_service.py tests/test_industrial_analytics_workflow.py tests/test_group_analysis_service.py tests/test_distribution_shape_analysis.py
```

Result: `312 passed, 1 warning, 9 subtests passed in 37.92s`.

```bash
python -m ruff check modules/export_backends.py modules/export_data_thread.py modules/export_dialog.py modules/export_html_dashboard.py modules/group_analysis_service.py modules/industrial_analytics_dialog.py modules/industrial_analytics_service.py modules/industrial_analytics_workflow.py modules/parsing_dialog.py modules/tabular_analytics_filter_dialog.py modules/tabular_analytics_grouping_dialog.py modules/tabular_analytics_service.py modules/worker_progress_dialog.py scripts/benchmark_paths.py tests/test_benchmark_paths.py tests/test_export_html_dashboard.py tests/test_group_analysis_service.py tests/test_industrial_analytics_service.py tests/test_industrial_analytics_workflow.py tests/test_tabular_analytics_filter_dialog.py tests/test_tabular_analytics_grouping_dialog.py tests/test_tabular_analytics_service.py tests/test_thread_flow_helpers.py tests/test_worker_progress_dialog.py
```

Result: `All checks passed!`.

```bash
python -m compileall -q modules/export_backends.py modules/export_data_thread.py modules/export_dialog.py modules/export_html_dashboard.py modules/group_analysis_service.py modules/industrial_analytics_dialog.py modules/industrial_analytics_service.py modules/industrial_analytics_workflow.py modules/parsing_dialog.py modules/tabular_analytics_filter_dialog.py modules/tabular_analytics_grouping_dialog.py modules/tabular_analytics_service.py modules/worker_progress_dialog.py scripts/benchmark_paths.py tests/test_benchmark_paths.py tests/test_export_html_dashboard.py tests/test_group_analysis_service.py tests/test_industrial_analytics_service.py tests/test_industrial_analytics_workflow.py tests/test_tabular_analytics_filter_dialog.py tests/test_tabular_analytics_grouping_dialog.py tests/test_tabular_analytics_service.py tests/test_thread_flow_helpers.py tests/test_worker_progress_dialog.py
```

Result: passed.

Final release-check validation on 2026-05-20:

```bash
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python -m pytest -q
```

Result: `1564 passed, 156 skipped, 6 warnings, 60 subtests passed in 88.02s`.

```bash
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python -m pytest tests -q --cov=. --cov-report=term --cov-report=xml:coverage.xml
```

Result: `1564 passed, 156 skipped, 86 warnings, 60 subtests passed in 114.40s`; total coverage `80%`.

```bash
python -m ruff check .
python -m compileall -q -x '^\./\.git/' .
python scripts/sync_release_metadata.py --check
python scripts/check_release_hygiene.py
python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects
```

Result: passed. Security audit dependency scan reported `No known vulnerabilities found`; Bandit warnings remain the existing report-only baseline.

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

Second-pass slow-path probe:

```bash
MPLCONFIGDIR=/tmp/metroliza-mpl python scripts/benchmark_paths.py --output-dir /tmp/metroliza_perf_opt_slice_existing_rerun --scenarios csv_summary_export_path distribution_fit_monte_carlo_path
```

- `csv_summary_export_path`: `5.5754s`
  - `groupstats_analysis`: `1.6503s`
  - `chart_generation`: `1.5676s`
  - `workbook_write`: `2.2876s`
- `distribution_fit_monte_carlo_path`: `16.8065s`
  - `ks_proxy_path`: `1.1910s`
  - `monte_carlo_bootstrap_path`: `7.2176s`
  - `monte_carlo_cache_warm_path`: `7.0909s`
  - `monte_carlo_cached_refit_path`: `1.3070s`

Second-pass SQLite threshold probe:

```bash
MPLCONFIGDIR=/tmp/metroliza-mpl python scripts/benchmark_paths.py --output-dir /tmp/metroliza_perf_opt_slice_sqlite160k --scenarios csv_summary_large_data_probe --large-csv-rows 160000 --large-csv-columns 20 --large-csv-materialize-columns 5 --large-csv-search P-00
```

- `csv_summary_large_data_probe`: `10.1024s`
  - `csv_load`: `8.6671s`
  - `materialize_required_columns`: `0.4788s`
  - `sqlite_value_preview`: `0.2593s`
  - `group_preview`: `0.0708s`
  - `sqlite_multi_column_group_preview`: `0.4835s`
  - `row_ids_for_search`: `0.0705s`
  - `sqlite_assign_filtered_scope`: `0.0718s`

Second-pass target-size probe:

```bash
MPLCONFIGDIR=/tmp/metroliza-mpl python scripts/benchmark_paths.py --output-dir /tmp/metroliza_perf_opt_slice_sqlite1m --scenarios csv_summary_large_data_probe --large-csv-rows 1000000 --large-csv-columns 20 --large-csv-materialize-columns 5 --large-csv-search P-00
```

- `csv_summary_large_data_probe`: `68.9709s`
  - `csv_load`: `59.8747s`
  - `materialize_required_columns`: `3.0195s`
  - `sqlite_value_preview`: `1.6333s`
  - `group_preview`: `0.4456s`
  - `sqlite_multi_column_group_preview`: `3.0719s`
  - `row_ids_for_search`: `0.4523s`
  - `sqlite_assign_filtered_scope`: `0.4729s`
  - `sqlite_use_grouping_sparse_assignment`: `0.0006s`

## Remaining Optimization Candidates

- CSV import is still the dominant `1M x 20` bottleneck. This slice kept runtime dependencies stable; the next meaningful import step is a measured SQLite bulk-loader experiment, then DuckDB/Arrow/Polars only if dependency policy changes.
- Distribution Monte Carlo remains a multi-second benchmark path; real export paths now use large-export fit policy, but the benchmark remains useful for native-kernel or stricter-cap experiments.
- Large SQLite multi-column selector preview is still computationally expensive, but it is now worker-backed with delayed duck loading dialog instead of blocking the grouping dialog.
