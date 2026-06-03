# Native module build and distribution requirements

This project ships optional native extension modules:

- `_metroliza_cmm_native` (`src/metroliza/native/cmm_parser`)
- `_metroliza_group_stats_native` (`src/metroliza/native/group_stats_coercion`)
- `_metroliza_comparison_stats_native` (`src/metroliza/native/comparison_stats_bootstrap`)
- `_metroliza_distribution_fit_native` (`src/metroliza/native/distribution_fit_ad`)
- `_metroliza_chart_native` (`src/metroliza/native/chart_renderer`)

Each extension is optional at runtime. The app must keep deterministic Python-path behavior when native binaries are unavailable.

## Supported platforms and architectures

Native wheels are built for CPython 3.11 on:

- Linux: `x86_64` (`manylinux`) and `aarch64`.
- Windows: `AMD64`.
- macOS: `x86_64` and `arm64`.

Source distributions (`sdist`) are published for unsupported combinations.
On unsupported platforms, the app defaults to pure-Python parsing.

## Wheel build pipeline

Build tooling requirements are tracked in `requirements-build.txt` (`maturin`, `cibuildwheel`, `build`).

Native crate manifests:

- `src/metroliza/native/cmm_parser/Cargo.toml`
- `src/metroliza/native/group_stats_coercion/Cargo.toml`
- `src/metroliza/native/comparison_stats_bootstrap/Cargo.toml`
- `src/metroliza/native/distribution_fit_ad/Cargo.toml`
- `src/metroliza/native/chart_renderer/Cargo.toml`

Local developer commands:

```bash
# build binary wheel(s) for local interpreter
python -m maturin build --manifest-path src/metroliza/native/cmm_parser/Cargo.toml --release
python -m maturin build --manifest-path src/metroliza/native/group_stats_coercion/Cargo.toml --release
python -m maturin build --manifest-path src/metroliza/native/comparison_stats_bootstrap/Cargo.toml --release
python -m maturin build --manifest-path src/metroliza/native/distribution_fit_ad/Cargo.toml --release
python -m maturin build --manifest-path src/metroliza/native/chart_renderer/Cargo.toml --release

# install extension in editable/dev mode
python -m maturin develop --manifest-path src/metroliza/native/cmm_parser/Cargo.toml
python -m maturin develop --manifest-path src/metroliza/native/group_stats_coercion/Cargo.toml
python -m maturin develop --manifest-path src/metroliza/native/comparison_stats_bootstrap/Cargo.toml
python -m maturin develop --manifest-path src/metroliza/native/distribution_fit_ad/Cargo.toml
python -m maturin develop --manifest-path src/metroliza/native/chart_renderer/Cargo.toml
```

Windows/PowerShell helper for the full native-first packaging flow:

```powershell
# build all native extensions, verify them, then package with Nuitka
./packaging/build_native_and_package.ps1

# build all native extensions, verify them, then package with PyInstaller
./packaging/build_native_and_package.ps1 -Packager pyinstaller

# only build+verify native extensions, skip packaging
./packaging/build_native_and_package.ps1 -Packager none

# narrow the build to the parser/chart hot paths
./packaging/build_native_and_package.ps1 -NativeTargets cmm,chart -Packager nuitka
```

The helper script:

- installs `requirements-build.txt` into the active Python environment,
- builds the requested native modules with `python -m maturin develop --release`,
- verifies backend availability in that same environment,
- then optionally hands off to `packaging/build_nuitka.ps1` or `python -m PyInstaller`.

On Windows, prefer CPython 3.11 x64 for release packaging. The helper warns on other interpreter versions because the project CI/wheel path is validated there first.

CI uses `cibuildwheel` and `maturin` to:

1. build wheels for all native crate manifests,
2. install a wheel artifact,
3. run import + minimal smoke checks for each native module,
4. validate explicit fallback behavior when extensions are intentionally absent,
5. run parser parity tests.

## Runtime backend + fallback behavior

Backend behavior varies per module and must remain explicit:

### CMM parser/persistence (`src/metroliza/native_bridges/cmm_native_parser.py`)

Parser backend selection is controlled by `METROLIZA_CMM_PARSER_BACKEND`:

- `auto` (default): use native backend when available; if extension import is unavailable, use pure Python.
- `native`: require native backend and raise if unavailable.
- `python`: force pure-Python backend (controlled operational rollback).

Persistence selection is controlled by `METROLIZA_CMM_PERSIST_BACKEND` with the same value semantics (`auto`/`native`/`python`).

