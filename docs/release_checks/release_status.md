# Release Status (Active Operations)

This is the active operational status hub for release freeze, open testing, and final release readiness.
Use this page first for current state, and use archived plans only for historical context.

Status timestamp is tracked in git history for this file.

## Current release window (metadata-driven)

Release/window metadata is defined in `src/metroliza/app/version.py` and synchronized into user-facing docs with `python scripts/sync_release_metadata.py` (or validated with `--check`).

## Active release line

- Release line metadata is canonical in `src/metroliza/app/version.py` (`RELEASE_VERSION`, `VERSION_DATE`, and `CURRENT_RELEASE_HIGHLIGHT`); `VersionDate.py` remains a compatibility import.
- Build/evidence branch, commit SHA, and artifact/build ID must be refreshed in the linked evidence docs whenever smoke evidence changes; do not rely on stale branch-local snapshot values in this file.

| Track | Status | Notes | Primary doc |
|---|---|---|---|
| Freeze | In progress | Use the RC checklist and implementation triage to record current blockers, owner assignments, and sign-offs for the active build identity. | [`release_candidate_checklist.md`](./release_candidate_checklist.md), [`implementation_item_triage.md`](./implementation_item_triage.md) |
| Open testing | Status tracked in linked evidence docs | Read the latest go/no-go state from the current smoke log and runbook evidence package, not from older branch snapshots. | [`google_conversion_smoke.md`](./google_conversion_smoke.md), [`open_testing_runbook.md`](./open_testing_runbook.md) |
| Release candidate readiness | Status tracked in linked checklist and smoke evidence | The current RC decision must be based on the latest checklist state plus the current smoke evidence bundle. | [`release_candidate_checklist.md`](./release_candidate_checklist.md), [`google_conversion_smoke.md`](./google_conversion_smoke.md) |
| Current rc2 hardening audit | Reorg complete / release blocked | The layout migration is complete on `rc2`; local QA/release gates were refreshed for dashboard UX/copy unification, static POPULATION layer support, Export/CSV Summary grouping cleanup, the raised 80% combined coverage gate, end-user training docs, startup/dashboard telemetry hardening, the selected-style reset Codex review fix, the analytics/export/grouping hardening slice, HTML dashboard histogram overlay coordinate parity, PyInstaller onefile bootloader splash support, summary-sheet planning extraction, CSV Summary file-name auto-grouping, full-module audit hardening, RC5 large-group dashboard optimization, dashboard visual setting cleanup, Industrial Data cache-to-CSV Summary analysis, Industrial Data fetch-to-cache CSV Summary follow-up, parser handoff integrity, and cache-first Industrial Data launcher export in build `260611`. Current validated rc2 implementation SHA `9a9310604604077b26fc5b2a4523459a4e14c5de` passed default GitHub Actions CI in run [`27327220468`](https://github.com/hexafe/metroliza/actions/runs/27327220468). Current local evidence is tracked in [`full_module_audit_2026-06-08.md`](./full_module_audit_2026-06-08.md), [`rc5_dashboard_industrial_cache_check_2026-06-09.md`](./rc5_dashboard_industrial_cache_check_2026-06-09.md), [`rc5_industrial_data_csv_summary_followup_2026-06-10.md`](./rc5_industrial_data_csv_summary_followup_2026-06-10.md), and [`rc5_parser_ux_release_closeout_2026-06-11.md`](./rc5_parser_ux_release_closeout_2026-06-11.md). Final Go remains blocked on manual release evidence and any explicit must-fix triage items. | [`release_candidate_checklist.md`](./release_candidate_checklist.md), [`implementation_item_triage.md`](./implementation_item_triage.md), [`full_module_audit_2026-06-08.md`](./full_module_audit_2026-06-08.md), [`rc5_dashboard_industrial_cache_check_2026-06-09.md`](./rc5_dashboard_industrial_cache_check_2026-06-09.md), [`rc5_industrial_data_csv_summary_followup_2026-06-10.md`](./rc5_industrial_data_csv_summary_followup_2026-06-10.md), [`rc5_parser_ux_release_closeout_2026-06-11.md`](./rc5_parser_ux_release_closeout_2026-06-11.md) |
| Google conversion smoke gate | Status tracked in smoke log | The latest PASS/FAIL result, command, and build identity belong in the smoke log for the current release line. | [`google_conversion_smoke.md`](./google_conversion_smoke.md) |

## Current rc2 CI evidence

- Commit `05b5049558509060df43778d7b39424726e56ff1` (`Fix dashboard datetime axis scaling`) passed default GitHub Actions CI in run [`26875151720`](https://github.com/hexafe/metroliza/actions/runs/26875151720) on 2026-06-03.
- Green automatic jobs: Static checks, Unit tests with combined coverage artifact upload, Native wheel build and smoke checks, CMM parser perf guardrail, and the non-blocking Performance benchmark trend check.
- Skipped manual/opt-in jobs in that run: Packaging smoke, Windows startup benchmark, and Google conversion smoke. These skipped lanes do not satisfy release-promotion evidence.
- Commit `24a50ed069cd45c927f40d10ea0c989a7800915f` (`Update dashboard training docs`) was fast-forwarded to `rc2` and passed GitHub Actions CI in run [`26891179285`](https://github.com/hexafe/metroliza/actions/runs/26891179285) on 2026-06-03.
- Green automatic jobs for run `26891179285`: Static checks, Unit tests with combined coverage artifact upload, Native wheel build and smoke checks, CMM parser perf guardrail, and the non-blocking Performance benchmark trend check.
- Skipped manual/opt-in jobs in run `26891179285`: Packaging smoke, Windows startup benchmark, and Google conversion smoke. These skipped lanes do not satisfy release-promotion evidence.
- Commit `60e0278739d3d696715f94c3c2eefe155a7f11fd` (`Fix dashboard selected style reset`) was fast-forwarded to `rc2` and passed GitHub Actions CI in run [`26947482310`](https://github.com/hexafe/metroliza/actions/runs/26947482310) on 2026-06-04.
- Green automatic jobs for run `26947482310`: Static checks, Unit tests with combined coverage artifact upload, Native wheel build and smoke checks, CMM parser perf guardrail, and the non-blocking Performance benchmark trend check.
- Skipped manual/opt-in jobs in run `26947482310`: Packaging smoke, Windows startup benchmark, and Google conversion smoke. These skipped lanes do not satisfy release-promotion evidence.
- Commit `ad186fa0a748b65ba941e11916d322771a6771fe` (`Harden export analytics and grouping`) was fast-forwarded to `rc2` and passed GitHub Actions CI in run [`26951307852`](https://github.com/hexafe/metroliza/actions/runs/26951307852) on 2026-06-04.
- Green automatic jobs for run `26951307852`: Static checks, Unit tests with combined coverage artifact upload, Native wheel build and smoke checks, CMM parser perf guardrail, and the non-blocking Performance benchmark trend check.
- Skipped manual/opt-in jobs in run `26951307852`: Packaging smoke, Windows startup benchmark, and Google conversion smoke. These skipped lanes do not satisfy release-promotion evidence.
- Commit `80a1802fce2ff58c7c70e6dfa86ff5e1c5656c8c` (`Classify PyInstaller splash import`) passed default GitHub Actions CI in run [`27006471511`](https://github.com/hexafe/metroliza/actions/runs/27006471511) on 2026-06-05.
- Green automatic jobs for run `27006471511`: Static checks, Unit tests with combined coverage artifact upload, Native wheel build and smoke checks, CMM parser perf guardrail, and the non-blocking Performance benchmark trend check.
- Skipped manual/opt-in jobs in run `27006471511`: Packaging smoke, Windows startup benchmark, and Google conversion smoke. These skipped lanes do not satisfy release-promotion evidence.
- Commit `aaa0ebdc32d31b9c05005da8408bca4a240f8373` (`Refresh release evidence and summary planning`) passed default GitHub Actions CI in run [`27021152454`](https://github.com/hexafe/metroliza/actions/runs/27021152454) on 2026-06-05.
- Green automatic jobs for run `27021152454`: Static checks, Unit tests with combined coverage artifact upload, Native wheel build and smoke checks, CMM parser perf guardrail, and the non-blocking Performance benchmark trend check.
- Skipped manual/opt-in jobs in run `27021152454`: Packaging smoke, Windows startup benchmark, and Google conversion smoke. These skipped lanes do not satisfy release-promotion evidence.
- Commit `e0af5d8ec4075aa266a76610b4b6f608fffb2bd7` (`Add CSV Summary file groups`) passed default GitHub Actions CI in run [`27155205470`](https://github.com/hexafe/metroliza/actions/runs/27155205470) on 2026-06-08.
- Green automatic jobs for run `27155205470`: Static checks, Unit tests with combined coverage artifact upload, Native wheel build and smoke checks, CMM parser perf guardrail, and the non-blocking Performance benchmark trend check.
- Skipped manual/opt-in jobs in run `27155205470`: Packaging smoke, Windows startup benchmark, and Google conversion smoke. These skipped lanes do not satisfy release-promotion evidence.
- Commit `9a9310604604077b26fc5b2a4523459a4e14c5de` (`Finalize RC5 parser and UX release`) passed default GitHub Actions CI in run [`27327220468`](https://github.com/hexafe/metroliza/actions/runs/27327220468) on 2026-06-11.
- Green automatic jobs for run `27327220468`: Static checks, Unit tests with combined coverage artifact upload, Native wheel build and smoke checks, CMM parser perf guardrail, and the non-blocking Performance benchmark trend check.
- Skipped manual/opt-in jobs in run `27327220468`: Packaging smoke, Windows startup benchmark, and Google conversion smoke. These skipped lanes do not satisfy release-promotion evidence.
- Manual packaging smoke, Windows executable clean-machine launch/startup evidence, Google conversion smoke, third-party notice artifact evidence, and any open must-fix triage item remain release-promotion blockers unless the release owner records an explicit waiver.

## Feature freeze policy

- Feature freeze means no new release scope, broad refactors, or behavior-expanding changes enter the RC line after freeze.
- A late-scope exception must be recorded in [`implementation_item_triage.md`](./implementation_item_triage.md) with rationale, owner, target RC, test evidence, rollback or deferral option, and explicit release-owner approval before it merges.
- Late-scope exceptions do not waive manual release evidence gates.

## Operating notes

- Gate semantics quick reference:
  - **PR-blocking CI gates** are defined in [`../ci-policy.md`](../ci-policy.md) and must be green for merge readiness.
  - **Release-blocking manual evidence gates** are defined in [`release_candidate_checklist.md`](./release_candidate_checklist.md) and must be complete for RC Go decisions.
  - Optional/manual workflow-dispatch lanes (`packaging-smoke`, `google-conversion-smoke`) are non-blocking for normal PR CI but may be linked as release confidence evidence when executed.
- Active release operations are governed by documents under `docs/release_checks/`.
- Current QA counts, exact commit SHAs, and artifact identifiers should be recorded in the linked evidence docs and CI runs when status changes; counts from older revisions of this file are historical only.
- Latest QA evidence belongs in the linked CI runs, smoke logs, and checklist entries for the build under review; do not carry branch-local test counts in this status hub.
- Active export-path follow-up docs: [`../roadmaps/exporter_audit_2026_03.md`](../roadmaps/exporter_audit_2026_03.md) for remaining structural backlog, plus [`../roadmaps/2026_03_rc2_stabilization_execution.md`](../roadmaps/2026_03_rc2_stabilization_execution.md) as the RC2 closeout/reference tracker.
- During the current RC stabilization window, only small behavior-preserving, test-backed slices should move forward; larger decomposition/architecture moves remain deferred per triage.
- Superseded planning docs are archived references only and should not be used as operational status trackers.
- If status changes, update this page first, then update linked runbooks/checklists as needed.

## Historical context (archive)

- [`../archive/2026/IMPLEMENTATION_PLAN.md`](../archive/2026/IMPLEMENTATION_PLAN.md)
- [`../archive/2026/TODO.md`](../archive/2026/TODO.md) *(optional historical reference; non-operational)*
- [`../archive/2026/GOOGLE_SHEETS_MIGRATION_PLAN.md`](../archive/2026/GOOGLE_SHEETS_MIGRATION_PLAN.md)
