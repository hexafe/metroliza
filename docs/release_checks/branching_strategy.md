# Branching strategy

This document defines the lightweight branching model used for Metroliza release work.

Authoritative source for branch naming rules: `docs/release_checks/branching_strategy.md`.

## 1) Branch purposes

- `main`: production-ready branch; only reviewed, releasable code is merged here.
- `develop` (optional): integration branch for active feature work before release cut.
- `release/*`: stabilization branches created for a specific release candidate cycle.
- `hotfix/*`: urgent production fix branches cut from `main` for post-release defects.

## 2) Naming conventions

- Release candidate branches use: `release/YYYY.MM-rcN`
  - Example: `release/2026.03-rc1`
- Hotfix branches use: `hotfix/x.y.z+1`
  - Example: `hotfix/2026.02.0+1`

Canonical RC branch creation commands:

```bash
git checkout main
git pull --ff-only origin main
git checkout -b release/2026.03-rc1
git push -u origin release/2026.03-rc1
```

## 3) Merge directions

- Feature work merges into `develop` when it exists; otherwise directly into `main` for small repositories.
- Release candidate branches are cut from `develop` (or `main` if no `develop`) and merge into `main` once approved.
- After a release merge, sync `main` back into `develop` to avoid drift.
- Hotfix branches merge into `main` first, then are back-merged into `develop` (if used).

## 4) Allowed change types per branch

- `main`:
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

- Tag each release candidate on the matching `release/*` branch using annotated tags: `vYYYY.MM-rcN` (example: `v2026.03-rc1`).
- After promoting to production, tag the merge commit on `main` as `vYYYY.MM` (example: `v2026.03`).
- Do not retag moved commits; create a new `-rcN` tag for any additional RC iteration.
- Hotfix releases should follow your monthly release policy while preserving monotonic version progression.
