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
- `user_manual/industrial_data.md` — end-user guide to the Industrial Data/Oznak cache-first workflow.
- `user_manual/realtime_industrial_monitoring.md` — operator guide to realtime industrial monitoring concepts, setup, event review, and false-positive handling.
- `user_manual/dashboard_visuals.md` — end-user guide to dashboard visual recipes and customization.
- `user_manual/parser_profiles.md` — end-user guide to Parser Profiles and LLM handoff folders.
- `user_manual/characteristic_name_matching.md` — end-user guide to Characteristic Name Matching.
- `user_manual/help_startup_and_license.md` — short support/reference page for startup, license, About, and Release notes.
- `user_manual/group_analysis/README.md` — index for the exported Group Analysis worksheet manual.
- `user_manual/group_analysis/user_manual.md` — plain-English end-user guide for interpreting the exported Group Analysis worksheet.
- `user_manual/group_analysis/user_manual.pdf` — optional printable companion version.
- `documentation_policy.md` — policy for permanent vs temporary docs, archival, and ownership.
- `realtime_industrial_validation.md` — deterministic fixture matrix for realtime industrial detector validation.
- `perf_realtime_detectors.md` — local throughput benchmark guide for deterministic realtime industrial detectors.
- `google_conversion_smoke_runbook.md` — local Google Sheets conversion smoke guidance.
- `native_build_distribution.md` — native build/distribution workflow and packaging references.
- `../THIRD_PARTY_NOTICES.md` — third-party license and notice inventory for packaged distributions.
- `parser_plugins/README.md` — active hub for declarative parser profiles, self-contained LLM handoff packages, package integrity checks, repair prompts, validation, installation, and rollout docs.
- `parser_plugins/parser_plugin_specification.md` — exact contract for declarative Metroliza parser profiles, generated handoff packages, V2 parser output, runtime discovery, and advanced generated parser plugins.
- `parser_plugins/non_technical_workflow.md` — non-technical step-by-step workflow for adding a new supplier report parser.
- `roadmaps/2026_03_rc2_stabilization_execution.md` — RC2 stabilization closeout/reference tracker for the completed parity-first slice.
- `roadmaps/OCR_BENCHMARKING_MASTER.md` — canonical OCR benchmarking, acceleration, privacy, and next-session handoff.
- `roadmaps/OZNAK_PRODUCTION_ANALYTICS_IMPLEMENTATION_PLAN.md` — active production-analytics roadmap using canonical `src/metroliza/*` implementation paths.
- `roadmaps/realtime_industrial_monitoring_plan.md` — active rollout plan for realtime industrial monitoring source safety, replay, operator workflow, and rollback.
- `roadmaps/PLOTSTATS_CENTRALIZATION_IMPLEMENTATION_PLAN.md` — future implementation plan for moving reusable Metroliza plot definitions into `hexafe-plotstats`.
- `roadmaps/static_population_layer_dashboard_plan.md` — completed implementation record for static large-group layer optimization in large HTML dashboards.
- `roadmaps/directory_reorganization_long_term.md` — completed directory reorganization record for the canonical `src/metroliza/` layout, legacy shims, packaging guardrails, and validation evidence.
- `roadmaps/post_reorganization_next_implementation_plan.md` — active next implementation plan after the completed directory reorganization.
- `roadmaps/full_module_audit_2026_06.md` — active full-module audit matrix, implemented fixes, and deferred follow-up backlog.
- `roadmaps/exporter_audit_2026_03.md` — focused exporter-path follow-up audit with the remaining structural refactor backlog.
- `roadmaps/rust_acceleration_scope.md` — native-acceleration scope and promotion-gate decision record.

## Roadmap inventory

Use this inventory before assigning work from `docs/roadmaps/`. Active entries
can drive new implementation. Completed records and historical handoffs preserve
pre-reorganization context and must be refreshed against canonical
`src/metroliza/*` paths before being used as write scopes.

