# Oznak Production Analytics Implementation Plan

Created: 2026-05-11

## Scope

This plan extends the current Metroliza Oznak integration from cached production-row
sync/export into an interactive production analytics workflow.

Requested user outcomes:

- Filter, group, and aggregate production data by selected criteria.
- Aggregate by hour, day, week, month, or year.
- Let the user choose aggregation method, starting with mean and median and extending
  to count, sum, min, max, standard deviation, percentiles, first, and last.
- Analyze production data alone, without any CMM report measurements.
- Build dashboards with histograms, time series, violin plots, box plots, and
  group-comparison/statistical outputs from `hexafe-groupstats`, `hexafe-plotstats`,
  and useful concepts from `hexafe/ProductionDataAnalyzer`.
- Let users paste a list of references, visibly mark those references on every plot,
  and optionally turn those references into a separate analysis group.
- Let users open CSV or Excel files and run the same filtering, grouping, aggregation,
  visualization, dashboard, and statistical analysis workflow on table columns.
- Replace the older CSV Summary workflow with the shared analytics workflow while retaining
  the important CSV Summary output option: separate workbook sheets for each selected
  parameter/column.

## Audit Summary

Current branch status:

- `Tools > Industrial data...` already provides source setup, reference-scoped sync,
  cached rows, report-to-production links, and a cached industrial workbook export.
- Current sync uses Oznak typed filters and selected columns through
  `modules/oznak_adapter.py`.
- Current cache tables live in `modules/industrial_data_schema.py`:
  `industrial_records` for common fields and `industrial_record_values` for dynamic
  source-specific values.
- Current industrial export in `modules/industrial_export_service.py` writes raw cached
  rows, grouped record counts, diagnostics, and one Excel count chart.
- Current grouping in `modules/industrial_workflow_state.py` is categorical only and
  limited to fixed production metadata fields.
- Current HTML dashboard support in `modules/export_html_dashboard.py` is mature, but
  it is coupled to measurement-export and group-analysis payload shapes.
- `hexafe-groupstats` is already a Metroliza runtime dependency and is bridged through
  `modules/hexafe_groupstats_adapter.py`.
- 2026-05-12 update: Metroliza now pins `hexafe-plotstats[pandas]` from a public Git
  commit and uses it through `modules/hexafe_plotstats_adapter.py` for histogram
  rendering/statistics-table reuse. Keep the adapter boundary narrow until a formal package
  release/tag replaces the temporary commit pin.
- `hexafe/ProductionDataAnalyzer` currently provides useful concepts and simple
  helpers, especially time-indexed organization, ID filtering, and period aggregation.
  It is not ready to consume directly as an application dependency: it is a single
  Colab-oriented module, its requirements omit pandas/matplotlib/gspread despite imports,
  and the current aggregation method is mean-only with code defects such as missing
  `numpy` import and `pd.error.OutOfBoundsDatetime`.

Main gaps:

- No production-only analytics screen exists.
- No user-selectable time bucket exists.
- No user-selectable aggregation method exists.
- Dynamic numeric fields stored in `industrial_record_values` are not surfaced as
  selectable analysis metrics.
- Export filtering is still reference-only; production analytics needs filter criteria
  for source, time range, reference, part, revision, station, line, operator, status,
  batch/lot, work order, and dynamic fields.
- Pasted reference lists can filter sync/export, but they do not create reusable marked
  cohorts or special plot styling.
- Industrial export charts are count-only workbook charts, not Plotly dashboards.
- Existing group analysis assumes measurement rows with `MEAS`, `GROUP`, `HEADER`, `AX`,
  and spec fields; production analytics needs a tidy production-data adapter.

## Detailed Research Notes

### Metroliza Industrial Cache

Relevant files:

- `modules/industrial_data_schema.py`
- `modules/industrial_data_repository.py`
- `modules/industrial_workflow_state.py`
- `modules/industrial_export_service.py`
- `modules/industrial_data_dialog.py`
- `modules/industrial_workers.py`

Findings:

- The local cache already has the right base tables for production-only analysis:
  `industrial_records` stores common fields and `industrial_record_values` stores
  source-specific dynamic fields.
- Useful fixed columns already exist for filtering and grouping: source, timestamp,
  reference, part number/name, revision, serial, batch/lot, work order, station, line,
  operator, and process status.
- Dynamic fields are preserved as key/value rows, but current export does not pivot
  them into selectable metrics.
- Current export loads only fixed columns from `industrial_records`; it does not expose
  dynamic numeric fields, time-range filtering, multi-field filtering, or aggregation.
- Current `IndustrialFilterState` supports reference lists only. Current
  `IndustrialGroupingState` supports fixed categorical fields only.
- `IndustrialDataDialog` is already a launcher for source setup, sync, links, and export.
  It should gain `Analyze...` without crowding the launcher.
- Current industrial long-running work uses `QThread` wrappers in `modules/industrial_workers.py`.
  Dashboard/workbook generation should follow that pattern once the service is stable.
- Existing tests cover schema creation, repository upserts, sync workers, launcher layout,
  filter parsing, grouping dialogs, and workbook export. The new analytics work should add
  parallel tests rather than weakening those paths.

Design consequence:

- Build analytics as a cache-only service over the existing SQLite tables. Do not require
  `report_metadata`, parsed reports, `report_measurements`, or accepted report-production
  links for production-only analysis.

### Metroliza Dashboard And Group Analysis

Relevant files:

- `modules/export_html_dashboard.py`
- `modules/group_analysis_service.py`
- `modules/hexafe_groupstats_adapter.py`
- `tests/test_export_html_dashboard.py`
- `tests/test_group_analysis_service.py`
- `tests/test_group_analysis_writer.py`

Findings:

- `export_html_dashboard.py` already writes a local Plotly runtime and can render
  Plotly histogram, violin, box/IQR, scatter, and trend specs.
- The existing dashboard writer is mature but measurement-oriented. Its section payloads
  assume exported CMM sections and group-analysis payloads assume workbook metric rows.
- `_normalize_group_analysis_manifest` and `_render_group_analysis` are good renderer
  references, but their current input contract is not a production analytics contract.
- `group_analysis_service.py` expects CMM measurement rows with canonical measurement
  columns and spec metadata.
- `hexafe_groupstats_adapter.analyze_group_metric(...)` is the reusable statistical seam:
  it accepts grouped numeric values and spec records, calls `hexafe-groupstats`, and returns
  Metroliza-shaped descriptive, pairwise, capability, insight, and diagnostics payloads.

Design consequence:

- Add a production dashboard manifest and writer path first. Reuse low-level Plotly helper
  ideas where practical, but avoid forcing production data into measurement section payloads.
- For groupstats, build grouped numeric samples from production data and call
  `analyze_group_metric(...)` directly. Do not depend on CMM group-analysis dataframe shape.

### Oznak Package

Relevant files in `/home/hexaf/Projects/oznak`:

- `src/oznak/query_builder.py`
- `src/oznak/filters.py`
- `src/oznak/result.py`
- `src/oznak/fetcher.py`

Findings:

- `QueryFilter` supports equality/inequality, comparison operators, LIKE/NOT LIKE,
  IN/NOT IN, and NULL checks with identifier validation.
- `QuerySpec` supports selected columns, filters, limits, date column ordering, chunk size,
  and pagination columns.
