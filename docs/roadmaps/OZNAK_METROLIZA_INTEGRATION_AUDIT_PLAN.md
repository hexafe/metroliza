# Oznak to Metroliza Integration Audit and Plan

Created: 2026-05-10
Last updated: 2026-05-10 after non-technical GUI workflow gap review

## Execution Tracker

Current branch: `codex/oznak-metroliza-integration`

Current implementation state:

- Completed: optional Metroliza adapter scaffold, additive industrial cache schema, repository, set-based report-link materialization, export option, export diagnostics, Tools-menu source/sync orchestrator, separate industrial filter and grouping dialogs, cached industrial workbook export with summaries/charts, release-hygiene guards, and focused/full verification.
- Gap identified by UX review: the previous dialog was not enough for a non-technical end user because it only initialized the cache and refreshed local links. It did not let the user create a database source, enter credentials, test the connection, sync rows, cancel a running sync, or inspect per-source Oznak diagnostics.
- Updated Oznak status from `/home/hexaf/Projects/oznak/docs/OZNAK_METROLIZA_STATUS.md`: Oznak reports implemented package contracts, `fetch_records()`, `FetchResult`, `MappingCredentialProvider`, `CancellationToken`, progress/cancel/timeout diagnostics, package-native FastAPI, typed `connect_timeout_seconds` and `query_timeout_seconds`, release-process docs, `210 passed` on the full suite, focused release-readiness checks passing, and Ruff passing. Metroliza can implement against this contract through the optional adapter. Pinning can use an explicit accepted Git commit after review or wait for a formal release tag/version policy.

Active acceptance target for this iteration:

1. A non-technical Metroliza user can open `Tools > Industrial data`, create or select an Oznak source profile, enter DB type/host/port/database/table/columns, enter credentials for the current session, and save the non-secret source metadata.
2. The user can run `Test connection` from the dialog and receive a compact success/error message with Oznak diagnostics, without writing fetched data into the cache.
3. The user can run `Sync now`; Metroliza performs the Oznak fetch on a background `QThread`, persists rows into the industrial cache, records the sync run, materializes report links, and updates visible counts.
4. The user can cancel a running sync; cancellation is forwarded to Oznak when available and the local sync run is finished as `cancelled` or `failed` without corrupting cached rows.
5. Export remains deterministic: no live database queries run during export, and industrial context is added only from cached rows when the user explicitly enables the export option.
6. Credentials are never stored in the report DB, docs, tests, logs, or release artifacts; non-secret connection metadata may be stored locally in the Metroliza SQLite DB so the profile can be reused.
7. Focused tests cover adapter contract construction, repository persistence of non-secret source metadata, GUI source setup/test/sync state, export unchanged-by-default behavior, release hygiene, and failure redaction.

Major-step update policy:

- After every implementation slice below, update this `Execution Tracker` with status, validation commands, failures, and next steps.
- Keep Oznak work and Metroliza work separated. Metroliza imports only the public `oznak` namespace and only inside `modules/oznak_adapter.py`.

### 2026-05-10 Update: End-User Source Setup Slice

Implemented:

- Added non-secret source connection metadata (`host`, `port`, `database_name`) to `industrial_source_profiles` with additive migration support for earlier local cache tables.
- Extended `IndustrialDataRepository.upsert_source_profile()` and listing to persist reusable source setup while keeping usernames/passwords out of SQLite.
- Extended `modules/oznak_adapter.py` to build current Oznak `DatabaseProfile`, `FetchRequest`, `MappingCredentialProvider`, and cancellation token objects through the lazy adapter boundary.
- Added stable row-hash fallback keys for rows without an explicit source primary key.
- Replaced the status-only industrial dialog with an end-user workflow: source selection, source form, credentials entry, save source, test connection, sync now, cancel, cache initialization, link refresh, counts, and visible progress/details.

Validation:

- `python -m py_compile modules/industrial_data_dialog.py modules/industrial_data_repository.py modules/industrial_data_schema.py modules/oznak_adapter.py`: passed.
- `python -m ruff check modules/industrial_data_dialog.py modules/industrial_data_repository.py modules/industrial_data_schema.py modules/oznak_adapter.py tests/test_oznak_adapter.py tests/test_industrial_data_schema_repository.py`: passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_oznak_adapter.py tests/test_industrial_data_schema_repository.py tests/test_industrial_join_service.py tests/test_export_industrial_context.py -q`: `12 passed`.

Next step:

- Add focused tests for the new Oznak contract helper and the PyQt dialog source-save/test/sync state using a mocked adapter, then update user docs and run the broader quality suite.

### 2026-05-10 Update: Focused Coverage Slice

Implemented:

- Added adapter tests that prove Metroliza builds the current Oznak public `DatabaseProfile`, `FetchRequest`, `MappingCredentialProvider`, cancellation-token path, and progress callback shape without importing Oznak outside the adapter.
- Added adapter coverage for deterministic row-hash fallback keys when the industrial source lacks an explicit key column.
- Added repository assertions for persisted non-secret host/port/database metadata and credential-column absence.
- Added PyQt/dialog-thread coverage for saving source metadata without storing credentials, syncing mocked Oznak rows into the cache, finishing a sync run, and proving `Test connection` does not persist fetched rows.

Validation:

- First run exposed a Qt test-harness issue: `QApplication` was released before dialog construction, causing a runtime abort. Fixed by retaining the application object in the test module.
- `python -m ruff check modules/industrial_data_dialog.py modules/oznak_adapter.py modules/industrial_data_repository.py tests/test_oznak_adapter.py tests/test_industrial_data_dialog.py tests/test_industrial_data_schema_repository.py`: passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_oznak_adapter.py tests/test_industrial_data_schema_repository.py tests/test_industrial_data_dialog.py -q`: `13 passed`.

Next step:

- Update user-facing docs to explain the new `Tools > Industrial data` workflow and then run broader export/main-window/schema/release checks.

### 2026-05-10 Update: Oznak Finished-Session Note Refresh

Re-read `/home/hexaf/Projects/oznak/docs/OZNAK_METROLIZA_STATUS.md` after the Oznak Codex session finished.

Current Oznak note says:

- `python -m pytest -q` passes with `210 passed`.
- `python -m pytest -q tests/test_release_readiness.py tests/test_roadmap.py` passes with `8 passed`.
- `python -m ruff check .` passes.
- `oznak.api:app`, package CLI/TUI, typed profile timeouts, release process docs, and opt-in integration marker now exist.
- Oznak worktree is still dirty and the status note itself is untracked locally; the latest committed baseline remains `ed677af Add CLI integration coverage` on branch `roadmap`.

Metroliza decision:

- Continue using the optional lazy adapter and current public `oznak` contract shape.
- Do not add a hard Oznak dependency or commit pin in Metroliza until the user accepts an Oznak commit/tag for consumption.
- Keep live database access only in explicit source test/sync actions, never in export hot paths.

### 2026-05-10 Update: User Documentation Slice

Implemented:

- Updated `docs/user_manual/main_window.md` so non-technical users see the full workflow from the industrial data Tools entry: create/select source, enter database connection fields, enter session credentials, save, test, sync, cancel, and refresh links.
- Updated `docs/user_manual/export_overview.md` to make the export dependency explicit: industrial context uses only cached rows created by the Tools workflow and never connects to plant databases during workbook creation.

Next step:

- Run broad focused checks around main-window/export/schema/release hygiene, then full compile/test checks, fix findings, and refresh this tracker.

### 2026-05-10 Update: Sidecar Audit Fix Slice

Implemented after sidecar review:

- Open `IndustrialDataDialog` instances now update when `MainWindow.set_db_file()` changes the selected Metroliza database.
- Release hygiene now checks blocked prefixes and filenames case-insensitively and normalizes Windows-style separators.
- Industrial schema join modes now match the implemented join service: `exact` and `time_window` only. `fuzzy` stays out until it is implemented.
- Adapter row mapping now also emits repository-canonical fields such as `source_record_key`, `batch_lot`, `operator_name`, and `process_status`, while preserving the compatibility aliases already covered by tests.
- Adapter diagnostics now redact warning/error strings captured from Oznak `FetchResult`.
- Column mappings can now come from Oznak profile metadata as well as direct Metroliza profile attributes.

Validation:

- `python -m ruff check modules/main_window.py modules/industrial_data_dialog.py modules/industrial_data_schema.py modules/industrial_join_service.py modules/oznak_adapter.py scripts/check_release_hygiene.py tests/test_main_window_metadata_ui.py tests/test_release_hygiene.py tests/test_industrial_join_service.py tests/test_oznak_adapter.py tests/test_industrial_data_dialog.py tests/test_industrial_data_schema_repository.py`: passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_oznak_adapter.py tests/test_industrial_data_schema_repository.py tests/test_industrial_data_dialog.py tests/test_industrial_join_service.py tests/test_main_window_metadata_ui.py tests/test_release_hygiene.py -q`: `25 passed`.

Next step:

- Run broader export/report-schema/query-plan checks, then compile/release checks and the full suite.

### 2026-05-10 Update: Broader Export/Schema Check Slice

Validation:

- `python -m ruff check modules tests scripts`: passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_export_industrial_context.py tests/test_export_presets.py tests/test_report_query_service.py tests/test_report_schema_repository.py tests/test_schema_index_query_plans.py tests/test_main_window_metadata_ui.py tests/test_release_hygiene.py -q`: `76 passed`.

Next step:

- Run compileall, release metadata/hygiene checks, and then the full test suite.

### 2026-05-10 Update: Final Verification Slice

Implemented after the first final suite:

- Added optional Oznak collection to PyInstaller and Nuitka packaging paths when `oznak` is installed in the build environment.
- Kept Oznak optional: no local path dependency and no hard pin until an accepted Oznak commit/tag is chosen.
- Added packaging tests proving optional Oznak collection stays wired.

Validation:

- `python -m compileall -q -x '^\./\.git/' .`: passed.
- `python -m ruff check modules tests scripts packaging`: passed.
- `python scripts/sync_release_metadata.py --check`: passed.
- `python scripts/check_release_hygiene.py`: passed before and after the full suite.
- `QT_QPA_PLATFORM=offscreen python -m pytest -q`: `1302 passed, 32 skipped, 7 warnings, 60 subtests passed`.

Current completion status:

- Metroliza-side Oznak integration is functionally complete for this branch: end-user source setup, session credentials, connection test, background sync, cancellation, cached industrial records, link materialization, optional export context, docs, release hygiene, and test coverage are implemented.
- Oznak is still optional at Metroliza runtime. This branch does not hard-pin Oznak because the Oznak repository note says pinning can use an accepted commit after review or wait for a release tag/version policy.
- No live database query runs during export; export uses only cached industrial rows.

### 2026-05-10 Update: Reference-Scoped Fetch Correction

Issue found:

- `Sync now` previously relied only on row limit/timeout, which is not safe for real production-line tables with years of history.

Implemented:

- Added `Reference column` and `References` controls to the industrial data dialog.
- Added `Use DB references` to populate the reference list from the selected Metroliza DB when desired.
- `Sync now` now refuses to run without at least one reference.
- `Test connection` remains available without references and performs only the one-row connectivity check.
- Metroliza passes references into Oznak as `QueryFilter(column=<reference column>, operator="IN", value=(...))`.
- Sync-run filter diagnostics store reference column and count, not the full reference list.

Validation:

- `python -m ruff check modules/industrial_data_dialog.py modules/oznak_adapter.py tests/test_oznak_adapter.py tests/test_industrial_data_dialog.py`: passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_oznak_adapter.py tests/test_industrial_data_dialog.py -q`: `11 passed`.

Remaining product layer:

- Industrial-only filtering beyond references, industrial grouping, and industrial-driven charts still need separate UI and export/dashboard work. The current branch now has safe reference-scoped fetch, local cache, links, and export context.

### 2026-05-10 Update: Chunking And Paste-Speed Fetch Scope

Implemented:

- Reference paste parsing now accepts comma, semicolon, whitespace, tab, and newline separated lists and de-duplicates values in input order.
- Oznak sync now batches reference lists by default so large pasted lists do not create one unbounded `IN (...)` clause.
- Oznak sync now prefers `fetch_records_chunked()` only for unbounded fetches when the package exposes it and the source profile has a pagination/record-key column.
- Normal `fetch_records()` remains the path when a sync/test limit is passed, when chunked fetch is unavailable, or when no pagination column is configured.
- Adapter diagnostics record fetch strategy, chunk size, reference batch size, reference batch count, filter column, and reference count.

Validation:

- `python -m ruff check modules/oznak_adapter.py modules/industrial_data_dialog.py tests/test_oznak_adapter.py tests/test_industrial_data_dialog.py`: passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_oznak_adapter.py tests/test_industrial_data_dialog.py -q`: `13 passed`.

### 2026-05-10 Update: Dialog Separation, Industrial Export, And Charts

Audit finding:

- Main Metroliza export workflows do not put every control in one launcher surface. `ExportDialog` opens a separate `FilterDialog` for filtering and a separate `DataGrouping` dialog for grouping. The Oznak integration was mixing source setup, reference filtering, sync, grouping intent, export intent, and chart intent in one dialog, which would not scale for production-line database data.

Plan:

- Keep `IndustrialDataDialog` as the source/sync/status orchestrator.
- Move Oznak fetch scope into a modal `IndustrialFilterDialog`, with quick reference paste and database-reference import.
- Move cached industrial grouping into a modal `IndustrialGroupingDialog`, using production-line fields instead of CMM measurement fields.
- Keep live Oznak fetches scoped by the industrial filter, using reference batching and chunked Oznak fetch where available.
- Add a cached industrial export service that writes production-line rows, grouped summaries, diagnostics, and Excel charts from the Oznak cache, independent from the CMM report export path.

Implemented:

- `modules/industrial_filter_dialog.py`
  - Separate Oznak fetch-filter dialog.
  - Quick parser for comma, semicolon, whitespace, tab, and newline pasted reference lists.
  - `Use DB references` reads references from the selected Metroliza database.
- `modules/industrial_grouping_dialog.py`
  - Separate industrial grouping dialog.
- `modules/industrial_workflow_state.py`
  - Pure non-Qt state for the industrial reference filter and production-line grouping selection.
  - Keeps service/tests importable under lightweight Qt stubs and avoids coupling export logic to PyQt dialogs.
- `modules/industrial_export_service.py`
  - Loads cached Oznak industrial rows scoped by the industrial filter.
  - Builds grouped summaries from `IndustrialGroupingState`.
  - Writes an Excel workbook with `Industrial Data`, `Industrial Summary`, `Diagnostics`, and optional `Industrial Charts`.
- `modules/industrial_data_dialog.py`
  - Refactored into a source/sync/status orchestrator.
  - Opens filter and grouping dialogs instead of embedding those controls in the source form.
  - Uses the selected filter for Oznak sync.
  - Can export cached industrial data with grouped summaries and charts.

Validation:

- First full-suite rerun exposed a collection problem: `industrial_export_service` imported filter/grouping state through PyQt dialog modules, which broke tests that install lightweight Qt stubs. Fixed by moving workflow state into `modules/industrial_workflow_state.py`.
- `python -m ruff check modules/industrial_data_dialog.py modules/industrial_filter_dialog.py modules/industrial_grouping_dialog.py modules/industrial_export_service.py tests/test_industrial_data_dialog.py tests/test_industrial_export_service.py`: passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_data_dialog.py tests/test_industrial_export_service.py tests/test_oznak_adapter.py -q`: `15 passed`.
- `python -m compileall -q -x '^\./\.git/' .`: passed.
- `python -m ruff check modules tests scripts packaging`: passed.
- `python scripts/sync_release_metadata.py --check`: passed.
- `python scripts/check_release_hygiene.py`: passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest -q`: `1305 passed, 34 skipped, 7 warnings, 60 subtests passed`.

Current completion status:

- Oznak filtering now follows Metroliza convention: the source dialog only launches filter editing, and actual filter input lives in a dedicated modal dialog.
- Oznak grouping now follows Metroliza convention: production-line grouping fields live in a dedicated modal dialog instead of the source form.
- Sync remains reference-scoped, with batching/chunking through the adapter; it no longer offers a one-click full-history fetch path.
- Industrial export is cache-only and uses the selected industrial filter/grouping to generate production-line data, summaries, diagnostics, and charts.

### 2026-05-10 Update: Oznak Window UX Audit And Refactor Plan

User-reported issue:

- The Oznak/industrial window is visually overloaded.
- Text is unreadable because fields are cut vertically.
- Connection configuration, filtering, grouping, and export must not live in the same surface.
- Industrial export should behave closer to CSV Summary: compact setup rows, output workbook, readiness state, primary export action, and an option to include plots or not.

Audit evidence:

- `IndustrialDataDialog` still builds the connection form, workflow actions, sync actions, export action, status labels, and close button in one non-scroll `QVBoxLayout`.
- The source form alone has 15 rows: saved source, source name, alias, DB type, host, port, database, table/view, columns, record key, timestamp, username, password, row limit, and timeout.
- The window uses `configure_window_size(self, minimum=(760, 560), initial=(900, 700))`, but the actual offscreen probe constrained it to `760x700` while the size hint was `407x839`. That means the content is taller than the window and there is no scroll/reflow path.
- The offscreen screenshot `/tmp/metroliza_oznak_window_audit.png` showed visible spinbox text clipping in `Sync row limit`, confirming the user's report.
- `ui_foundation.configure_window_size()` caps the top-level window against screen geometry; it does not solve overflow for a dense fixed-content dialog.
- The current `filter_state` is used both as sync scope and export scope. That is confusing because fetch filtering and cached export filtering are different user tasks.
- The current export entry is only a checkbox plus `Export industrial data`; it jumps straight to `QFileDialog` and a worker thread, so the export workflow has no visible readiness state, output path, or plot-mode summary.

