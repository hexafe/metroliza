# Release Status (Active Operations)

This is the active operational status for release freeze, open testing, and final release readiness.
Use this page first for current state, and use archived plans only for historical context.

Status timestamp is tracked in git history for this file.

## Current release window (metadata-driven)

Release/window metadata is defined in `VersionDate.py` and synchronized into user-facing docs with `python scripts/sync_release_metadata.py` (or validated with `--check`).

## Active build identity (single source for this status snapshot)

- Branch: `work`
- Commit SHA: `e86ecd214e21e42a89a28af1e794b33115857a6b`
- Artifact/build ID: `2026.03-build260301-e86ecd2`
- Release line metadata: `RELEASE_VERSION=2026.03`, `VERSION_DATE=260301`

| Track | Status | Notes | Primary doc |
|---|---|---|---|
| Freeze | Pre-freeze checks in progress | Implementation-item triage is complete, but broader freeze scope confirmation and owner assignment gates remain open. | [`release_candidate_checklist.md`](./release_candidate_checklist.md), [`implementation_item_triage.md`](./implementation_item_triage.md) |
| Open testing | Blocked (No-Go) | Do not promote this build to open testing: smoke evidence is recorded for the current build identity but outcome is **FAIL** due to OAuth refresh network/proxy `403 Forbidden`. | [`google_conversion_smoke.md`](./google_conversion_smoke.md), [`open_testing_runbook.md`](./open_testing_runbook.md) |
| Release candidate readiness | Blocked pending smoke rerun | Current RC decision is **No-Go** for build `2026.03-build260301-e86ecd2`; rerun smoke with valid sandbox credentials or cut a new build identity and re-evidence. | [`release_candidate_checklist.md`](./release_candidate_checklist.md), [`google_conversion_smoke.md`](./google_conversion_smoke.md) |
| Google conversion smoke gate | Evidence complete, status FAIL | Evidence package exists (command, outcome notes, and build identity), but gate remains release-blocking until PASS. | [`google_conversion_smoke.md`](./google_conversion_smoke.md) |

## Operating notes

- Active release operations are governed by documents under `docs/release_checks/`.
- Archived planning docs are references only and should not be used as the operational status tracker.
- If status changes, update this page first, then update linked runbooks/checklists as needed.

## Historical context (archive)

- [`../archive/2026/IMPLEMENTATION_PLAN.md`](../archive/2026/IMPLEMENTATION_PLAN.md)
- [`../archive/2026/TODO.md`](../archive/2026/TODO.md) *(optional historical reference; non-operational)*
- [`../archive/2026/GOOGLE_SHEETS_MIGRATION_PLAN.md`](../archive/2026/GOOGLE_SHEETS_MIGRATION_PLAN.md)
