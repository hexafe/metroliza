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


def compute_histogram_annotation_rows(
    annotation_specs,
    distance_threshold,
    *,
    threshold_mode='data_units',
    x_span=None,
    base_text_y_axes=1.01,
    row_step=0.025,
):
    """Assign collision-safe row indices for histogram annotations.

    Mean is always positioned on the highest row, while USL/LSL are constrained
    to rows below mean. Close x-neighbors (as defined by ``distance_threshold``)
    are forced onto separate rows.
    """

    if not annotation_specs:
        return [], 0

    safe_threshold = max(float(distance_threshold), 0.0)
    resolved_span = abs(float(x_span)) if x_span not in (None, 0) else None

    def _distance(left, right):
        delta = abs(float(left['x']) - float(right['x']))
        if threshold_mode == 'axis_fraction' and resolved_span:
            return delta / resolved_span
        return delta

    annotations = [dict(annotation) for annotation in annotation_specs]
    by_kind = {annotation.get('kind'): annotation for annotation in annotations}
    mean = by_kind.get('mean')
    usl = by_kind.get('usl')
    lsl = by_kind.get('lsl')

    row_map = {}
    if mean and usl and lsl:
        close_mean_usl = _distance(mean, usl) < safe_threshold
        close_mean_lsl = _distance(mean, lsl) < safe_threshold
        close_usl_lsl = _distance(usl, lsl) < safe_threshold

        best_map = None
        for mean_row in range(1, 6):
            for usl_row in range(0, mean_row):
                for lsl_row in range(0, mean_row):
                    if close_mean_usl and mean_row == usl_row:
                        continue
                    if close_mean_lsl and mean_row == lsl_row:
                        continue
                    if close_usl_lsl and usl_row == lsl_row:
                        continue

                    candidate = {'mean': mean_row, 'usl': usl_row, 'lsl': lsl_row}
                    if best_map is None:
                        best_map = candidate
                        continue
                    candidate_max = max(candidate.values())
                    best_max = max(best_map.values())
                    if candidate_max < best_max:
                        best_map = candidate
                    elif candidate_max == best_max and (candidate['usl'], candidate['lsl']) > (best_map['usl'], best_map['lsl']):
                        best_map = candidate

        row_map = best_map or {'mean': 1, 'usl': 0, 'lsl': 0}
    else:
        current_row = 0
        for annotation in annotations:
            row_map[annotation.get('kind')] = current_row
            current_row += 1

    for annotation in annotations:
        row_index = row_map.get(annotation.get('kind'), 0)
        annotation['row_index'] = row_index
        annotation['text_y_axes'] = base_text_y_axes + (row_index * row_step)

    return annotations, max(row_map.values()) if row_map else 0
