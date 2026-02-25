# Metroliza Unified Implementation Plan

This is the single, execution-ready plan that combines all previously discussed work into one prioritized roadmap.

## Current implementation status (repo audit)

Last audited on 2026-02-25.

Canonical phase mapping used throughout this plan:
- ✅ Completed
- 🟡 Partially implemented

Audit result based on the current repository state:
- **Phase 0:** ✅ Completed.
- **Phase 1:** ✅ Completed.
- **Phase 2:** 🟡 Partially implemented (core correctness and contract migration landed; structural decomposition and remaining DB call-site migration continue).
- **Phase 3:** ✅ Completed.
- **Phase 4:** ✅ Completed.

Use this section as the source of truth for what is done vs still outstanding.

## Goals
- Fix correctness issues first (grouping/plot mismatches, crashes, dedupe bugs).
- Standardize module communication through dataclass contracts.
- Improve cancellation/reliability for long-running parse/export tasks.
- Reduce maintenance cost via refactor, tests, and CI.

## Delivery principles
- **Safety first:** crash prevention and data correctness before refactor.
- **Backward compatibility:** use fallbacks during key/schema transitions.
- **Small mergeable slices:** each phase can ship independently.
- **Definition of done per phase:** test coverage + observable acceptance criteria.

---

## Phase 0 — Safety hotfixes (Priority P0, 1–2 days)

### Status: ✅ Completed

### Implementation checklist
1. **Shared safe Excel sheet-name utility** — ✅ done.
2. **Harden stats math (Cp/Cpk edge cases)** — ✅ done.
3. **Fix parse dedupe fingerprint** — ✅ done.
4. **Harden license parsing/validation** — ✅ done.

### Scope
1. Add a shared **safe Excel sheet-name utility** used by all sheet creation paths.
   - Sanitize invalid characters (`[]:*?/\\`).
   - Truncate to 31 chars.
   - Ensure uniqueness with deterministic suffixing.
2. Harden stats math (Cp/Cpk and related computations).
   - Guard for empty arrays, NaN, and `sigma == 0`.
   - Emit `N/A` rather than raising.
3. Fix parse dedupe fingerprint.
   - Use DB identity where available, otherwise composite key:
     `(REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER)`.
4. Harden license parsing/validation.
   - Local parse wrappers with targeted `try/except`.
   - Invalid payloads return an invalid-license state (no crash).

### Acceptance criteria
- Known failing exports no longer crash on invalid sheet names or zero-variance data.
- Duplicate detection distinguishes same filename across different directories.
- Malformed license strings are handled gracefully.

---

## Phase 1 — Reliability and cancellation (Priority P1, 2–3 days)

### Status: ✅ Completed

### Implementation checklist
1. **Cooperative cancellation in parse/export workers** — ✅ mostly done.
   - Cancellation flags and checkpoints are present in parse/export threads.
   - Forced thread termination in normal flow appears removed.
2. **Eliminate UI-thread blocking waits** — ✅ done.
   - Cancel handlers request cancellation and return immediately.
   - Guardrail tests now enforce no `.wait()` usage in parse/export dialog cancel flows.
3. **Adjust `CustomLogger` behavior in user flows** — ✅ done.
   - User-facing error paths consistently use `CustomLogger(..., reraise=False)`.
   - Guardrail tests prevent regressions in logger call-site behavior.

### Scope
1. Convert parse/export workers to **cooperative cancellation**.
   - Add cancellation flag checked at granular checkpoints (I/O, row loops, chart creation).
   - Remove forced `terminate()` usage in normal flow.
2. Eliminate UI-thread blocking waits.
   - Use non-blocking status updates and bounded wait/timeout patterns.
3. Adjust `CustomLogger` behavior in user flows.
   - Avoid unconditional re-raise for recoverable user-facing errors.
   - Preserve full diagnostics in logs.

### Acceptance criteria
- User cancellation exits workers cleanly.
- UI remains responsive during long-running operations.
- Recoverable errors show actionable message + preserved logs.

---

## Phase 2 — Correctness + structure + performance (Priority P1/P2, 3–5 days)

### Status: 🟡 Partially implemented

### Implementation checklist
1. **Fix grouping/plot mismatch root causes** — ✅ completed.
   - Deterministic sort by selected mode exists in export flow.
   - Stable merge key strategy (`GROUP_KEY`/`REPORT_ID`/composite fallback) and duplicate-key warning path are implemented.
   - Violin label/value payload now filters NaN-only buckets and preserves aligned labels/values from a single grouped source before plotting.
