# Native module build and distribution requirements

This project ships optional native extension modules:

- `_metroliza_cmm_native` (`modules/native/cmm_parser`)
- `_metroliza_group_stats_native` (`modules/native/group_stats_coercion`)
- `_metroliza_comparison_stats_native` (`modules/native/comparison_stats_bootstrap`)
- `_metroliza_distribution_fit_native` (`modules/native/distribution_fit_ad`)
- `_metroliza_chart_native` (`modules/native/chart_renderer`)

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

- `modules/native/cmm_parser/Cargo.toml`
- `modules/native/group_stats_coercion/Cargo.toml`
- `modules/native/comparison_stats_bootstrap/Cargo.toml`
- `modules/native/distribution_fit_ad/Cargo.toml`
- `modules/native/chart_renderer/Cargo.toml`

Local developer commands:

```bash
# build binary wheel(s) for local interpreter
python -m maturin build --manifest-path modules/native/cmm_parser/Cargo.toml --release
python -m maturin build --manifest-path modules/native/group_stats_coercion/Cargo.toml --release
python -m maturin build --manifest-path modules/native/comparison_stats_bootstrap/Cargo.toml --release
python -m maturin build --manifest-path modules/native/distribution_fit_ad/Cargo.toml --release
python -m maturin build --manifest-path modules/native/chart_renderer/Cargo.toml --release

# install extension in editable/dev mode
python -m maturin develop --manifest-path modules/native/cmm_parser/Cargo.toml
python -m maturin develop --manifest-path modules/native/group_stats_coercion/Cargo.toml
python -m maturin develop --manifest-path modules/native/comparison_stats_bootstrap/Cargo.toml
python -m maturin develop --manifest-path modules/native/distribution_fit_ad/Cargo.toml
python -m maturin develop --manifest-path modules/native/chart_renderer/Cargo.toml
```

CI uses `cibuildwheel` and `maturin` to:

1. build wheels for all native crate manifests,
2. install a wheel artifact,
3. run import + minimal smoke checks for each native module,
4. validate explicit fallback behavior when extensions are intentionally absent,
5. run parser parity tests.

## Runtime backend + fallback behavior

Backend behavior varies per module and must remain explicit:

### CMM parser/persistence (`modules/cmm_native_parser.py`)

Parser backend selection is controlled by `METROLIZA_CMM_PARSER_BACKEND`:

- `auto` (default): use native backend when available; if extension import is unavailable, use pure Python.
- `native`: require native backend and raise if unavailable.
- `python`: force pure-Python backend (controlled operational rollback).

Persistence selection is controlled by `METROLIZA_CMM_PERSIST_BACKEND` with the same value semantics (`auto`/`native`/`python`).

### Comparison stats (`modules/comparison_stats_native.py`)

- `METROLIZA_COMPARISON_STATS_CI_BACKEND` controls bootstrap CI native usage (`auto`/`native`/`python`).
- `METROLIZA_COMPARISON_STATS_BACKEND` controls pairwise native usage (`auto`/`native`/`python`).
- In `auto`, unavailable native symbols produce `None` so Python callers execute fallback logic.
- In `native`, unavailable symbols raise `RuntimeError`.

### Chart renderer (`modules/chart_renderer.py`)

- Backend selection is controlled by `METROLIZA_CHART_RENDERER_BACKEND` (`auto`/`native`/`matplotlib`).
- Native chart rendering is shipped when `_metroliza_chart_native` is available in the packaged build environment.
- If `METROLIZA_CHART_RENDERER_BACKEND=native` is set while `_metroliza_chart_native` is unavailable, runtime emits a warning and falls back to matplotlib.
- `auto` uses native only when the extension is present; otherwise it defaults to matplotlib.

### Distribution fit (`modules/distribution_fit_native.py`)

- No dedicated env toggle yet.
- Native wrappers are opportunistic: they execute when importable and return `None` when unavailable.

