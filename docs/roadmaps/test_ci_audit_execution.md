# Test/CI Audit and Execution Tracker (`release/2026.03-rc1`)

> Superseded by `docs/roadmaps/2026_03_rc1_test_ci_execution_tracker.md` for active RC1 execution tracking.

## 1) Purpose
Create and run a low-risk, iterative workstream that improves release confidence for `release/2026.03-rc1` by strengthening test guardrails, CI signal quality, coverage visibility, and release/testing documentation alignment.

## 2) Scope
In scope for this tracker:
- Test strategy and structure under `tests/`.
- Test/CI config in `pyproject.toml`, `requirements-dev.txt`, and `.github/workflows/ci.yml`.
- Release/test operational docs under `docs/ci-policy.md`, `docs/release_checks/`, and related runbooks/checklists.
- Release/test scripts (`scripts/sync_release_metadata.py`, `scripts/release_only_google_conversion_smoke.py`).
- Native parser smoke/parity fixtures and mechanisms (`tests/fixtures/cmm_parser/*`, `tests/test_cmm_parser_parity.py`, native CI lane).

## 3) Non-goals
- Broad architecture refactors unrelated to release confidence.
- Big-bang module naming migration.
- Turning environment-dependent Google OAuth smoke into a required PR gate.
- Heavy platform matrix expansion in one pass.
- Replacing existing RC process docs; this tracker aligns and tightens them incrementally.

## 4) Current-state audit summary
Repository-specific findings from static audit:
- Test suite is substantial and includes broad module coverage plus targeted regression tests for export logic, DB migration behavior, parser behavior, docs hygiene, and policy guardrails.
- CI already runs meaningful blocking jobs: static checks, full pytest suite, native wheel build/smoke, and parser parity (native-enabled).
- A release-only Google conversion smoke path exists and is intentionally non-blocking/opt-in in CI, matching local-OAuth constraints.
- Coverage reporting is not configured in test tooling or CI (no `pytest-cov` usage, no coverage artifact/public summary, no threshold policy).
- CI validates Linux/Python 3.11 only; release docs describe broader packaging/runtime responsibilities (Windows/macOS distribution concerns) that are not directly represented in automated CI lanes.
- Native parity fixtures exist but are relatively small (`tests/fixtures/cmm_parser/*.json`), increasing risk of parser-regression blind spots for real-world edge inputs.
- Export behavior has many helper-focused tests, but golden-path artifact regression coverage is concentrated and not systematically tracked as a release confidence metric.

## 5) Strengths
- Strong regression-oriented test culture with focused tests around prior defects (`phase*`, dialog safety, grouping/delete key handling, thread helpers).
- CI includes non-trivial native build + parity validation, which is high value for this repo’s risk profile.
- CI includes repository/diff secret scanning and release metadata consistency checks.
- Documentation quality checks exist in tests (`test_docs_markdown_links.py`, docstring policy checks, requirements hygiene checks).
- Google conversion process is explicitly documented with release gating semantics and evidence expectations.

## 6) Gaps / missing guardrails
1. **Coverage visibility gap:** no machine-visible coverage trend, no artifact, no baseline; hard to evaluate confidence drift.
2. **Critical-flow regression gap:** no explicit RC-critical flow map tying tests to release gates (parse → DB → export variants, conversion fallback, packaging startup).
3. **Packaging confidence gap:** CI validates native wheel/parity but not packaged desktop artifact smoke for release-risk platforms.
4. **Parity corpus depth gap:** limited parser fixture corpus may miss nuanced native/python divergence cases.
5. **Controller/dialog direct-protection gap:** some logic is tested, but there is no explicit maintained checklist mapping meaningful controller logic to direct regression tests.
6. **Docs alignment drift risk:** docs and CI are broadly aligned, but there is no single living test/CI execution tracker for incremental readiness work on this release line.
7. **Signal cost/clarity gap:** optional/manual checks are documented, but escalation path for "CI green but release not ready" can be made clearer in one place.

## 7) Risk-ranked recommendations
### High priority
- **R1:** Add non-blocking coverage reporting in CI (artifact + summary) to improve risk visibility without destabilizing PR flow.
- **R2:** Create/maintain an RC-critical-flow test matrix in docs and tie each flow to specific automated/manual checks.
- **R3:** Add targeted regression tests for highest-risk export/user flows that currently rely mostly on helper-level tests.

