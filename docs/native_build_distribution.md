# Native module build and distribution requirements

This project ships an optional native extension module: `_metroliza_cmm_native`.
The application defaults to native parsing when the extension is present and continues to run in pure-Python mode when it is not.

## Supported platforms and architectures

Native wheels are built for CPython 3.11 on:

- Linux: `x86_64` (`manylinux`) and `aarch64`.
- Windows: `AMD64`.
- macOS: `x86_64` and `arm64`.

Source distributions (`sdist`) are published for unsupported combinations.
On unsupported platforms, the app defaults to pure-Python parsing.

## Wheel build pipeline

The extension source lives in `modules/native/cmm_parser`.
Build tooling requirements are tracked in `requirements-build.txt` (`maturin`, `cibuildwheel`, `build`).

Local developer commands:

```bash
# build binary wheel(s) for local interpreter
python -m maturin build --manifest-path modules/native/cmm_parser/Cargo.toml --release

# install extension in editable/dev mode
python -m maturin develop --manifest-path modules/native/cmm_parser/Cargo.toml
```

CI uses `cibuildwheel` and `maturin` to:

1. build wheels from `modules/native/cmm_parser/Cargo.toml`,
2. install a wheel artifact,
3. run a native smoke check,
4. run parser parity tests.

## Runtime backend + fallback behavior

Parser backend selection is controlled by `METROLIZA_CMM_PARSER_BACKEND`:

- `auto` (default): use native backend when available; if extension import is unavailable, use pure Python.
- `native`: require native backend and raise if unavailable.
- `python`: force pure-Python backend (controlled operational rollback).

Runtime fallback from native execution errors is intentionally disabled so backend behavior is explicit and observable. This ensures packaged apps keep working when the native binary is not bundled, while preserving deterministic rollback controls.

## PyInstaller inclusion rules and smoke checks

`packaging/metroliza_onefile.spec` includes:

- `hiddenimports=['_metroliza_cmm_native']`

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


## Nuitka inclusion rules and smoke checks

`packaging/build_nuitka.ps1` now conditionally includes the native parser module when available in the build environment and auto-generates output naming from release metadata:

- default output filename is `metroliza_N_<RELEASE_VERSION>(<VERSION_DATE>).exe` from `VersionDate.py`
- still supports explicit override with `-OutputName`
- forces `--msvc=latest` on Windows so bundled PyMuPDF avoids the MinGW/SCons assembler failure path seen in some onefile builds
- auto-adds `--include-module=_metroliza_cmm_native` only when `_metroliza_cmm_native` is importable
- always includes the full `modules` package (`--include-package=modules`) so dynamic/compat imports are present in the executable
- requires PyMuPDF to be importable in the build environment and fails closed by default when it is not available
- always includes `pymupdf` / `fitz` package contents and validates the generated Nuitka report so packaged PDF parsing cannot silently drop out of the artifact
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
# unsafe diagnostics-only override; never acceptable for release artifacts
./packaging/build_nuitka.ps1 -AllowBrokenPdfParserBuild
```

If the extension is missing in the executable, parser code must still run in pure-Python mode. PDF parsing remains required for packaged builds, so `packaging/build_nuitka.ps1` now fails fast when PyMuPDF is not importable in the build environment and validates `nuitka-build-report.xml` after the build to confirm the packaged artifact still references PyMuPDF backends. On Windows, the script forces `--msvc=latest` so Nuitka uses the Visual Studio toolchain instead of the MinGW path that has been seen to fail while compiling PyMuPDF C sources.

## Required CI checks for native artifacts

The native-artifacts CI job must validate all of the following:

1. wheel build succeeds,
2. wheel install succeeds,
3. backend smoke checks for `python` and `native` selection behavior,
4. parser parity test passes when native backend is available.
