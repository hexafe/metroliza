"""Pure planning helpers for summary-sheet worksheet/chart rendering."""

from modules.summary_plot_palette import SUMMARY_PLOT_PALETTE


def build_summary_sheet_position_plan(base_col):
    """Return summary sheet anchors aligned with the 5-column measurement block layout."""
    # Summary rendering currently receives the post-increment measurement column
    # (5, 10, 15, ...). Normalize that to zero-based block indices (0, 1, 2, ...)
    # so row panels stack contiguously without gaps.
    block_index = max((base_col // 5) - 1, 0)
    row = block_index * 20
    return {
        'row': row,
        'column': 0,
        'header_row': row,
        'image_row': row + 1,
    }


def build_summary_image_anchor_plan(base_col):
    """Return deterministic worksheet anchor columns for all summary visual panels."""
    base_position = build_summary_sheet_position_plan(base_col)
    image_row = base_position['image_row']

    return {
        'header': (base_position['header_row'], base_position['column']),
        'distribution': (image_row, 0),
        'iqr': (image_row, 9),
        'histogram': (image_row, 19),
        'trend': (image_row, 29),
    }


def build_histogram_annotation_specs(average, usl, lsl, y_max):
    """Return stable annotation payloads for histogram mean/limit labels."""
    return [
        {
            'kind': 'mean',
            'x': average,
            'text_y_axes': 1.06,
            'text': f'Mean = {average:.3f}',
            'color': SUMMARY_PLOT_PALETTE['annotation_text'],
            'ha': 'center',
        },
        {
            'kind': 'usl',
            'x': usl,
            'text_y_axes': 1.02,
            'text': f'USL={usl:.3f}',
            'color': SUMMARY_PLOT_PALETTE['spec_limit'],
            'ha': 'center',
        },
        {
            'kind': 'lsl',
            'x': lsl,
            'text_y_axes': 1.02,
            'text': f'LSL={lsl:.3f}',
            'color': SUMMARY_PLOT_PALETTE['spec_limit'],
            'ha': 'center',
        },
    ]
