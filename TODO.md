# TODO

Last audited on 2026-02-25.

## Completed (moved from open follow-up)
- [x] Added credential/token gitignore guardrails (`credentials.json` + `token.json`) and shipped `config/google/credentials.example.json` template.
- [x] Added Google target selection + destination metadata contract plumbing in export dialog/validation flow.

## Open implementation tasks

### Google Sheets Drive conversion pipeline
- [ ] Implement Drive upload+convert flow for Google Sheets target.
  - [ ] Add service-layer API that uploads generated `.xlsx` with conversion request and returns converted file ID/URL.
  - [ ] Add unit tests for upload/convert request payloads, success mapping, and retryable-failure handling.
  - [ ] Wire export completion metadata to include converted-sheet link when target is Google Sheets.

### Post-conversion validation + fallback messaging
- [ ] Add post-conversion validation and fallback reporting.
  - [ ] Add a smoke-check routine that verifies expected worksheet/tab presence after conversion.
  - [ ] Surface non-blocking warning copy when conversion degrades unsupported formatting/charts.
  - [ ] Ensure export completion always reports `.xlsx` fallback path/link when conversion validation fails.

### Phase 2 decomposition follow-through (`ExportDataThread`)
- [ ] Continue remaining `ExportDataThread` decomposition slices.
  - [ ] Extract next worksheet-write section into a pure helper and cover with focused parity tests.
  - [ ] Extract next chart-rendering section into helper(s) with deterministic series/range assertions.
  - [ ] Keep regression coverage green for worksheet range parity and chart-series parity after each extraction slice.

## Maintenance
- [ ] Keep `README.md`, `IMPLEMENTATION_PLAN.md`, and this `TODO.md` synchronized after each roadmap PR.
