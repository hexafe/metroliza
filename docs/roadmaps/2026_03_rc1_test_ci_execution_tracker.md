# 2026.03 RC1 Test/CI Audit and Execution Tracker

## 1. Purpose
Drive a controlled, iterative test/CI confidence-improvement workflow for `release/2026.03-rc1`, with one small reviewable step at a time and clear release-readiness impact.

## 2. Scope
- Audit and improve test safety-net quality under `tests/`.
- Audit and improve CI signal quality in `.github/workflows/ci.yml`.
- Improve coverage visibility and regression protection for critical flows.
- Improve release/package confidence guardrails where practical.
- Keep `docs/ci-policy.md`, `docs/release_checks/*`, and related docs aligned with actual behavior.

## 3. Non-goals
- Broad architecture refactors unrelated to release confidence.
- Big-bang module renaming.
- Making environment-dependent Google OAuth smoke mandatory for all PR CI.
- Heavy platform-matrix expansion in one pass.
- Any change that weakens existing blocking CI checks.

## 4. Current-State Audit Summary
- Test suite breadth is strong (46 test modules) with targeted regression coverage for export helpers/flows, DB migration behavior, parser behavior, docs hygiene, and policy checks.
- CI has meaningful blocking lanes: static checks, full pytest, native wheel build/smoke, native parser parity tests; plus opt-in manual Google conversion smoke.
- Native parser confidence exists but parity fixture corpus is currently small (3 fixture JSON files), leaving potential edge-shape gaps.
- Coverage visibility baseline is in place (`pytest-cov`, `coverage.xml`, and uploaded CI artifact), with threshold gating intentionally deferred.
- Release docs and CI policy are generally coherent, but critical-flow mapping and “blocking vs manual release gate” semantics can be clearer in one operational stream.
- Desktop packaging/startup confidence is partly documented but not represented as a regular automated CI smoke lane.

### Current baseline (as of now)
- `requirements-dev.txt` includes `pytest-cov` for local and CI coverage collection.
- `.github/workflows/ci.yml` `unit-tests` runs `--cov-report=xml:coverage.xml` and uploads the `unit-test-coverage` artifact.
- `docs/ci-policy.md` and `docs/release_checks/release_candidate_checklist.md` define coverage as informational/non-blocking evidence.

## 5. Strengths
- Existing CI validates both Python and native parser quality paths.
- Export-related tests are substantial and include artifact-level assertions in integration slices.
- Repo includes docs/runbook checks in tests (link validation, docstring policy, requirements hygiene).
- Release metadata consistency and secret-hygiene checks are automated.
- Google conversion constraints are explicitly documented as environment-dependent release smoke.

## 6. Gaps and Risks
- **Coverage governance gap:** quantitative coverage visibility exists, but threshold policy remains intentionally deferred pending trend data.
- **Critical-flow mapping gap:** release-critical path coverage is not summarized in one maintainable matrix.
- **Parity depth risk:** small parser fixture set may miss native/python divergence edge cases.
- **Packaging confidence gap:** no routine packaging/startup smoke lane in CI for desktop release risk.
- **Docs clarity risk:** if CI/manual gate boundaries drift, “green CI vs release readiness” can be misinterpreted.

## 7. High-Priority Recommendations
1. Add non-blocking coverage reporting first (high value, low risk).
2. Add/strengthen one critical export golden-path regression assertion to protect user-visible output.
3. Add CI/release-smoke confidence increment (manual/dispatch packaging smoke first, not PR-blocking).
4. Tighten docs/checklist language for blocking CI vs manual release gates.
5. Expand native parser parity fixtures incrementally for realistic edge patterns.

## 8. Phased Implementation Plan
### Phase 1 - Audit and visibility
- Objective: Make risk visible without adding merge friction.
- Why: Immediate confidence gain with low disruption.
- Target files: `requirements-dev.txt`, `.github/workflows/ci.yml`, `docs/ci-policy.md`, `docs/release_checks/release_candidate_checklist.md`.
- Dependencies: Completed audit baseline.
- Acceptance criteria: Coverage report generated in CI as non-blocking informational signal and documented.
- Risk level: low.

