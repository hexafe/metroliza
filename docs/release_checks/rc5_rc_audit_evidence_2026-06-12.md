# RC5 RC Audit Evidence - 2026-06-12

- Release line: `2026.05 RC5`
- Build: `260612`
- Branch: `rc2`
- Evidence type: RC audit implementation and release-gate slice

## Scope

This evidence page records the June 12 RC audit slice for code quality, repo quality,
test coverage, logic, optimization, benchmark, and release-readiness review.

This slice closes the implementable audit findings for Industrial Data/Oznak SQL fetch,
cache behavior, UI wording, test coverage, benchmark probes, and local release-gate
evidence. It does not satisfy manual promotion-only evidence such as packaging smoke,
Windows clean-machine launch, Google conversion smoke, third-party notice artifact
review, or release-owner sign-off.

Inputs used for this audit record:

- local release documentation and current mixed worktree state on `rc2`,
- read-only code/logic review of Industrial Data, Oznak, SQL, cache, and CSV Summary
  paths,
- read-only test/coverage review of Industrial Data, SQL recipe, fetch-all, cache
  target, CSV Summary handoff, and large-group grouping paths,
- read-only performance/benchmark review of raw SQL fetching, cache ingestion,
  cache-to-CSV Summary pivoting, and large dashboard/grouping scenarios,
- current release status and checklist docs.

## Closed Or Recorded Findings

| ID | Area | Status | Evidence / disposition |
|---|---|---|---|
| DOC-1 | Release evidence | Closed in this slice | Added and updated this June 12 evidence page so closed findings, local gates, and remaining manual blockers are tracked in `docs/release_checks/`. |
| DOC-2 | Docs index | Closed in this slice | `docs/README.md` now links this RC audit evidence page. |
| DOC-3 | Industrial Data manual | Closed in this slice | The guided-source example now uses a simple table/view name and explains that schema-qualified objects belong in SQL recipes or an IT-provided simple view when the connector rejects dotted names. |
| LOGIC-1 | Raw SQL safety | Closed | Raw SQL validation now rejects side-effecting/read-locking `SELECT` forms such as `SELECT ... INTO`, `INTO OUTFILE` / `DUMPFILE`, `FOR UPDATE`, and `LOCK IN SHARE MODE` after comments and literals are stripped. |
| LOGIC-2 | Guided Oznak source objects | Closed | Guided source config now uses simple table/view identifiers for pinned Oznak compatibility; schema-qualified access is documented for SQL recipes or IT-provided simple views. |
| LOGIC-3 | Raw SQL fetch-all memory behavior | Closed | The Metroliza raw-SQL fallback now streams `fetchmany()` batches with cancellation/timeout checks and can upsert SQL fetch batches into the local cache incrementally. |
| LOGIC-4 | Industrial-only cache side effects | Closed | Industrial sync workers only materialize report links when an opened Metroliza report database is explicitly attached; temp/industrial-only cache fetches skip report schema creation. |
| UX-1 | Industrial Data SQL workflow polish | Closed | SQL preview warnings populate the preview table, mode tabs are disabled during active operations, and stale direct-export wording was removed. |
| TEST-1 | Test coverage gaps | Closed for RC | Added focused regressions for offscreen Qt setup, SQL recipe open/save, fetch-all confirmation, raw SQL safety, Oznak source-object compatibility, and Industrial sync/cache behavior. |
| PERF-1 | Benchmark coverage gaps | Closed for RC | Added opt-in benchmark probes for Industrial cache ingest, cache-to-CSV Summary bridge, static multi-group rendering, and high-cardinality grouping preview/materialization. |
| RC-1 | Prior CI evidence | Recorded only | Previous build `260611` default GitHub Actions evidence remains in `rc5_parser_ux_release_closeout_2026-06-11.md`; build `260612` local evidence is recorded below and pushed CI must be recorded after publication. |

## Known Open Findings

| ID | Area | Finding | Release disposition |
|---|---|---|---|
| REL-1 | Manual release evidence | Packaging smoke, Windows executable clean-machine startup, Google conversion smoke, third-party notice artifact evidence, and release-owner sign-off remain pending. | Release-blocking unless the release owner records explicit waivers. |
| DEP-1 | Dependency pin review | Runtime pins must remain full-SHA Git pins. Any future dependency touch must re-check whether Oznak, hexafe-groupstats, or hexafe-plotstats have formal release tags and keep `requirements.txt`, CI security audit sibling refs, and requirements hygiene tests synchronized. | No dependency change in this docs-only slice. Revisit during any dependency/code fix slice. |

## Completed Local Validation

The following commands passed locally on 2026-06-12 for build `260612`.

