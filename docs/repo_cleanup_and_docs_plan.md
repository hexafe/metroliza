# Repository cleanup + documentation organization plan (beginner-friendly)

This plan turns our discussion into a practical, repeatable workflow for a solo maintainer shipping internal release candidates (`.exe`) before merging to `main`.

## 0) Outcome we want

By the end of this cleanup pass:

- release work is predictable (`feature/*` -> `release/<version>-rcN` -> `main`),
- docs are easy to find (less root clutter, clear ownership),
- newcomer instructions are simple and step-by-step,
- release-candidate sign-off uses one clear checklist.

---

## 1) Branching model and release flow (keep this stable)

Use these branch types only:

- `feature/<short-name>` for isolated implementation work.
- `release/<version>-rcN` for release integration, stabilization, and internal deployment.
- `hotfix/<short-name>` for urgent production fixes.
- `main` as the releasable line.

### Beginner flow for combining multiple features into one RC

1. Cut `release/<version>-rc1` from current stable `main`.
2. Implement each planned change on separate `feature/*` branches.
3. Merge only approved features into the active release branch.
4. Freeze features and build/deploy the `.exe` from the release branch.
5. During test period, commit only release fixes/improvements on the release branch; retag (`rc2`, `rc3`) as needed.
6. Merge release branch back to `main` only after internal testing is green.

Reference: `docs/release_checks/release_branching_playbook.md`.

---

## 2) Documentation structure (target state)

Keep top-level docs minimal:

- `README.md` (product intro + quickstart)
- `CHANGELOG.md` (user-facing release notes)
- `CONTRIBUTING.md` (developer workflow)

Move planning and operational docs under `docs/`:

- `docs/release_checks/` -> RC checklist + smoke/runbooks
- `docs/planning/` -> active plans (implementation, migration, roadmap)
- `docs/archive/YYYY/` -> completed/superseded plans

### Proposed follow-up file moves (small, safe PR)

- `IMPLEMENTATION_PLAN.md` -> `docs/planning/IMPLEMENTATION_PLAN.md`
- `GOOGLE_SHEETS_MIGRATION_PLAN.md` -> `docs/planning/GOOGLE_SHEETS_MIGRATION_PLAN.md`
- `TODO.md` -> `docs/planning/TODO.md`

After moving, leave short compatibility references (or update links everywhere in one PR).

---

## 3) Documentation lifecycle rules (simple governance)

For every `.md` file, define:

- **Owner**: who keeps it fresh (you, as maintainer).
- **Audience**: users vs contributors vs release operators.
- **Update trigger**: what event requires an edit (feature release, process change, etc.).

### Practical rules

1. No new root `.md` files unless they are core (`README`, `CHANGELOG`, `CONTRIBUTING`).
2. Every new process doc must be linked from at least one index page.
3. Mark stale docs with an explicit status line (`Status: active / archived`).
4. Archive instead of deleting historical decisions.

---

## 4) Beginner-friendly documentation improvements

Create one new getting-started operator guide:

- `docs/release_checks/release_playbook_beginner.md`

It should include:

1. exact git commands for feature -> main -> release branch,
2. how to build and sanity-check `.exe`,
3. where to record RC test results,
4. how to decide Go/No-Go,
5. what to do if a late feature appears during RC.

Keep this guide procedural and short; link to advanced docs for details.

---

## 5) RC checklist hardening

Keep `docs/release_checks/release_candidate_checklist.md` as single RC source of truth and ensure it includes:

- metadata sync (`VersionDate.py`, `README`, `CHANGELOG`),
- baseline quality checks,
- Google conversion smoke policy/evidence location,
- packaging checks for executable outputs,
- final sign-off table.

Use one PR per RC docs update so sign-off evidence is easy to audit.

---

## 6) Suggested execution plan (4 small PRs)

### PR1 - Documentation index + links
- Add this file.
- Add links from `README.md` and `CONTRIBUTING.md`.

### PR2 - Move planning docs under `docs/planning/`
- Relocate root plan/todo docs.
- Update all internal links in one pass.

### PR3 - Beginner release operator playbook
- Add `release_playbook_beginner.md` with command-by-command flow.

### PR4 - Archive/clean stale docs
- Move outdated docs to `docs/archive/<year>/`.
- Keep only active docs in root + clear cross-links.

---

## 7) Definition of done for cleanup

Cleanup is complete when:

- branch/release process is documented and followed consistently,
- root markdown files are limited to core project docs,
- all planning docs live in `docs/planning/` (or are archived),
- beginner can perform RC cycle from docs without external help.
