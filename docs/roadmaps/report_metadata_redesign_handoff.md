# Report Metadata Redesign Handoff

Last updated: 2026-04-17 07:17 Europe/Warsaw

Roadmap link: [report_metadata_redesign_audit_plan.md](report_metadata_redesign_audit_plan.md)

## Current Branch State

- Working branch: `codex/report-metadata-redesign`
- Last known base commit before this continuation: `860659f Refactor report queries to view-backed helpers`
- The report metadata redesign implementation has been completed locally on this branch and is ready for commit/push after validation.
- Known unrelated untracked files present before this handoff: `.codex` and `docs/roadmaps/hexafe_groupstats_integration_codex_note.md`.
- The implementation roadmap file `docs/roadmaps/report_metadata_redesign_audit_plan.md` is part of this worktree.

## What Has Been Implemented

### Schema and Repository

- Added `modules/report_schema.py`.
- Added the new report metadata schema:
  - `source_files`
  - `source_file_locations`
  - `parsed_reports`
  - `report_metadata`
  - `report_metadata_candidates`
  - `report_metadata_warnings`
  - `report_measurements`
  - read views `vw_report_overview`, `vw_measurement_export`, `vw_grouping_reports`
- Deliberate schema adjustment from the frozen spec: source paths are stored in `source_file_locations` so `source_files` remains true content identity by `sha256`. This follows the optimized database proposal discussed before implementation.
- Replaced `modules/cmm_schema.py` with a thin compatibility wrapper around `ensure_report_schema`.
- Added `modules/report_repository.py` with:
  - SHA-256 source file upsert
  - parsed report upsert by `source_file_id`
  - canonical metadata replacement
  - candidate/warning replacement
  - flat measurement replacement
  - semantic duplicate warning helper
- Fixed a duplicate-detection bug in the synthetic native-row Python persistence path by allowing `ReportRepository.persist_parsed_report(..., source_sha256=...)`.
- Added `modules/report_metadata_persistence.py` as a neutral compatibility wrapper. Persistence ownership remains in `ReportRepository`; the wrapper only preserves the frozen module list/import surface.

### Metadata Extraction

- Added:
  - `modules/report_metadata_models.py`
  - `modules/report_metadata_normalizers.py`
  - `modules/report_metadata_profiles.py`
  - `modules/report_metadata_selector.py`
  - `modules/report_metadata_extractor.py`
  - `modules/report_identity.py`
- Implemented the `cmm_pdf_header_box` profile with serial and drawing variants.
- Implemented pure normalizers for reference, date, time, part name, revision, stats count, sample number, operator, and comment.
- Implemented filename fallback candidates as fallback evidence, not final truth.
- Implemented candidate scoring, selected candidate marking, warning emission, and stats-count projection into `sample_number`.

### Parser and Persistence Integration

- Refactored `modules/base_report_parser.py` so filename metadata is no longer finalized in the constructor.
- Refactored `modules/cmm_report_parser.py` to:
  - extract page count and first-page dimensions
  - build first-page header items from top-band lines
  - run metadata extraction before persistence
  - compute identity hash
  - persist through `ReportRepository`
  - populate flat `report_measurements`
  - compute `measurement_count`, `has_nok`, and `nok_count`
- `modules/cmm_native_parser.py` now keeps native parsing/normalization available, but routes DB persistence through the Python repository because the Rust writer still targets the old schema.
- Direct/synthetic parser callers that set legacy parser fields still get those values as fallback metadata when structured extraction cannot find them.

### Query, Filtering, Grouping, Export

- A subagent committed and pushed `860659f`, which added `modules/report_query_service.py` and moved grouping/filter helpers toward view-backed queries.
- After that commit, local edits further patched:
  - `modules/export_dialog.py`: default filter query now uses `build_measurement_export_query()`.
  - `modules/export_data_thread.py`: fallback export query now uses `vw_measurement_export`.
  - `modules/filter_dialog.py`: already routed through report query helpers from the subagent work.
  - `modules/data_grouping_service.py` and `modules/export_grouping_utils.py`: report-id-first grouping from the subagent work.
  - `modules/contracts.py`: grouping DataFrame validation now requires `REPORT_ID`; old composite fallback was removed.
  - `modules/report_fingerprint.py`: no filename-composite fallback remains; it now prefers `report_id`, `sha256`, or `identity_hash`.
  - `modules/modify_db.py`: ported from `REPORTS`/`MEASUREMENTS` to `report_metadata` and `report_measurements`.
  - export and group-analysis integration tests now seed through the new schema/repository and pass `REPORT_ID`-first grouping frames.

## Tests Added or Updated

New tests added:

- `tests/test_report_metadata_normalizers.py`
- `tests/test_report_metadata_extractor.py`
- `tests/test_report_metadata_persistence.py`
- `tests/test_report_schema_repository.py`

Updated tests so far:

- `tests/test_report_query_service.py`
- `tests/test_data_grouping_filter_query.py`
- `tests/test_modifydb_update_statements.py`
- `tests/test_phase0_hotfixes.py`
- `tests/test_thread_flow_helpers.py`
- `tests/test_cmm_parser_parity.py`
- `tests/test_cmm_native_parser_runtime.py`
- `tests/test_phase2_db_migrated_behaviors.py`
- `tests/test_phase2_db_migration.py`
- `tests/test_phase4_integration_happy_path.py`
- `tests/test_export_data_thread_group_analysis.py`
- `tests/test_export_query_service.py`
- `tests/test_export_workbook_output.py`
- `tests/test_parser_plugin_contracts.py`
- `tests/test_schema_index_query_plans.py`

## Completed Verification

```bash
python -m pytest tests/test_cmm_parser_parity.py tests/test_cmm_native_parser_runtime.py tests/test_phase2_db_migrated_behaviors.py tests/test_schema_index_query_plans.py -q
```

Result: `69 passed, 3 skipped`.

```bash
python -m pytest tests/test_phase4_integration_happy_path.py tests/test_export_workbook_output.py tests/test_export_data_thread_group_analysis.py tests/test_export_query_service.py tests/test_report_metadata_persistence.py -q
```

Result: `33 passed, 6 subtests passed`.

```bash
python -m pytest tests/test_parser_plugin_contracts.py tests/test_phase2_db_migration.py -q
```

Result: `10 passed`.

```bash
python -m pytest -q
```

Result: `1161 passed, 22 skipped, 7 warnings, 57 subtests passed`.

```bash
python -m ruff check .
```

Result: `All checks passed!`.

## Storage And Identity Summary

The implementation now has three storage layers:

- Physical source identity: `source_files` stores content identity keyed by `sha256`; `source_file_locations` stores path, directory, file name, extension, and active location history for that content.
- Parsed report identity: `parsed_reports.id` is the internal join key for one parser output per source file. It stores parser/template status, page/measurement rollups, NOK rollups, confidence, and `identity_hash`.
- Report facts and audit payloads: `report_metadata` stores the selected canonical report metadata; `report_metadata_candidates` and `report_metadata_warnings` store selection evidence and extraction issues; `report_measurements` stores the flat export/grouping measurement rows.

Use `source_files.sha256` to detect the same physical file content, `parsed_reports.id` as the only internal relational/report key, and `parsed_reports.identity_hash` to detect semantic duplicate reports across different source files. Do not use `FILELOC`, `FILENAME`, `REFERENCE`, `DATE`, or `SAMPLE_NUMBER` as identity.

The three read views are:

- `vw_report_overview`: report-level UI/listing surface.
- `vw_measurement_export`: flat measurement export/filter surface with compatibility aliases such as `FILELOC` and `FILENAME`.
- `vw_grouping_reports`: report-level grouping surface keyed by `report_id`.

Filters, grouping, and export now use report-id-first query helpers from `modules/report_query_service.py`. Grouping DataFrames must include `REPORT_ID`; display fields remain for workbook/UI readability only.

## Intentional Compatibility Surfaces

- `modules/report_query_service.py` still emits `FILELOC` and `FILENAME` aliases for workbook/export compatibility.
- `modules/export_data_thread.py` still writes the all-measurements worksheet as `MEASUREMENTS`.
- `modules/cmm_native_parser.py` keeps native parsing/normalization available, but DB persistence is routed through Python because the Rust native writer still targets legacy tables.

## Remaining Deferred Items

- `modules/native/cmm_parser/src/lib.rs` still contains the old Rust persistence SQL. It must remain bypassed or be ported in a follow-up.
- Structured first-page extraction currently builds selector items from top-band page text lines. The selector supports structured items, but `CMMReportParser.open_report()` does not yet use PyMuPDF `words`/`blocks`.
- The four acceptance PDFs from the frozen spec are not present in the repo. Final acceptance needs those PDFs or equivalent structured fixtures.
- The frozen spec listed `source_files.absolute_path`, `directory_path`, `file_name`, and `file_extension` directly on `source_files`. The implemented design moved those to `source_file_locations` for better content dedupe. This was intentional and should be kept unless the user reverses that architecture decision.

## How To Resume

Start with:

```bash
git status --short --branch
python -m pytest -q
python -m ruff check .
```

Then commit, push `codex/report-metadata-redesign`, check CI, and correct any CI-only failures.