### Group stats coercion (`modules/group_stats_native.py`)

- No dedicated env toggle yet.
- Native coercion is used when importable; otherwise wrapper falls back to Python coercion.

Runtime fallback from native execution errors in forced-`native` modes is intentionally disabled so backend behavior remains explicit and observable.

## PyInstaller inclusion rules and smoke checks

`packaging/metroliza_onefile.spec` includes:

- `hiddenimports=['_metroliza_cmm_native', '_metroliza_chart_native']`
- Windows Python runtime DLL collection (`libffi`, `python3*.dll`, `vcruntime`, `msvcp`) so onefile startup does not depend on a fragile ambient interpreter layout
- PyMuPDF/`fitz` data files, native libraries, and discovered submodules so packaged PDF parsing survives frozen builds

Distribution audit status:

- `pyinstaller packaging/metroliza_onefile.spec` produces a single-file artifact (`EXE(...)` with no `COLLECT(...)` stage), so it is configured as a onefile build rather than an onedir bundle.
- The spec explicitly preserves the known fragile runtime pieces for this app: optional native parser module, PyMuPDF backends, and Windows CPython runtime DLLs.
- Confidence is still release-evidence based rather than absolute: the generated artifact must be smoke-launched on a clean target environment before calling it ready for non-technical users.

Smoke checks after build:

```bash
pyinstaller packaging/metroliza_onefile.spec
# smoke import from generated app environment
python -c "import modules.cmm_native_parser as p; print(p.native_backend_available())"
```

If hidden import resolution fails on a platform, release may proceed only if pure-Python mode is validated.

If packaged Windows executables fail at startup with `ImportError: DLL load failed while importing _ctypes`, verify all of the following before release:

- build with current tooling from `requirements-build.txt` (newer PyInstaller + hooks),
- the build interpreter is a full CPython install (not embeddable/minimal),
- Python runtime DLLs under `<python>/DLLs` (including `libffi*.dll`) are bundled into the executable.

PyInstaller is the closest current path to a turnkey single-file distribution for non-technical users because it bundles the Python runtime into one artifact. Even so, treat "ready for distribution" as contingent on the packaged-artifact smoke run and at least one clean-machine launch check.


## Nuitka inclusion rules and smoke checks

`packaging/build_nuitka.ps1` now conditionally includes the native parser module when available in the build environment, auto-generates output naming from release metadata, and selects a healthy compiler strategy before invoking Nuitka:

- default output filename is `metroliza_N_<RELEASE_VERSION>(<VERSION_DATE>).exe` from `VersionDate.py`
- still supports explicit override with `-OutputName`
- supports `-CompilerStrategy auto|msvc|clang|gcc` plus opt-in `-AutoInstallCompiler` / `-OpenInstallHelp`
- prefers MSVC first on Windows, keeps GCC as a lower-priority fallback there, and prefers healthy clang/gcc toolchains on Linux/macOS
- maps the detected MSVC path to `--msvc=latest` so bundled PyMuPDF avoids the MinGW/SCons assembler failure path seen in some onefile builds
- prints candidate diagnostics, selected compiler, selection reason, and whether an auto-install attempt ran before the build starts
- can try an opt-in compiler install flow (`winget` on Windows, conventional package-manager flows on Linux/macOS when available), otherwise prints exact install guidance
- auto-adds `--include-module=_metroliza_cmm_native` only when `_metroliza_cmm_native` is importable
- auto-adds `--include-module=_metroliza_chart_native` only when `_metroliza_chart_native` is importable
- always includes the full `modules` package (`--include-package=modules`) so dynamic/compat imports are present in the executable
- explicitly includes `modules.cmm_report_parser`, `modules.report_parser_factory`, and `modules.pdf_backend` because the rc1 parser/plugin refactor introduced dynamic paths that packagers may otherwise under-detect
- requires PyMuPDF to be importable in the build environment and fails closed by default when it is not available
- always includes `pymupdf` / `fitz` package contents plus explicit PyMuPDF runtime submodules (`pymupdf._mupdf`, `pymupdf._extra`, `pymupdf.extra`, `pymupdf.mupdf`, table/utils helpers) so onefile builds do not silently omit parser internals
- validates the generated Nuitka report for both backend presence and required PyMuPDF runtime module references so packaged PDF parsing cannot silently drop out of the artifact
- defaults to pure-Python fallback packaging when native module is absent
- supports `-EnableConsole` for troubleshooting startup failures by showing a Windows console with traceback
- supports `-RequireNative` to fail fast if native module is missing
- bundles `credentials.json` into the executable only when the configured `-CredentialsPath` exists (default: `credentials.json`)
- always applies `--noinclude-data-files` guards for `token.json` path variants so OAuth tokens are not bundled

