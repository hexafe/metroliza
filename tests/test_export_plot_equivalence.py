"""Strict #1126 reference-export harness; references are captured before edits.

Set METROLIZA_PLOT_BASE and METROLIZA_PLOT_CANDIDATE to two XLSX paths to
compare a captured pre-change export with a candidate on the same machine.
No customer data or platform-specific golden bitmaps belong in the repository.
"""

from io import BytesIO
import os
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image
import pytest


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


def test_annotation_candidates_draw_only_once_and_tables_never_draw(monkeypatch):
    import matplotlib.pyplot as plt
    from metroliza.exporting.export_data_thread import (
        render_histogram_annotations, render_panel_table_in_panel_axes,
    )

    fig, ax = plt.subplots(figsize=(5, 3))
    try:
        ax.set_xlim(0, 10)
        calls = []
        original_draw = fig.canvas.draw
        def draw():
            calls.append(1)
            return original_draw()
        monkeypatch.setattr(fig.canvas, 'draw', draw)
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


@pytest.mark.skipif(not os.environ.get('METROLIZA_PLOT_BASE'), reason='Needs captured synthetic exports')
def test_captured_prechange_export_equivalence():
    assert_equivalent_workbooks(
        Path(os.environ['METROLIZA_PLOT_BASE']),
        Path(os.environ['METROLIZA_PLOT_CANDIDATE']),
    )
