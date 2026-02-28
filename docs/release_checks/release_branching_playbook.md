# Release branching playbook (solo maintainer)

This guide explains how to combine multiple `feature/*` branches into one release candidate (RC) branch without confusion.

## TL;DR flow

1. Create `release/<version>-rc1` from `main` to start the release cycle.
2. Build each planned change on its own `feature/*` branch.
3. Merge only release-approved features into the active release branch.
4. Freeze feature scope, then build EXE from the release branch and deploy internally.
5. During testing, keep working only on release fixes/improvements inside the release branch (`rc2`, `rc3`, ...).
6. After test deployment is green and sign-off is complete, merge release into `main` and tag final release.

---

## Branch roles

- `feature/<name>`: one isolated feature/fix.
- `main`: stable line; updated only by completed releases/hotfixes.
- `release/<version>-rcN`: active release integration + stabilization branch used for packaging and internal testing.
- `hotfix/<name>`: urgent production patch after a release.

## Important rule

Do **not** rename a feature branch into a release branch.

Instead:
- Keep feature branches short-lived.
- Cut the release branch first from `main`.
- Merge selected/approved features into that release branch only.
- Keep `main` untouched until release sign-off.

This keeps `main` maximally stable during the full RC cycle.

---

## How to combine multiple features into one RC

Assume you finished:
- `feature/csv-presets-improvement`
- `feature/google-export-warning-copy`
- `feature/export-speed-tuning`

### 1) Cut release branch first

```bash
git checkout main
git pull
git checkout -b release/2026.03-rc1
```

This branch is now the release integration target; `main` stays stable.

### 2) Merge release-approved features into release branch

```bash
git checkout release/2026.03-rc1
git merge --no-ff feature/csv-presets-improvement
git merge --no-ff feature/google-export-warning-copy
git merge --no-ff feature/export-speed-tuning
```

Run baseline checks and commit release-doc updates on the release branch.

### 3) Freeze scope

On `release/2026.03-rc1`, allow only:
- bug fixes,
- release metadata/docs/checklist updates,
- packaging fixes.

No new features during RC.

### 4) Build and deploy RC

Use the packaging/checklist flow in `release_candidate_checklist.md`.

### 5) If internal testing finds issues

Fix directly on RC:

```bash
git checkout release/2026.03-rc1
# apply fix
git commit -m "Fix: <issue>"
git tag v2026.03-rc2
```

Deploy rc2 and repeat until stable.

### 6) Finalize release

```bash
git checkout main
git merge --no-ff release/2026.03-rc1
git tag v2026.03
```

Then close/delete RC branch.

---

## If a new feature becomes ready during RC testing

Do not add it automatically to the current RC. Pick one of these:

- **Safe choice (recommended):** defer to next release branch.
- **If absolutely required for this release:** merge it into the active release branch and restart full RC validation from that point.

This protects stability by treating any late feature as a new release-scope decision.

---

## Suggested naming convention

- RC branch: `release/YYYY.MM-rcN` (example: `release/2026.03-rc1`)
- RC tag: `vYYYY.MM-rcN` (example: `v2026.03-rc2`)
- Final tag: `vYYYY.MM` (example: `v2026.03`)

You can use semantic versioning instead (`1.8.0-rc1`) if preferred.

---

## Release checklist linkage

Use this playbook together with:

- `docs/release_checks/release_candidate_checklist.md`
- `docs/google_conversion_smoke_runbook.md`
- `docs/release_checks/google_conversion_smoke.md`

These remain the operational source for validation evidence and sign-off.
