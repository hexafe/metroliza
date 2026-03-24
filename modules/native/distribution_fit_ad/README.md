# Native distribution-fit AD backend

This crate builds the optional Python extension module `_metroliza_distribution_fit_native`.

## Exported Python symbols

The extension exports:

- `_metroliza_distribution_fit_native.compute_ad_ks_statistics(distribution, fitted_params, sample_values) -> tuple[float, float]`
- `_metroliza_distribution_fit_native.estimate_ad_pvalue_monte_carlo(distribution, fitted_params, sample_size, observed_stat, iterations, seed=None) -> tuple[float | None, int]`

Runtime bridge module: `modules/distribution_fit_native.py`.

## Backend env toggles

This backend currently has **no runtime environment toggle**. The bridge always follows extension availability.

## Fallback semantics

When `_metroliza_distribution_fit_native` is unavailable:

- `estimate_ad_pvalue_monte_carlo_native(...)` returns `None`.
- `compute_ad_ks_statistics_native(...)` returns `None`.

When available, bridge inputs are normalized to Python primitives before the extension call. Extension-side validation errors are surfaced as Python exceptions.

## Build locally (Rust + maturin)

```bash
python -m maturin develop --manifest-path modules/native/distribution_fit_ad/Cargo.toml
```

## Build wheels

```bash
python -m maturin build --manifest-path modules/native/distribution_fit_ad/Cargo.toml --release
```

For project-level distribution + CI requirements across all native crates, see `docs/native_build_distribution.md`.
