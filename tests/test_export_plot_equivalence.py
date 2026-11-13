"""Strict #1126 reference-export harness; references are captured before edits.

Set METROLIZA_PLOT_BASE and METROLIZA_PLOT_CANDIDATE to two XLSX paths to
compare a captured pre-change export with a candidate on the same machine.
No customer data or platform-specific golden bitmaps belong in the repository.
"""

from io import BytesIO
import importlib.util
import os
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image
import pytest


def _uncached_text_extent(fig, renderer, text, fontsize, fontweight):
    from matplotlib.text import Text
    from metroliza.exporting.export_data_thread import _uses_symbol_font_fallback

    kwargs = dict(fontsize=fontsize, fontweight=fontweight, alpha=0.0)
    if _uses_symbol_font_fallback(text):
        kwargs['fontfamily'] = 'DejaVu Sans'
    probe = Text(0.0, 0.0, str(text), **kwargs)
    probe.set_figure(fig)
    extent = probe.get_window_extent(renderer=renderer)
    return extent.width, extent.height


@pytest.mark.parametrize('dpi', [72, 100, 150])
@pytest.mark.parametrize('weight', ['normal', 'bold'])
def test_panel_measurement_matches_uncached_text_exactly(dpi, weight):
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    from metroliza.exporting.export_data_thread import _measure_text_extent

    fig, _ = plt.subplots(dpi=dpi)
    try:
        for family in ['DejaVu Sans', 'DejaVu Serif']:
            with mpl.rc_context({'font.family': family}):
                renderer = fig.canvas.get_renderer()
                for text in ['Ag', 'Value', '1.234', 'two\nlines', '✓ Pass ×', '$x^2$', '']:
                    expected = _uncached_text_extent(fig, renderer, text, 8.4, weight)
                    for _ in range(2):
                        assert _measure_text_extent(
                            fig, renderer, text, fontsize=8.4, fontweight=weight,
                        ) == expected
        fig.set_dpi(dpi * 2)
        renderer = fig.canvas.get_renderer()
        assert _measure_text_extent(fig, renderer, 'Ag', fontsize=9) == (
            _uncached_text_extent(fig, renderer, 'Ag', 9, 'normal')
        )
    finally:
        plt.close(fig)


def test_panel_measurement_cache_reuses_probes_and_bounds_renderer_lifetime(monkeypatch):
    import matplotlib.pyplot as plt
    from metroliza.exporting import export_data_thread as module

    fig, _ = plt.subplots()
    try:
        renderer = fig.canvas.get_renderer()
        original_text = module.Text
        probes = []

        def text_probe(*args, **kwargs):
            probes.append(1)
            return original_text(*args, **kwargs)

        monkeypatch.setattr(module, 'Text', text_probe)
        expected = module._measure_text_extent(fig, renderer, 'Ag', fontsize=8)
        assert module._measure_text_extent(fig, renderer, 'Ag', fontsize=8) == expected
        assert len(probes) == 1
        for index in range(module._TEXT_EXTENT_CACHE_SIZE + 1):
            module._measure_text_extent(fig, renderer, str(index), fontsize=8)
        assert len(renderer._metroliza_text_extents) == module._TEXT_EXTENT_CACHE_SIZE
        before = len(probes)
        module._measure_text_extent(fig, renderer, 'Ag', fontsize=8)
        assert len(probes) == before + 1  # Oldest entry was evicted.
        fig.set_dpi(fig.dpi * 2)
        other_renderer = fig.canvas.get_renderer()
        assert other_renderer is not renderer
        module._measure_text_extent(fig, other_renderer, 'Ag', fontsize=8)
        assert len(probes) == before + 2
    finally:
        plt.close(fig)


def assert_equivalent_pngs(expected, actual):
    """Allow only isolated one-level antialiasing noise, never layout drift."""
    left = np.asarray(Image.open(BytesIO(expected)).convert('RGBA'), dtype=np.int16)
    right = np.asarray(Image.open(BytesIO(actual)).convert('RGBA'), dtype=np.int16)
    assert left.shape == right.shape
    delta = np.abs(left - right)
    assert delta.max() <= 1, 'A channel changed by more than 1/255'
    assert delta.mean() <= 0.0001, 'Mean channel error exceeds 0.0001/255'
    assert np.any(delta, axis=2).mean() <= 0.0001, 'More than 0.01% of pixels changed'


