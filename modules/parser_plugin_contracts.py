"""Parser plugin contracts and canonical V2 schema models.

This module defines the stable plugin interface and parse result structures used by
report parser plugins. Contracts are intentionally stdlib-first and dataclass-based
for performance and maintainability.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PluginManifest:
    """Metadata contract for parser plugin registration and selection."""

    plugin_id: str
    display_name: str
    version: str
    supported_formats: tuple[str, ...]
    supported_locales: tuple[str, ...] = ("*",)
    template_ids: tuple[str, ...] = ()
    priority: int = 100
    capabilities: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProbeResult:
    """Detection result returned by plugin probes."""

    plugin_id: str
    can_parse: bool
    confidence: int
    matched_template_id: str | None = None
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParseWarning:
    """Structured parse warning."""

    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True)
class ParseError:
    """Structured parse error."""

    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True)
class ParseMetaV2:
    """Canonical parse metadata for report-level diagnostics and provenance."""

    source_file: str
    source_format: str
    plugin_id: str
    plugin_version: str
    template_id: str | None
    parse_timestamp: str
    locale_detected: str | None
    confidence: int


@dataclass(frozen=True)
class ReportInfoV2:
    """Canonical report identity fields."""

    reference: str
    report_date: str
    sample_number: str
    file_name: str
    file_path: str


@dataclass(frozen=True)
class MeasurementV2:
    """Canonical measurement row representation."""

    axis_code: str
    nominal: float | None
    tol_plus: float | None
    tol_minus: float | None
    bonus: float | None
    measured: float | None
    deviation: float | None
    out_of_tolerance: float | None
    raw_tokens: tuple[str, ...] = ()
    raw_line_refs: tuple[int, ...] = ()
    extensions: dict[str, str | float | int | bool | None] = field(default_factory=dict)


@dataclass(frozen=True)
class MeasurementBlockV2:
    """Canonical measurement block representation."""

    header_raw: tuple[str, ...]
    header_normalized: str
    dimensions: tuple[MeasurementV2, ...]
    block_index: int


@dataclass(frozen=True)
class ParseResultV2:
    """Canonical parse output contract for all parser plugins."""

    meta: ParseMetaV2
    report: ReportInfoV2
    blocks: tuple[MeasurementBlockV2, ...]
    warnings: tuple[ParseWarning, ...] = ()
    errors: tuple[ParseError, ...] = ()


@dataclass(frozen=True)
class ProbeContext:
    """Detection context for plugin probes."""

    source_path: str
    source_format: str | None = None


def infer_source_format(file_path: str | Path) -> str:
    """Infer source format from file suffix."""

    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".xlsx", ".xls"}:
        return "excel"
    if suffix == ".csv":
        return "csv"
    return "unknown"


class BaseReportParserPlugin(ABC):
    """Stable interface for all parser plugins."""

    manifest: PluginManifest

    @classmethod
    @abstractmethod
    def probe(cls, input_ref: str | Path, context: ProbeContext) -> ProbeResult:
        """Return plugin match confidence for a given input reference."""

    @abstractmethod
    def parse_to_v2(self) -> ParseResultV2:
        """Return canonical V2 parse output."""

    @staticmethod
    @abstractmethod
    def to_legacy_blocks(parse_result_v2: ParseResultV2):
        """Adapt V2 result into legacy ``blocks_text`` shape during migration."""
