# Contributing to Metroliza

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements-dev.txt
```

Dependency files are split by purpose:

- `requirements.txt` for runtime.
- `requirements-dev.txt` for local development/tests.
- `requirements-build.txt` for packaging executables.


## Pre-commit hooks

Install and activate local hooks once per clone:

```bash
pre-commit install
```

Run all hooks on demand before opening a PR:

```bash
pre-commit run --all-files
```

The hook set includes whitespace/end-of-file normalization, Ruff linting, and secret-pattern checks. The committed allowlist keeps `config/google/credentials.example.json` as a permitted example template while still blocking real secret files such as `credentials.json`, `token.json`, `*.credentials.json`, and `*.token.json`.

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

For repository cleanup and docs organization sequencing, follow [`docs/archive/2026/repo_cleanup_and_docs_plan.md`](docs/archive/2026/repo_cleanup_and_docs_plan.md) (status: archived historical context).

- Keep documentation-only sync PRs separate from implementation PRs when updating roadmap/project-state docs.
- Update `IMPLEMENTATION_PLAN.md` and `GOOGLE_SHEETS_MIGRATION_PLAN.md` **after** implementation/testing PRs merge so status text reflects shipped behavior.
- For release-candidate documentation PRs, use [`docs/release_checks/release_candidate_checklist.md`](docs/release_checks/release_candidate_checklist.md) as the single RC source of truth and update all files referenced there in the same PR.
- For Google export docs, explicitly describe both:
  - required local secret files (`credentials.json`, `token.json`) and
  - fallback expectations (`.xlsx` remains the guaranteed artifact when conversion warns/fails).
- For branch/release flow guidance, follow [`docs/release_checks/release_branching_playbook.md`](docs/release_checks/release_branching_playbook.md) and keep the current RC scope frozen once `release/<version>-rcN` is cut.
- For a beginner-friendly end-to-end walkthrough, see [`docs/release_checks/release_playbook_beginner.md`](docs/release_checks/release_playbook_beginner.md).
- Quick branch role/naming/merge/tag reference: [`docs/release_checks/branching_strategy.md`](docs/release_checks/branching_strategy.md).

## Google export contributor checklist

When touching Google conversion/auth flows, validate and document:

1. **Prerequisites:** local OAuth setup, required env vars for optional smoke check, and sandbox-account usage.
2. **Secrets posture:** `credentials.json`/`token.json` are local-only, never committed, and covered by `.gitignore` patterns.
3. **Fallback behavior:** conversion degradation/failure messaging still reports the preserved `.xlsx` output path.
4. **Testing strategy:** baseline automated tests remain passing; optional live smoke check stays release-gated/non-default.
5. **Troubleshooting notes:** conversion warning guidance stays current in `README.md`.
6. **PR evidence for Google export surface changes:** any PR touching `modules/google_drive_export.py`, `modules/export_backends.py`, `modules/ExportDataThread.py`, or Google export UI/contract paths (for example `modules/ExportDialog.py`, `modules/contracts.py`) must include Google conversion smoke-check evidence in the PR description using the standard evidence format; if evidence is omitted, include explicit justification.
