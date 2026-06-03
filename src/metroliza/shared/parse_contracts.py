"""Lightweight parse request contracts.

This module intentionally avoids analytics, pandas, and chart imports so parser
UI imports stay cheap during application startup.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParseRequest:
    """Request payload for parsing a source directory into a target database."""

    source_directory: str
    db_file: str
    metadata_parsing_mode: str = "complete"
    run_background_metadata_enrichment: bool = False


_PARSE_METADATA_MODE_ALIASES = {
    "light": "light",
    "fast": "light",
    "lite": "light",
    "complete": "complete",
    "full": "complete",
    "standard": "complete",
}


def _validate_db_file_path(db_file: object) -> None:
    if not isinstance(db_file, str) or not db_file.strip():
        raise ValueError("A database file path is required.")


def validate_parse_request(request: ParseRequest) -> ParseRequest:
    """Validate parse request inputs and normalize metadata mode aliases."""

    if not isinstance(request, ParseRequest):
        raise ValueError("Parse request must be provided as a ParseRequest instance.")

    if not isinstance(request.source_directory, str) or not request.source_directory.strip():
        raise ValueError("A source directory is required.")

    _validate_db_file_path(request.db_file)

    mode_value = getattr(request, "metadata_parsing_mode", ParseRequest.metadata_parsing_mode)
    if not isinstance(mode_value, str):
        raise ValueError("metadata_parsing_mode must be provided as a string.")
    metadata_parsing_mode = _PARSE_METADATA_MODE_ALIASES.get(mode_value.strip().lower())
    if metadata_parsing_mode is None:
        raise ValueError(f"Unsupported metadata parsing mode '{mode_value}'.")
    if not isinstance(request.run_background_metadata_enrichment, bool):
        raise ValueError("run_background_metadata_enrichment must be a boolean.")

    return ParseRequest(
        source_directory=request.source_directory,
        db_file=request.db_file,
        metadata_parsing_mode=metadata_parsing_mode,
        run_background_metadata_enrichment=request.run_background_metadata_enrichment,
    )
