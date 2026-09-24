# Branching strategy

This document defines the lightweight branching model used for Metroliza development and release
work. The current branch transition and automatic evidence are recorded in
[`rc2_branch_transition_decision_2026-08-22.md`](./rc2_branch_transition_decision_2026-08-22.md).

## 0) Active repository state — decision 2026-08-22

- `develop` is the canonical branch for new Issue-driven development.
- `release/2026.06-rc2` is the frozen release-candidate/evidence branch for
  `2026.06 RC2 (build 260711)`.
- `rc2` is retained as a historical transition/reference branch and is no longer a target for new
  routine work.
- `master` remains the unchanged default/historical production branch until the current candidate
  receives complete automatic and manual promotion evidence plus a release-owner Go decision.

Validated branch-point content before this decision PR:

- commit: `a03bbdacbd6c308acf46ca31c16d0dd2caeab304`;
- tree: `dc10e028332cb311cb0b2c110deecee2841b9799`;
- CI run: `32585291955`;
- CI-tested synthetic merge: `0a3f2b982f827466f214cede76995a5bf3effa14`;
- tested and final tree SHA are identical.

The automatic gates passed, but packaged/clean-machine Windows, live Google conversion,
third-party notice/artifact, and legal/release-owner evidence remains open in #901. Therefore:

- branch reorganization: **Go**;
- `master` promotion/stable tag: **No-Go pending #901**.

Because GitHub still presents `master` as the default branch, every new pull request must select
its base explicitly: normally `develop`, or `release/2026.06-rc2` for approved release work.

Dependabot is an explicit platform exception. The checked-in `.github/dependabot.yml` policy sets
normal version-update pull requests to target `develop`. GitHub reads that file from the configured
default branch, so this policy becomes active only after the content reaches that branch or the
default-branch setting changes through a separate reviewed decision. Security-update pull requests
always target the repository default branch, currently `master`; `target-branch` does not redirect
them. That generated base does not authorize routine work on `master`, and accepted security fixes
must be reconciled into `develop` and any active release line where applicable.

## 1) Branch purposes

### `master`

`master`: current production-ready branch and historical/default production anchor. It represents
the last accepted production state; the current `2026.06 RC2` candidate is not approved for
promotion while #901 remains open. Only reviewed, release-owner-approved candidate merges and
minimal production hotfixes belong here.

`master` is not a development base. Its default-branch status does not authorize feature/refactor
work or promotion from an unvalidated branch.

### `develop`

Integration branch for active Issue-driven development:

- features;
- bug fixes not specific to the frozen candidate;
- behavior-preserving refactors;
- tests, documentation, security, dependencies, and shared-package work;
- future release preparation before feature freeze.

Normal Issue branches start from and target `develop`.

### `release/2026.06-rc2`

Frozen stabilization/evidence branch for the current candidate. Allowed changes are limited to:

- release-blocking defects;
- packaging/clean-machine fixes;
- release checks, evidence, notes, and metadata;
- narrowly approved security/legal-notice changes.

Every accepted release-line fix must be reconciled into `develop`. No feature expansion, broad
refactor, convenience dependency upgrade, or visual redesign enters this branch without the formal
late-scope exception process.

### `rc2`

Historical transition/reference branch. It preserves the long-running ad-hoc RC development line
and external references during the transition. Do not branch new work from it or target routine
pull requests at it after #900. Retire it only through a separate explicit cleanup after release
reconciliation.

### `hotfix/*`

Urgent production-fix branches cut from `master` after a stable release. They merge into `master`
and are then reconciled into `develop` and any active release line as applicable.

### Issue branches

Short-lived branches for one Issue or one reviewable slice of an Issue.

## 2) Issue branch naming

Use the primary Issue number and a short lowercase description:

- Bug fix: `fix/<issue>-<description>`
- Feature: `feature/<issue>-<description>`
- Refactor: `refactor/<issue>-<description>`
- Documentation: `docs/<issue>-<description>`
- Tests: `test/<issue>-<description>`
- Security: `security/<issue>-<description>`
- Chore/CI/dependency: `chore/<issue>-<description>`

Examples:

```text
docs/902-roadmap-consolidation
refactor/903-export-run-stages
security/906-bandit-renewal
fix/901-packaged-startup-blocker
```

Keep one primary Issue per branch/PR. Split broad Issues into several independently reviewable
branches instead of one product-wide change set.

## 3) Release and hotfix naming

- Release candidate branches: `release/YYYY.MM-rcN`
  - Current: `release/2026.06-rc2`
  - Future example: `release/2026.09-rc1`
- Hotfix branches: `hotfix/<version>-<description>`
  - Example: `hotfix/2026.09.1-startup-fix`

Future candidate creation:

