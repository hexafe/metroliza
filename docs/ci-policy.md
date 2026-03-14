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

- The `unit-tests` job now emits coverage output in two places:
  - terminal/log summary via `--cov-report=term`
  - machine-readable artifact via `coverage.xml` (`--cov-report=xml:coverage.xml`)
- Coverage reporting is **visibility-only** right now and is **not** a merge gate.
- There is intentionally no fail-under threshold configured yet.
- Threshold go/no-go governance criteria (observation window, evidence sources, owner, and decision output) are tracked in the RC1 execution tracker: `docs/roadmaps/2026_03_rc1_test_ci_execution_tracker.md` under **"TCI-007 governance criteria (deferred threshold decision)"**.
- Reviewers can inspect coverage evidence in:
  - the `unit-tests` job log (terminal summary), and
  - the uploaded workflow artifact named `unit-test-coverage` (contains `coverage.xml`).

## Optional/manual checks (non-blocking)

These checks are explicitly non-blocking for normal PR CI:

| Check | Workflow job name (`ci.yml`) | Trigger model | Blocking status |
|---|---|---|---|
| Packaging smoke build (release-only) | `packaging-smoke` | Manual `workflow_dispatch` with `run_packaging_smoke=1` | **Non-blocking** for regular PRs and pushes |
| Google conversion smoke (release-only) | `google-conversion-smoke` | Manual `workflow_dispatch` with `run_google_conversion_smoke=1` | **Non-blocking** for regular PRs and pushes |

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
