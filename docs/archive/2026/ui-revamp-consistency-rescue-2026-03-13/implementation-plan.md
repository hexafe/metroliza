# UI Consistency Rescue — Implementation Plan

## Execution order (mandatory)

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

## Constraints and risks

- Native OS title-bar/menu rendering may remain partially platform-controlled.
- Where native menu strip remains bright and mismatched, prefer in-window actions for main workflow entry points.
- Avoid redesigning flows; focus on consistency and readability.

## Acceptance criteria

- No light shell around dark content in client area.
- Token usage centralized; no random one-off widget colors for core UI.
- Info panels and controls clearly differentiated.
- Helper/empty/subtitle text contrast is readable across screens.
- Priority screens receive the specified consistency fixes.