```bash
git checkout develop
git pull --ff-only origin develop
git checkout -b release/2026.09-rc1
git push -u origin release/2026.09-rc1
```

Do not reuse the historical bare `rc2` naming pattern for future cycles.

## 4) Merge directions

### Normal development

```text
Issue branch -> develop
```

### Current/future release stabilization

```text
develop -> release/YYYY.MM-rcN    (branch cut at feature freeze)
release-fix branch -> release/YYYY.MM-rcN
accepted release fix -> develop   (reviewed reconciliation)
approved release/YYYY.MM-rcN -> master
master -> develop                  (post-release synchronization)
```

### Production hotfix

```text
master -> hotfix/<version>-...
hotfix -> master
hotfix result -> develop and active release branch where applicable
```

No direct feature/refactor merge into `master`, `rc2`, or a frozen release branch.

## 5) Allowed change types per branch

### `master`

Allowed:

- approved release merges;
- approved minimal hotfixes;
- documentation tied directly to production behavior when reviewed through the same process.

Not allowed:

- incomplete features;
- experiments;
- broad refactors;
- work based on stale branch assumptions.

### `develop`

Allowed:

- Issue-driven features and bug fixes;
- behavior-preserving refactors;
- tests, documentation, dependency maintenance, and research decisions;
- integration work that remains releasable through normal review.

Not allowed:

- untracked work without an Issue;
- unrelated scope bundled into one branch;
- secret/proprietary fixtures.

### `release/*`

Allowed:

- bug/regression fixes required for release;
- release notes/version metadata;
- packaging, smoke, security, and evidence work;
- documentation required for release readiness.

Not allowed:

- new feature scope;
- broad architecture refactors;
- convenience dependency upgrades;
- visual redesign.

Late-scope exception: after feature freeze, a scope-expanding change enters the RC line only when
`implementation_item_triage.md` records the rationale, owner, target RC, test evidence,
rollback/deferral option, and explicit release-owner approval. Manual release evidence still
applies.

### `rc2`

Allowed only for an explicit transition-maintenance decision before retirement. Routine work is not
allowed.

### `hotfix/*`

Allowed:

- minimal production fix;
- required regression test;
- required release/version/documentation evidence.

Not allowed:

- unrelated cleanup;
- features;
- broad dependency changes or refactors.

## 6) Pull requests and merge safety

- Every PR links one primary Issue.
- Every PR explicitly selects the correct base branch; never rely on the GitHub default.
- CI evidence must be terminal for the exact PR head/content tree.
- Behavior changes and structural refactors should be separate PRs.
- A large integration PR must explain why it could not be safely split.
- Release-line PRs must document reconciliation into `develop`.
- Avoid force-push after release evidence/review starts; if unavoidable, invalidate and rerun exact
  head evidence.
- Prefer squash merge for normal Issue slices when repository settings permit it.
- Release/history reconciliation uses the merge method that preserves required evidence and is
  explicitly stated in the release decision.

## 7) Tagging rules

- Tag each approved release candidate on the matching `release/*` branch using an annotated tag:
  `vYYYY.MM-rcN`.
- After production promotion, tag the approved merge commit on `master` as `vYYYY.MM`.
- Do not move or recreate a published tag. Create a new `-rcN` or patch version.
- Hotfix versions must progress monotonically according to the selected release scheme.
- Do not tag `release/2026.06-rc2` as stable until #901 and the final release-owner decision are
  complete.

## 8) Branch lifecycle and housekeeping

