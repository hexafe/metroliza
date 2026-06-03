# RC Implementation-Item Triage

Use this page as the **active operational record** for implementation-item gate triage during release-candidate preparation.

> Historical reference only: archived implementation context remains in [`../archive/2026/TODO.md`](../archive/2026/TODO.md), but that file is **non-operational** and must not be used as a required RC gate.

## How to use this table

- Add one row per open implementation item relevant to the current RC window.
- Fill all required columns before freeze proceeds.
- Keep this table current as triage outcomes change.
- Link each row to the current evidence source: checklist item, CI run, smoke log, issue, or PR.
- Remove rows after the release decision is recorded or move them to archive if the build is superseded.
- After feature freeze, record every late-scope exception here before merge, including rationale, owner, target RC, test evidence, rollback/deferral option, and explicit release-owner approval.

## Triage Categories

- **Must fix:** blocks the current RC until resolved or explicitly waived by the release owner.
- **Defer:** not required for this RC; track in the relevant roadmap, issue, or follow-up PR.
- **Informational:** useful evidence or cleanup that does not affect the current release decision.
- **Late-scope exception:** post-freeze scope that can enter the RC only with release-owner approval and linked validation evidence.

## Active Build Identity

Record the branch, commit SHA, artifact/build ID, and evidence links in the current release checklist and smoke logs. Avoid hard-coding superseded build identities here.

## Open-Item Triage Table

| Implementation item | Gate decision (`must-fix`/`defer`/`informational`/`late-scope exception`) | Owner | Target RC | Evidence / rationale |
| --- | --- | --- | --- | --- |
| Final RC4 commit and fresh CI baseline | `informational` | Release owner | 2026.05 RC4 | `codex/directory-reorg-plan` has local audit evidence, including the static POPULATION layer dashboard slice and the raised 80% combined coverage gate. Previous validation SHA `05b5049558509060df43778d7b39424726e56ff1` passed default GitHub Actions CI in run [`26875151720`](https://github.com/hexafe/metroliza/actions/runs/26875151720): Static checks, Unit tests with combined coverage artifact upload, Native wheel build and smoke checks, CMM parser perf guardrail, and the non-blocking Performance benchmark trend check were green. Manual/opt-in Packaging smoke, Windows startup benchmark, and Google conversion smoke were skipped and remain separate release-promotion evidence gates. The final docs/freeze merge commit still needs pushed-SHA CI evidence after merge to `rc2`. |
| Feature freeze / late-scope exception register | `informational` | Release owner | 2026.05 RC4 | Feature freeze remains in effect. No late-scope exception is approved by default; any post-freeze scope must be recorded in this table with rationale, owner, target RC, test evidence, rollback/deferral option, and explicit release-owner approval before merge. |
| Packaging smoke evidence for current RC4 promotion artifact | `must-fix` | Release engineer / QA | 2026.05 RC4 | Run the opt-in packaging smoke workflow or equivalent local build/launch smoke and link the artifact/logs before promotion. |
| Windows EXE clean-machine launch evidence | `must-fix` | Release engineer / QA | 2026.05 RC4 | Linux local validation cannot prove the Windows user artifact; build the Windows EXE and smoke-launch it in a clean/sandbox Windows environment. |
| Google conversion smoke evidence for current RC4 promotion artifact | `must-fix` | QA owner / Release manager | 2026.05 RC4 | [`google_conversion_smoke.md`](./google_conversion_smoke.md) has no RC4 live smoke result yet; green default CI does not satisfy this release gate. |
| Third-party notice artifact evidence for current RC4 promotion artifact | `must-fix` | Release manager / QA | 2026.05 RC4 | Attach or link the bundled notice/license artifact evidence for the promoted build, including RapidOCR, ONNX Runtime, OpenCV, NumPy, Excel reader packages, hexafe-plotstats, and Oznak. |
| Bandit medium SQL-construction baseline triage | `must-fix` | Dev / Security reviewer | 2026.05 RC4 | `scripts/security_audit.py --ci` currently treats medium Bandit findings as report-only warnings; review B608 SQL-construction findings and record a fix/waiver before Go. |
