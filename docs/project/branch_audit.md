# Branch inventory

- Status: Audit snapshot
- Owner: Repository maintainer
- Last reviewed: 2026-08-22
- Repository: `hexafe/metroliza`
- Tracking issue: [#911](https://github.com/hexafe/metroliza/issues/911)
- Time zone: Europe/Warsaw

This is a non-destructive archaeology report. The audit fetched and read refs, commits, diffs,
pull-request metadata, and CI metadata. It did not delete, merge, tag, force-update, or rewrite any
branch. Recommendations below are decisions for later work, not actions taken by this audit.

## Audit basis

The live remote exposed seven heads at the snapshot:

- `develop`
- `docs/900-branch-transition`
- `docs/project-governance-reset`
- `docs/project-specification-roadmap-2026-08`
- `master`
- `rc2`
- `release/2026.06-rc2`

The repository default branch is `master`, but `develop` is used as the comparison baseline. That
choice is based on the existing `develop` ref and the explicit branch-transition decision in
[#900](https://github.com/hexafe/metroliza/issues/900) and
[#910](https://github.com/hexafe/metroliza/pull/910), which name `develop` as the canonical base for
new Issue-driven work. PR #910 is still open, so the branch-role documentation is not yet fully
integrated even though the refs and decision already exist.

For `develop...branch`, **behind** means commits reachable only from `develop`; **ahead** means
commits reachable only from the named branch. “Unique commits” uses graph reachability, not commit
message similarity. A squash-merged branch can therefore have graph-unique commits while having no
tree-content difference from `develop`.

Age is shown in whole calendar days as of the snapshot. “Changed files” means the branch-side
three-dot delta unless otherwise stated. For an ancestor or patch-equivalent branch, tip-to-tip tree
drift is reported separately so missing canonical work is not mistaken for branch-unique work.

## Summary

| Branch or recovered ref | Tip at audit | Last commit | Age | Behind / ahead vs `develop` | Unique commits | Changed files | Recommendation |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| `develop` | `a03bbdacbd6c` | 2026-08-22 — project control center (#909) | 0 d | 0 / 0 | 0 | 0 | **KEEP** |
| `docs/900-branch-transition` | `94753979a05b` | 2026-08-22 — establish `develop` and frozen RC2 flow | 0 d | 0 / 1 | 1 | 8 | **MERGE** after CI is green |
| `docs/project-governance-reset` | `375cc433f0af` | 2026-08-22 — project control center | 0 d | 1 / 1 | 1 graph-only | 15 in original delta; 0 tip-tree drift | **DELETE** after normal deletion gate |
| `docs/project-specification-roadmap-2026-08` | `0e166bfa95c9` | 2026-08-22 — full feature backlog | 0 d | 0 / 4 | 4 | 4 | **MERGE** after CI and branch-order reconciliation |
| `master` | `ab26258e72d2` | 2026-03-30 — revert performance boost | 145 d | 279 / 0 | 0 | 0 unique; 904 files of tip-tree drift | **KEEP** |
| `rc2` | `a03bbdacbd6c` | 2026-08-22 — project control center (#909) | 0 d | 0 / 0 | 0 | 0 | **KEEP** temporarily |
| `release/2026.06-rc2` | `a03bbdacbd6c` | 2026-08-22 — project control center (#909) | 0 d | 0 / 0 | 0 | 0 | **KEEP** |
| requested `rc1`; recovered `release/2026.03-rc1` | `260a70d00eec` | 2026-03-18 — merge group-analysis improvements | 157 d | 652 / 0 | 0 | 238 in recovered release delta | **TAG_AND_DELETE**; exact bare-ref tip needs verification |
| historical `performance-boost` | `75f79b5a1c92` | 2026-03-30 — parser cancellation shutdown fix | 145 d | 282 / 0 | 0 | 107 in RC2-era delta | **SALVAGE** |
| requested `report-metadata-redesign`; recovered `codex/report-metadata-redesign` | `efe1c430c30e` | 2026-04-29 — stabilize OCR metadata enrichment | 115 d | 243 / 0 | 0 | 241 in PR delta | **SALVAGE** |
| historical `feature/realtime-industrial-ml-anomaly` | `13c47617ef85` | 2026-06-17 — fit industrial sync dialog in CI | 66 d | 57 / 0 | 0 | 776 in PR delta | **SALVAGE** |

## Current remote branches

### `develop`

- **Purpose:** canonical integration branch for new Issue-driven features, fixes, refactors, tests,
  documentation, security, and dependency work.
- **Current status:** tip `a03bbdacbd6c308acf46ca31c16d0dd2caeab304`; also the exact tip of
  `rc2` and `release/2026.06-rc2`. It is 279 commits ahead of stale `master`.
- **Unique commits and changed files:** none relative to itself.
- **Architectural areas affected:** this is the current product-wide baseline: `src/metroliza`,
  legacy compatibility modules, report/OCR storage, parsing, exports, native/Rust acceleration,
  industrial/realtime workflows, desktop UI, packaging, CI/security, and the expanded test suite.
- **Valuable changes:** it contains all recoverable tips examined for `performance-boost`, the report
  metadata redesign, realtime industrial work, and the RC1 release line. Nothing in those recovered
  tips is graph-unique against `develop`.
- **Tests/build impact:** the exact `a03bbdac` tree has green static checks, unit tests, native wheel
  build/import smoke, Windows core smoke, CMM parser performance guardrail, and performance trend
  evidence. The recorded main suite result is `3030 passed, 21 skipped`, with 83.80% aggregate
  coverage. Manual/opt-in packaged Windows startup, packaging, live Google conversion, notices, and
  legal/release-owner evidence remain open under [#901](https://github.com/hexafe/metroliza/issues/901).
- **Risks:** GitHub still defaults to stale `master`, and PR #910—the documentation that makes the
  branch roles unambiguous—is open and currently has a failing unit-test job.
- **Recommendation: KEEP.** Use it as the base and explicit PR target for this audit and normal new
  work. Do not confuse “canonical development” with “approved for production promotion.”

### `master`

- **Purpose:** default/historical production branch, retained until an approved release promotion.
- **Current status:** tip `ab26258e72d285c3917a595515798da185800373`, dated 2026-03-30. Its
  final commit is [PR #888](https://github.com/hexafe/metroliza/pull/888), which reverted the merge
  of `performance-boost` from [PR #887](https://github.com/hexafe/metroliza/pull/887).
- **Unique commits:** none relative to `develop`; it is 279 behind and 0 ahead.
- **Changed files and architecture:** no branch-unique files, but its tree differs from `develop` in
  904 files. The missing work is product-wide: about 17% of changed paths are under legacy
  `modules/`, about 27% under `tests/`, and large areas under `src/metroliza` cover reports,
  parsing, exports, charts, UI, native code, and industrial/realtime services. CI, scripts,
  packaging, security, and documentation also drift substantially.
- **Valuable changes:** it is the preserved production/history anchor and GitHub default. The
  performance merge and revert remain traceable in its history.
- **Tests/build impact:** no current exact-head evidence comparable to `develop` was found. A
  wholesale promotion would change 904 files and must not be inferred safe from the green
  development-tree evidence.
- **Risks:** contributors can accidentally base or target work here because GitHub presents it as
  default. Merging `develop` wholesale would also bypass the open manual release gates.
- **Recommendation: KEEP.** Preserve as the historical production line until the explicit release
  decision. Do not use it as the development base and do not fast-forward or merge it as part of
  branch cleanup.

### `rc2`

- **Purpose:** long-running ad-hoc RC integration line, now a transition/reference alias.
- **Current status:** tip `a03bbdacbd6c`, exactly equal to `develop` and
  `release/2026.06-rc2`; 0 behind, 0 ahead.
- **Unique commits and changed files:** none relative to `develop`.
- **Architectural areas affected:** no distinct current delta. Historically it accumulated the
  product-wide line now shared by all three refs.
- **Valuable changes:** preserves external references and the history of the RC2 stabilization line
  while branch roles are being changed.
- **Tests/build impact:** identical tree, automated evidence, and manual blockers to `develop`.
- **Risks:** three names for one commit invite wrong-base PRs and false assumptions that an RC label
  means release approval. It must not receive routine work after the transition decision.
- **Recommendation: KEEP** temporarily. Retire only through the separate verification/tagging gate
  in [#924](https://github.com/hexafe/metroliza/issues/924), after release reconciliation and after
  no open workflow, PR, or document depends on the name.

### `release/2026.06-rc2`

- **Purpose:** convention-compliant frozen stabilization and evidence line for the current RC2
  candidate.
- **Current status:** tip `a03bbdacbd6c`, exactly equal to `develop` and `rc2`; 0 behind, 0 ahead.
- **Unique commits and changed files:** none at the snapshot.
- **Architectural areas affected:** no distinct current delta. Future changes should be limited to
  release-blocking fixes, release evidence, packaging, security/legal notices, and metadata.
- **Valuable changes:** provides a bounded place to close [#901](https://github.com/hexafe/metroliza/issues/901)
  without putting routine feature work onto the candidate.
- **Tests/build impact:** shares `develop`'s green automated evidence and its still-open manual
  release blockers. Every accepted candidate fix must be reconciled back into `develop`.
- **Risks:** because it currently equals `develop`, it has not yet demonstrated separation from new
  feature work. Accidental feature merges would invalidate the freeze and require new exact-head
  evidence.
- **Recommendation: KEEP.** It is an active release/evidence branch, not a historical alias.

### `docs/900-branch-transition`

- **Purpose:** implement the non-destructive branch-role decision: canonical `develop`, frozen
  `release/2026.06-rc2`, transition-only `rc2`, and no promotion of `master` before #901.
- **Current status:** open [PR #910](https://github.com/hexafe/metroliza/pull/910), targeting `rc2`.
  Tip `94753979a05b263fdd2f486e42e328dfe7318146`; 0 behind, 1 ahead.
- **Unique commits:** `9475397 docs(release): establish develop and frozen RC2 branch flow`.
- **Changed files:** 8 documentation/process files: `CONTRIBUTING.md`, `docs/README.md`,
  `docs/project/{README.md,development_workflow.md,roadmap.md}`,
  `docs/release_checks/{branching_strategy.md,release_status.md}`, plus new
  `docs/release_checks/rc2_branch_transition_decision_2026-08-22.md` (624 insertions, 347
  deletions).
- **Architectural areas affected:** repository governance, contributor workflow, branch/release
  policy, evidence ownership, and roadmap routing. No runtime or build code changes.
- **Valuable changes:** resolves the most dangerous ambiguity in the repository: default branch,
  development base, release evidence line, and promotion are given separate roles.
- **Tests/build impact:** static checks, native wheel smoke, and Windows core smoke passed on the
  head. Both observed unit-test jobs failed in Actions run
  [`32586369190`](https://github.com/hexafe/metroliza/actions/runs/32586369190); downstream
  performance jobs and manual lanes were skipped. `git diff --check` also reports Markdown
  trailing spaces used in two changed status documents; the audit does not claim these caused the
  unit-test failure.
- **Risks:** merging with red required checks would contradict the exact-head evidence policy it
  introduces. It also overlaps `docs/project/README.md` and `roadmap.md` with the product-roadmap
  branch.
- **Recommendation: MERGE** through PR #910 only after the unit-test failure is diagnosed, the
  exact head is green, and the planned post-merge fast-forwards are reviewed. Do not cherry-pick
  fragments or merge this audit into the same branch.

### `docs/project-governance-reset`

- **Purpose:** establish the Issue-driven project control center, architecture/product documents,
  Issue forms, PR template, and documentation guardrails.
- **Current status:** [PR #909](https://github.com/hexafe/metroliza/pull/909) was squash-merged as
  `a03bbdac`; the remote source branch still points to `375cc433f0af4d2d0a49e5dacc33ec0b53733479`.
  It is 1 behind and 1 ahead by graph, but its tip tree is identical to `develop`.
- **Unique commits:** one graph-unique source commit, `375cc43`; no unique content remains.
- **Changed files:** the original delta touched 15 files (2,523 insertions, 101 deletions): Issue
  templates, PR template, contributor/docs indexes, seven `docs/project` and branching documents,
  and `tests/test_docs_markdown_links.py`. Tip-to-tip tree drift is 0 files.
- **Architectural areas affected:** governance and documentation architecture only; no application
  runtime, schema, packaging, or dependency changes.
- **Valuable changes:** fully retained in the squash commit and PR record.
- **Tests/build impact:** the resulting canonical tree has green full automated evidence. Keeping
  the source branch adds no testable content.
- **Risks:** the branch looks active despite being fully integrated and can attract accidental new
  work. Deleting it would make the source commit unreachable from normal heads, but the merged PR
  and squash commit preserve review and content history.
- **Recommendation: DELETE** after confirming no open PR/workflow depends on the branch. No tag is
  justified because it is not a release state and has no distinct tree content. This audit does
  not perform the deletion.

### `docs/project-specification-roadmap-2026-08`

- **Purpose:** add the full product capability catalog, expanded product specification, and an
  Issue-linked multi-phase roadmap.
- **Current status:** open [PR #958](https://github.com/hexafe/metroliza/pull/958), targeting `rc2`.
  Tip `0e166bfa95c98c81fbeaf77d75727cfe70a20b68`; 0 behind, 4 ahead.
- **Unique commits:** `2d7045c` feature catalog; `8e651db` product specification; `8c25c35`
  delivery roadmap; `0e166bf` project control-center update.
- **Changed files:** 4 files, 1,448 insertions and 457 deletions:
  `docs/project/README.md`, new `docs/project/feature_catalog.md`,
  `docs/project/product_specification.md`, and `docs/project/roadmap.md`.
- **Architectural areas affected:** product requirements, domain/feature boundaries, roadmap
  sequencing, and Issue traceability. No runtime or build code changes.
- **Valuable changes:** converts a diffuse backlog into explicit capabilities, requirement IDs,
  phases, and Issues.
- **Tests/build impact:** static checks, native wheel smoke, and Windows core smoke passed on the
  head. Both observed unit-test jobs failed in Actions run
  [`32590398667`](https://github.com/hexafe/metroliza/actions/runs/32590398667); downstream
  performance jobs and manual lanes were skipped. `git diff --check` reports Markdown trailing
  spaces in three changed project documents; the audit does not claim these caused the unit-test
  failure.
- **Risks:** `README.md` and `roadmap.md` overlap PR #910, and its text still describes `rc2` as the
  active product line. Merge order can therefore reintroduce stale branch policy or produce a
  content conflict.
- **Recommendation: MERGE** only after the unit-test failure is fixed and the branch is reconciled
  on top of the accepted #910 branch-role language. Retarget to the canonical branch when the
  transition permits; do not merge red CI.

## Requested names that are no longer remote heads

The following names were not returned by the live remote-head query. They are included because the
task and #911 explicitly require them. Where the exact requested ref was not recoverable, the audit
uses only concrete PR/head evidence and labels the gap instead of inventing a tip.

### `rc1` (historical; exact bare ref not recoverable)

- **Purpose:** historical 2026.03 release-candidate integration and stabilization.
- **Current status:** no remote head named `rc1` exists. No pull request with exact head or base
  `rc1` was found. The defensible release anchor is
  [PR #713](https://github.com/hexafe/metroliza/pull/713), whose exact head was
  `release/2026.03-rc1` at `260a70d00eec296e101b736776129778d86aa042`. A later, separate
  [PR #774](https://github.com/hexafe/metroliza/pull/774) came from
  `rc1/fixes-and-grouping-improvements` at `c593953f3f862289be84252d120a1c79c6f468ad`.
- **Last commit and age:** recovered release head: 2026-03-18, 157 days old; later fixes head:
  2026-03-22, 153 days old.
- **Unique commits:** both recovered heads are ancestors of `develop`; 0 commits are unique to
  either recovered line. The release head is 652 behind/0 ahead; the fixes head is 528 behind/0
  ahead.
- **Changed files:** the recoverable `release/2026.03-rc1` PR-base delta spans 238 files (52,576
  insertions, 4,265 deletions). The later fixes delta spans 120 files (8,058 insertions, 953
  deletions). These counts are historical branch deltas, not current unique content.
- **Architectural areas affected:** parser/plugin and native CMM work; export/group analysis and
  XLSX layout; database helpers; desktop dialogs; CI/coverage policy; Nuitka/PyInstaller packaging;
  release metadata; manuals and tests.
- **Valuable changes:** RC1 introduced broad parser/export/test infrastructure and the later fixes
  strengthened group-analysis output, parser packaging, module naming, help/manual integration,
  and workbook regression coverage. All recovered code is present in later history.
- **Tests/build impact:** the RC1 status recorded `827 passed, 20 skipped` for its then-current QA
  snapshot and added CI coverage visibility, native parity, export artifact assertions, and an
  opt-in packaging build. Its own release status was **No-Go** because Google credential smoke and
  runtime/manual packaging evidence were incomplete. That old evidence must not be treated as a
  current release claim.
- **Risks:** the exact bare `rc1` tip cannot be proven from current refs or PR metadata, so tagging
  an assumed SHA would create false history. The release line also predates large schema,
  industrial, realtime, security, and packaging changes.
- **Recommendation: TAG_AND_DELETE.** Keep the bare branch absent. Under #924, first confirm the
  intended exact RC1 state—prefer the evidence-backed `release/2026.03-rc1` head unless repository
  records prove a different bare-ref tip—then create an annotated historical tag with an honest
  validation note. No tag or deletion is performed here.

### `performance-boost` (historical)

- **Purpose:** a broad performance/native acceleration program, not merely one isolated speed fix.
  The inspected delta covers Python fallbacks, five Rust/PyO3 crates, chart composition, CMM
  parsing, distribution fitting, comparison/group statistics, export batching, telemetry,
  benchmarks, packaging, and CI guardrails.
- **Current status:** no remote head. Recovered tip
  `75f79b5a1c9211019c8b5d75ea61a904aad5fc55`, dated 2026-03-30, from PRs
  [#887](https://github.com/hexafe/metroliza/pull/887) and
  [#889](https://github.com/hexafe/metroliza/pull/889). It was merged into `master`, immediately
  reverted there by PR #888, and separately merged into the RC2 line. The tip is now an ancestor of
  `develop`.
- **Unique commits:** 0 relative to `develop`; 282 behind, 0 ahead. Against the RC2 base captured
  by PR #889, the historical line contains 228 commits.
- **Changed files:** 107 files in the RC2-era delta (22,135 insertions, 1,913 deletions). Key paths
  include `modules/{comparison_stats,distribution_fit_service,chart_renderer,cmm_native_parser,
  export_data_thread}.py`, native crates under `modules/native/`, benchmark scripts, packaging
  PowerShell/spec files, CI, parity fixtures, and focused tests.
- **Architectural areas affected:** Python/native boundaries, fallback selection, numerical parity,
  renderer payload contracts, parser staging/cancellation, workbook export, observability, build
  distribution, and performance governance.
- **Valuable changes:** benchmark harnesses and parity fixtures; vectorized Python bootstrap CI;
  removal of wasted distribution-fit precompute; native candidate-fit and chart paths; explicit
  fallbacks, telemetry, and parser cancellation fixes. The archived audit recorded representative
  improvements including about 11.4x for one bootstrap-CI scenario and 9.69x for native batch fit
  estimation, with parity checks on the audited fixtures.
- **Tests/build impact:** the historical audit records focused suites of 65, 32, 18, 104, and 155
  passing tests plus Ruff, native-wheel, parity, and benchmark checks. Native packaging introduced
  PyO3/Python-version and Windows build complexity; current `develop` CI is the stronger current
  evidence because the branch tip has no unique code.
- **Risks:** the immediate `master` revert had no explanatory body beyond “Reverts #887,” so the
  original integration should not be replayed. Microbenchmarks do not prove user-visible benefit;
  ndarray conversion, Python/Rust crossings, numerical tolerances, cancellation, optional backend
  behavior, and packaged-wheel availability all need end-to-end parity evidence.
- **Recommendation: SALVAGE.** Do not recreate or merge the historical branch. Keep its commits,
  benchmark methods, fixtures, and authorship as evidence; re-evaluate retained native paths via
  focused, benchmark-backed decisions under [#918](https://github.com/hexafe/metroliza/issues/918).

### `report-metadata-redesign` (historical requested label)

- **Purpose:** redesign report identity and persistence, then add structured metadata extraction,
  OCR enrichment, view-backed queries, UI/export integration, and packaging support.
- **Current status:** no exact ref named `report-metadata-redesign` exists. The matching concrete
  record is closed, unmerged draft [PR #892](https://github.com/hexafe/metroliza/pull/892), whose
  actual head was `codex/report-metadata-redesign` at
  `efe1c430c30ecb98ecb1246113e4869192f9c3bf`, dated 2026-04-29. That tip is nevertheless an
  ancestor of current `develop`, so the work entered the later product line by another integration
  path.
- **Unique commits:** 0 relative to `develop`; 243 behind, 0 ahead. The original PR line contained
  40 commits relative to its recorded `master` base.
- **Changed files:** 241 files in the historical PR delta (39,115 insertions, 2,961 deletions).
  Principal paths include `report_schema.py`, `report_repository.py`, metadata model/normalizer/
  selector/extractor modules, `report_query_service.py`, parser/persistence/query/export/grouping
  consumers, RapidOCR model assets and scripts, requirements and packaging, CI, and extensive
  schema/OCR/export tests.
- **Architectural areas affected:** physical-source SHA-256 identity; parsed-report identity;
  canonical metadata plus candidates/warnings; flat measurement storage and views; parser/native
  persistence boundary; report-id-first filtering/grouping/export; OCR runtime/model packaging; and
  background enrichment UI.
- **Valuable changes:** it separated file identity from report identity, made `parsed_reports.id`
  the relational key, preserved extraction evidence, moved reads behind stable views/query helpers,
  and added deterministic normalization, schema, OCR, persistence, and packaging tests.
- **Tests/build impact:** branch records show full validation of `1161 passed, 22 skipped`, Ruff
  clean, focused schema/parser/export suites, OCR package validation, and a saved-corpus privacy
  scan. Build impact is material: vendored ONNX models, OCR/runtime dependencies, Windows
  diagnostics, and PyInstaller/Nuitka data/notice paths. The native Rust DB writer still targeted
  the legacy schema and was intentionally bypassed.
- **Risks:** schema/data migration and compatibility aliases are durable contracts; filename versus
  content identity affects deduplication; OCR adds binary size, hardware/backend, accuracy, privacy,
  and licensing risk; acceptance PDFs were not committed; and renderer/query consumers can drift
  back to legacy tables. A closed unmerged PR is also not proof of rejection because the tip is in
  current history.
- **Recommendation: SALVAGE.** Do not merge or recreate the old branch. Audit and stabilize the
  already-integrated design through focused schema/result-model work under
  [#917](https://github.com/hexafe/metroliza/issues/917), retaining compatibility and migration
  tests before changing storage contracts.

### `feature/realtime-industrial-ml-anomaly` (historical)

- **Purpose:** an industrial data and realtime monitoring product line, including read-only Oznak
  acquisition, local SQLite cache/analytics/export, stream/replay contracts, anomaly detectors,
  operator UI, and interactive dashboards.
- **Current status:** no remote head. Closed, unmerged draft
  [PR #898](https://github.com/hexafe/metroliza/pull/898) identifies tip
  `13c47617ef85dc1a92d2088a8e1bd873cee4fe76`, dated 2026-06-17. The tip is an ancestor of
  `develop`, so the code entered the current product line by another integration path.
- **Unique commits:** 0 relative to `develop`; 57 behind, 0 ahead. Its historical PR line contained
  226 commits relative to the recorded `master` base.
- **Changed files:** 776 files in the PR-base delta (199,015 insertions, 38,432 deletions). That
  number includes intervening product-line integration, so it must not be read as 776 files of
  realtime-only work. The feature-specific paths include `src/metroliza/industrial/{anomaly,
  realtime}`, industrial repositories/services, Oznak adapter, dashboard/UI modules, replay and
  calibration scripts, 16 sanitized realtime fixtures, requirements/packaging, and a large focused
  test family.
- **Architectural areas affected:** production-source safety and credentials, bounded streaming and
  cache persistence, event/ingest time and cursor offsets, replay, detector contracts/baselines,
  alert/event storage, optional Isolation Forest dependencies, background polling/threading,
  operator dialogs, HTML dashboards, and packaged assets.
- **Valuable changes:** deterministic replay fixtures; explicit stream/sample contracts; transparent
  spec-limit, IQR, z-score, stale-source and drift detectors; local event/config repositories;
  read-only/bounded source access; cache-first export and dashboard behavior; and extensive failure,
  security, and UI tests.
- **Tests/build impact:** the June 17 release note records `2109 passed, 314 skipped`, focused 184-test
  industrial/realtime/dashboard coverage, Ruff/compile/release/security checks, and an 81% combined
  coverage gate. CI publication and manual packaged/Google/legal evidence were still pending. The
  branch adds optional anomaly dependencies, embedded dashboard assets, onedir/onefile packaging,
  database schemas, and significant Qt/background-worker surface.
- **Risks:** detector scores lack meaning without explicit alert costs and reviewed baselines;
  event-time ordering, late/missing data, warm-up/reset, source lag, and duplicate handling are
  safety-critical; production credentials and queries require strict read-only/bounded controls;
  GUI/file-analysis coupling can make replay and failure handling brittle; optional ML adds model
  identity and deployment complexity.
- **Recommendation: SALVAGE.** Do not merge or recreate the historical branch wholesale. Preserve
  replay, detector, streaming, source-safety, and UI findings, but re-scope them behind accepted
  contracts and an ADR under [#919](https://github.com/hexafe/metroliza/issues/919). Current product
  delivery remains separately tracked by [#941](https://github.com/hexafe/metroliza/issues/941).

## Consolidated disposition and sequencing

1. Keep `develop`, `master`, `release/2026.06-rc2`, and—temporarily—`rc2`.
2. Fix the failed unit-test job on `docs/900-branch-transition`, then merge PR #910 through review.
3. Reconcile `docs/project-specification-roadmap-2026-08` on the accepted branch-role documents,
   fix its failed unit-test job, then merge PR #958 through review.
4. Treat `docs/project-governance-reset` as an integrated delete candidate; apply the normal
   deletion gate in #911, not this audit PR.
5. Keep `rc1` absent. Verify an exact evidence-backed historical SHA before creating any annotated
   RC1 tag under #924.
6. Do not resurrect the performance, metadata, or realtime branches. Their recovered tips are
   already ancestors of `develop`; use #918, #917, and #919 for focused salvage and explicit
   acceptance/rejection decisions.
7. Do not promote or merge the development/candidate line into `master` until #901 supplies the
   missing manual release evidence and the release owner records a Go decision.

## Reproduction notes

The core mechanical checks used for each live ref were:

```text
git ls-remote --heads origin
git show -s --format=<sha,date,subject> <ref>
git rev-list --left-right --count origin/develop...<ref>
git log origin/develop..<ref>
git diff --name-status origin/develop...<ref>
git diff --shortstat origin/develop..<ref>
```

Historical refs were resolved from concrete PR head/base SHAs, then checked with the same
`rev-list`, `log`, `diff`, and ancestry operations. GitHub PR/check metadata was read to distinguish
merged, closed-unmerged, open, and failing-CI states. No branch name was treated as evidence of its
contents or safety.
