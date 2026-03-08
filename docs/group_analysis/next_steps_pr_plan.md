# Group Analysis — Next-Step PR Plan (Post-Documentation Audit)

## Goal

Turn the current baseline Group Analysis implementation into full behavior that matches the approved specification in `docs/group_analysis/group_analysis_spec_and_implementation_plan.md`, while keeping exports stable and reviewable through small PRs.

## Constraints

- Keep Group Analysis independent from main export preset behavior (`Extended plots`).
- Preserve backward compatibility for exports when Group Analysis is `Off`.
- Keep `POPULATION` as normal group behavior and avoid `UNGROUPED` semantics in Group Analysis paths.
- Do not re-expand the legacy all-in-one Group Comparison writer.

## Risks

- Service and writer are already integrated, so spec-alignment changes can create regressions in export output shape.
- Statistical comparability rules (spec status, A/B eligibility, capability) can subtly change user-visible conclusions.
- Diagnostics expansion may increase worksheet size and break assumptions in existing integration tests.

## Repository audit summary

Current code already includes:

- contracts + request plumbing for `group_analysis_level` and `group_analysis_scope`,
- Export dialog controls,
- Group Analysis service + writer modules,
- export-thread integration and basic integration tests.

Remaining work is mainly **spec alignment hardening**, not net-new feature scaffolding.

## Proposed PR sequence

### PR A — Spec-status taxonomy and comparability policy alignment

**Scope**

- `modules/group_analysis_service.py`
- `tests/test_group_analysis_service.py`

**Changes**

- Replace current coarse statuses (`complete`, `partial`, `missing`, etc.) with spec statuses:
  - `EXACT_MATCH`
  - `LIMIT_MISMATCH`
  - `NOM_MISMATCH`
  - `INVALID_SPEC`
- Apply 3-decimal numeric spec normalization and explicit match/mismatch classification logic.
- Encode Light-vs-Standard eligibility policy per status:
  - `NOM_MISMATCH`: no raw A/B in Light, skipped in Standard.
  - `LIMIT_MISMATCH`: warning-allowed in Light, skipped in Standard.
  - `INVALID_SPEC`: descriptive-only in Light, skipped in Standard.

**Deliverable**

Deterministic comparability classification matching the spec and enforced in payload assembly.

---

### PR B — Capability/flags semantics completion

**Scope**

- `modules/group_analysis_service.py`
- unit tests under `tests/`

**Changes**

- Implement explicit capability mode outputs:
  - bilateral (`Cp`, `Cpk`),
  - upper-only (`Capability type = Cpk+`, `Cp = N/A`),
  - lower-only representation scaffold (`Cpk-`).
- Enforce invalid capability as `N/A` for `std <= 0` and unusable specs.
- Add required flags:
  - per-group `LOW N`,
  - cross-group `IMBALANCED N`, `SEVERELY IMBALANCED N`,
  - interpretation `SPEC?` when applicable.

**Deliverable**

Capability and flag behavior aligned with Section 10/11 of the spec.

---

### PR C — Writer parity for Light vs Standard and diagnostics completeness

**Scope**

- `modules/group_analysis_writer.py`
- `modules/group_analysis_service.py`
- writer/integration tests

**Changes**

- Make worksheet rendering explicitly mode-aware (`light` vs `standard`).
- Add spec-summary and insight blocks per metric section.
- Add conservative histogram eligibility + explicit diagnostics entries for skipped histograms.
- Expand diagnostics fields to include required metadata and status counts, including possible unmatched metrics across references.

**Deliverable**

Readable report structure with mandatory diagnostics content matching the spec requirements.

---

### PR D — ExportDataThread skip/message behavior and scope messaging exactness

**Scope**

- `modules/ExportDataThread.py`
- integration tests (`tests/test_phase4_integration_happy_path.py` and related)

**Changes**

- Align forced-scope mismatch message-sheet text with spec wording.
- Ensure skip pathways always propagate consistent message + diagnostics reason payload.
- Remove duplicate readiness/payload decision drift where possible (single source of truth).

**Deliverable**

Scope mismatch and minimum-condition skip behavior that is deterministic and spec-conformant.

---

### PR E — Stabilization, legacy cleanup, and docs closeout

**Scope**

- tests + targeted cleanup in modules touched above
- `docs/group_analysis/group_analysis_spec_and_implementation_plan.md`
- optional mirror in `docs/group_analysis/codex_group_analysis_instructions.md`

**Changes**

- Finish test matrix for off/light/standard, mismatch classes, capability modes, flags, and diagnostics details.
- Remove safe dead references to legacy comparison flow where no longer needed.
- Update “Status after implementation cycle” block with:
  - implemented,
  - deferred,
  - single concrete next step.

**Deliverable**

Spec-aligned implementation with auditable documentation closeout.

## TODO checklist mapped to this plan

- [ ] PR A: finalize spec taxonomy + eligibility logic.
- [ ] PR B: finalize capability modes + flags.
- [ ] PR C: writer parity and full diagnostics contract.
- [ ] PR D: exact skip/scope messaging alignment in export integration.
- [ ] PR E: test hardening, cleanup, docs status closeout.

## Suggested execution order rationale

This order reduces risk by locking correctness in service semantics before expanding writer output and integration behavior. It also keeps PRs narrowly reviewable: logic first, presentation second, wiring polish third, then cleanup/documentation.
