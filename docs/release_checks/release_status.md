# Release Status (Active Operations)

This is the active operational status for release freeze, open testing, and final release readiness.
Use this page first for current state, and use archived plans only for historical context.

Status timestamp is tracked in git history for this file.

## Current release window (metadata-driven)

Release/window metadata is defined in `VersionDate.py` and synchronized into user-facing docs with `python scripts/sync_release_metadata.py` (or validated with `--check`).

## Active build identity (single source for this status snapshot)

- Branch: `work`
- Commit SHA: `84a2302475b3559f319eb225b554a7f3bfbbc214` *(snapshot commit for the status evidence below)*
- Artifact/build ID: `2026.03rc1-build260307-84a2302`
- Release line metadata (canonical): `RELEASE_VERSION=2026.03rc1`, `VERSION_DATE=260307`

| Track | Status | Notes | Primary doc |
|---|---|---|---|
| Freeze | Pre-freeze checks in progress | Implementation-item triage is complete, but broader freeze scope confirmation and owner assignment gates remain open. | [`release_candidate_checklist.md`](./release_candidate_checklist.md), [`implementation_item_triage.md`](./implementation_item_triage.md) |
| Open testing | Blocked (No-Go) | Do not promote this build to open testing: latest smoke evidence for build `2026.03-build260305-84a2302` is **FAIL** at credential preflight (`SmokeConfigError` missing local-only `credentials.json`). | [`google_conversion_smoke.md`](./google_conversion_smoke.md), [`open_testing_runbook.md`](./open_testing_runbook.md) |
| Release candidate readiness | Blocked pending smoke rerun | Current RC decision is **No-Go** for build `2026.03-build260305-84a2302`; provide valid sandbox OAuth bootstrap files and rerun smoke, or cut a superseding build identity and re-evidence. | [`release_candidate_checklist.md`](./release_candidate_checklist.md), [`google_conversion_smoke.md`](./google_conversion_smoke.md) |
| Google conversion smoke gate | Evidence complete, status FAIL | Evidence package is up to date for build `260305` (command, log path, and build identity captured), but gate remains release-blocking until PASS. | [`google_conversion_smoke.md`](./google_conversion_smoke.md) |

## Operating notes

- Gate semantics quick reference:
  - **PR-blocking CI gates** are defined in [`../ci-policy.md`](../ci-policy.md) and must be green for merge readiness.
  - **Release-blocking manual evidence gates** are defined in [`release_candidate_checklist.md`](./release_candidate_checklist.md) and must be complete for RC Go decisions.
  - Optional/manual workflow-dispatch lanes (`packaging-smoke`, `google-conversion-smoke`) are non-blocking for normal PR CI but may be linked as release confidence evidence when executed.
- Active release operations are governed by documents under `docs/release_checks/`.
- Snapshot IDs in runbooks/log evidence may differ from current `VersionDate.py` metadata when they represent earlier captured smoke runs; this is expected if the snapshot date/build context is explicitly documented.
- Active operational execution tracker: [`../roadmaps/2026_03_rc2_stabilization_execution.md`](../roadmaps/2026_03_rc2_stabilization_execution.md) (RC2 parity-first structural risk reduction, not rewrite scope).
- During RC2, only small behavior-preserving, test-backed stabilization slices should move forward; larger decomposition/architecture moves remain deferred per triage.
- Superseded planning docs are references only and should not be used as the operational status tracker (`../roadmaps/2026_03_rc1_test_ci_execution_tracker.md`, `../roadmaps/test_ci_audit_execution.md`).
- If status changes, update this page first, then update linked runbooks/checklists as needed.

## Historical context (archive)

- [`../archive/2026/IMPLEMENTATION_PLAN.md`](../archive/2026/IMPLEMENTATION_PLAN.md)
- [`../archive/2026/TODO.md`](../archive/2026/TODO.md) *(optional historical reference; non-operational)*
- [`../archive/2026/GOOGLE_SHEETS_MIGRATION_PLAN.md`](../archive/2026/GOOGLE_SHEETS_MIGRATION_PLAN.md)
