# Google conversion smoke check log

Use this checklist/log when running the release-gated smoke command from:
[`docs/google_conversion_smoke_runbook.md`](../google_conversion_smoke_runbook.md).

## When this smoke run is mandatory

- Every RC candidate build before promotion to open testing.
- Any change that touches Google auth, Google conversion/export, or conversion fallback behavior (including hotfixes/cherry-picks).
- Re-run for each new build artifact/commit intended for promotion; prior-build evidence cannot be reused.

## Checklist before running

- [ ] Running against sandbox/non-production Google project/account.
- [ ] `credentials.json` and `token.json` are local-only + gitignored.
- [ ] `METROLIZA_RUN_GOOGLE_CONVERSION_SMOKE=1` set for this run.
- [ ] Command output will be retained (CI link or local terminal capture).

## Run log template (copy for each execution)

## Evidence to record (required for each smoke execution)

- Evidence recorder owner role: **QA owner** (or delegated **Release manager** when QA owner is unavailable).
- The evidence set below is the minimum release-gate payload for each run.

- Command run (exact command text, including env vars).
- Date/time (with timezone).
- Environment/sandbox account (local/CI context + sandbox Google account/project identifier).
- Pass/fail outcome.
- Build identity under test (branch + commit SHA and artifact/build identifier).
- Fallback `.xlsx` behavior observed (path/link and whether fallback remained accessible as expected).
- Link/log location (CI job URL, artifact URI, or local log file path).

### Pass/fail escalation path

- **PASS**: QA owner records evidence and notifies Release manager that the build is eligible for open-testing promotion.
- **FAIL**: QA owner immediately marks RC as release-blocked, files/links incident ticket, and escalates to Release manager + responsible Dev owner for triage/remediation.
- **No evidence / incomplete evidence**: Treat as **FAIL (gate not met)** until minimum evidence is completed for the current build.

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
