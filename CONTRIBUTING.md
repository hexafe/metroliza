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
ruff check \
  VersionDate.py \
  modules/AboutWindow.py \
  modules/CSVSummaryDialog.py \
  modules/contracts.py \
  modules/csv_summary_utils.py \
  modules/db.py \
  modules/excel_sheet_utils.py \
  modules/ParseReportsThread.py \
  modules/stats_utils.py \
  tests/test_contracts.py \
  tests/test_csv_summary_integration.py \
  tests/test_csv_summary_utils.py \
  tests/test_db_utils.py \
  tests/test_phase0_hotfixes.py \
  tests/test_requirements_hygiene.py
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
- Add or update tests in `tests/` for each behavior change.
