# Google conversion smoke runbook (`tests/google_conversion_smoke.py`)

This runbook defines how maintainers run and interpret the release-gated live Google Drive → Google Sheets smoke check.

## Scope and intent

- Script: `tests/google_conversion_smoke.py`.
- Purpose: verify that Metroliza can upload a generated `.xlsx` workbook to Google Drive, convert it to a Google Sheet, and confirm expected tab/link metadata.
- Execution model: manual or explicitly gated CI job only (not part of default unit-test discovery).

## Prerequisites

Before running smoke:

1. **Python environment is ready**
   - Active virtualenv with dependencies installed from `requirements-dev.txt`.
2. **Sandbox Google account available**
   - Use a non-production account/project intended for validation runs.
3. **OAuth secret/token files exist locally**
   - `credentials.json` from your Google Cloud OAuth client setup.
   - `token.json` generated via prior interactive consent.
   - Both files must remain local-only and gitignored.
4. **Google APIs are enabled for the sandbox project**
   - Google Drive API.
   - Google Sheets API.
5. **Network path to Google APIs is available**
   - Outbound HTTPS access to Google OAuth/Drive/Sheets endpoints.

## Exact environment variables

The smoke script reads these environment variables:

- `METROLIZA_RUN_GOOGLE_CONVERSION_SMOKE`
  - Required opt-in gate.
  - Must be set to `1` or the script exits with `SmokeConfigError`.
- `METROLIZA_GOOGLE_SMOKE_CREDENTIALS_PATH`
  - Optional override path to `credentials.json`.
  - Defaults to `credentials.json` in current working directory.
  - File name must end in exactly `credentials.json`.
- `METROLIZA_GOOGLE_SMOKE_TOKEN_PATH`
  - Optional override path to `token.json`.
  - Defaults to `token.json` in current working directory.
  - File name must end in exactly `token.json`.

Reference command:

```bash
METROLIZA_RUN_GOOGLE_CONVERSION_SMOKE=1 \
METROLIZA_GOOGLE_SMOKE_CREDENTIALS_PATH=credentials.json \
METROLIZA_GOOGLE_SMOKE_TOKEN_PATH=token.json \
PYTHONPATH=. python tests/google_conversion_smoke.py
```

## Expected outcomes

### Pass criteria

A successful run prints:

- `Google conversion smoke check passed.`

And implies all of the following passed:

- Upload+conversion succeeded without `GoogleDriveExportError`.
- Returned `file_id` is non-empty.
- Returned `web_url` is a valid HTTPS Sheets link.
- Spreadsheet ID parsed from URL matches `file_id`.
- No post-conversion warnings were emitted.
- Expected tabs (`MEASUREMENTS`, `REF_A`) exist in the converted sheet.

### Expected fail classes (intentional fail-fast)

The smoke check is designed to fail with actionable messages when prerequisites or live dependencies are unhealthy. Common categories:

- **Configuration gate failures (`SmokeConfigError`)**
  - Missing `METROLIZA_RUN_GOOGLE_CONVERSION_SMOKE=1`.
  - Missing/incorrect secret file path.
  - File name mismatch (not exactly `credentials.json`/`token.json`).
- **Live conversion failures (`AssertionError` wrapping `GoogleDriveExportError`)**
  - OAuth auth/refresh failures.
  - Google API unavailable/transient server errors.
  - Quota/rate-limit enforcement.
- **Post-conversion validation failures (`AssertionError`)**
  - Empty `file_id`.
  - Invalid/malformed `web_url`.
  - URL/file ID mismatch.
  - Missing expected worksheet tabs.
  - Non-empty conversion warnings.

## Remediation guide for common failures

### Auth failures (invalid_grant, unauthorized_client, refresh errors)

1. Confirm the paths point to the intended sandbox `credentials.json` and `token.json`.
2. Delete stale `token.json` and re-run interactive auth flow to mint a fresh token.
3. Verify OAuth consent screen and client type match desktop/local app usage.
4. Confirm the account running smoke still has Drive access and has not revoked consent.
5. Re-run smoke after token refresh/regeneration.

### Quota/rate-limit failures (HTTP 429 / quotaExceeded / rateLimitExceeded)

1. Confirm smoke is running in the expected sandbox project (not production quota pool).
2. Wait briefly and retry (the upload path already includes bounded retries).
3. Reduce concurrent validation jobs hitting the same project.
4. If recurring, request higher quota or spread runs across dedicated validation windows.

### Network/connectivity failures (timeouts, DNS/TLS, proxy blocks)

1. Validate outbound HTTPS connectivity from runner/workstation.
2. Check proxy/firewall rules for Google OAuth, Drive, and Sheets endpoints.
3. Re-run from a known-good network to isolate local environment issues.
4. If CI-only, inspect runner egress restrictions and update allowlists.

### Conversion warning or tab-mismatch failures

1. Open returned Google Sheet link and verify tab presence/renaming behavior.
2. Confirm the smoke workbook generation still produces `MEASUREMENTS` and `REF_A` tabs.
3. Inspect recent Google export logic changes for tab mapping or post-conversion checks.
4. Treat generated `.xlsx` as fallback artifact while conversion issues are investigated.

## Recording outcomes for release-gated changes

For release-candidate validations and PRs that modify Google auth/conversion behavior:

- Record the smoke command used.
- Record pass/fail result and timestamp.
- Link to job logs (CI) or terminal capture (manual) in the PR description.
