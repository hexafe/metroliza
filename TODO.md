# TODO

## Immediate next slices (Phase 2)
- [ ] Extract additional `ExportDataThread` writer helpers:
  - [x] summary-sheet row layout planner
  - [x] chart insertion/format policy helper
  - [x] per-header worksheet write bundle helper
- [x] Add regression tests for extracted writer helpers to preserve worksheet range and chart-series parity.
- [ ] Add one focused locked-db retry/rollback regression test covering parse/export overlap behavior.

## Google Sheets roadmap follow-up
- [ ] Start GS2 backend split skeleton (`ExcelExportBackend` / `GoogleSheetsExportBackend`) while keeping Excel as default.
- [ ] Add backend selection plumbing to contract validation and export dialog wiring.

## Maintenance
- [ ] Keep `README.md` and `IMPLEMENTATION_PLAN.md` in sync after each roadmap PR.
