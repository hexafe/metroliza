# Group Comparison XLSX legacy implementation plan

## Legacy note
This file is preserved as a historical snapshot. Statements below may describe the pre-consolidation Group Comparison framing and should not override the current Group Analysis documentation.

## Metadata
- **Owner:** Data Export & Analysis Team
- **Status:** Superseded / legacy reference
- **Scope:** Historical phased plan from the earlier Group Comparison XLSX workstream.
- **Exit criteria:** Retained as historical planning context after the move to Group Analysis as the canonical surface.

## Phased work plan

### Phase 0 — Audit and requirements lock
- Confirm the exact workbook outputs, statistical rules, and chart requirements.
- Identify the current export entry points, aggregation helpers, workbook layout helpers, and chart payload builders that will be affected.
- Capture representative fixtures covering common, sparse, and edge-case group distributions.

### Phase 1 — Statistics and workbook contract
- Define the canonical output schema for each worksheet.
- Lock column ordering, label conventions, rounding/display rules, and handling for missing or suppressed values.
- Separate pure statistical computation from XLSX presentation concerns wherever possible.

### Phase 2 — Worksheet implementation
- Implement or adapt workbook-generation logic for the required comparison sheets.
- Add worksheet UX improvements such as stable titles, frozen panes, consistent widths, summary placement, and explanatory notes.
- Ensure output degrades cleanly when some requested comparisons cannot be computed.

### Phase 3 — Chart implementation and validation
- Add or refine chart payload generation for the supported comparison types.
- Validate chart readability under low-cardinality and high-cardinality scenarios.
- Document any fallback behavior for cases where charts would be misleading or unreadable.

### Phase 4 — Test, docs, and release hardening
- Add unit tests for stats/aggregation logic and structural tests for workbook output.
- Update user-facing documentation if workbook behavior changes.
- Complete the feature checklist and prepare archival/follow-up documentation.

## Architecture decisions
- Keep statistical computation in pure helper paths and keep XLSX formatting/layout logic in workbook-specific helpers.
- Prefer explicit workbook contracts over implicit sheet layouts so tests can assert stable structure.
- Treat chart generation as a downstream consumer of validated worksheet/statistical data rather than a separate source of truth.
- Preserve current export architecture boundaries documented in `docs/README.md` unless a concrete implementation blocker requires refactoring.


## Future extension hooks (deferred)
- Keep the first release focused on deterministic summary statistics and workbook presentation; do not add new anomaly-detection or ML pipelines in the current implementation.
- Add stable payload metadata hooks alongside existing chart/table summary payloads so future consumers can attach derived signals without changing worksheet contracts. Examples include per-comparison IDs, subgroup cardinality/context, metric families, and reserved fields for future `interestingness_score`, `ranking_reason`, or `discovery_flags` metadata.
- The most natural future insertion point for ranking/scoring logic is the Group Comparison summary section after core statistics are computed and before workbook summary rows or chart callouts are rendered. That keeps scoring as a downstream consumer of validated comparison outputs rather than a parallel source of truth.
- Future optional analysis modes can be layered onto that summary-stage hook, including hidden subgroup anomaly detection, clustering or mixture-model discovery, PCA or other multivariate separation views, and automated ranking of the most interesting group differences.
- If those follow-on modes are pursued later, prefer emitting explainable summary metadata and lightweight workbook annotations first, with heavier modeling kept behind explicit opt-in paths or offline analysis workflows.

## In scope now vs deferred

### In scope now
- Dedicated planning docs for audit, implementation sequencing, TODO tracking, and validation.
- Defining the expected statistics/workbook/chart contract for the first Group Comparison XLSX release.
- Identifying the minimum automated coverage needed to safely ship the feature.

### Deferred
- Broader exporter refactors unrelated to Group Comparison XLSX.
- New statistical methods that are not required for the first release.
- Non-essential workbook polish that does not affect correctness, readability, or release confidence.
- Long-term archival or permanent-documentation reshaping beyond the minimal index updates needed now.

## Risk notes
- Statistical correctness risk is the highest priority because incorrect comparison outputs can appear polished while still being wrong.
- XLSX layout regressions are easy to miss without structural tests and representative fixtures.
- Chart readability can degrade quickly with many groups or long labels, so fallback rules may be needed.
- If current export helpers mix calculation and presentation concerns, implementation scope may expand unless boundaries are enforced early.
