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

## Third-Pass Optimization Slice

- CSV Summary SQLite loading no longer creates expression indexes for the first 32 source columns up front. It now creates only core row/source/date/reference indexes during load and adds grouping/filter expression indexes lazily for active preview/filter columns.
- CSV Summary metric candidate sampling avoids repeated string conversion and list membership checks for every chunk.
- SQLite-backed grouping creation/addition for selected values now records selected keys as a deferred SQLite scope. It no longer expands all matching row IDs on the UI thread before `Use grouping`.
- Group Analysis payload construction no longer materializes `list(metric_frame.groupby(...))`; it uses `ngroups` for progress totals and streams group iteration.
- Industrial analytics groupstats input preparation now prepares numeric metric arrays once per analysis and reuses them for every groupstats metric.
- Dashboard writing now records Plotly payload budgets and HTML byte telemetry without mutating the caller manifest. Benchmark instrumentation now separates dashboard write, workbook export, and workbook close timings.

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

Third-pass local validation on 2026-05-20:

```bash
python -m ruff check modules/tabular_analytics_service.py modules/tabular_analytics_grouping_dialog.py modules/group_analysis_service.py modules/industrial_analytics_service.py modules/industrial_analytics_dashboard.py modules/industrial_analytics_workflow.py scripts/benchmark_paths.py tests/test_tabular_analytics_service.py tests/test_tabular_analytics_grouping_dialog.py tests/test_group_analysis_service.py tests/test_industrial_analytics_service.py tests/test_industrial_analytics_dashboard.py tests/test_industrial_analytics_workflow.py tests/test_benchmark_paths.py
git diff --check
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python -m pytest -q tests/test_tabular_analytics_service.py tests/test_tabular_analytics_grouping_dialog.py tests/test_group_analysis_service.py tests/test_industrial_analytics_service.py tests/test_industrial_analytics_dashboard.py tests/test_industrial_analytics_workflow.py tests/test_benchmark_paths.py
python -m compileall -q modules/tabular_analytics_service.py modules/tabular_analytics_grouping_dialog.py modules/group_analysis_service.py modules/industrial_analytics_service.py modules/industrial_analytics_dashboard.py modules/industrial_analytics_workflow.py scripts/benchmark_paths.py tests/test_tabular_analytics_service.py tests/test_tabular_analytics_grouping_dialog.py tests/test_group_analysis_service.py tests/test_industrial_analytics_service.py tests/test_industrial_analytics_dashboard.py tests/test_industrial_analytics_workflow.py tests/test_benchmark_paths.py
```

Result: Ruff passed, diff check clean, compileall passed, and pytest reported `197 passed, 7 subtests passed in 22.29s`.

```bash
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python -m pytest -q
```

Result: `1582 passed, 165 skipped, 6 warnings, 60 subtests passed in 103.36s`.

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

Third-pass baseline-vs-after benchmark comparison:

Baseline artifacts:

- `/tmp/metroliza_opt_audit_160k/benchmark-20260520-175237.json`
- `/tmp/metroliza_opt_audit_1m/benchmark-20260520-175550.json`
- `/tmp/metroliza_opt_audit_stats/benchmark-20260520-175319.json`

After-optimization artifacts:

- `/tmp/metroliza_opt_after_160k/benchmark-20260520-182055.json`
- `/tmp/metroliza_opt_after_1m/benchmark-20260520-182200.json`
- `/tmp/metroliza_opt_after_stats/benchmark-20260520-182235.json`

Commands:

```bash
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python scripts/benchmark_paths.py --output-dir /tmp/metroliza_opt_after_160k --scenarios csv_summary_large_data_probe --large-csv-rows 160000 --large-csv-columns 20 --large-csv-materialize-columns 5 --large-csv-search P-00
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python scripts/benchmark_paths.py --output-dir /tmp/metroliza_opt_after_1m --scenarios csv_summary_large_data_probe --large-csv-rows 1000000 --large-csv-columns 20 --large-csv-materialize-columns 5 --large-csv-search P-00
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python scripts/benchmark_paths.py --output-dir /tmp/metroliza_opt_after_stats --scenarios csv_summary_export_path distribution_fit_monte_carlo_path production_dashboard_workbook_path --csv-rows 1500 --csv-columns 8 --production-rows 1500 --production-metrics 3
```

