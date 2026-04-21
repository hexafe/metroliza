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
