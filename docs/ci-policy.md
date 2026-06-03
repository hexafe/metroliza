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
| Lint and static validation | `static-checks` | Python compile check, declarative parser profile self-service smoke, Ruff lint, release metadata consistency check, and repository/diff JSON secret scan. |
| Metadata checks | `static-checks` | `scripts/sync_release_metadata.py --check` is enforced in this job. |
| Full pytest suite + coverage gate | `unit-tests` | Runs the full Python test suite with coverage, then re-runs selected real-Qt UI shards in isolated pytest processes with `--cov-append` before enforcing `coverage report --fail-under=80` and writing `coverage.xml`. Qt runtime libraries are installed and `QT_QPA_PLATFORM=offscreen` is set for the lane. |
| Native artifact build + smoke/parity checks | `native-artifacts` | Builds all native wheels, installs them, runs import/smoke checks for each native module plus explicit fallback checks, executes native chart planner/parity smoke checks, runs an export-runtime fast-path contract smoke for extended summary charts, and runs native parser parity tests. |
| CMM parser perf guardrail + trend gate | `cmm-parser-perf-gate` | Runs `scripts/benchmark_paths.py` for `cmm_parser_backend_compare` with fixed synthetic workload, enforces native speed/usage guardrails, and compares measured medians to checked-in baseline via `scripts/benchmark_trend_compare.py`. |


### Coverage Reporting Semantics

- The `unit-tests` job emits coverage output in two places:
  - terminal/log summary via `python -m coverage report --fail-under=80`
  - machine-readable artifact via `coverage.xml` (`python -m coverage xml -o coverage.xml`)
- The same job enforces the blocking coverage threshold and publishes a coverage threshold status in the CI job summary.
- The status summary also reports canonical `src/metroliza` line coverage separately so legacy shim coverage cannot hide source-package regressions.
- The job installs minimal Qt runtime system libraries before Python setup so PyQt import tests exercise the real UI modules instead of skipping on missing runner libraries.
- Selected UI tests are re-run in isolated pytest processes with `--cov-append` because legacy module-scope PyQt stubs otherwise undercount real-Qt dialog coverage in a single interpreter.
- Coverage threshold changes require an explicit threshold update in `.github/workflows/ci.yml` plus this policy file.
- Reviewers can inspect coverage evidence in:
  - the `unit-tests` job log (terminal summary),
  - the CI step summary section **"Coverage threshold status"**, and
  - the uploaded workflow artifact named `unit-test-coverage` (contains `coverage.xml`).

### Coverage Threshold Policy

Coverage threshold enforcement is blocking for the full test lane:

1. **Blocking threshold stage:** `unit-tests` fails when coverage drops below the configured threshold.
2. **Ratcheting:** threshold increases should be made only after routine CI evidence shows stable headroom.
3. **Review signal:** `coverage.xml` remains published so reviewers can inspect package-level changes, especially after large refactors.
4. **Canonical source signal:** the CI summary includes `src/metroliza` line coverage alongside aggregate coverage.

The coverage threshold is blocking; do not lower it without recording the reason in the PR description or release evidence.

## Optional/manual checks (non-blocking)

These checks are explicitly non-blocking for normal PR CI:

| Check | Workflow job name (`ci.yml`) | Trigger model | Blocking status |
|---|---|---|---|
| Performance benchmark trend check | `perf-benchmarks` | Automatic on PRs and branch pushes after static checks and unit tests pass | **Non-blocking** advisory signal; compares medians with a 12% threshold and 0.100s absolute slowdown floor, reports export stage medians for review, and keeps the PR check green while artifacts preserve the advisory failure details |
| Packaging smoke build + packaged PDF parser check (release-only) | `packaging-smoke` | Manual `workflow_dispatch` with `run_packaging_smoke=1` | **Non-blocking** for regular PRs and pushes |
| Google conversion smoke (release-only) | `google-conversion-smoke` | Manual `workflow_dispatch` with `run_google_conversion_smoke=1` | **Non-blocking** for regular PRs and pushes |
| Windows startup benchmark (release-only) | `windows-startup-benchmark` | Manual `workflow_dispatch` with `run_windows_startup_benchmark=1` | **Non-blocking** for regular PRs and pushes |

### Packaging smoke parser semantics

