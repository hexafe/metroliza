# Group Analysis — Next-Step PR Plan (Post-Documentation + Code Audit)

## Goal

Bring the current Group Analysis implementation to full spec alignment with `docs/group_analysis/group_analysis_spec_and_implementation_plan.md` using small, low-risk PRs.

## Constraints

- Keep Group Analysis independent from main export preset behavior (`Extended plots`).
- Preserve backward compatibility for exports when Group Analysis is `Off`.
- Treat `POPULATION` as a normal group and avoid `UNGROUPED` semantics in Group Analysis paths.
- Do not re-expand the legacy all-in-one Group Comparison writer.

## Risks

- Service/writer are already integrated, so spec-alignment updates can change output shape and break tests.
- Spec-status and comparability policy changes can alter user-visible conclusions.
- Diagnostics expansion can increase worksheet size and affect integration test assumptions.

## Assumptions from this audit

- Contracts + request plumbing for `group_analysis_level` and `group_analysis_scope` are already present.
- Export dialog controls and ExportDataThread wiring are already present.
- Group Analysis service/writer exist with baseline tests.
- Remaining work is primarily semantic hardening and report/diagnostics parity with the spec.

## Proposed PR sequence

### PR A — Spec-status taxonomy + comparability policy alignment

**Files**

- `modules/group_analysis_service.py`
- `tests/test_group_analysis_service.py`

**Changes**

- Replace coarse statuses (`complete`, `partial`, `missing`, etc.) with spec statuses:
  - `EXACT_MATCH`
  - `LIMIT_MISMATCH`
  - `NOM_MISMATCH`
  - `INVALID_SPEC`
- Normalize specs numerically to 3 decimals before comparison.
- Encode Light/Standard eligibility policy per status:
  - `NOM_MISMATCH`: descriptive only in Light, skip in Standard.
  - `LIMIT_MISMATCH`: A/B allowed with warnings in Light, skip in Standard.
  - `INVALID_SPEC`: descriptive-only in Light, skip in Standard.

**Definition of done**

- Unit tests cover each status branch and eligibility behavior.
- Diagnostics payload emits deterministic status counts.

---

### PR B — Capability + flags semantics completion

**Files**

- `modules/group_analysis_service.py`
- `tests/test_group_analysis_service.py` (and any focused helper tests)

**Changes**

- Implement capability mode outputs:
  - bilateral (`Cp`, `Cpk`),
  - upper-only (`Capability type = Cpk+`, `Cp = N/A`),
  - lower-only scaffold (`Cpk-`).
- Force invalid capability to `N/A` for `std <= 0` and unusable specs.
- Add required flags:
  - per-group: `LOW N`,
  - cross-group: `IMBALANCED N`, `SEVERELY IMBALANCED N`,
  - interpretation: `SPEC?`.

**Definition of done**

- Capability rows are deterministic and nullable in the expected format.
- Flags appear in per-group, pairwise (where relevant), and diagnostics summaries.

---

### PR C — Writer parity (Light vs Standard) + diagnostics completeness

**Files**

- `modules/group_analysis_writer.py`
- `modules/group_analysis_service.py`
- writer/integration tests

**Changes**

- Make rendering explicitly mode-aware (`light` vs `standard`).
- Enforce compact per-metric block layout contract:
  - metric header,
  - descriptive stats table,
  - pairwise comparison table,
  - short insight/comment line.
- Add per-metric comparability/spec summary and concise insight/comment text.
- Enforce user-visible pairwise wording contract:
  - `Difference` column with `YES`/`NO` only,
  - remove raw boolean `significant` from user-visible output,
  - `Comment` column values such as `DIFFERENCE` / `NO DIFFERENCE` / `DESCRIPTIVE ONLY` / `USE CAUTION`.
- Enforce user-facing rounding contract:
  - descriptive stats: 3 decimals,
  - capability indices: 3 decimals,
  - effect size: 3 decimals,
  - adjusted p-values: 4 decimals.
