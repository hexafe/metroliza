# UI Revamp Consistency Rescue (Graphite Dark)

Status: **Completed (2026-03-13)**

This pass fixed implementation consistency and readability without introducing new product features.

## Core diagnosis (before)

1. Mixed light shell + dark inner widgets.
2. No reliable single source of truth for tokens.
3. Low contrast helper/subtitle/empty-state text.
4. Informational panels and controls not visually distinct.
5. Several windows still effectively old UI.
6. Main menu/title-bar chrome mismatch with dark content.

## Direction taken

- **Graphite dark theme across the full app client area**
- No mixed light roots with dark nested content

## What shipped

- Central token system applied across target screens.
- Role separation enforced (shell, cards, info panels, inputs, controls, lists/tables, helper text).
- Screen-by-screen consistency rescue completed for priority windows.
- Contrast/readability pass completed for helper, subtitle, status, and empty-state text.
- Main-window chrome/menu mismatch mitigated where app-controlled.

## Before/after consistency outcomes (concise)

- **Before:** inconsistent shell/surface treatment, weak text contrast, and ambiguous panel-vs-control styling.
- **After:** cohesive graphite-dark surfaces, token-driven styling, readable secondary text, and clearer interaction hierarchy.
- **Known platform-limited item:** native OS menu/title strips remain partially outside app styling control; in-window themed actions are the supported mitigation.

## Final token strategy for future UI work

Follow this source-of-truth chain for all future UI changes:

1. `design-system.md` for token values and semantic roles.
2. Shared theme/token implementation in code, kept aligned to the spec.
3. `screen-by-screen-review.md` for consistency/contrast validation before merge.

Do not introduce one-off core colors when a design-system token exists.

## Canonical docs

- [implementation-plan.md](./implementation-plan.md)
- [todo.md](./todo.md)
- [screen-by-screen-review.md](./screen-by-screen-review.md)
- [design-system.md](./design-system.md)
