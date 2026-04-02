# Documentation Index

This directory contains active operational, maintenance, and end-user documentation.

## Active docs

- `user_manual/README.md` — canonical hub for active end-user manuals.
- `user_manual/main_window.md` — end-user guide to the main launcher window and workflow order.
- `user_manual/parsing.md` — end-user guide to importing reports into a database file.
- `user_manual/modify_database.md` — end-user guide to editing stored REFERENCE / SAMPLE NUMBER / HEADER values.
- `user_manual/export_overview.md` — main end-user guide to the Export dialog.
- `user_manual/export_filtering.md` — focused end-user guide to Export filtering.
- `user_manual/export_grouping.md` — focused end-user guide to Export grouping.
- `user_manual/csv_summary.md` — end-user guide to the CSV Summary workflow.
- `user_manual/characteristic_name_matching.md` — end-user guide to Characteristic Name Matching.
- `user_manual/help_startup_and_license.md` — short support/reference page for startup, license, About, and Release notes.
- `user_manual/group_analysis/README.md` — index for the exported Group Analysis worksheet manual.
- `user_manual/group_analysis/user_manual.md` — plain-English end-user guide for interpreting the exported Group Analysis worksheet.
- `user_manual/group_analysis/user_manual.pdf` — optional printable companion version.
- `documentation_policy.md` — policy for permanent vs temporary docs, archival, and ownership.
- `google_conversion_smoke_runbook.md` — local Google Sheets conversion smoke guidance.
- `native_build_distribution.md` — native build/distribution workflow and packaging references.
- Grouping dialog color policy uses shared semantic tokens from `modules/ui_theme_tokens.py` (base row background, selected-row colors, default group color, and generated group palette) so dialogs stay visually consistent across light/dark themes.
- `roadmaps/2026_03_rc2_stabilization_execution.md` — **primary active execution tracker** for current RC2 refactor/stabilization sequencing.
- `roadmaps/exporter_audit_2026_03.md` — focused exporter-path audit with remaining refactor recommendations and priority backlog.
- `group_analysis/README.md` — historical index with links back to the active user-manual location and retained design notes.

## Active end-user manual area

Use `docs/user_manual/` as the canonical home for active end-user guides.

The `docs/group_analysis/` folder is retained for historical/design context. The active Group Analysis worksheet manual now lives under `docs/user_manual/group_analysis/`.

## Historical and superseded planning context

- `archive/2026/feature-group-analysis/` — historical Group Analysis implementation-cycle workspace archived after feature completion.
- `archive/2026/feature-group-comparison-xlsx/` — historical pre-consolidation Group Comparison XLSX planning workspace.
- `archive/2026/native_plot_matplotlib_parity_2026_03.md` — archived native chart parity audit/execution plan after rollout-ready closeout.
- `archive/2026/performance_boost_audit_2026_03.md` — archived performance audit/implementation plan after the measured fixes landed.
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
- `release_checks/cmm_parser_perf_guardrail.md` — CMM parser performance guardrail policy, variance expectations, and CI-failure triage steps.

Supplemental tutorial/playbook docs (how-to guidance that supports, but does not override, canonical docs):

- `release_checks/release_branching_playbook.md` — practical branch workflow examples.
- `release_checks/release_playbook_beginner.md` — beginner-friendly end-to-end RC walkthrough.

## Archive

Retired planning/temporary docs are under `archive/`.

- Archive entry point: `archive/README.md`
- Year buckets: `archive/YYYY/`
