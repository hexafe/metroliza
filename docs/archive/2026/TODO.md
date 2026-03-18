# TODO

Last audited: 2026-02-27.

> **Historical context note:** This TODO file is archived context. For active freeze/open-testing/release status, use [`docs/release_checks/release_status.md`](../../release_checks/release_status.md) first.

## Archived workstream status
- **Core roadmap phases (0-4): Completed**.
- **Google Sheets migration (GS0-GS5): Partial** (implementation complete; release-gated operational smoke-check practice remains open).
- **CSV Summary roadmap: Completed**.

## Completed implementation items (audited)
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

## Open implementation items (archived list)
- [ ] Maintain optional/manual sandbox Drive smoke checks as an ongoing release practice, and record outcomes in release notes using the standard evidence format (command run, date/time, environment/sandbox account, pass/fail, fallback `.xlsx` behavior observed, link/log location) whenever Google auth/conversion behavior changes.
- [ ] Execute an architectural cleanup pass for export flows with behavior parity as a strict requirement.
  - [ ] Split `modules/ExportDataThread.py` responsibilities into smaller modules that separate orchestration, pure payload/data-prep logic, and backend I/O/post-processing concerns (for example: `export_orchestrator`, `export_payload_builders`, `export_postprocess`).
  - [ ] Refactor `modules/CSVSummaryDialog.py` and `modules/ExportDialog.py` to isolate UI state management from validation and export request-building logic.
  - [ ] Add or update focused unit tests for extracted pure functions before changing behavior, then keep those tests green throughout the decomposition.
  - [ ] Add a non-blocking CI size/complexity guard that reports modules over an agreed threshold for visibility (informational reporting only; no merge block).

### Open-item RC triage decision table

| Open item | Gate | Owner | Target RC | Rationale |
| --- | --- | --- | --- | --- |
| Maintain optional/manual sandbox Drive smoke checks as an ongoing release practice and evidence capture for Google auth/conversion changes. | pre-open-testing | QA lead + Release manager | Current RC before freeze sign-off | This check directly validates release-gated Google conversion behavior and must be executed before freeze can proceed.
| Execute architectural cleanup pass for export flows with strict behavior parity. | defer | App architecture owner | 1.9.0-rc1 | This is risk-reduction/refactor scope, not a release integrity blocker for the current RC.
| Split `modules/ExportDataThread.py` into orchestration, payload/data-prep, and post-processing modules. | defer | Export pipeline maintainer | 1.9.0-rc1 | Dependency: complete decomposition design doc and baseline parity tests before moving production logic.
| Refactor `modules/CSVSummaryDialog.py` and `modules/ExportDialog.py` to isolate UI state from validation/request-building logic. | defer | UI/workflow maintainer | 1.9.0-rc2 | Dependency: land `ExportDataThread` split first so dialog extraction targets stable service boundaries.
| Add/update focused unit tests for extracted pure functions before behavior-preserving decomposition. | defer | QA automation + module owners | 1.9.0-rc1 | Dependency: identify extraction seams from architecture plan, then add parity tests as a prerequisite for refactor PRs.
| Add non-blocking CI size/complexity visibility guard for oversized modules. | defer | Dev productivity owner | 1.9.0-rc2 | Dependency: finalize threshold policy and reporting mechanism (informational only, no merge block).

## Carry-forward maintenance items only
- [ ] Keep `README.md`, `CHANGELOG.md`, `IMPLEMENTATION_PLAN.md`, `TODO.md`, and `GOOGLE_SHEETS_MIGRATION_PLAN.md` synchronized after each release-candidate documentation PR.
