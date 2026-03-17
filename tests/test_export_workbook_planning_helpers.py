from modules.export_workbook_planning_helpers import (
    compute_histogram_font_sizes,
    compute_histogram_three_region_layout,
    compute_histogram_table_layout,
)
from modules.export_histogram_layout import compute_histogram_panel_layout


def _rectangles_intersect(rect_a, rect_b, *, epsilon=1e-9):
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


def _assert_no_intersections(rectangles):
    names = list(rectangles.keys())
    for index, left_name in enumerate(names):
        for right_name in names[index + 1 :]:
            assert not _rectangles_intersect(rectangles[left_name], rectangles[right_name]), (
                f"Unexpected rectangle overlap: {left_name} vs {right_name}"
            )


def test_compute_histogram_font_sizes_scales_with_readability():
    baseline = compute_histogram_font_sizes((6, 4), has_table=True)
    boosted = compute_histogram_font_sizes((6, 4), has_table=True, readability_scale=1.0)

    assert boosted['annotation_fontsize'] > baseline['annotation_fontsize']
    assert boosted['table_fontsize'] > baseline['table_fontsize']


def test_compute_histogram_table_layout_bounds_right_margin_and_width():
    layout = compute_histogram_table_layout((12, 4), table_fontsize=11.0, has_table=True)

    assert 0.38 <= layout['table_bbox_width'] <= 0.48
    assert 0.64 <= layout['subplot_right'] <= 0.76


def test_compute_histogram_three_region_layout_returns_compact_separated_regions():
    layout = compute_histogram_three_region_layout((6.2, 4), table_fontsize=9.0)

    assert 0.21 <= layout['side_table_width'] <= 0.28
    assert layout['left_table_x'] < 0.0
    assert layout['right_table_x'] > 1.0
    assert 0.26 <= layout['subplot_left'] <= 0.34
    assert 0.66 <= layout['subplot_right'] <= 0.74
    assert layout['subplot_right'] - layout['subplot_left'] >= 0.43


def test_compute_histogram_panel_layout_preserves_non_overlapping_rectangles_across_distribution_fit_scenarios():
    scenarios = [
        {
            'name': 'standard one-sided distribution-fit case',
            'kwargs': {
                'figure_size': (6.2, 4.0),
                'table_fontsize': 8.8,
                'left_row_count': 6,
                'right_row_count': 9,
                'note_line_count': 4,
            },
        },
        {
            'name': 'bilateral case',
            'kwargs': {
                'figure_size': (6.2, 4.0),
                'table_fontsize': 8.8,
                'left_row_count': 7,
                'right_row_count': 9,
                'note_line_count': 4,
            },
        },
        {
            'name': 'long left-table labels',
            'kwargs': {
                'figure_size': (6.2, 4.0),
                'table_fontsize': 10.2,
                'left_row_count': 12,
                'right_row_count': 8,
                'note_line_count': 3,
            },
        },
        {
            'name': 'long note/context text',
            'kwargs': {
                'figure_size': (6.2, 4.0),
                'table_fontsize': 8.8,
                'left_row_count': 6,
                'right_row_count': 8,
                'note_line_count': 10,
            },
        },
        {
            'name': 'small/constrained figure width',
            'kwargs': {
                'figure_size': (4.2, 4.0),
                'table_fontsize': 9.2,
                'left_row_count': 8,
                'right_row_count': 8,
                'note_line_count': 6,
            },
        },
    ]

    for scenario in scenarios:
        rectangles = compute_histogram_panel_layout(**scenario['kwargs'])

        assert not _rectangles_intersect(rectangles['left_table_rect'], rectangles['plot_rect']), scenario['name']
        assert not _rectangles_intersect(rectangles['right_table_rect'], rectangles['note_rect']), scenario['name']

        note_rect = rectangles['note_rect']
        assert note_rect['x'] >= 0.0, scenario['name']
        assert note_rect['y'] >= 0.0, scenario['name']
        assert note_rect['x'] + note_rect['width'] <= 1.0, scenario['name']
        assert note_rect['y'] + note_rect['height'] <= 1.0, scenario['name']

        _assert_no_intersections(rectangles)
