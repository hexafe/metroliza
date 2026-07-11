# RC2 full-repository hardening release check

Date: 2026-07-09
Release metadata: `2026.06rc2(260709)`
Branch: `rc2`
Scope: export safety, OAuth storage, parser/report integrity, industrial
realtime correctness, UI shutdown, packaging enforcement, test isolation, and
security policy.

## Summary

This release check records implementation of the full-repository audit plan.
The work closes the release-blocking correctness and security findings first,
then implements the highest-value report and industrial backlog items.

Implemented release-relevant changes:

- Workbook output treats imported formula-like and URL-like values as literal
  data across standard, tabular, and industrial exports.
- Google OAuth tokens use a private application file, atomic replacement,
  restrictive permissions, symlink rejection, secret minimization, and safe
  migration from the legacy location.
- Dashboard publication uses complete atomic generations; temporary realtime
  dashboards live in private per-dialog directories.
- Parser resolution shares one bounded source inspection, declarative profiles
  enforce work limits without breaking multiline report fields, parser output is
  rehashed before persistence, and stored provenance is bounded.
- Report source ownership, typed membership filters, identifiers, tabular raw
  values, numeric shadows, measurement summaries, and CMM terminal-line parsing
  now enforce their data-integrity invariants.
- Industrial schema migration adds staging, dead-letter, source-health,
  timezone, query-index, and sync-heartbeat support. Streamed sync promotes
  atomically and startup recovery only reclaims stale staging leases.
- Realtime samples, stream events, and monotonic offsets commit in one
  transaction. Expected-checkpoint comparison rejects stale pollers, failure
  marking cannot overwrite a winning poller, and catch-up is bounded by chunk,
  cycle, cancellation, exhaustion, and no-progress guards.
- Allowed lateness is explicit, timestamps use canonical fixed-width UTC text,
  replay validates global input order before writing bounded batches, and direct
  industrial upsert plus terminal status is atomic.
- Detector selection and numeric configuration are validated strictly. Poison
  events are quarantined without blocking progress. Legacy pickle model loading
  is disabled and old artifacts are archived without deserialization.
- Realtime shutdown waits for database workers before session database cleanup.
  Export threads are released after completion, and test isolation prevents
  fake Qt modules from contaminating later UI tests.
- Runtime diagnostics, benchmarks, and test fixtures now close SQLite
  connections explicitly while preserving transaction semantics; an AST guard
  rejects the non-closing connection-context pattern.
- Required packaging dependencies now fail with package context instead of
  silently producing incomplete artifacts. CI scans tracked configuration for
  short and cross-format credentials and blocks new Bandit findings against an
  expiring reviewed baseline.

## Local validation

| Check | Status | Evidence |
|---|---|---|
| Ruff | Passed | `PYTHONPATH=src:. python -m ruff check .` |
| Compileall | Passed | `PYTHONPATH=src:. python -m compileall -q -x '^\./\.git/' .` |
| Full offscreen pytest with coverage | Passed | `2700 passed, 10 skipped, 6 warnings, 94 subtests passed` in `154.50s`; `coverage.xml` reports `89%` line coverage. |
| Release-blocker regression slice | Passed | `130 passed` across parser provenance/profile compatibility, replay atomicity, industrial staging leases, consumer concurrency, security policy, and startup integration. |
| Exact Qt isolation order regression | Passed | `144 passed, 3 subtests passed`. |
| Security policy tests | Passed | `13 passed`. |
| CI-mode security audit | Passed | `pip-audit` reported no known vulnerabilities. Accepted `155` reviewed Metroliza and `4` reviewed `hexafe-plotstats` medium findings. Baseline expiry remains `2026-10-31`; no unbaselined medium or high findings remain. |
| Dependency vulnerability lookup | Passed | The network-enabled `pip-audit` lookup completed with `No known vulnerabilities found`. |
| PyInstaller onefile collection | Artifact blocked; guard passed | PyInstaller `6.19.0` stopped before artifact creation with `Required packaging dependency 'hexafe_plotstats' is not installed`. The required-dependency guard behaved as intended, but no package smoke is claimed. |
| Release metadata and hygiene | Passed | Metadata sync, release hygiene, docs-link validation, Ruff, compileall, and whitespace checks were refreshed after this evidence file was added. |
| Pushed CI | Pending | The final integration commit has not yet been pushed. No GitHub Actions result is claimed here. |

## Release decision notes

The implementation and local test gates are green, but this is not release
promotion evidence. Promotion remains blocked on all of the following unless
the release owner records an explicit waiver:

- install the pinned `hexafe_plotstats` packaging dependency and produce a real
  PyInstaller artifact;
- commit and push the final worktree, then obtain fresh green CI for that exact
  commit;
- complete Windows executable launch and clean-machine smoke evidence;
- complete Google conversion smoke and third-party notice artifact review.
