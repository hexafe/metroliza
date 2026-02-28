# Google conversion smoke check log

Use this checklist/log when running the release-gated smoke command from:
[`docs/google_conversion_smoke_runbook.md`](../google_conversion_smoke_runbook.md).

## Checklist before running

- [ ] Running against sandbox/non-production Google project/account.
- [ ] `credentials.json` and `token.json` are local-only + gitignored.
- [ ] `METROLIZA_RUN_GOOGLE_CONVERSION_SMOKE=1` set for this run.
- [ ] Command output will be retained (CI link or local terminal capture).

## Run log template (copy for each execution)

## Evidence to record (required for each smoke execution)

- Command run (exact command text, including env vars).
- Date/time (with timezone).
- Environment/sandbox account (local/CI context + sandbox Google account/project identifier).
- Pass/fail outcome.
- Fallback `.xlsx` behavior observed (path/link and whether fallback remained accessible as expected).
- Link/log location (CI job URL, artifact URI, or local log file path).

## YYYY-MM-DD
- Date/time: <!-- YYYY-MM-DD HH:MM TZ -->
- Environment/sandbox account: <!-- local workstation or CI job + branch/commit + sandbox account/project -->
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
