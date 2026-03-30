# Release candidate checklist

Use this checklist as the **primary release gate** for RC readiness, sign-off, promotion, and rollback preparedness.

Authoritative source for branch naming rules: `docs/release_checks/branching_strategy.md`.

## 1) Pre-freeze checks

Complete before announcing code freeze or cutting an RC branch.

- [ ] Scope is locked for the target release; all non-release-critical work is moved out of milestone.
- [ ] Release owner and backup owner are assigned.
- [x] `VersionDate.py` version/build/date values are updated for this RC.
- [ ] `CHANGELOG.md` includes user-facing notes for this RC.
- [ ] `README.md` **Release highlights** reflects the current RC/release line.
- [ ] `python scripts/sync_release_metadata.py --check` passes (VersionDate/README/CHANGELOG are aligned).
- [ ] Open blockers are triaged against the defect criteria in section 6.
- [x] Open implementation-item gate triage is completed in [`implementation_item_triage.md`](./implementation_item_triage.md) (Gate/Owner/Target RC/Rationale filled) before freeze proceeds.

## 2) Documentation readiness

Complete before beginning open testing on an RC build.

- [ ] Public API changes have corresponding docstrings updated. *(Owner: Dev)*
- [ ] Complex logic changes include explanatory inline comments where needed. *(Owner: Dev)*
- [ ] `README.md` install/usage/config sections are validated against current behavior. *(Owner: QA)*
- [ ] `docs/README.md` index is updated for any new or renamed active docs. *(Owner: Release manager)*
- [x] Runbooks/checklists touched by behavior changes are updated in the same PR. *(Owner: Dev/QA)*
- [ ] Stale or outdated comments are removed. *(Owner: Dev)*
- [x] Documentation updates follow source-of-truth and archival requirements in [`docs/documentation_policy.md`](../documentation_policy.md). *(Owner: Release manager)*
- [ ] Final documentation sign-off includes links to evidence (PRs/commits) for all relevant documentation updates. *(Owner: Release manager)*

<a id="open-testing-entry-criteria"></a>

## 3) Open testing entry criteria

Complete before beginning open testing on an RC build.

- [ ] Feature freeze timestamp is recorded in release tracker and announcement thread. *(Owner: Release manager)*
- [ ] Active RC branch name is confirmed and documented (for example `release/2026.03-rc1`). *(Owner: Release engineer)*
- [x] Build identifier for open testing is published (artifact/version/hash) and linked in tracker. *(Owner: Release engineer)*
- [ ] Mandatory CI baseline is completed and linked (build/lint/tests) before open testing starts. *(Owner: Release owner)*
- [ ] Known-issues document link is prepared and shared with open testers. *(Owner: QA/Product)*
- [ ] Bug reporting channel is announced (for example issue board + chat channel) and monitored. *(Owner: Release manager/QA)*

## 4) RC branch creation

Create the RC branch from the approved base commit (typically `main`):

```bash
git checkout main
git pull --ff-only origin main
git checkout -b release/2026.03-rc1
git push -u origin release/2026.03-rc1
```

Alternative (single command if local main is already up to date):

```bash
git checkout -b release/2026.03-rc1 origin/main
git push -u origin release/2026.03-rc1
```

- [ ] RC branch follows naming convention (for example `release/2026.03-rc1`).
- [ ] Branch creation commit SHA and timestamp are recorded in release notes/tracker.

<a id="required-test-suites-and-sign-off-owners"></a>

## 5) Required test suites and sign-off owners

Run and record all required checks from the RC branch:

```bash
python -m compileall .
ruff check .
PYTHONPATH=. python -m pytest tests -q
```

- [ ] Compile check passed. *(Owner: Dev)*
- [ ] Lint check passed. *(Owner: Dev)*
- [ ] Unit test suite passed. *(Owner: QA/Dev)*

### Required packaging validation (release-blocking)

Build commands:

```bash
pyinstaller packaging/metroliza_onefile.spec
python -m maturin build --manifest-path modules/native/cmm_parser/Cargo.toml --release
```

```powershell
./packaging/build_nuitka.ps1
```

