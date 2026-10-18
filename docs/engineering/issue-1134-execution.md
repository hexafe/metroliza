# #1134 — frozen compute workers

Authority: supplied Issue #1134 and execution instructions; local-only work on
`feat/1134-frozen-compute-workers`, from RC2 candidate
`67a5fea10eee0607ed711503f0872fd9183ffd88`. No remote operations authorized.
Whole-PR class: FEATURE / CROSS-LAYER (packaging, process ownership, both pools,
Windows qualification). Coordinator only; runtime model/reasoning: not visible.
Sources: AGENTS.md, project README/architecture/development workflow, branch policy,
AI routing and packet/report templates, OCR worker/spec, identity/audit/probe,
both pools, portable qualification, startup route measurement and portable CI job.

## MUST

- Dedicated compute executable dispatches freeze support before application code;
  no Qt runtime/hooks. Frozen pools use its validated package identity with spawn.
- Preserve source behavior, ordered results, parent-only persistence/workbook ownership,
  bounded queues, serial fallback and supervised descendant cleanup.
- Register immutable component and explicitly verify owned compute topology.
- Add self-checking built supervised Windows qualification: >=40 Extended-plots
  groups and >=200 synthetic PDFs, forced on/off, equivalence, median-of-three
  timings, effective worker use and uploaded receipt. Keep existing qualifications.
- Run affected files, complexity/coverage/security gates and Ruff; commit locally.

## SHOULD

- Share executable selection; reject missing/modified packages before pool launch.
- Keep measurement fixtures synthetic and report performance/calibration honestly.

## DEFERRED