Smoke checks after build:

```powershell
./packaging/build_nuitka.ps1 -FastDev
# strict mode: require native parser to be present in the build env
./packaging/build_nuitka.ps1 -RequireNative
# troubleshooting mode: show console and traceback if startup fails
./packaging/build_nuitka.ps1 -EnableConsole
# compiler auto-detect (default)
./packaging/build_nuitka.ps1 -CompilerStrategy auto
# force MSVC on Windows and open install guidance if missing
./packaging/build_nuitka.ps1 -CompilerStrategy msvc -OpenInstallHelp
# opt-in attempt to install the preferred compiler if none is healthy
./packaging/build_nuitka.ps1 -AutoInstallCompiler
# unsafe diagnostics-only override; never acceptable for release artifacts
./packaging/build_nuitka.ps1 -AllowBrokenPdfParserBuild
```

If the extension is missing in the executable, parser code must still run in pure-Python mode. PDF parsing remains required for packaged builds, so `packaging/build_nuitka.ps1` still fails fast when PyMuPDF is not importable in the build environment and validates `nuitka-build-report.xml` after the build to confirm the packaged artifact still references PyMuPDF backends. On Windows, the script now auto-detects compiler health, prefers MSVC, and only applies `--msvc=latest` when MSVC is the selected path. If no healthy compiler is available, it either attempts an opt-in install flow or prints actionable guidance for Visual Studio 2022 Build Tools / Desktop development with C++ / MSVC toolset / Windows SDK. If the Nuitka compile step fails, the script throws immediately and does not continue to parser validation or misleading success output.

Nuitka release mode is also configured as onefile (`--onefile` by default, `--standalone` only for `-FastDev`). However, it is not yet a guaranteed zero-touch Windows distribution path because target machines may still need the Microsoft Visual C++ Redistributable installed. For non-technical-user releases, treat that prerequisite as a deployment risk unless your installer/bootstrapper handles it.

## Required CI checks for native artifacts

The native-artifacts CI job must validate all of the following:

1. wheel build succeeds for all native crate manifests,
2. wheel install succeeds for all built wheel artifacts,
3. each module imports and runs at least one minimal smoke function:
   - `modules.cmm_native_parser` (`parse_blocks_with_backend`)
   - `modules.group_stats_native` (`coerce_sequence_to_float64`)
   - `modules.comparison_stats_native` (`bootstrap_percentile_ci_native`, `pairwise_stats_native`)
   - `modules.distribution_fit_native` (`compute_ad_ks_statistics_native`, `estimate_ad_pvalue_monte_carlo_native`)
   - `modules.chart_renderer` (native histogram renderer path via `build_chart_renderer`)
4. fallback behavior is explicitly smoke-validated for intentionally absent extensions (mocked-unavailable symbols):
   - CMM parser path continues in Python when not forced to native,
   - comparison/distribution wrappers return `None` in availability-driven fallback mode,
   - group-stats coercion returns Python-coerced `float64`/`NaN` output.
5. parser parity tests pass when native backend is available.
