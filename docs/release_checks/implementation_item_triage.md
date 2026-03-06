# RC implementation-item triage table

Use this page as the **active operational record** for implementation-item gate triage during release-candidate preparation.

> Historical reference only: archived implementation context remains in [`../archive/2026/TODO.md`](../archive/2026/TODO.md), but that file is **non-operational** and must not be used as a required RC gate.

## How to use this table

- Add one row per open implementation item relevant to the current RC window.
- Fill all required columns before freeze proceeds.
- Keep this table current as triage outcomes change.

## Active build identity in scope

- Branch: `work`
- Commit SHA: `84a2302475b3559f319eb225b554a7f3bfbbc214`
- Artifact/build ID: `2026.03-build260305-84a2302`

## Open-item RC triage decision table

| Implementation item | Gate decision (`must-fix`/`defer`) | Owner | Target RC | Rationale |
| --- | --- | --- | --- | --- |
| Google conversion smoke rerun with valid sandbox OAuth credentials (`credentials.json` + `token.json`) for build `2026.03-build260305-84a2302`. | `must-fix` | QA owner + Release manager | 2026.03-rc1 | Current smoke evidence for build `260305` is a FAIL at smoke credential preflight (`SmokeConfigError` missing `credentials.json`); release promotion is blocked until a PASS run is captured for this build identity or a superseding build identity. |
| Export-flow architecture cleanup pass (behavior-parity refactor decomposition). | `defer` | App architecture owner | 2026.04-rc1 | Risk-reduction refactor scope; not required to prove release integrity for the active RC gate. |
| Split `modules/ExportDataThread.py` into orchestration, payload-building, and post-processing modules with parity tests. | `defer` | Export pipeline maintainer | 2026.04-rc1 | Depends on architecture-cleanup sequencing and dedicated parity test scaffolding; not release-blocking for current build identity. |
| Refactor `modules/CSVSummaryDialog.py` + `modules/ExportDialog.py` to isolate UI state from validation/request-building logic. | `defer` | UI/workflow maintainer | 2026.04-rc2 | Downstream of ExportDataThread decomposition; should not be mixed into the current RC stabilization window. |
| Add non-blocking CI module size/complexity visibility report for large files. | `defer` | Dev productivity owner | 2026.04-rc2 | Tooling enhancement for observability; informational and non-blocking by policy, so safe to schedule post-release. |
