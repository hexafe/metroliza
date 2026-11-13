# Branching strategy

This document defines the lightweight branching model used for Metroliza release work.

Authoritative source for branch naming rules: `docs/release_checks/branching_strategy.md`.

## 1) Branch purposes

- `main`: production-ready branch; only reviewed, releasable code is merged here.
- `dev`: canonical integration branch for normal Issue-driven work.
- `rc`: frozen active candidate; approved fixes and evidence only, with release-owner gates.
- `hotfix/*`: urgent production fix branches cut from `main` for post-release defects.

## 2) Naming conventions

- The active candidate uses the persistent `rc` branch. Candidate versions and immutable tags
  retain `YYYY.MM-rcN` numbering; they are not branch names.
- Hotfix branches use: `hotfix/x.y.z+1`
  - Example: `hotfix/2026.02.0+1`

At an explicitly approved feature-freeze point, reconcile the selected exact `dev` source into
`rc` through a reviewed, history-preserving PR. Do not reset or recreate the long-lived branch.
The 2026-11-13 #960 migration preserves the existing frozen candidate separately from `main`;
renaming or synchronizing governance does not approve product promotion.

## 3) Merge directions

- Normal Issue work starts from and targets `dev`; GitHub default selection is not base authority.
- The selected `dev` source enters `rc` only at an approved freeze; `rc` merges into `main` only after release sign-off.
- After a release merge, sync `main` back into `dev` to avoid drift.
- Hotfix branches merge into `main` first, then are back-merged into `dev`.

## 4) Allowed change types per branch

- `main`:
  - Allowed: release-ready features, approved fixes, documentation updates tied to shipped behavior.
  - Not allowed: incomplete features, experimental spikes.
- `dev`:
  - Allowed: feature development, refactors, non-breaking docs/test updates.
  - Not allowed: unreviewed emergency changes intended only for production hotfixing.
- `rc`:
  - Allowed: bug fixes, regression fixes, release notes/version metadata, docs needed for release readiness.
  - Not allowed: new features, large refactors, scope-expanding changes.
- `hotfix/*`:
  - Allowed: minimal-risk production fixes and required tests/docs for that fix.
  - Not allowed: unrelated cleanup, feature development, broad dependency upgrades.

## 5) Tagging rules (RC and final)

- Tag each release candidate on the matching `rc` branch using annotated tags: `vYYYY.MM-rcN` (example: `v2026.03-rc1`).
- After promoting to production, tag the merge commit on `main` as `vYYYY.MM` (example: `v2026.03`).
- Do not retag moved commits; create a new `-rcN` tag for any additional RC iteration.
- Hotfix releases should follow your monthly release policy while preserving monotonic version progression.
