# Edge Fixture Manifest

This manifest documents the intent of curated edge fixtures used by parser parity,
pairwise statistics, and distribution-fit native parity tests.

## CMM parser fixtures

- `tests/fixtures/cmm_parser/unusual_token_layout_variants.json`
  - **Intent:** exercise semantic labels (`NOMINAL`, `+TOL`, `OUTTOL`) and split TP tokens (`MMC`, `NOM:`) mixed with numeric payloads.
  - **Expected outcome:** parser drops non-numeric labels for non-TP rows, preserves TP qualifiers, and emits a single deterministic block snapshot.

## Pairwise statistics fixtures

- `tests/fixtures/comparison_stats/pairwise_edge_cases.json`
  - `tied ranks preserve exact cliffs delta`
    - **Intent:** verify rank-average tie handling path for cliffs delta.
    - **Expected outcome:** exact deterministic effect size `-0.28` with absolute tolerance `1e-12`.
  - `extreme imbalance keeps non-parametric path stable`
    - **Intent:** verify pairwise selection/effect robustness for very unbalanced group sizes with repeated ties.
    - **Expected outcome:** `Mann-Whitney U` is selected and deterministic effect size `0.032258064516129004` matches within `1e-12`.

## Distribution-fit native kernel fixtures

- `tests/fixtures/distribution_fit/native_kernel_edge_cases.json`
  - `normal with near-zero sigma`
    - **Intent:** stress AD/KS kernels with steep normal CDF slope.
    - **Expected outcome:** native AD/KS statistics match Python reference within `1e-10` absolute tolerance.
  - `gamma shape near exponential boundary`
    - **Intent:** stress gamma CDF near shape=1 transition.
    - **Expected outcome:** native AD/KS statistics match Python reference within `1e-10` absolute tolerance.
