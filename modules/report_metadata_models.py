"""Canonical metadata dataclasses for report metadata extraction."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetadataExtractionContext:
    source_file_id: int | None
    parser_id: str
    source_path: str
    file_name: str
    source_format: str
    page_count: int | None
    first_page_width: float | None
    first_page_height: float | None


@dataclass(frozen=True)
class MetadataCandidate:
    field_name: str
    raw_value: str | None
    normalized_value: str | None
    source_type: str
    source_detail: str | None
    page_number: int | None
    region_name: str | None
    label_text: str | None
    rule_id: str
    confidence: float
    evidence_text: str | None
    selected: bool = False


@dataclass(frozen=True)
class MetadataWarning:
    code: str
    field_name: str | None
    severity: str
    message: str
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalReportMetadata:
    parser_id: str
    template_family: str
    template_variant: str | None
    metadata_confidence: float
    reference: str | None
    reference_raw: str | None
    report_date: str | None
    report_time: str | None
    part_name: str | None
    revision: str | None
    sample_number: str | None
    sample_number_kind: str | None
    stats_count_raw: str | None
    stats_count_int: int | None
    operator_name: str | None
    comment: str | None
    page_count: int | None
    metadata_json: dict
    warnings: tuple[MetadataWarning, ...]


@dataclass(frozen=True)
class MetadataSelectionResult:
    metadata: CanonicalReportMetadata
    candidates: tuple[MetadataCandidate, ...]