Existing Metroliza conventions researched:

- `ExportDialog` keeps filter and grouping in separate `Edit...` dialogs and uses compact status rows in the launcher.
- `ExportDialog` puts its larger body inside a `QScrollArea` and uses bounded path fields with tooltips for long paths.
- `CSVSummaryDialog` is the better pattern for industrial cached export: input/source row, selection/config status rows, plot option checkbox/status, output workbook row, readiness chip, and one primary action.
- CSV Summary already models the user-requested plot toggle through `include_extended_plots`, a plot status chip, centralized readiness logic, and a worker/progress flow.
- `DataGrouping` uses a separate modal grouping dialog with list panes and summary chips.
- `FilterDialog` keeps filtering out of the launcher workflow and updates parent state through explicit callbacks.

Refactor target:

1. Keep `IndustrialDataDialog` as a compact status/launcher window only.
   - Shows selected Metroliza DB, Oznak availability, cache counts, current source, filter/export summaries, and last operation result.
   - Primary actions: `Sources...`, `Sync...`, `Export...`, `Refresh links`, `Close`.
   - No credentials, no host/table/column fields, no export file picker, no large pasted reference box.

2. Add `IndustrialSourceProfilesDialog`.
   - Owns source profile CRUD/editing only.
   - Fields: saved source, source name, alias, database type, host, port, database, table/view, allowed columns, record key/pagination column, timestamp column.
   - Stores only non-secret metadata through `IndustrialDataRepository`.
   - Does not contain username/password and does not start sync/export.

3. Add `IndustrialSyncDialog`.
   - Owns session credentials, connection test, sync, cancellation, and sync diagnostics.
   - Selects a saved source profile.
   - Opens `IndustrialFilterDialog` for fetch scope only.
   - `Sync now` still requires references; `Test connection` remains a one-row/non-persisting connection check.
   - Forwards cancellation token and progress exactly as the current worker does.
   - Keeps credentials in memory only for the current operation.

4. Keep and tighten `IndustrialFilterDialog`.
   - Treat this as sync/fetch scope, not generic export filtering.
   - Keep quick paste parsing for comma/semicolon/space/tab/newline.
   - Keep `Use DB references`, but it must remain a narrow local Metroliza query against `report_metadata`, never a plant DB fetch.
   - Add visible count/readiness state and prevent long summaries from resizing the launcher.

5. Keep and tighten `IndustrialGroupingDialog`.
   - Treat this as cached-export grouping only.
   - Use production-line fields, not CMM report grouping semantics.
   - Keep search, clear, apply, and deterministic field ordering.

6. Add `IndustrialExportDialog`.
   - Follow `CSVSummaryDialog`, not full `ExportDialog`.
   - Rows:
     - Metroliza DB/source summary.
     - Cached row/link summary.
     - Export filter summary with `Edit...` if export-specific filter is kept separate from sync filter.
     - Grouping summary with `Edit...`.
     - Plot mode row with `Include plots` checkbox and status chip.
     - Output workbook row with bounded path field and `Browse`.
     - Readiness chip.
   - Primary action: `Create industrial export`.
   - Calls `export_cached_industrial_workbook(..., include_charts=<checkbox>)`.
   - Must never import/call Oznak fetch functions.

7. Split state so labels and workflows match intent.
   - `sync_filter_state`: reference-scoped live fetch filter.
   - `export_filter_state`: cached export scope, initially can reuse the same `IndustrialFilterState` structure but must be named and surfaced as export state.
   - `grouping_state`: cached export grouping.
   - `include_plots`: export-only option.

Implementation task split with optimal subagents:

- Main integrator: `GPT-5.5`, reasoning `high`.
  - Own the final architecture, shared state model, file boundaries, integration review, and final full validation.
  - Keep write ownership over `IndustrialDataDialog` orchestration and roadmap updates.

- Subagent A, UI/source worker: `gpt-5.3-codex`, reasoning `high`.
  - Own new `modules/industrial_source_profiles_dialog.py`.
  - Move source-profile widgets/validation/persistence out of `IndustrialDataDialog`.
  - Add focused source-profile dialog tests.
  - Must not touch Oznak sync/export worker code.

- Subagent B, sync/filter worker: `gpt-5.3-codex`, reasoning `high`.
  - Own new `modules/industrial_sync_dialog.py` and tightening `modules/industrial_filter_dialog.py`.
  - Move username/password, test connection, sync, cancel, and progress handling out of the launcher.
  - Preserve reference-required sync and test-only no-persist behavior.
  - Add sync/filter dialog tests.

- Subagent C, export worker: `gpt-5.3-codex`, reasoning `high`.
  - Own new `modules/industrial_export_dialog.py` and any service adapter needed for CSV Summary-style export.
  - Implement output workbook row, readiness state, include-plots checkbox, grouped summary/chart toggle forwarding, and worker progress.
  - Add export-dialog tests proving cached-only export and `include_charts` forwarding.

- Subagent D, UX/layout explorer: `gpt-5.4`, reasoning `medium`.
  - Read-only before implementation and review-only after implementation.
  - Compare screenshots/size hints against `CSVSummaryDialog`, `ExportDialog`, `FilterDialog`, and `DataGrouping`.
  - Report clipping, excessive text, missing scroll/reflow, and long path/summary overflow risks.

- Subagent E, test/quality auditor: `gpt-5.4-mini`, reasoning `medium`.
  - Own test inventory and gap review after implementation.
  - Confirm new tests are placed by dialog boundary and that existing industrial repository/export/join tests still cover contracts.

Test plan:

- Keep `tests/test_industrial_data_dialog.py` as a launcher/orchestration suite only.
- Add `tests/test_industrial_source_profiles_dialog.py`.
  - Source metadata save/load.
  - Identifier/column validation.
  - No username/password fields or credential persistence.
- Add `tests/test_industrial_sync_dialog.py`.
  - Session credential validation.
  - `Test connection` calls Oznak worker with `test_only=True` and does not persist rows.
  - `Sync now` refuses empty references.
  - `Sync now` uses selected source and `sync_filter_state`.
  - Cancel forwards to the worker.
- Add `tests/test_industrial_filter_dialog.py`.
  - Paste parser.
  - `Use DB references` reads local Metroliza references only.
  - Clear/apply parent callback.
  - Invalid reference column rejected.
- Add `tests/test_industrial_grouping_dialog.py`.
  - Field ordering.
  - Search/hide behavior.
  - Clear/apply parent callback.
- Add `tests/test_industrial_export_dialog.py`.
  - Output path readiness.
  - Include-plots checkbox forwards to `include_charts`.
  - Export dialog calls `export_cached_industrial_workbook`.
  - Export dialog does not call/import Oznak fetch functions.
- Add or extend layout tests.
  - Offscreen launcher size hint must fit initial height or body must be scrollable.
  - No spinbox/line-edit text clipping in source/sync/export dialogs at normal DPI.
  - Long DB/output paths use bounded `path_field` behavior and do not expand the dialog.
  - Long filter/grouping summaries do not resize the launcher beyond screen bounds.
- Update `tests/test_dialog_parent_none_safety.py` for new dialog constructors.
- Keep full regression guards:
  - `tests/test_industrial_export_service.py` for cache-only data/summaries/charts.
  - `tests/test_oznak_adapter.py` for reference batching/chunking and no full-history fetch behavior.
  - `tests/test_industrial_data_schema_repository.py` for redaction/no credentials.
  - `tests/test_export_industrial_context.py` for main Metroliza export context.

Acceptance criteria:

- The first `Tools > Industrial data...` window is no longer a configuration form; it is a compact launcher/status window.
- Source configuration opens in a dedicated dialog.
- Sync/test/cancel opens in a dedicated dialog.
- Filtering opens in a dedicated dialog.
- Grouping opens in a dedicated dialog.
- Industrial export opens in a dedicated dialog modeled after CSV Summary and includes an explicit `Include plots` option.
- At 760px wide and normal DPI, no visible input text is cut vertically in source/sync/export dialogs.
- No workflow path performs unfiltered live plant DB fetch.
- Export remains cache-only.
- Credentials are never stored.
- Focused and full test suites pass after the split.

### 2026-05-10 Update: Oznak Window Refactor Implemented

Implemented:

