"""Parser registry and factory for report ingestion workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Type

from modules.CMMReportParser import CMMReportParser


@dataclass(frozen=True)
class PluginManifest:
    """Minimal parser plugin metadata used by runtime registry."""

    plugin_id: str
    display_name: str
    version: str
    supported_formats: tuple[str, ...]
    priority: int = 100


@dataclass(frozen=True)
class ProbeResult:
    """Detection result used by parser format resolution."""

    format_id: str
    can_parse: bool
    confidence: int
    reasons: tuple[str, ...] = ()


ParserType = Type
DetectorType = Callable[[str], ProbeResult]


PARSER_MAP: dict[str, ParserType] = {}
PARSER_MANIFESTS: dict[str, PluginManifest] = {}
PARSER_DETECTORS: dict[str, DetectorType] = {}


def _as_file_path(file_path: str | Path) -> str:
    return str(file_path)


def _default_cmm_detector(file_path: str) -> ProbeResult:
    if file_path.lower().endswith('.pdf'):
        return ProbeResult(
            format_id='cmm',
            can_parse=True,
            confidence=100,
            reasons=('pdf_extension',),
        )
    return ProbeResult(format_id='cmm', can_parse=False, confidence=0, reasons=('unsupported_extension',))


def detect_format(file_path: str | Path) -> str:
    normalized_path = _as_file_path(file_path)
    matches = [
        detector(normalized_path)
        for detector in PARSER_DETECTORS.values()
    ]
    best_match = max(
        (match for match in matches if match.can_parse),
        key=lambda match: match.confidence,
        default=None,
    )
    return best_match.format_id if best_match is not None else 'unknown'


def get_parser(file_path: str | Path, database: str, connection=None):
    normalized_path = _as_file_path(file_path)
    format_id = detect_format(normalized_path)
    parser_cls = PARSER_MAP.get(format_id)
    if parser_cls is None:
        raise ValueError(f"Unsupported report format: {format_id} ({normalized_path})")
    return parser_cls(normalized_path, database, connection=connection)


def register_parser(
    format_id: str,
    parser_cls: ParserType,
    *,
    detector: DetectorType | None = None,
    manifest: PluginManifest | None = None,
):
    """Register parser plugin and optional detector/manifest metadata."""

    PARSER_MAP[format_id] = parser_cls
    if detector is not None:
        PARSER_DETECTORS[format_id] = detector
    if manifest is not None:
        PARSER_MANIFESTS[format_id] = manifest


register_parser(
    'cmm',
    CMMReportParser,
    detector=_default_cmm_detector,
    manifest=PluginManifest(
        plugin_id='cmm',
        display_name='CMM PDF Parser',
        version='1.0.0',
        supported_formats=('pdf',),
        priority=100,
    ),
)
