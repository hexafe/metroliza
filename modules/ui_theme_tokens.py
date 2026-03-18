"""Shared semantic UI theme tokens for list/dialog row coloring."""

import colorsys

BASE_ROW_BACKGROUND_FALLBACK = "#FFFFFF"
SELECTED_ROW_BACKGROUND_FALLBACK = "#5E88AD"
DEFAULT_GROUP_COLOR = BASE_ROW_BACKGROUND_FALLBACK
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
