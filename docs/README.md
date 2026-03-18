# Documentation Index

This directory contains active operational and maintenance documentation.

## Active docs

- Group Comparison worksheet interpretation and statistical caveats: see root `README.md` section "Group Comparison export sheet".
- `documentation_policy.md` — policy for permanent vs temporary docs, archival, and ownership.
- `google_conversion_smoke_runbook.md` — local Google Sheets conversion smoke guidance.
- `native_build_distribution.md` — native build/distribution workflow and packaging references.
- Grouping dialog color policy uses shared semantic tokens from `modules/ui_theme_tokens.py` (base row background, selected-row colors, default group color, and generated group palette) so dialogs stay visually consistent across light/dark themes.
- `roadmaps/2026_03_rc2_stabilization_execution.md` — **primary active execution tracker** for current RC2 refactor/stabilization sequencing.
- `roadmaps/exporter_audit_2026_03.md` — focused exporter-path audit with remaining refactor recommendations and priority backlog.
- `feature/group-analysis/README.md` — **active implementation-cycle workspace** for Group Analysis; start here for current planning/execution docs (`implementation_plan.md`, `todo.md`, `checklist.md`).

## Historical and superseded planning context

- `roadmaps/2026_03_rc1_test_ci_execution_tracker.md` — superseded RC1 execution context (reference-only; no longer the active operational tracker).
- `roadmaps/test_ci_audit_execution.md` — superseded by the RC1 tracker above and retained only for historical planning context.

## Module boundary notes (export/grouping dialogs)

- `modules/export_data_thread.py` is the orchestration entry point. Pure computations are kept in helper modules:
  - `modules/export_chart_payload_helpers.py` for chart payload/table shaping.
  - `modules/export_workbook_planning_helpers.py` for workbook/table layout sizing heuristics.
  - `modules/export_row_aggregation_utils.py` for row/group aggregation computations.
- `modules/csv_summary_dialog.py` keeps dialog/UI concerns and delegates worker-side export logic to `modules/csv_summary_worker.py`.
- `modules/data_grouping.py` keeps widget/event orchestration and delegates data/query mutations to `modules/data_grouping_service.py`.

### Active release-check docs (`docs/release_checks/`)

Canonical release operations docs (release gate/source-of-truth set):

- `release_checks/release_status.md` — current release operational status and entry-point links.
- `release_checks/release_candidate_checklist.md` — primary RC gate checklist and required sign-offs.
- `release_checks/open_testing_runbook.md` — open-testing execution runbook and evidence expectations.
- `release_checks/branching_strategy.md` — authoritative branch naming/rules used during release work.
- `release_checks/google_conversion_smoke.md` — required release smoke evidence log for Google conversion checks.

Supplemental tutorial/playbook docs (how-to guidance that supports, but does not override, canonical docs):

- `release_checks/release_branching_playbook.md` — practical branch workflow examples.
- `release_checks/release_playbook_beginner.md` — beginner-friendly end-to-end RC walkthrough.

## Archive

Retired planning/temporary docs are under `archive/`.

- Archive entry point: `archive/README.md`
- Year buckets: `archive/YYYY/`
