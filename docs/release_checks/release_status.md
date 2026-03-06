# Release Status (Active Operations)

This is the active operational status for release freeze, open testing, and final release readiness.
Use this page first for current state, and use archived plans only for historical context.

Status timestamp is tracked in git history for this file.

## Current release window (metadata-driven)

Release/window metadata is defined in `VersionDate.py` and synchronized into user-facing docs with `python scripts/sync_release_metadata.py` (or validated with `--check`).

## Active build identity (single source for this status snapshot)

- Branch: `work`
- Commit SHA: `84a2302475b3559f319eb225b554a7f3bfbbc214`
- Artifact/build ID: `2026.03-build260305-84a2302`
- Release line metadata: `RELEASE_VERSION=2026.03`, `VERSION_DATE=260305`

| Track | Status | Notes | Primary doc |
|---|---|---|---|
| Freeze | Pre-freeze checks in progress | Implementation-item triage is complete, but freeze scope lock, release owner assignment, and metadata sync checks remain open in the RC checklist. | [`release_candidate_checklist.md`](./release_candidate_checklist.md), [`implementation_item_triage.md`](./implementation_item_triage.md) |
| Open testing | Blocked (No-Go) | Do not promote build `2026.03-build260305-84a2302`: release-gated Google smoke evidence is not yet recorded for this build identity, and the prior `260301` run ended **FAIL** (`403 Forbidden`) and cannot be reused. | [`google_conversion_smoke.md`](./google_conversion_smoke.md), [`open_testing_runbook.md`](./open_testing_runbook.md) |
| Release candidate readiness | Blocked pending current-build smoke evidence | Current RC decision is **No-Go** for build `2026.03-build260305-84a2302`; run smoke on branch `work` commit `84a2302475b3559f319eb225b554a7f3bfbbc214` and capture a PASS evidence set before promotion (or cut a superseding build and re-evidence). | [`release_candidate_checklist.md`](./release_candidate_checklist.md), [`google_conversion_smoke.md`](./google_conversion_smoke.md) |
| Google conversion smoke gate | Blocked (no PASS for current build) | Latest recorded evidence targets prior build `2026.03-build260301-e86ecd2` and is **FAIL**; gate remains release-blocking until a PASS is captured for active build `2026.03-build260305-84a2302`. | [`google_conversion_smoke.md`](./google_conversion_smoke.md) |

## Operating notes

- Active release operations are governed by documents under `docs/release_checks/`.
- Archived planning docs are references only and should not be used as the operational status tracker.
- If status changes, update this page first, then update linked runbooks/checklists as needed.

## Historical context (archive)

- [`../archive/2026/IMPLEMENTATION_PLAN.md`](../archive/2026/IMPLEMENTATION_PLAN.md)
- [`../archive/2026/TODO.md`](../archive/2026/TODO.md) *(optional historical reference; non-operational)*
- [`../archive/2026/GOOGLE_SHEETS_MIGRATION_PLAN.md`](../archive/2026/GOOGLE_SHEETS_MIGRATION_PLAN.md)
