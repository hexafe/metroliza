# UI Revamp Implementation Plan (Active)

This plan defines mandatory phase order, dependencies, and acceptance criteria for the current revamp cycle.

## Required Implementation Order

1. Foundation + shared shell
2. Characteristic mapping
3. Export
4. Grouping
5. Filter
6. Modify DB
7. Global consistency pass
8. Docs alignment + QA evidence
9. Archive move (closure only)

## Phase 1 — Foundation + shared shell

- **Priority:** Must-fix
- **Depends on:** none
- **Acceptance criteria:**
  - Shared header/status/action shell is standardized.
  - Core controls match refined design tokens and interaction states.
  - First-load path is clear and keyboard flow has no blocker regressions.

## Phase 2 — Characteristic mapping

- **Priority:** Must-fix
- **Depends on:** Phase 1
- **Acceptance criteria:**
  - Source/target mapping flow is scannable and unambiguous.
  - Coverage/progress summary remains visible during edits.
  - Validation guidance appears inline and in summary where needed.

## Phase 3 — Export

- **Priority:** Must-fix
- **Depends on:** Phase 2
- **Acceptance criteria:**
  - Export readiness is explicit before execution.
  - Options are grouped logically with sensible defaults.
  - Result summary includes destination, outcome status, and warnings/next steps.

## Phase 4 — Grouping

- **Priority:** Should-fix
- **Depends on:** Phase 1
- **Acceptance criteria:**
  - Group operation intent is previewable before apply.
  - Destructive/high-impact actions have explicit safety confirmation.
  - Selection context is preserved across multi-step edits.

## Phase 5 — Filter

- **Priority:** Should-fix
- **Depends on:** Phase 1, Phase 4
- **Acceptance criteria:**
  - Active filters are always visible and removable/resettable quickly.
  - Compound logic (AND/OR) is explicit in labels/layout.
  - No-result states explain cause and provide recovery actions.

## Phase 6 — Modify DB

- **Priority:** Must-fix
- **Depends on:** Phase 1
- **Acceptance criteria:**
  - Risk tier is visible before action execution.
  - Destructive operations require explicit acknowledgment.
  - Completion/failure guidance includes audit-friendly follow-up steps.

## Phase 7 — Global consistency pass

- **Priority:** Must-fix
- **Depends on:** Phases 1–6
- **Acceptance criteria:**
  - Token usage and control hierarchy are consistent across revised screens.
  - Helper/validation/empty-state messaging follows one voice and pattern.
  - Keyboard/focus/accessibility checks are complete for revised UI.

## Phase 8 — Docs alignment + QA evidence

- **Priority:** Should-fix (process-critical)
- **Depends on:** Phase 7
- **Acceptance criteria:**
  - Docs match final labels, controls, and workflow paths.
  - Screen-level evidence is captured for all revised screens.
  - Migration/release-note mappings cover renamed or removed controls.

## Phase 9 — Archive move (closure only)

- **Priority:** Nice-to-have (operational hygiene)
- **Depends on:** Phase 8
- **Acceptance criteria:**
  - Completion summary is appended to active revamp docs.
  - Active cycle is moved to `docs/archive/<year>/ui-revamp-<date>/`.
  - Year archive index and docs index links are updated.
