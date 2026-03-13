# UI Consistency Rescue — Implementation Plan

Status: **Executed and closed (2026-03-13)**

## Planned execution order (was mandatory)

1. Update docs (this folder)
2. Refine central theme system
3. Apply full dark client-area styling globally
4. Fix progress dialogs
5. Fix Characteristic Name Matching
6. Fix Review and Rename Data
7. Fix CSV Summary
8. Fix main dashboard/menu consistency
9. Polish Parsing / Export / Grouping / Filtering / About / Release Notes
10. Global consistency pass
11. Final docs update and move this folder to archive

## What was delivered

- All 11 planned steps were completed.
- The implementation standardized UI styling on the graphite-dark direction across target screens and dialogs.
- Contrast/readability improvements were applied for helper/subtitle/empty-state text and informational panel content.
- Main dashboard/menu mismatch was mitigated within app-controlled regions.

## Deviations and rationale

- **No full native menu-strip restyle:** OS-controlled title-bar/menu areas were not force-restyled because behavior is platform-limited and outside reliable cross-platform client-area control.
- **Mitigation used instead:** primary workflow actions and critical affordances remain in themed, app-controlled surfaces to preserve visual consistency.

## Final token strategy (source of truth)

Future UI work should follow this order:

1. **Primary source:** `docs/archive/2026/ui-revamp-consistency-rescue-2026-03-13/design-system.md`
2. **Implementation anchor:** shared UI theme/token modules in application code (align values and semantics with the design-system spec)
3. **Review checklist:** `screen-by-screen-review.md` to validate role separation and contrast per screen

Rules for new UI changes:

- Use centralized tokens only (no one-off ad hoc widget colors for core surfaces/text/borders/states).
- Keep role separation explicit: shell, surfaces, info panels, inputs, controls, lists/tables.
- Treat native OS chrome differences as constraints; mitigate in app-controlled UI rather than per-platform hacks.

## Constraints and risks (final)

- Native OS title-bar/menu rendering may remain partially platform-controlled.
- Where native menu strip remains bright and mismatched, prefer in-window actions for main workflow entry points.
- Avoid redesigning flows; focus on consistency and readability.

## Acceptance criteria result

- ✅ No light shell around dark content in client area.
- ✅ Token usage centralized; random one-off core widget colors removed/avoided.
- ✅ Info panels and controls clearly differentiated.
- ✅ Helper/empty/subtitle text contrast is readable across screens.
- ✅ Priority screens received the specified consistency fixes.
