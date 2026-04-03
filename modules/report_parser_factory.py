"""Parser plugin registry and deterministic runtime resolver.

This module keeps compatibility with both:
- new registration: ``register_parser(ParserClass)``
- legacy registration: ``register_parser(format_id, ParserClass, detector=..., manifest=...)``
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata as importlib_metadata
import importlib.util
import inspect
import logging
import os
from pathlib import Path
from typing import Callable, Type

from modules.cmm_report_parser import CMMReportParser
from modules import parser_plugin_paths
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


@dataclass(frozen=True)
class ExternalPluginLoadResult:
    """Result summary for external plugin discovery/loading."""

    loaded_plugin_ids: tuple[str, ...]
    loaded_modules: tuple[str, ...]
    loaded_entry_points: tuple[str, ...]
    skipped_paths: tuple[str, ...]
    errors: tuple[str, ...]


PARSER_MAP: dict[str, ParserType] = {}
PARSER_MANIFESTS: dict[str, PluginManifest] = {}
PARSER_DETECTORS: dict[str, DetectorType] = {}
PROBE_RESULT_CACHE: dict[tuple[str, str], ProbeResult] = {}

_EXTERNAL_PLUGINS_LOADED = False
_EXTERNAL_PLUGIN_CONFIG_SIGNATURE: tuple[tuple[str, ...], tuple[str, ...]] | None = None
_EXTERNAL_PLUGIN_ENTRY_POINTS: tuple[object, ...] | None = None
_EXTERNAL_PLUGIN_MODULE_COUNTER = 0

logger = logging.getLogger(__name__)


def _as_file_path(file_path: str | Path) -> str:
    return str(file_path)


def _coerce_string_tuple(values) -> tuple[str, ...]:
    """Return a stable tuple of non-empty string values."""

    if values is None:
        return ()
    if isinstance(values, tuple):
        iterable = values
    elif isinstance(values, (list, set, frozenset)):
        iterable = tuple(values)
    else:
        iterable = (values,)

    coerced: list[str] = []
    for value in iterable:
        text = str(value).strip()
        if text:
            coerced.append(text)
    return tuple(coerced)


def _clamp_confidence(confidence) -> int:
    """Normalize confidence into the supported runtime range."""

    try:
        value = int(confidence)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, value))


def _normalize_probe_result(
    *,
    plugin_id: str,
    raw_result,
    origin: str,
    normalized_path: str,
) -> ProbeResult:
    """Normalize plugin probe output into a safe ProbeResult instance."""

    if not isinstance(raw_result, ProbeResult):
        logger.warning(
            "Parser %s returned invalid probe output for %s: %r",
            origin,
            normalized_path,
            type(raw_result).__name__,
        )
        return ProbeResult(
            plugin_id=plugin_id,
            can_parse=False,
            confidence=0,
            reasons=(f"{origin}_invalid_probe_result",),
            warnings=(f"{origin} returned non-ProbeResult output",),
        )

    normalized_confidence = _clamp_confidence(raw_result.confidence)
    warnings = list(_coerce_string_tuple(raw_result.warnings))
    if normalized_confidence != raw_result.confidence:
        warnings.append(f"confidence_clamped_from_{raw_result.confidence}_to_{normalized_confidence}")
    if raw_result.plugin_id != plugin_id:
        warnings.append(f"plugin_id_normalized_from_{raw_result.plugin_id}")

    return ProbeResult(
        plugin_id=plugin_id,
        can_parse=bool(raw_result.can_parse),
        confidence=normalized_confidence,
        matched_template_id=raw_result.matched_template_id,
        reasons=_coerce_string_tuple(raw_result.reasons),
        warnings=tuple(warnings),
    )


def list_plugins() -> tuple[PluginManifest, ...]:
    """Return registered plugin manifests."""

    return tuple(PARSER_MANIFESTS.values())


def reset_probe_cache() -> None:
    """Clear in-process probe cache (primarily for tests and long-running jobs)."""

    PROBE_RESULT_CACHE.clear()


def reset_external_plugin_loader_state() -> None:
    """Reset external plugin discovery state for tests and controlled reloads."""

    global _EXTERNAL_PLUGINS_LOADED, _EXTERNAL_PLUGIN_CONFIG_SIGNATURE, _EXTERNAL_PLUGIN_ENTRY_POINTS

    _EXTERNAL_PLUGINS_LOADED = False
    _EXTERNAL_PLUGIN_CONFIG_SIGNATURE = None
    _EXTERNAL_PLUGIN_ENTRY_POINTS = None


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
    probe_origin = "detector" if detector is not None else "probe"

    try:
        result = detector(normalized_path) if detector is not None else parser_cls.probe(normalized_path, probe_context)
    except Exception as exc:  # pragma: no cover - defensive hardening
        logger.warning(
            "Parser %s failed for %s on %s: %s",
            probe_origin,
            plugin_id,
            normalized_path,
            exc,
        )
        return ProbeResult(
            plugin_id=plugin_id,
            can_parse=False,
            confidence=0,
            reasons=(f"{probe_origin}_exception",),
            warnings=(f"{parser_cls.__name__} {probe_origin} raised {exc.__class__.__name__}: {exc}",),
        )

    return _normalize_probe_result(
        plugin_id=plugin_id,
        raw_result=result,
        origin=probe_origin,
        normalized_path=normalized_path,
    )


def _strict_matching_enabled() -> bool:
    value = os.getenv("PARSER_STRICT_MATCHING", "true").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _minimum_confidence_for_selection() -> int:
    return 80 if _strict_matching_enabled() else 1


def _probe_with_cache(
    plugin_id: str,
    parser_cls: ParserType,
    normalized_path: str,
    probe_context: ProbeContext,
) -> ProbeResult:
    cache_key = (plugin_id, normalized_path)
    cached = PROBE_RESULT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    result = _safe_probe(plugin_id, parser_cls, normalized_path, probe_context)
    PROBE_RESULT_CACHE[cache_key] = result
    return result


def _iter_external_plugin_candidate_files(path_entry: str) -> list[Path]:
    path = Path(path_entry)
    if not path.exists():
        return []
    if path.is_file():
        if path.suffix == ".py":
            return [path]
        return []

    if not path.is_dir():
        return []

    return sorted(
        file
        for file in path.iterdir()
        if file.is_file() and file.suffix == ".py" and not file.name.startswith("_")
    )


def _next_external_module_name() -> str:
    global _EXTERNAL_PLUGIN_MODULE_COUNTER
    _EXTERNAL_PLUGIN_MODULE_COUNTER += 1
    return f"metroliza_external_parser_plugin_{_EXTERNAL_PLUGIN_MODULE_COUNTER}"


def _discover_plugin_classes_in_module(module) -> list[ParserType]:
    plugin_classes: list[ParserType] = []
    for value in vars(module).values():
        if not inspect.isclass(value):
            continue
        if value is BaseReportParserPlugin:
            continue
        if not issubclass(value, BaseReportParserPlugin):
            continue
        if inspect.isabstract(value):
            continue
        plugin_classes.append(value)
    return plugin_classes


def _iter_external_plugin_entry_points(group: str = "metroliza.parser_plugins"):
    try:
        entry_points = importlib_metadata.entry_points()
    except Exception:  # pragma: no cover - defensive
        return ()

    # Python >=3.10 exposes select(); older mapping style retained for compatibility.
    if hasattr(entry_points, "select"):
        return tuple(entry_points.select(group=group))
    return tuple(entry_points.get(group, ()))


def _discover_external_plugin_entry_points(*, force_refresh: bool = False) -> tuple[object, ...]:
    global _EXTERNAL_PLUGIN_ENTRY_POINTS

    if force_refresh or _EXTERNAL_PLUGIN_ENTRY_POINTS is None:
        _EXTERNAL_PLUGIN_ENTRY_POINTS = tuple(_iter_external_plugin_entry_points())
    return _EXTERNAL_PLUGIN_ENTRY_POINTS


def load_external_plugins(
    paths: str | tuple[str, ...] | None = None,
    *,
    entry_points: tuple[object, ...] | None = None,
) -> ExternalPluginLoadResult:
    """Load external parser plugins from python files/directories.

    Source can be supplied explicitly, via the default drop-in directory under the
    user's Metroliza home, or via ``PARSER_EXTERNAL_PLUGIN_PATHS`` where entries
    are separated by ``os.pathsep``.
    """

    loaded_plugin_ids: list[str] = []
    loaded_modules: list[str] = []
    loaded_entry_points: list[str] = []
    skipped_paths: list[str] = []
    errors: list[str] = []

    if paths is None:
        path_entries = list(parser_plugin_paths.configured_external_plugin_path_entries())
    elif isinstance(paths, str):
        path_entries = list(parser_plugin_paths.split_external_plugin_paths(paths))
    else:
        path_entries = [entry for entry in paths if entry]

    for entry in path_entries:
        candidates = _iter_external_plugin_candidate_files(entry)
        if not candidates:
            skipped_paths.append(entry)
            continue

        for candidate in candidates:
            module_name = _next_external_module_name()
            try:
                spec = importlib.util.spec_from_file_location(module_name, candidate)
                if spec is None or spec.loader is None:
                    errors.append(f"{candidate}: failed to create import spec")
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                loaded_modules.append(module_name)

                discovered = _discover_plugin_classes_in_module(module)
                if not discovered:
                    continue

                for parser_cls in discovered:
                    register_parser(parser_cls)
                    plugin_manifest = getattr(parser_cls, "manifest", None)
                    plugin_id = plugin_manifest.plugin_id if plugin_manifest is not None else parser_cls.__name__
                    loaded_plugin_ids.append(plugin_id)
            except Exception as exc:  # pragma: no cover - defensive hardening
                errors.append(f"{candidate}: {exc}")

    entry_points_to_load = entry_points if entry_points is not None else _discover_external_plugin_entry_points(force_refresh=True)
    for entry_point in entry_points_to_load:
        try:
            loaded = entry_point.load()
            parser_classes = loaded if isinstance(loaded, (list, tuple)) else (loaded,)
            for parser_cls in parser_classes:
                if not inspect.isclass(parser_cls) or not issubclass(parser_cls, BaseReportParserPlugin):
                    errors.append(
                        f"entry-point {entry_point.name}: loaded object must be BaseReportParserPlugin subclass"
                    )
                    continue
                if inspect.isabstract(parser_cls):
                    errors.append(f"entry-point {entry_point.name}: abstract parser classes are not loadable")
                    continue
                register_parser(parser_cls)
                manifest = getattr(parser_cls, "manifest", None)
                plugin_id = manifest.plugin_id if manifest is not None else parser_cls.__name__
                loaded_plugin_ids.append(plugin_id)
            loaded_entry_points.append(entry_point.name)
        except Exception as exc:  # pragma: no cover - defensive hardening
            errors.append(f"entry-point {entry_point.name}: {exc}")

    return ExternalPluginLoadResult(
        loaded_plugin_ids=tuple(loaded_plugin_ids),
        loaded_modules=tuple(loaded_modules),
        loaded_entry_points=tuple(loaded_entry_points),
        skipped_paths=tuple(skipped_paths),
        errors=tuple(errors),
    )


def _ensure_external_plugins_loaded_once() -> None:
    global _EXTERNAL_PLUGINS_LOADED, _EXTERNAL_PLUGIN_CONFIG_SIGNATURE

    path_entries = parser_plugin_paths.configured_external_plugin_path_entries()
    if _EXTERNAL_PLUGINS_LOADED and _EXTERNAL_PLUGIN_CONFIG_SIGNATURE is not None:
        loaded_path_entries, _loaded_entry_point_names = _EXTERNAL_PLUGIN_CONFIG_SIGNATURE
        if loaded_path_entries == path_entries:
            return

    entry_points = _discover_external_plugin_entry_points(force_refresh=not _EXTERNAL_PLUGINS_LOADED)
    entry_point_names = tuple(entry_point.name for entry_point in entry_points)
    config_signature = (path_entries, entry_point_names)

    if _EXTERNAL_PLUGINS_LOADED and _EXTERNAL_PLUGIN_CONFIG_SIGNATURE == config_signature:
        return

    has_path_config = bool(path_entries)
    has_entry_points = bool(entry_point_names)

    # No-op only when neither file-based paths nor package entry points are available.
    if not has_path_config and not has_entry_points:
        _EXTERNAL_PLUGINS_LOADED = True
        _EXTERNAL_PLUGIN_CONFIG_SIGNATURE = config_signature
        return

    load_external_plugins(entry_points=entry_points)
    _EXTERNAL_PLUGINS_LOADED = True
    _EXTERNAL_PLUGIN_CONFIG_SIGNATURE = config_signature


def resolve_parser_with_diagnostics(file_path: str | Path) -> ResolverDiagnostics:
    """Resolve plugin using deterministic confidence/priority/id tie-breakers."""

    _ensure_external_plugins_loaded_once()

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
        candidates.append(_probe_with_cache(plugin_id, parser_cls, normalized_path, probe_context))

    minimum_confidence = _minimum_confidence_for_selection()
    parseable = [c for c in candidates if c.can_parse and c.confidence >= minimum_confidence]
    if not parseable:
        rejected_reason = "no_plugin_can_parse"
        if any(c.can_parse for c in candidates):
            rejected_reason = "no_plugin_above_confidence_threshold"
        return ResolverDiagnostics(
            source_path=normalized_path,
            source_format=source_format,
            candidates_considered=tuple(candidates),
            selected=None,
            rejected_reason=rejected_reason,
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


def _default_cmm_detector(file_path: str) -> ProbeResult:
    if file_path.lower().endswith('.pdf'):
        return ProbeResult(
            plugin_id='cmm',
            can_parse=True,
            confidence=80,
            reasons=('pdf_extension',),
        )
    return ProbeResult(plugin_id='cmm', can_parse=False, confidence=0, reasons=('unsupported_extension',))


def _infer_plugin_id_from_parser_cls(parser_cls: ParserType) -> str:
    name = getattr(parser_cls, '__name__', 'parser')
    lowered = name.lower()
    if lowered.endswith('reportparser'):
        lowered = lowered[:-len('reportparser')]
    if lowered.endswith('parser'):
        lowered = lowered[:-len('parser')]
    return lowered or 'parser'


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
            plugin_id = _infer_plugin_id_from_parser_cls(parser_cls)
            plugin_manifest = _default_manifest(plugin_id, parser_cls)
        else:
            plugin_id = plugin_manifest.plugin_id

    PARSER_MAP[plugin_id] = parser_cls
    PARSER_MANIFESTS[plugin_id] = plugin_manifest
    PROBE_RESULT_CACHE.clear()
    if detector is not None:
        PARSER_DETECTORS[plugin_id] = detector
    else:
        PARSER_DETECTORS.pop(plugin_id, None)


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
