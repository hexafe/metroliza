# Google Conversion Smoke Runs (2026-03)

Historical smoke evidence moved out of the active release-check template.

## 2026-03-05 (Run 2 / Superseding Evidence)

- Date/time: 2026-03-05 00:00 UTC.
- Context: local workstation on branch `work` at `e86ecd214e21e42a89a28af1e794b33115857a6b`.
- Build identity: `2026.03-build260301-e86ecd2`.
- Outcome: FAIL. OAuth token refresh hit a `403 Forbidden` network/proxy tunnel response.
- Fallback `.xlsx` behavior: verified during the run and recorded in release tracker notes outside the repo.
- Status: superseded historical evidence.

## 2026-03-06 (Run 3 / Build 260305)

- Date/time: 2026-03-06 20:42:09 UTC.
- Context: local workstation on branch `work` at `84a2302475b3559f319eb225b554a7f3bfbbc214`.
- Build identity: `2026.03-build260305-84a2302`.
- Outcome: FAIL. Smoke exited during credential preflight because `/tmp/metroliza-smoke-260305/credentials.json` was missing.
- Fallback `.xlsx` behavior: not exercised because the run stopped before upload/conversion.
- Local log path recorded at the time: `logs/release_checks/google_conversion_smoke_260305_20260306T204206+0000.log`.
- Status: superseded historical evidence.
