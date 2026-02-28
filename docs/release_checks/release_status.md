# Release Status (Active Operations)

This is the active operational status for release freeze, open testing, and final release readiness.
Use this page first for current state, and use archived plans only for historical context.

Last updated: 2026-02-28.

## Current release window (`2026.02` / build `260228`)

| Track | Status | Notes | Primary doc |
|---|---|---|---|
| Freeze | Open (no hard freeze active) | Use normal PR flow; apply RC branch controls once freeze starts. | [`branching_strategy.md`](./branching_strategy.md), [`release_branching_playbook.md`](./release_branching_playbook.md) |
| Open testing | Active | Execute smoke cadence, triage, and handoff evidence collection. | [`open_testing_runbook.md`](./open_testing_runbook.md) |
| Release candidate readiness | In progress | Complete checklist evidence before RC cut/signoff. | [`release_candidate_checklist.md`](./release_candidate_checklist.md) |
| Google conversion smoke gate | Required for RC | Record latest smoke outcome before release decision. | [`google_conversion_smoke.md`](./google_conversion_smoke.md) |

## Operating notes

- Active release operations are governed by documents under `docs/release_checks/`.
- Archived planning docs are references only and should not be used as the operational status tracker.
- If status changes, update this page first, then update linked runbooks/checklists as needed.

## Historical context (archive)

- [`../archive/2026/IMPLEMENTATION_PLAN.md`](../archive/2026/IMPLEMENTATION_PLAN.md)
- [`../archive/2026/TODO.md`](../archive/2026/TODO.md)
- [`../archive/2026/GOOGLE_SHEETS_MIGRATION_PLAN.md`](../archive/2026/GOOGLE_SHEETS_MIGRATION_PLAN.md)