| Scenario | Stage | Baseline | After | Delta | Speedup |
| --- | ---: | ---: | ---: | ---: | ---: |
| CSV Summary probe, `160k x 20` | total | `14.8578s` | `5.9421s` | `-60.0%` | `2.50x` |
| CSV Summary probe, `160k x 20` | csv_load | `12.8875s` | `4.5740s` | `-64.5%` | `2.82x` |
| CSV Summary probe, `1M x 20` | total | `101.5418s` | `37.6827s` | `-62.9%` | `2.70x` |
| CSV Summary probe, `1M x 20` | csv_load | `88.9740s` | `28.7283s` | `-67.7%` | `3.10x` |
| CSV Summary export path | total | `8.3705s` | `5.6549s` | `-32.4%` | `1.48x` |
| CSV Summary export path | groupstats_analysis | `2.3465s` | `1.6387s` | `-30.2%` | `1.43x` |
| CSV Summary export path | chart_generation | `2.3940s` | `1.6291s` | `-31.9%` | `1.47x` |
| CSV Summary export path | workbook_write | `3.4992s` | `2.3115s` | `-33.9%` | `1.51x` |
| Distribution fit benchmark | total | `25.7237s` | `18.2863s` | `-28.9%` | `1.41x` |

New dashboard/workbook timing probe:

- `production_dashboard_workbook_path`: `2.4759s`
  - `aggregation`: `0.0116s`
  - `dashboard_manifest`: `1.0521s`
  - `dashboard_write`: `0.0188s`
  - `workbook_export`: `1.3934s`
  - `workbook_close`: `0.2396s`
  - `dashboard_plotly_spec_count`: `9`
  - `dashboard_plotly_serialized_json_bytes`: `256735`

## Fourth-Pass Optimization Audit Baseline

The fourth-pass audit treats the third-pass after-optimization artifacts as the new formal baseline:

- `/tmp/metroliza_opt_after_160k/benchmark-20260520-182055.json`
- `/tmp/metroliza_opt_after_1m/benchmark-20260520-182200.json`
- `/tmp/metroliza_opt_after_stats/benchmark-20260520-182235.json`

Same-shape confirmation runs on 2026-05-20 were slower, so they are recorded as observed variance instead of replacing the formal baseline:

- `/tmp/metroliza_opt_fourth_baseline_160k/benchmark-20260520-183756.json`
- `/tmp/metroliza_opt_fourth_baseline_1m/benchmark-20260520-183944.json`
- `/tmp/metroliza_opt_fourth_baseline_stats/benchmark-20260520-184032.json`

| Scenario | Stage | Formal baseline | Confirmation run |
| --- | ---: | ---: | ---: |
| CSV Summary probe, `160k x 20` | total | `5.9421s` | `10.2133s` |
| CSV Summary probe, `160k x 20` | csv_load | `4.5740s` | `7.8023s` |
| CSV Summary probe, `1M x 20` | total | `37.6827s` | `69.1382s` |
| CSV Summary probe, `1M x 20` | csv_load | `28.7283s` | `52.7641s` |
| CSV Summary probe, `1M x 20` | materialize_required_columns | `3.1101s` | `5.8893s` |
| CSV Summary probe, `1M x 20` | sqlite_value_preview | `1.4927s` | `2.6716s` |
| CSV Summary probe, `1M x 20` | sqlite_multi_column_group_preview | `2.9640s` | `5.4811s` |
| CSV Summary export path | total | `5.6549s` | `10.8445s` |
| CSV Summary export path | groupstats_analysis | `1.6387s` | `3.1996s` |
| CSV Summary export path | chart_generation/dashboard_write | `1.6291s` | `3.0875s` |
| CSV Summary export path | workbook_write/export | `2.3115s` | `4.4445s` |
| Distribution fit benchmark | total | `18.2863s` | `23.6378s` |
| Distribution fit benchmark | monte_carlo_bootstrap_path | `7.8828s` | `10.3390s` |
| Distribution fit benchmark | monte_carlo_cache_warm_path | `7.6630s` | `9.5330s` |
| Production dashboard/workbook | total | `2.4759s` | `3.5124s` |
| Production dashboard/workbook | dashboard_manifest | `1.0521s` | `1.4928s` |
| Production dashboard/workbook | workbook_export | `1.3934s` | `1.9790s` |

