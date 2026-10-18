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


@pytest.mark.skipif(not os.environ.get('METROLIZA_PLOT_BASE'), reason='Needs captured synthetic exports')
def test_captured_prechange_export_equivalence():
    assert_equivalent_workbooks(
        Path(os.environ['METROLIZA_PLOT_BASE']),
        Path(os.environ['METROLIZA_PLOT_CANDIDATE']),
    )
