"""Shared semantic UI tokens and reusable style builders for dialogs/screens.

Canonical dark graphite palette (design-system naming):
    color.bg.app: #121417
    color.bg.surface.primary: #1B1F24
    color.bg.surface.secondary: #232933
    color.bg.surface.elevated: #2A3140
    color.bg.input: #20262F
    color.text.primary: #F3F4F6
    color.text.secondary: #D1D5DB
    color.text.tertiary: #9CA3AF
    color.border.default: #364152
    color.border.strong: #4B5565
    color.accent.primary/hover/pressed: #3B82F6/#2563EB/#1D4ED8
    color.focus.ring: #93C5FD

Legacy token names are kept as aliases where possible to avoid broad breakage.
"""

import colorsys

BASE_ROW_BACKGROUND_FALLBACK = "#FFFFFF"
SELECTED_ROW_BACKGROUND_FALLBACK = "#5E88AD"
DEFAULT_GROUP_COLOR = BASE_ROW_BACKGROUND_FALLBACK

# Canonical graphite foundation tokens.
COLOR_BACKGROUND_APP = "#121417"
COLOR_BACKGROUND_PANEL = "#1B1F24"
COLOR_BACKGROUND_PANEL_MUTED = "#232933"
COLOR_BACKGROUND_PANEL_ELEVATED = "#2A3140"
COLOR_BACKGROUND_INPUT = "#20262F"
COLOR_TEXT_PRIMARY = "#F3F4F6"
COLOR_TEXT_SECONDARY = "#D1D5DB"
COLOR_TEXT_MUTED = "#9CA3AF"
COLOR_TEXT_DISABLED = "#6B7280"
COLOR_TEXT_HELPER = COLOR_TEXT_MUTED
COLOR_BORDER_DEFAULT = "#364152"
COLOR_BORDER_MUTED = COLOR_BORDER_DEFAULT
COLOR_BORDER_STRONG = "#4B5565"
COLOR_ACCENT_PRIMARY = "#3B82F6"
COLOR_ACCENT_HOVER = "#2563EB"
COLOR_ACCENT_PRESSED = "#1D4ED8"
COLOR_ACCENT_SUBTLE = "#1E3A8A33"
COLOR_ACCENT = COLOR_ACCENT_PRIMARY
COLOR_FOCUS_RING = "#93C5FD"
COLOR_SELECTION = COLOR_ACCENT_HOVER
COLOR_SURFACE_HOVER = COLOR_BACKGROUND_PANEL_ELEVATED
COLOR_SURFACE_ACTIVE = COLOR_ACCENT_SUBTLE
COLOR_TEXT_ON_ACCENT = "#FFFFFF"
COLOR_STATUS_SUCCESS = "#22C55E"
COLOR_STATUS_WARNING = "#F59E0B"
COLOR_STATUS_DANGER = "#EF4444"
COLOR_STATUS_DANGER_HOVER = "#DC2626"
COLOR_STATUS_DANGER_PRESSED = "#B91C1C"
COLOR_STATUS_INFO = "#38BDF8"
COLOR_STATUS_SUCCESS_BG = "#22C55E26"
COLOR_STATUS_WARNING_BG = "#F59E0B26"
COLOR_STATUS_DANGER_BG = "#EF444426"
COLOR_STATUS_INFO_BG = "#38BDF826"

SPACE_4 = 4
SPACE_8 = 8
SPACE_12 = 12
SPACE_16 = 16
SPACE_20 = 20
SPACE_24 = 24
SPACE_32 = 32

RADIUS_8 = 8
RADIUS_10 = 10
RADIUS_12 = 12
RADIUS_14 = 14

CONTROL_HEIGHT = 34

TYPE_PAGE_TITLE = "font-size: 16px; font-weight: 700;"
TYPE_DASHBOARD_PAGE_TITLE = "font-size: 23px; font-weight: 600;"
TYPE_SECTION_TITLE = "font-size: 16px; font-weight: 600;"
TYPE_CARD_TITLE = "font-size: 16px; font-weight: 600;"
TYPE_BODY = "font-size: 12px;"
TYPE_HELPER = "font-size: 11px;"
TYPE_TABLE = "font-size: 12px;"