- `FetchRequest` supports profiles, filters, columns, limit, date column, and timeout.
- `fetch_records(...)` and `fetch_records_chunked(...)` return pandas dataframes with
  per-source diagnostics.
- Oznak does not currently expose a group-by, aggregate, or time-bucket query contract.

Design consequence:

- Keep live Oznak fetch as the sync step only. Run filtering, grouping, aggregation,
  cohorts, statistics, and dashboard generation against Metroliza's local cache.
- Do not add server-side aggregation to Oznak as part of the first Metroliza slice. That can
  be a later Oznak package roadmap item if cache-side performance is not enough.

### Hexafe Groupstats

Relevant files in `/home/hexaf/Projects/hexafe-groupstats`:

- `README.md`
- `src/hexafe_groupstats/api.py`
- `src/hexafe_groupstats/adapters/pandas.py`
- `src/hexafe_groupstats/adapters/metroliza.py`

Findings:

- The public API supports grouped samples through `analyze_metric(...)` and tidy pandas
  inputs through `analyze_dataframe(...)`.
- It returns typed result models and helper row adapters for descriptive stats, pairwise
  rows, post-hoc rows, capability rows, distribution rows, and structured insights.
- Spec limits are optional, but capability and centering signals require valid lower,
  nominal, and upper limits.
- Group comparison needs at least two usable non-empty numeric groups.

Design consequence:

- Use the existing Metroliza adapter for the first production stats slice. Treat missing
  production limits as "descriptive and pairwise only" with explicit diagnostics.

### Hexafe Plotstats

Relevant files in `/home/hexaf/Projects/hexafe-plotstats`:

- `README.md`
- `src/hexafe_plotstats/adapters/metroliza.py`
- `src/hexafe_plotstats/adapters/groupstats.py`
- `src/hexafe_plotstats/payloads`
- `src/hexafe_plotstats/renderers`

Findings:

- Supported chart families map well to the requested dashboard: histogram, violin, IQR/box,
  scatter, and scatter with trend.
- Matplotlib is the default backend; Rust/native rendering is explicit and optional.
- Adapters exist for Metroliza-like and groupstats-like payloads.
- 2026-05-12 update: Metroliza now depends on `hexafe-plotstats[pandas]` through an
  explicit public Git commit pin and keeps usage behind a narrow adapter.

Design consequence:

- Keep interactive dashboards in Plotly where that provides the best user workflow, and use
  the `hexafe-plotstats` adapter for reusable plot/statistics rendering where it adds value.
- Replace the temporary Git commit pin with a formal package release/tag when available.

### ProductionDataAnalyzer

Relevant repository: `https://github.com/hexafe/ProductionDataAnalyzer`.

Findings:

- The README has useful product concepts: time-indexed production data, ID/reference
  filtering, temporal aggregation, timeframe comparison, SPC/capability ideas, and
  interactive time-series visualization.
- The current implementation is Colab-oriented and not desktop-app ready:
  it imports `google.colab` and `gspread`, prints status directly, and triggers Colab file
  downloads.
- `requirements.txt` only lists archive helpers, while the module imports pandas,
  matplotlib, gspread, and Google auth packages.
- `aggregate_data(...)` supports day/week/month/year and mean only; it does not support
  hour, median, or user-selected aggregation functions.
- The current code has defects and portability risks, including a missing `numpy` import
  for `np.number` and a typo around pandas datetime exception handling.

Design consequence:

- Use ProductionDataAnalyzer as a concept source only. Reimplement the needed time-bucket,
  ID/reference-list, and export ideas in Metroliza with tests.

### Current Test Baseline To Extend

Existing test files to extend or mirror:

- `tests/test_industrial_data_schema_repository.py`
- `tests/test_industrial_export_service.py`
- `tests/test_industrial_data_dialog.py`
- `tests/test_industrial_filter_dialog.py`
- `tests/test_industrial_grouping_dialog.py`
- `tests/test_export_html_dashboard.py`
- `tests/test_group_analysis_service.py`
- `tests/test_oznak_adapter.py`

New test files proposed:

- `tests/test_industrial_analytics_state.py`
- `tests/test_industrial_analytics_service.py`
- `tests/test_industrial_analytics_dashboard.py`
- `tests/test_industrial_analytics_dialog.py`
- `tests/test_industrial_analytics_workers.py`

## Architecture Decisions

1. Cache-first analytics is the release target.
   Dashboard generation must not call live Oznak, open network/database connections, or
   require credentials.

2. Production-only analysis is first-class.
   A database with only industrial cache tables must work. Measurement tables and
   `report_metadata` must be optional.

3. Dynamic production fields are metrics.
   Numeric-looking values in `industrial_record_values` should be discoverable and selectable
   as metrics without changing the cache schema.

4. Reference cohorts are analysis state, not just filters.
   Pasted references must support highlight, isolate, compare against rest, and groupstats
   grouping modes.

5. Plotly is the first dashboard renderer.
   It already supports all requested interactive views and avoids adding a new runtime
   dependency in the first slice.

6. `hexafe-groupstats` is in scope now.
   It is already integrated and can analyze grouped production samples through the existing
   Metroliza adapter.

7. `hexafe-plotstats` is in scope after dependency gating.
   It should be added through a lazy/narrow adapter or explicit dependency update, not by
   making current dashboard generation depend on native rendering.

8. ProductionDataAnalyzer is not a dependency.
   It informs the product model only.

## Product Model

Add a new analytics workflow under `Tools > Industrial data...`:

- `Analyze...` opens a production analytics dialog.
- The dialog is cache-only. It never opens a live plant database connection.
- The dialog works with only `industrial_records` and `industrial_record_values`.
- A selected Metroliza report database is only the local cache container. Parsed reports
  and measurements are optional.
- If report-to-production links exist, they can be used as an optional filter or overlay,
  but the production-only path must not depend on them.

The user-facing flow should be:

1. Select cached production source(s).
2. Choose filters.
3. Choose metrics from fixed numeric fields and dynamic source fields.
4. Choose grouping dimensions and optional pasted reference cohort.
5. Choose time bucket: raw rows, hour, day, week, month, or year.
6. Choose aggregation method per metric or a global default.
7. Preview row counts and selected groups.
8. Generate dashboard and optionally workbook output.

## Data Contracts

Add pure state/contracts in a new module, for example `modules/industrial_analytics_state.py`.

Core state objects:

- `ProductionFilterState`
  - source profile ids or aliases
  - time range
  - reference values
  - part number/name/revision
  - serial, batch/lot, work order
  - station, line, operator, process status
  - dynamic field filters from `industrial_record_values`
- `ProductionMetricSelection`
  - metric field name
  - display label
  - source: fixed column, raw record field, or dynamic value field
  - numeric coercion policy
  - optional limits source
- `ProductionAggregationState`
  - time bucket: `none`, `hour`, `day`, `week`, `month`, `year`
  - aggregation method: `mean`, `median`, `count`, `sum`, `min`, `max`, `std`,
    `p05`, `p95`, `first`, `last`
  - group fields
  - include raw row count in every aggregate row
- `ReferenceCohortState`
  - pasted reference list
  - label
  - color/style key
  - mode: highlight only, create group, isolate cohort, or compare cohort vs rest
- `ProductionChartSelection`
  - enabled chart families: histogram, time series, violin, box, groupstats tables
  - selected metrics
  - selected grouping
  - reference cohort display mode

