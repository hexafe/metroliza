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
5. Run CSV Summary to quickly generate per-column worksheets, trend plots, and an aggregated `CSV_SUMMARY` sheet from manufacturing CSV exports.
6. Optionally set per-column NOM/USL/LSL offsets in CSV Summary before export so Cp/Cpk and conditional highlighting use part-specific limits. Invalid limit order (LSL > NOM or NOM > USL) is now flagged in `CSV_SUMMARY`, and Cp/Cpk are emitted as `N/A` for that column.
7. Choose quick-look mode (trend only) or full-report mode (trend + histogram + boxplot-profile charts) to balance runtime vs chart depth.
8. CSV Summary now auto-defaults to quick-look mode for large selected-column sets, reducing first-run export time for wide datasets.
9. For chart-heavy exports, CSV Summary warns about estimated chart count and offers one-click fallback to quick-look mode before generation starts.
10. Use summary-only mode to generate just the aggregated `CSV_SUMMARY` worksheet for faster large-column exports.
11. Reuse CSV presets for recurring file families (delimiter/decimal, selected columns, spec limits, plot mode/toggles, and summary-only preference), or clear saved presets directly from the CSV Summary dialog.

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
ruff check .
PYTHONPATH=. python -m unittest discover -s tests -v
```

Run focused checks when iterating on specific areas:

```bash
PYTHONPATH=. python -m unittest tests.test_contracts tests.test_export_grouping_and_sorting tests.test_export_summary_utils tests.test_db_utils -v
PYTHONPATH=. python -m unittest tests.test_phase4_integration_happy_path -v
```

### Release-only Google conversion smoke check (manual / CI-gated)

Use the dedicated smoke harness for a real end-to-end sandbox Google Drive →
Google Sheets conversion check:

```bash
METROLIZA_RUN_GOOGLE_CONVERSION_SMOKE=1 \
METROLIZA_GOOGLE_SMOKE_CREDENTIALS_PATH=credentials.json \
METROLIZA_GOOGLE_SMOKE_TOKEN_PATH=token.json \
PYTHONPATH=. python tests/google_conversion_smoke.py
```

- This smoke check is **non-default** and is intentionally excluded from the
  standard unit-test discover run.
- It is intended for release validation only (or explicitly gated CI jobs).
- It fails fast with actionable configuration errors when the local
  credentials/token files are missing or misconfigured.

## Packaging (one-file executable)

Build with PyInstaller:

```bash
pyinstaller metroliza_onefile.spec
```

The generated executable is placed under `dist/`.

### Nuitka build notes (Windows + PyQt6)

If you package with Nuitka instead of PyInstaller, prefer:

```powershell
python -m nuitka metroliza.py `
  --onefile `
  --windows-console-mode=disable `
  --enable-plugin=pyqt6 `
  --windows-icon-from-ico=metroliza_icon2.ico `
  --output-filename=metroliza.exe `
  --assume-yes-for-downloads `
  --remove-output `
  --jobs=%NUMBER_OF_PROCESSORS%
