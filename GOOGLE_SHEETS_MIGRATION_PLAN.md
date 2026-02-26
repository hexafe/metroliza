# Google Sheets Migration Plan (Drive conversion from generated `.xlsx`)

## Goal
Keep Metroliza export Excel-first (`xlsxwriter`) and add a Google mode that uploads the generated `.xlsx` to Google Drive for server-side conversion to a native Google Sheet, while preserving current analytical output:
- raw measurement tables,
- computed statistics,
- per-header trend charts,
- summary matplotlib/seaborn plots.

---

## Current-state constraints to address
The current export path already produces rich `.xlsx` output with formulas, charts, and summary images. Re-implementing that surface directly via Sheets API would be high effort and high drift risk.

Key constraints and implications:
1. Horizontal-sheet export is tightly coupled to mature `xlsxwriter` logic that we should reuse.
2. Full chart/style parity through native Sheets chart specs is expensive to maintain.
3. Summary images and worksheet layout are already solved in Excel output.
4. Google Drive supports direct import/conversion of `.xlsx` files, which can offload most translation complexity to Google.

---

## Proposed target architecture
Adopt a **conversion pipeline** instead of a full backend rewrite:
- Continue generating `.xlsx` exactly as today (single source of truth).
- If export target is Google Sheets, upload the generated file with Google Drive API and request conversion (`application/vnd.google-apps.spreadsheet`).
- Return the converted file ID/URL to the user and optionally keep local `.xlsx` for backup/audit.

This minimizes implementation risk and keeps Excel + Google outputs aligned by construction.

---

## Phased implementation plan

### Phase 0 — Export target plumbing (UI/contracts)
1. Add export target option in UI/contracts:
   - `excel_xlsx` (default),
   - `google_sheets_drive_convert`.
2. Add Google destination metadata (folder, sharing option, account profile).
3. Keep existing Excel export path unchanged when target is `excel_xlsx`.

Acceptance criteria:
- export options validate target + required Google metadata,
- no behavior change for existing Excel export users.

---

### Phase 1 — Generate workbook + upload conversion
1. Run existing workbook generation flow to produce `.xlsx` artifact.
2. Add Drive API uploader:
   - upload file bytes,
   - set destination mime type to Google Sheet,
   - capture converted file ID + web link.
3. Surface converted link in UI/logs and optionally open browser.

Acceptance criteria:
- Google target yields a converted Google Sheet from the same generated `.xlsx`,
- local `.xlsx` can be retained as fallback artifact.

---

### Phase 2 — Auth, permissions, and ops
1. Add OAuth/service-account configuration path.
2. Use minimal scopes (`drive.file`; optionally `spreadsheets.readonly` for checks).
3. Add retry/backoff for upload/convert transient failures.
4. Add progress labels for “generating workbook”, “uploading”, and “converting”.

---

### Phase 3 — Post-conversion validation + fallback policy
1. Add lightweight validation after conversion (expected tabs exist, non-empty key sheets).
2. Detect and warn on known conversion degradations (if any formatting/chart losses appear).
3. Keep `.xlsx` as guaranteed fallback and include path in completion message.

Acceptance criteria:
- conversion issues are surfaced without silent failure,
- users always retain a valid `.xlsx` export.

---

### Phase 4 — Testing strategy
1. Unit tests
   - target/metadata validation,
   - upload request payload builder,
   - conversion response parser.
2. Integration tests
   - Excel export unchanged,
   - Google export smoke test with mocked Drive API.
3. Optional live smoke check
   - manual/CI gated test against a sandbox Drive account.

---

## Detailed task list for the immediate next step
1. Extend export options/contracts with `google_sheets_drive_convert` target.
2. After workbook generation, branch to Drive upload+convert when target is Google.
3. Persist/report converted sheet URL + local fallback path.
4. Add retries and clear error messages for auth/quota/network failures.
5. Add tests for option validation and Drive request/response handling.

---

## Risks and mitigations
- **Risk:** Google conversion may alter some advanced chart/formatting details.
  - **Mitigation:** keep `.xlsx` fallback, add post-conversion warnings, document known differences.
- **Risk:** OAuth/service-account setup friction.
  - **Mitigation:** provide clear setup guide + validation screen + actionable error mapping.
- **Risk:** API quotas and transient failures.
  - **Mitigation:** implement exponential backoff and resumable status logging.

---

## Success definition
Migration is complete when:
1. User can choose Google Sheets export target.
2. App generates `.xlsx` exactly as today and uploads it for Drive conversion.
3. User receives a working Google Sheet link/ID from converted file.
4. `.xlsx` fallback is always preserved/reported.
5. Excel export remains unchanged for default users.

---

## Deprecated approach (historical)
The earlier plan to build a full `GoogleSheetsExportBackend` and recreate charts/image placement natively in Sheets is intentionally deprioritized in favor of Drive conversion due to complexity and parity risk.
