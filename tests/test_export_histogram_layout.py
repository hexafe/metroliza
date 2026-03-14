import pytest

from modules.export_histogram_layout import (
    HISTOGRAM_MIN_NOTE_HEIGHT,
    HISTOGRAM_MIN_PLOT_WIDTH,
    assert_non_overlapping_rectangles,
    compute_histogram_panel_layout,
    rectangles_overlap,
)


def test_rectangles_overlap_detects_intersection_and_touching_edges_are_safe():
    a = {'x': 0.10, 'y': 0.10, 'width': 0.20, 'height': 0.20}
    b = {'x': 0.25, 'y': 0.25, 'width': 0.20, 'height': 0.20}
    c = {'x': 0.30, 'y': 0.10, 'width': 0.20, 'height': 0.20}

    assert rectangles_overlap(a, b)
    assert not rectangles_overlap(a, c)


def test_compute_histogram_panel_layout_returns_non_intersecting_panels():
    rects = compute_histogram_panel_layout(
        (6.2, 4),
        table_fontsize=9.0,
        left_row_count=8,
        right_row_count=12,
        note_line_count=4,
    )

    assert rects['plot_rect']['width'] >= HISTOGRAM_MIN_PLOT_WIDTH - 1e-9
    assert rects['note_rect']['height'] >= HISTOGRAM_MIN_NOTE_HEIGHT
    assert_non_overlapping_rectangles(rects)


def test_compute_histogram_panel_layout_shrinks_side_content_before_plot_overlap():
    rects = compute_histogram_panel_layout(
        (4.6, 4),
        table_fontsize=11.0,
        left_row_count=30,
        right_row_count=30,
        note_line_count=12,
    )

    assert rects['plot_rect']['width'] >= HISTOGRAM_MIN_PLOT_WIDTH - 1e-9
    assert rects['right_table_rect']['y'] >= rects['note_rect']['y'] + rects['note_rect']['height']


def test_assert_non_overlapping_rectangles_raises_for_invalid_overlap():
    with pytest.raises(AssertionError):
        assert_non_overlapping_rectangles(
            {
                'left_table_rect': {'x': 0.1, 'y': 0.2, 'width': 0.4, 'height': 0.6},
                'plot_rect': {'x': 0.45, 'y': 0.2, 'width': 0.4, 'height': 0.6},
            }
        )
