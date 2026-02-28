# Google conversion smoke runbook (`tests/google_conversion_smoke.py`)

This runbook defines how maintainers run and interpret the release-gated live Google Drive → Google Sheets smoke check.

## Scope and intent

- Script: `tests/google_conversion_smoke.py`.
- Purpose: verify that Metroliza can upload a generated `.xlsx` workbook to Google Drive, convert it to a Google Sheet, and confirm release-gated conversion metadata/warning expectations.
- Execution model: manual or explicitly gated CI job only (not part of default unit-test discovery).

## When smoke execution is mandatory

Run `tests/google_conversion_smoke.py` in all of these cases:

- Every RC candidate build before it can be promoted to open testing.
- Any PR/change set that modifies Google auth, Drive/Sheets conversion/export logic, or fallback `.xlsx` behavior.
- Any rebuilt RC artifact intended for promotion (smoke evidence must match the current build identity).

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
5. **Network path to Google APIs is available**
   - Outbound HTTPS access to Google OAuth/Drive endpoints.

## Script usage contract (`tests/google_conversion_smoke.py`)

### Required/optional inputs

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

### Expected success signals

A successful run prints:

- `Google conversion smoke check passed.`

And implies all of the following passed:

- Upload+conversion succeeded without `GoogleDriveExportError`.
- Returned `file_id` is non-empty.
- Returned `web_url` is a valid HTTPS Sheets link.
- Spreadsheet ID parsed from URL matches `file_id`.
- No post-conversion warnings were emitted (`warnings=()`).

### Warning handling policy

- Release-gated smoke runs require `warnings=()` to pass.
- If warnings appear, treat them as release-blocking until triaged.
- Keep the converted Google Sheet as convenience output and treat the generated `.xlsx` as the fidelity-baseline fallback artifact while warning root cause is investigated.

## Expected fail classes (intentional fail-fast)

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
2. Check proxy/firewall rules for Google OAuth and Drive endpoints.
3. Re-run from a known-good network to isolate local environment issues.
4. If CI-only, inspect runner egress restrictions and update allowlists.

### Conversion warning failures

1. Treat any non-empty `warnings` result as a release-blocking signal until triaged.
2. Inspect recent Google export logic changes for warning generation, conversion payload handling, or fallback-message behavior.
3. Validate that mocked/unit tests still cover expected tab-title semantics and fallback behavior after recent changes.
4. Keep the converted Google Sheet as convenience output and treat the generated `.xlsx` as the fidelity-baseline fallback artifact while warning root cause is investigated.

## Recording outcomes for release-gated changes

For release-candidate validations and PRs that modify Google auth/conversion behavior:

## Evidence to record (required for each smoke execution)

- Required evidence recorder owner role: **QA owner** (or delegated **Release manager** if QA owner is unavailable).
- Minimum evidence set per run:
  - Command run (exact command text, including env vars).
  - Date/time (with timezone).
  - Environment/sandbox account (local/CI context + sandbox Google account/project identifier).
  - Build identity under test (branch + commit SHA + artifact/build identifier).
  - Pass/fail outcome.
  - Fallback `.xlsx` behavior observed (path/link and whether fallback remained accessible as expected).
  - Link/log location (CI job URL, artifact URI, or local log file path).

### Pass/fail escalation path

- **PASS**: QA owner records evidence and notifies Release manager that the current build is eligible for open-testing promotion.
- **FAIL**: QA owner marks the build release-blocked, links/creates incident ticket, and escalates to Release manager + responsible Dev owner for remediation.
- **Evidence missing or incomplete for the current build**: treat as **FAIL (gate not met)**; promotion remains blocked until minimum evidence is complete.

- Record each run in `docs/release_checks/google_conversion_smoke.md`.
- Include the required evidence fields below for every smoke execution.
- Keep entries in reverse chronological order (newest first).

Use this template:

```md
## YYYY-MM-DD
- Date/time: <!-- YYYY-MM-DD HH:MM TZ -->
- Environment/sandbox account: <!-- local workstation or CI job + branch/commit + sandbox account/project -->
- Evidence recorder owner role: <!-- QA owner or delegated Release manager -->
- Build identity under test: <!-- branch + commit SHA + build/artifact identifier -->
- Command:
  ```bash
  METROLIZA_RUN_GOOGLE_CONVERSION_SMOKE=1 \
  METROLIZA_GOOGLE_SMOKE_CREDENTIALS_PATH=credentials.json \
  METROLIZA_GOOGLE_SMOKE_TOKEN_PATH=token.json \
  PYTHONPATH=. python tests/google_conversion_smoke.py
  ```
- Pass/fail: <!-- PASS / FAIL -->
- Fallback `.xlsx` behavior observed: <!-- preserved output path/link + observed behavior -->
- Link/log location: <!-- CI URL, artifact URI, or local log capture path -->
- Notes/remediation: <!-- optional -->
```

## Current warning interpretation policy

- Release-gated smoke runs currently require `warnings=()` to pass.
- If warnings appear, do not waive by default: record the exact warning text, impacted release candidate, and fallback implications before deciding next action.
- Keep the converted Google Sheet as convenience output and treat the generated `.xlsx` as the fidelity-baseline fallback artifact while warning root cause is investigated.
- Tab-title verification is intentionally not performed by the live smoke script; keep that behavior covered in mocked/unit tests to avoid adding Sheets API dependency to the release gate.
