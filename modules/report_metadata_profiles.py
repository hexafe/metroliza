"""Code-based metadata profile definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from modules.header_ocr_corrections import canonicalize_header_text_for_variant, compact_token
from modules.report_metadata_models import MetadataWarning
from modules.report_metadata_normalizers import (
    normalize_comment,
    normalize_operator_name,
    normalize_part_name,
    normalize_reference,
    normalize_report_date,
    normalize_report_time,
    normalize_revision,
    normalize_sample_number,
    normalize_stats_count,
)


@dataclass(frozen=True)
class PositionalCell:
    field_name: str
    row_index: int
    x0_ratio: float
    x1_ratio: float
    source_detail: str


@dataclass(frozen=True)
class MetadataProfile:
    parser_id: str
    template_family: str
    supported_source_formats: tuple[str, ...]
    header_band_fraction: float
    label_aliases: dict[str, tuple[str, ...]]
    field_priority_rules: dict[str, tuple[str, ...]]
    fallback_rules: dict[str, tuple[str, ...]]
    positional_cells: dict[str, tuple[PositionalCell, ...]]
    field_normalizers: dict[str, Callable[[str | None], object]]
    template_variant_detector: Callable[[str], tuple[str | None, tuple[MetadataWarning, ...]]]


def _detect_cmm_pdf_header_box_variant(header_text: str) -> tuple[str | None, tuple[MetadataWarning, ...]]:
    normalized = canonicalize_header_text_for_variant(header_text).upper()
    compact = compact_token(normalized)
    has_serial = (
        ("SERNUMBER" in compact or "SERNUNBER" in compact or "SERIALNUMBER" in compact)
        and ("REVNUMBER" in compact or "REVNUNBER" in compact)
    )
    has_drawing = (
        ("DRAWINGNO" in compact or "DRAWINGN0" in compact or "DRAWINGNUMBER" in compact)
        and "DRAWINGREV" in compact
    )

    if has_serial:
        return "cmm_pdf_header_box_serial_variant", ()
    if has_drawing:
        return "cmm_pdf_header_box_drawing_variant", ()

    warning = MetadataWarning(
        code="template_variant_unresolved",
        field_name=None,
        severity="warning",
        message="Template variant could not be resolved from page 1 header text.",
        details={},
    )
    return None, (warning,)


def _stats_count_normalizer(value: str | None) -> tuple[str | None, int | None]:
    return normalize_stats_count(value)


_HEADER_BOX_POSITIONAL_CELLS = (
    PositionalCell("part_name", 0, 0.24, 0.74, "row0_part_name_cell"),
    PositionalCell("report_date", 0, 0.74, 0.88, "row0_date_cell"),
    PositionalCell("report_time", 0, 0.88, 0.96, "row0_time_cell"),
    PositionalCell("revision", 1, 0.24, 0.50, "row1_revision_cell"),
    PositionalCell("reference", 1, 0.50, 0.74, "row1_reference_cell"),
    PositionalCell("stats_count_raw", 1, 0.74, 0.96, "row1_stats_count_cell"),
    PositionalCell("operator_name", 2, 0.24, 0.50, "row2_operator_cell"),
    PositionalCell("comment", 2, 0.50, 0.96, "row2_comment_cell"),
)


DEFAULT_CMM_PDF_HEADER_BOX_PROFILE = MetadataProfile(
    parser_id="cmm_pdf_header_box",
    template_family="cmm_pdf_header_box",
    supported_source_formats=("pdf",),
    header_band_fraction=0.22,
    label_aliases={
        "reference": (
            "REFERENCE",
            "SER NUMBER",
            "SER NUNBER",
            "SERNUMBER",
            "SERNUNBER",
            "SERIAL NUMBER",
            "SERIALNUMBER",
            "DRAWING NO",
            "DRAWING No",
            "DRAWING N0",
            "DRAWINGNO",
            "DRAWINGN0",
            "DRAWING NUMBER",
            "REF",
        ),
        "report_date": ("DATE", "REPORT DATE"),
        "report_time": ("TIME", "REPORT TIME"),
        "part_name": ("PART NAME", "PARTNAME", "PART NANE", "PARTNANE", "PART"),
        "revision": (
            "REVISION",
            "REV NUMBER",
            "REV NUMBERE",
            "REV NUNBER",
            "REVNUMBER",
            "REVNUMBERE",
            "REVNUNBER",
            "DRAWING REV",
            "DRAWINGREV",
        ),
        "sample_number": ("SAMPLE NUMBER",),
        "stats_count_raw": ("STATS COUNT", "STATSCOUNT", "STATS C0UNT", "STATSC0UNT"),
        "operator_name": (
            "MEASUREMENT MADE BY",
            "MEASUREMENT MADEBY",
            "MEASUREMENT NADE BY",
            "MEASUREMENT ON CMM SYSTEM",
            "MEASUREMENT",
            "OPERATOR",
        ),
        "comment": ("COMMENT",),
    },
    field_priority_rules={
        "reference": ("position_cell", "header_exact", "header_alias", "filename_candidate", "unknown"),
        "report_date": ("position_cell", "header_exact", "header_alias", "filename_candidate", "unknown"),
        "report_time": ("position_cell", "header_exact", "header_alias", "unknown"),
        "part_name": ("position_cell", "header_exact", "header_alias", "filename_candidate", "unknown"),
        "revision": ("position_cell", "header_exact", "header_alias", "unknown"),
        "stats_count_raw": ("position_cell", "header_exact", "header_alias", "filename_candidate", "unknown"),
        "sample_number": (
            "explicit_sample_number",
            "comment_derived",
            "projected_from_stats_count",
            "filename_candidate",
            "unknown",
        ),
        "operator_name": ("position_cell", "header_exact", "header_alias", "unknown"),
        "comment": ("position_cell", "header_exact", "header_alias", "unknown"),
    },
    fallback_rules={
        "reference": ("filename_reference", "unknown"),
        "report_date": ("filename_date", "unknown"),
        "report_time": ("unknown",),
        "part_name": ("filename_middle_tokens", "unknown"),
        "revision": ("unknown",),
        "stats_count_raw": ("filename_tail", "unknown"),
        "sample_number": ("selected_stats_count", "filename_tail", "unknown"),
        "operator_name": ("unknown",),
        "comment": ("unknown",),
    },
    positional_cells={
        "cmm_pdf_header_box_serial_variant": _HEADER_BOX_POSITIONAL_CELLS,
        "cmm_pdf_header_box_drawing_variant": _HEADER_BOX_POSITIONAL_CELLS,
    },
    field_normalizers={
        "reference": normalize_reference,
        "report_date": normalize_report_date,
        "report_time": normalize_report_time,
        "part_name": normalize_part_name,
        "revision": normalize_revision,
        "sample_number": normalize_sample_number,
        "stats_count_raw": _stats_count_normalizer,
        "operator_name": normalize_operator_name,
        "comment": normalize_comment,
    },
    template_variant_detector=_detect_cmm_pdf_header_box_variant,
)


PROFILE_REGISTRY = {
    (DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.parser_id, DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.template_family): DEFAULT_CMM_PDF_HEADER_BOX_PROFILE,
}


def get_metadata_profile(parser_id: str, template_family: str) -> MetadataProfile | None:
    return PROFILE_REGISTRY.get((parser_id, template_family))


def iter_metadata_profiles() -> tuple[MetadataProfile, ...]:
    return tuple(PROFILE_REGISTRY.values())
