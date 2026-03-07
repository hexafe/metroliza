"""Helpers for Google export stage/status and conversion metadata shaping."""

from __future__ import annotations


_GOOGLE_STAGE_LABELS = {
    "generating": "Google export stage: generating workbook",
    "uploading": "Google export stage: uploading",
    "converting": "Google export stage: converting",
    "validating": "Google export stage: validating",
    "completed": "Google export stage: completed",
    "fallback": "Google export stage: fallback",
}


def build_google_stage_message(stage: str, detail: str = "") -> str | None:
    """Build the user-facing stage message line for Google conversion progress."""

    base = _GOOGLE_STAGE_LABELS.get(stage)
    if not base:
        return None
    if detail:
        return f"{base} ({detail})"
    return base


def build_google_conversion_metadata(conversion) -> dict:
    """Build completion metadata payload from a conversion result object."""

    return {
        "converted_file_id": conversion.file_id,
        "converted_url": conversion.web_url,
        "local_xlsx_path": conversion.local_xlsx_path,
        "fallback_message": conversion.fallback_message,
        "conversion_warnings": list(conversion.warnings),
        "conversion_warning_details": list(getattr(conversion, "warning_details", ())),
        "converted_tab_titles": list(getattr(conversion, "converted_tab_titles", ())),
    }


def build_google_fallback_metadata(*, excel_file: str, error: Exception) -> dict:
    """Build completion metadata payload for local-xlsx fallback after conversion error."""

    return {
        "fallback_message": f"Google export failed; using local .xlsx fallback: {excel_file}",
        "conversion_warnings": [str(error)],
    }
