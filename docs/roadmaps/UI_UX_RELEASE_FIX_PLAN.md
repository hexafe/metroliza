# Metroliza UI/UX Release Fix Plan

Last updated: 2026-05-09

## Purpose

This plan captures the final UI/UX and release-readiness fixes requested before
the first official Metroliza release. It started as the implementation plan and
now records the completed local implementation and validation evidence for this
branch.

Base branch at plan time:

- `codex/metroliza-ui-ux-visual-revamp`
- Worktree was clean when this plan was written.
- Existing draft PR: `https://github.com/hexafe/metroliza/pull/893`

## Implementation Status

Implemented on 2026-05-09 on `codex/metroliza-ui-ux-visual-revamp`.

- Task 1 complete: CSV Summary moved to `Tools > CSV Summary...`; dialog footer
  now makes `Create Summary` the primary/default action; saved-preset clearing
  requires confirmation; CSV/XLSX path handling and worker failure messaging are
  covered by tests.
- Task 2 complete: normal folder `Fast import, then enrich metadata` now runs a
  light parse, closes Parsing, and emits a main-window enrichment request.
  Archive sources intentionally keep embedded enrichment because extracted files
  are temporary.
- Task 3 complete: grouping Enter-key behavior again creates/adds/renames by
  focused list and no longer applies grouping accidentally.
- Task 4 complete: worker progress dialogs show a larger aspect-preserving GIF
  using in-memory buffers instead of leaked temp files.
- Task 5 complete: Help/manual actions open GitHub-rendered docs; About and
  Release notes live under Help; operational utilities live under Tools.
- Task 6 complete: runtime release identity is `2026.05 (build 260509)` and
  README/CHANGELOG/release notes are synchronized.
- Task 7 local validation complete:
  - `QT_QPA_PLATFORM=offscreen python -m pytest -q` -> 1276 passed, 27 skipped,
    60 subtests passed.
  - `python -m ruff check .` -> passed.
  - `python scripts/sync_release_metadata.py --check` -> passed.
  - `git diff --check` -> passed.
  - `PYTHONPATH=. python scripts/benchmark_paths.py --output-dir /tmp/metroliza-perf-ci-warmup ...`
    -> passed, with synthetic benchmark outputs written under
    `/tmp/metroliza-perf-ci-warmup`.

Publish and GitHub CI status are tracked on PR #893 after the final commit is
pushed.

## User-Reported Release Blockers

1. CSV Summary should move under the Tools menu.
2. The dancing duck GIF during parsing/exporting should be bigger.
3. CSV Summary has an empty layout area around `Summary configuration`.
4. CSV Summary bottom actions are backwards: `Clear saved presets` looks more
   important than `Create Summary`.
5. Grouping Enter-key workflow changed; Enter should not apply grouping.
6. Release notes must be updated.
7. `Fast import, then enrich metadata` should run light parsing, close Parsing,
   then start main-window metadata enrichment so the user can keep using the app.
8. Docs/manual links should open GitHub-rendered documentation, not local files.
9. Check for any other first-official-release loose ends before merging.

## Implementation Tasks And Subagent Split

### Task 1: CSV Summary Tools Placement And Layout

Recommended owner: worker subagent

Recommended model: `gpt-5.3-codex`

Reason: medium-sized PyQt UI change with tests and docs, isolated enough for a
worker.

Files likely owned:

- `modules/main_window.py`
- `modules/csv_summary_dialog.py`
- `tests/test_main_window_metadata_ui.py`
- `tests/test_csv_summary_integration.py`
- `tests/test_ui_revamp_foundation_layout.py`
- `docs/user_manual/main_window.md`
- `docs/user_manual/csv_summary.md`

Required changes:

- Replace the main-window `CSV Summary` launcher button with
  `Tools > CSV Summary...`.
- Keep `launch_csv_summary_dialog()` as the shared entry point.
- Remove the standalone `Summary configuration` section label or make the CSV
  dialog layout prevent that label from consuming vertical surplus.
- Move footer actions out of the grid:
  - secondary action left: `Clear saved presets`
  - stretch in the middle
  - primary default action right: `Create Summary`
- Make `Create Summary` visually dominant and the default button.
- Ensure `Clear saved presets` is not auto-default and cannot accidentally win
  Enter-key activation.
- Add confirmation before clearing saved CSV presets.
- Tighten CSV input/output extension behavior:
  - do not silently append `.csv` to arbitrary selected input paths
  - ensure output paths end with `.xlsx`
- Separate CSV worker failure reporting from cancellation reporting.

Acceptance tests:

- Main window has no `csv_summary_button`.
- Tools menu includes `CSV Summary...` and
  `Enrich existing database metadata...`.
