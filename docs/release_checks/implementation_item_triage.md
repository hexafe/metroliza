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
| Earlier rc2 hardening commits and fresh CI baselines | `informational` | Release owner | 2026.05 RC5 | `rc2` has local and pushed CI evidence for startup/dashboard telemetry hardening, selected-style reset, analytics/export/grouping hardening, histogram overlay parity, PyInstaller onefile bootloader splash support, summary-sheet planning extraction, CSV Summary file-name auto-grouping, dashboard visual cleanup, and Industrial Data cache-to-CSV Summary follow-ups. Manual/opt-in Packaging smoke, Windows startup benchmark, and Google conversion smoke were skipped on default CI and remain separate release-promotion evidence gates. |
| CSV Summary multi-file file-name auto-grouping | `late-scope exception` | Release owner / Dev | 2026.05 RC5 | User-requested rc2 release work for build `260608`: when more than one CSV input is selected, CSV Summary prompts to create one custom group per source file stem, assigns each loaded row to its file group, and does not create a `POPULATION` group. The export path now relies on the existing in-window dashboard optimization dialog and no longer shows a second export-time optimization prompt. Local validation passed on 2026-06-08: `git diff --check`, `ruff`, `compileall`, release metadata sync, release hygiene, packaged PDF parser validation, security audit with no known vulnerabilities, focused CSV Summary tests (`81 passed`), focused workflow/dashboard/release tests (`71 passed`), full headless pytest with coverage tracking (`1878 passed`, `263 skipped`, `95 warnings`, `71 subtests passed`), and CI-shaped combined coverage at `81%` against the `80%` threshold. Pushed rc2 CI passed in run [`27155205470`](https://github.com/hexafe/metroliza/actions/runs/27155205470) for commit `e0af5d8ec4075aa266a76610b4b6f608fffb2bd7`. Rollback option: revert the tabular grouping helper, CSV Summary dialog prompt/removal, tests, and release docs before promotion if a final-head CI rerun fails. |
| June 12 RC audit hardening | `late-scope exception` | Release owner / Dev | 2026.05 RC5 | User-requested RC audit/fix work for build `260612`: hardens Industrial raw SQL validation, streams fallback SQL fetch-all batches into the cache, prevents report-link schema materialization for industrial-only caches, aligns guided Oznak source objects with pinned simple-identifier compatibility, adds SQL recipe/fetch-all/raw-SQL regressions, and adds advisory benchmark probes. Local validation is recorded in [`rc5_rc_audit_evidence_2026-06-12.md`](./rc5_rc_audit_evidence_2026-06-12.md): focused slice `180 passed`, full offscreen suite `1942 passed, 283 skipped, 6 warnings, 83 subtests passed`, CI-shaped coverage `82%` against the `80%` threshold, release hygiene/metadata checks passed, and security audit passed with no known vulnerabilities. Pushed rc2 CI is pending until this commit is published. Rollback option: revert the Industrial SQL/cache hardening, benchmark probe additions, focused tests, build-date bump, and June 12 release evidence if final-head CI or open testing exposes a regression. |
| Feature freeze / late-scope exception register | `informational` | Release owner | 2026.05 RC5 | Feature freeze remains in effect. No late-scope exception is approved by default; any post-freeze scope must be recorded in this table with rationale, owner, target RC, test evidence, rollback/deferral option, and explicit release-owner approval before merge. |
| Packaging smoke evidence for current RC5 promotion artifact | `must-fix` | Release engineer / QA | 2026.05 RC5 | Run the opt-in packaging smoke workflow or equivalent local build/launch smoke and link the artifact/logs before promotion. |
| Windows EXE clean-machine launch evidence | `must-fix` | Release engineer / QA | 2026.05 RC5 | Linux local validation cannot prove the Windows user artifact; build the Windows EXE and smoke-launch it in a clean/sandbox Windows environment. |
| Google conversion smoke evidence for current RC5 promotion artifact | `must-fix` | QA owner / Release manager | 2026.05 RC5 | [`google_conversion_smoke.md`](./google_conversion_smoke.md) has no RC5 live smoke result yet; green default CI does not satisfy this release gate. |
| Third-party notice artifact evidence for current RC5 promotion artifact | `must-fix` | Release manager / QA | 2026.05 RC5 | Attach or link the bundled notice/license artifact evidence for the promoted build, including RapidOCR, ONNX Runtime, OpenCV, NumPy, Excel reader packages, hexafe-plotstats, and Oznak. |
| Bandit medium SQL-construction baseline triage | `must-fix` | Dev / Security reviewer | 2026.05 RC5 | Current security audits pass with no known vulnerabilities, but `scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects` still reports medium Bandit findings as report-only baseline warnings. Review and fix or record a security-owner waiver before Go. |