Use pandas for the first implementation. Oznak currently fetches records safely, but it
does not expose server-side aggregation contracts. Local cached analytics is simpler,
testable, and avoids changing live database query behavior.

## Service Layer

Add `modules/industrial_analytics_service.py`.

Responsibilities:

- `load_production_analytics_frame(db_file, filter_state, metric_selection)`
  - reads `industrial_records`
  - pivots selected `industrial_record_values` into columns
  - preserves fixed metadata fields
  - coerces selected metric columns to numeric
  - parses `process_timestamp` to datetime
- `apply_production_filters(frame, filter_state)`
  - handles categorical filters and time range
  - keeps filter logic independent of Qt widgets
- `apply_reference_cohorts(frame, cohort_state)`
  - adds `reference_marked` boolean
  - adds `reference_cohort` label such as `Selected references` / `Other`
  - preserves pasted-list order for dashboard legends where practical
- `aggregate_production_frame(frame, aggregation_state)`
  - maps bucket values deterministically:
    - hour: `h`
    - day: `D`
    - week: Monday-start bucket computed from timestamp weekday
    - month: `MS`
    - year: `YS`
  - applies selected aggregation methods
  - returns both aggregate rows and diagnostics
- `build_production_groupstats_inputs(frame, metric, group_fields, cohort_state)`
  - creates tidy/grouped inputs for `hexafe-groupstats`
  - supports cohort-vs-rest and selected grouping dimensions
- `build_production_dashboard_manifest(...)`
  - returns a renderer-neutral manifest with chart payloads, tables, diagnostics,
    and reference-mark styling metadata.

This service must be fully testable without PyQt.

## Dashboard And Plotting

Start with a production-specific HTML dashboard writer, then consolidate later if it
becomes clear that `export_html_dashboard.py` can safely accept generic chart sections.

Initial dashboard:

- Summary header:
  - cached rows scanned
  - rows after filters
  - selected metrics
  - aggregation bucket/method
  - active reference cohort count
- Time series:
  - raw or aggregated values over time
  - split by selected group or cohort
  - marked references use distinct marker symbol/color and hover text
- Histograms:
  - raw or aggregated metric values
  - optional overlay for selected references vs other references
- Violin plots:
  - grouped by selected group fields or reference cohort
- Box plots:
  - same grouping as violin, useful for compact comparison
- Groupstats section:
  - descriptive stats
  - selected omnibus/pairwise test names
  - adjusted p-values/effect sizes
  - capability rows when valid limits exist
  - structured insight headline and first action

Plot implementation order:

1. Use Plotly directly for the production-only dashboard because it already supports
   interactive hover, zoom, legends, marker styling, histograms, time series, violin,
   and box plots.
2. Add `hexafe-plotstats` only behind a small adapter once dependency/release pinning is
   accepted. Target reusable payloads first: histogram, violin, IQR/box, scatter/trend.
3. Keep Metroliza's current measurement dashboard intact during this work.

## UI Plan

Add `modules/industrial_analytics_dialog.py`.

Follow the current Metroliza industrial UI split:

- Keep `IndustrialDataDialog` as a compact launcher/status window.
- Add an `Analyze...` action next to `Export...`.
- Do not put all analytics controls in the launcher.

Analytics dialog layout:

- Top status rows:
  - selected cache database
  - cached row count
  - active source(s)
  - rows matching current filter
- Controls:
  - `Metrics...` opens metric picker
  - `Filters...` opens production filter dialog
  - `References...` opens pasted reference cohort dialog
  - `Grouping...` opens grouping dialog
  - aggregation bucket segmented/dropdown control
  - aggregation method dropdown
  - chart family checkboxes
  - output dashboard path
- Primary action:
  - `Create dashboard`
- Optional action:
  - `Create workbook and dashboard`

Add focused subdialogs only where needed:

- `IndustrialProductionFilterDialog`
- `IndustrialMetricSelectionDialog`
- `IndustrialReferenceCohortDialog`
- reuse or extend `IndustrialGroupingDialog` only if it can clearly support dynamic
  fields and aggregation grouping without confusing export grouping.

## Reference Marking And Cohorts

The pasted reference list should become first-class analysis state, not just a filter.

Implement behavior:

- Parse comma, semicolon, tab, newline, and whitespace lists.
- De-duplicate in input order.
- Show count and first few references.
- Let user choose:
  - highlight selected references on plots
  - compare selected references against all other rows
  - filter to selected references only
  - create selected-reference group for groupstats
- Persist only if user explicitly saves a cohort; otherwise keep it dialog-local.

Suggested optional persistence tables:

- `industrial_reference_cohorts`
  - id, name, color, created_at, updated_at, settings_json
- `industrial_reference_cohort_items`
  - cohort_id, reference, position

Do not require persistence for the first usable version. Dialog-local state is enough
for pasted-list highlighting and one dashboard export.

## ProductionDataAnalyzer Usage Decision

Do not import `ProductionDataAnalyzer.py` directly into Metroliza.

Use it as a concept source only:

- time-indexed dataset organization
- ID/reference list filtering
- temporal aggregation periods
- CSV/workbook export of aggregated rows

Reimplement the needed parts in Metroliza's service layer with tests and desktop-safe
dependencies. If the analyzer later becomes a package with tests, imports separated
from Google Colab, and clean dependencies, it can be reconsidered as a shared package.

## Detailed Implementation Task Plan

## Implementation Progress

Last updated: 2026-05-11

- Step 0 status: completed.
  - Added reusable cached-production test fixtures in
    `tests/industrial_analytics_fixtures.py`.
  - Fixtures seed a production-only SQLite cache with fixed metadata, dynamic numeric
    fields, dynamic text fields, multiple references, multiple sources of grouping
    variation, and optional minimal report/link tables for later linked-context tests.
- Step 1 status: completed.
  - Added `modules/industrial_analytics_state.py` with Qt-free contracts for production
    filters, dynamic field filters, metric selections, aggregation state, reference
    cohorts, chart selections, full analytics requests, and readiness validation.
  - Added `tests/test_industrial_analytics_state.py`.
  - Validation passed:
    `python -m ruff check modules/industrial_analytics_state.py tests/test_industrial_analytics_state.py tests/industrial_analytics_fixtures.py`
    and
    `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_analytics_state.py -q`.
- Audit after Step 1: the plan remains valid. The only execution adjustment is that the
  reusable fixture helper was added before service tests; Step 2 will now use that fixture
  to prove production-only loading and metric discovery.
- Step 2 status: completed.
  - Added `modules/industrial_analytics_service.py` with metric discovery and cached
    production frame loading.
  - Dynamic numeric fields in `industrial_record_values` are now discoverable as metrics,
    mostly numeric fields are allowed with warnings, and all-text fields are skipped.
  - Selected dynamic metrics are pivoted onto production rows, timestamps are parsed into
    `process_datetime`, selected metrics are coerced numeric, and missing metrics produce
    diagnostics instead of crashes.
  - Added `tests/test_industrial_analytics_service.py`.
  - Validation passed:
    `python -m ruff check modules/industrial_analytics_state.py modules/industrial_analytics_service.py tests/test_industrial_analytics_state.py tests/test_industrial_analytics_service.py tests/industrial_analytics_fixtures.py`
    and
    `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_analytics_state.py tests/test_industrial_analytics_service.py -q`.