def assert_equivalent_workbooks(expected, actual):
    """Compare all workbook content/anchors byte for byte and every PNG pixel.

    Only document creation/modification timestamps are ignored. Drawing XML,
    cell values/formulas/styles, chart XML, relationships and PNG sizes match.
    """
    with zipfile.ZipFile(expected) as left, zipfile.ZipFile(actual) as right:
        assert left.namelist() == right.namelist()
        image_count = 0
        for name in left.namelist():
            if name == 'docProps/core.xml':
                continue
            if name.endswith('.png'):
                assert_equivalent_pngs(left.read(name), right.read(name))
                image_count += 1
            else:
                assert left.read(name) == right.read(name), name
        assert image_count > 0, 'The reference must exercise PNG rendering'
        return image_count


def test_png_equivalence_rejects_one_pixel_annotation_shift():
    image = Image.new('RGBA', (100, 100), 'white')
    image.putpixel((40, 40), (0, 0, 0, 255))
    left = BytesIO()
    image.save(left, format='PNG')
    image.putpixel((40, 40), (255, 255, 255, 255))
    image.putpixel((41, 40), (0, 0, 0, 255))
    right = BytesIO()
    image.save(right, format='PNG')
    with pytest.raises(AssertionError):
        assert_equivalent_pngs(left.getvalue(), right.getvalue())
    assert_equivalent_pngs(left.getvalue(), left.getvalue())


def test_annotation_candidates_layout_once_and_tables_never_draw(monkeypatch):
    import matplotlib.pyplot as plt
    from metroliza.exporting.export_data_thread import (
        render_histogram_annotations, render_panel_table_in_panel_axes,
    )

    fig, ax = plt.subplots(figsize=(5, 3))
    try:
        ax.set_xlim(0, 10)
        calls = []
        original_draw = fig.draw_without_rendering
        def draw():
            calls.append(1)
            return original_draw()
        monkeypatch.setattr(fig, 'draw_without_rendering', draw)
        monkeypatch.setattr(fig.canvas, 'draw', lambda: pytest.fail('Layout must not rasterize'))
        annotations = [dict(x=5., text='Overlapping specification label', color='black',
                            kind='usl', priority=i, text_y_axes=1.02) for i in range(3)]
        rendered = render_histogram_annotations(
            ax, annotations, annotation_fontsize=8,
            annotation_box=dict(boxstyle='round,pad=0.2', fc='white'),
        )
        assert len(calls) == 1
        assert rendered
        render_panel_table_in_panel_axes(
            ax=ax, title='Parameter', rows=[('Average', '10.123'), ('NOK', '0%')],
        )
        assert len(calls) == 1
    finally:
        plt.close(fig)


def _annotation_scene(module, positions):
    import matplotlib.pyplot as plt

    module.apply_summary_plot_theme()
    fig, ax = plt.subplots(figsize=(6, 4))
    try:
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 1)
        title = module.render_histogram_figure_title(fig, 'Synthetic collision / edge case')
        specs = [dict(x=x, text=f'{kind.upper()} = {x:.3f}', color='black', kind=kind,
                      priority=priority, text_y_axes=1.02)
                 for x, kind, priority in zip(positions, ['mean', 'lsl', 'usl'], [300, 200, 100])]
        artists = module.render_histogram_annotations(
            ax, specs, annotation_fontsize=9,
            annotation_box=dict(boxstyle='round,pad=0.2', fc='white', title_artist=title,
                                plot_rect=dict(x=.125, y=.11, width=.775, height=.77)),
        )
        decisions = [(type(a).__name__, a.get_text(), a.get_position(), a.get_ha()) for a in artists]
        png = BytesIO()
        fig.savefig(png, format='png', dpi=100)
        return decisions, png.getvalue()
    finally:
        plt.close(fig)


