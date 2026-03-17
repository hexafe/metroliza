"""Pure workbook-planning and layout helpers for export summary rendering."""


def compute_histogram_font_sizes(
    figure_size=(6, 4),
    *,
    has_table=True,
    readability_scale=None,
):
    """Compute histogram annotation/table font sizes for summary-sheet embedding."""
    fig_width = figure_size[0] if isinstance(figure_size, (tuple, list)) and figure_size else 6
    fig_width = max(float(fig_width), 1.0)
    width_scale = min(1.25, max(0.8, fig_width / 6.0))

    optional_readability = 0.0 if readability_scale is None else float(readability_scale)
    readability_bonus = optional_readability * 0.18

    annotation_fontsize = 8.2 * width_scale
    table_fontsize = 10.3 * width_scale
    if has_table:
        annotation_fontsize -= 0.2
    annotation_fontsize += readability_bonus
    table_fontsize += readability_bonus

    return {
        'annotation_fontsize': min(10.5, max(7.0, annotation_fontsize)),
        'table_fontsize': min(11.5, max(8.0, table_fontsize)),
    }


def compute_histogram_table_layout(
    figure_size=(6, 4),
    *,
    table_fontsize=8.0,
    has_table=True,
):
    """Compute table bbox width and subplot right margin for histogram layouts."""
    fig_width = figure_size[0] if isinstance(figure_size, (tuple, list)) and figure_size else 6
    fig_width = max(float(fig_width), 1.0)
    width_scale = min(1.25, max(0.8, fig_width / 6.0))
    oversized_font = max(0.0, float(table_fontsize) - 8.0)

    table_bbox_width = 0.40 + (0.018 * oversized_font) - (0.008 * (width_scale - 1.0))
    table_bbox_width = min(0.48, max(0.38, table_bbox_width))

    right_margin = 0.69 + (0.02 * (width_scale - 1.0)) - (0.013 * oversized_font)
    if has_table:
        right_margin -= 0.005
    right_margin = min(0.76, max(0.64, right_margin))

    return {
        'table_bbox_width': table_bbox_width,
        'subplot_right': right_margin,
    }


def compute_histogram_three_region_layout(
    figure_size=(6, 4),
    *,
    table_fontsize=8.0,
):
    """Compute compact left/center/right geometry for histogram + dual side tables."""
    fig_width = figure_size[0] if isinstance(figure_size, (tuple, list)) and figure_size else 6
    fig_width = max(float(fig_width), 1.0)
    width_scale = min(1.25, max(0.8, fig_width / 6.0))
    oversized_font = max(0.0, float(table_fontsize) - 8.0)

    side_table_width = 0.24 + (0.009 * oversized_font) - (0.012 * (width_scale - 1.0))
    side_table_width = min(0.28, max(0.21, side_table_width))

    side_gap = 0.028 + (0.002 * oversized_font)
    side_gap = min(0.04, max(0.024, side_gap))

    left_table_x = -(side_table_width + side_gap)
    right_table_x = 1.0 + side_gap

    left_margin = 0.13 + side_table_width + side_gap
    right_margin = 0.87 - side_table_width - side_gap
    center_min_width = 0.50
    center_width = right_margin - left_margin
    if center_width < center_min_width:
        deficit = center_min_width - center_width
        left_margin = max(0.28, left_margin - (deficit / 2.0))
        right_margin = min(0.72, right_margin + (deficit / 2.0))

    return {
        'side_table_width': side_table_width,
        'left_table_x': left_table_x,
        'right_table_x': right_table_x,
        'subplot_left': min(0.34, max(0.26, left_margin)),
        'subplot_right': min(0.74, max(0.66, right_margin)),
    }
