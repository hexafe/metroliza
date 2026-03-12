# UI Revamp Implementation Plan (Active)

This plan defines required iteration order, per-screen must-fix scope, and completion gates.

## Research-Driven Dark Theme Decision

The dark theme baseline uses graphite/dark-gray instead of pure black to preserve depth hierarchy, maintain clear surface separation, and improve long-session reading comfort.

## Required Iteration Order

1. Main Window
2. Characteristic Mapping
3. Export
4. Grouping
5. Filter
6. Modify DB
7. Global consistency pass
8. Docs alignment + QA evidence
9. Archive move

## Per-Screen Must-Fix Scope

### Main Window
- Audit entry-page information hierarchy and navigation cues.
- Redesign title + primary CTA placement to establish shared screen pattern.
- Add/standardize global status area for loading, success, and error feedback.
- Validate keyboard/focus order and first-load clarity.

### Characteristic Mapping
- Inventory confusing labels and ambiguous control names.
- Redesign mapping table/form layout for scanability.
- Add clear inline validation for unmapped/duplicate/conflicting values.
- Improve helper copy for batch actions and edge-case handling.

### Export
- Rework export preflight section (readiness checks + missing requirements).
- Group output options into logical sections with defaults.
- Improve confirmation and post-export summary messaging.
- Add visible troubleshooting guidance for common export failures.

### Grouping
- Improve discoverability of create/merge/split/rename actions.
- Add or refine preview state before group changes are applied.
- Update confirmation language for destructive group operations.
- Preserve selection context across multi-step grouping edits.

### Filter
- Make active filters persistent and always visible.
- Improve add/remove/reset interactions for compound filters.
- Clarify operator semantics (AND/OR) in UI labels/helper text.
- Revise empty-state copy with quick recovery actions.

### Modify DB
- Classify DB actions by risk level and align warning severity.
- Add impact previews before high-risk operations.
- Improve confirmation flow for destructive database changes.
- Ensure completion/error states include next-step guidance and audit hints.

## Global Rules and Completion Criteria

Required before closure:
- informational panels are non-clickable and receive **no hover/pressed treatment**,
- clickable controls implement hover/focus/pressed/disabled states,
- accent strategy is preserved (blue primary, green success-only, violet not primary),
- consistency pass verifies token usage, border/spacing/text hierarchy, button hierarchy, and hover/focus treatment.

## Completion Summary (2026-03-12)

Requested planning-doc updates for dark-theme decisioning, palette tokens, readability standards, global interaction rules, accent policy, iteration order, and closure criteria are complete. All checklists were marked done and the active folder was archived with index updates.
