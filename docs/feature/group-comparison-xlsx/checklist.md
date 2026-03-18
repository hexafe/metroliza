# Group Comparison XLSX checklist

## Metadata
- **Owner:** Data Export & Analysis Team
- **Status:** Active (draft)
- **Scope:** Final validation gates for correctness, usability, and release readiness.
- **Exit criteria:** All required items are checked or have documented exceptions with owner and follow-up.

## Stats correctness
- [ ] Comparison outputs match the approved statistical definitions.
- [ ] Missing, zero-count, and sparse-data cases are handled correctly.
- [ ] Rounding and display rules do not hide materially different values.
- [ ] Any suppressed or unavailable calculations are clearly labeled.

## Worksheet UX
- [ ] Sheet names are clear and stable.
- [ ] Headers, panes, widths, and summary sections support quick interpretation.
- [ ] Explanatory notes/caveats are present where users need them.
- [ ] Navigation between data, summaries, and charts is straightforward.

## Chart readability
- [ ] Series/category labels are readable.
- [ ] Color usage distinguishes groups clearly.
- [ ] Axis scales and legends are appropriate for the metric shown.
- [ ] Unreadable chart scenarios have a documented fallback behavior.

## Tests/docs
- [ ] Unit tests cover core statistical logic.
- [ ] Workbook structure/output tests cover the expected sheet contract.
- [ ] Relevant docs are updated, including active index links if needed.
- [ ] Any known limitations are documented.

## Release readiness
- [ ] Validation evidence has been captured.
- [ ] Regressions against existing export flows have been checked.
- [ ] Deferred items are explicitly tracked.
- [ ] Temporary docs are ready for archive or handoff once the feature ships.