- Renamed the main menu entry to `Tools > Industrial data...` because the first window is now a launcher, not a source-form window.
- Replaced `IndustrialDataDialog` with a compact launcher/status surface.
  - Shows selected DB, Oznak availability, cache counts, source count, sync filter, export filter, grouping, export plot mode, and last status.
  - Primary actions are now `Sources...`, `Sync...`, `Export...`, `Refresh links`, `Initialize cache`, and `Close`.
  - It no longer contains host/table/columns, username/password, large reference input, output-file selection, or embedded export controls.
- Added `modules/industrial_source_profiles_dialog.py`.
  - Dedicated source-profile editor for database type, host, port, database, table/view, allowed columns, record key, and timestamp column.
  - Stores non-secret source metadata only.
  - Does not contain username/password fields.
- Added `modules/industrial_sync_dialog.py`.
  - Dedicated connection-test/sync workflow.
  - Owns session username/password, source selection, row limit, timeout, filter launcher, `Test connection`, `Sync now`, and cancel.
  - Preserves reference-required sync and one-row/non-persisting connection tests.
  - Adds the selected reference column to the runtime Oznak profile if needed without mutating the saved source profile.
- Added `modules/industrial_export_dialog.py`.
  - Dedicated cached industrial export workflow modeled after `CSVSummaryDialog`.
  - Rows: DB, cache summary, export filter, grouping, plots, output workbook, readiness.
  - Includes explicit `Include plots` checkbox.
  - Calls cached `IndustrialExportThread`/`export_cached_industrial_workbook()` only; it does not import Oznak fetch functions.
- Added `modules/industrial_workers.py`.
  - Extracted link refresh, Oznak sync, and cached export worker threads out of the launcher.
  - Keeps worker dependencies out of UI launcher code.
- Updated `modules/ui_foundation.py`.
  - Added minimum input height for line edits, combo boxes, date edits, and spin boxes.
  - Made shared section/status labels fixed-height by default so extra dialog height does not stretch labels and create unreadable blocks.
- Updated user docs.
  - `docs/user_manual/main_window.md` now describes the launcher plus `Sources...`, `Sync...`, and `Export...`.
  - `docs/user_manual/export_overview.md` now points users to `Tools > Industrial data...` and explains that industrial cached export follows the CSV Summary-style workflow.

UX audit after implementation:

- Offscreen size/screenshot audit was run for launcher/source/sync/export dialogs using `/tmp/metroliza_oznak_ui_audit_after.db`.
- Size evidence:
  - Launcher: `size 560x430`, `sizeHint 351x428`, `minimum 560x340`.
  - Source profile dialog: `size 620x600`, `sizeHint 290x472`, `minimum 620x420`.
  - Sync dialog: `size 680x420`, `sizeHint 361x372`, `minimum 560x360`.
  - Export dialog: `size 760x430`, `sizeHint 396x364`, `minimum 620x380`.
- Screenshots reviewed:
  - `/tmp/metroliza_oznak_launcher_after.png`
  - `/tmp/metroliza_oznak_sources_after.png`
  - `/tmp/metroliza_oznak_sync3.png`
  - `/tmp/metroliza_oznak_export3.png`
- Result:
  - The launcher is no longer visually overloaded.
  - Connection configuration is isolated in a dedicated dialog.
  - Sync credentials and Oznak fetch controls are isolated in a dedicated dialog.
  - Filtering remains separate and is launched from sync/export contexts.
  - Export is a dedicated CSV Summary-style dialog with output path, readiness, and `Include plots`.
  - No visible input text clipping was observed in the reviewed offscreen screenshots.
  - Long paths are held in bounded `path_field` controls with tooltips.

Coverage added/updated:

- `tests/test_industrial_data_dialog.py`
  - Launcher has no connection/credential fields.
  - Launcher exposes `Sources...`, `Sync...`, and `Export...`.
  - Industrial launcher/source/sync/export dialog size hints fit configured initial windows.
- `tests/test_industrial_sync_dialog.py`
  - Credentials are session-only UI state.
  - Empty source state disables sync.
  - Runtime filter column can be added without mutating stored source metadata.
  - Credential validation is explicit.
- `tests/test_industrial_filter_dialog.py`
  - Paste parsing.
  - Parent callback behavior.
  - Invalid reference-column rejection.
  - `Use DB references` reads only local `report_metadata`.
- `tests/test_industrial_grouping_dialog.py`
  - Deterministic field order.
  - Search/hide behavior.
  - Apply/clear parent callback behavior.
- `tests/test_industrial_export_dialog.py`
  - Readiness is output-path gated.
  - `Include plots` forwards to `include_charts`.
  - Export dialog has no live Oznak fetch dependency.
- Existing industrial repository, adapter, join, export-service, main-export-context, and main-window tests remain active.

Validation:

- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_data_dialog.py tests/test_industrial_export_dialog.py tests/test_industrial_sync_dialog.py tests/test_industrial_filter_dialog.py tests/test_industrial_grouping_dialog.py tests/test_industrial_export_service.py tests/test_industrial_data_schema_repository.py tests/test_industrial_join_service.py tests/test_oznak_adapter.py tests/test_export_industrial_context.py tests/test_report_query_service.py tests/test_main_window_metadata_ui.py tests/test_dialog_parent_none_safety.py -q`: `60 passed`.
- `python -m compileall -q -x '^\./\.git/' .`: passed.
- `python -m ruff check modules tests scripts packaging`: passed.
- `python scripts/sync_release_metadata.py --check`: passed.
- `python scripts/check_release_hygiene.py`: passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest -q`: `1305 passed, 48 skipped, 7 warnings, 60 subtests passed`.

Current release-readiness status:

- Metroliza-side Oznak UI split is release-ready on this branch.
- No missing implementation gaps were found in the requested source/sync/filter/grouping/export split.
- Oznak remains an optional dependency until the user accepts an Oznak commit/tag for pinning.
- A real Windows GUI smoke remains useful before shipping an actual Windows build, but the headless Linux PyQt sizing/screenshot audit no longer reproduces the reported clipping.

### 2026-05-10 Update: File-Backed Source Config And Launcher Availability

User-reported issue:

- Opening `Tools > Industrial data...` could show a dead launcher when no Metroliza database was selected. The only path for configuring an Oznak source was disabled together with sync/export actions.
- Database configuration needs two equal entry paths: direct config-file editing and a GUI editor that modifies those config files.

Implemented:

- Added `modules/industrial_source_config.py`.
  - Uses Oznak-compatible YAML with a top-level `databases:` mapping.
  - Default file path is `~/.metroliza/industrial_sources.yaml`.
  - Loads direct file edits into `IndustrialSourceProfile` objects.
  - Writes GUI-edited profiles back to the same config file.
  - Imports file-backed profiles into the selected Metroliza DB cache when a DB is available.
  - Rejects credential-like keys so username/password/token data does not enter config files.
- Updated `IndustrialSourceProfilesDialog`.
  - Adds a visible config-file path, `Browse...`, and `Reload config`.
  - Can save profiles to the YAML config before any Metroliza DB is selected.
  - When a Metroliza DB is selected, saving also updates the local industrial source-profile cache.
  - Reloading the config synchronizes file-backed profiles into the selected DB.
- Updated `IndustrialDataDialog`.
  - `Sources...` now stays enabled without a selected Metroliza DB.
  - `Sync...`, `Export...`, `Initialize cache`, and `Refresh links` remain disabled until a DB is selected.
  - When a DB is selected, the launcher imports the current config-file profiles before showing counts.
- Added `PyYAML>=6.0.1` to runtime requirements because YAML source profiles are now a Metroliza feature, not only an optional Oznak detail.
- Extended release hygiene to block real `industrial_sources.yaml`/`databases.yaml` style config files from GitHub commits.
- Updated user docs to describe both configuration paths.

Validation:

- `python -m ruff check modules/industrial_source_config.py modules/industrial_source_profiles_dialog.py modules/industrial_data_dialog.py tests/test_industrial_source_config.py tests/test_industrial_data_dialog.py tests/test_release_hygiene.py scripts/check_release_hygiene.py`: passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_source_config.py tests/test_industrial_data_dialog.py tests/test_release_hygiene.py -q`: `14 passed`.
- `python -m compileall -q -x '^\./\.git/' .`: passed.
- `python -m ruff check modules tests scripts packaging`: passed.
- `python scripts/sync_release_metadata.py --check`: passed.
- `python scripts/check_release_hygiene.py`: passed after focused tests and again after the full suite.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_source_config.py tests/test_industrial_data_dialog.py tests/test_industrial_sync_dialog.py tests/test_industrial_export_dialog.py tests/test_industrial_filter_dialog.py tests/test_industrial_export_service.py tests/test_oznak_adapter.py tests/test_main_window_metadata_ui.py tests/test_release_hygiene.py -q`: `40 passed`.
- `QT_QPA_PLATFORM=offscreen python -m pytest -q`: `1308 passed, 50 skipped, 7 warnings, 60 subtests passed`.

