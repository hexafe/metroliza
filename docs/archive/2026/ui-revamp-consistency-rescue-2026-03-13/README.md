# UI Revamp Consistency Rescue (Graphite Dark)

Status: **In progress (consistency rescue pass)**

This pass is focused on fixing implementation consistency, not adding features.

## Core diagnosis

1. Mixed light shell + dark inner widgets.
2. No reliable single source of truth for tokens.
3. Low contrast helper/subtitle/empty-state text.
4. Informational panels and controls not visually distinct.
5. Several windows still effectively old UI.
6. Main menu/title-bar chrome mismatch with dark content.

## Hard decision

Adopt one direction across the whole client area:

- **Graphite dark theme everywhere**
- No mixed light roots with dark nested content

## Mandatory workstreams

- Central token system applied globally.
- Role separation (shell, cards, info panels, inputs, buttons, lists/tables, helper text).
- Contrast/readability pass.
- Screen-by-screen consistency fixes.
- Main-window chrome/menu mismatch mitigation.

## Canonical docs

- [implementation-plan.md](./implementation-plan.md)
- [todo.md](./todo.md)
- [screen-by-screen-review.md](./screen-by-screen-review.md)
- [design-system.md](./design-system.md)