BUTTON_INTERACTION = {
    'focus_border_width': 2,
    'default_border_width': 1,
}

BUTTON_VARIANTS = {
    'primary': {
        'text': COLOR_TEXT_ON_ACCENT,
        'background': COLOR_ACCENT_PRIMARY,
        'border': COLOR_ACCENT_PRIMARY,
        'hover_background': COLOR_ACCENT_HOVER,
        'hover_border': COLOR_ACCENT_HOVER,
        'pressed_background': COLOR_ACCENT_PRESSED,
        'pressed_border': COLOR_ACCENT_PRESSED,
    },
    'secondary': {
        'text': COLOR_TEXT_SECONDARY,
        'background': COLOR_BACKGROUND_PANEL,
        'border': COLOR_BORDER_DEFAULT,
        'hover_background': COLOR_SURFACE_HOVER,
        'hover_border': COLOR_ACCENT_PRIMARY,
        'pressed_background': COLOR_SURFACE_ACTIVE,
        'pressed_border': COLOR_ACCENT_HOVER,
    },
    'tertiary': {
        'text': COLOR_TEXT_SECONDARY,
        'background': COLOR_BACKGROUND_PANEL_MUTED,
        'border': COLOR_BORDER_MUTED,
        'hover_background': COLOR_SURFACE_HOVER,
        'hover_border': COLOR_ACCENT_HOVER,
        'pressed_background': COLOR_SURFACE_ACTIVE,
        'pressed_border': COLOR_ACCENT_PRESSED,
    },
    'danger': {
        'text': COLOR_TEXT_ON_ACCENT,
        'background': COLOR_STATUS_DANGER,
        'border': COLOR_STATUS_DANGER,
        'hover_background': COLOR_STATUS_DANGER_HOVER,
        'hover_border': COLOR_STATUS_DANGER_HOVER,
        'pressed_background': COLOR_STATUS_DANGER_PRESSED,
        'pressed_border': COLOR_STATUS_DANGER_PRESSED,
    },
}
BASE_GROUP_PALETTE = (
    "#FDE2E4",
    "#E2ECE9",
    "#E8E8FF",
    "#FFF1E6",
    "#E3F2FD",
    "#E7F6E7",
    "#F9E2FF",
    "#FFF9C4",
)


def _parse_hex_color(value):
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if len(stripped) != 7 or not stripped.startswith('#'):
        return None
    try:
        red = int(stripped[1:3], 16)
        green = int(stripped[3:5], 16)
        blue = int(stripped[5:7], 16)
    except ValueError:
        return None
    return red, green, blue


def _to_hex(red, green, blue):
    return f"#{int(red):02X}{int(green):02X}{int(blue):02X}"


def normalize_hex_color(color_hex, fallback=BASE_ROW_BACKGROUND_FALLBACK):
    """Return normalized #RRGGBB color (uppercase), or fallback when invalid."""
    parsed = _parse_hex_color(color_hex)
    if parsed is not None:
        return _to_hex(*parsed)
    fallback_parsed = _parse_hex_color(fallback)
    if fallback_parsed is not None:
        return _to_hex(*fallback_parsed)
    return BASE_ROW_BACKGROUND_FALLBACK


def ideal_text_color(background_hex):
    """Return high-contrast text token (#000000 or #FFFFFF)."""
    parsed = _parse_hex_color(background_hex)
    if parsed is None:
        return "#000000"
    red, green, blue = parsed
    luminance = ((0.299 * red) + (0.587 * green) + (0.114 * blue)) / 255
    return "#000000" if luminance > 0.6 else "#FFFFFF"


def resolve_base_row_background(base_hex=None):
    return normalize_hex_color(base_hex, fallback=BASE_ROW_BACKGROUND_FALLBACK)


