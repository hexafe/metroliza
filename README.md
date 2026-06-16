# Metroliza

[![CI](https://github.com/hexafe/metroliza/actions/workflows/ci.yml/badge.svg)](https://github.com/hexafe/metroliza/actions/workflows/ci.yml)

Metroliza is a Python desktop app for industrial metrology workflows: parsing measurement
reports, organizing data in SQLite, and creating analysis-ready Excel summaries,
dashboard-first grouped analysis, and CSV/production dashboards.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python metroliza.py
```

## Configuration essentials

- Google Sheets export is optional. Most users can run local Excel exports only; use Google export only if you need cloud sharing/sync.
- Google export needs local OAuth setup (Google Cloud project + OAuth client) before first use.
- Keep Google OAuth secrets local only: `credentials.json` and generated `token.json` should stay on your machine and must never be committed.
- For complete setup, validation, and troubleshooting, use the dedicated runbook: [`docs/google_conversion_smoke_runbook.md`](docs/google_conversion_smoke_runbook.md).

### License verification mode

- License verification is **disabled by default** at startup.
- Configure with `METROLIZA_LICENSE_VERIFICATION`:
  - truthy values (`1`, `true`, `yes`, `on`) enforce license validation.
  - falsy values (`0`, `false`, `no`, `off`) bypass license validation.
  - missing/invalid values fall back to the default (`disabled`).
- When license verification is enabled and validation fails, the app shows the hardware-id dialog and exits instead of launching the main window.
- `METROLIZA_STARTUP_SMOKE` remains available for non-interactive startup smoke checks.
- `METROLIZA_STARTUP_SPLASH=auto|1|0` controls launch feedback. The default `auto`
  shows an animated "Metroliza is loading..." splash during normal GUI launch,
  keeps it visible until feature warmup is complete, and disables it for
  headless UI-smoke runs.

Dependency files:
- `requirements.txt` - runtime
- `requirements-dev.txt` - development/testing
- `requirements-build.txt` - packaging
- `requirements-ocr.txt` - packaged header OCR runtime

## Windows Runtime Setup And OCR Diagnostics

On Windows, header OCR needs Python packages plus native DLL prerequisites. The
expected baseline is Windows x64, CPython x64, Microsoft Visual C++
Redistributable 2015-2022 x64, and the packages/model files listed above.

To create or refresh a local Windows runtime venv from the repo root:

```powershell
.\setup_windows_runtime.ps1 -Clean -InstallVcRedist
```

The script creates `.venv`, installs `requirements.txt` and `requirements-ocr.txt`,
checks for the VC++ Redistributable, validates the PyQt/Qt DLL runtime, validates
the vendored RapidOCR model files, and runs isolated ONNX/OpenCV/RapidOCR smoke
tests. If the VC++ Redistributable is missing, either install it from
`https://aka.ms/vs/17/release/vc_redist.x64.exe` or rerun with `-InstallVcRedist`.
If startup fails with `DLL load failed while importing QtCore`, run
`python scripts\validate_qt_runtime.py --compact` inside the activated venv.

To diagnose OCR for one PDF without relying on PowerShell output redirection:

```powershell
.\diagnose_windows_ocr.ps1 `
  -PdfPath "C:\path\to\report.pdf" `
  -DbFile "C:\path\to\reports.db" `
  -OutputPath "$env:USERPROFILE\Desktop\ocr_diag.json"
```

The output JSON includes module specs, native import smoke tests, VC++ runtime
registry status, RapidOCR model-file status, and the real parser metadata
diagnostic. A healthy OCR metadata path reports `header_extraction_mode="ocr"`
and `field_sources` such as `position_cell`, not `filename_candidate`.

## Build Windows EXE

For a simple PyInstaller onefile build on Windows, run from the repo root:

```powershell
.\build_windows_exe.ps1
```

Or double-click/run:

```bat
build_windows_exe.bat
```

The script creates `.venv-build`, installs runtime, PyInstaller, and OCR dependencies,
validates the vendored RapidOCR model files, builds `packaging/metroliza_onefile.spec`,
bundles `THIRD_PARTY_NOTICES.md`, and prints the generated `dist\*.exe` path. Use `.\build_windows_exe.ps1 -Clean` to
remove previous `build`/`dist` output first, or `.\build_windows_exe.ps1 -WithNative` to
use the native-module packaging helper.

If the OCR model files are missing, refresh them before building:

```powershell
python scripts/fetch_rapidocr_models.py
```

Official EXE builds include the OCR Python packages, RapidOCR model files, and
`THIRD_PARTY_NOTICES.md`. End users do not need to download OCR model files
separately when using an official EXE.

For a packaged parser smoke check, set a real OCR-needed PDF fixture and an
expected text fragment before launching the EXE:

```powershell
$env:METROLIZA_PDF_PARSER_SMOKE_FIXTURE = "C:\path\to\report.pdf"
$env:METROLIZA_PDF_PARSER_SMOKE_EXPECTED_TEXT = "expected text"
.\dist\metroliza.exe
```

The smoke path verifies that the packaged app can start, open the PDF parser
path, and find the expected text in the fixture. For an OCR-specific fixture,
also confirm the generated parser diagnostics report
`header_extraction_mode="ocr"`.


## Core workflow

1. Parse metrology PDFs/ZIPs and CSV data.
2. Store normalized records in SQLite.
3. Apply grouping labels where needed (default POPULATION rows stay white; user-created groups are auto color-coded with persistent pastel backgrounds).
4. Export local Excel workbooks with editable measurement sheets, summaries, and plots.
5. Review grouped Export analysis in the HTML dashboard; grouping enables dashboard output
   automatically.
6. Optionally generate a Google Sheets version while always keeping a local `.xlsx` fallback.
   - OAuth uses the minimal Drive scope: `https://www.googleapis.com/auth/drive.file`.
7. Optionally analyze CSV/Excel files or cached production-line rows with dashboard-first
   grouped analytics and optional Excel workbooks.
8. Optionally generate an HTML dashboard sidecar with offline Plotly interactions, an
   Auto/Light/Dark theme switch, and workbook-matching PNG snapshots.


## CMM parser backend policy

- Default (`METROLIZA_CMM_PARSER_BACKEND=auto`): native parser when extension is available.
- Automatic fallback to pure Python only when extension is missing.
- Controlled rollback: set `METROLIZA_CMM_PARSER_BACKEND=python`.
- Strict native mode: set `METROLIZA_CMM_PARSER_BACKEND=native` to fail fast if native extension is unavailable.

Parity between native and Python backends is enforced through fixture-based tests in `tests/test_cmm_parser_parity.py`.

## Chart renderer backend policy

- `METROLIZA_CHART_RENDERER_BACKEND` accepts `matplotlib` (default), `auto`, or `native`.
- `METROLIZA_PLOTSTATS_EXPORT_CHARTS=1` enables the release-candidate path that asks `hexafe-plotstats` to produce export chart artifacts first, then falls back to the current Metroliza/native renderer when the package cannot produce a given chart.
- Native chart rendering via `_metroliza_chart_native` is included when the native extension is built/installed in the packaging environment.
- `METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS` accepts a comma-separated allowlist such as `histogram,distribution,iqr,trend`; when unset, all supported chart kinds are enabled whenever native mode is opted in via `auto` or `native`.
- Matplotlib is the current default export path while native chart parity is still being tuned.
- In `auto`, the runtime export path re-enables native selection for enabled chart kinds whose native extension symbols are available.
- If `native` is forced while the native module is unavailable, Metroliza warns and falls back to matplotlib rendering.
- If `native` is forced for a chart kind that is not allowlisted for rollout, Metroliza warns and falls back to matplotlib rendering for that chart kind.
- Runtime export rendering is split into three layers:
  - `runtime` decides whether a chart kind may use the native backend.
  - `oracle` means the export path has already resolved matplotlib-derived geometry/spec data for parity-sensitive charts.
  - `fast-path` means the native compositor can render from that resolved payload without re-running matplotlib layout.
- Histogram, distribution, IQR, and trend use planner-driven native fast-path payloads in the export runtime only when native mode is opted in, the chart kind is allowlisted, and the native backend is available.
- The lower-level `_metroliza_chart_native` compositor entrypoints remain backward-compatible and can still synthesize fallback geometry/metadata for legacy payloads when called directly.
- For deterministic rollback behavior, either leave `METROLIZA_CHART_RENDERER_BACKEND` unset or set it explicitly to `matplotlib`.

## Additional native backend controls

- `METROLIZA_CMM_PERSIST_BACKEND`: controls CMM persistence backend (`auto`/`native`/`python`).
- `METROLIZA_COMPARISON_STATS_CI_BACKEND`: controls comparison bootstrap CI backend (`auto`/`native`/`python`).
- `METROLIZA_COMPARISON_STATS_BACKEND`: controls comparison pairwise backend (`auto`/`native`/`python`).
- `METROLIZA_DISTRIBUTION_FIT_KERNEL`: controls distribution-fit candidate kernel backend (`auto`/`native`/`python`).
- `METROLIZA_GROUP_STATS_BACKEND`: controls group-stats coercion backend (`auto`/`native`/`python`).
- See [`docs/native_build_distribution.md`](docs/native_build_distribution.md) for full backend semantics and packaging requirements.

### Local native chart extension build (optional)

```bash
python -m maturin develop --manifest-path src/metroliza/native/chart_renderer/Cargo.toml
# or build wheel artifacts
python -m maturin build --manifest-path src/metroliza/native/chart_renderer/Cargo.toml --release
```

## Parser plugin resolver controls

- End-user drop-in folder: Metroliza automatically discovers parser plugins placed in `~/.metroliza/parser_plugins/`.
- Default selection is strict and accepts parser probes only with confidence `>=80`; ties are resolved by confidence, plugin priority, then plugin id.
- To relax selection temporarily, set `PARSER_STRICT_MATCHING=false`.
- Probe results are cached per plugin/path during process runtime to reduce repeated probe work in batch parses.
- Normal report import discovers parser-supported `.pdf`, `.csv`, `.xlsx`, and `.xls` files, so approved CSV/Excel declarative profiles feed the same SQLite, CSV Summary, export, and dashboard path as PDF parsers.
- Advanced override: `PARSER_EXTERNAL_PLUGIN_PATHS` can point to extra plugin files or directories.
- Active parser plugin onboarding docs live under [`docs/parser_plugins/README.md`](docs/parser_plugins/README.md).
- Parser profile and generated-plugin handoff folders include self-contained LLM contracts, contract snippets, small prompts, a privacy checklist, and a manifest so external/local models do not need repository access.

## Group Analysis

Grouped Export analysis is dashboard-first. When grouping is applied, Export enables the
HTML dashboard automatically and writes the standard group comparison there. The workbook
stays focused on the main exported measurement sheets and selected workbook charts; do not
look for the standard group-analysis report as extra workbook worksheets.

Use Export grouping when you want named groups compared in the browser dashboard. Without
grouping, group analysis is off.

Current end-user training lives in the manuals:

- Export workflow and output choices:
  [`docs/user_manual/export_overview.md`](docs/user_manual/export_overview.md)
- CSV/Excel dashboard workflow, large-dataset options, sampling, snapshots, and
  troubleshooting: [`docs/user_manual/csv_summary.md`](docs/user_manual/csv_summary.md)
- Group analysis interpretation guide:
  [`docs/user_manual/group_analysis/user_manual.md`](docs/user_manual/group_analysis/user_manual.md)
- Printable group analysis companion:
  [`docs/user_manual/group_analysis/user_manual.pdf`](docs/user_manual/group_analysis/user_manual.pdf)

A practical reading order for grouped dashboard output is: start with the dashboard
summary, open the metric section you care about, then use the pairwise table, plots,
diagnostics, and caution notes for deeper review.

## Capability metrics legend (summary report)

Histogram statistics tables now use capability terminology aligned with common SPC notation:

- **Two-sided specs**: `Cp` and `Cpk` are shown.
- **One-sided upper specs**: `Cp` is shown as not defined (`Cp (not defined for one-sided) ⓘ`), and capability is shown as **`Cpu`**.
- **One-sided lower specs**: `Cp` is shown as not defined (`Cp (not defined for one-sided) ⓘ`), and capability is shown as **`Cpl`**.

Examples of metric availability by spec type:

- `Spec type: two-sided` → `Cp`, `Cpk`.
- `Spec type: one-sided upper` → `Cp (not defined for one-sided) ⓘ`, `Cpu`.
- `Spec type: one-sided lower` → `Cp (not defined for one-sided) ⓘ`, `Cpl`.

## Documentation map

### User manuals

- User manual hub: [`docs/user_manual/README.md`](docs/user_manual/README.md)
- Main window guide: [`docs/user_manual/main_window.md`](docs/user_manual/main_window.md)
- Parsing guide: [`docs/user_manual/parsing.md`](docs/user_manual/parsing.md)
- Modify Database guide: [`docs/user_manual/modify_database.md`](docs/user_manual/modify_database.md)
- Export overview: [`docs/user_manual/export_overview.md`](docs/user_manual/export_overview.md)
- CSV Summary guide: [`docs/user_manual/csv_summary.md`](docs/user_manual/csv_summary.md)
- Group analysis interpretation guide: [`docs/user_manual/group_analysis/user_manual.md`](docs/user_manual/group_analysis/user_manual.md)
- Group analysis printable companion: [`docs/user_manual/group_analysis/user_manual.pdf`](docs/user_manual/group_analysis/user_manual.pdf)

### Other repository docs

- Release highlights: [`CHANGELOG.md`](CHANGELOG.md)
- Third-party notices for packaged distributions: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)
- Contribution guide: [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Docs policy and lifecycle: [`docs/documentation_policy.md`](docs/documentation_policy.md)
- Release runbooks/checklists: [`docs/release_checks/`](docs/release_checks/)
- Google conversion smoke runbook: [`docs/google_conversion_smoke_runbook.md`](docs/google_conversion_smoke_runbook.md)
- Parser plugin generation and onboarding: [`docs/parser_plugins/README.md`](docs/parser_plugins/README.md)
- Historical plans and retired docs: [`docs/archive/`](docs/archive/)

## Release metadata

Current release highlight (`2026.06 RC1 (build 260616)`): Realtime and Industrial Data optimization release with streamed cache saves, multi-source fetches, shared source setup, background dashboard refresh, and dashboard point marking.

Canonical release metadata is in `src/metroliza/app/version.py`. The root `VersionDate.py`
module remains as a compatibility import for existing scripts.

### Changelog highlights (release `2026.06 RC1 (build 260616)`)

- See [`CHANGELOG.md`](CHANGELOG.md) for end-user release notes and version history.

Sync docs from release metadata:

```bash
python scripts/sync_release_metadata.py
```

Validate metadata consistency:

```bash
python scripts/sync_release_metadata.py --check
```
