# RC implementation-item triage table

Use this page as the **active operational record** for implementation-item gate triage during release-candidate preparation.

> Historical reference only: archived implementation context remains in [`../archive/2026/TODO.md`](../archive/2026/TODO.md), but that file is **non-operational** and must not be used as a required RC gate.

## How to use this table

- Add one row per open implementation item relevant to the current RC window.
- Fill all required columns before freeze proceeds.
- Keep this table current as triage outcomes change.
- For RC2 stabilization triage, classify each item as either:
  - **RC2-safe stabilization slice**: small, behavior-preserving, and test-backed work that reduces structural risk without changing UX/output semantics.
  - **Deferred architecture move**: larger decomposition, architecture/platform rollout, or broad UX/schema changes that carry elevated release risk.
- Use the execution tracker in [`../roadmaps/2026_03_rc2_stabilization_execution.md`](../roadmaps/2026_03_rc2_stabilization_execution.md) as the source for sequencing and per-item status.

## RC2 track rationale and guardrails

The 2026.03-rc2 track is for **structural risk reduction with behavior parity**, not a rewrite. This means we intentionally accept only narrow, test-backed extractions in this window and explicitly defer higher-risk architecture swings.

The following item classes are explicitly **disallowed in RC2** and remain deferred:

- Full plugin runtime rollout.
- Parser registry/factory rollout.
- LLM-assisted parser generation.
- Broad schema/export/UX redesign.
- Big-bang module or API renames.

## Active build identity in scope

- Branch: `work`
- Commit SHA: `84a2302475b3559f319eb225b554a7f3bfbbc214`
- Artifact/build ID: `2026.03-build260305-84a2302`

## Open-item RC triage decision table

| Implementation item | Gate decision (`must-fix`/`defer`) | Owner | Target RC | Rationale |
| --- | --- | --- | --- | --- |
| Google conversion smoke rerun with valid sandbox OAuth credentials (`credentials.json` + `token.json`) for build `2026.03-build260305-84a2302`. | `must-fix` | QA owner + Release manager | 2026.03-rc1 | Current smoke evidence for build `260305` is a FAIL at smoke credential preflight (`SmokeConfigError` missing `credentials.json`); release promotion is blocked until a PASS run is captured for this build identity or a superseding build identity. |
| Export context helper extraction from `ExportDataThread` into pure helper/service seam with parity tests (EX-001 class). | `must-fix` | Export pipeline maintainer | 2026.03-rc2 | **RC2-safe stabilization slice**: small, behavior-preserving, and test-backed extraction explicitly aligned to the RC2 execution tracker. |
| Export dependency shaping around extracted seam with focused tests only (EX-002/EX-003 class). | `must-fix` | Export pipeline maintainer + UI/workflow maintainer | 2026.03-rc2 | **RC2-safe stabilization slice** when limited to narrow seams and parity-backed checks; do not include user-visible behavior changes. |
| Export-flow architecture cleanup pass (broad behavior-parity decomposition). | `defer` | App architecture owner | 2026.04-rc1 | **Deferred architecture move**: larger decomposition exceeds RC2-safe slice boundaries; keep for post-rc2 sequencing in execution tracker. |
| Split `modules/export_data_thread.py` into orchestration, payload-building, and post-processing modules as a full decomposition. | `defer` | Export pipeline maintainer | 2026.04-rc1 | **Deferred architecture move**: broad module split has integration-risk blast radius beyond rc2 stabilization scope. |
| Refactor `modules/csv_summary_dialog.py` + `modules/export_dialog.py` into full UI-state/validation architecture layers. | `defer` | UI/workflow maintainer | 2026.04-rc2 | **Deferred architecture move**: larger boundary reshaping should follow rc2 parity stabilization completion. |
| Add non-blocking CI module size/complexity visibility report for large files. | `defer` | Dev productivity owner | 2026.04-rc2 | Tooling enhancement for observability; informational and non-blocking by policy, so safe to schedule post-release. |
| Full plugin runtime rollout for export path extensibility. | `defer` | Platform architecture owner | 2026.04+ | Explicitly disallowed for RC2; deferred larger platform move tracked in execution roadmap phases C+. |
| Parser registry/factory rollout across export/parser flows. | `defer` | Platform architecture owner | 2026.04+ | Explicitly disallowed for RC2; sequencing requires post-stabilization architecture runway. |
| LLM-assisted parser generation integration. | `defer` | Platform architecture owner | 2026.04+ | Explicitly disallowed for RC2; requires separate safety, fallback, and governance validation. |
| Broad schema/export/UX redesign package. | `defer` | Product + architecture owners | 2026.04+ | Explicitly disallowed for RC2; rewrite-scale UX/schema shifts conflict with parity-first stabilization mandate. |
| Big-bang renames (module/API naming migration done in one sweep). | `defer` | Architecture owner | 2026.04+ | Explicitly disallowed for RC2; staged rename migration only after stabilization to reduce release risk. |
