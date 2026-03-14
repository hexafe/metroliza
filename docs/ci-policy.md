# CI Policy for Pull Requests and Branch Pushes

This policy defines the **required CI checks** for every pull request and every branch push, as implemented in `.github/workflows/ci.yml`.

## Scope and enforcement

- CI is triggered on:
  - every `pull_request`
  - every `push` to any branch (`'**'`)
- For PR merge readiness, the required checks are the blocking jobs listed below.

## Required checks (blocking)

The following checks must pass on every PR and branch push.

| Requirement | Workflow job name (`ci.yml`) | What it validates |
|---|---|---|
| Lint and static validation | `static-checks` | Python compile check, Ruff lint, release metadata consistency check, and repository/diff JSON secret scan. |
| Metadata checks | `static-checks` | `scripts/sync_release_metadata.py --check` is enforced in this job. |
| Full pytest suite + coverage visibility | `unit-tests` | Runs `python -m pytest tests -q --cov=. --cov-report=term --cov-report=xml:coverage.xml` for the full Python test suite and publishes coverage outputs. |
| Native artifact build + smoke/parity checks | `native-artifacts` | Builds native wheel, installs it, runs backend smoke checks, and executes native parser parity tests. |


### Coverage reporting semantics

- The `unit-tests` job emits coverage output in two places:
  - terminal/log summary via `--cov-report=term`
  - machine-readable artifact via `coverage.xml` (`--cov-report=xml:coverage.xml`)
- The same job also publishes a **non-blocking coverage threshold status** in the CI job summary by comparing observed line coverage from `coverage.xml` to `COVERAGE_WARNING_THRESHOLD`.
- Current staged rollout keeps threshold checks **non-blocking**; a warning is emitted when coverage is below the warning threshold.
- Threshold governance criteria (observation window, evidence sources, owner, decision date, and acceptance criteria) are tracked in the RC1 execution tracker: `docs/roadmaps/2026_03_rc1_test_ci_execution_tracker.md` under **"TCI-007 governance criteria and staged threshold rollout"**.
- Reviewers can inspect coverage evidence in:
  - the `unit-tests` job log (terminal summary),
  - the CI step summary section **"Coverage threshold status (non-blocking)"**, and
  - the uploaded workflow artifact named `unit-test-coverage` (contains `coverage.xml`).

### Coverage threshold staged policy

Coverage threshold adoption follows a staged policy to reduce noise risk while still surfacing regressions early:

1. **Informational stage (current baseline):** coverage outputs are visible in logs/artifacts; no threshold signal.
2. **Soft threshold warning stage (current enforcement mode):** CI emits a non-blocking warning in the job summary if coverage falls below `COVERAGE_WARNING_THRESHOLD`.
3. **Blocking threshold stage (future):** after tracker acceptance criteria are satisfied and a dated owner decision is recorded, `unit-tests` may enable a blocking fail-under gate.

Until the stage-3 decision is recorded, coverage threshold status is advisory and does not block PR merges.

## Optional/manual checks (non-blocking)

These checks are explicitly non-blocking for normal PR CI:

| Check | Workflow job name (`ci.yml`) | Trigger model | Blocking status |
|---|---|---|---|
| Packaging smoke build + startup launch check (release-only) | `packaging-smoke` | Manual `workflow_dispatch` with `run_packaging_smoke=1` | **Non-blocking** for regular PRs and pushes |
| Google conversion smoke (release-only) | `google-conversion-smoke` | Manual `workflow_dispatch` with `run_google_conversion_smoke=1` | **Non-blocking** for regular PRs and pushes |

### Packaging smoke startup semantics

- After PyInstaller builds `dist/metroliza`, the workflow runs a minimal non-interactive launch smoke command against the built artifact with:
  - `METROLIZA_STARTUP_SMOKE=1` (app-level init-and-exit mode), and
  - `QT_QPA_PLATFORM=offscreen` (headless runner compatibility).
- The smoke command is bounded with a timeout to prevent hanging CI runners.
- Startup logs (`stdout`, `stderr`, and discovered `metroliza.log` paths) are gathered into `smoke-artifacts/`.
- On failure, those artifacts are uploaded as `packaging-smoke-artifacts` for troubleshooting.

## Dependency setup and cache policy

- CI no longer uses a standalone `python-setup` dependency warm-up job. That job did not share an environment with downstream jobs (each job runs on a fresh runner), so it added serial waiting time without reducing downstream install work.
- Each job now performs only the setup it actually needs:
  - `static-checks`, `unit-tests`, `google-conversion-smoke` use `requirements-dev.txt`.
  - `native-artifacts`, `packaging-smoke` use `requirements-build.txt`.
- `actions/setup-python@v5` pip caching is enabled per job with deterministic dependency keys via `cache-dependency-path` pinned to the exact requirements file used by that job.

### Cache determinism and safety

- The cache key includes the dependency file hash (via `cache-dependency-path`) and the selected Python version, so cache reuse is deterministic for unchanged dependency manifests.
- Any edit to `requirements-dev.txt` or `requirements-build.txt` automatically invalidates the relevant pip cache and forces a refresh.
- This keeps cache behavior safe for dependency updates while preserving faster warm-cache installs for unchanged dependency sets.

## CI duration measurement (before/after)

Because this repository snapshot is running in a local container without GitHub Actions run history access, timing here is recorded as a **critical-path structural measurement** from workflow topology, which is deterministic from `ci.yml`:

| Metric | Before | After | Impact |
|---|---:|---:|---:|
| Required serial gate jobs before main checks start | 1 (`python-setup`) | 0 | -1 serial gate job |
| Required jobs that independently install Python dependencies | 3 | 3 | no change |
| Redundant dependency install pass in required path | 1 | 0 | removed |

Interpretation:
- The required checks now start immediately (no pre-job gate), which reduces end-to-end CI wall-clock time by the former `python-setup` job duration on every required run.
- Warm-cache improvements are additionally expected for repeated runs because each job now restores pip wheels/downloads from deterministic cache keys.

Recommended follow-up measurement (on GitHub-hosted runs):
- Compare median duration of the `CI` workflow across at least 10 runs before/after this change using `gh run list --workflow ci.yml --limit 20 --json databaseId,createdAt,updatedAt,status,conclusion` plus runtime aggregation.

## PR checklist

Use this quick checklist when opening or reviewing PRs:

- [ ] Lint/static checks pass (`static-checks`)
- [ ] Metadata consistency checks pass (`static-checks`)
- [ ] Full pytest suite passes (`unit-tests`)
- [ ] Native artifact smoke/parity checks pass (`native-artifacts`)
- [ ] Optional/manual non-blocking checks reviewed as needed (`packaging-smoke`, `google-conversion-smoke`)
