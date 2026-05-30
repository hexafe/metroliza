# RC Implementation-Item Triage

Use this page as the **active operational record** for implementation-item gate triage during release-candidate preparation.

> Historical reference only: archived implementation context remains in [`../archive/2026/TODO.md`](../archive/2026/TODO.md), but that file is **non-operational** and must not be used as a required RC gate.

## How to use this table

- Add one row per open implementation item relevant to the current RC window.
- Fill all required columns before freeze proceeds.
- Keep this table current as triage outcomes change.
- Link each row to the current evidence source: checklist item, CI run, smoke log, issue, or PR.
- Remove rows after the release decision is recorded or move them to archive if the build is superseded.

## Triage Categories

- **Must fix:** blocks the current RC until resolved or explicitly waived by the release owner.
- **Defer:** not required for this RC; track in the relevant roadmap, issue, or follow-up PR.
- **Informational:** useful evidence or cleanup that does not affect the current release decision.

## Active Build Identity

Record the branch, commit SHA, artifact/build ID, and evidence links in the current release checklist and smoke logs. Avoid hard-coding superseded build identities here.

## Open-Item Triage Table

| Implementation item | Gate decision (`must-fix`/`defer`/`informational`) | Owner | Target RC | Evidence / rationale |
| --- | --- | --- | --- | --- |
| Final RC4 commit and fresh CI baseline | `informational` | Release owner | 2026.05 RC4 | `codex/directory-reorg-plan` has local audit evidence; record the final commit SHA and fresh GitHub Actions run after publish before merge/tag. |
| Packaging smoke evidence for current RC4 promotion artifact | `must-fix` | Release engineer / QA | 2026.05 RC4 | Run the opt-in packaging smoke workflow or equivalent local build/launch smoke and link the artifact/logs before promotion. |
| Windows EXE clean-machine launch evidence | `must-fix` | Release engineer / QA | 2026.05 RC4 | Linux local validation cannot prove the Windows user artifact; build the Windows EXE and smoke-launch it in a clean/sandbox Windows environment. |
| Google conversion smoke evidence for current RC4 promotion artifact | `must-fix` | QA owner / Release manager | 2026.05 RC4 | [`google_conversion_smoke.md`](./google_conversion_smoke.md) has no RC4 live smoke result yet; green default CI does not satisfy this release gate. |
| Bandit medium SQL-construction baseline triage | `must-fix` | Dev / Security reviewer | 2026.05 RC4 | `scripts/security_audit.py --ci` currently treats medium Bandit findings as report-only warnings; review B608 SQL-construction findings and record a fix/waiver before Go. |