### Phase 2 - Regression protection
- Objective: Add targeted tests for critical user-facing regression risk.
- Why: Raise confidence where failures are costly (export outputs/parity).
- Target files: `tests/test_phase4_integration_happy_path.py`, selected `tests/test_export_*`, `tests/fixtures/cmm_parser/*.json`, `tests/test_cmm_parser_parity.py`.
- Dependencies: Phase 1 visibility baseline.
- Acceptance criteria: At least one strengthened export golden-path test and one parser parity-fixture increment (or explicit deferral rationale).
- Risk level: low-medium.

### Phase 3 - CI and release-smoke improvements
- Objective: Improve packaging/release confidence with practical CI/manual smoke strategy.
- Why: Desktop release risk extends beyond unit tests.
- Target files: `.github/workflows/ci.yml`, `docs/release_checks/open_testing_runbook.md`, `docs/release_checks/release_candidate_checklist.md`, `docs/ci-policy.md`.
- Dependencies: Phase 1–2 outputs.
- Acceptance criteria: Useful packaging/startup smoke path defined and aligned with docs; non-blocking for standard PRs unless proven stable/value-positive.
- Risk level: medium.

### Phase 4 - Docs and checklist alignment
- Objective: Keep release/testing documentation synchronized with real CI/test behavior.
- Why: Operational clarity is part of release readiness.
- Target files: `docs/ci-policy.md`, `docs/release_checks/*`, `docs/README.md`, this tracker.
- Dependencies: Ongoing; applies after each step.
- Acceptance criteria: Every behavior/policy change reflected in docs in same step, with explicit rationale when no update is needed.
- Risk level: low.

## 9. Prioritized TODO Backlog

| Item | Current status | Lifecycle |
| --- | --- | --- |
| TCI-001 | completed | `todo` -> `in_progress` -> `completed` |
| TCI-002 | completed | `todo` -> `in_progress` -> `completed` |
| TCI-003 | completed | `todo` -> `in_progress` -> `completed` |
| TCI-004 | completed | `todo` -> `in_progress` -> `completed` |
| TCI-005 | completed | `todo` -> `in_progress` -> `completed` |
| TCI-006 | todo | `todo` -> `in_progress` -> `completed` |

### TCI-001 - Audit current tests, CI, and release-validation coverage
- Status: completed
- Phase: Phase 1 - Audit and visibility
- Priority: high
- Why: Establish accurate baseline before making guardrail changes.
- Target files: `tests/`, `.github/workflows/ci.yml`, `pyproject.toml`, `requirements-dev.txt`, `docs/ci-policy.md`, `docs/release_checks/*`, `docs/README.md`, `scripts/release_only_google_conversion_smoke.py`, `scripts/sync_release_metadata.py`
- Tests/checks: repository inspection commands; targeted inventory counts
- Docs review: `docs/README.md`, `docs/ci-policy.md`, `docs/release_checks/*`, tracker
- Risk notes: audit can miss implicit runtime assumptions if not paired with future focused implementation steps
- Definition of done:
  - Repository-specific strengths/gaps documented.
  - Phased plan and prioritized TODO backlog recorded.
  - Exactly one recommended next step identified.

### TCI-002 - Add coverage visibility/reporting plan and implement the safest first increment
- Status: completed
- Phase: Phase 1 - Audit and visibility
- Priority: high
- Why: Coverage visibility is currently absent, reducing confidence trend tracking.
- Target files: `requirements-dev.txt`, `.github/workflows/ci.yml`, `docs/ci-policy.md`, `docs/release_checks/release_candidate_checklist.md`, this tracker
- Tests/checks: run unit tests with coverage locally (or dry-run CI command), validate CI YAML and docs consistency
- Docs review: `docs/ci-policy.md`, `docs/release_checks/release_candidate_checklist.md`, tracker
- Risk notes: avoid introducing noisy blocking thresholds initially
- Definition of done:
  - Coverage tool dependency added and CI emits coverage output/artifact.
  - Coverage remains non-blocking initially.
  - Docs explicitly describe coverage lane semantics.

### TCI-003 - Strengthen regression protection for one critical export path
- Status: completed
- Phase: Phase 2 - Regression protection
- Priority: high
- Why: Critical export confidence still relies heavily on helper-level tests.
- Target files: `tests/test_phase4_integration_happy_path.py` and/or targeted `tests/test_export_*`
- Tests/checks: run targeted pytest module(s) and relevant integration/regression tests
- Docs review: tracker; release docs only if release/test process expectations change
- Risk notes: avoid brittle assertions tied to unstable formatting internals
- Definition of done:
  - One meaningful artifact-level regression assertion added/strengthened.
  - Test is deterministic and reviewable.
  - Existing related tests remain green.