### Comparison stats (`src/metroliza/native_bridges/comparison_stats_native.py`)

- `METROLIZA_COMPARISON_STATS_CI_BACKEND` controls bootstrap CI native usage (`auto`/`native`/`python`).
- `METROLIZA_COMPARISON_STATS_BACKEND` controls pairwise native usage (`auto`/`native`/`python`).
- In `auto`, unavailable native symbols produce `None` so Python callers execute fallback logic.
- In `native`, unavailable symbols raise `RuntimeError`.

### Chart renderer (`src/metroliza/charts/chart_renderer.py`)

- Backend selection is controlled by `METROLIZA_CHART_RENDERER_BACKEND` (`matplotlib`/`auto`/`native`).
- Workbook images and HTML dashboard Plotly specs use the `hexafe-plotstats` chart artifact path by default, then fall back to the existing Metroliza/native renderer for unsupported payloads. Set `METROLIZA_PLOTSTATS_EXPORT_CHARTS=0` (or `false`/`off`/`legacy`) to disable the plotstats-first path for diagnostics or rollback.
- Native rollout selection is controlled per chart kind by `METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS` (comma-separated allowlist such as `histogram,distribution,iqr,trend`); when unset, all supported chart kinds are enabled whenever `auto` or `native` is selected.
- Native chart rendering is shipped when `_metroliza_chart_native` is available in the packaged build environment.
- The current native module covers histogram, distribution, IQR, and trend summary charts through the `_metroliza_chart_native` extension surface.
- The native chart path is a payload-driven non-matplotlib compositor intended for workbook/export rendering, not an HTML/interactive chart stack.
- The optional HTML dashboard sidecar remains a separate Python-side export artifact rather than part of the native chart extension.
- The dashboard copies a vendored Plotly runtime into each exported `*_dashboard_assets/` folder, so interactive hover/zoom works offline and survives frozen Windows builds without a CDN dependency; the saved page also ships an Auto/Light/Dark theme control.
- If `METROLIZA_CHART_RENDERER_BACKEND=native` is set while `_metroliza_chart_native` is unavailable, runtime emits a warning and falls back to matplotlib.
- With the plotstats-first path disabled, Matplotlib remains the fallback renderer while native chart parity is being tuned.
- With the plotstats-first path disabled, `auto` re-enables native selection for enabled chart kinds when the extension is present and otherwise falls back to matplotlib.
- CI's native-artifacts job now runs `tests/test_native_chart_renderer_smoke.py` against the compiled wheel so histogram, distribution, IQR, and trend all prove native dispatch with planner-built resolved specs attached, and it also runs a focused export-runtime fast-path contract smoke for the extended summary-sheet charts.
- In the export runtime, histogram, distribution, IQR, and trend use planner-driven resolved specs on the native fast-path only when native mode is opted in and the chart kind is enabled for rollout.

### Distribution fit (`src/metroliza/native_bridges/distribution_fit_native.py`)

- Candidate-kernel backend selection is controlled by `METROLIZA_DISTRIBUTION_FIT_KERNEL` (`auto`/`native`/`python`).
- `auto` (default) is availability-driven: native candidate kernels are attempted when present and otherwise Python fallback remains active.
- `native` requires native candidate-kernel execution semantics (no silent mode switch to Python).
- `python` forces pure-Python candidate metrics and skips native dispatch.
- `_metroliza_distribution_fit_native` now exports native candidate metric kernels and native batch fit-parameter estimation.
- The current native fit batch covers the full current candidate pool: `norm`, `skewnorm`, `halfnorm`, `foldnorm`, `gamma`, `weibull_min`, `lognorm`, and `johnsonsu`.
- Backend diagnostics expose both `metrics_available` and `fit_available` for the distribution-fit candidate bridge.

### Group stats coercion (`src/metroliza/native_bridges/group_stats_native.py`)

- Backend selection is controlled by `METROLIZA_GROUP_STATS_BACKEND` (`auto`/`native`/`python`).
- `auto` (default): uses native coercion when available, otherwise wrapper falls back to Python coercion.
- `native`: requires native coercion and raises if unavailable.
- `python`: forces Python coercion and bypasses native dispatch.

Runtime fallback from native execution errors in forced-`native` modes is intentionally disabled so backend behavior remains explicit and observable.

## PyInstaller inclusion rules and smoke checks

