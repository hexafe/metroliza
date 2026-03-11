# UI Revamp (Active Planning Cycle)

Status: **Active (planning)**  
Owner: UI revamp execution stream  
Last updated: 2026-03-11

This folder is the active source of truth for the current UI revamp cycle. It supersedes previous archived planning sets except where historical context is explicitly referenced.

## Corrective Review Summary (New)

A corrective review of the prior cycle identified that we need stronger lockstep between design rules and execution evidence. This cycle addresses those gaps by:

- locking a refined design system (color, spacing, radius, interaction states, and typography) before feature-phase work starts,
- carrying forward must-fix screen items as explicit non-negotiable scope,
- enforcing mandatory implementation order with phase-level acceptance criteria,
- requiring closure evidence before archival.

## Canonical Documents

1. [Implementation Plan](./implementation-plan.md)
2. [Execution TODO Tracker](./todo.md)
3. [Screen-by-Screen Corrective Review](./screen-by-screen-review.md)
4. [Design System (Refined Baseline)](./design-system.md)

## Mandatory Phase Order

Implementation must proceed in this order:

1. Foundation + shared shell
2. Characteristic mapping
3. Export
4. Grouping
5. Filter
6. Modify DB
7. Global consistency pass
8. Docs alignment + QA evidence
9. Archive move (closure only)

## Completion and Archive Protocol

After implementation completion:

1. append a completion summary to this README and `implementation-plan.md`,
2. confirm all phase acceptance criteria are met,
3. move this folder to `docs/archive/<year>/ui-revamp-<date>/`,
4. update `docs/archive/<year>/README.md` and `docs/README.md` links.

Historical references:
- `docs/archive/2026/ui-revamp/`
- `docs/archive/2026/ui-revamp-closure-2026-03/`