### Medium priority
- **R4:** Deepen native parser parity fixtures with a small curated set of tricky real-world token/layout patterns.
- **R5:** Add lightweight packaging smoke lane (manual/nightly first) for desktop artifact startup confidence, especially Windows-oriented.
- **R6:** Tighten docs to clearly separate blocking CI gates vs required manual release gates and evidence ownership.

### Lower priority / defer unless evidence worsens
- **R7:** Coverage threshold enforcement (make blocking) only after stable baseline and noise analysis.
- **R8:** Broader CI matrix expansion beyond highest-value platform smoke checks.

## 8) Implementation phases
### Phase 1 — Visibility improvements
- **Objective:** Add confidence visibility without increasing merge friction.
- **Rationale:** Immediate signal gain, low change risk.
- **Target files:** `.github/workflows/ci.yml`, `requirements-dev.txt`, `pyproject.toml` (if needed), `docs/ci-policy.md`, `docs/release_checks/release_candidate_checklist.md`.
- **Dependencies:** none.
- **Acceptance criteria:** coverage report generated in CI and documented as non-blocking informational signal.
- **Risk:** low.
- **Immediate/deferred:** immediate.

### Phase 2 — Targeted regression protection
- **Objective:** Close high-risk test gaps in RC-critical user flows.
- **Rationale:** Improves regression safety where failures are most costly.
- **Target files:** selected `tests/test_export_*`, `tests/test_thread_flow_helpers.py`, `tests/test_phase4_integration_happy_path.py`, native parser fixture/tests.
- **Dependencies:** Phase 1 visibility baseline.
- **Acceptance criteria:** added/updated tests for explicitly identified RC-critical gaps; no behavior regressions.
- **Risk:** low-medium.
- **Immediate/deferred:** immediate, incrementally.

### Phase 3 — CI/release smoke confidence
- **Objective:** Improve packaging/distribution confidence with cost-controlled smoke checks.
- **Rationale:** Desktop release risk includes install/startup/runtime packaging behavior.
- **Target files:** `.github/workflows/ci.yml`, release smoke scripts/docs.
- **Dependencies:** Phase 1/2 evidence.
- **Acceptance criteria:** documented and executable smoke lane policy (manual/nightly/dispatch) for packaging confidence.
- **Risk:** medium.
- **Immediate/deferred:** immediate for doc/process scaffolding, defer heavy automation if cost too high.

### Phase 4 — Docs/checklist alignment hardening
- **Objective:** Keep operational docs synchronized with actual CI/test behavior.
- **Rationale:** Release confidence depends on clear ownership and gate semantics.
- **Target files:** `docs/ci-policy.md`, `docs/release_checks/*`, `docs/README.md`, this tracker.
- **Dependencies:** outputs from Phases 1-3.
- **Acceptance criteria:** docs updated in same PRs as behavior/policy changes; no stale gate descriptions.
- **Risk:** low.
- **Immediate/deferred:** immediate and continuous.

## 9) Prioritized TODO backlog
| ID | title | status | linked phase | rationale | target files | tests affected | docs/CI files affected | risk note | definition of done |
|---|---|---|---|---|---|---|---|---|---|
| TCI-001 | Add non-blocking coverage reporting to CI | todo | Phase 1 | No current coverage visibility; improves risk signal | `.github/workflows/ci.yml`, `requirements-dev.txt` | full pytest invocation in CI | `docs/ci-policy.md`, `docs/release_checks/release_candidate_checklist.md`, tracker | low | CI uploads coverage artifact + summary; docs reflect non-blocking status |
| TCI-002 | Document RC-critical flow → test/check matrix | todo | Phase 1 | Makes confidence gaps explicit and reviewable | `docs/release_checks/release_candidate_checklist.md` (or dedicated release_checks doc) | maps existing tests/manual checks | `docs/README.md`, `docs/ci-policy.md`, tracker | low | matrix committed and linked from checklist/status docs |
| TCI-003 | Add export golden-path regression test slice | todo | Phase 2 | Reduce reliance on helper-only coverage for user-visible exports | `tests/test_phase4_integration_happy_path.py` and/or `tests/test_export_*` | new/updated focused regression tests | tracker (+ docs only if workflow changes) | low-medium | deterministic regression assertion for selected critical export behavior |
| TCI-004 | Expand native parser parity fixture corpus | todo | Phase 2 | Existing fixture set is small for parity-sensitive code | `tests/fixtures/cmm_parser/*.json`, `tests/test_cmm_parser_parity.py` | parity tests | tracker | medium | new fixtures cover identified edge patterns and pass both backends |
| TCI-005 | Define packaging smoke lane policy for RC confidence | todo | Phase 3 | CI currently lacks packaging artifact smoke despite desktop release risk | `.github/workflows/ci.yml` (if automated), release docs | optional smoke checks/manual runbooks | `docs/release_checks/open_testing_runbook.md`, `docs/release_checks/release_candidate_checklist.md`, `docs/ci-policy.md`, tracker | medium | policy and execution path documented; automation level agreed and implemented if low-risk |
| TCI-006 | Clarify blocking vs manual gate semantics across docs | todo | Phase 4 | Avoid "CI green but not release-ready" ambiguity | docs only | none | `docs/ci-policy.md`, `docs/release_checks/release_status.md`, `docs/release_checks/google_conversion_smoke.md`, tracker | low | docs consistently distinguish PR-blocking vs release-blocking checks |
| TCI-007 | Evaluate coverage threshold policy (deferred decision) | deferred | Phase 4 | Should follow stable baseline to avoid noisy blockers | `.github/workflows/ci.yml` (optional), docs | coverage job | `docs/ci-policy.md`, tracker | medium | explicit go/no-go decision recorded after baseline observation window |