- Audit after Step 2: the plan remains valid. Step 3 should extend the same service module
  with dynamic-field filters and row-count diagnostics rather than adding a separate filter
  engine module.
- Step 3 status: completed.
  - Added `apply_production_filters(...)` and dynamic-filter handling inside
    `load_production_analytics_frame(...)`.
  - Fixed-field filters, parsed timestamp ranges, dynamic numeric comparisons, and dynamic
    text filters now return diagnostics instead of crashing on missing fields.
- Step 4 status: completed.
  - Added `aggregate_production_frame(...)` with raw row-level output and grouped/time-bucket
    aggregation for mean, median, count, sum, min, max, std, p05, p95, first, and last.
  - Week aggregation now computes Monday-start buckets explicitly instead of relying on the
    ambiguous pandas `W-MON` period shorthand.
- Step 5 status: completed.
  - Added `apply_reference_cohorts(...)` with highlight, compare-rest, filter-selected, and
    group-selected-ready columns.
  - Missing pasted references are reported in diagnostics.
  - Validation passed:
    `python -m ruff check modules/industrial_analytics_state.py modules/industrial_analytics_service.py tests/test_industrial_analytics_state.py tests/test_industrial_analytics_service.py tests/industrial_analytics_fixtures.py`
    and
    `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_analytics_state.py tests/test_industrial_analytics_service.py -q`.
- Audit after Step 5: the plan remains valid. Step 6 can build dashboard manifests directly
  from the service results; no extra persistence tables are needed for the first cohort slice.
- Scope addition from 2026-05-11 user review:
  - Add CSV/Excel files as a second analytics source alongside cached Oznak production data.
  - Reuse the same grouping, aggregation, dashboards, charts, and groupstats paths.
  - Treat this as the replacement direction for the current CSV Summary module.
  - Preserve a workbook option that creates separate sheets for each selected CSV/Excel
    parameter column.
  - Implementation adjustment: introduce a generic tabular analytics loader/exporter after
    the production dashboard writer, then wire both Oznak and file sources into one UI.
- Step 6 status: completed.
  - Added `build_production_dashboard_manifest(...)` in
    `modules/industrial_analytics_dashboard.py`.
  - The manifest contains summary cards, chart specs, metric metadata, diagnostics, and
    selected-reference styling metadata without exposing raw cached JSON.
- Step 7 status: completed.
  - Added `write_production_dashboard(...)` with offline local Plotly asset copying.
  - Added `tests/test_industrial_analytics_dashboard.py`.
  - Validation passed:
    `python -m ruff check modules/industrial_analytics_state.py modules/industrial_analytics_service.py modules/industrial_analytics_dashboard.py tests/test_industrial_analytics_state.py tests/test_industrial_analytics_service.py tests/test_industrial_analytics_dashboard.py tests/industrial_analytics_fixtures.py`
    and
    `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_analytics_state.py tests/test_industrial_analytics_service.py tests/test_industrial_analytics_dashboard.py -q`.
- Audit after Step 7: the plan remains valid, with the user-requested CSV/Excel source now
  promoted to Step 11. The dashboard writer is dataframe-based enough to be reused for
  file analytics after a small normalization loader.
- Step 11 status: service/export slice completed ahead of UI wiring.
  - Added `modules/tabular_analytics_service.py` for CSV/Excel analytics input.
  - CSV loading reuses the existing encoding/delimiter fallback helper; Excel loading
    supports a selected sheet.
  - Table columns are normalized into safe analytics identifiers while preserving an
    original-to-normalized mapping for UI labels.
  - Timestamp and reference/id columns are inferred or can be selected explicitly.
  - Numeric columns are discovered as selectable metrics and can reuse the same
    aggregation and dashboard manifest path as cached production data.
  - Added workbook export with `Table Data`, `Aggregates`, `Metrics`, `Diagnostics`, and
    optional one-sheet-per-parameter output for selected CSV/Excel columns.
  - Excel export now strips timezone metadata from workbook-bound datetime columns because
    Excel does not support timezone-aware datetimes.
  - Added `tests/test_tabular_analytics_service.py`.
  - Validation passed:
    `python -m ruff check modules/tabular_analytics_service.py tests/test_tabular_analytics_service.py`
    and
    `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_tabular_analytics_service.py -q`.
- Audit after Step 11 service/export slice: the plan remains valid. Remaining Step 11 work
  is UI replacement wiring for CSV Summary and shared source selection; the service contract
  is ready to be consumed by the same dashboard/statistics/workbook workflow as production
  cache data.
- Step 8 status: completed.
  - Added `build_production_groupstats_inputs(...)` and
    `analyze_production_groupstats(...)` in `modules/industrial_analytics_service.py`.
  - Groupstats input can group by one field, multiple fields, time bucket, selected
    reference cohort, or selected-reference-vs-rest cohorts.
  - Non-numeric and non-finite metric values are dropped per group.
  - Missing metrics, missing group fields, bad timestamps, low sample groups, all-null
    metrics, and insufficient groups now produce diagnostics instead of crashes.
  - The wrapper calls the existing `hexafe_groupstats_adapter.analyze_group_metric(...)`
    and removes the non-serializable backend result object from dashboard payloads.
  - Production limits/specs remain absent in this slice, so capability is intentionally
    unavailable unless a future limits source is added.
  - Dashboard manifests now carry groupstats metric payloads, descriptive rows, pairwise
    rows, insights, and diagnostics, and the HTML writer renders compact stats tables.
  - Validation passed:
    `python -m ruff check modules/industrial_analytics_service.py modules/industrial_analytics_dashboard.py tests/test_industrial_analytics_service.py tests/test_industrial_analytics_dashboard.py`
    and
    `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_analytics_service.py tests/test_industrial_analytics_dashboard.py -q`.
- Audit after Step 8: the plan remains valid. Step 9 should consume the now-stable
  dataframe/groupstats/dashboard service from a Qt worker and dialog instead of adding more
  statistics behavior first.
- Step 9 status: completed for first usable production/file analytics UI.
  - Added `modules/industrial_analytics_workflow.py` as the shared end-to-end entry point
    for cached production data and CSV/Excel files.
  - Added `IndustrialAnalyticsThread` in `modules/industrial_workers.py`.
  - Added `modules/industrial_analytics_dialog.py` with source-aware production and
    CSV/Excel modes, metric loading, metric selection, grouping, time bucket selection,
    aggregation method selection, reference cohort modes, chart toggles, groupstats toggle,
    dashboard path, workbook path, and separate-parameter-sheet option.
  - Added `Analyze...` to the existing `IndustrialDataDialog` launcher.
  - Routed the existing `CSV Summary...` tools-menu action to the new CSV/Excel analytics
    dialog while keeping the menu label stable for users and existing UI expectations.
  - Added `tests/test_industrial_analytics_dialog.py`.
- Step 10 status: completed.
  - Added `modules/industrial_analytics_workbook.py` for production analytics workbook
    output.
  - Production workbooks now include `Production Data`, optional `Aggregates`, `Metrics`,
    optional `Groupstats`, `Diagnostics`, and optional one-sheet-per-selected-metric output.
  - Production workbook output omits cached `raw_record_json` payloads.
  - CSV/Excel analytics workbooks already include `Table Data`, optional `Aggregates`,
    `Metrics`, `Diagnostics`, and one-sheet-per-selected-parameter output through the
    tabular service.
