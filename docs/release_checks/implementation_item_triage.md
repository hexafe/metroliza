# RC implementation-item triage table

Use this page as the **active operational record** for implementation-item gate triage during release-candidate preparation.

> Historical reference only: archived implementation context remains in [`../archive/2026/TODO.md`](../archive/2026/TODO.md), but that file is **non-operational** and must not be used as a required RC gate.

## How to use this table

- Add one row per open implementation item relevant to the current RC window.
- Fill all required columns before freeze proceeds.
- Keep this table current as triage outcomes change.

## Open-item RC triage decision table

| Implementation item | Gate decision (`must-fix`/`defer`) | Owner | Target RC | Rationale |
| --- | --- | --- | --- | --- |
| _Example: Packaging smoke flake on clean VM_ | `must-fix` | Release engineer | 2026.03-rc1 | Blocks launch validation in required packaging checks. |
|  |  |  |  |  |
