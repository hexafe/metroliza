# Group stats native coercion helper

This crate exposes `_metroliza_group_stats_native.coerce_sequence_to_float64(values)`.

Behavior:
- Accepts a Python sequence.
- Returns `float64` NumPy array values.
- Non-coercible entries are mapped to `NaN`.

Build locally:

```bash
python -m maturin develop --manifest-path modules/native/group_stats_coercion/Cargo.toml
```