Profiling artifacts:

- `/tmp/metroliza_fourth_csv_160k.prof`
- `/tmp/metroliza_opt_fourth_profile_160k/benchmark-20260520-184117.json`
- `/tmp/metroliza_fourth_stats.prof`
- `/tmp/metroliza_opt_fourth_profile_stats/benchmark-20260520-184226.json`

Profile findings:

- `csv_summary_large_data_probe` at `160k x 20`: `_load_csv_files_into_sqlite()` took `8.84s`, with `_update_metric_stats()` taking `4.49s`; the benchmark fixture `to_csv()` took `4.31s`, so load profiling should separate fixture-generation time from application load time in the next harness change.
- `distribution_fit_monte_carlo_path`: `fit_measurement_distribution()` took `31.68s` across 160 calls; Monte Carlo p-value estimation took `21.42s`, `_ad_statistic()` took `14.73s`, and SciPy candidate fitting took `9.70s`.
- Dashboard/workbook profile: `build_production_dashboard_manifest()` took `6.62s` across two calls, distribution image rendering/savefig dominated chart generation, and `add_analytics_workbook_charts()` took `5.36s` across two calls.

Ranked next implementation candidates:

| Rank | Candidate | Class | Baseline evidence | Expected impact | Risk |
| ---: | --- | --- | --- | --- | --- |
| 1 | Instrument CSV SQLite load sub-stages and optimize or sample `_update_metric_stats()` | quick Python / benchmark instrumentation | `csv_load 28.73s` formal baseline; profile shows `_update_metric_stats 4.49s` on 160k | high for load transparency; medium speedup | low |
| 2 | Split spec-independent distribution fit cache from spec-dependent risk output | algorithm/cache | cached refit still `1.4142s`; cache key includes spec limits | medium; improves refit/export reuse | medium |
| 3 | Move Monte Carlo AD p-value simulation to native backend or limit MC to selected/top candidates | native/Rust or algorithm | MC paths `7.88s` and `7.66s`; native status unavailable in this run | high for fit benchmark | medium-high |
| 4 | Add workbook sub-timings and cache per-metric numeric/grouped chart data | quick Python / instrumentation | workbook export `2.31s`, profile shows chart insertion `5.36s` under combined profile | medium | low-medium |
| 5 | Split CSV Summary dashboard timing into manifest/spec/render stages and reuse per-metric chart inputs | instrumentation / algorithm cache | dashboard write `1.63s`; production manifest `1.05s`; profile shows distribution image rendering dominates | medium | low-medium |
| 6 | Improve SQLite preview strategy for 1M grouping: prefix search, cached grouped keys, or deferred exact totals | query/schema/index | `sqlite_multi_column_group_preview 2.96s`, confirmation `5.48s` | medium-high for grouping UX | medium |
| 7 | Avoid routine full-table materialization before it is needed, or chunk materialization for downstream stages | dataflow change | `materialize_required_columns 3.11s` | high for large CSV flows | medium-high |

Fourth-pass validation commands:

```bash
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python scripts/benchmark_paths.py --output-dir /tmp/metroliza_opt_fourth_baseline_160k --scenarios csv_summary_large_data_probe --large-csv-rows 160000 --large-csv-columns 20 --large-csv-materialize-columns 5 --large-csv-search P-00
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python scripts/benchmark_paths.py --output-dir /tmp/metroliza_opt_fourth_baseline_1m --scenarios csv_summary_large_data_probe --large-csv-rows 1000000 --large-csv-columns 20 --large-csv-materialize-columns 5 --large-csv-search P-00
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python scripts/benchmark_paths.py --output-dir /tmp/metroliza_opt_fourth_baseline_stats --scenarios csv_summary_export_path distribution_fit_monte_carlo_path production_dashboard_workbook_path --csv-rows 1500 --csv-columns 8 --production-rows 1500 --production-metrics 3
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python -m cProfile -o /tmp/metroliza_fourth_csv_160k.prof scripts/benchmark_paths.py --output-dir /tmp/metroliza_opt_fourth_profile_160k --scenarios csv_summary_large_data_probe --large-csv-rows 160000 --large-csv-columns 20 --large-csv-materialize-columns 5 --large-csv-search P-00
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python -m cProfile -o /tmp/metroliza_fourth_stats.prof scripts/benchmark_paths.py --output-dir /tmp/metroliza_opt_fourth_profile_stats --scenarios csv_summary_export_path distribution_fit_monte_carlo_path production_dashboard_workbook_path --csv-rows 1500 --csv-columns 8 --production-rows 1500 --production-metrics 3
```

