import pytest
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

from modules.export_histogram_layout import (
    HISTOGRAM_OUTER_PADDING_BOTTOM,
    HISTOGRAM_OUTER_PADDING_TOP,
    HISTOGRAM_TITLE_BAND_HEIGHT,
    HISTOGRAM_MIN_NOTE_HEIGHT,
    HISTOGRAM_MIN_PLOT_WIDTH,
    compute_panel_table_content_height,
    assert_non_overlapping_rectangles,
    compute_histogram_panel_layout,
    compute_histogram_plot_with_right_info_layout,
    rectangles_overlap,
    resolve_inner_table_rect,
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


def test_compute_histogram_panel_layout_supports_independent_side_width_hints():
    rects = compute_histogram_panel_layout(
        (6.2, 4),
        table_fontsize=8.8,
        left_row_count=6,
        right_row_count=8,
        note_line_count=3,
        left_panel_width_hint=0.26,
        right_panel_width_hint=0.19,
    )
    assert rects['left_table_rect']['width'] > rects['right_table_rect']['width']
    assert rects['plot_rect']['width'] >= HISTOGRAM_MIN_PLOT_WIDTH - 1e-9


def test_compute_histogram_panel_layout_preserves_safe_gutter_with_wider_export_geometry():
    rects = compute_histogram_panel_layout(
        (7.2, 4.0),
        table_fontsize=8.8,
        left_row_count=8,
        right_row_count=9,
        note_line_count=3,
        left_panel_width_hint=0.27,
        right_panel_width_hint=0.19,
    )

    left_right_edge = rects['left_table_rect']['x'] + rects['left_table_rect']['width']
    plot_left_edge = rects['plot_rect']['x']
    assert rects['left_table_rect']['width'] > rects['right_table_rect']['width']
    assert rects['plot_rect']['width'] >= HISTOGRAM_MIN_PLOT_WIDTH - 1e-9
    assert (plot_left_edge - left_right_edge) >= 0.022 - 1e-9
    assert_non_overlapping_rectangles(rects)


def test_compute_histogram_panel_layout_uses_separate_top_and_bottom_padding():
    rects = compute_histogram_panel_layout((6.0, 4.0))
    assert rects['plot_rect']['y'] == pytest.approx(HISTOGRAM_OUTER_PADDING_BOTTOM)
    plot_top = rects['plot_rect']['y'] + rects['plot_rect']['height']
    assert (1.0 - plot_top) == pytest.approx(HISTOGRAM_OUTER_PADDING_TOP)


def test_resolve_inner_table_rect_limits_table_height_to_content():
    panel_rect = {'x': 0.1, 'y': 0.2, 'width': 0.3, 'height': 0.6}
    inner_rect = resolve_inner_table_rect(panel_rect, row_count=4, row_height=0.06, header_rows=1, pad_y=0.02)
    expected_height = compute_panel_table_content_height(4, header_rows=1, row_height=0.06, pad_y=0.02)
    assert inner_rect['height'] == pytest.approx(expected_height)
    assert inner_rect['y'] > panel_rect['y']


def test_assert_non_overlapping_rectangles_raises_for_invalid_overlap():
    with pytest.raises(AssertionError):
        assert_non_overlapping_rectangles(
            {
                'left_table_rect': {'x': 0.1, 'y': 0.2, 'width': 0.4, 'height': 0.6},
                'plot_rect': {'x': 0.45, 'y': 0.2, 'width': 0.4, 'height': 0.6},
            }
        )


def _axes_bounds(ax):
    box = ax.get_position()
    return (box.x0, box.y0, box.width, box.height)


def test_histogram_export_uses_dedicated_panel_axes_geometry():
    fig = plt.figure(figsize=(6.2, 4.0))
    try:
        rects = compute_histogram_panel_layout(
            (6.2, 4.0),
            table_fontsize=9.0,
            left_row_count=6,
            right_row_count=10,
            note_line_count=4,
        )
        left_ax = fig.add_axes([
            rects['left_table_rect']['x'],
            rects['left_table_rect']['y'],
            rects['left_table_rect']['width'],
            rects['left_table_rect']['height'],
        ])
        plot_ax = fig.add_axes([
            rects['plot_rect']['x'],
            rects['plot_rect']['y'],
            rects['plot_rect']['width'],
            rects['plot_rect']['height'],
        ])
        right_ax = fig.add_axes([
            rects['right_table_rect']['x'],
            rects['right_table_rect']['y'],
            rects['right_table_rect']['width'],
            rects['right_table_rect']['height'],
        ])
        note_ax = fig.add_axes([
            rects['note_rect']['x'],
            rects['note_rect']['y'],
            rects['note_rect']['width'],
            rects['note_rect']['height'],
        ])

        for axis_name, axis in (
            ('left_table_rect', left_ax),
            ('plot_rect', plot_ax),
            ('right_table_rect', right_ax),
            ('note_rect', note_ax),
        ):
            bounds = _axes_bounds(axis)
            target = rects[axis_name]
            assert bounds == pytest.approx(
                (target['x'], target['y'], target['width'], target['height']),
                abs=1e-6,
            )
    finally:
        plt.close(fig)


def test_histogram_panel_axes_rectangles_do_not_overlap():
    fig = plt.figure(figsize=(6.2, 4.0))
    try:
        rects = compute_histogram_panel_layout(
            (6.2, 4.0),
            table_fontsize=9.0,
            left_row_count=10,
            right_row_count=12,
            note_line_count=5,
        )
        axes = {
            'left_table_rect': fig.add_axes([
                rects['left_table_rect']['x'],
                rects['left_table_rect']['y'],
                rects['left_table_rect']['width'],
                rects['left_table_rect']['height'],
            ]),
            'plot_rect': fig.add_axes([
                rects['plot_rect']['x'],
                rects['plot_rect']['y'],
                rects['plot_rect']['width'],
                rects['plot_rect']['height'],
            ]),
            'right_table_rect': fig.add_axes([
                rects['right_table_rect']['x'],
                rects['right_table_rect']['y'],
                rects['right_table_rect']['width'],
                rects['right_table_rect']['height'],
            ]),
            'note_rect': fig.add_axes([
                rects['note_rect']['x'],
                rects['note_rect']['y'],
                rects['note_rect']['width'],
                rects['note_rect']['height'],
            ]),
        }

        names = list(axes.keys())
        for i, left in enumerate(names):
            left_bounds = _axes_bounds(axes[left])
            left_rect = {'x': left_bounds[0], 'y': left_bounds[1], 'width': left_bounds[2], 'height': left_bounds[3]}
            for right in names[i + 1 :]:
                right_bounds = _axes_bounds(axes[right])
                right_rect = {'x': right_bounds[0], 'y': right_bounds[1], 'width': right_bounds[2], 'height': right_bounds[3]}
                assert not rectangles_overlap(left_rect, right_rect)
    finally:
        plt.close(fig)



def test_compute_histogram_plot_with_right_info_layout_reserves_title_band_above_plot():
    rects = compute_histogram_plot_with_right_info_layout((8.4, 4.0), table_fontsize=8.8, fit_row_count=8, stats_row_count=9)

    plot_top = rects['plot_rect']['y'] + rects['plot_rect']['height']
    expected_top = 1.0 - HISTOGRAM_OUTER_PADDING_TOP - HISTOGRAM_TITLE_BAND_HEIGHT
    assert plot_top == pytest.approx(expected_top)


def test_compute_histogram_plot_with_right_info_layout_geometry_and_nesting():
    rects = compute_histogram_plot_with_right_info_layout(
        (8.4, 4.0),
        table_fontsize=8.8,
        fit_row_count=8,
        stats_row_count=9,
        note_line_count=3,
        right_container_width_hint=0.34,
    )

    assert rects['plot_rect']['width'] >= HISTOGRAM_MIN_PLOT_WIDTH - 1e-9
    assert rects['plot_rect']['width'] > rects['right_container_rect']['width']
    assert rects['fit_table_rect']['x'] >= rects['right_container_rect']['x']
    assert rects['stats_table_rect']['x'] >= rects['right_container_rect']['x']
    assert rects['fit_table_rect']['x'] == pytest.approx(rects['right_container_rect']['x'])
    assert rects['stats_table_rect']['x'] == pytest.approx(rects['right_container_rect']['x'])
    assert rects['fit_table_rect']['width'] == pytest.approx(rects['right_container_rect']['width'])
    assert rects['stats_table_rect']['width'] == pytest.approx(rects['right_container_rect']['width'])
    assert rects['footer_rect']['x'] == pytest.approx(rects['right_container_rect']['x'])
    assert rects['footer_rect']['width'] == pytest.approx(rects['right_container_rect']['width'])
    assert rects['footer_rect']['height'] == pytest.approx(0.0)
    assert rects['fit_table_rect']['y'] + rects['fit_table_rect']['height'] <= rects['stats_table_rect']['y'] + 1e-9
    assert rects['footer_rect']['y'] + rects['footer_rect']['height'] <= rects['fit_table_rect']['y'] + 1e-9
    assert_non_overlapping_rectangles({
        'plot_rect': rects['plot_rect'],
        'fit_table_rect': rects['fit_table_rect'],
        'stats_table_rect': rects['stats_table_rect'],
        'footer_rect': rects['footer_rect'],
    })


def test_histogram_right_info_layout_keeps_plot_dominant_vs_old_composition():
    legacy = compute_histogram_panel_layout(
        (7.2, 4.0),
        table_fontsize=8.8,
        left_row_count=8,
        right_row_count=9,
        note_line_count=3,
        left_panel_width_hint=0.27,
        right_panel_width_hint=0.19,
    )
    final = compute_histogram_plot_with_right_info_layout(
        (8.4, 4.0),
        table_fontsize=8.8,
        fit_row_count=8,
        stats_row_count=9,
        note_line_count=3,
        right_container_width_hint=0.34,
    )

    assert final['plot_rect']['width'] > legacy['plot_rect']['width']
    assert final['plot_rect']['width'] >= HISTOGRAM_MIN_PLOT_WIDTH - 1e-9
    assert final['right_container_rect']['width'] >= 0.30
