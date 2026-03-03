# Release candidate checklist

Use this checklist as the **primary release gate** for RC readiness, sign-off, promotion, and rollback preparedness.

Authoritative source for branch naming rules: `docs/release_checks/branching_strategy.md`.

## 1) Pre-freeze checks

Complete before announcing code freeze or cutting an RC branch.

- [ ] Scope is locked for the target release; all non-release-critical work is moved out of milestone.
- [ ] Release owner and backup owner are assigned.
- [ ] `VersionDate.py` version/build/date values are updated for this RC.
- [ ] `CHANGELOG.md` includes user-facing notes for this RC.
- [ ] `README.md` **Release highlights** reflects the current RC/release line.
- [ ] `python scripts/sync_release_metadata.py --check` passes (VersionDate/README/CHANGELOG are aligned).
- [ ] Open blockers are triaged against the defect criteria in section 5.
- [ ] Open implementation-item gate triage is completed in [`implementation_item_triage.md`](./implementation_item_triage.md) (Gate/Owner/Target RC/Rationale filled) before freeze proceeds.

<a id="open-testing-entry-criteria"></a>

## 2) Open testing entry criteria

Complete before beginning open testing on an RC build.

- [ ] Feature freeze timestamp is recorded in release tracker and announcement thread. *(Owner: Release manager)*
- [ ] Active RC branch name is confirmed and documented (for example `release/2026.03-rc1`). *(Owner: Release engineer)*
- [ ] Build identifier for open testing is published (artifact/version/hash) and linked in tracker. *(Owner: Release engineer)*
- [ ] Mandatory smoke baseline is completed and linked to evidence before open testing starts. *(Owner: QA)*
- [ ] Known-issues document link is prepared and shared with open testers. *(Owner: QA/Product)*
- [ ] Bug reporting channel is announced (for example issue board + chat channel) and monitored. *(Owner: Release manager/QA)*

## 3) RC branch creation

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

## 4) Required test suites and sign-off owners

Run and record all required checks from the RC branch:

```bash
python -m compileall .
ruff check .
PYTHONPATH=. python -m unittest discover -s tests -v
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
python -m nuitka metroliza.py `
  --onefile `
  --windows-console-mode=disable `
  --enable-plugin=pyqt6 `
  --windows-icon-from-ico=packaging/metroliza_icon2.ico `
  --output-filename=metroliza.exe `
  --assume-yes-for-downloads `
  --remove-output `
  --jobs=%NUMBER_OF_PROCESSORS%
```

- [ ] PyInstaller output exists under `dist/` and launches. *(Owner: Release engineer/QA)*
- [ ] Nuitka output executable exists and launches on a clean/sandbox target environment. *(Owner: Release engineer/QA)*
- [ ] Native wheel build succeeds for release target(s), and `_metroliza_cmm_native` import smoke check passes. *(Owner: Release engineer/QA)*
- [ ] Pure-Python parser fallback works when native module is intentionally unavailable (`METROLIZA_CMM_PARSER_BACKEND=python`). *(Owner: QA)*
- [ ] Basic startup flow works (open app, load a representative input, generate an export). *(Owner: QA)*
- [ ] Produced artifacts are named/versioned as expected for RC distribution. *(Owner: Release manager)*

- [ ] Google conversion smoke procedure executed per runbook: [`docs/google_conversion_smoke_runbook.md`](../google_conversion_smoke_runbook.md). *(Owner: QA)*
- [ ] Smoke evidence and outcomes recorded in: [`docs/release_checks/google_conversion_smoke.md`](google_conversion_smoke.md). *(Owner: QA/Release manager)*
- [ ] Open-testing promotion is blocked unless smoke evidence exists for the **current build identity** (branch + commit SHA + artifact/build ID) in: [`docs/release_checks/google_conversion_smoke.md`](google_conversion_smoke.md). *(Owner: Release manager)*

> Do not duplicate smoke steps in this checklist. Follow the linked runbook and evidence template as the source of procedure detail.

<a id="defect-triage-criteria"></a>

## 5) Defect triage criteria (must-fix vs defer)

Use the following policy for RC exit triage:

### Must-fix before release (Go blocked)

- Data loss/corruption, crash on core user flow, or export integrity failure.
- Security/privacy issue with no acceptable mitigation.
- Regression in release-gated workflows (including Google conversion smoke failures) without acceptable workaround.
- Build/package defect that prevents launch, install, or expected startup on supported targets.

### Can defer (Go may proceed with explicit approval)

- Cosmetic/UI issues with low user impact.
- Non-default/edge-case defects with documented workaround.
- Low-severity defects not affecting release-gated workflows.

- [ ] Every open RC defect is labeled `must-fix` or `defer` with rationale and owner.
- [ ] Deferred defects are captured in the next-release backlog/milestone.

<a id="open-testing-exit-criteria"></a>

## 6) Open testing exit criteria

Complete before declaring open testing closed and moving to final Go/No-Go decision.

- [ ] Blocker count is `0` for current RC candidate. *(Owner: Release manager/QA)*
- [ ] Deferred defect list is approved and captured with owner + milestone. *(Owner: Product/Release manager)*
- [ ] Mandatory smoke baseline is re-run on the release candidate and passes. *(Owner: QA)*
- [ ] Required sign-off owners have all recorded completion in the release tracker. *(Owner: Release manager)*

## 7) Merge-to-main and tagging criteria

Only promote RC when all gates are green and approvals are complete.

- [ ] All required checks and smoke evidence in the [Required test suites and sign-off owners](#required-test-suites-and-sign-off-owners) section are complete and linked.
- [ ] No unresolved `must-fix` defects remain.
- [ ] Release owner + QA sign-off recorded.
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

## 8) Rollback plan and communication checklist

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
| RC owner |  |
| QA owner |  |
| Sign-off date |  |
| Decision | Go / No-Go |
| Release tag |  |
| Notes |  |
