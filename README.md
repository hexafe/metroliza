# Metroliza

[![CI](https://github.com/hexafe/metroliza/actions/workflows/ci.yml/badge.svg)](https://github.com/hexafe/metroliza/actions/workflows/ci.yml)

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

## Release highlights

A short, non-technical changelog for end users is available in [`CHANGELOG.md`](CHANGELOG.md).

Current release highlight (`2026.02`, build `260228`): Google Sheets export messaging is clearer, `.xlsx` fallback is explicit, and chart-heavy exports remain faster for daily use.

Release-candidate readiness is tracked in the canonical checklist:
[`docs/release_checks/release_candidate_checklist.md`](docs/release_checks/release_candidate_checklist.md).

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

## Google Sheets export prerequisites and secret handling

Before using the Google Sheets export target (`google_sheets_drive_convert`), ensure:

- You have a Google Cloud OAuth client secret file available locally as `credentials.json` (or a local path you explicitly point the smoke harness to).
- A local OAuth token cache (`token.json`) is generated after first consent (Metroliza now opens an interactive Google authorization flow automatically when the token is missing or no longer refreshable); keep it local-only and rotate/revoke if shared machine access changes.
- `credentials.json` and `token.json` are ignored by git (including wildcard/path variants) and never committed to the repository.
- Only redacted examples/templates (for example `config/google/credentials.example.json`) are allowed in-repo.

If conversion fails or warnings indicate degraded chart/format fidelity, Metroliza keeps and reports the generated `.xlsx` path as the guaranteed fallback artifact.

Detailed smoke execution and troubleshooting guidance lives in the dedicated runbook:
[`docs/google_conversion_smoke_runbook.md`](docs/google_conversion_smoke_runbook.md).
Record release-gated smoke outcomes in:
[`docs/release_checks/google_conversion_smoke.md`](docs/release_checks/google_conversion_smoke.md).

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
Google Sheets conversion check (full runbook: [`docs/google_conversion_smoke_runbook.md`](docs/google_conversion_smoke_runbook.md)):

```bash
METROLIZA_RUN_GOOGLE_CONVERSION_SMOKE=1 \
METROLIZA_GOOGLE_SMOKE_CREDENTIALS_PATH=credentials.json \
METROLIZA_GOOGLE_SMOKE_TOKEN_PATH=token.json \
PYTHONPATH=. python tests/google_conversion_smoke.py
```

- This smoke check is **optional/non-default** and is intentionally excluded from the
  standard unit-test discover run.
- Use it for release validation (or explicitly gated CI jobs) to verify live Drive conversion behavior against a sandbox account.
- It fails fast with actionable configuration errors when local credentials/token files are missing or misconfigured.
- **Required cadence:** run for each release candidate and for any PR that changes Google-auth or Google-conversion logic.
- Current smoke expectations are release-gated conversion success + valid Google Sheet URL/ID metadata + `warnings=()`; keep the converted Google Sheet as convenience output and treat the generated `.xlsx` as the fidelity-baseline fallback artifact while warning root cause is investigated. Tab-title validation is covered by mocked tests, not by the live smoke script.

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

### Google conversion warnings or degraded formatting

Google Drive conversion can alter some advanced Excel chart/style details. Current release-gated smoke policy expects `warnings=()` on success for the Google Sheets export target (`google_sheets_drive_convert`).

- If warnings appear in app logs or release validation output, treat them as release blockers until triaged.
- Keep the converted Google Sheet as convenience output and treat the generated `.xlsx` as the fidelity-baseline fallback artifact while warning root cause is investigated.
- Re-run the optional live smoke check when changing credentials, scopes, or conversion-related logic.
- Confirm `credentials.json`/`token.json` are local-only and gitignored if auth errors or missing-file warnings appear.
- Record each release-gated run in `docs/release_checks/google_conversion_smoke.md`.

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
For release-candidate validation and documentation sync requirements, use the canonical checklist in [`docs/release_checks/release_candidate_checklist.md`](docs/release_checks/release_candidate_checklist.md) (single RC source of truth).

Current high-level state:
- Phase 0: ✅ Completed.
- Phase 1: ✅ Completed.
- Phase 2: ✅ Completed (correctness fixes, contracts migration, DB-helper consolidation, worker decomposition, and performance follow-through landed).
- Phase 3: ✅ Completed (docs/dependency hygiene/contributor guide + full-repository CI lint gate).
- Phase 4: ✅ Completed.



### Next implementation steps
- Keep Phase 0-4 regression checks green while maintenance/refinement work lands.
- Maintain release-gated Google conversion smoke-check discipline for release candidates and auth/conversion-changing PRs.
- Expand optional non-default validation coverage (additional mocked conversion/fallback cases and optional runbook automation).



### Changelog highlights (release `2026.02`, build `260228`)
- Google Sheets export target (`google_sheets_drive_convert`) now has clearer, fully aligned completion/fallback wording across user-facing docs.
- Conversion fallback behavior remains explicit: generated `.xlsx` output is always retained as the baseline artifact if Google conversion fails.
- Chart-heavy export optimizations from recent PRs continue to provide better runtime on large reports, and troubleshooting guidance now reflects that expected impact.

### Candidate new capabilities
- Add export-profile presets (chart-heavy vs fast diagnostics) to reduce repetitive dialog setup.
- Add optional parse pipeline benchmark report output (CSV/JSON) for factory-scale ingest tuning.

### Planned optimization follow-ups
- Export: additional profiling and inner-loop precomputation for chart-heavy workbooks.
- Parsing: stage-level timing + reduced redundant DB checks/regex work in large parse batches.

### Remaining optional/manual release validation
- Run the manual/CI-gated Google conversion smoke check for every release candidate.
- Also run it for any PR that changes Google auth/conversion behavior, then record command, timestamp, and outcome in PR notes.
- For conversion warnings, keep release blocked until warning cause + fallback impact are documented.
