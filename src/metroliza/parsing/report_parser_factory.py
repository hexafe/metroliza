"""Parser plugin registry and deterministic runtime resolver.

Parser discovery and selection are owned by :mod:`metroliza.parsing`.  The former
``metroliza.reports.report_parser_factory`` path remains a module-identity compatibility alias.

This module keeps compatibility with both:
- new registration: ``register_parser(ParserClass)``
- legacy registration: ``register_parser(format_id, ParserClass, detector=..., manifest=...)``
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field, replace
from importlib import metadata as importlib_metadata
import importlib.util
import inspect
import logging
from pathlib import Path
import sys
from threading import Event, RLock
from typing import Callable, Type

from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.shared.env_utils import env_bool
from metroliza.parsing import parser_plugin_paths
from metroliza.parsing.parser_plugin_contracts import (
    BaseReportParserPlugin,
    PluginManifest,
    ProbeContext,
    ProbeResult,
    infer_source_format,
)
from metroliza.parsing.source_inspection import SourceInspectionContext


ParserType = Type[BaseReportParserPlugin]
DetectorType = Callable[..., ProbeResult]
ExternalPluginConfigSignature = tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[tuple[str, str, str], ...],
    tuple[str, ...],
]


@dataclass(frozen=True)
class ResolverDiagnostics:
    """Selection diagnostics for plugin resolution."""

    source_path: str
    source_format: str
    candidates_considered: tuple[ProbeResult, ...]
    selected: ProbeResult | None
    rejected_reason: str | None = None
    source_inspection: SourceInspectionContext | None = field(
        default=None,
        compare=False,
        repr=False,
    )


@dataclass(frozen=True)
class ExternalPluginLoadResult:
    """Result summary for external plugin discovery/loading."""

    loaded_plugin_ids: tuple[str, ...] = ()
    loaded_profile_ids: tuple[str, ...] = ()
    loaded_modules: tuple[str, ...] = ()
    loaded_entry_points: tuple[str, ...] = ()
    skipped_paths: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ParserRegistration:
    """One coherent parser-registry generation entry."""

    plugin_id: str
    parser_cls: ParserType
    manifest: PluginManifest
    detector: DetectorType | None


PARSER_MAP: dict[str, ParserType] = {}
PARSER_MANIFESTS: dict[str, PluginManifest] = {}
PARSER_DETECTORS: dict[str, DetectorType] = {}
PROBE_RESULT_CACHE_MAX_ENTRIES = 2048
PROBE_RESULT_CACHE: OrderedDict[
    tuple[str, str, tuple[object, ...], int, int],
    ProbeResult,
] = OrderedDict()
_PARSER_REGISTRY_LOCK = RLock()
_PROBE_RESULT_CACHE_LOCK = RLock()
_PROBE_RESULT_CACHE_INFLIGHT: dict[
    tuple[int, tuple[str, str, tuple[object, ...], int, int]],
    Event,
] = {}
_PROBE_RESULT_CACHE_EPOCH = 0
_EXTERNAL_PLUGINS_LOADED = False
_EXTERNAL_PLUGIN_CONFIG_SIGNATURE: ExternalPluginConfigSignature | None = None
_EXTERNAL_PLUGIN_ENTRY_POINTS: tuple[object, ...] | None = None
_EXTERNAL_PLUGIN_MODULE_COUNTER = 0
_EXTERNAL_PLUGIN_LOADER_EPOCH = 0

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

    with _PARSER_REGISTRY_LOCK:
        return tuple(PARSER_MANIFESTS.values())


def _registry_snapshot() -> tuple[_ParserRegistration, ...]:
    """Return a coherent immutable view without holding a lock during plugin code."""

    with _PARSER_REGISTRY_LOCK:
        registrations: list[_ParserRegistration] = []
        for plugin_id, parser_cls in PARSER_MAP.items():
            manifest = PARSER_MANIFESTS.get(plugin_id)
            if manifest is None:
                continue
            registrations.append(
                _ParserRegistration(
                    plugin_id=plugin_id,
                    parser_cls=parser_cls,
                    manifest=manifest,
                    detector=PARSER_DETECTORS.get(plugin_id),
                )
            )
        return tuple(registrations)


def reset_probe_cache() -> None:
    """Clear in-process probe cache (primarily for tests and long-running jobs)."""

    global _PROBE_RESULT_CACHE_EPOCH

    with _PROBE_RESULT_CACHE_LOCK:
        PROBE_RESULT_CACHE.clear()
        _PROBE_RESULT_CACHE_EPOCH += 1


def reset_external_plugin_loader_state() -> None:
    """Reset external plugin discovery state for tests and controlled reloads."""

    global _EXTERNAL_PLUGINS_LOADED, _EXTERNAL_PLUGIN_CONFIG_SIGNATURE
    global _EXTERNAL_PLUGIN_ENTRY_POINTS, _EXTERNAL_PLUGIN_LOADER_EPOCH

    with _PARSER_REGISTRY_LOCK:
        _EXTERNAL_PLUGINS_LOADED = False
        _EXTERNAL_PLUGIN_CONFIG_SIGNATURE = None
        _EXTERNAL_PLUGIN_ENTRY_POINTS = None
        _EXTERNAL_PLUGIN_LOADER_EPOCH += 1


def _unregister_parser(plugin_id: str) -> None:
    with _PARSER_REGISTRY_LOCK:
        PARSER_MAP.pop(plugin_id, None)
        PARSER_MANIFESTS.pop(plugin_id, None)
        PARSER_DETECTORS.pop(plugin_id, None)
        reset_probe_cache()


def _unregister_declarative_profile_parsers() -> None:
    with _PARSER_REGISTRY_LOCK:
        changed = False
        for plugin_id, manifest in tuple(PARSER_MANIFESTS.items()):
            if manifest.capabilities.get("declarative_profile") is True:
                PARSER_MAP.pop(plugin_id, None)
                PARSER_MANIFESTS.pop(plugin_id, None)
                PARSER_DETECTORS.pop(plugin_id, None)
                changed = True
        if changed:
            reset_probe_cache()


def plugins_for_format(source_format: str) -> tuple[ParserType, ...]:
    """Return plugins compatible with a source format."""

    return tuple(
        registration.parser_cls
        for registration in _registry_snapshot()
        if source_format in registration.manifest.supported_formats
    )


def _callable_accepts_keyword(callback, keyword: str) -> bool:
    """Return whether ``callback`` accepts one named keyword argument."""

    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return False
    parameter = signature.parameters.get(keyword)
    if parameter is not None and parameter.kind is not inspect.Parameter.POSITIONAL_ONLY:
        return True
    return any(
        candidate.kind is inspect.Parameter.VAR_KEYWORD
        for candidate in signature.parameters.values()
    )


def _safe_probe(
    plugin_id: str,
    parser_cls: ParserType,
    normalized_path: str,
    probe_context: ProbeContext,
    detector: DetectorType | None = None,
) -> ProbeResult:
    """Run detector/probe and normalize plugin id for compatibility."""

    probe_origin = "detector" if detector is not None else "probe"

    try:
        if detector is None:
            result = parser_cls.probe(normalized_path, probe_context)
        elif _callable_accepts_keyword(detector, "probe_context"):
            result = detector(normalized_path, probe_context=probe_context)
        else:
            result = detector(normalized_path)
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
    return env_bool("PARSER_STRICT_MATCHING", default=True)


def _minimum_confidence_for_selection() -> int:
    return 80 if _strict_matching_enabled() else 1


def _probe_with_cache(
    plugin_id: str,
    parser_cls: ParserType,
    normalized_path: str,
    probe_context: ProbeContext,
    detector: DetectorType | None = None,
) -> ProbeResult:
    source_inspection = probe_context.source_inspection
    cache_identity = (
        source_inspection.cache_identity
        if source_inspection is not None
        else SourceInspectionContext.from_path(
            normalized_path,
            source_format=probe_context.source_format,
        ).cache_identity
    )
    cache_key = (
        plugin_id,
        normalized_path,
        cache_identity,
        id(parser_cls),
        id(detector),
    )
    while True:
        with _PROBE_RESULT_CACHE_LOCK:
            cached = PROBE_RESULT_CACHE.get(cache_key)
            if cached is not None:
                PROBE_RESULT_CACHE.move_to_end(cache_key)
                return cached

            cache_epoch = _PROBE_RESULT_CACHE_EPOCH
            inflight_key = (cache_epoch, cache_key)
            inflight = _PROBE_RESULT_CACHE_INFLIGHT.get(inflight_key)
            if inflight is None:
                inflight = Event()
                _PROBE_RESULT_CACHE_INFLIGHT[inflight_key] = inflight
                owns_probe = True
            else:
                owns_probe = False

        if owns_probe:
            break
        inflight.wait()

    try:
        result = _safe_probe(
            plugin_id,
            parser_cls,
            normalized_path,
            probe_context,
            detector,
        )
        with _PROBE_RESULT_CACHE_LOCK:
            if cache_epoch == _PROBE_RESULT_CACHE_EPOCH:
                PROBE_RESULT_CACHE[cache_key] = result
                PROBE_RESULT_CACHE.move_to_end(cache_key)
                while len(PROBE_RESULT_CACHE) > PROBE_RESULT_CACHE_MAX_ENTRIES:
                    PROBE_RESULT_CACHE.popitem(last=False)
        return result
    finally:
        with _PROBE_RESULT_CACHE_LOCK:
            completed = _PROBE_RESULT_CACHE_INFLIGHT.pop(inflight_key, inflight)
            completed.set()


def _non_strict_pdf_extension_fallback(
    candidates: list[ProbeResult],
    priorities: dict[str, int],
) -> ProbeResult | None:
    """Keep diagnostics/backward-compat fallback explicit when strict matching is disabled."""

    if _strict_matching_enabled():
        return None
    extension_candidates = [
        candidate
        for candidate in candidates
        if candidate.plugin_id == "cmm"
        and candidate.confidence > 0
        and "pdf_extension" in candidate.reasons
    ]
    if not extension_candidates:
        return None
    selected = max(
        extension_candidates,
        key=lambda match: (
            match.confidence,
            priorities[match.plugin_id],
            match.plugin_id,
        ),
    )
    return replace(
        selected,
        can_parse=True,
        reasons=tuple(dict.fromkeys((*selected.reasons, "non_strict_pdf_extension_fallback"))),
    )


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
    with _PARSER_REGISTRY_LOCK:
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
    disabled_ids = parser_plugin_paths.disabled_plugin_ids()

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
                sys.modules[module_name] = module
                try:
                    spec.loader.exec_module(module)
                except Exception:
                    sys.modules.pop(module_name, None)
                    raise
                loaded_modules.append(module_name)

                discovered = _discover_plugin_classes_in_module(module)
                if not discovered:
                    continue

                for parser_cls in discovered:
                    plugin_manifest = getattr(parser_cls, "manifest", None)
                    plugin_id = plugin_manifest.plugin_id if plugin_manifest is not None else parser_cls.__name__
                    if plugin_id in disabled_ids:
                        continue
                    register_parser(parser_cls)
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
                manifest = getattr(parser_cls, "manifest", None)
                plugin_id = manifest.plugin_id if manifest is not None else parser_cls.__name__
                if plugin_id in disabled_ids:
                    continue
                register_parser(parser_cls)
                loaded_plugin_ids.append(plugin_id)
            loaded_entry_points.append(entry_point.name)
        except Exception as exc:  # pragma: no cover - defensive hardening
            errors.append(f"entry-point {entry_point.name}: {exc}")

    return ExternalPluginLoadResult(
        loaded_plugin_ids=tuple(loaded_plugin_ids),
        loaded_profile_ids=(),
        loaded_modules=tuple(loaded_modules),
        loaded_entry_points=tuple(loaded_entry_points),
        skipped_paths=tuple(skipped_paths),
        errors=tuple(errors),
    )


def _load_approved_declarative_profiles() -> ExternalPluginLoadResult:
    """Load approved data-only parser profiles from the self-service store."""

    try:
        from metroliza.parsing.declarative_parser_profiles import load_approved_profile_parsers
    except Exception as exc:  # pragma: no cover - import hardening
        return ExternalPluginLoadResult(
            loaded_plugin_ids=(),
            loaded_profile_ids=(),
            loaded_modules=(),
            loaded_entry_points=(),
            skipped_paths=(),
            errors=(f"declarative profile loader unavailable: {exc}",),
        )

    loaded_profile_ids: list[str] = []
    errors: list[str] = []
    profiles, profile_errors = load_approved_profile_parsers()
    errors.extend(profile_errors)
    with _PARSER_REGISTRY_LOCK:
        _unregister_declarative_profile_parsers()
        for plugin_id, parser_cls in profiles:
            try:
                register_parser(parser_cls)
                loaded_profile_ids.append(plugin_id)
            except Exception as exc:
                errors.append(f"declarative profile {plugin_id}: {exc}")

    return ExternalPluginLoadResult(
        loaded_plugin_ids=tuple(loaded_profile_ids),
        loaded_profile_ids=tuple(loaded_profile_ids),
        loaded_modules=(),
        loaded_entry_points=(),
        skipped_paths=(),
        errors=tuple(errors),
    )


def _current_declarative_profile_signature() -> tuple[tuple[str, str, str], ...]:
    try:
        from metroliza.parsing.declarative_parser_profiles import profile_store_signature
    except Exception as exc:  # pragma: no cover - import hardening
        return (("profile_loader_unavailable", type(exc).__name__, str(exc)),)
    try:
        return profile_store_signature()
    except Exception as exc:  # pragma: no cover - filesystem hardening
        return (("profile_signature_unavailable", type(exc).__name__, str(exc)),)


def _ensure_external_plugins_loaded_once() -> None:
    """Refresh external registrations once per coherent configuration generation."""

    global _EXTERNAL_PLUGINS_LOADED, _EXTERNAL_PLUGIN_CONFIG_SIGNATURE

    while True:
        with _PARSER_REGISTRY_LOCK:
            was_loaded = _EXTERNAL_PLUGINS_LOADED

        path_entries = parser_plugin_paths.configured_external_plugin_path_entries()
        entry_points = _discover_external_plugin_entry_points(force_refresh=not was_loaded)
        entry_point_names = tuple(entry_point.name for entry_point in entry_points)
        profile_signature = _current_declarative_profile_signature()
        disabled_ids = tuple(sorted(parser_plugin_paths.disabled_plugin_ids()))
        config_signature: ExternalPluginConfigSignature = (
            path_entries,
            entry_point_names,
            profile_signature,
            disabled_ids,
        )

        with _PARSER_REGISTRY_LOCK:
            loader_epoch = _EXTERNAL_PLUGIN_LOADER_EPOCH
            if (
                _EXTERNAL_PLUGINS_LOADED
                and _EXTERNAL_PLUGIN_CONFIG_SIGNATURE == config_signature
            ):
                return

        profile_load_result = _load_approved_declarative_profiles()
        for error in profile_load_result.errors:
            logger.warning("Declarative parser profile load issue: %s", error)

        if path_entries or entry_point_names:
            result = load_external_plugins(entry_points=entry_points)
            for error in result.errors:
                logger.warning("External parser plugin load issue: %s", error)

        with _PARSER_REGISTRY_LOCK:
            if loader_epoch != _EXTERNAL_PLUGIN_LOADER_EPOCH:
                continue
            _EXTERNAL_PLUGINS_LOADED = True
            _EXTERNAL_PLUGIN_CONFIG_SIGNATURE = config_signature
            return


def _resolve_parser_with_registration(
    file_path: str | Path,
    *,
    source_inspection: SourceInspectionContext | None = None,
) -> tuple[ResolverDiagnostics, _ParserRegistration | None]:
    """Resolve one parser from a coherent registry snapshot."""

    _ensure_external_plugins_loaded_once()
    registrations = _registry_snapshot()
    registrations_by_id = {
        registration.plugin_id: registration for registration in registrations
    }
    priorities = {
        registration.plugin_id: registration.manifest.priority
        for registration in registrations
    }

    normalized_path = _as_file_path(file_path)
    source_format = infer_source_format(normalized_path)
    if source_inspection is None:
        source_inspection = SourceInspectionContext.from_path(
            normalized_path,
            source_format=source_format,
        )
    elif Path(source_inspection.source_path).resolve(strict=False) != Path(
        normalized_path
    ).resolve(strict=False):
        raise ValueError(
            "Source inspection context does not match parser input: "
            f"{source_inspection.source_path} != {normalized_path}"
        )
    probe_context = ProbeContext(
        source_path=normalized_path,
        source_format=source_format,
        source_inspection=source_inspection,
    )

    candidates: list[ProbeResult] = []
    for registration in registrations:
        if source_format not in registration.manifest.supported_formats:
            continue
        candidates.append(
            _probe_with_cache(
                registration.plugin_id,
                registration.parser_cls,
                normalized_path,
                probe_context,
                registration.detector,
            )
        )

    minimum_confidence = _minimum_confidence_for_selection()
    parseable = [c for c in candidates if c.can_parse and c.confidence >= minimum_confidence]
    if not parseable:
        fallback = _non_strict_pdf_extension_fallback(candidates, priorities)
        if fallback is not None:
            return (
                ResolverDiagnostics(
                    source_path=normalized_path,
                    source_format=source_format,
                    candidates_considered=tuple(candidates),
                    selected=fallback,
                    source_inspection=source_inspection,
                ),
                registrations_by_id[fallback.plugin_id],
            )
        rejected_reason = "no_plugin_can_parse"
        if any(c.can_parse for c in candidates):
            rejected_reason = "no_plugin_above_confidence_threshold"
        return (
            ResolverDiagnostics(
                source_path=normalized_path,
                source_format=source_format,
                candidates_considered=tuple(candidates),
                selected=None,
                rejected_reason=rejected_reason,
                source_inspection=source_inspection,
            ),
            None,
        )

    selected = max(
        parseable,
        key=lambda match: (
            match.confidence,
            priorities[match.plugin_id],
            match.plugin_id,
        ),
    )
    return (
        ResolverDiagnostics(
            source_path=normalized_path,
            source_format=source_format,
            candidates_considered=tuple(candidates),
            selected=selected,
            source_inspection=source_inspection,
        ),
        registrations_by_id[selected.plugin_id],
    )


def resolve_parser_with_diagnostics(
    file_path: str | Path,
    *,
    source_inspection: SourceInspectionContext | None = None,
) -> ResolverDiagnostics:
    """Resolve plugin using deterministic confidence/priority/id tie-breakers."""

    diagnostics, _registration = _resolve_parser_with_registration(
        file_path,
        source_inspection=source_inspection,
    )
    return diagnostics


def detect_format(file_path: str | Path) -> str:
    """Backward-compatible format identifier detection."""

    diagnostics = resolve_parser_with_diagnostics(file_path)
    return diagnostics.selected.plugin_id if diagnostics.selected else "unknown"


def get_parser(
    file_path: str | Path,
    database: str,
    connection=None,
    metadata_parsing_mode=None,
    source_inspection: SourceInspectionContext | None = None,
):
    """Construct parser instance for a given file path."""

    normalized_path = _as_file_path(file_path)
    diagnostics, registration = _resolve_parser_with_registration(
        normalized_path,
        source_inspection=source_inspection,
    )
    if diagnostics.selected is None or registration is None:
        raise ValueError(f"Unsupported report format: unknown ({normalized_path})")

    parser_cls = registration.parser_cls

    constructor_kwargs = {"connection": connection}
    if metadata_parsing_mode is not None:
        try:
            signature = inspect.signature(parser_cls)
        except (TypeError, ValueError):
            signature = None
        supports_metadata_mode = False
        if signature is not None:
            supports_metadata_mode = "metadata_parsing_mode" in signature.parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
        if supports_metadata_mode:
            constructor_kwargs["metadata_parsing_mode"] = metadata_parsing_mode

    parser = parser_cls(normalized_path, database, **constructor_kwargs)
    parser.source_inspection_context = diagnostics.source_inspection

    if metadata_parsing_mode is not None and hasattr(parser, "metadata_parsing_mode"):
        parser.metadata_parsing_mode = metadata_parsing_mode

    return parser


def invoke_parser_factory(
    parser_factory,
    file_path: str | Path,
    *args,
    source_inspection: SourceInspectionContext | None = None,
    **kwargs,
):
    """Invoke old or context-aware parser factories without masking callback errors."""

    factory_kwargs = dict(kwargs)
    if source_inspection is not None and _callable_accepts_keyword(
        parser_factory,
        "source_inspection",
    ):
        factory_kwargs["source_inspection"] = source_inspection
    parser = parser_factory(file_path, *args, **factory_kwargs)
    if source_inspection is not None and getattr(parser, "source_inspection_context", None) is None:
        try:
            parser.source_inspection_context = source_inspection
        except (AttributeError, TypeError):
            pass
    return parser


def _default_cmm_detector(
    file_path: str,
    *,
    probe_context: ProbeContext | None = None,
) -> ProbeResult:
    return CMMReportParser.probe_pdf_candidate(
        file_path,
        probe_context=probe_context,
    )


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

    with _PARSER_REGISTRY_LOCK:
        PARSER_MAP[plugin_id] = parser_cls
        PARSER_MANIFESTS[plugin_id] = plugin_manifest
        if detector is not None:
            PARSER_DETECTORS[plugin_id] = detector
        else:
            PARSER_DETECTORS.pop(plugin_id, None)
        reset_probe_cache()


register_parser(
    'cmm',
    CMMReportParser,
    detector=_default_cmm_detector,
    manifest=PluginManifest(
        plugin_id='cmm',
        display_name='CMM PDF Parser',
        version='1.1.0',
        supported_formats=('pdf',),
        priority=100,
    ),
)
