# Native CMM parser

This crate exposes the following Python extension entrypoints:

- `_metroliza_cmm_native.parse_blocks(raw_lines)`
- `_metroliza_cmm_native.normalize_measurement_rows(blocks, reference, fileloc, filename, date, sample_number)`
- `_metroliza_cmm_native.persist_measurement_rows(database, rows)`

`normalize_measurement_rows` emits a stable flat row schema:
`(ax, nom, tol_plus, tol_minus, bonus, meas, dev, outtol, header, reference, fileloc, filename, date, sample_number)`.

## Runtime policy

- Default behavior (`METROLIZA_CMM_PARSER_BACKEND=auto`) selects the native backend whenever the extension is available.
- If the extension is missing, runtime automatically falls back to the pure-Python backend.
- Controlled rollback is available via `METROLIZA_CMM_PARSER_BACKEND=python`.
- `METROLIZA_CMM_PARSER_BACKEND=native` enforces native usage and raises if the extension is unavailable.

This policy keeps performance wins by default while preserving a safe rollback path for operations.

## Build locally (Rust + maturin)

```bash
python -m maturin develop --manifest-path modules/native/cmm_parser/Cargo.toml
```

## Build wheels

```bash
python -m maturin build --manifest-path modules/native/cmm_parser/Cargo.toml --release
```

## Parity strategy

Parity is verified by fixture-based tests that compare native and Python parser outputs when the extension is available (`tests/test_cmm_parser_parity.py`).

For project-level distribution requirements and CI pipeline details, see
`docs/native_build_distribution.md`.
