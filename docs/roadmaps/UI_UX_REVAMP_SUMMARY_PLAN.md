# Metroliza UI/UX Revamp Summary Plan

Last updated: 2026-05-09

## Scope

This is the repo-local plan for a focused UI/UX revamp of the Metroliza desktop app and exported HTML dashboard. It combines the earlier branch-local UI plan with the May 2026 audit of `modules/main_window.py`, `modules/export_dialog.py`, `modules/parsing_dialog.py`, `modules/modify_db.py`, `modules/characteristic_mapping_dialog.py`, and `modules/csv_summary_dialog.py`.

Metroliza should remain a professional metrology workflow tool: quiet, dense, predictable, and fast to scan. The goal is not a decorative redesign, not a marketing shell, and not a broad rewrite. Changes should be incremental, tested, and compatible with the current `codex/report-metadata-redesign` branch.

## Current Branch Status

- 2026-05-09 branch `codex/metroliza-ui-ux-visual-revamp` started for the PyQt6 UI/UX and visual theme revamp.
- Shared UI helpers now live in `modules/ui_foundation.py`, with semantic visual tokens in `modules/ui_theme_tokens.py`.
- The first implementation slice covers the main window command center, parsing layout/readiness, worker progress/release notes, CSV Summary, Modify Database, filtering/grouping, export, Characteristic Matching, and HTML dashboard review polish.
- The 2026-05-09 release-fix pass completed the final pre-release UI blockers:
  CSV Summary moved under Tools and gained clearer footer actions; fast-then-enrich
  parsing now hands folder imports back to the main window for modeless
  enrichment; grouping Enter-key shortcuts were restored; progress animation is
  larger and temp-file-free; Help/manual links open GitHub-rendered docs.
