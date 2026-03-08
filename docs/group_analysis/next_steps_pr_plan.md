# Group Analysis — Audit and PR Plan (Current Repo vs Spec)

## Goal

Audit the repo against the implementation plan, then define the next PR sequence with a **docs/todo closeout as the last PR**.

## Current-state audit (spec vs repo)

| Area | Plan expectation | Current repo state | Status |
|---|---|---|---|
| Contracts + request plumbing | `group_analysis_level` / `group_analysis_scope` validated and propagated | Implemented in contracts + export dialog service + tests | ✅ Done |
| Export dialog UX | Separate Group Analysis section, level/scope controls, scope disabled when Off | Implemented in `ExportDialog` + tests | ✅ Done |
| Export integration | Off/Light/Standard flow, scope mismatch messaging, diagnostics always written | Implemented in `ExportDataThread` + integration coverage | ✅ Done |
| Service/writer architecture | New service + writer path active, legacy writer not extended | Implemented (`group_analysis_service.py`, `group_analysis_writer.py`) | ✅ Done |
| Flag semantics parity | `LOW N`, `IMBALANCED N`, `SEVERELY IMBALANCED N`, `SPEC?` end-to-end | Implemented in service + writer conditional formatting + tests | ✅ Done |
| Standard plots | Standard should insert real eligible plots (not placeholders) | Implemented with real chart insertion for eligible metrics | ✅ Done |
| Final docs closeout | Status + next-step wording reflects shipped behavior | Updated to match shipped behavior and post-cycle follow-up | ✅ Done |

## Remaining scope (active TODO only)

1. **Final documentation and TODO closeout (this PR)**
   - Update implementation status sections to reflect true shipped state.
   - Record one concrete post-plot next step.

2. **Post-cycle functional follow-up**
   - Implement dedicated **Characteristic Alias Mapping v1** for multi-reference comparisons.
   - Keep v1 manual-only (no canonical IDs/ontology/auto-matching) while preserving deterministic diagnostics and comparability labeling.

## PR acceptance criteria (single source of truth)

- [ ] **Docs status mirrors shipped behavior.**
  - Standard chart insertion is marked implemented (not deferred).
- [ ] **Deferred scope is explicit and accurate.**
  - Manual Characteristic Alias Mapping v1 is identified as the next delivery, while suggestion engine/fuzzy/canonical-ID work remains deferred.
- [ ] **One concrete next follow-up is captured.**
  - Next item identifies a specific post-cycle target and module/test direction.

## PR testable outcomes

- [ ] `group_analysis_spec_and_implementation_plan.md` includes a dedicated “Characteristic Alias Mapping v1” section and updated status/deferred wording.
- [ ] `next_steps_pr_plan.md` checklist marks Standard plot PR complete and identifies the next concrete follow-up item.
- [ ] `codex_group_analysis_instructions.md` current-cycle status note mirrors shipped behavior and the same next step.

## Proposed PR sequence

### PR 1 — Docs/todo closeout (this PR)

**Target files**
- `docs/group_analysis/group_analysis_spec_and_implementation_plan.md`
- `docs/group_analysis/codex_group_analysis_instructions.md`
- `docs/group_analysis/next_steps_pr_plan.md`

**Definition of done**
- Docs clearly separate implemented vs deferred work.
- Standard plot completion is reflected across status/checklist sections.
- One concrete post-cycle next step is recorded.

## TODO checklist

- [x] PR 1: deliver Standard plot insertion beyond placeholders.
- [x] PR 2 (last PR): update plan/status/todo docs to match shipped behavior.
- [ ] Next follow-up: implement Characteristic Alias Mapping v1 (manual mappings table, scoped resolution, and pipeline integration).

## Sequencing rationale

Standard chart insertion is now closed; this docs closeout aligns roadmap/status text with shipped behavior and leaves a single concrete follow-up (Characteristic Alias Mapping v1) for the next implementation cycle.