- Step 11 status: completed for the shared-service and first UI replacement path.
  - CSV/Excel input can now be loaded from the new analytics dialog and analyzed through
    the same grouping, aggregation, dashboard, groupstats, and workbook workflow as
    cached production data.
  - The old CSV Summary action now opens the shared analytics path, preserving the
    requested per-parameter workbook-sheet behavior.
  - Validation passed:
    `python -m ruff check modules/industrial_analytics_state.py modules/industrial_analytics_service.py modules/industrial_analytics_dashboard.py modules/industrial_analytics_workbook.py modules/industrial_analytics_workflow.py modules/tabular_analytics_service.py modules/industrial_analytics_dialog.py modules/industrial_workers.py modules/industrial_data_dialog.py modules/main_window.py tests/test_industrial_analytics_state.py tests/test_industrial_analytics_service.py tests/test_industrial_analytics_dashboard.py tests/test_industrial_analytics_workflow.py tests/test_industrial_analytics_dialog.py tests/test_tabular_analytics_service.py tests/industrial_analytics_fixtures.py`
    and
    `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_analytics_state.py tests/test_industrial_analytics_service.py tests/test_industrial_analytics_dashboard.py tests/test_industrial_analytics_workflow.py tests/test_industrial_analytics_dialog.py tests/test_tabular_analytics_service.py tests/test_main_window_metadata_ui.py tests/test_industrial_data_dialog.py -q`.
- Step 12 status: partially completed on 2026-05-12.
  - The shipped dashboard path keeps offline Plotly for interactive histogram, time-series,
    violin, and box views.
  - `hexafe-plotstats` is now pinned as a runtime dependency and used through
    `modules/hexafe_plotstats_adapter.py` for histogram rendering/statistics-table reuse.
  - Remaining follow-up: replace the temporary Git commit pin with a formal package
    release/tag when available.
- Step 13 status: completed for implementation notes and validation record; release-note
  publication remains separate from this feature implementation unless requested.
- Final validation:
  - `python -m ruff check .`
  - `python -m compileall -q -x '^\\./\\.git/' .`
  - `python scripts/sync_release_metadata.py --check`
  - `python scripts/check_release_hygiene.py`
  - `QT_QPA_PLATFORM=offscreen python -m pytest -q`
  - Full pytest result: 1360 passed, 53 skipped, 7 warnings, 60 subtests passed in
    68.51 seconds.
- Final audit: the core requested workflow is now functional for cached production rows
  and CSV/Excel files. Dashboards avoid raw cached JSON and CDN assets; production
  workbooks now omit raw cached JSON. The first implementation intentionally keeps
  advanced fixed-field/dynamic-field filters in the service contract; the dialog currently
  exposes reference/cohort filtering plus grouping and aggregation controls.

### Step 0: Baseline Fixtures And Guardrails

Goal:

- Establish reliable fixtures for cache-only production analytics before adding behavior.

Primary files:

- `tests/test_industrial_analytics_service.py`
- `tests/test_industrial_analytics_dashboard.py`
- `tests/test_industrial_analytics_dialog.py`
- `tests/test_industrial_data_schema_repository.py`

Tasks:

1. Create a fixture helper that initializes only industrial cache tables in a fresh SQLite
   database.
2. Seed records with fixed metadata fields and dynamic numeric fields:
   `cycle_time_s`, `temperature_c`, `force_n`, `pressure_bar`, `cavity`, and `defect_count`.
3. Seed records across multiple timestamps so hour/day/week/month/year buckets can be tested.
4. Seed records across multiple references, stations, lines, operators, process statuses, and
   batches.
5. Seed at least one all-text dynamic field and one mostly-numeric dynamic field to validate
   metric discovery thresholds.
6. Add a fixture database with no report/measurement tables to prove production-only analytics
   does not touch CMM schema.
7. Add a fixture database with industrial cache plus report metadata/link tables to prove the
   optional linked-report path still works later.
8. Add regression tests that analytics service calls do not fail when `report_metadata` is
   absent.
9. Add a test that analytics dashboard generation does not import or call live Oznak fetch
   functions.
10. Document fixture expectations inside the test helper, not in application code.

Exit criteria:

- Tests can create representative production-only databases without external files,
  credentials, Oznak connections, report metadata, or measurements.

### Step 1: Analytics State And Contracts

Goal:

- Add pure, Qt-free contracts that describe filters, metrics, aggregation, chart selection,
  and reference cohorts.

Primary files:

- `modules/industrial_analytics_state.py`
- `tests/test_industrial_analytics_state.py`
- `modules/industrial_workflow_state.py` for shared reference parsing only if needed

Tasks:

1. Add `ProductionFilterState`.
2. Add source-profile filtering by id and alias.
3. Add fixed-field filters for reference, part number/name, revision, serial, batch/lot,
   work order, station, line, operator, and process status.
4. Add time-range fields with inclusive start and exclusive end semantics.
5. Add dynamic-field filter records with field name, operator, value, and value kind.
6. Add `ProductionMetricSelection` with field name, display label, source kind, and numeric
   coercion policy.
7. Add `ProductionAggregationState` with time bucket, aggregation methods, group fields, and
   "include raw rows" flag.
8. Add supported bucket enum values: `none`, `hour`, `day`, `week`, `month`, `year`.
9. Add supported aggregation enum values: `mean`, `median`, `count`, `sum`, `min`, `max`,
   `std`, `p05`, `p95`, `first`, and `last`.
10. Add `ReferenceCohortState` with pasted references, label, color/style key, and mode.
11. Add cohort modes: `highlight`, `compare_rest`, `filter_selected`, and `group_selected`.
12. Add `ProductionChartSelection` for histogram, time series, violin, box, and groupstats.
13. Add validation helpers that return user-facing messages instead of raising where the UI
   needs readiness status.
14. Add serialization helpers only if UI persistence or worker handoff needs them.
15. Keep state objects frozen dataclasses where practical, matching existing state style.

Tests:

1. Reference parsing accepts comma, semicolon, tab, newline, and whitespace separators.
2. Reference parsing de-duplicates while preserving input order.
3. Unsupported bucket and aggregation values are rejected.
4. Invalid dynamic-field identifiers are rejected before SQL construction.
5. Empty metric selection produces a readiness warning, not a crash.

Exit criteria:

- All analytics decisions can be represented without Qt widgets and without database access.

### Step 2: Production Frame Loader And Metric Discovery

Goal:

- Load fixed and dynamic production fields into a pandas dataframe suitable for analytics.

Primary files:

- `modules/industrial_analytics_service.py`
- `tests/test_industrial_analytics_service.py`

Tasks:

1. Add `discover_production_metric_candidates(db_file, filter_state=None)`.
2. Add fixed numeric candidates from `industrial_records` where values are numeric or
   numeric-looking.
3. Add dynamic numeric candidates from `industrial_record_values`.
4. Use a conservative numeric threshold for dynamic fields, for example at least 80 percent
   parseable numeric values and a minimum non-null count.
5. Return candidate metadata: field name, label, source kind, source profile coverage,
   non-null count, numeric count, sample values, and warning flags.
