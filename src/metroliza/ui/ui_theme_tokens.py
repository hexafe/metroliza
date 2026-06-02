"""Shared semantic UI theme tokens for Metroliza desktop UI surfaces."""

import colorsys

BASE_ROW_BACKGROUND_FALLBACK = "#FFFFFF"
SELECTED_ROW_BACKGROUND_FALLBACK = "#5E88AD"
DEFAULT_GROUP_COLOR = BASE_ROW_BACKGROUND_FALLBACK

WINDOW_BACKGROUND = "#F6F8FA"
SURFACE_BACKGROUND = "#FFFFFF"
SURFACE_MUTED_BACKGROUND = "#EEF2F5"
BORDER_SUBTLE = "#D6DDE3"
BORDER_STRONG = "#B7C2CC"
TEXT_PRIMARY = "#1F2933"
TEXT_SECONDARY = "#586574"
TEXT_MUTED = "#6C7886"
ACCENT_PRIMARY = "#256D85"
ACCENT_PRIMARY_HOVER = "#1F5B70"
ACCENT_INFO = "#2F6FED"
ACCENT_SUCCESS = "#2E7D5B"
ACCENT_WARNING = "#B7791F"
ACCENT_DANGER = "#B42318"
DISABLED_TEXT = "#8B98A7"
FOCUS_RING = "#8AB7C7"

SPACING_XS = 4
SPACING_SM = 8
SPACING_MD = 12
SPACING_LG = 16
RADIUS_SM = 4
RADIUS_MD = 6

STATUS_COLORS = {
    "info": (ACCENT_INFO, "#EAF2FF"),
    "success": (ACCENT_SUCCESS, "#EAF7F1"),
    "warning": (ACCENT_WARNING, "#FFF6E5"),
    "danger": (ACCENT_DANGER, "#FDEDEC"),
    "neutral": (TEXT_SECONDARY, SURFACE_MUTED_BACKGROUND),
}

DARK_WINDOW_BACKGROUND = "#0F1720"
DARK_SURFACE_BACKGROUND = "#17212B"
DARK_SURFACE_MUTED_BACKGROUND = "#223140"
DARK_BORDER_SUBTLE = "#334456"
DARK_BORDER_STRONG = "#4B6276"
DARK_TEXT_PRIMARY = "#E7EEF6"
DARK_TEXT_SECONDARY = "#B7C5D5"
DARK_TEXT_MUTED = "#93A4B7"
DARK_ACCENT_PRIMARY = "#4FB3C8"
DARK_ACCENT_PRIMARY_HOVER = "#74C9D9"
DARK_ACCENT_INFO = "#7CA8FF"
DARK_ACCENT_SUCCESS = "#66D0A0"
DARK_ACCENT_WARNING = "#F2B84B"
DARK_ACCENT_DANGER = "#FF8A7E"
DARK_DISABLED_TEXT = "#7C8997"
DARK_FOCUS_RING = "#8DD9E8"
DARK_STATUS_COLORS = {
    "info": (DARK_ACCENT_INFO, "#162A4A"),
    "success": (DARK_ACCENT_SUCCESS, "#163629"),
    "warning": (DARK_ACCENT_WARNING, "#3F2C10"),
    "danger": (DARK_ACCENT_DANGER, "#421E1D"),
    "neutral": (DARK_TEXT_SECONDARY, DARK_SURFACE_MUTED_BACKGROUND),
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


def theme_tokens(dark_mode=False):
    """Return semantic color tokens for the requested desktop palette."""
    if dark_mode:
        return {
            "WINDOW_BACKGROUND": DARK_WINDOW_BACKGROUND,
            "SURFACE_BACKGROUND": DARK_SURFACE_BACKGROUND,
            "SURFACE_MUTED_BACKGROUND": DARK_SURFACE_MUTED_BACKGROUND,
            "BORDER_SUBTLE": DARK_BORDER_SUBTLE,
            "BORDER_STRONG": DARK_BORDER_STRONG,
            "TEXT_PRIMARY": DARK_TEXT_PRIMARY,
            "TEXT_SECONDARY": DARK_TEXT_SECONDARY,
            "TEXT_MUTED": DARK_TEXT_MUTED,
            "ACCENT_PRIMARY": DARK_ACCENT_PRIMARY,
            "ACCENT_PRIMARY_HOVER": DARK_ACCENT_PRIMARY_HOVER,
            "ACCENT_INFO": DARK_ACCENT_INFO,
            "ACCENT_SUCCESS": DARK_ACCENT_SUCCESS,
            "ACCENT_WARNING": DARK_ACCENT_WARNING,
            "ACCENT_DANGER": DARK_ACCENT_DANGER,
            "DISABLED_TEXT": DARK_DISABLED_TEXT,
            "FOCUS_RING": DARK_FOCUS_RING,
            "STATUS_COLORS": DARK_STATUS_COLORS,
            "BUTTON_HOVER_BACKGROUND": "#1B2A37",
            "DEFAULT_BUTTON_TEXT": "#06121A",
        }
    return {
        "WINDOW_BACKGROUND": WINDOW_BACKGROUND,
        "SURFACE_BACKGROUND": SURFACE_BACKGROUND,
        "SURFACE_MUTED_BACKGROUND": SURFACE_MUTED_BACKGROUND,
        "BORDER_SUBTLE": BORDER_SUBTLE,
        "BORDER_STRONG": BORDER_STRONG,
        "TEXT_PRIMARY": TEXT_PRIMARY,
        "TEXT_SECONDARY": TEXT_SECONDARY,
        "TEXT_MUTED": TEXT_MUTED,
        "ACCENT_PRIMARY": ACCENT_PRIMARY,
        "ACCENT_PRIMARY_HOVER": ACCENT_PRIMARY_HOVER,
        "ACCENT_INFO": ACCENT_INFO,
        "ACCENT_SUCCESS": ACCENT_SUCCESS,
        "ACCENT_WARNING": ACCENT_WARNING,
        "ACCENT_DANGER": ACCENT_DANGER,
        "DISABLED_TEXT": DISABLED_TEXT,
        "FOCUS_RING": FOCUS_RING,
        "STATUS_COLORS": STATUS_COLORS,
        "BUTTON_HOVER_BACKGROUND": "#F9FCFD",
        "DEFAULT_BUTTON_TEXT": "#FFFFFF",
    }


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


def resolve_default_group_color_from_base(base_hex=None, fallback_hex=BASE_ROW_BACKGROUND_FALLBACK):
    return resolve_base_row_background(base_hex or fallback_hex)


def resolve_widget_base_row_background(widget, fallback_hex=BASE_ROW_BACKGROUND_FALLBACK):
    palette = widget.palette() if hasattr(widget, "palette") else None
    base = palette.base().color() if palette is not None and hasattr(palette, "base") else None
    base_hex = base.name() if base is not None and hasattr(base, "isValid") and base.isValid() else None
    return resolve_default_group_color_from_base(base_hex, fallback_hex=fallback_hex)


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