### TCI-004 - Improve CI/release-smoke confidence and align docs/checklists
- Status: completed
- Phase: Phase 3 - CI and release-smoke improvements
- Priority: high
- Dependency/sequencing: Can proceed in parallel with TCI-005, but preferred sequence is **TCI-005 first, then TCI-004** so parser-confidence gains land before higher-cost CI/workflow changes.
- Why: Desktop packaging/startup confidence is only partially represented in CI.
- Target files: `.github/workflows/ci.yml`, `docs/ci-policy.md`, `docs/release_checks/open_testing_runbook.md`, `docs/release_checks/release_candidate_checklist.md`, tracker
- Tests/checks: validate workflow syntax and run any introduced smoke script/check locally where feasible
- Docs review: `docs/ci-policy.md`, `docs/release_checks/*`, `docs/README.md` (if docs set changes), tracker
- Risk notes: platform-specific runners/cost/time may require staged rollout
- Definition of done:
  - CI/manual smoke increment implemented or explicitly deferred with concrete rationale.
  - Blocking vs non-blocking semantics documented clearly.
  - Release checklist/runbook updated to match behavior.

### TCI-005 - Expand native parser parity corpus with one incremental edge fixture set
- Status: completed
- Phase: Phase 2 - Regression protection
- Priority: medium
- Dependency/sequencing: Chosen to run **before TCI-004** (or in parallel) because it is lower risk, faster to validate, and improves confidence without introducing CI runtime/cost volatility.
- Why: Current fixture depth is limited for parser parity-sensitive code.
- Target files: `tests/fixtures/cmm_parser/*.json`, `tests/test_cmm_parser_parity.py`, tracker
- Tests/checks: `python -m pytest tests/test_cmm_parser_parity.py -q`
- Docs review: tracker
- Risk notes: ensure fixture additions reflect realistic parser inputs and avoid overfitting
- Definition of done:
  - At least one new edge-pattern fixture added.
  - Parity assertions pass in python backend and native-enabled contexts where available.
  - Tracker records risk reduction and remaining gaps.

### TCI-006 - Align docs semantics for PR-blocking CI checks vs release-blocking manual evidence
- Status: todo
- Phase: Phase 4 - Docs and checklist alignment
- Priority: high
- Why: Section 15 identifies a docs-only alignment pass to keep PR-blocking CI semantics clearly separated from release-blocking manual evidence, preventing policy drift and misread release readiness.
- Target files: `docs/release_checks/release_status.md`, `docs/release_checks/release_candidate_checklist.md`, `docs/release_checks/open_testing_runbook.md`, `docs/ci-policy.md`, this tracker
- Tests/checks: `python -m pytest tests/test_docs_markdown_links.py -q`; `python -m pytest tests/test_ci_policy_sync.py -q` (or closest docs-policy consistency check available)
- Docs review: `docs/release_checks/release_status.md`, `docs/release_checks/release_candidate_checklist.md`, `docs/release_checks/open_testing_runbook.md`, `docs/ci-policy.md`, tracker, and section 15 sequencing note
- Risk notes: language-only changes can still introduce semantic ambiguity if terms like “blocking,” “required,” and “evidence” are not used consistently across all docs touchpoints
- Definition of done:
  - Docs explicitly distinguish PR-blocking CI checks from release-blocking manual evidence using consistent terms.
  - Any checklist/status matrices map each gate type to an owner/evidence source without contradiction.
  - Tracker and section 15 stay synchronized on next-step intent and lifecycle status transitions.

## 10. Progress Log


