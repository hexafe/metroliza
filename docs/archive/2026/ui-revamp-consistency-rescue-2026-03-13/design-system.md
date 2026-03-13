# UI Revamp Design System — Graphite Dark (Rescue Baseline)

## 1) Central token system (single source of truth)

### Backgrounds
- `app_bg = #0B1220`
- `surface_1 = #111827`
- `surface_2 = #172033`
- `surface_3 = #1E293B`
- `input_bg = #0F172A`

### Borders
- `border_subtle = #334155`
- `border_strong = #475569`

### Text
- `text_primary = #F8FAFC`
- `text_secondary = #CBD5E1`
- `text_muted = #94A3B8`

### Accent
- `primary = #3B82F6`
- `primary_hover = #2563EB`
- `focus_ring = #60A5FA`

### Semantic
- `success = #22C55E`
- `warning = #F59E0B`
- `danger = #EF4444`

### Spacing
- `8 / 12 / 16 / 20 / 24 / 32`

### Radius
- `controls = 10px`
- `cards_panels = 12px`

## 2) Visual role separation (mandatory)

- **App shell**: uses `app_bg` only.
- **Section cards/panels**: `surface_1`/`surface_2` + subtle borders.
- **Informational panels**: static, no hover/pressed affordance, `surface_3` + stronger border.
- **Inputs**: `input_bg`, clear border/focus ring.
- **Buttons**: explicit clickable states (hover/focus/pressed/disabled).
- **Tables/lists**: integrated with same surfaces and border scale.
- **Helper text**: use `text_muted`, never near-invisible.

## 3) Contrast/readability standards

Priority targets for rescue:

- subtitles
- helper text
- section descriptions
- empty-state text
- pre-load status text
- note/example/info panels

Muted text must remain readable and secondary, never effectively hidden.
