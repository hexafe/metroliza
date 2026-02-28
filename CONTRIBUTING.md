# Contributing to Metroliza

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

## Baseline checks

Before opening a PR, run:

```bash
python -m compileall .
ruff check .
PYTHONPATH=. python -m unittest discover -s tests -v
```

## Architecture notes

Metroliza's core flow is:

1. **Parse** (`modules/ParseReportsThread.py`) ingests reports/archives and normalizes rows.
2. **Persist** (`modules/db.py` + DB call sites) stores and queries SQLite data.
3. **Group/Filter** (`modules/DataGrouping.py`, `modules/FilterDialog.py`) prepares user-selected subsets.
4. **Export** (`modules/ExportDataThread.py`) creates Excel outputs with summary stats/charts.

## Contracts usage

Request/option contracts live in `modules/contracts.py`.

- Parse flows should build and validate `ParseRequest`.
- Export flows should build and validate `ExportRequest` and nested dataclasses (`AppPaths`, `ExportOptions`, `GroupingAssignment`).
- Prefer adding validation to contract constructors/helpers instead of duplicating checks in UI/dialog code.

## Coding guidance

- Keep changes incremental and phase-aligned with `IMPLEMENTATION_PLAN.md`.
- Prefer shared helpers in `modules/db.py` over direct `sqlite3.connect` in feature modules.
- **Transaction granularity:** each logical write unit (e.g., inserting one parsed report and all related measurements, or applying all edits from one Modify DB submission) must execute inside a single `run_transaction_with_retry` call so retries are atomic and rollback-safe.
- Use `run_transaction_with_retry` for multi-statement write workflows; keep retries centralized in `modules/db.py` rather than implementing ad-hoc retry loops in feature modules.
- Add or update tests in `tests/` for each behavior change.


## Documentation sync policy

- Keep documentation-only sync PRs separate from implementation PRs when updating roadmap/project-state docs.
- Update `IMPLEMENTATION_PLAN.md` and `GOOGLE_SHEETS_MIGRATION_PLAN.md` **after** implementation/testing PRs merge so status text reflects shipped behavior.
- For release-candidate documentation PRs, treat `CONTRIBUTING.md` (this section) as the source of truth for mandatory cross-file sync and update all of the following in the same PR:
  - `README.md`
  - `CHANGELOG.md`
  - `IMPLEMENTATION_PLAN.md`
  - `TODO.md`
  - `GOOGLE_SHEETS_MIGRATION_PLAN.md`
  - `VersionDate.py` (version/build text alignment).
- For Google export docs, explicitly describe both:
  - required local secret files (`credentials.json`, `token.json`) and
  - fallback expectations (`.xlsx` remains the guaranteed artifact when conversion warns/fails).

## Google export contributor checklist

When touching Google conversion/auth flows, validate and document:

1. **Prerequisites:** local OAuth setup, required env vars for optional smoke check, and sandbox-account usage.
2. **Secrets posture:** `credentials.json`/`token.json` are local-only, never committed, and covered by `.gitignore` patterns.
3. **Fallback behavior:** conversion degradation/failure messaging still reports the preserved `.xlsx` output path.
4. **Testing strategy:** baseline automated tests remain passing; optional live smoke check stays release-gated/non-default.
5. **Troubleshooting notes:** conversion warning guidance stays current in `README.md`.
6. **PR evidence for Google export surface changes:** any PR touching `modules/google_drive_export.py`, `modules/export_backends.py`, `modules/ExportDataThread.py`, or Google export UI/contract paths (for example `modules/ExportDialog.py`, `modules/contracts.py`) must include Google conversion smoke-check evidence in the PR description using the standard evidence format; if evidence is omitted, include explicit justification.
