# Google Sheets Migration Plan (Drive conversion from generated `.xlsx`)

> **Canonical source note:** This file is the canonical source for Google Sheets migration phase names, acceptance criteria wording, and status updates. `IMPLEMENTATION_PLAN.md` contains only a companion summary with a reference back here.

## Goal
Keep Metroliza export Excel-first (`xlsxwriter`) and add a Google mode that uploads the generated `.xlsx` to Google Drive for server-side conversion to a native Google Sheet, while preserving current analytical output:
- raw measurement tables,
- computed statistics,
- per-header trend charts,
- summary matplotlib/seaborn plots.

---

## Migration status (audited 2026-02-27)
- **Phase GS0:** ✅ Completed.
- **Phase GS1:** ✅ Completed.
- **Phase GS2:** ✅ Completed.
- **Phase GS3:** ✅ Completed.
- **Phase GS4:** ✅ Completed.
- **Phase GS5:** ✅ Completed.

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


## Credential and token handling policy
- Use a local OAuth client secret file named `credentials.json` (user-provided) for Google Drive API authorization.
- OAuth refresh/access token cache is written to `token.json` after first consent.
- Both files are **local-only secrets** and must never be committed.
- Repository includes only a redacted template: `config/google/credentials.example.json`.
- `.gitignore` must include `credentials.json` and `token.json` (plus wildcard variants) to prevent accidental uploads.

## Phased implementation plan

### Phase GS0 — Export target plumbing (UI/contracts) ✅ Completed
1. Add export target option in UI/contracts:
   - `excel_xlsx` (default),
   - `google_sheets_drive_convert`.
2. Add Google destination metadata (folder, sharing option, account profile).
3. Keep existing Excel export path unchanged when target is `excel_xlsx`.

### Phase GS1 — Excel output hardening for conversion ✅ Completed
1. Keep worksheet-backed USL/LSL series ranges and helper anchor cells so chart source ranges remain deterministic for conversion.
2. Preserve existing hardening changes because they reduce conversion drift risk.

### Phase GS2 — Generate workbook + upload conversion ✅ Completed
1. Run existing workbook generation flow to produce `.xlsx` artifact.
2. Add Drive API uploader:
   - upload file bytes,
   - set destination mime type to Google Sheet,
   - capture converted file ID + web link.
3. Surface converted link in UI/logs and optionally open browser.

### Phase GS3 — Auth, permissions, and ops ✅ Completed
1. Add OAuth configuration path using local `credentials.json` and generated `token.json`.
2. Ensure `credentials.json`/`token.json` are gitignored and never logged in plaintext.
3. Use minimal scopes (`drive.file`; optionally `spreadsheets.readonly` for checks).
4. Add retry/backoff for upload/convert transient failures.
5. Add progress labels for “generating workbook”, “uploading”, and “converting”.

### Phase GS4 — Post-conversion validation + fallback policy ✅ Completed
1. Add lightweight validation after conversion (expected tabs exist, non-empty key sheets).
2. Detect and warn on known conversion degradations (if any formatting/chart losses appear).
3. Keep `.xlsx` as guaranteed fallback and include path in completion message.

### Phase GS5 — Testing strategy ✅ Completed
1. **Automated coverage completed**
   - unit tests cover target/metadata validation, upload payload builder, conversion response parsing, credential-file hygiene (`credentials.json`/`token.json` gitignore coverage), conversion-warning surfaces, edge-case validation, fallback messaging/content assertions, and negative-path auth/setup + transient conversion-failure handling while preserving successful `.xlsx` completion semantics,
   - integration checks verify Excel export behavior remains unchanged and Google conversion flow works with mocked Drive API + stub credentials.
2. **Optional live smoke check (non-default)**
   - manual/CI-gated sandbox Drive smoke checks are documented for release-gated workflows using local-only credentials files (`credentials.json`, `token.json`).

### Unified acceptance criteria (single-source wording)
- Google Sheets export target is selectable and functional.
- Selecting Google Sheets generates the same `.xlsx` content and uploads it through Drive conversion.
- User receives converted Google Sheet link/identifier after successful upload.
- On conversion degradation/failure, app preserves and reports `.xlsx` fallback without data loss.

---


## Remaining execution order (GS follow-through)
1. Keep GS0-GS5 behavior stable and treat GS5 automated coverage as the merge gate for regressions.
2. Run optional/manual sandbox Drive smoke checks only in release-gated workflows, then fold outcomes back into docs/tests as needed.

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
4. `.xlsx` fallback is always preserved/reported, including warning/degradation paths.
5. Excel export remains unchanged for default users.
6. GS5 coverage includes expanded automated tests plus documented optional release-gated live smoke validation.

---

## Deprecated approach (historical)
The earlier plan to build a full `GoogleSheetsExportBackend` and recreate charts/image placement natively in Sheets is intentionally deprioritized in favor of Drive conversion due to complexity and parity risk.
