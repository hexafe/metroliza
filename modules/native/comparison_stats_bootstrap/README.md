# Native comparison stats bootstrap backend

This crate builds the optional Python extension module `_metroliza_comparison_stats_native`.

## Exported Python symbols

The extension exports:

- `_metroliza_comparison_stats_native.bootstrap_percentile_ci(effect_kernel, groups, level, iterations, seed) -> tuple[float, float] | None`
- `_metroliza_comparison_stats_native.pairwise_stats(labels, groups, alpha, correction_method, non_parametric, equal_var) -> list[dict]`

Runtime bridge module: `modules/comparison_stats_native.py`.

## Backend env toggles

`modules/comparison_stats_native.py` uses independent toggles:

- `METROLIZA_COMPARISON_STATS_CI_BACKEND` controls `bootstrap_percentile_ci_native(...)`.
- `METROLIZA_COMPARISON_STATS_BACKEND` controls `pairwise_stats_native(...)`.

Allowed values for each toggle:

- `auto` (default): use native when extension is importable, otherwise fall back.
- `native`: require native backend and raise if extension is unavailable.
- `python`: force Python fallback path.

## Fallback semantics

- In `auto` mode, when `_metroliza_comparison_stats_native` cannot be imported:
  - `bootstrap_percentile_ci_native(...)` returns `None`.
  - `pairwise_stats_native(...)` returns `None`.
- In `native` mode with missing extension, both bridge functions raise `RuntimeError`.
- Invalid/unsupported native inputs are validated in Rust and can raise `ValueError` from the extension.

## Build locally (Rust + maturin)

```bash
python -m maturin develop --manifest-path modules/native/comparison_stats_bootstrap/Cargo.toml
```

## Build wheels

```bash
python -m maturin build --manifest-path modules/native/comparison_stats_bootstrap/Cargo.toml --release
```

For project-level distribution + CI requirements across all native crates, see `docs/native_build_distribution.md`.
