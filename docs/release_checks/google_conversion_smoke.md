# Google conversion smoke check log

Use this checklist/log when running the release-gated smoke command from:
[`docs/google_conversion_smoke_runbook.md`](../google_conversion_smoke_runbook.md).

## Checklist before running

- [ ] Running against sandbox/non-production Google project/account.
- [ ] `credentials.json` and `token.json` are local-only + gitignored.
- [ ] `METROLIZA_RUN_GOOGLE_CONVERSION_SMOKE=1` set for this run.
- [ ] Command output will be retained (CI link or local terminal capture).

## Run log template (copy for each execution)

## YYYY-MM-DD
- Environment: <!-- local workstation / CI job name + branch/commit -->
- Credentials source: <!-- e.g., local sandbox OAuth client + token refresh date -->
- Command:
  ```bash
  METROLIZA_RUN_GOOGLE_CONVERSION_SMOKE=1 \
  METROLIZA_GOOGLE_SMOKE_CREDENTIALS_PATH=credentials.json \
  METROLIZA_GOOGLE_SMOKE_TOKEN_PATH=token.json \
  PYTHONPATH=. python tests/google_conversion_smoke.py
  ```
- Result: <!-- PASS / FAIL -->
- Warnings: <!-- warnings=() or exact warning tuple/message -->
- Logs/evidence: <!-- CI URL or local log capture path -->
- Notes/remediation: <!-- optional -->
