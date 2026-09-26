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

The intended steady state is deliberately small:

```text
master                 # production/history anchor (rename to main is a separate repository decision)
develop                # canonical integration branch
release/YYYY.MM-rcN    # only while that release/evidence cycle is active
<active PR heads>      # feature/fix/docs/test/chore/etc. currently being reviewed or integrated
```

A remote branch is a **temporary execution ref, not an archive or evidence store**. Durable evidence
lives in the linked Issue/PR, commit/tree SHA, CI run, retained artifact, and release tag when
applicable.

### Create fewer branches

- Create one branch for one primary Issue/PR when implementation actually starts.
- Do not create remote branches for backlog ideas, read-only reviewers, agents, test attempts,
  review rounds, checkpoints, or "maybe useful later" snapshots.
- Keep in-scope corrections on the existing branch/PR.
- Research/design work uses an Issue/comment or a documentation PR. It gets a dedicated remote
  branch only when it contains a concrete mergeable deliverable.
- A replacement `-v2` branch is exceptional: record why the first branch cannot continue and close
  or retire the predecessor rather than keeping competing versions indefinitely.

### Delete as part of merge closeout

The merging orchestrator owns branch retirement in the same closeout as the merge.

Default rule:

> **Merged PR -> delete its source branch immediately.**

Keep the branch only when a **named live dependency** still requires that ref name, such as an open
PR based on it, an active release/integration stack, or a currently running executor/workflow that
cannot yet move. The keep decision must name the consumer and the exact retirement trigger.

A historical link, old CI run, benchmark, audit, review, or useful commit is **not** a reason to keep
the branch. Those remain recoverable through the PR/commit history.

Closed or superseded unmerged PRs also retire once unique useful work is either integrated elsewhere
or deliberately preserved in a durable PR/commit/document. Do not merge stale code merely to make
the branch list shorter.

### Temporary integration stacks are exceptions

Normal work starts from and targets `develop`. A delivery may temporarily use an integration branch
and, when genuinely required, one acceptance/package branch. Such a stack must have:

- one delivery owner;
- an explicit dependency map;
- a named final destination;
- a retirement trigger.

Do not grow a tree of per-worker/per-test integration branches. When leaf work is integrated into the
retained integration branch, retire the leaf branch. When the delivery is reconciled into its final
branch, retire the integration/acceptance refs.

### Cleanup gate

Before deleting a branch:

1. re-read its current SHA and PR state;
2. confirm no open PR uses it as head/base and no active workflow/executor needs the ref name;
3. confirm accepted work is present in the retained destination or intentionally preserved through
   the PR/commit history;
4. delete only the exact expected ref/SHA, never by wildcard or blind force;
5. verify the ref is absent and record the cleanup result in #921 when the operation is part of a
   batch.

A branch with no open PR and no explicit release/integration role is a cleanup candidate immediately.
Housekeeping should happen continuously after merges, not as a rare repository-wide archaeology
project. There is no cosmetic numeric branch cap, but the normal count should be approximately the
long-lived refs plus genuinely active PR heads.

### Long-lived and historical release refs

Keep `develop` and `master` in their current roles. Keep an active `release/*` branch only while
its release/evidence cycle is open. Prefer immutable tags for historical release points rather than
keeping old release branches indefinitely. Retire the historical `rc2` only through its recorded
release-transition decision; default-branch renaming and release promotion remain separate actions.