def selected_row_background_override(highlight_hex=None):
    normalized = normalize_hex_color(highlight_hex, fallback=SELECTED_ROW_BACKGROUND_FALLBACK)
    red, green, blue = _parse_hex_color(normalized)
    hue, lightness, saturation = colorsys.rgb_to_hls(red / 255.0, green / 255.0, blue / 255.0)
    softened_lightness = min(0.62, max(0.42, lightness))
    softened_saturation = min(saturation, 0.45)
    soft_red, soft_green, soft_blue = colorsys.hls_to_rgb(hue, softened_lightness, softened_saturation)
    return _to_hex(round(soft_red * 255), round(soft_green * 255), round(soft_blue * 255))


def selected_text_color(selected_background_hex):
    return ideal_text_color(selected_background_hex)


def is_dark_mode_base(base_hex):
    return ideal_text_color(base_hex) == "#FFFFFF"


def clamp_group_color_for_theme(color_hex, dark_mode=False):
    color = _parse_hex_color(color_hex)
    if color is None:
        return normalize_hex_color(color_hex)
    if not dark_mode:
        return _to_hex(*color)

    red, green, blue = color
    gray = (red + green + blue) / 3

    def _channel(value):
        saturated = gray + ((value - gray) * 1.25)
        darkened = int(saturated * 0.7)
        return max(70, min(185, darkened))

    return _to_hex(_channel(red), _channel(green), _channel(blue))


def themed_group_palette(base_palette=None, dark_mode=False):
    colors = base_palette if base_palette is not None else BASE_GROUP_PALETTE
    return [clamp_group_color_for_theme(color, dark_mode=dark_mode) for color in colors]


def generate_group_color(seed, dark_mode=False):
    hue = (int(seed) * 47) % 360
    red, green, blue = colorsys.hls_to_rgb(hue / 360.0, 225 / 255.0, 110 / 255.0)
    generated = _to_hex(round(red * 255), round(green * 255), round(blue * 255))
    return clamp_group_color_for_theme(generated, dark_mode=dark_mode)


def normalize_group_display_color(color_hex, dark_mode=False, fallback=DEFAULT_GROUP_COLOR):
    normalized = normalize_hex_color(color_hex, fallback=fallback)
    return clamp_group_color_for_theme(normalized, dark_mode=dark_mode)


def typography_style(preset, color=None):
    presets = {
        'page': TYPE_PAGE_TITLE,
        'dashboard_page': TYPE_DASHBOARD_PAGE_TITLE,
        'section': TYPE_SECTION_TITLE,
        'card': TYPE_CARD_TITLE,
        'body': TYPE_BODY,
        'helper': TYPE_HELPER,
        'table': TYPE_TABLE,
    }
    style = presets.get(preset, TYPE_BODY)
    resolved_color = color if color is not None else COLOR_TEXT_PRIMARY
    return f"{style} color: {resolved_color};"


def button_style(variant='secondary'):
    colors = BUTTON_VARIANTS.get(variant, BUTTON_VARIANTS['secondary'])
    return (
        "QPushButton {"
        f" min-height: {CONTROL_HEIGHT}px;"
        f" padding: {SPACE_8}px {SPACE_12}px;"
        f" border: {BUTTON_INTERACTION['default_border_width']}px solid {colors['border']};"
        f" border-radius: {RADIUS_10}px;"
        f" background-color: {colors['background']};"
        f" color: {colors['text']};"
        "}"
        "QPushButton:hover {"
        f" border: {BUTTON_INTERACTION['default_border_width']}px solid {colors['hover_border']};"
        f" background-color: {colors['hover_background']};"
        "}"
        "QPushButton:focus {"
        f" border: {BUTTON_INTERACTION['focus_border_width']}px solid {COLOR_FOCUS_RING};"
        " outline: none;"
        f" background-color: {colors['hover_background']};"
        "}"
        "QPushButton:pressed {"
        f" border: {BUTTON_INTERACTION['default_border_width']}px solid {colors['pressed_border']};"
        f" background-color: {colors['pressed_background']};"
        "}"
        "QPushButton:disabled {"
        f" border: {BUTTON_INTERACTION['default_border_width']}px solid {COLOR_BORDER_MUTED};"
        f" background-color: {COLOR_BACKGROUND_PANEL_MUTED};"
        f" color: {COLOR_TEXT_DISABLED};"
        "}"
    )


