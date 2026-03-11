# UI Revamp Design System (Refined Baseline)

Status: **Active**  
Owner: UI revamp execution stream  
Last updated: 2026-03-11

This baseline is mandatory for all revamp phases. Deviations must be tracked in phase notes with mitigation and follow-up alignment.

## 1) Color System (Refined)

Use semantic tokens only.

- `color.bg.canvas`: `#F8FAFC`
- `color.bg.surface`: `#FFFFFF`
- `color.bg.subtle`: `#F1F5F9`
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

## 2) Spacing System (Refined)

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

## 3) Radius and Borders (Refined)

- `radius.sm`: 4px
- `radius.md`: 8px
- `radius.lg`: 12px
- Border width: 1px default, 2px focus/selected emphasis only.

## 4) Typography System (Refined)

- Font family: system sans stack
- `text.xs`: 12/16
- `text.sm`: 14/20
- `text.md`: 16/24
- `text.lg`: 20/28
- `text.xl`: 24/32
- Weights: 400 body/help, 500 labels/section headers, 600 page headers/key metrics.

## 5) Interaction System (Refined)

All interactive controls must visibly support:

- hover
- focus-visible
- pressed/active
- disabled

Rules:

- Focus uses `color.focus.ring` with no layout shift.
- Transition timing stays subtle (`<=150ms`) for standard controls.
- Destructive actions require explicit confirmation copy with impact scope.
- Empty/no-result states must include reason + recovery action.

## 6) Control Hierarchy

1. **Primary**: one per view region.
2. **Secondary**: safe alternatives.
3. **Tertiary/Text**: low-emphasis utility actions.
4. **Destructive**: reserved for irreversible actions.

## 7) Screen-Level Layout Rules

- Main Window: header -> workflow summary -> next-step CTA.
- Characteristic Mapping: source/target clarity + pinned coverage summary.
- Export: preflight -> options -> execution -> result summary.
- Grouping: operation bar + preview before apply.
- Filter: persistent active filters + reset control.
- Modify DB: risk-tiered sections + impact preview + explicit confirmation.
