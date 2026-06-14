# Realtime Industrial Implementation Checklist

Last updated: 2026-06-14

This file is the handoff/checkpoint log for the realtime industrial monitoring
implementation on `rc2`. Update it after every significant implementation,
validation, push, or CI step so the next Codex session can resume from the last
known-good checkpoint.

## Current Resume Point

- Active integration worktree: `/tmp/metroliza-rc2`
- Active integration branch: `rc2`
- Current local head: latest local commit records the temporary realtime DB UX follow-up.
- Remote status at last update: `rc2` push completed through `dfe988d`; GitHub CI run `27493528691` completed green.
- Current step in progress: push `19ab5d6` and verify the new GitHub Actions run.

## Integrated Checkpoints

| Status | Branch/checkpoint | Commit | Notes |
| --- | --- | --- | --- |
| Done | `audit-hardening-rc2` | `caa475d` | Hardened parser probe confidence, industrial error redaction, SQL safety tests, repository regressions. |
| Done | `feature/realtime-industrial-foundation` | `3702f20`, `34fbaed` | Added realtime/anomaly schema, repositories, contracts, deterministic detectors, replay CLI, schema index tests. |
| Done | `test/realtime-industrial-validation` | `e1a6be5` | Added deterministic fixtures, replay scenario tests, edge cases, benchmark script/docs. |
| Done | `hardening/industrial-realtime-security` | `27feabc` | Added realtime stream config validation, redacted diagnostics, raw-record/offset redaction, security checklist. |
| Done | `feature/realtime-industrial-poller` | `123435e` | Added bounded SQL generation, source reader protocol, sample mapper, polling service, runtime wrapper, poller tests. |
| Done | `feature/realtime-industrial-dashboard-docs` | `df959b2` | Added read-only dashboard service/HTML, menu action, operator docs, rollout checklist. |
| Done | `feature/realtime-industrial-ml-anomaly-rc2` | `4ab5498` | Added optional lazy ML dependencies, features, model registry, isolation forest, online drift, calibration script/tests. |
| Done | `rc2` hygiene follow-up | `2ba3b40` | Allowed checked-in deterministic realtime CSV fixtures in release hygiene policy. |
| Done | realtime dashboard temp DB UX follow-up | `a31de2a` | Removes the accidental Metroliza DB precondition when opening realtime monitoring; defaults to a session temporary SQLite store when no report DB is selected. |

## Validation Evidence So Far

| Status | Command | Result |
| --- | --- | --- |
| Pass | `PYTHONPATH=src:. python -m compileall -q -x '^\\./\\.git/' .` | Passed on integrated `rc2`. |
| Pass | `PYTHONPATH=src:. python -m ruff check .` | Passed on integrated `rc2`. |
| Pass | `QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_realtime_*.py tests/test_anomaly_*.py tests/test_replay_industrial_stream.py -q --maxfail=1` | `117 passed, 2 skipped`. |
| Pass | `QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_oznak_adapter.py tests/test_industrial_source_config.py tests/test_industrial_data_schema_repository.py tests/test_industrial_data_repository_regression.py tests/test_industrial_error_redaction.py tests/test_industrial_sync_dialog.py tests/test_industrial_data_dialog.py tests/test_industrial_workers_access_check.py tests/test_industrial_tabular_bridge.py -q --maxfail=1` | `110 passed`. |
| Pass | `python scripts/sync_release_metadata.py --check` | Release metadata already in sync. |
| Pass | `python scripts/check_release_hygiene.py` | Passed after `2ba3b40`. |
| Pass | `python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects` | Escalated rerun passed: no known vulnerabilities found. Existing Bandit/dynamic-import findings remain report-only baseline warnings. |
| Pass | `QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests -q --maxfail=1` | `2086 passed, 298 skipped, 6 warnings, 83 subtests passed` in 109.29s. |
| Pass | CI-shaped coverage sequence from `.github/workflows/ci.yml` | Primary suite plus appended UI/dialog slices passed; `coverage report --fail-under=80` reported `82%`; `coverage.xml` generated. |
| Pass | `python scripts/check_release_hygiene.py` | Passed after coverage artifacts were present. |
| Pass | `git push origin rc2` | Pushed integrated realtime implementation to GitHub. |
| Pass | GitHub Actions run `27493528691` | Completed green for `dfe988df35dce22500d47c21e809084ef79bb2ec`: static checks, unit tests, native wheel/smoke, CMM parser perf guardrail, and non-blocking performance trend check passed. |
| Pass | `QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_main_window_metadata_ui.py -q` | `19 passed`; realtime monitoring dashboard now opens with a temporary session DB when no Metroliza DB is selected. |

## Remaining Release Checklist

- [x] Finish escalated security audit and record pass/fail here.
- [x] Run full offscreen test suite:
  `QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests -q --maxfail=1`
- [x] If full suite passes, optionally run CI-shaped coverage gate:
  `QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests -q --cov=. --cov-report=term --cov-report=xml:coverage.xml`
- [x] Re-run release hygiene after coverage, because `coverage.xml` must remain untracked/ignored.
- [x] Review `git status --short --branch` in `/tmp/metroliza-rc2`.
- [x] Push `rc2` to GitHub.
- [x] Check GitHub Actions for the pushed commit until terminal green.
- [x] Update this checklist with final CI run IDs and conclusions.
- [x] Validate the temporary realtime DB UX follow-up locally.
- [ ] Push the temporary realtime DB UX follow-up and verify its GitHub Actions run.

## Notes For Next Session

- Main checkout `/home/hexaf/Projects/metroliza` still has the original dirty
  `feature/realtime-industrial-ml-anomaly` worktree. Do not reset it unless the
  user explicitly asks. The integrated, validated work is in `/tmp/metroliza-rc2`.
- Optional ML is integrated through the separate branch name
  `feature/realtime-industrial-ml-anomaly-rc2` to avoid rewriting the dirty main
  checkout branch.
- The poller is backend-only: it does not start continuous monitoring from the
  GUI by default. Dashboard UI reads persisted tables only.
- Security audit warnings about dynamic imports are expected for plugin/lazy
  optional dependency paths, but `pip-audit` still needs a clean pass before
  release push.
