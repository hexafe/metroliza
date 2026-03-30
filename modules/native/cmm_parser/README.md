# Native CMM parser

This crate exposes `_metroliza_cmm_native.parse_blocks(raw_lines)` as a Python extension.

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