## 10) Per-item status tracker
| Item ID | current status | completed work | changed files | tests run | docs reviewed/updated | remaining risks | next recommended step |
|---|---|---|---|---|---|---|---|
| TCI-001 | todo | Not started | — | — | Initial plan captured in this tracker | coverage blind spot remains | Start TCI-001 |
| TCI-002 | todo | Not started | — | — | Initial plan captured in this tracker | critical-flow mapping remains implicit | After TCI-001, start TCI-002 |
| TCI-003 | todo | Not started | — | — | Initial plan captured in this tracker | export golden-path regression gap remains | After TCI-002, start TCI-003 |
| TCI-004 | todo | Not started | — | — | Initial plan captured in this tracker | parity fixture depth remains limited | After TCI-003, start TCI-004 |
| TCI-005 | todo | Not started | — | — | Initial plan captured in this tracker | packaging smoke confidence gap remains | Start when phase-2 signal is in place |
| TCI-006 | todo | Not started | — | — | Initial plan captured in this tracker | docs semantics drift risk remains | Execute alongside TCI-001/002/005 |
| TCI-007 | deferred | Deferred pending stable coverage baseline | — | — | Defer rationale recorded | premature threshold could create noisy failures | Revisit after 2–4 weeks of coverage trend data |

## 11) Test strategy updates
- Keep full-suite PR testing and native parity checks as existing hard gates.
- Add visibility-first coverage reporting before enforcing thresholds.
- Prioritize regression tests that validate user-visible outcomes (artifact-level behavior) over internal-only helper tests when selecting new RC safety tests.
- Grow parity fixtures incrementally with real edge patterns; avoid massive corpus churn in a single PR.
- Keep environment-dependent Google conversion checks release-only/manual unless credentials and sandbox infra are guaranteed.

## 12) CI strategy updates
- Maintain current blocking checks: static checks, full pytest, native artifacts/parity.
- Add informational coverage output in PR CI as first increment.
- Keep Google conversion smoke opt-in/manual; treat as release gate evidence, not PR merge gate.
- Introduce packaging smoke confidence via low-cost path first (manual/dispatch/nightly), then consider promotion to stricter gate if stable/value-positive.

## 13) Documentation update rules
For every completed item in this tracker:
1. Review touched code comments/docstrings for accuracy.
2. Review `README.md` if developer workflow or behavior changed.
3. Review `docs/README.md` when adding/renaming active docs.
4. Review/update `docs/ci-policy.md` for any CI semantics changes.
5. Review/update relevant `docs/release_checks/*` for gate/runbook/checklist impact.
6. Update this tracker in the same PR with completed work, tests run, and next step.
7. If no doc changes are needed, record explicit rationale: "docs reviewed, no update needed, because ...".

## 14) Deferred items
- Coverage threshold enforcement (`TCI-007`) deferred until baseline exists and false-positive/noise profile is understood.
- Any full multi-OS packaging matrix expansion deferred unless phase-3 evidence shows high payoff vs CI cost.
- Any broad refactor not directly tied to release confidence remains out of scope.

## 15) Next recommended step
**TCI-001 — Add non-blocking coverage reporting to CI**
- Add `pytest-cov` to `requirements-dev.txt`.
- Extend CI `unit-tests` job to generate XML + terminal summary and upload artifact.
- Keep non-blocking while documenting semantics in `docs/ci-policy.md` and RC checklist.

This is the highest-value, lowest-risk first implementation step because it improves confidence visibility immediately without changing product behavior.