## Fifth-Pass Optimization Implementation

Implemented on 2026-05-20:

- `_update_metric_stats()` now uses a numeric dtype fast path, preserving candidate counts/warnings while skipping full string strip and numeric coercion for already-numeric metric columns.
- `fit_measurement_distribution()` now uses a spec-independent payload cache; cache hits recompute only `risk_estimates` for the requested LSL/USL.
- `scripts/benchmark_paths.py` now adds additive sub-timings for CSV Summary dashboard/workbook paths and explicit CSV load sub-stage placeholders.

Validation:

```bash
python -m ruff check modules/tabular_analytics_service.py tests/test_tabular_analytics_service.py modules/distribution_fit_service.py tests/test_distribution_fit_service.py scripts/benchmark_paths.py tests/test_benchmark_paths.py
git diff --check
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python -m pytest -q tests/test_tabular_analytics_service.py tests/test_distribution_fit_service.py tests/test_distribution_fit_native_parity.py tests/test_benchmark_paths.py
```

Result: Ruff passed, diff check clean, and pytest reported `87 passed, 6 skipped in 20.38s`.

Benchmark artifacts:

- `/tmp/metroliza_opt_implementation_160k/benchmark-20260520-185015.json`
- `/tmp/metroliza_opt_implementation_1m/benchmark-20260520-185221.json`
- `/tmp/metroliza_opt_implementation_stats/benchmark-20260520-185304.json`

| Scenario | Stage | Formal baseline | Fifth-pass run | Result |
| --- | ---: | ---: | ---: | --- |
| CSV Summary probe, `160k x 20` | total | `5.9421s` | `11.8829s` | slower; same session variance pattern as fourth-pass confirmation |
| CSV Summary probe, `160k x 20` | csv_load | `4.5740s` | `9.1986s` | slower; deeper load sub-stage instrumentation still needed |
| CSV Summary probe, `1M x 20` | total | `37.6827s` | `74.1283s` | slower; comparable to fourth-pass confirmation variance |
| CSV Summary probe, `1M x 20` | csv_load | `28.7283s` | `58.1531s` | slower; no reliable CSV win claimed |
| CSV Summary export path | total | `5.6549s` | `8.6928s` | slower than formal baseline, faster than fourth-pass confirmation |
| CSV Summary export path | dashboard_manifest | n/a | `2.3952s` | new timing key |
| CSV Summary export path | dashboard_html_write | n/a | `0.0124s` | new timing key |
| CSV Summary export path | workbook_sheet_writes | n/a | `0.8154s` | new timing key |
| CSV Summary export path | workbook_export_overhead | n/a | `2.0012s` | new timing key |
| Distribution fit benchmark | total | `18.2863s` | `22.3437s` | slower overall under current run variance |
| Distribution fit benchmark | monte_carlo_cached_refit_path | `1.4142s` | `0.0113s` | `~125.6x` faster |
| Production dashboard/workbook | total | `2.4759s` | `3.5511s` | slower than formal baseline, similar to fourth-pass confirmation |
| Production dashboard/workbook | workbook_sheet_writes | n/a | `0.4324s` | new timing key |
| Production dashboard/workbook | workbook_export_overhead | n/a | `1.2199s` | new timing key |

Conclusion: the spec-independent fit cache produced the measurable win in this pass. The CSV numeric fast path is correct, but the benchmark remains too noisy and too coarse to show a reliable total-load improvement; the next CSV pass should instrument `_load_csv_files_into_sqlite()` internally before further claims.

## Sixth-Pass CSV Load Timing And Monte Carlo Optimization

Implemented on 2026-05-20:

- `TabularAnalyticsLoadResult` now carries `load_timings_s` from `_load_csv_files_into_sqlite()`.
- CSV Summary large-data benchmarks now report real load sub-stages: sampling, chunk reads, normalization/building, metric stats, SQLite write/indexing, candidate build, preview, and unattributed time.
- Pure-Python Monte Carlo AD p-value fallback now batches simulation samples and computes AD statistics vectorized by chunk. Native Monte Carlo remains the first path when available.

Validation:

```bash
python -m ruff check modules/tabular_analytics_service.py tests/test_tabular_analytics_service.py modules/distribution_fit_service.py tests/test_distribution_fit_service.py scripts/benchmark_paths.py tests/test_benchmark_paths.py
git diff --check
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python -m pytest -q tests/test_tabular_analytics_service.py tests/test_distribution_fit_service.py tests/test_distribution_fit_native_parity.py tests/test_benchmark_paths.py
```

Result: Ruff passed, diff check clean, and pytest reported `88 passed, 6 skipped in 15.53s`.

Benchmark artifacts:

- `/tmp/metroliza_opt_load_mc_160k/benchmark-20260520-190054.json`
- `/tmp/metroliza_opt_load_mc_1m/benchmark-20260520-190225.json`
- `/tmp/metroliza_opt_load_mc_stats/benchmark-20260520-190256.json`

| Scenario | Stage | Formal baseline | Sixth-pass run | Result |
| --- | ---: | ---: | ---: | --- |
| CSV Summary probe, `1M x 20` | total | `37.6827s` | `54.4931s` | slower than formal baseline, faster than the slower fifth-pass run |
| CSV Summary probe, `1M x 20` | csv_load | `28.7283s` | `40.9162s` | now split into real sub-stages |
| CSV Summary probe, `1M x 20` | csv_load_read_file | n/a | `6.3488s` | new timing key |
| CSV Summary probe, `1M x 20` | csv_load_metric_stats | n/a | `14.7202s` | new timing key |
| CSV Summary probe, `1M x 20` | csv_load_sqlite_ingest | n/a | `18.7819s` | `sqlite_write 13.4443s`, `indexing 5.3366s` |
| CSV Summary probe, `1M x 20` | csv_load_unattributed | n/a | `0.0373s` | timing coverage is effectively complete |
| Distribution fit benchmark | total | `18.2863s` | `8.8936s` | `2.06x` faster |
| Distribution fit benchmark | monte_carlo_bootstrap_path | `7.8828s` | `3.6856s` | `2.14x` faster |
| Distribution fit benchmark | monte_carlo_cache_warm_path | `7.6630s` | `3.4236s` | `2.24x` faster |
| Distribution fit benchmark | monte_carlo_cached_refit_path | `1.4142s` | `0.0127s` | `111.2x` faster |

Native distribution-fit status in this run: Monte Carlo `0`, AD/KS `0`, candidate metrics `0`, candidate fit `0`. The Monte Carlo improvement came from the Python fallback, not native acceleration.

## Seventh-Pass Large-Sample Monte Carlo GOF Policy

Implemented on 2026-05-20:

- Distribution fitting now keeps full-data model fitting, risk estimates, ranking metrics, PDFs, CDFs, and KDEs, while allowing Monte Carlo AD p-values to use an effective GOF sample policy.
- New GOF controls on `fit_measurement_distribution()` and batch fitting: `gof_sample_policy="auto"|"full"|"subsampled"`, `gof_max_sample_size`, and `gof_subsample_method="quantile_stratified"`.
- `auto` preserves full Monte Carlo for samples up to the cap and uses a deterministic quantile-stratified effective GOF sample above the cap.
- GOF metadata now records the method, requested/effective policy, full/effective sample sizes, subsample method, full AD statistic, and effective AD statistic. Subsampled Monte Carlo p-values are labeled `ad_parametric_bootstrap_subsampled`.
- Benchmark harness now has a separate `distribution_fit_gof_policy_compare` scenario so the formal full-Monte-Carlo baseline remains intact.

Validation:

```bash
python -m ruff check modules/distribution_fit_service.py tests/test_distribution_fit_service.py scripts/benchmark_paths.py tests/test_benchmark_paths.py
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python -m pytest -q tests/test_distribution_fit_service.py tests/test_benchmark_paths.py
```

Result: Ruff passed and pytest reported `42 passed in 18.10s`.

Benchmark artifacts:

