# Native CMM parser prototype

This crate exposes `_metroliza_cmm_native.parse_blocks(raw_lines)` as a Python extension.

Current status:
- Optional native backend.
- Runtime fallback to pure Python remains supported and required.
- Used for parity testing when built locally or in CI.

## Build locally (Rust + maturin)

```bash
python -m maturin develop --manifest-path modules/native/cmm_parser/Cargo.toml
```

## Build wheels

```bash
python -m maturin build --manifest-path modules/native/cmm_parser/Cargo.toml --release
```

For project-level distribution requirements and CI pipeline details, see
`docs/native_build_distribution.md`.
