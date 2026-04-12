# Release Status (Active Operations)

This is the active operational status hub for release freeze, open testing, and final release readiness.
Use this page first for current state, and use archived plans only for historical context.

Status timestamp is tracked in git history for this file.

## Current release window (metadata-driven)

Release/window metadata is defined in `VersionDate.py` and synchronized into user-facing docs with `python scripts/sync_release_metadata.py` (or validated with `--check`).

## Active release line

- Release line metadata (canonical): `RELEASE_VERSION=2026.03rc3`, `VERSION_DATE=260329`
- Build/evidence branch, commit SHA, and artifact/build ID must be refreshed in the linked evidence docs whenever smoke evidence changes; do not rely on stale branch-local snapshot values in this file.

| Track | Status | Notes | Primary doc |
|---|---|---|---|
| Freeze | In progress | Use the RC checklist and implementation triage to record current blockers, owner assignments, and sign-offs for the active build identity. | [`release_candidate_checklist.md`](./release_candidate_checklist.md), [`implementation_item_triage.md`](./implementation_item_triage.md) |
| Open testing | Status tracked in linked evidence docs | Read the latest go/no-go state from the current smoke log and runbook evidence package, not from older branch snapshots. | [`google_conversion_smoke.md`](./google_conversion_smoke.md), [`open_testing_runbook.md`](./open_testing_runbook.md) |
| Release candidate readiness | Status tracked in linked checklist and smoke evidence | The current RC decision must be based on the latest checklist state plus the current smoke evidence bundle. | [`release_candidate_checklist.md`](./release_candidate_checklist.md), [`google_conversion_smoke.md`](./google_conversion_smoke.md) |
| Google conversion smoke gate | Status tracked in smoke log | The latest PASS/FAIL result, command, and build identity belong in the smoke log for the current release line. | [`google_conversion_smoke.md`](./google_conversion_smoke.md) |

## Operating notes

- Gate semantics quick reference:
  - **PR-blocking CI gates** are defined in [`../ci-policy.md`](../ci-policy.md) and must be green for merge readiness.
  - **Release-blocking manual evidence gates** are defined in [`release_candidate_checklist.md`](./release_candidate_checklist.md) and must be complete for RC Go decisions.
  - Optional/manual workflow-dispatch lanes (`packaging-smoke`, `google-conversion-smoke`) are non-blocking for normal PR CI but may be linked as release confidence evidence when executed.
- Active release operations are governed by documents under `docs/release_checks/`.
- Current QA counts, exact commit SHAs, and artifact identifiers should be recorded in the linked evidence docs and CI runs when status changes; counts from older revisions of this file are historical only.
- Latest local QA/docs audit on the current branch state: `pytest tests -q --cov=. --cov-report=term --cov-report=xml:coverage.xml` passed (`1103 passed, 19 skipped, 57 subtests passed`, total coverage `83%`), targeted native chart/docs checks passed (`60 passed` across chart parity/spec/smoke and docs-policy suites), and hygiene checks passed (`ruff check .`, `git diff --check`).
- Active export-path follow-up docs: [`../roadmaps/exporter_audit_2026_03.md`](../roadmaps/exporter_audit_2026_03.md) for remaining structural backlog, plus [`../roadmaps/2026_03_rc2_stabilization_execution.md`](../roadmaps/2026_03_rc2_stabilization_execution.md) as the RC2 closeout/reference tracker.
- During RC2 closeout, only small behavior-preserving, test-backed stabilization slices should move forward; larger decomposition/architecture moves remain deferred per triage.
- Superseded planning docs are references only and should not be used as the operational status tracker (`../roadmaps/2026_03_rc1_test_ci_execution_tracker.md`, `../roadmaps/test_ci_audit_execution.md`).
- If status changes, update this page first, then update linked runbooks/checklists as needed.

## Historical context (archive)

- [`../archive/2026/IMPLEMENTATION_PLAN.md`](../archive/2026/IMPLEMENTATION_PLAN.md)
- [`../archive/2026/TODO.md`](../archive/2026/TODO.md) *(optional historical reference; non-operational)*
- [`../archive/2026/GOOGLE_SHEETS_MIGRATION_PLAN.md`](../archive/2026/GOOGLE_SHEETS_MIGRATION_PLAN.md)