def card_button_style(variant='secondary'):
    colors = BUTTON_VARIANTS.get(variant, BUTTON_VARIANTS['secondary'])
    return (
        "QPushButton {"
        f" min-height: {CONTROL_HEIGHT}px;"
        f" padding: {SPACE_8}px {SPACE_12}px;"
        f" border: {BUTTON_INTERACTION['default_border_width']}px solid {colors['border']};"
        f" border-radius: {RADIUS_12}px;"
        f" background-color: {colors['background']};"
        f" color: {colors['text']};"
        " text-align: left;"
        "}"
        "QPushButton:hover {"
        f" border: {BUTTON_INTERACTION['default_border_width']}px solid {colors['hover_border']};"
        f" background-color: {colors['hover_background']};"
        "}"
        "QPushButton:pressed {"
        f" border: {BUTTON_INTERACTION['default_border_width']}px solid {colors['pressed_border']};"
        f" background-color: {colors['pressed_background']};"
        "}"
        "QPushButton:focus {"
        f" border: {BUTTON_INTERACTION['focus_border_width']}px solid {COLOR_FOCUS_RING};"
        " outline: none;"
        f" background-color: {colors['hover_background']};"
        "}"
        "QPushButton:focus-visible {"
        f" border: {BUTTON_INTERACTION['focus_border_width']}px solid {COLOR_FOCUS_RING};"
        f" background-color: {colors['hover_background']};"
        "}"
        "QPushButton:disabled {"
        f" border: {BUTTON_INTERACTION['default_border_width']}px solid {COLOR_BORDER_MUTED};"
        f" background-color: {COLOR_BACKGROUND_PANEL_MUTED};"
        f" color: {COLOR_TEXT_DISABLED};"
        "}"
    )


def navigation_button_style():
    return (
        "QPushButton {"
        f" min-height: {CONTROL_HEIGHT}px;"
        f" padding: {SPACE_8}px {SPACE_12}px;"
        f" border: 1px solid {COLOR_BORDER_MUTED};"
        f" border-radius: {RADIUS_10}px;"
        f" background-color: {COLOR_BACKGROUND_PANEL_MUTED};"
        f" color: {COLOR_TEXT_SECONDARY};"
        " text-align: left;"
        "}"
        "QPushButton:hover {"
        f" border: 1px solid {COLOR_ACCENT_PRIMARY};"
        f" background-color: {COLOR_SURFACE_HOVER};"
        "}"
        "QPushButton:focus {"
        f" border: 2px solid {COLOR_FOCUS_RING};"
        " outline: none;"
        f" background-color: {COLOR_SURFACE_HOVER};"
        "}"
        "QPushButton:checked {"
        f" border: 1px solid {COLOR_ACCENT_HOVER};"
        f" background-color: {COLOR_SURFACE_ACTIVE};"
        f" color: {COLOR_TEXT_PRIMARY};"
        "}"
        "QPushButton:checked:hover {"
        f" border: 1px solid {COLOR_ACCENT_PRIMARY};"
        f" background-color: {COLOR_ACCENT_SUBTLE};"
        "}"
    )


def panel_style(card=False):
    radius = RADIUS_12
    background = COLOR_BACKGROUND_PANEL if card else COLOR_BACKGROUND_PANEL_MUTED
    return f"QFrame {{ background-color: {background}; border: 1px solid {COLOR_BORDER_DEFAULT}; border-radius: {radius}px; }}"


def info_panel_style():
    return (
        "QFrame {"
        f" background-color: {COLOR_BACKGROUND_PANEL_ELEVATED};"
        f" border: 1px solid {COLOR_BORDER_STRONG};"
        f" border-radius: {RADIUS_12}px;"
        "}"
    )


def dialog_shell_style(selector='QDialog'):
    return app_shell_style(selector)


def app_shell_style(selector='QWidget'):
    return (
        f"{selector} {{"
        f" background-color: {COLOR_BACKGROUND_APP};"
        f" color: {COLOR_TEXT_SECONDARY};"
        "}"
    )


