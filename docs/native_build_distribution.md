# Native module build and distribution requirements

This project ships an optional native extension module: `_metroliza_cmm_native`.
The application must continue to run in pure-Python mode when the extension is not present.

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

- `auto` (default): use native backend when available, fallback to pure Python on import/runtime failure.
- `native`: require native backend, raise errors if unavailable/failing.
- `python`: force pure-Python backend.

This ensures packaged apps keep working even when the native binary is not bundled on a target machine.

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

## Nuitka inclusion rules and smoke checks

`packaging/build_nuitka.ps1` includes:

- `--include-module=_metroliza_cmm_native`

Smoke checks after build:

```powershell
./packaging/build_nuitka.ps1 -FastDev
# run the built executable in a sandbox and verify startup
```

If the extension is missing in the executable, parser code must still run in pure-Python mode.

## Required CI checks for native artifacts

The native-artifacts CI job must validate all of the following:

1. wheel build succeeds,
2. wheel install succeeds,
3. backend smoke checks for `python` and `native` selection behavior,
4. parser parity test passes when native backend is available.
