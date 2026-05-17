# 2026.05 RC2 Release Audit Evidence

Audit date: 2026-05-17  
Release identity: `2026.05 RC2 (build 260517)`  
Validation branch: `codex/oznak-metroliza-integration`  
Base commit before final audit documentation updates:
`ae124fcb293a74977b9f091d989bd192804642f9`

## Decision

Current decision: **LOCAL PASS / RELEASE BLOCKED**

Reason: local release gates passed for the current audit worktree, but the
candidate still contains uncommitted audit, dependency, UX, and release-check
changes. A final RC2 commit has not been pushed, fresh CI has not run for that
final commit, and release-blocking manual evidence is still missing.

## Worktree Scope Reviewed

Release-intended untracked files currently present:

- `.github/dependabot.yml`
- `scripts/security_audit.py`
- `tests/test_base_report_parser.py`
- `tests/test_hexafe_groupstats_adapter.py`
- `tests/test_matplotlib_runtime.py`
- `tests/test_security_audit.py`

Release-intended modified areas include dependency pins, CI security audit,
release hygiene, groupstats/plotstats/Oznak adapters, CSV/industrial analytics
dashboard behavior, export/dashboard UI, theme tokens, and focused tests.

Local-only contributor guidance was also refreshed in `AGENTS.md`. That file is
excluded by `.git/info/exclude` in this clone, so it is not part of the tracked
release artifact set unless explicitly force-added later.

No generated data artifacts, real reports, logs, databases, exported workbooks,
`credentials.json`, or `token.json` were present in the tracked/untracked status
snapshot used for this audit note.

## Local Validation

Status: **passed locally** for the current audit worktree.

Commands and results:

| Command | Result |
| --- | --- |
| `python -m ruff check .` | Passed |
| `python -m compileall -q -x '^\./\.git/' .` | Passed |
| `python scripts/sync_release_metadata.py --check` | Passed |
| `python scripts/check_release_hygiene.py` | Passed |
| `git diff --check` | Passed |
| `python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects` | Passed after allowing `pip-audit` temporary dependency setup; no known vulnerabilities found |
| `QT_QPA_PLATFORM=offscreen python -m pytest -q` | `1454 passed, 126 skipped, 6 warnings, 60 subtests passed` |
| `QT_QPA_PLATFORM=offscreen python -m pytest tests -q --cov=. --cov-report=term --cov-report=xml:coverage.xml` | `1454 passed, 126 skipped, 86 warnings, 60 subtests passed`; total line coverage `80%` |

Coverage evidence produced `coverage.xml`; release hygiene confirmed generated
coverage files are ignored and not commit candidates.

## Performance Smoke

Command:

```bash
python scripts/benchmark_paths.py --output-dir /tmp/metroliza_release_audit_benchmarks --scenarios csv_summary_export_path chart_render_budget_path group_preprocess_mixed_types_compare distribution_fit_monte_carlo_path --csv-rows 1000 --csv-columns 8 --chart-render-iterations 2 --chart-render-histogram-points 1000 --fit-group-count 8 --fit-sample-size 80 --fit-monte-carlo-samples 30 --group-preprocess-groups 8 --group-preprocess-values 1000
```

Result file:
`/tmp/metroliza_release_audit_benchmarks/benchmark-20260517-100209.json`

Summary:

| Scenario | Result |
| --- | --- |
| `csv_summary_export_path` | `5.4019s` wall time for 1000 rows, 8 CSV columns, 20 charts |
| `chart_render_budget_path` | `0.0924s` wall time; native histogram available; branch ratio `0.9907` |
| `group_preprocess_mixed_types_compare` | `0.0034s` wall time; optimized coercion speedup `1.8543x` |
| `distribution_fit_monte_carlo_path` | `1.1390s` wall time; cached refit vs uncached ratio `0.6538` |

## Security Notes

- Runtime internal Hexafe dependencies are pinned by full Git SHA.
- CI now checks the same sibling SHAs used by `requirements.txt`.
- `scripts/security_audit.py` covers import declarations, dynamic import warnings,
  internal dependency pin validation, `pip-audit`, and Bandit report-only findings.
- Bandit medium SQL-construction findings remain a release triage item. They must
  be fixed or explicitly waived by the release owner/security reviewer before Go.
- Coverage run emitted ResourceWarning noise in several older test paths; it did
  not fail the run, but it should be cleaned separately from this release gate if
  the release owner wants warning volume reduced.

## Release Blockers

| Blocker | Status | Required evidence |
| --- | --- | --- |
| Final commit and fresh CI | Missing | Push final RC2 candidate and link green GitHub CI for that exact SHA. |
| Packaging smoke | Missing | Link opt-in packaging-smoke workflow run or equivalent build/launch logs. |
| Windows EXE clean-machine launch | Missing | Link Windows build artifact and clean/sandbox launch smoke evidence. |
| Google conversion smoke | Missing | Record live RC2 smoke run in `google_conversion_smoke.md`. |
| Bandit SQL baseline triage | Missing | Record fix, waiver, or deferral rationale in `implementation_item_triage.md`. |
| Third-party notice packaging evidence | Missing | Confirm packaged artifact includes `THIRD_PARTY_NOTICES.md` and bundled package notices. |

## Go/No-Go Rule

- `GO` requires all local validation commands passing, fresh green CI for the final
  committed SHA, and every release blocker above closed with linked evidence.
- `LOCAL PASS / RELEASE BLOCKED` is acceptable only for local audit closeout when
  local validation passes but manual/CI release evidence is still missing.
- `NO-GO` applies if any local validation command fails or a security/export/core
  workflow regression is found.
