"""Code-based metadata profile definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

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
class MetadataProfile:
    parser_id: str
    template_family: str
    supported_source_formats: tuple[str, ...]
    header_band_fraction: float
    label_aliases: dict[str, tuple[str, ...]]
    field_priority_rules: dict[str, tuple[str, ...]]
    fallback_rules: dict[str, tuple[str, ...]]
    field_normalizers: dict[str, Callable[[str | None], object]]
    template_variant_detector: Callable[[str], tuple[str | None, tuple[MetadataWarning, ...]]]


def _detect_cmm_pdf_header_box_variant(header_text: str) -> tuple[str | None, tuple[MetadataWarning, ...]]:
    normalized = header_text.upper()
    has_serial = "SER NUMBER" in normalized and "REV NUMBER" in normalized
    has_drawing = ("DRAWING NO" in normalized or "DRAWING NO." in normalized) and "DRAWING REV" in normalized

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


DEFAULT_CMM_PDF_HEADER_BOX_PROFILE = MetadataProfile(
    parser_id="cmm_pdf_header_box",
    template_family="cmm_pdf_header_box",
    supported_source_formats=("pdf",),
    header_band_fraction=0.22,
    label_aliases={
        "reference": ("REFERENCE", "SER NUMBER", "SERIAL NUMBER", "DRAWING NO", "DRAWING NUMBER", "REF"),
        "report_date": ("DATE", "REPORT DATE"),
        "report_time": ("TIME", "REPORT TIME"),
        "part_name": ("PART NAME", "PART"),
        "revision": ("REVISION", "REV NUMBER", "DRAWING REV"),
        "sample_number": ("SAMPLE NUMBER",),
        "stats_count_raw": ("STATS COUNT",),
        "operator_name": ("MEASUREMENT MADE BY", "OPERATOR"),
        "comment": ("COMMENT",),
    },
    field_priority_rules={
        "reference": ("header_exact", "header_alias", "filename_candidate", "unknown"),
        "report_date": ("header_exact", "header_alias", "filename_candidate", "unknown"),
        "report_time": ("header_exact", "header_alias", "unknown"),
        "part_name": ("header_exact", "header_alias", "filename_candidate", "unknown"),
        "revision": ("header_exact", "header_alias", "unknown"),
        "stats_count_raw": ("header_exact", "header_alias", "filename_candidate", "unknown"),
        "sample_number": ("explicit_sample_number", "projected_from_stats_count", "filename_candidate", "unknown"),
        "operator_name": ("header_exact", "header_alias", "unknown"),
        "comment": ("header_exact", "header_alias", "unknown"),
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
