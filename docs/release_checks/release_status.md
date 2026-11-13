# Metroliza release status

- Status: Active release status hub
- Owner: Release maintainer
- Last reviewed: 2026-11-13

Historical source-line selection: the Product Owner selected `release/2026.09-rc1` under
[#1153](https://github.com/hexafe/metroliza/issues/1153). It was cut from accepted `develop` after
the ordered #1109, #1142, STEP2+STEP3 and #1063 integrations. The live execution ledger records
the actual merge commits, final branch cut and cleanup receipts. This source-line decision does
not distribute or publish a packaged candidate.

The 2026-11-13 naming decision maps the current roles to `main` (production/history default),
`dev` (daily integration) and `rc` (active frozen candidate). Its native `rc2` to `rc` rename preserves
hosted-blob redirect compatibility, with the former `release/2026.09-rc1` reconciled through the
reviewed history-preserving migration. Branch names and governance/configuration do not qualify artifacts.
Original branch names, source SHA/tree, build identities and receipts below retain their historical
bindings; do not interpret a current ref tip as the frozen build's source.

## Current development build and exact delivery evidence

The PO adopted `0.8.0-dev.1` and the semantic channel/stable contract under
[#1228](https://github.com/hexafe/metroliza/issues/1228), parent #920; see the
[versioning policy](../project/versioning_policy.md). This is the next identity, not a claim that
a new package has passed CI, been built, delivered or accepted. Its exact source/run/artifact ledger
belongs to #1228; the #1220 / PR #1224 records below retain their completed historical bindings.
The accepted `0.8.0` scope and additional `1.0.0` targets do not relabel older RC artifacts.

The canonical release/build identity is defined in
[`src/metroliza/app/version.py`](../../src/metroliza/app/version.py). The delivered main HTML and
related save-path repair is tracked in [#1220](https://github.com/hexafe/metroliza/issues/1220),
[#1221](https://github.com/hexafe/metroliza/issues/1221) and
[PR #1224](https://github.com/hexafe/metroliza/pull/1224).

Use each version's coordinator-owned exact-source delivery/integration ledger (#1228 for the new
line; #1220 / PR #1224 for the historical export repair) for its source commit/tree, version,
required source/manual-workflow CI outcomes,
canonical Windows run/jobs, retained qualification artifacts, EXE/ZIP hashes and byte sizes,
local download/finalizer/delivery receipts, independent/GitHub review disposition and actual merge.
Read the recorded terminal verdict for each boundary; a version assignment, branch tip, one successful
job or previously delivered artifact is not a substitute for that exact candidate's complete ledger.
A later prose commit does not change the packaged source recorded by its receipt.

Current development work integrates through `dev`. The frozen `rc` baseline and production/history
`main` remain distinct; delivering a development test package does not promote either branch or
assign stable/release-owner approval. The immutable historical package checkpoints below document
what actually happened, including adverse runs; they do not silently follow later build metadata.

On 2026-11-13 the Product Owner explicitly deferred their private-data retest to the following week
and instructed implementation/integration and repository cleanup to finish meanwhile. That is an
explicit retest deferral, not private-data acceptance or a request to stop authorized engineering
work. Any subsequent user observation must retain its own exact artifact/data-scope binding in the
existing issue ledger. Physical/device/accessibility, private-report, clean-machine/AV, desktop Excel,
applicable live-service, notices/legal and release-owner criteria remain separate from automated proof.

## Historical development-package checkpoint — build 261118

This dated checkpoint retains both the actual delivery/qualification proof and the subsequently
observed adverse workflow result. It is not a globally green CI or release-acceptance claim.

| Item | Observed result | Exact binding / limit |
|---|---|---|
| 261118 source | `ddad2c78866eb36bc9058eeacf0f2ead43780e7e`, tree `98cc46a09fee16b95697eb504b6e05cb6bb3284f` | `2026.09rc1(261118)`. The final retention change at this checkpoint adds one exact `**/main-html.zip` upload rule, a meaningful four-run/decoy policy test and build metadata; exporter/diagnostic/qualification logic is unchanged from 261117 |
| 261118 independent retention-delta review | **PASS_SOURCE_DELTA** | [Exact-source report](https://github.com/hexafe/metroliza/pull/1224#issuecomment-6856800998); source-only verdict, with unchanged earlier product reviews retaining their own bindings |
| 261118 primary source CI | **PASS** | [Run 43449127438](https://github.com/hexafe/metroliza/actions/runs/43449127438) completed successfully on exact ddad source; native Windows job 131966455212 included 67 PASS / 0 SKIP in 30.56s |
| 261118 Combined and downloaded user ZIP jobs | **PASS** | [Run 43449763500](https://github.com/hexafe/metroliza/actions/runs/43449763500): Combined job 131968550806 and downloaded-user-ZIP verifier job 131979266861. One same-package diagnostics/core chain at DPR 1.0/1.25/1.5 and forced native-unavailable, with six actual main exports per run; qualified onedir retained through launcher packing, smoke and user ZIP |
| 261118 actual retained qualification evidence | **PASS** | Acceptance artifact 14051817233: 42929123 B, SHA-256 `45c43962290439eeb2e0f4dc77c15394d3d4a57027317d13eca9432a80dec15a`, 151 members including exactly four run-relative `main-html.zip` files. Unchanged strict local finalizer exited 0 in 6.6478s with exact native-receipt equality and original inputs unchanged |
| 261118 local ZIP/EXE identity and handoff | **PASS for the delivered development-test bytes** | Local downloaded ZIP/EXE identity and strict finalizer matched the CI receipts; the package was handed to the user on 2026-11-13 (coordinator's 15:36 handoff). The whole-workflow failure below was observed by the coordinator after handoff; the Unit failure had already occurred before handoff and remains adverse |
| 261118 user ZIP | `metroliza_2026.09rc1_261118_windows.zip`, 284804594 B | SHA-256 `a983eaacd4bb3dd0e1e4d742d18ece7fedcd9f0943fdec9fb095ec61489fc0dd` |
| 261118 launcher EXE | `metroliza_2026.09rc1_261118_launcher.exe`, 335066896 B, PE32+ x86-64 | SHA-256 `970870544e9176096569ad1defa5b6648873075ef5588ad86db812b2262a6660`; payload content SHA-256 `0035dfa3f3058985f81e094435ddf378c23804f707f25eb1490b5ddbd4cc7d43`. Actual smoke-tested EXE/local-vs-CI downloaded receipt identity preserved |
| 261118 manual workflow overall | **FAIL**, despite the package-job successes above | Run 43449763500's duplicate Unit job 131968761529 failed at the unchanged diagnostic-launcher test cleanup `join(1)` boundary: Unit step FAIL at 15:36:25 UTC, job exit at 15:36:27 UTC, before the package handoff. The coordinator subsequently observed this adverse result through the merge operator. The same-head primary source run passed. The actual FAIL and its separate diagnosis/disposition remain in #1220 / PR #1224; do not infer merge readiness or relabel the whole workflow green from the package receipts |
| 261118 private user retest / manual or release approval | **Deferred by the user; acceptance not granted by this checkpoint** | The 2026-11-13 instruction deferred private retest to the following week while implementation/repository closeout continued. No private-data cause/retest, physical comfort, screen-reader, clean-machine/desktop Excel, live-service, legal or release-owner acceptance follows from these automated results |

A separate controlled investigation reproduced the same cleanup assertion when a real resolver
storage-directory fsync was held behind a test barrier, despite close returning SAVED in 0.75010s,
final_saved=true and all incident assertions passing. The ordinary unchanged stalled case passed
in 1.06s, and all workers stopped after the barrier was released. This establishes the teardown
mechanism and supports the admitted test-fixture-only repair; it does not identify the actual CI
worker's blocked frame or prove that the injected storage stall caused the historical CI failure.
The pre-correction launcher/store/test bytes matched accepted dev `0c4a357d`. The admitted fixture
control subsequently recorded old-cleanup FAIL in 2.11s and repaired-fixture PASS in 1.08s, with
close returning SAVED in 0.75032s. These are source control results; the final candidate's CI,
package, delivery and integration outcomes remain authoritative in the issue/PR ledger.

Any correction or later build has its own source/tree, identity and exact receipt ledger. This table
preserves the 261118 outcomes rather than predicting the result, merge or delivery of a future build.

## Historical export-correction attempts — builds 261116 and 261117

- `261116`: [run 43434896238](https://github.com/hexafe/metroliza/actions/runs/43434896238), source
  `86561ff691fe00f25b6358b7eca6a4acbb3e1fd1`, was **CANCELLED** after a new original-OS-error-code
  boundary finding required correction. Combined/source qualification did not complete; **NOT_DELIVERED**.
- `261117`: source `b3ee75615588e4e2a7df51d083b28f0ca2f77776`, tree
  `86afc02a29ed377277da834f9677e5d5ad7feea7`; actual runtime Combined qualification **PASS** in
  [run 43444061065, job 131948804883](https://github.com/hexafe/metroliza/actions/runs/43444061065/job/131948804883).
  The separately downloaded user ZIP also passed its identity checks. However, retained Actions
  receipts artifact `14048196167` omitted all four required `main-html.zip` outputs. Actual downloaded
  artifact digest/size matched, and the unchanged strict local finalizer failed with `FileNotFoundError`
  for `core-dpr-1.0/main-html.zip`; the other three required run archives were also absent.
  **RETAINED_EVIDENCE_FAIL / NOT_DELIVERED**. Runtime PASS and downloaded ZIP identity PASS remain valid
  within their own scopes; neither substitutes for the missing retained qualification evidence.
  Earlier environment-setup failures remain distinct from that reproduced artifact failure.
- `261118` is a new build identity for that exact bounded retention-rule/test correction; no archive
  is reconstructed, validator weakened or earlier failed/cancelled attempt relabelled PASS.

## Delivered UI workflow development package — build 261115

The UI delivery under [#1159](https://github.com/hexafe/metroliza/issues/1159) used
`2026.09 RC1 (build 261115)` on the unchanged `2026.09rc1` line. It brought visible
commands and workspace navigation, completed report results, clearer filter/group controls and
output choices, guided Profiles/Industrial/Realtime setup, and a compact offline dashboard overview.
It was delivered on 2026-11-13 as a qualified development test package. Broader product epics retain
their original criteria; these UI additions do not establish their completion.

| Item | State | Evidence / scope |
|---|---|---|
| 261115 delivered source | `ed8b6ccf35614c005d9e04281e03380a26fc4f25`, tree `6ebee9551e51e787ccf21d31ac8820480e68c7ce` | [PR #1215](https://github.com/hexafe/metroliza/pull/1215) merged as `dd10cdd7cf6db6aec0ccbf26e65cd880dabe9310` with the identical tree. Later branch tips or prose commits do not redefine these package bytes |
| 261115 final source CI | **PASS** | [PR run 43383599732](https://github.com/hexafe/metroliza/actions/runs/43383599732) completed successfully on the exact source: 10621 PASS / 149 SKIP / 419 subtests plus nine appended cohorts; coverage 84.05% / 87.50% against 80%. Independent/GitHub review and root integration adjudication are preserved in [the final record](https://github.com/hexafe/metroliza/pull/1215#issuecomment-6847485588) |
| 261115 Combined + launcher + downloaded ZIP | **PASS / DELIVERED development test package** | [Run 43386007818](https://github.com/hexafe/metroliza/actions/runs/43386007818), Combined job 131754547854: same-package diagnostics/core at DPR 1.0/1.25/1.5 and forced native-unavailable, independent data/offline-output checks, unchanged-onedir launcher packing, cold/warm/incident/cache smoke and downloaded user ZIP verification. Strict local re-verification used the exact Windows CRLF source representation and produced a receipt identical to the native result |
| 261115 user ZIP | `metroliza_2026.09rc1_261115_windows.zip`, 284762864 B | SHA-256 `aeb862b160f69111608ba867475c17e381f1695a23a10abeadb447aeec9df831`; contains the smoke-tested launcher, source provenance, notices/inventory and instructions |
| 261115 launcher EXE | `metroliza_2026.09rc1_261115_launcher.exe`, 335027792 B, PE32+ x86-64 | SHA-256 `4bf2e9fb9523070d8d9beb86a445778267308f1fec1633cbeb0fb918e45644db`; payload content SHA-256 `ccc54808b84dda04f9070c0738ab60daabb1cd3ca2aace81c46ec5ea3935e57b`. Local and CI downloaded-ZIP receipts agree; this is the actual smoke-tested EXE |
| 261115 notices and inventory | Bytes/source/build inventory match; 0 drift/problems in the delivery adjudication | 79 Python / 126 Rust entries; metadata matching does not constitute legal review or release-owner approval |
| 261115 manual set | Committed and pinned | [Immutable manuals](https://github.com/hexafe/metroliza/tree/964241e1d872bec158f2def4bad4fdbd3c0e6bc9/docs/user_manual), including the central keyboard reference; the same full SHA is the default Help/export docs ref |
| 261115 human / release acceptance | **NOT_RUN / NOT_GRANTED** beyond the recorded automated/visual scope | Thirty genuine native captures were inspected; that does not prove physical Polish-keyboard/AltGr/hand comfort, screen-reader use, clean-machine/desktop Excel, representative private reports or applicable live-service/legal acceptance. Remaining #1159 acceptance and release-owner decision stay separately tracked |
| Superseded candidate 261114 | Build attempt started; no accepted package claimed | PR #1215 Windows core job 131502055816 ended 614 PASS / 1 FAIL / 1 SKIP: all six real completed-result corruption controls passed, then the native fixture lacked required expected-DPR context. Original FAIL retained; the build attempt does not qualify 261115 |
| Superseded candidate 261113 | Build attempt started; no accepted package claimed | PR #1215 Windows core job 131492860207 failed an assertion comparing native Windows and POSIX path spellings after the real read-only SQLite connection succeeded. Original FAIL retained; the build attempt does not qualify 261114. The original 261113 assignment check at 20:35 UTC on 2026-11-12 covered reachable version history, current refs/tags, three releases and latest 100 of 2,894 artifacts |
| Earlier local Stage A checks | PASS on `b5e1f629`: 70 focused tests, one declared DPR 1.5 geometry case and full security audit | Earlier preliminary security FAIL remains retained. The six unchanged SQL finding rebindings and one public fixture placeholder passed the strict local gate; this evidence is earlier than the final-source CI |
| Historical source build 261112 | Retained at source `7b0de056` and its accepted integration history | Historical 261112 source/CI evidence stays bound to its original bytes |

The later [#1220 export investigation](https://github.com/hexafe/metroliza/issues/1220) does not erase
261115's actual delivery/qualification results, and those results do not prove the later correction
or the user's original failure cause. Preserve the earlier download interruption, hardlink and
source-representation failures beside the successful byte-bound re-verification.

The frozen qualified `261031` package and its still-open manual acceptance remain as recorded
below. The development packages above do not move its archived source, hashes, receipts or acceptance.

## Frozen RC qualification and existing decisions

| Item | State | Evidence / next gate |
|---|---|---|
| Integration order | #1109, #1142, one STEP2+STEP3 aggregate, #1063; merge commits | #1153, current-base checks and independent reviews per merge |
| Current RC source line | `rc` (formerly `release/2026.09-rc1`) | Original cut from accepted final develop; exact frozen SHA/tree in #1153 and the rows below |
| STEP3 delivery | Complete with disclosed limits | [Immutable report](https://github.com/hexafe/metroliza/blob/f69ca5da31be5ef7efd5547457f14744dcb93baa/docs/engineering/performance-boost-step3.md) |
| Frozen RC build identity | `261031`: Combined, launcher smoke and ZIP gates **PASS** in CI (scope in the rows below); `261029` stays bound to the historical bytes below | Synchronized source metadata under #1158 (#1189); changed binaries never reuse 261029 |
| Frozen candidate source (261031) | `6dc0554667a842e107bd547fc86aeefedc52aec4`, tree `710332799cb9d7b6f58e59603b8e4630fb2f34d0` | Head of `release/2026.09-rc1` after sync #1190 (#1185, #1186, #1188, #1189); RC tree equals `develop` `d558a430` |
| 261031 Combined + launcher + ZIP (one build) | **PASS** in run [41154237127](https://github.com/hexafe/metroliza/actions/runs/41154237127): diagnostics, core at DPR 1.0/1.25/1.5, forced native-unavailable, fresh reopen, onedir unchanged by acceptance, launcher packed from that onedir without rebuild, launcher smoke in four scenarios (normal/cold, normal/verified reopen, hard exit/warm, preview/warm; warm is the cache state), ZIP completeness, inventory gate, downloaded-ZIP re-check | Job 124397401592 `combined-candidate-receipt.json` (package tree `1461ef3a…`, `qualified-windows-development-package.zip` `799760d3…`, artifact 13024638914). Onedir content hash (packer definition) `6b8ce7372494c77def5005dd456bd68bc77828239bbf4d23fe63508fa0a56ae1` = EXE payload. Job 124401380755 verified the downloaded ZIP. Packing the qualified onedir does not by itself accept the launcher start path beyond the smoke scenarios |
| 261031 user ZIP | One launcher EXE, original provenance, visible `.licenses`, README; unsigned | `metroliza_2026.09rc1_261031_windows.zip` SHA-256 `7005d05e13ea9159bcc7ec6b10de6224ff7fb4f19d0b11162f8ed92552699c20`, 284555192 B; EXE `metroliza_2026.09rc1_261031_launcher.exe` SHA-256 `2ee40bd389f9547cf9a0f52294d4c8943e2c509c184f91c6c09957cc2c778952`, 334822568 B; runtime cache `2026.09rc1_261031-6b8ce7372494_6dc05546`. Actions artifact 13024584128 (`windows-release-zip`, wrapper `987009e3…`), retained until 2027-01-29. Re-verified locally after download on 2026-10-31 |
| 261031 notices and inventory | ZIP notices equal the RC source; inventory equals this build (79 Python, 126 Rust packages) | `release/third-party-inventory.json` PASS, 0 differences, compared with the frozen build venv and 27 bundled dist-info; Rust list over-approximates (all targets and kinds). `review_status` unchanged: metadata not reviewed, no release-owner or legal sign-off |
| 261031 Help documentation ref | Pinned to `b2510e0aa651e8c96363e5a9c224c841318cc9d0` | `scripts/check_release_docs_ref.py --online`: 12 manuals + group-analysis Markdown/PDF present and published at that commit |
| 261031 frozen compute workers, portable envelope, native launcher synthetic qualification | **NOT_RUN** on 261031 | Not dispatched. The portable onefile job builds a second payload; the compute driver `qualify_windows_compute_workers.py --artifact-dir` itself accepts an existing onedir but CI runs it only inside that job; the synthetic launcher qualification packs a test entry as `2026.00test(260101)`. Only the portable job, as wired, builds a second 261031 onedir and EXEs; the other two could run without producing a second 261031 EXE |
| 261031 durable archive | Done; recovery from GitHub **PASS** (2026-10-31) | Tag `archive/2026.09-rc1/build-261031` on `6dc05546`, unpublished draft release with the four original Actions archives, the unchanged user ZIP, job logs, run metadata, manifests and `ARCHIVE_SHA256SUMS`; see [archive record](../archive/2026/build-261031-provenance/README.md). Actions retention ends 2027-01-29 |
| 261031 manual ZIP/EXE acceptance | **NOT_RUN** | [Tester ZIP packet](rc1_261031_zip_acceptance_2026-10-31.md): W1 (Windows + desktop Excel), W2 (clean machine with antivirus), private reports, #1143 copy, Google smoke |
| 261029 accepted candidate source (historical, fixed) | `b2510e0aa651e8c96363e5a9c224c841318cc9d0`, tree `e165267b09b437b7fe5a1556b5809e87123f1c9a` | Head of `release/2026.09-rc1` when run [40991278786](https://github.com/hexafe/metroliza/actions/runs/40991278786) was dispatched. Later commits on `develop`, including this document, do not move or replace it |
| 261029 Combined Windows candidate acceptance (CI onedir) | **PASS**: diagnostics, core at DPR 1.0/1.25/1.5, forced native-unavailable, fresh reopen; one package | Job 123854028888, `combined-candidate-receipt.json`. Accepted `qualified-windows-development-package.zip` SHA-256 `da8a25eb2d0a4e79c80823bc03f470bc81fde3fe0a83d7037437ac61e495b84c`, 538738623 B, package tree `cb9b18c1…`; Actions artifact 12949329678. Not clean-machine, desktop Excel, real-report or release acceptance |
| 261029 tester launcher EXE | Separate build from the same source; **not** the Combined bytes; unsigned | `metroliza_2026.09rc1_261029_launcher.exe` SHA-256 `16f3edb988bc9d0e5000c89796f40daf0bd2ebfef468c6e34827a3947512b408`, 334830360 B; Actions artifact 12949892358 (job 123854029137). Launcher smoke **PASS** on these bytes: cold, verified and warm cache, hard exit, preview |
| 261029 portable envelope EXE | Smoke **PASS** (same job) | `metroliza_2026.09rc1_261029.exe` SHA-256 `1c87cc32…`; not the tester file and not archived |
| 261029 frozen compute workers | Equal to serial outputs | Receipt 12949499262, measured on the onefile job's own supervised onedir, neither on the Combined package nor on the EXE |
| 261029 native launcher qualification | **PASS**, synthetic payload | Job 123854029037: component test with a synthetic test entry, not a run of the tester EXE |
| 261029 manual EXE acceptance | **NOT_RUN** (historical packet) | Native dialogs and mouse focus, desktop Excel lock, clean machine with antivirus, representative real reports, Help/manual, notices/legal, #1143 disposition and Google smoke, all on the exact tester EXE (#1158) |
| 261029 durable archive | Original Actions archives, EXE, receipts, job logs | Tag `archive/2026.09-rc1/build-261029`, unpublished draft release; see [archive record](../archive/2026/build-261029-provenance/README.md). Actions retention ends 2027-01-28 |
| Core-flow Qt retain at exit | Open follow-up, not a gate for the Combined PASS | [#1184](https://github.com/hexafe/metroliza/issues/1184) |
| Promotion to main / published release | **Not authorized by #1153** | Full RC checklist and release-owner Go required |
| Historical RC lines | 2026.06 RC2 closed without a release (#901); `release/2026.06-rc2` retired, recovery tag `archive/2026.06-rc2/final` | Historical `rc2` hosted links preserved by rename redirects to `rc` (#1187/#924); verify during migration |
| Dependency upgrades #972/#973 | Deferred until after RC | Refresh separately, preserve STEP3 exact dependency pins |
| Security exception review #906 | Open | Selected STEP3 baseline earliest expiry 2026-11-23; verify the actual baseline before every gate and renew before expiry. The issue's original 2026-10-31 deadline is historical, not a new waiver |

The frozen qualified RC1 package is `2026.09 RC1 (build 261031)` on the same RC1 release line; its
CI evidence is listed above, its bytes are archived under `archive/2026.09-rc1/build-261031`, and its manual acceptance is open. For 261031 the launcher EXE
carries the same onedir that passed Combined (content hash above); it is not a separate build.
Build `261029` (which replaced the inherited 261020 label) remains the historical accepted
candidate: its Combined PASS accepts the 261029 CI onedir bytes only, and its tester launcher
EXE was a separate build of the same source. Every release-owner criterion remains open in
#1158. At the frozen qualification checkpoint, the copy of this file on
`release/2026.09-rc1` was intentionally not synchronized and its head was the 261031 source
`6dc05546`. The naming migration does not rewrite that source/receipt binding. Historical test
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
`RELEASE_VERSION` defines the public version and `CURRENT_RELEASE_HIGHLIGHT` the synchronized
release summary. Follow the [versioning policy](../project/versioning_policy.md) for actual
`YYYY-MM-DD` build dates from `built_at_utc`; `VERSION_DATE` is legacy compatibility metadata,
not the new public version or an inferred actual build date. Run
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
It does not designate June RC2 as the current candidate. The original snapshot preserves the
then-current refs and gate state; later June RC2 closure without a release under #901 and immutable
recovery under `archive/2026.06-rc2/final` remain separate historical decisions. The current main/dev/rc
names do not rewrite those receipts or grant September candidate/release approval.
