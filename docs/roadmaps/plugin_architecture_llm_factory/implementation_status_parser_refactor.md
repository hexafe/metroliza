# Implementation Status: Parser Refactor (Base + Registry)

## Scope covered
This implementation aligns the current runtime with roadmap Pass 1 / Pass 3 intent by introducing:
- shared parser base abstraction (`BaseReportParser`),
- parser registry + detector factory (`report_parser_factory`),
- workflow decoupling (`ParseReportsThread` uses factory, not concrete parser).

## What is now implemented
1. **Base parser contract**
   - `open_report()` and `split_text_to_blocks()` are abstract.
   - Shared metadata and legacy aliases are standardized in one place.

2. **Concrete plugin parser (CMM)**
   - `CMMReportParser` now inherits from `BaseReportParser`.
   - Existing DB persistence, telemetry backend tracking, and tolerance flow are preserved.

3. **Registry and detection**
   - `report_parser_factory` now supports parser registration and pluggable detection.
   - Runtime parser creation is centralized through `get_parser(...)`.

4. **Workflow orchestration**
   - `ParseReportsThread` no longer instantiates CMM parser directly.
   - Future parsers can be added through registration without thread changes.

## Compatibility decisions
- Kept legacy aliases (`pdf_*`) to avoid breaking older callsites/tests.
- Kept `cmm_open()` alias as compatibility shim for historical method usage.
- Kept `modules.cmm_report_parser` shim import path.

## Deferred roadmap items
The following roadmap items remain future work (outside this incremental refactor):
- full `ParseResultV2` canonical schema,
- full plugin manifest/probe governance lifecycle,
- legacy <-> V2 adapters,
- plugin loader from external packages / entrypoints.