| Roadmap | Status | Notes |
|---|---|---|
| `roadmaps/post_reorganization_next_implementation_plan.md` | Active | Current post-reorganization implementation plan and workstream hub. |
| `roadmaps/full_module_audit_2026_06.md` | Active | Full-module audit matrix for parser/report persistence, export/charting, CSV Summary, UI/UX, CI, packaging, and release gates. |
| `roadmaps/OZNAK_PRODUCTION_ANALYTICS_IMPLEMENTATION_PLAN.md` | Active | Production and tabular analytics roadmap; paths are canonicalized to `src/metroliza/*`. |
| `roadmaps/realtime_industrial_monitoring_plan.md` | Active | Realtime industrial monitoring rollout plan for source safety, replay, operator workflow, and rollback. |
| `roadmaps/OCR_BENCHMARKING_MASTER.md` | Active | OCR benchmarking and acceleration handoff; new work follows the post-reorganization path policy. |
| `roadmaps/static_population_layer_dashboard_plan.md` | Completed record | Static large-group layer optimization closeout for large CSV Summary dashboards and shared dashboard renderer parity. |
| `roadmaps/PLOTSTATS_CENTRALIZATION_IMPLEMENTATION_PLAN.md` | Future active | Plotstats boundary migration plan. |
| `roadmaps/exporter_audit_2026_03.md` | Active follow-up | Exporter Phase-B structural backlog after RC2 seam closeout. |
| `roadmaps/rust_acceleration_scope.md` | Active decision record | Native-acceleration promotion gate and candidate-scope decision record. |
| `roadmaps/directory_reorganization_long_term.md` | Completed record | Directory reorganization closeout and compatibility-shim policy. |
| `roadmaps/2026_03_rc2_stabilization_execution.md` | Completed record | RC2 export-path stabilization closeout; `modules/*` references are historical. |
| `roadmaps/UI_UX_RELEASE_FIX_PLAN.md` | Completed record | May 2026 UI/UX release-fix closeout; pre-reorganization path references are historical. |
| `roadmaps/UI_UX_REVAMP_SUMMARY_PLAN.md` | Reference record | UI/UX revamp design principles and remaining polish guidance. |
| `roadmaps/TESTS_CLEANUP_PLAN.md` | Completed record | Test-cleanup closeout and future cleanup cautions. |
| `roadmaps/METROLIZA_AUDIT_NEXT_SESSION.md` | Historical handoff | April 2026 audit handoff; refresh before assigning new work. |
| `roadmaps/OCR_TEST_CLEANUP_NEXT_SESSION_README.md` | Historical handoff | OCR/test-cleanup handoff after the 2026-04-28 pass. |
| `roadmaps/OZNAK_METROLIZA_INTEGRATION_AUDIT_PLAN.md` | Historical implementation record | Oznak integration branch record; new industrial work should use the active production analytics plan. |

## Active end-user manual area

Use `docs/user_manual/` as the canonical home for active end-user guides.

The legacy `docs/group_analysis/user_manual.md` path is retained only as a redirect stub. The active Group Analysis worksheet manual now lives under `docs/user_manual/group_analysis/`, and historical design notes live under `docs/archive/2026/feature-group-analysis/`.

## Historical and superseded planning context

- `archive/2026/feature-group-analysis/` — historical Group Analysis implementation-cycle workspace archived after feature completion.
- `archive/2026/feature-group-comparison-xlsx/` — historical pre-consolidation Group Comparison XLSX planning workspace.
- `archive/2026/feature-groupstats-integration/` — historical standalone `hexafe-groupstats` extraction/integration notes after package adoption.
- `archive/2026/feature-nuitka-parser-audit/` — archived packaged-parser audit workspace after packaging/CI hardening landed.
- `archive/2026/feature-parser-plugin-factory/` — archived intermediate quickstart/status docs superseded by the active parser plugin documentation set.
- `archive/2026/feature-report-metadata-redesign/` — archived report metadata redesign audit/handoff after implementation landed.
- `archive/2026/test-ci-audit/` — archived RC1 test/CI audit and execution trackers.
- `archive/2026/module_naming_migration.md` — archived module naming migration closeout; active naming rules live in `CONTRIBUTING.md`.
- `archive/2026/native_plot_matplotlib_parity_2026_03.md` — archived native chart parity audit/execution plan after rollout-ready closeout.
- `archive/2026/parser_audit_2026_03.md` — archived parser performance/plugin audit after implementation closeout.
- `archive/2026/performance_boost_audit_2026_03.md` — archived performance audit/implementation plan after the measured fixes landed.

## Module boundary notes (export/grouping dialogs)

- `src/metroliza/exporting/export_data_thread.py` is the orchestration entry point. Pure computations are kept in helper modules:
  - `src/metroliza/charts/export_chart_payload_helpers.py` for chart payload/table shaping.
  - `src/metroliza/exporting/export_workbook_planning_helpers.py` for workbook/table layout sizing heuristics.
  - `src/metroliza/exporting/export_row_aggregation_utils.py` for row/group aggregation computations.
