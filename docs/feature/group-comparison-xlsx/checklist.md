# Group Comparison XLSX legacy checklist

## Legacy note
This file is preserved as a historical snapshot. Statements below may describe the pre-consolidation Group Comparison framing and should not override the current Group Analysis documentation.

## Metadata
- **Owner:** Data Export & Analysis Team
- **Status:** Superseded / legacy reference
- **Scope:** Historical validation ideas from the earlier Group Comparison XLSX framing.
- **Exit criteria:** Preserved as legacy reference; active validation now belongs to Group Analysis docs.

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
