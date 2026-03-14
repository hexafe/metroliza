from modules.export_workbook_planning_helpers import (
    compute_histogram_font_sizes,
    compute_histogram_three_region_layout,
    compute_histogram_table_layout,
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