6. Add `load_production_analytics_frame(db_file, filter_state, metric_selection)`.
7. Read fixed columns from `industrial_records`.
8. Pivot selected dynamic fields from `industrial_record_values` into dataframe columns.
9. Preserve `industrial_record_id`, `source_profile_id`, `source_db_alias`, and
   `source_record_key`.
10. Parse `process_timestamp` into a datetime column without failing the whole load on bad
    values.
11. Coerce selected metric columns with `pd.to_numeric(errors="coerce")`.
12. Add diagnostics for missing selected metrics, bad timestamps, non-numeric values, and
    empty data.
13. Use parameterized SQL and temporary tables for large pasted reference lists when needed.
14. Keep schema initialization explicit: analytics should check for industrial tables and
    return a clear diagnostic when cache is missing.

Tests:

1. Dynamic fields pivot into stable columns.
2. Text dynamic fields are not offered as numeric metrics.
3. Mostly numeric dynamic fields are offered and non-numeric values become nulls.
4. Production-only databases without CMM tables load successfully.
5. Missing cache tables produce a clear unavailable-cache diagnostic.
6. Selected metrics absent from one source produce warnings, not crashes.

Exit criteria:

- The service can return a clean dataframe and metric list from only cached Oznak data.

### Step 3: Filtering Engine

Goal:

- Support practical user filtering before aggregation and plotting.

Primary files:

- `modules/industrial_analytics_service.py`
- `tests/test_industrial_analytics_service.py`

Tasks:

1. Add `apply_production_filters(frame, filter_state)`.
2. Implement fixed-field include-list filters.
3. Implement source profile filters by id and alias.
4. Implement time range filtering on parsed process timestamps.
5. Implement reference filters using normalized pasted lists.
6. Implement dynamic-field filters for equality, inequality, comparison, contains, starts
   with, ends with, in-list, and null/not-null.
7. Add case sensitivity policy and document it in diagnostics. Default should be
   case-insensitive for text fields.
8. Add numeric comparison only after numeric coercion.
9. Add skipped-filter diagnostics for fields that are not present in the loaded frame.
10. Add row-count diagnostics before and after each filter category.
11. Keep UI-neutral filter labels for summary display.

Tests:

1. Time range filters include the start and exclude the end.
2. Multiple fixed filters combine with AND semantics.
3. Multi-value filters use OR semantics inside one field.
4. Dynamic numeric comparisons work.
5. Dynamic text contains/in-list filters work.
6. Missing fields are reported and do not crash dashboard creation.

Exit criteria:

- The service can narrow cached production data by the requested practical criteria.

### Step 4: Aggregation Engine

Goal:

- Aggregate production metrics by selected time buckets, group fields, and methods.

Primary files:

- `modules/industrial_analytics_service.py`
- `tests/test_industrial_analytics_service.py`

Tasks:

1. Add `aggregate_production_frame(frame, aggregation_state, metric_selection)`.
2. Map time buckets deterministically:
   - `hour`: `h`
   - `day`: `D`
   - `week`: Monday-start bucket computed from timestamp weekday
   - `month`: `MS`
   - `year`: `YS`
3. Support `none` bucket for row-level analysis.
4. Include selected group fields in the groupby keys.
5. Include reference cohort fields in groupby keys when cohort grouping is enabled.
6. Implement aggregation methods:
   - `mean`
   - `median`
   - `count`
   - `sum`
   - `min`
   - `max`
   - `std`
   - `p05`
   - `p95`
   - `first`
   - `last`
7. Always include `raw_row_count` for aggregate rows.
8. Decide output column naming before UI work, for example
   `<metric>__<method>` for multi-method output.
9. Preserve display labels in metadata so dashboards show friendly names.
10. Add deterministic sorting by group fields and bucket start.
11. Add diagnostics for empty buckets, invalid timestamps, all-null metrics, and unsupported
    aggregation requests.
12. Add a small helper to format bucket labels for dashboards and workbook sheets.

Tests:

1. Hour/day/week/month/year buckets are deterministic.
2. Week buckets start on Monday.
3. Mean and median are correct with uneven groups.
4. Count counts numeric values, while raw row count counts source rows.
5. Percentiles are deterministic.
6. `none` bucket preserves row-level values.
7. Empty metric columns produce skipped diagnostics.

Exit criteria:

- The service can return raw or aggregated production analysis rows for dashboard and export.

### Step 5: Reference Cohorts And Plot Marking

Goal:

- Turn pasted references into reusable analysis columns and visual styling metadata.

Primary files:

- `modules/industrial_analytics_state.py`
- `modules/industrial_analytics_service.py`
- `tests/test_industrial_analytics_state.py`
- `tests/test_industrial_analytics_service.py`

Tasks:

1. Add `apply_reference_cohorts(frame, cohort_state)`.
2. Add `reference_marked` boolean column.
3. Add `reference_cohort` label column.
4. Add optional `reference_cohort_order` column for stable legend ordering.
5. Add normalized reference matching that treats whitespace consistently.
6. Add diagnostics for references that were pasted but not found in current data.
7. Implement `highlight` mode without filtering data.
8. Implement `filter_selected` mode.
9. Implement `compare_rest` mode by labeling selected rows and all other rows.
10. Implement `group_selected` mode for groupstats grouping.
11. Add style metadata: selected color, selected marker symbol, rest opacity, and legend
    labels.
12. Keep persistence out of first release unless UI review says saved cohorts are required.
13. If persistence is later added, use new tables `industrial_reference_cohorts` and
    `industrial_reference_cohort_items`.

Tests:

1. Pasted references mark matching rows.
2. Missing references are reported.
3. Highlight mode leaves row count unchanged.
4. Filter mode removes non-selected references.
5. Compare-rest mode creates exactly two groups when both sides exist.
6. Cohort grouping feeds groupstats with selected/rest labels.

Exit criteria:

- Every downstream chart and analysis can distinguish selected references from the rest.

### Step 6: Production Dashboard Manifest

Goal:

- Define renderer-neutral dashboard data before building UI.

Primary files:

- `modules/industrial_analytics_service.py`
- `modules/industrial_analytics_dashboard.py`
- `tests/test_industrial_analytics_dashboard.py`

Tasks:

1. Add `build_production_dashboard_manifest(...)`.
2. Include top-level summary: source count, row counts, metric count, selected bucket,
   aggregation methods, active filters, and cohort summary.
3. Include diagnostics in a structured list with severity: info, warning, skipped, error.
4. Add chart sections for each selected metric.
5. Add time-series payloads using raw rows or aggregate rows based on state.
6. Add histogram payloads with selected/rest overlays when cohort highlighting is active.
7. Add violin payloads grouped by selected group fields or cohort labels.
8. Add box payloads with the same grouping policy as violin.
9. Add groupstats payload references when available.
10. Add table payloads for aggregates and groupstats summaries.
11. Add manifest version and settings snapshot for reproducibility.
12. Keep raw record JSON out of the manifest by default.
13. Cap oversized payloads with a visible diagnostic or use downsampling for scatter/time
    series if needed.

Tests:

1. Manifest includes all requested chart families.
2. Manifest works with raw row-level mode.
3. Manifest works with aggregated mode.
4. Manifest includes selected-reference styling metadata.
5. Manifest omits raw JSON and credentials.
6. Empty data produces a dashboard-ready skipped state.

Exit criteria:

- A complete dashboard can be generated from a manifest without direct database access.

### Step 7: Plotly Production Dashboard Writer

Goal:

- Generate the requested interactive production dashboard from the manifest.

Primary files:

- `modules/industrial_analytics_dashboard.py`
- `modules/export_html_dashboard.py` only if reusable helpers are extracted safely
- `tests/test_industrial_analytics_dashboard.py`
- `tests/test_export_html_dashboard.py`

Tasks:

1. Reuse the local Plotly asset copy approach from `export_html_dashboard.py`.
2. Add a production dashboard HTML template or writer function.
3. Render overview cards for rows scanned, rows after filters, active metrics, bucket,
   aggregation method, and selected-reference count.
4. Render time-series charts.
5. Render histograms.
6. Render violin plots.
7. Render box plots.
8. Render groupstats tables and insight panels when present.
9. Apply selected-reference markers on time series.
10. Apply selected/rest overlays for histograms.
11. Apply selected/rest or selected group styling on violin and box plots.
12. Add hover data for reference, source, station, timestamp, group label, and metric value.
13. Add empty-state panels for skipped charts.
14. Keep the dashboard offline-capable by avoiding CDN assets.
15. Keep the current measurement dashboard unchanged.

Tests:

1. HTML file and asset directory are written.
2. Plotly is local, not CDN.
3. Expected chart count is reported.
4. Selected references appear as a distinct trace or marker style.
5. Dashboard renders without measurements or report metadata.
6. Dashboard does not expose raw credentials or raw record JSON.

Exit criteria:

- Users can create a standalone production analytics HTML dashboard from cached Oznak data.

### Step 8: Production Groupstats Adapter

Goal:

- Analyze production metrics by selected groups and reference cohorts.

Primary files:

- `modules/industrial_analytics_service.py`
- `modules/hexafe_groupstats_adapter.py` only if a small shared helper is needed
- `tests/test_industrial_analytics_service.py`

Tasks:

1. Add `build_production_groupstats_inputs(frame, metric, group_fields, cohort_state)`.
2. Build grouped numeric arrays from raw or aggregated production values.
3. Support group labels from one field, multiple fields, time bucket, and cohort.
4. Support cohort-vs-rest comparison.
5. Drop null/non-finite values per group.
6. Require at least two non-empty groups for pairwise/statistical comparisons.
7. Pass optional spec records when valid limits are available later.
8. For the first release, mark capability unavailable unless production limits are explicitly
   provided.
9. Call `analyze_group_metric(...)`.
10. Convert returned descriptive, pairwise, capability, and insight payloads into dashboard
    manifest sections.
11. Add diagnostics for insufficient groups, low sample size, missing specs, and all-null
    metrics.
12. Keep Monte Carlo/simulation off by default for interactive performance.

Tests:

1. Selected-reference vs rest comparison works.
2. Station or line grouping works.
3. Multi-field grouping labels are deterministic.
4. Insufficient groups produce skipped diagnostics.
5. Missing specs do not crash and capability is clearly unavailable.
6. Pairwise rows and descriptive rows appear in dashboard manifest.

Exit criteria:

- Production dashboards can include groupstats results when grouping data is sufficient.

### Step 9: Analytics UI Workflow

Goal:

- Add a compact user workflow for configuring and running production analytics.

Primary files:

- `modules/industrial_data_dialog.py`
- `modules/industrial_analytics_dialog.py`
- `modules/industrial_analytics_workers.py`
- Optional focused subdialogs:
  - `modules/industrial_metric_selection_dialog.py`
  - `modules/industrial_production_filter_dialog.py`
  - `modules/industrial_reference_cohort_dialog.py`
  - `modules/industrial_analytics_grouping_dialog.py`
- Tests:
  - `tests/test_industrial_data_dialog.py`
  - `tests/test_industrial_analytics_dialog.py`
  - `tests/test_industrial_analytics_workers.py`

Tasks:

1. Add an `Analyze...` button to `IndustrialDataDialog`.
2. Add `IndustrialAnalyticsDialog`.
3. Keep launcher surface compact and do not place all analytics controls on the launcher.
4. Show cache status, source count, cached row count, selected metric count, rows after
   filters, and output path.
5. Add `Metrics...` action.
6. Add `Filters...` action.
7. Add `References...` action.
8. Add `Grouping...` action.
9. Add bucket dropdown or segmented control: raw rows, hour, day, week, month, year.
10. Add aggregation method dropdown with mean and median visible first.
11. Add advanced aggregation options for count, sum, min, max, std, p05, p95, first, last.
12. Add chart-family checkboxes for time series, histogram, violin, box, and groupstats.
13. Add output dashboard path selector.
14. Add optional workbook path selector only after dashboard generation is stable.
15. Add readiness validation requiring cache database, at least one metric, at least one chart,
    and output path.
16. Run dashboard generation in a worker thread.
17. Emit progress/status messages from service phases.
18. Keep normal Windows laptop viewport sizing within existing UI constraints.
19. Add offscreen layout tests that no initial dialog clips its size hint.

Tests:

1. Launcher opens analytics dialog.
2. `Analyze...` is disabled without a selected database, matching export/sync behavior.
3. Readiness requires required inputs.
4. Metric discovery populates metric controls from dynamic cache values.
5. Aggregation controls map to state objects.
6. Reference dialog parses pasted lists and updates cohort state.
7. Worker emits result and error signals.
8. Dialog size hint fits initial width/height.

Exit criteria:

- A user can configure and create a production analytics dashboard through the app.

### Step 10: Workbook Export Extension

Goal:

- Add optional workbook output that mirrors dashboard data for users who need Excel.

Primary files:

- `modules/industrial_export_service.py`
- `modules/industrial_analytics_service.py`
- `tests/test_industrial_export_service.py`
- `tests/test_industrial_analytics_service.py`

Tasks:

1. Decide whether workbook output belongs in current `IndustrialExportDialog` or the new
   analytics dialog.
2. Add an export function for analytics output, for example
   `export_production_analytics_workbook(...)`.
3. Add `Production Data` sheet for filtered raw rows.
4. Add `Production Aggregates` sheet for aggregate rows.
5. Add `Production Group Stats` sheet for descriptive and pairwise results.
6. Add `Production Dashboard Diagnostics` sheet.
7. Add a `Settings` sheet with filters, grouping, bucket, aggregation, metrics, and cohort
   summary.
8. Keep current industrial raw workbook export backward compatible.
9. Avoid workbook chart work until dashboard chart behavior is accepted.

Tests:

1. Workbook writes expected sheets.
2. Raw-only production data works.
3. Aggregated output works.
4. Groupstats sheet is omitted or empty with clear diagnostics when unavailable.
5. Existing industrial workbook export tests keep passing.

Exit criteria:

- Excel users can inspect the same filtered/aggregated production analytics data used by
  the dashboard.

### Step 11: CSV/Excel Analytics Source And CSV Summary Replacement

Goal:

- Let a user open CSV or Excel data and run the same analytics path used for cached
  production data.

Primary files:

- `modules/tabular_analytics_service.py`
- `modules/industrial_analytics_service.py`
- `modules/industrial_analytics_dashboard.py`
- `modules/industrial_analytics_dialog.py` as the shared CSV/Excel and production-cache launcher
- `tests/test_tabular_analytics_service.py`
- `tests/test_industrial_analytics_dashboard.py`