`packaging/metroliza_onefile.spec` and `packaging/metroliza_onedir.spec` share
the same collection rules through `packaging/pyinstaller_common.py`. They include:

- `hiddenimports=['_metroliza_cmm_native', '_metroliza_chart_native', '_metroliza_group_stats_native', '_metroliza_comparison_stats_native', '_metroliza_distribution_fit_native']`
- Windows Python runtime DLL collection (`libffi`, `python3*.dll`, `vcruntime`, `msvcp`) so onefile startup does not depend on a fragile ambient interpreter layout
- PyMuPDF/`fitz` data files, native libraries, and discovered submodules so packaged PDF parsing survives frozen builds
- RapidOCR, ONNX Runtime, OpenCV, NumPy, OCR adapter modules, and vendored
  `src/metroliza/resources/ocr_models/rapidocr/*.onnx` model assets so packaged header OCR does not
  depend on runtime downloads
- root `THIRD_PARTY_NOTICES.md` plus OCR package distribution metadata where available,
  so release artifacts retain the RapidOCR/ONNX/OpenCV/NumPy license and attribution
  notice set
- the vendored dashboard runtime asset at `src/metroliza/resources/html_dashboard_assets/plotly-2.27.0.min.js` so HTML sidecars can copy a local Plotly bundle into the export folder

Distribution audit status:

- `pyinstaller packaging/metroliza_onefile.spec` produces the single-file
  convenience artifact.
- `pyinstaller packaging/metroliza_onedir.spec` produces the faster-starting
  folder artifact under `dist/metroliza_P_<RELEASE_VERSION>(<VERSION_DATE>)_onedir/`.
- default PyInstaller output filename follows release metadata: `metroliza_P_<RELEASE_VERSION>(<VERSION_DATE>).exe`
- the root `build_windows_exe.ps1` wrapper supports
  `-Mode onefile|onedir|both` and defaults to `both` for RC testing.
- The spec explicitly preserves the known fragile runtime pieces for this app: optional native parser module, PyMuPDF backends, and Windows CPython runtime DLLs.
- The root `build_windows_exe.ps1` wrapper installs `requirements-build.txt`, then
  `requirements-ocr.txt`, and runs the packaged-dependency validator with
  `--require-header-ocr` before building, so missing build dependencies, RapidOCR
  dependencies, or model files fail before a broken EXE is produced.
- Commercial or external distributions must keep `THIRD_PARTY_NOTICES.md` with the
  packaged artifact and retain the bundled package license/metadata files where the
  packager preserves them.
- Exported HTML dashboards no longer rely on internet access: the packaged app copies the bundled Plotly runtime into the dashboard asset folder next to the PNG snapshots.
- Confidence is still release-evidence based rather than absolute: the generated artifact must be smoke-launched on a clean target environment before calling it ready for non-technical users.

Smoke checks after build:

```bash
pyinstaller packaging/metroliza_onefile.spec
pyinstaller packaging/metroliza_onedir.spec
# smoke import from generated app environment
python -c "import metroliza.native_bridges.cmm_native_parser as p; print(p.native_backend_available())"
```

If hidden import resolution fails on a platform, release may proceed only if pure-Python mode is validated.

If packaged Windows executables fail at startup with `ImportError: DLL load failed while importing _ctypes`, verify all of the following before release:

- build with current tooling from `requirements-build.txt` (newer PyInstaller + hooks),
- the build interpreter is a full CPython install (not embeddable/minimal),
- Python runtime DLLs under `<python>/DLLs` (including `libffi*.dll`) are bundled into the executable.

If a source venv or packaged artifact fails with `ImportError: DLL load failed while importing QtCore`, first validate the Windows runtime venv:

```powershell
.\setup_windows_runtime.ps1 -Clean -InstallVcRedist
.\.venv\Scripts\python.exe scripts\validate_qt_runtime.py --compact
```

The Qt validator reports the installed `PyQt6`, `PyQt6-Qt6`, `PyQt6-sip`, Qt
library paths, and VC++ Redistributable registry status. Do not release a Windows
artifact from an environment where the PyQt wrapper and bundled Qt payload are
from different Qt major/minor lines.

PyInstaller onefile remains the closest turnkey single-file distribution for
non-technical users because it bundles the Python runtime into one artifact.
For startup-sensitive Windows testing, prefer the onedir artifact: it avoids
bootloader extraction of the full scientific/OCR payload on every cold launch
and gives Windows Defender a more stable file set to cache. Treat both outputs
as contingent on packaged-artifact smoke runs and at least one clean-machine
launch check.

