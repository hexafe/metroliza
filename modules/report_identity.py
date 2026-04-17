"""Semantic report identity helpers."""

from __future__ import annotations

import hashlib

from modules.report_metadata_models import CanonicalReportMetadata


def _normalize_component(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def build_report_identity_hash(metadata: CanonicalReportMetadata) -> str:
    components = (
        metadata.parser_id,
        metadata.template_family,
        metadata.template_variant,
        metadata.reference,
        metadata.report_date,
        metadata.report_time,
        metadata.part_name,
        metadata.revision,
        metadata.sample_number,
        metadata.page_count,
    )
    payload = "\x1f".join(_normalize_component(component) for component in components)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
