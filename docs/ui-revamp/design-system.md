# UI Revamp Design System (Locked Baseline)

Status: **Active**  
Owner: UI revamp execution stream  
Last updated: 2026-03-11

This document is the implementation baseline for all UI revamp screens. Any deviation requires an explicit note in the phase tracker and a follow-up consistency pass.

## 1) Visual Tokens

### 1.1 Color tokens

Use semantic tokens in implementation. Do not hardcode one-off colors per screen.

- `color.bg.canvas`: `#F8FAFC` (app background)
- `color.bg.surface`: `#FFFFFF` (cards, modals, panels)
- `color.bg.subtle`: `#F1F5F9` (secondary section backgrounds)
- `color.border.default`: `#CBD5E1`
- `color.border.strong`: `#94A3B8`
- `color.text.primary`: `#0F172A`
- `color.text.secondary`: `#475569`
- `color.text.muted`: `#64748B`
- `color.action.primary`: `#2563EB`
- `color.action.primaryHover`: `#1D4ED8`
- `color.action.primaryPressed`: `#1E40AF`
- `color.action.secondaryBg`: `#EFF6FF`
- `color.success`: `#15803D`
- `color.warning`: `#B45309`
- `color.error`: `#B91C1C`
- `color.info`: `#0369A1`
- `color.focus.ring`: `#2563EB`

### 1.2 Spacing scale

Use an 8px base system.

- `space.0`: 0
- `space.1`: 4px
- `space.2`: 8px
- `space.3`: 12px
- `space.4`: 16px
- `space.5`: 20px
- `space.6`: 24px
- `space.8`: 32px
- `space.10`: 40px
- `space.12`: 48px

### 1.3 Radii, borders, and shadows

- Radius: `radius.sm` 4px, `radius.md` 8px, `radius.lg` 12px
- Border width: 1px default, 2px for focus/selected emphasis only
- Shadow:
  - `shadow.sm`: subtle elevation for cards (`0 1px 2px rgba(15,23,42,0.06)`)
  - `shadow.md`: elevated overlays (`0 6px 18px rgba(15,23,42,0.12)`)

### 1.4 Typography

- Font family: system sans stack
- Type scale:
  - `text.xs`: 12px / 16px
  - `text.sm`: 14px / 20px
  - `text.md`: 16px / 24px
  - `text.lg`: 20px / 28px
  - `text.xl`: 24px / 32px
- Weight:
  - Regular 400 for body/help
  - Medium 500 for labels and section headers
  - Semibold 600 for page headers and key metrics

## 2) Component Rules

### 2.1 Button hierarchy (locked)

1. **Primary button**
   - Exactly one primary action per view region (page header or modal footer).
   - Filled with `color.action.primary`; white text.
2. **Secondary button**
   - Used for alternate safe actions.
   - Tinted/outlined style; never visually stronger than primary.
3. **Tertiary button / text button**
   - Low-emphasis actions like “Learn more”, “Cancel filter chip”.
4. **Destructive button**
   - Use `color.error` only for irreversible actions.
   - Requires confirmation pattern for high-risk actions.

Placement:
- Primary action is right-most in horizontal button groups.
- Cancel/back actions are left of primary and secondary emphasis.

### 2.2 Cards and panels

- Use cards to group related decisions; avoid nested cards deeper than one level.
- Card padding: `space.4` minimum.
- Card header includes title + optional helper line.
- Use panel separators (`space.6` vertical spacing) before introducing a new concern.
- If a section has a primary action, place it in card footer aligned with the app-level hierarchy.

### 2.3 Inputs and state matrix

Input rules:
- Every input has a visible label.
- Helper text appears below input before validation text.
- Required fields marked consistently (`*` in label + required helper summary at section level).

State matrix:

| State | Border | Text/Message | Icon | Behavior |
|---|---|---|---|---|
| Default | `color.border.default` | Optional helper (muted) | None | Normal interaction |
| Hover | `color.border.strong` | No change | Optional affordance icon | Pointer affordance only |
| Focus | 2px ring `color.focus.ring` + default border | No change | None | Keyboard visible, no layout shift |
| Filled valid | `color.border.default` | Optional success hint | Optional success icon | No disruptive animation |
| Warning | `color.warning` border/accent | Warning text under field | Warning icon optional | Allow continue if non-blocking |
| Error | `color.error` border/accent | Error text with fix guidance | Error icon optional | Block submit when field is required |
| Disabled | low-contrast border/bg | Muted text | None | No hover/press state |

### 2.4 Tables and lists

- Sticky header for long data tables where feasible.
- Row height minimum: 40px.
- Numeric values right-aligned; labels left-aligned.
- Sorting affordance visible on sortable headers.
- Selected row state must be visible without relying on color alone.
- Bulk actions appear only when row selection exists.
- Empty tables must render the empty-state component (see section 2.5).

### 2.5 Helper text and empty states

Helper text:
- Keep concise: what this control changes + safe defaults.
- Use sentence case and action-oriented language.
- Avoid repeating label text in helper line.

Empty states:
- Must include:
  1) explicit reason for no content,
  2) one primary recovery action,
  3) optional secondary doc/help link.
- No blank data regions without explanatory text.

### 2.6 Interaction states (global)

All clickable controls must support and visually differentiate:
- Hover
- Focus-visible
- Pressed/active
- Disabled

Motion:
- Keep transitions subtle and under 150ms for standard controls.
- No motion for critical error/safety messaging.

## 3) Per-Screen Layout Rules (Locked)

## 3.1 Main window

- Structure: global header → workflow summary cards → next-step primary CTA.
- Show status/health banner near top when blocking or important warnings exist.
- Keep first-load guidance above fold.

## 3.2 Characteristic matching

- Two-column pattern preferred: source attributes (left), mapping target/details (right).
- Coverage/progress summary pinned above table.
- Validation messages remain near affected rows and in a top summary strip.

## 3.3 Export

- Preflight checks first (readiness state), then output options, then execution block.
- Primary export action remains disabled until required preconditions pass.
- Post-run summary panel appears in-place with artifact location and warnings.

## 3.4 Grouping

- Top action bar: create/merge/split/rename grouped by operation type.
- Preview area must be visible before confirm for destructive or high-impact changes.
- Preserve selection context between edits unless user explicitly resets.

## 3.5 Filter

- Active filter chips/pills always visible at top of results region.
- Composer section for adding criteria should not hide active logic (AND/OR clarity).
- Include one-click reset all control near chips.

## 3.6 Modify DB

- Risk-tier sections: low-risk operations separated from destructive operations.
- Destructive operations require impact preview + explicit confirmation step.
- Completion panel includes audit guidance and recommended next action.

## 4) Enforcement and Change Control

- These rules are mandatory for all revamp phases.
- If implementation constraints require divergence, record:
  - the reason,
  - affected screen/component,
  - temporary mitigation,
  - target phase for alignment.
- Run a final consistency pass after screen implementations complete.
