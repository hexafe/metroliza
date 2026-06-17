# Realtime Industrial Performance Release Check - 2026-06-17

Release line: `2026.06 RC1`
Build: `260617`
Branch: `feature/realtime-industrial-ml-anomaly`
Scope: Industrial Data SQLite handoff performance, cached workbook export,
realtime monitoring polling cost, Oznak SQL fallback diagnostics, and dashboard
point-marking closeout.

## Scope Summary

This note records the QA/release audit closeout for the June 17 performance
slice. It builds on the June 16 realtime industrial optimization note and
closes the follow-up findings found during release audit.

User-facing behavior covered by this release note:

- Industrial Data opens cached rows in CSV Summary through indexed local
  metadata so filter lists and simple grouping previews do not need to scan the
  full industrial view.
- Industrial Data workbook export can include a raw-data sheet from the cached
  store while streaming rows directly from the local cache.
- Additional Industrial export filters now apply consistently to cached and
  live export paths, including dynamic production fields from the filter dialog.
- Same-session industrial cache updates refresh filter facets even when row and
  field-value updates happen within the same second.
- Temporary industrial tabular views are pruned before new cache handoffs so
  long-running sessions do not accumulate abandoned SQLite views.
- Raw SQL fallback fetches now report partial progress when rows have already
  been streamed and a later callback or fetch step fails.
- Realtime anomaly review now loads newly inserted sample rows by ID instead of
  rescanning history for each polling cycle.

## QA Findings Closed

| Finding | Status | Evidence |
| --- | --- | --- |
| Export dialog additional filters were accepted by the UI but not applied by cached/live workbook export. | Closed | Cached export now applies record and dynamic-field query filters; live export forwards query filters into the Oznak fetch request. |
| Industrial tabular metadata/facet caches could remain stale for same-second updates. | Closed | Cache fingerprints now include value counts and max value IDs, and cache timestamps keep microsecond precision. |
| UUID industrial tabular views could accumulate if cleanup was skipped. | Closed | Handoff creation now prunes stale `industrial_tabular_rows_%` views before creating a new view. |
| Raw SQL fallback callback failures lacked partial-progress diagnostics. | Closed | Oznak fallback now reports row count, partial success, and callback streaming status when a later step fails. |
| Industrial Sync dialog initial width no longer fit the expanded fetch controls in the CI-shaped UI shard. | Closed | The dialog now starts wide enough for its size hint; the failed layout shard passed after the fix. |

## Documentation And Metadata Updates

- Release metadata moved to `2026.06 RC1 (build 260617)` in
  `src/metroliza/app/version.py`.
- README and changelog mirrors were refreshed from canonical release metadata.
- `tests/test_release_metadata_sync.py` now guards the new build label and
  current release-note wording.
- Active release docs were updated to link this evidence note and keep build
  `260617` status separate from earlier pushed build `260615` CI.

## Local Validation

Local validation passed before publication:

- `python scripts/sync_release_metadata.py --check` passed:
  `Release metadata is already in sync.`
- `python scripts/check_release_hygiene.py` passed:
  `Release hygiene check passed.`
- `PYTHONPATH=src:. python -m ruff check .` passed:
  `All checks passed!`
- `PYTHONPATH=src:. python -m compileall -q -x '^\./\.git/' .` passed.
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest
  tests/test_release_metadata_sync.py tests/test_docs_markdown_links.py
  tests/test_ci_policy_sync.py tests/test_docs_policy_repo_metrics_hygiene.py -q`
  passed: `23 passed`.
- Focused industrial/realtime/dashboard regression set passed:
  `184 passed`.
- Full offscreen pytest passed:
  `2109 passed, 314 skipped, 6 warnings, 83 subtests passed`.
- `python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects`
  passed after network access was allowed for pip-audit setup:
  `No known vulnerabilities found` and `Security audit passed.`
- CI-shaped combined coverage gate passed after isolated UI shards:
  full suite `2109 passed, 314 skipped, 101 warnings, 83 subtests passed`;
  isolated shards `24 passed`, `40 passed`, `78 passed`, `12 passed`,
  `79 passed`, `82 passed`, and `37 passed`; final coverage report passed
  `--fail-under=80` with total coverage `81%`.

## Release Status

- Local release/QA validation: passed.
- Push and green GitHub Actions CI for build `260617`: pending final integrated
  commit publication.
- Promotion remains blocked on the standing manual release gates: packaging
  smoke, Windows clean-machine launch/startup evidence, Google conversion smoke,
  third-party notice artifact evidence, and security-owner triage/waiver for any
  report-only findings.
