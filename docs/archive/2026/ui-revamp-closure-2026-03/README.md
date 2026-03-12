# UI Revamp (Finalized and Archived)

This folder is the finalized planning and execution record for the completed UI revamp cycle.

## Canonical Documents

1. [Design System (Locked Baseline)](./design-system.md)
   - Visual tokens (colors, spacing, radii, borders, shadows, typography)
   - Button hierarchy
   - Cards/panels rules
   - Input rules and full state matrix
   - Table/list rules
   - Helper text and empty state behavior
   - Interaction states (hover/focus/pressed/disabled)
   - Per-screen layout rules (main window, characteristic matching, export, grouping, filter, modify DB)

2. [Phase Tracker and Mandatory Implementation Order](./phase-tracker.md)
   - Ordered implementation phases and dependencies
   - Exit criteria per phase
   - Progress and blocking notes

3. [Execution TODO Checklist](./todo.md)
   - Practical implementation checklist by screen
   - Cross-screen consistency and closure tasks

## Mandatory Implementation Order

Implementation must proceed in this order and may not skip dependencies:

1. Foundation + shared shell
2. Characteristic matching
3. Export
4. Grouping
5. Filter
6. Modify DB
7. Global consistency pass
8. Docs alignment and QA evidence
9. Archive move (closure only)

## Guardrails

- Do **not** archive active revamp docs during execution.
- Archive move is a closure step only after implementation and consistency acceptance are complete.
- Any temporary deviation from `design-system.md` must be documented in `phase-tracker.md`.

## Historical Reference

Previous completed planning artifacts remain available for historical context at:

- [`docs/archive/2026/ui-revamp-closure-2026-03-12/`](../ui-revamp-closure-2026-03-12/README.md)


## Closure Update

This active set has been finalized after the Export/Grouping/Filter/Modify DB consistency pass and is ready for archive move.