- After PyInstaller builds the versioned `dist/metroliza_P_*` artifact, the workflow discovers that artifact and runs a non-interactive packaged PDF parser smoke command against it with:
  - `METROLIZA_PDF_PARSER_SMOKE_FIXTURE=tests/fixtures/pdf/cmm_smoke_fixture.pdf`,
  - `METROLIZA_PDF_PARSER_SMOKE_EXPECTED_TEXT=METROLIZA PDF PARSER SMOKE`, and
  - `QT_QPA_PLATFORM=offscreen` (headless runner compatibility if Qt is touched during startup/imports).
- The smoke command is bounded with a timeout to prevent hanging CI runners.
- Startup logs (`stdout`, `stderr`, and discovered `metroliza.log` paths) are gathered into `smoke-artifacts/`.
- On failure, those artifacts are uploaded as `packaging-smoke-artifacts` for troubleshooting.

### Parser profile self-service smoke

- The `static-checks` job creates a synthetic declarative parser profile through
  `scripts/parser_plugin_self_service.py init`.
- The same job validates the profile against a synthetic CSV sample and expected-results
  CSV, diagnoses the sample, installs it into an isolated profile store with an
  approval sidecar, and prints the generated evidence JSON.
- This smoke proves the standard self-service lane stays data-only and does not
  depend on generated Python parser code.

### Windows startup benchmark semantics

- The `windows-startup-benchmark` job builds PyInstaller onefile and onedir
  artifacts through `build_windows_exe.ps1 -Mode both`.
- It launches both artifacts with `METROLIZA_STARTUP_PROFILE=1` and
  `METROLIZA_STARTUP_UI_SMOKE=1`, so the app records startup timing JSONL and
  exits after the first Qt event-loop tick.
- Visual startup splash is disabled by default for offscreen/UI-smoke launches.
  Normal GUI launches use `METROLIZA_STARTUP_SPLASH=auto`; set
  `METROLIZA_STARTUP_SPLASH=1` only when manually validating splash rendering.
  In normal GUI mode, the splash remains visible until feature warmup completes.
- The job uploads `startup-artifacts/`, including raw profile JSONL files and
  `startup-summary.json`, as release evidence for onefile-vs-onedir startup
  comparisons.

### Performance benchmark trend semantics

- The `perf-benchmarks` job may run extra synthetic benchmark scenarios so the
  artifact keeps broader diagnostic context.
- The trend comparison is scoped to scenario keys that have checked-in baseline
  medians in `docs/perf_baseline_snapshot.json`; scenarios without baselines are
  not treated as trend rows.
- Export stage metrics remain advisory and can include stage timings from
  scenarios that are not baseline-gated.

## Dependency setup and cache policy

- CI no longer uses a standalone `python-setup` dependency warm-up job. That job did not share an environment with downstream jobs (each job runs on a fresh runner), so it added serial waiting time without reducing downstream install work.
- Each job now performs only the setup it actually needs:
  - `static-checks`, `unit-tests`, `google-conversion-smoke` use `requirements-dev.txt`.
  - `native-artifacts` uses `requirements-build.txt`.
  - `packaging-smoke` uses both `requirements-build.txt` and `requirements-ocr.txt`.
- `actions/setup-python@v5` pip caching is enabled per job with deterministic dependency keys via `cache-dependency-path` pinned to the exact requirements file used by that job.

### Cache determinism and safety

- The cache key includes the dependency file hash (via `cache-dependency-path`) and the selected Python version, so cache reuse is deterministic for unchanged dependency manifests.
- Any edit to `requirements-dev.txt`, `requirements-build.txt`, or `requirements-ocr.txt` automatically invalidates the relevant pip cache and forces a refresh.
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
- [ ] CMM parser perf guardrail and trend comparison pass (`cmm-parser-perf-gate`)
- [ ] Optional/manual non-blocking checks reviewed as needed (`packaging-smoke`, `google-conversion-smoke`)

### Additional checklist for parser plugin changes

When a PR touches parser plugin contracts/registry/plugins, also complete the governance checklist in:

- [`docs/release_checks/parser_plugin_rollout_runbook.md`](./release_checks/parser_plugin_rollout_runbook.md)
- [`docs/parser_plugins/README.md`](./parser_plugins/README.md)
