# Rust Acceleration Scope Decision Record

## Objective
Define when introducing Rust is justified, where it is currently out of scope, and what evidence is required before any Python path is promoted to native-default mode.

## Rust is justified when all of the following are true
1. **Compute-bound kernel**: the target is a pure (or effectively pure) function dominated by large-`N` loops and CPU time.
2. **Stable contract**: input/output types and semantics are stable enough to freeze at the boundary.
3. **Measurable outcome**: there is a declared speedup target and a parity test plan before implementation starts.

## Current non-candidates (explicitly out of scope)
- Chart rendering / UI flows.
- Worksheet I/O-heavy code paths.

These paths are typically latency- and integration-bound rather than CPU-kernel-bound, so Rust is not the primary lever today.

## Current candidate kernels
- Bootstrap CI compute kernels.
- AD Monte Carlo kernels.
- Large-scale coercion kernels.

These are expected to be loop-heavy and computationally dominant, making them suitable for targeted native acceleration.

## Promotion gate for native-default mode (mandatory)
A new Rust-backed path **must not** become native-default until both are demonstrated:
1. **Benchmark delta evidence**: reproducible benchmark results showing the agreed speedup target (or better) relative to Python baseline.
2. **Parity evidence**: automated parity tests proving output equivalence (within documented tolerances, if applicable) across representative and edge-case inputs.

If either benchmark delta or parity evidence is missing, the Python path remains the default.

## Decision status
- **Accepted** for roadmap governance and implementation triage.
