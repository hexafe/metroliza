# Metroliza

Metroliza is a Python desktop tool for industrial metrology data processing, grouping, and Excel report generation.

## Quickstart

### 1) Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
```

### 2) Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

### 3) Run the application

```bash
python metroliza.py
```


Dependency files are split by purpose:

- `requirements.txt` for runtime.
- `requirements-dev.txt` for local development/tests.
- `requirements-build.txt` for packaging executables.

## What the app does

Metroliza supports an end-to-end flow:

1. Parse metrology source files (PDF/ZIP) and production CSV exports.
2. Persist normalized data in SQLite.
3. Optionally assign grouping labels (for example `OK` / `NOK`).
4. Export Excel workbooks with:
   - statistical summaries,
   - grouped violin plots,
   - trend charts by date or sample order.

## Project layout

- `metroliza.py` — application entry point.
- `modules/` — core app modules (parsing, grouping, export, dialogs, contracts, DB helpers, export summary utilities).
- `tests/` — regression/unit tests.
- `IMPLEMENTATION_PLAN.md` — roadmap and phase status.
- `metroliza_onefile.spec` — PyInstaller one-file build spec.

## Development checks

Run the baseline checks locally:

```bash
python -m compileall .
ruff check modules/contracts.py modules/db.py modules/excel_sheet_utils.py modules/stats_utils.py tests/test_contracts.py tests/test_db_utils.py tests/test_phase0_hotfixes.py tests/test_requirements_hygiene.py
PYTHONPATH=. python -m unittest discover -s tests -v
```

Run focused checks when iterating on specific areas:

```bash
PYTHONPATH=. python -m unittest tests.test_contracts tests.test_export_grouping_and_sorting tests.test_export_summary_utils tests.test_db_utils -v
PYTHONPATH=. python -m unittest tests.test_phase4_integration_happy_path -v
```

## Packaging (one-file executable)

Build with PyInstaller:

```bash
pyinstaller metroliza_onefile.spec
```

The generated executable is placed under `dist/`.

## Troubleshooting

### `ModuleNotFoundError` on launch

- Confirm the virtual environment is active.
- Reinstall dependencies:

```bash
pip install -r requirements-dev.txt
```

### Qt plugin/display issues in headless shells

Some test environments do not provide a display server. Use the unit tests that stub GUI dependencies (already present in `tests/`) and avoid launching the full GUI.

### Database lock errors

Recent code paths use retry-aware helpers from `modules/db.py`. If a lock persists, ensure no other app instance has the same SQLite file open.

### Empty or partial charts in exports

Check grouping and filtering choices first. Group/plot alignment, NaN-only bucket handling, and merge-key fallback selection (blank `GROUP_KEY`/`REPORT_ID` now fall back to composite identity) were hardened in the Phase 2 correctness work; rerun export after verifying source rows in the selected date/reference scope.

### Export and parsing performance notes

Recent performance-focused changes include:
- cached preparation of grouping assignments during export summary generation (reused across headers),
- vectorized NaN filtering/list aggregation for violin payload construction,
- vectorized column-width sizing during raw-sheet export,
- faster dataframe-to-widget row iteration in grouping dialogs (`itertuples` over `iterrows`),
- sparse repeated sample labels in summary trend plots to improve readability on dense exports.

For very large databases, prefer narrow filter scopes before export to reduce Excel-writing and charting time.

## Roadmap status

Roadmap progress and next actions are maintained in `IMPLEMENTATION_PLAN.md`.

Current high-level state:
- Phase 0: completed.
- Phase 1: completed.
- Phase 2: partially completed (remaining structural/performance items).
- Phase 3: partially completed (docs/dependency hygiene/contributor guide done; CI lint rollout remains incremental).
- Phase 4: completed.
