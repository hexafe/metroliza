# Tests Cleanup Plan

Last updated: 2026-04-26

Codex resume keywords: tests cleanup, test cleanup, useless tests, stale tests,
remove old feature tests.

This is the next-session entry point for pruning low-value Metroliza tests.
The 2026-04-26 cleanup pass below is complete. Do not start by deleting broad
groups of tests. First re-check the current worktree because this branch is
dirty and OCR/report-metadata work may still be moving.

## Current Audit Result

The suite currently collects `1257` tests from `111` top-level test files after
the 2026-04-26 cleanup passes. Baseline before cleanup was `1262` tests from
`112` top-level test files.

Most tests that mention `legacy`, `old`, or parity are not cleanup candidates:
they preserve backwards-compatible payloads, old-vs-new parser/chart parity, or
current user-facing output contracts.

The confirmed cleanup passes removed five stale, duplicated, or timing-only
tests and one test file. No additional broad deletion target is approved in
this document.

## Completed Cleanup Items

Completed removals:

- `tests/test_module_naming_compat.py`
  - Reason: only checks that two old CamelCase shim files stay deleted:
    `CMMReportParser.py` and `ParseReportsThread.py`.
  - Verification: those files do not exist, and broader naming/import policy
    tests cover the class of problem.

- `tests/test_no_camelcase_module_imports.py::test_modules_directory_contains_only_snake_case_python_modules`
  - Reason: duplicates `tests/test_module_naming_policy.py`.
  - Keep `test_no_first_party_camelcase_module_imports`, which scans AST imports
    and catches a different failure mode.

- The single assertion in `tests/test_ci_policy_sync.py` that checks
  `docs/roadmaps/2026_03_rc1_test_ci_execution_tracker.md` is not present in
  `docs/ci-policy.md`.
  - Reason: this is an old cleanup assertion about an archived roadmap path, not
    a current CI contract.

- `tests/test_export_data_thread_group_analysis.py::test_summary_sheet_extended_charts_keep_native_fast_paths_for_distribution_iqr_and_trend`
  - Reason: source-inspection test over implementation strings.
  - Keep the following behavioral test:
    `test_summary_sheet_extended_charts_runtime_native_fast_path_contract_is_behavioral`.

Completed benchmark cleanup:

- `tests/test_benchmark_paths.py::test_group_stats_coercion_microbenchmark_tracks_target_speedup`
  - Reason: it has a `1.5` target variable but never asserts the target, and
    timing-based checks are noisy in normal unit tests.
  - Resolution: removed from the unit suite. Keep performance tracking in the
    benchmark script path rather than wall-clock unit tests.
  - Existing correctness coverage: `tests/test_group_stats_tests.py`.

Completed timing-noise cleanup:

- `tests/test_comparison_stats.py::test_cliffs_delta_rank_based_path_scales_better_on_large_arrays`
  - Reason: duplicated nearby Cliff's delta parity coverage and only added a
    wall-clock `optimized_time < legacy_time` assertion.
  - Resolution: removed. Keep deterministic parity coverage in
    `test_cliffs_delta_rank_based_path_matches_legacy_loop_with_ties`.

- `tests/test_csv_summary_utils.py::test_load_csv_with_fallbacks_wide_csv_timing`
  - Reason: mixed useful wide-CSV behavior coverage with a noisy
    `optimized_time < legacy_time` assertion.
  - Resolution: renamed and reduced to deterministic wide CSV shape/config
    coverage.

- `tests/test_comparison_stats.py::test_bootstrap_ci_benchmark_by_group_count_and_iterations`
  - Reason: useful smoke coverage, but `elapsed > 0` timing assertions added no
    contract.
  - Resolution: renamed and reduced to deterministic group-count/iteration
    coverage.

- `tests/test_cmm_native_parser_runtime.py::test_native_persistence_routes_to_python_repository`
  - Reason: useful behavior coverage, but repeated timing loops and
    `duration >= 0` added no contract.
  - Resolution: reduced to one behavior assertion.

- `tests/test_export_chart_writer.py::test_debug_timing_cached_range_builder_path_runs`
  - Reason: useful cache-path coverage, but `perf_counter` loops and elapsed
    assertions added no contract.
  - Resolution: renamed and reduced to cached-vs-uncached output parity.

- `tests/test_export_sheet_writer.py::test_debug_timing_cached_header_plan_path_runs`
  - Reason: useful cache-path coverage, but `perf_counter` loops and elapsed
    assertions added no contract.
  - Resolution: renamed and reduced to cached-vs-uncached output parity.

## Tests That Look Suspicious But Should Stay