Owner: external orchestrator. Operational decisions and the current inventory are recorded in
[#921](https://github.com/hexafe/metroliza/issues/921). The August #960
[execution ledger](../project/branch_cleanup_execution.md) remains historical evidence, not a
current branch count or a mandate to repeat its complete archaeology for each cleanup.

### Create only for an owned outcome

One primary Issue and one coherent result per topic branch/PR. Create the branch when execution
starts, not for every backlog idea. Each PR records its owner, actual base, dependency PRs (or
`none`), live downstream consumers and retirement condition. Do not make a remote branch per
agent, test attempt, review round or checkpoint. Reuse the existing branch for in-scope corrections.

A replacement such as `-v2` requires a recorded reason and predecessor/successor links. Preserve
needed unique work and close the superseded proposal explicitly; do not silently abandon the old
branch or assume the new name contains its history. Research/design proposals end in an accepted
document, a named implementation, or a reasoned rejection with recoverable evidence, not indefinite
competing instructions. Closing a proposal does not mean its implementation was accepted or merged.

### Keep dependent branches explicit

Normal work still targets `develop`. A temporary integration/acceptance stack is an explicit
exception with one delivery owner, a dependency map and a retirement condition. A composed source
is not automatically merged, and a passing source test is not package acceptance.

Before integrating or retiring a parent, check every open PR's head and base, the current delivery
packet and active workflow use. Agree the next base with the affected owner; never silently retarget
an active stack. Update retained branches through normal integration and refresh the affected
exact-head evidence. Do not force-rebase an active executor or use cleanup to change its source.

After a leaf is integrated, its ordinary branch can retire as soon as no live consumer needs it;
it does not need to wait for unrelated features or the entire release. Engineering/acceptance
parents retire only after dependent work is integrated or explicitly preserved and the owner has
released their live names. A historical link by SHA/PR is not by itself an active-name dependency.

### Make retirement part of post-merge closeout

The merging orchestrator owns the retirement decision in the same closeout. Record one of:

- `RETIRED`: actual guarded deletion and post-delete verification recorded;
- `KEEP_ACTIVE`: named downstream PR, executor or workflow plus release condition;
- `KEEP_EVIDENCE`: exact historical use plus verified preservation/next review plan;
- `DELETE_CANDIDATE`: merge disposition known, but one or more deletion checks remain;
- `BLOCKED_TOOLING`: the safe mutation/recovery capability is unavailable; assign an executor and
  retain the exact pending set instead of claiming deletion.

A remaining branch is not a product-merge failure, but it must have an owner and a concrete next
trigger. Do not rewrite application code, restart reviews or add full QA merely to remove a ref.
A proposal may be closed as superseded without merging stale code. Never merge a dependency bump,
prototype, diagnostic experiment or incomplete product PR merely to make the branch list shorter.
Actual required merge and release gates remain unchanged.

### Safe deletion gate

A retirement candidate is not deletion approval. Prepare one finite exact-ref manifest for approval;
one approval may name multiple independently checked entries. Each entry records the full expected
SHA, PR/disposition, retained integration result, dependency check, recovery proof and executor.
Protected/default/release refs and unique unmerged work are excluded from routine batches.

Before deleting an entry:

1. Re-read its current full SHA and PR state. Require no post-merge unreviewed commits. Verify the
   integration result exists in the intended retained branch. For squash/cherry-pick history,
   compare the accepted tree/patch as well as the graph; `git branch --merged` alone is insufficient.
2. Require no open PR using the name as head/base, no active executor/CI use and no other live
   release, workflow, settings or packet dependency. Unknown means retain that entry. Do not modify
   another executor's local branches, worktrees or uncommitted work.
3. In a clean disposable repository, actually fetch the exact commit/tree through a retained
   recovery ref such as `refs/pull/<number>/head`. Alternatively use a separately approved,
   checksummed, restore-tested durable archive. A remembered SHA, API page or local path alone is
   not a backup. Do not create/move archive or release tags implicitly.
4. Use the approved exact-SHA deletion, with an explicit expected-old-value lease. Recheck the
   dependency snapshot immediately before mutation. A moved ref or new consumer cancels that entry,
   not the entire completed batch. No bare name-only deletion, wildcard pruning or `--force`.
5. Verify the ref is absent and retained refs/recovery still match, then record the actual result.
   Recovery is a separate authorized create-ref operation that refuses an already-existing target;
   never overwrite a concurrently recreated branch.

The lease is a compare-and-delete safety check, not permission to rewrite history. Its form is
`--force-with-lease=refs/heads/<branch>:<full-expected-sha>` with one explicit deletion refspec.
See [Git's push contract](https://git-scm.com/docs/git-push). Do not replace this with an unguarded
REST delete when the required lease-capable execution surface is unavailable.

### Prevent accumulation without automatic destruction

Review unresolved post-merge entries during ordinary weekly planning and before release freeze.
This is a small inventory/dependency check, not a recurring code audit or an automation started by
this document. Fourteen days without meaningful activity triggers owner/status review; thirty days
requires an explicit continue, park, supersede or archive decision. Age never authorizes deletion.

Track merged-but-unretired topics and ownerless/stale branches, not a cosmetic global branch limit.
The intended steady state is the justified long-lived refs plus current delivery slices. Start new
slices only with useful ownership; finish or explicitly park existing work first. No separate
remote branches are required for read-only reviewers or mechanical subagent work.

Automatic head deletion may be enabled only by a separate settings decision after recovery,
protected/release refs and active stacks are accounted for. GitHub supports this setting and notes
that branch protection/rulesets can prevent deletion; the toggle is not proof of our stronger
recovery/consumer gate. See [GitHub's automatic-deletion documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-the-automatic-deletion-of-branches).
This policy does not change that setting or install a cleanup workflow.

### Long-lived and historical release refs

Keep `develop` and `master` in their existing roles. Keep an active release/evidence branch while
its cycle is open. Retire `rc2` only through #924 after promotion or explicit abandonment,
reconciliation and preservation of useful references. Equal tips for `rc2` and a release branch
are not sufficient authority to delete either. Default-branch changes, tags and release promotion
remain separate decisions.