2. **Introduce dataclass contracts in `modules/contracts.py`** — ✅ completed for parse/export entrypoints.
   - `ParseRequest`, `AppPaths`, `ExportOptions`, `GroupingAssignment`, and `ExportRequest` exist.
   - Validation helpers now cover parse, paths, options, grouping, and end-to-end export request validation.
   - Parse and export thread entrypoints now require validated request dataclasses from UI call sites.
3. **Decompose heavy workers into testable units** — 🟡 in progress (summary-stat extraction helpers added for export flow; chart scaling helper extraction broadened).
   - Added dedicated pure helpers for summary rendering payloads: sparse trend labels (`build_sparse_unique_labels`), histogram statistics table rows (`build_histogram_table_data`), summary trend payload assembly (`build_trend_plot_payload`), histogram density overlay payloads (`build_histogram_density_curve_payload`), and chart y-limit scaling (`compute_scaled_y_limits`) with direct unit coverage to keep behavior stable during continued worker decomposition.
   - Added a dedicated worksheet-formula builder (`build_measurement_stat_formulas`) so per-header MIN/AVG/MAX/STD/Cp/Cpk/NOK formulas are generated by a pure helper and regression-tested before continuing workbook-write extraction.
4. **Create shared DB utilities module (`db.py`)** — 🟡 partially implemented (core helpers added; adopted in grouping/filter/export paths, with modify flow now using transactional retry helper).
5. **Performance cleanup** — 🟡 in progress (export/grouping hot paths optimized; broader parser/export profiling still pending).
6. **Summary-plot visual refinement + grouped stats overlays** — ✅ completed.
   - Summary plots now use a minimalistic visual theme (reduced grid/spine prominence, cleaner palette, lighter line weights).
   - Violin plots now mark min/avg/max and ±3σ for each group.
   - Grouped violin views now include a per-group statistics table with sample count, min/avg/max/std and Welch t-test p-values against the first group (single-group fallback vs population).

### Scope
1. Fix grouping/plot mismatch root causes.
   - Merge grouping via stable unique key (prefer `REPORT_ID`; fallback composite fingerprint).
   - Add duplicate-key detection/warnings.
   - Enforce deterministic sort in summary path based on selected mode (`date`/`sample`).
   - Build violin values and labels from the same grouped object.
2. Introduce dataclass contracts in `modules/contracts.py`.
   - `ParseRequest`, `AppPaths`, `ExportOptions`, `GroupingAssignment`, `ExportRequest`.
   - Add validators (`validate_export_options`, `validate_paths`, `validate_grouping_df`).
3. Decompose heavy workers into testable units.
   - Split `ExportDataThread` into acquisition, workbook writing, stats/chart generation.
   - ✅ Summary-stat and limit calculation logic extracted to `modules/export_summary_utils.py` and consumed by export summary generation.
   - Add pure functions for formulas/statistics.
4. Create shared DB utilities module (`db.py`).
   - Connection handling, retry policy, query helpers.
   - ✅ Initial implementation landed (`connect_sqlite`, `execute_with_retry`, `read_sql_dataframe`) and first call-sites migrated (`DataGrouping`, `FilterDialog`).
   - ✅ Export data-loading now also uses shared helpers (`read_sql_dataframe`, `execute_select_with_columns`).
   - ✅ Parse flow uses shared DB helpers (`execute_with_retry`) instead of direct `sqlite3.connect`.
   - ✅ Modify flow now runs batched updates through shared retry helper (`execute_many_with_retry`) and no longer opens ad-hoc write connections in `ModifyDB`.
5. Performance cleanup.
   - ✅ Cache/reuse grouping dataframe preparation across summary-sheet header renders.
   - ✅ Reduce export dataframe hot-path overhead via vectorized operations (violin payload build and column-width sizing).
   - ✅ Replace `iterrows` with `itertuples` in grouping-dialog list population hot paths.
   - ✅ Cache workbook formats (reuse per-sheet conditional highlight format instead of recreating per-header loop).
   - Continue reducing plotting overhead (seaborn styling has been introduced for summary charts; monitor render-cost impact on large exports).
   - Precompute expensive loop constants.