- CSV Summary offscreen layout has no large blank header area.
- `Create Summary` is default/dominant; `Clear saved presets` is secondary.
- Clearing presets requires confirmation.
- CSV worker errors show an error state, not a canceled state.

### Task 2: Parsing Fast-Then-Enrich Modeless Flow

Recommended owner: worker subagent

Recommended model: `gpt-5.5`

Reason: cross-thread workflow behavior with data integrity and archive-source
edge cases; highest risk item.

Files likely owned:

- `modules/parsing_dialog.py`
- `modules/main_window.py`
- `modules/parse_reports_thread.py` only if archive handling requires it
- `tests/test_parsing_dialog_selection_flow.py`
- `tests/test_main_window_metadata_ui.py`
- `tests/test_metadata_enrichment_thread.py`
- `docs/user_manual/parsing.md`
- `docs/user_manual/main_window.md`

Required changes:

- Keep the `Fast import, then enrich metadata` combo option.
- For GUI parsing, send `ParseReportsThread` a light parse request only:
  - `metadata_parsing_mode="light"`
  - `run_background_metadata_enrichment=False`
- Add a parsing-dialog signal or callback for successful post-parse enrichment
  request, for example `metadata_enrichment_requested(db_file)`.
- On successful fast-then-enrich parsing:
  - close progress dialog
  - close Parsing
  - update main-window selected database
  - call main-window modeless metadata enrichment
- Do not start enrichment after parse error or cancellation.
- Keep normal Fast import and Complete import behavior unchanged.
- Decide archive behavior before implementation:
  - current embedded enrichment can read temp-extracted files before cleanup
  - modeless enrichment may fail if archive extraction paths disappear
  - acceptable fixes include guarded fallback to embedded enrichment for archives,
    durable extracted paths, or re-extraction support.

Acceptance tests:

- Fast mode sends light parse and does not request enrichment.
- Fast-then-enrich sends light parse and requests modeless enrichment only after
  success.
- Complete mode sends complete parse and does not request modeless enrichment.
- Canceled/error parses do not start enrichment.
- Main window receives the signal and starts `MetadataEnrichmentThread`.
- Export/Modify Database buttons remain usable while enrichment runs.
- Archive-source behavior has an explicit regression test or an explicit
  product decision in code/docs.

### Task 3: Grouping Enter-Key Workflow Regression

Recommended owner: worker subagent

Recommended model: `gpt-5.3-codex`

Reason: narrow PyQt event-handling fix with existing tests.

Files likely owned:

- `modules/data_grouping.py`
- `tests/test_data_grouping_delete_key.py`
- `tests/test_data_grouping_layout.py`
- `docs/user_manual/export_grouping.md`

Required changes:

- `Use grouping` and `Clear grouping` must not be default/auto-default buttons.
- Enter should mirror visible/double-click workflows:
  - focused Reference list: create group prefilled with selected reference
  - focused Part list: create/add selected parts to a group
  - focused Groups list: rename/edit selected group
  - focused Part-in-group list: consume Enter without applying grouping
- Delete/Backspace behavior should remain unchanged.
- Apply/Clear grouping should stay explicit button actions only.

Acceptance tests:

- Enter on Reference list calls `create_group(initial_group_name=...)`.
- Enter on Part list calls `create_group()`.
- Enter on Groups list calls `rename_group()`.
- Enter on Part-in-group list is consumed and does not apply grouping.
- `Use grouping` is not default or auto-default in the real PyQt dialog.

### Task 4: Progress Dialog Dancing Duck GIF

Recommended owner: worker subagent

Recommended model: `gpt-5.4-mini`

Reason: small UI polish task with bounded tests.

Files likely owned:

- `modules/worker_progress_dialog.py`
- `tests/test_ui_revamp_foundation_layout.py`

Required changes:

- Increase the GIF size from the current 96 px presentation.
- Preserve the GIF aspect ratio; do not force a square if the source is not
  square.
- Keep the progress dialog text-first enough that status and cancel remain easy
  to see.
- Own and clean up any temporary GIF file, or switch to an approach that avoids
  leaked temp files.

Acceptance tests:

- Movie scaled size is larger than current 96 px.
- Aspect ratio is preserved within a small tolerance.
- Dialog remains within available offscreen desktop size.
- Status text and Cancel button remain present.
- Temporary GIF file is cleaned up after dialog close, if temp files remain.

### Task 5: Help Menu And Documentation Links

Recommended owner: worker subagent

Recommended model: `gpt-5.4`

Reason: docs/navigation task with release packaging implications.

Files likely owned:

