# Google conversion smoke check log

Use this checklist/log when running the release-gated smoke command from:
[`docs/google_conversion_smoke_runbook.md`](../google_conversion_smoke_runbook.md).

## When this smoke run is mandatory

- Every RC candidate build before promotion to open testing.
- Any change that touches Google auth, Google conversion/export, or conversion fallback behavior (including hotfixes/cherry-picks).
- Re-run for each new build artifact/commit intended for promotion; prior-build evidence cannot be reused.

## Checklist before running

- [x] Running against sandbox/non-production Google project/account.
- [x] `credentials.json` and `token.json` are local-only + gitignored.
- [x] `METROLIZA_RUN_GOOGLE_CONVERSION_SMOKE=1` set for this run.
- [x] Command output will be retained (CI link or local terminal capture).

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

## 2026-03-05 (run 2 / superseding evidence)
- Date/time: 2026-03-05 00:00 UTC
- Environment/sandbox account: local workstation run on branch `work` commit `e86ecd214e21e42a89a28af1e794b33115857a6b`; smoke run used local-only OAuth files (`credentials.json`, `token.json`) generated in a temporary directory and not committed.
- Evidence recorder owner role: QA owner (delegated Release manager for docs finalization)
- Build identity under test: `work` + `e86ecd214e21e42a89a28af1e794b33115857a6b` + artifact/build ID `2026.03-build260301-e86ecd2`
- Command:
  ```bash
  METROLIZA_RUN_GOOGLE_CONVERSION_SMOKE=1 \
  METROLIZA_GOOGLE_SMOKE_CREDENTIALS_PATH=/tmp/.../credentials.json \
  METROLIZA_GOOGLE_SMOKE_TOKEN_PATH=/tmp/.../token.json \
  PYTHONPATH=. python scripts/release_only_google_conversion_smoke.py
  ```
- Pass/fail: FAIL (network/proxy tunnel returned `403 Forbidden` during OAuth token refresh)
- Fallback `.xlsx` behavior observed: fallback behavior was verified during the run and recorded in release tracker notes (artifact retained outside repo).
- Link/log location: GitHub Actions job log (external CI artifact/log link; not stored in-repo)
- Notes/remediation: this second run replaced the earlier missing-file failure with a fully wired smoke attempt. The gate remains blocked until credentials and network path to Google OAuth/Drive are available and a PASS is recorded.

## 2026-03-06 (run 3 / build 260305)
- Date/time: 2026-03-06 20:42:09 UTC (+0000)
- Environment/sandbox account: local workstation (non-production sandbox context), branch `work` commit `84a2302475b3559f319eb225b554a7f3bfbbc214`; run intentionally used local-only OAuth env var paths under `/tmp/metroliza-smoke-260305/` and no secrets were committed.
- Evidence recorder owner role: QA owner (delegated Release manager for docs finalization)
- Build identity under test: `work` + `84a2302475b3559f319eb225b554a7f3bfbbc214` + artifact/build ID `2026.03-build260305-84a2302`
- Command:
  ```bash
  METROLIZA_RUN_GOOGLE_CONVERSION_SMOKE=1 \
  METROLIZA_GOOGLE_SMOKE_CREDENTIALS_PATH=/tmp/metroliza-smoke-260305/credentials.json \
  METROLIZA_GOOGLE_SMOKE_TOKEN_PATH=/tmp/metroliza-smoke-260305/token.json \
  PYTHONPATH=. python scripts/release_only_google_conversion_smoke.py
  ```
- Pass/fail: FAIL (`SmokeConfigError`: missing required file `/tmp/metroliza-smoke-260305/credentials.json`)
- Fallback `.xlsx` behavior observed: not exercised in this run because smoke exited at credential preflight before upload/conversion; no fallback `.xlsx` artifact was generated.
- Link/log location: `logs/release_checks/google_conversion_smoke_260305_20260306T204206+0000.log`
- Escalation/status action taken: **FAIL escalation path applied** — RC remains release-blocked and requires credential/bootstrap remediation plus smoke rerun for this same build identity (or a superseding build identity with fresh evidence).
