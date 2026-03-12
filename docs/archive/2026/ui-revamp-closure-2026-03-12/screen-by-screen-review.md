# Screen-by-Screen UX Review

This review captures current issues and target-state UX direction for each relevant screen.

## 1) Main Window

### Current issues

- Landing context is unclear for first-time users.
- Competing actions appear visually equivalent, causing decision friction.
- Status/progress signals are either buried or inconsistent.

### Target UX

- Present one obvious primary path from the landing screen.
- Separate “start workflow” actions from lower-priority utilities.
- Keep global status messaging persistent and predictable.

### Wording updates

- Replace generic action labels (e.g., “Run”, “Process”) with intent-based verbs.
- Add concise page subtitle clarifying expected next step.

### Layout changes

- Standardize page scaffold: title + subtitle, primary CTA, contextual secondary actions.
- Reserve a consistent region for transient and persistent status messages.

### Helper text / tooltip opportunities

- Tooltip for each primary module entry describing when to use it.
- First-load helper text describing recommended workflow sequence.

---

## 2) Characteristic Mapping

### Current issues

- Mapping terminology is inconsistent and sometimes domain-jargon-heavy.
- Unmapped/conflict states are not always obvious until late.
- Batch operations lack clear discoverability.

### Target UX

- Make source ↔ target relationship explicit in every row/control.
- Surface mapping completeness and conflicts continuously.
- Support fast, safe bulk assignment with visible impact.

### Wording updates

- Harmonize labels for source fields, target fields, and mapping status.
- Rewrite error text to include corrective action (not just failure state).

### Layout changes

- Reorganize table columns by decision flow (input, proposed mapping, status, actions).
- Pin summary panel showing mapped/unmapped/conflict counts.

### Helper text / tooltip opportunities

- Inline helper for mapping rules/constraints.
- Tooltip for bulk actions with explicit scope and undo limitations.

---

## 3) Export

### Current issues

- Users can attempt export without understanding preconditions.
- Option density makes format/destination choices feel risky.
- Success/failure results do not always provide actionable context.

### Target UX

- Add explicit readiness/preflight panel before export action.
- Use grouped option sections with defaults and concise explanations.
- Provide post-run summary with links or direct navigation to output details.

### Wording updates

- Replace vague labels with concrete destination/format wording.
- Improve failure copy to include likely cause + immediate next step.

### Layout changes

- Sequence screen vertically: preflight → options → confirm/export → result summary.
- Keep risky options visually separated from default path.

### Helper text / tooltip opportunities

- Tooltip on each export format describing intended downstream use.
- Inline “why blocked” explanations for disabled export action.

---

## 4) Grouping

### Current issues

- Group operations are powerful but not always predictable.
- High-risk edits may be applied without sufficient preview context.
- Action discoverability varies by mode/state.

### Target UX

- Make intended grouping outcome previewable before apply.
- Improve operation affordances for create/merge/split/rename.
- Reduce accidental destructive actions with stronger confirmation UX.

### Wording updates

- Clarify operation names and side effects in action labels.
- Add explicit confirmation copy that describes what will change.

### Layout changes

- Place preview panel adjacent to action area for immediate feedback.
- Keep selected items and target group context visible while editing.

### Helper text / tooltip opportunities

- Contextual helper for merge/split rules and edge cases.
- Tooltips on disabled actions explaining unmet prerequisites.

---

## 5) Filter

### Current issues

- Active filter criteria can be easy to miss.
- Compound filter behavior (AND/OR) is not always clear.
- Empty/no-result states feel like data absence rather than filter mismatch.

### Target UX

- Maintain persistent active-filter summary near data view.
- Make criteria composition explicit and editable in-place.
- Offer quick reset and “show all” pathways.

### Wording updates

- Standardize operator naming and criterion labels.
- Rewrite no-result copy to explain likely cause and fixes.

### Layout changes

- Show applied filter chips/tokens in a stable top region.
- Separate “add criteria” controls from “apply/reset” controls.

### Helper text / tooltip opportunities

- Inline examples for common compound queries.
- Tooltip clarifying operator semantics and precedence.

---

## 6) Modify DB

### Current issues

- Impact of DB actions may be under-communicated before execution.
- Confirmation patterns are inconsistent across operation types.
- Error/success states can be too terse for safe follow-up.

### Target UX

- Clearly classify operations by risk and required confirmation depth.
- Require deliberate acknowledgment for destructive operations.
- Present outcomes with audit-friendly details and next actions.

### Wording updates

- Use explicit verbs for irreversible actions (delete/overwrite/reset).
- Expand confirmation copy with scope (records/tables affected).

### Layout changes

- Add impact preview panel before high-risk submit actions.
- Align action placement so destructive controls are visually distinct.

### Helper text / tooltip opportunities

- Helper copy describing rollback/backup expectations.
- Tooltip on risky operations linking to operational guidance.

---

## Cross-Screen Wording and Interaction Notes

- Keep terminology map for repeated concepts (status, mapping state, confirmation states).
- Standardize button labels for primary/secondary/destructive actions.
- Define message templates for validation errors, blocking conditions, and completion summaries.
- Ensure helper text style is concise, action-oriented, and consistent in voice.
