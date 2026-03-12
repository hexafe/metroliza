# Screen-by-Screen Corrective Review

Status: **Active planning input**

## Research-Driven Dark Theme Decision

All reviewed screens use graphite/dark-gray layering instead of pure black to preserve hierarchy depth and reduce high-contrast fatigue during long analysis sessions.

## Iteration Order (Required)

1. Main Window
2. Characteristic Mapping
3. Export
4. Grouping
5. Filter
6. Modify DB
7. Global consistency pass
8. Docs alignment + QA evidence
9. Archive move

## 1) Main Window — Must-Fix Checklist

- [x] Audit entry-page information hierarchy and navigation cues.
- [x] Redesign title + primary CTA placement to establish shared screen pattern.
- [x] Add/standardize global status area for loading, success, and error feedback.
- [x] Validate keyboard/focus order and first-load clarity.

## 2) Characteristic Mapping — Must-Fix Checklist

- [x] Inventory confusing labels and ambiguous control names.
- [x] Redesign mapping table/form layout for scanability.
- [x] Add clear inline validation for unmapped/duplicate/conflicting values.
- [x] Improve helper copy for batch actions and edge-case handling.

## 3) Export — Must-Fix Checklist

- [x] Rework export preflight section (readiness checks + missing requirements).
- [x] Group output options into logical sections with defaults.
- [x] Improve confirmation and post-export summary messaging.
- [x] Add visible troubleshooting guidance for common export failures.

## 4) Grouping — Must-Fix Checklist

- [x] Improve discoverability of create/merge/split/rename actions.
- [x] Add or refine preview state before group changes are applied.
- [x] Update confirmation language for destructive group operations.
- [x] Preserve selection context across multi-step grouping edits.

## 5) Filter — Must-Fix Checklist

- [x] Make active filters persistent and always visible.
- [x] Improve add/remove/reset interactions for compound filters.
- [x] Clarify operator semantics (AND/OR) in UI labels/helper text.
- [x] Revise empty-state copy with quick recovery actions.

## 6) Modify DB — Must-Fix Checklist

- [x] Classify DB actions by risk level and align warning severity.
- [x] Add impact previews before high-risk operations.
- [x] Improve confirmation flow for destructive database changes.
- [x] Ensure completion/error states include next-step guidance and audit hints.

## Completion Criteria

A screen is only considered done after global consistency pass confirms:
- tokens are used consistently,
- border/spacing/text hierarchy are consistent,
- button hierarchy is consistent,
- hover/focus behavior is consistent.