- 2026-03-07 — **TCI-004 completed**.
  - Work completed:
    - Added a new manual/opt-in CI lane `packaging-smoke` gated behind `workflow_dispatch` input `run_packaging_smoke=1`.
    - Implemented low-cost packaging confidence signal by building the PyInstaller onefile artifact and asserting expected output existence (`dist/metroliza`).
    - Updated CI and release docs to clearly classify packaging smoke as non-blocking for regular PR/push CI and as optional release evidence.
  - Changed files:
    - `.github/workflows/ci.yml`
    - `docs/ci-policy.md`
    - `docs/release_checks/release_candidate_checklist.md`
    - `docs/release_checks/open_testing_runbook.md`
    - `docs/roadmaps/2026_03_rc1_test_ci_execution_tracker.md`
  - Tests/checks run:
    - `python -m compileall .github/workflows/ci.yml docs/ci-policy.md docs/release_checks/release_candidate_checklist.md docs/release_checks/open_testing_runbook.md docs/roadmaps/2026_03_rc1_test_ci_execution_tracker.md`
    - `python -m pytest tests/test_docs_markdown_links.py -q`
    - `git diff -- .github/workflows/ci.yml docs/ci-policy.md docs/release_checks/release_candidate_checklist.md docs/release_checks/open_testing_runbook.md docs/roadmaps/2026_03_rc1_test_ci_execution_tracker.md`
  - Docs reviewed/updated:
    - Reviewed: `docs/ci-policy.md`, `docs/release_checks/release_candidate_checklist.md`, `docs/release_checks/open_testing_runbook.md`, this tracker.
    - **docs update required and applied**: CI/manual smoke semantics and checklist/runbook references aligned to new `packaging-smoke` lane behavior.
  - New/remaining risks:
    - Packaging smoke currently validates build + artifact existence only; launch/runtime behavior remains a manual release checklist gate.

- 2026-03-07 — **TCI-005 completed**.
  - Work completed:
    - Added a new parser parity fixture for interrupted multi-line tokenization with semantic label interruptions (`interrupted_multiline_tokens.json`) to expand parity corpus depth with a realistic edge shape.
    - Added a focused intent test that loads the named fixture and explicitly asserts this edge shape remains a single block containing `X` and `Y` measurement rows.
  - Changed files:
    - `tests/fixtures/cmm_parser/interrupted_multiline_tokens.json`
    - `tests/test_cmm_parser_parity.py`
    - `docs/roadmaps/2026_03_rc1_test_ci_execution_tracker.md`
  - Tests/checks run:
    - `python -m pytest tests/test_cmm_parser_parity.py -q`
  - Docs reviewed/updated:
    - Reviewed: this tracker.
    - **docs update required and applied**: tracker updated to record TCI-005 completion, changed files, executed tests, and remaining risks.
  - New/remaining risks:
    - Parser parity corpus depth improved, but additional edge shapes (e.g., mixed TP qualifiers across multi-block reports and malformed-token recovery) remain unrepresented.
    - Packaging/startup CI confidence remains limited until TCI-004.

- 2026-03-07 — **TCI-003 completed**.
  - Work completed:
    - Strengthened the phase-4 happy-path workbook regression by asserting exported worksheet XML includes expected measurement payload values (`10.1`, `10.2`) in addition to existing chart-range/formula checks.
    - Kept assertion scope artifact-level and deterministic to protect user-visible export behavior without coupling to unstable formatting internals.
  - Changed files:
    - `tests/test_phase4_integration_happy_path.py`
    - `docs/roadmaps/2026_03_rc1_test_ci_execution_tracker.md`
  - Tests/checks run:
    - `python -m pytest tests/test_phase4_integration_happy_path.py -q`
  - Docs reviewed/updated:
    - Reviewed: this tracker.
    - **docs reviewed, no update needed, because** this change only strengthens an existing test assertion and does not alter CI policy, release gates, or developer workflow behavior.
  - New/remaining risks:
    - Native parser parity fixture depth remains limited until TCI-005.
    - Packaging/startup CI confidence remains limited until TCI-004.

- 2026-03-07 — **TCI-002 completed**.
  - Work completed:
    - Added `pytest-cov` to developer/test dependencies for local and CI coverage support.
    - Updated `unit-tests` in CI to emit coverage summary in logs and generate `coverage.xml`.
    - Added coverage artifact upload (`unit-test-coverage`) for reviewer visibility.
    - Updated CI/release docs to clarify coverage is informational (non-blocking) and where evidence is reviewed.
  - Changed files:
    - `requirements-dev.txt`
    - `.github/workflows/ci.yml`
    - `docs/ci-policy.md`
    - `docs/release_checks/release_candidate_checklist.md`
    - `docs/roadmaps/2026_03_rc1_test_ci_execution_tracker.md`
  - Tests/checks run:
    - `python -m pytest tests -q --cov=. --cov-report=term --cov-report=xml:coverage.xml` (failed locally before dependency install due missing `pytest-cov` in environment)
    - `PYTHONPATH=. python -m pytest tests -q`
    - `git diff -- requirements-dev.txt .github/workflows/ci.yml docs/ci-policy.md docs/release_checks/release_candidate_checklist.md docs/roadmaps/2026_03_rc1_test_ci_execution_tracker.md`
  - Docs reviewed/updated:
    - Reviewed: `docs/ci-policy.md`, `docs/release_checks/release_candidate_checklist.md`, this tracker.
    - **docs update required and applied**: coverage semantics/evidence locations documented and RC checklist updated.
  - New/remaining risks:
    - Coverage remains visibility-only until a baseline is established for future threshold gating.

