# Report Metadata Redesign Audit Plan

Branch: `codex/report-metadata-redesign-audit`

Implementation handoff: [report_metadata_redesign_handoff.md](report_metadata_redesign_handoff.md)

## Audit Summary

The frozen specification is directionally correct for this codebase. The current app has a small legacy storage model and uses parser output as an export-ready table shape. That makes the proposed split into source identity, parsed report metadata, audit side tables, and flat measurements the right architectural move.

The main gap is scale of impact. This is not a contained parser patch. A repository scan found 43 module, test, and doc files that reference the old `REPORTS` / `MEASUREMENTS` shape, `REPORT_ID`, `GROUP_KEY`, `FILELOC`, `FILENAME`, or `SAMPLE_NUMBER`.

No online research was needed for this audit. The necessary decisions are driven by local schema, parser, query, and test code. PyMuPDF is already the local PDF dependency, and the required page text extraction can be implemented against its existing page text APIs.

## Current State

Storage is currently defined in `modules/cmm_schema.py` as two tables:

- `REPORTS`: `ID`, `REFERENCE`, `FILELOC`, `FILENAME`, `DATE`, `SAMPLE_NUMBER`
- `MEASUREMENTS`: flat numeric measurement columns plus `HEADER` and `REPORT_ID`

There are no report metadata audit tables, no source file table, no parsed report table, no view layer, and no schema versioning path beyond idempotent bootstrap helpers.

Metadata is finalized too early. `modules/base_report_parser.py` derives date, reference, and sample number from filename in the constructor. `modules/cmm_report_parser.py` then persists those filename-derived values as report truth.

Duplicate handling conflicts with the frozen spec in three places:

- parse discovery batches by filename and reference/date candidates
- CMM persistence skips by filename and then by a composite report tuple
- native persistence repeats the same composite duplicate check

Export and grouping are partially `REPORT_ID`-aware but not `report_id`-first. Grouping prefers a derived composite `GROUP_KEY`, exports partition by `REFERENCE`, and summary SQL keys on `(REFERENCE, HEADER, AX)`.

The four acceptance PDFs named in the frozen spec are not present in the repository. Only `tests/fixtures/pdf/cmm_smoke_fixture.pdf` exists locally, so fixture acquisition or synthetic structured page fixtures must happen before final acceptance can be proven.

## Review Of Frozen Spec

Strong parts:

- `source_files.sha256` cleanly separates physical file identity from report identity.
- `parsed_reports.id` as the only internal join key fixes the current filename/composite leakage.
- `report_metadata_candidates` and `report_metadata_warnings` are the right audit model and should stay out of hot export paths.
- Keeping `report_measurements` flat is the right performance decision for current export/grouping code.
- Views for overview, export, and grouping give the UI a stable surface while storage changes underneath.

Required adjustments while implementing:

- Replace `modules/cmm_schema.py` with a neutral schema bootstrap module, but keep a thin import-compatible wrapper only if needed by unrelated code during the rewrite.
- Treat the current native persistence path as a follow-up unless it can be adapted cleanly. The Python path should become canonical first.
- Replace raw filter SQL strings with query helpers that target `vw_measurement_export`; otherwise the UI will keep depending on table internals.
- Rewrite tests that seed legacy tables directly. Assertion tweaks will not be enough because many tests create the old schema inline.
- Keep existing parser plugin contracts as adapters during the rewrite, but do not let `ParseResultV2.report` remain the canonical metadata source.

## Impact Map

Schema and persistence:

- `modules/cmm_schema.py`
- `modules/db.py`
- `modules/cmm_report_parser.py`
- `modules/cmm_native_parser.py`
- `modules/parse_reports_thread.py`
- `modules/report_fingerprint.py`

Parser and metadata:

- `modules/base_report_parser.py`
- `modules/cmm_report_parser.py`
- `modules/cmm_parsing.py`
- `modules/parser_plugin_contracts.py`
- `modules/report_parser_factory.py`

Query, grouping, export, filtering:

- `modules/data_grouping_service.py`
- `modules/data_grouping.py`
- `modules/export_grouping_utils.py`
- `modules/export_query_service.py`
- `modules/export_data_thread.py`
- `modules/export_dialog.py`
- `modules/export_dialog_service.py`
- `modules/filter_dialog.py`
- `modules/contracts.py`

High-churn tests:

- `tests/test_cmm_parser_parity.py`
- `tests/test_cmm_native_parser_runtime.py`
- `tests/test_schema_index_query_plans.py`
- `tests/test_phase2_db_migrated_behaviors.py`
- `tests/test_phase4_integration_happy_path.py`
- `tests/test_thread_flow_helpers.py`
- `tests/test_data_grouping_service.py`
- `tests/test_data_grouping_filter_query.py`
- `tests/test_export_grouping_and_sorting.py`
- `tests/test_export_query_service.py`
- `tests/test_export_workbook_output.py`
- `tests/test_export_data_thread_group_analysis.py`

