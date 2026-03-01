# Data Structure Decision Record (V2 Parsing Schema)

## Objective
Choose a V2 data structure approach that balances:
- **performance** (low CPU/memory overhead for large report batches),
- **maintainability** (clear contracts, easy onboarding, safe refactors),
- **scalability** (many templates/plugins, multilingual suppliers, future schema evolution).

## Evaluated options

| Option | Runtime performance | Maintainability | Scalability | Notes |
|---|---|---|---|---|
| `dict`/`list` only (status quo style) | High raw speed, low allocation overhead | Low (implicit keys/order assumptions) | Low-medium (drift risk across plugins) | Fast but fragile over time. |
| `TypedDict` only | Similar to dict/list at runtime | Medium (better static docs) | Medium | No runtime validation; still easy to drift semantically. |
| `dataclass` only | High (near-stdlib baseline) | High (explicit fields, defaults, helpers) | High | Good core model; needs boundary shape convention. |
| `dataclass` + `TypedDict` boundary | High | **Very high** | **Very high** | Best balance: typed domain + stable serialized contracts. |
| `pydantic` models everywhere | Medium (validation cost per object) | High | High | Strong validation, but heavier runtime/dependency footprint. |
| Columnar (Arrow/Polars-first) | Very high in vectorized analytics | Medium | High for analytics workloads | Overkill for parser domain model; better as downstream export stage. |

## Recommendation (industry-standard hybrid)
Use **`dataclass` domain models + `TypedDict` boundary contracts** as default architecture.

### Why this is the best fit now
1. **Performance:** dataclasses are lightweight and fast enough for per-row object modeling without introducing heavy runtime validation overhead.
2. **Maintainability:** explicit field names and optional helper methods reduce positional/index bugs.
3. **Scalability:** supports many plugins/templates while keeping a single canonical in-memory model.
4. **Migration safety:** TypedDict boundaries allow stable fixture snapshots and API-like contracts for adapters/tests.
5. **Dependency discipline:** keeps core parser path stdlib-first while allowing optional stricter validation later.

## Target implementation pattern

### Internal canonical model (dataclass)
- `ParseMetaV2`
- `MeasurementV2`
- `MeasurementBlockV2`
- `CMMReportV2`

### Boundary contracts (TypedDict)
- `ParseMetaV2Dict`
- `MeasurementV2Dict`
- `MeasurementBlockV2Dict`
- `CMMReportV2Dict`

### Adapter boundaries
- `legacy -> v2 dataclass`
- `v2 dataclass -> legacy`
- `v2 dataclass <-> v2 typeddict` for serialization/testing

## Performance guardrails
- Avoid dual long-lived copies: keep V2 as source of truth, derive legacy lazily at boundary.
- Reuse normalized token buffers where possible.
- Keep object creation linear and single-pass per file.
- Track:
  - p50/p95 parse latency,
  - peak memory,
  - adapter overhead ratio.

## Evolution path
- Phase 1–2: dataclass + TypedDict only.
- Phase 3+: optional targeted runtime validation (manual checks or selective pydantic) for high-risk plugins.
- Phase 4+: optional columnar transform at analytics/export stage, not parser core.

## Decision status
- **Proposed default for implementation planning:** Accepted, pending architecture sign-off at Pass 1.
