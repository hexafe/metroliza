# Metroliza Unified Implementation Plan

This is a historical implementation plan preserved for archive/reference purposes.

> **Historical context note:** This document is archived context. For active freeze/open-testing/release status, use [`docs/release_checks/release_status.md`](../../release_checks/release_status.md) first.

## Current implementation status (repo audit)

Last audited: 2026-02-27.

Phase-state labels used throughout this archived plan:
- **Completed**
- **Partial**
- **Open**

Audit result based on the current repository state:
- **Phase 0:** Completed.
- **Phase 1:** Completed.
- **Phase 2:** Completed.
  - **Completed:** grouping/plot correctness fixes, dataclass request-contract migration, shared DB helper adoption (including transactional modify flows), export worksheet/chart decomposition slices, and post-extraction profiling/precompute follow-through on chart-heavy exports.
- **Phase 3:** Completed.
- **Phase 4:** Completed.

This section captures the historical snapshot of what was done vs outstanding at the time.

## Next implementation plan (proposed PR sequence)

All previously proposed PR slices in this section are now completed. Any newly open implementation work is tracked only in `TODO.md`.

## Release-candidate documentation sequence (2026.02 build 260228)

### Status: Completed

Completed PR-sequence summary for release-candidate signoff docs:
- Consolidated user-facing release notes/changelog wording for Google Sheets export target `google_sheets_drive_convert`.
- Standardized fallback language so `.xlsx` retention is described identically across changelog, README, and smoke-check docs.
- Synced performance-impact wording (chart-heavy export improvements for large reports) across release highlights and troubleshooting guidance.
- Confirmed this release-candidate documentation PR is non-functional (docs/version metadata only).

Doc sync done when (release-candidate docs):
- [ ] `README.md`
- [ ] `CHANGELOG.md`
- [ ] `IMPLEMENTATION_PLAN.md`
- [ ] `TODO.md`
- [ ] `GOOGLE_SHEETS_MIGRATION_PLAN.md`
- [ ] `VersionDate.py` (version/build text alignment)

Carry-forward implementation work remains tracked only in `TODO.md`.

---

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

### Status: Completed

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

### Status: Completed

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

### Status: Completed.

Completion summary:
- **Completed:** correctness hardening (deterministic grouping + merge-key fallback + NaN-bucket filtering), parse/export dataclass contracts, DB helper consolidation (including retry-aware transactional modify flow), full export worksheet/chart decomposition slices, and targeted profiling/precompute cleanup for chart-heavy exports.

### Implementation checklist
1. **Fix grouping/plot mismatch root causes** — ✅ completed.
   - Deterministic sort by selected mode exists in export flow.
   - Stable merge key strategy (`GROUP_KEY`/`REPORT_ID`/composite fallback) and duplicate-key warning path are implemented.
   - Violin label/value payload now filters NaN-only buckets and preserves aligned labels/values from a single grouped source before plotting.
2. **Introduce dataclass contracts in `modules/contracts.py`** — ✅ completed for parse/export entrypoints.
   - `ParseRequest`, `AppPaths`, `ExportOptions`, `GroupingAssignment`, and `ExportRequest` exist.
   - Validation helpers now cover parse, paths, options, grouping, and end-to-end export request validation.
   - Parse and export thread entrypoints now require validated request dataclasses from UI call sites.
3. **Decompose heavy workers into testable units** — ✅ completed (summary-stat extraction helpers plus worksheet/chart decomposition slices landed with parity coverage).
   - Added dedicated pure helpers for summary rendering payloads: sparse trend labels (`build_sparse_unique_labels`), histogram statistics table rows (`build_histogram_table_data`), summary trend payload assembly (`build_trend_plot_payload`), histogram density overlay payloads (`build_histogram_density_curve_payload`), and chart y-limit scaling (`compute_scaled_y_limits`) with direct unit coverage to keep behavior stable during continued worker decomposition.
   - Added worksheet-writer decomposition helpers for summary-sheet placement and per-header rendering: `build_summary_sheet_position_plan`, `build_measurement_chart_format_policy`, and `build_measurement_write_bundle`, with regression tests to lock layout/series behavior before backend split work.
   - Added a dedicated worksheet-formula builder (`build_measurement_stat_formulas`) so per-header MIN/AVG/MAX/STD/Cp/Cpk/NOK formulas are generated by a pure helper and regression-tested before continuing workbook-write extraction.
