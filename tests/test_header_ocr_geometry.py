from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.header_ocr_backend import HeaderOcrRecord
from modules.header_ocr_geometry import (
    convert_ocr_records_to_header_items,
    select_header_crop,
)
from modules.report_metadata_selector import _as_text_item


class _FakePage:
    def __init__(self, width: float, height: float, blocks: list[dict]):
        self.rect = SimpleNamespace(
            width=width,
            height=height,
            x0=0.0,
            y0=0.0,
            x1=width,
            y1=height,
        )
        self._blocks = blocks

    def get_text(self, mode: str):
        assert mode == "dict"
        return {"blocks": self._blocks}


def test_select_header_crop_prefers_one_top_image_block_instead_of_union():
    page = _FakePage(
        1000.0,
        2000.0,
        [
            {"type": 1, "bbox": (10.0, 12.0, 510.0, 180.0)},
            {"type": 1, "bbox": (520.0, 14.0, 980.0, 190.0)},
        ],
    )

    selection = select_header_crop(page)

    assert selection.source == "top_image_block"
    assert selection.selected_candidate_index == 0
    assert selection.candidate_count == 2
    assert selection.bbox[0] <= 10.0
    assert selection.bbox[2] < 600.0
    assert selection.diagnostics["selected_candidate_bbox"] == (10.0, 12.0, 510.0, 180.0)


def test_select_header_crop_uses_top_band_when_no_image_candidate_exists():
    page = _FakePage(
        1200.0,
        1800.0,
        [{"type": 0, "bbox": (0.0, 0.0, 1200.0, 200.0)}],
    )

    selection = select_header_crop(page, header_band_fraction=0.16)

    assert selection.source == "top_band"
    assert selection.candidate_count == 0
    assert selection.bbox == (0.0, 0.0, 1200.0, 288.0)
    assert selection.diagnostics["selection_reason"] == "no_image_candidate"


def test_convert_ocr_records_to_header_items_scales_boxes_and_preserves_diagnostics():
    records = [
        HeaderOcrRecord(
            text="REFERENCE",
            confidence=0.87,
            box=((100.0, 200.0), (300.0, 200.0), (300.0, 400.0), (100.0, 400.0)),
            source="rapidocr_latin",
            diagnostics={"raw_index": 0, "raw_shape": "attribute_arrays"},
        )
    ]

    items = convert_ocr_records_to_header_items(
        records,
        crop_bbox=(10.0, 20.0, 110.0, 220.0),
        crop_pixel_size=(1000.0, 1000.0),
        page_number=1,
        region_name="page1_header_band_ocr",
        header_crop_source="top_image_block",
    )

    assert len(items) == 1
    item = items[0]
    assert item["text"] == "REFERENCE"
    assert item["confidence"] == pytest.approx(0.87)
    assert item["x0"] == pytest.approx(20.0)
    assert item["y0"] == pytest.approx(60.0)
    assert item["x1"] == pytest.approx(40.0)
    assert item["y1"] == pytest.approx(100.0)
    assert item["source"] == "rapidocr_latin"
    assert item["header_crop_source"] == "top_image_block"
    assert item["ocr_diagnostics"]["raw_index"] == 0

    text_item = _as_text_item(item)
    assert text_item.text == "REFERENCE"
    assert text_item.x0 == pytest.approx(20.0)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_native_mixed_image_geometry_matches_literal_dict_contract(rotation):
    """Image block indices include intervening text blocks, even on rotated pages."""
    from io import BytesIO

    from PIL import Image
    from metroliza.parsing.header_ocr_geometry import _block_candidates
    from metroliza.parsing.pdf_backend import require_pdf_backend

    image = BytesIO()
    Image.new("RGB", (20, 10), "red").save(image, format="PNG")
    with require_pdf_backend().open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text((20, 20), "first text")
        page.insert_image((30, 40, 570, 120), stream=image.getvalue(), keep_proportion=False)
        page.insert_text((20, 160), "second text")
        page.insert_image((30, 170, 570, 200), stream=image.getvalue(), keep_proportion=False)
        page.insert_image((30, 500, 570, 600), stream=image.getvalue(), keep_proportion=False)
        page.set_rotation(rotation)
        # Pass fixed unrotated bounds to expose the mixed-block index independently.
        candidates = _block_candidates(page, page_width=600, page_height=800,
                                       top_limit_fraction=0.24, min_width_fraction=0.45)
        assert candidates == [
            {"index": 1, "bbox": (30.0, 40.0, 570.0, 120.0),
             "width": 540.0, "height": 80.0, "area": 43200.0},
            {"index": 3, "bbox": (30.0, 170.0, 570.0, 200.0),
             "width": 540.0, "height": 30.0, "area": 16200.0},
        ]
        class DictPage:
            rect = page.rect

            def get_text(self, mode):
                return page.get_text(mode)

        # The adapter deliberately retains the original dict path as an oracle.
        assert select_header_crop(page) == select_header_crop(DictPage())


