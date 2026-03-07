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
- Reviewers can inspect coverage evidence in:
  - the `unit-tests` job log (terminal summary), and
  - the uploaded workflow artifact named `unit-test-coverage` (contains `coverage.xml`).

## Optional/manual checks (non-blocking)

These checks are explicitly non-blocking for normal PR CI:

| Check | Workflow job name (`ci.yml`) | Trigger model | Blocking status |
|---|---|---|---|
| Packaging smoke build (release-only) | `packaging-smoke` | Manual `workflow_dispatch` with `run_packaging_smoke=1` | **Non-blocking** for regular PRs and pushes |
| Google conversion smoke (release-only) | `google-conversion-smoke` | Manual `workflow_dispatch` with `run_google_conversion_smoke=1` | **Non-blocking** for regular PRs and pushes |

## PR checklist

Use this quick checklist when opening or reviewing PRs:

- [ ] Lint/static checks pass (`static-checks`)
- [ ] Metadata consistency checks pass (`static-checks`)
- [ ] Full pytest suite passes (`unit-tests`)
- [ ] Native artifact smoke/parity checks pass (`native-artifacts`)
- [ ] Optional/manual non-blocking checks reviewed as needed (`packaging-smoke`, `google-conversion-smoke`)
