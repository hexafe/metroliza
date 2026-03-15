"""Pure planning helpers for summary-sheet worksheet/chart rendering."""

from modules.summary_plot_palette import SUMMARY_PLOT_PALETTE


CHART_TOP_SLOT_ORDER = (
    'title_band',
    'spec_primary',
    'mean_primary',
    'spec_secondary',
    'spec_tertiary',
)

CHART_TOP_SLOT_Y = {
    'title_band': 1.145,
    'spec_primary': 1.065,
    'mean_primary': 1.020,
    'spec_secondary': 0.975,
    'spec_tertiary': 0.935,
}

ANNOTATION_SLOT_Y = dict(CHART_TOP_SLOT_Y)
ANNOTATION_SLOT_ORDER = tuple(CHART_TOP_SLOT_ORDER)


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
    del y_max
    return [
        {
            'kind': 'mean',
            'x': average,
            'text': f'Mean = {average:.3f}',
            'color': SUMMARY_PLOT_PALETTE['annotation_text'],
            'ha': 'center',
            'priority': 300,
            'preferred_slot': 'mean_primary',
        },
        {
            'kind': 'usl',
            'x': usl,
            'text': f'USL={usl:.3f}',
            'color': SUMMARY_PLOT_PALETTE['spec_limit'],
            'ha': 'center',
            'priority': 260,
            'preferred_slot': 'spec_primary',
        },
        {
            'kind': 'lsl',
            'x': lsl,
            'text': f'LSL={lsl:.3f}',
            'color': SUMMARY_PLOT_PALETTE['spec_limit'],
            'ha': 'center',
            'priority': 250,
            'preferred_slot': 'spec_secondary',
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
    del row_step

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

    slot_index = {name: idx for idx, name in enumerate(ANNOTATION_SLOT_ORDER)}
    fallback_slot_by_kind = {
        'title': 'title_band',
        'mean': 'mean_primary',
        'usl': 'spec_tertiary',
        'lsl': 'spec_tertiary',
    }

    def _slot_y(slot_name):
        return ANNOTATION_SLOT_Y.get(slot_name, base_text_y_axes)

    def _safe_slot(slot_name, *, kind=None):
        if slot_name in slot_index:
            return slot_name
        fallback_slot = fallback_slot_by_kind.get(kind)
        if fallback_slot in slot_index:
            return fallback_slot
        return ANNOTATION_SLOT_ORDER[-1]

    row_map = {}
    if mean and usl and lsl:
        assigned_slots = {
            'mean': _safe_slot(mean.get('preferred_slot'), kind='mean'),
            'usl': _safe_slot(usl.get('preferred_slot'), kind='usl'),
            'lsl': _safe_slot(lsl.get('preferred_slot'), kind='lsl'),
        }

        close_pairs = set()
        for left_index, left in enumerate(annotations):
            for right in annotations[left_index + 1 :]:
                if abs(float(left['x']) - float(right['x'])) < threshold_data_units:
                    close_pairs.add(tuple(sorted((left['kind'], right['kind']))))

        def _promote_slot(current_slot):
            current_index = slot_index[current_slot]
            next_index = min(current_index + 1, len(ANNOTATION_SLOT_ORDER) - 1)
            return ANNOTATION_SLOT_ORDER[next_index]

        for _ in range(8):
            moved = False
            for left_kind, right_kind in sorted(close_pairs):
                if assigned_slots[left_kind] != assigned_slots[right_kind]:
                    continue
                left = by_kind[left_kind]
                right = by_kind[right_kind]
                loser_kind = left_kind if int(left.get('priority', 100)) <= int(right.get('priority', 100)) else right_kind
                promoted = _promote_slot(assigned_slots[loser_kind])
                if promoted != assigned_slots[loser_kind]:
                    assigned_slots[loser_kind] = promoted
                    moved = True
            if not moved:
                break

        row_map = {kind: slot_index[slot] for kind, slot in assigned_slots.items()}
    else:
        for index, annotation in enumerate(annotations):
            row_map[annotation.get('kind')] = index
            annotation['assigned_slot'] = ANNOTATION_SLOT_ORDER[min(index, len(ANNOTATION_SLOT_ORDER) - 1)]

    for annotation in annotations:
        row_index = row_map.get(annotation.get('kind'), 0)
        assigned_slot = annotation.get('assigned_slot') or ANNOTATION_SLOT_ORDER[min(row_index, len(ANNOTATION_SLOT_ORDER) - 1)]
        annotation['row_index'] = row_index
        annotation['assigned_slot'] = assigned_slot
        annotation['text_y_axes'] = _slot_y(assigned_slot)

    return annotations, max(row_map.values()) if row_map else 0
