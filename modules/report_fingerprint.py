"""Compatibility helpers for report identity fingerprints."""

from pathlib import Path

from modules.report_repository import compute_sha256


def _mapping_value(mapping, *keys):
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def build_report_fingerprint(report):
    """Build a report-id-first diagnostic fingerprint from a DB row mapping."""
    report_id = _mapping_value(report, "report_id", "REPORT_ID", "ID", "id")
    if report_id is not None:
        return f"report_id:{report_id}"

    sha256_value = _mapping_value(report, "sha256", "SHA256")
    if sha256_value is not None:
        return f"sha256:{sha256_value}"

    identity_hash = _mapping_value(report, "identity_hash", "IDENTITY_HASH")
    if identity_hash is not None:
        return f"identity_hash:{identity_hash}"

    return "unresolved"


def _get_attr(obj, *names):
    for name in names:
        value = getattr(obj, name, None)
        if value not in (None, ""):
            return value
    return None


def build_parser_fingerprint(report_parser):
    """Build a parser diagnostic fingerprint without filename-composite identity."""
    sha256_value = _get_attr(report_parser, "sha256", "source_sha256")
    if sha256_value is not None:
        return f"sha256:{sha256_value}"

    report_id = _get_attr(report_parser, "report_id")
    if report_id is not None:
        return f"report_id:{report_id}"

    identity_hash = _get_attr(report_parser, "identity_hash", "_metadata_identity_hash")
    if identity_hash is not None:
        return f"identity_hash:{identity_hash}"

    source_path = _get_attr(report_parser, "source_path")
    if source_path is None:
        file_path = _get_attr(report_parser, "file_path", "pdf_file_path")
        file_name = _get_attr(report_parser, "file_name", "pdf_file_name")
        source_path = Path(str(file_path)) / str(file_name) if file_path and file_name else None

    if source_path is not None and Path(source_path).is_file():
        return f"sha256:{compute_sha256(source_path)}"

    return "unresolved"
