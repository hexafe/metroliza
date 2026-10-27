# CI Policy for Pull Requests and Branch Pushes

This policy defines the **required CI checks** and Tier-0 selection implemented in
`.github/workflows/ci.yml` (Issue #1061, CI audit #976).

## Scope and enforcement

- CI is triggered on:
  - every `pull_request`, without path or target-branch filtering;
  - direct `push` to `master`, `main`, `develop`, `rc2`, `integrate/**`, `release/**`,
    `hotfix/**` and `build/**` (RC artifacts are cut from build branches), including
    nested names;
  - `workflow_dispatch`, with the existing opt-in qualification inputs.
- Topic branches use PR CI only. A topic push without an open PR has no automatic CI;
  open a PR or dispatch CI to qualify it. This removes duplicate topic push + PR workloads
  without querying PR state, changing concurrency keys, or losing integration-push CI.
  Integration/release/hotfix/build branches intentionally retain push coverage even when
  they are also PR sources; that exceptional pair can still run both integration and PR CI.
- Pushes always run the full lane. Only `pull_request` events can select Tier 0, so a
  push run and a PR run on the same SHA never disagree about which checks ran, and the
  integration-branch push remains a backstop for the PR classification.
- For PR merge readiness, the required checks are the blocking jobs listed below.

## Tier 0: docs-only classification

`classify-changes` runs `scripts/ci_change_classifier.py` against complete local Git
history (`fetch-depth: 0`). A PR compares its merge base with the event's head SHA,
covering all commits in the PR rather than just the latest push or an API file page.
Pushes and `workflow_dispatch` never take Tier 0. Only additions and modifications
can qualify: a deletion, and therefore a rename (expanded into a delete/add pair), runs
full CI because the bug-sweep ownership ledger names exact prose paths.

Only regular, non-executable Markdown in these human-facing prose locations qualifies:

- root `AGENTS.md`, `CONTRIBUTING.md`, and `.github/pull_request_template.md`;
- Markdown directly under `docs/`;
- Markdown under `docs/project/`, `docs/engineering/`, `docs/release_checks/`,
  `docs/roadmaps/`, `docs/quality/`, and `docs/archive/`.

Directories named `assets`, `fixtures`, `generated`, `templates`, `prompts`, or
`contracts` are excluded even inside those prose roots. Human task/report templates
in `docs/engineering/` remain prose. A new code-consumed Markdown input must stay
outside the allowlist or gain an explicit exclusion with classifier tests before use.
Markdown inside the prose roots that code or non-Tier-0 tests read (for example the
feature catalog, the bug-sweep templates and the supervised diagnostics contract) is listed
in `EXECUTABLE_INPUT_DOCS` and runs full CI. A structural test scans `tests/`, `scripts/`,
`src/` and `packaging/` for Markdown references and fails when a new consumer of prose
appears, and another test keeps its Tier-0 list in sync with the workflow step.

The following require **full CI**, regardless of file extension:

- application/source code, scripts, tests, `tests/fixtures/*.md` (and nested fixtures),
  source templates and code-consumed prompts/contracts;
- workflow and configuration changes, dependencies, build/packaging files;
- generated assets, JSON/CSV/PDF/images and other non-Markdown files;
- root `README.md` and `CHANGELOG.md` (release metadata checked/synced by scripts),
  `THIRD_PARTY_NOTICES.md` (packaged notice input), and runtime help under `docs/user_manual/`;
- unknown locations, symlinks, executable files, submodules and type changes.

Mixed changes are full CI. Empty diffs, new branches with a zero `before` SHA,
missing comparison objects/merge bases, malformed events/diffs and Git errors also
select full CI. `workflow_dispatch` always selects full CI, so manual packaging and
startup dependencies remain qualified. No API token, network lookup, or changed-file
count limit is used by the classifier.

For docs-only changes, `Static checks` runs focused docs/link/policy/classifier and
release-hygiene tests with minimal Python dependencies, release metadata consistency,
tracked-file secret scanning, release hygiene and `git diff --check`. It does not
install application dependencies, build native wheels, run runtime smoke or benchmarks,
or emit full-suite coverage evidence. Code, mixed and workflow-change PRs retain the
complete existing checks below, including the blocking 80% coverage threshold.

All existing job IDs and displayed required check names remain unchanged. The heavy
jobs still exist and report a skipped success/neutral status on docs-only changes;
the whole workflow is never path-ignored. `Static checks` always evaluates after the
classifier (unless the workflow is cancelled) and fails if classification failed or
its boolean output is absent/invalid. Thus a classifier failure cannot silently waive
the existing required merge predicate. The CMM and advisory performance jobs still
require successful static and unit jobs in the full lane. No required-check setting,
review gate or merge authority is changed by this path selection.

Classifier unit tests separately cover docs-only, code, mixed and workflow changes,
renames in both directions, deletions, generated assets, release-synced Markdown,
fixture/template Markdown, file modes and unavailable history. Policy synchronization
tests guard the job names, failure behavior, dependencies and event filters. Local
tests are source evidence only: the coordinator must validate real docs-only/code/
mixed/workflow test PRs on GitHub and read back required statuses and branch protection
before claiming hosted CI qualification. Existing workflow and per-job dispatch
concurrency, cancellation exceptions and owner-only qualification predicates are preserved.

## Required checks (blocking)

The following checks must pass in the full lane on every PR and eligible branch push.
For docs-only changes the Tier-0 result and explicit heavy-job skips described above apply.

| Requirement | Workflow job name (`ci.yml`) | What it validates |
|---|---|---|
| Lint and static validation | `static-checks` | Python compile check, declarative parser profile self-service smoke, Ruff lint, strict mypy checking for new typed boundary modules, release metadata consistency, tracked-file secret scanning, and Bandit enforcement against the reviewed expiring baseline. |
| Metadata checks | `static-checks` | `scripts/sync_release_metadata.py --check` is enforced in this job. |
| Full pytest suite + coverage gate | `unit-tests` | Runs the full Python test suite with coverage, then re-runs selected real-Qt UI shards in isolated pytest processes with `--cov-append` before enforcing `coverage report --fail-under=80` and writing `coverage.xml`. Qt runtime libraries are installed and `QT_QPA_PLATFORM=offscreen` is set for the lane. |
| Windows core smoke | `windows-core-smoke` | Runs cross-platform SQLite, build-helper, packaging-contract, release-metadata, and OAuth-template tests on Python 3.11 under `windows-latest`. The separate `Run native Windows startup diagnostics tests` step selects the complete bootstrap-startup, diagnostic-event, managed-logging, and build-provenance test files, including real safe-sink and typed startup identity assertions. The blocking `Run native Windows supervised incident tests` step also covers the full safe wire/ring/store/transport, real workflow, viewer and qualification-driver test files. These native source tests do not establish packaged EXE qualification. Also runs real industrial Qt lifecycle tests with `QT_QPA_PLATFORM=windows`; the tests require the actual Windows platform plugin and exercise delayed progress, grouping reopen, cancellation, and C++ teardown. The separate `Run native Windows report planner tests` step exercises real review/selection/import against scratch SQLite, keyboard/focus and compact/large layout at scale factors 1, 1.25, 1.5 and 2 with the Windows Qt plugin. This step sets a 1920x1080 display on the disposable hosted VM and the actual Qt screen geometry/DPR verifies that physical size at each scale, so the 720x480 logical window fits. The additive `Run native Windows realtime dashboard scheduling tests` step runs the complete realtime dialog selection with an asserted Windows Qt plugin. It covers the controlled deferred-dispatch fake-worker oracle, a blocked-start negative control, coalescing and shutdown ownership, and real QThread/SQLite/HTML execution. The explicit 3000 ms positive observation bound is test-only; production debounce and runtime deadlines are unchanged. The blocking `Run native Windows grouping-preview lifecycle tests` step runs the complete `tests/test_tabular_analytics_grouping_dialog.py` file with the actual Windows Qt platform plugin. It exercises asynchronous SQLite selector preview, latest-request ownership, close/cancel, and legitimate worker completion before the independent OCR/PowerShell contract step. The blocking `Run native Windows cache publication tests` step exercises real SQLite backup/flush and atomic no-replace publication, including source preservation on failure. `Run native Windows cache lifecycle tests` retains the archive adversarial suite and the real MainWindow save-before-rebind, cancel and active-database protection cases. The named `Run native Windows specialist geometry tests` step configures the disposable VM to 1920x1080, requires the Windows Qt plugin, and records real Qt screen, client-frame, keyboard, and scroll-reachability evidence for Industrial Data, production-source profiles, and industrial sync at DPR 1, 1.25, 1.5, and 2. It validates source Qt widgets only; packaged-EXE and clean-machine acceptance remain separate release evidence. These source tests do not qualify a packaged EXE or clean-machine deployment. |
| Native artifact build + smoke/parity checks | `native-artifacts` | Builds all native wheels, runs the cross-platform tests of the native launcher crate (`packaging/launcher`, `cargo test --locked`), installs the wheels, runs import/smoke checks for each native module plus explicit fallback checks, executes native chart planner/parity smoke checks, runs an export-runtime fast-path contract smoke for extended summary charts, and runs native parser parity tests. |
| CMM parser perf guardrail + trend gate | `cmm-parser-perf-gate` | Runs `scripts/benchmark_paths.py` for `cmm_parser_backend_compare` with fixed synthetic workload, enforces native speed/usage guardrails, and compares measured medians to checked-in baseline via `scripts/benchmark_trend_compare.py`. |


The additive `Run native Windows report workspace tests` step in `windows-core-smoke`
checks the main Home/Reports/Tools composition: one real report owner, scratch-SQLite
subset import across navigation, accepted/rejected context changes, cancellation and
main-window close, and lazy diagnostic-menu availability/failure handling. Its native
geometry matrix verifies the actual Windows Qt plugin, physical 1920x1080 display and
scale factors 1, 1.25, 1.5 and 2, including compact client/frame fit and keyboard use.
Existing planner, industrial lifecycle and OCR steps remain independent. These source
checks do not qualify a packaged EXE or the separately owned diagnostic preview/export.

### Coverage Reporting Semantics

- The `unit-tests` job emits coverage output in two places:
  - terminal/log summary via `python -m coverage report --fail-under=80`
  - machine-readable artifact via `coverage.xml` (`python -m coverage xml -o coverage.xml`)
- The same job enforces the blocking coverage threshold and publishes a coverage threshold status in the CI job summary.
- The status summary also reports canonical `src/metroliza` line coverage separately so legacy shim coverage cannot hide source-package regressions.
- The job installs minimal Qt runtime system libraries before Python setup so PyQt import tests exercise the real UI modules instead of skipping on missing runner libraries.
- Selected UI tests are re-run in isolated pytest processes with `--cov-append` to exercise real-Qt dialog paths; an architecture test prevents collection-time `sys.modules` replacements from poisoning later test imports.
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

The complete realtime selection also checks Windows owner/DACL/effective access on the
owned temporary dashboard directory and its generated HTML. The native lane retains the
observed Python 3.11.9 and asserts that version. POSIX retains its original `0700` oracle.
A deliberately permissive inherited descriptor must fail the native oracle. The receipt
labels this as `restricted_current_user`: actual access checks and file operations with
Administrators disabled and no enabled privilege except traversal. It does not claim an
actual separate ordinary-user account, a linked token, or protection from a privileged
administrator. Only safe classifications/counts are printed; short tracebacks suppress fixture identity dumps.
Real token access checks and impersonated file operations are required; mock access checks,
DACL-presence-only checks, and an omitted whole-file test are not acceptance.
The product atomically creates the owned Windows directory and receives its handle using
`NtCreateFile` with a protected allowlist, validates the native handle before output, and retains it through worker
completion to refuse directory replacement. Native failure controls cover real creation,
collision preservation, denied/nonfinal creation, untrusted child-delete ACEs,
secondary identity-query/security failures and handle-directed cleanup of the atomically
created object; UI tests retain ownership
and refuse false shutdown completion when cleanup fails. An unavailable private session
blocks default output with a fixed explanation while an explicitly chosen output file
keeps its existing operator-directed behavior. Real MainWindow close tests distinguish the
private-storage retry reason from the preserved unsaved-source cancellation reason.
The deferred parent-close case uses a real held writer and real SQLite-to-HTML output:
after cleanup fails, an explicit failure notification clears pending automatic-close
intent and leaves the parent/storage available for manual retry. Stale-owner signals and
an earlier queued child-close retry cannot close the parent after that failure.

## Optional/manual checks (non-blocking)

These checks are explicitly non-blocking for normal PR CI:

| Check | Workflow job name (`ci.yml`) | Trigger model | Blocking status |
|---|---|---|---|
| Performance benchmark trend check | `perf-benchmarks` | Automatic in the full lane on PRs and eligible branch pushes after static checks and unit tests pass | **Non-blocking** advisory signal; compares medians with a 12% threshold and 0.100s absolute slowdown floor, reports export stage medians for review, and keeps the PR check green while artifacts preserve the advisory failure details |
| Packaging smoke build + packaged PDF parser check (release-only) | `packaging-smoke` | Manual `workflow_dispatch` with `run_packaging_smoke=1` | **Non-blocking** for regular PRs and pushes |
| Google conversion smoke (release-only) | Local secure workstation command documented in `docs/google_conversion_smoke_runbook.md` | Explicit local opt-in with sandbox `credentials.json` and `token.json` | Not a hosted CI job; **release-blocking** evidence for promoted RC artifacts |
| Windows startup benchmark (release-only) | `windows-startup-benchmark` | Manual `workflow_dispatch` with `run_windows_startup_benchmark=1` | **Non-blocking** for regular PRs and pushes; builds the shipped supervised onedir, the portable envelope EXE and the native launcher EXE (user flavor) and measures the same startup smoke through each route (see below) |
| Supervised portable onefile + native launcher qualification (opt-in) | `windows-portable-onefile` | Owner-only manual `workflow_dispatch` with `run_windows_portable_onefile=1` on a public repository | **Non-blocking**; builds the supervised onedir and the portable envelope, then packs the same onedir into the native launcher EXE. Both EXEs run the same first-launch, reopen, hard-exit and incident scenarios (`scripts/qualify_windows_portable_onefile.py`, `--kind envelope\|launcher`); the launcher run also asserts `cache=cold` then `cache=warm` and one complete content-keyed runtime directory. Uploads `windows-supervised-portable-onefile` (envelope) and `windows-supervised-launcher-exe` (launcher, for testers). |
| Native launcher qualification (opt-in) | `windows-launcher-qualification` | Owner-only manual `workflow_dispatch` with `run_windows_launcher_qualification=1` on a public repository | **Non-blocking**; builds the launcher, runs its tests on Windows, qualifies a synthetic payload (cold/warm/second instance/corruption/self-repair on exit 75/upgrade/kill) and uploads the EXE and JSON report. Does not qualify the real application payload or signing. |

### Packaging smoke parser semantics

- After PyInstaller builds the versioned `dist/metroliza_P_*` artifact, the workflow discovers that artifact and runs a non-interactive packaged PDF parser smoke command against it with:
  - `METROLIZA_PDF_PARSER_SMOKE_FIXTURE=tests/fixtures/pdf/cmm_smoke_fixture.pdf`,
  - `METROLIZA_PDF_PARSER_SMOKE_EXPECTED_TEXT=METROLIZA PDF PARSER SMOKE`, and
  - `QT_QPA_PLATFORM=offscreen` (headless runner compatibility if Qt is touched during startup/imports).
- The smoke command is bounded with a timeout to prevent hanging CI runners.
- Startup logs (`stdout`, `stderr`, and discovered `metroliza.log` paths) are gathered into `smoke-artifacts/`.
- A successful run stages a visible notice sidecar beside the executable and uploads the binary, `THIRD_PARTY_NOTICES.md`, the generated dependency inventory, and `NOTICE_MANIFEST.json` together as `packaging-smoke-release-artifact`.
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

- The job has no `needs:`: like the other opt-in Windows jobs it runs on its own, so a failing
  unrelated blocking job cannot silently turn the requested measurement into a skipped job.
- The `windows-startup-benchmark` job builds the route users actually get, in the
  `user` build flavor: `build_windows_portable_exe.ps1` (the supervised onedir
  plus the PyInstaller portable envelope) and then
  `build_windows_launcher_exe.ps1 -Supervised` (the same onedir packed into the
  native launcher EXE `metroliza_<label>_launcher.exe`). The legacy single-process
  `metroliza_onefile.spec` is no longer built or measured here; it remains in use
  by `packaging-smoke` and `build_windows_exe.ps1 -Mode both`, and
  `scripts/measure_windows_startup.ps1` stays available for local comparisons.
- `scripts/measure_windows_startup_routes.py` runs the same non-interactive smoke
  through each route, 3 runs each: (a) the portable envelope (extracts the whole
  onedir to `%TEMP%` on every launch), (b) the launcher cold (a fresh
  `METROLIZA_RUNTIME_ROOT` for every run), (c) the launcher second launch (parallel
  SHA-256 verification and flush on each of the three pending caches) and (d) the
  launcher warm (launches 3 to 5 of one completed cache). Each launcher run must
  log the expected `cache=cold|verified|warm`, otherwise the run fails.
- The smoke is `METROLIZA_STARTUP_UI_SMOKE=1`: the application builds and shows
  the real main window and exits after the first Qt event-loop tick.
  `METROLIZA_LICENSE_VERIFICATION=0` and `METROLIZA_LAUNCHER_NO_UI=1` keep every
  dialog away, and each launch has a timeout after which its process tree is
  killed. The supervisor passes its environment on to the application, so the
  same variables reach the real window code through the supervised chain.
  `METROLIZA_STARTUP_PROFILE=1` records the profile events, which carry a
  wall-clock `epoch_ms` since this change, so the script reports the time from
  process creation to `main_window_show_called` and to `first_event_loop_tick`
  (the first moment the event loop could deliver the initial paint; reported as
  `first paint`), including bootloader, extraction, launcher and supervisor time.
- Each sample must exit with code 0, write a startup profile with the
  `first_event_loop_tick` event and `epoch_ms`, and (launcher) the expected cache
  state before evidence is accepted. A failing run is kept in the report and
  fails the job.
- Visual startup splash is disabled by default for offscreen/UI-smoke launches.
  Normal GUI launches use `METROLIZA_STARTUP_SPLASH=auto`; set
  `METROLIZA_STARTUP_SPLASH=1` only when manually validating splash rendering.
  In normal GUI mode, the splash remains visible until feature warmup completes.
- The job prints the table, appends it to the step summary and uploads
  `startup-artifacts/` as `windows-startup-artifacts`: `startup-benchmark.json`,
  `startup-benchmark.md`, the raw profile JSONL files and the launcher logs.
  Hosted-runner numbers are advisory; they are not clean-machine evidence.

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
  - `static-checks`, `unit-tests`, and `windows-core-smoke` use `requirements-dev.txt`.
  - `native-artifacts` uses `requirements-build.txt`.
  - `packaging-smoke` uses both `requirements-build.txt` and `requirements-ocr.txt`.
- `actions/setup-python@v5` pip caching is enabled per job with deterministic dependency keys via `cache-dependency-path` pinned to the exact requirements file used by that job.

### Cache determinism and safety

- The cache key includes the dependency file hash (via `cache-dependency-path`) and the selected Python version, so cache reuse is deterministic for unchanged dependency manifests.
- Any edit to `requirements-dev.txt`, `requirements-build.txt`, or `requirements-ocr.txt` automatically invalidates the relevant pip cache and forces a refresh.
- This keeps cache behavior safe for dependency updates while preserving faster warm-cache installs for unchanged dependency sets.

## CI duration measurement (before/after)

At the time of this topology change, the measurement was taken from a local
container without GitHub Actions run-history access. The recorded comparison is
therefore a **critical-path structural measurement** from `ci.yml`:

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
- [ ] Optional/manual non-blocking checks reviewed as needed (`packaging-smoke`, `windows-startup-benchmark`)
- [ ] Local Google conversion smoke evidence is recorded for the exact promoted RC artifact

### Additional checklist for parser plugin changes

When a PR touches parser plugin contracts/registry/plugins, also complete the governance checklist in:

- [`docs/release_checks/parser_plugin_rollout_runbook.md`](./release_checks/parser_plugin_rollout_runbook.md)
- [`docs/parser_plugins/README.md`](./parser_plugins/README.md)

### Windows incident feature qualification

The explicit `diagnostic_mode=startup` discriminator runs the existing feature
journey with fixed empty startup-phase markers enabled only for synthetic normal
starts. Failed pre-readiness receipts may include a closed `startup_phases` list;
an empty list is unknown, not proof of a bootloader or import failure. Exclusive
marker creation adds filesystem work and can affect timing. This mode cannot
upload a qualified development package. Default `full` mode leaves the probe
disabled and remains the package qualification path; containment, cleanup,
identity, privacy and all positive/negative controls remain mandatory.

The owner-only public Windows lane `windows-diagnostic-qualification` is selected explicitly by `run_windows_diagnostic_qualification=1` (default 0), capped at 45 minutes, and isolated from ordinary CI cancellation. It builds the actual onedir with `build_windows_exe.ps1 -Mode onedir`, then runs a bounded driver with hash-pinned public synthetic input and a restricted ordinary-user child token. The driver checks useful startup/import/export history after child loss, local preview/export, no-development-Python/no-console operation, repeat and concurrent starts, normal main-window startup, observed process roles, missing components and matched performance measurements. The complete tested tree, canonical manifest and exact `qualified-windows-development-package.zip` are bound by SHA-256; that ZIP is the uploaded development package. Only validated fixed-schema receipts and the successful development ZIP are uploaded; scratch databases and business outputs are excluded. This feature-specific proof does not grant release or real-data acceptance.

The restricted qualification token has a private default DACL for newly created
kernel objects: its TokenUser SID and LocalSystem only. Administrator deny-only
membership, removed privileges, medium integrity, Job containment and process
identity checks remain in force. The qualifier verifies the exact non-NULL ACL
readback before launch. This avoids inheriting an elevated build runner's object
permissions that its restricted child cannot use. Native controls compare an
unmodified token's default pipe permissions with an explicit private descriptor,
then verify the corrected token; only closed synthetic outcomes are printed.
This host qualification correction does not grant product users extra rights.

The required native incident cohort includes `tests/test_windows_runtime_audit.py`.
Each synthetic packaged application start also installs an earliest app-only
audit hook with a unique private journal. Before each Popen it records only a
fixed command-purpose enum and bounded callsite category; raw arguments, paths
and frames are never persisted. Journal failures terminate that synthetic run
with exit97, never silently becoming a zero-event result. The launcher does not
install the hook, and ordinary product starts do not enable it.

The qualifier retains physical Job counts and accepts the specific Windows
version-query suffix only when the same run proves one exact system cmd/ver
call through both required CPython platform frames and the exact contained
app-to-system-cmd-to-system-conhost relationship. Unknown members, commands,
parents, late calls, missing samples, mismatched counts and incomplete cleanup
still fail. Every concurrent Job owns its own probe and journal; no receipt is
transferred between runs. Synchronous journal writes, native handle/snapshot
queries and5ms sampling perturb timing and remain part of the measured journey.

### Frozen compute worker qualification (#1134)

The owner-only `windows-portable-onefile` job additionally runs
`scripts/qualify_windows_compute_workers.py` against the same built supervised
onedir through `metroliza.exe`. It runs Extended plots (40 synthetic groups)
and a 200-PDF synthetic import with workers forced off/on, three samples each,
asserts actual worker use and identical DB rows/workbook parts (only declared
persistence clocks and document timestamps excluded), and verifies exact owned
compute images and Job drain. `windows-compute-worker-receipt` is uploaded even
on failure. Existing envelope/launcher first-launch, reopen, incident and cleanup
gates remain required. Windows candidates use 2 workers, minimum 40 groups / 200
reports, independently overrideable by `METROLIZA_EXPORT_GROUP_WORKERS`,
`METROLIZA_EXPORT_GROUP_MIN_GROUPS`, `METROLIZA_IMPORT_PREPARE_WORKERS` and
`METROLIZA_IMPORT_PREPARE_MIN_REPORTS`; `METROLIZA_EXPORT_GROUP_MP=0` disables
render pooling. These are proposed Windows defaults until the exact-build
Windows receipt is inspected; Linux/source measurements do not calibrate them.
