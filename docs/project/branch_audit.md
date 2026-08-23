# Branch inventory

- Status: Current non-destructive audit snapshot
- Owner: Repository maintainer
- Last reviewed: 2026-08-23
- Audit timestamp: `2026-08-23T23:27:31+02:00` (`Europe/Warsaw`)
- Repository: `hexafe/metroliza`
- Tracking issue: [#911](https://github.com/hexafe/metroliza/issues/911)
- Time zone: Europe/Warsaw
- Comparison baseline: `develop` at `1b58303fee1483a88d2c987f7f06595dac8db7f3`
- Live remote branch count: 9

This is a non-destructive archaeology report. The audit fetched and read refs, commits, diffs,
pull-request metadata, and CI metadata. Its only branch-history change is the authorized normal
merge of current `develop` into this existing topic branch. It did not merge a PR, delete a branch,
create or move a tag, force-update or rewrite history, update a protected/release ref, or execute a
recommendation below.

## Audit basis and changes since the previous snapshot

`git fetch --prune` plus an explicit all-heads refspec and a fresh GitHub query exposed nine remote
heads at the timestamp above:

- `develop`
- `docs/900-branch-transition`
- `docs/911-branch-archaeology-audit`
- `docs/960-branch-cleanup-execution`
- `docs/project-governance-reset`
- `docs/project-specification-roadmap-2026-08`
- `master`
- `rc2`
- `release/2026.06-rc2`

The previous audit used `develop` at `a03bbdacbd6c308acf46ca31c16d0dd2caeab304` and seven live
branches. Since then:

- [PR #910](https://github.com/hexafe/metroliza/pull/910) was squash-merged as
  `1eeeab27352ed2c6bcbdca2af81f3fdd7c1f8cac`; its branch policy and Dependabot version-update
  targeting are integrated;
- [PR #958](https://github.com/hexafe/metroliza/pull/958) was squash-merged as current `develop`
  `1b58303fee1483a88d2c987f7f06595dac8db7f3`; the product specification, feature catalog, roadmap,
  and acyclic dependency model are integrated;
- `rc2` and `release/2026.06-rc2` remain at `1eeeab2`, one commit behind `develop`, so they are no
  longer identical to it; their seven-file drift is the develop-only #958 product-control delta;
- the merged #910 and #958 source branches became deletion candidates subject to the normal gate;
- the #959 audit branch and stacked #961 cleanup-plan branch are now live active branches.

The repository default remains `master`, while `develop` is the accepted canonical base for normal
Issue-driven development. `master` is retained as the production/history anchor pending #901, and
the frozen release line is not expected to absorb later develop-only product planning.

For `develop...branch`, **behind** means commits reachable only from `develop`; **ahead** means
commits reachable only from the named branch. “Unique commits” uses graph reachability, not commit
message similarity. A squash-merged branch can therefore have graph-unique commits while having no
tree-content difference from `develop`.

“Tip-tree drift” is the two-dot file/content difference between each tip and this exact `develop`.
For squash-integrated branches, the audit also compares the source tip with its recorded squash
commit. This prevents graph-unique source commits from being misclassified as tree-unique work.
Historical PR deltas remain historical evidence and are not substituted for current tip drift.

The published #959 head at the remote snapshot is `56150b4a20d0ef510cf8364bb0786ec2257c3393`.
During this authorized reconciliation, current `develop` was merged normally as local merge commit
`ec467735f93d62933f1a12811d2e0a8735db0c35`; its parents are the published #959 head and the exact
`develop` baseline above. The eventual audit commit and exact-head CI are recorded in PR #959
because a version-controlled document cannot contain its own commit SHA without changing it.

## Summary

Every live branch appears exactly once in this current-state table. Behind/ahead and tree drift use
the same exact `develop` SHA recorded in the metadata.

| Live branch | Exact head and last commit | Behind / ahead | Graph-unique commits | Tip-tree drift vs `develop` | Open PR use | Relevant exact-head CI | Recommendation |
|---|---|---:|---:|---|---|---|---|
| `develop` | `1b58303fee1483a88d2c987f7f06595dac8db7f3`; 2026-08-23T23:08:56+02:00 — product specification, roadmap and feature backlog (#958) | 0 / 0 | 0 | 0 files | base of #959 | [32666611423](https://github.com/hexafe/metroliza/actions/runs/32666611423) — success | **KEEP** |
| `docs/900-branch-transition` | `b978a759f341d2c0c44f61bc4d0416aec868fb0e`; 2026-08-23T10:23:15+02:00 — target Dependabot updates at `develop` | 2 / 3 | 3 squash-source commits | 7 files; source tree equals #910 squash `1eeeab2` | none; #910 merged | [32628140821](https://github.com/hexafe/metroliza/actions/runs/32628140821) — success | **DELETE** after gate |
| `docs/911-branch-archaeology-audit` | `56150b4a20d0ef510cf8364bb0786ec2257c3393`; 2026-08-22T21:57:43+02:00 — separate cleanup plan | 2 / 3 at remote snapshot | 3 published audit-history commits | 17 files before reconciliation | head of #959; base of #961 | [32595391862](https://github.com/hexafe/metroliza/actions/runs/32595391862) — success on snapshot head | **KEEP** until #959 and #961 dependency clear |
| `docs/960-branch-cleanup-execution` | `2a80a0dd3317fe17b5b4c3538e1adff1b284bd0b`; 2026-08-22T21:59:59+02:00 — cleanup execution plan | 2 / 4 | 4, including 3 inherited audit commits | 18 files; unique plan delta vs #959 is 2 files | head of draft #961 | [32595415370](https://github.com/hexafe/metroliza/actions/runs/32595415370) — success | **KEEP** until #961 is reconciled and merged |
| `docs/project-governance-reset` | `375cc433f0af4d2d0a49e5dacc33ec0b53733479`; 2026-08-22T18:37:10+02:00 — project control center | 3 / 1 | 1 squash-source commit | 16 files; source tree equals #909 squash `a03bbda` | none; #909 merged | [32585291955](https://github.com/hexafe/metroliza/actions/runs/32585291955) — success | **DELETE** after gate |
| `docs/project-specification-roadmap-2026-08` | `b8b698c020f616a3c53bcc5286291206ae1026f3`; 2026-08-23T22:49:16+02:00 — normalize dependency graph | 1 / 6 | 6 squash-source/history commits | 0 files; tree equals #958 squash/current `develop` | none; #958 merged | [32665601016](https://github.com/hexafe/metroliza/actions/runs/32665601016) — success | **DELETE** after gate |
| `master` | `ab26258e72d285c3917a595515798da185800373`; 2026-03-30T19:43:19+02:00 — revert performance boost (#888) | 281 / 0 | 0; ancestor of `develop` | 907 files | none | [23758996717](https://github.com/hexafe/metroliza/actions/runs/23758996717) — success, historical 2026-03-30 evidence | **KEEP** |
| `rc2` | `1eeeab27352ed2c6bcbdca2af81f3fdd7c1f8cac`; 2026-08-23T10:56:09+02:00 — branch transition (#910) | 1 / 0 | 0; ancestor of `develop` | 7 files, all from develop-only #958 | none | [32629600614](https://github.com/hexafe/metroliza/actions/runs/32629600614) — success | **KEEP** temporarily |
| `release/2026.06-rc2` | `1eeeab27352ed2c6bcbdca2af81f3fdd7c1f8cac`; 2026-08-23T10:56:09+02:00 — branch transition (#910) | 1 / 0 | 0; ancestor of `develop` | 7 files, all from develop-only #958 | none | [32629649201](https://github.com/hexafe/metroliza/actions/runs/32629649201) — success | **KEEP** while #901 is open |

### Recovered historical refs

| Requested or historical ref | Recovered exact head and last commit | Behind / ahead | Current tip-tree drift | Evidence | Recommendation |
|---|---|---:|---|---|---|
| requested `rc1`; recovered `release/2026.03-rc1` | `260a70d00eec296e101b736776129778d86aa042`; 2026-03-18T06:19:15+01:00 — merge group-analysis improvements | 654 / 0 | 927 files | merged PR #713; ancestor of `develop` | **TAG_AND_DELETE** only after exact historical-state verification |
| later `rc1/fixes-and-grouping-improvements` | `c593953f3f862289be84252d120a1c79c6f468ad`; 2026-03-22T09:37:23+01:00 — open Markdown files in default browser | 530 / 0 | 907 files | merged PR #774; ancestor of `develop` | **ARCHIVE** as supporting RC1 evidence |
| historical `performance-boost` | `75f79b5a1c9211019c8b5d75ea61a904aad5fc55`; 2026-03-30T19:29:25+02:00 — parser cancellation shutdown fix | 284 / 0 | 897 files | PRs #887/#889; ancestor of `develop` | **SALVAGE** evidence only |
| requested `report-metadata-redesign`; recovered `codex/report-metadata-redesign` | `efe1c430c30ecb98ecb1246113e4869192f9c3bf`; 2026-04-29T07:24:04+02:00 — stabilize OCR metadata enrichment | 245 / 0 | 822 files | closed draft PR #892; ancestor of `develop` | **SALVAGE** unmet intent only |
| historical `feature/realtime-industrial-ml-anomaly` | `13c47617ef85dc1a92d2088a8e1bd873cee4fe76`; 2026-06-17T21:37:41+02:00 — fit industrial sync dialog in CI | 59 / 0 | 410 files | closed draft PR #898; ancestor of `develop` | **SALVAGE** contracts/fixtures only |

## Current remote branches

### `develop`

- **Purpose:** canonical integration branch for new Issue-driven features, fixes, refactors, tests,
  documentation, security, and dependency work.
- **Current status:** tip `1b58303fee1483a88d2c987f7f06595dac8db7f3`; 0 behind/0 ahead of
  itself and 281 commits ahead of `master`. It contains squash-merged #910 and #958. Open PR #959
  targets it.
- **Unique commits and changed files:** none relative to itself.
- **Architectural areas affected:** this is the current product-wide baseline: `src/metroliza`,
  legacy compatibility modules, report/OCR storage, parsing, exports, native/Rust acceleration,
  industrial/realtime workflows, desktop UI, packaging, CI/security, and the expanded test suite.
- **Valuable changes:** it contains all recoverable tips examined for `performance-boost`, the report
  metadata redesign, realtime industrial work, and the RC1 release line. Nothing in those recovered
  tips is graph-unique against `develop`.
- **Tests/build impact:** exact-head push CI
  [32666611423](https://github.com/hexafe/metroliza/actions/runs/32666611423) is green. The #910 and
  #958 PR heads also completed exact-head CI before squash integration. Manual/opt-in packaged
  Windows startup, packaging, live Google conversion, notices, and legal/release-owner evidence
  remain open under [#901](https://github.com/hexafe/metroliza/issues/901).
- **Risks:** GitHub still defaults to `master`, so contributors must select `develop` explicitly.
  Green development CI is not production-promotion evidence and does not waive #901.
- **Recommendation: KEEP.** Use it as the base and explicit PR target for this audit and normal new
  work. Do not confuse “canonical development” with “approved for production promotion.”

### `master`

- **Purpose:** default/historical production branch, retained until an approved release promotion.
- **Current status:** tip `ab26258e72d285c3917a595515798da185800373`, dated 2026-03-30. Its
  final commit is [PR #888](https://github.com/hexafe/metroliza/pull/888), which reverted the merge
  of `performance-boost` from [PR #887](https://github.com/hexafe/metroliza/pull/887).
- **Unique commits:** none relative to `develop`; it is an ancestor 281 behind and 0 ahead.
- **Changed files and architecture:** no branch-unique files, but its tree differs from `develop` in
  907 files. The drift is product-wide across canonical `src/metroliza`, compatibility-only
  `modules`, tests, parsing, reports, exports, UI, native code, industrial/realtime services, CI,
  packaging, security, and documentation.
- **Valuable changes:** it is the preserved production/history anchor and GitHub default. The
  performance merge and revert remain traceable in its history.
- **Tests/build impact:** exact-head run
  [23758996717](https://github.com/hexafe/metroliza/actions/runs/23758996717) succeeded on 2026-03-30.
  That historical result is not comparable to current `develop` evidence and cannot validate a
  907-file promotion delta.
- **Risks:** contributors can accidentally base or target work here because GitHub presents it as
  default. Merging `develop` wholesale would also bypass the open manual release gates.
- **Recommendation: KEEP.** Preserve as the historical production line until the explicit release
  decision. Do not use it as the development base and do not fast-forward or merge it as part of
  branch cleanup.

### `rc2`

- **Purpose:** long-running ad-hoc RC integration line, now a transition/reference alias.
- **Current status:** tip `1eeeab27352ed2c6bcbdca2af81f3fdd7c1f8cac`, exactly equal to
  `release/2026.06-rc2`; it is an ancestor 1 behind and 0 ahead of `develop`.
- **Unique commits and changed files:** no graph-unique commits. Its seven-file tip-tree drift is
  exactly the develop-only #958 product-control delta: product/index/architecture/roadmap/catalog
  documentation plus the offline catalog test.
- **Architectural areas affected:** no distinct active implementation delta. The branch simply
  predates the later product-planning squash merge.
- **Valuable changes:** preserves external references and the history of the RC2 stabilization line
  while branch roles are being changed.
- **Tests/build impact:** exact-head push CI
  [32629600614](https://github.com/hexafe/metroliza/actions/runs/32629600614) is green. That evidence
  belongs to `1eeeab2`, not the later `develop` tree.
- **Risks:** its stale-looking proximity to both development and release refs can still attract
  wrong-base work. The name has historical/external value but no routine development role.
- **Recommendation: KEEP** temporarily. Retire only through the separate verification/tagging gate
  in [#924](https://github.com/hexafe/metroliza/issues/924), after release reconciliation and after
  no open workflow, PR, or document depends on the name.

### `release/2026.06-rc2`

- **Purpose:** convention-compliant frozen stabilization and evidence line for the current RC2
  candidate.
- **Current status:** tip `1eeeab27352ed2c6bcbdca2af81f3fdd7c1f8cac`, exactly equal to `rc2`;
  it is an ancestor 1 behind and 0 ahead of `develop`.
- **Unique commits and changed files:** no graph-unique commits. The seven-file tree drift is the
  develop-only #958 product-control delta; frozen release policy does not require this candidate
  branch to absorb later planning documents or their documentation-contract test.
- **Architectural areas affected:** no release-line implementation delta. Future changes remain
  limited to release blockers/evidence, packaging, security/legal notices, and metadata.
- **Valuable changes:** provides a bounded place to close [#901](https://github.com/hexafe/metroliza/issues/901)
  without putting routine feature work onto the candidate.
- **Tests/build impact:** exact-head push CI
  [32629649201](https://github.com/hexafe/metroliza/actions/runs/32629649201) is green. Manual release
  blockers remain open in #901, and every accepted candidate fix must be reconciled into `develop`.
- **Risks:** treating its one-commit lag as missing work would violate the freeze. Conversely,
  accidental feature/planning merges would invalidate evidence and require a new candidate audit.
- **Recommendation: KEEP.** It is an active release/evidence branch, not a historical alias.

### `docs/900-branch-transition`

- **Purpose:** implement the non-destructive branch-role decision: canonical `develop`, frozen
  `release/2026.06-rc2`, transition-only `rc2`, and no promotion of `master` before #901.
- **Current status:** [PR #910](https://github.com/hexafe/metroliza/pull/910) was squash-merged as
  `1eeeab27352ed2c6bcbdca2af81f3fdd7c1f8cac`. The source branch remains at
  `b978a759f341d2c0c44f61bc4d0416aec868fb0e`; it is 2 behind/3 ahead by graph.
- **Unique commits:** three source commits (`9475397`, `cc86af8`, `b978a75`) remain graph-unique
  because of the squash merge. The source tree is byte-for-byte equal to the #910 squash tree, so
  none is tree-unique.
- **Changed files:** the seven-file tip drift from current `develop` is entirely the later #958
  product-control merge. It is not an unreviewed source-branch delta.
- **Architectural areas affected:** repository governance, contributor workflow, branch/release
  policy, evidence ownership, and roadmap routing. No runtime or build code changes.
- **Valuable changes:** resolves the most dangerous ambiguity in the repository: default branch,
  development base, release evidence line, and promotion are given separate roles.
- **Tests/build impact:** exact source-head PR CI
  [32628140821](https://github.com/hexafe/metroliza/actions/runs/32628140821) succeeded before merge;
  current `develop` also has green post-#958 push CI.
- **Risks:** no open PR, workflow, or tree-unique delta was found. The remaining risk is an external
  reference to the branch name or loss of its recovery SHA during later cleanup.
- **Recommendation: DELETE** only through #960 after the normal deletion gate. Record recovery SHA
  `b978a759f341d2c0c44f61bc4d0416aec868fb0e`; no merge or salvage remains to perform.

### `docs/911-branch-archaeology-audit`

- **Purpose:** carry this non-destructive #911 audit through
  [PR #959](https://github.com/hexafe/metroliza/pull/959).
- **Current status:** published tip `56150b4a20d0ef510cf8364bb0786ec2257c3393`; 2 behind/3 ahead
  at the remote snapshot. It is both the head of draft PR #959 and the base of stacked draft PR
  #961. The normal reconciliation merge is local commit `ec467735f93d62933f1a12811d2e0a8735db0c35`.
- **Unique commits:** published graph-unique commits are `31bfb94` (audit), `b158c92` (initial
  cleanup-plan placement), and `56150b4` (separate that plan). After the normal merge, the branch is
  0 behind and 4 ahead before this refresh commit.
- **Changed files:** the stale remote tip differs from `develop` in 17 files because it predates
  #910/#958. After reconciliation, the intended PR delta is only `docs/project/branch_audit.md` and
  its `docs/README.md` index entry.
- **Open PRs and CI:** #959 uses it as head; #961 uses it as base. Snapshot-head CI
  [32595391862](https://github.com/hexafe/metroliza/actions/runs/32595391862) succeeded. Fresh
  exact-head CI is required after this report is committed and pushed.
- **Valuable changes:** the audit evidence and recovery ledger inputs are prerequisites for safe
  #960 decisions. The branch also anchors the current stacked base of #961.
- **Risks:** deleting or rewriting it now would disrupt both active PRs. Recording only graph counts
  would also misstate the squash-integrated source branches.
- **Recommendation: KEEP** until #959 is merged and #961 no longer depends on its branch/history;
  only then evaluate deletion under #960.

### `docs/960-branch-cleanup-execution`

- **Purpose:** carry the separate #960 gated cleanup execution plan through stacked
  [PR #961](https://github.com/hexafe/metroliza/pull/961).
- **Current status:** tip `2a80a0dd3317fe17b5b4c3538e1adff1b284bd0b`; 2 behind/4 ahead of
  current `develop`. Draft PR #961 remains based on the #959 audit branch and is mergeable in that
  stacked relationship; it must not be retargeted or merged until #959 lands.
- **Unique commits:** four against current `develop`: the three inherited published #959 commits
  plus `2a80a0d`. Relative to the published #959 head, the only tree-unique content is
  `docs/project/branch_cleanup_execution.md` plus one `docs/README.md` index line (176 insertions).
- **Open PRs and CI:** #961 is the only open head use. Exact-head PR CI
  [32595415370](https://github.com/hexafe/metroliza/actions/runs/32595415370) succeeded on `2a80a0d`.
- **Valuable changes:** the plan's branch matrix, deletion gate, recovery procedure, and retained
  two-file delta remain intact. Normal future reconciliation with merged #959 does not require
  dropping or redefining that content.
- **Risks:** its metrics and sequencing are stale, and premature retargeting could obscure its
  stacked diff. It authorizes no cleanup by itself.
- **Recommendation: KEEP** until #959 merges, then retarget/reconcile #961 normally, review its
  refreshed two-file diff, obtain exact-head CI, and merge before considering deletion.

### `docs/project-governance-reset`

- **Purpose:** establish the Issue-driven project control center, architecture/product documents,
  Issue forms, PR template, and documentation guardrails.
- **Current status:** [PR #909](https://github.com/hexafe/metroliza/pull/909) was squash-merged as
  `a03bbdac`; the remote source branch still points to `375cc433f0af4d2d0a49e5dacc33ec0b53733479`.
  It is 3 behind and 1 ahead by graph. Its tip tree is identical to the #909 squash commit, not to
  later current `develop`.
- **Unique commits:** one graph-unique source commit, `375cc43`; no tree-unique source content
  remains because `375cc43` and `a03bbda` have identical trees.
- **Changed files:** the original delta touched 15 files (2,523 insertions, 101 deletions): Issue
  templates, PR template, contributor/docs indexes, seven `docs/project` and branching documents,
  and `tests/test_docs_markdown_links.py`. Current tip-to-`develop` drift is 16 files, all explained
  by later #910/#958 integration.
- **Architectural areas affected:** governance and documentation architecture only; no application
  runtime, schema, packaging, or dependency changes.
- **Valuable changes:** fully retained in the squash commit and PR record.
- **Tests/build impact:** source-head PR CI
  [32585291955](https://github.com/hexafe/metroliza/actions/runs/32585291955) succeeded, and the
  later integrated `develop` head is green. Keeping the source branch adds no testable content.
- **Risks:** the branch looks active despite being fully integrated and can attract accidental new
  work. Deleting it would make the source commit unreachable from normal heads, but the merged PR
  and squash commit preserve review and content history.
- **Recommendation: DELETE** after the #960 gate. No open PR dependency was found; recheck external
  and workflow references and record recovery SHA
  `375cc433f0af4d2d0a49e5dacc33ec0b53733479`. No tag is justified.

### `docs/project-specification-roadmap-2026-08`

- **Purpose:** add the full product capability catalog, expanded product specification, and an
  Issue-linked multi-phase roadmap.
- **Current status:** [PR #958](https://github.com/hexafe/metroliza/pull/958) was reconciled with
  #910, retargeted to `develop`, and squash-merged as current `develop`
  `1b58303fee1483a88d2c987f7f06595dac8db7f3`. The source remains at
  `b8b698c020f616a3c53bcc5286291206ae1026f3`; it is 1 behind/6 ahead by graph.
- **Unique commits:** six source/history commits (`2d7045c`, `8e651db`, `8c25c35`, `0e166bf`,
  reconciliation merge `be2b61c`, and DAG fix `b8b698c`) remain graph-unique because of squash.
- **Changed files:** tip-to-tip tree drift against current `develop` is exactly 0 files. The complete
  approved product content and test tree are present in the squash result.
- **Architectural areas affected:** product requirements, domain/feature boundaries, roadmap
  sequencing, and Issue traceability. No runtime or build code changes.
- **Valuable changes:** converts a diffuse backlog into explicit capabilities, requirement IDs,
  phases, and Issues.
- **Tests/build impact:** exact source-head PR CI
  [32665601016](https://github.com/hexafe/metroliza/actions/runs/32665601016) succeeded before merge;
  post-merge `develop` run 32666611423 also succeeded.
- **Risks:** no open PR, workflow, or unreviewed tree delta was found. The remaining risk is an
  external branch-name dependency or failure to retain the recovery SHA.
- **Recommendation: DELETE** only after the #960 gate. Record recovery SHA
  `b8b698c020f616a3c53bcc5286291206ae1026f3`; no further merge or salvage is required.

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
- **Last commits:** recovered release head: 2026-03-18; later fixes head: 2026-03-22.
- **Unique commits:** both recovered heads are ancestors of `develop`; 0 commits are unique to
  either recovered line. The release head is 654 behind/0 ahead; the fixes head is 530 behind/0
  ahead. Their current tip-tree drift is 927 and 907 files respectively; this is later canonical
  evolution, not missing RC1 content.
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
- **Unique commits:** 0 relative to `develop`; it is an ancestor 284 behind, 0 ahead. Current
  tip-tree drift is 897 files. Against the RC2 base captured by PR #889, the historical line
  contains 228 commits.
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
- **Unique commits:** 0 relative to `develop`; it is an ancestor 245 behind, 0 ahead, with 822 files
  of current tip-tree drift. The original PR line contained 40 commits relative to its recorded
  `master` base.
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
- **Unique commits:** 0 relative to `develop`; it is an ancestor 59 behind, 0 ahead, with 410 files
  of current tip-tree drift. Its historical PR line contained 226 commits relative to the recorded
  `master` base.
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
2. Record #910 as merged at `1eeeab27352ed2c6bcbdca2af81f3fdd7c1f8cac` with exact-head CI
   `32628140821`; no #910 integration work remains.
3. Record #958 as merged at `1b58303fee1483a88d2c987f7f06595dac8db7f3` with exact-head CI
   `32665601016`; no #958 reconciliation or product-DAG work remains.
4. Reconcile, review, and merge #959 into `develop` with fresh exact-head evidence. Keep its branch
   while draft #961 still uses it as a base.
5. After #959 lands, retarget/reconcile #961 to `develop`, verify that its unique delta remains the
   cleanup-plan document plus index entry, obtain fresh review/CI, and merge it.
6. Only after both documents are integrated may #960 re-run gates and execute separately approved
   mutations. This audit executes none.
7. Treat `docs/900-branch-transition`, `docs/project-governance-reset`, and
   `docs/project-specification-roadmap-2026-08` as squash-integrated **DELETE** candidates with
   recovery SHAs `b978a759...`, `375cc433...`, and `b8b698c...`; never infer safety from graph
   counts alone.
8. Keep `rc1` absent. Verify an exact evidence-backed historical SHA before creating any annotated
   RC1 tag under #924.
9. Do not resurrect the performance, metadata, or realtime branches. Their recovered tips are
   already ancestors of `develop`; use #918, #917, and #919 for focused salvage and explicit
   acceptance/rejection decisions.
10. Do not promote or merge the development/candidate line into `master` until #901 supplies the
   missing manual release evidence and the release owner records a Go decision.

## Reproduction notes

The core mechanical checks used for each live ref were:

```text
git ls-remote --heads origin
git show -s --format=<sha,date,subject> <ref>
git rev-list --left-right --count origin/develop...<ref>
git log origin/develop..<ref>
git diff --name-status origin/develop <ref>
git diff --shortstat origin/develop <ref>
gh pr list --state open --json number,headRefName,baseRefName,headRefOid
gh run list --branch <branch> --json databaseId,event,headSha,status,conclusion
```

Historical refs were resolved from concrete PR head/base SHAs, then checked with the same
`rev-list`, `log`, `diff`, and ancestry operations. GitHub PR/check metadata was read to distinguish
merged, closed-unmerged, and open state and to match CI to exact heads. Source-tip trees for squash
PRs #909, #910, and #958 were compared directly with squash commits `a03bbda`, `1eeeab2`, and
`1b58303`; all three comparisons returned zero files. No branch name, graph count, old CI run, or
closed PR state was treated alone as evidence of content or deletion safety.
