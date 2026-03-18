# Group Comparison XLSX implementation plan

## Metadata
- **Owner:** Data Export & Analysis Team
- **Status:** Active (draft)
- **Scope:** Define the phased implementation approach for a dedicated Group Comparison XLSX workstream.
- **Exit criteria:** The scoped phases are either implemented or explicitly deferred with rationale.

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
