"""High-level orchestration for report metadata extraction."""

from __future__ import annotations

from modules.report_metadata_models import MetadataExtractionContext, MetadataSelectionResult
from modules.report_metadata_profiles import DEFAULT_CMM_PDF_HEADER_BOX_PROFILE, get_metadata_profile
from modules.report_metadata_selector import select_report_metadata


def extract_report_metadata(
    context: MetadataExtractionContext,
    *,
    header_items=None,
    filename: str | None = None,
    ocr_fallback=None,
    parser_id: str | None = None,
    template_family: str | None = None,
) -> MetadataSelectionResult:
    resolved_parser_id = parser_id or context.parser_id
    resolved_template_family = template_family or DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.template_family
    profile = get_metadata_profile(resolved_parser_id, resolved_template_family)
    if profile is None:
        profile = DEFAULT_CMM_PDF_HEADER_BOX_PROFILE

    return select_report_metadata(
        context=context,
        profile=profile,
        header_items=header_items,
        filename=filename or context.file_name,
        ocr_fallback=ocr_fallback,
    )
