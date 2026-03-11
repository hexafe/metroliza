# Screen-by-Screen Corrective Review

Status: **Active planning input**

## Corrective Review Delta

Compared with the prior archived cycle, the corrective review confirms that most direction remains valid, but must-fix execution details must remain explicit and testable throughout implementation. The sections below preserve current/target UX guidance and include non-negotiable must-fix scope exactly as specified.

## 1) Main Window

### Current issues

- Landing context is unclear for first-time users.
- Competing actions appear visually equivalent, causing decision friction.
- Status/progress signals are either buried or inconsistent.

### Target UX

- Present one obvious primary path from the landing screen.
- Separate “start workflow” actions from lower-priority utilities.
- Keep global status messaging persistent and predictable.

### Must-fix items (exact)

- Audit current entry-page information hierarchy and navigation cues.
- Redesign title + primary CTA placement to establish shared screen pattern.
- Add/standardize global status area for loading, success, and error feedback.
- Validate keyboard/focus order and first-load clarity.

## 2) Characteristic Mapping

### Current issues

- Mapping terminology is inconsistent and sometimes domain-jargon-heavy.
- Unmapped/conflict states are not always obvious until late.
- Batch operations lack clear discoverability.

### Target UX

- Make source ↔ target relationship explicit in every row/control.
- Surface mapping completeness and conflicts continuously.
- Support fast, safe bulk assignment with visible impact.

### Must-fix items (exact)

- Inventory confusing labels and ambiguous control names.
- Redesign mapping table/form layout for scanability.
- Add clear inline validation for unmapped/duplicate/conflicting values.
- Improve helper copy for batch actions and edge-case handling.

## 3) Export

### Current issues

- Users can attempt export without understanding preconditions.
- Option density makes format/destination choices feel risky.
- Success/failure results do not always provide actionable context.

### Target UX

- Add explicit readiness/preflight panel before export action.
- Use grouped option sections with defaults and concise explanations.
- Provide post-run summary with links or direct navigation to output details.

### Must-fix items (exact)

- Rework export preflight section (readiness checks + missing requirements).
- Group output options into logical sections with defaults.
- Improve confirmation and post-export summary messaging.
- Add visible troubleshooting guidance for common export failures.

## 4) Grouping

### Current issues

- Group operations are powerful but not always predictable.
- High-risk edits may be applied without sufficient preview context.
- Action discoverability varies by mode/state.

### Target UX

- Make intended grouping outcome previewable before apply.
- Improve operation affordances for create/merge/split/rename.
- Reduce accidental destructive actions with stronger confirmation UX.

### Must-fix items (exact)

- Improve discoverability of create/merge/split/rename actions.
- Add or refine preview state before group changes are applied.
- Update confirmation language for destructive group operations.
- Preserve selection context across multi-step grouping edits.

## 5) Filter

### Current issues

- Active filter criteria can be easy to miss.
- Compound filter behavior (AND/OR) is not always clear.
- Empty/no-result states feel like data absence rather than filter mismatch.

### Target UX

- Maintain persistent active-filter summary near data view.
- Make criteria composition explicit and editable in-place.
- Offer quick reset and “show all” pathways.

### Must-fix items (exact)

- Make active filters persistent and always visible.
- Improve add/remove/reset interactions for compound filters.
- Clarify operator semantics (AND/OR) in UI labels/helper text.
- Revise empty-state copy with quick recovery actions.

## 6) Modify DB

### Current issues

- Impact of DB actions may be under-communicated before execution.
- Confirmation patterns are inconsistent across operation types.
- Error/success states can be too terse for safe follow-up.

### Target UX

- Clearly classify operations by risk and required confirmation depth.
- Require deliberate acknowledgment for destructive operations.
- Present outcomes with audit-friendly details and next actions.

### Must-fix items (exact)

- Classify DB actions by risk level and align warning severity.
- Add impact previews before high-risk operations.
- Improve confirmation flow for destructive database changes.
- Ensure completion/error states include next-step guidance and audit hints.
