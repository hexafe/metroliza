# Release status — 2026.09 RC1 source candidate

- Status: Active release status hub
- Owner: Release maintainer
- Last reviewed: 2026-10-30

The Product Owner selected `release/2026.09-rc1` as the current RC source line under
[#1153](https://github.com/hexafe/metroliza/issues/1153). Cut it from accepted `develop` after
the ordered #1109, #1142, STEP2+STEP3 and #1063 integrations. The live execution ledger records
the actual merge commits, final branch cut and cleanup receipts. This source-line decision does
not distribute or publish a packaged candidate.

## Current decisions

| Item | State | Evidence / next gate |
|---|---|---|
| Integration order | #1109, #1142, one STEP2+STEP3 aggregate, #1063; merge commits | #1153, current-base checks and independent reviews per merge |
| Current RC source line | `release/2026.09-rc1` | Cut from accepted final develop; exact SHA/tree in #1153 |
| STEP3 delivery | Complete with disclosed limits | [Immutable report](https://github.com/hexafe/metroliza/blob/f69ca5da31be5ef7efd5547457f14744dcb93baa/docs/engineering/performance-boost-step3.md) |
| Final build identity | Assigned `261031` to the next candidate (pinned Help docs ref, one user ZIP); `261029` stays bound to the historical bytes below | Synchronized source metadata under #1158; changed binaries never reuse 261029 |
| Accepted candidate source (historical, fixed) | `b2510e0aa651e8c96363e5a9c224c841318cc9d0`, tree `e165267b09b437b7fe5a1556b5809e87123f1c9a` | Head of `release/2026.09-rc1` when run [40991278786](https://github.com/hexafe/metroliza/actions/runs/40991278786) was dispatched. Later commits on `develop`, including this document, do not move or replace it |
| Combined Windows candidate acceptance (CI onedir) | **PASS**: diagnostics, core at DPR 1.0/1.25/1.5, forced native-unavailable, fresh reopen; one package | Job 123854028888, `combined-candidate-receipt.json`. Accepted `qualified-windows-development-package.zip` SHA-256 `da8a25eb2d0a4e79c80823bc03f470bc81fde3fe0a83d7037437ac61e495b84c`, 538738623 B, package tree `cb9b18c1…`; Actions artifact 12949329678. Not clean-machine, desktop Excel, real-report or release acceptance |
| Tester launcher EXE | Separate build from the same source; **not** the Combined bytes; unsigned | `metroliza_2026.09rc1_261029_launcher.exe` SHA-256 `16f3edb988bc9d0e5000c89796f40daf0bd2ebfef468c6e34827a3947512b408`, 334830360 B; Actions artifact 12949892358 (job 123854029137). Launcher smoke **PASS** on these bytes: cold, verified and warm cache, hard exit, preview |
| Portable envelope EXE | Smoke **PASS** (same job) | `metroliza_2026.09rc1_261029.exe` SHA-256 `1c87cc32…`; not the tester file and not archived |
| Frozen compute workers | Equal to serial outputs | Receipt 12949499262, measured on the onefile job's own supervised onedir, neither on the Combined package nor on the EXE |
| Native launcher qualification | **PASS**, synthetic payload | Job 123854029037: component test with a synthetic test entry, not a run of the tester EXE |
| Manual EXE acceptance | **NOT_RUN** | Native dialogs and mouse focus, desktop Excel lock, clean machine with antivirus, representative real reports, Help/manual, notices/legal, #1143 disposition and Google smoke, all on the exact tester EXE (#1158) |
| Durable archive | Original Actions archives, EXE, receipts, job logs | Tag `archive/2026.09-rc1/build-261029`, unpublished draft release; see [archive record](../archive/2026/build-261029-provenance/README.md). Actions retention ends 2027-01-28 |
| Core-flow Qt retain at exit | Open follow-up, not a gate for the Combined PASS | [#1184](https://github.com/hexafe/metroliza/issues/1184) |
| Promotion to master / published release | **Not authorized by #1153** | Full RC checklist and release-owner Go required |
| Historical RC lines | Retained, cycle closure pending | `rc2` and `release/2026.06-rc2`, separate #901/#924 decisions |
| Dependency upgrades #972/#973 | Deferred until after RC | Refresh separately, preserve STEP3 exact dependency pins |
| Security exception review #906 | Open | Selected STEP3 baseline earliest expiry 2026-11-23; verify the actual baseline before every gate and renew before expiry. The issue's original 2026-10-31 deadline is historical, not a new waiver |

The final RC1 candidate's source metadata is assigned `2026.09 RC1 (build 261029)` under
#1158, replacing the inherited build 261020 label while keeping the same RC1 release line.
The Combined PASS above accepts the CI onedir bytes only. The tester launcher EXE is a
separate build of the same source with its own smoke evidence; its manual acceptance and
every release-owner criterion remain open in #1158. The copy of this file on
`release/2026.09-rc1` is intentionally not synchronized, so the RC head stays at the
accepted source. Historical test
build 261021 is separately archived under
`archive/repo-cleanup-2026-10-27/build/step2-rc1-261021`; do not merge that old build-number
commit into the final RC. The unpublished archive container preserves original binaries,
sidecar provenance, the actual embedded `build_provenance.json` and exact hashes. No standalone
`BUILD_INFO.txt` exists in that launcher payload. Archival retention is not candidate qualification.

## Qualification required before RC distribution or release

**PR-blocking CI gates** are defined in [`../ci-policy.md`](../ci-policy.md).
**Release-blocking manual evidence gates** are defined in [`release_candidate_checklist.md`](./release_candidate_checklist.md).
Google conversion smoke is intentionally local-only and remains release-blocking for promotion.

Release line metadata is canonical in `src/metroliza/app/version.py`:
`RELEASE_VERSION` defines the release line, `VERSION_DATE` its six-digit build identity,
and `CURRENT_RELEASE_HIGHLIGHT` the synchronized release summary. Run
`python scripts/sync_release_metadata.py --check` before recording candidate evidence.

Follow the [timeless checklist](release_candidate_checklist.md) and
[Windows candidate protocol](windows_candidate_acceptance.md). Bind evidence to final source
commit/tree, synchronized build identity, resolved dependency/toolchain inventory, BUILD_INFO,
the actual archive and EXE hashes, and the exact tested artifact. Include clean-machine/AV,
launcher startup/fallback/repair/second instance, worker pools, parser/OCR, SQLite, dashboard,
XLSX and candidate acceptance. Record applicable Google/live-service, notices/legal,
rollback and release-owner decisions. Ordinary Windows core PASS is source evidence.

STEP3 measurements retain their actual cohorts 93641f82/75ea71c5/18d67f59, separate indices 14/18/23,
large-export n=1, and separately completed Group Analysis postcheck. They are not reruns on a
final packaged EXE. T26 remains WITHHELD. No new Linux campaign is implied by this source-line cut.

Historical C07, Windows publication and Industrial post-test139 remain separate UNKNOWN incidents.
The passing ordinary CI does not establish their cause or repair. #1110, #1143, #1144 and #1147
retain their actual follow-up criteria; #1153 does not close them by changing branches.

Operational evidence remains in the [Google smoke log](google_conversion_smoke.md),
[late-scope triage](implementation_item_triage.md) and [testing runbook](open_testing_runbook.md).
Stable promotion and a stable tag remain No-Go without the applicable manual gates and release-owner Go.

## Historical June RC2 evidence

The [2026-08-22 transition decision](rc2_branch_transition_decision_2026-08-22.md) remains valid
historical evidence. Original release-status content is preserved at
[the STEP3 snapshot](https://github.com/hexafe/metroliza/blob/f69ca5da31be5ef7efd5547457f14744dcb93baa/docs/release_checks/release_status.md).
It does not designate June RC2 as the current candidate after this decision. Both historical
refs remain unchanged. No abandonment, promotion, tag movement or cycle closeout is implied.
