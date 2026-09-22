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
| Lint and static validation | `static-checks` | Python compile check, declarative parser profile self-service smoke, Ruff lint, strict mypy checking for new typed boundary modules, release metadata consistency, tracked-file secret scanning, and Bandit enforcement against the reviewed expiring baseline. |
| Metadata checks | `static-checks` | `scripts/sync_release_metadata.py --check` is enforced in this job. |
| Full pytest suite + coverage gate | `unit-tests` | Runs the full Python test suite with coverage, then re-runs selected real-Qt UI shards in isolated pytest processes with `--cov-append` before enforcing `coverage report --fail-under=80` and writing `coverage.xml`. Qt runtime libraries are installed and `QT_QPA_PLATFORM=offscreen` is set for the lane. |
| Windows core smoke | `windows-core-smoke` | Runs cross-platform SQLite, build-helper, packaging-contract, release-metadata, and OAuth-template tests on Python 3.11 under `windows-latest`. The separate `Run native Windows startup diagnostics tests` step selects the complete bootstrap-startup, diagnostic-event, managed-logging, and build-provenance test files, including real safe-sink and typed startup identity assertions. Also runs real industrial Qt lifecycle tests with `QT_QPA_PLATFORM=windows`; the tests require the actual Windows platform plugin and exercise delayed progress, grouping reopen, cancellation, and C++ teardown. The separate `Run native Windows report planner tests` step exercises real review/selection/import against scratch SQLite, keyboard/focus and compact/large layout at scale factors 1, 1.25, 1.5 and 2 with the Windows Qt plugin. This step sets a 1920x1080 display on the disposable hosted VM and the actual Qt screen geometry/DPR verifies that physical size at each scale, so the 720x480 logical window fits. The additive `Run native Windows realtime dashboard scheduling tests` step runs the complete realtime dialog selection with an asserted Windows Qt plugin. It covers the controlled deferred-dispatch fake-worker oracle, a blocked-start negative control, coalescing and shutdown ownership, and real QThread/SQLite/HTML execution. The explicit 3000 ms positive observation bound is test-only; production debounce and runtime deadlines are unchanged. The blocking `Run native Windows grouping-preview lifecycle tests` step runs the complete `tests/test_tabular_analytics_grouping_dialog.py` file with the actual Windows Qt platform plugin. It exercises asynchronous SQLite selector preview, latest-request ownership, close/cancel, and legitimate worker completion before the independent OCR/PowerShell contract step. The blocking `Run native Windows cache publication tests` step exercises real SQLite backup/flush and atomic no-replace publication, including source preservation on failure. `Run native Windows cache lifecycle tests` retains the archive adversarial suite and the real MainWindow save-before-rebind, cancel and active-database protection cases. The named `Run native Windows specialist geometry tests` step configures the disposable VM to 1920x1080, requires the Windows Qt plugin, and records real Qt screen, client-frame, keyboard, and scroll-reachability evidence for Industrial Data, production-source profiles, and industrial sync at DPR 1, 1.25, 1.5, and 2. It validates source Qt widgets only; packaged-EXE and clean-machine acceptance remain separate release evidence. These source tests do not qualify a packaged EXE or clean-machine deployment. |
