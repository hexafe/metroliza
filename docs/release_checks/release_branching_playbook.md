# Release branching playbook (solo maintainer)

This **tutorial-only** guide shows one practical way to combine multiple `feature/*` branches into one release candidate (RC) branch without confusion.

For canonical policy (branch naming, merge rules, and tagging rules), always follow:

- `docs/release_checks/branching_strategy.md`
- `docs/release_checks/release_candidate_checklist.md`

## TL;DR flow

1. Integrate each planned change into `dev` through its reviewed `feature/*` or `fix/*` PR.
2. At the approved feature-freeze point, prepare the approved `dev` scope on existing `rc` through a reviewed release PR.
3. After freeze, use short-lived release-fix branches that target the active release branch and
   reconcile each accepted fix into `dev`.
4. Build the EXE from the release branch and deploy it internally.
5. Repeat release-fix and validation cycles on the same candidate branch or a successor candidate identity on the same `rc`.
6. After validation and sign-off are complete, merge the approved release into `main` and tag
   the final release.

---

## Branch roles

- `feature/<name>`: one isolated feature/fix.
- `dev`: canonical integration line and source for the approved `rc` scope at feature freeze.
- `main`: stable line; updated only by completed releases/hotfixes.
- `rc`: active release integration + stabilization branch used for packaging and internal testing.
- `hotfix/<name>`: urgent production patch after a release.

## Important rule

Do **not** rename a feature branch into a release branch.

Instead:
- Keep feature branches short-lived.
- Merge approved feature branches into `dev` through reviewed PRs before feature freeze.
- Prepare the approved scope on existing `rc` from `dev` at the approved feature-freeze point.
- After freeze, target only approved release-fix branches at the release branch and reconcile each
  accepted fix into `dev`.
- Keep `main` untouched until release sign-off.

This keeps `main` maximally stable during the full RC cycle.

---

## How to combine multiple features into one RC

Assume you finished:
- `feature/csv-presets-improvement`
- `feature/google-export-warning-copy`
- `feature/export-speed-tuning`

### 1) Integrate the approved feature set into `dev`

Review and merge each approved feature PR into `dev`. Do not merge the feature branches
directly into the frozen release line. When the approved scope is integrated:

```bash
git checkout dev
git pull --ff-only origin dev
```

### 2) Prepare the candidate line at feature freeze

```bash
# Prepare the approved dev scope on existing rc through a reviewed release PR.
git checkout rc
git pull --ff-only origin rc
```

This branch is now the frozen release target; `main` stays stable and `dev` continues as the
normal integration line.

### 3) Freeze scope

On `rc`, allow only:
- bug fixes,
- release metadata/docs/checklist updates,
- packaging fixes.

No new features during RC.

### 4) Build and deploy RC

Use the packaging/checklist flow in `release_candidate_checklist.md`.

### 5) If internal testing finds issues

Create a short-lived fix branch from the current RC:

```bash
git checkout rc
git pull --ff-only origin rc
git checkout -b fix/<issue>-release-blocker
# apply fix
git commit -m "Fix: <issue>"
git push -u origin fix/<issue>-release-blocker
```

Open a reviewed PR targeting `rc`. After it is accepted, reconcile the fix into
`dev` through a separate reviewed PR, then deploy and repeat validation until stable.

### 6) Finalize release

```bash
git checkout main
git merge --no-ff rc
git tag -a v2026.05 -m "Release v2026.05"
```

Then reconcile the production result into `dev` through a reviewed PR. Keep `rc` as the candidate
line; preserve completed candidate evidence with immutable tags and exact source/artifact hashes.

---

## If a new feature becomes ready during RC testing

Do not add it automatically to the current RC. Pick one of these:

- **Safe choice (recommended):** defer to next release branch.
- **If absolutely required for this release:** merge it into the active release branch and restart full RC validation from that point.

This protects stability by treating any late feature as a new release-scope decision.

---

## Suggested naming convention

- RC branch: `rc` (reused across candidate iterations)
- RC tag: `vYYYY.MM-rcN` (example: `v2026.05-rc2`)
- Final tag: `vYYYY.MM` (example: `v2026.05`)

Use the monthly release format for metadata and tags; the candidate branch remains `rc`.

---

## Release checklist linkage

Use this playbook as companion guidance together with:

- `docs/release_checks/release_candidate_checklist.md`
- `docs/google_conversion_smoke_runbook.md`
- `docs/release_checks/google_conversion_smoke.md`

These remain the operational source for validation evidence and sign-off.
