# Native CMM parser prototype

This crate exposes `_metroliza_cmm_native.parse_blocks(raw_lines)` as a Python extension.

Current status:
- Prototype only.
- Not enabled by default in `CMMReportParser`.
- Used only for parity testing when built locally.

Build example (requires Rust + maturin):

```bash
cd modules/native/cmm_parser
maturin develop
```
