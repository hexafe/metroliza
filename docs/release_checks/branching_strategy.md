# Branching strategy

This document defines the lightweight branching model used for Metroliza development and release
work.

Authoritative source for branch naming and merge rules:
`docs/release_checks/branching_strategy.md`.

## 0) Transitional repository state — 2026-08-22

The intended model says `master` is production-ready, but the current branch topology does not yet
match that model:

- `master` points to `ab26258e72d285c3917a595515798da185800373` from 2026-03-30.
- `rc2` points to `202690eb21087314a3c8000aa3ebdb58a1a09c1b` from 2026-07-17.
- At the audit snapshot, `rc2` is 278 commits ahead of `master` and zero commits behind it.
- PR #895 records successful exact-head CI for the earlier RC2 head
  `ce7556098626f93d3ade95abd49ede00be341611` and was intentionally closed without promotion.
- The current `rc2` head is one large product-wide commit after that validated head and has not yet
  been accepted as a releasable replacement through the current process.

Temporary rules until #900 closes:

- current documentation, validation fixes, and narrowly approved work branch from `rc2`;
- pull requests for that work target `rc2`;
- stale `master` receives no feature, refactor, or documentation-development merges;
- no new release branch is cut from stale `master`;
- no force-push or history rewrite is used to reconcile `rc2` and `master`;
- promotion requires exact-head automated evidence (#900) and applicable manual release evidence
  (#901);
- the final decision must name the canonical development base and update this section.

These temporary rules describe repository reality; they do not declare `rc2` released.

## 1) Branch purposes

- `master`: current production-ready branch after an approved release promotion. Only reviewed,
  releasable code is merged here. Older examples or generic release tooling may say `main`;
  substitute `master` in this repository unless the default branch is formally renamed.
- `develop` (optional): integration branch for active feature/refactor work when the volume of
  concurrent work justifies it.
- `release/*`: stabilization branches created for a specific release candidate cycle.
- `hotfix/*`: urgent production-fix branches cut from `master` for post-release defects.
- Issue branches: short-lived branches for one Issue or one reviewable slice of an Issue.

The long-term choice between direct Issue branches and an optional `develop` branch is decided by
#900 after the current RC split is resolved.

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
docs/899-project-governance-reset
fix/900-parser-preflight-regression
refactor/903-export-run-stages
security/906-bandit-renewal
```

Keep one primary Issue per branch/PR. Split broad Issues into several independently reviewable
branches instead of one product-wide change set.

## 3) Release and hotfix naming

- Release candidate branches: `release/YYYY.MM-rcN`
  - Example: `release/2026.09-rc1`
- Hotfix branches: `hotfix/<version>-<description>`
  - Example: `hotfix/2026.09.1-startup-fix`

Canonical release branch creation after the current transition is resolved:

```bash
git checkout <approved-development-base>
git pull --ff-only origin <approved-development-base>
git checkout -b release/2026.09-rc1
git push -u origin release/2026.09-rc1
```

Do not copy the historical ad-hoc name `rc2` into future release cycles.

## 4) Merge directions

Normal intended flow:

- Issue branches merge into `develop` when it exists; otherwise into the approved development base.
- Release candidate branches are cut from the approved development base and merge into `master`
  only after automated and manual gates pass.
- After release promotion, sync `master` back into `develop`/the approved development base to avoid
  drift.
- Hotfix branches merge into `master` first, then back into the development base.

Current transition:

- `docs/project-governance-reset` and other approved current work target `rc2` until #900 decides
  the permanent direction.
- Nothing in this document authorizes merging `rc2` into `master` before the release decision.

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

### Development base (`develop` or approved equivalent)

Allowed:

- Issue-driven features;
- behavior-preserving refactors;
- tests, documentation, dependency maintenance, and research decisions;
- integration work that remains releasable through normal review.

Not allowed:

- untracked work without an Issue;
- unrelated scope bundled into one branch;
- secret/proprietary fixtures.

### `release/*`

Allowed:

- bug/regression fixes;
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
- PRs target the branch appropriate to the current repository/release state.
- CI evidence must be terminal for the exact PR head.
- Behavior changes and structural refactors should be separate PRs.
- A large integration PR must explain why it could not be safely split.
- Avoid force-push after release evidence/review starts; if unavoidable, invalidate and rerun exact
  head evidence.
- Prefer squash merge for normal Issue slices when repository settings permit it.
- Release/history reconciliation uses the merge method that preserves required evidence and is
  explicitly stated in the release decision.

## 7) Tagging rules

- Tag each approved release candidate on the matching `release/*` branch using an annotated tag:
  `vYYYY.MM-rcN`.
- After production promotion, tag the merge commit on `master` as `vYYYY.MM`.
- Do not move or recreate a published tag. Create a new `-rcN` or patch version.
- Hotfix versions must progress monotonically according to the selected release scheme.
- Do not tag the current `rc2` head as a stable release until #900 and #901 gates are satisfied.

## 8) Branch cleanup

- Delete merged short-lived Issue branches after the PR and evidence are complete.
- Keep active release branches only while their release/evidence cycle is open.
- Preserve historical commits through merged PRs/tags rather than indefinite abandoned branches.
- Never delete `rc2` or change the default branch as part of routine cleanup; that action belongs to
  the explicit #900 transition decision.