- Parallel preflight (Issue #1134 deferred seam); migrations, releases and remote work.
- Windows execution is unavailable here. Proposed Windows defaults require the
  Windows receipt before they can be described as calibrated or release-qualified.

## Validation and handoff

Base snapshot and pre-edit synthetic reference outputs are captured under the
session scratch `codex/1134` directory (archive of HEAD, no second worktree).
The handoff records exact commands/results, comparison, source head and remaining
Windows-only proof. Independent exact-head review and all remote CI belong to the
external orchestrator. Stop before any unapproved remote/destructive operation.

## Implementation handoff

Status: **IMPLEMENTED / LOCAL_VALIDATION_PASS / WINDOWS_EVIDENCE_PENDING**.
Tested implementation: `0bcef2beb8ad7e4646a7ec30d59650f63fa7c515`.
The final handoff commit changes this document only. Independent exact-head review,
Windows CI and acceptance remain with the external orchestrator. No remote actions
were performed. Actual runtime model/reasoning: `not visible`.

### Design and preserved seams

- The onedir spec builds `metroliza_compute_worker.exe` with the standard
  multiprocessing runtime hook, no Qt/UI/bootstrap payload, and freeze support
  before product imports. A direct invocation exits with code 2.
- Both pools use the shared spawn-context selector. Frozen Windows selects the
  fixed sibling only after complete package identity verification; source builds
  keep normal Python spawn. Pool failure retains existing serial recovery.
- The immutable manifest includes the compute image, preserves existing component
  order and keeps provenance last. The identity discriminator adds a missing-compute
  receipt. Supervisor Jobs retain ownership of compute descendants.
- `workers/export_thread_runtime.py` supplies synchronous, instance-local signals
  only inside the compute image. The application continues using real Qt classes.
  Shared Windows-version handling has no feature-package dependency; OCR preserves
  its original fixed failure code and test seam.
- Runtime qualification pairs exact CPython frozen CreateProcess arguments with
  fixed native image identity, application ancestry, observed member counts and
  an empty Job. The four expected compute members represent two separate pools.
  Existing OCR/core qualifications do not acquire an unconditional compute allowance.
- New portable-job qualification runs the built **supervised onedir** through
  `metroliza.exe`, in addition to unchanged envelope/native-launcher qualifications.
  It generates 200 distinct synthetic PDFs and verifies 40 chart groups, alternates
  workers off/on, and records three samples per mode. It rejects silent fallback,
  compares every persisted row and XLSX part/PNG hash, and records native topology,
  package/source identity and timings in an always-uploaded receipt. Only declared
  persistence clocks and XLSX creation/modification timestamps are excluded.

CPython's frozen command builder retains the parent application in argv[0], while
its Windows Popen passes the selected compute image as application_name. The audit
checks both independently. Sources: [CPython spawn](https://github.com/python/cpython/blob/3.11/Lib/multiprocessing/spawn.py),
[Windows Popen](https://github.com/python/cpython/blob/3.11/Lib/multiprocessing/popen_spawn_win32.py),
[PyInstaller hook](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/PyInstaller/hooks/rthooks/pyi_rth_multiprocessing.py).

### Equivalence and timings

Before edits, an archive of the exact base was used to capture outputs from 24
synthetic imported PDFs and one 18-sample render task. No additional Git worktree
was created. Against the final implementation, database rows and all six worksheet
commands, including all four PNG byte payloads, match exactly. The same render task
matches with Qt imports prohibited. The separate 200-PDF/40-group integration test
compares serial and actual spawned workers, including all XLSX parts.

Small **serial source control** measurements, seconds, median of three:

| Workload | Base | Final |
| --- | ---: | ---: |
| One four-PNG group | 1.040 | 1.219 |
| Import 24 PDFs | 0.273 | 0.333 |

Base load average (1/5/15 minutes): 0.976 / 2.330 / 4.292.
Final load: 3.424 / 2.962 / 3.037. These differing-load controls show no speed-up;
they do not establish a Windows performance result or explain the timing difference.
Raw samples, reference outputs, scripts and logs remain in the session scratch
`codex/1134/` directory.

### Exact local commands and results

Working directory for the following commands is the current worktree. The first
command passed **585 tests, 17 skipped** in 167.55 s:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" tests/test_compute_worker_qualification.py tests/test_frozen_compute_worker.py tests/test_export_summary_render_pool.py tests/test_import_prepare_pool.py tests/test_windows_runtime_audit.py tests/test_windows_owned_process_probe.py tests/test_packaging_payload_exclusions.py tests/test_diagnostic_package.py tests/test_ci_policy_sync.py tests/test_qualify_package_identity.py tests/test_complexity_ratchet.py tests/test_bug_sweep_coverage.py tests/test_security_audit.py tests/test_directory_reorganization_architecture.py tests/test_frozen_ocr_worker.py tests/test_package_identity_reasons.py tests/test_portable_supervised_entry.py
```

The related export/compatibility selection passed **488 tests and 32 subtests** in
54.09 s:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" tests/test_backend_diagnostics_boundary.py tests/test_directory_reorganization_architecture.py tests/test_export_dialog_behavior.py tests/test_public_docstrings.py tests/test_phase4_integration_happy_path.py tests/test_export_presets.py tests/test_matplotlib_distribution_geometry.py tests/test_export_plot_helpers.py tests/test_export_workbook_output.py tests/test_analytics_exporting_boundary.py tests/test_phase1_reliability.py tests/test_export_workbook_equivalence.py tests/test_active_dialog_close_guards.py tests/test_export_industrial_context.py tests/test_1089_acceptance_analytics.py tests/test_thread_flow_helpers.py tests/test_export_grouping_and_sorting.py
```

Final base capture/comparison: **2 passed** in 10.84 s:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper CAPTURE_LABEL=final /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" /tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/codex/1134/test_capture.py /tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/codex/1134/test_compare.py
```

```bash
/home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m ruff check .
git diff --check
/home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m bandit -q -r src/metroliza scripts packaging --severity-level medium --format json --exit-zero
```

Ruff and diff checks pass. Bandit reports the same 152 existing medium findings as
the base, with zero new or shifted findings. Export findings remain at lines 3967
and 3987; the baseline file is unchanged. The new read-only SQLite oracle has one
narrow B608 suppression for schema-derived, double-quote-escaped identifiers,
covered by a hostile table-name test. Complexity stays within 147; package-cycle,
Qt-boundary and shared-layer budgets/allowlists are unchanged.

Earlier adverse runs remain in scratch `validation/`: complexity failures,
component-position/provenance fixture failures, four architecture-boundary failures,
and the OCR injection-seam failures. Each was corrected and its affected files
rerun. A broader earlier selection also passed 1,343 tests with 35 skips; it is
not presented as final-implementation evidence.

### MUST evidence and remaining risks

| Requirement | Local evidence | Remaining acceptance |
| --- | --- | --- |
| Dedicated executable and frozen selection | Spec execution tests, identity rejection and real Qt-blocked render/parser probe pass | Actual Windows PyInstaller build and bootloader dispatch |
| Output equivalence and fallback | Captured base equality, 200-PDF/40-group source integration, existing failure/cancellation tests pass | Frozen serial/on output comparison and real native role observations |
| Ownership and identity | Manifest, discriminator, audit adversarial tests and Job-proof validation pass | Built package topology/drain plus unchanged first/reopen/incident/cleanup qualifications |
| Windows defaults | Separate overrideable candidates: 2 workers, 40 groups / 200 reports; CI records median-of-three stage timings and ratios | Windows measurement and review must confirm or revise these candidates; **not yet calibrated** |
| Non-frozen behavior and architecture | Source export/import, compatibility and dependency guards pass | Windows source/frozen and clean-machine evidence remain distinct |

No Windows execution, frozen build, antivirus/startup-cost measurement, hosted CI,
clean-machine qualification, release acceptance or independent review occurred here.
Only the Windows run can prove the frozen scientific payload is complete, the
actual Windows Analysis passes its no-Qt/UI payload guard, spawn arguments dispatch
correctly, the serial and worker package outputs agree, and all observed descendants
drain under the real supervisor. Its measurements must also establish whether the proposed defaults pay
off. The CI step uses the permitted supervised-onedir route; existing separate gates
cover the native launcher and envelope. Hosted evidence will not establish every
clean-machine/antivirus configuration.

Rollback/disable: `METROLIZA_EXPORT_GROUP_MP=0` and
`METROLIZA_IMPORT_PREPARE_WORKERS=0` retain serial processing. No data migration or
preflight parallelization was introduced. No push, PR, merge, rebase, hard reset,
force push, shared stash, release or deployment was performed.

## Windows CI repair packet — run 39134591765

Authority: the external orchestrator's supplied repair task for Issue #1134;
continue locally on the existing branch at `0e094149dc0d926eb76c9cef2c29a95d42fe75c4`.
The approved RC2 base/target and FEATURE / CROSS-LAYER whole-PR classification
remain unchanged. This repair is BOUNDED INTEGRATION, coordinator-only because
the launch classifier, receipt and regression evidence form one bounded slice.
Runtime model/reasoning: `not visible`. No remote operations are authorized.

### MUST

- Explicitly close both SQLite test connections while preserving transactions.
- Diagnose the four rejected launch events without expanding accepted process
  roles, command signatures, counts, ancestry or cleanup allowances.
- Retain the failed run, failing stage and bounded audit events in the receipt
  and print that evidence, including failures during topology verification.
- Record import preflight, prepare and persist timings; preserve output and
  processing behavior. Run related files and all required local quality gates.
- Commit locally, with Issue #1134 and the requested co-author trailer.

### SHOULD

- Preserve completed workload timings when a later topology check fails.
- Explain timing scopes and retain base-versus-final synthetic output evidence
  under the session scratch `codex/1134-ci-fix/` directory.

### DEFERRED

- Import optimization, parallel preflight, audit allowlist expansion, runtime
  upgrades, remote operations, Windows execution and frozen-build acceptance.
  The external orchestrator owns the Windows rerun and independent review.

Owned files: this execution record, `tests/test_compute_worker_qualification.py`,
`tests/test_frozen_compute_worker.py`, `tests/test_windows_runtime_audit.py`,
`src/metroliza/shared/diagnostic_runtime_audit.py`,
`src/metroliza/app/compute_worker_qualification.py`, and
`scripts/qualify_windows_compute_workers.py`. Keep pipeline, packaging, OCR,
SQLite schema, security baseline and complexity budget unchanged. Stop and
escalate if a repair requires crossing these boundaries. Validation is source
evidence only; the recorded Windows failure supersedes the earlier local-pass
claim for frozen qualification.

## Windows CI repair handoff

Status: **SOURCE_FIX / LOCAL_CHECKS_PASS / WINDOWS_RERUN_REQUIRED**.
Implementation head: `411a58cce70c437489608698f89261d9d26fe275`; the next
commit only records this handoff. Starting head:
`0e094149dc0d926eb76c9cef2c29a95d42fe75c4`. Actual runtime model/reasoning:
`not visible`. Coordinator-only routing remained adequate for the bounded fix;
external independent exact-head review and Windows CI remain outstanding.

### Diagnosis and design

The saved CI log contains four `other_command` events, zero
`compute_worker_launch` events, four verified compute images and exactly one
NumPy-owned command/console pair. The four rejected events correspond to the
compute launches, not four extra version-probing subprocesses. CPython 3.11.9
[passes a command-line PyObject pointer to the native audit event using `uuu`](https://github.com/python/cpython/blob/v3.11.9/Modules/_winapi.c#L1184),
which treats it as wide-character data. The synchronous Python caller still
holds the actual command passed to CreateProcess.

- The classifier now requires the **immediate**
  `multiprocessing.popen_spawn_win32.__init__` frame, matches its `python_exe`
  to the native event's executable, and validates its actual `cmd` using the
  existing exact frozen command signature. Native cwd, fixed image identity,
  application ancestry, member counts, phases and empty-Job proof remain
  required. It never serializes command lines or frame locals. Outer-frame,
  missing-local, changed-command/image/cwd and unrelated-caller cases fail.
- The log also shows NumPy's lazy parent version probe **between** the import
  and export pools, incompatible with the existing strict helper-before-compute
  order. The synthetic qualification entry now installs the existing native
  Windows-version fallback before lazy workload imports. No audit roles,
  allowlists, ordering rules or topology validators were changed. Worker
  freeze-support dispatch remains unchanged.
- Both SQLite fixtures use `closing(connection), connection`, preserving commit
  behavior and explicit closure on Windows.
- The host registers each run before launch, records its stage, reads completed
  workload timings before topology verification, snapshots bounded runtime
  events/owned-process evidence before journal cleanup, and prints the final
  receipt. Failures identify the stage, run and fixed failure code. Arbitrary
  exception text is omitted.
- Import profiling exists only in the explicit synthetic qualification workflow.
  `stage_seconds.preflight` measures the initial scan; `prepare` measures parser
  construction/preparation and parent-side pool wait; `persist` measures the
  persistence callback; `other_pipeline` contains setup, source approval and
  cleanup outside those callbacks. These are parent wall times, not summed
  worker CPU times. Existing `seconds` still excludes the initial preflight;
  `total_seconds` includes it. Hooks restore on success and failure. No import
  algorithm, optimization, schema or normal UI path was changed.

### MUST evidence

| Requirement | Evidence | Result |
| --- | --- | --- |
| Explicit SQLite closure | Full `test_db_utils.py`, including repository AST rule | PASS locally |
| Exact compute launch observation | Native-event corruption simulation, live Python call-frame observation and adversarial rejection cases | PASS locally; real Windows pending |
| Preserve topology contract | Existing role/count/ancestry/drain tests; native fallback installed before synthetic workloads | PASS locally; built package pending |
| Self-explaining failures | Injected topology rejection retains workload, stage, fixed failure code, audit events and empty-Job evidence before close; timeout run is registered before launch | PASS locally |
| Import stage timing | Deterministic 1/2/3/4-second stage test, hook restoration on failure, real 200-report serial/worker timing fields | PASS locally |
| Equivalence and quality gates | Captured base equality, full 200-report/40-group integration, required gates below | PASS locally |

Changed scope: this document, `scripts/qualify_windows_compute_workers.py`,
`src/metroliza/app/compute_worker_qualification.py`,
`src/metroliza/shared/diagnostic_runtime_audit.py`,
`tests/test_compute_worker_qualification.py`, and
`tests/test_windows_runtime_audit.py`. No new repository files need coverage
ownership. No security baseline, complexity budget, packaging or pipeline file
was changed. No push, PR, merge, rebase, hard reset, force push or stash occurred.

### Equivalence and before/after controls

A `git archive` of the exact starting head was captured before implementation
under session scratch `codex/1134-ci-fix/base/`; no extra worktree was created.
Three baseline and three final source trials imported 24 synthetic reports and
rendered one four-PNG group. All persisted non-clock rows and all worksheet
commands, including exact PNG bytes, match. The separate integration test
compares all database rows and XLSX parts for 200 reports/40 groups with actual
spawned workers enabled and disabled.

| Source serial control, median of three (seconds) | Base | Updated |
| --- | ---: | ---: |
| Import 24 synthetic PDFs | 0.397 | 0.295 |
| Render one four-PNG group | 1.753 | 1.582 |

Load averages (1/5/15 minutes) at capture: base 8.572 / 8.458 / 5.623;
updated 9.028 / 8.583 / 5.770. These are differing-load source controls, not a
speedup claim or Windows calibration. The reported CI serial 200-report import
72.571 s/export 63.154 s remain the prior Windows measurements; no new packaged
Windows measurement exists. Scripts, raw samples, comparison and scan outputs
remain under the authorized session scratch `codex/1134-ci-fix/` directory.

### Exact commands and results

All tests used the required persistent-QApplication plugin and disabled cores.
The first selection passed **167 tests, 13 skipped, 5 subtests** in 10.21 s:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" tests/test_windows_runtime_audit.py tests/test_frozen_compute_worker.py tests/test_db_utils.py
```

The qualification integration and required gates passed **126 tests** in
173.99 s. Two additional failure/native-order tests were added afterward and
passed in the following related selection; the integration implementation and
quality-gated production paths were unchanged except for the tested native
fallback at the separate smoke entry.

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" tests/test_compute_worker_qualification.py tests/test_complexity_ratchet.py tests/test_bug_sweep_coverage.py tests/test_security_audit.py
```

The final related selection passed **149 tests, 3 skipped, 1 deselected** in
22.40 s (`large_real` is the already-passed 200-report integration):

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" tests/test_compute_worker_qualification.py -k 'not large_real' tests/test_frozen_ocr_worker.py tests/test_windows_owned_process_probe.py tests/test_export_summary_render_pool.py tests/test_import_prepare_pool.py tests/test_directory_reorganization_architecture.py tests/test_packaging_payload_exclusions.py
```

The required gates were rerun against implementation head `411a58cc` after all
production changes: **118 passed** in 66.06 s.

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" tests/test_complexity_ratchet.py tests/test_bug_sweep_coverage.py tests/test_security_audit.py
```

Base workload capture (cwd: scratch `codex/1134-ci-fix/base/`) passed **1 test**
in 8.78 s; final workload capture (cwd: working root) passed **1 test** in 7.48 s:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper CAPTURE_LABEL=base-workload /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" /tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/codex/1134-ci-fix/test_capture.py
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper CAPTURE_LABEL=final-workload /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" /tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/codex/1134-ci-fix/test_capture.py
```

Exact saved-output comparison passed **1 test** in 0.01 s:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" /tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/codex/1134-ci-fix/test_compare.py
```

```bash
/home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m ruff check .
git diff --check
/home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m bandit -q -r src/metroliza scripts packaging --severity-level medium --format json --exit-zero -o /tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/codex/1134-ci-fix/bandit-final.json
```

Ruff and diff checks pass. Base and updated Bandit scans each contain the same
152 medium findings at the same file/line/test/message identities, with zero new
or shifted findings. `config/security/bandit_baseline.json` is unchanged.
An initial Ruff E731 test-fixture finding was corrected before commit.

### Open proof and risks

Windows/frozen build, real native audit argument recovery, packaged worker
startup, strict topology order after removal of the parent helper pair, packaged
output equivalence and per-stage Windows timings are **not verified locally**.
The immediate-frame adapter deliberately depends on the qualified CPython
multiprocessing caller and local names; an upstream implementation change fails
closed and needs renewed review. Linux mocks/source checks do not replace the
orchestrator's Windows CI rerun. No full suite, release acceptance, clean-machine
proof or independent external review was claimed. The import slowdown remains
undiagnosed pending the new Windows stage measurements, as requested.

## Review-fix integration packet — 2026-10-18

Authority: external orchestrator's current #1134 integration request. Merge the
local remote-tracking ref `origin/build/rc2-candidate-20261018` at
`ea72c9e9616eac1006c0b96412b969023c68f7dc` into this worktree's current branch,
`feat/1134-frozen-compute-workers`, starting at
`c1c292bbf0ea09d784c6ffa0b6c811cf67ec20f9`. A normal local merge commit is
explicitly authorized; push, PR creation/merge, rebase and destructive Git
operations are excluded. No second worktree or remote actions are needed.

Whole PR remains FEATURE / CROSS-LAYER; this slice is BOUNDED INTEGRATION of
accepted pool fixes, with concurrency/lifecycle checks retained. Coordinator
only; no delegated writers. Runtime model/reasoning: `not visible`. Provider
reserve: UNKNOWN; external Claude Code orchestrator owns independent exact-head
review, push and Windows CI. The reported earlier CI run `39137432316` is supplied
context, not evidence for this new integrated head.

### MUST

- Preserve #1130 render polling (100 ms), shared cancellation at chart boundaries,
  cancellation-aware serial replay, and bounded cooperative/terminate/kill/reap.
- Preserve #1132 import cancellation without serial re-preparation, bounded
  terminate/kill/reap, and ownership retention if shutdown fails.
- Use #1134's shared spawn selector and validated compute executable for supported
  frozen Windows pools. Unsupported/unvalidated frozen packages stay serial,
  including explicit import worker counts. Revalidate identity at launch.
- Keep every test function from both parents, adapt combined-policy fixtures
  explicitly, run affected pool/frozen/qualification/equivalence tests and gates,
  and commit locally with the requested issue reference and co-author trailer.

### SHOULD

- Share the availability guard across both policies, retain separate packaged
  thresholds, and add negative identity and selected-context cancellation tests.
- Capture synthetic pre-merge outputs and median-of-three timing/load receipts
  before edits, under session scratch `codex/1134-integration/`.

### DEFERRED

- Native Windows/frozen executable execution and exact-head Windows CI: external
  orchestrator after push. Linux mocks/source workers do not establish these.
- Review or redesign of unrelated upstream fixes: preserved by the normal merge;
  this task owns the four pool conflicts, shared availability guard, frozen tests
  and this evidence record. No new optimization or changed performance defaults.

### Combined design and test adaptations

`compute_workers_available()` accepts normal source execution, rejects unsupported
frozen platforms, and requires `worker_executable()` package identity validation
for frozen Windows. Both policies consult it before enabling pools. The spawn
selector validates again immediately before process creation. The render event
comes from that same selected context and travels through initializer `initargs`;
compute runtime initialization and shared chart-boundary cancellation both run.
The incoming import cancellation exception and both shutdown implementations are
preserved, using executor-owned process/manager handles regardless of executable.

All test function names from both parents were compared with Python AST sets:
render retains the union (12 functions); import retains the union (18 functions).
Adaptations are:

- The incoming render event-creation failure fixture patches `spawn_context()`
  instead of the replaced direct `multiprocessing.get_context()` call.
- Existing #1134 Windows threshold/default tests explicitly establish validated
  availability. The frozen render context fixture now exposes `Event`, and still
  checks the selected context and packaged worker cap.
- The incoming unsupported-frozen matrix remains intact, alongside the #1134
  validated-Windows defaults and explicit override test.
- The Qt-free compute renderer test retains the original successful-render case
  and adds cancellation before rendering, using the combined initializer/event.

New frozen-policy cases cover Windows/Linux, auto/3/16 counts, and verified,
missing, modified or unavailable package identity. A launch-time identity-change
case proves both pool constructors reject stale policy approval. Selected-context
cancellation cases observe compute image selection, bounded future polling,
shared render event and terminate/kill/join of owned handles; real source-spawn
regressions separately exercise cooperative chart cancellation and stuck-process
reaping. These are explicitly local evidence, not a frozen Windows execution.

### Integration evidence and limitations

Code merge: `08c816b3d7725949bc326c2b9e88708359a9e498`, parents
`c1c292bbf0ea09d784c6ffa0b6c811cf67ec20f9` and
`ea72c9e9616eac1006c0b96412b969023c68f7dc`. The later evidence commit changes
this document only. State: **MERGED LOCALLY / FOCUSED GATES PASS /
INTEGRATED VALIDATION INCOMPLETE**. No push, PR, remote CI, native Windows
execution or independent review was performed in this session.

The nine incoming cancellation/poll/collection/shutdown functions compare equal
by AST to the merge's second parent, including import `_result` and `close`.
See scratch `cancellation-ast.json`. The availability guard/context wiring is the
combined-behavior change; cancellation implementations were not redesigned.

Before editing, `git archive` captured starting HEAD and a synthetic reference
run imported 24 PDFs and rendered one four-PNG group three times. The final
comparison passes: all database values except the existing explicitly declared
wall-clock columns match; worksheet commands/PNG bytes, warnings/details,
labels and backend accounting match exactly. Existing pool tests also compare
new serial versus spawned outputs, providing the serial-base-to-spawned-result
link. Scratch `comparison.json` contains the equality results and raw medians.

| Serial source control, median of 3 (seconds) | Pre-merge | Integrated |
| --- | ---: | ---: |
| One four-PNG group | 1.013453 | 1.336770 |
| Import 24 synthetic PDFs | 0.178987 | 0.250290 |

Load averages (1/5/15 minutes): base **1.133 / 1.228 / 2.484**; integrated
**1.787 / 1.970 / 2.188**. These differing-load controls establish equivalence,
not a speed-up or Windows calibration. This task adds no optimization.

Terminal successful receipts:

- `pools-final.log`: **80 passed**, 25.66 s, on the committed pool integration
  without the diagnostic watchdog.
- `base-capture.log`: **1 passed**, 5.44 s.
- `final-capture.log`: **2 passed**, 6.85 s.
- `frozen-gates-resolved.log`: **151 passed**, 50.51 s; includes the final
  expanded frozen tests plus complexity, ownership and security gates.
- `component-equivalence.log`: **495 passed, 21 skipped, 1 deselected,
  5 subtests passed**, 25.66 s. The deselected case is the large qualification
  workload, deliberately not repeated after the diagnostic crash. Skips include
  platform/package-dependent cases and four historical plot-reference cases
  without their older external references; the fresh pre/post comparison above
  supplies this integration's captured-base evidence.
- `ui-selection.log`: **331 passed, 24 subtests passed**, 63.04 s.
- `parsing-ui-diagnostic.log`: **78 passed, 18 subtests passed**, 17.86 s.
- Ruff: **PASS**; `git diff --check`: **PASS**.

Adverse receipts remain visible:

1. The first gate run, before `git add` resolved the merge index, had 10 coverage
   failures due to duplicate index-stage paths and 141 passes. Resolving the index
   (without changing coverage rules/budgets) yielded the 151-pass receipt above.
2. `integrated.log` recorded a failure and then stopped progressing in the
   parsing-dialog eligibility area. SIGINT did not return it; the task-owned
   parent was terminated with SIGTERM (exit 143). No core was generated by that
   signal. Its exact failed node/traceback was not emitted before the hang.
   The isolated file and smaller UI selection passed, so the broader shared
   session failure remains unresolved and is not replaced by those green runs.
3. A single verbose, stop-on-first-failure diagnostic repetition added
   `faulthandler_timeout=30` to identify that failure. Instead, during
   `test_large_real_import_and_extended_export_match_with_workers_on_and_off`,
   its 30-second watchdog dump stopped partway through a Matplotlib stack and
   the process exited **139 / SIGSEGV**. `coredumpctl info 1935653` confirms
   timestamp 2026-10-18 17:36:16 CEST, TID 1937718, `SI_KERNEL`, **Storage: none**,
   and no generated core. The checked kernel interval has no OOM evidence;
   approximately 27 GiB RAM was available at the check. Cause is unresolved;
   this is not evidence that the pool implementation caused the crash. No crash
   was deliberately reproduced and that diagnostic/large workload was not retried.
   Sanitized local receipt: `crash-receipt.json`.

The earlier broad attempt passed through the large qualification before its UI
failure, but there is no clean terminal integrated receipt. Fresh large-workload
qualification, shared-session stability, exact-head Windows/frozen cancellation,
packaged topology/drain and independent review remain for the external
orchestrator. Existing reported Windows CI is not evidence for this merged head.

Bandit: **152 medium findings**, identical in path/line/code to the previous
source scan (`1134-ci-fix/bandit-final.json`); **zero added, removed or shifted**.
The one unmatched baseline fingerprint is the pre-existing B102 at
`packaging/pyinstaller_common.py:142`; that file's blob is identical to the
starting commit. No baseline was changed. Complexity and ownership budgets were
not changed; no new repository file needs an ownership entry.

### Exact integration commands

All commands ran from this worktree. Outputs are the correspondingly named logs
under session scratch `codex/1134-integration/`; complete command strings are also
in its `commands.json`. The two broad commands below are retained as adverse
receipts, **not recommended reruns**. In particular, do not repeat the crashing
watchdog diagnostic merely to seek green output.

`pools-final`:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" tests/test_export_summary_render_pool.py tests/test_import_prepare_pool.py tests/test_frozen_compute_worker.py
```

`frozen-gates-resolved`:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" tests/test_frozen_compute_worker.py tests/test_complexity_ratchet.py tests/test_bug_sweep_coverage.py tests/test_security_audit.py
```

`component-equivalence`:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" tests/test_compute_worker_qualification.py -k 'not large_real' tests/test_frozen_ocr_worker.py tests/test_windows_runtime_audit.py tests/test_windows_owned_process_probe.py tests/test_diagnostic_package.py tests/test_qualify_package_identity.py tests/test_packaging_payload_exclusions.py tests/test_ci_policy_sync.py tests/test_directory_reorganization_architecture.py tests/test_export_plot_equivalence.py tests/test_export_workbook_equivalence.py tests/test_export_workbook_output.py tests/test_csv_summary_export_equivalence.py tests/test_db_utils.py tests/test_import_single_verification.py tests/test_measure_windows_startup_routes.py tests/test_metadata_review_core.py
```

`ui-selection`:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" tests/test_filter_dialog_behavior.py tests/test_filter_dialog_metadata.py tests/test_main_window_metadata_ui.py tests/test_modifydb_record_model.py tests/test_package_identity_reasons.py tests/test_parsing_dialog_selection_flow.py tests/test_portable_supervised_entry.py tests/test_qt_application_lifetime.py tests/test_report_workspace_shell.py tests/test_xlsx_bulk_sheet.py -x -vv -o faulthandler_timeout=30
```

`parsing-ui-diagnostic`:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" tests/test_parsing_dialog_selection_flow.py -x -vv -o faulthandler_timeout=30
```

`base-capture`:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper CAPTURE_LABEL=base-workload /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" /tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/codex/1134-integration/test_capture.py
```

`final-capture`:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper CAPTURE_LABEL=final-workload /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" /tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/codex/1134-integration/test_capture.py /tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/codex/1134-integration/test_compare.py
```

`integrated`:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" tests/test_export_summary_render_pool.py tests/test_import_prepare_pool.py tests/test_frozen_compute_worker.py tests/test_compute_worker_qualification.py tests/test_frozen_ocr_worker.py tests/test_windows_runtime_audit.py tests/test_windows_owned_process_probe.py tests/test_diagnostic_package.py tests/test_qualify_package_identity.py tests/test_packaging_payload_exclusions.py tests/test_ci_policy_sync.py tests/test_directory_reorganization_architecture.py tests/test_export_plot_equivalence.py tests/test_export_workbook_equivalence.py tests/test_export_workbook_output.py tests/test_csv_summary_export_equivalence.py tests/test_db_utils.py tests/test_filter_dialog_behavior.py tests/test_filter_dialog_metadata.py tests/test_import_single_verification.py tests/test_main_window_metadata_ui.py tests/test_measure_windows_startup_routes.py tests/test_metadata_review_core.py tests/test_modifydb_record_model.py tests/test_package_identity_reasons.py tests/test_parsing_dialog_selection_flow.py tests/test_portable_supervised_entry.py tests/test_qt_application_lifetime.py tests/test_report_workspace_shell.py tests/test_xlsx_bulk_sheet.py
```

`integrated-diagnostic`:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" tests/test_export_summary_render_pool.py tests/test_import_prepare_pool.py tests/test_frozen_compute_worker.py tests/test_compute_worker_qualification.py tests/test_frozen_ocr_worker.py tests/test_windows_runtime_audit.py tests/test_windows_owned_process_probe.py tests/test_diagnostic_package.py tests/test_qualify_package_identity.py tests/test_packaging_payload_exclusions.py tests/test_ci_policy_sync.py tests/test_directory_reorganization_architecture.py tests/test_export_plot_equivalence.py tests/test_export_workbook_equivalence.py tests/test_export_workbook_output.py tests/test_csv_summary_export_equivalence.py tests/test_db_utils.py tests/test_filter_dialog_behavior.py tests/test_filter_dialog_metadata.py tests/test_import_single_verification.py tests/test_main_window_metadata_ui.py tests/test_measure_windows_startup_routes.py tests/test_metadata_review_core.py tests/test_modifydb_record_model.py tests/test_package_identity_reasons.py tests/test_parsing_dialog_selection_flow.py tests/test_portable_supervised_entry.py tests/test_qt_application_lifetime.py tests/test_report_workspace_shell.py tests/test_xlsx_bulk_sheet.py -x -vv -o faulthandler_timeout=30
```

`ruff`:

```bash
/home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m ruff check .
```

`bandit`:

```bash
/home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m bandit -q -r src/metroliza scripts packaging --severity-level medium --format json --exit-zero -o /tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/codex/1134-integration/bandit-final.json
```
