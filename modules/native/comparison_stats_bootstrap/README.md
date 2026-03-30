# Comparison stats native bootstrap + pairwise kernels

This crate builds the Python extension module `_metroliza_comparison_stats_native`.

## Exported Python symbols

The extension exports:

- `_metroliza_comparison_stats_native.bootstrap_percentile_ci(effect_kernel, groups, level, iterations, seed)`
- `_metroliza_comparison_stats_native.pairwise_stats(labels, groups, alpha, correction_method, non_parametric, equal_var)`

Application-level wrappers live in `modules/comparison_stats_native.py`:

- `bootstrap_percentile_ci_native(...)`
- `pairwise_stats_native(...)`
- `native_backend_available()`

## Backend env toggles

Two runtime toggles control fallback and strictness:

- `METROLIZA_COMPARISON_STATS_CI_BACKEND` controls the bootstrap CI kernel path (`auto` | `native` | `python`, default `auto`).
- `METROLIZA_COMPARISON_STATS_BACKEND` controls pairwise stats kernel path (`auto` | `native` | `python`, default `auto`).

Invalid values are treated as `auto`.

## Fallback semantics

- `auto` (default): use native when importable; otherwise return `None` and the Python implementation continues.
- `python`: always bypass native and return `None`.
- `native`: require extension availability and raise `RuntimeError` if unavailable.

There is no silent fallback from a forced `native` mode.

## Build commands

```bash
# Install extension into the current interpreter (dev/editable workflow)
python -m maturin develop --manifest-path modules/native/comparison_stats_bootstrap/Cargo.toml

# Build wheel artifact(s)
python -m maturin build --manifest-path modules/native/comparison_stats_bootstrap/Cargo.toml --release
```

For cross-crate packaging and CI parity expectations, see `docs/native_build_distribution.md`.
