"""Histogram panel layout helpers and rectangle-guard utilities."""

from __future__ import annotations

# Layout constants (normalized figure coordinates)
HISTOGRAM_OUTER_PADDING_X = 0.03
HISTOGRAM_OUTER_PADDING_TOP = 0.10
HISTOGRAM_OUTER_PADDING_BOTTOM = 0.103
HISTOGRAM_TITLE_BAND_HEIGHT = 0.05
HISTOGRAM_INTER_PANEL_GAP = 0.022
HISTOGRAM_MIN_PLOT_WIDTH = 0.42
HISTOGRAM_MIN_NOTE_HEIGHT = 0.125
HISTOGRAM_SIDE_PANEL_MIN_WIDTH = 0.16
HISTOGRAM_SIDE_PANEL_MAX_WIDTH = 0.28
HISTOGRAM_RIGHT_INFO_MIN_WIDTH = 0.28
HISTOGRAM_RIGHT_INFO_MAX_WIDTH = 0.37

_HISTOGRAM_BASE_SIDE_PANEL_WIDTH = 0.23
_HISTOGRAM_TABLE_ROW_HEIGHT = 0.027
_HISTOGRAM_BASE_TABLE_HEIGHT = 0.30
_HISTOGRAM_NOTE_LINE_HEIGHT = 0.032
_HISTOGRAM_BASE_NOTE_HEIGHT = 0.07
_HISTOGRAM_MIN_TABLE_HEIGHT = 0.24
_HISTOGRAM_PANEL_TABLE_ROW_HEIGHT = 0.060
_HISTOGRAM_PANEL_TABLE_PAD_Y = 0.02
_HISTOGRAM_RIGHT_TABLE_MIN_HEIGHT = 0.24
_HISTOGRAM_RIGHT_STACK_GAP = 0.012
_HISTOGRAM_RIGHT_COLUMN_LEFT_INSET = 0.010


def _clamp(value, lower, upper):
    return min(upper, max(lower, value))


def rectangles_overlap(rect_a, rect_b, *, epsilon=1e-9):
    """Return True when two normalized rectangles intersect."""
    ax0 = float(rect_a['x'])
    ay0 = float(rect_a['y'])
    ax1 = ax0 + float(rect_a['width'])
    ay1 = ay0 + float(rect_a['height'])

    bx0 = float(rect_b['x'])
    by0 = float(rect_b['y'])
    bx1 = bx0 + float(rect_b['width'])
    by1 = by0 + float(rect_b['height'])

    separated = (
        ax1 <= bx0 + epsilon
        or bx1 <= ax0 + epsilon
        or ay1 <= by0 + epsilon
        or by1 <= ay0 + epsilon
    )
    return not separated


def assert_non_overlapping_rectangles(rectangles):
    """Raise AssertionError when any named rectangle pair intersects."""
    names = list(rectangles.keys())
    for index, left_name in enumerate(names):
        for right_name in names[index + 1 :]:
            if rectangles_overlap(rectangles[left_name], rectangles[right_name]):
                raise AssertionError(
                    f"Layout rectangles intersect: {left_name} vs {right_name}"
                )