Startup profiling:

```powershell
.\build_windows_exe.ps1 -Mode both
.\scripts\measure_windows_startup.ps1 `
  -ArtifactPath .\dist\metroliza_P_<version>.exe,.\dist\metroliza_P_<version>_onedir\metroliza.exe `
  -Iterations 3 `
  -WarmupRuns 1
```

The benchmark helper launches each artifact with `METROLIZA_STARTUP_PROFILE=1`
and `METROLIZA_STARTUP_UI_SMOKE=1`, writes JSONL timing profiles, and exits after
the first Qt event-loop tick. Python-side events start at `process_entry`; they
cannot include PyInstaller/Nuitka bootloader extraction time, so compare the
helper's wall-clock time against the first profile event to understand onefile
extraction and antivirus overhead.

For local diagnosis, run `python scripts/summarize_startup_profile.py
<profile.jsonl>` on a captured profile. The summary reports first feedback,
first main-window show, first event-loop tick, and post-paint feature warmup
module timings. The visual startup splash defaults to `METROLIZA_STARTUP_SPLASH=auto`
for normal GUI launches, stays visible until feature warmup finishes, and remains
disabled for offscreen UI smoke unless forced.


## Nuitka inclusion rules and smoke checks

`packaging/build_nuitka.ps1` now conditionally includes the native parser module when available in the build environment, auto-generates output naming from release metadata, and selects a healthy compiler strategy before invoking Nuitka:

- default output filename is `metroliza_N_<RELEASE_VERSION>(<VERSION_DATE>).exe` from package release metadata
- still supports explicit override with `-OutputName`
- supports `-Mode onefile|standalone`; legacy `-FastDev` maps to
  `-Mode standalone`
- supports `-CompilerStrategy auto|gcc|clang` plus opt-in `-AutoInstallCompiler`
  / `-OpenInstallHelp`
- intentionally avoids MSVC/Visual Studio Build Tools, prefers MinGW-w64 GCC on
  Windows, and uses Clang as the non-MSVC fallback
- prints candidate diagnostics, selected compiler, selection reason, and whether an auto-install attempt ran before the build starts
- can try an opt-in compiler install flow (`winget` on Windows, conventional package-manager flows on Linux/macOS when available), otherwise prints exact install guidance
- auto-adds `--include-module=_metroliza_cmm_native` only when `_metroliza_cmm_native` is importable
- auto-adds `--include-module=_metroliza_chart_native` only when `_metroliza_chart_native` is importable
- auto-adds `--include-module=_metroliza_group_stats_native` only when `_metroliza_group_stats_native` is importable
- auto-adds `--include-module=_metroliza_comparison_stats_native` only when `_metroliza_comparison_stats_native` is importable
- auto-adds `--include-module=_metroliza_distribution_fit_native` only when `_metroliza_distribution_fit_native` is importable
- always includes the full `modules` package (`--include-package=modules`) so dynamic/compat imports are present in the executable
- explicitly includes `metroliza.parsing.cmm_report_parser`, the header OCR adapter modules,
  `metroliza.reports.report_parser_factory`, and `metroliza.parsing.pdf_backend` because the parser/plugin
  refactor introduced dynamic paths that packagers may otherwise under-detect
- requires RapidOCR/ONNX/OpenCV/NumPy and the three vendored RapidOCR ONNX files by
  default; `-AllowMissingHeaderOcrBuild` exists only for unsafe local diagnostics and is
  not acceptable for release artifacts
- includes RapidOCR, ONNX Runtime, OpenCV, NumPy package data and the vendored OCR model
  files in the Nuitka data set
- includes RapidOCR, ONNX Runtime, OpenCV, and NumPy distribution metadata where
  available, and bundles the root `THIRD_PARTY_NOTICES.md` notice file as release data
- explicitly includes the vendored Plotly runtime as a data file so exported HTML dashboards can stay offline-capable in frozen builds
- requires PyMuPDF to be importable in the build environment and fails closed by default when it is not available
- always includes `pymupdf` / `fitz` package contents plus explicit PyMuPDF runtime submodules (`pymupdf._mupdf`, `pymupdf._extra`, `pymupdf.extra`, `pymupdf.mupdf`, table/utils helpers) so onefile builds do not silently omit parser internals
- validates the generated Nuitka report for PyMuPDF runtime modules and header OCR
  modules/model data plus `THIRD_PARTY_NOTICES.md` so packaged PDF parsing, OCR, or the
  OCR notice file cannot silently drop out of the artifact
- defaults to pure-Python fallback packaging when native module is absent
- supports `-EnableConsole` for troubleshooting startup failures by showing a Windows console with traceback
- supports `-RequireNative` to fail fast if native module is missing
- disables OAuth credential bundling by default; credentials are included only
  when an explicitly approved build passes both `-BundleCredentials` and
  `-CredentialsPath <path>`
- always applies `--noinclude-data-files` guards for `token.json` path variants so OAuth tokens are not bundled

Smoke checks after build:

```powershell
./packaging/build_nuitka.ps1 -Mode standalone
./packaging/build_nuitka.ps1 -FastDev
# strict mode: require native parser to be present in the build env
./packaging/build_nuitka.ps1 -RequireNative
# troubleshooting mode: show console and traceback if startup fails
./packaging/build_nuitka.ps1 -EnableConsole
# explicitly approved sandbox credential bundle, never the normal release default
./packaging/build_nuitka.ps1 -BundleCredentials -CredentialsPath .\sandbox.credentials.json
# compiler auto-detect (default)
./packaging/build_nuitka.ps1 -CompilerStrategy auto
# force GCC on Windows and open install guidance if missing
./packaging/build_nuitka.ps1 -CompilerStrategy gcc -OpenInstallHelp
# opt-in attempt to install the preferred compiler if none is healthy
./packaging/build_nuitka.ps1 -AutoInstallCompiler
# unsafe diagnostics-only override; never acceptable for release artifacts
./packaging/build_nuitka.ps1 -AllowBrokenPdfParserBuild
# unsafe diagnostics-only override; never acceptable for release artifacts
./packaging/build_nuitka.ps1 -AllowMissingHeaderOcrBuild
```

If the extension is missing in the executable, parser code must still run in pure-Python mode. PDF parsing remains required for packaged builds, so `packaging/build_nuitka.ps1` still fails fast when PyMuPDF is not importable in the build environment and validates `nuitka-build-report.xml` after the build to confirm the packaged artifact still references PyMuPDF backends. On Windows, the script auto-detects compiler health, prefers MinGW-w64 GCC, and uses Clang as the non-MSVC fallback. If no healthy compiler is available, it either attempts an opt-in install flow or prints actionable guidance for MSYS2/MinGW-w64 or LLVM/Clang. If the Nuitka compile step fails, the script throws immediately and does not continue to parser validation or misleading success output.

Nuitka release mode is also configured as onefile (`--onefile` by default,
`--standalone` for `-Mode standalone` or `-FastDev`). However, it is not yet a
guaranteed zero-touch Windows distribution path because target machines may
still need the Microsoft Visual C++ Redistributable installed. For
non-technical-user releases, treat that prerequisite as a deployment risk unless
your installer/bootstrapper handles it.

## Required CI checks for native artifacts

The native-artifacts CI job must validate all of the following:

1. wheel build succeeds for all native crate manifests,
2. wheel install succeeds for all built wheel artifacts,
3. each module imports and runs at least one minimal smoke function:
   - `metroliza.native_bridges.cmm_native_parser` (`parse_blocks_with_backend`)
   - `metroliza.native_bridges.group_stats_native` (`coerce_sequence_to_float64`)
   - `metroliza.native_bridges.comparison_stats_native` (`bootstrap_percentile_ci_native`, `pairwise_stats_native`)
   - `metroliza.native_bridges.distribution_fit_native` (`compute_ad_ks_statistics_native`, `estimate_ad_pvalue_monte_carlo_native`)
   - `metroliza.charts.chart_renderer` (native histogram renderer path via `build_chart_renderer`)
4. fallback behavior is explicitly smoke-validated for intentionally absent extensions (mocked-unavailable symbols):
   - CMM parser path continues in Python when not forced to native,
   - comparison/distribution wrappers return `None` in availability-driven fallback mode,
   - group-stats coercion returns Python-coerced `float64`/`NaN` output.
5. native chart planner parity smoke passes against the checked-in chart fixtures:
   - live planner builders match `tests/fixtures/chart_parity/*/planner_spec.json`,
   - native chart rendering stays within the configured image-diff thresholds against the checked-in matplotlib references,
   - the compiled-wheel smoke covers histogram, distribution scatter, distribution violin, IQR, and trend dispatch,
   - the export runtime fast-path contract is smoke-validated for the extended summary-sheet chart path.
6. parser parity tests pass when native backend is available.