### Acceptance criteria
- Grouped plots are deterministic and label/data aligned on regression datasets.
- Parse/export entrypoints accept request dataclasses rather than long primitive arg lists.
- No measurable regressions in existing export outputs.
- Summary-sheet visuals remain clean/readable with grouped violin statistical context (min/avg/max, ±3σ, and t-test table).

---

## Phase 3 — Documentation + developer quality baseline (Priority P2, 1–2 days)

### Status: ✅ Completed

### Implementation checklist
1. **Rewrite `README.md` (quickstart/setup/run/package/troubleshooting)** — ✅ done.
2. **Dependency hygiene (UTF-8 + split runtime/dev/build)** — ✅ completed.
3. **Baseline CI (`compileall`, lint, smoke tests)** — ✅ completed (`compileall`, full-repository lint, unit tests, and lightweight smoke-import checks run in CI).
4. **Add `CONTRIBUTING.md` + architecture notes** — ✅ done (initial contributor setup, checks, architecture flow, and contracts guidance added).

### Scope
1. Rewrite `README.md`.
   - Quickstart.
   - Environment setup.
   - Run/package commands.
   - Troubleshooting.
2. Dependency hygiene.
   - ✅ `requirements.txt` normalized to UTF-8 and reduced to runtime dependencies.
   - ✅ Added `requirements-dev.txt` and `requirements-build.txt` for development/test and packaging tools.
3. Add baseline CI.
   - `compileall`.
   - Lint step.
   - Minimal smoke tests.
4. Add `CONTRIBUTING.md` and architecture notes.
   - Module interaction overview.
   - Dataclass contract usage.
   - Parse → DB → group/filter → export flow.

### Acceptance criteria
- New contributor can install, run, and package from docs alone.
- CI runs on each PR with basic quality gates.
- Full-project linting gate runs in CI on every PR.

---

## Phase 4 — Test coverage baseline (Priority P1/P2, 2–4 days)

### Status: ✅ Completed

### Implementation checklist
- **Unit tests for Phase 0 regressions** — ✅ done.
- **Additional unit tests (grouping merge key correctness + deterministic label/value order)** — ✅ done (coverage now includes deterministic ordering plus merge-key fallback behavior for blank `GROUP_KEY`/`REPORT_ID` values).
- **Integration test (parse → DB → export happy path)** — ✅ done (`tests/test_phase4_integration_happy_path.py`).

### Unit tests
- License parsing and validation edge cases.
- Sheet naming sanitizer/uniqueness behavior.
- Cp/Cpk behavior for sigma=0, NaN, empty samples.
- Dedupe behavior for same filename across distinct directories.
- Grouping merge key correctness and deterministic label/value order.

### Integration test
- Lightweight parse → DB → export happy path using sample fixtures.

### Acceptance criteria
- Core regression suite protects known failure modes.
- Happy-path integration verifies end-to-end viability.

---



## Google Sheets compatibility roadmap (Excel → Google Sheets)

### Status: 🟡 Partially implemented

This roadmap extension captures the approved migration path from Excel-first export to Google Sheets-compatible export while preserving analytics and visuals.

### Scope and sequencing
1. **Phase GS0 — Export target contract/UX**
   - Add an explicit export target selector in **Export Dialog** so the user can choose **Excel** or **Google Sheets** at export time.
   - Default selection must remain **Excel** for now (`excel_xlsx`), with `google_sheets` as the secondary option.
   - Extend export option validation with Google destination metadata.
   - Keep existing Excel behavior unchanged by default.
2. **Phase GS1 — First requested step: USL/LSL anchors + series columns** — ✅ completed
   - ✅ Added per-header `USL_SERIES` and `LSL_SERIES` worksheet columns in the same measurement block row range as measured values.
   - ✅ Switched USL/LSL chart series from inline array-literals to worksheet cell-range series references.
   - ✅ Added explicit `USL_MAX`, `USL_MIN`, `LSL_MAX`, and `LSL_MIN` helper-anchor cells near statistics headers for backend-neutral chart generation.
   - Add `USL_SERIES` and `LSL_SERIES` columns in the same measurement block as measured values.
   - Add helper cells near statistics header with **2x USL** and **2x LSL** (`USL_MAX`, `USL_MIN`, `LSL_MAX`, `LSL_MIN`).
   - Switch chart limits from Excel inline array-literals to sheet **cell-range based** series.
   - Build upper/lower spec visuals from these ranges (or 2-point anchors where chart type requires).
