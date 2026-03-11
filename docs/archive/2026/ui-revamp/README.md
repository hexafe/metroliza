# UI Revamp Overview

This folder captures the planning docs for a structured UI revamp across the main user workflow.

## Goals

- Improve first-pass usability for primary workflows (mapping, exporting, grouping, filtering, and database edits).
- Reduce ambiguity in labels, helper copy, and state transitions.
- Normalize layout, spacing, and interaction patterns so screens feel like one product rather than separate tools.
- Cut operator mistakes by adding clearer affordances, validation messaging, and safer defaults.
- Establish a finish-line process (consistency pass, docs update, archival) so design debt does not linger.

## Visual Direction

- **Calm, utilitarian interface:** prioritize readability and decision speed over decorative visuals.
- **Consistent hierarchy:** stable placement for page title, primary action, secondary actions, and contextual help.
- **Progressive disclosure:** keep advanced options collapsed or grouped until needed.
- **Status-forward feedback:** clear success/warning/error states near the control that triggered them.
- **Accessibility baseline:** high-contrast text, explicit labels, keyboard-friendly focus order, and tooltip/helper parity.

## Documents

- [Implementation Plan](./implementation-plan.md) — phased rollout, dependencies, priorities, acceptance criteria, and per-phase completion notes.
- [Module TODO Tracker](./todo.md) — execution checklist with completion status by module.
- [Screen-by-Screen Review](./screen-by-screen-review.md) — pain points, UX targets, wording/layout changes, and helper-text opportunities.

## Completion Summary

**Status:** Completed and archived.

### Outcomes

- Delivered a consistent main-window shell pattern that improved initial workflow clarity.
- Reduced ambiguity in mapping/export/filter/grouping workflows via clearer labels, helper copy, and validation guidance.
- Added stronger safety and confirmation affordances for high-risk database operations.
- Completed a cross-screen consistency pass for interaction patterns and message tone.
- Reconciled revamp documentation to reflect final UI wording and navigation.

### Acceptance Criteria Status

- **Phase 1–7 (product-facing):** Complete.
- **Phase 8 (documentation alignment):** Complete.
- **Phase 9 (archive/closure):** Complete.

### Archive Location

The completed revamp planning set is archived under:

- [`docs/archive/2026/ui-revamp/`](./README.md)

## Scope Guardrail

No implementation code should start until these planning docs are reviewed and approved.