def input_style():
    return (
        "QLineEdit, QComboBox {"
        f" min-height: {CONTROL_HEIGHT}px;"
        f" padding: {SPACE_8}px;"
        f" border: 1px solid {COLOR_BORDER_DEFAULT};"
        f" border-radius: {RADIUS_10}px;"
        f" background-color: {COLOR_BACKGROUND_INPUT};"
        f" color: {COLOR_TEXT_SECONDARY};"
        "}"
        "QLineEdit:hover, QComboBox:hover {"
        f" border: 1px solid {COLOR_ACCENT_PRIMARY};"
        "}"
        "QLineEdit:focus, QComboBox:focus {"
        f" border: 2px solid {COLOR_FOCUS_RING};"
        " outline: none;"
        f" background-color: {COLOR_BACKGROUND_PANEL_MUTED};"
        "}"
        "QLineEdit:disabled, QComboBox:disabled {"
        f" border: 1px solid {COLOR_BORDER_MUTED};"
        f" background-color: {COLOR_BACKGROUND_PANEL_MUTED};"
        f" color: {COLOR_TEXT_DISABLED};"
        "}"
        "QLineEdit::placeholder {"
        f" color: {COLOR_TEXT_HELPER};"
        "}"
    )


def invalid_input_style():
    return (
        "QLineEdit, QComboBox {"
        f" border: 2px solid {COLOR_STATUS_DANGER};"
        f" background-color: {COLOR_STATUS_DANGER_BG};"
        "}"
    )


def table_style(cell_padding=SPACE_8):
    return (
        "QTableWidget, QListWidget {"
        f" border: 1px solid {COLOR_BORDER_MUTED};"
        f" border-radius: {RADIUS_8}px;"
        f" background-color: {COLOR_BACKGROUND_PANEL};"
        f" color: {COLOR_TEXT_SECONDARY};"
        "}"
        "QHeaderView::section {"
        f" background-color: {COLOR_BACKGROUND_PANEL_MUTED};"
        f" color: {COLOR_TEXT_PRIMARY};"
        f" padding: {cell_padding}px {SPACE_12}px;"
        f" border: 1px solid {COLOR_BORDER_MUTED};"
        "}"
        "QTableWidget::item, QListWidget::item {"
        f" padding: {cell_padding}px {SPACE_12}px;"
        "}"
        "QTableWidget::item:hover {"
        f" background-color: {COLOR_ACCENT_SUBTLE};"
        "}"
        "QTableWidget::item:selected, QListWidget::item:selected {"
        f" background-color: {COLOR_ACCENT_HOVER};"
        f" color: {COLOR_TEXT_PRIMARY};"
        "}"
        "QTableWidget::item:focus, QListWidget::item:focus {"
        f" border: 1px solid {COLOR_ACCENT_PRIMARY};"
        "}"
    )


def modal_surface_style(selector='QFrame'):
    return (
        f"{selector} {{"
        f" background-color: {COLOR_BACKGROUND_PANEL};"
        f" border: 1px solid {COLOR_BORDER_DEFAULT};"
        f" border-radius: {RADIUS_12}px;"
        "}"
    )


def progress_bar_style():
    return (
        "QProgressBar {"
        f" border: 1px solid {COLOR_BORDER_DEFAULT};"
        f" border-radius: {RADIUS_10}px;"
        f" background-color: {COLOR_BACKGROUND_INPUT};"
        f" color: {COLOR_TEXT_PRIMARY};"
        " text-align: center;"
        "}"
        "QProgressBar::chunk {"
        f" border-radius: {RADIUS_10}px;"
        f" background-color: {COLOR_ACCENT_PRIMARY};"
        "}"
        "QProgressBar:disabled {"
        f" border: 1px solid {COLOR_BORDER_MUTED};"
        f" background-color: {COLOR_BACKGROUND_PANEL_MUTED};"
        f" color: {COLOR_TEXT_DISABLED};"
        "}"
        "QProgressBar::chunk:disabled {"
        f" background-color: {COLOR_BORDER_STRONG};"
        "}"
    )
