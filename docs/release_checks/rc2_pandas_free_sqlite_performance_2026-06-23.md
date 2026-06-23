# RC2 pandas-free SQLite performance release check

Date: 2026-06-23  
Release metadata: `2026.06rc2(260623)`  
Branch: `rc2`  
Scope: parser/report, CSV Summary, export, industrial analytics, and shared
SQLite row-handling paths for the pandas-removal and SQLite-first performance
slice.

## Summary

This release check covers the RC2 optimization that keeps more routine data
flows in SQLite row/query contracts instead of materializing intermediate
tables.

Implemented release-relevant changes:

- Shared SQLite query scopes and row batches for selected rows, row counts, and
  bounded streaming.
- CSV Summary store APIs for pandas-free row results, batch streaming, and
  grouped metric aggregation directly from stored rows.
- Type-based SQLite numeric aggregation that avoids repeated text validation
  during grouped metric summaries.
- Parser/report/export/industrial helpers adjusted to keep runtime table helpers
  light while preserving compatibility shims for legacy paths.
- Benchmark coverage for tabular SQLite aggregation, streaming, and materialized
  compatibility reads.

## Benchmarks

Matched median before/after runs, clean `b2929c5` versus the current worktree:

| Scenario | Before | After | Delta | Speedup |
|---|---:|---:|---:|---:|
| `cmm_parser_backend_compare` | 0.003537s | 0.004460s | +26.1% | 0.79x |
| `excel_export_path` | 0.157444s | 0.077585s | -50.7% | 2.03x |
| `excel_export_write_vs_shape_path` | 0.064847s | 0.022976s | -64.6% | 2.82x |
| `excel_export_high_header_cardinality_compare` | 0.221417s | 0.146003s | -34.1% | 1.52x |
| `csv_summary_export_path` | 6.455493s | 6.417883s | -0.6% | 1.01x |
| `csv_summary_large_data_probe` | 0.113964s | 0.112696s | -1.1% | 1.01x |
| `sqlite_grouping_high_cardinality_probe` | 0.169400s | 0.179651s | +6.1% | 0.94x |

New tabular aggregate probe, text-guard draft versus final type-based aggregate:

| Fixture | Text guard | Type guard | Result |
|---|---:|---:|---:|
| 4k rows / 200 groups | 0.199841s | 0.021751s | 9.19x faster |
| 100k rows / 200 groups | 4.940768s | 0.590585s | 8.37x faster |

The 100k-row probe streamed 100,000 rows in 0.170924s and avoided about
43.6 MB of materialized RSS in the compatibility read comparison.

Benchmark artifacts:

- Comparable final after runs:
  `/tmp/metroliza-bench-after-current-final-comparable/run-*`
- Aggregate final probes:
  `/tmp/metroliza-bench-new-sqlite-aggregate-after-typeof-4k`
  and `/tmp/metroliza-bench-new-sqlite-aggregate-after-typeof-100k`

## Local validation

| Check | Status | Evidence |
|---|---|---|
| Ruff | Passed | `PYTHONPATH=src:. python -m ruff check .` |
| Compileall | Passed | `PYTHONPATH=src:. python -m compileall -q -x '^\\./\\.git/' .` |
| Full offscreen pytest with coverage | Passed | `2186 passed, 320 skipped, 112 warnings, 83 subtests passed`; broad repository coverage command wrote `coverage.xml` and reported 74% because tests were included in the coverage target. |
| Focused SQLite/tabular/benchmark suite | Passed | `87 passed` for `tests/test_db_utils.py`, `tests/test_tabular_analytics_service.py`, and `tests/test_benchmark_paths.py`. |
| Release metadata sync | Passed | `PYTHONPATH=src:. python scripts/sync_release_metadata.py --check` reported release metadata already in sync. |
| Release hygiene | Passed | `python scripts/check_release_hygiene.py` passed after `coverage.xml` was regenerated. |
| Security audit | Passed | `python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects` passed; `pip-audit` reported no known vulnerabilities, with existing Bandit and dynamic-import warnings remaining report-only baseline findings. |
| CI-shaped coverage gate | Passed | `python -m coverage report --fail-under=80` passed at 81% after the full suite and appended coverage shards. The `industrial_filter_dialog` append-shard hang was reproduced locally, fixed by making the reference-loading fixture satisfy report-schema foreign keys, and rerun successfully (`79 passed`). |
| Pushed GitHub CI | Passed | Commit `4a9f159a8c6a77a824a7170b61f0877f08978984` passed GitHub Actions CI run [`28035951993`](https://github.com/hexafe/metroliza/actions/runs/28035951993): Static checks, Unit tests with combined coverage, Native wheel build and smoke checks, CMM parser perf guardrail, and Performance benchmark trend check all passed. Manual/opt-in packaging, Windows startup benchmark, and Google conversion smoke jobs were skipped. |

## Release decision notes

This slice improves release confidence for routine CSV Summary and export paths,
but it does not close manual promotion gates. Packaging smoke, Windows
clean-machine launch/startup evidence, Google conversion smoke, third-party
notice artifact evidence, and security-owner triage/waiver for report-only
findings remain release-promotion blockers unless the release owner records an
explicit waiver.
