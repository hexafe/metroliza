# Realtime Industrial Optimization Release Check - 2026-06-16

Release line: `2026.06 RC1`
Build: `260616`
Branch: `feature/realtime-industrial-ml-anomaly`
Scope: Industrial Data fetch, realtime monitoring, and interactive dashboard
optimization slice.

## Scope Summary

This note records the release metadata and user-facing documentation closeout for
the June 16 optimization slice. Implementation and behavior tests for the
industrial fetcher, realtime monitor, and dashboard runtime are owned by the
implementation slice already present in the worktree.

User-facing behavior covered by this release note:

- Industrial Data can save large guided or SQL fetch results into the local
  cache while the production read is still running.
- Industrial Data can run the same guided filters or reviewed SQL query across
  checked production sources and report one batch result.
- Production source setup accepts copied CSV headers or an approved all-columns
  marker for reviewed simple table/view access.
- The SQL query workflow has a larger editor and preview table before fetching.
- Realtime monitoring imports the shared production source YAML file, reloads
  source changes, and opens the shared source editor from the monitor.
- Realtime dashboard snapshots refresh in the background after polling, and
  Open Dashboard waits for an in-progress refresh.
- Interactive HTML dashboards can find and mark individual points without
  changing source data or chart recipes.

## Documentation And Metadata Updates

- Release metadata moved to `2026.06 RC1 (build 260616)` in
  `src/metroliza/app/version.py`.
- README and changelog mirrors were refreshed from canonical release metadata.
- `tests/test_release_metadata_sync.py` now guards the new build label and
  current release note wording.
- User manuals were updated:
  - [`../user_manual/industrial_data.md`](../user_manual/industrial_data.md)
  - [`../user_manual/realtime_industrial_monitoring.md`](../user_manual/realtime_industrial_monitoring.md)
  - [`../user_manual/dashboard_visuals.md`](../user_manual/dashboard_visuals.md)
- Active release docs were updated to link this evidence note and keep build
  `260616` status separate from earlier pushed build `260615` CI.

## Local Validation

- Release/QA audit found and fixed one high-risk streamed Oznak edge case:
  streamed rows followed by a failed diagnostic now remain a completed-with-
  warnings result instead of being reported as a hard failure after rows were
  saved.
- `git diff --check` passed.
- `PYTHONPATH=src:. python -m ruff check .` passed: `All checks passed!`
- `PYTHONPATH=src:. python -m compileall -q -x '^\./\.git/' .` passed.
- `python scripts/sync_release_metadata.py --check` passed:
  `Release metadata is already in sync.`
- `python scripts/check_release_hygiene.py` passed:
  `Release hygiene check passed.`
- `python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects`
  passed after network access was allowed for pip-audit setup:
  `No known vulnerabilities found` and `Security audit passed.`
- `python scripts/validate_packaged_pdf_parser.py --require-header-ocr`
  passed: `Validated packaged header OCR dependencies and 3 vendored model
  files.`
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest -q
  tests/test_release_metadata_sync.py tests/test_docs_markdown_links.py
  tests/test_ci_policy_sync.py tests/test_docs_policy_repo_metrics_hygiene.py`
  passed: `23 passed in 0.26s`.
- Focused release/industrial/docs regression set passed:
  `109 passed in 5.07s`.
- Streamed Oznak partial-success regression and worker access checks passed:
  `38 passed in 3.54s`.
- Full offscreen pytest with coverage tracking passed:
  `2092 passed, 308 skipped, 100 warnings, 83 subtests passed`.
- CI-shaped combined coverage gate passed after isolated UI shards:
  full suite `2092 passed, 308 skipped, 100 warnings, 83 subtests passed`;
  isolated shards `24 passed`, `40 passed`, `78 passed`, `12 passed`,
  `74 passed`, `82 passed`, and `37 passed`; final coverage report passed
  `--fail-under=80` with total coverage `81%`.

## Release Status

- Local release/QA validation: passed.
- Push and green GitHub Actions CI for build `260616`: superseded by build
  `260617` before final integrated commit publication. Current final-push
  evidence is tracked in
  [`realtime_industrial_performance_check_2026-06-17.md`](./realtime_industrial_performance_check_2026-06-17.md).
- Promotion remains blocked on the standing manual release gates: packaging
  smoke, Windows clean-machine launch/startup evidence, Google conversion smoke,
  third-party notice artifact evidence, and security-owner triage/waiver for any
  report-only findings.