def compute_histogram_panel_layout(
    figure_size=(6, 4),
    *,
    table_fontsize=8.0,
    left_row_count=0,
    right_row_count=0,
    note_line_count=0,
    left_panel_width_hint=None,
    right_panel_width_hint=None,
):
    """Compute normalized non-overlapping rectangles for histogram side panels and plot."""
    fig_width = figure_size[0] if isinstance(figure_size, (tuple, list)) and figure_size else 6
    fig_width = max(float(fig_width), 1.0)
    width_scale = min(1.25, max(0.8, fig_width / 6.0))
    oversized_font = max(0.0, float(table_fontsize) - 8.0)

    side_pref = _HISTOGRAM_BASE_SIDE_PANEL_WIDTH + (0.008 * oversized_font) - (0.012 * (width_scale - 1.0))
    side_pref = _clamp(
        side_pref,
        HISTOGRAM_SIDE_PANEL_MIN_WIDTH,
        HISTOGRAM_SIDE_PANEL_MAX_WIDTH,
    )

    content_width = 1.0 - (2.0 * HISTOGRAM_OUTER_PADDING_X)
    gaps_width = 2.0 * HISTOGRAM_INTER_PANEL_GAP
    available_columns = content_width - gaps_width

    left_width = float(left_panel_width_hint) if left_panel_width_hint is not None else (side_pref + 0.018)
    right_width = float(right_panel_width_hint) if right_panel_width_hint is not None else side_pref
    left_width = _clamp(left_width, HISTOGRAM_SIDE_PANEL_MIN_WIDTH, HISTOGRAM_SIDE_PANEL_MAX_WIDTH)
    right_width = _clamp(right_width, HISTOGRAM_SIDE_PANEL_MIN_WIDTH, HISTOGRAM_SIDE_PANEL_MAX_WIDTH)
    plot_width = available_columns - left_width - right_width
    if plot_width < HISTOGRAM_MIN_PLOT_WIDTH:
        deficit = HISTOGRAM_MIN_PLOT_WIDTH - plot_width
        shrink_budget = (left_width - HISTOGRAM_SIDE_PANEL_MIN_WIDTH) + (right_width - HISTOGRAM_SIDE_PANEL_MIN_WIDTH)
        shrink = min(deficit, max(0.0, shrink_budget))
        if shrink > 0:
            left_share = (left_width - HISTOGRAM_SIDE_PANEL_MIN_WIDTH) / shrink_budget if shrink_budget > 0 else 0.5
            left_width -= shrink * left_share
            right_width -= shrink * (1.0 - left_share)
        left_width = max(HISTOGRAM_SIDE_PANEL_MIN_WIDTH, left_width)
        right_width = max(HISTOGRAM_SIDE_PANEL_MIN_WIDTH, right_width)
        plot_width = available_columns - left_width - right_width

    content_height = 1.0 - HISTOGRAM_OUTER_PADDING_TOP - HISTOGRAM_OUTER_PADDING_BOTTOM
    y_bottom = HISTOGRAM_OUTER_PADDING_BOTTOM

    desired_table_height = _HISTOGRAM_BASE_TABLE_HEIGHT + (_HISTOGRAM_TABLE_ROW_HEIGHT * max(left_row_count, right_row_count))
    desired_note_height = _HISTOGRAM_BASE_NOTE_HEIGHT + (_HISTOGRAM_NOTE_LINE_HEIGHT * note_line_count)
    note_height = max(HISTOGRAM_MIN_NOTE_HEIGHT, desired_note_height)

    target_right_table_height = _clamp(
        desired_table_height,
        _HISTOGRAM_MIN_TABLE_HEIGHT,
        max(_HISTOGRAM_MIN_TABLE_HEIGHT, content_height - HISTOGRAM_INTER_PANEL_GAP - HISTOGRAM_MIN_NOTE_HEIGHT),
    )
    max_note_height = max(HISTOGRAM_MIN_NOTE_HEIGHT, content_height - HISTOGRAM_INTER_PANEL_GAP - target_right_table_height)
    note_height = min(note_height, max_note_height)
    right_table_height = content_height - HISTOGRAM_INTER_PANEL_GAP - note_height

    if right_table_height < _HISTOGRAM_MIN_TABLE_HEIGHT:
        shortfall = _HISTOGRAM_MIN_TABLE_HEIGHT - right_table_height
        note_height = max(HISTOGRAM_MIN_NOTE_HEIGHT, note_height - shortfall)
        right_table_height = content_height - HISTOGRAM_INTER_PANEL_GAP - note_height

    left_x = HISTOGRAM_OUTER_PADDING_X
    plot_x = left_x + left_width + HISTOGRAM_INTER_PANEL_GAP
    right_x = plot_x + plot_width + HISTOGRAM_INTER_PANEL_GAP

    right_table_y = y_bottom + note_height + HISTOGRAM_INTER_PANEL_GAP
    rectangles = {
        'left_table_rect': {
            'x': left_x,
            'y': y_bottom,
            'width': left_width,
            'height': content_height,
        },
        'plot_rect': {
            'x': plot_x,
            'y': y_bottom,
            'width': plot_width,
            'height': content_height,
        },
        'right_table_rect': {
            'x': right_x,
            'y': right_table_y,
            'width': right_width,
            'height': right_table_height,
        },
        'note_rect': {
            'x': right_x,
            'y': y_bottom,
            'width': right_width,
            'height': note_height,
        },
    }
    assert_non_overlapping_rectangles(rectangles)
    return rectangles


