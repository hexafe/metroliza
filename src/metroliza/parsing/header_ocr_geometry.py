"""Header OCR geometry helpers for crop selection and page-space conversion.

The parser will use these helpers to choose a single top-of-page header crop and
translate OCR pixel boxes back into the page coordinate system expected by
``modules.report_metadata_selector.HeaderTextItem``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class HeaderCropSelection:
    """Selected page crop for header OCR."""

    bbox: tuple[float, float, float, float]
    source: str
    page_width: float
    page_height: float
    candidate_count: int
    selected_candidate_index: int | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _page_rect(page: Any) -> Any:
    rect = getattr(page, "rect", None)
    if rect is None:
        raise ValueError("Page object must expose a rect with width and height.")
    return rect


def _page_size(page: Any) -> tuple[float, float]:
    rect = _page_rect(page)
    width = float(getattr(rect, "width", 0.0) or 0.0)
    height = float(getattr(rect, "height", 0.0) or 0.0)
    if width <= 0 or height <= 0:
        raise ValueError("Page rect must expose positive width and height.")
    return width, height


def _rect_tuple(bbox: Any) -> tuple[float, float, float, float] | None:
    if bbox is None:
        return None
    if isinstance(bbox, Mapping):
        keys = ("x0", "y0", "x1", "y1")
        if all(key in bbox for key in keys):
            return tuple(float(bbox[key]) for key in keys)  # type: ignore[return-value]
        return None
    if isinstance(bbox, Sequence) and len(bbox) == 4:
        try:
            return (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        except (TypeError, ValueError):
            return None
    return None


def _clamp_bbox(
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    *,
    margin: float,
    bottom_limit: float | None = None,
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    y1_limit = page_height if bottom_limit is None else min(page_height, bottom_limit)
    return (
        max(0.0, x0 - margin),
        max(0.0, y0 - margin),
        min(page_width, x1 + margin),
        min(y1_limit, y1 + margin),
    )


def _bbox_width(bbox: tuple[float, float, float, float]) -> float:
    return max(0.0, bbox[2] - bbox[0])


def _bbox_height(bbox: tuple[float, float, float, float]) -> float:
    return max(0.0, bbox[3] - bbox[1])


def _block_candidates(
    page: Any,
    *,
    page_width: float,
    page_height: float,
    top_limit_fraction: float,
    min_width_fraction: float,
) -> list[dict[str, Any]]:
    try:
        blocks = page.get_text("dict").get("blocks", ())
    except Exception:
        return []

    top_limit = page_height * top_limit_fraction
    min_width = page_width * min_width_fraction
    candidates: list[dict[str, Any]] = []

    for index, block in enumerate(blocks):
        if block.get("type") != 1:
            continue
        bbox = _rect_tuple(block.get("bbox"))
        if bbox is None:
            continue
        if bbox[1] > top_limit or _bbox_width(bbox) < min_width:
            continue
        candidates.append(
            {
                "index": index,
                "bbox": bbox,
                "width": _bbox_width(bbox),
                "height": _bbox_height(bbox),
                "area": _bbox_width(bbox) * _bbox_height(bbox),
            }
        )

    return candidates


def select_header_crop(
    page: Any,
    *,
    header_band_fraction: float = 0.22,
    top_limit_fraction: float = 0.24,
    min_width_fraction: float = 0.45,
    max_header_height_fraction: float = 0.18,
    margin: float = 3.0,
) -> HeaderCropSelection:
    """Choose a single top-of-page crop for header OCR.

    The selector prefers a single image block near the top of the page. If one is
    found, it is clamped to a header-height band instead of unioning multiple
    blocks. When no suitable image block exists, the function falls back to a
    height-limited crop across the page width.
    """

    page_width, page_height = _page_size(page)
    candidates = _block_candidates(
        page,
        page_width=page_width,
        page_height=page_height,
        top_limit_fraction=top_limit_fraction,
        min_width_fraction=min_width_fraction,
    )

    fallback_bbox = (0.0, 0.0, page_width, page_height * header_band_fraction)
    diagnostics: dict[str, Any] = {
        "page_size": (page_width, page_height),
        "header_band_fraction": header_band_fraction,
        "top_limit_fraction": top_limit_fraction,
        "min_width_fraction": min_width_fraction,
        "max_header_height_fraction": max_header_height_fraction,
        "candidate_bboxes": tuple(candidate["bbox"] for candidate in candidates),
    }

    if not candidates:
        diagnostics["selection_reason"] = "no_image_candidate"
        return HeaderCropSelection(
            bbox=fallback_bbox,
            source="top_band",
            page_width=page_width,
            page_height=page_height,
            candidate_count=0,
            diagnostics=diagnostics,
        )

    max_header_height = page_height * max_header_height_fraction
    selected_index, selected_candidate = min(
        enumerate(candidates),
        key=lambda item: (
            item[1]["height"] > max_header_height,
            item[1]["bbox"][1],
            -item[1]["width"],
            -item[1]["area"],
            item[1]["bbox"][0],
        ),
    )
    selected_bbox = _clamp_bbox(
        selected_candidate["bbox"],
        page_width,
        page_height,
        margin=margin,
        bottom_limit=page_height * header_band_fraction,
    )

    if _bbox_height(selected_bbox) <= 0 or _bbox_width(selected_bbox) <= 0:
        diagnostics["selection_reason"] = "candidate_clamped_to_empty"
        return HeaderCropSelection(
            bbox=fallback_bbox,
            source="top_band",
            page_width=page_width,
            page_height=page_height,
            candidate_count=len(candidates),
            selected_candidate_index=selected_index,
            diagnostics=diagnostics,
        )

    diagnostics.update(
        {
            "selection_reason": "image_block",
            "selected_candidate_bbox": selected_candidate["bbox"],
            "selected_candidate_clamped": selected_bbox != selected_candidate["bbox"],
            "selected_candidate_height_over_limit": selected_candidate["height"]
            > max_header_height,
            "selected_candidate_index": selected_index,
        }
    )

    return HeaderCropSelection(
        bbox=selected_bbox,
        source="top_image_block",
        page_width=page_width,
        page_height=page_height,
        candidate_count=len(candidates),
        selected_candidate_index=selected_index,
        diagnostics=diagnostics,
    )


def _record_get(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def _box_points(box: Any) -> list[tuple[float, float]] | None:
    if box is None:
        return None
    if isinstance(box, Mapping):
        nested = box.get("box") if "box" in box else None
        if nested is not None:
            return _box_points(nested)
        rect = _rect_tuple(box)
        if rect is not None:
            x0, y0, x1, y1 = rect
            return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        return None
    if isinstance(box, Sequence) and len(box) == 4 and all(
        isinstance(item, (int, float)) for item in box
    ):
        x0, y0, x1, y1 = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if isinstance(box, Sequence):
        points: list[tuple[float, float]] = []
        for point in box:
            if not isinstance(point, Sequence) or len(point) < 2:
                continue
            try:
                points.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
        return points or None
    return None


def _box_bounds(box: Any) -> tuple[float, float, float, float] | None:
    points = _box_points(box)
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def convert_pixel_box_to_page_bbox(
    box: Any,
    *,
    crop_bbox: tuple[float, float, float, float],
    crop_pixel_size: tuple[float, float],
) -> tuple[float, float, float, float] | None:
    """Convert an OCR pixel box inside a crop into page-space coordinates."""

    pixel_bounds = _box_bounds(box)
    if pixel_bounds is None:
        return None

    pixel_width = float(crop_pixel_size[0] or 0.0)
    pixel_height = float(crop_pixel_size[1] or 0.0)
    if pixel_width <= 0 or pixel_height <= 0:
        raise ValueError("Crop pixel size must be positive.")

    crop_x0, crop_y0, crop_x1, crop_y1 = crop_bbox
    crop_width = crop_x1 - crop_x0
    crop_height = crop_y1 - crop_y0

    scale_x = crop_width / pixel_width
    scale_y = crop_height / pixel_height

    return (
        crop_x0 + pixel_bounds[0] * scale_x,
        crop_y0 + pixel_bounds[1] * scale_y,
        crop_x0 + pixel_bounds[2] * scale_x,
        crop_y0 + pixel_bounds[3] * scale_y,
    )


def _record_to_mapping(record: Any, *, source_name: str) -> Mapping[str, Any]:
    if isinstance(record, Mapping):
        return record

    diagnostics = _record_get(record, "diagnostics", {})
    if diagnostics is None:
        diagnostics = {}

    return {
        "text": _record_get(record, "text", ""),
        "confidence": _record_get(record, "confidence", None),
        "box": _record_get(record, "box", None),
        "source": _record_get(record, "source", source_name),
        "diagnostics": diagnostics,
    }


def convert_ocr_records_to_header_items(
    records: Sequence[Any],
    *,
    crop_bbox: tuple[float, float, float, float],
    crop_pixel_size: tuple[float, float],
    page_number: int = 1,
    region_name: str = "page1_header_band_ocr",
    source_name: str = "rapidocr_latin",
    header_crop_source: str | None = None,
) -> list[dict[str, Any]]:
    """Convert OCR records into ``HeaderTextItem``-compatible dictionaries."""

    items: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        mapping = _record_to_mapping(record, source_name=source_name)
        text = str(mapping.get("text", "")).strip()
        if not text:
            continue

        confidence = mapping.get("confidence", None)
        try:
            confidence_value = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence_value = None

        pixel_box = mapping.get("box")
        page_box = convert_pixel_box_to_page_bbox(
            pixel_box,
            crop_bbox=crop_bbox,
            crop_pixel_size=crop_pixel_size,
        )
        item: dict[str, Any] = {
            "text": text,
            "x0": page_box[0] if page_box is not None else None,
            "y0": page_box[1] if page_box is not None else None,
            "x1": page_box[2] if page_box is not None else None,
            "y1": page_box[3] if page_box is not None else None,
            "page_number": page_number,
            "region_name": region_name,
            "confidence": confidence_value,
            "source": source_name,
            "ocr_source": mapping.get("source", source_name),
            "ocr_box": _box_points(pixel_box),
            "ocr_pixel_box": _box_bounds(pixel_box),
            "ocr_record_index": index,
            "ocr_diagnostics": mapping.get("diagnostics", {}),
            "header_crop_bbox": crop_bbox,
        }
        if header_crop_source is not None:
            item["header_crop_source"] = header_crop_source
        items.append(item)

    return items
