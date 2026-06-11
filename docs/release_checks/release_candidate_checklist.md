# Release candidate checklist

Use this checklist as the **primary release gate** for RC readiness, sign-off, promotion, and rollback preparedness.

Authoritative source for branch naming rules: `docs/release_checks/branching_strategy.md`.

## 1) Pre-freeze checks

Complete before announcing code freeze or cutting an RC branch.

- [ ] Scope is locked for the target release; all non-release-critical work is moved out of milestone.
- [ ] Release owner and backup owner are assigned.
- [x] `src/metroliza/app/version.py` version/build/date values are updated for this RC.
- [x] `CHANGELOG.md` includes user-facing notes for this RC/release.
- [x] `README.md` **Release highlights** reflects the current RC/release line.
- [x] `python scripts/sync_release_metadata.py --check` passes (release metadata, README, and CHANGELOG are aligned).
- [x] Open blockers are triaged against the defect criteria in section 6.
- [x] Open implementation-item gate triage is completed in [`implementation_item_triage.md`](./implementation_item_triage.md) (Gate/Owner/Target RC/Rationale filled) before freeze proceeds.
- [ ] Feature freeze is active for the RC line; any late-scope exception is recorded with release-owner approval before merge.

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
- [ ] Late-scope exception register is empty, or every exception has rationale, owner, target RC, test evidence, rollback/deferral option, and explicit release-owner approval. *(Owner: Release owner)*
- [ ] Active RC branch name is confirmed and documented (for example `release/2026.05-rc1`; validation branches are not final RC branches). *(Owner: Release engineer)*
- [ ] Build identifier for open testing is published (artifact/version/hash) and linked in tracker. *(Owner: Release engineer)*
- [x] Mandatory CI baseline is completed and linked (build/lint/tests) before open testing starts for validation SHA `05b5049558509060df43778d7b39424726e56ff1`: GitHub Actions run [`26875151720`](https://github.com/hexafe/metroliza/actions/runs/26875151720). *(Owner: Release owner)*
- [ ] Known-issues document link is prepared and shared with open testers. *(Owner: QA/Product)*
- [ ] Bug reporting channel is announced (for example issue board + chat channel) and monitored. *(Owner: Release manager/QA)*

## 4) RC branch creation

Create the RC branch from the approved base commit (currently `master` in this repository):

```bash
git checkout master
git pull --ff-only origin master
git checkout -b release/2026.05-rc1
git push -u origin release/2026.05-rc1
```

Alternative (single command if local `master` is already up to date):

```bash
git checkout -b release/2026.05-rc1 origin/master
git push -u origin release/2026.05-rc1
```

- [ ] RC branch follows naming convention (for example `release/2026.05-rc1`).
- [ ] Branch creation commit SHA and timestamp are recorded in release notes/tracker.

<a id="required-test-suites-and-sign-off-owners"></a>

## 5) Required test suites and sign-off owners

Run and record all required checks from the RC branch:

```bash
python -m compileall .
ruff check .
PYTHONPATH=src:. python -m pytest tests -q
```

- [x] Compile check passed locally for the current audit worktree. *(Owner: Dev)*
- [x] Lint check passed locally for the current audit worktree. *(Owner: Dev)*
- [x] Unit test suite passed locally for the current audit worktree. *(Owner: QA/Dev)*

### Required packaging validation (release-blocking)

Build commands:

```bash
pyinstaller packaging/metroliza_onefile.spec
pyinstaller packaging/metroliza_onedir.spec
python -m maturin build --manifest-path src/metroliza/native/cmm_parser/Cargo.toml --release
python -m maturin build --manifest-path src/metroliza/native/chart_renderer/Cargo.toml --release
python -m maturin build --manifest-path src/metroliza/native/group_stats_coercion/Cargo.toml --release
python -m maturin build --manifest-path src/metroliza/native/comparison_stats_bootstrap/Cargo.toml --release
python -m maturin build --manifest-path src/metroliza/native/distribution_fit_ad/Cargo.toml --release
```

```powershell
./build_windows_exe.ps1 -Mode both
./packaging/build_nuitka.ps1 -Mode standalone
./scripts/measure_windows_startup.ps1 -ArtifactPath <onefile.exe>,<onedir\metroliza.exe>
```

- [ ] PyInstaller onefile output exists under `dist/` and launches. *(Owner: Release engineer/QA)*
- [ ] PyInstaller onedir output exists under `dist/` and launches faster than onefile on the clean Windows test machine. *(Owner: Release engineer/QA)*
- [ ] Nuitka output executable exists and launches on a clean/sandbox target environment. *(Owner: Release engineer/QA)*
- [ ] Startup profile JSONL evidence is attached for onefile and onedir launch tests. *(Owner: QA)*
- [ ] Native wheel build succeeds for release target(s), and `_metroliza_cmm_native` import smoke check passes. *(Owner: Release engineer/QA)*
- [ ] Native chart wheel build succeeds for release target(s), and `_metroliza_chart_native` histogram render smoke check passes. *(Owner: Release engineer/QA)*
- [ ] Native group statistics, comparison statistics, and distribution-fit wheels build and their import smoke checks pass. *(Owner: Release engineer/QA)*
- [ ] Pure-Python parser fallback works when native module is intentionally unavailable (`METROLIZA_CMM_PARSER_BACKEND=python`). *(Owner: QA)*
- [ ] Basic startup flow works (open app, load a representative input, generate an export). *(Owner: QA)*
- [ ] Produced artifacts are named/versioned as expected for RC distribution. *(Owner: Release manager)*
- [ ] Third-party notices/license attribution are bundled or attached to release artifacts, including RapidOCR, ONNX Runtime, OpenCV, NumPy, Excel reader packages, hexafe-plotstats, and Oznak. *(Owner: Release manager/QA)*

- [x] GitHub CI checks for the final pushed rc2 hardening commit are green before tag/promotion: run [`26947482310`](https://github.com/hexafe/metroliza/actions/runs/26947482310) passed for commit `60e0278739d3d696715f94c3c2eefe155a7f11fd`. Previous rc2 merge evidence run [`26891179285`](https://github.com/hexafe/metroliza/actions/runs/26891179285) passed for commit `24a50ed069cd45c927f40d10ea0c989a7800915f`. *(Owner: Release owner)*
- [ ] CMM parser perf gate evidence (`cmm-parser-perf-gate` + `cmm-parser-perf-artifacts`) is reviewed when parser/backend changes are present; triage follows [`cmm_parser_perf_guardrail.md`](./cmm_parser_perf_guardrail.md). *(Owner: Release owner/QA)*
- [ ] Coverage threshold from `unit-tests` passes, and `unit-test-coverage` artifact `coverage.xml` is reviewed as RC confidence evidence. *(Owner: Release owner/QA)*
- [ ] Manual release smoke evidence is linked before open-testing promotion when applicable. Google conversion smoke is release-blocking for promoted RC artifacts; skipped default CI does not satisfy that gate. *(Owner: Release owner)*

### 2026.05 RC5 rc2 hardening evidence

Current validation branch: `rc2`.
Current RC metadata: `2026.05rc5(260611)`.
Current plotstats hotfix pin:
`1e2c72107d342f44a37e5fb78d7d76992ea60315`.

- Static scatter annotation audit evidence lives in
  [`rc4_static_scatter_annotation_backgrounds_2026-05-23.md`](./rc4_static_scatter_annotation_backgrounds_2026-05-23.md).
- Previous RC2 audit evidence remains historical in
  [`rc2_release_audit_2026-05-17.md`](./rc2_release_audit_2026-05-17.md).
- Local release gates passed for the current directory-reorganization audit
  worktree after the chart reference-label dedupe and `260602` build-date
  refresh: `ruff`, `compileall`, release metadata sync, release hygiene,
  security audit, full pytest with coverage, and packaged PDF parser input
  validation.
- Full pytest with coverage passed:
  `1773 passed, 207 skipped, 95 warnings, 60 subtests passed`; combined
  CI-scope coverage `67.20%` against the `65%` threshold.
- Security audit passed after allowing `pip-audit` to create/upgrade its temporary
  dependency environment; `pip-audit` reported no known vulnerabilities.
- Dashboard UX/copy unification QA passed on 2026-06-01 after the CSV Summary and
  Export dashboard updates: focused dashboard tests passed
  (`114 passed`), full headless pytest passed
  (`1773 passed, 207 skipped, 6 warnings, 60 subtests passed`), and the CI-style
  coverage gate passed (`1773 passed, 207 skipped, 95 warnings, 60 subtests
  passed`; coverage `67.26%` against the `65%` threshold). Local gates also
  passed for `ruff`, `compileall`, packaged PDF parser validation, release
  metadata sync, release hygiene, and the security audit. The first sandboxed
  security-audit attempt failed only because `pip-audit` could not refresh its
  temporary dependency environment; the escalated rerun reported no known
  vulnerabilities.
- Static POPULATION layer QA passed locally on 2026-06-01. The full headless
  suite passed (`1825 passed, 259 skipped, 95 warnings, 60 subtests passed`),
  focused dashboard/contract tests passed, and the combined coverage gate passed
  with isolated real-Qt UI shards at `81%` against the raised `80%` threshold.
  The current pushed-SHA CI baseline below covers this slice before merge/tag.
- Oznak access-check and CSV Summary static POPULATION regression QA passed
  locally on 2026-06-02. `Check access` no longer requests a reference column
  unless reference filtering is configured, and 5,000-row all-POPULATION CSV
  Summary time-series dashboards render a visible static POPULATION layer with
  all rows when the sample cap is 50,000. Local gates passed: release metadata
  sync, release hygiene, packaged PDF parser validation, security audit, focused
  Oznak/dashboard tests (`17 passed` and `57 passed`), full headless suite
  (`1828 passed, 261 skipped, 95 warnings, 60 subtests passed`), and the
  CI-shaped combined coverage gate at `81%` against the `80%` threshold.
  The current pushed-SHA CI baseline below covers this slice before merge/tag.
- Export/CSV Summary cleanup QA passed locally on 2026-06-02. Export grouping
  now infers standard group analysis from applied grouping, creates the HTML
  dashboard automatically for grouped exports, and keeps Group Analysis out of
  the workbook when the dashboard is generated. CSV Summary now removes the
  former detail selector, uses full dashboard rendering by default, and keeps
  pasted-reference controls out of the CSV/Excel workflow. Focused Export and
  release metadata tests passed (`78 passed`), local release gates passed
  (`ruff`, `compileall`, release metadata sync, release hygiene, and security
  audit with no known vulnerabilities), the full headless suite passed
  (`1828 passed, 259 skipped, 95 warnings, 60 subtests passed`), and the
  CI-shaped combined coverage gate passed at `81%` against the `80%` threshold.
  The final docs/freeze merge commit passed pushed rc2 CI in run
  [`26891179285`](https://github.com/hexafe/metroliza/actions/runs/26891179285).
- Pre-merge validation branch CI passed: GitHub Actions run [`26875151720`](https://github.com/hexafe/metroliza/actions/runs/26875151720)
  for commit `05b5049558509060df43778d7b39424726e56ff1` (`Fix dashboard
  datetime axis scaling`) on 2026-06-03. Green automatic jobs were Static checks,
  Unit tests with combined coverage artifact upload, Native wheel build and
  smoke checks, CMM parser perf guardrail, and the non-blocking Performance
  benchmark trend check. Manual/opt-in jobs were skipped: Packaging smoke,
  Windows startup benchmark, and Google conversion smoke.
- The pre-merge CI run is kept as history for the dashboard/freeze work before
  merge. The rc2 run below is the current pushed-branch CI evidence. Neither run
  closes release-promotion evidence for packaging smoke, Windows executable
  clean-machine launch/startup, Google conversion, or third-party notice
  artifact review.
- rc2 docs/freeze merge CI passed: GitHub Actions run [`26891179285`](https://github.com/hexafe/metroliza/actions/runs/26891179285)
  for commit `24a50ed069cd45c927f40d10ea0c989a7800915f` (`Update dashboard
  training docs`) on 2026-06-03. Green automatic jobs were Static checks, Unit
  tests with combined coverage artifact upload, Native wheel build and smoke
  checks, CMM parser perf guardrail, and the non-blocking Performance benchmark
  trend check. Manual/opt-in jobs were skipped: Packaging smoke, Windows startup
  benchmark, and Google conversion smoke.
- rc2 startup/dashboard hardening CI passed: GitHub Actions run [`26947482310`](https://github.com/hexafe/metroliza/actions/runs/26947482310)
  for commit `60e0278739d3d696715f94c3c2eefe155a7f11fd` (`Fix dashboard
  selected style reset`) on 2026-06-04. Green automatic jobs were Static checks,
  Unit tests with combined coverage artifact upload, Native wheel build and
  smoke checks, CMM parser perf guardrail, and the non-blocking Performance
  benchmark trend check. Manual/opt-in jobs were skipped: Packaging smoke,
  Windows startup benchmark, and Google conversion smoke.
- Local rc2 hardening release gate passed before the `60e0278` push: `git diff
  --check`, `ruff`, `compileall`, release metadata sync, release hygiene,
  packaged PDF parser validation, security audit with no known vulnerabilities,
  focused selected-style reset regression (`1 passed`), and the CI-shaped
  combined coverage gate (`1857 passed`, `261 skipped`, `95 warnings`,
  `71 subtests passed`, plus isolated UI coverage shards; total coverage `81%`
  against the `80%` threshold).
- Local rc2 analytics/export/grouping hardening audit passed on 2026-06-04 before
  push. This slice restored one-sided zero-bound GD&T handling in modeled tail
  risk, capability/statistics payloads, workbook formulas, observed NOK counts,
  and plotstats payload adaptation; removed the histogram KDE reference overlay;
  reduced inserted workbook image display size without lowering rendered image
  quality; and made Export grouping search/filter behavior match the visible
  list fields. Local gates passed: `git diff --check`, `ruff`, `compileall`,
  release metadata sync, release hygiene, packaged PDF parser validation,
  security audit with no known vulnerabilities, full headless pytest with
  coverage (`1869 passed`, `261 skipped`, `95 warnings`, `71 subtests passed`),
  and the CI-shaped combined coverage gate with isolated UI shards at `81%`
  against the `80%` threshold. Pushed-SHA CI evidence for this slice must be
  recorded below before merge/tag.
- rc2 analytics/export/grouping hardening CI passed: GitHub Actions run
  [`26951307852`](https://github.com/hexafe/metroliza/actions/runs/26951307852)
  for commit `ad186fa0a748b65ba941e11916d322771a6771fe` (`Harden export
  analytics and grouping`) on 2026-06-04. Green automatic jobs were Static
  checks, Unit tests with combined coverage artifact upload, Native wheel build
  and smoke checks, CMM parser perf guardrail, and the non-blocking Performance
  benchmark trend check. Manual/opt-in jobs were skipped: Packaging smoke,
  Windows startup benchmark, and Google conversion smoke.
- Codex review follow-up local gate passed on 2026-06-04 after the pushed
  analytics CI evidence: stale industrial dynamic values are deleted when a
  source record is replaced with a row that no longer carries that dynamic
  field, dashboard visual runtime and Qt preview JSON escape `</script>` before
  embedding labels/settings/specs in inline scripts, and legacy industrial
  sync-run table rebuilds preserve `industrial_records.sync_run_id` links under
  caller-owned active transactions. Focused regression tests passed (`19 passed`
  for the first review follow-up, `5 passed` for the strengthened schema
  migration regression, and `40 passed` for
  `tests/test_dashboard_visual_options.py` after adding the preview escaping
  regression), and follow-up gates passed for `git diff --check`, full `ruff`,
  `compileall`, release metadata sync, release hygiene, security audit with no
  known vulnerabilities, full headless pytest with CI coverage tracking
  (`1871 passed`, `261 skipped`, `95 warnings`, `71 subtests passed`), and the
  CI-shaped combined coverage gate with isolated UI shards at `81%` against the
  `80%` threshold.
- Histogram overlay UI/UX and logic audit passed on 2026-06-04 after fixing the
  HTML dashboard Plotly path where package-generated histogram overlay traces
  could keep stale `x` coordinates while Metroliza supplied the resolved
  selected-model and tail-shading `plotly_y` values. Package-backed histogram
  overlays now replace both `x` and `y` from the resolved Metroliza overlay rows,
  filled/tail traces are recognized as modeled overlays before reference-line
  filtering, and fallback HTML dashboard coverage asserts selected model, KDE,
  and tail-shading coordinate parity. Focused export/chart regressions passed
  (`67 passed`), full `ruff`, `compileall`, release metadata sync, release
  hygiene, security audit with no known vulnerabilities, full headless pytest
  with CI coverage tracking (`1871 passed`, `261 skipped`, `95 warnings`,
  `71 subtests passed`), and the CI-shaped combined coverage gate with isolated
  UI shards passed at `81%` against the `80%` threshold.
- PyInstaller onefile bootloader splash support passed local Linux packaging and
  startup smoke on 2026-06-05. The slice adds a Windows onefile bootloader splash
  asset/spec hook, updates it through `pyi_splash` during Python startup, and
  closes it when Qt startup gating hands off to the app splash/main window. Local
  focused gates passed for app bootstrap/splash tests, packaging hidden-import
  tests, CI-policy sync, `ruff`, and Linux onefile packaging/startup smoke. The
  final pushed rc2 head passed GitHub Actions CI in run
  [`27006471511`](https://github.com/hexafe/metroliza/actions/runs/27006471511)
  for commit `80a1802fce2ff58c7c70e6dfa86ff5e1c5656c8c` (`Classify PyInstaller
  splash import`) on 2026-06-05. Green automatic jobs were Static checks, Unit
  tests with combined coverage artifact upload, Native wheel build and smoke
  checks, CMM parser perf guardrail, and the non-blocking Performance benchmark
  trend check. Manual/opt-in jobs were skipped: Packaging smoke, Windows startup
  benchmark, and Google conversion smoke.
- Post-plan summary-sheet planning extraction and release-evidence refresh passed
  local gates and GitHub Actions CI on 2026-06-05. Commit
  `aaa0ebdc32d31b9c05005da8408bca4a240f8373` (`Refresh release evidence and
  summary planning`) passed default CI in run
  [`27021152454`](https://github.com/hexafe/metroliza/actions/runs/27021152454).
  Green automatic jobs were Static checks, Unit tests with combined coverage
  artifact upload, Native wheel build and smoke checks, CMM parser perf
  guardrail, and the non-blocking Performance benchmark trend check. Manual and
  opt-in jobs were skipped: Packaging smoke, Windows startup benchmark, and
  Google conversion smoke.
- CSV Summary file-name grouping QA passed locally on 2026-06-08 for build
  `260608`. Multi-CSV loads can now offer one custom group per source file name
  without creating a `POPULATION` group, and the export path now uses the
  in-window dashboard optimization settings without a second export-time prompt.
  Local gates passed: `git diff --check`, `ruff`, `compileall`, release metadata
  sync, release hygiene, packaged PDF parser validation, security audit with no
  known vulnerabilities, focused CSV Summary dialog/service tests (`81 passed`),
  focused workflow/dashboard/release tests (`71 passed`), full headless pytest
  with coverage tracking (`1878 passed`, `263 skipped`, `95 warnings`,
  `71 subtests passed`), and the CI-shaped combined coverage gate with isolated
  UI shards at `81%` against the `80%` threshold. Pushed rc2 CI passed in
  GitHub Actions run
  [`27155205470`](https://github.com/hexafe/metroliza/actions/runs/27155205470)
  for commit `e0af5d8ec4075aa266a76610b4b6f608fffb2bd7` (`Add CSV Summary file
  groups`) on 2026-06-08. Green automatic jobs were Static checks, Unit tests
  with combined coverage artifact upload, Native wheel build and smoke checks,
  CMM parser perf guardrail, and the non-blocking Performance benchmark trend
  check. Manual and opt-in jobs were skipped: Packaging smoke, Windows startup
  benchmark, and Google conversion smoke.
- Full-module audit hardening QA passed locally on 2026-06-08 for build
  `260609`. The branch `codex/full-module-audit-20260608` hardens parsed-report
  persistence atomicity, CMM persistence error propagation, HTML-only dashboard
  failure handling, CSV Summary SQLite/header/filter parity, native chart
  fallback behavior, packaging OCR smoke gates, Windows startup evidence checks,
  and CMM performance trend baseline/observed-run requirements. Local gates
  passed: `git diff --check`, `ruff`, `compileall`, release metadata sync,
  release hygiene, security audit with no known vulnerabilities, and full
  headless pytest (`1889 passed`, `263 skipped`, `6 warnings`,
  `71 subtests passed`). Evidence is recorded in
  [`full_module_audit_2026-06-08.md`](./full_module_audit_2026-06-08.md).
- RC5 parser and UX release closeout QA passed locally on 2026-06-11 for build
  `260611`. The slice fixes parser handoff manifest prompt ordering and
  integrity validation, blocks routine live Industrial Data workbook export
  without a local cache target, adds direct `ParseResultV2` persistence and
  Industrial sync-run repository coverage, and refreshes release metadata. Local
  gates passed: `git diff --check`, `ruff`, `compileall`, release metadata sync,
  release hygiene, packaged PDF parser validation, security audit with no known
  vulnerabilities, focused parser tests (`36 passed`), focused Industrial Data
  tests (`45 passed`), release metadata tests (`5 passed`), full headless pytest
  with CI coverage tracking (`1922 passed`, `273 skipped`, `97 warnings`,
  `74 subtests passed`), and the CI-shaped combined coverage gate with isolated
  UI shards at `82%` against the `80%` threshold. Evidence is recorded in
  [`rc5_parser_ux_release_closeout_2026-06-11.md`](./rc5_parser_ux_release_closeout_2026-06-11.md).
  Pushed rc2 CI passed in GitHub Actions run
  [`27327220468`](https://github.com/hexafe/metroliza/actions/runs/27327220468)
  for commit `9a9310604604077b26fc5b2a4523459a4e14c5de` (`Finalize RC5 parser
  and UX release`) on 2026-06-11. Green automatic jobs were Static checks, Unit
  tests with combined coverage artifact upload, Native wheel build and smoke
  checks, CMM parser perf guardrail, and the non-blocking Performance benchmark
  trend check. Manual and opt-in jobs were skipped: Packaging smoke, Windows
  startup benchmark, and Google conversion smoke.
- Post-reorganization follow-up local audit passed after docs/reference cleanup,
  parser-plugin productionization coverage, architecture guardrail hardening, and
  release-status refresh.
- Parser profile self-service QA audit passed after fixing Excel workbook
  extraction, expected-results cardinality checks, duplicate-row matching,
  date/missing-token normalization, handoff folder open/copy actions, third-party
  notice coverage for Excel reader packages, and docs split between declarative
  profiles and advanced generated plugins.
- Latest published branch CI for the parser profile self-service follow-up slice
  passed: GitHub Actions run `26719879455` for commit
  `8d7717e4755d8bdba5593a6e05342f6f4a90143b`. Static checks, parser profile
  self-service smoke, security audit, unit tests with coverage, native smoke/parity
  checks, CMM parser perf guardrail, and the non-blocking benchmark trend check
  passed. Optional manual packaging/Google/Windows lanes remained skipped as
  expected for default push CI.
- GitHub Actions CI passed for hexafe-plotstats run `26337409366` on the
  package `main` commit
  `1e2c72107d342f44a37e5fb78d7d76992ea60315`.
- Manual packaging smoke, Windows executable clean-machine launch/startup,
  Google conversion smoke, third-party notice artifact evidence, and any open
  must-fix triage item are not recorded for the current RC5 promotion artifact
  yet and remain release-promotion blockers unless the release owner records an
  explicit waiver.

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

## 8) Merge-to-master and tagging criteria

Only promote RC when all gates are green and approvals are complete.

- [ ] All required checks in the [Required test suites and sign-off owners](#required-test-suites-and-sign-off-owners) section are complete and linked.
- [ ] No unresolved `must-fix` defects remain.
- [ ] Release owner sign-off recorded.
- [ ] RC branch merged to `master` with approved strategy.
- [ ] Release tag created from the merge commit (example: `vYYYY.MM` (for example `v2026.05`)).
- [ ] Tag is pushed and visible on remote.

Suggested commands:

```bash
git checkout master
git pull --ff-only origin master
git tag -a v2026.05 <merge-commit-sha> -m "Release v2026.05"
git push origin v2026.05
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