Keep these unless a new audit proves they are obsolete:

- `tests/test_phase0_hotfixes.py`
  - Despite the name, it covers current sheet naming, stats, fingerprint, and
    license-hardening behavior.

- `tests/test_phase1_reliability.py`
  - Guards current UI cancellation and logging behavior. It is static, but the
    failure mode is still relevant for the PyQt app.

- `tests/test_phase2_db_migration.py`
  - Follow-up verification found it still has unique source-level guardrails for
    shared DB helper usage, `ReportRepository` delegation, and removal of old
    direct-write patterns. Keep it until those contracts are replaced by more
    focused behavioral tests.

- Parser/chart/group-analysis tests with `legacy` in the name.
  - These generally protect backwards-compatible payloads or parity with the
    old Python/matplotlib path.

- OCR optional-dependency tests.
  - These intentionally stub optional imports so normal CI can validate OCR
    integration without installing the full OCR runtime stack.

## Suggested Subagent Split

Use subagents only for bounded verification tasks. Avoid parallel edits in the
same test files.

Recommended low-usage split for future cleanup passes:

- Explorer A, `gpt-5.4-mini`, low effort:
  - Re-verify naming/phase migration cleanup candidates.
  - Files owned: read-only over `tests/test_module_naming_policy.py`,
    `tests/test_no_camelcase_module_imports.py`,
    `tests/test_phase2_db_migration.py`,
    `tests/test_phase2_db_migrated_behaviors.py`.
  - Output: confirm delete/keep list with file references.
  - 2026-04-26 result: delete `test_module_naming_compat.py` and the duplicate
    no-CamelCase filename test; keep `test_phase2_db_migration.py`.

- Explorer B, `gpt-5.4-mini`, low effort:
  - Re-verify static CI/export/benchmark candidates.
  - Files owned: read-only over `tests/test_ci_policy_sync.py`,
    `tests/test_export_data_thread_group_analysis.py`,
    `tests/test_benchmark_paths.py`,
    nearby behavioral coverage.
  - Output: confirm which assertions/tests can be removed without losing
    current behavior coverage.
  - 2026-04-26 result: remove the old CI roadmap-path assertion, remove the
    static export-source inspection test, and remove or reduce the timing-based
    benchmark unit test.

- Main agent, inherited model:
  - Apply deletions after the two explorers return.
  - Keep edits scoped to the confirmed test files.
  - Do not touch OCR, parser, chart parity, or group-analysis behavioral tests
    beyond the confirmed static source-inspection test.

Optional worker split only if the cleanup grows:

- Worker C, `gpt-5.4-mini`, low effort:
  - Delete any newly confirmed naming candidates.
  - Owned write set:
    `tests/test_no_camelcase_module_imports.py`.

- Worker D, `gpt-5.4-mini`, low effort:
  - Delete/update CI/export/benchmark candidates.
  - Owned write set:
    `tests/test_ci_policy_sync.py`,
    `tests/test_export_data_thread_group_analysis.py`,
    `tests/test_benchmark_paths.py`.

If workers are used, tell them they are not alone in the codebase and must not
revert unrelated dirty work.

## Future Implementation Order

1. Re-run collection:

   ```bash
   python -m pytest --collect-only -q tests
   ```

2. Re-run candidate verification:

   ```bash
   python -m pytest \
     tests/test_module_naming_policy.py \
     tests/test_no_camelcase_module_imports.py \
     tests/test_phase1_reliability.py \
     tests/test_phase2_db_migration.py \
     tests/test_phase2_db_migrated_behaviors.py \
     -q
   ```

   ```bash
   python -m pytest \
     tests/test_benchmark_paths.py \
     tests/test_export_data_thread_group_analysis.py::TestExportDataThreadGroupAnalysis::test_summary_sheet_extended_charts_runtime_native_fast_path_contract_is_behavioral \
     tests/test_cmm_parser_parity.py::test_cmm_report_parser_wired_to_interface_layer \
     -q
   ```

3. Apply only confirmed removals/edits.

4. Run focused validation:

   ```bash
   python -m pytest \
     tests/test_module_naming_policy.py \
     tests/test_no_camelcase_module_imports.py \
     tests/test_phase1_reliability.py \
     tests/test_phase2_db_migration.py \
     tests/test_phase2_db_migrated_behaviors.py \
     tests/test_db_utils.py \
     tests/test_report_schema_repository.py \
     tests/test_report_query_service.py \
     tests/test_export_data_thread_group_analysis.py::TestExportDataThreadGroupAnalysis::test_summary_sheet_extended_charts_runtime_native_fast_path_contract_is_behavioral \
     tests/test_group_stats_tests.py \
     -q
   ```