- 2026-03-07 — **TCI-001 completed**.
  - Work completed:
    - Performed repository-specific audit across required areas (tests, CI workflow, test config, release docs, release scripts, native parity fixtures).
    - Captured strengths, gaps/risks, recommendations, phased plan, and prioritized backlog in this tracker.
  - Changed files:
    - `docs/roadmaps/2026_03_rc1_test_ci_execution_tracker.md`
  - Tests/checks run:
    - `sed` review pass over required files (`ci.yml`, `pyproject.toml`, `requirements-dev.txt`, docs and runbooks).
    - Python inventory check for test module count and parser fixture count.
  - Docs reviewed/updated:
    - Reviewed: `docs/README.md`, `docs/ci-policy.md`, `docs/release_checks/release_candidate_checklist.md`, `docs/release_checks/open_testing_runbook.md`, `docs/release_checks/google_conversion_smoke.md`.
    - **docs update required and applied**: this tracker created as the required operational source of truth.
  - New/remaining risks:
    - Coverage visibility still absent until TCI-002.
    - Packaging/startup CI confidence remains limited until TCI-004.

- 2026-03-07 — **Tracker consistency update completed**.
  - Work completed:
    - Updated tracker narrative to reflect implemented coverage baseline state and removed stale statements claiming missing visibility.
    - Added explicit "Current baseline (as of now)" references to dependency, CI workflow behavior, and docs semantics.
    - Recorded deferred threshold work as trend-based governance decision rather than setup work.
  - Changed files:
    - `docs/roadmaps/2026_03_rc1_test_ci_execution_tracker.md`
  - Tests/checks run:
    - `git diff -- docs/roadmaps/2026_03_rc1_test_ci_execution_tracker.md`
  - Docs reviewed/updated:
    - Reviewed: this tracker.
    - **docs update required and applied**: this was a tracker consistency pass only; no CI behavior change.
  - New/remaining risks:
    - Coverage threshold decision remains deferred pending baseline trend/noise profile.

## 11. Test Strategy Notes
- Keep existing full-suite and native parity checks as baseline hard gates.
- Next confidence increment is visibility-first (coverage reporting) before threshold enforcement.
- Prefer deterministic artifact-level regression assertions for export critical paths.
- Keep Google conversion smoke as release/manual evidence due to local OAuth dependency model.

## 12. CI Strategy Notes
- Preserve current blocking checks: static checks, unit tests, native artifacts/parity.
- Introduce coverage reporting as non-blocking informational signal first.
- Treat Google conversion smoke as release gate evidence (manual/opt-in), not standard PR blocker.
- Stage packaging smoke confidence increment carefully to avoid high-cost/noisy PR friction.

## 13. Documentation Review Rules
For every step, explicitly review and record outcome for:
- touched docstrings/comments
- `README.md` if setup/workflow/developer instructions change
- `docs/README.md` if active docs are added/renamed
- `docs/ci-policy.md`
- relevant files under `docs/release_checks/`
- this tracker
- any release/test/runbook/checklist affected by the change

For each step, include one explicit statement:
- “docs update required and applied”, or
- “docs reviewed, no update needed, because ...”

## 14. Deferred Items
- **TCI-007 (deferred):** coverage threshold decision pending baseline trend and noise profile.
- Any broad multi-OS packaging matrix expansion is deferred unless incremental smoke lanes show clear value.

## 15. Next Recommended Step
Sequencing note: **TCI-005 was intentionally prioritized ahead of/alongside TCI-004** because it delivers faster confidence gain at lower implementation and operational risk; TCI-004 introduces broader CI/workflow surface area and potential runtime/cost noise.

Execute **TCI-006** next: perform a docs-only semantics alignment pass across `docs/release_checks/release_status.md` and related runbooks so "PR-blocking CI" vs "release-blocking manual evidence" distinctions remain explicit and drift-resistant.