Current status after fix:

- The non-technical starting path is no longer blocked: open `Industrial data...`, choose `Sources...`, create/edit source profiles in the GUI, and the GUI writes the config file.
- Technical users can edit `~/.metroliza/industrial_sources.yaml` directly; Metroliza imports those profiles into the selected Metroliza report database for sync/export workflows.
- Credentials remain session-only in `Sync...`.

### 2026-05-10 Update: Database Terminology Split

User correction:

- The UI/docs must not use generic "database" wording for both sides of the integration.
- There are two different database types with different ownership, structure, and data:
  - **Metroliza report database**: the SQLite database Metroliza creates and manages from metrology/CMM reports. This is where Metroliza stores report metadata, measurements, local industrial cache rows, sync diagnostics, and report-to-production links.
  - **Production line database/source**: the existing MySQL/MSSQL source that Oznak reads from. This stores production-line sensor/process rows and is not created or owned by Metroliza.

Implemented:

- Updated industrial launcher labels:
  - `Database` -> `Metroliza report database`.
  - `Sources...` -> `Production sources...`.
  - `Cache` -> `Local industrial cache`.
  - `Sources` -> `Production sources`.
  - Empty path state now says `No Metroliza report database selected`.
- Updated launcher status copy so users can configure production sources without a Metroliza report DB, while sync/export/link actions explicitly require a report DB because they write/read the local industrial cache.
- Updated production source dialog labels:
  - `Database type` -> `Production DB type`.
  - `Host` -> `Production host`.
  - `Database` -> `Production database`.
  - `Table/view` -> `Production table/view`.
  - `Columns` -> `Production columns`.
- Updated sync dialog labels and validation copy so username/password refer to the production database, while the selected Metroliza report database is only the local cache/link target.
- Updated export dialog labels so cached export clearly reads from the Metroliza report database/local industrial cache, not from live production databases.
- Updated `IndustrialFilterDialog` button/copy from `Use DB references` to `Use report DB references`, clarifying that reference import reads only local Metroliza report metadata.
- Updated user docs to define both database concepts before explaining the workflow.

Validation:

- `python -m ruff check modules/industrial_data_dialog.py modules/industrial_source_profiles_dialog.py modules/industrial_sync_dialog.py modules/industrial_export_dialog.py modules/industrial_filter_dialog.py modules/industrial_source_config.py tests/test_industrial_data_dialog.py`: passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_data_dialog.py tests/test_industrial_sync_dialog.py tests/test_industrial_export_dialog.py tests/test_industrial_filter_dialog.py -q`: `18 passed`.
- `python -m compileall -q -x '^\./\.git/' modules tests scripts packaging`: passed.
- `python -m ruff check modules tests scripts packaging`: passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_source_config.py tests/test_industrial_data_dialog.py tests/test_industrial_sync_dialog.py tests/test_industrial_export_dialog.py tests/test_industrial_filter_dialog.py tests/test_industrial_export_service.py tests/test_oznak_adapter.py tests/test_main_window_metadata_ui.py tests/test_release_hygiene.py -q`: `40 passed`.
- `python scripts/check_release_hygiene.py`: passed.

### 2026-05-10 Update: Manual Production Linking

User clarification:

- Metroliza report references do not have to match production database references.
- The relationship can be created after sync by the user linking cached production rows to Metroliza reports.

Implemented:

- Added manual link service helpers in `modules/industrial_join_service.py`.
  - `set_manual_industrial_report_link()` creates an accepted link between one Metroliza report and one cached production row, regardless of reference values.
  - `clear_manual_industrial_report_link()` removes only the user-managed link for a report.
  - Manual links use a high-priority `manual_user_link` join rule, so export chooses them before automatic exact-reference links.
- Added `modules/industrial_linking_dialog.py`.
  - Dedicated `Production links` dialog.
  - Shows Metroliza reports on one side and cached production rows on the other.
  - Search boxes filter both lists.
  - `Link selected` stores a manual accepted link.
  - `Clear manual link` removes the manual link without deleting cached production rows or automatic candidates.
  - `Refresh auto links` remains available for exact-reference candidates.
- Added `Production links...` to the industrial launcher.
- Updated user docs to explain the manual link path for systems that use different references.

Validation:

- `python -m ruff check modules/industrial_join_service.py modules/industrial_linking_dialog.py modules/industrial_data_dialog.py tests/test_industrial_join_service.py tests/test_industrial_linking_dialog.py tests/test_industrial_data_dialog.py`: passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_join_service.py tests/test_industrial_linking_dialog.py tests/test_industrial_data_dialog.py -q`: `14 passed`.
- `python -m compileall -q -x '^\./\.git/' modules tests scripts packaging`: passed.
- `python -m ruff check modules tests scripts packaging`: passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_source_config.py tests/test_industrial_data_dialog.py tests/test_industrial_sync_dialog.py tests/test_industrial_export_dialog.py tests/test_industrial_filter_dialog.py tests/test_industrial_grouping_dialog.py tests/test_industrial_export_service.py tests/test_industrial_join_service.py tests/test_industrial_linking_dialog.py tests/test_oznak_adapter.py tests/test_export_industrial_context.py tests/test_report_query_service.py tests/test_main_window_metadata_ui.py tests/test_release_hygiene.py -q`: `61 passed`.
- `python scripts/check_release_hygiene.py`: passed.
- `python scripts/sync_release_metadata.py --check`: passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest -q`: `1309 passed, 51 skipped, 7 warnings, 60 subtests passed`.
- `git diff --check`: passed.

Current status after fix:

- Automatic exact-reference linking is no longer the only path.
- User-managed links can connect different Metroliza and production references after sync.
- Export will prefer the user-managed link because it is stored with priority `0`.

### 2026-05-12 Update: CSV Summary And Oznak Sync Hardening

Implemented:

- Oznak sync no longer reports partial Oznak batch failures as clean success.
  Worker/UI results now use `completed_with_warnings` when rows were fetched but
  Oznak diagnostics contain warnings/errors; cached rows are still upserted, and
  the sync-run row stores `succeeded` with a redacted warning summary because the
  current SQLite status enum is `running/succeeded/failed/cancelled`.
- Oznak bounded fetch behavior is safer:
  - explicit sync limits and `Test connection` use normal `fetch_records()`;
  - chunked fetch remains available for unbounded runs with a pagination column;
  - timeout seconds are mapped into `DatabaseProfile.connect_timeout_seconds`
    and `DatabaseProfile.query_timeout_seconds` when the installed Oznak contract
    supports those fields;
  - runtime fetch columns include timestamp, pagination, and reference-filter
    columns without mutating saved source profiles.
- CSV Summary quick-look mode now skips all chart parts instead of keeping a
  scatter chart hidden in the workbook.
- CSV Summary scatter downsampling now writes sampled row-position/value helper
  columns and charts those sampled points, rather than pointing the chart at the
  first contiguous workbook rows.
- Legacy CSV Summary workbook creation now writes to a same-directory temporary
  `.xlsx` file and atomically replaces the target only after success. Cancelled
  or failed runs clean up the temp file and preserve an existing target workbook.
- Malformed CSV Summary preset numeric values are coerced safely to defaults with
  a warning instead of breaking dialog readiness.
- Industrial analytics dynamic metric reads now chunk large SQLite `IN (...)`
  queries so large cached datasets do not exceed parameter limits.
- Industrial launcher readiness now distinguishes:
  - no Metroliza report DB selected;
  - cache unavailable/not initialized;
  - cache empty;
  - cache ready with synced production rows.
- Added accessibility names and explicit tab order for the industrial launcher.

Validation:

- `python -m ruff check .`: passed.
- `python -m compileall -q -x '^\./\.git/' .`: passed.
- `python scripts/sync_release_metadata.py --check`: passed.
- `python scripts/check_release_hygiene.py`: passed.
- `git diff --check`: passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_csv_summary_utils.py tests/test_csv_summary_integration.py tests/test_oznak_adapter.py tests/test_industrial_data_dialog.py tests/test_industrial_sync_dialog.py tests/test_industrial_analytics_service.py -q`: `92 passed`.
- `QT_QPA_PLATFORM=offscreen python -m pytest -q`: `1413 passed, 82 skipped, 7 warnings, 60 subtests passed`.

## Verified Baselines

Metroliza local baseline:

- Repository: `/home/hexaf/Projects/metroliza`
- Branch: `codex/oznak-metroliza-integration`
- Branch point: `d57dbe3e50d44425fbc3a2b20e6e41d7195d90a0` (`Fix Windows EXE build dependencies`)
- Worktree status at integration start: only this roadmap was untracked