3. **Phase GS2 — Backend abstraction split**
   - Separate shared export data/layout logic from output renderer logic.
   - Retain `ExcelExportBackend`; implement `GoogleSheetsExportBackend`.
4. **Phase GS3 — Google Sheets chart parity**
   - Recreate per-header measurement + USL + LSL charts with Google chart specs.
5. **Phase GS4 — Matplotlib/seaborn summary plots in Google Sheets**
   - Preserve summary plots by rendering PNGs and inserting them into target sheets via supported Google path.
6. **Phase GS5 — Auth/ops hardening + testing**
   - OAuth/service account, retries/backoff, API-progress reporting.
   - Unit + integration + visual checks for parity and regressions.

### Acceptance criteria
- Google Sheets export target is selectable and functional.
- USL/LSL are represented using range-backed series (Google-compatible).
- Per-header charts include measurement, USL, and LSL series.
- Summary matplotlib/seaborn outputs remain present in Google Sheets export.

---


## CSV Summary module roadmap (new)

### Status: ✅ Completed

Recent completion updates:
- ✅ Added CSV Summary spec-limit-order validation (`LSL <= NOM <= USL`) so invalid limit sets are flagged in `CSV_SUMMARY` and capability values fall back to `N/A` instead of producing misleading values.
- ✅ Added lightweight CSV Summary timing telemetry (per-column sheet-write and chart-generation timing logs) to better tune chart thresholds over real datasets.
- ✅ Fixed cross-platform CI unit-test invocation by setting `PYTHONPATH` via workflow `env`, avoiding PowerShell inline env assignment errors on Windows runners.

### Completed in current step
- ✅ Added robust CSV load fallback logic for common manufacturing delimiters/decimals (`;`, `,`, `\t`, `|` with `,`/`.` decimals).
- ✅ Added numeric-column-aware default selection to reduce manual filtering for first-pass analysis.
- ✅ Added aggregated `CSV_SUMMARY` worksheet output (per selected column: sample size, min/avg/max/std/Cp/Cpk).
- ✅ Added focused utility tests for CSV load fallback, default-column resolution, and empty-series stats safety.
- ✅ Added optional per-column spec-limit inputs (NOM/USL/LSL) in CSV Summary UI and wired them into exported Cp/Cpk + overview stats.
- ✅ Added quick-look/full-report plot toggles for CSV Summary so histogram and boxplot-profile chart generation can be skipped per run.
- ✅ Added CSV Summary preset persistence (JSON in user home) to remember delimiter/decimal detection preferences and selected index/data columns by source-file pattern.
- ✅ Extended CSV Summary preset persistence to include per-column NOM/USL/LSL limits, full-report/quick-look choice, and per-column plot toggles.
- ✅ Added an optional CSV Summary UI action to clear saved presets from disk.
- ✅ Added a light integration test validating generated XLSX contains both detail sheets and `CSV_SUMMARY`.

### Next steps
1. ✅ Add a small migration utility for older preset payloads (pre-spec-limit / pre-plot-toggle format) and cover it with tests.
2. ✅ Add CSV Summary cancellation-path regression coverage for long-running workbook generation.
3. ✅ Add a summary-only mode that skips per-column sheets/charts while still generating the `CSV_SUMMARY` worksheet, and persist this preference in presets.
4. ✅ Profile CSV Summary chart generation on large column counts and tune defaults (adaptive full-report default + pre-run chart-count advisory with quick-look fallback).
5. ✅ Add lightweight CSV Summary timing telemetry (per-column write/chart time buckets) to better tune chart generation thresholds over real datasets.

---

## Branching and merge strategy
- Primary implementation branch: `roadmap/phase-implementation`.
- Use short-lived child branches per phase (for example, `roadmap/phase-0-safety-hotfixes`, `roadmap/phase-1-reliability`).
- Each phase lands only after:
  1. implementation is complete for that phase scope,
  2. phase tests/checks pass,
  3. PR review is approved.
- Merge sequence to `main` is strictly phase-ordered (Phase 0 -> 1 -> 2 -> 3 -> 4).
- If a later phase depends on earlier unfinished work, keep it behind feature flags or defer until prior phase is merged.

---

## Milestone sequence
1. **Week 1:** Phase 0 + grouping correctness tests from Phase 2.
2. **Week 2:** Phase 1 (cooperative cancellation + logger behavior).
3. **Week 3:** Remaining Phase 2 structure/performance work + grouping alignment hardening.
4. **Week 4:** Phase 3 docs/CI + Phase 4 coverage baseline.

