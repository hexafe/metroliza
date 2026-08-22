# Branch cleanup execution plan

- Status: Proposed; no branch mutation authorized
- Owner: Repository maintainer
- Last reviewed: 2026-08-22
- Repository: `hexafe/metroliza`
- Tracking issue: [#911](https://github.com/hexafe/metroliza/issues/911)
- Source audit: [`branch_audit.md`](branch_audit.md)

This document converts the branch archaeology snapshot into a sequence of decisions and gates. It
does not authorize or record a merge, tag, deletion, force-update, default-branch change, or other
ref mutation. Commit counts and dependencies were refreshed on 2026-08-22 after the audit branch
and draft [PR #959](https://github.com/hexafe/metroliza/pull/959) were created.

## Decision vocabulary

- **KEEP:** retain the branch in its present role.
- **MERGE:** integrate through its reviewed pull request after its stated gates pass.
- **SALVAGE:** carry still-useful requirements or ideas through current Issues and new focused
  branches; do not revive or merge the historical branch wholesale.
- **TAG_AND_DELETE:** preserve a verified release boundary with an immutable tag, then retire the
  redundant branch only after explicit approval.
- **DELETE:** remove a remote source branch only after integration, dependency, SHA-recording, and
  approval checks pass.

## Branch decision matrix

The canonical comparison base is `develop`. “Unique” means commits reachable from the named ref but
not from `develop`; it does not mean a commit message merely differs. Historical names that are no
longer remote heads are included because they were explicitly in scope and still affect cleanup
decisions.

| Branch | Current state | Decision | Action | Risk | Required confirmation |
| --- | --- | --- | --- | --- | --- |
| `master` | **Why/state:** GitHub default and historical production line at `ab26258e72d2`; 279 behind / 0 ahead of `develop`, with **0 unique commits** but 904 files of tip-tree drift. **Class:** release history/production. **Dependencies:** no open PR targets it; [#900](https://github.com/hexafe/metroliza/issues/900), [#901](https://github.com/hexafe/metroliza/issues/901), and [#920](https://github.com/hexafe/metroliza/issues/920) govern its role and any promotion. | **KEEP** | Protect it and accept changes only through an approved release or hotfix PR. Do not use cleanup work to fast-forward it. | Product-wide 904-file promotion surface; current `develop` evidence does not close packaged Windows, live Google, notices, or legal gates for `master`. | Release owner approves #901 evidence, exact promotion diff/SHA, green required checks, rollback owner, and the separate production PR. |
| `develop` | **Why/state:** canonical integration base at `a03bbdacbd6c`; **0 unique commits** relative to itself and currently equal to `rc2` and `release/2026.06-rc2`. **Class:** active development. **Dependencies:** draft PR #959 targets it; #900 and PR #910 define its canonical role. | **KEEP** | Make it the explicit base for normal Issue-driven work after the transition sequence below. Keep branch protection and required CI. | GitHub still defaults to stale `master`; PR #910 has not yet integrated the authoritative branch-role text. | PR #910 is accepted first, planned fast-forwards are verified, protection/default settings are reviewed, and exact-head CI is green. |
| `rc1` (historical; recovered candidate `release/2026.03-rc1`) | **Why/state:** requested release-history name, but no exact bare `rc1` remote ref or pull-request ref remains. The defensible recovered release tip is `260a70d00eec`, 652 behind / 0 ahead of `develop`, with **0 unique commits**; later RC1 fixes are visible at `c5939533f5a9`. **Class:** release history, not active development. **Dependencies:** no active PR depends on the missing ref; [#924](https://github.com/hexafe/metroliza/issues/924) must settle identity and [#920](https://github.com/hexafe/metroliza/issues/920) owns future release naming. | **TAG_AND_DELETE** | Keep the branch absent. If #924 proves the intended release boundary, create one annotated archival tag at the approved SHA; there is no current branch ref to delete. | Tagging the wrong of two plausible historical points would permanently mislabel release history; recreating the branch would add ambiguity. | Maintainer records the exact intended RC1 SHA, tag name/message, provenance from PR #713/#774, absence of an existing conflicting tag, and explicit tag approval. |
| `rc2` | **Why/state:** transition/reference alias for the long-running RC line; tip `a03bbdacbd6c` exactly matches `develop` and `release/2026.06-rc2`, so it has **0 unique commits**. **Class:** temporary release history/transition. **Dependencies:** active PRs [#910](https://github.com/hexafe/metroliza/pull/910) and [#958](https://github.com/hexafe/metroliza/pull/958) target it; #900, #901, and #924 depend on its current identity. | **KEEP** | Retain through the open-PR transition. Freeze routine work after #910, reconcile accepted release fixes, then reassess under #924 for eventual **TAG_AND_DELETE**. | Removing or moving it now breaks active PR bases and historical links; accepting new feature work prolongs the ambiguity. | #910 and #958 are resolved, no open PR/workflow/docs link requires the ref, the release SHA is reconciled, #924 approves the archival tag, and deletion receives separate approval. |
| `release/2026.06-rc2` | **Why/state:** convention-compliant frozen candidate/evidence branch at `a03bbdacbd6c`; **0 unique commits** at the snapshot. **Class:** active release work. **Dependencies:** PR #910 plans to fast-forward it after branch-policy integration; #901 and #920 govern release evidence and process. | **KEEP** | Use only for release-blocking fixes and evidence. Reconcile every accepted candidate fix back to `develop`; retain through release closeout. | Feature drift invalidates the freeze; a release-only fix can be lost if it is not reconciled to `develop`. | Release owner approves each candidate change, exact-head checks and #901 manual gates pass, and every release-only commit is accounted for in `develop`. |
| `docs/900-branch-transition` | **Why/state:** implements the branch-role decision; open PR #910 targets `rc2`. Tip `94753979a05b` is 0 behind / 1 ahead with **1 unique commit** and an eight-file docs/process delta. **Class:** active documentation/governance development. **Dependencies:** PR #910 and issue #900 directly depend on it; #958 and #959 must follow its accepted policy. | **MERGE** | Diagnose the unit-test failure, update without rewriting history, obtain green exact-head CI, then merge PR #910 first. Record its final merge SHA before any source-branch cleanup. | Observed unit-test jobs failed; it overlaps `docs/project/README.md` and `roadmap.md` with #958. Merging out of order can invalidate the planned fast-forward and restore stale branch policy. | Required CI is green, conflicts are reviewed, #900 accepts the language, a maintainer approves the merge method, and the final SHA is recorded. |
| `docs/911-branch-archaeology-audit` | **Why/state:** preserves the non-destructive inventory and this execution plan in draft PR #959 targeting `develop`. It had **1 unique commit** (`31bfb94e8870`) before this plan; this plan is a second documentation-only commit, for a three-file PR delta. **Class:** active documentation/audit work. **Dependencies:** PR #959 and issue #911 directly depend on it; its base/order depends on #910. | **MERGE** | Keep #959 draft until #910 is integrated. Bring the updated `develop` into this branch with a normal, non-force update, refresh counts if refs changed, obtain green CI/review, then merge the documentation PR. | Merging #959 into `develop` before #910 would make #910's planned fast-forward of `develop` impossible without reconciliation. Audit facts can also become stale while other PRs move refs. | #910 transition is complete, refreshed refs match the document, required docs/CI checks pass, reviewer accepts every disposition, and a maintainer approves merge. |
| `docs/project-governance-reset` | **Why/state:** source branch for the project control center. PR #909 was squash-merged as `a03bbdac`; its source tip `375cc433f0af` is graph-divergent by 1/1 with **1 graph-unique commit**, but its tree is identical to `develop`. **Class:** obsolete merged source branch. **Dependencies:** no active PR or current Issue needs the ref; the closed PR and squash commit preserve review/content history. | **DELETE** | After the deletion gate, record `375cc433f0af`, recheck tree equality and dependencies, obtain approval, and delete only this remote branch. | The source commit will no longer be reachable from a normal head; an unnoticed automation or external bookmark could still name it. | `git diff --quiet` proves tree equality, no open PR has it as head/base, no workflow or protected-branch rule names it, recovery SHA is recorded, and a maintainer explicitly approves deletion. |
| `docs/project-specification-roadmap-2026-08` | **Why/state:** product capability catalog, expanded specification, and Issue-linked roadmap in open PR #958 targeting `rc2`. Tip `0e166bfa95c9` is 0 behind / 4 ahead with **4 unique commits** and four changed docs. **Class:** active documentation/product-planning work. **Dependencies:** PR #958 and open issues #902/#925 depend on this planning work; closed #899 is governance context, and the branch's content overlaps PR #910. | **MERGE** | After #910, reconcile the accepted branch-role language, retarget to the canonical base when allowed, fix the failing unit-test lane, review the large docs delta, and merge through #958. | Observed unit-test jobs failed; merging before reconciliation can reintroduce `rc2` as the normal product line or overwrite accepted roadmap wording. | #910 is integrated, base/overlap resolution is reviewed, exact-head CI is green, issue links are current, and a maintainer approves #958. |
| `performance-boost` (historical) | **Why/state:** broad performance line later merged and reverted on `master`; recovered tip `75f79b5a1c92` is 282 behind / 0 ahead with **0 unique commits** against `develop`. It is not a live remote head. **Class:** obsolete implementation branch with useful research history. **Dependencies:** no active PR needs the ref; [#918](https://github.com/hexafe/metroliza/issues/918) and [#908](https://github.com/hexafe/metroliza/issues/908) carry benchmark/native-acceleration decisions. | **SALVAGE** | Keep the branch absent. Extract only benchmark findings or narrowly verified changes into the active Issues and new focused branches based on current `develop`; never re-merge the historical 107-file delta. | The old line crossed parser, UI, native, and performance surfaces and was explicitly reverted on `master`; wholesale resurrection risks regressions and duplicates changes already in `develop`. | Each salvaged item has an Issue, current baseline benchmark, focused diff, parity/rollback criteria, and green targeted plus full required tests. |
| `report-metadata-redesign` (historical; recovered `codex/report-metadata-redesign`) | **Why/state:** report metadata/provenance redesign represented by closed unmerged draft PR #892 at `efe1c430c30e`; the tip is 243 behind / 0 ahead with **0 unique commits** and is not a live head. **Class:** obsolete development branch with requirements history. **Dependencies:** no active PR needs the ref; #917 owns metadata/provenance schema work, with #915, #929, and #930 covering adjacent model/OCR/database concerns. | **SALVAGE** | Keep the branch absent. Convert unmet requirements into #917 acceptance criteria and implement only current-schema gaps in focused branches from `develop`. | The historical 241-file PR delta mixes migration, OCR, report, persistence, UI, and test changes; replaying it can regress the now-canonical result model or duplicate landed work. | Schema owner maps each proposed field/migration to current code and Issues, confirms backward compatibility and rollback, and approves focused tests before any implementation PR. |
| `feature/realtime-industrial-ml-anomaly` (historical) | **Why/state:** broad realtime industrial/ML anomaly work from closed PR #898 at `13c47617ef85`; 57 behind / 0 ahead with **0 unique commits**, and no live remote head. **Class:** obsolete development branch with product/validation history. **Dependencies:** no active PR needs the ref; #919 and #941 carry realtime contracts and operator-ready delivery. | **SALVAGE** | Keep the branch absent. Route only still-missing contracts, detector evidence, or operator safeguards through #919/#941 and new focused branches from current `develop`. | The historical 776-file delta included line integration and many unrelated areas; wholesale revival would obscure provenance and can invalidate current replay, bounded-read, UI, and packaging evidence. | Domain owner identifies a current requirement gap, fixture/replay and performance gates are defined, rollback behavior is documented, and focused/full required tests pass. |

## Recommended future branch strategy

Use a small role-based topology:

1. `master` is protected production history. It receives only reviewed release-promotion or emergency
   hotfix PRs and is never the base for routine work.
2. `develop` is the protected canonical integration branch and default base for normal work. After
   #910 settles the transition, changing the GitHub default from `master` to `develop` is a separate
   maintainer decision, not an implicit cleanup step.
3. `release/YYYY.MM-rcN` is a temporary frozen stabilization branch. Only release blockers,
   evidence, packaging, security/legal notices, and release metadata belong there. Every accepted
   release-only fix is reconciled to `develop` before promotion.
4. Short-lived Issue branches use `<type>/<issue>-<slug>`, where `type` is `feature`, `fix`, `docs`,
   `refactor`, `test`, `security`, or `chore`. They are deleted only after their PR is integrated and
   the deletion gate passes.
5. `hotfix/<issue>-<slug>` starts from the production commit, lands in `master` through review, and
   is immediately reconciled into `develop` and any open release branch.
6. Immutable annotated tags identify approved release boundaries. Bare rolling aliases such as
   `rc1` and `rc2` are not created for future releases.

## Migration path

The ordering is part of the safety model. A later phase must not begin until the preceding phase's
recorded gates pass.

### Phase 0 — preserve and verify

1. Keep PR #959 in draft and save the current head inventory plus all recovery SHAs in #911/#924.
2. Refresh heads, PR head/base dependencies, branch protection, workflow references, and tags with
   the read-only commands below.
3. Record an approval owner and rollback owner for every planned ref mutation. If any branch moves,
   recalculate ancestry, unique commits, and changed files before continuing.

### Phase 1 — integrate the branch-role decision first

1. Diagnose PR #910's failing unit-test lane and update its source branch without rebasing or force
   pushing.
2. When #910 is green and approved, merge it through GitHub into `rc2` using the reviewed merge
   method and record the resulting commit.
3. Confirm that `develop` and `release/2026.06-rc2` can be fast-forwarded to that exact accepted
   commit. A maintainer may then perform those two fast-forwards as separately approved actions.
4. Verify that all three trees match and that branch protections remain enabled.

This phase must precede #959: merging #959 into `develop` first would make the planned #910
fast-forward diverge and would require an extra reconciliation merge.

### Phase 2 — integrate the active documentation branches

1. Update `docs/911-branch-archaeology-audit` from the post-#910 `develop` with a normal merge or
   equivalent non-rewriting PR update. Refresh this plan, make #959 ready, and merge it only after
   documentation checks and review pass.
2. Update `docs/project-specification-roadmap-2026-08` from the accepted branch-policy baseline,
   resolve its overlap with #910 explicitly, retarget #958 to `develop` when the transition permits,
   fix its failing test lane, and merge only after review.
3. Record final source and merge SHAs for #910, #959, and #958 in their PRs or tracking Issues.

### Phase 3 — clean integrated documentation source branches

For each candidate independently, run the deletion gate, obtain approval, delete the one named
remote branch, and immediately verify it is absent. The initial candidates are:

- `docs/project-governance-reset`, after its already-merged state is reverified;
- `docs/900-branch-transition`, after #910 and the post-merge fast-forwards complete;
- `docs/911-branch-archaeology-audit`, after #959 merges;
- `docs/project-specification-roadmap-2026-08`, after #958 merges.

Do not batch approvals: one stale or dependent branch must not block accurate handling of another.

### Phase 4 — close the release transition

1. Complete #901's packaged Windows, live Google, notice/legal, and release-owner evidence on the
   exact release candidate.
2. Promote the approved `release/2026.06-rc2` state to `master` only through a dedicated reviewed
   PR and record its production tag.
3. Reconcile the released commit back into `develop` and verify no release-only commit was lost.
4. Under #924, verify the RC1 historical SHA and the final RC2 SHA/tag, confirm no remaining
   dependency on `rc2`, and request separate approval before retiring the alias.
5. Only after the branch roles are stable, decide whether GitHub's default branch should change to
   `develop`; update protections, templates, automation, and contributor documentation together.

### Phase 5 — salvage historical themes without reviving branches

Use #918/#908 for performance, #917 for report metadata, and #919/#941 for realtime industrial
work. Every salvaged item starts from current `develop`, has a narrow Issue and acceptance criteria,
and produces new exact-head evidence. The missing historical branch names remain absent.

## Exact actions requiring human approval

The following mutations are deliberately **not executed by this plan**. Each occurrence requires a
named maintainer's explicit approval after its branch-specific gate; prior approval for one item
does not authorize another.

| Mutating action | Exact target | Approval evidence required before execution |
| --- | --- | --- |
| Merge a pull request | #910, then #959, then #958 in the gated order above | Approved exact head SHA, green required checks, reviewed conflicts/merge method, and recorded rollback owner. |
| Fast-forward a protected branch | `develop` to the accepted #910 result | Proof that the update is a fast-forward, exact target SHA, clean comparison, and maintainer approval. No force update. |
| Fast-forward a release branch | `release/2026.06-rc2` to the accepted #910 result | Same proof plus release-owner confirmation that candidate evidence remains valid. No force update. |
| Promote a release | `release/2026.06-rc2` into `master` through a dedicated PR | #901 complete, exact promotion diff, green checks, production rollback plan, and release-owner sign-off. |
| Create an annotated tag | verified RC1 SHA; approved RC2/release SHA | #924 identity record, unused tag name, exact object SHA/message, and release-owner approval. Never move an existing published tag. |
| Delete a remote branch | `docs/project-governance-reset` | Recorded recovery SHA `375cc433f0af4d2d0a49e5dacc33ec0b53733479`, zero tree drift, no dependency, and explicit deletion approval. |
| Delete a remote branch | `docs/900-branch-transition` | #910 merged, final source/merge SHAs recorded, planned fast-forwards verified, no dependency, and explicit deletion approval. |
| Delete a remote branch | `docs/911-branch-archaeology-audit` | #959 merged, final source/merge SHAs recorded, no dependency, and explicit deletion approval. |
| Delete a remote branch | `docs/project-specification-roadmap-2026-08` | #958 merged, final source/merge SHAs recorded, no dependency, and explicit deletion approval. |
| Delete the transition alias | `rc2` | #910/#958 resolved, #901/release reconciliation complete, #924 archival tag verified, no dependency, and separate explicit deletion approval. |
| Change repository settings | GitHub default branch and protection/rulesets for `master`, `develop`, or release branches | Maintainer review of open PR bases, automation, required checks, documentation, permissions, and rollback steps. |

There is no deletion action for `rc1`, `performance-boost`, `report-metadata-redesign`, or
`feature/realtime-industrial-ml-anomaly`: those exact remote heads are already absent. Do not
recreate them merely to delete them.

## Safe commands for later verification

These commands are read-only with respect to the remote repository. `git fetch --no-tags origin`
updates only local remote-tracking knowledge; it intentionally omits `--prune` so stale local refs
are not removed during evidence collection.

```bash
git fetch --no-tags origin
git ls-remote --heads origin
git ls-remote --tags origin
git rev-parse origin/develop
git rev-list --left-right --count origin/develop...origin/rc2
git rev-list --left-right --count origin/develop...origin/release/2026.06-rc2
git log --oneline origin/develop..origin/docs/900-branch-transition
git log --oneline origin/develop..origin/docs/911-branch-archaeology-audit
git log --oneline origin/develop..origin/docs/project-governance-reset
git log --oneline origin/develop..origin/docs/project-specification-roadmap-2026-08
git diff --name-status origin/develop...origin/docs/900-branch-transition
git diff --name-status origin/develop...origin/docs/911-branch-archaeology-audit
git diff --quiet origin/develop origin/docs/project-governance-reset
git merge-base --is-ancestor origin/master origin/develop
git merge-base --is-ancestor origin/rc2 origin/develop
git merge-base --is-ancestor origin/release/2026.06-rc2 origin/develop
gh pr list --repo hexafe/metroliza --state open --json number,headRefName,baseRefName,url
gh issue view 900 --repo hexafe/metroliza
gh issue view 901 --repo hexafe/metroliza
gh issue view 924 --repo hexafe/metroliza
rg -n 'docs/project-governance-reset|docs/900-branch-transition|docs/911-branch-archaeology-audit|docs/project-specification-roadmap-2026-08|rc2' .github docs CONTRIBUTING.md README.md
```

Before any deletion candidate is approved, repeat the relevant ancestry/tree commands using its
recorded full SHA, inspect open PRs with the candidate as both head and base, and check GitHub branch
protection/rulesets in the repository settings. Exit status 0 from `git diff --quiet` or
`git merge-base --is-ancestor` is evidence for one predicate only; it is not deletion authorization.

### Approval-only deletion commands

The later remote deletion commands, shown here so the exact scope can be reviewed, are:

```bash
# HUMAN APPROVAL REQUIRED; do not run as part of this plan.
git push origin --delete docs/project-governance-reset
git push origin --delete docs/900-branch-transition
git push origin --delete docs/911-branch-archaeology-audit
git push origin --delete docs/project-specification-roadmap-2026-08
git push origin --delete rc2
```

No `--force`, `--force-with-lease`, history rewrite, bulk deletion, or wildcard command belongs in
this cleanup.

## Rollback strategy

1. **Before each mutation:** write the full source SHA, target SHA, approver, timestamp, PR/Issue,
   and expected result into the governing PR or Issue. This is the recovery ledger.
2. **Wrong source-branch deletion:** recreate only the exact deleted ref from its recorded SHA with
   `git push origin <RECORDED_FULL_SHA>:refs/heads/<EXACT_BRANCH_NAME>`, after separate approval.
   Do not reconstruct from memory or from a similar commit message.
3. **Problematic documentation or policy merge:** revert the merge/squash commit through a new PR;
   do not reset or force-push the protected branch. Reopen the original Issue with the failed gate.
4. **Problematic release promotion:** use a reviewed revert or forward hotfix on `master`, then
   reconcile the correction into `develop` and the active release line. Never rewrite published
   production history.
5. **Wrong default-branch setting:** restore the recorded previous default, protections, required
   checks, and PR-base guidance; then inspect all PR bases created during the interval.
6. **Wrong published tag:** do not silently move it. Freeze release activity, document the error,
   create a corrected tag name only with release-owner approval, and treat tag deletion as a new
   exceptional destructive action.
7. **Failed salvage:** close or revise the focused PR/Issue. Because salvage starts from current
   `develop` and does not revive old refs, historical branch state remains unchanged.

Cleanup is complete only when every retained branch has one documented role, every removed branch
has a recovery SHA and approval record, active PR bases match the target strategy, and no release or
development commit is reachable only through a branch scheduled for removal.
