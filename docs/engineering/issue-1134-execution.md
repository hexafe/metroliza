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