Oznak baseline:

- Repository: `hexafe/oznak`
- Visibility: public
- Default branch: `main`
- Current commit cloned for audit: `aff29558741cc0a49f3845a3f10528d56250ac3b`
- Commit title: `Merge pull request #28 from hexafe/codex/fix-test-for-unsupported-database-type`
- Local read-only clone used for inspection: `/tmp/oznak-audit`
- Validation run: `python -m pytest -q` in `/tmp/oznak-audit` passed with `57 passed in 1.16s`

Current local Oznak work in progress:

- Repository: `/home/hexaf/Projects/oznak`
- Branch: `roadmap...origin/roadmap`
- Latest committed baseline: `ed677af` (`Add CLI integration coverage`)
- Worktree status: dirty, with uncommitted package-foundation work in `pyproject.toml`, `src/oznak/`, and new contract tests
- Oznak handoff note: `/home/hexaf/Projects/oznak/docs/OZNAK_METROLIZA_STATUS.md`
- Emerging package namespace: `oznak`
- Emerging public contracts: `DatabaseProfile`, `QueryFilter`, `FetchRequest`, `FetchResult`, credentials, diagnostics, dialects
- Current verification reported by Oznak session: `python -m pytest -q` passes with `146 passed`
- Typed query contract status: `oznak.query_builder.compile_query(profile, spec)` compiles parameterized SQL, enforces allowed columns, and supports MySQL/MSSQL quoting
- Current limitation reported by Oznak session: fetch orchestration is still legacy; structured `fetch_records()` with per-source diagnostics, timeout, and cancellation is not ready for Metroliza pinning

Metroliza must therefore treat Oznak as an optional, moving dependency until a pinned Git commit or release tag exposes a real fetch implementation.

## Executive Verdict

Oznak is a useful starting point for industrial database access, but it is not ready to be a required Metroliza runtime dependency yet. The active Oznak session has started converting it into an installable `oznak` package with typed contracts, but the fetch API is still stubbed locally.

The right integration path is:

1. Keep Oznak behind a narrow optional Metroliza adapter, following the existing package-adapter pattern rather than spreading imports across the app.
2. Cache industrial data into Metroliza's local SQLite database through additive tables and views.
3. Join cached industrial/assembly context with metrology measurements during filtering, grouping, export, dashboards, and later analysis.
4. Pin Oznak only after the other session provides a stable installable commit with implemented fetch functions and green package CI.

Do not query live industrial databases inside Metroliza's hot export loop. Network/ODBC failures must be isolated to an explicit sync/enrichment step so export remains deterministic, offline-capable, cancellable, and inspectable.

## Current Metroliza Implementation Target

This branch should deliver the Metroliza side of the integration without waiting for Oznak fetch internals:

- Optional `modules/oznak_adapter.py` that reports Oznak availability and maps Oznak-like result rows into Metroliza industrial-record payloads.
- Additive industrial SQLite schema/repository for source profiles, sync runs, cached records, join rules, and link candidates.
- Join service that materializes exact/time-window report-level links from cached industrial records.
- Enriched measurement export query that preserves the existing workbook aliases and appends industrial context columns only when explicitly requested.
- Optional industrial-context worksheet and diagnostics generated from local cache only.
- Tools-menu entry points for inspecting industrial integration status and refreshing local links.
- Release hygiene and tests that keep credentials, connection dumps, real plant data, and generated industrial exports out of Git.

Live Oznak sync can be wired after Oznak exposes implemented `fetch_records()` behavior.

## Metroliza Iteration Log

### 2026-05-10: Optional Adapter, Cache, Join, Export MVP

Implemented in branch `codex/oznak-metroliza-integration`:

- Added optional lazy Oznak adapter in `modules/oznak_adapter.py`.
- Added additive industrial cache schema and repository in `modules/industrial_data_schema.py` and `modules/industrial_data_repository.py`.
- Wired industrial schema initialization into normal report schema setup.
- Added report-level industrial link materialization in `modules/industrial_join_service.py`.
- Added enriched measurement export SQL that preserves existing workbook aliases and appends `INDUSTRIAL_*` columns only when requested.
- Added `ExportOptions.include_industrial_context`, Export dialog checkbox, and export-thread context/diagnostics worksheets.
- Added Tools-menu industrial status dialog for cache initialization, Oznak availability, counts, and local link refresh.
- Updated release hygiene to block industrial artifacts, connection dumps, `.env`, and ODBC/token files.
- Updated user manuals for the Tools entry and export option.

Oznak dependency status:

- Metroliza now pins Oznak from Git in `requirements.txt` while the sibling package is still on the integration path.
- Live source sync is available through the optional adapter when Oznak exposes package-native fetch behavior with structured per-source diagnostics, timeout, and cancellation.
- Export uses local cached rows only.

Validation so far:

- Focused tests: `81 passed`.
- Focused Ruff pass: clean.
- `python -m compileall -q -x '^\./\.git/' .`: passed.
- `python scripts/check_release_hygiene.py`: passed.
- `python scripts/sync_release_metadata.py --check`: passed.
- Full test suite: `1298 passed, 28 skipped, 7 warnings, 60 subtests passed`.

Post-audit fixes:

- Replaced the initial Python report-by-record join loop with set-based SQL materialization in `modules/industrial_join_service.py`.
- Moved industrial link refresh from the dialog's main-thread handler into `IndustrialLinkRefreshThread`.
- Added focused coverage for industrial context with a custom filtered export scope.

## Oznak Audit

### Strengths

- Modular structure already exists: `src/db`, `src/query`, `src/services`, `src/cli`, `src/api`, `src/storage`, and `src/utils`.
- Oznak supports MySQL and MSSQL through SQLAlchemy in `src/db/manager.py`.
- Fetching multiple database aliases returns a combined pandas DataFrame with a `source_database` column from `src/services/multi_database_fetcher.py`.
- Query generation is database-aware for MySQL backticks and MSSQL brackets in `src/query/builder.py`.
- CLI commands exist for normal and chunked loading in `src/cli/main.py`.
- FastAPI exposes `/health` and `/fetch` in `src/api/rest.py`.
- Tests cover query generation, mocked fetches, CLI calls, API function calls, and DB-manager validation.
- CI exists in `.github/workflows/ci.yml`, running Python 3.10 and `pytest -q`.
- MIT license is compatible with reuse if notices are preserved.

### Blockers Before Embedding

- No package metadata exists: no `pyproject.toml`, `setup.py`, `setup.cfg`, wheel build, console-script declaration, or stable import namespace. Current imports use `src.*`, which is fragile inside another application.
- Runtime requirements are unpinned and mix runtime/dev concerns. `pytest` is in `requirements.txt`.
- Windows runtime requirements are heavy and environment-sensitive: `pyodbc` plus `ODBC Driver 17 for SQL Server`, `PyMySQL`, and `mysql-connector-python`.
- Config is hard-wired to repo-local `config/databases.yaml` through `config/settings.py`.
- Credentials are read from environment variables by alias via `src/utils/env.py`, and `.env` is loaded globally at import time.
- `config/databases.yaml` contains concrete private IP-like host examples and table names. Keep only templates in public/distribution paths.
- `MultiDatabaseFetcher` constructs `DBManager()` directly, so config path, credentials provider, logger, executor, timeout, and cancellation are not injectable.
- Error reporting is not UI-safe: code prints messages, swallows many exceptions, and often turns failures into empty DataFrames. Metroliza must distinguish "no rows" from "query failed".
- `ThreadPoolExecutor` work is blocking to the caller and lacks timeout, cancellation, progress, and structured per-database metrics.

### Query Safety Risks

- `IS` and `IS NOT` values are interpolated directly into SQL in `src/query/builder.py`; only explicit `NULL` and `NOT NULL` style predicates should be allowed.
- Multi-word operators such as `NOT LIKE` and `IS NOT` are advertised but not parsed correctly because the parser treats only the second token as the operator.
- `build_chunked_query` does not validate `chunk_size`; CLI validates it, but library callers can bypass the guard.
- Column/table validation is syntactic, not schema-allowlist based. A desktop UI should never expose arbitrary valid identifiers without a configured table schema/profile.
- CLI date-column validation and query-builder validation disagree on dotted identifiers.

### Oznak Product Gap

Oznak currently fetches industrial rows, but it does not model manufacturing context. It has no domain objects for station, line, work order, lot, batch, serial, fixture, cavity, operator, cycle time, assembly timestamp, process status, or traceability links. Those semantics should be layered in Metroliza through profiles and join rules, not assumed by raw Oznak tables.

## Metroliza Audit

### Current Data Model

Metroliza stores parsed report data in SQLite through `modules/report_schema.py`.

Important tables and fields:

- `source_files` and `source_file_locations` preserve source report identity and current path.
- `parsed_reports` stores parser/template/status fields and report-level parse metrics.
- `report_metadata` stores `reference`, `report_date`, `report_time`, `part_name`, `revision`, `sample_number`, `operator_name`, and metadata JSON.
- `report_measurements` stores measurement rows, including `header`, `characteristic_name`, `ax`, `nominal`, tolerances, `meas`, `dev`, `outtol`, `is_nok`, and `status_code`.

Important views:

- `vw_report_overview` is report-level browsing/filtering scope.
- `vw_measurement_export` is the main export shape.
- `vw_grouping_reports` is grouping-dialog scope.

`ensure_report_schema()` drops/recreates views and writes schema metadata. This is the correct place to add industrial views, but new industrial tables should be additive and schema-versioned carefully.

Important persistence behavior:

- `ReportRepository.upsert_parsed_report()` is parser-owned and reparses can replace report measurements, metadata candidates, and warnings. Industrial rows should not be stored inside parser-owned measurement rows.
- `replace_report_metadata_enrichment()` is the closer precedent: it is a side-channel enrichment path that updates report metadata without owning measurement extraction.
- `ParseReportsThread` fingerprints report files and skips already-ingested reports. Industrial records need their own external-system fingerprints such as source profile, external primary key, updated timestamp, and row fingerprint.
- External parser plugins are for new report-file formats, not assembly-process database rows unless those rows are themselves metrology reports.

### Export and Analysis Flow

- `modules/report_query_service.py` builds SQL strings for report overview, measurement export, filtering, and distinct filter values.
- `modules/export_dialog.py` stores the active `filter_query` and optional grouping DataFrame, then builds an `ExportRequest`.
- `modules/contracts.py` validates `ExportRequest`, `ExportOptions`, and grouping DataFrames.
- `modules/export_data_thread.py` materializes a temporary export snapshot from `filter_query`, partitions by `REFERENCE`, builds filtered sheets, summary sheets, charts, optional HTML dashboard content, and group analysis.
- `modules/export_query_service.py` wraps `filter_query` as a scoped source and computes partitions and SQL summaries.

This design strongly favors adding industrial context as columns in a query/view-compatible export scope. The least disruptive path is a new enriched export query that preserves existing measurement columns and appends industrial columns.

### UI Extension Points

- Main window has a `Tools` menu in `modules/main_window.py`; this is the right first home for industrial data source, sync, link, and export workflows.
- Export dialog already has a compact optional workflow row pattern for filters and grouping. Add industrial context as a third optional row only after the sync/cache path is stable.
- Filter dialog currently knows a fixed set of report/measurement filters. Industrial filters should be profile-driven and added after cached industrial fields exist.
- Data grouping already uses filtered export scope and DataFrames; industrial grouping should reuse that path by adding industrial columns to the scope rather than building a separate grouping subsystem.

### Dependency and Release Constraints

- Metroliza pins `hexafe-groupstats[pandas]` and `hexafe-plotstats[pandas]` from public Git commits in `requirements.txt`.
- Tests assert dependency hygiene and prevent local path dependencies.
- Packaging specs explicitly collect optional package hidden imports and data for `hexafe_groupstats`, `hexafe_plotstats`, OCR, PyMuPDF, and native modules.
- Release hygiene blocks databases, logs, PDFs, CSVs, and Excel files unless explicitly allowed.
- Any industrial integration must preserve the rule: no real reports, real industrial exports, credentials, logs with credentials, or report-derived/plant-derived data in GitHub.

## Recommended Architecture

### Component Boundaries

Use three layers:

1. `hexafe-oznak` package:
   - Owns database connection profiles, typed filters, dialect-aware SQL generation, fetching, chunking, structured errors, and per-source metrics.
   - Has no Metroliza imports.

2. Metroliza Oznak adapter:
   - New module, for example `modules/oznak_adapter.py`.
   - Converts Metroliza industrial profiles and UI requests into Oznak fetch contracts.
   - Converts Oznak results into Metroliza cache rows and diagnostics.
   - Is the only Metroliza module that imports Oznak.

3. Metroliza industrial cache and join layer:
   - New schema/repository modules, for example `modules/industrial_data_schema.py`, `modules/industrial_data_repository.py`, and `modules/industrial_join_service.py`.
   - Stores fetched industrial records locally in SQLite.
   - Provides enriched export views/queries.
   - Keeps export deterministic and offline after sync.

### Initial Metroliza Tables

Add additive tables, not changes to existing report tables:

- `industrial_source_profiles`
  - Profile id/name, DB alias, database type, table/view name, allowed columns JSON, timestamp column, default pagination column, enabled flag.

- `industrial_sync_runs`
  - Source profile id, started/finished timestamps, status, row count, error summary, filters JSON, Oznak package version/commit, and redacted diagnostics.

- `industrial_records`
  - Source profile id, source database alias, source primary key or fingerprint, process timestamp, reference, part number/name, revision, serial, batch/lot, work order, station, line, operator, status, and raw JSON.

- `industrial_record_values`
  - Optional long-form extra attributes for profile-specific columns that should not become permanent first-class columns yet.

- `industrial_join_rules`
  - Named mapping between Metroliza report fields and industrial fields, with exact/time-window/fuzzy mode, priority, and enabled flag.

- `industrial_link_candidates`
  - Candidate links between `report_id` or `measurement_id` and industrial records, with rule id, confidence, status, and explanation.

Only promote a field from JSON/long-form to a first-class indexed column after it is used by filters, joins, grouping, or export repeatedly.

### First Join Keys To Support

Start with exact and time-window joins:

- Internal `report_id` for local joined tables and grouping.
- `source_files.sha256` when the same report file must be recognized across environments.
- `parsed_reports.identity_hash` as a semantic fallback built from parser/template/report metadata.
- `REFERENCE` / `reference`
- `PART_NAME` / part number or part name
- `REVISION`
- `SAMPLE_NUMBER` if it maps to a serial, cavity, piece number, or process sequence
- `DATE` plus `TIME` against process timestamp with configurable window
- Optional `OPERATOR_NAME`, station, line, batch/lot, work order, and source database alias

Do not assume `sample_number` is globally meaningful. Treat it as profile-configured, because in Metroliza it can be explicit, stats-derived, filename-derived, or unknown.

Measurement-level links need extra caution. `measurement_id` is exact only for the current local DB snapshot and can change after reparse. Prefer `report_id + header + ax + characteristic_name + row_order` or a future stable measurement fingerprint when linking assembly operations to individual characteristics.

The existing `modules/bom_manager.py` has product/part/parent-reference concepts that may help future assembly matching, but it is not currently a central report/export integration point.

### Export Behavior

First export target:

- Add an optional "Industrial context" worksheet with one row per linked report/process record.
- Add selected industrial columns to the filtered data sheet only when explicitly enabled.
- Add clear diagnostics: synced source profile, sync time, rows fetched, rows linked, unmatched reports, ambiguous links.

Later export targets:

- Allow grouping by line, station, work order, batch, or process status.
- Add summary charts split by industrial context.
- Add HTML dashboard sections for industrial context and unmatched/ambiguous links.
- Feed industrial group labels into Group Analysis only after join quality is visible and accepted.

## Phased Implementation Plan

### Phase 0: Decisions and Safety Baseline

Owner: main agent.

Tasks:

- Confirm package name and repo direction: `hexafe-oznak` import namespace should become `oznak`.
- Confirm first target DB types: keep MySQL and MSSQL only for MVP.
- Confirm first industrial records to combine with metrology: assembly line/station/work-order/cycle/status style data.
- Define "no real plant data in GitHub" acceptance rules and synthetic fixture naming.
- Create a durable cross-repo checkpoint note if work spans both repos.

Acceptance:

- Agreed MVP fields and join keys.
- No implementation starts until Oznak package boundary and Metroliza cache boundary are agreed.

### Phase 1: Oznak Package Hardening

Owner: Oznak package worker.

Write scope: Oznak repo only.

Tasks:

- Add `pyproject.toml`, package metadata, version source, and `src/oznak/` namespace.
- Replace `src.*` imports with package imports.
- Split requirements into runtime/dev.
- Add typed public contracts:
  - `DatabaseProfile`
  - `CredentialProvider`
  - `QueryFilter`
  - `FetchRequest`
  - `FetchResult`
  - `SourceFetchDiagnostics`
- Make config path, credentials provider, logger, executor, timeout, and fetch policy injectable.
- Replace `print()` with logging and structured diagnostics.
- Preserve CLI and FastAPI as thin wrappers over the package API.

Acceptance:

- Oznak installs as a wheel.
- Existing CLI/API tests pass.
- Package API can be used without repo-local `config/` or `.env`.
- Metroliza can depend on a pinned Git commit instead of a local path.

### Phase 2: Oznak Query Safety and Reliability