- `modules/help_menu.py`
- `modules/main_window.py`
- `modules/group_analysis_writer.py`
- `tests/test_help_menu.py`
- `tests/test_main_window_metadata_ui.py`
- `README.md`
- `docs/user_manual/*.md`

Required changes:

- Verify all in-app Help/manual actions open GitHub-rendered Markdown/PDF URLs,
  not local file URLs.
- Keep local file existence checks only as a development guard if useful; the
  opened URL should be GitHub-rendered docs.
- Replace hard-coded `master` doc refs with a deliberate release docs ref or a
  configurable constant. For this release, decide whether it should remain
  `master`, point to the release branch/tag, or use `VersionDate` metadata.
- Move `About`, `Release notes`, and manual actions under a conventional Help
  menu.
- Keep Tools for operational tools:
  - `CSV Summary...`
  - `Enrich existing database metadata...`
- Update docs so they describe the new menu hierarchy.

Acceptance tests:

- `manual_url()` returns GitHub `https://github.com/.../blob/...` URLs.
- `open_manual()` calls `QDesktopServices.openUrl()` with GitHub URL.
- No in-app help/manual action opens `file://` or a local path.
- Main-window top-level menus are conventional and stable:
  - `Tools`
  - `Help`
- Help contains manual, release notes, and About actions.

### Task 6: Release Notes, Release Identity, And Docs Sync

Recommended owner: main agent

Recommended model: parent model, no subagent required

Reason: final integration work should happen after behavior changes are known.

Files likely owned:

- `VersionDate.py`
- `CHANGELOG.md`
- `README.md`
- `docs/release_checks/release_candidate_checklist.md`
- `docs/roadmaps/UI_UX_REVAMP_SUMMARY_PLAN.md`
- `docs/roadmaps/UI_UX_RELEASE_FIX_PLAN.md`
- `tests/test_release_metadata_sync.py`

Required changes:

- Update current release notes with user-facing bullets:
  - CSV Summary moved to Tools and has clearer primary action
  - Fast import with enrichment now returns control to the main window
  - Grouping keyboard shortcuts restored
  - Larger clearer parsing/export progress animation
  - Help/manual links open GitHub docs
  - calmer release-ready desktop layout polish
- Decide official release identity:
  - if this is first official release, remove `rc1` from runtime-facing labels
  - use a concrete build date; if finalized on 2026-05-09, use `260509`
- Run `python scripts/sync_release_metadata.py` after release metadata edits.
- Update docs and checklist evidence.

Acceptance tests:

- `python scripts/sync_release_metadata.py --check` passes.
- Release notes are short, user-facing, and non-technical.
- Version labels agree across runtime, About, release notes, README, changelog,
  and packaging metadata tests if present.

### Task 7: Final Release Validation And Publish Follow-Through

Recommended owner: main agent

Recommended model: parent model, no subagent required

Reason: final verification and CI follow-through should happen in one place.

Commands:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
python -m ruff check .
python scripts/sync_release_metadata.py --check
PYTHONPATH=. python scripts/benchmark_paths.py --output-dir /tmp/metroliza-perf-ci-warmup --pdf-count 20 --report-count 40 --headers-per-report 6 --csv-rows 300 --csv-columns 4 --fit-group-count 12 --fit-sample-size 90 --fit-monte-carlo-samples 40 --group-preprocess-groups 10 --group-preprocess-values 1500 --cmm-bench-report-count 120 --cmm-bench-measurements-per-report 120
git diff --check
```

Publish requirements:

- Commit in small, reviewable chunks.
- Push `codex/metroliza-ui-ux-visual-revamp`.
- Update PR #893 body with final validation.
- Wait for GitHub CI green.
- If CI fails, inspect job logs before editing.

## Suggested Execution Order

1. Task 1: CSV Summary placement/layout/action fixes.
2. Task 3: Grouping keyboard regression.
3. Task 2: Parsing fast-then-enrich modeless enrichment.
4. Task 4: Progress GIF sizing/cleanup.
5. Task 5: Help/menu/docs-link cleanup.
6. Task 6: Release notes, release identity, docs sync.
7. Task 7: Full validation, push, PR update, CI green.

## Resolved Decisions

1. Official release label:
   - Use `2026.05 (build 260509)` for the first official release branch state.
2. Archive imports with fast-then-enrich:
   - Folder imports use modeless main-window enrichment after light parsing.
   - Archive imports keep embedded enrichment because temporary extraction paths
     are cleaned up when parsing ends.
3. Documentation ref:
   - In-app GitHub manual links default to `master` to avoid pre-tag 404s.
   - `METROLIZA_RELEASE_DOCS_REF` can override the ref for release builds.
