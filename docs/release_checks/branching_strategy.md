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

## 1) Branch purposes

### `master`

Production-ready branch after an approved release promotion. Only reviewed, release-owner-approved
candidate merges and minimal production hotfixes belong here.

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

## 8) Branch cleanup

- Delete merged short-lived Issue branches after the PR and evidence are complete.
- Keep active release branches only while their release/evidence cycle is open.
- Preserve historical commits through merged PRs/tags rather than indefinite abandoned branches.
- Retire `rc2` only after the current candidate is promoted or explicitly abandoned, `develop` is
  synchronized, useful references are preserved, and a dedicated cleanup decision is recorded.
- Changing the GitHub default branch is a repository-setting decision and must not be conflated with
  force-moving `master` or release promotion.
