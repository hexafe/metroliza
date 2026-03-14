"""Parser plugin registry and deterministic runtime resolver.

This module keeps compatibility with both:
- new registration: ``register_parser(ParserClass)``
- legacy registration: ``register_parser(format_id, ParserClass, detector=..., manifest=...)``
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Type

from modules.CMMReportParser import CMMReportParser
from modules.parser_plugin_contracts import (
    BaseReportParserPlugin,
    PluginManifest,
    ProbeContext,
    ProbeResult,
    infer_source_format,
)


ParserType = Type[BaseReportParserPlugin]
DetectorType = Callable[[str], ProbeResult]


@dataclass(frozen=True)
class ResolverDiagnostics:
    """Selection diagnostics for plugin resolution."""

    source_path: str
    source_format: str
    candidates_considered: tuple[ProbeResult, ...]
    selected: ProbeResult | None
    rejected_reason: str | None = None


PARSER_MAP: dict[str, ParserType] = {}
PARSER_MANIFESTS: dict[str, PluginManifest] = {}
PARSER_DETECTORS: dict[str, DetectorType] = {}


def _as_file_path(file_path: str | Path) -> str:
    return str(file_path)


def list_plugins() -> tuple[PluginManifest, ...]:
    """Return registered plugin manifests."""

    return tuple(PARSER_MANIFESTS.values())


def plugins_for_format(source_format: str) -> tuple[ParserType, ...]:
    """Return plugins compatible with a source format."""

    return tuple(
        parser_cls
        for plugin_id, parser_cls in PARSER_MAP.items()
        if plugin_id in PARSER_MANIFESTS and source_format in PARSER_MANIFESTS[plugin_id].supported_formats
    )


def _safe_probe(
    plugin_id: str,
    parser_cls: ParserType,
    normalized_path: str,
    probe_context: ProbeContext,
) -> ProbeResult:
    """Run detector/probe and normalize plugin id for compatibility."""

    detector = PARSER_DETECTORS.get(plugin_id)
    if detector is not None:
        result = detector(normalized_path)
    else:
        result = parser_cls.probe(normalized_path, probe_context)

    if result.plugin_id != plugin_id:
        return ProbeResult(
            plugin_id=plugin_id,
            can_parse=result.can_parse,
            confidence=result.confidence,
            matched_template_id=result.matched_template_id,
            reasons=result.reasons,
            warnings=result.warnings,
        )

    return result


def resolve_parser_with_diagnostics(file_path: str | Path) -> ResolverDiagnostics:
    """Resolve plugin using deterministic confidence/priority/id tie-breakers."""

    normalized_path = _as_file_path(file_path)
    source_format = infer_source_format(normalized_path)
    probe_context = ProbeContext(source_path=normalized_path, source_format=source_format)

    candidates: list[ProbeResult] = []
    for plugin_id, parser_cls in PARSER_MAP.items():
        manifest = PARSER_MANIFESTS.get(plugin_id)
        if manifest is None:
            continue
        if source_format not in manifest.supported_formats:
            continue
        candidates.append(_safe_probe(plugin_id, parser_cls, normalized_path, probe_context))

    parseable = [c for c in candidates if c.can_parse]
    if not parseable:
        return ResolverDiagnostics(
            source_path=normalized_path,
            source_format=source_format,
            candidates_considered=tuple(candidates),
            selected=None,
            rejected_reason="no_plugin_can_parse",
        )

    selected = max(
        parseable,
        key=lambda match: (
            match.confidence,
            PARSER_MANIFESTS[match.plugin_id].priority,
            match.plugin_id,
        ),
    )
    return ResolverDiagnostics(
        source_path=normalized_path,
        source_format=source_format,
        candidates_considered=tuple(candidates),
        selected=selected,
    )


def detect_format(file_path: str | Path) -> str:
    """Backward-compatible format identifier detection."""

    diagnostics = resolve_parser_with_diagnostics(file_path)
    return diagnostics.selected.plugin_id if diagnostics.selected else "unknown"


def get_parser(file_path: str | Path, database: str, connection=None):
    """Construct parser instance for a given file path."""

    normalized_path = _as_file_path(file_path)
    diagnostics = resolve_parser_with_diagnostics(normalized_path)
    if diagnostics.selected is None:
        raise ValueError(f"Unsupported report format: unknown ({normalized_path})")

    parser_cls = PARSER_MAP[diagnostics.selected.plugin_id]
    return parser_cls(normalized_path, database, connection=connection)


def _default_manifest(plugin_id: str, parser_cls: ParserType) -> PluginManifest:
    return PluginManifest(
        plugin_id=plugin_id,
        display_name=getattr(parser_cls, "__name__", plugin_id),
        version="1.0.0",
        supported_formats=("pdf",),
    )


def register_parser(
    parser_or_format: ParserType | str,
    parser_cls: ParserType | None = None,
    *,
    detector: DetectorType | None = None,
    manifest: PluginManifest | None = None,
):
    """Register parser plugin class.

    Supported call styles:
    - ``register_parser(ParserClass)``
    - ``register_parser("plugin_id", ParserClass, detector=..., manifest=...)``
    """

    if isinstance(parser_or_format, str):
        if parser_cls is None:
            raise ValueError("parser_cls is required when registering by format id.")
        plugin_id = parser_or_format
        plugin_manifest = manifest or getattr(parser_cls, "manifest", None) or _default_manifest(plugin_id, parser_cls)
        if plugin_manifest.plugin_id != plugin_id:
            plugin_manifest = PluginManifest(
                plugin_id=plugin_id,
                display_name=plugin_manifest.display_name,
                version=plugin_manifest.version,
                supported_formats=plugin_manifest.supported_formats,
                supported_locales=plugin_manifest.supported_locales,
                template_ids=plugin_manifest.template_ids,
                priority=plugin_manifest.priority,
                capabilities=dict(plugin_manifest.capabilities),
            )
    else:
        parser_cls = parser_or_format
        plugin_manifest = manifest or getattr(parser_cls, "manifest", None)
        if plugin_manifest is None:
            raise ValueError("Parser class must define `manifest` or pass `manifest=` during registration.")
        plugin_id = plugin_manifest.plugin_id

    PARSER_MAP[plugin_id] = parser_cls
    PARSER_MANIFESTS[plugin_id] = plugin_manifest
    if detector is not None:
        PARSER_DETECTORS[plugin_id] = detector


register_parser(CMMReportParser)