```

### What to install/check on your machine (based on your build log)

- **Remove PyQt5 from the build venv** if you build a PyQt6 app (`pip uninstall PyQt5`). Your log shows a direct PyQt5/PyQt6 conflict warning from the Nuitka PyQt plugin.
- **Install Microsoft Visual C++ Redistributable (x64, 2015-2022)** on target systems. Your log warns that Windows Runtime DLLs were not bundled automatically.
- **Use a clean dedicated build venv** (`requirements-build.txt`) and keep only runtime + build tooling to avoid accidental heavy imports.
- **Keep build/cache/output on SSD** (project folder + `%LocalAppData%\Nuitka\Nuitka\Cache`) for much faster compile/link and onefile compression stages.
- **Exclude Nuitka cache/build folders from realtime AV scanning** (if your security policy allows) to reduce C object and archive churn overhead.

### Build-time and exe-size tuning

- Use `--report=nuitka-build-report.xml` to inspect unexpectedly included packages and prune imports.
- For **faster iteration**, use standalone builds while developing (`--standalone` + no `--onefile`), then switch to `--onefile` for release.
- For **smaller onefile outputs**, keep compression enabled (default) and avoid importing heavy libraries in top-level module scope when possible.
- For large scientific stacks (`scipy`, `pymupdf`), expect long first full rebuilds; subsequent builds improve if Python/Nuitka/toolchain versions remain stable (better cache hits).

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
- sparse repeated sample labels in summary trend plots to improve readability on dense exports,
- minimalistic, clean summary-plot styling (reduced gridline density, lighter spines, restrained palette) across violin/scatter/histogram/trend renders for more professional exports,
- violin plots now annotate per-group min/avg/max markers and ±3σ spread markers for quicker visual distribution reading,
- grouped violin summaries now include an embedded per-group stats table (`n`, min/avg/max/std, and Welch t-test p-value vs first group; single-group fallback compares against population),
- extracted/tested summary payload helpers for histogram-stat tables and trend chart payload construction (supports safer refactors in `ExportDataThread`),
- extracted/tested y-axis scaling helper for summary charts (`compute_scaled_y_limits`) to reduce duplicated chart math,
- extracted/tested histogram density-curve payload helper (`build_histogram_density_curve_payload`) to isolate normal-fit rendering decisions in histogram overlays,
- extracted/tested worksheet statistic-formula builder (`build_measurement_stat_formulas`) for MIN/AVG/MAX/STD/Cp/Cpk/NOK cells to support ongoing `ExportDataThread` decomposition,
- extracted/tested measurement-block coordinate planner (`build_measurement_block_plan`) and wired header worksheet/chart writes to use the plan object for data-range, conditional-format, and chart-placement coordinates (reduces duplicated row/column math in `ExportDataThread`),
- cached conditional-format workbook style objects during horizontal-sheet export (avoids repeated format allocations in per-header loops),
- worksheet-backed `USL_SERIES` / `LSL_SERIES` columns, explicit `USL_MAX`/`USL_MIN`/`LSL_MAX`/`LSL_MIN` anchor helper cells near per-header stats, and range-based chart spec-limit series (removes inline array-literal chart ranges and prepares Google Sheets-compatible chart data wiring),
- CSV Summary auto-detect for common delimiter/decimal combinations with numeric-column-aware defaults, optional per-column NOM/USL/LSL inputs, and an aggregated `CSV_SUMMARY` overview sheet for faster first-pass diagnostics.
- CSV Summary validates spec-limit ordering (`LSL <= NOM <= USL`) and records invalid-limit notes in `CSV_SUMMARY` while keeping the export successful (`Cp`/`Cpk` become `N/A` for invalid columns).
- CSV Summary now emits lightweight per-column timing telemetry (sheet write + chart generation) to help tune chart-heavy runs.
- CSV Summary preset persistence for recurring file families (remembers preferred delimiter/decimal parse settings, selected index/data columns, per-column NOM/USL/LSL limits, per-column plot toggles, and summary-only preference in `~/.metroliza/.csv_summary_presets.json`, with migration of older preset formats).
- CSV Summary includes an in-dialog control to clear saved presets when changing data families or starting fresh.
- CSV Summary cancellation now cleans up partial workbook outputs and is covered by regression tests.
- CSV Summary performance tuning now applies an adaptive default (quick-look for large column selections) and warns when a run is configured to generate a high chart count, with an in-flow one-click switch to quicker mode.
- Modify DB updates are now batched and committed transactionally via shared retry-aware DB helpers, improving reliability under transient SQLite lock contention.

For very large databases, prefer narrow filter scopes before export to reduce Excel-writing and charting time.

## Roadmap status

Detailed, canonical roadmap lives in `IMPLEMENTATION_PLAN.md`.

Current high-level state:
- Phase 0: ✅ Completed.
- Phase 1: ✅ Completed.
- Phase 2: 🟡 Partially implemented (DB helper migration and major export-worker extraction landed; remaining decomposition/performance follow-through continues).
- Phase 3: ✅ Completed (docs/dependency hygiene/contributor guide + full-repository CI lint gate).
- Phase 4: ✅ Completed.



### Next implementation steps
- Continue the remaining Phase 2 decomposition slices in `ExportDataThread` (worksheet-write and chart-rendering helper extraction with parity tests).
- Keep Phase 0/1/3/4 regression checks green while the remaining Phase 2 slices land.
- Expand optional Google export validation/testing coverage (including broader mocked and live-sandbox smoke checks as needed).


### Candidate new capabilities
- Add export-profile presets (chart-heavy vs fast diagnostics) to reduce repetitive dialog setup.
- Add optional parse pipeline benchmark report output (CSV/JSON) for factory-scale ingest tuning.

### Planned optimization follow-ups
- Export: additional profiling and inner-loop precomputation for chart-heavy workbooks.
- Parsing: stage-level timing + reduced redundant DB checks/regex work in large parse batches.
