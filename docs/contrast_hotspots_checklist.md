# Dark theme contrast hotspots checklist

Resolved contrast hotspots in the shared UI token layer (`modules/ui_theme_tokens.py`):

- [x] **Helper/caption copy** (`COLOR_TEXT_HELPER` via `COLOR_TEXT_MUTED`) brightened for improved readability on dark panels.
- [x] **Placeholder text** remains mapped to helper token and now benefits from the same contrast increase.
- [x] **Disabled text** (`COLOR_TEXT_DISABLED`) increased to remain clearly legible while still visually subordinate to body text.
- [x] **Low-emphasis borders** (`COLOR_BORDER_DEFAULT`) strengthened to better define controls and panel edges on graphite backgrounds.
- [x] **Strong borders** (`COLOR_BORDER_STRONG`) increased to keep elevated/info surfaces and disabled controls distinguishable.
- [x] **Subtle active/selection surface** (`COLOR_ACCENT_SUBTLE`) opacity increased so hover/active/checked states are easier to differentiate in dark mode.
- [x] **Disabled controls** (buttons, inputs, progress bars) remapped to use stronger disabled borders with a darker panel fill for clearer non-interactive state differentiation.
- [x] **Info panels vs controls** preserved with separate backgrounds and stronger borders (`info_panel_style` vs `input_style`) to maintain hierarchy without adding visual noise.
