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
            'text_y_axes': 1.018,
            'text': f'Mean = {average:.3f}',
            'color': SUMMARY_PLOT_PALETTE['annotation_text'],
            'ha': 'center',
        },
        {
            'kind': 'usl',
            'x': usl,
            'text_y_axes': 1.075,
            'text': f'USL={usl:.3f}',
            'color': SUMMARY_PLOT_PALETTE['spec_limit'],
            'ha': 'center',
        },
        {
            'kind': 'lsl',
            'x': lsl,
            'text_y_axes': 0.94,
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

    Mean is always positioned above the baseline label row, while close
    x-neighbors (as defined by ``distance_threshold``) are forced onto separate
    rows. Output preserves input ordering while row assignment stays
    deterministic.
    """

    if not annotation_specs:
        return [], 0

    safe_threshold = max(float(distance_threshold), 0.0)
    resolved_span = abs(float(x_span)) if x_span not in (None, 0) else None
    threshold_data_units = safe_threshold
    if threshold_mode == 'axis_fraction' and resolved_span:
        threshold_data_units = safe_threshold * resolved_span

    annotations = [dict(annotation) for annotation in annotation_specs]
    by_kind = {annotation.get('kind'): annotation for annotation in annotations}
    mean = by_kind.get('mean')
    usl = by_kind.get('usl')
    lsl = by_kind.get('lsl')

    row_map = {}
    if mean and usl and lsl:
        kind_order = {'mean': 0, 'usl': 1, 'lsl': 2}
        sorted_annotations = sorted(
            (mean, usl, lsl),
            key=lambda item: (float(item['x']), kind_order.get(item.get('kind'), 99)),
        )
        sorted_kinds = [item['kind'] for item in sorted_annotations]
        close_pairs = set()
        for left_index, left in enumerate(sorted_annotations):
            for right in sorted_annotations[left_index + 1 :]:
                if abs(float(left['x']) - float(right['x'])) < threshold_data_units:
                    close_pairs.add(tuple(sorted((left['kind'], right['kind']))))

        def _is_close(left_kind, right_kind):
            return tuple(sorted((left_kind, right_kind))) in close_pairs

        best_map = None
        best_rank = None
        for mean_row in range(1, 6):
            for usl_row in range(0, 6):
                for lsl_row in range(0, 6):
                    if _is_close('mean', 'usl') and mean_row == usl_row:
                        continue
                    if _is_close('mean', 'lsl') and mean_row == lsl_row:
                        continue
                    if _is_close('usl', 'lsl') and usl_row == lsl_row:
                        continue

                    candidate = {'mean': mean_row, 'usl': usl_row, 'lsl': lsl_row}
                    candidate_rank = (
                        max(candidate.values()),
                        -candidate['mean'],
                        tuple(candidate[kind] for kind in sorted_kinds),
                    )
                    if best_rank is None or candidate_rank < best_rank:
                        best_rank = candidate_rank
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