- Enforce spec-status label mapping for user-visible surfaces:
  - `EXACT_MATCH` → `Exact match`
  - `LIMIT_MISMATCH` → `Limits differ`
  - `NOM_MISMATCH` → `Nominal differs`
  - `INVALID_SPEC` or missing → `Spec missing / Invalid spec`.
- Add conservative histogram gating + explicit diagnostics entries for omitted histograms.
- Expand diagnostics fields to required metadata and mismatch/skip summaries, including potentially unmatched metrics across references.
- Add required diagnostics per-metric columns:
  - `Metric`, `Groups`, `Spec status`, `Pairwise comparisons`,
  - `Included in Light`, `Included in Standard`, `Comment`.
- Include explicit skip/exclusion rationale and unmatched-metric notes.
- Implement conditional formatting as in-scope behavior (not polish), including minimum rules for pairwise Difference/Comment, spec status, flags, diagnostics YES/NO inclusion, and restrained optional numeric threshold highlighting.

**Definition of done**

- Light/Standard sheet shapes are consistent and readable.
- Diagnostics always render required fields when Group Analysis is enabled.
- Writer/integration tests assert layout contract, rounding, pairwise wording contract, spec-status label mapping, and conditional-formatting rule presence/behavior.

---

### PR D — Export integration skip-path exactness

**Files**

- `modules/ExportDataThread.py`
- integration tests (`tests/test_phase4_integration_happy_path.py` and related)

**Changes**

- Align forced-scope mismatch message text exactly with spec wording.
- Ensure skip pathways emit consistent message + diagnostics reason payload.
- Reduce duplicate readiness/payload decision drift (single source of truth where practical).

**Definition of done**

- Scope mismatch behavior is deterministic for Auto/Single/Multi.
- Off/Light/Standard wiring remains backward compatible for non-Group-Analysis exports.

---

### PR E — Stabilization + docs closeout

**Files**

- targeted tests/cleanup in modules above
- `docs/group_analysis/group_analysis_spec_and_implementation_plan.md`
- optional mirror in `docs/group_analysis/codex_group_analysis_instructions.md`

**Changes**

- Finalize test matrix: off/light/standard, scope resolution, mismatch classes, capability modes, flags, diagnostics details, compact block layout contract, rounding contract, pairwise wording contract, and conditional-formatting checks.
- Remove safe dead references to legacy comparison flow where no longer needed.
- Update final status block with:
  - implemented in cycle,
  - deferred/not implemented,
  - one concrete next implementation step.

**Definition of done**

- Test suite passes for touched Group Analysis paths.
- Documentation status is updated and auditable.
- Readability + conditional formatting requirements are explicitly tracked as delivered scope (not deferred polish).

## PR-by-PR verification checklist

- PR A: service unit tests for taxonomy + eligibility.
- PR B: service unit tests for capability + flags.
- PR C: writer/integration tests for worksheet + diagnostics output, including block layout, rounding, wording contract, diagnostics columns, and conditional-formatting checks.
- PR D: integration tests for scope mismatch/skip messaging and non-regression.
- PR E: full targeted regression pass for Group Analysis paths and docs closeout check.

## TODO checklist

- [ ] PR A: finalize spec taxonomy + eligibility logic.
- [ ] PR B: finalize capability modes + flags.
- [ ] PR C: finalize writer parity + diagnostics + rounding/wording/conditional-formatting contracts.
- [ ] PR D: finalize skip/scope message-path exactness in export integration.
- [ ] PR E: finalize stabilization, cleanup, and docs status closeout.

## Suggested order rationale

Lock service semantics first (A/B), then rendering contract (C), then integration exactness (D), then stabilization/docs closeout (E). This sequencing minimizes regression blast radius and keeps each PR reviewable.

## Explicit in-scope implementation note

Readability and conditional formatting are current-scope deliverables for this PR plan; they are not deferred UI polish.
