# Branching strategy

This document defines the lightweight branching model used for Metroliza release work.

Authoritative source for branch naming rules: `docs/release_checks/branching_strategy.md`.

## 1) Branch purposes

- `master`: current production-ready branch; only reviewed, releasable code is merged here.
  Older examples or generic release tooling may say `main`; substitute `master` in this
  repository unless the default branch is renamed.
- `develop` (optional): integration branch for active feature work before release cut.
- `release/*`: stabilization branches created for a specific release candidate cycle.
- `hotfix/*`: urgent production fix branches cut from `master` for post-release defects.

## 2) Naming conventions

- Release candidate branches use: `release/YYYY.MM-rcN`
  - Example: `release/2026.05-rc1`
- Hotfix branches use: `hotfix/x.y.z+1`
  - Example: `hotfix/2026.02.0+1`

Canonical RC branch creation commands:

```bash
git checkout master
git pull --ff-only origin master
git checkout -b release/2026.05-rc1
git push -u origin release/2026.05-rc1
```

## 3) Merge directions

- Feature work merges into `develop` when it exists; otherwise directly into `master` for small repositories.
- Release candidate branches are cut from `develop` (or `master` if no `develop`) and merge into `master` once approved.
- After a release merge, sync `master` back into `develop` to avoid drift.
- Hotfix branches merge into `master` first, then are back-merged into `develop` (if used).

## 4) Allowed change types per branch

- `master`:
  - Allowed: release-ready features, approved fixes, documentation updates tied to shipped behavior.
  - Not allowed: incomplete features, experimental spikes.
- `develop`:
  - Allowed: feature development, refactors, non-breaking docs/test updates.
  - Not allowed: unreviewed emergency changes intended only for production hotfixing.
- `release/*`:
  - Allowed: bug fixes, regression fixes, release notes/version metadata, docs needed for release readiness.
  - Not allowed: new features, large refactors, scope-expanding changes.
- `hotfix/*`:
  - Allowed: minimal-risk production fixes and required tests/docs for that fix.
  - Not allowed: unrelated cleanup, feature development, broad dependency upgrades.

## 5) Tagging rules (RC and final)

- Tag each release candidate on the matching `release/*` branch using annotated tags: `vYYYY.MM-rcN` (example: `v2026.05-rc1`).
- After promoting to production, tag the merge commit on `master` as `vYYYY.MM` (example: `v2026.05`).
- Do not retag moved commits; create a new `-rcN` tag for any additional RC iteration.
- Hotfix releases should follow your monthly release policy while preserving monotonic version progression.