5. Run collection again and compare counts.

6. Run ruff over touched tests:

   ```bash
   python -m ruff check <touched-test-files>
   ```

## Acceptance Criteria

- Removed tests are only stale, duplicated, or implementation-detail static
  assertions.
- No current behavior coverage is lost without a named replacement test.
- Full test collection succeeds.
- Focused replacement/neighbor tests pass.
- Final summary states exactly how many tests/files were removed or changed.

## Cleanup Execution Log

### 2026-04-26

- Baseline collection before cleanup: `1262` tests.
- Subagent verification split used:
  - Explorer A, `gpt-5.4-mini`, low effort: naming and phase migration
    candidates.
  - Explorer B, `gpt-5.4-mini`, low effort: CI, export, and benchmark
    candidates.
- Removed `tests/test_module_naming_compat.py`.
- Removed duplicate filename-policy test from
  `tests/test_no_camelcase_module_imports.py`.
- Kept `tests/test_phase2_db_migration.py` after follow-up verification found
  remaining source-level DB-helper guardrails.
- Removed the old roadmap-path assertion from `tests/test_ci_policy_sync.py`.
- Removed the static export-source inspection test from
  `tests/test_export_data_thread_group_analysis.py`.
- Removed the timing-based group-stats coercion microbenchmark unit test from
  `tests/test_benchmark_paths.py`; the benchmark script remains the performance
  tracking path.
- Validation:
  - `python -m pytest --collect-only -q tests`: `1258` tests collected.
  - `python -m pytest tests/test_module_naming_policy.py tests/test_no_camelcase_module_imports.py tests/test_phase1_reliability.py tests/test_phase2_db_migration.py tests/test_phase2_db_migrated_behaviors.py tests/test_db_utils.py tests/test_report_schema_repository.py tests/test_report_query_service.py tests/test_group_stats_tests.py tests/test_benchmark_paths.py -q`: `68 passed, 13 subtests passed`.
  - `python -m pytest tests/test_benchmark_paths.py tests/test_no_camelcase_module_imports.py tests/test_export_data_thread_group_analysis.py::TestExportDataThreadGroupAnalysis::test_summary_sheet_extended_charts_runtime_native_fast_path_contract_is_behavioral -q`: `3 passed`.
  - `python -m ruff check tests/test_no_camelcase_module_imports.py tests/test_ci_policy_sync.py tests/test_export_data_thread_group_analysis.py tests/test_benchmark_paths.py`: passed.

### 2026-04-26 Timing Cleanup Pass

- Baseline collection before this pass: `1258` tests.
- Removed one timing-only duplicate test:
  `tests/test_comparison_stats.py::test_cliffs_delta_rank_based_path_scales_better_on_large_arrays`.
- Simplified timing-noise tests while keeping deterministic behavior coverage:
  - `tests/test_csv_summary_utils.py::test_load_csv_with_fallbacks_handles_wide_semicolon_decimal_csv`
  - `tests/test_comparison_stats.py::test_bootstrap_ci_runs_for_group_count_and_iterations`
  - `tests/test_cmm_native_parser_runtime.py::test_native_persistence_routes_to_python_repository`
  - `tests/test_export_chart_writer.py::TestExportChartWriter::test_cached_range_builder_matches_uncached_output`
  - `tests/test_export_sheet_writer.py::TestExportSheetWriter::test_cached_header_plan_matches_uncached_output`
- Removed unused `time` imports and the now-unused CSV legacy timing helper.
- Validation:
  - `python -m pytest tests/test_csv_summary_utils.py::CsvSummaryUtilsTests::test_load_csv_with_fallbacks_handles_wide_semicolon_decimal_csv tests/test_comparison_stats.py::test_cliffs_delta_rank_based_path_matches_legacy_loop_with_ties tests/test_comparison_stats.py::test_bootstrap_ci_runs_for_group_count_and_iterations tests/test_cmm_native_parser_runtime.py::test_native_persistence_routes_to_python_repository tests/test_export_chart_writer.py::TestExportChartWriter::test_cached_range_builder_matches_uncached_output tests/test_export_sheet_writer.py::TestExportSheetWriter::test_cached_header_plan_matches_uncached_output -q`: `6 passed`.
  - `python -m pytest --collect-only -q tests`: `1257` tests collected.
  - `python -m ruff check tests/test_csv_summary_utils.py tests/test_comparison_stats.py tests/test_cmm_native_parser_runtime.py tests/test_export_chart_writer.py tests/test_export_sheet_writer.py`: passed.