- Focused integration validation for the slice: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_theme_tokens.py tests/test_ui_revamp_foundation_layout.py tests/test_main_window_metadata_ui.py tests/test_parsing_dialog_selection_flow.py tests/test_parsing_dialog_parent_none.py tests/test_dialog_parent_none_safety.py tests/test_export_dialog_layout.py tests/test_export_presets.py tests/test_filter_dialog_layout.py tests/test_filter_dialog_metadata.py tests/test_filter_dialog_delete_key.py tests/test_data_grouping_layout.py tests/test_data_grouping_filter_query.py tests/test_data_grouping_delete_key.py tests/test_data_grouping_error_paths.py tests/test_csv_summary_integration.py tests/test_csv_summary_utils.py tests/test_modifydb_update_statements.py tests/test_modifydb_shift_range_selection.py tests/test_modifydb_record_updates.py tests/test_characteristic_mapping_dialog.py tests/test_export_html_dashboard.py tests/test_release_metadata_sync.py -q` -> 184 passed, 3 subtests passed.
- Release metadata sync check is green: `python scripts/sync_release_metadata.py --check`.
- Main window metadata enrichment has already been deduplicated: the launcher button is gone, and enrichment is available from `Tools -> Enrich existing database metadata...` with visible status/progress/cancel controls.
- Parsing metadata mode has already moved to a single selector with fast, fast-then-enrich, and complete choices. The remaining parsing issue is layout elasticity and visible guidance, not the old dropdown-plus-checkbox model.
- Export now has active filter summaries and a Clear filters action. Remaining export work should refine hierarchy, path containment, validation, and accessibility while preserving the compact single-window design.
- Modify Database normalization has moved from three side-by-side tables to field tabs with search and occurrence counts. Remaining work is responsive sizing, table behavior, impact messaging, and undo clarity.
- Characteristic Matching is one of the stronger management-dialog patterns, but it still needs responsive sizing, table stretch behavior, and calmer action grouping.
- CSV Summary no longer has the largest release-blocking layout issues: it is
  launched from Tools, its main dialog uses clearer state rows and a primary
  `Create Summary` footer action, and preset/input/output safety behavior is
  covered by tests. Remaining future work is limited to deeper subdialog/table
  polish rather than release-blocking navigation.

## Audit Reconciliation

The external audit correctly identifies the app-wide pattern of fixed geometry, fixed table widths, dense forms, and overlong tooltips. Those findings should become shared implementation rules.

Some audit details are now stale on the current branch:

- The main window no longer contains a duplicated `Enrich Metadata` launcher button.
- Parsing no longer exposes separate metadata mode and enrichment controls.
- Export is no longer missing a filter summary/reset path.
- Modify Database normalization is no longer the old side-by-side three-table layout.

The plan below keeps those completed decisions and focuses on the remaining UX debt.

## Product UX Principles

1. Keep the main workflow visible: Parse reports, review or clean database values, match characteristic names when needed, then export.
2. Keep the export flow in one compact working window. Do not turn export into a wizard, full tabbed flow, or accordion-heavy interface.
3. Use progressive disclosure narrowly: collapsed advanced options, `Edit...` actions, status rows, and empty states. Do not hide primary decisions.
4. Use visible status over explanatory paragraphs: selected source, selected database, enrichment state, active filters, grouping state, output target, last result.
5. Tooltips are supplementary only. Vital instructions, constraints, and warnings must be visible in labels, validation text, status rows, or empty states.
6. Prefer elastic layouts: no fixed window-size assumptions for core dialogs, no fixed table columns where resize modes work better, and no layouts that waste extra space when expanded.
7. Use tabs only where the data model is naturally partitioned, such as filtering categories or Modify Database record categories.
8. Preserve metrology terminology, but reduce all-caps labels where they hurt scanability.
9. Design against real stress cases: long paths, many headers, many references, dense metadata, small screens, high-DPI displays, Windows packaging, and active OCR enrichment.
10. Keep long-running work visible, cancelable, and specific about current step and completion result.

## Visual Theme Direction

The PyQt6 revamp should make Metroliza feel like a precise metrology workbench:
compact, calm, readable, and visibly intentional without looking like a web app.

- Use a restrained light desktop palette: neutral background, white/soft-gray inputs
  and tables, charcoal text, muted secondary text, and one blue-teal primary accent.
- Use status colors only for meaning: green for complete/success, amber for warnings
  or attention, red for errors/destructive actions, and blue for active/info states.
- Prefer subtle borders, 4-6 px radius, compact spacing, clear focus rings, and
  selected-row highlights over decorative gradients or heavy custom skins.
- Keep native platform controls. Use QSS as a polish layer for buttons, inputs,
  tables, focus states, disabled states, progress bars, and status chips.
- Visual effects should be functional: hover feedback, focus rings, active state,
  compact progress animation, and readable empty/status rows. Do not add decorative
  blobs, glass effects, animated backgrounds, or oversized cards.

## Shared UI Rules

- Replace `setGeometry(...)` as a sizing strategy with minimum sizes, `resize(...)` for initial hints, `sizePolicy`, layout stretch, and bounded maximum sizes only where necessary.
- Tables should use `QHeaderView` resize modes, user-resizable columns, sensible minimums, and `Stretch` for the column most likely to contain long values.
- Path fields should be read-only, bounded, copyable where practical, and show the full path in tooltip or context action without expanding the whole dialog.
- Primary actions should be visually and structurally separated from secondary/destructive actions. Close/Cancel should not compete with Apply/Export/Parse.
- Inline validation should disable unsafe primary actions and explain what is missing near the relevant control.
- Every rewritten dialog must define tab order and accessible names/descriptions for important controls.
- Help/manual access should be available through help buttons or menu actions, not buried in long tooltips.
- Tooltips should be short microcopy. Delete redundant tooltips that repeat button text.

## Revamp Phases

### Phase 1: Shared UI Foundation

- Add or extend a small PyQt UI foundation for spacing, section labels, path fields, status chips, dividers, info buttons, button rows, and table header policies.
- Expand `ui_theme_tokens.py` from list selection colors into semantic tokens for status, warning, info, success, disabled text, borders, and subtle backgrounds.
- Add a minimal shared QSS layer through the PyQt UI foundation for restrained buttons, inputs, table headers, selected rows, progress bars, status chips, and focus states.
- Define reusable helpers for:
  - bounded path display,
  - section header rows,
  - compact key/value status rows,
  - primary/secondary/destructive button placement,
  - table resize policies,
  - accessible names and tab-order registration.
- Keep native platform controls. Avoid heavy QSS that fights Windows desktop expectations.
- Add offscreen layout probes for main window, parsing, export, filtering, grouping, Modify Database, CSV Summary, characteristic matching, progress dialog, and release notes.

### Phase 2: Main Window Command Center

- Replace the remaining vertical launcher stack with a compact workflow command surface:
  - primary actions: Parse Reports, Export Workbook.
  - preparation actions: Modify Database, Match Characteristic Names.
  - utility actions: Tools menu CSV Summary and metadata enrichment, with visible
    enrichment status row when active or recently completed.
- Remove the fixed `300 x 150` window assumption. Let the command surface breathe on large screens and remain usable on small displays.
- Add persistent context rows for selected source/database and enrichment status.
- Keep only one major database workflow dialog active at a time, but explain close/switch behavior through visible status text when needed.
- Keep About, Release notes, Help, and metadata enrichment in menus. Do not hide current workflow state in menus.

### Phase 3: Parsing And OCR UX

- Keep Fast import as the default.
- Keep the single metadata mode selector, but review the copy so it is shorter and user-facing:
  - Fast import: light metadata, no OCR.
  - Fast import, then enrich metadata: import first, OCR metadata pass after.
  - Complete import: OCR during parsing, slower.
- Replace parsing fixed geometry with elastic layout and a realistic initial size.
- Move critical steps out of tooltips: visible source row, database row, metadata mode row, and parse readiness/validation text.
- Add completion summary details: reports parsed, reports skipped, metadata enrichment queued or completed, warnings, output database.
- Preserve visible progress and cancel state for parsing and background enrichment.

### Phase 4: Export Dialog Refinement

- Preserve the current compact single-window export layout.
- Refine visual hierarchy around the export decision path:
  - preset and output level,
  - database and output workbook,
  - filters and grouping summaries,
  - chart/group-analysis options,
  - optional outputs,
  - advanced options.
- Keep active filter summaries and Clear filters. Add equivalent clear/reset affordance for grouping if missing.
- Ensure essential constraints are visible, not only tooltip text: missing database, missing output workbook, unavailable output folder, invalid numeric fields.
- Keep advanced options collapsed and verify expanded state at small desktop sizes.
- Keep path fields bounded and resistant to long-path width expansion.
- Keep export usable while background metadata enrichment is active, with the current-database-state warning visible.

### Phase 5: Filtering And Grouping

- Filtering:
  - Keep the Measurement, Report metadata, and Source tabs.
  - Add or preserve active counts per category and a compact whole-filter summary.
  - Keep Clear filters and Apply visible in the footer.
  - Ensure date range, NOK-only, and parser/source filters are visible enough to discover.
- Grouping:
  - Replace fixed-width list panes with stretch-aware panes and minimum widths.
  - Add group counts and selected-reference/selected-part summaries.
  - Split actions by context: create/add, rename/delete group, remove from selected group, apply/clear grouping.
  - Preserve keyboard and double-click shortcuts, but make common actions visible.

### Phase 6: Modify Database

- Remove the fixed `1100 x 650` sizing assumption. Use resize hints, minimum size, and stretch factors.
- Replace fixed normalize table widths with header resize policies and user-resizable columns.
- Keep Normalize values as field tabs unless a single field selector proves simpler after testing. The current field tabs are acceptable because the data model is naturally partitioned.
- Keep search above each normalization table.
- Show impact before apply: field name, old value, new value, occurrence count, and affected scope.
- Make Apply confirmation explicit and concise.
- Revisit Undo before exposing it as a primary action. If undo stays disabled or hidden, explain the current safety model through confirmation and transaction behavior.
- Keep Report records and Measurement rows functional; do not refactor their data logic unless required for layout consistency.

### Phase 7: CSV Summary Revamp

- 2026-05-09 release-fix status: main-dialog blockers are complete. CSV Summary
  is under Tools, the old `Summary configuration` header gap is gone, `Create
  Summary` is the primary/default footer action, clearing presets is confirmed,
  CSV/XLSX path handling is explicit, and worker failures no longer appear as
  cancellations.
- Redesign CSV Summary around state rows:
  - input CSV selected/not selected,
  - selected index and data columns,
  - spec limits configured,
  - plot options,
  - output file,
  - primary Create Summary action.
- Replace small fixed dialog geometries in the main dialog and subdialogs with elastic layouts.
- Make column/spec selection dialogs table/list surfaces that resize naturally.
- Replace generic labels like `START` or terse OK-only flows with specific action labels.
- Surface essential constraints inline: missing CSV, missing output, no data columns, invalid spec limits.
- Keep presets, but show what a preset changes before applying it.

### Phase 8: Characteristic Matching

- Keep Characteristic Matching as the reference management-dialog pattern: table, empty state, Add/Edit/Delete, Import/Export, Close.
- Remove the fixed `900 x 600` assumption. Use resize hints and table stretch policies.
- Group actions into table actions, import/export actions, and close.
- Make alias scope and collision warnings visible before save.
- Ensure table columns resize with window growth and long names remain readable.

### Phase 9: Progress, Errors, Release Notes, Help

- Replace spinner-first progress with a compact text-first progress component:
  - current step,
  - detail line,
  - progress bar,
  - cancel state,
  - final summary.
- Keep progress dialogs modeless where the workflow allows it and modal only where user action would corrupt state.
- Make error messages actionable. Put technical details behind expandable/copyable diagnostics.
- Keep in-app release notes short and non-technical.
- Keep manuals as reference. Critical first-use guidance belongs in contextual empty states and status rows.

### Phase 10: HTML Dashboard Review UX

- Preserve workbook parity and PNG/Plotly click-routing behavior.
- Keep rich chart details, but use responsive summary grids instead of long vertical detail blocks.
- Make metric navigation sticky or easy to return to.
- Keep Auto/Light/Dark theme support for the dashboard.
- Add dashboard visual regression fixtures for representative histogram, trend, group-analysis, PNG, and Plotly cases.

## Validation Plan

- Run offscreen PyQt layout probes for each core dialog at small and normal desktop sizes.
- Include long paths, many filter values, many groups, empty database, active enrichment, and no selected files.
- Add keyboard tab-order checks for rewritten dialogs.
- Add tooltip audits for rewritten dialogs:
  - no tooltip may contain the only copy of a required instruction,
  - no tooltip should be a paragraph of operational guidance,
  - repeated button-label tooltips should be removed.
- Add table resize tests for Modify Database, Characteristic Matching, CSV Summary subdialogs, and Grouping.
- Keep existing focused tests and add equivalents as surfaces are rewritten:
  - `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_export_dialog_layout.py tests/test_filter_dialog_layout.py -q`
  - add layout tests for main, parse, grouping, Modify Database, CSV Summary, progress, and characteristic matching.
- For dashboard:
  - run dashboard tests through the full export thread path, not only helper rendering,
  - inspect generated HTML for Plotly/PNG route separation and responsive detail rendering.
- On Windows/package work:
  - launch the actual app and verify first window, workflow windows, file dialogs, and progress dialogs.

## Suggested Implementation Order

1. Shared UI foundation and layout/tooltip/accessibility test harness.
2. Main window command center and responsive sizing.
3. Parsing responsive cleanup and visible validation copy.
4. Progress/status component cleanup.
5. CSV Summary revamp, because it is isolated and still visibly old.
6. Modify Database sizing/table polish on top of the current normalization tab work.
7. Grouping dialog revamp.
8. Export polish pass on top of the current compact layout and filter summary work.
9. Characteristic Matching responsive/table/action grouping pass.
10. HTML dashboard review UX polish.
11. Docs/manual updates and in-app release-note summary.

## Non-Goals

- Do not redesign export as a wizard.
- Do not make export a full tabbed or accordion-driven flow.
- Do not remove rich dashboard/chart detail to make the page shorter.
- Do not collapse PNG and Plotly dashboard interactions into one generic handler.
- Do not make native chart visuals diverge from the established matplotlib/workbook parity contract.
- Do not introduce a heavy custom widget framework before the shared PyQt foundation proves necessary.
- Do not broaden this into unrelated parser/export/data-model refactors.