Tasks:

1. Add a file loader for `.csv`, `.xlsx`, and `.xls`.
2. For CSV, reuse existing delimiter/decimal detection where practical from
   `modules/csv_summary_utils.py`.
3. For Excel, support sheet selection, defaulting to the first sheet.
4. Infer numeric metric candidates from table columns using the same numeric threshold logic
   as dynamic production fields.
5. Let the user choose optional time/date and reference/id columns.
6. Normalize loaded tables to the analytics dataframe contract:
   `process_datetime`, `reference`, source/file metadata, selected numeric metric columns,
   and original grouping columns.
7. Reuse filtering, reference cohorts, aggregation, dashboard manifest, dashboard writer, and
   groupstats functions.
8. Add workbook export for tabular analytics.
9. Add an option to create a separate sheet for each selected parameter/column.
10. Include overview, aggregate, groupstats, diagnostics, and settings sheets.
11. Keep the old CSV Summary tests passing until the new workflow fully replaces the UI
    launcher.
12. Update user manual wording from CSV Summary to the new analytics file workflow when the
    replacement UI ships.

Tests:

1. CSV load detects numeric metric columns.
2. Excel load detects numeric metric columns.
3. A CSV dataframe can create the same dashboard chart families as production data.
4. Aggregation and grouping work on selected CSV/Excel columns.
5. Workbook export writes one sheet per selected parameter when enabled.
6. Existing CSV Summary worker tests remain green during the transition.

Exit criteria:

- Users can analyze CSV/Excel table data with the same dashboard and workbook analysis
  path as cached production data, including separate parameter sheets.

### Step 12: Hexafe-Plotstats Adapter

Goal:

- Integrate `hexafe-plotstats` only after the production dashboard is stable and dependency
  policy is resolved.

Primary files:

- `requirements.txt`
- `packaging/`
- `modules/hexafe_plotstats_adapter.py`
- `tests/test_hexafe_plotstats_adapter.py`
- `tests/test_industrial_analytics_dashboard.py`

Tasks:

1. Decide version source: released tag, commit pin, or optional local development path.
2. Update requirements only when the package source is stable enough for Windows packaging.
3. Add lazy adapter import so production dashboard still works if optional plotting package is
   unavailable, unless it becomes a hard dependency.
4. Convert production histogram payloads to `hexafe-plotstats` histogram payloads.
5. Convert production group payloads to violin and IQR/box payloads.
6. Convert time-series payloads to scatter/trend payloads where the package contract fits.
7. Preserve Plotly dashboard as the interactive output.
8. Use plotstats payloads for reusable stats/render snapshots only where they add value.
9. Validate native backend availability reporting and graceful fallback.
10. Verify Windows packaging includes any package data/native assets required by the selected
    dependency mode.

Tests:

1. Adapter imports lazily.
2. Histogram payload mapping preserves values and limits.
3. Violin/box payload mapping preserves group labels and values.
4. Scatter/trend payload mapping preserves x/y ordering.
5. Missing native backend reports unavailable without breaking dashboard generation.

Exit criteria:

- Metroliza can optionally use `hexafe-plotstats` payloads without destabilizing the
  production dashboard or Windows builds.

### Step 13: Documentation, Release Notes, And CI

Goal:

- Make the feature understandable and releasable.

Primary files:

- `README.md`
- `CHANGELOG.md`
- `VersionDate.py`
- `docs/release_checks/`
- User help/manual files under `docs/`
- `docs/roadmaps/OZNAK_PRODUCTION_ANALYTICS_IMPLEMENTATION_PLAN.md`

Tasks:

1. Update user-facing Industrial Data documentation.
2. Explain production-only analytics without mentioning implementation internals.
3. Document what "cached production data" means.
4. Document filter/group/aggregate behavior and time bucket definitions.
5. Document reference cohort modes with short user-facing language.
6. Document that dashboards are generated from local cache and do not query live production
   databases.
7. Update release notes when the feature ships.
8. Update release metadata only in the release slice.
9. Run focused tests after each phase.
10. Run full quality gates before push.
11. Use SSH push and monitor GitHub CI when the implementation is ready to publish.

Exit criteria:

- Docs, release metadata, tests, and CI all match the shipped behavior.

## Dependency Order

Recommended implementation order:

1. Step 0 fixtures.
2. Step 1 state contracts.
3. Step 2 loader and metric discovery.
4. Step 3 filtering.
5. Step 4 aggregation.
6. Step 5 reference cohorts.
7. Step 6 dashboard manifest.
8. Step 7 Plotly dashboard writer.
9. Step 8 groupstats adapter.
10. Step 9 UI workflow.
11. Step 10 workbook extension.
12. Step 11 CSV/Excel analytics source and CSV Summary replacement.
13. Step 12 plotstats adapter dependency gate, partially completed with a temporary public
    Git commit pin on 2026-05-12.
14. Step 13 implementation notes and validation record; release notes/CI happen in the
    publish slice.

This order keeps the highest-risk behavior in pure service tests before adding UI and worker
complexity.

## Risks And Open Decisions

- Dynamic field typing: numeric inference can misclassify IDs that look numeric. Start with a
  conservative threshold and let users explicitly select metrics.
- Large cached datasets: pandas pivoting can be memory-heavy. Dynamic metric value reads now
  chunk SQLite `IN (...)` queries; consider server-side cache summaries later if dataframe
  memory use becomes the bottleneck.
- Timestamp quality: production sources may emit mixed formats or time zones. Preserve raw
  timestamp text and report invalid parse counts.
- Week definition: use Monday-start weeks unless user feedback requires ISO label formatting
  changes.
- Spec limits: capability output needs valid production limits. Initial groupstats support
  should show descriptive/pairwise output and make missing capability explicit.
- Cohort persistence: first release can keep pasted references dialog-local. Add saved cohorts
  only after workflow review.
- Oznak server-side aggregation: not needed for first release. Revisit if cache-side analytics
  is too slow.
- Plotstats dependency: add only after tag/pin and Windows package behavior are confirmed.

## Acceptance Criteria

- A user can create a production analytics dashboard from cached Oznak data without
  parsed reports or measurements.
- A user can aggregate by hour, day, week, month, and year.
- A user can choose at least mean and median; count/min/max/std should ship in the
  same slice unless blocked.
- A user can paste references and see those references highlighted differently on time
  series, histograms, violin plots, and box plots.
- A user can turn pasted references into a separate group for analysis.
- Groupstats results are available when there are at least two usable groups.
- Dashboard generation never queries a live plant database.
- Export and dashboard paths remain cache-only and deterministic.
- Missing specs, missing numeric data, and insufficient groups produce visible skipped
  diagnostics instead of crashes.
- The workflow remains usable on a normal Windows laptop viewport.

## Validation Plan

Focused checks after each implementation phase:

```bash
python -m ruff check modules tests
python -m compileall -q -x '^\./\.git/' .
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_analytics_service.py -q
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_analytics_dialog.py -q
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_export_html_dashboard.py tests/test_industrial_export_service.py -q
```

Before push/release:

```bash
python -m ruff check .
python -m compileall -q -x '^\./\.git/' .
python scripts/sync_release_metadata.py --check
python scripts/check_release_hygiene.py
QT_QPA_PLATFORM=offscreen python -m pytest -q
```