- CSV/Excel Summary is routed through `src/metroliza/ui/industrial_analytics_dialog.py` and the shared tabular analytics workflow; large-dashboard chart interactivity and large-group layer thresholds are controlled by the CSV Summary dashboard interactivity contract in `src/metroliza/shared/contracts.py`.
- `src/metroliza/ui/data_grouping.py` keeps widget/event orchestration and delegates data/query mutations to `src/metroliza/tabular/data_grouping_service.py`.
- Grouping dialog colors use shared semantic tokens from `src/metroliza/ui/ui_theme_tokens.py` so dialogs stay visually consistent across light/dark themes.
- Group Analysis statistical computation is bridged through `src/metroliza/analytics/hexafe_groupstats_adapter.py`; workbook, dashboard, export orchestration, and UI remain Metroliza-owned.

### Active release-check docs (`docs/release_checks/`)

Canonical release operations docs (release gate/source-of-truth set):

- `release_checks/release_status.md` — current release operational status and entry-point links, including build `260623` CMM parser resolver hotfix evidence.
- `release_checks/release_candidate_checklist.md` — primary RC gate checklist and required sign-offs.
- `release_checks/open_testing_runbook.md` — open-testing execution runbook and evidence expectations.
- `release_checks/branching_strategy.md` — authoritative branch naming/rules used during release work.
- `release_checks/google_conversion_smoke.md` — required release smoke evidence log for Google conversion checks.
- `release_checks/cmm_parser_perf_guardrail.md` — CMM parser performance guardrail policy, variance expectations, and CI-failure triage steps.
- `release_checks/realtime_industrial_rollout_checklist.md` — current 2026.06 RC1 realtime industrial tester rollout gate for replay, bounded reads, source lag, threshold review, and rollback.
- `release_checks/realtime_monitor_ui_ux_audit_2026-06-15.md` — build `260615` realtime monitor UI/UX audit, implemented workflow guardrails, About cleanup, and deferred dashboard-mode follow-up.
- `release_checks/realtime_industrial_optimization_check_2026-06-16.md` — build `260616` Industrial Data fetch, realtime dashboard, and interactive dashboard point-marking release-check note.
- `release_checks/realtime_industrial_performance_check_2026-06-17.md` — build `260617` Industrial Data SQLite handoff, cached workbook export, realtime polling, and Oznak fallback release-check note.
- `release_checks/ui_overlap_layout_audit_2026-06-19.md` — build `260619` UI overlap/layout audit covering PyQt geometry, dashboard CSS containment, chart legend geometry, and workbook image slots.

Historical RC/rc2 evidence:

- `release_checks/rc2_release_audit_2026-05-17.md` — historical RC2 release audit evidence and blocker summary.
- `release_checks/rc2_performance_optimization_check_2026-05-20.md` — CSV Summary/grouping/dashboard performance optimization evidence and remaining bottlenecks.
- `release_checks/full_module_audit_2026-06-08.md` — build `260609` full-module audit hardening release-check evidence.
- `release_checks/rc5_dashboard_industrial_cache_check_2026-06-09.md` — build `260609` RC5 dashboard large-group, dashboard visuals, and Industrial Data cache release-check evidence.
- `release_checks/rc5_industrial_data_csv_summary_followup_2026-06-10.md` — build `260609` Industrial Data fetch-to-cache and CSV Summary follow-up evidence.
- `release_checks/realtime_industrial_rollout_checklist.md` — realtime industrial monitoring rollout gate for replay, bounded reads, source lag, threshold review, and rollback.
- `release_checks/rc5_parser_ux_release_closeout_2026-06-11.md` — build `260611` RC5 parser handoff, Industrial Data cache-first UX, coverage, and release-gate closeout evidence.
- `release_checks/rc5_rc_audit_evidence_2026-06-12.md` — build `260612` June 12 RC audit implementation evidence, local validation results, pushed-CI follow-up, and remaining manual release blockers.

Supplemental tutorial/playbook docs (how-to guidance that supports, but does not override, canonical docs):

- `release_checks/release_branching_playbook.md` — practical branch workflow examples.
- `release_checks/release_playbook_beginner.md` — beginner-friendly end-to-end RC walkthrough.

## Archive

Retired planning/temporary docs are under `archive/`.

- Archive entry point: `archive/README.md`
- Year buckets: `archive/YYYY/`