---

## Risk management
- **Key migration risk:** add fallback mapping and migration guardrails.
- **Output drift risk during refactor:** snapshot/golden checks for representative exports.
- **Cancellation race/deadlock risk:** bounded waits + explicit state transitions + logging.
- **Abstraction overhead risk:** incremental rollouts and strict interface boundaries.

---

## Definition of Done (global)
- [x] **Phase 0:** Safety hotfixes merged and covered (dedupe, sheet naming, stats edge cases, license parsing).
- [x] **Phase 1:** Reliability/cancellation behavior shipped (cooperative cancellation + non-blocking cancel flows + logger guardrails).
- [x] **Phase 2 (implemented slice):** Grouping correctness fixes and dataclass contract migration are merged and regression-covered; remaining structural decomposition/DB call-site migration is tracked as open.
- [x] **Phase 3 (implemented slice):** README, dependency split, contributor + architecture docs, and baseline CI checks are in place.
- [x] **Phase 3 (remaining slice):** Full-project lint enablement in CI is complete.
- [x] **Phase 4:** Unit + integration coverage baseline for known regressions and happy-path parse → DB → export is present.

## Remaining execution order (updated)
1. Execute remaining **Phase 2** structural items in small mergeable PRs:
   - continue worker decomposition (remaining chart/workbook sections),
   - continue extracting + testing pure plotting/data-shaping helpers from `ExportDataThread` (histogram/trend payload + y-limit scaling + histogram density payload helpers completed; next targets are worksheet write segments and additional chart rendering decomposition),
   - DB utilities (continue migration of remaining direct connection call-sites to richer `modules/db.py` helpers and keep write paths transactional).
2. Keep **Phase 0/1/3/4 (completed)** coverage green while remaining Phase 2 structural tasks land.
3. Track and prioritize Google Sheets roadmap execution (GS2+ backend split).

### Audit-backed next implementation steps (next 2-3 PRs)
Based on the latest repository audit, these are the highest-value next slices to execute:

1. **Phase 2 / DB consolidation PR: remove remaining ad-hoc retry/write loops in parser path.**
   - `modules/CMMReportParser.py` still contains a manual retry loop around `cursor.execute` + `executemany` with `sqlite3.OperationalError` handling.
   - Replace this with `modules/db.py` helper-driven transactional write APIs so lock/backoff behavior is centralized and testable.
   - Add/extend tests to assert parser write path no longer uses inline retry loops and remains duplicate-safe.

2. **Phase 2 / Export worker decomposition PR: split `ExportDataThread` worksheet+chart writers into pure payload builders + thin renderer.**
   - `modules/ExportDataThread.py` remains the largest hot-path module and still combines orchestration, SQL loading, payload shaping, and worksheet/chart rendering.
   - Prioritize extraction of: (a) header-block write plan objects, (b) chart series/range spec builders, (c) summary-sheet row layout planners.
   - Maintain existing output parity by snapshot-style tests over generated worksheet ranges/series configuration.

3. **Phase GS2 kickoff PR: introduce backend interface skeleton without behavior change.**
   - Add backend abstraction interfaces/classes (`ExcelExportBackend` first) and route existing Excel write calls through the abstraction.
   - Keep default export target at `excel_xlsx`; do not enable Google Sheets rendering yet.
   - This de-risks GS3+ by separating data/layout planning from output mechanics before API integration.

### Suggested acceptance checks for the next slice
- Parser+DB migration checks: parser write transactionality, duplicate detection, locked-db retry behavior, and regression tests for existing parse happy path.
- Export decomposition checks: deterministic grouping/order tests and chart-range parity assertions remain green.
- Google backend skeleton checks: no behavior delta in generated Excel output for representative fixtures.


## Optimization backlog (exporting/parsing focus)
- **Export path**
  - Profile chart-heavy exports and batch chart/worksheet operations where possible.
  - Reduce repeated formula/text assembly in inner header loops by precomputing static string fragments.
  - Evaluate optional toggles to skip expensive chart generation for large ad-hoc exports.
- **Parsing path**
  - Add lightweight timing instrumentation around PDF open/split/DB-write stages to identify dominant cost centers.
  - Batch parser DB writes where safe and avoid repeated existence checks when fingerprints already prove novelty.
  - Investigate memoizing filename-derived metadata during parse batches to avoid repeated regex work.