## Implementation Plan

### Phase 1: Schema Foundation

Add `modules/report_schema.py` with the frozen tables, indexes, and views. Use one bootstrap entry point that creates the new schema from scratch. Include table-level validation tests for all columns, indexes, foreign keys, allowed status values where enforced, and the three views.

Add `modules/report_repository.py` for transactional persistence:

- upsert or fetch `source_files` by sha256
- create/update one `parsed_reports` row per source file
- replace canonical metadata for a report
- replace candidates and warnings for a report
- bulk insert flat measurements
- detect same `identity_hash` across different source files and persist the required warning

### Phase 2: Metadata Model And Normalizers

Add the required dataclass modules:

- `modules/report_metadata_models.py`
- `modules/report_metadata_normalizers.py`
- `modules/report_metadata_profiles.py`
- `modules/report_metadata_selector.py`
- `modules/report_metadata_extractor.py`
- `modules/report_metadata_persistence.py`
- `modules/report_identity.py`

Write pure unit tests first for date, time, reference, revision, part name, stats count, sample number, operator, and comment normalization.

Implement the `cmm_pdf_header_box` profile with serial and drawing variants. Candidate emission must include filename fallback candidates but selection must prefer structured header candidates.

### Phase 3: Parser Rewrite

Refactor `BaseReportParser` so the constructor only builds source descriptors. Legacy-style properties may remain as projections from canonical metadata after extraction.

Refactor `CMMReportParser` to:

- open the PDF once for page count, first-page dimensions, structured first-page text, and plain measurement lines
- extract metadata after page 1 is available
- detect template family and variant through the metadata profile
- parse measurements using the existing block parser
- enrich flat rows with `page_number`, `row_order`, `section_name`, `feature_label`, `characteristic_family`, `status_code`, and `raw_measurement_json`
- compute `measurement_count`, `has_nok`, and `nok_count`
- persist through `report_repository`

Stop filename-only duplicate checks. The parse loop should precompute sha256 for discovered files and use `source_files.sha256` as the physical duplicate guard.

### Phase 4: Query Services And UI Integration

Add `modules/report_query_service.py` as the only normal read surface for report overview, measurement export, grouping, and filter options.

Move export defaults from raw `REPORTS` / `MEASUREMENTS` SQL to `vw_measurement_export`.

Move grouping to `vw_grouping_reports` and make `report_id` the stored and merged grouping key. Keep display columns such as reference, date, sample number, part name, revision, and file name for UI readability only.

Update filtering to preserve:

- AX
- HEADER
- REFERENCE
- DATE range

Add report-level filters:

- PART NAME
- REVISION
- TEMPLATE VARIANT
- SAMPLE NUMBER
- HAS_NOK

The filter dialog should build a query through a helper, not interpolate list values into raw SQL.

### Phase 5: Export And Grouping Migration

Update export helpers to expect `report_id` in every measurement export row.

Use `report_id` for grouping assignment merges. Keep reference-based worksheet partitioning only as a presentation choice, not as an identity rule.

Update summary SQL cache keys from `(REFERENCE, HEADER, AX)` to a report-aware or export-view-safe shape. For cross-report charts, continue grouping by characteristic display fields, but do not use those as report identity.

### Phase 6: Test And Performance Guardrails

Add focused tests for:

- sha256 source dedupe
- identity hash stability
- serial and drawing variant detection
- header-over-filename selection
- warning persistence for conflicts and fallbacks
- stats count projection into sample number
- page count and NOK rollups
- flat measurement persistence
- all three views
- `report_id`-first grouping and export merges
- absence of filename-only duplicate guards

Rewrite existing integration tests to seed through `report_schema` helpers or through repository methods instead of inline legacy DDL.

Add query-plan tests for the new views and indexes. Candidate and warning tables must not appear in normal export query plans.

## Deferred Items

- Mandatory OCR integration
- Separate section and feature tables
- Measurement modifier table unless it is low-risk after the main rewrite
- Native persistence parity for the new schema if it slows the first implementation
- Semantic duplicate merging
- Broad UI redesign beyond the required filter additions

## Execution Order

1. Land schema, repository, identity, and view tests.
2. Land normalizers, profile detection, selector, and extractor tests.
3. Rewrite Python parser persistence and parse thread duplicate handling.
4. Migrate query service, filter, grouping, and export to view-based reads.
5. Update integration tests and performance guardrails.
6. Adapt or temporarily bypass native persistence behind the existing runtime switch.
7. Run the full test suite and add the four acceptance PDFs or equivalent structured fixtures before final sign-off.
