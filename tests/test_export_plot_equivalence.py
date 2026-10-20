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