Owner: Oznak query/security worker.

Write scope: Oznak query/filter/service tests.

Tasks:

- Replace string filters with typed operator enum and typed values.
- Support multi-word operators correctly.
- Restrict `IS` and `IS NOT` to safe null predicates.
- Require table/column allowlists from profile metadata.
- Validate chunk size and pagination column at library boundary.
- Add structured partial-failure results rather than returning empty DataFrames for errors.
- Add timeout/cancel hooks suitable for GUI callers.
- Add tests for injection attempts, malformed operators, null predicates, empty/no-row vs failed-query, and per-source partial failure.

Acceptance:

- Query builder emits parameterized SQL for all non-identifier values.
- UI callers can show per-source failure diagnostics.
- "No rows" and "failed query" are never conflated.

### Phase 3: Metroliza Adapter and Industrial Schema

Owner: Metroliza schema/adapter worker.

Write scope:

- `modules/oznak_adapter.py`
- `modules/industrial_data_schema.py`
- `modules/industrial_data_repository.py`
- focused tests under `tests/`

Tasks:

- Add optional import adapter around Oznak.
- Add industrial schema bootstrap and indexes.
- Add repository functions for source profiles, sync runs, records, and join rules.
- Keep all credentials outside SQLite report DB unless intentionally encrypted and accepted.
- Add synthetic industrial fixtures only.
- Add release hygiene tests blocking `.env`, connection dumps, and industrial export artifacts.

Acceptance:

- `ensure_report_schema()` can coexist with industrial schema initialization.
- Existing Metroliza tests still pass.
- Industrial tables can be created in a temp SQLite DB and populated from synthetic rows.
- No Oznak imports outside the adapter.

### Phase 4: Sync Worker and UI

Owner: Metroliza UI/worker worker.

Write scope:

- New industrial source/sync dialogs.
- New industrial sync thread.
- Main window Tools menu wiring.
- Tests for request validation and UI state.

Tasks:

- Add an industrial data Tools entry for profile setup and test connection.
- Add `Sync industrial data...` with explicit filters, selected source profiles, progress, cancel, and diagnostics.
- Store sync diagnostics in local DB and show a compact summary.
- Ensure sync runs off the Qt main thread.
- Redact credentials and connection strings in all UI/log surfaces.

Acceptance:

- User can configure a synthetic source profile.
- User can run a mocked/synthetic sync and see row count, source, and errors.
- Cancellation does not corrupt the local cache.
- Export remains available while no sync is running; sync does not silently run during export.

### Phase 5: Join Rules and Enriched Export Scope

Owner: Metroliza export/join worker.

Write scope:

- `modules/industrial_join_service.py`
- `modules/report_query_service.py`
- `modules/export_query_service.py`
- export/filter/grouping tests

Tasks:

- Implement exact and time-window join rules.
- Materialize link candidates and selected links.
- Add enriched export query builder that preserves existing columns and appends industrial columns.
- Add optional industrial context worksheet.
- Add unmatched/ambiguous link diagnostics.
- Add filter/grouping support for first industrial fields only after cached fields are indexed.

Acceptance:

- Existing export behavior is unchanged when industrial context is disabled.
- Enabling industrial context adds deterministic columns/sheets from local cache only.
- Ambiguous and unmatched links are visible in exported diagnostics.
- Synthetic tests cover one-to-one, unmatched, and ambiguous joins.

### Phase 6: Analytics Built On Industrial Context

Owner: Metroliza analysis worker.

Write scope:

- group analysis integration points
- summary/dashboard payload builders
- tests and synthetic examples

Tasks:

- Enable grouping by station, line, work order, batch, process status, or source database alias.
- Add industrial-context splits to summary sheets and HTML dashboard.
- Add process-context correlation slices, for example NOK by station or measurement drift by line.
- Feed only validated industrial groupings into Group Analysis.

Acceptance:

- The user can compare metrology distributions by industrial grouping.
- Group Analysis inputs identify the industrial grouping source.
- HTML/dashboard output keeps context visible without hiding measurement details.

### Phase 7: Packaging, Docs, and Release Gates

Owner: packaging/docs worker.

Write scope:

- `requirements.txt`
- packaging specs/scripts
- `THIRD_PARTY_NOTICES.md` if needed
- user manual pages
- release checks/tests

Tasks:

- Pin Oznak Git dependency once package-ready.
- Add PyInstaller/Nuitka hidden imports and driver/runtime diagnostics.
- Document Windows ODBC/MySQL driver prerequisites.
- Add setup/runtime diagnostics for Oznak availability and configured driver status.
- Add user manual pages for source setup, sync, join rules, export context, and troubleshooting.
- Update release hygiene for industrial data artifacts.

Acceptance:

- Packaged app can import Oznak and run adapter diagnostics.
- Missing ODBC/MySQL drivers produce actionable diagnostics.
- User docs explain setup without exposing real credentials or plant data.

## Subagent Assignment Plan

Use subagents only for bounded, disjoint work. The main agent should own architecture, cross-repo sequencing, final integration, and merge decisions.

| Phase | Subagent | Recommended model | Reasoning effort | Role | Write scope |
|---|---|---|---|---|---|
| 1 | Oznak package worker | `gpt-5.3-codex` | high | Convert Oznak into installable package with stable API | Oznak packaging/import files only |
| 2 | Oznak query/security worker | `gpt-5.5` | high | Harden SQL/filter contracts and failure semantics | Oznak query/service/tests |
| 3 | Metroliza schema worker | `gpt-5.3-codex` | high | Add industrial schema and repository foundation | `modules/industrial_data_schema.py`, `modules/industrial_data_repository.py`, focused tests |
| 4 | Metroliza adapter worker | `gpt-5.3-codex` | high | Add optional Oznak availability and row-mapping adapter | `modules/oznak_adapter.py`, focused tests |
| 5 | Metroliza UI worker | `gpt-5.4` | high | Build PyQt source/sync/status dialog and progress/cancel UX | Main window plus new dialog/thread files |
| 6 | Metroliza export worker | `gpt-5.5` | high | Integrate enriched export scope without regressions | Query/export/join modules/tests |
| 7 | Analytics worker | `gpt-5.3-codex` | high | Add industrial grouping and analysis slices | Analysis/dashboard/export payload files |
| 8 | Packaging/docs worker | `gpt-5.3-codex` | medium | Update requirements, packagers, diagnostics, docs | Packaging scripts, docs, release tests |
| All | Verification explorer | `gpt-5.3-codex-spark` | high | Run focused tests, inspect diffs, report regressions | Read-only |

Active Metroliza agents on this branch:

- `Averroes` (`explorer`, inherited model, high): completed Oznak local-status audit.
- `Gibbs` (`explorer`, inherited model, high): completed Metroliza seam audit.
- `Singer` (`worker`, `gpt-5.3-codex`, high): implementing schema/repository foundation in new files only.
- `Schrodinger` (`worker`, `gpt-5.3-codex`, high): implementing optional Oznak adapter in new files only.

Parallelization rules:

- Run Oznak package worker and Oznak query/security worker sequentially unless write scopes are split first.
- Run Metroliza schema worker before UI/export workers.
- UI worker and packaging/docs worker can proceed in parallel after the adapter contract is stable.
- Export worker should not start until industrial cache and join contracts are available.
- Verification explorer can run after each phase while the main agent reviews diffs and owns final fixes.

## First Implementation Slice

Recommended first slice:

1. Create Oznak `pyproject.toml` and `oznak` package namespace.
2. Add injectable `FetchRequest`/`FetchResult` API with existing behavior preserved.
3. Add Metroliza read-only `modules/oznak_adapter.py` that can import Oznak when installed and report availability/diagnostics.
4. Add Metroliza industrial schema skeleton and synthetic tests.

This gives Metroliza a stable seam without changing export behavior, and it makes the later industrial cache/export work much lower risk.

## Validation Commands

Oznak:

```bash
python -m pytest -q
```

Metroliza focused checks after adapter/schema slice:

```bash
python -m pytest tests/test_requirements_hygiene.py tests/test_release_hygiene.py tests/test_report_schema_repository.py -q
python -m ruff check modules tests
python -m compileall -q -x '^\./\.git/' .
```

Metroliza broader checks before publish:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
python scripts/sync_release_metadata.py --check
python scripts/check_release_hygiene.py
```

## Open Questions

- Which industrial systems and DB types are the real MVP: MySQL, MSSQL, both, or additional sources later?
- What are the first assembly-process tables and trusted join keys?
- Is the primary join report-level, measurement-level, or both?
- Should credentials live only in environment variables for MVP, or should Metroliza add a local credential store abstraction immediately?
- Should industrial sync write into each Metroliza report DB, or into a separate local industrial cache DB linked at export time?
- Which industrial columns should appear in the first workbook release?
