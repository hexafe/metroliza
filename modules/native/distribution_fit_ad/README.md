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

There is currently **no dedicated backend env toggle** for distribution-fit native kernels.

Runtime policy is import-driven:

- If `_metroliza_distribution_fit_native` imports successfully, wrappers call native kernels.
- If the extension is unavailable, wrappers return `None` and callers continue with Python implementations.

## Fallback semantics

- Native is opportunistic (auto-by-availability only).
- Absence of the extension is non-fatal and expected to trigger Python fallback.
- There is no `native`-forcing toggle for this module today.

## Build commands

```bash
# Install extension into the current interpreter (dev/editable workflow)
python -m maturin develop --manifest-path modules/native/distribution_fit_ad/Cargo.toml

# Build wheel artifact(s)
python -m maturin build --manifest-path modules/native/distribution_fit_ad/Cargo.toml --release
```

For cross-crate packaging and CI parity expectations, see `docs/native_build_distribution.md`.