- [ ] PyInstaller output exists under `dist/` and launches. *(Owner: Release engineer/QA)*
- [ ] Nuitka output executable exists and launches on a clean/sandbox target environment. *(Owner: Release engineer/QA)*
- [ ] Native wheel build succeeds for release target(s), and `_metroliza_cmm_native` import smoke check passes. *(Owner: Release engineer/QA)*
- [ ] Pure-Python parser fallback works when native module is intentionally unavailable (`METROLIZA_CMM_PARSER_BACKEND=python`). *(Owner: QA)*
- [ ] Basic startup flow works (open app, load a representative input, generate an export). *(Owner: QA)*
- [ ] Produced artifacts are named/versioned as expected for RC distribution. *(Owner: Release manager)*

- [ ] GitHub CI checks for the RC branch/PR are green before merge/tag. *(Owner: Release owner)*
- [ ] Coverage visibility output from `unit-tests` is reviewed (job log summary and `unit-test-coverage` artifact `coverage.xml`) as RC confidence evidence; this is informational and not a blocking PR check. *(Owner: Release owner/QA)*
- [ ] Any optional manual smoke evidence (if executed) is linked from release notes or tracker (`packaging-smoke`, `google-conversion-smoke`). *(Owner: Release owner)*

Optional CI/manual smoke commands (non-blocking for regular PRs/pushes):

```bash
# Packaging smoke build
# Trigger CI workflow_dispatch with input: run_packaging_smoke=1

# Google conversion smoke
# Trigger CI workflow_dispatch with input: run_google_conversion_smoke=1
```

> For solo-maintainer flow, treat GitHub CI status as the primary release gate before merge/tag.

<a id="defect-triage-criteria"></a>

## 6) Defect triage criteria (must-fix vs defer)

Use the following policy for RC exit triage:

### Must-fix before release (Go blocked)

- Data loss/corruption, crash on core user flow, or export integrity failure.
- Security/privacy issue with no acceptable mitigation.
- Regression in release-gated workflows without acceptable workaround.
- Build/package defect that prevents launch, install, or expected startup on supported targets.

### Can defer (Go may proceed with explicit approval)

- Cosmetic/UI issues with low user impact.
- Non-default/edge-case defects with documented workaround.
- Low-severity defects not affecting release-gated workflows.

- [x] Every open RC defect is labeled `must-fix` or `defer` with rationale and owner.
- [x] Deferred defects are captured in the next-release backlog/milestone.

<a id="open-testing-exit-criteria"></a>

## 7) Open testing exit criteria

Complete before declaring open testing closed and moving to final Go/No-Go decision.

- [ ] Blocker count is `0` for current RC candidate. *(Owner: Release manager/QA)*
- [ ] Deferred defect list is approved and captured with owner + milestone. *(Owner: Product/Release manager)*
- [ ] Required sign-off owners have all recorded completion in the release tracker. *(Owner: Release manager)*

## 8) Merge-to-main and tagging criteria

Only promote RC when all gates are green and approvals are complete.

- [ ] All required checks in the [Required test suites and sign-off owners](#required-test-suites-and-sign-off-owners) section are complete and linked.
- [ ] No unresolved `must-fix` defects remain.
- [ ] Release owner sign-off recorded.
- [ ] RC branch merged to `main` with approved strategy.
- [ ] Release tag created from the merge commit (example: `vYYYY.MM` (for example `v2026.03`)).
- [ ] Tag is pushed and visible on remote.

Suggested commands:

```bash
git checkout main
git pull --ff-only origin main
git tag -a v2026.03 <merge-commit-sha> -m "Release v2026.03"
git push origin v2026.03
```

## 9) Rollback plan and communication checklist

Prepare before release announcement; execute if post-release issues require rollback.

### Rollback readiness

- [ ] Previous stable tag/version is identified and verified runnable.
- [ ] Owner for rollback execution is assigned.
- [ ] Rollback method is selected (revert commit(s), re-cut artifact from prior tag, or re-point distribution channel).

### Communication checklist

- [ ] Internal stakeholders notified of release decision (Go/No-Go).
- [ ] Support/operations channel receives known issues + workarounds.
- [ ] If rollback occurs, incident message includes impact, affected versions, mitigation, and ETA for follow-up RC.
- [ ] Post-release summary posted with final outcome and links to evidence.

## RC decision record

| Item | Value |
| --- | --- |
| RC owner | Solo maintainer |
| QA owner | N/A (solo-maintainer flow) |
| Sign-off date | 2026-03-05 (last updated) |
| Decision | Pending CI Go/No-Go |
| Release tag | `v2026.03-rc1` (not cut) |
| Notes | Solo-maintainer release flow: rely on GitHub CI green status before merge/tag; optional manual smoke evidence can be linked from CI/ticket artifacts when needed. |