```bash
PYTHONPATH=src:. python -m ruff check .
PYTHONPATH=src:. python -m compileall -q -x '^\./\.git/' .
git diff --check
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests -q
python scripts/sync_release_metadata.py --check
python scripts/check_release_hygiene.py
python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects
```

Results:

- Focused Industrial/Oznak/grouping/benchmark regression slice:
  `180 passed`.
- New advisory benchmark smoke:
  `industrial_cache_ingest_probe`,
  `industrial_cache_to_csv_summary_bridge_probe`,
  `dashboard_static_multi_group_probe`, and
  `sqlite_grouping_high_cardinality_probe` wrote JSON/CSV evidence under
  `/tmp/metroliza-rc-audit-bench-smoke`.
- Full offscreen pytest suite:
  `1942 passed, 283 skipped, 6 warnings, 83 subtests passed`.
- CI-shaped combined coverage gate with appended UI shards:
  `82%` total coverage against the `80%` threshold; `coverage.xml` written locally
  and ignored by release hygiene.
- Security audit:
  sandboxed attempt failed while `pip-audit` upgraded its temporary environment;
  escalated rerun passed with `No known vulnerabilities found` and existing Bandit
  medium findings treated as report-only baseline warnings.

Focused commands run:

```bash
PYTHONPATH=src:. python -m pytest tests/test_oznak_adapter.py tests/test_industrial_source_config.py tests/test_industrial_sync_dialog.py tests/test_industrial_workers_access_check.py tests/test_industrial_data_dialog.py tests/test_industrial_filter_dialog.py tests/test_industrial_tabular_bridge.py tests/test_tabular_analytics_grouping_dialog.py tests/test_benchmark_paths.py -q
PYTHONPATH=src:. python scripts/benchmark_paths.py --output-dir /tmp/metroliza-rc-audit-bench-smoke --scenarios industrial_cache_ingest_probe industrial_cache_to_csv_summary_bridge_probe dashboard_static_multi_group_probe sqlite_grouping_high_cardinality_probe --industrial-cache-rows 100 --industrial-cache-dynamic-fields 4 --static-group-count 4 --static-group-rows-per-group 250 --grouping-high-cardinality-rows 1000 --grouping-high-cardinality-groups 50
```

CI-shaped coverage command:

```bash
python -m coverage erase
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests -q --cov=src/metroliza --cov=modules --cov=scripts --cov-report= --cov-fail-under=0
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_dashboard_visual_options_dialog.py -q --cov=src/metroliza --cov=modules --cov=scripts --cov-append --cov-report= --cov-fail-under=0
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_industrial_analytics_dialog.py -q --cov=src/metroliza --cov=modules --cov=scripts --cov-append --cov-report= --cov-fail-under=0
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_tabular_analytics_grouping_dialog.py tests/test_tabular_analytics_filter_dialog.py -q --cov=src/metroliza --cov=modules --cov=scripts --cov-append --cov-report= --cov-fail-under=0
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_export_dialog_behavior.py tests/test_export_dialog_layout.py -q --cov=src/metroliza --cov=modules --cov=scripts --cov-append --cov-report= --cov-fail-under=0
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_industrial_data_dialog.py tests/test_industrial_export_dialog.py tests/test_industrial_filter_dialog.py tests/test_industrial_linking_dialog.py tests/test_industrial_sync_dialog.py -q --cov=src/metroliza --cov=modules --cov=scripts --cov-append --cov-report= --cov-fail-under=0
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_data_grouping_filter_query.py tests/test_modifydb_record_updates.py tests/test_modifydb_update_statements.py -q --cov=src/metroliza --cov=modules --cov=scripts --cov-append --cov-report= --cov-fail-under=0
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_worker_progress_dialog.py tests/test_parser_plugin_wizard.py tests/test_main_window_metadata_ui.py -q --cov=src/metroliza --cov=modules --cov=scripts --cov-append --cov-report= --cov-fail-under=0
python -m coverage report --fail-under=80
python -m coverage xml -o coverage.xml
```

Status on 2026-06-12: local gate passed. Pushed GitHub Actions CI is pending until
this commit is published.

## Release Blockers And Waivers

No new waivers are recorded in this document.

Release remains blocked until all of the following are closed or explicitly waived by the
release owner:

- remaining release blockers in this document,
- pushed-commit GitHub Actions evidence for the final implementation commit,
- packaging smoke for final artifacts,
- Windows executable clean-machine launch/startup evidence,
- Google conversion smoke for the final artifact,
- third-party notice artifact evidence,
- release-owner sign-off for remaining implementation/security triage items.

## Next Implementation Slice

1. Push the final implementation commit to `rc2`.
2. Check Codex/GitHub review notes for actionable issues.
3. Poll pushed-commit GitHub Actions until terminal green.
4. Record pushed CI run details in release status.
5. Complete or waive manual promotion gates before RC Go.