def compute_histogram_plot_with_right_info_layout(
    figure_size=(8.4, 4.0),
    *,
    table_fontsize=8.0,
    fit_row_count=0,
    stats_row_count=0,
    note_line_count=0,
    right_container_width_hint=None,
):
    """Return non-overlapping rectangles for histogram + stacked right information column layout."""

    fig_width = figure_size[0] if isinstance(figure_size, (tuple, list)) and figure_size else 8.4
    fig_width = max(float(fig_width), 1.0)
    width_scale = min(1.35, max(0.85, fig_width / 8.4))
    oversized_font = max(0.0, float(table_fontsize) - 8.0)

    left_padding = 0.056
    right_padding = 0.016
    content_width = 1.0 - left_padding - right_padding
    content_height = 1.0 - HISTOGRAM_OUTER_PADDING_TOP - HISTOGRAM_OUTER_PADDING_BOTTOM
    content_height = max(0.0, content_height - HISTOGRAM_TITLE_BAND_HEIGHT)
    panel_gap = HISTOGRAM_INTER_PANEL_GAP

    base_right_width = 0.315 + (0.005 * oversized_font) - (0.012 * (width_scale - 1.0))
    right_container_width = (
        float(right_container_width_hint)
        if right_container_width_hint is not None
        else base_right_width
    )
    right_container_width = _clamp(
        right_container_width,
        HISTOGRAM_RIGHT_INFO_MIN_WIDTH,
        HISTOGRAM_RIGHT_INFO_MAX_WIDTH,
    )

    plot_width = content_width - panel_gap - right_container_width
    if plot_width < HISTOGRAM_MIN_PLOT_WIDTH:
        right_container_width = max(
            HISTOGRAM_RIGHT_INFO_MIN_WIDTH,
            content_width - panel_gap - HISTOGRAM_MIN_PLOT_WIDTH,
        )
        plot_width = content_width - panel_gap - right_container_width

    y_bottom = HISTOGRAM_OUTER_PADDING_BOTTOM
    plot_rect = {
        'x': left_padding,
        'y': y_bottom,
        'width': plot_width,
        'height': content_height,
    }
    right_container_x = left_padding + plot_width + panel_gap
    right_container_width = max(
        HISTOGRAM_RIGHT_INFO_MIN_WIDTH,
        right_container_width - _HISTOGRAM_RIGHT_COLUMN_LEFT_INSET,
    )
    right_container_rect = {
        'x': right_container_x + _HISTOGRAM_RIGHT_COLUMN_LEFT_INSET,
        'y': y_bottom,
        'width': right_container_width,
        'height': content_height,
    }

    del note_line_count
    footer_height = 0.0

    stats_target = compute_panel_table_content_height(int(stats_row_count), row_height=0.056, header_rows=1, pad_y=0.018)
    fit_target = compute_panel_table_content_height(int(fit_row_count), row_height=0.056, header_rows=1, pad_y=0.018)
    content_for_tables = max(0.0, content_height - _HISTOGRAM_RIGHT_STACK_GAP)
    total_target = max(1e-9, stats_target + fit_target)
    stats_height = content_for_tables * (stats_target / total_target)
    fit_height = content_for_tables - stats_height

    min_table_height = 0.24
    if stats_height < min_table_height:
        delta = min_table_height - stats_height
        stats_height = min_table_height
        fit_height = max(min_table_height, fit_height - delta)
    if fit_height < min_table_height:
        delta = min_table_height - fit_height
        fit_height = min_table_height
        stats_height = max(min_table_height, stats_height - delta)

    fit_table_rect, stats_table_rect, footer_rect = split_stacked_right_container(
        right_container_rect,
        y_bottom=y_bottom,
        stats_height=stats_height,
        fit_height=fit_height,
        footer_height=footer_height,
        gap=_HISTOGRAM_RIGHT_STACK_GAP,
    )

    rectangles = {
        'plot_rect': plot_rect,
        'right_container_rect': right_container_rect,
        'fit_table_rect': fit_table_rect,
        'stats_table_rect': stats_table_rect,
        'footer_rect': footer_rect,
    }
    assert_non_overlapping_rectangles(
        {
            'plot_rect': plot_rect,
            'fit_table_rect': fit_table_rect,
            'stats_table_rect': stats_table_rect,
            'footer_rect': footer_rect,
        }
    )
    return rectangles


def split_stacked_right_container(
    right_container_rect,
    *,
    y_bottom,
    stats_height,
    fit_height,
    footer_height,
    gap,
):
    """Split right container into stacked stats, fit, and optional compact footer areas."""
    full_x = float(right_container_rect['x'])
    full_y = float(y_bottom)
    full_w = float(right_container_rect['width'])

    footer_y = full_y
    fit_y = footer_y + float(footer_height) + (float(gap) if footer_height > 0 else 0.0)
    stats_y = fit_y + float(fit_height) + float(gap)

    stats_table_rect = {
        'x': float(right_container_rect['x']),
        'y': stats_y,
        'width': full_w,
        'height': float(stats_height),
    }
    fit_table_rect = {
        'x': full_x,
        'y': fit_y,
        'width': full_w,
        'height': float(fit_height),
    }
    footer_rect = {
        'x': full_x,
        'y': footer_y,
        'width': full_w,
        'height': float(footer_height),
    }
    return fit_table_rect, stats_table_rect, footer_rect


def compute_panel_table_content_height(row_count, *, header_rows=1, row_height=_HISTOGRAM_PANEL_TABLE_ROW_HEIGHT, pad_y=_HISTOGRAM_PANEL_TABLE_PAD_Y):
    total_rows = max(0, int(row_count)) + int(header_rows)
    return (total_rows * float(row_height)) + (2.0 * float(pad_y))


def resolve_inner_table_rect(panel_rect, *, row_count, row_height=_HISTOGRAM_PANEL_TABLE_ROW_HEIGHT, header_rows=1, pad_y=_HISTOGRAM_PANEL_TABLE_PAD_Y, valign='top'):
    content_height = min(
        float(panel_rect['height']),
        compute_panel_table_content_height(
            row_count,
            header_rows=header_rows,
            row_height=row_height,
            pad_y=pad_y,
        ),
    )
    if valign == 'top':
        y = float(panel_rect['y']) + float(panel_rect['height']) - content_height
    elif valign == 'center':
        y = float(panel_rect['y']) + ((float(panel_rect['height']) - content_height) / 2.0)
    else:
        y = float(panel_rect['y'])
    return {
        'x': float(panel_rect['x']),
        'y': y,
        'width': float(panel_rect['width']),
        'height': content_height,
    }