4. **Create shared DB utilities module (`db.py`)** — ✅ completed (core helpers added and adopted across grouping/filter/export/parse/modify flows).
5. **Performance cleanup** — ✅ completed (export/grouping hot paths optimized and post-decomposition precompute/profiling follow-through landed).
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
   - ✅ Reduced repeated header/chart spec string assembly through caching in chart-heavy worksheet loops.
   - ✅ Precomputed expensive loop constants and reused cached series/range templates where safe.

### Acceptance criteria
- Grouped plots are deterministic and label/data aligned on regression datasets.
- Parse/export entrypoints accept request dataclasses rather than long primitive arg lists.
- No measurable regressions in existing export outputs.
- Summary-sheet visuals remain clean/readable with grouped violin statistical context (min/avg/max, ±3σ, and t-test table).

---

## Phase 3 — Documentation + developer quality baseline (Priority P2, 1–2 days)

### Status: Completed

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

### Status: Completed

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

### Status: **Partial**

Completion summary:
- **Completed:** GS0-GS5 implementation is merged (target plumbing, Drive conversion flow, auth/ops handling, post-conversion validation, `.xlsx` fallback reporting, and expanded GS5 testing-depth coverage).
- **Open:** maintain optional release-gated live smoke checks as an operational release-readiness practice.

> **Historical cross-reference:** Google Sheets migration detail is archived in `GOOGLE_SHEETS_MIGRATION_PLAN.md`. This section remains a concise companion summary.

### Companion summary
- Google Sheets support follows a Drive conversion strategy: generate the standard `.xlsx`, upload to Drive, convert to Google Sheets, and return the resulting link while preserving/reporting the `.xlsx` fallback.
- **Phase GS5 — Testing strategy ✅ Completed.**
- GS0-GS5 implementation work is merged (target plumbing, upload/convert flow, auth/ops handling, post-conversion validation/fallback messaging, and GS5 testing-depth completion).
- GS5 testing-depth scope is complete in automation; keep optional/manual release-gated conversion smoke checks documented while preserving historical wording and acceptance criteria in the archived migration plan.

### Historical reference
- See `GOOGLE_SHEETS_MIGRATION_PLAN.md` for:
  - GS0-GS5 scope and sequence,
  - unified acceptance criteria wording,
  - implementation task breakdown and risk management.

---


## CSV Summary module roadmap (new)

### Status: Completed

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
- [x] **Phase 2:** Grouping correctness fixes, dataclass contract migration, DB helper consolidation, export-worker decomposition, and performance follow-through are merged and regression-covered.
- [x] **Phase 3 (implemented slice):** README, dependency split, contributor + architecture docs, and baseline CI checks are in place.
- [x] **Phase 3 (remaining slice):** Full-project lint enablement in CI is complete.
- [x] **Phase 4:** Unit + integration coverage baseline for known regressions and happy-path parse → DB → export is present.

## Remaining execution order (updated)
1. Keep **Phase 0-4 (completed)** regression coverage green as maintenance work lands.
2. Track and execute open implementation work from `TODO.md` only (do not duplicate status here).
3. Maintain companion-document summaries (`GOOGLE_SHEETS_MIGRATION_PLAN.md`) as references to the archived open-item list in `TODO.md`.

## Optimization backlog (exporting/parsing focus)

> Reference ideas only (non-canonical). Do not treat this backlog as open implementation status; historical open items were tracked in `TODO.md`.

- **Export path**
  - Profile chart-heavy exports and batch chart/worksheet operations where possible.
  - Reduce repeated formula/text assembly in inner header loops by precomputing static string fragments.
  - Evaluate optional toggles to skip expensive chart generation for large ad-hoc exports.
- **Parsing path**
  - Add lightweight timing instrumentation around PDF open/split/DB-write stages to identify dominant cost centers.
  - Batch parser DB writes where safe and avoid repeated existence checks when fingerprints already prove novelty.
  - Investigate memoizing filename-derived metadata during parse batches to avoid repeated regex work.
