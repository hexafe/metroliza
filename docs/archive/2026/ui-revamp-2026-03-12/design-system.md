# UI Revamp Design System (Refined Baseline)

Status: **Active**  
Owner: UI revamp execution stream  
Last updated: 2026-03-12

This baseline is mandatory for all revamp phases. Deviations must be tracked in phase notes with mitigation and follow-up alignment.

## 1) Research-Driven Dark Theme Decision

Graphite/dark-gray surfaces are the required dark-theme base; pure black is explicitly rejected.

Why graphite over pure black:
- **Hierarchy/depth:** near-black tiers create visible separation between app background, primary surfaces, and elevated surfaces without relying on heavy borders.
- **Visual comfort:** pure black (`#000000`) creates harsh contrast fatigue across long data-review sessions.
- **Readable emphasis:** text tiers and semantic states remain clearer on graphite ramps, especially helper/subtitle text.

## 2) Color Tokens (Requested Spec)

Use semantic tokens only; no one-off hardcoded colors.

### 2.1 Dark theme foundation tokens

- `color.bg.app`: `#121417` (app background)
- `color.bg.surface.primary`: `#1B1F24` (primary surface)
- `color.bg.surface.secondary`: `#232933` (secondary surface)
- `color.bg.surface.elevated`: `#2A3140` (elevated surface, dialogs/popovers)
- `color.bg.input`: `#20262F` (input background)
- `color.border.default`: `#364152`
- `color.border.strong`: `#4B5565`

### 2.2 Text tiers

- `color.text.primary`: `#F3F4F6`
- `color.text.secondary`: `#D1D5DB`
- `color.text.tertiary`: `#9CA3AF`
- `color.text.disabled`: `#6B7280`

### 2.3 Accent states

- `color.accent.primary`: `#3B82F6`
- `color.accent.hover`: `#2563EB`
- `color.accent.pressed`: `#1D4ED8`
- `color.accent.subtle`: `#1E3A8A33`

### 2.4 Semantic colors

- `color.semantic.success`: `#22C55E`
- `color.semantic.warning`: `#F59E0B`
- `color.semantic.error`: `#EF4444`
- `color.semantic.info`: `#38BDF8`

### 2.5 Focus ring

- `color.focus.ring`: `#93C5FD`

## 3) Contrast and Readability Standards

Minimum readability requirements (dark theme):
- Helper text: use `color.text.tertiary`, target **>= 4.5:1** on `color.bg.surface.primary`.
- Subtitles/section descriptors: use `color.text.secondary`, target **>= 4.5:1**.
- Body copy: use `color.text.primary`, target **>= 7:1** preferred.
- Empty-state copy: title `color.text.secondary`, supporting note `color.text.tertiary`, never below **4.5:1**.
- Notes (non-critical contextual info): `color.text.tertiary`; do not drop to disabled tone unless actually disabled.

## 4) Global Rules: Informational Panels vs Clickable Controls

Informational panels (status summaries, explanations, passive metrics):
- No hover treatment.
- No pressed/active treatment.
- No pointer cursor.
- May use subtle border/elevation only to communicate grouping.

Clickable controls (buttons, links, chips, selectable rows):
- Must show hover, focus-visible, pressed, and disabled states.
- Must keep hit area and visual affordance consistent with role.

## 5) Accent Strategy

- Blue is the only primary action accent.
- Green is reserved for success/positive semantic feedback.
- Violet is **not** used as a primary accent or primary CTA fill.

## 6) Spacing System

8px base scale:

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

## 7) Radius, Borders, Typography

- `radius.sm`: 4px
- `radius.md`: 8px
- `radius.lg`: 12px
- Border width: 1px default, 2px focus/selected emphasis only.
- Font family: system sans stack.
- `text.xs`: 12/16, `text.sm`: 14/20, `text.md`: 16/24, `text.lg`: 20/28, `text.xl`: 24/32.
- Weights: 400 body/help, 500 labels/section headers, 600 page headers/key metrics.

## 8) Completion Criteria (Required Consistency Pass)

Completion requires a final consistency pass validating:
- token usage consistency,
- border/spacing/text hierarchy consistency,
- button hierarchy consistency,
- hover/focus behavior consistency.
