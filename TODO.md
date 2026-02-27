# TODO

Last audited on 2026-02-27.

## Completed (audited)
- [x] Added credential/token gitignore guardrails (`credentials.json` + `token.json`) and shipped `config/google/credentials.example.json` template.
- [x] Added Google target selection + destination metadata contract plumbing in export dialog/validation flow.
- [x] Implemented Drive upload+convert flow for Google Sheets target.
  - [x] Added service-layer API that uploads generated `.xlsx` with conversion request and returns converted file ID/URL.
  - [x] Added unit tests for upload/convert request payloads, success mapping, and retryable-failure handling.
  - [x] Wired export completion metadata to include converted-sheet link when target is Google Sheets.
- [x] Added post-conversion validation + fallback reporting.
  - [x] Added a smoke-check routine that verifies expected worksheet/tab presence after conversion.
  - [x] Surface non-blocking warning copy when conversion degrades unsupported formatting/charts.
  - [x] Ensure export completion reports `.xlsx` fallback path/link for conversion outcomes.
- [x] Migrated direct SQLite call-sites to shared retry/transaction helpers in `modules/db.py`.
- [x] Landed additional `ExportDataThread` decomposition slices with helper extraction + parity-focused tests.
- [x] Completed Google Sheets GS5 testing-depth scope.
  - [x] Expanded mocked failure/edge-case coverage for conversion warnings and fallback messaging/content assertions.
  - [x] Documented optional/manual sandbox Drive smoke-check runbook and expected-result checklist.

## Open implementation tasks

### Phase 2 decomposition follow-through (`ExportDataThread`)
- [x] Continue remaining `ExportDataThread` decomposition slices.
  - [x] Extract next worksheet-write section into a pure helper and cover with focused parity tests.
  - [x] Extract next chart-rendering section into helper(s) with deterministic series/range assertions.
  - [x] Keep regression coverage green for worksheet range parity and chart-series parity after each extraction slice.

### Google Sheets post-completion operational checks
- [x] Keep optional/manual sandbox Drive smoke checks release-gated and record outcomes when executed.

## Maintenance
- [ ] Keep `README.md`, `IMPLEMENTATION_PLAN.md`, `TODO.md`, and `GOOGLE_SHEETS_MIGRATION_PLAN.md` synchronized after each roadmap PR.