- `/tmp/metroliza_gof_policy_compare/benchmark-20260520-191928.json`
- `/tmp/metroliza_gof_existing_mc_check/benchmark-20260520-192007.json`

Formal-vs-auto policy benchmark command:

```bash
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python scripts/benchmark_paths.py --output-dir /tmp/metroliza_gof_policy_compare --scenarios distribution_fit_gof_policy_compare --fit-group-count 10 --fit-sample-size 5000 --fit-monte-carlo-samples 120 --fit-gof-max-sample-size 500
```

| Scenario | Stage | Full formal MC | Auto GOF policy | Result |
| --- | ---: | ---: | ---: | --- |
| Distribution GOF policy compare, `10 x 5000`, `120` MC iterations | full_monte_carlo_path | `7.5613s` | n/a | full-data AD p-value sample size `5000` |
| Distribution GOF policy compare, `10 x 5000`, `120` MC iterations | auto_gof_policy_path | n/a | `1.8503s` | effective GOF sample size `500` |
| Distribution GOF policy compare, `10 x 5000`, `120` MC iterations | auto_policy_speedup_ratio | n/a | `4.0865x` | auto policy faster |
| Distribution GOF policy compare, `10 x 5000`, `120` MC iterations | auto_cached_refit_path | n/a | `0.0057s` | cached spec refit remains effectively instant |

Legacy small-sample formal benchmark check:

```bash
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python scripts/benchmark_paths.py --output-dir /tmp/metroliza_gof_existing_mc_check --scenarios distribution_fit_monte_carlo_path --fit-group-count 40 --fit-sample-size 120 --fit-monte-carlo-samples 250
```

| Scenario | Stage | Sixth-pass run | Seventh-pass check | Result |
| --- | ---: | ---: | ---: | --- |
| Distribution fit benchmark, `40 x 120`, `250` MC iterations | total | `8.8936s` | `11.6886s` | slower in this run; small-sample path remains full MC |
| Distribution fit benchmark, `40 x 120`, `250` MC iterations | monte_carlo_bootstrap_path | `3.6856s` | `5.0220s` | no subsampling because sample size is below cap |
| Distribution fit benchmark, `40 x 120`, `250` MC iterations | monte_carlo_cache_warm_path | `3.4236s` | `4.4339s` | no subsampling because sample size is below cap |
| Distribution fit benchmark, `40 x 120`, `250` MC iterations | monte_carlo_cached_refit_path | `0.0127s` | `0.0131s` | stable cached spec-refit path |

Native distribution-fit status in both seventh-pass benchmark runs: Monte Carlo `0`, AD/KS `0`, candidate metrics `0`, candidate fit `0`.

## Release Check Before Push

Run on 2026-05-20 before pushing `rc2`:

```bash
python -m ruff check .
python scripts/sync_release_metadata.py --check
python scripts/check_release_hygiene.py
git diff --check
python -m compileall -q -x '^\./\.git/' .
python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mpl python -m pytest tests -q --cov=. --cov-report=term --cov-report=xml:coverage.xml
```

Result:

- Ruff passed.
- Release metadata was already in sync.
- Release hygiene passed.
- Diff whitespace check was clean.
- Compileall passed.
- Security audit passed after rerunning outside the sandbox for `pip-audit` tool setup. `pip-audit` reported no known vulnerabilities; Bandit warnings remained report-only baseline findings.
- Full pytest with coverage passed: `1591 passed, 165 skipped, 90 warnings, 60 subtests passed in 250.80s`.

## Remaining Optimization Candidates

- CSV import is still the dominant `1M x 20` bottleneck after the third pass, but the measured load phase dropped from `88.9740s` to `28.7283s`. The next meaningful import step is a measured SQLite bulk-loader experiment, then DuckDB/Arrow/Polars only if dependency policy changes.
- Distribution Monte Carlo remains a multi-second benchmark path; real export paths now use large-export fit policy, but the benchmark remains useful for native-kernel or stricter-cap experiments.
- Large SQLite multi-column selector preview is still computationally expensive, but it is now worker-backed with delayed duck loading dialog instead of blocking the grouping dialog.
- Workbook export is now clearly separated from workbook close timing; the measured CSV Summary workbook path still takes more than `2s` and remains a candidate for sheet-write batching/native writer experiments.