def test_geometry_backend_error_keeps_empty_candidates():
    from metroliza.parsing.header_ocr_geometry import _block_candidates

    class BrokenPage:
        def get_text(self, mode):
            raise RuntimeError("broken image dictionary")

    assert _block_candidates(BrokenPage(), page_width=600, page_height=800,
                             top_limit_fraction=0.24, min_width_fraction=0.45) == []


@pytest.mark.parametrize("image_bbox", [(-10, 40, 590, 120), (10, -10, 590, 120),
                                         (10, 40, 610, 120), (10, 740, 590, 830),
                                         (700, 40, 1280, 120), (-700, 40, -100, 120)])
def test_native_partially_clipped_image_keeps_original_dict_geometry(image_bbox):
    from io import BytesIO
    from PIL import Image
    from metroliza.parsing.pdf_backend import require_pdf_backend

    image = BytesIO()
    Image.new("RGB", (20, 10), "blue").save(image, format="PNG")
    with require_pdf_backend().open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text((20, 20), "text before image")
        page.insert_image(image_bbox, stream=image.getvalue(), keep_proportion=False)
        page.insert_image((30, 130, 570, 180), stream=image.getvalue(), keep_proportion=False)

        class DictPage:
            rect = page.rect

            def get_text(self, mode):
                return page.get_text(mode)

        assert select_header_crop(page) == select_header_crop(DictPage())


def test_native_custom_dictionary_guard_keeps_original_dispatch():
    from metroliza.parsing.pdf_backend import require_pdf_backend

    class TrapDict(dict):
        def __contains__(self, key):
            pytest.fail("native guard must not invoke custom dictionary membership")

    with require_pdf_backend().open() as document:
        page = document.new_page(width=600, height=800)
        page.__dict__ = TrapDict(page.__dict__)
        assert select_header_crop(page).source == "top_band"


@pytest.mark.parametrize("stateful", [False, True])
def test_native_raw_method_key_keeps_single_lookup_and_geometry(stateful):
    from io import BytesIO
    from PIL import Image
    from metroliza.parsing.header_ocr_geometry import _block_candidates
    from metroliza.parsing.pdf_backend import require_pdf_backend

    events = []

    class Key(str):
        __hash__ = str.__hash__

        def __eq__(self, other):
            result = stateful and bool(events)
            events.append(result)
            return result

    image = BytesIO()
    Image.new("RGB", (20, 10), "red").save(image, format="PNG")
    with require_pdf_backend().open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_image((30, 40, 570, 120), stream=image.getvalue(), keep_proportion=False)
        object.__getattribute__(page, "__dict__")[Key("get_text")] = None
        actual = _block_candidates(page, page_width=600, page_height=800,
                                   top_limit_fraction=0.24, min_width_fraction=0.45)
        assert actual == [{"index": 0, "bbox": (30.0, 40.0, 570.0, 120.0),
                           "width": 540.0, "height": 80.0, "area": 43200.0}]
        assert events == [False]
