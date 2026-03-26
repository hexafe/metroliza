# Distribution-fit native AD/KS + Monte Carlo kernels

This crate builds the Python extension module `_metroliza_distribution_fit_native`.

## Exported Python symbols

The extension exports:

- `_metroliza_distribution_fit_native.compute_ad_ks_statistics(distribution, fitted_params, sample_values)`
- `_metroliza_distribution_fit_native.estimate_ad_pvalue_monte_carlo(distribution, fitted_params, sample_size, observed_stat, iterations, seed=None)`

Application-level wrappers live in `modules/distribution_fit_native.py`:

- `compute_ad_ks_statistics_native(...)`
- `estimate_ad_pvalue_monte_carlo_native(...)`
- `native_backend_available()`

## Backend env toggles

Distribution-fit candidate kernels are controlled by `METROLIZA_DISTRIBUTION_FIT_KERNEL`:

- `auto` (default): attempt native candidate-kernel dispatch; if native symbols are unavailable, callers continue with Python implementations.
- `native`: require native candidate-kernel execution; unavailable native symbols return flagged kernel output and callers remain explicit about native-only intent.
- `python`: force Python candidate-kernel execution and skip native dispatch.

## Fallback semantics

- Native is opportunistic by default (`METROLIZA_DISTRIBUTION_FIT_KERNEL=auto`).
- Absence of the extension is non-fatal and expected to trigger Python fallback.
- Operators may force rollback (`python`) or require native (`native`) via `METROLIZA_DISTRIBUTION_FIT_KERNEL`.

## Build commands

```bash
# Install extension into the current interpreter (dev/editable workflow)
python -m maturin develop --manifest-path modules/native/distribution_fit_ad/Cargo.toml

# Build wheel artifact(s)
python -m maturin build --manifest-path modules/native/distribution_fit_ad/Cargo.toml --release
```

For cross-crate packaging and CI parity expectations, see `docs/native_build_distribution.md`.
