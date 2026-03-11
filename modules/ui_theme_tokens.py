"""Shared semantic UI tokens and reusable style builders for dialogs/screens."""

import colorsys

BASE_ROW_BACKGROUND_FALLBACK = "#FFFFFF"
SELECTED_ROW_BACKGROUND_FALLBACK = "#5E88AD"
DEFAULT_GROUP_COLOR = BASE_ROW_BACKGROUND_FALLBACK

COLOR_BACKGROUND_APP = "#F8FAFC"
COLOR_BACKGROUND_PANEL = "#FFFFFF"
COLOR_BACKGROUND_PANEL_MUTED = "#F1F5F9"
COLOR_TEXT_PRIMARY = "#0F172A"
COLOR_TEXT_SECONDARY = "#1F2937"
COLOR_TEXT_MUTED = "#475569"
COLOR_TEXT_HELPER = "#64748B"
COLOR_BORDER_DEFAULT = "#CBD5E1"
COLOR_BORDER_MUTED = "#E2E8F0"
COLOR_BORDER_STRONG = "#94A3B8"
COLOR_ACCENT = "#2563EB"
COLOR_ACCENT_HOVER = "#1D4ED8"
COLOR_ACCENT_SUBTLE = "#DBEAFE"
COLOR_FOCUS_RING = "#2563EB"
COLOR_SELECTION = "#5E88AD"
COLOR_STATUS_SUCCESS = "#059669"
COLOR_STATUS_WARNING = "#D97706"
COLOR_STATUS_DANGER = "#DC2626"

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
        'text': "#FFFFFF",
        'background': COLOR_ACCENT,
        'border': COLOR_ACCENT,
        'hover_background': COLOR_ACCENT_HOVER,
        'hover_border': COLOR_ACCENT_HOVER,
        'pressed_background': "#1E40AF",
        'pressed_border': "#1E40AF",
    },
    'secondary': {
        'text': COLOR_TEXT_SECONDARY,
        'background': COLOR_BACKGROUND_PANEL,
        'border': COLOR_BORDER_DEFAULT,
        'hover_background': COLOR_BACKGROUND_PANEL_MUTED,
        'hover_border': COLOR_BORDER_STRONG,
        'pressed_background': "#E2E8F0",
        'pressed_border': COLOR_BORDER_STRONG,
    },
    'tertiary': {
        'text': COLOR_TEXT_SECONDARY,
        'background': COLOR_BACKGROUND_PANEL_MUTED,
        'border': COLOR_BORDER_MUTED,
        'hover_background': "#E2E8F0",
        'hover_border': COLOR_BORDER_DEFAULT,
        'pressed_background': "#CBD5E1",
        'pressed_border': COLOR_BORDER_DEFAULT,
    },
    'danger': {
        'text': "#FFFFFF",
        'background': COLOR_STATUS_DANGER,
        'border': COLOR_STATUS_DANGER,
        'hover_background': "#B91C1C",
        'hover_border': "#B91C1C",
        'pressed_background': "#991B1B",
        'pressed_border': "#991B1B",
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
        f" padding: {SPACE_8}px {SPACE_12}px;"
        f" border: {BUTTON_INTERACTION['default_border_width']}px solid {colors['border']};"
        f" border-radius: {RADIUS_8}px;"
        f" background-color: {colors['background']};"
        f" color: {colors['text']};"
        "}"
        "QPushButton:hover {"
        f" border: {BUTTON_INTERACTION['default_border_width']}px solid {colors['hover_border']};"
        f" background-color: {colors['hover_background']};"
        "}"
        "QPushButton:focus {"
        f" border: {BUTTON_INTERACTION['focus_border_width']}px solid {COLOR_FOCUS_RING};"
        f" background-color: {colors['hover_background']};"
        "}"
        "QPushButton:pressed {"
        f" border: {BUTTON_INTERACTION['default_border_width']}px solid {colors['pressed_border']};"
        f" background-color: {colors['pressed_background']};"
        "}"
        "QPushButton:disabled {"
        f" border: {BUTTON_INTERACTION['default_border_width']}px solid {COLOR_BORDER_MUTED};"
        f" background-color: {COLOR_BACKGROUND_PANEL_MUTED};"
        f" color: {COLOR_TEXT_HELPER};"
        "}"
    )


def card_button_style(variant='secondary'):
    colors = BUTTON_VARIANTS.get(variant, BUTTON_VARIANTS['secondary'])
    return (
        "QPushButton {"
        f" padding: {SPACE_8}px {SPACE_12}px;"
        f" border: {BUTTON_INTERACTION['default_border_width']}px solid {colors['border']};"
        f" border-radius: {RADIUS_10}px;"
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
        f" background-color: {colors['hover_background']};"
        "}"
        "QPushButton:focus-visible {"
        f" border: {BUTTON_INTERACTION['focus_border_width']}px solid {COLOR_FOCUS_RING};"
        f" background-color: {colors['hover_background']};"
        "}"
        "QPushButton:disabled {"
        f" border: {BUTTON_INTERACTION['default_border_width']}px solid {COLOR_BORDER_MUTED};"
        f" background-color: {COLOR_BACKGROUND_PANEL_MUTED};"
        f" color: {COLOR_TEXT_HELPER};"
        "}"
    )


def panel_style(card=False):
    radius = RADIUS_10 if card else RADIUS_12
    background = COLOR_BACKGROUND_PANEL if card else COLOR_BACKGROUND_PANEL_MUTED
    return f"QFrame {{ background-color: {background}; border: 1px solid {COLOR_BORDER_MUTED}; border-radius: {radius}px; }}"


def input_style():
    return (
        "QLineEdit, QComboBox {"
        f" padding: {SPACE_8}px;"
        f" border: 1px solid {COLOR_BORDER_DEFAULT};"
        f" border-radius: {RADIUS_8}px;"
        f" background-color: {COLOR_BACKGROUND_PANEL};"
        f" color: {COLOR_TEXT_SECONDARY};"
        "}"
        "QLineEdit:hover, QComboBox:hover {"
        f" border: 1px solid {COLOR_BORDER_STRONG};"
        "}"
        "QLineEdit:focus, QComboBox:focus {"
        f" border: 2px solid {COLOR_FOCUS_RING};"
        f" background-color: {COLOR_ACCENT_SUBTLE};"
        "}"
        "QLineEdit:disabled, QComboBox:disabled {"
        f" border: 1px solid {COLOR_BORDER_MUTED};"
        f" background-color: {COLOR_BACKGROUND_PANEL_MUTED};"
        f" color: {COLOR_TEXT_HELPER};"
        "}"
    )


def invalid_input_style():
    return (
        "QLineEdit, QComboBox {"
        f" border: 2px solid {COLOR_STATUS_DANGER};"
        f" background-color: #FEF2F2;"
        "}"
    )


def table_style(cell_padding=SPACE_8):
    selected_background = selected_row_background_override(COLOR_SELECTION)
    selected_text = selected_text_color(selected_background)
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
        f" padding: {cell_padding}px;"
        f" border: 1px solid {COLOR_BORDER_MUTED};"
        "}"
        "QTableWidget::item, QListWidget::item {"
        f" padding: {cell_padding}px;"
        "}"
        "QTableWidget::item:hover {"
        f" background-color: {COLOR_ACCENT_SUBTLE};"
        "}"
        "QTableWidget::item:selected, QListWidget::item:selected {"
        f" background-color: {selected_background};"
        f" color: {selected_text};"
        "}"
        "QTableWidget::item:focus {"
        f" border: 1px solid {COLOR_FOCUS_RING};"
        "}"
    )