@pytest.mark.skipif(not os.environ.get('METROLIZA_PLOT_REFERENCE_MODULE'), reason='Needs base source capture')
@pytest.mark.parametrize('positions', [(5., 5.01, 5.02), (5., 0., 10.), (0.02, 0., 0.04)])
def test_prechange_collision_and_edge_layout(positions):
    from metroliza.exporting import export_data_thread as candidate

    spec = importlib.util.spec_from_file_location(
        '_1126_reference', os.environ['METROLIZA_PLOT_REFERENCE_MODULE'],
    )
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    expected_decisions, expected_png = _annotation_scene(reference, positions)
    actual_decisions, actual_png = _annotation_scene(candidate, positions)
    assert actual_decisions == expected_decisions
    assert_equivalent_pngs(expected_png, actual_png)


@pytest.mark.skipif(not os.environ.get('METROLIZA_PLOT_BASE'), reason='Needs captured synthetic exports')
def test_captured_prechange_export_equivalence():
    assert_equivalent_workbooks(
        Path(os.environ['METROLIZA_PLOT_BASE']),
        Path(os.environ['METROLIZA_PLOT_CANDIDATE']),
    )


# Frozen measuring renderer from the T01 admission base (45d14391).
# Keep this independent of the optimized renderer: it is the layout/PNG oracle.
def _render_panel_table_before_t01(
    *,
    ax,
    fig,
    title,
    rows,
    rect,
    style_options=None,
):
    """Render a non-overlapping side panel table with dynamic width/height fitting.

    Returns metadata describing used bounds, overflow, deferred rows, and fallbacks.
    """

    from functools import lru_cache
    from metroliza.exporting.export_data_thread import (
        _measure_text_extent, _uses_symbol_font_fallback, _wrap_table_value_text,
        apply_explicit_table_row_heights, resolve_table_row_line_count,
    )

    options = dict(style_options or {})
    base_fontsize = float(options.get('fontsize', 8.0))
    min_fontsize = float(options.get('min_fontsize', 6.8))
    max_fontsize = float(options.get('max_fontsize', 9.0))
    fontsize = min(max(base_fontsize, min_fontsize), max_fontsize)

    min_label_fraction = float(options.get('min_label_fraction', 0.52))
    min_value_fraction = float(options.get('min_value_fraction', 0.22))
    header_fontweight = options.get('header_fontweight', 'bold')
    compact_label_mapping = dict(options.get('compact_label_mapping') or {})
    value_wrap_width = int(options.get('value_wrap_width', 0) or 0)
    cell_padding_points = float(options.get('cell_padding_points', 2.2))
    explicit_row_heights = options.get('explicit_row_heights')
    shared_row_metrics = options.get('shared_row_metrics')
    explicit_label_fraction = options.get('explicit_label_fraction')
    explicit_value_fraction = options.get('explicit_value_fraction')

    normalized_rows = []
    for row in rows or []:
        if len(row) >= 2:
            label_text = str(row[0])
            value_text = str(row[-1])
            if value_wrap_width > 0:
                value_text = _wrap_table_value_text(value_text, width=value_wrap_width)
            normalized_rows.append((label_text, value_text))

    # Panel axes geometry and text metrics do not require rendering any artists.
    renderer = fig.canvas.get_renderer()
    ax_height_px = max(1.0, float(ax.bbox.height))
    available_height_px = max(1.0, rect['height'] * ax_height_px)
    cell_padding_px = cell_padding_points * (fig.dpi / 72.0)

    state_rows = list(normalized_rows)
    applied_fallbacks = []
    using_compact_labels = False

    @lru_cache(maxsize=256)
    def _measure(text, fontsize, fontweight='normal'):
        return _measure_text_extent(fig, renderer, text, fontsize=fontsize, fontweight=fontweight)

    def _measure_layout(candidate_rows, candidate_fontsize):
        label_header_w, header_h = _measure(title, candidate_fontsize, header_fontweight)
        value_header_w, _ = _measure('Value', candidate_fontsize, header_fontweight)
        line_h = _measure('Ag', candidate_fontsize)[1]

        label_max = label_header_w
        value_max = value_header_w
        for label, value in candidate_rows:
            label_max = max(label_max, _measure(label, candidate_fontsize)[0])
            value_max = max(value_max, _measure(value, candidate_fontsize)[0])

        required_total_w = label_max + value_max + (4.0 * cell_padding_px)
        dynamic_label_fraction = (label_max + (2.0 * cell_padding_px)) / required_total_w if required_total_w > 0 else 0.5
        dynamic_value_fraction = (value_max + (2.0 * cell_padding_px)) / required_total_w if required_total_w > 0 else 0.5

        if explicit_label_fraction is not None and explicit_value_fraction is not None:
            label_fraction = max(0.0, float(explicit_label_fraction))
            value_fraction = max(0.0, float(explicit_value_fraction))
        else:
            label_fraction = max(min_label_fraction, dynamic_label_fraction)
            value_fraction = max(min_value_fraction, dynamic_value_fraction)
        total_fraction = label_fraction + value_fraction
        if total_fraction <= 0.0:
            label_fraction = 0.5
            value_fraction = 0.5
        elif total_fraction != 1.0:
            label_fraction /= total_fraction
            value_fraction /= total_fraction

        if shared_row_metrics:
            header_height_px = float(shared_row_metrics['header_row_height_px'])
            row_height_px = float(shared_row_metrics['base_row_height_px'])
            extra_line_height_px = float(shared_row_metrics['extra_line_height_px'])
        else:
            header_height_px = header_h + (2.0 * cell_padding_px)
            row_height_px = line_h + (2.0 * cell_padding_px)
            extra_line_height_px = row_height_px
        required_rows_height_px = 0.0
        for label, value in candidate_rows:
            line_count = resolve_table_row_line_count(label, value)
            required_rows_height_px += row_height_px + ((line_count - 1) * extra_line_height_px)
        required_height_px = header_height_px + required_rows_height_px

        return {
            'label_fraction': label_fraction,
            'value_fraction': value_fraction,
            'required_height_px': required_height_px,
            'row_height_px': row_height_px,
        }

    metrics = _measure_layout(state_rows, fontsize)

    if metrics['required_height_px'] > available_height_px and compact_label_mapping:
        compacted_rows = [(compact_label_mapping.get(label, label), value) for (label, value) in state_rows]
        compact_metrics = _measure_layout(compacted_rows, fontsize)
        if compact_metrics['required_height_px'] <= metrics['required_height_px']:
            state_rows = compacted_rows
            metrics = compact_metrics
            using_compact_labels = True
            applied_fallbacks.append('compact_label_mapping')

    while metrics['required_height_px'] > available_height_px and fontsize > min_fontsize:
        fontsize = max(min_fontsize, fontsize - 0.4)
        metrics = _measure_layout(state_rows, fontsize)
    if fontsize < base_fontsize:
        applied_fallbacks.append('reduced_fontsize')

    overflow_rows = []
    deferred_rows = []

    table = ax.table(
        cellText=state_rows,
        colLabels=[title, 'Value'],
        cellLoc='center',
        colWidths=[metrics['label_fraction'], metrics['value_fraction']],
        bbox=[rect['x'], rect['y'], rect['width'], rect['height']],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(fontsize)

    for (row_index, col_index), cell in table.get_celld().items():
        cell.PAD = max(cell.PAD, cell_padding_points / 10.0)
        txt = cell.get_text()
        if row_index == 0:
            txt.set_fontweight(header_fontweight)
            txt.set_fontsize(fontsize * 1.05)
        else:
            txt.set_fontsize(fontsize)
        if col_index == 0:
            txt.set_ha('left')
        else:
            txt.set_ha('right')
        txt.set_va('center')
        if _uses_symbol_font_fallback(txt.get_text()):
            txt.set_fontfamily('DejaVu Sans')

    row_heights = None
    if explicit_row_heights:
        row_heights = [float(v) for v in explicit_row_heights]
        apply_explicit_table_row_heights(table, row_heights=row_heights, ncols=2)

    return {
        'table': table,
        'used_bounds': dict(rect),
        'overflow': metrics['required_height_px'] > available_height_px,
        'overflow_rows': overflow_rows,
        'deferred_rows': deferred_rows,
        'rendered_rows': state_rows,
        'font_size': fontsize,
        'used_compact_labels': using_compact_labels,
        'fallbacks_applied': applied_fallbacks,
        'explicit_row_heights': row_heights,
    }



_PANEL_ROWS = [
    [('Average', '12.345'), ('Count', '1500'), ('NOK', '0%')],
    [('Long parameter\nlabel', '12.345'), ('Second\nparameter', '0.001'), ('Count', '1500')],
    [('Description', 'A very long synthetic value for wrapping'), ('Range', '12345678901234567890'), ('N', '1500')],
    [('Pass ✓', '✓ Pass ×'), ('Sigma σ', 'μ ± 1.23'), ('Count', '1500')],
    [('Fit', '$x^2$'), ('Value', 'first\nsecond\nthird'), ('Status', 'OK')],
    [(123, None), ('Blank', ''), ('Finite', '-0.000000')],
]


def _panel_scene(renderer, content, layout, style_overrides=None):
    import matplotlib as mpl
    import matplotlib.pyplot as plt

    rows = _PANEL_ROWS[content]
    with mpl.rc_context({'font.family': 'DejaVu Serif'}):
        fig, ax = plt.subplots(figsize=(4.5, 2.8), dpi=100)
        try:
            ax.set_axis_off()
            options = {
                'fontsize': 9.0, 'min_fontsize': 6.8,
                'explicit_label_fraction': 0.63,
                'explicit_value_fraction': 0.37,
                'shared_row_metrics': {
                    'header_row_height_px': 20., 'base_row_height_px': 18.,
                    'extra_line_height_px': 15.,
                },
                'explicit_row_heights': [0.22, 0.26, 0.26, 0.26],
            }
            rect = dict(x=.03, y=.03, width=.94, height=.9)
            if layout in ('overflow', 'compact'):
                rect['height'] = .08
            if layout == 'compact':
                options['compact_label_mapping'] = {
                    str(label): f'L{i}' for i, (label, _) in enumerate(rows)
                }
            if layout == 'wrapped':
                options['value_wrap_width'] = 8
                options['explicit_label_fraction'] = 2.
                options['explicit_value_fraction'] = 1.
            if layout == 'default':
                options = None
            elif layout == 'empty':
                options = {}
            else:
                options.update(style_overrides or {})
            meta = renderer(ax=ax, fig=fig, title='Parameter ✓', rows=rows,
                            rect=rect, style_options=options)
            snapshot = {key: value for key, value in meta.items() if key != 'table'}
            png = BytesIO()
            fig.savefig(png, format='png', dpi=100)
            snapshot['cells'] = {
                key: (cell.get_text().get_text(), cell.get_width(), cell.get_height(),
                      cell.get_text().get_fontsize(), cell.get_text().get_fontweight(),
                      tuple(cell.get_text().get_fontfamily()), cell.get_text().get_ha(),
                      cell.get_text().get_va(), cell.get_xy(), cell.PAD)
                for key, cell in meta['table'].get_celld().items()
            }
            return snapshot, png.getvalue()
        finally:
            plt.close(fig)


@pytest.mark.parametrize('content', range(6))
@pytest.mark.parametrize('layout', ['fit', 'overflow', 'compact', 'wrapped'])
def test_panel_table_t01_exact_prechange_equivalence(content, layout):
    """Compare metadata, cells and literal PNGs with the frozen measuring path."""
    from metroliza.exporting.export_data_thread import render_panel_table

    expected, expected_png = _panel_scene(_render_panel_table_before_t01, content, layout)
    actual, actual_png = _panel_scene(render_panel_table, content, layout)
    assert actual == expected
    assert actual_png == expected_png
    assert actual['overflow'] == (layout in ('overflow', 'compact'))
    if layout in ('overflow', 'compact'):
        assert actual['font_size'] == 6.8
    assert actual['used_compact_labels'] == (layout == 'compact')
    capture = os.environ.get('METROLIZA_PANEL_CAPTURE_DIR')
    if capture:
        import json

        target = Path(capture)
        target.mkdir(parents=True, exist_ok=True)
        stem = f'{layout}-{content}'
        (target / f'{stem}-reference.png').write_bytes(expected_png)
        (target / f'{stem}-candidate.png').write_bytes(actual_png)
        (target / f'{stem}.json').write_text(json.dumps(
            {**actual, 'cells': {str(key): value for key, value in actual['cells'].items()}},
            sort_keys=True, indent=2,
        ))


@pytest.mark.parametrize('layout', ['fit', 'overflow', 'compact', 'wrapped'])
def test_panel_table_t01_skips_overridden_measurements(monkeypatch, layout):
    from metroliza.exporting import export_data_thread as module

    def discarded_measurement(*args, **kwargs):
        pytest.fail('Explicit widths and shared metrics must skip text measurement')

    monkeypatch.setattr(module, '_measure_text_extent', discarded_measurement)
    _panel_scene(module.render_panel_table, 3, layout)


@pytest.mark.parametrize('style_overrides', [
    {'explicit_label_fraction': None},
    {'explicit_value_fraction': None},
    {'explicit_label_fraction': None, 'explicit_value_fraction': None},
    {'shared_row_metrics': None},
    {'shared_row_metrics': {}},
    {'explicit_label_fraction': None, 'shared_row_metrics': {}},
])
def test_panel_table_t01_incomplete_overrides_keep_measuring(monkeypatch, style_overrides):
    from metroliza.exporting import export_data_thread as module

    expected, expected_png = _panel_scene(
        _render_panel_table_before_t01, 2, 'wrapped', style_overrides,
    )
    original = module._measure_text_extent
    calls = []

    def measure(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, '_measure_text_extent', measure)
    actual, actual_png = _panel_scene(module.render_panel_table, 2, 'wrapped', style_overrides)
    assert calls, 'Incomplete overrides must retain the general measuring path'
    assert actual == expected
    assert actual_png == expected_png


@pytest.mark.parametrize('fractions', [(0., 0.), (-1., 2.), (2., 3.)])
def test_panel_table_t01_explicit_fraction_normalization(monkeypatch, fractions):
    from metroliza.exporting import export_data_thread as module

    options = dict(zip(['explicit_label_fraction', 'explicit_value_fraction'], fractions))
    expected, expected_png = _panel_scene(_render_panel_table_before_t01, 0, 'fit', options)
    monkeypatch.setattr(module, '_measure_text_extent',
                        lambda *args, **kwargs: pytest.fail('Metrics are fully overridden'))
    actual, actual_png = _panel_scene(module.render_panel_table, 0, 'fit', options)
    assert actual == expected
    assert actual_png == expected_png


def test_panel_table_t01_incomplete_shared_metrics_preserve_error():
    from metroliza.exporting.export_data_thread import render_panel_table

    for renderer in (_render_panel_table_before_t01, render_panel_table):
        with pytest.raises(KeyError, match='base_row_height_px'):
            _panel_scene(renderer, 0, 'fit', {
                'shared_row_metrics': {'header_row_height_px': 20.},
            })


@pytest.mark.parametrize('layout', ['default', 'empty'])
def test_panel_table_t01_empty_styles_keep_measuring(monkeypatch, layout):
    from metroliza.exporting import export_data_thread as module

    expected, expected_png = _panel_scene(_render_panel_table_before_t01, 0, layout)
    original = module._measure_text_extent
    calls = []

    def measure(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, '_measure_text_extent', measure)
    actual, actual_png = _panel_scene(module.render_panel_table, 0, layout)
    assert calls
    assert actual == expected
    assert actual_png == expected_png


@pytest.mark.parametrize('change', ['text', 'width', 'font', 'height'])
def test_panel_table_t01_reference_detects_cell_changes(change):
    expected, expected_png = _panel_scene(_render_panel_table_before_t01, 0, 'fit')

    def changed_renderer(**kwargs):
        meta = _render_panel_table_before_t01(**kwargs)
        cell = meta['table'][(1, 0)]
        if change == 'text':
            cell.get_text().set_text('Changed')
        elif change == 'width':
            cell.set_width(cell.get_width() * .8)
        elif change == 'font':
            cell.get_text().set_fontsize(6.)
        else:
            cell.set_height(cell.get_height() * .8)
        return meta

    actual, actual_png = _panel_scene(changed_renderer, 0, 'fit')
    assert actual != expected
    assert actual_png != expected_png
