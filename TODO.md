# TODO

## Immediate next slices (Phase 2)
- [ ] Extract additional `ExportDataThread` writer helpers:
  - [x] summary-sheet row layout planner
  - [x] chart insertion/format policy helper
  - [x] per-header worksheet write bundle helper
- [x] Add regression tests for extracted writer helpers to preserve worksheet range and chart-series parity.
- [x] Add one focused locked-db retry/rollback regression test covering parse/export overlap behavior.

## Google Sheets roadmap follow-up
- [ ] Add credential/token security guardrails (`credentials.json` + `token.json` in `.gitignore`) and ship `config/google/credentials.example.json` template.
- [ ] Start Google Drive conversion pipeline for Google Sheets target (upload generated `.xlsx` and convert server-side).
- [ ] Add Google target selection + destination metadata plumbing to contract validation and export dialog wiring.
- [ ] Add post-conversion validation + `.xlsx` fallback reporting in export completion flow.

## Maintenance
- [ ] Keep `README.md` and `IMPLEMENTATION_PLAN.md` in sync after each roadmap PR.
